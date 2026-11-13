package com.antreklabs.bayi.altyapi;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.LockSupport;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Bayiyi bir test süresince özel alır (web: tests/fixtures.ts {@code acquireDealer}).
 *
 * <p>Aynı uygulamaya karşı koşan Java süreçleri (ör. yerel koşu ve test-runner aynı anda) ve aynı
 * JVM'deki paralel iş parçacıkları aynı bayiyi aynı anda sıfırlamasın diye işletim sistemi dosya kilidi kullanılır: bekleme sorgusuz (bloklayan
 * {@link FileChannel#lock()}), süreç ölünce kilit kendiliğinden düşer (bayat kilit temizliği gerekmez).
 * Aynı JVM içindeki iş parçacıkları önce adil bir {@link ReentrantLock} ile sıraya girer.
 */
public final class BayiKilidi implements AutoCloseable {

  private static final Map<Path, ReentrantLock> SUREC_ICI = new ConcurrentHashMap<>();

  private final ReentrantLock surecIci;
  private final FileChannel kanal;
  private final FileLock kilit;

  private BayiKilidi(ReentrantLock surecIci, FileChannel kanal, FileLock kilit) {
    this.surecIci = surecIci;
    this.kanal = kanal;
    this.kilit = kilit;
  }

  /** Aynı uygulamaya (web + API adresi) karşı koşan süreçlerin paylaştığı kilit dizini. */
  public static Path dizin(String baseUrl, String demoApiUrl) {
    try {
      byte[] ozet = MessageDigest.getInstance("SHA-256").digest(("web-java|" + baseUrl + "|" + demoApiUrl).getBytes(StandardCharsets.UTF_8));
      String kisa = HexFormat.of().formatHex(ozet).substring(0, 12);
      return Path.of(System.getProperty("java.io.tmpdir"), "demoapp-e2e-java-kilit-" + kisa);
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  /**
   * Bayi kilidini alır; {@code bekleme} içinde alınamazsa açıklayıcı hata.
   *
   * @return {@link #close()} ile bırakılan kilit
   */
  public static BayiKilidi al(Path dizin, String kullaniciAdi, Duration bekleme) {
    Path dosya = dizin.resolve(kullaniciAdi + ".kilit").toAbsolutePath().normalize();
    long bitis = System.nanoTime() + bekleme.toNanos();
    ReentrantLock surecIci = SUREC_ICI.computeIfAbsent(dosya, d -> new ReentrantLock(true));
    try {
      if (!surecIci.tryLock(bekleme.toNanos(), TimeUnit.NANOSECONDS)) {
        throw zamanAsimi(kullaniciAdi, bekleme, dosya);
      }
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("bayi kilidi beklenirken kesildi", e);
    }
    FileChannel kanal = null;
    try {
      Files.createDirectories(dizin);
      kanal = FileChannel.open(dosya, StandardOpenOption.CREATE, StandardOpenOption.WRITE);
      FileLock kilit = dosyaKilidi(kanal, bitis - System.nanoTime(), kullaniciAdi, bekleme, dosya);
      kanal.truncate(0);
      kanal.write(ByteBuffer.wrap((ProcessHandle.current().pid() + "\n").getBytes(StandardCharsets.UTF_8)));
      return new BayiKilidi(surecIci, kanal, kilit);
    } catch (IOException | RuntimeException e) {
      kapat(kanal);
      surecIci.unlock();
      if (e instanceof RuntimeException) {
        throw (RuntimeException) e;
      }
      throw new IllegalStateException("bayi kilidi alınamadı: " + dosya, e);
    }
  }

  private static FileLock dosyaKilidi(
      FileChannel kanal, long kalanNs, String kullaniciAdi, Duration bekleme, Path dosya) throws IOException {
    // Başka süreç tutuyorsa süre dolana kadar kısa aralıklarla tryLock. Bloklayan lock() +
    // kesme KULLANILMAZ: Windows'ta kanalı kapatmak bloklu LockFileEx bitene dek bekler ve kilit
    // sahibi bırakmazsa süreç asılı kalır. parkNanos kilit yoklamasının
    // bekleme aralığıdır; test akışında bekleme değildir (Bekle sınıfı oradadır).
    long bitis = System.nanoTime() + Math.max(0, kalanNs);
    long aralik = TimeUnit.MILLISECONDS.toNanos(20);
    while (true) {
      FileLock kilit = kanal.tryLock();
      if (kilit != null) {
        return kilit;
      }
      long kalan = bitis - System.nanoTime();
      if (kalan <= 0) {
        throw zamanAsimi(kullaniciAdi, bekleme, dosya);
      }
      LockSupport.parkNanos(Math.min(aralik, kalan));
      if (Thread.currentThread().isInterrupted()) {
        throw new IllegalStateException("bayi kilidi beklenirken kesildi");
      }
      aralik = Math.min(aralik * 2, TimeUnit.MILLISECONDS.toNanos(200));
    }
  }

  private static IllegalStateException zamanAsimi(String kullaniciAdi, Duration bekleme, Path dosya) {
    return new IllegalStateException(
        "'" + kullaniciAdi + "' bayisi " + bekleme.toSeconds() + " sn içinde serbest kalmadı (kilit: " + dosya + ")");
  }

  private static void kapat(FileChannel kanal) {
    if (kanal != null) {
      try {
        kanal.close();
      } catch (IOException ignored) {
        // kapanırken hata: kilit zaten bırakılır
      }
    }
  }

  /** Kilidi bırakır (birden çok çağrı zararsız). */
  @Override
  public void close() {
    if (!kanal.isOpen()) {
      return;
    }
    try {
      kilit.release();
    } catch (IOException ignored) {
      // kanal kapanınca kilit düşer
    } finally {
      kapat(kanal);
      surecIci.unlock();
    }
  }
}

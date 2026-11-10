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
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Bayiyi bir test süresince özel alır (web: tests/fixtures.ts {@code acquireDealer}).
 *
 * <p>Aynı demo API'ye karşı koşan Java süreçleri (ör. Android ve iOS koşusu aynı anda) aynı bayiyi
 * aynı anda sıfırlamasın diye işletim sistemi dosya kilidi kullanılır: bekleme sorgusuz (bloklayan
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

  /** Aynı demo API'ye karşı koşan süreçlerin paylaştığı kilit dizini. */
  public static Path dizin(String demoApiUrl) {
    try {
      byte[] ozet = MessageDigest.getInstance("SHA-256").digest(("app|" + demoApiUrl).getBytes(StandardCharsets.UTF_8));
      String kisa = HexFormat.of().formatHex(ozet).substring(0, 12);
      return Path.of(System.getProperty("java.io.tmpdir"), "demoapp-e2e-app-kilit-" + kisa);
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
    FileLock hemen = kanal.tryLock();
    if (hemen != null) {
      return hemen;
    }
    // Başka süreç tutuyor: bloklayan lock() ayrı iş parçacığında, süre dolunca kesilir
    // (kesme kanalı kapatır ve beklemeyi bitirir).
    ExecutorService yurutucu = Executors.newSingleThreadExecutor(r -> {
      Thread t = new Thread(r, "bayi-kilidi-" + kullaniciAdi);
      t.setDaemon(true);
      return t;
    });
    try {
      Future<FileLock> gelecek = yurutucu.submit(() -> kanal.lock());
      try {
        return gelecek.get(Math.max(0, kalanNs), TimeUnit.NANOSECONDS);
      } catch (java.util.concurrent.TimeoutException e) {
        gelecek.cancel(true);
        throw zamanAsimi(kullaniciAdi, bekleme, dosya);
      } catch (InterruptedException e) {
        gelecek.cancel(true);
        Thread.currentThread().interrupt();
        throw new IllegalStateException("bayi kilidi beklenirken kesildi", e);
      } catch (ExecutionException e) {
        throw new IOException("bayi kilidi alınamadı: " + dosya, e.getCause());
      }
    } finally {
      yurutucu.shutdownNow();
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

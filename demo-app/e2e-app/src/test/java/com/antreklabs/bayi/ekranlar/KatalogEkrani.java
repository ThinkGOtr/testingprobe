package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Kimlik;
import com.antreklabs.bayi.altyapi.UygulamaOturumu;
import org.openqa.selenium.WebElement;

/** Ürün kataloğu ekranı (web: pages/catalog/catalog.page.ts {@code CatalogPage}). */
public class KatalogEkrani extends Ekran {

  /** Başarılı eklemede ürün kartındaki bilgi mesajının parçası (web: "{n} adet sepete eklendi."). */
  private static final String EKLENDI = "sepete eklendi";

  public KatalogEkrani(UygulamaOturumu oturum) {
    super(oturum);
  }

  private static String kart(String urunKodu) {
    return Kimlik.ekli(Kimlikler.Katalog.URUN_KARTI_ONEK, urunKodu);
  }

  /** Katalog ekranını açar. */
  public void ac() {
    dokun(Kimlikler.Menu.KATALOG);
    gorunurBekle(Kimlikler.Katalog.URUN_LISTESI);
  }

  /** Üst menüden kataloğa gider. */
  public void menudenAc() {
    ac();
  }

  /** Ürün kartındaki adet alanına değer yazar. */
  public void adetGir(String urunKodu, int adet) {
    yaz(Kimlik.ekli(Kimlikler.Katalog.ADET_ONEK, urunKodu), String.valueOf(adet));
  }

  /** Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler. */
  public void sepeteEkle(String urunKodu, int adet) {
    int once = sepetSayaci();
    adetGir(urunKodu, adet);
    dokun(kart(urunKodu), Kimlikler.Katalog.SEPETE_EKLE);
    String durum = Kimlik.ekli(Kimlikler.Katalog.EKLEME_DURUMU_ONEK, urunKodu);
    // Web isteğin yanıtını bekler; uygulamada ağ görünmez: kart mesajı + sayaç artışı beklenir.
    bekle()
        .kosul(
            "sepete ekleme tamamlanmadı: '" + durum + "' mesajı ve sepet sayacı " + (once + adet),
            s -> {
              WebElement mesajOgesi = hemenBul(null, durum);
              String mesaj = mesajOgesi == null ? "" : metin(mesajOgesi);
              if (!mesaj.isEmpty() && !mesaj.contains(EKLENDI)) {
                throw new AssertionError("sepete ekleme başarısız: " + mesaj);
              }
              return mesaj.contains(EKLENDI) && sayacHemen() == once + adet ? Boolean.TRUE : null;
            });
  }

  /** Üst menüden sepete gider. */
  public void sepetiAc() {
    dokun(Kimlikler.Menu.SEPET);
    biriGorunurBekle(Kimlikler.Sepet.TABLO, Kimlikler.Sepet.BOS);
  }

  /** Ürün kartının katalogda göründüğünü doğrular. */
  public void dogrulaUrunGorunur(String urunKodu) {
    gorunurOlmali(kart(urunKodu));
  }

  /** Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL"). */
  public void dogrulaUrunFiyati(String urunKodu, String fiyat) {
    metinOlmali(Kimlik.ekli(Kimlikler.Katalog.URUN_FIYATI_ONEK, urunKodu), fiyat);
  }

  /** Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava"). */
  public void dogrulaKampanya(String urunKodu, String kampanyaAdi) {
    tumMetinIcermeli(kart(urunKodu), kampanyaAdi);
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular. */
  public void dogrulaSepetSayaci(int adet) {
    metinOlmali(Kimlikler.Menu.SEPET_SAYACI, String.valueOf(adet));
  }

  // ---------------------------------------------------------------- yardımcılar (sembol tablosu dışı)

  private int sepetSayaci() {
    gorunurBekle(Kimlikler.Menu.SEPET_SAYACI);
    return bekle().kosul("sepet sayacı okunamadı: kimlik '" + Kimlikler.Menu.SEPET_SAYACI + "'", s -> {
      int n = sayacHemen();
      return n < 0 ? null : n;
    });
  }

  /** Sayacı beklemeden okur; yoksa ya da sayı değilse -1. */
  private int sayacHemen() {
    WebElement e = hemenBul(null, Kimlikler.Menu.SEPET_SAYACI);
    if (e == null) {
      return -1;
    }
    try {
      return Integer.parseInt(metin(e));
    } catch (NumberFormatException ex) {
      return -1;
    }
  }
}

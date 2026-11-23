package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.UygulamaOturumu;

/** Bayi giriş ekranı (web: pages/login/login.page.ts {@code LoginPage}). */
public class GirisEkrani extends Ekran {

  public GirisEkrani(UygulamaOturumu oturum) {
    super(oturum);
  }

  /** Giriş ekranını açar (uygulama her testte sıfırdan, giriş ekranında başlar). */
  public void ac() {
    gorunurBekle(Kimlikler.Giris.KULLANICI_ADI);
  }

  /** Bayi kullanıcı adı ve parolasıyla giriş yapar. */
  public void girisYap(String kullaniciAdi, String parola) {
    alanlariYazVeGonder(kullaniciAdi, parola);
    // iOS: güvenli parola alanında tuş vuruşu yanlış karaktere düşebiliyor (iosHatadaYenidenDene).
    iosHatadaYenidenDene(kullaniciAdi, parola);
  }

  /** Oturumu kapatır. */
  public void cikisYap() {
    dokun(Kimlikler.Menu.CIKIS);
  }

  /** Hata mesajının göründüğünü ve metnini doğrular. */
  public void dogrulaHataMesaji(String beklenen) {
    metinOlmali(Kimlikler.Giris.HATA, beklenen);
  }

  /** Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular. */
  public void dogrulaGirisYapildi(String bayiAdi) {
    metinOlmali(Kimlikler.Menu.BAYI_ADI, bayiAdi);
    gorunurOlmali(Kimlikler.Katalog.URUN_LISTESI);
  }

  /** Giriş ekranında olunduğunu doğrular. */
  public void dogrulaGirisEkraninda() {
    gorunurOlmali(Kimlikler.Giris.GIRIS_YAP);
    yokOlmali(Kimlikler.Menu.BAYI_ADI);
  }

  // ---------------------------------------------------------------- yardımcılar (sembol tablosu dışı)
  // Sınıf sonunda: public metotların satır numaraları (sembol tablosu) değişmesin.

  private static final String HATA = "hata";

  private void alanlariYazVeGonder(String kullaniciAdi, String parola) {
    yaz(Kimlikler.Giris.KULLANICI_ADI, kullaniciAdi);
    yaz(Kimlikler.Giris.PAROLA, parola);
    dokun(Kimlikler.Giris.GIRIS_YAP);
  }

  /**
   * iOS: parola alanı güvenli metin alanıdır; XCUITest değerini yalnız maskeli (•••) okur, yazılan
   * parolanın İÇERİĞİ doğrulanamaz (yalnız uzunluğu, bkz. {@code Ekran.yaz}). iOS 27 simülatöründe
   * tuş vuruşu ara sıra yanlış karaktere düşüyor: uzunluk aynı, API 401 → "Kullanıcı adı veya parola
   * hatalı" (GitHub mobil-ios gece koşularında 4 koşunun 2'sinde, her seferinde tek bir giriş). Giriş
   * hatası görünürse alanlar bir kez yeniden yazılıp gönderilir. Gerçekten yanlış parolada (ör.
   * {@code hataliParola}) ikinci deneme de aynı hatayı verir: test sonucu değişmez.
   */
  private void iosHatadaYenidenDene(String kullaniciAdi, String parola) {
    if (com.antreklabs.bayi.altyapi.Kimlik.platform() == com.antreklabs.bayi.altyapi.Platform.IOS
        && girisHatasiGorundu()) {
      alanlariYazVeGonder(kullaniciAdi, parola);
    }
  }

  /** Gönderimden sonra giriş tamamlanana ya da hata görünene kadar bekler; hata göründüyse true. */
  private boolean girisHatasiGorundu() {
    // FluentWait null ve Boolean.FALSE'u "henüz değil" sayar: sonuç metinle döndürülür.
    try {
      return HATA.equals(
          bekle()
              .kosul(
                  "giriş sonucu görünmedi (kimlik '" + Kimlikler.Menu.BAYI_ADI + "' ya da '"
                      + Kimlikler.Giris.HATA + "')",
                  s -> {
                    if (hemenBul(null, Kimlikler.Giris.HATA) != null) {
                      return HATA;
                    }
                    return hemenBul(null, Kimlikler.Menu.BAYI_ADI) != null ? "giris" : null;
                  }));
    } catch (org.openqa.selenium.TimeoutException e) {
      return false; // sonuç yok: çağıranın kendi doğrulaması raporlar
    }
  }
}

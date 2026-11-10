package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Ekran;
import com.antreklabs.bayi.altyapi.Kimlik;
import io.appium.java_client.AppiumDriver;

/** Bayi giriş ekranı. Uygulama açılışında görünür. */
public class GirisEkrani extends Ekran {
  public GirisEkrani(AppiumDriver surucu) {
    super(surucu);
  }

  /** Bayi kullanıcı adı ve parolasıyla giriş yapar. */
  public void girisYap(String kullaniciAdi, String parola) {
    yaz(Kimlik.bul(Kimlikler.Giris.KULLANICI_ADI), kullaniciAdi);
    yaz(Kimlik.bul(Kimlikler.Giris.PAROLA), parola);
    dokun(Kimlik.bul(Kimlikler.Giris.GONDER));
  }

  /**
   * Hata mesajının göründüğünü ve metnini doğrular.
   *
   * @param beklenen beklenen metin
   */
  public void dogrulaHataMesaji(String beklenen) {
    metinDogrula(Kimlik.bul(Kimlikler.Giris.HATA), beklenen);
  }

  /** Yardımcı: tabloya girmez. */
  private void bekle() {}

  /** Statik yardımcı: tabloya girmez. */
  public static String surum() {
    return "1";
  }
}

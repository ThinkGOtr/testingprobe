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
    yaz(Kimlikler.Giris.KULLANICI_ADI, kullaniciAdi);
    yaz(Kimlikler.Giris.PAROLA, parola);
    dokun(Kimlikler.Giris.GIRIS_YAP);
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
}

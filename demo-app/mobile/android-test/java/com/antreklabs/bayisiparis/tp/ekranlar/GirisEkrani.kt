package com.antreklabs.bayisiparis.tp.ekranlar

import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu

/** Bayi giriş ekranı (web: pages/login/login.page.ts `LoginPage`). */
class GirisEkrani(oturum: UygulamaOturumu) : Ekran(oturum) {

  /** Giriş ekranını açar (uygulama her testte sıfırdan, giriş ekranında başlar). */
  fun ac() {
    gorunurBekle(Kimlikler.Giris.KULLANICI_ADI)
  }

  /** Bayi kullanıcı adı ve parolasıyla giriş yapar. */
  fun girisYap(kullaniciAdi: String, parola: String) {
    yaz(Kimlikler.Giris.KULLANICI_ADI, kullaniciAdi)
    yaz(Kimlikler.Giris.PAROLA, parola)
    dokun(Kimlikler.Giris.GIRIS_YAP)
  }

  /** Oturumu kapatır. */
  fun cikisYap() {
    dokun(Kimlikler.Menu.CIKIS)
  }

  /** Hata mesajının göründüğünü ve metnini doğrular. */
  fun dogrulaHataMesaji(beklenen: String) {
    metinOlmali(Kimlikler.Giris.HATA, beklenen)
  }

  /** Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular. */
  fun dogrulaGirisYapildi(bayiAdi: String) {
    metinOlmali(Kimlikler.Menu.BAYI_ADI, bayiAdi)
    gorunurOlmali(Kimlikler.Katalog.URUN_LISTESI)
  }

  /** Giriş ekranında olunduğunu doğrular. */
  fun dogrulaGirisEkraninda() {
    gorunurOlmali(Kimlikler.Giris.GIRIS_YAP)
    yokOlmali(Kimlikler.Menu.BAYI_ADI)
  }
}

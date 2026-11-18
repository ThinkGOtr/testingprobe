package com.antreklabs.bayisiparis.tp.ekranlar

import com.antreklabs.bayisiparis.tp.altyapi.Kimlik
import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu

/** Sepet ekranı: satırlar, kampanya, toplamlar ve sipariş onayı (web: pages/cart/cart.page.ts `CartPage`). */
class SepetEkrani(oturum: UygulamaOturumu) : Ekran(oturum) {

  /** Sepet ekranını açar. */
  fun ac() {
    dokun(Kimlikler.Menu.SEPET)
    biriGorunurBekle(Kimlikler.Sepet.TABLO, Kimlikler.Sepet.BOS)
  }

  /** Ürünü sepetten kaldırır. */
  fun urunuKaldir(urunKodu: String) {
    dokun(Kimlik.ekli(Kimlikler.Sepet.SATIRI_KALDIR_ONEK, urunKodu))
    val satir = Kimlik.ekli(Kimlikler.Sepet.SATIR_ONEK, urunKodu)
    bekle().kosul("satır sepetten kalkmadı: kimlik '$satir'") { if (gorulenMetin(null, satir) == YOK) true else null }
  }

  /** "Siparişi onayla" butonuna basar ve onay ekranının açılmasını bekler. */
  fun siparisiOnayla() {
    dokun(Kimlikler.Sepet.SIPARISI_ONAYLA)
    gorunurBekle(Kimlikler.Onay.ONAY_ALANI)
  }

  /** Sepet satırındaki adedi doğrular. */
  fun dogrulaSatirAdedi(urunKodu: String, adet: Int) {
    metinOlmali(Kimlik.ekli(Kimlikler.Sepet.SATIR_ADEDI_ONEK, urunKodu), adet.toString())
  }

  /** Sepet satırında kampanyayla bedava verilen adedi doğrular. */
  fun dogrulaBedavaAdet(urunKodu: String, adet: Int) {
    metinOlmali(Kimlik.ekli(Kimlikler.Sepet.BEDAVA_ADET_ONEK, urunKodu), adet.toString())
  }

  /** Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL"). */
  fun dogrulaSatirToplami(urunKodu: String, tutar: String) {
    metinOlmali(Kimlik.ekli(Kimlikler.Sepet.SATIR_TOPLAMI_ONEK, urunKodu), tutar)
  }

  /** Ara toplamı doğrular (ör. "175,00 TL"). */
  fun dogrulaAraToplam(tutar: String) {
    metinOlmali(Kimlikler.Sepet.ARA_TOPLAM, tutar)
  }

  /** Kampanya indirimi tutarını doğrular (ör. "25,00 TL"). */
  fun dogrulaIndirim(tutar: String) {
    metinOlmali(Kimlikler.Sepet.INDIRIM, tutar)
  }

  /** Sepetin indirim sonrası genel toplamını doğrular (ör. "150,00 TL"). */
  fun dogrulaToplam(tutar: String) {
    metinOlmali(Kimlikler.Sepet.TOPLAM, tutar)
  }

  /** Minimum sipariş uyarısının verilen metni içerdiğini doğrular (ör. "Minimum sipariş tutarı 750,00 TL"). */
  fun dogrulaMinimumSiparisUyarisi(mesaj: String) {
    metinIcermeli(Kimlikler.Sepet.MIN_SIPARIS_UYARISI, mesaj)
  }

  /** Minimum sipariş uyarısının gösterilmediğini doğrular. */
  fun dogrulaMinimumSiparisUyarisiYok() {
    yokOlmali(Kimlikler.Sepet.MIN_SIPARIS_UYARISI)
  }

  /** "Siparişi onayla" butonunun pasif olduğunu doğrular. */
  fun dogrulaOnayPasif() {
    etkinOlmali(Kimlikler.Sepet.SIPARISI_ONAYLA, false)
  }

  /** "Siparişi onayla" butonunun aktif olduğunu doğrular. */
  fun dogrulaOnayAktif() {
    etkinOlmali(Kimlikler.Sepet.SIPARISI_ONAYLA, true)
  }

  /** Sepette ürünün bulunmadığını doğrular. */
  fun dogrulaUrunSepetteYok(urunKodu: String) {
    yokOlmali(Kimlik.ekli(Kimlikler.Sepet.SATIR_ONEK, urunKodu))
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet ekranında). */
  fun dogrulaSepetSayaci(adet: Int) {
    metinOlmali(Kimlikler.Menu.SEPET_SAYACI, adet.toString())
  }

  /** Sepetin boş olduğunu doğrular. */
  fun dogrulaSepetBos() {
    gorunurOlmali(Kimlikler.Sepet.BOS)
  }
}

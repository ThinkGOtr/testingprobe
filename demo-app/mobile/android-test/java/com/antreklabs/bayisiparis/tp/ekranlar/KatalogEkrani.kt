package com.antreklabs.bayisiparis.tp.ekranlar

import com.antreklabs.bayisiparis.tp.altyapi.Kimlik
import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu

/** Ürün kataloğu ekranı (web: pages/catalog/catalog.page.ts `CatalogPage`). */
class KatalogEkrani(oturum: UygulamaOturumu) : Ekran(oturum) {

  private fun kart(urunKodu: String): String = Kimlik.ekli(Kimlikler.Katalog.URUN_KARTI_ONEK, urunKodu)

  /** Katalog ekranını açar. */
  fun ac() {
    dokun(Kimlikler.Menu.KATALOG)
    gorunurBekle(Kimlikler.Katalog.URUN_LISTESI)
  }

  /** Üst menüden kataloğa gider. */
  fun menudenAc() {
    ac()
  }

  /** Ürün kartındaki adet alanına değer yazar. */
  fun adetGir(urunKodu: String, adet: Int) {
    yaz(Kimlik.ekli(Kimlikler.Katalog.ADET_ONEK, urunKodu), adet.toString())
  }

  /** Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler. */
  fun sepeteEkle(urunKodu: String, adet: Int) {
    val once = sepetSayaci()
    adetGir(urunKodu, adet)
    dokun(kart(urunKodu), Kimlikler.Katalog.SEPETE_EKLE)
    val durum = Kimlik.ekli(Kimlikler.Katalog.EKLEME_DURUMU_ONEK, urunKodu)
    // Web isteğin yanıtını bekler; uygulamada ağ görünmez: kart mesajı + sayaç artışı beklenir.
    bekle().kosul("sepete ekleme tamamlanmadı: '$durum' mesajı ve sepet sayacı ${once + adet}") {
      val mesaj = gorulenMetin(null, durum).let { if (it == YOK) "" else it }
      if (mesaj.isNotEmpty() && !mesaj.contains(EKLENDI)) {
        throw AssertionError("sepete ekleme başarısız: $mesaj")
      }
      if (mesaj.contains(EKLENDI) && sayacHemen() == once + adet) true else null
    }
  }

  /** Üst menüden sepete gider. */
  fun sepetiAc() {
    dokun(Kimlikler.Menu.SEPET)
    biriGorunurBekle(Kimlikler.Sepet.TABLO, Kimlikler.Sepet.BOS)
  }

  /** Ürün kartının katalogda göründüğünü doğrular. */
  fun dogrulaUrunGorunur(urunKodu: String) {
    gorunurOlmali(kart(urunKodu))
  }

  /** Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL"). */
  fun dogrulaUrunFiyati(urunKodu: String, fiyat: String) {
    metinOlmali(Kimlik.ekli(Kimlikler.Katalog.URUN_FIYATI_ONEK, urunKodu), fiyat)
  }

  /** Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava"). */
  fun dogrulaKampanya(urunKodu: String, kampanyaAdi: String) {
    tumMetinIcermeli(kart(urunKodu), kampanyaAdi)
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular. */
  fun dogrulaSepetSayaci(adet: Int) {
    metinOlmali(Kimlikler.Menu.SEPET_SAYACI, adet.toString())
  }

  // ---------------------------------------------------------------- yardımcılar (sembol tablosu dışı)

  private fun sepetSayaci(): Int {
    gorunurBekle(Kimlikler.Menu.SEPET_SAYACI)
    return bekle().kosul("sepet sayacı okunamadı: kimlik '${Kimlikler.Menu.SEPET_SAYACI}'") {
      sayacHemen().takeIf { it >= 0 }
    }
  }

  /** Sayacı beklemeden okur; yoksa ya da sayı değilse -1. */
  private fun sayacHemen(): Int = gorulenMetin(null, Kimlikler.Menu.SEPET_SAYACI).toIntOrNull() ?: -1

  private companion object {
    /** Başarılı eklemede ürün kartındaki bilgi mesajının parçası (web: "{n} adet sepete eklendi."). */
    const val EKLENDI = "sepete eklendi"
  }
}

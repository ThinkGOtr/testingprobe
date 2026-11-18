package com.antreklabs.bayisiparis.tp.ekranlar

import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu

/**
 * Sipariş onayı ekranı (web: pages/order/order.page.ts `OrderPage`'in onay bölümü).
 *
 * Web'deki `readOrderNumber()` değer döndürür; ekran nesnesi sözleşmesinde yalnız `Unit` metot
 * olduğundan okunan numara oturumda saklanır ve [SiparisEkrani.dogrulaOnaylananSiparisToplami]
 * gibi metotlar onu kullanır.
 */
class OnayEkrani(oturum: UygulamaOturumu) : Ekran(oturum) {

  /** Onay ekranındaki sipariş numarasını okur ve oturumda saklar. */
  internal fun siparisNumarasiniOku(): String {
    metinKalibinaUymali(Kimlikler.Onay.SIPARIS_NUMARASI, SIPARIS_NUMARASI)
    val numara = gorulenMetin(null, Kimlikler.Onay.SIPARIS_NUMARASI)
    oturum().sonSiparisNumarasi = numara
    return numara
  }

  /** Sipariş onayının ve sipariş numarasının gösterildiğini doğrular. */
  fun dogrulaSiparisOnayi() {
    gorunurOlmali(Kimlikler.Onay.ONAY_ALANI)
    siparisNumarasiniOku()
  }

  /** Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL"). */
  fun dogrulaOnaylananToplam(tutar: String) {
    metinOlmali(Kimlikler.Onay.TOPLAM, tutar)
  }

  /** Onaylanan siparişin kampanya indirimini doğrular (ör. "25,00 TL"). */
  fun dogrulaOnaylananIndirim(tutar: String) {
    metinOlmali(Kimlikler.Onay.INDIRIM, tutar)
  }

  /** Onay ekranında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular. */
  fun dogrulaOnaylananSiparisGecmiste() {
    val numara = siparisNumarasiniOku()
    val gecmis = SiparisEkrani(oturum())
    gecmis.menudenAc()
    gecmis.dogrulaSiparisGecmiste(numara)
  }

  /** Onay ekranından "Siparişlerime git" ile sipariş geçmişine gider. */
  fun siparislerimeGit() {
    dokun(Kimlikler.Onay.SIPARISLERIME_GIT)
    biriGorunurBekle(Kimlikler.Siparis.TABLO, Kimlikler.Siparis.BOS)
  }

  /** Onay ekranından "Alışverişe devam et" ile kataloğa döner. */
  fun alisveriseDevamEt() {
    dokun(Kimlikler.Onay.ALISVERISE_DEVAM)
    gorunurBekle(Kimlikler.Katalog.URUN_LISTESI)
  }

  internal companion object {
    /** Sipariş numarası biçimi (web: `ORDER_NUMBER`). */
    val SIPARIS_NUMARASI = Regex("^SP-\\d{6}$")
  }
}

package com.antreklabs.bayisiparis.tp.ekranlar

import com.antreklabs.bayisiparis.tp.altyapi.Kimlik
import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu

/** Sipariş geçmişi (Siparişlerim) ekranı (web: pages/order/order.page.ts `OrderPage`'in geçmiş bölümü). */
class SiparisEkrani(oturum: UygulamaOturumu) : Ekran(oturum) {

  /** Sipariş geçmişi ekranını açar. */
  fun ac() {
    dokun(Kimlikler.Menu.SIPARISLER)
    biriGorunurBekle(Kimlikler.Siparis.TABLO, Kimlikler.Siparis.BOS)
  }

  /** Üst menüden sipariş geçmişine gider. */
  fun menudenAc() {
    ac()
  }

  /** Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular. */
  fun dogrulaSiparisGecmiste(siparisNo: String) {
    gorunurOlmali(Kimlik.ekli(Kimlikler.Siparis.SATIR_ONEK, siparisNo))
  }

  /** Sipariş geçmişindeki siparişin genel toplamını doğrular. */
  fun dogrulaSiparisToplami(siparisNo: String, tutar: String) {
    metinOlmali(Kimlik.ekli(Kimlikler.Siparis.SATIR_TOPLAMI_ONEK, siparisNo), tutar)
  }

  /** Bu testte onay ekranında görülen son siparişin geçmişteki genel toplamını doğrular. */
  fun dogrulaOnaylananSiparisToplami(tutar: String) {
    val numara =
      oturum().sonSiparisNumarasi
        ?: throw IllegalStateException("bu testte onaylanmış sipariş yok (önce onay ekranı doğrulanmalı)")
    dogrulaSiparisToplami(numara, tutar)
  }

  /** Sipariş geçmişinin boş olduğunu doğrular. */
  fun dogrulaSiparisYok() {
    gorunurOlmali(Kimlikler.Siparis.BOS)
  }
}

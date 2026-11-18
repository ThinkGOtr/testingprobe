package com.antreklabs.bayisiparis.tp.altyapi

/**
 * Bir testin uygulama oturumu: bekleme ayarı ve test boyunca ekranlar arası taşınan durum
 * (ör. onay ekranında okunan sipariş numarası; ekran nesnesi metotları değer döndürmez).
 */
class UygulamaOturumu(val bekle: Bekle) {

  /** Bu testte onay ekranında okunan son sipariş numarası (yoksa null). */
  var sonSiparisNumarasi: String? = null
}

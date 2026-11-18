package com.antreklabs.bayisiparis.tp.ekranlar

/**
 * Erişilebilirlik kimlikleri — SAF VERİ. Değerler web'deki data-testid'lerin aynısıdır.
 *
 * Yalnızca iç içe `object`'ler ve `const val` dize sabitleri; başka kod yok (TP statik koruması
 * denetler). KDoc ilk cümlesi = niyet (intent). `_ONEK` ile biten sabit önektir: ürün kodu /
 * sipariş numarası eklenir (`URUN_KARTI_ONEK + "P-001" = "product-card-P-001"`). Uygulamada kimlik
 * değişirse onarım yalnızca buradaki değeri değiştirir. Java karşılığı:
 * `demo-app/e2e-app/.../ekranlar/Kimlikler.java` (eşitlik testi).
 */
object Kimlikler {

  /** Üst menü (tüm oturumlu ekranlarda ortak). */
  object Menu {
    /** Üst menüde ürün kataloğuna giden bağlantı. */
    const val KATALOG = "nav-catalog"
    /** Üst menüde sepete giden bağlantı (sepet sayacını içerir). */
    const val SEPET = "nav-cart"
    /** Sepetteki toplam ürün adedini gösteren sayaç. */
    const val SEPET_SAYACI = "cart-count"
    /** Üst menüde sipariş geçmişine giden bağlantı. */
    const val SIPARISLER = "nav-orders"
    /** Oturumu kapatan buton. */
    const val CIKIS = "nav-logout"
    /** Oturum açmış bayinin adı. */
    const val BAYI_ADI = "current-dealer"
  }

  /** Giriş ekranı. */
  object Giris {
    /** Giriş formunda kullanıcı adı alanı. */
    const val KULLANICI_ADI = "login-username"
    /** Giriş formunda parola alanı. */
    const val PAROLA = "login-password"
    /** Giriş formunu gönderen buton. */
    const val GIRIS_YAP = "login-submit"
    /** Hatalı girişte gösterilen hata mesajı. */
    const val HATA = "login-error"
  }

  /** Ürün kataloğu ekranı. */
  object Katalog {
    /** Ürün kartlarının listesi. */
    const val URUN_LISTESI = "product-list"
    /** Tek bir ürünün kartı. */
    const val URUN_KARTI_ONEK = "product-card-"
    /** Ürün kartındaki birim fiyat. */
    const val URUN_FIYATI_ONEK = "product-price-"
    /** Ürün kartında eklenecek adet alanı. */
    const val ADET_ONEK = "qty-input-"
    /** Ürün kartında sepete ekleme butonu (her kartta aynı kimlik; ürün kartının içinde aranır). */
    const val SEPETE_EKLE = "add-to-cart"
    /** Sepete ekleme sonrası ürün kartındaki bilgi mesajı. */
    const val EKLEME_DURUMU_ONEK = "product-status-"
  }

  /** Sepet ekranı. */
  object Sepet {
    /** Sepet satırları tablosu. */
    const val TABLO = "cart-table"
    /** Sepet boşken gösterilen bilgi alanı. */
    const val BOS = "cart-empty"
    /** Sepette bir ürünün satırı. */
    const val SATIR_ONEK = "cart-line-"
    /** Sepet satırındaki adet. */
    const val SATIR_ADEDI_ONEK = "cart-line-qty-"
    /** Sepet satırında kampanyayla bedava verilen adet. */
    const val BEDAVA_ADET_ONEK = "cart-line-free-"
    /** Sepet satırının indirim sonrası tutarı. */
    const val SATIR_TOPLAMI_ONEK = "cart-line-total-"
    /** Satırı sepetten kaldıran buton. */
    const val SATIRI_KALDIR_ONEK = "cart-line-remove-"
    /** Sepetin indirim öncesi ara toplamı. */
    const val ARA_TOPLAM = "cart-subtotal"
    /** Sepetteki toplam kampanya indirimi. */
    const val INDIRIM = "cart-discount"
    /** Sepetin indirim sonrası genel toplamı. */
    const val TOPLAM = "cart-total"
    /** Minimum sipariş tutarının altında gösterilen uyarı. */
    const val MIN_SIPARIS_UYARISI = "min-order-warning"
    /** Sipariş onayı başarısız olduğunda hata mesajı. */
    const val ONAY_HATASI = "checkout-error"
    /** Siparişi onaylayan buton. */
    const val SIPARISI_ONAYLA = "checkout-submit"
  }

  /** Sipariş onayı ekranı. */
  object Onay {
    /** Sipariş onaylandıktan sonra gösterilen onay alanı. */
    const val ONAY_ALANI = "order-confirmation"
    /** Onay alanındaki sipariş numarası. */
    const val SIPARIS_NUMARASI = "order-number"
    /** Onaylanan siparişin kampanya indirimi. */
    const val INDIRIM = "order-discount"
    /** Onaylanan siparişin genel toplamı. */
    const val TOPLAM = "order-total"
    /** Onay ekranından sipariş geçmişine giden buton. */
    const val SIPARISLERIME_GIT = "go-orders"
    /** Onay ekranından kataloğa dönen buton. */
    const val ALISVERISE_DEVAM = "go-catalog"
  }

  /** Sipariş geçmişi (Siparişlerim) ekranı. */
  object Siparis {
    /** Sipariş geçmişi tablosu. */
    const val TABLO = "orders-table"
    /** Hiç sipariş yokken gösterilen bilgi alanı. */
    const val BOS = "orders-empty"
    /** Sipariş geçmişinde bir siparişin satırı. */
    const val SATIR_ONEK = "order-row-"
    /** Sipariş geçmişi satırındaki genel toplam. */
    const val SATIR_TOPLAMI_ONEK = "order-total-"
  }
}

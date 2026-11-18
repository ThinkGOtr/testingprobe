import XCTest

/// Sipariş geçmişi (Siparişlerim) ekranı (web: pages/orders/orders.page.ts; Java: SiparisEkrani).
final class SiparisEkrani: Ekran {
    /// Sipariş geçmişi ekranını açar.
    func ac() {
        dokun(Kimlikler.Menu.siparisler)
        biriGorunurBekle(Kimlikler.Siparis.tablo, Kimlikler.Siparis.bos)
    }

    /// Üst menüden sipariş geçmişine gider.
    func menudenAc() {
        ac()
    }

    /// Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular.
    func dogrulaSiparisGecmiste(siparisNo: String) {
        gorunurOlmali(Ekran.ekli(Kimlikler.Siparis.satirOnek, siparisNo))
    }

    /// Sipariş geçmişindeki siparişin genel toplamını doğrular.
    func dogrulaSiparisToplami(siparisNo: String, tutar: String) {
        metinOlmali(Ekran.ekli(Kimlikler.Siparis.satirToplamiOnek, siparisNo), tutar)
    }

    /// Bu testte onay ekranında görülen son siparişin geçmişteki genel toplamını doğrular.
    func dogrulaOnaylananSiparisToplami(tutar: String) {
        guard let numara = oturum.sonSiparisNumarasi else {
            XCTFail("\(Ekran.eylemIsareti) bu testte onaylanmış sipariş yok (önce onay ekranı doğrulanmalı)")
            return
        }
        dogrulaSiparisToplami(siparisNo: numara, tutar: tutar)
    }

    /// Sipariş geçmişinin boş olduğunu doğrular.
    func dogrulaSiparisYok() {
        gorunurOlmali(Kimlikler.Siparis.bos)
    }
}

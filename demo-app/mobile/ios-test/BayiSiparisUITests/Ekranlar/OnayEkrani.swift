import XCTest

/// Sipariş onayı ekranı (web: pages/checkout/confirmation.page.ts; Java: OnayEkrani).
final class OnayEkrani: Ekran {
    /// Sipariş numarası biçimi (web: `ORDER_NUMBER`).
    private static let siparisNumarasiKalibi = "SP-[0-9]{6}"

    /// Onay ekranındaki sipariş numarasını okur ve oturumda saklar.
    @discardableResult
    private func siparisNumarasiniOku() -> String {
        metinKalibinaUymali(Kimlikler.Onay.siparisNumarasi, OnayEkrani.siparisNumarasiKalibi)
        let numara = gorunurBekle(Kimlikler.Onay.siparisNumarasi).map { metin($0) } ?? ""
        oturum.sonSiparisNumarasi = numara
        return numara
    }

    /// Sipariş onayının ve sipariş numarasının gösterildiğini doğrular.
    func dogrulaSiparisOnayi() {
        gorunurOlmali(Kimlikler.Onay.onayAlani)
        siparisNumarasiniOku()
    }

    /// Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL").
    func dogrulaOnaylananToplam(tutar: String) {
        metinOlmali(Kimlikler.Onay.toplam, tutar)
    }

    /// Onaylanan siparişin kampanya indirimini doğrular (ör. "25,00 TL").
    func dogrulaOnaylananIndirim(tutar: String) {
        metinOlmali(Kimlikler.Onay.indirim, tutar)
    }

    /// Onay ekranında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular.
    func dogrulaOnaylananSiparisGecmiste() {
        let numara = siparisNumarasiniOku()
        let gecmis = SiparisEkrani(oturum: oturum)
        gecmis.menudenAc()
        gecmis.dogrulaSiparisGecmiste(siparisNo: numara)
    }

    /// Onay ekranından "Siparişlerime git" ile sipariş geçmişine gider.
    func siparislerimeGit() {
        dokun(Kimlikler.Onay.siparislerimeGit)
        biriGorunurBekle(Kimlikler.Siparis.tablo, Kimlikler.Siparis.bos)
    }

    /// Onay ekranından "Alışverişe devam et" ile kataloğa döner.
    func alisveriseDevamEt() {
        dokun(Kimlikler.Onay.alisveriseDevam)
        gorunurBekle(Kimlikler.Katalog.urunListesi)
    }
}

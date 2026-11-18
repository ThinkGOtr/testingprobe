import XCTest

/// Ürün kataloğu ekranı (web: pages/catalog/catalog.page.ts `CatalogPage`; Java: KatalogEkrani).
final class KatalogEkrani: Ekran {
    /// Başarılı eklemede ürün kartındaki bilgi mesajının parçası (web: "{n} adet sepete eklendi.").
    private static let eklendi = "sepete eklendi"

    private static func kart(_ urunKodu: String) -> String {
        Ekran.ekli(Kimlikler.Katalog.urunKartiOnek, urunKodu)
    }

    /// Katalog ekranını açar.
    func ac() {
        dokun(Kimlikler.Menu.katalog)
        gorunurBekle(Kimlikler.Katalog.urunListesi)
    }

    /// Üst menüden kataloğa gider.
    func menudenAc() {
        ac()
    }

    /// Ürün kartındaki adet alanına değer yazar.
    func adetGir(urunKodu: String, adet: Int) {
        yaz(Ekran.ekli(Kimlikler.Katalog.adetOnek, urunKodu), String(adet))
    }

    /// Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler.
    func sepeteEkle(urunKodu: String, adet: Int) {
        let once = sepetSayaci()
        adetGir(urunKodu: urunKodu, adet: adet)
        dokun(Kimlikler.Katalog.sepeteEkle, kapsayici: KatalogEkrani.kart(urunKodu))
        let durum = Ekran.ekli(Kimlikler.Katalog.eklemeDurumuOnek, urunKodu)
        // Uygulamada ağ görünmez: kart mesajı + sayaç artışı beklenir.
        kosul("sepete ekleme tamamlanmadı: '\(durum)' mesajı ve sepet sayacı \(once + adet)") { () -> Bool? in
            let mesaj = hemenBul(nil, durum).map { metin($0) } ?? ""
            if !mesaj.isEmpty && !mesaj.contains(KatalogEkrani.eklendi) {
                XCTFail("\(Ekran.eylemIsareti) sepete ekleme başarısız: \(mesaj)")
                return false
            }
            return mesaj.contains(KatalogEkrani.eklendi) && sayacHemen() == once + adet ? true : nil
        }
    }

    /// Üst menüden sepete gider.
    func sepetiAc() {
        dokun(Kimlikler.Menu.sepet)
        biriGorunurBekle(Kimlikler.Sepet.tablo, Kimlikler.Sepet.bos)
    }

    /// Ürün kartının katalogda göründüğünü doğrular.
    func dogrulaUrunGorunur(urunKodu: String) {
        gorunurOlmali(KatalogEkrani.kart(urunKodu))
    }

    /// Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL").
    func dogrulaUrunFiyati(urunKodu: String, fiyat: String) {
        metinOlmali(Ekran.ekli(Kimlikler.Katalog.urunFiyatiOnek, urunKodu), fiyat)
    }

    /// Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava").
    func dogrulaKampanya(urunKodu: String, kampanyaAdi: String) {
        tumMetinIcermeli(KatalogEkrani.kart(urunKodu), kampanyaAdi)
    }

    /// Üst menüdeki sepet sayacının verilen adet olduğunu doğrular.
    func dogrulaSepetSayaci(adet: Int) {
        metinOlmali(Kimlikler.Menu.sepetSayaci, String(adet))
    }

    // ---------------------------------------------------------------- yardımcılar (sembol tablosu dışı)

    private func sepetSayaci() -> Int {
        gorunurBekle(Kimlikler.Menu.sepetSayaci)
        return kosul("sepet sayacı okunamadı: kimlik '\(Kimlikler.Menu.sepetSayaci)'") { () -> Int? in
            let n = sayacHemen()
            return n < 0 ? nil : n
        } ?? 0
    }

    /// Sayacı beklemeden okur; yoksa ya da sayı değilse -1.
    private func sayacHemen() -> Int {
        guard let e = hemenBul(nil, Kimlikler.Menu.sepetSayaci) else { return -1 }
        return Int(metin(e)) ?? -1
    }
}

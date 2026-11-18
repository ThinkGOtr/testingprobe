import XCTest

/// Sepet ekranı (web: pages/cart/cart.page.ts `CartPage`; Java: SepetEkrani).
final class SepetEkrani: Ekran {
    /// Sepet ekranını açar.
    func ac() {
        dokun(Kimlikler.Menu.sepet)
        biriGorunurBekle(Kimlikler.Sepet.tablo, Kimlikler.Sepet.bos)
    }

    /// Ürünü sepetten kaldırır.
    func urunuKaldir(urunKodu: String) {
        dokun(Ekran.ekli(Kimlikler.Sepet.satiriKaldirOnek, urunKodu))
        let satir = Ekran.ekli(Kimlikler.Sepet.satirOnek, urunKodu)
        kosul("satır sepetten kalkmadı: kimlik '\(satir)'") { hemenBul(nil, satir) == nil ? true : nil }
    }

    /// "Siparişi onayla" butonuna basar ve onay ekranının açılmasını bekler.
    func siparisiOnayla() {
        dokun(Kimlikler.Sepet.siparisiOnayla)
        gorunurBekle(Kimlikler.Onay.onayAlani)
    }

    /// Sepet satırındaki adedi doğrular.
    func dogrulaSatirAdedi(urunKodu: String, adet: Int) {
        metinOlmali(Ekran.ekli(Kimlikler.Sepet.satirAdediOnek, urunKodu), String(adet))
    }

    /// Sepet satırında kampanyayla bedava verilen adedi doğrular.
    func dogrulaBedavaAdet(urunKodu: String, adet: Int) {
        metinOlmali(Ekran.ekli(Kimlikler.Sepet.bedavaAdetOnek, urunKodu), String(adet))
    }

    /// Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL").
    func dogrulaSatirToplami(urunKodu: String, tutar: String) {
        metinOlmali(Ekran.ekli(Kimlikler.Sepet.satirToplamiOnek, urunKodu), tutar)
    }

    /// Ara toplamı doğrular (ör. "175,00 TL").
    func dogrulaAraToplam(tutar: String) {
        metinOlmali(Kimlikler.Sepet.araToplam, tutar)
    }

    /// Kampanya indirimi tutarını doğrular (ör. "25,00 TL").
    func dogrulaIndirim(tutar: String) {
        metinOlmali(Kimlikler.Sepet.indirim, tutar)
    }

    /// Sepetin indirim sonrası genel toplamını doğrular (ör. "150,00 TL").
    func dogrulaToplam(tutar: String) {
        metinOlmali(Kimlikler.Sepet.toplam, tutar)
    }

    /// Minimum sipariş uyarısının verilen metni içerdiğini doğrular (ör. "Minimum sipariş tutarı 750,00 TL").
    func dogrulaMinimumSiparisUyarisi(mesaj: String) {
        metinIcermeli(Kimlikler.Sepet.minSiparisUyarisi, mesaj)
    }

    /// Minimum sipariş uyarısının gösterilmediğini doğrular.
    func dogrulaMinimumSiparisUyarisiYok() {
        yokOlmali(Kimlikler.Sepet.minSiparisUyarisi)
    }

    /// "Siparişi onayla" butonunun pasif olduğunu doğrular.
    func dogrulaOnayPasif() {
        etkinOlmali(Kimlikler.Sepet.siparisiOnayla, false)
    }

    /// "Siparişi onayla" butonunun aktif olduğunu doğrular.
    func dogrulaOnayAktif() {
        etkinOlmali(Kimlikler.Sepet.siparisiOnayla, true)
    }

    /// Sepette ürünün bulunmadığını doğrular.
    func dogrulaUrunSepetteYok(urunKodu: String) {
        yokOlmali(Ekran.ekli(Kimlikler.Sepet.satirOnek, urunKodu))
    }

    /// Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet ekranında).
    func dogrulaSepetSayaci(adet: Int) {
        metinOlmali(Kimlikler.Menu.sepetSayaci, String(adet))
    }

    /// Sepetin boş olduğunu doğrular.
    func dogrulaSepetBos() {
        gorunurOlmali(Kimlikler.Sepet.bos)
    }
}

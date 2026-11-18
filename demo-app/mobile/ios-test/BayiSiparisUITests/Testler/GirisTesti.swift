import XCTest

/// Giriş (TPD-1) — web: tests/login.spec.ts; Java: testler/GirisTesti.java. Elle yazılmış referans
/// testtir; TP'nin ürettiği testler `TPUretilen/` altındadır.
final class GirisTesti: TestTabani {
    func testGecerliBilgilerleGiris() {
        girisEkrani.ac()
        girisEkrani.girisYap(kullaniciAdi: "bayi1", parola: "Demo123!")
        girisEkrani.dogrulaGirisYapildi(bayiAdi: "Merkez Bayi")
    }

    func testHataliParolaHataGosterir() {
        girisEkrani.ac()
        girisEkrani.girisYap(kullaniciAdi: "bayi1", parola: "yanlis")
        girisEkrani.dogrulaHataMesaji(beklenen: "Kullanıcı adı veya parola hatalı")
        girisEkrani.dogrulaGirisEkraninda()
    }
}

/// Katalog ve sepet (TPD-1) — web: tests/cart.spec.ts; Java: testler/SepetTesti.java.
final class SepetTesti: TestTabani {
    override class var oturumAcik: Bool { true }

    override func hazirlikSonrasi() {
        katalogEkrani.ac()
    }

    func testSepeteEkleSayaciArtirir() {
        katalogEkrani.dogrulaSepetSayaci(adet: 0)
        katalogEkrani.sepeteEkle(urunKodu: "P-002", adet: 1)
        katalogEkrani.dogrulaSepetSayaci(adet: 1)
    }
}

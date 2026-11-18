// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map_app · platform: ios · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 46175a46bd07b3e2b3e31ca480890fd9846f06f5c3276a5a93846e227326987b · şablon: 0cd23e804f2315feb72fe77b2026c520e68d3419b259a77f0fd3901648754247
// Doğrulama: müşteri CI (mobil-ios-swift) · kırarak doğrulanmadı
// Senaryo: 7 adet kampanyalı üründe 1 adet bedava verilir
import XCTest

final class TPD1IosC2_3f9b1c2eTests: TestTabani {
    override class var bayi: String? { "bayi1" }

    func testSenaryo() {
        // S1 — Giriş sayfasını aç
        girisEkrani.ac()
        // S2 — Bayi kullanıcısıyla giriş yap
        girisEkrani.girisYap(kullaniciAdi: "bayi1", parola: "Demo123!")
        // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
        katalogEkrani.sepeteEkle(urunKodu: "P-001", adet: 7)
        // S4 — Üst menüden sepete git
        katalogEkrani.sepetiAc()
        // Beklenen sonuç (değerler onaylı case metninden)
        sepetEkrani.dogrulaSatirAdedi(urunKodu: "P-001", adet: 7)
        sepetEkrani.dogrulaBedavaAdet(urunKodu: "P-001", adet: 1)
        sepetEkrani.dogrulaAraToplam(tutar: "175,00 TL")
        sepetEkrani.dogrulaIndirim(tutar: "25,00 TL")
        sepetEkrani.dogrulaToplam(tutar: "150,00 TL")
    }
}

import XCTest

/// Tüm UI testlerinin tabanı (Java: altyapi/TestTabani.java; web: tests/fixtures.ts).
///
/// Her test için, sırasıyla: bayi seçilir (`bayi` sınıf özelliği, yoksa `bayi1`), bayinin verisi
/// sıfırlanır (`TestVerisi.sifirla`; `TP_E2E_NO_RESET=1` ise atlanır), uygulama sıfırdan başlatılır,
/// `oturumAcik` ise arayüzden giriş yapılır, sonra `hazirlikSonrasi()`.
///
/// Fikstür erişimi (TASARIM §3.4): her ekran için `lowerCamel(SınıfAdı)` özelliği; üretilen testler
/// yalnızca bu özelliklerin metotlarını çağırır (`girisEkrani.girisYap(kullaniciAdi:parola:)`).
/// Gizli test verisi `ortam("TP_TESTVERI_…")` ile okunur.
class TestTabani: XCTestCase {
    /// Testin sabitlendiği e2e bayisi (üretilen test `override class var bayi` ile verir).
    class var bayi: String? { nil }
    /// true: hazırlıkta arayüzden giriş yapılır.
    class var oturumAcik: Bool { false }

    private(set) var oturum: UygulamaOturumu!
    private(set) var bayiBilgisi: BayiBilgisi!

    lazy var girisEkrani = GirisEkrani(oturum: oturum)
    lazy var katalogEkrani = KatalogEkrani(oturum: oturum)
    lazy var sepetEkrani = SepetEkrani(oturum: oturum)
    lazy var onayEkrani = OnayEkrani(oturum: oturum)
    lazy var siparisEkrani = SiparisEkrani(oturum: oturum)

    /// Test koşucusu ortamındaki değer (yoksa boş; xcodebuild'e `TEST_RUNNER_<AD>` ile verilir).
    func ortam(_ ad: String) -> String {
        ProcessInfo.processInfo.environment[ad] ?? ""
    }

    /// Alt sınıfın hazırlık sonrası adımı (ör. kataloğu açmak).
    func hazirlikSonrasi() {}

    override func setUpWithError() throws {
        try super.setUpWithError()
        continueAfterFailure = false
        let ad = Self.bayi ?? Bayiler.e2e[0].kullaniciAdi
        guard let b = Bayiler.bul(ad) else {
            throw TestVerisi.Hata.ayarYok("bilinmeyen e2e bayisi: \(ad)")
        }
        bayiBilgisi = b
        if ortam("TP_E2E_NO_RESET") != "1" {
            try TestVerisi.sifirla(kullaniciAdi: b.kullaniciAdi)
        }
        let app = XCUIApplication()
        app.launch()
        oturum = UygulamaOturumu(app: app)
        oturumuKapat(app)
        if Self.oturumAcik {
            girisEkrani.girisYap(kullaniciAdi: b.kullaniciAdi, parola: b.parola)
            girisEkrani.dogrulaGirisYapildi(bayiAdi: b.ad)
        }
        hazirlikSonrasi()
    }

    /// Uygulama yeniden kurulmadan başlatıldığı için önceki testin oturumu (çerez) kalabilir:
    /// açık oturum varsa arayüzden kapatılır, giriş ekranı beklenir (Java'da her test yeni kurulum).
    private func oturumuKapat(_ app: XCUIApplication) {
        let giris = app.descendants(matching: .any)[Kimlikler.Giris.kullaniciAdi]
        let cikis = app.descendants(matching: .any)[Kimlikler.Menu.cikis]
        let son = Date().addingTimeInterval(20)
        while Date() < son && !giris.exists && !cikis.exists {
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        if cikis.exists {
            cikis.tap()
            _ = giris.waitForExistence(timeout: 15)
        }
    }

    override func tearDownWithError() throws {
        if let app = oturum?.app, testRun?.hasSucceeded == false {
            let ek = XCTAttachment(screenshot: app.screenshot())
            ek.name = "hata-ekrani"
            ek.lifetime = .keepAlways
            add(ek)
        }
        oturum?.app.terminate()
        try super.tearDownWithError()
    }
}

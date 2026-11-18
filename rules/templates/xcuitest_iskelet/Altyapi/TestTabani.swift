import XCTest

/// Tüm UI testlerinin tabanı (AI Testing Probe kurulum iskeleti).
///
/// Her test uygulamayı sıfırdan başlatır. Fikstür erişimi: her ekran nesnesi için
/// `lowerCamel(SınıfAdı)` adlı `lazy var` (ör. `lazy var girisEkrani = GirisEkrani(oturum: oturum)`);
/// TP'nin ürettiği testler (`TPUretilen/`) yalnızca bu özelliklerin metotlarını çağırır. Gizli test
/// verisi `ortam("TP_TESTVERI_…")` ile okunur (xcodebuild'e `TEST_RUNNER_TP_TESTVERI_…`).
/// Test verisi sıfırlama / giriş gibi proje adımlarını `setUpWithError` içine ekleyin.
class TestTabani: XCTestCase {
    /// Testin sabitlendiği test kullanıcısı (üretilen test `override class var bayi` ile verir).
    class var bayi: String? { nil }

    private(set) var oturum: UygulamaOturumu!

    // Ekran erişimcileri, ör.:
    // lazy var girisEkrani = GirisEkrani(oturum: oturum)

    /// Test koşucusu ortamındaki değer (yoksa boş).
    func ortam(_ ad: String) -> String {
        ProcessInfo.processInfo.environment[ad] ?? ""
    }

    override func setUpWithError() throws {
        try super.setUpWithError()
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        oturum = UygulamaOturumu(app: app)
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

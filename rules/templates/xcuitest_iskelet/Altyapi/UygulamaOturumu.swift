import XCTest

/// Bir testin uygulama oturumu: başlatılan uygulama + testler arası taşınmayan durum
/// (Java: altyapi/UygulamaOturumu.java).
final class UygulamaOturumu {
    let app: XCUIApplication
    /// Bu testte onay ekranında görülen son sipariş numarası.
    var sonSiparisNumarasi: String?

    init(app: XCUIApplication) {
        self.app = app
    }
}

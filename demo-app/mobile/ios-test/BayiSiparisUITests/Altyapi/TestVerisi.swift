import Foundation

/// Test verisi sıfırlama (Java: altyapi/TestVerisi.java): `POST <DEMO_API_URL>/test/reset`,
/// `X-Demoapp-Test-Token` başlığıyla. Değerler test koşucusunun ortamından okunur; xcodebuild'e
/// `TEST_RUNNER_DEMO_API_URL` / `TEST_RUNNER_DEMOAPP_TEST_TOKEN` olarak verilir (önek düşer).
enum TestVerisi {
    static let tokenBasligi = "X-Demoapp-Test-Token"

    enum Hata: Error, CustomStringConvertible {
        case ayarYok(String)
        case istek(String)

        var description: String {
            switch self {
            case .ayarYok(let m), .istek(let m): return m
            }
        }
    }

    /// Bayinin verisini sıfırlar (sepet, siparişler, kırılmalar).
    static func sifirla(kullaniciAdi: String, ortam: [String: String] = ProcessInfo.processInfo.environment) throws {
        guard let kok = ortam["DEMO_API_URL"], !kok.isEmpty, let token = ortam["DEMOAPP_TEST_TOKEN"], !token.isEmpty
        else {
            throw Hata.ayarYok(
                "DEMO_API_URL / DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz "
                    + "(xcodebuild'e TEST_RUNNER_ önekiyle verin ya da TP_E2E_NO_RESET=1)")
        }
        let adres = kok.replacingOccurrences(of: "/+$", with: "", options: .regularExpression) + "/test/reset"
        guard let url = URL(string: adres) else { throw Hata.ayarYok("geçersiz DEMO_API_URL: \(kok)") }
        var istek = URLRequest(url: url, timeoutInterval: 20)
        istek.httpMethod = "POST"
        istek.setValue("application/json", forHTTPHeaderField: "Content-Type")
        istek.setValue(token, forHTTPHeaderField: tokenBasligi)
        istek.httpBody = try JSONSerialization.data(withJSONObject: ["kullanici_adi": kullaniciAdi])

        let bitti = DispatchSemaphore(value: 0)
        var durum = -1
        var hata: Error?
        URLSession.shared.dataTask(with: istek) { _, yanit, h in
            durum = (yanit as? HTTPURLResponse)?.statusCode ?? -1
            hata = h
            bitti.signal()
        }.resume()
        if bitti.wait(timeout: .now() + 25) == .timedOut {
            throw Hata.istek("POST /test/reset zaman aşımı")
        }
        if let hata { throw Hata.istek("POST /test/reset başarısız: \(hata.localizedDescription)") }
        guard (200..<300).contains(durum) else { throw Hata.istek("POST /test/reset başarısız: \(durum)") }
    }
}

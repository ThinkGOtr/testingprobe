/// e2e bayileri (Java: altyapi/Bayiler.java `E2E`; web: tests/fixtures.ts `DEALERS`). Demo verisidir;
/// gerçek bir müşteri projesinde parolalar `TP_TESTVERI_*` sırlarından okunur (`TestTabani.ortam`).
struct BayiBilgisi {
    let kullaniciAdi: String
    let parola: String
    let ad: String
}

enum Bayiler {
    static let e2e: [BayiBilgisi] = [
        BayiBilgisi(kullaniciAdi: "bayi1", parola: "Demo123!", ad: "Merkez Bayi"),
        BayiBilgisi(kullaniciAdi: "bayi2", parola: "Demo123!", ad: "Sahil Bayi"),
    ]

    static func bul(_ kullaniciAdi: String) -> BayiBilgisi? {
        e2e.first { $0.kullaniciAdi == kullaniciAdi }
    }
}

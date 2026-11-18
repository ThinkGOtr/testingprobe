// Erişilebilirlik kimlikleri — SAF VERİ (AI Testing Probe kurulum iskeleti).
//
// Uygulamadaki `accessibilityIdentifier` değerleri burada toplanır. Yalnızca iç içe `enum`'lar ve
// `static let` dize sabitleri; başka kod yok (TP koruması denetler). `///` belge yorumunun ilk
// cümlesi = niyet. `Onek` ile biten sabit önektir (`urunKartiOnek + kod`). Ekran nesneleri
// (`Ekran`'dan türeyen `final class`'lar) kimliklere yalnız buradan başvurur.

enum Kimlikler {
    /// Örnek ekran (silin ya da yeniden adlandırın).
    enum Ornek {
        /// Örnek buton.
        static let buton = "ornek-buton"
    }
}

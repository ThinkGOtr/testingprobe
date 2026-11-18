import XCTest

/// Bayi giriş ekranı (web: pages/login/login.page.ts `LoginPage`; Java: GirisEkrani).
final class GirisEkrani: Ekran {
    /// Giriş ekranını açar (uygulama her testte sıfırdan, giriş ekranında başlar).
    func ac() {
        gorunurBekle(Kimlikler.Giris.kullaniciAdi)
    }

    /// Bayi kullanıcı adı ve parolasıyla giriş yapar.
    func girisYap(kullaniciAdi: String, parola: String) {
        yaz(Kimlikler.Giris.kullaniciAdi, kullaniciAdi)
        yaz(Kimlikler.Giris.parola, parola)
        dokun(Kimlikler.Giris.girisYap)
    }

    /// Oturumu kapatır.
    func cikisYap() {
        dokun(Kimlikler.Menu.cikis)
    }

    /// Hata mesajının göründüğünü ve metnini doğrular.
    func dogrulaHataMesaji(beklenen: String) {
        metinOlmali(Kimlikler.Giris.hata, beklenen)
    }

    /// Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular.
    func dogrulaGirisYapildi(bayiAdi: String) {
        metinOlmali(Kimlikler.Menu.bayiAdi, bayiAdi)
        gorunurOlmali(Kimlikler.Katalog.urunListesi)
    }

    /// Giriş ekranında olunduğunu doğrular.
    func dogrulaGirisEkraninda() {
        gorunurOlmali(Kimlikler.Giris.girisYap)
        yokOlmali(Kimlikler.Menu.bayiAdi)
    }
}

# language: tr
# Testing Probe — onaylı ve hazır case'lerden deterministik dönüşüm (model çağrısı yok).
# 2 case · 2 senaryo (0 taslak)
Özellik: TPD-4 — Bayi girişi
  # AC1: Bayi geçerli kullanıcı adı ve parolayla giriş yaptığında ürün kataloğu açılır.
  # AC2: Hatalı parola girildiğinde "Kullanıcı adı veya parola hatalı" mesajı gösterilir ve giriş yapılmaz.

  @AC1 @EP @P1 @pozitif @tp-41768be0-2e12-5ade-8055-8f024a244c6c
  Senaryo: Geçerli kullanıcı adı ve parola ile giriş yapılır
    Diyelim ki Oturum açık değil
    Ve test verileri:
      | ad                              | değer            | sınıf |
      | geçerli kullanıcı adı ve parola | bayi1 / Demo123! | EP-V1 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Kullanıcı adı ve parola gir, "Giriş yap" butonuna bas, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Ve Bayi başarıyla giriş yapar ve katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    # Temizlik: Çıkış yap

  @AC2 @EP @P1 @negatif @tp-59d76184-9ca7-5417-be5e-4c90cf0f20c8
  Senaryo: Hatalı parola ile girişte hata mesajı gösterilir
    Diyelim ki Oturum açık değil
    Ve test verileri:
      | ad                    | değer      | sınıf |
      | kayıtlı kullanıcı adı | bayi1      |       |
      | hatalı parola         | Yanlis123! | EP-I1 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Kullanıcı adı ve hatalı parola gir, "Giriş yap" butonuna bas, veri: "bayi1 / Yanlis123!"
    O zaman "Kullanıcı adı veya parola hatalı" mesajı görünür ve giriş sayfasında kalınır
    Ve "Kullanıcı adı veya parola hatalı" mesajı gösterilir ve giriş yapılmaz

# language: tr
# Testing Probe — onaylı ve hazır case'lerden deterministik dönüşüm (model çağrısı yok).
# 3 case · 3 senaryo (0 taslak)
Özellik: TPD-3 — Katalogda ürün arama
  # AC1: Bayi katalogda ürün adının bir bölümünü yazdığında yalnızca eşleşen ürünler listelenir.
  # AC2: Eşleşen ürün yoksa "Ürün bulunamadı" mesajı gösterilir.

  @AC1 @EP @P2 @pozitif @tp-783ab9fa-2d9f-546e-a109-eb20b6eb3f75
  Senaryo: Ürün adının bir bölümüyle arama yalnızca eşleşen ürünleri listeler
    Diyelim ki bayi1 / Demo123! ile giriş yapılmış
    Ve katalog sayfası açık
    Ve test verileri:
      | ad                               | değer | sınıf |
      | Arama metni (tek ürünle eşleşir) | Gazoz | EP-V1 |
    Eğer ki arama alanına ürün adının bir bölümünü yazarsa (test verisi: Arama metni (tek ürünle eşleşir))
    O zaman yalnızca "Portakal Gazozu 1L" listelenir
    Ve katalogda yalnızca "Portakal Gazozu 1L" görünür; diğer ürünler listelenmez

  @AC1 @EP @P3 @pozitif @tp-3c337c5a-aa8f-55ce-bd5c-c7abecb93b43
  Senaryo: Birden çok ürünle eşleşen arama hepsini listeler
    Diyelim ki bayi1 / Demo123! ile giriş yapılmış
    Ve katalog sayfası açık
    Ve test verileri:
      | ad                               | değer | sınıf |
      | Arama metni (iki ürünle eşleşir) | 1L    | EP-V2 |
    Eğer ki arama alanına ortak bir ad parçası yazarsa (test verisi: Arama metni (iki ürünle eşleşir))
    O zaman "Portakal Gazozu 1L" ve "Şeftalili Soğuk Çay 1L" listelenir
    Ve katalogda yalnızca "Portakal Gazozu 1L" ve "Şeftalili Soğuk Çay 1L" görünür

  @AC2 @EP @P2 @negatif @tp-ed94423f-53b4-59f0-905d-59786cdc875a
  Senaryo: Eşleşme olmayan aramada "Ürün bulunamadı" mesajı gösterilir
    Diyelim ki bayi1 / Demo123! ile giriş yapılmış
    Ve katalog sayfası açık
    Ve test verileri:
      | ad                        | değer | sınıf |
      | Arama metni (eşleşme yok) | Kahve | EP-I1 |
    Eğer ki arama alanına hiçbir ürünle eşleşmeyen bir metin yazarsa (test verisi: Arama metni (eşleşme yok))
    O zaman "Ürün bulunamadı" mesajı görünür
    Ve ürün listelenmez ve "Ürün bulunamadı" mesajı gösterilir

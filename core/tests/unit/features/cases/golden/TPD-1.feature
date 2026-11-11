# language: tr
# Testing Probe — onaylı ve hazır case'lerden deterministik dönüşüm (model çağrısı yok).
# 10 case · 9 senaryo (1 taslak)
Özellik: TPD-1 — Sepet ve sipariş
  # AC1: Bayi katalogda bir ürün için "Sepete ekle" butonuna bastığında ürün sepete eklenir ve sepet sayacı artar.
  # AC2: Kampanyalı üründe her 6 adette 1 adet bedava verilir: bayi 5 adet öder, 1 adet bedava alır (6 adette 1, 12 adette 2 bedava).
  # AC3: Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL'dir; altında "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur.
  # AC4: Sipariş tutarı bayinin kredi limitini aşarsa "Kredi limiti aşıldı" uyarısı gösterilir ve sipariş onaylanamaz.
  # AC5: Sipariş onaylandığında sipariş numarası gösterilir ve sipariş, sipariş geçmişinde listelenir.
  # AC6: Kampanyalı siparişlerde minimum sipariş tutarı şartı aranmaz.

  @AC1 @EP @P1 @pozitif @tp-d2f16769-b49a-5caa-94d9-633458704018
  Senaryo: Sepete ekle ile ürün sepete eklenir ve sepet sayacı artar
    Diyelim ki Sepet boş
    Ve test verileri:
      | ad               | değer            | sınıf |
      | bayi kullanıcısı | bayi1 / Demo123! |       |
      | ürün ve adet     | P-001 × 1        | EP-V1 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi 1 yapıp "Sepete ekle" butonuna bas, veri: "P-001 × 1"
    O zaman Sepet sayacı 1 olur
    Ve Ürün sepete eklenir ve sepet sayacı 1 olur
    # Temizlik: Sepeti boşalt

  @AC2 @EP @P1 @pozitif @tp-ee88012e-d8ca-5f51-83fb-3b3035538761
  Senaryo: 7 adet kampanyalı üründe 1 adet bedava verilir
    Diyelim ki Sepet boş
    Ve P-001 "6 al 1 bedava" kampanyasında
    Ve test verileri:
      | ad                      | değer            | sınıf |
      | bayi kullanıcısı        | bayi1 / Demo123! |       |
      | kampanyalı ürün ve adet | P-001 × 7        | EP-V3 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas, veri: "P-001 × 7"
    O zaman Sepet sayacı 7 olur
    Eğer ki Üst menüden sepete git
    O zaman P-001 satırında adet 7, bedava adet 1; ara toplam 175,00 TL, indirim 25,00 TL, toplam 150,00 TL
    Ve 7 adette 1 adet bedava verilir; indirim 25,00 TL, toplam 150,00 TL
    # Temizlik: Sepeti boşalt

  @AC2 @BVA @EP @P1 @sınır-değer
  Senaryo taslağı: AC2 · sınır değer analizi (BVA) — 2 örnek
    Diyelim ki Sepet boş
    Ve P-001 "6 al 1 bedava" kampanyasında
    Ve test verileri:
      | ad                      | değer            | sınıf   |
      | bayi kullanıcısı        | bayi1 / Demo123! |         |
      | kampanyalı ürün ve adet | P-001 × <girdi>  | <sınıf> |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi <girdi> yapıp "Sepete ekle" butonuna bas, veri: "P-001 × <girdi>"
    O zaman Sepet sayacı <girdi> olur
    Eğer ki Üst menüden sepete git
    O zaman <ara_beklenen>
    Ve <beklenen>
    # Temizlik: Sepeti boşalt

    @tp-f605169a-4659-5d96-94ba-39cc90f87610
    Örnekler: 6 adet kampanyalı üründe 1 adet bedava verilir
      | teknik | bölüm_id | girdi | sınıf | beklenen                                                           | ara_beklenen                                                                                    |
      | BVA    | BV-2     | 6     | BV-2  | 6 adette 1 adet bedava verilir; indirim 25,00 TL, toplam 125,00 TL | P-001 satırında adet 6, bedava adet 1; ara toplam 150,00 TL, indirim 25,00 TL, toplam 125,00 TL |

    @tp-26fb1747-82bb-5672-8a4d-63433785e8e2
    Örnekler: 5 adet kampanyalı üründe bedava ürün verilmez
      | teknik  | bölüm_id    | girdi | sınıf | beklenen                                                       | ara_beklenen                                                                                   |
      | BVA, EP | BV-1, EP-V2 | 5     | BV-1  | 5 adette bedava adet 0 olur; indirim 0,00 TL, toplam 125,00 TL | P-001 satırında adet 5, bedava adet 0; ara toplam 125,00 TL, indirim 0,00 TL, toplam 125,00 TL |

  @AC3 @EP @P1 @negatif @tp-fc10a6c6-5a60-5777-b8e9-f34b6310d989
  Senaryo: Kampanyasız siparişte minimum tutarın altında uyarı gösterilir ve onay pasif olur
    Diyelim ki Sepet boş
    Ve Sepette kampanyalı ürün yok
    Ve test verileri:
      | ad                                          | değer            | sınıf |
      | bayi kullanıcısı                            | bayi1 / Demo123! |       |
      | kampanyasız ürün ve adet (toplam 150,00 TL) | P-002 × 10       | EP-I1 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Limonata 330ml" (P-002) kartında adedi 10 yapıp "Sepete ekle" butonuna bas, veri: "P-002 × 10"
    O zaman Sepet sayacı 10 olur
    Eğer ki Üst menüden sepete git
    O zaman Toplam 150,00 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı görünür ve "Siparişi onayla" butonu pasiftir
    Ve "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur
    # Temizlik: Sepeti boşalt

  @AC3 @BVA @EP @P1 @sınır-değer @tp-d5a6b0af-1fa4-58ac-a0d8-db0c76a2db6e
  Senaryo: Kampanyasız siparişte minimum tutara eşit toplamda uyarı gösterilmez ve onay aktif olur
    Diyelim ki Sepet boş
    Ve Sepette kampanyalı ürün yok
    Ve test verileri:
      | ad                                          | değer            | sınıf |
      | bayi kullanıcısı                            | bayi1 / Demo123! |       |
      | kampanyasız ürün ve adet (toplam 750,00 TL) | P-004 × 25       | BV-5  |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna bas, veri: "P-004 × 25"
    O zaman Sepet sayacı 25 olur
    Eğer ki Üst menüden sepete git
    O zaman Toplam 750,00 TL; minimum sipariş uyarısı görünmez ve "Siparişi onayla" butonu aktiftir
    Ve Toplam 750,00 TL olduğunda uyarı gösterilmez ve sipariş onaylanabilir
    # Temizlik: Sepeti boşalt

  @AC4 @EP @P1 @negatif @tp-17ef2a6f-2afd-53e1-b9fb-a2a13b309d26
  Senaryo: Kredi limitini aşan siparişte uyarı gösterilir ve sipariş onaylanamaz
    Diyelim ki Sepet boş
    Ve bayi2 (Sahil Bayi) kredi limiti 500,00 TL
    Ve test verileri:
      | ad                                        | değer            | sınıf |
      | bayi kullanıcısı (kredi limiti 500,00 TL) | bayi2 / Demo123! |       |
      | ürün ve adet (toplam 750,00 TL)           | P-004 × 25       | EP-I2 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi2 / Demo123!"
    O zaman Katalog sayfası "Sahil Bayi" oturumuyla görüntülenir
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna bas, veri: "P-004 × 25"
    O zaman Sepet sayacı 25 olur
    Eğer ki Üst menüden sepete git
    O zaman Toplam 750,00 TL kredi limitini (500,00 TL) aşar; "Kredi limiti aşıldı" uyarısı görünür ve "Siparişi onayla" butonu pasiftir
    Ve "Kredi limiti aşıldı" uyarısı gösterilir ve sipariş onaylanamaz
    # Temizlik: Sepeti boşalt

  @AC5 @UC @P1 @pozitif @tp-09f14c76-b77d-5e01-839f-bed67b40feee
  Senaryo: Onaylanan siparişin numarası gösterilir ve sipariş geçmişinde listelenir
    Diyelim ki Sepet boş
    Ve test verileri:
      | ad                              | değer            | sınıf |
      | bayi kullanıcısı                | bayi1 / Demo123! |       |
      | ürün ve adet (toplam 750,00 TL) | P-004 × 25       |       |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna bas, veri: "P-004 × 25"
    O zaman Sepet sayacı 25 olur
    Eğer ki Üst menüden sepete git
    O zaman Toplam 750,00 TL ve "Siparişi onayla" butonu aktiftir
    Eğer ki "Siparişi onayla" butonuna bas
    O zaman Sipariş onay sayfasında sipariş numarası ve toplam 750,00 TL gösterilir; sipariş, sipariş geçmişinde bu numarayla listelenir
    Ve Sipariş numarası gösterilir ve sipariş, sipariş geçmişinde listelenir
    # Temizlik: Oluşturulan sipariş, sipariş geçmişinde kalır; test ortamı sıfırlanırken temizle

  @AC6 @EP @P2 @pozitif @tp-9739c53b-04f2-5e4a-908f-926ac797f674
  Senaryo: Kampanyalı siparişte minimum sipariş tutarı şartı aranmaz
    Diyelim ki Sepet boş
    Ve P-001 "6 al 1 bedava" kampanyasında
    Ve test verileri:
      | ad                                         | değer            | sınıf |
      | bayi kullanıcısı                           | bayi1 / Demo123! |       |
      | kampanyalı ürün ve adet (toplam 150,00 TL) | P-001 × 7        | EP-V7 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas, veri: "P-001 × 7"
    O zaman Sepet sayacı 7 olur
    Eğer ki Üst menüden sepete git
    O zaman Toplam 150,00 TL; minimum sipariş uyarısı görünmez ve "Siparişi onayla" butonu aktiftir
    Ve Kampanyalı sepette toplam 150,00 TL olsa da minimum sipariş uyarısı gösterilmez ve sipariş onaylanabilir
    # Temizlik: Sepeti boşalt

  @AC2 @EP @P1 @pozitif @tp-f2a64199-1d3d-59e7-9b02-752253ee8214
  Senaryo: Kampanyalı üründen 7 adet sepete eklenince bedava adet ve tutarlar doğru hesaplanır
    Diyelim ki Sepet boş
    Ve P-001 "6 al 1 bedava" kampanyasında
    Ve test verileri:
      | ad                      | değer            | sınıf |
      | bayi kullanıcısı        | bayi1 / Demo123! |       |
      | kampanyalı ürün ve adet | P-001 × 7        | EP-V3 |
    Eğer ki Giriş sayfasını aç
    O zaman Giriş formu görüntülenir
    Eğer ki Bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas, veri: "P-001 × 7"
    O zaman Sepet sayacı 7 olur
    Eğer ki Üst menüden sepete git
    O zaman P-001 satırında adet 7, bedava adet 1; ara toplam 175,00 TL, indirim 25,00 TL, toplam 150,00 TL
    Ve 7 adette 1 adet bedava verilir; indirim 25,00 TL, toplam 150,00 TL
    # Temizlik: Sepeti boşalt

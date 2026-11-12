# language: tr
# Testing Probe — onaylı ve hazır case'lerden deterministik dönüşüm (model çağrısı yok).
# 6 case · 6 senaryo (0 taslak)
Özellik: SERBEST — Sepetten ürün kaldırma
  # AC1: Satırdaki "Kaldır" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır.
  # AC2: Kaldırma sonrası kampanya indirimi her 6 adette 1 bedava kuralıyla yeniden hesaplanır.
  # AC3: Sepette kampanyalı ürün yoksa ve sepet tutarı 750,00 TL altına düşerse "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur.

  @AC1 @UC @P2 @pozitif @tp-2da75294-877e-589a-a2b7-9807571ff0f3
  Senaryo: Kaldır ile ürün satırı sepetten çıkar ve sepet sayacı azalır
    Diyelim ki sepet boş
    Ve test verileri:
      | ad                         | değer            | sınıf |
      | bayi kullanıcısı           | bayi1 / Demo123! |       |
      | sepette kalan ürün ve adet | P-002 × 2        |       |
      | kaldırılan ürün ve adet    | P-003 × 1        |       |
    Eğer ki giriş sayfasını aç ve bayi kullanıcısıyla giriş yaparsa (test verisi: bayi kullanıcısı)
    O zaman katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Limonata 330ml" (P-002) kartında adedi 2 yapıp "Sepete ekle" butonuna basarsa (test verisi: sepette kalan ürün ve adet)
    O zaman sepet sayacı 2 olur
    Eğer ki "Maden Suyu 200ml" (P-003) kartında adedi 1 yapıp "Sepete ekle" butonuna basarsa (test verisi: kaldırılan ürün ve adet)
    O zaman sepet sayacı 3 olur
    Eğer ki üst menüden sepete git ve P-003 satırındaki "Kaldır" butonuna basarsa (veri: "P-003")
    O zaman P-003 satırı sepetten kalkar ve sepet sayacı 2 olur
    Ve kaldırılan ürün sepetten çıkar ve sepet sayacı 2 olur
    # Temizlik: Sepeti boşalt

  @AC2 @EP @P1 @pozitif @tp-9b0ebe76-548b-5ee2-a3e8-e00119b7cbd1
  Senaryo: Kampanyalı satır kaldırılınca kampanya indirimi yeniden hesaplanır ve sıfırlanır
    Diyelim ki sepet boş
    Ve P-001 "6 al 1 bedava" kampanyasında
    Ve test verileri:
      | ad                                     | değer            | sınıf |
      | bayi kullanıcısı                       | bayi1 / Demo123! |       |
      | kaldırılan kampanyalı ürün ve adet     | P-001 × 6        | EP-V1 |
      | sepette kalan ürün ve adet (900,00 TL) | P-004 × 30       |       |
    Eğer ki giriş sayfasını aç ve bayi kullanıcısıyla giriş yaparsa (test verisi: bayi kullanıcısı)
    O zaman katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi 6 yapıp "Sepete ekle" butonuna basarsa (test verisi: kaldırılan kampanyalı ürün ve adet)
    O zaman sepet sayacı 6 olur
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 30 yapıp "Sepete ekle" butonuna basarsa (test verisi: sepette kalan ürün ve adet (900,00 TL))
    O zaman sepet sayacı 36 olur
    Eğer ki üst menüden sepete giderse
    O zaman P-001 satırında adet 6, bedava adet 1; ara toplam 1.050,00 TL, indirim 25,00 TL, toplam 1.025,00 TL
    Eğer ki P-001 satırındaki "Kaldır" butonuna basarsa (veri: "P-001")
    O zaman P-001 satırı sepetten kalkar ve sepet sayacı 30 olur; ara toplam 900,00 TL, indirim 0,00 TL, toplam 900,00 TL
    Ve kampanyalı satır kaldırılınca bedava adet kalmaz: indirim 0,00 TL, toplam 900,00 TL; minimum sipariş uyarısı gösterilmez
    # Temizlik: Sepeti boşalt

  @AC3 @DT @P1 @negatif @tp-751cc51d-72ed-5aba-a0b9-d730aae4bf74
  Senaryo: Kaldırma sonrası kampanyasız sepet minimum tutarın altına düşünce uyarı gösterilir ve onay pasif olur
    Diyelim ki sepet boş
    Ve sepette kampanyalı ürün yok
    Ve test verileri:
      | ad                                    | değer            | sınıf |
      | bayi kullanıcısı                      | bayi1 / Demo123! |       |
      | kaldırılan ürün ve adet               | P-004 × 25       |       |
      | sepette kalan ürün ve adet (15,00 TL) | P-002 × 1        | DT-R1 |
    Eğer ki giriş sayfasını aç ve bayi kullanıcısıyla giriş yaparsa (test verisi: bayi kullanıcısı)
    O zaman katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna basarsa (test verisi: kaldırılan ürün ve adet)
    O zaman sepet sayacı 25 olur
    Eğer ki "Limonata 330ml" (P-002) kartında adedi 1 yapıp "Sepete ekle" butonuna basarsa (test verisi: sepette kalan ürün ve adet (15,00 TL))
    O zaman sepet sayacı 26 olur
    Eğer ki üst menüden sepete git ve P-004 satırındaki "Kaldır" butonuna basarsa (veri: "P-004")
    O zaman toplam 15,00 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı görünür ve "Siparişi onayla" butonu pasiftir
    Ve "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur
    # Temizlik: Sepeti boşalt

  @AC3 @BVA @DT @P2 @sınır-değer @tp-163ecc34-7109-53fa-997a-1e4c60a4054b
  Senaryo: Kaldırma sonrası toplam minimum tutara eşit kalınca uyarı gösterilmez ve onay aktif olur
    Diyelim ki sepet boş
    Ve sepette kampanyalı ürün yok
    Ve test verileri:
      | ad                                     | değer            | sınıf |
      | bayi kullanıcısı                       | bayi1 / Demo123! |       |
      | sepette kalan ürün ve adet (750,00 TL) | P-004 × 25       | BV-1  |
      | kaldırılan ürün ve adet                | P-003 × 1        |       |
    Eğer ki giriş sayfasını aç ve bayi kullanıcısıyla giriş yaparsa (test verisi: bayi kullanıcısı)
    O zaman katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna basarsa (test verisi: sepette kalan ürün ve adet (750,00 TL))
    O zaman sepet sayacı 25 olur
    Eğer ki "Maden Suyu 200ml" (P-003) kartında adedi 1 yapıp "Sepete ekle" butonuna basarsa (test verisi: kaldırılan ürün ve adet)
    O zaman sepet sayacı 26 olur
    Eğer ki üst menüden sepete git ve P-003 satırındaki "Kaldır" butonuna basarsa (veri: "P-003")
    O zaman toplam 750,00 TL; minimum sipariş uyarısı görünmez ve "Siparişi onayla" butonu aktiftir
    Ve toplam 750,00 TL olduğunda uyarı gösterilmez ve sipariş onaylanabilir
    # Temizlik: Sepeti boşalt

  @AC3 @DT @P2 @sınır-değer @tp-4ebfc3a6-d75f-5106-bd36-e987bd0e41b3
  Senaryo: Kaldırma sonrası kampanyalı sepette minimum tutar uyarısı gösterilmez
    Diyelim ki sepet boş
    Ve P-001 "6 al 1 bedava" kampanyasında
    Ve test verileri:
      | ad                                                | değer            | sınıf |
      | bayi kullanıcısı                                  | bayi1 / Demo123! |       |
      | sepette kalan kampanyalı ürün ve adet (125,00 TL) | P-001 × 6        | DT-R3 |
      | kaldırılan ürün ve adet                           | P-004 × 25       |       |
    Eğer ki giriş sayfasını aç ve bayi kullanıcısıyla giriş yaparsa (test verisi: bayi kullanıcısı)
    O zaman katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Portakal Gazozu 1L" (P-001) kartında adedi 6 yapıp "Sepete ekle" butonuna basarsa (test verisi: sepette kalan kampanyalı ürün ve adet (125,00 TL))
    O zaman sepet sayacı 6 olur
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna basarsa (test verisi: kaldırılan ürün ve adet)
    O zaman sepet sayacı 31 olur
    Eğer ki üst menüden sepete git ve P-004 satırındaki "Kaldır" butonuna basarsa (veri: "P-004")
    O zaman toplam 125,00 TL; minimum sipariş uyarısı görünmez ve "Siparişi onayla" butonu aktiftir
    Ve kampanyalı sepette toplam 125,00 TL olsa da minimum sipariş uyarısı gösterilmez ve sipariş onaylanabilir
    # Temizlik: Sepeti boşalt

  @AC3 @BVA @P2 @sınır-değer @tp-bab57e15-539e-5c1e-a893-f3b3ade3cd13
  Senaryo: Kaldırma sonrası kampanyasız sepet 749,00 TL'ye düşünce minimum tutar uyarısı gösterilir ve onay pasif olur
    Diyelim ki Sepet boş
    Ve Sepette kampanyalı ürün yok
    Ve test verileri:
      | ad                                                          | değer                   | sınıf |
      | bayi kullanıcısı                                            | bayi1 / Demo123!        |       |
      | kalan kampanyasız ürünler (749,00 TL; en yakın kurulabilen) | P-002 × 43 + P-003 × 13 | BV-2  |
      | kaldırılan ürün ve adet                                     | P-004 × 1               |       |
    Eğer ki Giriş sayfasını aç ve bayi kullanıcısıyla giriş yap, veri: "bayi1 / Demo123!"
    O zaman Katalog sayfası "Merkez Bayi" oturumuyla görüntülenir
    Eğer ki "Limonata 330ml" (P-002) kartında adedi 43 yapıp "Sepete ekle" butonuna bas, veri: "P-002 × 43"
    O zaman Sepet sayacı 43 olur
    Eğer ki "Maden Suyu 200ml" (P-003) kartında adedi 13 yapıp "Sepete ekle" butonuna bas, veri: "P-003 × 13"
    O zaman Sepet sayacı 56 olur
    Eğer ki "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 1 yapıp "Sepete ekle" butonuna bas, veri: "P-004 × 1"
    O zaman Sepet sayacı 57 olur
    Eğer ki Üst menüden sepete git ve P-004 satırındaki "Kaldır" butonuna bas, veri: "P-004"
    O zaman Sepet tutarı minimum sipariş tutarının (750,00 TL) hemen altındadır; "Minimum sipariş tutarı 750,00 TL" uyarısı görünür ve "Siparişi onayla" butonu pasiftir
    Ve Kaldırma sonrası sepet tutarı minimum sipariş tutarının (750,00 TL) hemen altına düşer; "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur
    # Temizlik: Sepeti boşalt

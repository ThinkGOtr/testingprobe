// Serbest metin demo gereksinimi ("Sepetten ürün çıkarma"). Metin, REPLAY golden'ının girdi
// beyanıyla (rules/replay/*/golden/SERBEST.json `input_match`, rules/replay/README.md) birebir
// aynıdır: tek kelime farkı REPLAY-MISS'e düşürür. lib.test.ts bu sabitleri golden kaynağıyla
// (src/api/mock/golden/kaynaklar.json → serbest_girdi) karşılaştırır.

export const ORNEK_SERBEST_GEREKSINIM = {
  baslik: "Sepetten ürün çıkarma",
  aciklama: "Bayi sepetteki bir ürün satırını kaldırabilmeli; toplamlar ve kampanya indirimi yeniden hesaplanmalıdır.",
  /** "ACn: " öneki olmadan (core önekisiz AC'leri sırayla numaralar). */
  ac: [
    'Satırdaki "Kaldır" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır.',
    "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır.",
    "Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir.",
  ],
} as const;

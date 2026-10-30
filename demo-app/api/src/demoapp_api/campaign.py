"""Kampanya hesabı: "6 al 1 bedava".

Kampanyalı bir sepet satırında bedava verilecek adet bu dosyadaki tek fonksiyonda hesaplanır.
Sepet ve sipariş tutarları (`pricing.py`) bu fonksiyonu kullanır; kampanyanın hangi ürünlerde
geçerli olduğu `kampanya` tablosundan okunur; kampanya adı ürün kartında ve sepet satırında
gösterilir.

Demo kırılması ("kırarak doğrula"): indirim hiç uygulanmaz (bedava = 0). İki yolla açılır:
- `bozuk=True`: bayi kapsamlı çalışma zamanı anahtarı (`POST /test/break`, `test_kirilma`
  tablosu). test-runner koşu başına bunu kullanır; diğer bayiler ve servisler etkilenmez.
- `BREAK_CAMPAIGN=1` ortam değişkeni: tüm süreç için (geriye dönük; yalnızca yerel deneme).
"""

import os

KAMPANYA_ADI = "6 al 1 bedava"


def bedava_adet(adet: int, bozuk: bool = False) -> int:
    """Kampanyalı bir sepet satırında bedava verilecek adet."""
    if bozuk or os.environ.get("BREAK_CAMPAIGN") == "1":
        return 0
    return adet // 6

"""Asistan araçları (AI-ASISTAN-PLANI §5).

Yeni araçlar ham metin döndürür; sır temizleme (`scrub_secret_patterns`), maskeleme, kanıt havuzu
ve `<untrusted>` sarma ortak sarmalayıcıdadır (`tools.base`, §5.0). Rol kısıtı araç uygulamasında,
iş yükündeki kullanıcıyla (asla argümandan).

- `product` — `product_search`, `product_read`: core-worker'a salt okunur bağlanan ürün bilgi
  paketi (`/opt/tp-bilgi`, MANIFEST birebir).
"""

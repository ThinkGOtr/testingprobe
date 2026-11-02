# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: cart.spec.ts >> Sepet (TPD-1) >> AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar
- Location: tests/cart.spec.ts:16:3

# Error details

```
TimeoutError: locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for getByTestId('product-card-P-002').getByTestId('add-to-cart')

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - link "İçeriğe geç" [ref=e4] [cursor=pointer]:
    - /url: "#icerik"
  - banner [ref=e5]:
    - generic [ref=e6]:
      - link "Bayi Sipariş Portalı" [ref=e7] [cursor=pointer]:
        - /url: /katalog
      - navigation "Ana menü" [ref=e13]:
        - link "Katalog" [ref=e14] [cursor=pointer]:
          - /url: /katalog
        - link "Sepet 0 ürün" [ref=e15] [cursor=pointer]:
          - /url: /sepet
          - text: Sepet
          - generic [ref=e16]: "0"
          - generic [ref=e17]: ürün
        - link "Siparişlerim" [ref=e18] [cursor=pointer]:
          - /url: /siparisler
      - generic [ref=e19]:
        - generic [ref=e20]: Merkez Bayi
        - button "Çıkış yap" [ref=e21] [cursor=pointer]
  - main [ref=e22]:
    - generic [ref=e23]:
      - heading "Ürün kataloğu" [level=1] [ref=e24]
      - paragraph [ref=e25]: Adet seçip ürünleri sepetinize ekleyin. Fiyatlara KDV dahildir.
    - generic [ref=e26]:
      - article [ref=e27]:
        - generic [ref=e29]: P
        - generic [ref=e30]:
          - paragraph [ref=e31]: P-001
          - heading "Portakal Gazozu 1L" [level=2] [ref=e32]
          - paragraph [ref=e33]: "Kampanya: 6 al 1 bedava"
          - paragraph [ref=e34]: 25,00 TL
          - generic [ref=e35]:
            - generic [ref=e36]:
              - generic [ref=e37]: Adet
              - spinbutton "Adet" [ref=e38]: "1"
            - button "Sepete ekle" [ref=e39] [cursor=pointer]
          - status [ref=e40]
      - article [ref=e41]:
        - generic [ref=e43]: L
        - generic [ref=e44]:
          - paragraph [ref=e45]: P-002
          - heading "Limonata 330ml" [level=2] [ref=e46]
          - paragraph [ref=e47]: 15,00 TL
          - generic [ref=e48]:
            - generic [ref=e49]:
              - generic [ref=e50]: Adet
              - spinbutton "Adet" [active] [ref=e51]: "1"
            - button "Sepete ekle" [ref=e52] [cursor=pointer]
          - status [ref=e53]
      - article [ref=e54]:
        - generic [ref=e56]: M
        - generic [ref=e57]:
          - paragraph [ref=e58]: P-003
          - heading "Maden Suyu 200ml" [level=2] [ref=e59]
          - paragraph [ref=e60]: 8,00 TL
          - generic [ref=e61]:
            - generic [ref=e62]:
              - generic [ref=e63]: Adet
              - spinbutton "Adet" [ref=e64]: "1"
```

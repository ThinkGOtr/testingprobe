# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: locators.spec.ts >> locators.ts rol/ad sözleşmesi >> menü, katalog, sepet ve sipariş sayfaları
- Location: tests/locators.spec.ts:108:3

# Error details

```
Error: addToCart: testId 'add-to-cart' sayfada bulunamadı

expect(locator).toBeAttached() failed

Locator: getByTestId('product-card-P-001').getByTestId('add-to-cart').first()
Expected: attached
Timeout: 5000ms
Error: element(s) not found

Call log:
  - addToCart: testId 'add-to-cart' sayfada bulunamadı getByTestId('product-card-P-001').getByTestId('add-to-cart').first() with timeout 5000ms
  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart').first()

```

```yaml
- link "İçeriğe geç":
  - /url: "#icerik"
- banner:
  - link "Bayi Sipariş Portalı":
    - /url: /katalog
  - navigation "Ana menü":
    - link "Katalog":
      - /url: /katalog
    - link "Sepet 0 ürün":
      - /url: /sepet
    - link "Siparişlerim":
      - /url: /siparisler
  - text: Sahil Bayi
  - button "Çıkış yap"
- main:
  - heading "Ürün kataloğu" [level=1]
  - paragraph: Adet seçip ürünleri sepetinize ekleyin. Fiyatlara KDV dahildir.
  - article "Portakal Gazozu 1L":
    - paragraph: P-001
    - heading "Portakal Gazozu 1L" [level=2]
    - paragraph: "Kampanya: 6 al 1 bedava"
    - paragraph: 25,00 TL
    - text: Adet
    - spinbutton "Adet": "1"
    - button "Sepete ekle"
    - status
  - article "Limonata 330ml":
    - paragraph: P-002
    - heading "Limonata 330ml" [level=2]
    - paragraph: 15,00 TL
    - text: Adet
    - spinbutton "Adet": "1"
    - button "Sepete ekle"
    - status
  - article "Maden Suyu 200ml":
    - paragraph: P-003
    - heading "Maden Suyu 200ml" [level=2]
    - paragraph: 8,00 TL
    - text: Adet
    - spinbutton "Adet": "1"
    - button "Sepete ekle"
    - status
  - article "Şeftalili Soğuk Çay 1L":
    - paragraph: P-004
    - heading "Şeftalili Soğuk Çay 1L" [level=2]
    - paragraph: 30,00 TL
    - text: Adet
    - spinbutton "Adet": "1"
    - button "Sepete ekle"
    - status
- contentinfo: Bayi Sipariş Portalı · Örnek uygulama · Tüm veriler sentetiktir
```

# Test source

```ts
  1   | // locators.ts sözleşmesi: role + name meta verisi uygulamayla tutarlı olmalı.
  2   | // Locator onarımı (TEKNIK-TASARIM §8.7) kırılan testId'nin adayını getByRole(role, { name }) ile
  3   | // bulur; bu test, adı olan her locator'ın rol + adla bulunan elemanlarının o testId'yi
  4   | // (önek locator'larda o önekle başlayan testId'yi) taşıdığını doğrular. Rol + ad sayfada birden
  5   | // fazla elemana uyuyorsa locator `within` (kapsayıcı testId öneki) taşımalıdır ve her kapsayıcının
  6   | // içinde rol + ad TAM OLARAK bir elemana uymalıdır; onarım adayı o kapsayıcıda aranır.
  7   | import type { Locator, Page, TestInfo } from "@playwright/test";
  8   | import { writeFileSync } from "n
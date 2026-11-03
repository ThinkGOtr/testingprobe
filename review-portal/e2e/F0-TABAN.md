# F0 tabanı — axe ölçümleri (tasarım planı §6.2 F0, §8)

Ölçüm: 2026-11-03, dal `ui-test` (taban `443a668`), `vite build --mode mock` + `vite preview`, Playwright 1.64.1
Chromium, `@axe-core/playwright` 4.14.0. Tema `localStorage` (`tp-tema-v=2`, `tp-tema=acik|koyu|sistem`) ve
`emulateMedia` ile aynı yöne ayarlandı (sistem turu: OS açık, yalnız 1440 px). Her sayfada axe öncesi
`.kabuk::before,.giris-sayfa::before,.giris-sayfa::after{display:none}` (bugün bu pseudo'lar yok; etkisiz).
`/kosular/run-107`'de ilk test satırı açılıp `Test ayrıntısı: …` bölgesi beklendi; `/demo` sunucu rolüyle,
"Buton kimliğini değiştir" tıklanıp "Buton kimliği değiştirme onayı" grubu açıkken ölçüldü.

## Diğer tabanlar

| Kapı | Sonuç |
|---|---|
| Birim (`npx vitest run`) | 34 dosya · **511 geçen + 1 atlanan** (512) |
| Tip (`npm run typecheck`) | 0 hata |
| Duman e2e (`duman.spec.ts`, 19 test) | 17 geçen, 2 kırık (dev'de zaten kırık, tasarımla ilgisiz): "insan kapıları uçtan uca" (Jira'ya yazıldı sayımı), "Faz 5: analist TPD-1'e ölçülmüş baz" (ölçüm · analist) |

## `wcag21aa` + `wcag22aa` deneme koşusu

Etiketler `wcag2a, wcag2aa, wcag21aa, wcag22aa`; aşağıdaki 19 sayfa × (koyu 1440/390, açık 1440/390,
sistem 1440) = 95 ölçüm. **İhlal: 0** (hiçbir etki düzeyinde). Plandaki örnek "bildirim kapat 16 px"
(`target-size`) bu turda görünmez: bildirim yalnız bir işlemden sonra açılır, axe turundaki sayfalarda
bildirim yok. Bu yüzden `duman.spec.ts` axe döngüsü dört etiketle koşar (§8: "ihlaller düzeltildikten
sonra eklenir" — düzeltilecek ihlal yok).

## `color-contrast` incomplete düğüm sayısı (sayısal kapı: aşılamaz)

Ek B2 fikstürü (run-107 ayrıntısı, run-108 Sauce çipi) **dahil**. Fikstür öncesi değerler: `/kosular/run-107`
koyu 9/6, açık 8/5, sistem 9 (fark tamamen açılan ayrıntı panelindeki `aria-hidden` ✓/✗ gliflerinden ve
yeni metinlerden); `/kosular/run-108` fikstürden önce ölçülmedi.

| Sayfa | koyu 1440 | koyu 390 | açık 1440 | açık 390 | sistem 1440 |
|---|---|---|---|---|---|
| `/giris` | 0 | 0 | 0 | 0 | 0 |
| `/gereksinimler/req-tpd-1` | 13 | 11 | 12 | 10 | 13 |
| `/gereksinimler/req-tpd-1/caseler` | 4 | 2 | 3 | 1 | 4 |
| `/kod/scr-2` | 13 | 31 | 12 | 30 | 13 |
| `/denetim` | 3 | 73 | 2 | 72 | 3 |
| `/kontrol-kulesi` | 5 | 22 | 4 | 21 | 5 |
| `/gereksinimler/req-ft-1` | 7 | 5 | 6 | 4 | 7 |
| `/gereksinimler/req-tpd-1/yayin` | 4 | 24 | 3 | 23 | 4 |
| `/claude-code` | 3 | 2 | 2 | 1 | 3 |
| `/hatalar/fail-2` | 15 | 13 | 14 | 12 | 15 |
| `/bug-taslaklari/bug-4` | 5 | 2 | 4 | 1 | 5 |
| `/yol-haritasi` | 12 | 10 | 11 | 9 | 12 |
| `/gereksinimler` | 3 | 2 | 2 | 1 | 3 |
| `/kod` | 3 | 17 | 2 | 16 | 3 |
| `/kosular` | 7 | 63 | 6 | 62 | 7 |
| `/kosular/run-107` | 23 | 20 | 22 | 19 | 23 |
| `/kosular/run-108` | 7 | 5 | 6 | 4 | 7 |
| `/bug-taslaklari` | 3 | 17 | 2 | 16 | 3 |
| `/demo` | 4 | 2 | 3 | 1 | 4 |

Notlar:
- Koyu ve sistem turunda her Kabuk sayfasında +1: tema düğmesi (`.dugme-hayalet`, ☾/◐ glifi).
- Sık görülen incomplete hedefleri: `h1` ve ilk `p` (ÖRNEK VERİ bandı / yapışkan üst çubukla örtüşme),
  `aria-hidden` glifler (▸, ✓, ✗, ☰), `#kosular-gece-aciklama`/`#kosular-deploy-aciklama` (negatif üst marj),
  390 px'te yatay kayan tablolardaki hücreler (`/denetim`, `/kosular`: tablo sarıcı dışına taşan satırlar).
- Bu sayılar `duman.spec.ts` içinde `F0_INCOMPLETE` sabitidir; F2 sonrası azalırsa taban düşürülür,
  artış PR'ı durdurur (elle inceleme §3.3).

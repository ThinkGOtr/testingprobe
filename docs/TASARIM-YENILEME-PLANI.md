# İnceleme Portalı — Tasarım Yenileme Planı

| | |
|---|---|
| Sürüm | **v5 (uygulamaya hazır)** — 3 inceleme turu + plan sonrası kod değişikliği taraması (Ek A, Ek B); 2. ve 3. turda engelleyici yok |
| Tarih | 2026-11-03 |
| Kapsam | `review-portal/` (React + Vite, nginx). **Görsel dil ve ekran düzeni.** |
| Kapsam dışı | `demo-app/` (test edilen uygulama; Script detayındaki önizlemesi dahil kendi görünümünde kalır), `sims/jira-sim/` (Jira'yı taklit eder), core/API, iş kuralları, arayüz metinleri |
| Referans | Agent Probe web sitesi (`agent-probe/website/style.css`), dashboard (`agent-probe/dashboard/static/index.html`, `login.html`), rapor ekranı (`report.html`, açık yüz) |
| Durum | Analiz ve hazırlık. Bu belgede kod değişikliği yoktur. |

---

## 0. Özet

Portal işlevsel olarak olgun (≈500 birim testi, iki temada axe denetimi, rol bazlı akış) ama görsel dili
**jenerik bir yönetim paneli**: gri zemin, beyaz kartlar, tek lacivert vurgu, her hücrede farklı renkte çip,
zayıf tipografik hiyerarşi, çok uzun sayfalar. Agent Probe ailesinin kimliği — koyu lacivert zemin,
indigo/mor vurgu, Inter + JetBrains Mono, ince kenarlı yüzeyler, hap rozetler, dashboard üst çubuğunun
gradyan çizgisi, statik ortam ışıması — yok. Sunumlar Agent Probe renklerinde, ürün ekranı değil.

**Asıl sıçrama hex değerleri değil**: katman ayrışması, tipografi, renk disiplini (mor yalnızca AI) ve
yoğunluk. Yalnızca paleti değiştirip işi bitmiş saymak bu planın amacını kaçırır.

Mimari buna uygun: TSX dosyalarında tek bir sabit renk yok; görünüm `src/styles.css`'teki CSS
değişkenlerinden ve sınıflardan geliyor.

**Teslim stratejisi:** Demodan önce yalnızca **Minimum Değerli Teslim (MVT, §6.1)** — CSS ağırlıklı,
DOM/metin/rol değişmeyen kısım. Ekran düzeni değişiklikleri (KPI şeridi, bölüm gezgini vb.) demodan sonra.

**Temel güvenlik kuralı (tüm fazlar):** Hiçbir sınıf adı, `data-testid`, ARIA rolü/adı, başlık seviyesi,
görünür metin (glifler dahil), rota, bağlantı silinmez, yeniden adlandırılmaz, çoğaltılmaz. Ekleme
serbesttir ama §9'daki test-etki taramasından geçer.

---

## 1. Mevcut durum analizi

### 1.1 Teknik tablo

| Konu | Durum (kanıt) | Yenilemeye etkisi |
|---|---|---|
| Stil mimarisi | Tek dosya `src/styles.css` (2420 satır; HEAD `5a791de`'de **2520** — Ek B; aşağıdaki satır numaraları 2420'lik tabana göredir, ~244 kök sınıf). Bileşenler ekran bölümlerinde bağlamlı olarak yeniden tanımlanıyor (`.kart` 551 / `.kule-izgara > .kart` 2019; `.cip` 696 / `.karar-ozet .cip` 1391 / `.hazirlik-tablo td .cip` 2305; `.uyari-kutusu` 743 / `.yerel-kontrol .uyari-kutusu` 2164; `.dugme-ek` 2146; `.rozet-degerlendirme` 1885) | Her bileşen değişikliğinde **sonraki tekrar tanımlar da** güncellenir (§6.3) |
| Stil dosyasını okuyan test | `inceleme.test.tsx:463-467` `styles.css`'i metin olarak okuyup `.tablo-yigin` 640 px kuralını arıyor | Dosya bölünmez (§6.3, karar K1) |
| TSX'te sabit renk | Yok. Satır içi stil 6 yerde (konum/genişlik) | Görünüm CSS'ten yönetilir |
| Tema | `tp-tema`: `temaOku()` (`Kabuk.tsx:52-60`) yalnız `acik`/`koyu` tanır, aksi `sistem`; `useTema` (62-76) **her açılışta** değeri yazar (`setItem` 68-72) → daha önce açılmış her tarayıcıda `tp-tema=sistem` kayıtlı | Göç gerekir (§3.1) |
| Font | `--font: "Inter", …` ama Inter **yüklenmiyor** | Self-host |
| CSP (`nginx.conf:38,148`) | `default-src 'self'` (font-src yok) · `img-src 'self' data:` · satır içi betik yasak | Google Fonts yok; **`data:` font da yok** (Vite 4 KB altı dosyayı gömer — §6.2) |
| Docker | Yalnız `index.html`, `src/` vb. kopyalanır; `public/` yok | Statik varlık `src/`'den import edilir veya `data:` URI |
| Birim test | 2026-11-03 ölçümleri 496 → 497 → 498 → **512** (HEAD `5a791de`, 34 dosya; `kosuSonuclari.test.tsx` eklendi; paralel geliştirme sürüyor); `tsc` temiz | Kapı: **F0'da ölçülen taban sayısından az değil** |
| E2E duman | Örnek veri, `vite preview` (nginx/CSP yok). axe döngüsü `["light","dark"]` için `emulateMedia` (`duman.spec.ts:334-361`), 1440 + 390 px, serious/critical = 0 | Statik koyu varsayılan bu döngüyü **sessizce tek temaya düşürür** → yeniden yazılır (§8) |
| Ölçüm testleri | Yatay taşma (`:252-258, 296-302, 313-320`), "Adım" hücresi >250 px (`:326-329`), akış adı çakışması 375 px (`:382-394`) | Font/boşluk değişimine duyarlı; `document.fonts.ready` beklenir |
| Prova | `rehearsal/ui`: `npm run birim` yalnız yardımcı fonksiyon; arayüz provası `npm run tur` / `npm run canli` | Kapı: `tur` (§8) |
| Demo senaryosu | `CANLI-DEMO-SENARYOSU.md` konum/renk tarifleri (§1.3) | Korunur |

### 1.2 Görsel sorunlar (`e2e/ekranlar/`)

| # | Sorun | Nerede |
|---|---|---|
| G1 | Marka kimliği yok: gri-beyaz admin şablonu, lacivert `#1f4fbf` | Tümü |
| G2 | Renk gürültüsü: tetik, kaynak, tür, durum hepsi farklı renkte çip; mor hem AI hem AI-olmayan şeyler için | Koşular, Kule, Gereksinimler, Case, Bulgu |
| G3 | Pasif birincil düğme soluk mavi (`opacity:.5`) — "bozuk" görünüyor, neden yalnız `title`'da | Koşular, Triage, Script, Gereksinim |
| G4 | ÖRNEK VERİ bandı (yalnız örnek veri derlemesinde) sayfanın en baskın öğesi | Tümü (mock) |
| G5 | Zayıf tipografik hiyerarşi (h1 ~22 px, gövde 15 px, KPI ile açıklama aynı ağırlık) | Tümü |
| G6 | Dengesiz kart yükseklikleri, büyük boşluklar | Kule, Triage |
| G7 | Değer olmayan metin ("ölçülmüş baz yok") dev italik KPI gibi | Kule, Case review |
| G8 | Çok uzun sayfalar, yön bulma yok (Gereksinim 3900 px, Case review 4900 px) | Gereksinim, Case review |
| G9 | 14 adım göstergesi küçük; yol haritasında daire rengi *durumu* gösteriyor, *türü* (AI/insan) değil — demo anlatısı "mor = AI, yeşil = insan" ekranda yok | Gereksinim, Yol haritası |
| G10 | Giriş ekranı jenerik | `/giris` |
| G11 | Kabuktaki dekoratif glifler (☰ ◐ ☾ ☀ ↗) farklı fontlardan, boyları tutarsız | Üst çubuk, dış bağlantılar |
| G12 | İçerik `max-width:1280px` ve **sola yaslı**; 1920 px'te sağda ölü alan | Tümü |
| G13 | Case review'da karar bekleyen 4 kart, karara bağlanmış 6 kartla aynı ağırlıkta | Case review |
| G14 | Case başlığında 5–6 hap yan yana (durum, tür, risk, AC, kanal, REPLAY) | Case review |
| G15 | Çözülmüş "Engelleyici" bulgu hâlâ kalın kırmızı kenarla bağırıyor | Gereksinim |
| G16 | Boş durumlar tutarsız ("—", italik "case yok", "ölçülmedi"); 2 veri noktalı grafik koca kart | Kule |
| G17 | Yol haritasında "Sıradaki" düz metin, aynı anda 3 adım "sürüyor" | Yol haritası |
| G18 | Mobilde kesilen tabloların kaydırılabildiğine işaret yok | Mobil |
| G19 | Eylem sütunlarında altı çizili mavi bağlantılar | Yol haritası, tablolar |

### 1.3 Demo senaryosu bağımlılıkları (korunur)

**Satır numaraları kayar** (senaryo sürekli güncelleniyor; 2026-11-03 12:53'te 313. satırdan sonra 5 satır
eklendi). Uygulamada her atıf alıntı metniyle `grep -n` ile yeniden bulunur; aşağıdaki numaralar
2026-11-03 15:10 itibarıyladır (HEAD `5a791de`, 639 satır; 13:00'teki numaralar 35–75 satır kaydı — senaryo
gün içinde sürekli düzenleniyor, bu numaralara değil alıntıya güvenin).

`CANLI-DEMO-SENARYOSU.md` satırları: sağ üst **Canlı olaylar** göstergesi yeşil (125), kırmızı = sorun (610);
"Mor adımlar AI taslağı, yeşil adımlar insan kapısı" (168); REPLAY rozeti her AI çıktısında (170); gri
**"Kod"** kutusu (204); kartın sağ üstünde yeşil **"✓ kanıt doğrulandı"** (207); **"✓ Doküman son hâl · PO
teyidi bekliyor"** kartın sağ üstünde (222 — çip artık `bilgi`/indigo, §5); **PO onaylı** rozeti (238); sağ üst
**Case üret** ve **Case review** düğmeleri, Case review → **Yayın önizleme** (250-265); 4\. adımın **kesikli
halkası = AI adımı** (254); "✓ İnsan kapısı geçildi" (255); **Defect adayı** durumu (307); sağdaki **Kırarak
doğrula** kartı, yeşil → kırmızı → yeşil (323-325) ve zayıf testte **⚠ "Yeşil · beklenmeyen sonuç"** + **sarı
kutu** "Zayıf test" (327-329); merge kapısı altındaki sarı kabul kutusu (354-355); "Merge kapısı açık ✓" (351);
**"⚠️ Sauce koşmadı"** uyarısı (398-400, §4.6 `SauceCipi`); Koşu detayı raporları (Adım 10, 419); Kule
"Beklenen boşluklar" (428-432); Koşular'da **"Kasıtlı kırma koşuları"** kutusu ve **"Başarısızlıklar ve triage"**
kartı (L2, 485-487); "tamamı yeşil 36/36" (L4, 513); mükerrer **"yüksek olasılık"** (534); REPLAY-MISS amber
(612); Denetim verify yeşil (579); sunum makinesi **%125 zoom** (114).
Bulma: `grep -n "<alıntı>" docs/CANLI-DEMO-SENARYOSU.md`.

---

## 2. Hedef görsel dil — "Agent Probe çizgisi"

| Yüz | Kaynak | Portalda |
|---|---|---|
| **Koyu** (marka) | `website/style.css`, `dashboard/static/index.html`, `login.html` | **Varsayılan tema** |
| **Açık** (rapor) | `dashboard/static/report.html` | İkinci tema — uzun okuma ekranlarında birinci sınıf; F2'de her ekran iki temada gözden geçirilir |

**Alınanlar:** palet; Inter + JetBrains Mono; 12/20 px yarıçap; ince kenarlı yüzeyler; hap rozetler (büyük
harf, harf aralığı); `section-badge` (geri bağlantısı ve ÖRNEK VERİ rozeti); tablo başlığı (büyük harf,
`surface2`); sol kenar şeritli sonuç kartı (`.test-result`); istatistik şeridi (`.hero-stats` + `.stat-divider`,
demo sonrası); **mock-panel başlık şeridi** (tablo/kod kartlarında); **dashboard üst çubuğunun 2 px
indigo→mor gradyan çizgisi** ve parlayan logo; **statik ortam ışıması** (sol üst indigo, sağ alt mor);
giriş ekranında ızgara + ışıma; birincil düğmenin indigo ışıması; `::selection` ve ince kaydırma çubuğu.

**Alınmayanlar:** animasyonlu blob'lar ve panel salınımı; 900 ağırlıklı hero başlıkları; emoji ikonlar;
pencere noktaları; gradyan metnin marka kelimesi ve giriş başlığı dışında kullanımı; AA'yı geçmeyen site
değerleri (`#6366f1` üstünde beyaz 4,47; `#64748b` koyu yüzeyde 3,9).

**Renk disiplini (karar K4):** Indigo = marka ve etkileşim (bağlantı, birincil düğme, aktif menü, şimdiki
adım). **Mor (`--vurgu`) = yalnız AI** (AI adımı, AI çıktısı, REPLAY). **Yeşil = insan kapısı ve başarı.**
Amber = uyarı/örnek veri. Kırmızı = hata/engelleyici. Nötr = kategorik bilgi (tetik, kaynak, tür, kanal).

**Bağımsızlık kuralı:** Testing Probe, Agent Probe'dan bağımsızdır. Kod, CSS, font dosyası veya paket
**paylaşılmaz**; değerler bu belgede kopyalanır ve portalın kendi `styles.css`'inde tanımlanır.

---

## 3. Tasarım belirteçleri

Mevcut değişken **adları korunur**; değerleri değişir; yeni değişkenler eklenir. Temaya bağlı **her** değer
token'dır — bileşen CSS'inde sabit `rgb()`/hex ve `[data-theme]` seçicisi kullanılmaz.

### 3.1 Tema stratejisi

- `:root` (niteliksiz) = **koyu** değerler + `color-scheme: dark`.
- `:root[data-theme="light"]` = açık değerler + `color-scheme: light`.
- `@media (prefers-color-scheme: light) { :root:not([data-theme]) { …açık… } }` = "sistem" kipi.
- Mevcut iki koyu blok (`@media dark :root:not([data-theme="light"])` ve `:root[data-theme="dark"]`)
  silinir; `data-theme="dark"` niteliksiz kökle aynı değerleri alır.
- Yeni `src/lib/tema.ts`: `temaOku()` ve `temaUygula(tema)` (try/catch ile; depolama yoksa koyu).
  - Tanınan değerler `sistem`/`acik`/`koyu`; diğer her şey → `koyu`.
  - **Göç:** eski sürüm `sistem`'i kendiliğinden yazıyordu. `tp-tema-v=2` işareti yoksa göç adımı
    `localStorage.removeItem("tp-tema")` yapar ve `tp-tema-v=2` yazar (eski değer **silinir**; yalnız yok
    saymak ikinci açılışta `sistem`'i geri getirir).
  - `useTema` efekti yalnız `temaUygula` çağırır; `localStorage.setItem("tp-tema", …)` **yalnız `degistir`
    içinde** (bugün `Kabuk.tsx:68-72` her açılışta yazıyor — bu yazma kaldırılır).
  - `main.tsx` render'dan önce `temaUygula(temaOku())`; `useTema` aynı fonksiyonları kullanır. Böylece
    `Kabuk` dışındaki `/giris` de doğru temada açılır.
  - Birim testler: depolama boş → koyu; işaretsiz `tp-tema=sistem` ile **iki ardışık** `temaOku()` → ikisi de
    koyu; işaretli `sistem` korunur; döngü sırası; depolama istisnasında koyu; mount yazma yapmaz.
- `index.html`: `<html lang="tr" data-theme="dark">` (ilk boyama koyu).
  **Bilinen kısıt:** açık tema seçmiş kullanıcıda modül betiği çalışana dek (boş `#root`) zemin bir an koyu
  görünebilir. Satır içi betik CSP'ye takılır; klasik `/tema.js` için Dockerfile'a `public/` kopyalamak
  gerekir — maliyete değmez, kabul edildi.
- Döngü ve etiketler aynı: `koyu → acik → sistem → koyu`, "Tema: koyu" vb.
- **Demo:** tema projektör provasında seçilir, 5 tarayıcı profilinin her birinde elle ayarlanır; yedek video
  aynı temayla kaydedilir (§6.4).

### 3.2 Renk değerleri

| Token | Koyu (varsayılan) | Açık | Not |
|---|---|---|---|
| `--bg` | `#06060f` | `#f6f7fb` | site `#04040c` bir ton açıldı |
| `--surface` | `#0e0e1c` | `#ffffff` | katman ayrışması (tasarımcı) |
| `--surface-2` | `#15152a` | `#f2f4f8` | |
| `--surface-3` | `#1c1c33` | `#e9ecf3` | |
| `--border` | `#2e2e58` | `#e4e7ed` | **kart kenarı**: bg'ye 1,58, surface'e 1,50 |
| `--border-soft` *(yeni)* | `#25254a` | `#eceef3` | kart içi ayraç, tablo satırı (projektörde kaybolmasın diye `#1e1e35`'ten açıldı) |
| `--border-strong` | `#3a3a66` | `#d1d5de` | ikincil düğme kenarı |
| `--border-input` *(yeni)* | `#6b6e94` | `#7a8093` | ≥3:1 tüm yüzeylerde (koyu 3,39–4,12; açık 3,33–3,94) |
| `--text` | `#f0f0ff` | `#0f1117` | |
| `--text-2` | `#94a3b8` | `#4b5263` | koyu 6,5–7,9 |
| `--muted` | `#8590a6` | `#5f6678` | koyu 5,2–6,3. **Tonlu (`*-bg`) zeminde kullanılmaz** → `--text-2` |
| `--accent` | `#818cf8` | `#4f46e5` | **yalnız metin ve kenar** (koyu 5,6–6,8) |
| `--accent-hover` | `#a5b4fc` | `#4338ca` | |
| `--accent-soft` | `rgb(99 102 241 / .12)` | `#eef2ff` | aktif menü zemini |
| `--accent-solid` *(yeni)* | `#4f46e5` | `#4f46e5` | **dolu zeminler**; beyazla 6,29 |
| `--accent-solid-hover` *(yeni)* | `#5b54e8` | `#4338ca` | beyazla 5,41 / 7,9 |
| `--accent-text` | `#ffffff` | `#ffffff` | yalnız `--accent-solid` üstünde |
| `--on-ton` *(yeni)* | `#06060f` | `#ffffff` | tür/durum renginde dolu zemin üstündeki metin ve ✓ (koyu: mor 7,6 · yeşil 10,5 · nötr 13,6; açık: yeşil 5,5 · nötr 7,8 · mor 7,0) |
| `--focus` | `#a5b4fc` | `#4f46e5` | koyu 8,6–10,1; açık 5,3–6,3 |
| `--ok` / `--ok-bg` | `#34d399` / `rgb(52 211 153 / .12)` | `#065f46` / `#e6f2ee` | |
| `--err-solid` *(yeni)* | `#be123c` | `#be123c` | `tehlike` düğme zemini; beyazla 6,29 |
| `--warn` / `--warn-bg` | `#fbbf24` / `rgb(251 191 36 / .12)` | `#92400e` / `#fdf3e7` | |
| `--err` / `--err-bg` | `#fb7185` / `rgb(251 113 133 / .12)` | `#9f1239` / `#f8e7ec` | |
| `--info` / `--info-bg` | `#38bdf8` / `rgb(56 189 248 / .12)` | `#075985` / `#e6f0f6` | yalnız bilgi kutusu ikonu/şeridi. **`cip-bilgi` (süren/inceleniyor durumları) indigo `--accent` + `--accent-soft` kullanır** — gökmavisi altıncı ton olarak çiplere girmez |
| `--vurgu` / `--vurgu-bg` | `#c084fc` / `rgb(192 132 252 / .12)` | `#7e22ce` / `#f5edfc` | **yalnız AI** (dashboard gradyan ucu) |
| `--notr` / `--notr-bg` | `#cbd5e1` / `rgb(203 213 225 / .10)` | `#4b5263` / `#eef0f4` | kategorik |
| `--replay` / `--replay-bg` | = `--vurgu` | = `--vurgu` | biçimle ayrılır (§4.6) |
| `--replay-miss` / `-bg` | = `--warn` | = `--warn` | ayrı ikon |
| `--ins`/`--ins-bg`, `--del`/`--del-bg` | `#6ee7b7`/`#0f2f26`, `#fda4af`/`#3a1220` | mevcut açık değerler | 7,1–9,5 |
| `--code-bg` | `#08080f` | `#f6f8fa` | |
| `--kod-vurgu` | `rgb(251 191 36 / .18)` (+ 3 px `--warn` sol çubuk, review 2) | `#fff4c2` | `--tk-*` bu satırda ≥5,7 |
| `--chart-bar` / `-active` | `#818cf8` / `#c7d2fe` | `#4f46e5` / `#3730a3` | |
| `--chart-grid` | `#1e1e35` | `#e4e7ed` | |
| `--glow` *(yeni)* | `0 0 0 1px rgb(99 102 241 / .35), 0 8px 32px rgb(99 102 241 / .18)` | `0 0 #0000` | `none` değil (virgüllü gölgede geçersiz olur) |
| `--shadow` | `0 4px 24px rgb(0 0 0 / .4)` | `0 1px 3px rgb(0 0 0 / .06), 0 1px 2px rgb(0 0 0 / .04)` | |
| `--hover` *(yeni)* | `rgb(255 255 255 / .04)` | `rgb(15 17 23 / .04)` | |
| `--hover-accent` *(yeni)* | `rgb(99 102 241 / .06)` | `rgb(79 70 229 / .05)` | tıklanabilir satır |
| `--halka` *(yeni)* | `0 0 0 3px rgb(99 102 241 / .25)` | `0 0 0 3px rgb(79 70 229 / .18)` | odakta **ek** halka |
| `--ust-cubuk-bg` *(yeni)* | `rgb(6 6 15 / .92)` | `rgb(255 255 255 / .92)` | .92 altı → altından kayan metinde AA kaybı |
| `--marka-cizgi` *(yeni)* | `linear-gradient(90deg, transparent, #6366f1, #a855f7, #6366f1, transparent)` | aynı, opaklık .5 | dashboard imzası |
| `--ortam` *(yeni)* | `radial-gradient(900px 600px at 0 0, rgb(99 102 241 / .07), transparent), radial-gradient(700px 500px at 100% 100%, rgb(139 92 246 / .05), transparent)` | `none` | statik ortam ışıması |
| `--giris-izgara` *(yeni)* | `rgb(99 102 241 / .04)` | `rgb(79 70 229 / .03)` | |
| `--select-ok` *(yeni)* | `url("data:image/svg+xml,…stroke='%2394a3b8'…")` | `…stroke='%234b5263'…` | `data:` SVG'de `currentColor`/`var()` çalışmaz |
| `--tk-*` | mevcut koyu değerler | mevcut açık değerler | yeni `--code-bg`/`--kod-vurgu` ile yeniden doğrulandı (≥5,7) |

**Kurallar:**
1. `--accent` dolu zemin olarak **kullanılmaz** (koyuda beyazla 2,98). `background: var(--accent)` /
   `var(--accent-hover)` kullanan mevcut kurallar → `--accent-solid` / `--accent-solid-hover`: `.atla` (256),
   `.dugme-birincil` (614) ve `:hover` (618), `.sekme.aktif` (1099). `.akis-tamam .akis-no` (1203) bu
   listede **değil** — §4.10 geçerlidir (tür renginde dolgu + `--on-ton`). `.odak-isaret` (444) ve akış
   çizgisi (1179) metinsiz, değişmez.
   `.ilerleme-dolgu` (1617) metinsiz olduğu için `--accent` kalır (koyuda iz üstünde 5,6; `--accent-solid`
   2,78 olurdu).
2. Hap zemini = rengin **%12**'si (koyu en düşük 4,67 — indigo, `surface-3` üstünde). Açık temada hap
   zemini sabit token (`*-bg`) kullanılır.
3. `--muted` hiçbir tonlu zeminde (`*-bg`, hap, uyarı kutusu) kullanılmaz; orada `--text-2`.
4. `--accent-solid` koyu yüzeyde ~2,8:1'dir; aktif menü şeridi ve "Sıradaki" bandında **tek gösterge değildir**
   (zemin + metin rengi de değişir), bu yüzden uygundur. Tek gösterge olarak kullanılmaz.
5. **Dekoratif mor istisnası (K4):** marka işareti gradyanı, `--marka-cizgi` ve `--ortam` dekoratiftir, anlam
   taşımaz. Bileşen ve durum düzeyinde mor yalnız `--vurgu`'dur; hover/odak/çizgi için gradyan moru
   kullanılmaz.
6. **Yeşil = insan onayı verildi.** Yeşil şerit/dolgu yalnız geçilmiş insan kapısı ve insanın onayladığı
   varlık (onaylı/yayınlanmış case, birleştirilmiş PR) içindir. "Çözüldü" bulgu ve kapanmış kayıt nötr
   (`--border-strong`) şerit alır; başarı bilgisi hapta yeşil kalır.

### 3.3 Kontrast doğrulaması (2026-11-03, iki bağımsız hesap)

Hesap: WCAG 2.x göreli parlaklık; alfa'lı zeminler `bg`, `surface`, `surface-2`, `surface-3` ile
harmanlandı (~260 çift). Koyu: `--text` 14,7–17,9 · `--text-2` 6,5–7,9 · `--muted` 5,2–6,3 · `--accent`
5,6–6,8 · `--vurgu` 6,3–7,6 · haplar ≥4,67 · beyaz/`--accent-solid` 6,29 · `--on-ton` ≥7,6. Açık: `--text`
≥16 · `--text-2` ≥6,6 · `--muted` ≥4,85 · haplar ≥4,6 · pasif düğme (`--muted`/`--surface-3`) koyu 5,17,
açık 4,85. Tur 2'de ortam ışıması (`bg+--ortam`) zemini de hesaba katıldı; `.ust-baglanti` 5,75 / 5,62.
Metin dışı (1.4.11): `--border-input` ≥3,33; odak halkası ≥5,3; akış dairesi kenarı tür rengi ≥5,5.

Yeni renk çifti eklenirse aynı hesap yapılır; e2e axe iki temada geçmeden faz kapanmaz (§8). axe'in
**incomplete** sonuçları (yarı saydam katman, gradyan metin, `backdrop-filter`) elle incelenir.

### 3.4 Tipografi, boşluk, şekil

| Token | Değer | Not |
|---|---|---|
| `--font` | `"Inter Variable", "Inter", system-ui, -apple-system, "Segoe UI", sans-serif` | `@fontsource-variable/inter@5.3.0` (OFL-1.1). Tüm alt kümeler pakette; latin-ext (ğ ş İ) `unicode-range` ile otomatik |
| `--mono` | `"JetBrains Mono Variable", ui-monospace, "SF Mono", Menlo, Consolas, monospace` | `@fontsource-variable/jetbrains-mono@5.3.0` (OFL-1.1) |
| Kök | `font-size: 90.625%` (≈14,5 px, kullanıcı tarayıcı boyutuna saygılı) / satır 1,55 | |
| Alt sınır | Bilgi taşıyan metin ≥ `0.75rem`; grafik ekseni ≥ 11 px | |
| h1 | `1.6rem` / 800 / `-0.02em` | |
| h2 (kart) | `1rem` / 700; şerit başlıkta `0.9rem` | |
| Eyebrow | `0.75rem` / 700 / büyük harf / `.08em` / `--muted` | |
| KPI | `1.9rem` / 800 / `tabular-nums`; renk `--text`, durum anlamı varsa `--ok/--err/--warn`. Stat şeridinde (`.metrik-izgara`) `1.6rem` ve `--accent` (§4.12) | site `.stat-val` |
| Mono kimlik | TPD-1, run-107, sha, yol → `--mono` `0.85em` | |
| Paragraf | `max-width: 72ch` | |
| `--radius` / `--radius-lg` / `--radius-sm` | 12 / 20 / 8 px; düğme ve giriş 10 px; hap 999 px | |
| Boşluk | 4 · 8 · 12 · 16 · 20 · 24 · 32 · 48; kart iç 20, kartlar arası 16 | |
| İçerik | `.icerik { max-width: 1320px }`; `@media (min-width: 1680px) { margin-inline: auto }` | G12 |

---

## 4. Bileşen spesifikasyonları

**C** = yalnız CSS · **M** = küçük markup ekleme (metin/rol/sınıf değişmez) · **MVT** = demo öncesi teslim.

### 4.1 Kabuk — `Kabuk.tsx`, `.kabuk .ust-cubuk .yan-menu .menu-*` — MVT (C)

- **Arka plan:** `.kabuk { isolation: isolate }` +
  `.kabuk::before { content: ""; position: fixed; inset: 0; background: var(--ortam); pointer-events: none; z-index: -1 }`
  (statik; `background-attachment: fixed` kullanılmaz). `isolation` olmadan `body`'nin opak `--bg` zemini
  ışımayı örter. `.bildirimler` (`App.tsx:131`) kabuk dışında render edildiği için etkilenmez.
- **Üst çubuk:** 56 px, `background: var(--ust-cubuk-bg)`, `backdrop-filter` ve `-webkit-backdrop-filter`
  `blur(16px)`; `.ust-cubuk::after` 2 px `var(--marka-cizgi)` (statik). Yedek:
  `@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)))` ve
  `@media (prefers-reduced-transparency: reduce)` → `background: var(--surface)`.
  `html { scroll-padding-top: 72px }` (WCAG 2.4.11).
- **Marka:** `.marka-isaret` CSS altıgen (`clip-path: polygon(...)`), `#6366f1 → #8b5cf6` gradyan, iç nokta,
  `box-shadow: 0 0 12px rgb(99 102 241 / .3)` (C). "Probe" kelimesinin `<strong>` ile ayrılması (M) **F3'te**;
  hem `Kabuk.tsx` hem `Giris.tsx` (ikinci kopya). "Testing Probe" arasındaki boşluk korunur.
  `.marka-alt` mevcut **860 px** kırılımında gizlenmeye devam eder. Marka metni (MVT, C): 700 / `-0.01em`.
- **Kabuk glifleri (MVT, C):** SVG'ye geçiş F3'e kadar ☰ ve tema düğmesindeki ◐ ☾ ☀ şu stille tutarlı
  görünür: 32×32 px kutu, `font-family: var(--mono)`, `font-size: 1rem`, `line-height: 1`, `--text-2`.
- **Sağ grup:** ÖRNEK VERİ rozeti (amber `section-badge` kalıbı) · bağlantı göstergesi: **bağlı = yeşil nabız**,
  bağlanıyor/yeniden = amber, kapalı = kırmızı, örnek veri = `--muted`; nabız `box-shadow` + `opacity` ile
  (transform yok → taşma üretmez), hareket azaltmada statik · tema düğmesi · `.kullanici` · Çıkış (ikincil).
- **Sol menü:** 240 px, `--surface`, sağ kenar `--border`. Grup başlığı eyebrow. Öğe 36 px, 10 px yarıçap,
  hover `--hover`. **Aktif:** `--accent-soft` + `--accent` metin + solda 2 px `--accent-solid` şerit. Pasif
  ("bu fazda yok"): `opacity` **kaldırılır** (bugün `.7` → 4,23), `--muted` metin, kesik kenarlı not hapı.
- **Mobil (≤860 px):** davranış aynı. Açık menüye perde yalnız görsel ve mevcut gölgeyle birleşik:
  `.yan-menu.acik { box-shadow: <.yan-menu'deki mevcut gölge, styles.css:471>, 0 0 0 100vmax rgb(0 0 0 / .5) }`
  (tıklamayı yakalamaz, taşma üretmez). Menü z-index 30 > üst çubuk 20 olduğundan perde üst çubuğu da
  karartır; hamburger tıklanabilir kalır — kabul edildi.
- **AI asistan kancaları (korunur; `docs/AI-ASISTAN-PLANI.md` §11 Kabuk adımı, R7):** reskin bunları
  taşımaz ve silmez, yalnız görünüm belirteçlerini alır.
  - `Kabuk.tsx`: `.atla` yanında `<AsistanaAtla />` (`button.atla.atla-asistan`, "Asistanı aç"; yalnız
    asistan hazırken görünür); `.ust-sag`'ın **en solunda** `<OneriDugmesi />` (yalnız kuralı olan ekranlarda
    çizilir; sağa yaslı grupta solda durduğu için görünüp kaybolması ÖRNEK VERİ ve bağlantı göstergesini
    kaydırmaz); `Kabuk` → `KabukIcerik` bölünmesi ve `KabukDurumuSaglayici`/`useKabukDurumu`
    (menü durumu `menuAcik` buradan gelir; `useState`'e geri çevrilmez).
  - Katman sırası (`styles.css` "kabuk" bölümü ve `asistan.css` baş yorumu ile aynı; `kabuk.test.tsx` kilitler): üst
    çubuk 20 · menü perdesi 29 · yan menü 30 · "Bu ne?" bindirmesi 39 · asistan başlatıcı ve panel 40 · panel içi modal 45 ·
    `.bildirimler` 50 · `.atla` 100. Yeni sabit öğe (perde, ortam ışıması dahil) bu sıraya oturtulur.
  - `body:has(.asistan-baslatici) .bildirimler { bottom: 72px }`: sağ alttaki "Asistan" düğmesi
    görünürken bildirimler onun üstünde durur; §4.15 bildirim konumu değişirse bu kural birlikte taşınır.
  - Asistan paneli `top: 56px` ile üst çubuğun altından başlar (üst çubuk border-box 56 px, 2 px marka
    çizgisi dahil); üst çubuk yüksekliği değişirse panel ofseti birlikte güncellenir.
  - 760–860 px'de panel ile mobil menü çekmecesi birbirini dışlar (`KabukDurumu`): panel açılınca menü,
    menü açılınca panel kapanır; kipsel menünün yanında karartılmamış, tıklanabilir ikinci bölge kalmaz.
- **AI asistan arayüzü (görsel dil):** asistan bileşenleri portalın token'larını kullanır; sabit renk yok.
  - Renk: mor (`--vurgu`) yalnız AI kimliği ve AI içeriği (panel başlık ikonu, AI cevabı/AI önerisi sol
    3 px şeridi, AI hapı); etkileşim (başlatıcı, Öneri düğmesi rozeti ve kenarı, seçili sekme, "Bu ne?"
    hedef çerçevesi) indigo; insan kararı yeşil; ÖRNEK VERİ amber; pasiflik nötr kesik kenar.
  - Başlatıcı (sağ alt, z 40): sakin yüzey (`--surface-2`, 1 px `--accent` kenar, indigo ikon), indigo dolgu
    yalnız hover/odakta; 1280 px altında ya da ≤760 px yüksekliğinde 44 px yuvarlak, yalnız ikon. Pasifken
    kesik kenar + düğmenin solunda görünür neden (`aria-describedby`). Görünür ad erişilebilir adın içinde.
  - Üst çubuk Öneri düğmesi: ikincil küçük düğme, görünür "Öneriler" + sayı rozeti, ad `Öneriler: N`
    (WCAG 2.5.3); ≤520 px'te 32 px kare, rozet köşede. Dar üst çubukta "Probe" 320 px'te de tam görünür
    (≤360 px'te ÖRNEK VERİ görsel olarak "ÖRNEK"); duman testi rozetli ekranda ölçer.
  - Panel: masaüstünde sağa yaslı 420 px çekmece (kart yüzeyi, sol ayraç), < 760 px tam ekran modal.
    "Bu ne?" ipucu bandı içeriğin üstünde (üst çubuğun 8 px altında), içerik alanına ortalı; tıklamayı yutmaz
    (yalnız "Vazgeç" tıklanır), altındaki öğe de seçilebilir.

### 4.2 ÖRNEK VERİ bandı — `.ornek-veri-bandi` (testid korunur)

Görünüm bugün `.uyari-kutusu.uyari-uyari`'den gelir; bant için kural **`.uyari-kutusu.ornek-veri-bandi`**
seçicisiyle yazılır (sonraki `.uyari-kutusu` 2164 tanımı ezmesin).
- **MVT (C):** amber `--warn-bg` zemin + sol 3 px `--warn` şerit, metin `--text`, `min-height: 36px`
  (390 px'te iki satır), tam genişlik, kapatılamaz, yapışkan içerikle örtülmez, sayfa başlığının üstünde.
  Ton zemini **korunur** (dürüstlük etiketi zayıflatılmaz).
- **F3 (M):** tam örnek veri derlemesi (`mockZorunlu()`) için `ornek-veri-tam` niteleyici sınıf → yalnız bu
  durumda daha ince yazı. Canlı derlemede kısmi örnek veri bandı bugünkü belirginlikte kalır.
- "ÖRNEK VERİ" üst çubukta ve bantta iki kez görünür — **bilinçli** (biri kalıcı durum, biri açıklama).

### 4.3 Sayfa başlığı — `SayfaBasligi`, `.sayfa-basligi .ust-baglanti` — MVT (C)

`.ust-baglanti` → `section-badge` hapı (`0.75rem`, 600, büyük harf, `.1em`, `--accent`, `--accent-soft`
zemin, `rgb(99 102 241 / .25)` kenar; açık temada token). h1 §3.4, açıklama `--text-2` `72ch`. Eylemler
sağda, birincil en sağda ("Case üret" sağ üstte kalır).

### 4.4 Kart — `Kart`, `.kart .kart-baslik` — MVT (C)

- `--surface`, 1 px `--border`, 12 px, `padding: 20px` (bugün `18px 20px`, 555 — şerit başlığın `-20px`
  marjıyla eşleşsin); koyuda gölge yok, açıkta `--shadow`; hover yok.
- Izgaralarda `align-items: start` (G6). `.kart` 2019 tekrar tanımı da güncellenir.
- **Şerit başlık** (site mock-panel): `.kart:has(> .tablo-sarici, > .kod-blok, > .kod)` içindeki
  `.kart-baslik` kart kenarına taşan şerit olur — `margin: -20px -20px 12px`, üst köşeler
  `border-radius: 12px 12px 0 0`, `--surface-2` zemin, alt kenar `--border-soft`, `14px 20px` iç boşluk, h2
  `0.9rem`. `.kart`'a `overflow: hidden` **konmaz** (odak halkası kesilir). (`KodGorunumu` `figure.kod` üretir;
  `.kod-blok` yalnız ham `<pre>`'lerde.) Metin kartlarında ayraç yok.
- **Durum şeridi** (site `.test-result`), sol 3 px, §3.2 kural 6'ya göre:

  | Kart | Seçici | Şerit |
  |---|---|---|
  | Kart | Seçici | Şerit |
  |---|---|---|
  | Bulgu (açık) | `article.bulgu.bulgu-blocking:is([data-durum="open"], [data-durum="unverified"])` | `--err` |
  | Bulgu (açık, uyarı) | `article.bulgu:not(.bulgu-blocking):is([data-durum="open"], [data-durum="unverified"])` | `--warn` |
  | Bulgu (kapanmış) | `article.bulgu:is([data-durum="decided"], [data-durum="resolved"], [data-durum="stale"], [data-durum="discarded"])` | `--border-strong` |
  | Case | mevcut `.case-${durum}` (`CaseKarti.tsx:101`) | `draft` → `--vurgu` (AI taslağı, karar bekliyor); `approved`/`published` → `--ok`; `rejected`/`superseded` → `--border-strong` |
  | PO kapısı | bekliyor: `.kart:has([data-testid="po-kapisi"].soluk)` (`GereksinimDetay.tsx:556`); geçildi: `.kart:has([data-testid="po-kapisi"]:not(.soluk))` (`:552`) | `--warn` / `--ok` |
  | Merge kapısı | geçildi: `.merge-kapisi:has(> .ok-metin)` (yalnız birleştirilmiş dalda doğrudan çocuk, `ScriptDetay.tsx:747-748`); bekliyor: `.merge-kapisi:not(:has(> .ok-metin))` ("açık ✓" iç içe olduğu için `>` iki hali ayırır, `:761-763`) | `--ok` / `--warn` |
  | Bug karar paneli | `.karar-paneli` (yalnız `draft` iken çizilir, `BugTaslaklari.tsx:402, 649`) | `--warn` |

  `data-durum` MVT DOM değişikliğidir (`BulguKarti.tsx:105`'e `data-durum={bulgu.durum}`; değerler
  `etiketler.ts:90-97`). Mevcut `.bulgu` 4 px `--warn` sol kenarı ve `.bulgu-blocking` kuralları (1319-1328)
  bu tabloyla değiştirilir. Karara bağlanmış bulguda önem yalnız hapta (G15). Şerit tek başına anlam
  taşımaz; kartta durum metni/hapı her zaman var. İnsan kapısı kartlarında her durumda maske "kişi" ikonu
  (`content: ""` + `mask-image`). **Yeni görünür metin eklenmez.**

### 4.5 Düğmeler — `.dugme .dugme-*`, `IslemDugmesi` — MVT (C)

| Tür | Görünüm |
|---|---|
| `birincil` | `--accent-solid`, beyaz, 600, 10 px, 36 px (küçük 30); hover `--accent-solid-hover` + `--glow` + `translateY(-1px)` |
| `ikincil` | saydam, 1 px `--border-strong`, `--text`; hover `--hover` |
| `hayalet` | kenarsız, `--text-2`; hover `--text` |
| `tehlike` | `--err-solid`, beyaz (6,29) |
| **pasif** | `opacity` **yok** — mevcut `.dugme:disabled { opacity: .5 }` (609) ve `.dugme-ek { opacity: .85 }` (2146) silinir. Zemin `--surface-3`, metin `--muted` (5,17 / 4,85), kesik kenar `--border-strong`, `cursor: not-allowed`. Rol yüzünden pasifse (`[data-yetkisiz]`) maske ile kilit ikonu (`content: ""`) |
| çalışıyor | döner simge; genişlik sabit |
| **metin düğmesi** `.dugme-metin` *(plan sonrası, Ek B; 2432+ bloğu)* | Tablo hücresinde açılır-kapanır test adı (`aria-expanded`). Kenarsız/zeminsiz kalır; metin `--text` 500, hover `--accent` + alt çizgi; odak global halka. Önündeki ▸/▾ glifi `aria-hidden` metin kalır (SVG listesine girmez, §4.16) ve `--muted` |
| **seçim (segment) düğmeleri** | Test sonucu süzgecindeki "Tümü (n) / Başarısız (n) …" (`aria-pressed`): seçili = `birincil` (`--accent-solid`), diğerleri `ikincil`, küçük (30 px). Sayısı 0 olan pasif görünümü yukarıdaki pasif kuralıyla (opacity yok). Sınıf değişmez |

Pasif öğeler axe'ten zaten muaf (native `disabled` / `aria-disabled`), ama renkler yine AA'yı sağlar.

**Görünür pasiflik nedeni** (`.dugme-neden`, F3, demo sonrası): native `disabled` düğme odak almadığı için
`title` klavyede okunmaz. Neden metni düğmenin **dışında**, `aria-describedby` ile bağlı, `--muted`, tonlu
zemine konmaz. Ön koşul: o `title` metni (ve "Bu işlem için gereken rol:" öneki) aynı ekranda
`getByText`/`findByText`/`page.getByText` ile aranıyorsa o düğmede çizilmez (çift eşleşme → strict mode).
Bilinen adaylar: `inceleme.test.tsx:396,404`, `bilesenler.test.tsx:144`, `demob.test.tsx:97,127,208`,
`duzeltmeler.test.tsx:109,125`, `duzeltmeler3.test.tsx:68,70`.

### 4.6 Rozet ve çip — `.rozet .rozet-* .cip .cip-*` — MVT (C) + ton (M)

- **Hap:** 999 px, `0.75rem`, 600, `2px 8px`, zemin %12, kenar %30, metin = renk. `.rozet` ek olarak büyük
  harf + `.06em`. `.rozet` 1885 ve `.cip` 2305 tekrar tanımları da güncellenir.
- Ton eşlemesi (`Ton` tipi değişmez): `basari→--ok`, `uyari→--warn`, `hata→--err`, `bilgi→--accent`
  (süren/inceleniyor; indigo), `vurgu→--vurgu` (yalnız AI), `notr→--notr`.
- **REPLAY** (`.rozet-replay`): mor + büyük harf + 1,5 px tam opak kenar + önde maske "kayıt" ikonu →
  diğer mor haplardan **biçimle** ayrılır. **REPLAY-MISS**: amber + ayrı uyarı ikonu. **kanıt doğrulandı**
  (`.rozet-dogrulandi`): yeşil, ✓ metni aynen.
- **Ton değişikliği (M, MVT) — tam liste:**
  - AI olmayan kategorik çipler → `notr`: bulgu türü (`BulguKarti.tsx:114`), "Serbest metin"
    (`Gereksinimler.tsx:125`), "Claude Code" (`CaseKarti.tsx:113`), "Doğrulama/Eylem" (`ScriptDetay.tsx:238`),
    koşu tetiği `TETIK_TONU`'nda **yalnız** `nightly` ve `deploy` (`Kosular.tsx:13-17`; `break_verify: "uyari"`
    kalır), koşu kaynağı üçlüsü (`Kosular.tsx:67, 379`) sabit `notr` (Kule aynı `KosuTablosu`'nu kullanır,
    `KontrolKulesi.tsx:301`), Demo kontrolleri "onarıldı" (`DemoKontrolleri.tsx:817`). *(Satırlar 15:00
    çalışma ağacına göre; Ek B.)*
  - AI olmayan `vurgu` durumları → `bilgi` (indigo, "insan incelemesi bekliyor"): "Case review"
    (`etiketler.ts:37`), `SCRIPT_DURUMU` içinde **yalnız** `pr_open` "PR açık" (`etiketler.ts:130`), Triage
    onarım "PR açık" (`HataDetay.tsx:16`), PR "Açık" çipi (`ScriptDetay.tsx:688`).
  - **Bilerek mor kalır (AI):** Triage AI karar kaynağı (`HataDetay.tsx:606`), yol haritası REPLAY
    (`YolHaritasi.tsx:108`).
  - Yol haritası `HAL.tamam.ton` `basari` → `notr` (`YolHaritasi.tsx:30`; ✓ zaten `.yh-no`'da, hap metnine
    eklenmez). `HAL.suruyor` `bilgi` kalır (artık indigo).
  - **Değişmez (plan sonrası eklenen çipler, Ek B):** `SauceCipi` (`Kosular.tsx:101-113`: geçti `basari`,
    kırmızı `hata`, "Sauce koşmadı: …" `uyari` — senaryo 389-391 "⚠️" ile uyumlu —, atlandı `notr`,
    sırada/sürüyor `bilgi`); `CiAdimlari` "geçti/kaldı/atlandı" ve GitHub işi sonuç hapları
    (`KosuSonuclari.tsx` `GH_SONUC_TONU`). Bunlar test/iş sonucu haplarıdır: §3.2 kural 6 gereği yeşil
    **hapta** kalır, şerit/dolgu almaz.
  - **Değişmez:** "Kırarak doğrula"/kırma çipi `uyari` (`Kosular.tsx:56`); "1 defect adayı" `cip-uyari`
    (testte kilitli); `SCRIPT_DURUMU`'nun `pr_open` dışındaki tonları ve `YEREL_SINIF` ("Defect adayı" `hata`,
    "Kararsız (flaky)" ve kabul gerektiren işaretler amber).
  - **CSS'te `--info` kullanan diğer yerler:** `.kirma-running .kirma-ikon` (1778-1781) →
    `--accent`/`--accent-soft`; `.bildirim-bilgi` (2112) şeridi `--info` kalır.
  - Test etkisi: tek ton sınıfı doğrulaması `cip-uyari`; yol haritası testleri yalnız `data-hal`'e bakıyor
    (`duzeltmeler6.test.tsx:139`, `faz5.test.tsx:418`, `canli.spec.ts:381`, `duman.spec.ts:508`) — tarama
    2026-11-03.
- **Mükerrer benzerliği** kategorik hap kalır ("yüksek olasılık" vb.) + REPLAY; çubuk/yüzde gösterilmez.

### 4.7 Tablo — `.tablo .tablo-sarici .tablo-sik .tablo-yigin` — MVT (C)

Başlık hücresi `--surface-2`, `0.75rem`/700/büyük harf/`.05em`/`--muted` (5,6); satır `12px 14px`, ayraç
`--border-soft`, son satır ayraçsız; tıklanabilir satırlarda hover `--hover-accent`. `.tablo-sarici`: 1 px
`--border`, 12 px, `overflow-x: auto`, odaklanabilir bölge aynı; mobilde kaydırılabilirken sağ kenarda 24 px
solma gölgesi (CSS scroll-shadow, G18). İlk sütun kimlikleri `--mono`; sayılar `tabular-nums` sağa yaslı.
`.tablo-yigin` 640 px kuralı (test bunu metin olarak arıyor) **aynı yerde ve aynı biçimde** kalır.
**Açılır ayrıntı satırı** (`tr.test-ayrinti-satiri`, Koşu detayı, Ek B): `td` zemini `--surface-2` (bugün de
öyle) + üst ayraç `--border-soft`; satır hover'ı **almaz** (`.tablo tbody tr:not(.test-ayrinti-satiri):hover`).
Açık satırın üstündeki test satırına sol 3 px `--accent` şerit (`tr:has(+ .test-ayrinti-satiri) > td:first-child
{ box-shadow: inset 3px 0 0 var(--accent) }`) — hangi testin açıldığı görünür. İçteki `.test-deneme`/`.test-blok`
(`<details>`) 1 px `--border-soft`, 8 px; `summary` 600; `.pw-adim-hata` `--err` (değişmez), başarılı adım ✓
`--muted`. `.hata-mesaji-kisa` (6,5em kesik) altına 1,5em `--surface` → saydam solma (yalnız görsel).
Ek görselleri (`.test-ek-resim img`, `.test-ek-video video`) 1 px `--border`, `--radius-sm` (bugün de öyle).

### 4.8 Form — MVT (C)

`--surface-2` zemin, 1 px `--border-input`, 10 px, 36 px. Odak: global `outline: 2px solid var(--focus)`
**korunur**, `--halka` yalnız ek. `select:not([multiple]):not([size])` → `appearance: none` +
`background-image: var(--select-ok)`; `@media (forced-colors: active) { select { appearance: auto; background-image: none } }`.
`accent-color: var(--accent-solid)`. Hata: `--err` kenar + `.alan-hata`.

### 4.9 Uyarı kutuları — `.uyari-kutusu .uyari-*` — MVT (C)

Ton **zemini korunur** (`--*-bg`; demo'daki "sarı kutu" tarifleri) + sol 3 px ton şeridi + maske ikon;
metin `--text`, ikincil metin `--text-2` (tonlu zeminde `--muted` yasak). `.kapi-uyarilari` ve "Zayıf test"
kutusu amber kalır. `.uyari-kutusu` 2164 tekrar tanımı da güncellenir.

**Mevcut hata (plan sonrası ortaya çıktı, MVT'de düzeltilir — yalnız CSS):** `.uyari-kutusu strong { display:
block }` (bugün 763) **gövdedeki satır içi `<strong>`'ları da** blok yapıyor. Demo kontrollerine eklenen
"Bu demo ne gösteriyor? Test bakımı" kutusunda (`data-testid="locator-aciklama"`) "**bakımı**", "**Ayırt
eder**", "**Tek satırlık onarım önerir**", "**İnsan onaylar**" kendi satırlarına düşüyor. Seçici
`.uyari-kutusu > strong` olur (`Uyari` başlığı doğrudan çocuk `<strong>`, `ui.tsx:90`). Ayrıca başlık +
uzun gövde yan yana iki sütuna bölünmesin diye `.uyari-kutusu > strong { flex-basis: 100% }`; gövdedeki
`ol/ul` `padding-left: 1.25rem`, `margin: 6px 0`; `p + p` `margin-top: 6px`. 1440 ve 390 px ekran görüntüsüyle
onaylanır. Kapsam: `<Uyari baslik>` kullanan **36 yer** (BugTaslaklari 8, DemoKontrolleri 7, HataDetay 5,
Yayin 4, ScriptDetay 3, …; `grep -rn "<Uyari[^>]*baslik=" src`). Bugün geniş ekranda başlık gövdenin **solunda**
duruyor (flex satırı); `flex-basis: 100%` ile her yerde **üstüne** geçer — bilinçli, site uyarı dilidir.
Senaryo tarifleri ("sarı kutu", "✓ Zincir doğrulandı") metin/renk düzeyinde olduğundan etkilenmez; F2-C'de
Denetim, Script detay (merge kapısı, "Dal main'in gerisinde"), Bug taslakları ve `/demo` ekranları önce/sonra
karşılaştırılır.

### 4.10 Akış göstergesi (14 adım) — `AkisAdimlari.tsx`, `.akis*` — MVT (C)

**Tür = biçim + renk** (bugünkü biçim dili korunur; demo satır 251 (v4'te 214) "kesikli halka = AI"):

| Tür | Biçim | Renk |
|---|---|---|
| AI | daire, `2px dashed var(--vurgu)` | `--vurgu` |
| İnsan kapısı | köşeli kare, `2px solid var(--ok)` | `--ok` |
| AI + insan | köşeli kare, `2px dashed var(--vurgu)` dış kenar + `box-shadow: inset 0 0 0 2px var(--ok)` iç halka (`border-image` **kullanılmaz** — kesik kenarı ve yarıçapı geçersiz kılar) | `--vurgu` + `--ok` |
| Sistem | küçük daire, `2px solid var(--notr)` | `--notr` |

**Durum renkten ve kesiklikten bağımsız:**
- **tamam:** tür renginde dolgu, `background-clip: padding-box` + 3 px iç gölge halkası → dolgu içeride kalır, tür
  kenarı (kesik/düz) dışarıda görünür; ✓ `--on-ton` (AI + insan dolgusu `--vurgu`). Mevcut
  `.akis-tamam .akis-no` kuralındaki `border-style: solid` (1205), `border-color: var(--accent)` ve
  `background: var(--accent)` silinir (aksi halde AI'nin kesik kenarını ezer).
- **şimdiki:** tür kenarı aynen + dışına `box-shadow: 0 0 0 3px var(--bg), 0 0 0 5px var(--accent)` ve
  `--glow`; ad 700 + `--text`. Indigo halka yalnız "neredeyiz" anlamı taşır (≥5,6:1). Adımlar odaklanabilir
  değildir; halka klavye odağıyla karışmaz.
- **bekliyor:** boş iç + tür renginde kenar, `opacity` yok (kenar ≥5,5:1).

Lejant (`AkisAdimlari.tsx:27-31`) dört öğe: AI adımı, İnsan kapısı, **AI + insan kapısı** (review turu 1:
dördüncü biçimin görsel karşılığı yoktu; lejant `aria-hidden`, testlere etkisi yok), Sistem. Kenar en az 2 px; `.akis-no` zaten 28 px
(1189-1190). Mobil 4 sütun ve "adım adları çakışmaz" kuralı korunur; daire 28 px'ye büyürken `.akis-ad` ölçümü
(`duman.spec.ts:381-394`) kapıdır.

### 4.11 Kod ve fark — MVT (C)

`--code-bg`, 1 px `--border`, 12 px; `.kod-dosya` şerit (`--surface-2`, mono `--muted`). Pencere noktası yok.
Satır no `--muted`; vurgu satırı `--kod-vurgu`. `ins`/`del` hap zeminli. `.kod-*` 2141 tekrar tanımı da
güncellenir. ("Kod" etiketli kutu koyu temada siyahımsı olur → senaryo satır 201 (v4'te 164) MVT senaryo düzeltmesinde netleşir.)

### 4.12 Metrik / KPI — `Metrik`, `.metrik*`, `.olculmedi`, `Ilerleme` — MVT (C)

- Değer §3.4 KPI, rengi `--text`; **yalnız stat şeridi içinde** (`.metrik-izgara`, F4 KPI şeridi) site gibi
  `--accent` — şerit dışında indigo yalnız etkileşimdir. Etiket eyebrow; alt metin `--text-2` (değer "—"
  iken de).
- **`.metrik-izgara` (1578) site `.hero-stats` görünümü (MVT, C):** tek `--surface-2` zemin, 1 px
  `--border`, 12 px; içteki `.metrik` kutularının kenar ve zemini kalkar, aralarında 1 px `--border-soft`
  ayraç; değer `1.6rem`/800 `--accent`. DOM, testid ve (i) ipuçları aynı.
- **Boş değer tek stil (G16):** `.bos-hucre`, tablo içi "case yok" ve "—" → `--muted`, normal yazı (italik
  değil), hap değil. Hap yalnız `.olculmedi`.
- **Kule maliyeti REPLAY'de (MVT, M):** `KontrolKulesi.tsx:146-153` — koşul
  `ai.cagri_sayisi !== null && ai.cagri_sayisi > 0 && ai.replay_cagri === ai.cagri_sayisi` (null koruması;
  `yolHaritasi.ts:567-568` `modOzeti` ile aynı mantık; `demob.test.tsx:386-396` null senaryosu "ölçülmedi"
  demez) ise "Maliyet (toplam)" ve "Bugün" değeri `<Olculmedi metin="REPLAY — ölçülmedi" />`
  olur (Case review'daki mevcut metinle aynı; `inceleme.test.tsx:276-283` emsali). Alt satır ("n model
  çağrısı", "Günlük tavan …") aynen. Önkoşul §9: bu metnin Kule sayfasında kapsamsız `getByText` ile
  aranmadığı doğrulanır.
- **`.olculmedi`** (2235): değer yuvasında, etiketle aynı ya da büyük boyda, `--text-2`, 600, kesik kenarlı
  hap; italik değil. Metin aynen.
- `Ilerleme`: 6 px, iz `--surface-3`, dolgu `--accent` (hedef altıysa `--warn`), hedef işareti 2 px
  `--text-2`. `role="meter"` aynen.

### 4.13 Grafik — MVT (C)

Sütun `--chart-bar`, aktif `--chart-bar-active`, ızgara `--chart-grid`, hedef çizgisi kesik `--warn`, ipucu
`--surface-2` + `--shadow`. Grafik `max-height: 180px`; eksen ≥11 px. Sütun genişliği SVG'de hesaplanıyor
(en fazla 28 px) — değişmez.

### 4.14 Giriş — `Giris.tsx`, `.giris-sayfa .giris-kart` — MVT (C), P2

`--bg`; `::before` 60 px ızgara (`--giris-izgara`), `::after` iki statik radyal ışıma (animasyonsuz). Kart
400 px, `--radius-lg`, `rgb(14 14 28 / .85)` + blur(20px) (+ `-webkit-`), 1 px `rgb(99 102 241 / .25)`
kenar (açıkta token), `--shadow`. Marka: büyük altıgen + "AI Testing Probe" gradyan metin (F3'te
`<strong>`). Metin, alan sırası, `<details>` aynı.

### 4.15 Bildirim — `BildirimProvider`/`useBildirim` (`Bildirim.tsx`), `.bildirim*` — MVT (C)

Sağ alt, `--surface-2` + `--shadow` + sol ton şeridi; 150 ms giriş (hareket azaltmada yok). **Kapat düğmesi
en az 24×24 px** (WCAG 2.5.8; bugün ~16 px).

### 4.16 İkonlar — F3 (M), demo sonrası

Yeni `src/components/Ikon.tsx`: bağımlılık yok; kendi çizimimiz ~12 sade SVG (24×24, `stroke="currentColor"`,
1,75), `aria-hidden="true"`, `focusable="false"`, **`<title>` yok**. CSS ikonları her zaman
`content: ""` + `mask-image` (Playwright erişilebilir ad hesabına pseudo `content` metni girer).

**SVG'ye çevrilenler yalnız:** ☰ (`Kabuk.tsx:132`), ☾ ☀ ◐ (`Kabuk.tsx:159`), ↗ (`ui.tsx:192`) — hiçbir
testte aranmıyor. **✓ ✗ ⚠ ○ ◌ → ← glifleri `aria-hidden` olsalar bile her yerde metin olarak kalır**
(testler arıyor: `duzeltmeler4.test.tsx:229` "⚠", `duzeltmeler5.test.tsx:103-134`, "açık ✓",
"✓ Birleştirildi", "✓ Zincir doğrulandı", "Test hata yakalıyor ✓", "✓ İnsan kapısı geçildi" …); görünümleri
yalnız CSS ile (renk, font) iyileşir. Menü öğelerine ikon F3'te; NavLink erişilebilir adı değişmez.

---

## 5. Ekran bazlı plan

MVT (§6.1) bittiğinde tüm ekranlar yeni dile geçer. Bu tablo, **ek** düzen değişikliklerini listeler.
Öncelik demo rollerine göre: P1 = demoda görünen ana ekran.

| Ekran | Rota | Rol | Öncelik | MVT'de (C) | Demo sonrası (F4, M) | Kilitler |
|---|---|---|---|---|---|---|
| Yol haritası | `/yol-haritasi` | Sunucu | **P1** | **MVT DOM:** `<li class="yh-adim">`'e `data-tur={a.tur}` (`YolHaritasi.tsx:71`; bugün tür DOM'da yok). Daire **= tür** (§4.10 biçim+renk, `[data-tur]` seçicisiyle). Durum yalnız `.yh-no`'daki ✓ + durum hapı; **"tamam" hapı `notr`** (§4.6; yeşil insan onayına ait). `yh-tur` metni `[data-tur]`'a göre tür renginde hap. Mevcut dört durum kuralı `.yh-adim.yh-{tamam,suruyor,engel,yedek} .yh-no` (2350-2369) **silinir**; `.yh-no` §4.10 gibi çizilir: `[data-tur]` kenarı; `tamam` → tür dolgusu + ✓ `--on-ton`; diğer haller boş iç. `yh-tur` hap rengi: sistem `--notr`, insan `--ok`, ai ve ai_insan `--vurgu`. "Sıradaki" = `[data-testid="yh-sonraki"]` paragrafı (`YolHaritasi.tsx:243`): sol 3 px `--accent-solid` + `--accent-soft` bant. "Sürüyor" yalnız hapta (`bilgi` → indigo). Adımlar arası ayraç mevcut `border-top` (2326-2336) `--border-soft` — **yeşil bağlantı çizgisi yok**. Bağlantılar çizgisiz `--accent`, hover'da çizili | — | `yh-adim-*`, `yh-ilerleme`, `yh-mod`, liste "14 adımlı demo akışı" (14 öğe), "Locator kırılması ilerlemesi" |
| Gereksinim detayı | `/gereksinimler/:id` | Analist | **P1** | Bulgu şerit önceliği (§4.4); "✓ kanıt doğrulandı" sağ üst, yeşil; "✓ Doküman son hâl" çipi sağ üst — **ton kodda belirlenir (Ek B, `GereksinimDetay.tsx:300`): `pending_po` → `bilgi` (indigo, "sıradaki adım"), `doc_final`/`po_approved` → `basari`**; tasarım bu tonları değiştirmez; PO kartı insan kapısı şeridi | **Bölüm gezgini** üç aralıkta: ≤860 px gizli (`display: none`), 861–1279 px üst çubuğun altında yapışkan tek satır yatay şerit, ≥1280 px sağda yapışkan sütun; `<nav aria-label="Sayfa bölümleri">` + düz `<a href="#…">` (list/article değil); `scroll-padding-top` yapışkanlar toplamına (şerit aralığında 120 px = 56 + 45 + 16; şerit sarmaz) | `article.bulgu` (sayı 3), `.rozet-dogrulandi`, `bulgu-sayaclari`, `.baslik-anahtar`, `aria-current="step"`, "Case üret" sağ üst, navigation "14 adımlı akıştaki ilerleme" |
| Kod üretimi | `/kod` | Mühendis | **P1** | Ton değişikliği yalnız "PR açık" (indigo, §4.6). "Defect adayı" mevcut `hata` tonuyla kalır; öne çıkması yalnız CSS: `tr:has(.cip-hata) > td:first-child { box-shadow: inset 3px 0 0 var(--err) }` (tablo `border-collapse: collapse`, 832; "Başarısız" satırları da `hata` olduğundan aynı şeridi alır — kabul) ve hap 700. Uyarı/kabul gerektiren işaretler amber | — | bölge "Üretilen testler tablosu" |
| Script detay | `/kod/:id` | Mühendis | **P1** | PR + Kırarak doğrula kartları üst hizalı; merge kapısı insan kapısı şeridi; zayıf test kutusu amber; zaman çizelgesi yeşil→kırmızı→yeşil. **Plan sonrası (Ek B):** beklenenin tersi sonuç (`data-beklenmedik`) de `kirma-sonucsuz` sınıfı + ⚠ alır → `.kirma-sonucsuz .kirma-ikon` amber kuralı (bugün 1796) **iki durumu da** kapsar, yeşil/kırmızı aşama kuralları onu ezmemeli (seçici özgüllüğü F2-D'de kontrol). Kod üretimi tablosundaki "Kırma etkilemedi · kabulle birleşti / kabul gerekli" düz metindir (hap değil, `Kod.tsx:169-171`) — MVT'de renk verilmez | — | `merge-kapisi`, `merge-uyarilari`, `yerel-sinif`, `kirma-*`, `.ok-metin`, `.ajan-ekran img`, liste "Kırarak doğrulama zaman çizelgesi", "PR check'leri", bölge "Eşlenen adımlar tablosu", demo-app önizlemesi kendi görünümünde |
| Bug taslakları / detay | `/bug-taslaklari(/:id)` | Testçi | **P1** | Karar düğmeleri insan kapısı kartında; mükerrer kategorik hap + REPLAY; kasıtlı kırma taslağı uyarısı amber | — | `mukerrer-onerisi`, liste "Mükerrer adayları", "Olası mükerrerler" |
| Case review | `/gereksinimler/:id/caseler` | Analist | **P1** | Mevcut `.case-${durum}` sınıflarıyla (G13): şerit §4.4 tablosu; `approved/published/rejected/superseded` kartlar `--surface-2` zemin ve adım tablosu hücre dolgusu `6px 10px`; `draft` kartlar `--surface` (öne çıkar). Rozet yığını (G14): `.case-baslik .satir-ogeler > .cip ~ .cip-notr { background: none; border: 0; padding: 0 0 0 8px; border-left: 1px solid var(--border-soft); color: var(--text-2) }` (ilk `.cip` = durum çipi hap kalır; "Yerini yenisi aldı"/"Düşük risk" gibi nötr durum/risk çipleri ilk sırada değilse düzleşir — F2-D'de 1440 px ekran görüntüsüyle onaylanır) — ayraç `content` ile **değil** kenarla (pseudo metin erişilebilir ada girer). Özet `.metrik-izgara` şerit görünümü (§4.12) | Sekmeler yapışkan. `<details>` ile katlama **yapılmaz** (bölge sorguları). (v2'deki `data-durum` maddesi gereksiz — sınıf zaten var) | `Adımlar:` bölgeleri, `tablo-yigin`, `case-karar-kilit`, `case-baz*`, `.metrik`/`.metrik-deger` `/^—$/`, meter "Case kabul oranı", "Onayla/Düzelt/Reddet/Yeniden aç" |
| Koşular | `/kosular` | Sunucu | **P1** (Adım 8, L2, L4) | Tetik/kaynak nötr (§4.6); durum renkli; kimlik mono; satır hover. **Tetik açıklamaları** (`ul.tetik-aciklamalari`, Ek B): `margin: -10px 0 14px` `.sayfa-basligi`'nın alt boşluğuna (bugün 18 px) yaslanıyor — §4.3 başlık boşluğu değişirse negatif marj aynı oranda yeniden ayarlanır; metin `--text-2` (`.soluk` → `--muted` değil, 2 satırlık okunur açıklama), ≤100ch. Açıklama zaten görünür ve `aria-describedby` bağlı → bu iki düğmeye F3'te `.dugme-neden` **eklenmez** | — | süzgeç etiketleri, checkbox "Kasıtlı kırma koşuları", bölge "Koşular tablosu", düğmeler "Deploy sonrası testleri koş" / "Gece koşusunu şimdi başlat", liste "Tetik düğmeleri", `#kosular-gece-aciklama` / `#kosular-deploy-aciklama` |
| Kontrol Kulesi | `/kontrol-kulesi` | Sunucu | **P1** | Kart şerit başlıkları (tablolar); `.metrik-izgara` stat şeridi görünümü; grafik ≤180 px; boş durumlar tek stil; `align-items:start`; **REPLAY'de maliyet "REPLAY — ölçülmedi"** (§4.12, MVT DOM) | **KPI şeridi**: Geçme oranı · Açık defect adayı · Case kabul · Script ilk review · Hazırlık kazancı. **Maliyet şeride girmez.** REPLAY'de mevcut `Olculmedi` metinleri ("REPLAY: hesaplanmaz", "ölçülmüş baz yok") **aynen** kullanılır — yeni metin yok (`duman.spec.ts:499`, `faz5.test.tsx:259` kilitli). Öğeler kartlardan **taşınır, kopyalanmaz**; testid ve (i) ipucu birlikte taşınır; "Geçme oranı" h2 olarak tek kalır | `gecme-orani`, `hazirlik-kazanci`, `hazirlik-TPD-1`, `kazanc-kapsam`, başlık "Geçme oranı", bölge "AI katkısı", "Karne tablosu", "Karne (story ve uygulama alanı)", kapsamsız `getByText("ölçülmüş baz yok")` (tekil kalmalı) |
| Triage | `/hatalar/:id` | Mühendis/Testçi | **P1** (demo Adım 12 ve L3) | Kartlar üst hizalı; onarım aşamaları dikey zaman çizelgesi; "Onarım PR'ı aç" pasif görünüm (§4.5). Görsel kapı: 1152 px'te sınıf + sinyaller + onarım kartı ilk ekranda | — | `triage-sinif`, bölge "Locator yoklaması (locator-probe)", liste "Onarım hattı", "Karar kaynağı: deterministik kural" |
| Denetim | `/denetim` | Sunucu | P2 | Hash mono; "✓ Zincir doğrulandı" yeşil, belirgin | — | "✓ Zincir doğrulandı" / "✗ Zincir kırık" |
| Demo kontrolleri | `/demo` | Sunucu | **P1** (L1) | Kart başlığı artık **"Test bakımı demosu"**; düğme **"Buton kimliğini değiştir"** `tehlike` (onaydaki "Evet, buton kimliğini değiştir" de `tehlike`); onay grubu kartı. Kartın başındaki "Bu demo ne gösteriyor? Test bakımı" bilgi kutusu (`locator-aciklama`, numaralı 3 madde) §4.9 düzeltmesiyle: satır içi vurgular satırda kalır, başlık üstte, liste girintili; kutu `--info-bg` (K10: gökmavisi yalnız bilgi kutusunda). Kart altındaki **"Teknik ayrıntı"** `<details className="soluk kucuk">` (plan sonrası) kart katlama değildir (K8 kartın kendisi için), içerik ayrıntısıdır: `summary` `--text-2` 500, varsayılan işaretçi, odak global halka | — | grup **"Buton kimliği değiştirme onayı"** (`5a791de` ile "Locator kırma onayı" adından değişti), liste "Locator kırılması ilerlemesi", liste "Demo olay günlüğü", exact "Buton kimliğini değiştir", "Evet, buton kimliğini değiştir", testid `locator-aciklama`, `on-kosul-hazir` |
| Giriş | `/giris` | — | P2 | §4.14 (demoda seyirci görmez) | `<strong>Probe</strong>` | "Oturum aç", etiketler, "Giriş yap" |
| Gereksinimler | `/gereksinimler` | Analist | P2 | Tablo; "Serbest metin" nötr | — | "Gereksinimler tablosu", `tablo-yigin` |
| Koşu detayı | `/kosular/:id` | Sunucu/Mühendis | **P1** (Adım 9 Sauce, Adım 10 raporlar, L2 "Başarısızlıklar ve triage", L4 "36/36") — plan sonrası büyüdü (`KosuSonuclari.tsx`, Ek B) | Kart sırası değişmez (Raporlar ve bağlantılar → metrik kartı (`.metrik-izgara`, §4.12 stat şeridi; L4 "36/36" burada okunur) → Başarısızlıklar ve triage → CI adımları → Test sonuçları). "Test sonuçları" ve "CI adımları" kartlarında şerit başlık (§4.4; Test sonuçları kartında başlıkla tablo arasında süzgeç çubuğu durur — şerit yine başlığa uygulanır, süzgeç çubuğu şeridin altında 12 px). Süzgeç: segment düğmeleri (§4.5), `Ara`/`Dosya`/`Sırala` §4.8 formu, sayaç `role="status"` `--muted` tabular-nums, 390 px'te alt alta sarar. Açılır ayrıntı satırı §4.7. `.ci-meta` `dl` iki sütun `dt --muted`; 390 px'te tek sütun. Günlük (`.kod-blok.gunluk`) §4.11 kod kutusu. `SauceCipi` başlık çipleri arasında (§4.6). "(GitHub artefaktında)" bağlantıları normal bağlantı stili | — | "Raporlar ve bağlantılar", liste "Kanıt bağlantıları", kart "Başarısızlıklar ve triage", bölgeler "Test sonuçları tablosu", "CI adımları", `Test ayrıntısı: …`, `Adımlar (deneme N)`; gruplar "Test sonucu süzgeci", "Duruma göre"; düğmeler "Tümü (n)", "Başarısız (n)" … (`aria-pressed`); searchbox "Ara"; listeler "Yerel CI adımları", "GitHub işleri"; `dl` "ci-meta.json özeti"; img `Ekran görüntüsü: …`, video `Video: …`; bağlantılar `/… \(GitHub artefaktında\)/`, `/Playwright HTML raporu( \(GitHub\))?/`, "Playwright trace'i indir"; metinler "Sauce koşmadı: …", "geçti"/"kaldı", "Süzgece uyan test yok."; `[data-hatali='1']`, `.dugme-metin` |
| Yayın | `/gereksinimler/:id/yayin` | Analist | P2 | Tablo | — | `yayin-*` |
| Claude Code | `/claude-code` | Analist | P3 | Kurulum adımları zaman çizelgesi | — | "Token oluştur", bölge "Token listesi" |
| 404 / yetki yok | — | — | P3 | Boş durum stili | — | "Sayfa bulunamadı", "Bu ekran için yetkiniz yok." |

**Kapsam dışı bırakılan öneri:** Koşular üstüne "Toplam/Geçti/Başarısız" stat şeridi — yeni görünür metin;
ayrı onay gerekir.

---

## 6. Uygulama fazları

### 6.1 Minimum Değerli Teslim (MVT — demo öncesi)

**MVT = F1 + F2 (A–D birlikte) + aşağıdaki küçük DOM değişiklikleri + demo senaryosu düzeltmeleri.**
Yol haritası ve akış tür kodlaması, pasif düğme görünümü, ÖRNEK VERİ bandı, kabuk imzaları, Case review
düzeni (G13/G14, CSS), Kule stat şeridi görünümü dahil.

**MVT'deki DOM değişikliklerinin tam listesi** (başka yok; her biri §9 taramasından geçer):

| # | Dosya | Değişiklik |
|---|---|---|
| 1 | `src/lib/tema.ts` (yeni), `main.tsx`, `Kabuk.tsx` (`useTema`), `index.html` | Tema (§3.1), font importları, favicon |
| 2 | `vite.config.ts`, `package.json`, `package-lock.json` | `assetsInlineLimit`, iki font paketi |
| 3 | §4.6 ton listesindeki dosyalar | `ton` prop değerleri |
| 4 | `YolHaritasi.tsx:71` | `data-tur={a.tur}` |
| 5 | `BulguKarti.tsx:105` | `data-durum={bulgu.durum}` |
| 6 | `KontrolKulesi.tsx:146-153` | REPLAY'de maliyet `Olculmedi` (§4.12) |
| 7 | `e2e/duman.spec.ts`, yeni birim testler, `src/api/mock/fixtures.ts` (yalnız örnek veri, Ek B2) | §8 test değişiklikleri |

**Demo senaryosu düzeltmeleri (MVT'de, demo öncesi)** — `CANLI-DEMO-SENARYOSU.md`; satırlar alıntıyla
`grep -n` ile bulunur (§1.3):
- ~~"Sol menü **Case review**" / "Sol menü **Yayın**" → TPD-1 başlığındaki düğmeler~~ — **yapıldı** (`5a791de`).
- ~~"benzerlik **high**" → "yüksek olasılık"~~ — **yapıldı** (`5a791de`, ≈534).
- "gri **"Kod"** kutusu" (≈204) → "'Kod' etiketli kod kutusu".
- "4. adımın kesikli halkası" (≈254) → "kesik **kenar** = AI içerir; kare = insan kapısı".
- "Mor adımlar AI taslağı, yeşil adımlar insan kapısı" (≈168) — çizimle uyumlu, değişmez.
- Adım 11 (Kontrol Kulesi) **"Beklenen boşluklar"** maddesi (≈429-430, plan sonrası eklendi): "**Maliyet
  $0,00**" → "**Maliyet 'REPLAY — ölçülmedi'**" (MVT DOM #6 ile ekranda artık $0,00 görünmez; madde değişmezse
  sunucu ekranda olmayan bir sayıyı arar). Aynı maddedeki "REPLAY'de model çağrısı yok, süre ve ücret ölçülmez"
  cümlesi kalır — v4'teki "Söyle paragrafına ekleme" bununla karşılandı, ayrıca eklenmez.
- L1 / Bölüm 6 / sorun giderme metinleri "Buton kimliğini değiştir" adını zaten kullanıyor — tasarım
  değişikliği gerektirmez; §9 kilidine alındı.
- §1.3 hazırlık: tema her profilde elle seçilir; projektör soluksa → açık.

Demo sonrası: F3 (ikon seti, `<strong>Probe</strong>`, avatar, `ornek-veri-tam`, `.dugme-neden`) ve F4
(Kule KPI şeridi, Gereksinim bölüm gezgini, Case review yapışkan sekmeler).

### 6.2 Fazlar

**F0 — Hazırlık (kod yok)**
1. Dal `ui-yenileme` (`dev`'den). `core/` altındaki commit'lenmemiş başka çalışmalara dokunulmaz.
2. Taban: `npm test` (sayıyı kaydet), `npm run typecheck`, `npm run build`, `npm run build:mock`,
   `npm run e2e`; axe **incomplete** düğüm sayıları; `wcag21aa`+`wcag22aa` etiketleriyle **deneme** axe
   koşusu (ihlaller listelenir, F2'de düzeltilir — örn. bildirim kapat 16 px).
3. `e2e/ekranlar/*.png` kopyası `e2e/ekranlar-once/` (commit'lenmez); `rehearsal/ui` `npm run typecheck`.

**F1 — Altyapı (görseli değiştirir; tek PR, üç commit)**
1. Fontlar: `npm i -E @fontsource-variable/inter@5.3.0 @fontsource-variable/jetbrains-mono@5.3.0`;
   `main.tsx`'te `import "@fontsource-variable/inter/wght.css"` ve jetbrains eşdeğeri (`styles.css`'ten önce).
   `vite.config.ts`: `build.assetsInlineLimit: (f) => (/\.woff2?$/.test(f) ? false : undefined)` — JetBrains
   Mono'nun 2 KB'lık kiril-ext dosyası aksi halde `data:` URI olur ve CSP'ye takılır. Kapı:
   `grep -c 'data:font' dist/assets/*.css` = 0.
2. Tema: `src/lib/tema.ts` + göç (§3.1), `main.tsx` önyükleme, `index.html` `data-theme="dark"`, `useTema`
   bu modülü kullanır; mount'ta yazma kaldırılır. **Birim testler** §3.1'deki liste.
3. Favicon: altıgen SVG, `index.html`'de URL-kodlu `data:image/svg+xml` (`#`→`%23`, tek tırnak).
   `<title>` aynı.

**F2 — Tasarım sistemi (CSS; tek PR olarak birleşir, kısmi F2 yayına çıkmaz)**

Satır numaraları 2026-11-03 tabanına (2420 satır) göredir; F2 başında taban commit kimliği PR'a yazılır ve
satırlar o commit'te yeniden doğrulanır. **`5a791de`'deki kayma (2520 satır):** 525–533 `.tetik-aciklamalari`
eklendi (B/C sınırı: C'ye girer) → ≥525 satırlar **+9**; 1390'da `.hata-mesaji`'ya bir satır → ≥1391 satırlar
**+10**; 2431–2520 yeni **"Koşu detayı: test sonucu ayrıntısı"** bloğu → **D şeridi** (§4.5 `.dugme-metin`
ve §4.7 ayrıntı satırı kuralları burada yazılır). Örnek: `.dugme:disabled` 609 → 618, `.yh-adim … .yh-no`
2350-2369 → 2360-2379, `.kirma-sonucsuz .kirma-ikon` 1786 → 1796.

| Şerit | `styles.css` bölümleri (mevcut satırlar) | İçerik |
|---|---|---|
| A (önce, ~½ gün) | 1–248 (token + temel) + **447–456 (`.icerik`) ve 500–505 (hareket azaltma)** | §3 token'ları, tema blokları, tipografi, odak, bağlantı, `.icerik`, hareket azaltma, forced-colors, `::selection`, kaydırma çubuğu |
| B | 249–506 (kabuk), 1104–1143 (giriş), 2084–2150 (bildirim) — **447–456, 500–505, 2141 ve 2146 hariç** | §4.1, §4.2, §4.14, §4.15 |
| C | 507–1103 (yapı, düğme, rozet, durum, tablo, form) + D aralığındaki bileşen tanımları: 1391 (`.karar-ozet .cip`), 1578–1622 (metrik/ilerleme), 1885 (`.rozet-degerlendirme`), 2019 (`.kule-izgara > .kart`), 2027 (`.buyuk-sayi`), 2034–2070 (`.grafik*`), 2146 (`.dugme-ek`), 2164 (`.yerel-kontrol .uyari-kutusu`), 2195–2211 (`.filtre-cubugu*`), 2235 (`.olculmedi`), 2275 (`.buyuk-sayi-kucuk`), 2305 (`.hazirlik-tablo td .cip`) | §4.3–§4.9, §4.12, §4.13 |
| D | 1144–1267 (akış), 1268–1496 (gereksinim, kod — `.kod-blok` 1367 dahil), 1497–2083 (case, kod üretimi, triage, kule), 2141 (`.adim-liste .kod-blok`), 2151–2420 (Demo-B, Faz 5, yol haritası), **+ yeni blok 2431–2520 (Koşu detayı, `5a791de` numarası)** — C'nin listelediği satırlar hariç; TSX DOM değişiklikleri (§6.1 #3–#6) | §4.10, §4.11, §5 MVT sütunu, §4.6 |

Şeritler aynı dosyada **ayrık satır aralıklarında** çalışır; Git ayrık parçaları birleştirir. Şerit sınır
satırlarına ve başka şeridin aralığının ±3 satırına yalnız o aralığın sahibi dokunur; yeni kural gerekiyorsa
kendi aralığının sonuna eklenir. Çakışma olursa birleştirme sırası A → C → B → D. Her şerit sonunda iki temada 1440, 1152 (≈1440@%125) ve 390 px gözden
geçirme.

**F3 — Küçük markup (demo sonrası)** §4.16 ikonlar, marka `<strong>`, avatar (`.kullanici` içinde,
`.kullanici-ad`'ın **kardeşi**, `aria-hidden`, baş harf ad/rol metnini tekrarlamaz), `ornek-veri-tam`,
`.dugme-neden` (§4.5 ön koşulu).

**F4 — Ekran düzenleri (demo sonrası)** §5 "Demo sonrası" sütunu; her ekran ayrı commit.

**F5 — Kapanış** Senaryo düzeltmeleri MVT'de yapıldı (§6.1); F3/F4 sonrasında senaryo yeniden okunur ve
konum ifadeleri doğrulanır. `README.md`'ye kısa "Görsel dil" bölümü. Ekran görüntüleri yeniden üretilir.

### 6.3 Neden stil dosyası bölünmüyor (karar K1)

Bölme (a) `inceleme.test.tsx:463-467`'i kırar, (b) anlamsal dosyalara taşıma tekrar tanımlar yüzünden
kaskadı değiştirir, (c) bitişik satır aralıklarıyla bölmek ise sahiplik sorununu çözmez. Paralellik ayrık
satır aralıklarıyla sağlanır; F2 sonunda dosya yine tek parçadır. Bölme gerekirse ayrı, sıfır-fark bir PR
olarak demodan sonra değerlendirilir (kapı: `cat` birleşimi orijinalle `diff` boş + derlenmiş CSS aynı +
test güncellemesi).

### 6.4 Donma ve güvenli durma noktaları

- Güvenli durma: **(a)** F1 sonu, **(b)** F2'nin tamamı. Yarım F2 `dev`'e alınmaz.
- Demodan **3 iş gününden** kısa süre kala hiçbir görsel değişiklik birleştirilmez; F3/F4 demodan sonra.
- Her birleştirmeden sonra prova kapısı (§8) ve **yedek video yeniden kaydedilir** (eski görünümdeki video
  canlı ekranla çelişir).
- Demoyu tehdit eden kapsam ertelenir (anayasa).

---

## 7. Erişilebilirlik ve hareket

- Kontrast §3.3; yeni çiftler aynı hesapla.
- Odak: `outline: 2px solid var(--focus); outline-offset: 2px`; mevcut `:focus-visible { border-radius: 3px }`
  (204) **silinir** (haplarda/düğmelerde köşeyi bozuyor). `outline: none` gerekçesiz yok.
- Bağlantılar: paragraf ve gövde metnindeki `a` **altı çizili kalır** (accent/text oranı koyu 2,64 — renk tek
  başına yetmez). Tablo/eylem sütunu, menü, düğme ve hap biçimli bağlantılar çizgisiz, hover'da çizili.
- Renk tek başına anlam taşımaz: haplar metinli; akış türü biçim + renk + görünmez metin; kart şeridi
  yanında durum metni.
- Hareket azaltma bloğu (500–505) genişler: `animation-iteration-count: 1 !important`,
  `.dugme-birincil:hover:not(:disabled) { transform: none }` (kalkış kuralıyla **aynı seçici**; `.dugme:hover`
  özgüllüğü yetmez); nabız noktası statik; döner simge statik + `aria-busy` mevcut.
- `@media (prefers-reduced-transparency: reduce)` ve `backdrop-filter` desteği yokken opak zemin.
- `@media (forced-colors: active)`: ilerleme dolgusu, akış daireleri, noktalar `CanvasText` 1 px kenar.
- Hedef boyutu ≥24×24 (bildirim kapat).
- Koyu temada uzun metin blokları `--text-2` değil `--text`; ışıma (halation) şikâyeti olursa uzun gövde
  metni için `#e4e4f2` (16:1) değerlendirilir.
- "İçeriğe atla" (`.atla`) `--accent-solid` zemin + beyaz.

---

## 8. Doğrulama kapıları (her PR)

| Kapı | Komut | Ölçüt |
|---|---|---|
| Birim | `npm test` | F0 tabanından az değil + F1 tema testleri |
| Tip | `npm run typecheck` | 0 hata |
| Derleme | `npm run build`, `npm run build:mock` | 0 hata; `dist/assets/*.woff2` var; `grep -c 'data:font' dist/assets/*.css` = 0 |
| Duman e2e | `npm run e2e` | Tümü geçer (axe, konsol hatası 0, taşma 0) |
| **axe döngüsü yeniden yazılır** | `duman.spec.ts:334-361` | Tema `emulateMedia` ile değil: ilk `page.goto`'dan önce `page.addInitScript(t => { localStorage.setItem("tp-tema-v","2"); localStorage.setItem("tp-tema", t) }, "acik"\|"koyu")`. Her sayfada axe'tan önce `expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme))` beklenen `light`/`dark`; `acik`/`koyu` turunda `html` `data-theme` = `light`/`dark`. Üçüncü tur: `sistem` + `emulateMedia({colorScheme:"light"})`, yalnız 1440 px, `html` `not.toHaveAttribute("data-theme")`. `analyze()` öncesi `page.addStyleTag({ content: ".kabuk::before,.giris-sayfa::before,.giris-sayfa::after{display:none}" })` (büyük dekoratif pseudo zeminler axe kontrastını `incomplete`'e düşürmesin). Eklenen sayfalar ve bekleme işaretleri: `/giris` (**oturum açmadan önce**, her turda) → button "Giriş yap"; `/gereksinimler` → region "Gereksinimler tablosu"; `/kod` → region "Üretilen testler tablosu"; `/kosular` → region "Koşular tablosu"; `/kosular/run-107` → region "Raporlar ve bağlantılar"; `/bug-taslaklari` → heading "Bug taslakları"; `/demo` → **aynı turda `girisYap(page, "sunucu")` sonrası** (rol `presenter` ister, `App.tsx:113-119`), group "Buton kimliği değiştirme onayı". `color-contrast` **incomplete** düğüm sayısı sayfa başına raporlanır ve F0 tabanını aşamaz (sayısal kapı). Etiketler, F0 denemesindeki ihlaller düzeltildikten sonra `wcag21aa`, `wcag22aa` eklenir |
| Açık tema görüntüleri | aynı döngü | 1440 px'te `e2e/ekranlar/acik/<ad>.png` |
| **Koşu detayı kapsamı** (Ek B) | F0'da `src/api/mock/fixtures.ts` `run-107` | Örnek veride `denemeler`/`adimlar`/`ekler`/`github`/`sauce_durum` **yok** (`run-107` 2026-11-01'den beri değişmedi) → yeni Test sonuçları ayrıntısı, CI adımları ve Sauce çipi ne ekran görüntüsüne ne axe'a giriyor. F0'da `run-107`'ye bir başarısız sonucun deneme+adım+ek (resim) verisi, `adimlar` ve `sauce_durum: "error"` eklenir — önce `grep -rn "run-107" src e2e` ile sayım/metin testleri kontrol edilir (`lib.test.ts`, `sayfalar.test.tsx`); kırılırsa ayrı `run-108` fikstürü. duman axe turunda `/kosular/run-1xx` sayfasında ilk test adı düğmesine tıklanıp `region "Test ayrıntısı: …"` beklenir, sonra axe. Ek resmi `img-src 'self'` altında aynı kökenden gelir (CSP değişmez) |
| "Mobil görünüm ve koyu tema" testi | `duman.spec.ts:246-263` | `emulateMedia({colorScheme:"light"})` + `html[data-theme=dark]` doğrulaması (OS açıkken de varsayılan koyu) |
| Font zamanlaması | `girisYap` ve ölçüm öncesi | `await page.evaluate(() => document.fonts.ready)` |
| %125 zoom eşdeğeri | yeni kısa e2e | 1152×720 viewport'ta Script detayında `getByRole("region", { name: "Kırarak doğrula" })` PR kartının **sağında** (aynı adlı düğme var — rol ile seç) |
| Prova | Bir kez: `make reset` + `rehearsal/ui: npm run canli` (yığın dolar, korunur). Her F2/F3/F4 PR'ında: `docker compose build review-portal && docker compose up -d review-portal` → `rehearsal/ui: npm run typecheck && npm run tur` | Geçer. `tur` boş yığında başarısız olur (dolu demo akışı bekler). Demo öncesi bir kez daha `make reset` + `npm run canli` |
| CSP + font | `canli.spec.ts`'e test | Konsolda `/Content Security Policy/` 0; `document.fonts.check('16px "Inter Variable"')` true. F5'te `DEMOA_UI=1 DEMOB_UI=1` |
| Görsel | `e2e/ekranlar` önce/sonra, `screenshot({ animations: "disabled" })` | Ekran sahibi onayı; yan yana `site-home` / `dash-app` ile aile karşılaştırması. Aynı makine + Playwright 1.64.1 Chromium; CI ile yerel karşılaştırılmaz; eylem sonrası (saatli) ekranlar karşılaştırmaya girmez |
| Projektör | sunum makinesi, %125 zoom, iki tema | Koyu: kart sınırları, tablo ayraçları, mor/yeşil ayrımı seçilir. Açık: kart ayrımı (`--border` zemine ~1,2:1, ayrım `--shadow`'a kalıyor) seçilir. Seçilmeyen temada sorun varsa demo diğer temayla yapılır |

---

## 9. Test-etki analizi (her markup/ton değişikliği öncesi)

```bash
cd testing-probe
# 1) Değişen metin/sınıf/testid/ad testlerde ve provada geçiyor mu
grep -rn "<metin|sınıf|testid|ad>" review-portal/src --include='*.test.*' review-portal/e2e rehearsal/ui/*.ts
# 2) title metinleri görünür metin olarak aranıyor mu (.dugme-neden)
grep -rn "Bu işlem için gereken rol\|getByTitle\|toHaveAttribute(\"title\"" review-portal/src review-portal/e2e rehearsal/ui/*.ts
# 3) Ad eşleşmeleri (ikon/strong eklerken)
grep -rn "getByRole(\"\(link\|button\|region\|list\|navigation\|heading\|group\|meter\)\"" review-portal/src --include='*.test.*' review-portal/e2e rehearsal/ui/*.ts
# 4) Rol sayımları (yeni article/list/region/status eklerken)
grep -rn "getAllByRole\|getByRole(\"article\")\|toHaveCount" review-portal/src --include='*.test.*' review-portal/e2e
```

**Kilitli sınıflar:** `tablo-yigin` (+ `td[data-etiket]`, 640 px kuralı metni), `tablo-sarici`, `cip`,
`cip-uyari`, `rozet-replay`, `rozet-replay-miss`, `rozet-dogrulandi`, `kirma-sonucsuz`, `kullanici`,
`kullanici-ad`, `metrik`, `metrik-deger`, `kod-vurgu`, `tk-metin`, `mark.kaynak-deger`, `akis-ad`,
`ok-metin`, `dugme-birincil`, `dugme-ikincil`, `ajan-ekran`, `yan-menu`, `gorunmez`, `kanit`, `kanit-baslik`,
`article.bulgu`, `sayfa-basligi`, `baslik-anahtar`, `#po-parola`.

**Kilitli erişilebilir adlar ve sayımlar:** tüm `data-testid`'ler; navigation "Ana menü", "14 adımlı
akıştaki ilerleme"; button "Menü", "Çıkış"; listeler "14 adımlı demo akışı" (14), "PR check'leri",
"Kırarak doğrulama zaman çizelgesi" (sıra), "Mükerrer adayları", "Locator kırılması ilerlemesi", "Demo olay
günlüğü", "Onarım hattı", "Kanıt bağlantıları" (`:scope > li`); bölgeler "Gereksinimler tablosu",
`Adımlar: …`, "Raporlar ve bağlantılar", "Önerilen değişiklik farkı", "Eşlenen adımlar tablosu", "Üretilen
testler tablosu", "Koşular tablosu", "Karne tablosu", "Token listesi", "Manuel baz değer", "Locator
yoklaması (locator-probe)", "AI katkısı"; grup "Buton kimliği değiştirme onayı" (eski adı "Locator kırma onayı"; §8 axe bekleme işareti de bu adla); bölge/liste "Test bakımı yolu" (yol haritası, eski adı "Locator kırılma yolu"); meter "Case kabul oranı"; heading
"Geçme oranı"; img `/^Kaynak: …/`; link "Story'yi aç →", "Kod üretiminde incele"; `getByRole("article")`
= 3 (`/gereksinimler/req-ft-1`); `.baglanti` `role="status"`; `ROTALAR` başlıkları; `Olculmedi` metinleri
"REPLAY: hesaplanmaz" (`duman.spec.ts:499` tam eşleşme), "ölçülmüş baz yok" (kapsamsız, tekil),
"REPLAY — ölçülmedi"; yol haritası `data-hal`. Prova dürüstlük kilidi: DOM'a "CANLI"/"live" yazılmaz (`prova.spec.ts:227-230`).

**Plan sonrası eklenen kilitler (Ek B, `5a791de`):** sınıflar `dugme-metin`, `test-ayrinti-satiri`,
`pw-adim-hata` (+ `[data-hatali='1']`), `kirma-sonucsuz` (+ `data-beklenmedik`), `tetik-aciklamalari`;
düğmeler "Buton kimliğini değiştir", "Evet, buton kimliğini değiştir", "Deploy sonrası testleri koş", "Gece
koşusunu şimdi başlat", "Tümü (n)"/"Başarısız (n)" … (`aria-pressed`); kart başlıkları "Test bakımı demosu",
"Başarısızlıklar ve triage", "CI adımları", "Test sonuçları"; bölgeler "Test sonuçları tablosu", `Test
ayrıntısı: …`, `Adımlar (deneme N)`; gruplar "Test sonucu süzgeci", "Duruma göre"; listeler "Tetik
düğmeleri", "Yerel CI adımları", "GitHub işleri"; `dl` "ci-meta.json özeti"; searchbox "Ara"; checkbox
"Kasıtlı kırma koşuları"; img `Ekran görüntüsü: …`, video `Video: …`; metinler "Sauce koşmadı: …", "Sauce:
geçti", "(GitHub artefaktında)", "Süzgece uyan test yok.", "✓ Doküman son hâl" (şapkalı â), yol haritası L2
"Buton kimliğini değiştir (add-to-cart → cart-add)"; id `kosular-gece-aciklama`, `kosular-deploy-aciklama`
(`aria-describedby` hedefi — kaldırılmaz/yeniden adlandırılmaz).

**Review turu 1 kilitleri:** navigation "Sayfa bölümleri" (gereksinim detayı; ≤860 px gizli, 861–1279 px
yapışkan yatay şerit, ≥1280 px yapışkan sütun — yani ≥861 px'te görünür) bağlantı metinleri "Doküman", "PO
teyidi", "Manuel baz değer", "Ön inceleme soruları", "Tutarlılık bulguları" kart başlıklarıyla aynıdır ve DOM'da
içerikten önce gelir → kart başlıkları yalnız `getByRole("region", { name })` ile aranır, `getByText` ile
aranmaz: ≥861 px'te `getByText(…).first()` gezgin bağlantısını bulur ve kart kaybını yakalamaz, ≤860 px'te
gizli bağlantıyı bulur (`duman.spec.ts` "bölüm gezgini" testi). `.dugme-neden` grup başına tekildir: aynı `.eylemler` /
`.satir-ogeler` içinde eş metinli neden bir kez çizilir, her düğmenin `aria-describedby`'si ona bağlıdır.

**Review turu 2–3 kilitleri:** id `kirma-kapali-neden` (`ScriptDetay.tsx` `aria-describedby` hedefi;
`dugmeNeden.test.tsx` birebir arar — kaldırılmaz/yeniden adlandırılmaz). `main#ana-icerik` `tabIndex=-1`:
"İçeriğe atla" hedefi ve açık mobil menüden gezinince odak buraya taşınır (`duman.spec.ts` mobil menü testi,
`sayfalar.test.tsx`). Açık mobil menü (≤860 px) kipseldir: menü düğmesi ile `nav#yan-menu` dışı (`.atla`,
`.marka`, `.ust-sag`, `#ana-icerik`) `inert`, açılışta odak ilk menü bağlantısında, Tab/Shift+Tab menü ile
menü düğmesi arasında döner, Escape kapatır ve odağı düğmeye verir (aynı testler). `src/tema-on.js`: ilk boyama
betiği, `src/lib/tema.ts` ile aynı kurallar (`tema.test.tsx` "tema-on.js" testleri kaynağı `?raw` okur);
`vite.config.ts` `tp-tema-on` eklentisi derlemede küçültüp `<head>` sonuna klasik `<script src>` ekler (satır
içi değil, CSP). Stil kancası sınıfları (test kimliği değil, styles.css bağlı; yeniden adlandırılırsa CSS
birlikte): `insan-kapisi` + `kapi-gecti`/`kapi-bekliyor` (PO teyidi kartı, `merge-kapisi`), `test-sonuclari`
(koşu sonuç tablosu), `yh-sonraki` (testid ile aynı ad). Giriş markası `<strong data-metin="Probe">`: gradyan
bindirme kelimeyi bu nitelikten okur (`content: attr(data-metin) / ""`).

**Yeni markup kuralları:** `article`, `list`/`listitem`, `region`, `status` rolü eklenmez (eklenirse
benzersiz ad + sayım testleri tek tek kontrol); `aria-current="step"` yalnız akışta; yeni görünür metin
eklenmez; CSS ikon `content: ""`.

---

## 10. Riskler

| Risk | Olasılık | Önlem |
|---|---|---|
| Açık tema denetimsiz kalır (axe döngüsü tek temaya düşer) | Yüksek → giderildi | §8 döngü yeniden yazımı + `data-theme` doğrulaması |
| Eski `tp-tema=sistem` kaydı koyu varsayılanı gizler | Yüksek → giderildi | Göç eski değeri **siler** + mount'ta yazma yok + iki ardışık okuma birim testi; demo profillerinde elle seçim |
| axe dekoratif zeminler yüzünden kontrastı ölçemez | Orta → giderildi | Pseudo zeminler axe öncesi gizlenir; `incomplete` sayısal kapı |
| MVT kapsamı "yalnız CSS" sanılıp yol haritası tür kodlaması sessizce düşer | Orta → giderildi | §6.1 DOM değişiklikleri tam listesi |
| `data:` font CSP'ye takılır | Orta → giderildi | `assetsInlineLimit` + grep kapısı + canlı CSP testi |
| Kontrast ihlali | Orta | §3.3 iki bağımsız hesap; §3.2 kuralları |
| Projektörde koyu tema soluk | Orta | Katman/kenar ayrışması; projektör kapısı; tek tık açık tema |
| Tekrar tanımlar yeni stili ezer | Orta | §6.2 şerit tablosunda satırlar listelendi |
| Font/boşluk değişimi mobil ölçüm testlerini kırar | Orta | `document.fonts.ready`; F2 sonrası dört ölçüm testi ayrıca |
| Yarım F2 karışık görünüm | Düşük | F2 tek birleştirme |
| Demo anlatısı bozulur | Düşük | §1.3 korunur; F4 demodan sonra; F5 senaryo düzeltmesi |
| `backdrop-filter` yavaş/eksik | Düşük | Yalnız üst çubuk ve giriş kartı; `-webkit-` + yedek |
| Portal ve senaryo yenileme sırasında da değişiyor (13:09–14:54 arası 7 portal commit'i; ad/metin değişiklikleri) | **Yüksek** | Ek B taraması F0'da tekrarlanır: `git log <plan-tabanı>..HEAD -- review-portal docs/CANLI-DEMO-SENARYOSU.md`; yeni ekran/sınıf/ad → §5 + §9'a eklenir; satırlar alıntıyla bulunur |
| Yeni ekranlar örnek veride boş kalır, görsel kapıdan kaçar | Orta | §8 "Koşu detayı kapsamı" satırı |

---

## 11. Kabul ölçütleri

1. Varsayılan açılış, `site-home.png` ve `dash-app.png` ile yan yana konduğunda aynı aileden görünür
   (gradyan çizgili üst çubuk, ortam ışıması, indigo vurgu, Inter, hap rozetler); açık tema rapor ekranı
   dilindedir.
2. G1–G19 için önce/sonra kanıtı (MVT kapsamındakiler MVT'de; F3/F4 kalemleri demo sonrası).
3. Mor yalnız AI/REPLAY'de; yol haritasında daire = tür, "tamam" yeşil değil; akış türü biçimle de ayırt edilir.
4. §8'deki tüm kapılar yeşil; birim sayısı F0 tabanından az değil.
5. §9 kilitlerinin hiçbiri değişmemiş; taramalar PR açıklamasında.
6. Demo senaryosu (F5 düzeltmeleriyle) değişmeden yürür; yedek video yeni görünümle.
7. Yeni bağımlılık yalnız iki OFL font paketi (sabit sürüm).

---

## 12. Kararlar (önceki açık sorular)

| # | Karar | Gerekçe |
|---|---|---|
| K1 | Stil dosyası bölünmez | §6.3 |
| K2 | Varsayılan tema **koyu**; açık tema birinci sınıf; demo teması projektörde seçilir | Marka; tasarımcı + ürün |
| K3 | "İnceleme portalı" alt adı kalır | Metin değişikliği kapsam dışı |
| K4 | Mor yalnız AI; AI olmayan çipler nötr; REPLAY biçimle ayrılır | Tasarımcı + ürün |
| K5 | KPI şeridinde Maliyet yok; REPLAY'de para/süre sayısı yok | Anayasa (ölçülmemiş sayı söylenmez) |
| K6 | MVT demodan önce; F3/F4 demodan sonra; 3 iş günü donma | Ürün |
| K7 | Akış ve yol haritasında tür = biçim + renk; durum ✓ + hap | Erişilebilirlik + demo satır 251 (v4'te 214) |
| K8 | Kart katlama (`<details>`) yok | Bölge sorguları ve prova |
| K9 | Yeşil = insan onayı verildi; çözülmüş/kapanmış kayıt nötr şerit | Tasarımcı + ürün (tur 2) |
| K10 | `cip-bilgi` indigo; gökmavisi yalnız bilgi kutusunda | Renk sayısını azaltma (tasarımcı) |
| K11 | Senaryo düzeltmeleri demo öncesi (MVT) | Ürün (tur 2) |

**Kullanıcıya açık kalan tek soru:** demo tarihi (donma kuralı buna göre işler).

---

## Ek A — İnceleme günlüğü

| Tur | Rol | Engelleyici | Önemli | İşlenen başlıca değişiklikler |
|---|---|---|---|---|
| 1 | Marka/UX tasarımcısı | 2 (katman ayrışması; Case review reskin) | 14 | Katman/kenar değerleri; gradyan çizgi, ortam ışıması, section-badge, şerit başlık, KPI şeridi yapısı; mor = AI; G12 düzeltmesi, G13–G19 |
| 1 | Ürün sahibi / demo sunucusu | 3 (Maliyet KPI; akış kesikli halka anlamı; yol haritasında yeşilin iki anlamı) | 9 | K5, K6, K7; MVT; donma kuralı; P1/P2 yeniden; insan kapısı kartları; demo senaryosu hata listesi; tema göçü ve profil ayarı |
| 1 | Erişilebilirlik uzmanı | 3 (`--accent` dolu zemin 2,98; axe döngüsü; akış ✓ kontrastı) | 8 | `--accent-solid` kuralı, `--on-ton`, `--border-input`, üst çubuk .92, hareket azaltma, hedef boyutu, bağlantı alt çizgisi, forced-colors |
| 1 | QA / test otomasyonu | 1 (açık tema axe sessizce kayboluyor) | 11 | §9 kilit listesi genişledi; glif kuralı (yalnız ☰ ☾ ☀ ◐ ↗); `.dugme-neden` önkoşulu; font zamanlaması; prova/CSP kapıları; taban sayısı |
| 1 | Frontend mühendisi | 2 (stil dosyasını okuyan test; bölme çelişkisi) | 8 | K1; `tema.ts` + göç; `assetsInlineLimit`; tema token'ları (`--hover`, `--ust-cubuk-bg` …); `.uyari-kutusu.ornek-veri-bandi`; `--glow` açık değeri; `-webkit-backdrop-filter`; `--select-ok` |
| 2 | Marka/UX tasarımcısı | 0 | 9 | Case review G13/G14 MVT'ye (mevcut `.case-*` sınıfları); `.metrik-izgara` stat görünümü; kabuk glifleri; akış: tamam dolgusu `content-box`, AI+insan çizimi, şimdiki halka indigo; K9; dekoratif mor istisnası; KPI rengi; `--border-soft` |
| 2 | Erişilebilirlik uzmanı | 0 | 4 | AI+insan `border-image` yerine kesik kenar + inset halka; şimdiki halka 3:1; hareket azaltma seçicisi; `/giris` axe incomplete. Palet yeniden hesaplandı: tüm metin çiftleri ≥4,5 |
| 2 | Ürün sahibi / demo sunucusu | 0 | 6 | Yol haritası `data-tur` MVT'ye; insan kapısı şeridi duruma göre (K9); Kule maliyeti REPLAY'de "ölçülmedi"; Kod üretimi tonları değişmez; senaryo düzeltmeleri demo öncesi (K11); Triage P1 |
| 2 | QA / test otomasyonu | 0 | 5 | MVT DOM listesi (§6.1); axe pseudo zemin gizleme + incomplete kapısı; KPI'da mevcut `Olculmedi` metinleri; `colorScheme` doğrulaması; prova yığını hazırlığı |
| 2 | Frontend mühendisi | 0 | 4 | Göç eski değeri siler + mount yazmaz; `.kabuk { isolation: isolate }`; şerit tablosu sınırları ve eksik tekrar tanımlar; `.kart:has(> .kod)` + taşan şerit |
| 3 | Uygulayıcı mühendis (bağımsız son kapı; 498/498 test, ~60 atıf doğrulandı) | 0 | 8 | "PR açık" tonu çelişkisi ve eksik `vurgu` kullanımları; akış `tamam` kuralı (1203/1205); yol haritası yeşil çizgi kaldırıldı + eski durum kuralları silinir; insan kapısı bekliyor/geçildi seçicileri kesinleşti; bulgu 6 durum eşlemesi; Kule null koruması; axe `/demo` rolü + bekleme işaretleri; senaryo satır kaymaları (alıntıyla bulma kuralı). Küçükler: Case başlık seçicisi, kart dolgusu, şerit A/B sınırı, `--info` kalan kullanımlar, KPI rengi, atıf düzeltmeleri |

---

## Ek B — Plan sonrası kod değişikliği taraması (2026-11-03, v4 → v5)

v4 13:09'da kapandı. 13:09 – 14:54 arasında `review-portal/` ve demo senaryosuna 7 commit girdi
(`b210841`, `94aa954`, `c378925`, `9c71526`, `102597e`, `5a791de` ve senaryo commit'leri). Tarama:
`git log 022921e..HEAD -- review-portal docs/CANLI-DEMO-SENARYOSU.md`, plandaki 56 dosya:satır atıfının
`022921e` ile HEAD arasında satır metniyle karşılaştırılması, birim testler (512/512, `tsc` temiz).

| # | Değişiklik (commit) | Plana etkisi | İşlendiği yer |
|---|---|---|---|
| B1 | **Okunur test sonuçları ekranı** — `KosuSonuclari.tsx` (549 satır): süzgeç, açılır deneme/adım/ek ayrıntısı, CI adımları, günlük; `styles.css` sonuna 90 satır (`94aa954`, `5a791de`) | Koşu detayı P2 → **P1** (senaryo Adım 9, 10, L2, L4); yeni bileşen kalıpları (metin düğmesi, segment düğme, açılır satır, `<details>` blokları, ek görselleri) | §4.5, §4.7, §5 Koşu detayı, §6.2 D şeridi, §8 kapsam satırı, §9 |
| B2 | Örnek veride (`fixtures.ts` `run-107`) bu ekranın verisi yok | Duman ekran görüntüsü ve axe yeni ekranı **görmüyor** | §8 "Koşu detayı kapsamı" (F0) |
| B3 | "Locator'ı kır" → kart **"Test bakımı demosu"**, düğme **"Buton kimliğini değiştir"**, onay grubu **"Buton kimliği değiştirme onayı"**; yol haritası bölümü **"Test bakımı yolu"**; açıklama kutusu + "Teknik ayrıntı" `<details>` (`c378925`, `5a791de`) | v4'teki kilitler (exact "Locator'ı kır", grup "Locator kırma onayı") ve axe bekleme işareti **eskidi** | §5 Demo kontrolleri, §8 axe, §9 |
| B4 | **Mevcut CSS hatası:** `.uyari-kutusu strong { display: block }` yeni açıklama kutusundaki satır içi `<strong>`'ları satır başına atıyor | MVT'de düzeltilir (yalnız CSS); 36 `<Uyari baslik>` yerinde başlık üste geçer | §4.9 |
| B5 | `SauceCipi` (geçti/kırmızı/koşmadı/atlandı/sürüyor), CI adımı ve GitHub işi sonuç hapları, Türkçe iş sonuçları (`9c71526`, `5a791de`) | Ton listesine "değişmez" olarak eklendi (test sonucu hapı; §3.2 kural 6) | §4.6 |
| B6 | Koşular: tetik düğmelerine görünür açıklama listesi (`aria-describedby`), negatif üst marj; düğme başına ayrı meşgul durumu | Başlık boşluğu değişiminde marj yeniden ayarı; bu düğmelere F3 `.dugme-neden` eklenmez | §5 Koşular |
| B7 | "✓ Doküman son hâl" çipi: `pending_po` → `bilgi`, metin şapkalı "hâl" (`5a791de`) | v4 "yeşil" diyordu → kodun kararı esas alındı (K9 ile uyumlu: PO onayı henüz verilmedi) | §1.3, §5 Gereksinim detayı |
| B8 | Kırarak doğrulamada beklenmeyen sonuç ⚠ + `kirma-sonucsuz` (`c0eb3f9`); senaryoda "⚠ Yeşil · beklenmeyen sonuç" | Amber kuralı iki durumu da kapsamalı | §1.3, §5 Script detay |
| B9 | Senaryo: "Sol menü Case review/Yayın" ve "benzerlik high" düzeltmeleri **kullanıcı tarafından yapıldı**; Kule "Beklenen boşluklar"da yeni "**Maliyet $0,00**" maddesi | İki MVT senaryo maddesi kapandı; Maliyet maddesi MVT DOM #6 ile çelişir → güncellenir | §6.1 senaryo düzeltmeleri |
| B10 | Satır kaymaları: `Kosular.tsx` (+1, +85), `DemoKontrolleri.tsx` (+24), `GereksinimDetay.tsx` (+2), `inceleme.test.tsx` (+2), `faz5.test.tsx` (+18), `yolHaritasi.ts` (+45), `styles.css` (+9/+10, sonda +90); senaryo 35–75 satır | Atıflar güncellendi; değişmeyen atıflar (Kabuk, YolHaritasi.tsx:71, BulguKarti.tsx:105, KontrolKulesi.tsx:146-153, duman.spec.ts:334-361/499/508 …) doğrulandı | §1.3, §4.6, §5, §6.2, §9 |

Sonuç: engelleyici yok. MVT kapsamına eklenen tek iş B4 (CSS) ve B2 (F0 fikstürü); geri kalanı
spesifikasyon ve kilit güncellemesi. F0'da bu tarama `5a791de..HEAD` için tekrarlanır.

# Review Portal (Kontrol Kulesi)

React 18 + Vite 8 + TypeScript (strict), react-router. Arayüz metinleri Türkçe.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `npm run dev` | Geliştirme sunucusu; `/api` → `http://127.0.0.1:8000` (core-api) |
| `npm run build` | `tsc --noEmit` (uygulama + `tsconfig.test.json` ile testler) + üretim derlemesi (Docker imajı bunu kullanır) |
| `npm run typecheck` | Yalnızca tip denetimi (uygulama ve testler) |
| `npm run build:mock` | Tamamen örnek veriyle çalışan derleme (`VITE_MOCK=1`, arka uç gerekmez) |
| `npm test` | Vitest + Testing Library (API istemcisi, SSE, mock arka uç, bileşenler, ekranlar). `fixtures.test.ts` örnek veriyi repodaki kaynaklara karşı doğrular: demo-app dosya/satırları, golden REPLAY kayıtları, jira-sim seed'i, core durum makinesi ve olay adları; üretilen test kodu `demo-app/e2e` page object'lerine karşı tsc'den geçirilir (o dizinin `node_modules`'u yoksa bu tek test atlanır). |
| `PORTAL_LIVE=1 npx playwright test` | Canlı yığın testi (`e2e/canli.spec.ts`): çalışan portala (`PORTAL_URL`, varsayılan `http://127.0.0.1:8080`) analist olarak girer (`SEED_USER_PASSWORD`; `set -a; . ../.env; set +a`), gerekirse Jira'dan çeker, TPD-1'i açar; çekirdek `/requirements` sunmuyorsa açıkça başarısız olur (örnek veriye düşen sahte geçiş yok) |
| `npm run e2e` | Playwright duman testi: mock derlemeyi `vite preview` ile açar, tüm rotaları gezer, ekran görüntülerini `e2e/ekranlar/` altına yazar; her rolde ölü iç bağlantı, 390 px taşma ve axe (WCAG 2 AA, açık/koyu tema) denetimi yapar (ilk seferde `npx playwright install chromium`) |

**Detay sayfa iskeleti (DS-1):** detay sayfaları `src/components/DetaySayfasi.tsx` ile çizilir: özet kartı
(`OzetKarti`: kimlik + başlık h1, durum rozetleri, meta, "Sıradaki adım", sağda eylemler) → isteğe bağlı şerit
(ör. `<AkisAdimlari kompakt />`) → üst alan (sayfa geneli uyarı ve açılan formlar) → ana sekmeler
(`role=tablist`, ←/→ Home/End, `?sekme=<id>` derin bağlantı; eski bölüm çapaları `#bulgular` gibi
sekmenin `capalar` listesinden ilgili sekmeyi açar). Paneller tembel çizilir ve sonra `hidden` kalır
(form durumu korunur). Alt düzey için aynı `Sekmeler` bileşeni `duzey="alt"` ile kullanılır (ör. tasarım
modeli `?model=<id>`). Boş sekme gizlenmez, `SekmeBos`/`BosDurum` ile ne olmadığını söyler. Aralıklar
`--space-1…6` (4/8/12/16/24/32) token'larıdır. Örnek: `pages/GereksinimDetay.tsx`.

**Test yazarken:** sekme içeriği yalnız o sekme açıkken DOM'dadır. Sayfayı `…?sekme=tutarlilik` ile açın ya da
`sekmeAc("PO teyidi")` (`src/test/yardimci.tsx`) kullanın. Kart başlıkları `getByRole("region", { name })`
ile aranır. Aynı düğme grubundaki eş
pasiflik nedeni (`.dugme-neden`) bir kez yazılır; diğer düğmeler `aria-describedby` ile ona bağlanır,
neden metnini düğmenin erişilebilir açıklamasıyla (`toHaveAccessibleDescription`) doğrulayın.

## Görsel dil

"Agent Probe çizgisi"; ayrıntı ve gerekçeler [`docs/TASARIM-YENILEME-PLANI.md`](../docs/TASARIM-YENILEME-PLANI.md) (§2–§4).

- **Token kuralı:** temaya bağlı her değer `src/styles.css` başındaki `:root` token'ıdır. Bileşen
  kurallarında sabit renk ve `[data-theme]` seçicisi yazılmaz. `--accent` yalnız metin ve kenar içindir.
  Dolu zeminde `--accent-solid` + `--accent-text` kullanılır (`--err-solid` de aynı mantıkla).
- **Renk disiplini:** indigo = marka ve etkileşim (bağlantı, birincil düğme, aktif menü, şimdiki adım);
  mor (`--vurgu`) = **yalnız AI** (AI adımı/çıktısı, REPLAY); yeşil = insan kapısı ve başarı; amber =
  uyarı ve örnek veri; kırmızı = hata ya da engel; nötr = kategorik bilgi (tetik, kaynak, tür, kanal).
- **Kontrast:** yeni renk çifti WCAG 2.x hesabıyla eklenir (metin ≥ 4,5, kenar ve ikon ≥ 3) ve değer
  token yorumuna yazılır. `npm run e2e` axe denetimi iki temada geçmelidir.
- **Tema:** varsayılan koyu. Döngü koyu → açık → sistem şeklindedir; `src/lib/tema.ts` yönetir.
  `localStorage` anahtarları `tp-tema` (`koyu`/`acik`/`sistem`) ve göç işareti `tp-tema-v=2` (işaret
  yoksa eski `tp-tema` silinir). `index.html` ilk boyamayı `data-theme="dark"` ile yapar.
- **Font:** Inter ve JetBrains Mono (değişken, OFL) `@fontsource-variable` ile self-host edilir ve
  `main.tsx`'te `styles.css`'ten önce yüklenir. Inter latin ve latin-ext dosyaları derlemede
  `<link rel="preload">` ile önyüklenir (`vite.config.ts`).
- **İkon:** `src/components/Ikon.tsx` içinde bağımlılıksız satır içi SVG'ler var (`aria-hidden`,
  `<title>` yok). ✓ ✗ ⚠ gibi glifler metin olarak kalır, çünkü testler bunları arar.
- **CSP:** nginx `default-src 'self'` kullanır; `font-src` yoktur ve satır içi betik yasaktır. Bu
  yüzden Google Fonts ya da CDN kullanılmaz. `data:` font da kullanılmaz: `vite.config.ts` woff2
  dosyalarını gömmez. Kapı: `grep -c 'data:font' dist/assets/*.css` = 0.

## Tasarım sistemi kullanımı (UX-T)

Kaynak: `aip-review/tp-ux-denetim/sistem.md` §2–§4. Bileşenler `src/components/tasarim.tsx` (+ `ui.tsx`
genişletmeleri, `Ipucu.tsx`), CSS `src/styles.css` sonundaki "UX-T" bloğu. Renk eklenmez; yalnız mevcut belirteçler.
Yeni ekran kodu sabit px/rem yazmaz, aşağıdaki değişkenleri kullanır.

**Ölçekler** (`:root`)
- Yazı (8 basamak, rem): `--fs-hap` 0.75 (hap/çip, th, sayaç — taban, altına inilmez) · `--fs-sik` 0.8125 (veri atfı,
  küçük düğme, tablo mono) · `--fs-ikincil` 0.875 (`.kucuk`, meta, dt) · `--fs-tablo` 0.9 (tablo gövdesi, h4) ·
  `--fs-h3` 0.95 · `--fs-govde` 1 · `--fs-h2` 1.05 (kart başlığı; şeritli kartta da aynı) · `--fs-h1` 1.6.
  h1–h4 global tanımlı (tarayıcı varsayılanı sızmaz); bileşen başlık boyutunu ezmez. Bileşen içinde boyut rem; em
  yalnız düz metindeki `code`. Özel (ölçek dışı, bilinçli): marka 1.25, giriş 1.5, KPI 1.9rem.
- Kalınlık: 400 gövde · 600 vurgu/etiket/hap · 700 başlık · 800 yalnız h1 (`--fw-*`). 450/500/550/650 kullanılmaz.
- Boşluk: `--space-0` 2 (hap dikey dolgusu) · `--space-1` 4 · `--space-2` 8 · `--space-3` 12 · `--space-4` 16 ·
  `--space-5` 24 · `--space-6` 32 · `--kart-ic` 20 (kart dolgusu; şerit başlık `calc(-1 * var(--kart-ic))`). Dönüşüm:
  6 → öğe içi `--space-1`, öğeler arası `--space-2`; 10 → `--space-2`/`--space-3`; 14 → `--space-3`; 18 → `--space-4`.
- Kırılım (4): ≤640 telefon (tablo yığını, dokunma 44 px) · ≤860 menü kapanır · ≤1279 dar masaüstü · ≥1440 geniş
  (`--kirilim-*` belge değişkenleri; `@media` değişken okuyamaz, değer aynen yazılır). Bileşen içi eşik: `@container`.
- Köşe: `--radius-etiket` 6 (etiket çip, kimlik) · `--radius-sm` 8 · `--radius-kontrol` 10 · `--radius` 12 · `--radius-hap`.
- Dokunma: `--dokunma` 44 px; ≤640'ta düğme/sekme/summary/satır bağlantısı/onay kutusu etiketi en az bu yükseklikte.

**Tablo kuralı** — her tablo `TabloSarici` ile (elle `div.tablo-sarici` yazılmaz):
```tsx
<TabloSarici etiket="Koşular tablosu" darEkran="yigin" /* | "kaydir" */ yogunluk="normal" /* | "sik" */ uzun={satir > 15}>
  <thead>…</thead><tbody><tr><td className="sutun-metin" data-etiket="Başlık">…</td>…</tr></tbody>
</TabloSarici>
```
- `darEkran="yigin"`: kayıt tablosu (satır = kayıt) ≤640'ta "etiket: değer" kartı; her `td` `data-etiket` taşır.
  `"kaydir"`: matris tablo (karar tablosu, sürüm × ölçüt) kendi içinde kayar, ilk sütun yapışkan.
- `yogunluk`: `th` ve `td` yatay dolgusu her zaman eşit (12, ≤1279'da 8). `sik` = kart içi/detay tabloları.
- `uzun`: sarıcı ≥641 px'te en çok 70vh, kendi içinde kayar; başlık satırı yapışkan. Klavye odağı satırı vurgular.
- Sütun türü = hücre sınıfı: `sutun-kimlik` (mono, tek satır; uzunsa `Kimlik`/`KisaDeger`) · `sutun-durum` (çipler;
  tek çip sarılmaz, çok çip satır içinde sarar) · `sutun-sayi` (sağa, tabular) · `sutun-tarih` (tek satır) ·
  `sutun-metin` (min 14rem, sarar; içindeki mono yol da sarar) · `sutun-zengin` (adım/veri/beklenen: min 12rem, asla
  mono, çip hücre içinde sarar) · `sutun-eylem` (yatay kayan tabloda sağa yapışık) · `sutun-ikincil` (641–1279'da gizli).
- Uzun değer: metin ve çip sarılır, kesilmez (`<Cip sar>`); tek teknik belirteç (sha/uuid/yol) `Kimlik` ile
  kısaltılır, tam değer ipucu + kopyala. **Yasak:** hücre içinde `nowrap` + yüzdeli `max-width` +
  `overflow-wrap: anywhere` birlikte (min-content sıfırlanır → taşma ya da 53 px sütun, DZ-01/02). `anywhere` yalnız
  min-width'li (metin/zengin) sütunda.

**Bileşen API'leri**
- `Cip({ ton, bicim?: "hap"|"etiket"|"duz", boyut?: "normal"|"kucuk", sar?, aciklama?, title?, className?, testId? })` —
  `aciklama` erişilebilir ipucu (yeni kodda `title` yerine). Yerel hap kopyası (`.yh-tur`, `.ac-ref`…) yazılmaz.
- `DurumCipi({ harita, deger, aciklama? })` — `lib/etiketler.ts` haritası (CASE_DURUMU, SCRIPT_DURUMU…); bilinmeyen nötr.
- `Kimlik({ deger, tur?: "jira"|"ac"|"kosu"|"case"|"sha"|"uuid"|"yol"|"diger", kisaltUzunluk?, kirp?, kopyala? })`,
  `KisaDeger({ deger, uzunluk=7, kopyala=true })`, `KopyalaDugmesi({ deger })`, `kisalt(deger, n, kirp)`.
- `Ipucu({ metin, children })` — title-only açıklamanın yerine (ET-06): odak/dokunma/fare ile açılır, Esc kapatır;
  kapalıyken `aria-description`, açıkken `role=tooltip`. Balon yalnız açıkken DOM'da.
- `MetaIzgara({ ogeler: {etiket, deger, genis?}[], duzen?: "yan"|"ust", yogun?, etiket? })` — "etiket: değer" (dl);
  boş değer "—"; ≤640'ta tek sütun. `MetaSatiri({ ogeler: {etiket?, deger}[] })` — 2–4 kısa bilgi, "·" ayraçlı.
- `SuzgecCubugu({ etiket, sonuc?, children })` — süzgeç denetimleri + sağda `role=status` sonuç ("12/41 test").
  `SegmentSecici({ etiket, secenekler: {deger, ad, sayi?, pasif?}[], deger, degistir })` — `aria-pressed`, `.sekme`
  görünümü; gezinme sekmesi değildir (o DetaySayfasi `Sekmeler`). Çok seçenek: mevcut `SuzgecSecimi`.
- `EylemCubugu({ hiza?: "bas"|"son", etiket?, children })` — `.eylemler` sınıfını korur; içindeki kilitli
  `IslemDugmesi` `disabled` yerine `aria-disabled` (Tab sırasında kalır, nedeni okunur, tıklama engellenir; ET-07).
  Tek düğmede `<IslemDugmesi odaklanabilir>`. Dışarıda varsayılan yerel `disabled` (geriye uyum; testlerde
  `toBeDisabled` yerine `toHaveAttribute("aria-disabled", "true")`).
- `BosDurum({ baslik, children?, kip?: "bolum"|"sekme"|"satir", eylem? })` — tek boş durum; `eylem` sonraki adım
  yuvası. Satır içi "X yok." paragrafı yerine `kip="satir"`.
- `TabloSarici({ etiket, darEkran?, yogunluk?, uzun?, className?, tabloClassName?, testId?, children })`.
- DetaySayfasi (DS-1) ile: `OzetKarti` yuvaları `kimlik` → `Kimlik`, `rozetler` → `DurumCipi`, `meta` → `MetaSatiri`,
  `eylemler` → `EylemCubugu hiza="son"`; sayı rozeti `Sayac`.
- Kırıntı (IA-22): `OzetKarti kirinti={[{ ad: "Gereksinimler", yol: "/gereksinimler" }, { ad: "TPD-1", yol }, { ad: "Case review" }]}`
  (son halka `aria-current="page"`); `ust` yalnız ilgili sayfa bağlantıları. `eylemler` OzetKarti içinde kendiliğinden
  `EylemCubugu hiza="son"`a sarılır (kilitli düğme aria-disabled). Sayfaya özgü CSS `src/stiller/detay-*.css`.

## API sözleşmesi

- `src/api/client.ts`: MIMARI-SOZLESME §5'teki her uç için türlü istemci.
- `src/api/types.ts`: yanıt şemaları. Veritabanı kökenli alanlar Türkçe (`durum`, `olusturma`…),
  AI şemalarından gelen yükler TEKNIK-TASARIM §7/§8'deki İngilizce adları taşır (`icerik.steps`,
  `evidence[].kind`, `suggested_doc_text`…). core-api yanıtları bu tiplere uymalıdır.
- `src/api/events.tsx`: `/api/events` SSE. EventSource adlı olayları yalnızca `addEventListener(ad)`
  ile teslim eder; bu yüzden hem core'un bugün yayımladığı adlar (`CORE_OLAYLARI`: her durum
  makinesi için `<varlık>.state` ve `review.recorded`, core `workflow/service.py`) hem portalın
  ayrıntılı adları (`agent.step`, `ci.status`, …) dinlenir; `data.type` taşıyan varsayılan `message`
  da işlenir. Sayfalar konu adına abone olur (`requirement.updated`, `case.updated`, …);
  `olayKonulari` core adlarını bu konulara çevirir (`requirement.state` → `requirement.updated`,
  `review.recorded` → `nesne_turu`'nun konusu, kimlik `nesne_id`). Hata halinde kapatıp üstel geri
  çekilmeyle (1 sn → 30 sn) yeniden bağlanır. Bazı uçlar örnek veriden geliyorsa gerçek SSE'nin yanında
  süreç içi olay yolu da dinlenir.
- Gereksinim durumları core'un `REQUIREMENT` durum makinesiyle birebir aynıdır (`GEREKSINIM_DURUMLARI`);
  14 adımlı akıştaki adım durumdan türetilir (`src/lib/akis.ts`). "Kabul kriteri yok" durum değil,
  `ac_missing` bayrağıdır.
- Bulgu, case, script ve bug taslağı durumları da core makineleriyle birebir aynıdır
  (`BULGU_DURUMLARI`, `CASE_DURUMLARI`, `SCRIPT_DURUMLARI`, `BUG_DURUMLARI`). Türetilmiş arayüz
  kavramları durum değildir: "merge'e hazır" (`pr_open` + CI + kırarak doğrulama), "zayıf test"
  (`zayif_test`), "bağlandı" (`published` + `karar: "link"` + `link_key`), "Jira'ya yazıldı"
  (`resolved` + `fix_doc`). `src/api/sozlesme.test.ts` birlikleri core'dan üretilmiş
  `src/api/sozlesme/durum-makineleri.json` ile karşılaştırır; `uv` ve `../core` varsa dışa aktarımı
  yeniden üretip güncelliğini de denetler. core makineleri değişince: `npm run sozlesme:durumlar`.
- İnsan kararları (bulgu, case, bug taslağı, PO onayı, merge) ekranda görülen nesnenin
  `icerik_hash`'ini gövdede gönderir; merge ayrıca incelenen `head_sha`'yı bağlar (MIMARI-SOZLESME §5).
  409 gelirse ekran yeniden yüklenir ve "İçerik değişti, yeniden inceleyin." gösterilir. Mock arka uç
  core gibi davranır: hash yoksa 422, eskiyse 409.
- Bağlantılar `Baglanti` bileşeniyle çizilir: portal ekranı → uygulama içi, http(s) ve `/api/…` →
  yeni sekme, adresi olmayan ya da portalın sunmadığı yol (artifact/forge sunucusu henüz yok) →
  tıklanamaz metin. Ölü "Sayfa bulunamadı" bağlantısı üretilmez.

## Örnek veri (mock) modu

- `VITE_MOCK=1` (`npm run build:mock`): her uç süreç içi mock arka uçtan cevaplanır.
- Varsayılan derlemede portal açılışta core'un uç listesini bir kez okur (`GET /api/openapi.json`).
  Listede olmayan uçlar için **ağ isteği hiç yapılmaz**, doğrudan örnek veriye gidilir (DevTools'ta
  404 seli yok). Liste okunamazsa eski yol: genel `{"detail":"Not Found"}` 404'ünde veya JSON olmayan
  404'te **yalnızca o uç** mock'a düşer. Türkçe "kayıt bulunamadı" 404'leri hata olarak gösterilir.
  `VITE_MOCK=0` keşfi ve geri düşüşü tamamen kapatır.
- Mock'tan gelen veri üst çubukta **ÖRNEK VERİ** rozetiyle işaretlenir (hangi uçların mock olduğu
  rozetin ipucunda). Mock arka uç rol kontrollerini ve insan kapılarını (PO teyidi, onay hash'i,
  kırarak doğrulamadan önce merge yok, gerekçesiz bilinçli fark yok) gerçek API gibi uygular.
- Veri `docs/DEMO-VERISI.md` ile aynıdır (TPD-1..4, 4 bilinçli uyumsuzluk, `add-to-cart → cart-add`).
  Kanıt yolları/satırları ve case içerikleri golden REPLAY kayıtlarından gelir
  (`src/api/mock/golden/kaynaklar.json`, `npm run sozlesme:golden`; test farkı yakalar). Örnek veri
  ana demo yolunu (REPLAY senaryosu `f2-kod-hatasi`) gösterir: F2 kampanya ve F4 kredi limiti
  "Kod hatalı", F1/F3 "Dokümanı düzelt"; AC2 özgün kalır, C3 (6 adet) defect adayıdır. Jira anahtarları jira-sim seed'iyle uyumludur
  (mükerrer adayı TPD-5; ürünün oluşturduğu kayıtlar TPD-8'den).
  Mock kullanıcıları: `analist`, `muhendis`, `sunucu`, `po`, `testci` (boş olmayan her parola).

## REPLAY

`mode: "replay"` → **REPLAY**, `mode: "replay_miss"` → **REPLAY-MISS** (uyarı renginde) rozeti;
`live` için rozet yoktur.

## Demo-A çekirdek bağlantısı (Faz 2)

- Yanıtlar `src/api/uyum.ts` uyarlayıcılarından geçer: portal şekli (types.ts) aynen; veritabanı kolon
  adları (`tur`, `kanitlar`, `onerilen_metin`, `analist_karari`, `uretim_modu`, `po_onaylayan` …) da
  kabul edilir. Model modu bilinmiyorsa `null` (rozet yok; "live" uydurulmaz).
- Case uçları cases şeridiyle aynı: `POST /cases/{id}/viewed` (ilk görüntüleme, review süresi
  başlangıcı; analistin ekranına giren taslak case için bir kez), `POST /cases/{id}/decision
  {karar: "reopen", icerik_hash}` ("Taslağa al"), `GET /requirements/{id}/case-metrics` (kabul oranı
  ilk karara göre, AI + review süresi). Taslağa alınan case'te core'un son kararı (`karar`) önceki
  karar olarak kalır; ekran "bekleyen"i durumdan (`draft`) sayar.
- İşlem kaynağa bağlıdır (`istek(..., {kaynak})`): case listesi çekirdekten geliyorsa çekirdekte henüz
  olmayan bir case işlemi örnek veriye **düşmez**, 501 "Bu işlem çekirdekte henüz yok." döner.
- `POST /publish` 202 + `job_id` dönerse ekran `test_case.state` / `publish.*` olaylarıyla yenilenir.
  Dış anahtar bağlantısı: sonuçtaki `url` > önizlemedeki `jira_browse_url` > story'nin `jira_url`'i.
- Gereksinim ekranı `unverified` ve `discarded` bulguları göstermez, yalnızca sayar (`elenen_bulgu`).
- Bug taslağı "Olası mükerrerler": tutarlılık denetiminden (`kaynak: consistency`) gelen taslakta core
  henüz Jira mükerrer araması yapmıyor (§8.12 JQL + dup_rank Faz 4). Aday listesi boşsa ekran "Jira'da
  benzer açık bug bulunamadı" demez; "Mükerrer araması yapılmadı (Faz 4)" yazar, listede "Arama yapılmadı"
  görünür ve onay panelinin üstünde Jira'yı kontrol etme uyarısı çıkar. **Sunum notu:** Demo-A'da F2
  (kampanya) için açılan taslak, jira-sim'deki açık TPD-5'in ("Kampanya indirimi sepette yanlış
  hesaplanıyor") mükerreridir. Sahnede "Onayla ve Jira'da aç" ile onaylamayın; mükerrer kayıt açılır.
  Gerekirse "Mevcut kayda bağla" ile TPD-5'e bağlayın.
- Serbest metin örnek gereksinimi (`req-ft-1`) `SERBEST` golden'larının girdisiyle aynıdır: ön inceleme,
  bulgular ve (öneriler aynen kabul edilirse) case'ler REPLAY; girdisi tutmayan serbest metin REPLAY-MISS.

## Faz 5 (portal)

- **Manuel baz değer (Gereksinim detayı):** story başına ölçülmüş manuel case hazırlama süresi.
  Kaynak `olcum` (portaldan girilen gerçek ölçüm: giren, zaman, not) · `varsayilan`
  (`TP_MANUAL_BASELINE_S`; story için ölçülmedi) · `olculmedi`. Analist/PO `PUT
  /requirements/{id}/baseline {deger_s, not}` ile girer (1 sn – 40 saat, not 3–500 karakter, "gerçek
  ölçüm" onayı zorunlu), `DELETE` ile siler. Çekirdek alanı sunmuyorsa kart "bilinmiyor" der ve form
  çizilmez. Uyarlayıcı: `src/api/uyumFaz5.ts`.
- **Kontrol Kulesi kazancı:** yalnızca baz değeri `olcum` olan story'lerden (core `hazirlik[]`);
  kapsam metni kaç story'nin hesaba girdiğini ve dışarıda kalanları söyler. REPLAY'de AI süresi
  ölçülmediği için süre yalnız review süresidir (etiketli). Kaynak bildirmeyen eski core satırı
  varsayılan sayılır (kazanç yok).
- **Demo yol haritası (`/yol-haritasi`, sunucunun açılış ekranı):** 14 adım + locator yolu, TPD-1
  için gerçek API durumundan (`src/lib/yolHaritasi.ts`); her adım ilgili ekrana bağlanır. Sauce
  kimliği yokken 9. adım "yerel yedek" yazar. Model kipi / REPLAY strict / prompt değerlendirmesi
  `/demo/status` `model`, `degerlendirme` alanlarından; yoksa gözlenen çıktı modlarından türetilir ve
  "çekirdek bildirmiyor" denir ("canlı" uydurulmaz). Okunamayan uçlar listelenir, adımları "tamam" sayılmaz.
- **Triage kanıt bağlantıları:** aynı türün deneme kopyaları (Playwright `-retryN` dizinleri) tek
  satırda "1. deneme · 2. deneme" olarak gösterilir.
- **Demo kontrolleri:** `onarim_on_kosulu` (yeşil temel koşu yoksa "Buton kimliğini değiştir" pasif + yönerge)
  ve `locator_demo.destekleniyor` (GitHub kipinde neden) ipuçları.

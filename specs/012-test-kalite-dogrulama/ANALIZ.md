# 012 — Test kalite doğrulama — Analiz

Tarih: 2026-11-11 · Dal: `feat/test-kalite-dogrulama` (dev `e0e5015`'ten) · Durum: kararlar alındı,
geliştirme başlıyor

Kaynak: "AI Testing Probe – Test Quality Validation Engine – Teknik Tasarım v2.1" (PDF + referans
kod; `.docs/` altında, repoya girmez) ve bu belgenin mevcut ürüne göre incelemesi.

Bu doküman kapsamı, alınan kararları, bileşenler arası sözleşmeleri ve geliştirme şeritlerini
sabitler. Şeritler bu dokümana göre çalışır; sözleşme değişikliği önce buraya yazılır.

## 1. Amaç ve kapsam

Amaç, AI'ın ürettiği testlerin **doğru şeyi beklediğini** ve **gerçekten hata yakaladığını**
kanıtlamaktır. Kaynak belge birim testi ve kaynak kod erişimi varsayar (PIT/Stryker, Test IR,
runtime assertion capture). Testing Probe ise onaylı case'ten uçtan uca test üretir; kod şablondan
çıkar ve assertion değeri onaylı case metninde geçmek zorundadır. Bu yüzden belgeden bize uyan
beş parça alınır:

| # | İş | Kaynak belgedeki karşılığı |
|---|---|---|
| F1 | **Karar tablosu ile bağımsız beklenen sonuç kontrolü.** Hesaplama kuralı için PO onaylı tablo; case'in beklenen değerleri onaydan önce tabloyla karşılaştırılır | Independent Oracle Validation |
| F2 | **Triage ayrımı.** Assertion farkında "test beklentisi mi yanlış, uygulama mı" | İki bağımsız doğrulama hattı |
| F3 | **Ekilmiş hata koşusu.** Demo uygulamaya bilerek hata konur, onaylı suite koşar, kırmızıya dönmesi beklenir; "hata yakalama oranı" | Mutation Testing (uçtan uca uyarlaması) |
| F4 | **Beklenti doğruluğu metriği.** AI'ın ürettiği beklenen değerlerin tabloyla uyuşma oranı | `generatorExpectationAccuracy` |
| F5 | **İlişki tabanlı ek case.** Onaylı metamorfik ilişkiden deterministik türetilen case'ler | Metamorphic Testing |

Kapsam dışı (bilerek alınmadı): PIT/Stryker ve mutant evreni, B / B+A katkı metrikleri, ayrı Test IR
ve runtime assertion capture (şablonla kod üretimi bunu zaten sağlıyor), yeni flaky politikası
(3 tekrar ve Kontrol Kulesi flaky takibi var), ayrı servis / webhook / SARIF, beş kararlı release
gate, zamanlanmış ekilmiş hata koşusu, tp-vm'e deploy.

## 2. Kararlar (2026-11-11, ürün sahibi)

| # | Konu | Karar |
|---|---|---|
| K1 | Kapsam | F1–F5 birlikte, tek seferde |
| K2 | Tabloyu kim yazar | AI kabul kriterinden taslak çıkarır, analist düzenler, PO onaylar. Case üreten adım tabloyu göremez |
| K3 | Uyuşmazlıkta davranış | Riski **yüksek** case onaylanamaz; gerekçeli istisna açılabilir ve kayda geçer. Orta ve düşük riskte yalnız uyarı |
| K4 | Ekilmiş hata türü | Veri (parametre) hataları **ve** demo uygulamada yalnız test kipinde açılabilen bayraklı kod hataları |
| K5 | Tetikleme | Kontrol Kulesi'nden elle |
| K6 | Platform | Web **ve** mobil/masaüstü (android, ios, windows) |
| K7 | Bitiş | İş özellik dalında push'lanmış kalır; dev'e birleştirmeyi ürün sahibi onaylar |
| K8 | Taban | dev'den açılır. `feat/case-gen-v3`'ün dokunduğu `rules/schemas/case_generation.schema.json`, `rules/prompts/case-generation.md` ve case üretim çağrısı **değiştirilmez** |

### 2.1 Öneri olarak alınan varsayılanlar (ürün sahibi değiştirebilir)

Bunlar sorulmadı; geliştirme sırasında bu değerlerle ilerlenir, her biri tek noktadan değişir.

| # | Konu | Varsayılan | Gerekçe |
|---|---|---|---|
| V1 | İstisnayı kim açar | Analist (onayı veren rol); gerekçe en az 20 karakter; denetim kaydına ve Kontrol Kulesi sayacına düşer | Onay kapısının sahibi analist; PO'ya ikinci tur demoda akışı keser |
| V2 | Kontrol edilemeyen yüksek riskli case | Onaylanabilir, "kontrol edilemedi" uyarısıyla | K3 uyuşmazlığı engeller; değer çıkarılamaması uyuşmazlık değildir. Metrikte ayrı sayılır |
| V3 | Kontrol henüz bitmemişse | Yüksek riskli ve tablo kapsamındaki case onayı kontrol bitene kadar reddedilir (409) | Aksi halde kapı yarışla aşılır |
| V4 | Ekilmiş hata koşusunu kim başlatır | `engineer` ve `presenter` | `/ci/trigger` ve demo kontrolleriyle aynı çizgi |
| V5 | Varsayılan platform seçimi | Web işaretli; android/ios/windows elle işaretlenir | Cihaz ve VM her zaman açık değil; uygulama platformlarında koşu uzun |
| V6 | Koşu kaydı | Ekilmiş hata koşuları `run.tetik='break_verify'` + `ortam.hata_kodu` ile yazılır | KPI dışlama ve triage "kasıtlı kırılma" davranışı zaten bu tetiğe bağlı; yeni tetik değeri CHECK, portal ve sözleşme dosyalarını gereksiz yere değiştirir |
| V7 | Migrasyon numarası | `0022`, `down_revision="0020"` | `feat/case-gen-v3` `0021`'i kullanıyor. İki dal birleşirken `0022`'nin `down_revision`'ı `"0021"` yapılır (tek satır) |
| V8 | Canlı model | Geliştirme ve testler REPLAY ile; canlı model çağrısı yapılmaz | Maliyet kararı ürün sahibinindir. Yeni prompt'lar `evaluations.yaml`'da `pending` |

## 3. Mevcut durum (tasarımı belirleyen bulgular)

- **Beklenen değer serbest metindir.** `test_case.icerik` içinde yalnız `steps[].expected` ve
  `expected_result` (string) vardır; sayısal alan yoktur. Karşılaştırma için değer metinden
  çıkarılmalıdır.
- **Onayın tek noktası** `cases/service.py` `decide()`; onay öncesi deterministik kontrol örneği
  orada zaten var (`unknown_ac_refs` → `InvalidCaseContent` 422).
- **Model çağrısı yalnız worker'da yapılır**; API senkron model çağıramaz.
- **Zayıf nokta:** tutarlılık denetiminde (`fix_doc`) doküman koda hizalanabilir; kod yanlışsa case
  de aynı yanlışı doğrular. F1 bunu kapatır: tablo yalnız onaylı gereksinim metninden çıkar.
- **Demo uygulamada hesaplama kuralları:** kampanya (`adet // 6`, kod sabiti), minimum sipariş
  (`ayar.min_siparis_tutari=750.00`, indirim sonrası toplam, dahil, kampanyalı sepet muaf), satır ve
  sepet toplamları, `ROUND_HALF_UP`. KDV, kademeli indirim ve kredi limiti kontrolü yoktur.
- **Tek ekilmiş hata bugün var:** `POST /test/break {kullanici_adi, kampanya}` (tablo
  `test_kirilma`, bayi bazında) ve süreç ortamı `BREAK_CAMPAIGN=1`. Ürün tarafında tek script için
  "kırarak doğrula" (`codegen.break_verify`). Suite düzeyinde koşu ve toplu oran yoktur.
- **`/test/reset` her testten önce çağrılır ve tabloları yeniden tohumlar.** Tabloya doğrudan
  yazılan veri hatası testten önce silinir; veri hataları da bayi bazlı kırılma kaydıyla uygulanır.
- **Core'un demo uygulamaya yazma yolu yoktur** (`DEMOAPP_TEST_TOKEN` yalnız test-runner'da).
  Bu sınır korunur: hatayı test fixture'ı uygular, core yalnız koşuyu ister.
- **Satır sabitlemeleri:** core testleri demo uygulamada şu satırları numarasıyla sabitler:
  `campaign.py:23`, `pricing.py:94`, `pricing.py:97`, `main.py:331`, `main.py:450`. Bu satırların
  numarası ve içeriği değişmez.
- **Kontrol Kulesi'nin kendi tablosu yoktur;** her sayı okuma anında hesaplanır ve `kaynaklar`
  metniyle gelir. Kırma koşuları KPI'lara girmez (`_kirma_degil()`).
- **Platform:** nightly/deploy/manual CI koşuları yalnız web'dir (`script_id` yoksa platform `web`).
  Uygulama platformlarında cihaz/Appium önceden açık olmalıdır; tek cihaz vardır ve web ile uygulama
  suite'leri aynı API'ye karşı eşzamanlı koşamaz.

## 4. Tasarım

### 4.1 Karar tablosu (F1)

Karar tablosu, bir hesaplama kuralının **PO onaylı** girdi → çıktı tanımıdır.

İçerik (`karar_tablosu.icerik`, JSONB; şema `rules/schemas/karar_tablosu.schema.json`):

```json
{
  "ad": "Kampanya: 6 al 1 bedava",
  "ac_refs": ["AC2"],
  "aciklama": "…",
  "girdiler": [{"ad": "adet", "tur": "sayi", "aciklama": "Kampanyalı üründen sepetteki adet"},
               {"ad": "birim_fiyat", "tur": "sayi", "birim": "TL"}],
  "ciktilar": [{"ad": "bedava_adet", "tur": "sayi"},
               {"ad": "indirim", "tur": "sayi", "birim": "TL", "tolerans": "0.01"}],
  "satirlar": [
    {"id": "R1", "kosul": "adet >= 7", "cikti": {"bedava_adet": "adet // 7", "indirim": "(adet // 7) * birim_fiyat"}},
    {"id": "R2", "kosul": "adet < 7",  "cikti": {"bedava_adet": "0", "indirim": "0"}}
  ]
}
```

- `tur`: `sayi | metin | mantiksal`. Sayılar `Decimal`'dir; `tolerans` verilmezse `0`.
- `kosul` ve çıktı değerleri **sınırlı ifade dilidir** (§4.2). İlk koşulu sağlayan satır geçerlidir.
  Hiçbir satır eşleşmezse sonuç "satır yok"tur (uyuşmazlık değildir).
- Sınırlar: en çok 12 girdi, 12 çıktı, 60 satır; ifade en çok 300 karakter.

Durum makinesi (`workflow/states.py`, tür `karar_tablosu`):
`draft → pending_po → approved`; `pending_po → draft` (analist geri çeker ya da PO değişiklik
ister); `approved → draft` (analist yeniden açar); her durumdan `superseded` (yeni taslak üretimi
eskisini geçersiz kılar). İçerik yalnız `draft`'ta değişir. Onay `record_approval` ile, rol `po`,
görülen `icerik_hash` ile. Onay anındaki gereksinim içerik hash'i `gereksinim_hash` olarak saklanır;
gereksinim sonradan değişirse tablo **bayat** sayılır (hesaplanan özellik, durum değil) ve kontrolde
kullanılmaz.

AI taslağı: amaç `decision_table_draft`, paket `decision-table-draft`. Girdi **yalnız** gereksinim
bloğu ve PO cevaplarıdır; kod, veri ve case'ler verilmez. Çıktı: `tables[]` (yukarıdaki içerik) ve
`relations[]` (§4.5). Gereksinim `po_approved` ya da sonrasında olmalıdır. Taslaklar
`ai_generated=true`, `durum=draft` yazılır.

Bağımsızlık kuralları (testle sabitlenir):
1. Case üretim girdisi (`generation_messages`) tablo içeriği taşımaz.
2. Değer çıkarma adımı (§4.3) tablonun yalnız kolon adını, türünü ve açıklamasını görür; satır ve
   ifadeleri görmez.
3. Kontrol sonucu case içeriğini otomatik düzeltmez.

### 4.2 Sınırlı ifade dili

Tek, saf, yan etkisiz modül: `tp_core/features/karar_tablosu/ifade.py`. `eval` kullanılmaz; kendi
ayrıştırıcısı vardır.

- Değerler: sayı (`7`, `25.00`), metin (`"min_siparis"`), `dogru` / `yanlis`, girdi adı.
- İşleçler: `+ - * /`, `//` (tam bölme), `%`, karşılaştırma `== != < <= > >=`, `ve`, `veya`,
  `degil`, parantez.
- İşlevler: `min(a,b)`, `max(a,b)`, `yuvarla(x, hane)` (HALF_UP), `taban(x)`, `tavan(x)`,
  `eger(kosul, a, b)`.
- Hata: bilinmeyen ad, tür uyuşmazlığı, sıfıra bölme, derinlik > 32 → `IfadeHatasi(mesaj, konum)`.

Arayüz (şeritler bunu kullanır, yeniden yazmaz):

```python
def dogrula(icerik: dict) -> list[str]            # şema + her ifadenin ayrıştırılması; hata metinleri
def degerlendir(icerik: dict, girdiler: dict[str, Any]) -> Degerlendirme
# Degerlendirme(satir_id: str | None, ciktilar: dict[str, Any], eksik_girdiler: list[str], hata: str | None)
def sayi_ayristir(metin: str) -> Decimal | None   # "1.250,00 TL" → 1250.00; "−25,00 TL" → -25.00; "7" → 7
def sayi_bicimle(deger: Decimal, ornek: str) -> str  # örneğin biçiminde yazar: (300, "150,00 TL") → "300,00 TL"
def esit_mi(a: Any, b: Any, tolerans: Decimal) -> bool
```

### 4.3 Beklenen sonuç kontrolü

Akış (case başına, `oracle.check` işi, worker):

1. Case'in `acceptance_criteria_refs`'iyle kesişen, `approved` ve bayat olmayan tablolar bulunur.
   Yoksa sonuç `kapsam_disi`.
2. **Değer çıkarma** (amaç `case_facts`, paket `case-facts`): girdi case içeriği ve tabloların kolon
   tanımları. Çıktı `groups[]`: `{table_ref, inputs: [olgu], expected: [olgu]}`;
   `olgu = {column, value, field, quote}`; `field` case içindeki yoldur (`steps[2].expected`,
   `steps[1].data`, `expected_result`, `preconditions[0]`, `title`).
3. **Deterministik doğrulama (LLM'siz):** her olgu için `quote`, belirtilen alanda birebir geçmeli ve
   `sayi_ayristir(quote)` (ya da metin/mantıksal eşleniği) `value`'ya eşit olmalı. Tutmayan olgu
   atılır. Girdisi eksik kalan grup `cikarilamadi` olur.
4. **Değerlendirme:** `degerlendir(tablo, girdiler)`; her beklenen olgu `esit_mi` ile karşılaştırılır.

Sonuç (`case_oracle_kontrol.sonuc`): `uyumlu | uyumsuz | kapsam_disi | kontrol_edilemedi`.
`ayrintilar` (JSONB): `{gruplar: [{tablo_id, tablo_ad, satir_id, girdiler: [olgu], karsilastirmalar:
[{column, alan, alinti, case_degeri, tablo_degeri, uyumlu}], durum, neden}], atilan_olgular: n}`.

Kayıt anahtarı `(test_case_id, icerik_hash)`. `icerik_hash` case'in o anki içeriğinin ya da
**önerilen** (düzeltme formundaki) içeriğin hash'idir.

Ne zaman koşar:
- Case üretimi bitince (`run_generation` sonunda gereksinimin tüm taslakları için işler kuyruğa girer).
- Bir tablo onaylanınca (o gereksinimin `draft` ve `approved` case'leri için).
- İstek üzerine: `POST /cases/{id}/oracle-check` (düzeltme formundan, önerilen içerikle).

Onay kapısı (`cases.service.decide`, `approve` ve `edit`): `oracle.kapi.onay_denetimi(session, tc,
icerik_hash, istisna_gerekce) -> Uyari | None`.

| Durum | Yüksek risk | Orta / düşük risk |
|---|---|---|
| `uyumlu`, `kapsam_disi` | onay | onay |
| `uyumsuz`, istisna yok | 422 `oracle_uyumsuz` | onay + uyarı kaydı |
| `uyumsuz`, geçerli istisna | onay; `oracle.exception` denetim kaydı | onay |
| `kontrol_edilemedi` | onay + uyarı (V2) | onay |
| kontrol kaydı yok, kapsayan tablo var | 409 `oracle_bekleniyor` (V3) | onay |
| kapsayan tablo yok | onay | onay |

İstisna `case_oracle_kontrol` satırına yazılır: `istisna_gerekce`, `istisna_veren_id`,
`istisna_zamani`.

REPLAY: `case_facts` için golden kayıtlar demo story'sinin (TPD-1) case'lerini kapsar; kaçırmada
politika nötr boş çıktıdır (`groups: []` → `kontrol_edilemedi`).

### 4.4 Triage ayrımı (F2)

`rules.py` 4. kuralı (`product_defect`) şu ek girdiyle inceltilir: `Girdi.oracle:
list[OracleOlgu] | None` (case'in güncel onaylı içeriğine ait kontrolün karşılaştırmaları:
`case_degeri`, `tablo_degeri`). Eşleme deterministiktir: hatanın `beklenen` değeri
(`sayi_ayristir`) `case_degeri`'ne eşit olan karşılaştırmalar alınır; tablo değerleri tek ise karar
verilir, değilse ek sinyal üretilmez.

| Test beklentisi = tablo | Gerçekleşen = tablo | Sınıf | Alt tür | Sinyal |
|---|---|---|---|---|
| evet | hayır | `product_defect` | — | `karar_tablosu_uyumlu` (uygulama tabloya aykırı) |
| hayır | evet | `test_maintenance` | `beklenti` | `karar_tablosu_beklenti_farkli` |
| hayır | hayır | `product_defect` | — | `karar_tablosu_ikisi_de_farkli` |
| tablo yok / eşleşme yok | — | bugünkü davranış | — | — |

`test_maintenance/beklenti` için bug taslağı ve locator onarımı açılmaz; öneri metni "Case'in
beklenen değeri onaylı karar tablosuyla uyuşmuyor; case düzeltilmeli" olur. DB CHECK değişmez
(`alt_tur` serbest metin).

### 4.5 İlişki tabanlı ek case (F5)

İlişki (`metamorfik_iliski.icerik`; şema `rules/schemas/metamorfik_iliski.schema.json`):

```json
{
  "ad": "Adet iki katına çıkınca ara toplam iki katına çıkar",
  "ac_refs": ["AC1"],
  "tablo_ref": "T1",
  "on_kosul": "adet >= 1 ve adet * 2 <= 999",
  "donusum": {"adet": "adet * 2"},
  "iliski": {"ara_tutar": "ara_tutar * 2"},
  "aciklama": "Kampanyasız üründe geçerlidir"
}
```

- `on_kosul` kaynak girdiler üzerinde değerlendirilir; sağlanmazsa sonuç `iliski_gecersiz`
  (atlanır, raporlanır).
- `donusum` yeni girdileri, `iliski` yeni beklenen çıktıları **kaynak case'in değerlerinden**
  hesaplar (tablodan değil). Türetilen case sonra normal oracle kontrolünden geçer; ilişki ile tablo
  çelişirse uyuşmazlık olarak görünür.
- Durum makinesi karar tablosuyla aynıdır (PO onayı).
- Türetme deterministiktir: kaynak case'in doğrulanmış olgularındaki `alinti`'lar yeni değerle
  (`sayi_bicimle`) değiştirilir; başlığa ` (ilişki: <ad>)` eklenir, `tags`'e `metamorfik` eklenir.
  Aynı alıntı bir alanda birden çok kez geçiyorsa ve değerleri farklı olgulara aitse türetme yapılmaz
  (`belirsiz_alinti`).
- Türetilen case `draft` olarak, aynı `uretim_no` ve sıradaki `sira_no` ile yazılır; insan onayından
  geçer. Aynı kaynak + ilişki çifti ikinci kez türetilmez.

### 4.6 Ekilmiş hata (F3)

**Demo uygulama.** Hata kataloğu `demo-app/api/src/demoapp_api/faults.py`; her hata bayi bazında
uygulanır (`test_kirilma.hata` kolonu). Uçlar (mevcut koruma: `DEMOAPP_TEST_MODE=1` + belirteç):

- `POST /test/break {kullanici_adi, kampanya?: bool, hata?: string | null}` — `kampanya: true`
  geriye uyumludur ve `hata: "kampanya_bedava_yok"` ile eşanlamlıdır.
- `GET /test/faults` → katalog.

| Kod | Tür | Etki | Beklenen: hangi kural yakalar |
|---|---|---|---|
| `kampanya_bedava_yok` | kod | Bedava adet 0 (mevcut kırılma) | kampanya |
| `kampanya_esik_7` | kod | `adet // 7` | kampanya (6'nın katlarında) |
| `kampanya_cift_indirim` | kod | İndirim iki kez düşülür | kampanya toplamı |
| `min_siparis_haric` | kod | `toplam > min` (sınır dahil değil) | minimum sipariş sınırı |
| `min_siparis_muafiyet_yok` | kod | Kampanyalı sepet de minimuma tabi | minimum sipariş muafiyeti |
| `min_siparis_500` | veri | Minimum 750 → 500 | minimum sipariş |
| `min_siparis_1000` | veri | Minimum 750 → 1000 | minimum sipariş |
| `fiyat_p004_31` | veri | P-004 fiyatı 30 → 31 | toplam |
| `kampanya_urunu_p002` | veri | Kampanyalı ürün P-001 → P-002 | kampanya |

Veri hataları tabloya yazılmaz (reset siler); ilgili değer o bayi için okunurken ezilir. Sabitlenen
satırlar (§3) yerinde kalır.

**Koşucu.** `TP_FAULT=<kod>` test sürecine geçer; web fixture'ı (`e2e/tests/fixtures.ts`) ve Java
`TestVerisi`/`TestTabani` her testten önce `/test/break {hata}` çağırır. Toolchain: `/check` ve
`/run` gövdesinde `fault: string | null` (`^[a-z0-9_]{1,40}$`); `ALLOWED_ENV`'e `TP_FAULT` eklenir;
koşu sonunda tüm bayiler için kırılma kaldırılır (mevcut `break_restore`). `BREAK_CAMPAIGN`
davranışı değişmez.

**Core.** Özellik `features/hata_kosusu/`. Katalog `rules/hata-katalogu.yaml` (kod, ad, tür,
açıklama); demo uygulama kataloğuyla eşitliği testle denetlenir.

- `POST /fault-runs {platformlar: [..], hatalar?: [..]}` (engineer, presenter) → 202.
  Süren koşu varsa 409 `hata_kosusu_suruyor`.
- `GET /fault-runs?limit=`, `GET /fault-runs/{id}`, `GET /fault-runs/catalog`,
  `POST /fault-runs/{id}/cancel`.
- İş `hata_kosusu.calistir` (uzun şerit). Platformlar **sırayla** koşar. Platform başına:
  1. Temel koşu (hatasız). Yeşil değilse platformun tüm adımları `gecersiz` ("temel koşu yeşil
     değil").
  2. Her hata için suite koşusu (`fault=<kod>`): en az bir assertion kırmızısı → `yakalandi`
     (kıran testler kaydedilir); tümü yeşil → `kacti`; ortam/altyapı hatası → `gecersiz`.
  3. Kapanış koşusu (hatasız, yeşil beklenir); yeşil değilse koşu uyarı taşır.
- Oran: `yakalanan / (yakalanan + kacan)`; `gecersiz` paydaya girmez, ayrı gösterilir.
- Koşular `run` tablosuna `tetik='break_verify'`, `ortam.hata_kodu`, `ortam.hata_kosusu_id` ile
  yazılır; triage bu koşular için bug taslağı açmaz.
- Olay: `hata_kosusu.ilerleme {id, durum, platform, hata_kodu, sonuc}`.

### 4.7 Metrikler (F4) ve Kontrol Kulesi

`GET /control-tower` yanıtına iki anahtar eklenir (okuma anında hesaplanır; `kaynaklar` metniyle):

- `beklenti_dogrulugu`: `{oran, uyumlu, uyumsuz, kapsam_disi, kontrol_edilemedi, istisna,
  kapsam_orani}`. Sayım, AI'ın ürettiği içeriğin (insan düzeltmesinden önceki hash) kontrol
  sonuçları üzerindendir. `oran = uyumlu / (uyumlu + uyumsuz)`; payda 0 ise `null` ("ölçülmedi").
- `hata_yakalama`: `{son_kosu: {id, bitis, durum}, oran, yakalanan, kacan, gecersiz,
  platformlar: [{platform, oran, …}], kacanlar: [{hata_kodu, ad, platform}]}`; koşu yoksa `null`.

`GET /requirements/{id}/case-metrics` yanıtına `beklenti_dogrulugu` (aynı şekil, gereksinim
kapsamında) eklenir.

## 5. Veri modeli (migrasyon `0022_kalite_dogrulama`)

Tüm tablolar tek migrasyondadır; modeller `models/kalite_feature.py`.

| Tablo | Kolonlar |
|---|---|
| `karar_tablosu` | `id`, `requirement_id` (FK), `sira_no`, `icerik` JSONB, `icerik_hash`, `onaylanan_hash`, `durum`, `gereksinim_hash`, `ai_generated`, `ai_call_id`, `uretim_modu`, `olusturan_id`, `olusturma`, `guncelleme` |
| `metamorfik_iliski` | `id`, `requirement_id` (FK), `karar_tablosu_id` (FK, null olabilir), `sira_no`, `icerik` JSONB, `icerik_hash`, `onaylanan_hash`, `durum`, `gereksinim_hash`, `ai_generated`, `ai_call_id`, `uretim_modu`, `olusturan_id`, `olusturma`, `guncelleme` |
| `case_oracle_kontrol` | `id`, `test_case_id` (FK), `icerik_hash`, `sonuc`, `ayrintilar` JSONB, `tablo_hashleri` JSONB, `ai_icerik` bool, `ai_call_id`, `uretim_modu`, `istisna_gerekce`, `istisna_veren_id`, `istisna_zamani`, `olusturma`; UNIQUE `(test_case_id, icerik_hash)` |
| `metamorfik_turetme` | `id`, `iliski_id` (FK), `kaynak_case_id` (FK), `turetilen_case_id` (FK, null), `sonuc` (`turetildi \| iliski_gecersiz \| belirsiz_alinti \| olgu_yok`), `neden`, `olusturan_id`, `olusturma`; UNIQUE `(iliski_id, kaynak_case_id)` |
| `hata_kosusu` | `id`, `durum` (`queued \| running \| done \| failed \| cancelled`), `platformlar` JSONB, `hatalar` JSONB, `commit`, `baslatan_id`, `ozet` JSONB, `uyarilar` JSONB, `baslama`, `bitis`, `olusturma` |
| `hata_kosusu_adim` | `id`, `kosu_id` (FK), `platform`, `hata_kodu` (temel/kapanış koşusunda null), `asama` (`temel \| hata \| kapanis`), `run_id` (FK run, null), `sonuc` (`bekliyor \| yakalandi \| kacti \| gecersiz \| yesil \| kirmizi`), `kiran_testler` JSONB, `neden`, `sure_ms`, `sira` |
| `test_kirilma` (demo uygulama, `create_all`) | + `hata` (string, null) |

`tp_app` rolüne `SELECT, INSERT, UPDATE` verilir (`DELETE` yok).

Yeni hata kodları (`rules/assistant/hata-sozlugu.yaml`'a da girer): `oracle_uyumsuz`,
`oracle_bekleniyor`, `karar_tablosu_gecersiz`, `hata_kosusu_suruyor`, `iliski_gecersiz`.

## 6. API (özet)

| Metot | Yol | Rol | Açıklama |
|---|---|---|---|
| GET | `/requirements/{id}/decision-tables` | herkes | Tablolar + ilişkiler (durum, `bayat`, hash) |
| POST | `/requirements/{id}/decision-tables/draft` | analyst | AI taslağı işi (202) |
| POST | `/requirements/{id}/decision-tables` | analyst | Elle boş tablo |
| PUT | `/decision-tables/{id}` | analyst | İçerik güncelle (`icerik`, `icerik_hash`); 422 `karar_tablosu_gecersiz` |
| POST | `/decision-tables/{id}/submit` · `/withdraw` · `/reopen` | analyst | Durum geçişleri |
| POST | `/decision-tables/{id}/approve` · `/request-changes` | po | `{icerik_hash, gerekce?}` |
| POST | `/decision-tables/{id}/evaluate` | herkes | `{girdiler}` → `Degerlendirme` (önizleme, kayıt yok) |
| PUT, POST | `/relations/{id}` ve aynı geçiş uçları | aynı | İlişkiler için eşleniği |
| GET | `/cases/{id}/oracle` | herkes | Güncel kontrol sonucu |
| POST | `/cases/{id}/oracle-check` | analyst | `{icerik?}` → 202; önerilen içerik için kontrol |
| POST | `/cases/{id}/decision` | analyst | Mevcut uç; gövdeye `oracle_istisna_gerekce?` eklenir |
| POST | `/requirements/{id}/metamorphic-cases` | analyst | `{iliski_id, case_ids?}` → türetilen / atlanan liste |
| * | `/fault-runs…` | §4.6 | |

`GET /cases` ve `GET /cases/{id}` yanıtındaki her case'e `oracle: {sonuc, ozet, karsilastirmalar,
istisna} | null` eklenir. Olaylar: `karar_tablosu.state`, `metamorfik_iliski.state`,
`oracle.checked {case_id, requirement_id, icerik_hash, sonuc}`, `hata_kosusu.ilerleme`.

## 7. Portal

- **Karar tabloları** sayfası: `/gereksinimler/:id/karar-tablolari`. Gereksinim detayından ve case
  review'dan bağlantı. Tablo düzenleyici (kolonlar, satırlar, ifade alanları, satır içi doğrulama),
  "örnekle dene" önizlemesi, durum çipi, "PO onayına gönder", "PO olarak onayla", "Değişiklik iste".
  Aynı sayfada **İlişkiler** bölümü ve "Ek case türet".
- **Case review:** kartta kontrol çipi ("Tabloyla uyumlu ✓" / "Tabloyla uyuşmuyor ✗" / "Kontrol
  edilemedi" / "Tablo yok") ve karşılaştırma tablosu (alan, case değeri, tablo değeri). Yüksek riskli
  uyuşmazlıkta "Onayla" pasif, nedeni görünür; "İstisnayla onayla" gerekçe formu. Düzeltme formu
  gönderilmeden önce önerilen içerik için kontrol ister. Özet kartında "Beklenti doğruluğu".
- **Kontrol Kulesi:** KPI şeridine "Beklenti doğruluğu" ve "Hata yakalama oranı"; "Ekilmiş hata
  koşusu" kartı (platform ve hata seçimi, başlat, ilerleme, hata × platform sonuç tablosu, kaçan
  hatalar listesi).
- Tasarım kuralları `docs/TASARIM-YENILEME-PLANI.md`'ye uyar: yalnız token, mor yalnız AI çıktısı,
  yeşil yalnız insan onayı, ölçülmeyen değer "ölçülmedi", mevcut sınıf / testid / metin silinmez.

## 8. Şeritler

Dalga 0 tek başına, Dalga 1 paralel, Dalga 2–3 birleşik çalışma ağacında.

| Şerit | İş | Dizinler (yalnız bunlara yazar) |
|---|---|---|
| **Ş0 temel** | Migrasyon `0022` + modeller + enum + durum makineleri + `ifade.py` + JSON şemaları + `hata-katalogu.yaml` + hata kodları | `core/alembic`, `core/src/tp_core/models`, `workflow/states.py`, `features/karar_tablosu/ifade.py`, `rules/schemas`, `rules/hata-katalogu.yaml`, `rules/assistant/hata-sozlugu.yaml` |
| **Ş1 karar tablosu** | Tablo ve ilişki servisi, API, AI taslak işi, `decision_table_draft` amacı + REPLAY | `features/karar_tablosu/` (ifade.py hariç), `rules/` içinde bu amacın dosyaları |
| **Ş2 oracle** | Değer çıkarma + doğrulama, kontrol işi, onay kapısı, `case_facts` amacı, metrik işlevi | `features/oracle/`, `features/cases/` içinde yalnız kanca satırları, `rules/` içinde bu amacın dosyaları |
| **Ş3 triage** | §4.4 | `features/triage/` |
| **Ş4 demo + koşucu** | Hata kataloğu, `/test/break` genişletme, web ve Java fixture, toolchain `fault` | `demo-app/`, `toolchain/` |
| **Ş5 hata koşusu** | §4.6 core | `features/hata_kosusu/`, `features/ci` / `codegen/toolchain.py` içinde yalnız `fault` parametresi |
| **Ş6 metamorfik** | §4.5 | `features/metamorfik/` |
| **Ş7 portal kalite** | Karar tabloları sayfası, case review değişiklikleri, ilişkiler | `review-portal/` (yeni dosyalar `kalite/` altında) |
| **Ş8 portal kule** | Kontrol Kulesi kartı ve KPI'lar | `review-portal/` (yeni dosyalar `kule/` altında) |

Ortak dosyalarda (`client.ts`, `types.ts`, `mock/handlers.ts`, `etiketler.ts`, `styles.css`,
`rules/models.yaml`, `rules/evaluations.yaml`, `rules/README.md`) her şerit yalnız kendi bloğunu
**ekler**; var olan satırı değiştirmez. Çakışmaları birleştirme adımı çözer.

**Dalga 2 (birleştirme):** dalları birleştir, Kontrol Kulesi'ne iki anahtarı bağla (§4.7), demo
story için uçtan uca REPLAY verisi, dokümanlar (`TEKNIK-TASARIM`, `MIMARI-SOZLESME`,
`DEGISIKLIK-TEST-REHBERI`), izole yığında (`COMPOSE_PROJECT_NAME=tp-kalite`, ayrı portlar) uçtan uca
deneme, Chrome for Testing ile ekran testi, cihazlarda ekilmiş hata koşusu.

**Dalga 3 (review döngüsü):** farklı rollerden bağımsız inceleme (test mühendisi, güvenlik, arka uç
mimarı, ön yüz/erişilebilirlik, analist/PO gözü, doğrulama bağımsızlığı) → bulgular → düzeltme →
yeniden inceleme; kritik ve önemli bulgu kalmayana kadar.

## 9. Test ve kabul

Her şerit: hedefli birim testleri + `ruff check` + `ruff format --check` (core); `vitest` +
`typecheck` (portal); `uv run pytest` (demo API); `./mvnw -q test -Dgroups=birim` (Java).
Tam paket yalnız birleştirme sonunda bir kez koşar.

Kabul senaryoları (demo story TPD-1 üzerinde):

| # | Senaryo | Beklenen |
|---|---|---|
| 1 | AI taslağı → analist düzenler → PO onaylar | Tablo `approved`; onay hash'i ve onaylayan kayıtlı |
| 2 | Case beklenen değeri tabloyla aynı | Çip "uyumlu"; onay serbest |
| 3 | Yüksek riskli case, beklenen değer tablodan farklı | "Onayla" pasif; API 422 `oracle_uyumsuz` |
| 4 | Aynı case, gerekçeli istisna | Onaylanır; denetim kaydı ve Kule sayacı |
| 5 | Orta riskli case, uyuşmazlık | Onaylanır; uyarı görünür ve kayıtlı |
| 6 | Düzeltme: değer tabloya getirilir | Önerilen içerik kontrol edilir, onaylanır |
| 7 | Gereksinim onaydan sonra değişir | Tablo "bayat"; kontrolde kullanılmaz |
| 8 | Case üretim girdisi | Tablo içeriği taşımaz (test) |
| 9 | Triage: test 150 bekler, uygulama 125, tablo 150 | `product_defect` + `karar_tablosu_uyumlu` |
| 10 | Triage: test 125 bekler, uygulama 150, tablo 150 | `test_maintenance/beklenti`; bug taslağı yok |
| 11 | Ekilmiş hata, web | Temel yeşil → her hata için sonuç → kapanış yeşil; oran hesaplanır |
| 12 | Hiçbir testin yakalamadığı hata | `kacti`; "kaçan hatalar" listesinde |
| 13 | Cihaz kapalıyken uygulama platformu | Adımlar `gecersiz`, neden görünür; oran etkilenmez |
| 14 | Ekilmiş hata koşuları | Geçme oranı KPI'ına girmez; bug taslağı açılmaz |
| 15 | İlişki: adet ×2 | Türetilen case `draft`, değerler doğru biçimde |
| 16 | İlişki ön koşulu sağlanmaz | `iliski_gecersiz`; case yazılmaz |
| 17 | Sabitlenen demo uygulama satırları | Numara ve içerik aynı; core golden testleri yeşil |

## 10. Riskler

| Risk | Önlem |
|---|---|
| Değer çıkarma modelin hatasına açık | Alıntı birebir doğrulanır; tutmayan olgu atılır; sonuç "kontrol edilemedi" olur, "uyumlu" olmaz |
| Tablo da yanlış olabilir | PO onayı, görülen hash, "örnekle dene" önizlemesi, gereksinim değişince bayatlama |
| AI taslağı ile case aynı yanlış okumayı paylaşabilir | Taslak yalnız onaylı gereksinim metnini görür; insan düzenler ve PO onaylar; metrik insan onaylı tabloya göredir |
| `feat/case-gen-v3` ile çakışma | Şema, prompt ve üretim çağrısına dokunulmaz; `cases/service.py`'de yalnız iki kanca; migrasyon notu V7 |
| Uygulama platformlarında koşu uzun (hata başına 3–5 dk) | Platformlar ve hatalar seçilebilir; varsayılan yalnız web |
| Windows VM ve cihazlar her zaman açık değil | Erişilemeyen platform `gecersiz` raporlanır, koşu düşmez |
| Yerelde çalışan ana yığın | Denemeler ayrı adlı izole yığında koşar; ana yığına dokunulmaz |

## 11. Ş0 notları

Ş0 (temel) sırasında alınan kararlar. Diğer şeritler bunlara güvenir; değişiklik önce buraya yazılır.

### 11.1 Dosya yolları

| Ne | Yol |
|---|---|
| Migrasyon | `core/alembic/versions/0022_kalite_dogrulama.py` (`0022`, `down_revision="0020"`) |
| Modeller | `core/src/tp_core/models/kalite_feature.py` (`tp_core.models`'ten de dışa aktarılır) |
| Değer kümeleri | `core/src/tp_core/models/enums.py` (012 bloğu) |
| İfade dili | `core/src/tp_core/features/karar_tablosu/ifade.py` |
| Hata sınıfları | `core/src/tp_core/features/karar_tablosu/hatalar.py` |
| İçerik şemaları | `rules/schemas/icerik/karar_tablosu.schema.json`, `rules/schemas/icerik/metamorfik_iliski.schema.json` |
| Hata kataloğu | `rules/hata-katalogu.yaml` |

**İçerik şemaları `rules/schemas/` altında değil, `rules/schemas/icerik/` altındadır** (§4.1 ve
§4.5'teki yolun yerine). Neden: `rules/schemas/*.json` her dosyayı bir model amacının çıktı şeması
sayar (`test_schema_compat.py`, `load_schema`); içerik şeması amaç değildir. Model çıktı şemaları
(`decision_table_draft`, `case_facts`) Ş1 ve Ş2'nindir ve `rules/schemas/`'a girer.

### 11.2 Durum makinesi ve servis çağrıları

Tür adları `karar_tablosu` ve `metamorfik_iliski` (tablo adıyla aynı); ikisi aynı makinedir.
Durumlar: `draft` (başlangıç), `pending_po`, `approved`, `superseded` (son durum). Kararlar:
`approve`, `request_changes`; onaylayan karar `approve`; karar verebilen rol yalnız `po`;
`CONTENT_FIELDS = ("icerik",)`. Tek insan kapısı `pending_po → approved`'dır.

| Uç | Çağrı (aynı işlemde, sırayla) |
|---|---|
| submit (analyst) | `transition(s, n, "pending_po", user, "draft")` |
| approve (po) | `record_approval(s, n, user, "approve", beklenen_hash=<gövdedeki icerik_hash>)` → `transition(s, n, "approved", user, "pending_po")` → `n.gereksinim_hash = content_hash_of(requirement)` |
| request-changes (po) | `record_approval(s, n, user, "request_changes", beklenen_hash=…, gerekce=…)` → `transition(s, n, "draft", user, "pending_po")` |
| withdraw (analyst) | `transition(s, n, "draft", user, "pending_po")` |
| reopen (analyst) | `transition(s, n, "draft", user, "approved")` |
| supersede (sistem) | `transition(s, n, "superseded", SYSTEM, <mevcut durum>)` |

- `durum` ve `onaylanan_hash` yalnız `transition()` ile değişir (ORM yazma koruması). Yeni satır
  `durum` verilmeden (ya da `draft`) ve `onaylanan_hash` boş eklenir. `approved`'a girişte
  `onaylanan_hash` yazılır, `draft`'a dönüşte silinir. `gereksinim_hash` korunan alan değildir.
- **`approved`'a giden tek yol approve ucudur ve her seferinde yeni `record_approval` yazar.**
  Analistin geri çekme ve yeniden açma geçişleri onay kaydı yazmadığı için, içerik değişmeden
  yeniden gönderilen bir tabloda eski `approve` kaydı kapıyı teknik olarak açık bırakır; servis
  `approved` geçişini başka hiçbir yerden çağırmaz.
- İçeriğin yalnız `draft`'ta değişmesini servis denetler (makine içerik yazımını engellemez).
  İçerik yazan kod `icerik_hash = content_hash(icerik)` değerini de günceller.
- "Bayat": `n.durum == "approved" and n.gereksinim_hash != content_hash_of(requirement)`.
- `review` tablosunun `nesne_turu` CHECK'i iki türü kabul edecek şekilde genişletildi.
- Portal: `durum-makineleri.json` yeniden üretildi; `events.tsx`'e `karar_tablosu.state` ve
  `metamorfik_iliski.state` eklendi, ikisi de `karar_tablosu.updated` konusuna çevrilir;
  `MakineAdi`'na iki tür eklendi.

### 11.3 Veri modeli ekleri (§5'te yazmayanlar)

- `karar_tablosu` ve `metamorfik_iliski`: `UNIQUE (requirement_id, sira_no)`. `sira_no` gereksinim
  içinde artar ve yeniden kullanılmaz (`superseded` satırlar dahil); yeni satır `max + 1` alır.
  `ai_generated` varsayılanı `false`'tur (elle tablo); AI taslağı `true` yazar.
- `metamorfik_iliski.karar_tablosu_id`: `ON DELETE SET NULL`. `icerik.tablo_ref` (`T<sira_no>`,
  isteğe bağlı) yalnız okunur bilgidir; yetkili bağ bu kolondur.
- `case_oracle_kontrol.tablo_hashleri`: `{<karar_tablosu.id>: <icerik_hash>}`. `ai_icerik`: bu hash
  AI'ın ürettiği (insan düzeltmesinden önceki) içeriğe aitse `true` (§4.7 sayımı).
- `metamorfik_turetme`: `kaynak_case_id` `ON DELETE CASCADE`, `turetilen_case_id` `ON DELETE SET
  NULL`. Atlanan sonuçlar da (`iliski_gecersiz` …) çifti tutar; yeniden deneme satırı günceller.
- `hata_kosusu.durum` iş durumudur, `workflow.MACHINES`'te değildir (düz atanır). Varsayılan
  `queued`; `ozet` `{}`, `uyarilar` `[]`. Süren koşu kümesi `enums.HATA_KOSUSU_SUREN`. Tek süren
  koşu kuralını DB kısıtı değil servis sağlar (ör. `pg_advisory_xact_lock` + sorgu).
- `hata_kosusu_adim`: `UNIQUE (kosu_id, sira)`; `sonuc` varsayılanı `bekliyor`; CHECK
  `(asama = 'hata') = (hata_kodu IS NOT NULL)`; `platform` `enums.PLATFORM`'dan.
- `tp_app` altı tabloda `SELECT, INSERT, UPDATE` yapar; `DELETE` ve `TRUNCATE` yoktur.

### 11.4 İfade dili (§4.2'ye ekler)

- Metin sabiti çift ya da tek tırnakla yazılır (`"a"`, `'a'`); kaçış yoktur. Anahtar sözcükler
  yalnız küçük harf ve ASCII'dir (`değil` kabul edilmez).
- `//` aşağı yuvarlar (`-7 // 2 = -4`), `%` bölenin işaretini alır (Python tam sayılarıyla aynı).
  `min` ve `max` tam iki değer alır; `yuvarla` hanesi 0–12 arası tam sayıdır.
- `ve`, `veya`, `eger` tembeldir (`b != 0 ve a / b > 2` sıfıra bölmez). Karşılaştırma zincirlenmez.
- Tür denetimi statiktir (`dogrula` ifadeyi çalıştırmadan tür hatasını bulur); örtük dönüşüm yok.
- Sayılar 60 anlamlı basamak, ROUND_HALF_UP; mutlak değeri 10^30 ve üstü hatadır.
- `IfadeHatasi.konum` 0 tabanlı karakter indeksidir; `str(hata)` 1 tabanlı yazar ("… (konum 5)").
- Kolon adı deseni `^[a-z][a-z0-9_]{0,39}$`; anahtar sözcük ve işlev adları ad olamaz; aynı ad hem
  girdi hem çıktı olamaz. Satır kimliği `^R[0-9]{1,3}$`. Her satır her çıktıyı tanımlar. Çıktı
  ifadeleri yalnız girdi adlarını kullanır. `tolerans` metindir (`"0.01"`), yalnız sayı çıktısında.
- `dogrula` boş `girdiler` / `ciktilar` / `satirlar` / `ac_refs`'i kabul eder (elle açılan boş
  taslak). PO'ya gönderim için `gonderim_hatalari(icerik)` her birinden en az bir tane ister.
- `degerlendir`: tablonun herhangi bir ifadesinde geçen bir girdi verilmemişse `eksik_girdiler`
  dolar ve hiçbir satır değerlendirilmez. Sayı girdisi `Decimal`, `int`, `float` ya da metin
  (`"25.00"`, `"25,00 TL"`) olabilir. `Degerlendirme.as_dict()` sayıları metin olarak verir.
- Sözleşmeye eklenen yardımcılar: `gonderim_hatalari`, `toleranslar(icerik)`, `girdi_donustur`,
  tek ifade için `ayristir`, `adlar`, `ifade_turu`, `hesapla`; ilişki için
  `iliski_dogrula(icerik, tablo_icerik=None)` ve `iliski_uygula(icerik, girdiler, ciktilar) →
  IliskiSonucu(gecerli, girdiler, ciktilar, eksik, hata)`. İlişkide `on_kosul` zorunludur
  (koşulsuz ilişki `"dogru"` yazar) ve yalnız kaynak girdileri görür; `donusum` ve `iliski`
  kaynak girdi ve çıktıları görür.

### 11.5 Sayı metni

- `sayi_ayristir` metinde tek sayı ister. Önünde işaret, para/yüzde simgesi ya da boşlukla ayrılmış
  kısa birim; arkasında en çok üç sözcüklük birim olabilir. `"AC2"`, `"P-004"`, `"3 koli 7 adet"`
  sayı değildir (`None`).
- Nokta ve virgül birlikteyse sonda gelen ondalıktır. Tek virgül ondalıktır (`"1,250"` → 1.250).
  Tek nokta, ardında tam üç rakam ve önünde 1–3 rakam varsa binliktir (`"1.250"` → 1250); değilse
  ondalıktır (`"1250.00"`, `"0.125"`). Boşluk binlik ayırıcı olabilir (`"1 250,00"`).
- `sayi_bicimle` değeri **yuvarlamaz**: örneğin hane sayısına sığmayan değer gereken kadar haneyle
  yazılır (`187.5`, `"125 TL"` → `"187,5 TL"`). Sonuç `sayi_ayristir` ile aynı değere geri
  okunamıyorsa ya da örnek sayı değilse `ValueError` verir.
- `esit_mi`: sayılar tolerans içinde; metin baş/son boşluk atılarak birebir; `bool` sayı değildir;
  türler farklıysa `False`.

### 11.6 Hata kodları ve asistan değerlendirme kaydı

- Beş sınıf `hatalar.py`'dedir. `KararTablosuGecersiz(mesaj, hatalar)` ve `IliskiGecersiz(mesaj,
  hatalar)` ayrıntıları hem `.hatalar`'da hem mesaj metninde taşır.
- Sözlük kayıtlarının `rota`'ları var olan rotalardır (`/gereksinimler/:id/caseler`,
  `/gereksinimler/:id`, `/kontrol-kulesi`); karar tabloları rotası Ş7 ile gelince güncellenebilir.
- **Açık konu (ürün sahibi kararı):** `rules/assistant/hata-sozlugu.yaml` asistan paketinin içerik
  hash'ine girer. Beş kaydın eklenmesiyle `assistant@v1` durumu `evaluated`'tan `icerik_degisti`'ye
  döndü ve iki test kırmızıya döndü:
  `tests/unit/features/demo/test_model_durumu.py::test_degerlendirme_durumu_durust_etiket` (izinli
  durum listesinde `icerik_degisti` yok) ve
  `tests/unit/gateway/test_evaluation_status.py::test_readme_status_table_matches_manifest`
  (`rules/README.md` durum tablosu hâlâ "canlı değerlendirildi" diyor). `rules/evaluations.yaml`'daki
  kayıtlı hash'e ve README tablosuna dokunulmadı: hash canlı değerlendirmenin kaydıdır. Çözüm
  seçenekleri: asistanın canlı değerlendirmesini yeniden koşmak (`make eval-live
  A=--update-status`), sahibin istisna yazması, ya da durumu `icerik_degisti` olarak kabul edip
  README tablosunu ve testin durum listesini buna göre güncellemek.

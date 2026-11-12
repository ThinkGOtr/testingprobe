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
| V7 | Migrasyon numarası | `0022`, `down_revision="0020"` | `feat/case-gen-v3` `0021`–`0028`'i kullanıyor. **Düzeltme (review 2):** birleşmede `0029`, `down_revision="0028"` ve `review_nesne_turu_ck` birleşimi (§14.1); "tek satır" değildir |
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
| `feat/case-gen-v3` ile çakışma | Şema, prompt ve üretim çağrısına dokunulmaz; `cases/service.py`'de işaretli kanca blokları (`# --- 012 … # --- /012 ---`); birleştirme planı §14 |
| Uygulama platformlarında koşu uzun (hata başına 3–5 dk) | Platformlar ve hatalar seçilebilir; varsayılan yalnız web |
| Windows VM ve cihazlar her zaman açık değil | Erişilemeyen platform `gecersiz` raporlanır, koşu düşmez |
| Yerelde çalışan ana yığın | Denemeler ayrı adlı izole yığında koşar; ana yığına dokunulmaz |

## 11. Ş0 notları

Ş0 (temel) sırasında alınan kararlar. Diğer şeritler bunlara güvenir; değişiklik önce buraya yazılır.

### 11.1 Dosya yolları

| Ne | Yol |
|---|---|
| Migrasyon | `core/alembic/versions/0022_kalite_dogrulama.py` (`0022`, `down_revision="0020"`; v3 birleşmesinde `0029` / `"0028"`, §14.1) |
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

## 12. Birleştirme notları

Dalga 2 (çekirdek birleştirme, 2026-11-12) sonunda uygulamanın §4–§6'dan ayrıldığı yerler. §11'deki
Ş0 notları geçerlidir; burada yalnız şerit ekleri ve birleştirme düzeltmeleri vardır.

### 12.1 Şekil ve sözleşme farkları

| Konu | §4–§6'da | Uygulamada |
|---|---|---|
| İçerik şemaları | `rules/schemas/karar_tablosu.schema.json` | `rules/schemas/icerik/` (§11.1) |
| Migrasyon | `0022`, `down_revision="0020"` | Aynı; `test_alembic_tek_bas` başı `0022` bekler. `feat/case-gen-v3` `0021`–`0028`'i kullandığı için birleşmede dosya `0029_kalite_dogrulama.py` olur (`revision="0029"`, `down_revision="0028"`); V7'deki "`0021`" notu geçersizdir (§14.1) |
| Model çıktısındaki satır | — | `decision_table_draft` çıktısı satır çıktılarını ve ilişki `donusum`/`iliski`'yi `[{ad, ifade}]` listesi verir; `karar_tablosu.service.taslak_tablo_icerigi` / `taslak_iliski_icerigi` içerik biçimine (`cikti: {ad: ifade}`) çevirir |
| Tablo araması | iki şeritte ayrı | Tek kaynak `karar_tablosu.service.gecerli_tablolar`; `oracle/tablolar.py` yeniden dışa aktarır. AC atfı boşluksuz büyük harfle karşılaştırılır (`"ac 2"` = `"AC2"`) |
| Tablo olayı | `karar_tablosu.state` | Durum geçişleri `karar_tablosu.state` / `metamorfik_iliski.state` (iş akışı); içerik ve AI taslağı `karar_tablosu.updated` (`eylem`: `created`, `updated`, `ai_draft`) |
| Oracle işleri | `oracle.check` | `oracle.check_requirement {requirement_id, neden}` (gereksinimin `draft`/`approved` case'leri; düzeltilmiş case'in AI içeriği de) → `oracle.check_case {case_id, icerik_hash, icerik?}`. Tablo onayı, yeniden açma ve onaylı tablonun geçersiz kılınması (Ş1), case üretimi sonu (yalnız geçerli tablo varsa) ve metamorfik türetme (Ş6) `check_requirement` açar |
| Ş1 iş anahtarı | — | **§13.2 ile değişti** (gereksinim başına tek bekleyen iş). Eskiden `oracle.check_requirement:<req>:<tablo>:<neden>:<uuid>` — olay başına tekil. Birleştirmede düzeltildi: önceki `…:<onaylanan_hash \| acik>` ikinci yeniden açmayı ve aynı içeriğin yeniden onayını yutuyordu; kayıtlar eski tablo kümesinde kalıp kapı 409'da takılıyordu |
| Kısmi değerlendirme | eksik girdi → grup `cikarilamadi` | `dogrulama.kismi_degerlendir`: eksik girdi yalnız onu kullanan koşul ve çıktıyı etkiler. Satırlar sırayla denenir; koşulu eksik girdiye dayanan ilk satırda durulur (seçilen satır tam değerlendirmeyle aynıdır). Seçilen satırın eksik girdiye dayanan çıktıları karşılaştırılmaz; o çıktıların doğrulanmış olguları gruptaki `karsilastirilamayan: [{column, value, field, quote, neden}]` listesine yazılır, sonuca girmez. `ifade.degerlendir` sözleşmesi değişmedi |
| `ayrintilar.gruplar[]` | `{tablo_id, tablo_ad, satir_id, girdiler, karsilastirmalar, durum, neden}` | + `karsilastirilamayan` (yukarıda). Alan yolları 0 tabanlıdır (`steps[3].expected`); `case_degeri`/`tablo_degeri` sayıda düz ondalık metin (`"25.00"`), mantıksalda JSON bool, metinde str |
| Portal `oracle` nesnesi | `{sonuc, ozet, karsilastirmalar, istisna}` | + `icerik_hash`, `kontrol_suruyor` (kayıt yokken `sonuc: null`), `karsilastirilamayan: [{tablo_id, tablo_ad, column, alan, alinti, case_degeri, neden}]`; `ozet` karşılaştırılamayanları söyler. `GET /cases/{id}/oracle?icerik_hash=` ayrıca `guncel_icerik`, `kapsayan_tablolar` döner |
| Alıntı sınırı | — | Alanın başındaki sayı alıntısı (`"7 adette"` içinde `7`) önceden yanlışlıkla atılıyordu (boş dizginin `in` denetimi); düzeltildi |
| Metamorfik olgular | — | Ş6 `karsilastirmalar` ve `karsilastirilamayan`'ı çıktı olgusu olarak okur; mantıksal olgu sayı alıntısından önce ayrılır (`"Minimum 750,00 TL" uyarısı görünür` sayı sayılmaz). Değeri değişen alıntının olgusuz kopyası varsa `belirsiz_alinti`; bu yüzden golden olguları bir değerin case'teki **tüm** geçişlerini taşır |
| Ek uçlar | — | `GET /requirements/{id}/metamorphic-derivations`, `POST /decision-tables/{id}/evaluate` gövdesinde isteğe bağlı kaydedilmemiş `icerik`, `GET /fault-runs/catalog` |
| Kontrol Kulesi | `kaynaklar` metniyle | Değerler `kaynak` taşımaz (Kule kuralı); metin `kaynaklar["beklenti_dogrulugu"]`, `kaynaklar["hata_yakalama"]`'dadır (koşu yoksa "henüz yok (ölçülmedi)"). `/requirements/{id}/case-metrics`'teki `beklenti_dogrulugu` `kaynak`'ı nesne içinde taşır |
| Asistan önerisi | §4.4 "locator onarımı açılmaz" | Yeni olgu `beklenti_farki` (failure); `hata-bakim-onarim` artık `beklenti_farki_esit: false` ister; yeni kurallar `hata-beklenti-case-duzelt` (analist) ve `hata-beklenti-bilgi` (mühendis). Kural sayısı 26 → 28: **ürün sahibi K10 onayı bekler**. Ş7'nin rotası `/gereksinimler/:id/karar-tablolari` öneri kapsamına bilinçli boş, asistan prompt'unun ekran listesine eklendi (asistan paketi zaten `icerik_degisti`, §11.6) |

### 12.2 TPD-1 demo tabloları ve sonuçlar

Demo tabloları Ş1'in AI taslak golden'ıdır (`rules/replay/decision_table_draft/golden/TPD-1.json`);
oracle şeridi ve testler onu yükler (`core/tests/unit/features/oracle/tpd1.py`), kopya yoktur:

- **T1 "Kampanya: 6 al 1 bedava (7 adette 1 bedava)"** (AC2): girdiler `adet`, `birim_fiyat`;
  çıktılar `bedava_adet` (R1 `adet >= 7` → `adet // 7`; R2 → `0`), `indirim` (R1 `(adet // 7) *
  birim_fiyat`, tolerans 0.01; R2 → `0`). Story'yi izler; demo uygulama `adet // 6` uygular.
- **T2 "Minimum sipariş tutarı (kampanyasız siparişler)"** (AC3, AC6): girdiler `kampanyali_sepet`,
  `sepet_tutari`; çıktı `minimum_uyarisi` (R1 kampanyalı → yanlış; R2 `sepet_tutari < 750` → doğru;
  R3 → yanlış).
- **İlişki** (T1): `adet >= 7 ve adet % 7 == 0` iken `adet × 2` → `bedava_adet × 2`, `indirim × 2`.

Case'ler birim fiyatı yazmaz: `birim_fiyat` olgusu çıkarılmaz (uydurulmaz). Bu yüzden 7 adette
`indirim` karşılaştırılamaz (`karsilastirilamayan`), 7'den az adette (R2, sabit 0) karşılaştırılır.

Demo ana yolu (`f2-kod-hatasi`: AC2 özgün, case'ler senaryo golden'ından), dürüst sonuçlar
(`core/tests/unit/features/kalite_e2e/test_tpd1_uctan_uca.py` ile sabit):

| Case | AC | Risk | Sonuç | Ayrıntı |
|---|---|---|---|---|
| C1 sepete ekle | AC1 | orta | `kapsam_disi` | Tablo yok; model çağrılmaz |
| C2 7 adette 1 bedava | AC2 | yüksek | `uyumlu` | T1 R1: bedava 1 = 7 // 7 (3 alıntı); indirim 25,00 karşılaştırılamadı (birim fiyat yok) |
| C3 6 adette bedava yok | AC2 | yüksek | `uyumlu` | T1 R2: bedava 0 = 0, indirim 0,00 = 0. **Defect adayı:** uygulama 6 // 6 = 1 bedava verir; testin kırmızısı triage'da `product_defect` + `karar_tablosu_uyumlu` ("test beklentisi 0, gerçekleşen 1, tablo 0") |
| C4 5 adette bedava yok | AC2 | orta | `uyumlu` | T1 R2 |
| C5 kampanyasız 150 TL | AC3 | yüksek | `uyumlu` | T2 R2: uyarı görünür |
| C6 kampanyasız 750 TL | AC3 | yüksek | `uyumlu` | T2 R3: tam 750'de uyarı yok |
| C7 kredi limiti | AC4 | yüksek | `kapsam_disi` | Kredi limiti tablosu yok (limit bayi verisi) |
| C8 sipariş numarası | AC5 | yüksek | `kapsam_disi` | Hesaplama kuralı yok |
| C9 kampanyalı 150 TL | AC6 | orta | `uyumlu` | T2 R1: uyarı yok |
| C10 C2'nin tekrarı | AC2 | orta | `uyumlu` | C2 ile aynı |

Beklenti doğruluğu (AI içeriği): `oran 1.0`, uyumlu 7, uyumsuz 0, kapsam dışı 3, kontrol edilemedi
0, `kapsam_orani 0.7`. Hiçbir AI case'i tabloyla uyuşmazlık göstermez; kapıyı demoda göstermek için
analistin yanlış düzeltmesi kullanılır (uçtan uca testte: C5'i "uyarı görünmez" yapmak → önerilen
içerik `uyumsuz` → 422 `oracle_uyumsuz` → gerekçeli istisnayla onay, `istisna 1`).

F2 `fix_doc` alternatifinde (ana golden, AC2 koda uyarlanmış) yalnız C3 farklıdır ("6 adette 1
bedava"); bu yolda Ş1 taslağı REPLAY-MISS olur (tablo yok → kontrol yok). Story tablosuyla
değerlendirilseydi C3 `uyumsuz` olurdu (bedava 1 ≠ 0, indirim 25 ≠ 0; yüksek risk → 422); saf
testlerde kapının gösterimi olarak tutulur. `case_facts` golden'ları: ana `TPD-1-C2…C6, C9, C10`
ve senaryo `f2-kod-hatasi/TPD-1-C3`.

Metamorfik türetme ana yolda C2 ve C10'dan iki ek case üretir (C3, C4 ön koşulu sağlamaz:
`iliski_gecersiz`). Türetilen case `ai_generated=false`'tur, metriğe girmez; golden'ı olmadığı için
kontrolü `kontrol_edilemedi`'dir. **Bilinen sınır:** T1'de `ara_toplam`/`toplam` kolonu yoktur;
türetilen case'te "ara toplam 175,00 TL … toplam 150,00 TL" kaynak değerde kalır (14 adet için
yanlış). Case insan onayından geçer; analist düzeltmeli ya da tabloya bu çıktılar (ve birim fiyat
girdisi) eklenmelidir.

### 12.3 Açık konular

- Asistan önerisi kural setinin 26 → 28 olması (K10) ve asistan paketinin `icerik_degisti` durumu
  (§11.6) ürün sahibi kararıdır. Portal sahte veri öneri kuralları (`review-portal/src/api/mock/
  oneri.ts`) yeni olguyu ve iki kuralı bilmez.
- Portal `karsilastirilamayan` listesini henüz göstermez (yalnız `ozet` cümlesi söyler).
- `case_facts` ve `decision_table_draft` golden'ları elle hazırlanmıştır; canlı modelle kayıt
  (`TP_MODEL_MODE=record`) ve değerlendirme (`evaluations.yaml` `pending`) ürün sahibi kararıdır.

## 13. Review turu 1 kararları ve düzeltme sözleşmesi (2026-11-12)

Altı rollü review (test, güvenlik, mimari, ön yüz, analist/PO, doğrulama bağımsızlığı) bulguları
`scratchpad/review1/*.md`'dedir. Bu bölüm düzeltme şeritlerinin uyacağı kararları ve sözleşmeyi
sabitler; §4–§6 ile çelişirse bu bölüm geçerlidir.

### 13.1 Kararlar

| # | Konu | Karar |
|---|---|---|
| K9 | Kaçan hata | `kampanya_esik_7` katalogdan çıkar (story'ye uygun davranış). Yerine `kampanya_tek_bedava`: bedava adet `min(1, adet // 6)` — 6/7 adette doğru görünür, 12+ adette yanlış. Katalog kayıtlarına `ac_refs`, `tablo` (ör. `T1`) ve `ayirt_edici` (girdi + doğru/hatalı çıktı) eklenir |
| K10 | Kontrol edilemedi | Yüksek riskte, kapsayan geçerli tablo varken `kontrol_edilemedi` → gerekçeli onay (istisna ile aynı gövde alanı, tür `kontrolsuz`); orta/düşükte uyarı. Kule'de "kontrolsüz onay" sayacı. Model çağrısı hatası ayrıca kaydedilir (`neden: cagri_hatasi`) |
| K11 | Kısmi sonuç | Yeni sonuç `kismen`: fark yok ama kapsanan bir grup değerlendirilemedi, ya da beklenen bir olgu atıldı / karşılaştırılamadı. Kapıda uyarı (yüksek risk dahil engellemez), doğruluk oranına girmez, değer düzeyinde sayım gösterilir |
| K12 | Yakalama oranı | Ana oran yalnız onaylı case'lerden üretilen testlerle (`tests/generated/`, `uretilen/`); el yazısı suite ayrı sütun. Bir hata ancak şu testle "yakalandı" sayılır: hatasız temelde yeşil, hatalı koşuda assertion kırmızısı. Temelde kırmızı testler koşuyu geçersiz kılmaz, hariç tutulur ve listelenir |
| V9 | T1 (kampanya) | Girdiler `adet`, `ara_toplam`; çıktılar `bedava_adet`, `indirim = yuvarla(ara_toplam / adet * (adet // 7), 2)`, `toplam = ara_toplam - indirim`. `birim_fiyat` girdisi kalkar (case'lerde yazmıyor; ara toplam yazıyor) |
| V10 | İstisna yolları | İstisna formu iki yol sunar: "Case doğru, tabloya rağmen onayla" (istisna) ve "Tablo yanlış" (tabloyu yeniden açar, case onaylanmaz). İstisnalar append-only `oracle_istisna` tablosunda tutulur; sayaçlar oradan |
| V11 | Kapı girdileri | Risk = max(saklı, AI özgün, gönderilen); kapsayan tablolar = saklı ∪ gönderilen AC ref'leri. Risk ya da kapsanan AC düşüren düzeltme audit'e `oracle.dusurme` yazar ve uyuşmazlıkta istisna gerektirir. Yüksek risk tek işlevden: `risk == "high"` ya da (v3 içeriği) `priority == "P1"` |
| V12 | İleri uyumluluk (v3) | Alan grameri `test_data[i].value`, `verification_point`, `teardown`'u kabul eder. Migrasyon numarası ve `review_nesne_turu_ck` birleşimi `feat/case-gen-v3` ile birleşirken yapılır (§12 + mimari kontrol listesi) |

### 13.2 Sözleşme değişiklikleri

Uygulandığı hâliyle (düzeltme şeritleri R1–R4 birleştirildikten sonra, kod okunarak yazıldı;
§12.1 ile çelişirse bu bölüm geçerlidir).

**Veri.** `ORACLE_SONUC` += `kismen`; `TURETME_SONUC` += `tutarsiz_kalan_deger`. `0022` migrasyonu
yerinde güncellendi (dal dev'e girmedi; izole yığın yeniden kurulur). Yeni tablo `oracle_istisna(id,
test_case_id, icerik_hash, tur: uyumsuz|kontrolsuz, gerekce, veren_id (boş olabilir), zaman,
tablo_hashleri)`, yalnız INSERT/SELECT. `case_oracle_kontrol` istisna kolonlarını geriye uyum için
yazar; sayımlar ve "istisna verilmiş" görünümü `oracle_istisna`'dandır.

**Oracle nesnesi** (`GET /cases/{id}/oracle` içinde `oracle`, case listesinde case başına;
`service.oracle_gorunumu`). Kapsayan tablo da geçerli kayıt da yoksa `null`.

```
{ sonuc: uyumlu|uyumsuz|kismen|kontrol_edilemedi|kapsam_disi|null,   // null: kontrol sürüyor
  icerik_hash, ozet, kontrol_suruyor: bool,
  karsilastirmalar: [{tablo_id, tablo_ad, satir_id, column, alan, alinti, case_degeri,
                      tablo_degeri, uyumlu}],
  karsilastirilamayan: [{tablo_id, tablo_ad, column, alan, alinti, case_degeri, neden}],
      // eksik girdi yüzünden hesaplanamayan değerler + tamlık denetiminde hiçbir olguya ya da
      // `ignored`'a bağlanmayan sayılar (tablo_id/column/case_degeri null)
  degerler: {uyumlu, uyumsuz, karsilastirilamayan, atilan},   // değer düzeyinde sayım
  istisna: {tur, gerekce, veren, zaman, gecerli} | null,      // son kayıt; gecerli = aynı
      // tablo kümesiyle verilmiş (kapı yeniden gerekçe istemez)
  neden: cagri_hatasi|replay_miss|null }
```

`GET /cases/{id}/oracle?icerik_hash=` sarmalayıcısı: `{case_id, icerik_hash, guncel_icerik,
kapsayan_tablolar: [{id, ref, ad, icerik_hash}], oracle}`. `POST /cases/{id}/oracle-check
{icerik?}` → 202 `{job_id, icerik_hash}`; iş `(case, hash, tablo kümesi, kayıt sürümü)`
anahtarlıdır, case başına dakikada 10 yeni iş.

**Model çıktısı** (`case_facts` şema v2): `{groups: [{table_ref, inputs[], expected[]}], ignored:
[{field, quote, reason}]}` — `ignored` zorunludur. Beklenen alanlardaki (`steps[i].expected`,
`expected_result`, `verification_point`) her sayı bir olgunun ya da `ignored` kaydının alıntısı
içinde olmalı; değilse kayıt `kismen` olur (fark varsa `uyumsuz`).

**Karar gövdesi** (`POST /cases/{id}/decision`, `approve` | `edit`): `oracle_istisna_gerekce?`
(≤ 2000; iki tür için de) + `oracle_istisna_turu?: uyumsuz|kontrolsuz` (verilmezse sonuçtan
çıkarılır; sonuca uymazsa 422 `gecersiz_karar`). Gerekçe boşluk atılınca ≥ 20 karakter ve ≥ 10
harf (değilse 422 `gecersiz_karar`).

**Kapı** (`oracle/kapi.py`). "Zorunlu" = yüksek risk (saklı, AI özgün ya da gönderilen içerikten
biri; `risk == "high"` ya da v3 `priority == "P1"`) ya da düşürme (V11; `oracle.dusurme` denetimi,
engellenen deneme de `engellendi: true` ile yazılır).

| Durum | Zorunlu | Diğer |
|---|---|---|
| kapsayan tablo yok · `uyumlu` · `kapsam_disi` | onay | onay |
| `kismen` | onay + uyarı | onay + uyarı |
| `uyumsuz`, gerekçe / geçerli istisna yok | 422 `oracle_uyumsuz` | onay + uyarı |
| `kontrol_edilemedi`, gerekçe / geçerli istisna yok | 422 `oracle_kontrolsuz` | onay + uyarı |
| gerekçe verildi ya da aynı tür + tablo kümesiyle önceki istisna | onay (`oracle_istisna`, `oracle.exception`) | onay + uyarı |
| kayıt yok, kapsayan tablo var | 409 `oracle_bekleniyor` (kontrol ayrı işlemde kuyruğa) | onay |
| `oracle-check` dakikalık sınır aşıldı | 429 `oracle_kontrol_siniri` | aynı |

Uyarılar karar kaydına (`review.duzeltme_olculeri.oracle_uyarilari`) ve `oracle.warning`
denetimine yazılır.

**Kontrol işleri.** `oracle.check_requirement {requirement_id, neden, nedenler?}` gereksinim başına
tek bekleyen işe birleşir (`oracle.service.gereksinim_kontrolu_kuyruga_al`; bekleyen iş varsa
`nedenler`'e eklenir, yoksa `TP_ORACLE_BIRLESTIRME_S` (2 sn) sonra koşacak yeni iş). Tablo onayı /
yeniden açma / onaylı tablonun geçersiz kılınması (`karar_tablosu.service.oracle_kontrolu_iste`),
case üretimi ve metamorfik türetme bu işlevi çağırır; §12.1'deki olay başına tekil anahtar kalktı.
`decide` (edit / reopen) aynı işlemde `oracle.check_case` açar. Onaylı case sonradan `uyumsuz`
çıkarsa (geçerli istisnasız) `oracle.onayli_uyumsuz` olayı + denetimi.

**`beklenti_dogrulugu`** (`oracle/metrik.py`): `{oran, uyumlu, uyumsuz, kismen, kontrol_edilemedi,
kapsam_disi, istisna, kontrolsuz_onay, n_case, n_story, tablolu_story, toplam_story, kapsam_orani,
golden_kaynakli, tekrar, kaynak}`. `oran = uyumlu / (uyumlu + uyumsuz)` (payda 0 → `null`);
`kapsam_orani = (uyumlu + uyumsuz + kismen) / tablolu story'lerdeki AI case toplamı`; `tekrar` =
aynı gereksinimde aynı satırı aynı değerlerle denetleyen, tek sayılan case'ler (paydadan da düşülür);
`istisna` / `kontrolsuz_onay` = `oracle_istisna`'dan case ve tür başına bir. Kule değeri `kaynak`
taşımaz (metin `kaynaklar`'dadır); Kule ayrıca `onayli_uyumsuz: [{case_id, requirement_id,
baslik}]` verir (onaylı/yayınlı, güncel içeriğin geçerli kaydı `uyumsuz`, aynı tablo kümesiyle
`uyumsuz` istisnası yok).

**Hata koşusu** (`/fault-runs`). Koşu: `{id, durum, iptal_istendi, platformlar, hatalar, commit,
baslatan_id, baslatan, ozet | null, uyarilar, baslama, bitis, olusturma}`; iptal yanıtı `{id, durum,
iptal_istendi}` (koşan adım varken koşu `running` kalır). Adım: `{id, platform, hata_kodu,
hata_adi, asama: temel|hata|kapanis, run_id, sonuc, kiran_testler: [{test, kaynak: ai|el}],
temelde_kirmizi: [test], neden, sure_ms, sira}`. Özet:

```
{ oran, yakalanan, kacan, gecersiz, bekleyen,          // oran = AI (üretilen testler)
  el_yazisi: {oran, yakalanan, kacan}, tum_testler: {oran, yakalanan, kacan},
  kapsam: {kosulan_hata, katalog, platformlar, tam_katalog, gecerli_adim},
  platformlar: [{platform, oran, yakalanan, kacan, gecersiz, bekleyen, el_yazisi, tum_testler,
                 uretilen_test, el_test, temel, kapanis}],
  kacanlar: [{hata_kodu, ad, platform}] }
```

Kule `hata_yakalama`: son `done` koşu ki `kapsam.tam_katalog` ve `gecerli_adim ≥ 1`; şekil
`{son_kosu: {id, bitis, durum}, oran, yakalanan, kacan, gecersiz, el_yazisi, tum_testler, kapsam,
platformlar: [{platform, oran, yakalanan, kacan, gecersiz, el_yazisi}], kacanlar}`. Katalog
(`GET /fault-runs/catalog`): `{kod, ad, tur, aciklama, yakalayan_kural, ac_refs, tablo,
ayirt_edici: {girdi, dogru, hatali}}`; `kampanya_esik_7` yerine `kampanya_tek_bedava` (K9).
Hatalar: 409 `hata_kosusu_suruyor`, 422 `gecersiz_istek`.

**Karar tablosu ve ilişki.** `GET /decision-tables/{id}/ornekler` → `{ornekler: [{girdiler,
satir_id, ciktilar, hata}], uyarilar: [{tur: ortusme|hic_eslesmez|golgede|satir_yok|hata|
ornek_sinirli|gecersiz, mesaj, satirlar?, girdiler?}]}`. İlişki öğesi `karar_tablosu_id` ve
`tablo_engeli` taşır (onaylı ilişkinin bağlı tablosu onaylandığı sürümde değilse nedeni; o zaman
`bayat: true`; sürüm onay review'unun `sonra.bagli_tablo`'sundadır). İlişki içeriğinde isteğe bağlı
`degismez: [metin]` (≤ 20, ≤ 80 karakter): türetmede değişmeyen parçalar. TPD-1 T1 V9'dur
(`adet`, `ara_toplam` → `bedava_adet`, `indirim`, `toplam`; ilişki `ara_toplam`'ı da ikiye katlar).

**Metamorfik türetme.** Sonuç += `tutarsiz_kalan_deger`: kaynak grupta `degismez` parçasıyla
örtülmeyen karşılaştırılamayan değer varsa ya da yeniden yazılan alanda olgusuz/örtülmeyen sayı
kalırsa türetme yapılmaz. Yalnız sonucu `uyumlu` grup türetir. Olmayan ilişki 404
`iliski_bulunamadi`.

**Triage.** Sinyal `{kod, aciklama, kaynak, kanit, baslik?}`; karar tablosu sinyalleri tek satırlık
`baslik` taşır. `test_maintenance/beklenti` kararına ek sinyal `karar_tablosu_tablo_suphesi`
("Tablo da yanlış olabilir"). İnceltme yalnız başarısız adıma ait karşılaştırmada; kayıtlı istisna
inceltmeyi kapatır.

### 13.3 Açık konular

Review turu 2 (2026-11-12) sonrası güncel liste. Kapananlar: v3 birleştirme notu (→ §14), demo
dokümanları (`docs/DEMO-VERISI.md` ve `docs/DEMO-AKISI.md` 012 bölümleri; minimum sipariş 500 → 750
geçmişi), test rehberi §8 (tur 1/2 davranışı).

- **Golden'ların canlı kaydı (ürün sahibi):** `case_facts` (ana yol, `f2-kod-hatasi`,
  `rehber-duzeltme`, `ai-sinir-hatasi`) ve `decision_table_draft` golden'ları elle hazırlandı
  (`ai_call.model = golden-elle`). T2 taslak golden'ı tur 2'de bilerek AI sınır hatası taşır
  (`sepet_tutari <= 750`; PO düzeltir). `TP_MODEL_MODE=record` ile canlı kayıt ve
  `evaluations.yaml` `pending` → değerlendirme kararı bekliyor. Kule ve case metrikleri bu yüzden
  "REPLAY / elle golden — gösterge, model ölçümü değil" etiketini taşır. v3 birleşmesinde
  `case_facts` golden'ları v3 TPD-1 case metinlerine göre yeniden üretilmelidir (§14.6).
- **Asistan paketi değerlendirmesi (ürün sahibi):** `assistant` paketi `icerik_degisti` (§11.6);
  `test_readme_status_table_matches_manifest` ve `test_degerlendirme_durumu_durust_etiket` bu yüzden
  kırmızı (tam paketteki tek iki kırmızı). Seçenekler değişmedi: `make eval-live
  A=--update-status`, sahibin istisnası ya da `icerik_degisti`'yi kabul edip README ve testi
  güncellemek. Öneri kuralı 26 → 28 (K10 öneri onayı) aynı kararın parçasıdır; v3 birleşmesinde
  sayılar ayrıca değişir (§14.8).
- **`beklenti` için elle bug taslağı yolu yok:** `test_maintenance/beklenti` kararında bug taslağı
  ve locator onarımı açılmaz (doğru varsayılan). Tablo da yanlışsa (`karar_tablosu_tablo_suphesi`
  sinyali) kullanıcının ürün hatası taslağını elle açacağı bir uç ya da düğme yok; bugün yol
  "tabloyu yeniden aç → PO düzeltir → yeniden sınıflandırma"dır. Karar: elle "Ürün hatası taslağı
  aç" (gerekçeli, `failure` kararını değiştirmeden) eklenmeli mi?
- **`HataKosusuSuruyor` yeri:** hata koşusu hatası `karar_tablosu/hatalar.py`'de duruyor (Ş0 ortak
  hata modülü); `hata_kosusu` özelliğine taşınması düşünülmeli (mimari-15, tur 2'de Q2'de).
- **İsteğe bağlı kolonlar (R2/R4 önerisi):** `karar_tablosu`/`metamorfik_iliski`'de
  `son_duzenleyen_id`, `insan_duzenledi`, `metamorfik_iliski.tablo_onaylanan_hash` (bugün denetim
  kayıtları ve onay review'undan okunuyor); `hata_kosusu`'nda iptal işareti ve temel envanter için
  kolon (bugün `ozet._ic` JSON'ında). Dal dev'e girmediği sürece `0022` yerinde güncellenebilir;
  v3 birleşmesinden sonra (`0029`) yeni kolon yeni migrasyon ister. Karar birleşmeden önce
  verilmeli (§14.9 adım 0).
- **v3 birleşmesi:** plan ve riskler §14'tedir. Ürün sahibi onayı (K7) olmadan hiçbir dal dev'e
  birleşmez.

## 14. `feat/case-gen-v3` ile birleştirme planı

Durum: 2026-11-12, `feat/case-gen-v3` (`ee35221`, `e0e5015`'ten 353 dosya) ile bu dal yan
yanadır; ikisi de dev'e girmedi. Bu bölüm v3 dalının kendisi okunarak yazıldı (`git show
feat/case-gen-v3:<yol>`); satır numaraları o commit'e aittir. Mimari review 1 (#1, #2, #3, #7, #16,
#19) ve test/mimari review 2 (`t2` N7) bulgularının birleşik cevabıdır. §2.1 V7 ve §12.1'deki
"`0021`" notları bununla geçersizdir.

### 14.1 Migrasyon: yeniden numaralandırma

v3 zinciri (hepsi tek baş, `0020`'den):

| Rev. | Dosya | `down_revision` | 012 ile ilgisi |
|---|---|---|---|
| `0021` | `0021_case_uretim.py` | `0020` | `case_uretim` (tp_app'e başta DELETE verir) |
| `0022` | `0022_tasarim_modeli.py` | `0021` | `tasarim_modeli`; gereksinim durumlarına `modeling`, `model_ready`; **`review_nesne_turu_ck` += `design_model`** |
| `0023` | `0023_case_set_review_audit.py` | `0022` | `case_set_review`, `case_set_audit` |
| `0024` | `0024_uretim_secenekleri.py` | `0023` | — |
| `0025` | `0025_agent_probe.py` | `0024` | `asistan_denetim`, `ajan_*` |
| `0026` | `0026_kalite_yetkileri.py` | `0025` | DELETE/TRUNCATE geri alımı; `case_set_audit_tamam_karar_ck`; **`review_ret_nedeni_ck` yeniden kurulur** |
| `0027` | `0027_agent_probe_sertlestirme.py` | `0026` | yetki sertleştirme (`asistan_denetim`, `ajan_testi_talebi`) |
| `0028` | `0028_acik_soru.py` | `0027` | açık soru tablosu |

Bu dalın `0022_kalite_dogrulama.py`'si v3'ün `0022_tasarim_modeli`'siyle **aynı revision kimliğini**
taşır (Alembic iki `0022` görünce yüklenmez). Birleşmede:

- `git mv core/alembic/versions/0022_kalite_dogrulama.py core/alembic/versions/0029_kalite_dogrulama.py`
- `revision = "0029"`, `down_revision = "0028"`; docstring `Revision ID: 0029`, `Revises: 0028`.
- İçerik (tablolar, yetkiler, CHECK'ler) değişmez; yalnız `review_nesne_turu_ck` listeleri (14.2).
- `docs/MIMARI-SOZLESME.md` 012 tablo paragrafındaki migrasyon adı `0029` olur.

### 14.2 `review_nesne_turu_ck` birleşimi

Kısıtın değeri iki yerden gelir: ORM'de `in_check("nesne_turu", enums.REVIEW_NESNE, …)`
(`models/requirements.py`), `REVIEW_NESNE = frozenset(KARARLAR)`; migrasyonda elle yazılmış liste.
v3'ün `0022_tasarim_modeli.py:36-39` listesi `design_model`'i ekler; bu dalın `0022` listesi
`karar_tablosu`, `metamorfik_iliski`'yi ekler ve **v3'ten habersiz** eski kümeyi (`design_model`'siz)
geri yükler. v3'te bu kısıta 0022'den sonra dokunan başka migrasyon yoktur (`git grep
nesne_turu_ck feat/case-gen-v3` yalnız `0002` ve `0022_tasarim_modeli`).

`0029_kalite_dogrulama.py`'de olması gereken:

```python
_NESNE_ESKI = (  # v3 0022_tasarim_modeli sonrası küme (downgrade bunu geri yükler)
    "'bug_draft', 'consistency_finding', 'design_model', 'requirement', 'script', 'test_case'"
)
_NESNE_YENI = (
    "'bug_draft', 'consistency_finding', 'design_model', 'karar_tablosu', 'metamorfik_iliski', "
    "'requirement', 'script', 'test_case'"
)
```

- **upgrade:** `DROP CONSTRAINT review_nesne_turu_ck` → `CHECK (nesne_turu IN (<_NESNE_YENI>))`
  (sekiz değer, alfabetik; ORM `in_check` sıralı yazar, `test_migrations` model ↔ şema eşitliği
  bunu bekler).
- **downgrade:** `CHECK (nesne_turu IN (<_NESNE_ESKI>)) NOT VALID` — v3'ün altı değerlik kümesi,
  `design_model` **dahil**. `design_model` düşerse `0028`'e inen bir veritabanında tasarım modeli
  kararı yazılamaz. `NOT VALID` korunur: `karar_tablosu` review satırları geçmiştir, silinmez.
- `REVIEW_NESNE` kod tarafında kendiliğinden birleşir (`KARARLAR` iki dalın türlerini taşıyınca);
  `workflow/states.py` birleşiminde `KARARLAR`, `MACHINES`, `APPROVER_ROLES` ve v3'ün
  `ENTITY_BY_TABLE`'ı birlikte kalmalı. `ENTITY_BY_TABLE` yalnız `tasarim_modeli → design_model`
  eşler; bizim tablo adlarımız tür adıyla aynı olduğu için varsayılan yoldan geçer.

### 14.3 v3 `0026_kalite_yetkileri` etkileri

- **DELETE geri alımı:** yalnız `case_uretim`, `tasarim_modeli`, `case_set_review`,
  `case_set_audit` için. 012 tablolarına `tp_app` zaten DELETE/TRUNCATE vermez, `oracle_istisna`
  yalnız SELECT/INSERT — çakışma yok, ek iş yok. v3'ün
  `test_0026_tp_app_kalite_kayitlarini_silemez` testi yalnız kendi dört tablosunu dener; 012
  tablolarının eşleniği `test_durum_makinesi.py`'de vardır.
- **`review_ret_nedeni_ck`:** `CHECK (ret_nedeni IS NULL OR ret_nedeni IN (CASE_RET ∪ MODEL_RET))`.
  Karar tablosu ve ilişki review'ları (`approve`, `request_changes`) `ret_nedeni` **yazmaz**
  (`karar_tablosu/service.py` `record_approval`'a `ret_nedeni` geçirmez → `NULL`): kısıtı sağlar.
  `review_ret_ck` (`karar <> 'reject' OR ret_nedeni IS NOT NULL`) da etkilenmez (bizde `reject` yok).
  v3'ün `record_approval`'ı ret nedenini `ret_nedenleri(kind)`'e göre denetler; `karar_tablosu` /
  `metamorfik_iliski` için ortak `RET_NEDENLERI` döner — `request_changes`'te neden verilmediği
  sürece etkisiz. Birleşmeden sonra bir PO değişiklik isteğine taksonomik neden eklenmek istenirse
  (ör. `wrong_boundary` — T2 hikâyesi) bu, `ret_nedenleri()`'ne yeni dal ve `0029`'da kısıt
  değişikliği ister; bugün kapsam dışı.

### 14.4 Revizyonu sabitleyen testler

| Dosya | Bu dalda | Birleşmede |
|---|---|---|
| `core/tests/unit/platform/test_aiprobe_sso.py:938-943` `test_alembic_tek_bas` | `bas == ["0022"]`, `0022.down_revision == "0020"` | v3 sürümünü al (`0021`…`0028` zinciri), `bas == ["0029"]` ve `0029.down_revision == "0028"` ekle. v3 sürümündeki **yinelenen** assert blokları (`938-966`, aynı satırlar üç kez) temizlenmeli |
| `core/tests/unit/features/karar_tablosu/test_durum_makinesi.py:453-475` `test_0022_geri_alinir_ve_yeniden_yukselir` | `run_alembic(…, "0020", "downgrade")` | `"0028"`; test adı `test_0029_…`. `"0020"`'de kalırsa v3'ün sekiz migrasyonunu da geri alır (test yavaşlar, v3 downgrade'lerini de dener) |
| `core/tests/unit/platform/test_migrations.py` (model ↔ şema eşitliği) | — | Kod değişmez; `review_nesne_turu_ck` sekiz değerle eşleşmeli (14.2) |
| Diğer `run_alembic(…, "<rev>", "downgrade")` çağrıları (`0016`, `0011`, `0009`, `0014`) | — | Etkilenmez (ikisi de aynı) |

İki dalda başka sabit revizyon yoktur (`git grep -nE '"00(19|2[0-9])"'` her iki dalda core
testleri ve kaynağı).

### 14.5 Kancaların taşınması (`cases/service.py`, `cases/api.py`, `cases/toplu.py`)

Bu daldaki kancalar `# --- 012 … # --- /012 ---` işaretlidir. v3 satırları `ee35221`'e göredir.

| Kanca | Bu dalda | v3'te yeri |
|---|---|---|
| Üretim sonrası kontrol: `oracle_service.uretim_sonrasi(session, req.id)` (eklenen varsa) | `store_cases` sonu, `session.flush()` ile `return` arası | `service.py:823-824` arası. v3'te `store_cases`'i üç yol çağırır: `run_generation` (`:1074`), `submit_drafts` (`:1362`, IDE/MCP) ve **`deepen.py:469`** (derinleştirme) — kanca tek yerde kalınca üçü de kapsanır (mimari-7) |
| `decide` imzası: `oracle_istisna_gerekce`, `oracle_istisna_turu` | parametreler | `service.py:1482-1494`; v3'ün yeni `ek_olculer` parametresinden sonra |
| `reopen` sonrası `oracle_service.karar_sonrasi(session, tc)` | `if karar == "reopen":` dalı | `service.py:1504-1505` (`return _reopen(...)` yerine sonuç değişkene alınıp kanca + return) |
| Onay kapısı `oracle_kapi.onay_denetimi(...)` → `olculer["oracle_uyarilari"]` | `approve`/`edit` dallarından sonra, `review_sure_ms`'ten önce | `service.py:1561`–`1562` arası: v3'ün K6 `approval_block` (`:1520`), düzeltmenin `content_errors` / `readiness` denetimleri (`:1523-1553`) ve `acik_sorular.record_correction_source` (`:1557`) **ondan önce** koşar. Böylece şema/hazırlık hatası 422'si kapıdan önce döner, kapının 409'u boşuna kontrol işi açmaz. `olculer.update(ek_olculer)` (`:1564`) kapı uyarılarını ezmez (farklı anahtar) |
| Düzeltme sonrası `karar_sonrasi(session, tc)` | `transition(... hedef ...)` sonrası, `karar == "edit"` | `service.py:1579` sonrası (`return tc`'den önce) |
| `serialize_cases`: `case_oracle_ozetleri` | `old_content_case_ids` döngüsünden sonra | `service.py:1707` sonrası |
| `serialize_cases`: `uyarilar += oracle_uyarilari` | eski içerik uyarısından sonra | `service.py:1727` (`consistency_problems`) sonrası |
| `serialize_cases`: `"oracle": …` | `"olusturma"`'dan sonra | `service.py:1784` sonrası |
| `requirement_metrics`: `"beklenti_dogrulugu"` + `_beklenti_dogrulugu` | `"manuel_baz": baz` sonrası | `service.py:2057` sonrası; yardımcı işlev `requirement_metrics`'in ardına |
| API gövdesi: `CaseKararGirdisi.oracle_istisna_gerekce`, `oracle_istisna_turu` | `cases/api.py` | v3 `api.py:59-77` (sınıf sonu, `beklenen_anlam_degisti`'den sonra) |
| API çağrısı: iki alanın `service.decide`'a geçmesi | `cases/api.py` | v3 `api.py:169-179` |

Ayrıca: tur 2 düzeltme şeritleri (Q1) kapının imzasını değiştirebilir (ör. görülen kayıt damgası,
g2 Y9); taşıma, birleşme anındaki bu dalın kanca bloklarını birebir alır, bu tablo yer gösterir.

**Toplu onay (`cases/toplu.py`, 011 K20).** `bulk_approve` (`toplu.py:69`) her kalem için kendi
SAVEPOINT'inde `service.decide(..., karar="approve", icerik_hash=...)` çağırır (`:82`); `WorkflowError`
yakalanır ve kalem `{basarili: false, hata, kod: exc.status_code}` olur (`:84-93`). Kapıyla etkileşim:

- `OracleUyumsuz` (422), `OracleKontrolsuz` (422), `OracleBekleniyor` (409) ve `OracleKontrolSiniri`
  (429) `WorkflowError`'dır: kalem başarısız olur, diğerleri sürer — doğru davranış (yüksek riskli
  uyuşmazlık toplu onayla aşılamaz).
- 409 yolunda kapı kontrol işini **ayrı bir işlemde** (ikinci bağlantı) kuyruğa alır; SAVEPOINT
  geri alımı bunu silmez (istenen). 50 kalemlik toplu onayda en çok 50 sıralı ek bağlantı açılır
  (mimari-19); g2 Y6'nın kullanıcı/gereksinim başına sınırı (Q1) bunu da sınırlar.
- **İstisna gerekçesi geçirilemez:** `TopluKalem` yalnız `case_id`, `icerik_hash` taşır
  (`api.py:184-188`, `extra="forbid"`). Öneri (sözleşme değişikliği): toplu onaya istisna
  **eklenmez** — istisna case başına insan yargısıdır, V10'un iki yolu (istisna / "Tablo yanlış")
  tekil formdadır. Bunun yerine kalem sonucuna `hata_kodu: exc.kod` (`oracle_uyumsuz`,
  `oracle_kontrolsuz`, `oracle_bekleniyor`, `oracle_kontrol_siniri`, …) eklenir; mevcut `kod`
  (HTTP durum sayısı) geriye uyum için kalır. Portal toplu sonuç listesinde bu kodlu kalemleri
  "Tekil kararda istisnayla onaylayın" bağlantısıyla case kartına götürür; `oracle_bekleniyor`
  kalemi için "kontrol bitince yeniden deneyin". `MIMARI-SOZLESME` `POST /cases/bulk-decision`
  satırı buna göre güncellenir.
- `assumption_verified` (`toplu.py:146`, `:191`) `decide(karar="edit")` çağırır ve istisna alanı
  geçirmez: yüksek riskli uyuşmazlıkta 422 döner; analist "Düzelt" ile tekil yoldan gider. Kabul
  edilir; portal mesajı `oracle_uyumsuz` için tekil forma yönlendirmelidir.

### 14.6 İçerik ve girdi uyumu

- **risk → priority:** v3 case'inde `risk` yoktur, `priority` (`P1|P2|P3`) zorunludur
  (`case_generation.schema.json`). Yüksek risk tek işlevdedir: `oracle/dogrulama.py:779
  yuksek_risk_mi` = `risk == "high"` **veya** `priority == "P1"`; düşürme özeti (`kapi.py:265-266`)
  `risk or priority` okur. Ek iş yok. **Demo etkisi:** v3 TPD-1 golden'ında (`f2-kod-hatasi`, 15
  case) minimum tutara eşitlik case'i (C6) `P2`'dir; AI sınır hatası hikâyesinde (`docs/DEMO-VERISI.md`
  012 bölümü) kapı 422 yerine **uyarıyla** onaylar. v3'te bu gösterim için ya varyant golden'ı `P1` yazar
  ya da sahnede "orta öncelikte uyarı, yüksekte engel" anlatılır (karar: ürün sahibi).
- **Alan grameri:** `test_data[i].value`, `verification_point`, `teardown` kabul edilir
  (`dogrulama.py:84-91`, V12). v3'te `verification_point` bir enum'dur (`UI|API|event|DB|log|other`);
  sayı taşımadığı için tamlık denetimine etkisi yoktur.
- **`case_facts` girdisi** case JSON'unun tamamıdır (`oracle/cikarma.py facts_messages`): v3
  case'leri yeni alanlarla gelir, bu yüzden bugünkü golden'ların `input_match.case_text`'i v3
  metniyle eşleşmez → REPLAY-MISS → `kontrol_edilemedi` → P1 case'te 422 `oracle_kontrolsuz`.
  **Birleşmede zorunlu:** `python -m tests.unit.features.oracle.tpd1` v3 `f2-kod-hatasi/TPD-1`
  case'lerinden yeniden üretilir; v3'ün 15 case'i için C numaraları ve beklenen sonuç tablosu
  (§12.2, `test_tpd1_uctan_uca.py`) yeniden yazılır. Kazanç: v3 golden'ında 13 ve 14 adetlik
  kampanya case'leri vardır; bunlardan üretilen testler `kampanya_tek_bedava`'yı yakalar (bugün
  kaçan tek hata).
- **`ONAYLI_GEREKSINIM`:** `karar_tablosu/service.py:94-107` v3 durumlarını (`modeling`,
  `model_ready`) makinede varsa kendiliğinden ekler; ek iş yok (mimari-16).
- **Taslak girdisinde açık soru yanıtları:** `karar_tablosu/service.py:1008 acik_soru_yanitlari`
  v3'ün `cases.acik_sorular.generation_input`'unu (v3 `acik_sorular.py:569`; case üretimi,
  derinleştirme ve tasarım modeli de bunu kullanır) `importlib` ile arar, yoksa boş metin döner.
  v3'te işlev vardır, birleşince yanıtlar taslağa girer. Birleşmede dinamik arama doğrudan
  içe aktarmaya çevrilmeli ve "yanıtlı soru taslak mesajında görünür" testiyle sabitlenmeli
  (işlev adı değişirse sessizce boş dönmesin). PO ön inceleme cevapları zaten
  `_onaylanan_sorular` / `_po_cevaplari_metni` ile gider.
- **Bağımsızlık kuralı 1 (case üretim girdisi tablo taşımaz):** v3'te case üretimine giden üç
  girdi vardır — `generation_messages` (`service.py:429`), derinleştirme (`deepen.py:196
  deepening_messages`) ve tasarım modeli (`model_service.py`). Mevcut test
  (`tests/unit/features/oracle/test_oracle_db.py:616`) yalnız `generation_messages`'ı denetler;
  birleşmede üçünü kapsayacak şekilde genişletilir.

### 14.7 Kontrol Kulesi ile v3 `case_kalitesi.py`

v3 ayrı uç ekler: `GET /control-tower/case-quality` (`control_tower/case_kalitesi.py`; kapsam, set
review skoru, denetim kararı, tekrar, readiness, içerik denetimi, sürümler). 012 ise
`GET /control-tower`'a `beklenti_dogrulugu`, `hata_yakalama`, `onayli_uyumsuz` ekler. Kod düzeyinde
çakışma yok (ayrı dosya, ayrı uç; `control_tower/api.py` birleşimi iki satır). Anlam çakışmaları:

- **`tekrar`** iki yerde farklı anlamdadır: v3'te set review'un `remove_or_merge` önerisi oranı;
  012'de aynı satırı aynı değerlerle denetleyen, tek sayılan case sayısı. Portalda ikisi aynı
  ekranda görünürse etiketler ayrılmalı ("tekrar öneri" / "aynı denetim").
- **Kapsam:** v3 `oranlar.gereksinim_kapsami` (kapsam matrisi) ile 012 `kapsam_orani` (tablolu
  story'lerde kontrol edilebilen AI case oranı) farklı paydalardır; KPI şeridinde yan yana
  konacaksa "tablo kapsamı" adı korunmalı.
- Öneri: 012 anahtarları `/control-tower`'da kalır; ileride "Case kalitesi" bölümüne taşınması
  ayrı karardır.

### 14.8 Asistan

- `assistant/tools/probe.py`: v3 `REQUIREMENT_KAPILARI`'na `modeling`, `model_ready` ve analist
  kuyruğuna `model_ready` ekler; 012 `_failure_kapisi`'na `beklenti` dalı ekler — farklı işlevler,
  birleşim elle ama basit.
- Kural sayıları: `oneriler.yaml` dev 26, v3 26 (yalnız `bos_ekranlar` += `/ajan-urunleri`), 012
  28 → birleşik **28**; `test_oneri.py:47-50` 012 sürümü (28) alınır. `hata-sozlugu.yaml` dev 24,
  v3 27 (+3 `ajan-*`), 012 32 (+8) → birleşik **35**. `rotalar.json` v3 satırı eklenir.
- Asistan paketi iki daldan da içerik değiştirir; `assistant@v1` `icerik_degisti` kalır (§13.3).

### 14.9 Sıra ve test komutları

0. Ürün sahibi kararları: §13.3 isteğe bağlı kolonlar (birleşmeden önce `0022`'ye mi, sonra yeni
   migrasyona mı), v3'te C6 önceliği (14.6), toplu onay sözleşmesi (14.5). Q1–Q4 bu dala birleşmiş,
   tam paket yeşil (asistan değerlendirme kaydı dışında).
1. Hangi dal dev'e önce girerse girsin birleştirme ayrı dalda yapılır:
   `git switch -c merge/012-v3 feat/test-kalite-dogrulama && git merge feat/case-gen-v3`.
2. Migrasyon: 14.1 + 14.2; testler 14.4.
   `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/platform/test_aiprobe_sso.py::test_alembic_tek_bas tests/unit/platform/test_migrations.py tests/unit/features/karar_tablosu/test_durum_makinesi.py -q`
3. Ortak dosyalar: `workflow/states.py`, `models/enums.py`, `models/__init__.py`, `rules/models.yaml`,
   `rules/evaluations.yaml`, `rules/README.md` (iki tarafın blokları birlikte);
   `review-portal/src/api/sozlesme/durum-makineleri.json` yeniden üretilir; portal `types.ts`,
   `client.ts`, `mock/handlers.ts` birleşimi.
4. Kancalar 14.5 (+ toplu `hata_kodu`).
   `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/cases tests/unit/features/oracle tests/unit/features/karar_tablosu tests/unit/features/metamorfik -q`
5. Golden'lar ve uçtan uca (14.6): `case_facts` yeniden üretimi, §12.2 tablosunun v3 karşılığı,
   bağımsızlık testinin üç girdiye genişlemesi.
   `cd core && uv run python -m tests.unit.features.oracle.tpd1 && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/kalite_e2e tests/unit/gateway/test_codegen_goldens.py tests/unit/integrations/test_jira_seed.py -q`
6. Asistan ve Kule (14.7, 14.8):
   `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/assistant tests/unit/features/control_tower tests/unit/features/hata_kosusu tests/unit/features/triage -q`
7. Statik: `cd core && uv run ruff check && uv run ruff format --check`;
   `cd review-portal && npm run typecheck && npx vitest run`; demo API `cd demo-app/api && uv run pytest`.
8. Tam paket bir kez: `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest -q`.
9. İzole yığında (`COMPOSE_PROJECT_NAME=tp-kalite`) `alembic upgrade head` → `downgrade 0028` →
   `upgrade head` gidiş-dönüşü; TPD-1 uçtan uca (rehber §8) ve Chrome for Testing ekran turu.

### 14.10 Riskler

| Risk | Etki | Önlem |
|---|---|---|
| `0022` revision çakışması | Alembic yüklenmez; tüm DB testleri düşer | 14.1 (ilk adım) |
| Downgrade `design_model`'i düşürür | `0028`'e inen DB'de tasarım modeli kararı yazılamaz | 14.2 `_NESNE_ESKI` v3 kümesi |
| `case_facts` golden'ları v3 metniyle eşleşmez | P1 case'lerde 422 `oracle_kontrolsuz`; demo kilitlenir | 14.6 yeniden üretim; birleşme testi `kalite_e2e` |
| C6 v3'te `P2` | AI sınır hatası demosu engel yerine uyarı | 14.6 karar |
| Toplu onayda istisna yolu yok | Kullanıcı neden reddedildiğini göremez | 14.5 `hata_kodu` + portal yönlendirmesi |
| v3'ün yeni case girdileri (deepen, tasarım modeli) bağımsızlık testinin dışında | Tablo içeriği sızarsa fark edilmez | 14.6 test genişletmesi |
| Kule'de iki "tekrar" / iki "kapsam" | Yanlış okuma | 14.7 etiketler |
| Kapı v3'ün K6 denetiminden önce koşarsa | Hazır olmayan case için boşuna kontrol işi + 409 | 14.5 sıralama |

# rules/replay — REPLAY kayıtları ve Demo-A golden'ları

Anahtarsız demo (`TP_MODEL_MODE=auto` → `replay`) her AI adımını bu dizindeki kayıtlardan oynatır.
Mod her zaman `replay` veya `replay_miss`'tir, **asla `live` değildir** (constitution VIII); portal
REPLAY / REPLAY-MISS rozetini `ai_call.mod`'dan gösterir.

## Arama sırası

1. **Birebir kayıt** `<amaç>/<anahtar>.json` (`TP_MODEL_MODE=record` veya `promote` ile yazılır).
   Köken: `recorded` / `golden_promoted`.
2. **Eşleşen golden** `<amaç>/golden/<ad>.json`: golden `input_match` ile hangi girdi için
   hazırlandığını beyan eder; gerçek girdi beyana uyarsa mod **`replay`**, köken
   `golden_matched` (`ai_call.ek.replay_kokeni`).
3. **Eşleşmeyen golden**: mod **`replay_miss`**, nedenler `ai_call.ek.replay_eslesme`'de
   (ör. `["AC2 metni farklı"]`). `TP_REPLAY_STRICT=1` (prova) bunu `ReplayMiss` hatasına çevirir.
   - Golden girdi beyanı (`input_match`) taşıyorsa ve amacın **nötr yedeği**
     (`<amaç>/on_miss.json`) varsa golden çıktısı **kullanılmaz** (başka bir dokümanın cevabıdır);
     nötr yedeğin çıktısı döner, köken `miss_neutral`, `cikti_kokeni = notr_yedek`.
   - Beyansız golden (senaryo adı: `triage`, `bug_draft`, `dup_rank`) veya nötr yedeği olmayan
     amaç: golden çıktısı döner, köken `golden`.
4. Golden de yoksa `ReplayNotFound`.

### REPLAY-MISS'te ön inceleme (`requirement_review/on_miss.json`)

Ön inceleme sorularına deterministik doğrulama uygulanmaz (bulgulardaki kanıt denetimi gibi);
eşleşmeyen golden'ın soruları gösterilirse kullanıcı başka gereksinimin sorularını, olmayan AC'lere
atıflarla (ör. tek AC'li serbest metinde "AC2'de her 7 adette…") "AI soruları" olarak görür. Bu
yüzden ön incelemede REPLAY-MISS her zaman nötr çıktı verir:

```json
{"questions": [], "verdict": "needs_po",
 "summary": "Bu girdi için kayıtlı model çıktısı yok (REPLAY-MISS); canlı model gerekir. …"}
```

`verdict = needs_po`: AI incelemesi yapılmadı, gereksinim insan incelemesine kalır (hiçbir zaman
`ready` denmez). Golden'ın soruları ai_call'a da yazılmaz (`cikti` = nötr çıktı;
`replay_eslesme` nedenleri saklar). `promote` nötr satırları yükseltmez ("nötr REPLAY-MISS yedeği;
yükseltilmez"): başka dokümanın sorularını bu girdinin kaydı yapmak aynı hatayı kalıcılaştırır.
**Jira:** REPLAY-MISS ön incelemesinde PO yorumu "AI ön incelemesi yapılamadı (REPLAY-MISS …)"
notunu taşır; "sorular var" denmez (gereksinim akışı, `review_comment`).

### REPLAY-MISS'te tutarlılık denetimi (`consistency_check/on_miss.json`)

Eşleşmeyen golden'ın bulguları başka bir dokümana aittir; kod kanıtındaki satır demo-app'te var
olduğu için deterministik doğrulamadan bile geçebilir (ör. "Sipariş iptali" serbest metninde SERBEST
golden'ının kampanya bulgusu). Bu yüzden denetim de REPLAY-MISS'te nötr çıktı verir
(`{"findings": [], "notes": "… REPLAY-MISS …"}`); gereksinim akışı bu turu güvenilmez sayar ve
belgeyi otomatik son hal yapmaz (analist açıkça "Son hal olarak onayla" der).
Case üretiminin nötr yedeği yoktur (şema en az bir case ister): REPLAY-MISS case'leri
`REPLAY-MISS` rozetiyle taslak olarak gelir, analist reddeder.

### Çıktının kökeni: hazırlanmış örnek mi, model kaydı mı

Bu dizindeki golden çıktıları **elle hazırlanmıştır** (`note`); hiçbiri bir modelin ürettiği kayıt
değildir. Geçit bunu kayda ve etikete taşır:

| Kaynak | `ai_call.model` | `ek.cikti_kokeni` | `mode_label(...)` |
|---|---|---|---|
| `record` modunun yazdığı birebir kayıt (`recording` üst verisi) | kaydeden model | `model_kaydi` | REPLAY (<model> ile kaydedilmiş model çıktısı) |
| `recording` üst verisi taşıyan golden (canlı kayıttan kopyalanmış) | `recording.model` | `model_kaydi` | aynı |
| Elle hazırlanmış golden, ondan `promote` edilmiş kayıt | `golden-elle` | `elle_hazirlanmis` | REPLAY (hazırlanmış örnek çıktı; canlı model değil) |
| Nötr REPLAY-MISS yedeği | `golden-elle` | `notr_yedek` | REPLAY-MISS (bu girdi için kayıtlı model çıktısı yok; canlı model gerekir) |

`record` modu kayda `recording = {model, provider, latency_ms, input_tokens, output_tokens}` ve
`recorded_at` yazar. Bir golden'ı canlı kayıtla yenilerken bu alanlar golden'a taşınmalıdır; aksi
hâlde çıktı "hazırlanmış örnek" olarak etiketlenir. Jira yorumu ve portal ipucu
`tp_core.gateway.mode_label(mode, ai_call.model)` kullanmalıdır ("kayıtlı model çıktısı" yalnızca
gerçek kayıtta).

**Sunucu için tek cümle:** "Bu demoda anahtar yok; ekranda REPLAY yazan AI çıktıları, bu
gereksinimler için ekibimizin hazırladığı örnek çıktılardır, canlı Claude çıktısı değildir — kanıt
doğrulaması, insan onay kapıları ve denetim kaydı ise gerçekten çalışan koddur; canlı anahtarla aynı
akış modelin kendi cevabını üretir."

Böylece **senaryodaki demo yolu REPLAY-MISS'siz** koşar (§13 prova maddesi, yükseltme
gerekmeden), story/case değişirse dürüstçe REPLAY-MISS olur. Bunu
`core/tests/unit/gateway/test_replay_matching.py` gerçek kod yoluyla (jira-sim → `RestJira` →
`requirement_block` → geçit, sıkı kip) doğrular.

### `input_match`

```json
"input_match": {
  "sources": ["jira:TPD-1"],
  "acceptance_criteria": ["AC1: …", "AC2: …"],
  "contains": ["<açıklama paragrafı>"]
}
```

- `sources`: `fnmatch` desenleri; yalnızca bu kaynaklı `<untrusted>` blokları okunur (PO
  cevapları, önceki bulgular gibi başka bloklardaki `AC3: …` alıntıları karışmaz).
- `acceptance_criteria`: bloklardaki `ACn: metin` satırları **tam olarak** bu küme olmalı
  (NFC + boşluk daraltma dışında gevşetme yok). `[]` = AC yok (TPD-2).
- `contains`: her metin girdide geçmeli (story açıklaması; verify_and_map'te case başlığı, adım
  eylemleri ve beklenenleri).
- Desteklenen gövde biçimleri: düz satırlar (`AC1: …`, `- AC1: …`), JSON gövde, metne gömülü
  `json.dumps(...)` (ensure_ascii dahil).

**Özellik şeritleri için sözleşme:** story/serbest metin bloğunu `tp_core.gateway.requirement_block`
ile kurun (Jira: kaynak `jira:<KEY>`, tür `jira`; serbest metin: kaynak `serbest:<requirement_id>`,
tür `text`; önekisiz AC'ler `AC1: …` diye numaralanır). Golden adı `golden_name(...)`; serbest
metinde `golden_name(FREE_TEXT_KEY)` → `SERBEST` / `SERBEST-r2`. `fix_doc` önerisi
(`suggested_doc_text`) `ACn: ` önekli **tam AC satırıdır**; Jira'ya
`update_description(key, description, acs)` ile o AC'nin yerine yazılır (önek iki kez yazılmaz).

| Amaç | Golden | Hangi doküman |
|---|---|---|
| `requirement_review` | `TPD-1..4`, `SERBEST` | Özgün (jira-sim seed / girilen serbest metin). Düzeltmeden sonra yeniden ön inceleme yapılırsa REPLAY-MISS olur |
| `consistency_check` | `TPD-1..4`, `SERBEST` (1. tur) | Özgün |
| `consistency_check` | `TPD-1-r2`, `SERBEST-r2` (2.+ tur) | Aşağıdaki düzeltilmiş metin |
| `case_generation` | `TPD-1`, `SERBEST` | Düzeltilmiş metin; `TPD-3`, `TPD-4` özgün |
| `verify_and_map` | `TPD-1-C1..C10`, `TPD-4-C1..C2` | case_generation golden'ındaki case (insan düzeltirse REPLAY-MISS) |
| `triage`, `bug_draft`, `dup_rank` | senaryo adları | Beyan yok → her zaman REPLAY-MISS (Demo-A dışında; `promote` ile birebir kayda yükseltilebilir) |

## TPD-1: kararlar ve düzeltilmiş metin (golden'ların varsaydığı)

1. tur bulguları (`consistency_check/golden/TPD-1.json`) docs/DEMO-VERISI.md'deki 4 uyumsuzluktur;
kanıtlar forge'daki demo-app kaynağının **güncel** satırlarıdır (yol depo içinde `demo-app/` köküne
göre):

| Bulgu | Tür | Kanıt | Analist kararı (senaryo) |
|---|---|---|---|
| F1 | internal_contradiction (AC3 ↔ AC6) | `api/src/demoapp_api/pricing.py:94` `min_aranir = not any(s.kampanyali for s in satirlar)` | fix_doc |
| F2 | doc_vs_code (AC2) | `api/src/demoapp_api/campaign.py:23` `return adet // 6` | fix_doc |
| F3 | doc_vs_data (AC3) | `SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'` → `min_siparis_tutari=750.00` | fix_doc |
| F4 | missing_in_code (AC4) | `api/src/demoapp_api/pricing.py:97` (yalnızca minimum uyarısı) | code_defect → bug taslağı |

F1 ve F3 aynı AC3 metnini önerir; hangi sırayla kabul edilirse edilsin sonuç aynıdır. 2. turda
(`TPD-1-r2`) yalnızca F4 `warning` olarak kalır → engelleyici bulgu yok → "son hal" → PO teyidi.

**Düzeltilmiş TPD-1 kabul kriterleri** (jira-sim'e yazılan; `TPD-1-r2` ve `case_generation/TPD-1`
bunu varsayar):

```text
AC1: Bayi katalogda bir ürün için "Sepete ekle" butonuna bastığında ürün sepete eklenir ve sepet sayacı artar.
AC2: Kampanyalı üründe her 6 adette 1 adet bedava verilir: bayi 5 adet öder, 1 adet bedava alır (6 adette 1, 12 adette 2 bedava).
AC3: Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL'dir; altında "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur.
AC4: Sipariş tutarı bayinin kredi limitini aşarsa "Kredi limiti aşıldı" uyarısı gösterilir ve sipariş onaylanamaz.
AC5: Sipariş onaylandığında sipariş numarası gösterilir ve sipariş, sipariş geçmişinde listelenir.
AC6: Kampanyalı siparişlerde minimum sipariş tutarı şartı aranmaz.
```

**F2 önerisinin metni.** Önceki öneri (`"6 al 1 bedava" kampanyasında … her 6 adette 1 bedava`)
kendi içinde çelişiyordu: "6 al 1 bedava" olağan perakende kullanımında 6 öde + 7. bedava demektir;
öneri adı koruyup kuralı 5 öde + 1 bedava diye yeniden tanımlıyordu (AI gereksinimi koda uyduruyor
gibi). Yeni öneri kuralı **adsız ve açık** yazar (5 öde + 1 bedava; 6'da 1, 12'de 2). Bulgunun
`observed` metni iş etkisini (6 adette bayi dokümana göre 0, kodda 1 bedava = 25,00 TL; 42 adette 6
yerine 7) ve kampanya adının kuralla çeliştiğini söyler, kodun hatalı olabileceğini ve o durumda
kararın `code_defect` olması gerektiğini belirtir. Ekrandaki ad (demo-app `KAMPANYA_ADI`) kod/veri
değişikliğidir; `fix_doc` kapsamı dışındadır.

**Neden kampanya farkı `fix_doc` (doküman koda uyar) ve `code_defect` değil:** DEMO-VERISI ve
1. faz entegrasyonu bu kararı bağlar (2. turda engelleyici bulgu kalmaz; portal örnek verisi,
verify_and_map golden'ları ve CI golden-drift kopyası buna göre). Demo'da "AI case'i hikâyeyi
doğrular, kod tutmaz" anını iki yer üretir:
- **AC4 kredi limiti** (F4 → `code_defect`): case `Kredi limitini aşan siparişte uyarı …`
  `expected-code-defect` etiketlidir; verify_and_map'te `missing_methods`'a düşer (uydurma eşleme
  yok) ve bug taslağı `bug_draft/golden/credit-limit.json` ile açılır.
- **Kırarak doğrula** (adım 6): `BREAK_CAMPAIGN` ile bedava = 0; `6 adet … 1 adet bedava`,
  `7 adet … 1 adet bedava` case'leri kırmızıya döner (`test_campaign_scripts_catch_break_campaign`).

Analist F2 için `code_defect` seçerse doküman değişmez; 2. tur girdisi `TPD-1-r2` beyanına uymaz ve
dürüstçe REPLAY-MISS olur (canlı modelde gerçek cevap gelir).

### case_generation/TPD-1

10 case (6 AC; pozitif/negatif/sınır), her biri ≤ 8 adım (bugün en çok 5). Beklenen metinler kod üretiminin assert
edeceği literal değerleri taşır (`1 adet bedava`, `150,00 TL`, `"Minimum sipariş tutarı 750,00
TL"`, `Toplam 750,00 TL`); `test_goldens.py` her tutarı/adedi/uyarıyı demo-app fiyat fonksiyonlarıyla
yeniden hesaplar. Bugün geçenler: sepete ekle + sayaç, 7/6/5 adet kampanya, 750,00 TL minimum
(altı/eşit), kampanyalı sepette minimum aranmaz, sipariş onayı. Bugün kalan: AC4 (kod hatası).
**C10 bilerek C2'nin tekrarıdır** (aynı sepet ve beklenen, farklı başlık): QA incelemesinde
"reddet" gerçek bir karar olsun diye (gerekçe: C2 ile aynı). Reddi hiçbir AC'yi kapsamsız bırakmaz;
AC6'nın tek case'i C9'dur, reddedilirse AC6 kapsamsız kalır (portal/yayın önizlemesi AC kapsamını
göstermelidir). C1–C9 numaraları korunur (verify_and_map golden'ları, portal ve CI kopyası buna
bağlı); `TPD-1-C10` verify_and_map golden'ı C2'nin kaydından türetilmiştir.

**Yönerge kuralları** (`prompts/case-generation.md`, `test_goldens.py` her case golden'ında
denetler): her AC en az bir case ile kapsanır (kural/limit/hata mesajı içeren AC'de negatif/sınır
case'ler kapsamdır; ayrı pozitif zorunlu değil — TPD-1 AC3/AC4, SERBEST AC3 böyledir), case başına
≤ 8 adım, story başına ≤ 10 case (1–2 AC'li story'de 4'ten az olabilir).

## Serbest metin örneği (`SERBEST`)

Portaldan girilen demo gereksinimi (portal örnek verisindeki `req-ft-1` ile aynı metin):

```text
Başlık: Sepetten ürün çıkarma
Açıklama: Bayi sepetteki bir ürün satırını kaldırabilmeli; toplamlar ve kampanya indirimi yeniden hesaplanmalıdır.
AC: Satırdaki "Kaldır" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır.
AC: Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır.
AC: Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir.
```

1. tur: F1 doc_vs_code (AC2, `campaign.py:23`), F2 doc_vs_data (AC3, ayar 750.00), F3
missing_in_doc (AC3, kampanyalı sepette minimum aranmaz, `pricing.py:94`); hepsi `fix_doc`. Düzeltilmiş
metin: AC2 `Kaldırma sonrası kampanya indirimi her 6 adette 1 bedava kuralıyla yeniden hesaplanır.`,
AC3 `Sepette kampanyalı ürün yoksa ve sepet tutarı 750,00 TL altına düşerse "Minimum sipariş tutarı
750,00 TL" uyarısı gösterilir ve onay butonu pasif olur.` `SERBEST-r2` bulgu içermez;
`case_generation/SERBEST` 5 case (≤ 8 adım) bu metne göredir. C2 kampanyalı satırı (P-001 × 6)
kaldırır: bedava adet 1 → yok, indirim 25,00 TL → 0,00 TL, yani AC2'nin "yeniden hesaplanır"ı
gerçekten sınanır (kampanyasız satırı kaldırmak bedava adedi değiştirmezdi). `test_goldens.py`
her adımın beklentisini o adımdaki sepet durumuyla demo-app fiyat fonksiyonlarına karşı denetler.

Başka herhangi bir serbest metin `serbest:*` deseniyle bu golden'a düşer ve beyanına uymaz:
ön inceleme nötr REPLAY-MISS çıktısı verir (yukarıda), soru göstermez.

## Veri kanıtı özeti (`result_digest`)

`tp_core.gateway.result_digest(rows)`: her satırın değerleri SELECT sırasıyla `=` ile, satırlar
sıralanıp `; ` ile birleşir (`min_siparis_tutari=750.00`); `NULL`, `true/false`, Decimal ölçeği
korunur; 10 satırdan/200 karakterden büyük sonuç `sha256:<16 hex> (<n> satır)`. Doğrulayıcı
sorguyu salt okuma rolüyle yeniden çalıştırıp `digest_matches(claimed, rows)` ile karşılaştırır.
`db_query` aracının sonucu modelin kopyalayabilmesi için `result_digest: <özet>` satırını
içermelidir (prompt bunu ister). Golden'lardaki her veri kanıtı ve kayıtlı `db_query` adımı demo-app
seed'i üzerinde yeniden çalıştırılır (`test_goldens.py`; tablolar `db.RO_TABLES` + `bayi`).

## Sürüklenme (drift) ve güncelleme

- demo-app kodu kayarsa `test_goldens.py::test_golden_evidence_matches_demo_app_source` kırmızı olur
  (dosya:satır:alıntı birebir); golden'lar birlikte güncellenir. Aynı denetimin tp_core'suz kopyası
  `.github/golden-drift/`'te, portal kopyası `review-portal/src/api/mock/golden/kaynaklar.json`'da
  (`npm run sozlesme:golden` ile yeniden üretilir).
- jira-sim seed'i değişirse `test_tpd_input_match_follows_jira_sim_seed` kırmızı olur.
- Prompt/şema/model değişince bundle hash değişir; birebir kayıtlar bayatlar, beyanlı golden'lar
  etkilenmez (beyan girdiye bakar, prompt'a değil).
- Golden çıktıları elle hazırlanmıştır (`note`); canlı anahtar geldiğinde `TP_MODEL_MODE=record`
  ile yenilenmeli (kayıt üst verisi `recording` golden'a taşınarak) ve değerlendirme seti canlı
  koşturulmalıdır (constitution X). O zamana kadar her replay satırı `model = golden-elle`'dir.

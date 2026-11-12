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
3. **Aynı story'nin sonraki tur golden'ı**: 1. tur adı (`TPD-1`) uymazsa veya yoksa aynı önekli
   `-rN` golden'ları (`TPD-1-r2`) içerikle denenir; uyan ilk golden `replay` / `golden_matched`
   döner (`ek.replay_kaynagi` gerçekten kullanılan dosyadır). Böylece `make reset` olmadan ikinci
   koşuda jira-sim'deki düzeltilmiş TPD-1 metni 1. turda da REPLAY olur. Geriye bakılmaz: r2 adı
   uymazsa 1. tur golden'ı denenmez (düzeltilmemiş belgenin 2. turu dürüstçe REPLAY-MISS), case
   düzeyi adlar (`TPD-1-C2`) bu aramaya girmez.
3b. **Senaryo golden'ı** `<amaç>/golden/<senaryo>/<ad>.json` (ör. `f2-kod-hatasi/`): analistin
   başka bir kararla vardığı belge için aynı adlı golden. Ana golden ve tur golden'ları uymazsa
   senaryo dizinleri ada göre sıralı denenir (1. tur story adında senaryonun `-rN` dosyaları da);
   yalnızca `input_match` taşıyan ve girdiye **uyan** senaryo golden'ı `replay` / `golden_matched`
   döner (`ek.replay_kaynagi` = `…/golden/<senaryo>/<ad>.json`, kayıttaki `golden` =
   `<senaryo>/<ad>`). Beyansız ya da uymayan senaryo golden'ı hiçbir zaman döndürülmez; iskalama
   ana adın politikasıyla olur. Ana golden'lar, CI kopyası (`.github/golden-drift`) ve portal
   kopyası (`golden/*.json`) bu dizinleri görmez; senaryolar çekirdek testlerinde denetlenir.
4. **İskalama** (mod **`replay_miss`**, nedenler `ai_call.ek.replay_eslesme`'de, ör.
   `["AC2 metni farklı"]` veya golden dosyası hiç yoksa `["bu anahtar için golden yok"]`).
   `TP_REPLAY_STRICT=1` (prova) her iskalamayı `ReplayMiss` hatasına çevirir. Golden girdi beyanı
   (`input_match`) taşıyorsa **veya golden hiç yoksa** (ör. demo sırasında jira-sim'de açılan
   TPD-24) amacın `<amaç>/on_miss.json` politikası uygulanır:
   - **nötr yedek** (`output` alanı; `requirement_review`, `consistency_check`, `triage` →
     sınıf `unknown`, `decision_table_draft` → boş taslak): golden çıktısı
     **kullanılmaz** (başka bir dokümanın cevabıdır); nötr yedeğin çıktısı döner, köken
     `miss_neutral`, `cikti_kokeni = notr_yedek`. Yeni Jira story'si de serbest metin gibi bu
     yoldan ilerler (gereksinim akışı: denetim güvenilmez, "Son hal olarak onayla").
   - **`"policy": "raise"`** (`case_generation`, `verify_and_map`, `verify_and_map_app`,
     `bug_draft`, `dup_rank`):
     çıktı yoktur; geçit `ReplayNoOutput` fırlatır
     ("REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok; canlı model gerekir"), sıfır taslak.
   - Beyansız golden veya `on_miss.json`'u olmayan amaç: golden varsa çıktısı döner, köken
     `golden` (Faz 4'ten beri depoda beyansız golden yoktur).
5. Golden de iskalama politikası da yoksa `ReplayNotFound`.

Bulunamayan/çıktısız her iskalama da `ai_call`'a yazılır (mod `replay_miss`, `cikti = NULL`,
`hata = "ReplayNoOutput: …"` / `"ReplayMiss: …"` / `"ReplayNotFound: …"`, `ek.replay_kokeni =
yok`; constitution VIII). `promote` bu çıktısız satırları atlar.

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

### REPLAY-MISS'te case üretimi (`case_generation/on_miss.json`, `"policy": "raise"`)

Case şeması en az bir case ister, nötr çıktı yoktur. Önceden eşleşmeyen golden'ın case'leri
`replay_miss` taslağı olarak dönüyordu: "Fatura indirme" serbest metni "Kaldır ile ürün satırı
sepetten çıkar…" case'lerini alıyordu; AC1/AC2/AC3 atıfları gereksinimde 3 AC olduğu için AC
denetiminden de geçiyor, QA onayından Jira/Xray'e yayınlanabiliyordu. Analist SERBEST AC2'yi
"7 adette" bırakırsa (code_defect) 6-adet kuralını doğrulayan case'ler gelip tutulan belgeyle
çelişiyordu. Artık geçit başka dokümanın case'lerini **hiç döndürmez**: `ReplayNoOutput`
(`ReplayNotFound` alt sınıfı), sıfır taslak; case'ler elle girilebilir veya IDE kanalı
kullanılabilir. Gereksinim akışı bu hatayı "Bu girdi için kayıtlı REPLAY çıktısı yok…" olarak
gösterir (iş kalıcı hatadır; yeniden denemek sonucu değiştirmez).

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
| `requirement_review` | `TPD-1..4`, `SERBEST` | Özgün (jira-sim seed / girilen serbest metin). Düzeltmeden sonra yeniden ön inceleme yapılırsa nötr REPLAY-MISS olur (`make reset` önerilir) |
| `consistency_check` | `TPD-1..4`, `SERBEST` (1. tur) | Özgün; düzeltilmiş metinle 1. tur `-r2`'ye düşer (arama sırası 3) |
| `consistency_check` | `TPD-1-r2`, `SERBEST-r2` (2.+ tur) | Aşağıdaki düzeltilmiş metin |
| `case_generation` | `TPD-1`, `SERBEST` | Düzeltilmiş metin; `TPD-3`, `TPD-4` özgün |
| `verify_and_map` | `TPD-1-C1..C10`, `TPD-4-C1..C2` | case_generation golden'ındaki case (insan düzeltirse REPLAY-MISS) |
| `verify_and_map_app` | `TPD-1-C2-android` | 009 mobil: aynı C2 case'i; platform golden adındadır (`<story>-C<n>-<platform>`), başka platform REPLAY-MISS. Araç adımları app-mcp sözleşmesine uyan sahte oturumda yazıldı (`core/tests/unit/gateway/build_app_goldens.py`), gerçek cihazda kaydedilmedi |
| `decision_table_draft` | `TPD-1` | 012 karar tablosu: demo ana yolunun (`f2-kod-hatasi`) PO onaylı metni — AC2 özgün (7 adette 1 bedava → `adet // 7`; kod `// 6` uygular, tablo story'yi izler), AC3 düzeltilmiş (kampanyasız 750,00 TL), AC6. Başka metin (fix_doc yolu dahil) nötr REPLAY-MISS: boş taslak (`on_miss.json`) |
| `case_facts` | `TPD-1-C2…C6`, `TPD-1-C9`, `TPD-1-C10`, `f2-kod-hatasi/TPD-1-C3`, `rehber-duzeltme/TPD-1-C5`, `ai-sinir-hatasi/TPD-1-C6` | 012 değer çıkarma: case_generation golden'ındaki case metni (`input_match.case_text`); demo ana yolunun C3'ü senaryo golden'ından. İki kapı varyantı: rehber §8.6'daki düzeltilmiş C5 ve AI'ın sınır hatası C6 (750,00 TL'de uyarı) — ikisi de `uyumsuz`. Düzeltilmiş/önerilen içerik ve golden'ı olmayan case (C1, C7, C8 zaten modele gitmez; metamorfik türetilen case'ler) nötr REPLAY-MISS: `groups: []` → `kontrol_edilemedi` (`on_miss.json`). Ayrıntı aşağıda "012 değer çıkarma" |
| `consistency_check` | `f2-kod-hatasi/TPD-1-r2` | F2 `code_defect` yolu: AC2 özgün, AC3 düzeltilmiş (aşağıda "Demo-B") |
| `case_generation` | `f2-kod-hatasi/TPD-1` | Aynı belge; ana golden'dan tek farkı C3 (6 adette bedava yok) |
| `verify_and_map` | `f2-kod-hatasi/TPD-1-C3` | Senaryonun C3'ü; diğer case'ler ana golden'larla birebir aynı, ana golden eşleşir |
| `triage`, `bug_draft`, `dup_rank` | `HATA` + senaryo dizinleri | Faz 4 (aşağıda "Faz 4"): kanonik hata/bulgu bloğuna göre beyanlı |

## 012 değer çıkarma (`case_facts`)

Karar tablosu kontrolü (specs/012-test-kalite-dogrulama/ANALIZ.md §4.3, §12) için model case'ten
tablo kolonlarına karşılık gelen değerleri **alıntısıyla** çıkarır; model tablonun yalnız kolon
tanımlarını görür (satır, koşul, ifade görmez). Golden adı case düzeyidir
(`golden_name(story, case_no=n)` → `TPD-1-C3`); eşleşme case içeriğinin kanonik metnine göredir.

- Golden'lar elle hazırlanmıştır (`ai_call.model = golden-elle`) ve
  `core/tests/unit/features/oracle/tpd1.py`'den üretilir:
  `cd core && uv run python -m tests.unit.features.oracle.tpd1` (elle düzenlemeyin;
  `test_cikarma_golden.py` depodakiyle aynı olduğunu denetler).
- Kolon adları Ş1'in `decision_table_draft/golden/TPD-1.json` tablolarınındır (T1: `adet`,
  `ara_toplam` → `bedava_adet`, `indirim`, `toplam` (V9); T2: `kampanyali_sepet`,
  `sepet_tutari` → `minimum_uyarisi`). Model yalnız tablo ref'ini ve kolonların ad/tür/birimini
  görür (tablo adı ve açıklamalar gitmez).
- Bir değer case'te birden çok yerde geçiyorsa (başlık, adım eylemi/verisi/beklenen, sonuç) her
  geçiş ayrı olgudur: metamorfik türetme değişen alıntının bütün kopyalarını ister. Beklenen
  alanlardaki kolonsuz sayılar (sepet sayacı, "7. adette") `ignored[]`'dadır; ikisinde de
  olmayan sayı tamlık denetiminde kapsanmamış sayılır (`kismen`).
- Alıntılar birebirdir; ürün her olguyu deterministik doğrular, tutmayanı atar.
- Değerlendirme seti `rules/evaluation/case-facts.json` (C2, ana yol C3, C5 ve iki tuzaklı varyant) aynı modülden
  `build_eval_sets.py` ile üretilir.

## Prova kipi (`TP_REPLAY_STRICT=1`): ana yol tam

§13 prova listesindeki "REPLAY-MISS olmadan replay" maddesi sunumun ANA yolu (`f2-kod-hatasi`,
docs/DEMO-VERISI.md) için `core/tests/unit/gateway/test_rehearsal_strict.py` ile doğrulanır: geçit
ortamdan kurulur (`build_gateway`, `TP_MODEL_MODE=replay`, `TP_REPLAY_STRICT=1`), girdiler
üretimin kurucularıdır (`Snapshot.message()` + `replay_key_for`, `generation_messages` PO cevabı ve
test verisi blokları dahil, `mapping_messages`, `gateway.defects`). Sıra: ön inceleme → 1. tur →
F1/F3 Jira'da düzeltilir (F2/F4 `code_defect`) → 2. tur → 10 case → her case için doğrulama ajanı →
F2 taslak + TPD-5 bağla → F4 taslak (aday yok, sıralama yok) → C3 taslak + TPD-5 bağla → kırma
taslağı + yeni kayıt. Her çağrı `replay` / `golden_matched` döner; test kullanılan golden kümesini
de sabitler (eksik veya fazla golden kırmızıdır):

| Amaç | Golden |
|---|---|
| requirement_review | `TPD-1` |
| consistency_check | `TPD-1`, `f2-kod-hatasi/TPD-1-r2` |
| case_generation | `f2-kod-hatasi/TPD-1` |
| verify_and_map | `TPD-1-C1`…`C10` (C3 hariç), `f2-kod-hatasi/TPD-1-C3` |
| bug_draft | `f2-kampanya/HATA`, `f4-kredi-limiti/HATA`, `HATA` (C3), `kirma-kampanya/HATA` |
| dup_rank | `f2-kampanya/HATA`, `HATA` (C3), `kirma-kampanya/HATA` |

Triage ana yolda modele gitmez (C3, kırma, locator ve ortam kurallarla sınıflanır); `triage/HATA`
yalnızca kuralsız zaman aşımı içindir (`test_defect_goldens.py`). TPD-2/3/4 ön inceleme +
tutarlılık (+ TPD-3/4 case üretimi) da prova kipinde REPLAY'dir. Eksik golden bulunmadı (2026-11-01).

Bilinen sınır (prova yolu dışında): `make reset` olmadan Demo-A ikinci kez başlatılırsa jira-sim'deki
TPD-1 metni düzeltilmiş hâldedir; tutarlılık turları tur/senaryo golden'larıyla REPLAY olur, ama ön
incelemenin düzeltilmiş metin için golden'ı yoktur → gevşek kipte dürüst REPLAY-MISS (nötr), sıkı
kipte `ReplayMiss`. Prova her zaman temiz `make reset` ile başlar (§13).

Her satırın etiketi dürüsttür: mod `replay` (asla `live`), `ai_call.model = golden-elle`,
`ek.degerlendirme.etiket = "canlı değerlendirme bekliyor"`.

## TPD-1: kararlar ve düzeltilmiş metin (golden'ların varsaydığı)

1. tur bulguları (`consistency_check/golden/TPD-1.json`) docs/DEMO-VERISI.md'deki 4 uyumsuzluktur;
şiddetler yönergenin risk tabanlı kuralına uyar (`prompts/consistency-check.md` v4: kod eksiği
para, kredi/limit veya sipariş onayını koruyorsa `blocking`, henüz yapılmamış basit özellikse
`warning` — TPD-2/TPD-3 böyledir);
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
**Bilinen fark:** risk kuralına uyan canlı model 2. turda kredi limiti bulgusunu yine `blocking`
diyebilir (girdide önceki karar yok). Bulgu 1. turdakiyle aynı tür, aynı AC4 metni ve aynı kanıttır
(`pricing.py:97`); gereksinim akışı önceki `code_defect` kararını devralır ve yeni karar istemez —
sonuç aynı (son hal), yalnızca şiddet etiketi farklı olur.

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

**Tarihçe — ana golden'lar neden `fix_doc` yolunda:** (Faz 3 kararıyla demo'nun ana yolu
`f2-kod-hatasi` senaryosudur; bkz. docs/DEMO-VERISI.md. Ana golden'lar alternatif yol olarak kalır.) DEMO-VERISI ve
1. faz entegrasyonu bu kararı bağlar (2. turda engelleyici bulgu kalmaz; portal örnek verisi,
verify_and_map golden'ları ve CI golden-drift kopyası buna göre). Demo'da "AI case'i hikâyeyi
doğrular, kod tutmaz" anını iki yer üretir:
- **AC4 kredi limiti** (F4 → `code_defect`): case `Kredi limitini aşan siparişte uyarı …`
  `expected-code-defect` etiketlidir; verify_and_map'te `missing_methods`'a düşer (uydurma eşleme
  yok) ve bug taslağı `bug_draft/golden/credit-limit.json` ile açılır.
- **Kırarak doğrula** (adım 6): `BREAK_CAMPAIGN` ile bedava = 0; `6 adet … 1 adet bedava`,
  `7 adet … 1 adet bedava` case'leri kırmızıya döner (`test_campaign_scripts_catch_break_campaign`).

Analist F2 için `code_defect` seçerse doküman değişmez (AC2 özgün kalır); 2. tur girdisi `TPD-1-r2`
beyanına uymaz, `f2-kod-hatasi/TPD-1-r2` senaryo golden'ına uyar (REPLAY). Bu yol Demo-B'nin
"defect adayı" anını üretir (aşağıda). F1/F3'ten biri de reddedilirse belge iki golden'a da uymaz ve
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

## Kod üretimi (Demo-B): verify_and_map golden'ları

### REPLAY'de ajan nasıl oynatılır (tüm yörünge, tur başına değil)

Bir verify_and_map golden'ı **tek bir ajan koşusunun tamamıdır**: `steps` (araç çağrıları, sırasıyla)
ve son yapılandırılmış çıktı (`output`: `step_mapping`, `expects`, `missing_methods`). Model turları
ayrı ayrı kaydedilmez (canlıda modelin her turu bir `ai_call`; REPLAY'de model yoktur). Geçit
`run_agent` REPLAY'de:

1. golden'ı bulur (arama sırası yukarıda; ad `golden_name(<KEY>, case_no=n)`), çıktıyı şemayla
   doğrular ve **tek** `ai_call` satırı yazar (`mod = replay`, `model = golden-elle`);
2. kayıtlı her adımı **aynı sırayla** çağıranın `execute`'una verir
   (`replay_executes_tools=True`, varsayılan): Playwright MCP'de gerçekten yürütülür
   (anayasa V — ajan uygulamayı gerçekten görür), her adım bir `tool_call` satırı ve bir
   `on_step(AgentStep)` olayıdır (portal adım akışı / kod üretimi şeridi bunu gösterir). Adımın
   `result_summary`'si canlı yürütmenin sonucudur; golden'daki özet kayıt anında görüleni gösterir.
   İzin listesi REPLAY'de de geçerlidir (listede olmayan kayıtlı araç yürütülmez).
   **Snapshot ref'leri deterministik değildir:** ref'ler (`[ref=e21]`) Playwright MCP oturumuna
   özgüdür ve aynı yörüngede bile koşudan koşuya kayar (`browser_navigate` SPA henüz çizilirken
   örtük snapshot alır ve bazen fazladan bir ref harcar; sayfa +1 kayar — canlı yığında aynı giriş
   sayfası için `button "Giriş yap" [ref=e20]` ve `[ref=e21]` gözlendi). Bu yüzden ref alan her
   kayıtlı adım (`browser_generate_locator`) yapılandırılmış bir **`hedef`** taşır
   (`{"rol", "ad", "kapsam"?}`; ör. `{"rol": "button", "ad": "Sepete ekle", "kapsam":
   "paragraph: P-002"}`) ve geçit ref'i **bu oturumun son snapshot'ından** rol/ad/kapsamla yeniden
   çözer (`tp_core.gateway.snapshot_refs`); çağrı canlı ref'le yapılır, adım/denetim de onu taşır.
   Eleman canlı snapshot'ta bulunamazsa adım **çalıştırılmaz** ve `Araç hatası (ReplayHedefYok)`
   olarak akar (kod üretimi REPLAY'de başarısız adımı insana düşürür). Canlı `generate_locator`
   sonucu kayıttakinden farklıysa adım özeti `REPLAY sapması: kayıtta …, bu oturumda …` ile başlar.
   Eylem sonuçlarındaki MCP sunucu dosyası bağlantıları (`- [Snapshot](…yml)`,
   `New console entries: …log`) modele ve denetime gitmez;
3. golden çıktısını döndürür. Araç dizisi kayıttaki gibidir; ref'ler ve canlı sonuç özetleri bu
   oturumun sayfasından gelir.

**Yığın kontrolü:** `python -m tp_core.gateway.replay_check --runs 5` (core-worker içinde, yığın
ayakta) her verify_and_map golden'ını üretimdeki `AgentBrowser`/`McpBrowserSession` ve geçidin
REPLAY yoluyla N kez oynatır; her izinli adımın başarılı olduğunu ve her `generate_locator`
sonucunun kayıttaki locator'la aynı olduğunu doğrular (çıkış kodu 0/1).

**Önkoşul (kod üretimi şeridi):** ajan tarayıcısı **doğrulama bayisiyle** (`bayi3`, "Doğrulama
Bayi"; `tp_core.gateway.VERIFY_AGENT_DEALER`, demo-app seed'i ve `e2e/tests/fixtures.ts`
`AGENT_DEALER`) girer; e2e bayileri (bayi1/bayi2) ajan tarafından kullanılmaz. Kayıtlı yörüngeler
boş sepet varsayar ("Sepet 0 ürün" snapshot'ta görülür): kod üretimi **her case'ten önce** bayi3'ü
`POST /test/reset {kullanici_adi: "bayi3"}` ile sıfırlamalıdır (core-worker demo-app-api'ye
erişemez; test-runner/toolchain üzerinden). Bekleme metni durumdan bağımsızdır ("7 adet sepete
eklendi."), sepet dolu olsa da yörünge takılmaz ama snapshot özeti farklı sayıları gösterir.

### Girdi ve anahtar kararlılığı

Kod üretimi girdisini şu yardımcılarla kurmalıdır (`tp_core.gateway`):

- `approved_case_block(case, jira_key=…, sira_no=…)` — onaylı case, kaynak `case:<KEY>-C<n>`;
  golden'ların `input_match.contains` beyanı (başlık, adım eylemleri, beklenenler) bu metinde birebir
  geçer (`test_canonical_case_block_satisfies_the_golden_declaration`). Case insan düzeltmesiyle
  değişirse dürüst REPLAY-MISS.
- `symbol_table_block(table)` — `POST /symbols` çıktısı; checkout kökü (`root`), `line` ve boş
  `errors` atılır, sınıf/locator sıralanır: aynı page object kaynağı aynı birebir anahtarı verir.
- `verification_context_block()` — uygulama kökü + doğrulama bayisi (parola case verisinden
  yazılır; hatalı parola case'i böyle yeniden üretilir). Kod üretimi şeridinin araç katmanı
  giriş alanına yazılan e2e bayi adını bayi3'e çevirir; golden yörüngeleri doğrudan `bayi3`
  yazar, çeviri onları değiştirmez (iki yol aynı tarayıcı oturumunu verir).
- Case'i JSON olarak (`json.dumps(case)`) bloğa koymak da eşleşir (`input_match` JSON görünümünü
  okur); sembol tablosu kaynağındaki kısa sha (`symbols:<sha12>`) anahtar normunda `<SHA>` olur.
- Diğer oynak değerler (zaman damgası, UUID, sha, snapshot `ref=eN`) `normalize_text` ile zaten
  anahtar dışıdır.

### Yönerge (`prompts/verify-and-map.md` v3 — canlı değerlendirme bekliyor, bkz. rules/README.md)

Tarayıcıda doğrulama bayisi; hedefler page object locator'larının `data-testid` seçicileri (kapsamlı
locator'da `within` + ürün kodu); eylemde kullanılan **her** locator'a ilk kez dayanmadan önce
`browser_generate_locator` (golden yörüngeleri de böyledir: kullanıcı adı, parola, giriş butonu,
ürün kartındaki adet alanı ve sepete ekle, sepet bağlantısı, minimum uyarısı, onay butonu,
Siparişlerim bağlantısı);
her sayfa değişiminden sonra snapshot; eşleme argümanları case'in `action`/`data`'sından; `expects`
son adımdan sonra koşar ve argümanları case'in beklenen metninde **literal** geçer (normalize:
`1.250,00 TL` ≡ `1250`; aritmetik yok, sayfadan kopya yok). Sayfa case'ten farklı değer gösterirse
beklenti **değişmez**: adım `verified` kalır, `evidence_ref` "gözlenen: … · beklenen: …" notunu
taşır; yerel kontrol o assertion'da kırmızı olur ve case insana **defect adayı** olarak gider
(otomatik onarım yok, §8.4 adım 5). Golden'larda bu not **"kayıttaki not — gözlenen: …"** diye
etiketlidir: değerler kayıt anındaki sayfadandır ve REPLAY koşusunda yeniden ölçülmez (portal bunu
ajan kanıtı olarak gösterir; etiket bunun kayıt olduğunu söyler). Defect adayı kararı
(`demo_check`) serbest metinden değil golden'ın yapılandırılmış **`defect_adayi`** alanından
(`{"step_id", "beklenen", "kayittaki_gozlem"}`) okunur; alan eşlemedeki bir adımı göstermelidir. Expect metodu olmayan beklenti → `missing_methods` (uydurma yok).

### Demo-B hikâyesi ve iki yol

| Yol | Analist kararı (F2) | Kod üretimi sonucu |
|---|---|---|
| Alternatif | `fix_doc` (AC2 koda uyar: 6'da 1) | Kampanya case'leri (C2 7→1, C3 6→1, C4 5→0) bugün yeşil, BREAK_CAMPAIGN'da C2/C3 kırmızı (kırarak doğrula ✓). Assertion'da kırmızı case yok; tek kod hatası AC4 (C7) `missing_methods`'ta durur |
| **Ana demo yolu** `f2-kod-hatasi` | `code_defect` (AC2 özgün: 7'de 1) | C2 "7 adet → 1 bedava" bugün yeşil, BREAK_CAMPAIGN'da kırmızı; **C3 "6 adet → bedava yok"** eşlenir ve kod üretilir, yerel kontrolde `expectFreeQuantity("P-001", 0)` kırmızı (kod 1 verir: `adet // 6`) → **defect adayı** (Faz 4 triage → bug taslağı); C5 "Minimum sipariş tutarı 750,00 TL", C1 sepet sayacı, C8 sipariş onayı yeşil |

`test_codegen_goldens.py` her iki yolu demo-app'in saf fiyat fonksiyonlarıyla (yerel kontrolün
sonucunu öngörerek) ve geçidin gerçek kod yoluyla (jira-sim → F1/F3 fix_doc → 2. tur → case üretimi
→ her case için `run_agent`, sıkı kip) denetler.

### Kayıt (gerçek Playwright MCP)

`steps` gerçek Playwright MCP'de (compose imajı 1.64.1, bayraklar: `--isolated`, `--caps=testing`,
vision yok) compose yığınındaki demo-app'e (demo-app-web/demo-app-api) karşı core-worker içinden
koşturulup kaydedildi (2026-10-31). Kayıt aracı: `core/tests/unit/gateway/record_verify_goldens.py`
(kullanım dosya başında; her case'ten önce bayi3'ün sepeti boşaltılır). Kayıt **bayt bayt
tekrarlanabilir değildir**: snapshot ref'leri koşudan koşuya kayabilir, compose yığınında sipariş
numarası (C8: `SP-000056`) ve bayi3'ün sipariş geçmişi yığının durumuna bağlıdır. Ref'ler yalnızca o
kaydın gözlemidir; REPLAY `hedef`'ten çözer. Araç `output`'u **elle
hazırlanmış eşleme olarak korur** (yeni senaryo case'i için önce elle yazılır); yalnızca adımları ve
`evidence_ref`'teki gözlemleri günceller. demo-app UI'ı veya page object'ler değişince yeniden
koşturulur.

### Sürüklenme denetimi (`test_codegen_goldens.py`)

- Her eşlenen `po.method` güncel `pages/**/*.page.ts`'te doğru arity/türle var; regex ayrıştırıcı
  toolchain'in gerçek sembol çıkarıcısıyla (`toolchain/symbols/dist`, node varsa) aynı tabloyu verir.
- Her `expects` argümanı, golden'ın `case.case_golden`'ındaki (yoksa `<KEY>`) onaylı case metninde
  normalize edilerek geçer; `login` eşlemesi case verisidir.
- Tarayıcı adımları: izin listesi, ≤ 25, yalnızca demo kökü, hedef/generate_locator testId'leri
  locators.ts'te var, tarayıcıya yazılan kullanıcı yalnızca bayi3, sayfa değişiminden sonra snapshot.
- Eylemde (click/type) kullanılan her testId ilk kullanımından önce bir `generate_locator`
  sonucunda görülmüştür (prompt v3); ref alan her adım `hedef` taşır ve hedef kayıttaki snapshot'ta
  tam o ref'e çözülür.
- Gözlenen ≠ beklenen olduğunda (ve yalnızca o zaman) sepet adımının `evidence_ref`'i "beklenen:"
  taşır ve golden `defect_adayi` beyanı içerir; değerler "kayıttaki not" etiketlidir.

## Faz 4: triage → bug taslağı → mükerrer sıralaması

### Girdi sözleşmesi (triage ve bug şeritleri)

Golden beyanları ve birebir anahtar ancak girdi tek biçimde kurulursa tutar. Şeritler model
mesajlarını YALNIZCA `tp_core.gateway.defects` kurucularıyla kurar (testlerdeki örnek:
`core/tests/unit/gateway/defect_inputs.py`):

| Amaç | Mesajlar | Bloklar |
|---|---|---|
| `triage` (yalnızca kural eşleşmezse) | `triage_messages(failure_block(f, …, rule_signals=…, include_aria=True))` | `failure:<case_ref\|e2e>` |
| `bug_draft` | `bug_draft_messages(sources, testdata=cases.testdata.block(), story_key, test_case_key)` | hata: `failure_block` + varsa `case_block(case, "TPD-1-C3")`; bulgu: `finding_block(...)`; `testdata:demo-app` |
| `dup_rank` | `dup_rank_messages(sources, draft=<taslak içeriği>, candidates=<JiraPort.search sonucu>, jql=…)` | aynı `sources` + `taslak:` + `jira-arama:Bug` |

- `failure_block(failure, test_title=…, test_file=…, story_key=…, case_ref=…, saglik=…,
  statuses=…, consistent=…, break_campaign=…)`: `failure` toolchain `/check` / test-runner
  `failure_groups[].failure` nesnesidir (toolchain/README.md "Failure inputs"); `statuses` /
  `consistent` grubun alanları, `saglik` koşunun sağlık bloğu, `break_campaign`
  `run.ortam.break_campaign` / kırma koşusu.
- `finding_block(story_key, finding_type, doc_ref, doc_text, claim, observed, evidence)`: bulgu
  (`consistency_finding` + `_ek.iddia/gozlem/mevcut_doc_text`), kanıtlar bulgunun `kanitlar`'ı.
- `replay_key=defect_replay_key(story_key)` → `{"name": "HATA", "jira_key": …}`; çağrı kimliği
  `deterministic_call_id(job_id, "<amaç>")`.
- Anahtar dışı tutulanlar: koşu kimliği, artefakt yolları (kanıtlar yalnızca `kanit:trace`,
  `kanit:error_context`, `kanit:screenshot` … adıyla anılır), üretilen dosyanın uuid8 soneki,
  başlıktaki `@etiket`ler ve describe yolu, tam Playwright mesajı (çağrı günlüğündeki tekrar sayısı
  koşuya göre değişir), aday kayıtların `updated` zamanı, bulgu etiketi (`F2 (tur 1)`), depo adı ve
  denetim commit'i. `test_defect_inputs.py` iki farklı koşunun aynı anahtarı verdiğini sınar.
- **Çıktıdan sonra (şerit):** `resolve_evidence(output, links={"trace": url, …},
  literal_refs=literal_evidence_refs(bulgu_kanitlari))` `kanit:<ad>`'ı gerçek bağlantıya çevirir,
  bağlantısızları ve girdide olmayan referansları (uydurma URL/yol) atar. `story_key` ve
  `test_case_key` şeridin kendi verisinden yazılır (golden'da `test_case_key = null`; Jira Test
  anahtarı yayında oluşur). `dup_rank_problems(output, candidates)` boş değilse sıralama
  gösterilmez (canlı modelde de): aramada olmayan anahtar (`invented_dup_keys`), aynı adayın iki
  kez ya da aramadaki adayın hiç sıralanmaması, 1..n olmayan sıra, 200 karakteri aşan gerekçe,
  `high` olmayan adaya `link`. Şema da gerekçeyi `maxLength: 200` ile sınırlar.
- Adaylar: açık Bug'lar (`statusCategory != Done`; TPD-7 kapalıdır, aday olmaz). Aday yoksa
  `dup_rank` çağrılmaz (`dup_rank_messages` en az bir aday ister).

### Golden'lar (ad `HATA`; içerikle seçilir)

| Amaç | Golden | Beyan (özet) | Çıktı |
|---|---|---|---|
| `triage` | `HATA` | `Hata türü: test_timeout`, sipariş testi, sağlık başarılı | `unknown` (kuralsız zaman aşımı; insana) |
| `bug_draft` | `HATA` (ana yol) | C3: `cart-line-free-P-001` beklenen "0" gerçekleşen "1", kırılma kapalı, case başlığı | "Sepet: 6 adet Portakal Gazozu sepete eklendiğinde bedava adet 0 beklenirken 1 görünüyor" |
| `bug_draft` | `kirma-kampanya/HATA` | beklenen "1" gerçekleşen "0", kırılma açık, "7 adet", test verisi | 7 adette bedava 0; ortam "kasıtlı demo kırılması" |
| `bug_draft` | `f2-kampanya/HATA` | bulgu `doc_vs_code` AC2, `campaign.py:23` | 6 adette bedava 1 (TPD-5 ile aynı hata) |
| `bug_draft` | `f4-kredi-limiti/HATA` | bulgu `missing_in_code` AC4, `pricing.py:97`, bayi2 500,00 TL, P-004 | bayi2 + 25 × P-004 = 750,00 TL: minimumu geçer, limiti aşar |
| `dup_rank` | `HATA` (ana yol) | C3 imzası + aday kümesi (aşağıda) | TPD-5 `high` → `link` TPD-5; TPD-6 `low` |
| `dup_rank` | `f2-kampanya/HATA` | F2 bulgusu + aday kümesi | TPD-5 `high` → `link` |
| `dup_rank` | `f4-kredi-limiti/HATA` | F4 bulgusu (`missing_in_code` AC4, `pricing.py:97`) + aday kümesi | TPD-5 ve TPD-6 `low` → `new`; aramada önceki F4 Bug'ı varsa o `high` → `link` |
| `dup_rank` | `kirma-kampanya/HATA` | kırma imzası + aday kümesi | TPD-5 `medium` (ters belirti) → `new`; aramada önceki kırma Bug'ı varsa o `high` → `link` |

**Aday kümesi beyanı (`input_match.candidates`).** Mükerrer araması genel terimlerle (ör.
`adette`, `kampanyalı`) yapılır; demo sırasında "Yeni kayıt" ile açılan her Bug sonraki aramalara
girer (canlı yığında F4 → TPD-8 açıldıktan sonra C3/F2 araması `[TPD-5, TPD-8]` döndü). Bu yüzden
golden sabit bir `Aday anahtarları: [...]` satırına değil kümeye bağlıdır: `required: [TPD-5]`
(F4'te boş), `optional: [TPD-6]`, `by_summary`: özeti golden taslaklarından bilinen ve demo
sırasında açılabilen Bug'lar (`6 adet … 0 beklenirken 1`, `7 adet … 1 beklenirken 0`,
`Kredi limiti aşıldığında`). Bunların olasılık/gerekçesi golden'ın `extra_candidates` alanındadır.
Geçit çıktıyı girdideki GERÇEK kümeye göre kurar (`matching.matched_output`): yalnızca aramadaki
anahtarlar, her biri bir kez, sıra 1..n (önce olasılık, sonra golden sırası), öneri prompt kuralıyla
(ilk `high` aday → `link`, yoksa `new`). Beyan dışı aday (özeti tanınmayan Bug, ör. testçinin
özeti değiştirdiği kayıt) dürüstçe REPLAY-MISS'tir: golden bilmediği kaydı sıralamaz.

Sahne sırası: F4 "Yeni kayıt", C3 ve kırma taslaklarından önce de verilebilir; C3/F2 sıralaması
yine TPD-5 `high` + bağla, F4 Bug'ı `low` olur. Kırma "Yeni kayıt" sonrası ikinci bir kırma koşusu
önceki kırma Bug'ını aynı belirti olarak (`high` → bağla) önerir. Testçi Jira'da özeti
değiştirirse o kayıt beyan dışı kalır ve sıralama REPLAY-MISS olur (adaylar sırasız; karar yine
testçinin).

Senaryo yolundaki triage kararları kuraldır (C3/kırma assertion → `product_defect`,
`add-to-cart` → `cart-add` → `test_maintenance/locator`, sağlık hatası → `environment`); modele
gitmez, golden'ı yoktur. İskalama: `triage/on_miss.json` nötr `unknown`; `bug_draft` ve `dup_rank`
`"policy": "raise"` → `ReplayNoOutput` (şerit şablon taslağa / sıralamasız aday listesine düşer).

**Sürüklenme denetimi:** `test_defect_goldens.py` (her senaryo girdisi tam olarak kendi golden'ına
düşer, başka hata REPLAY-MISS olur, şema, yönerge kuralları; mükerrer sıralaması yayımlanmış Bug'larla
genişleyen kümelerde de yalnızca aramadaki anahtarları sıralar),
`test_bug_draft_goldens.py` (adımlar demo-app fiyat fonksiyonlarıyla hatayı gerçekten gösterir:
6 adette kodda 1 bedava, kırmada 7 adette 0, bayi2 limiti 750,00 TL ile aşılır ve başka kural
onayı engellemez), `test_jira_seed_goldens.py` (adaylar jira-sim aramasından, TPD-5 C3'ün
değerleriyle aynı hatayı anlatır; F4 ve kırma Bug'ları jira-sim'de açıldıktan sonra üretimin JQL
araması ile C3/F2 TPD-5'i yine `high` + bağla alır).

**Değerlendirme setleri (constitution X):** `rules/evaluation/{triage,bug-draft,dup-rank}.json`
kanonik kurucularla üretilir (`core/tests/unit/gateway/build_eval_sets.py`; `test_eval_sets`
bayatlığı yakalar). Canlı anahtar sahibi `cd core && uv run python -m tp_core.gateway.eval_set
--bundle <paket> --update-status` ile koşturur; tüm vakalar geçerse `rules/evaluations.yaml`
kaydı `evaluated` olur ve rapor `rules/evaluation/results/` altına yazılır. REPLAY koşusu
(`--allow-replay`) yalnızca duman testidir, durumu değiştirmez.

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
ön inceleme ve denetim nötr REPLAY-MISS çıktısı verir (yukarıda), soru/bulgu göstermez; case
üretimi `ReplayNoOutput` ile sıfır taslak verir (başka özelliğin case'leri gelmez).

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

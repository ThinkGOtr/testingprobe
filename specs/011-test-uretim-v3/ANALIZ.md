# 011 — Gereksinimden test üretimi v3 ("Prompt Seti v2") — Analiz

Tarih: 2026-11-11 · Dal: `feat/case-gen-v3` (dev'den) · Durum: kararlar alındı, geliştirme başlıyor

Kaynak: Cengizhan Günaydın, "Test Probe & Agent Probe – Gereksinimden Test Üretim Prompt Seti (v2)"
(3 PDF; `.docs/` altında, repoya girmez). 1. belge P0, P0.5, P8, P9; 2. belge P1–P7 ekleri;
3. belge gerekçe ve kaynakça (prompt değildir).

Bu doküman kapsamı, alınan kararları, bileşenler arası sözleşmeleri ve geliştirme şeritlerini
sabitler. Şeritler bu dokümana göre çalışır; sözleşme değişikliği önce buraya yazılır.

## 1. Amaç ve kapsam

Bugün case üretimi tek model çağrısıdır (`case-generation` v2): başlık, tür, risk, AC atıfı, adımlar.
Hedef, belgedeki akışın tamamı:

| # | İş | Belgedeki karşılığı |
|---|---|---|
| F1 | Case şeması ve promptu v3: teknik, kapsam öğeleri, öncelik, hazır olma durumu, açık soru / varsayım, negatif kapsam kararı, doğrulama noktası, test verisi, temizlik | P0 |
| F2 | Üretimden sonra ayrı çağrıyla review (eleştirmen rolü, 12 madde) | P8 |
| F3 | İki tur: önce test tasarım modeli, insan onayı, sonra yalnız onaylı modelden case | P0.5 |
| F4 | Platform ekleri (Web, Mobil, Desktop, API, Data) + negatif genişletme ve teknik derinleştirme düğmeleri | P1–P4.5, P5, P6 |
| F5 | Denetim kapısı: KABUL / DÜZELTME_GEREKLİ / ENGELLE; yalnız KABUL alan set yayınlanır | P9 |
| F6 | AI ajan ürünleri: test Agent Probe'da koşar, Testing Probe süreci yönetir (simüle bütünleşme) | P7 yerine |
| F7 | Asistan denetimi: asistana yazılan soru ve asistanın cevabı anlık puanlanır | (yeni istek) |
| F8 | Gherkin dışa aktarımı (deterministik) | P0 "Gherkin alternatifi" |

Kapsam dışı: P7 YAML test suite üretimi (ajan testi Agent Probe'un işidir), gerçek Agent Probe
servisine ağ çağrısı, PICT ile pairwise satır üretimi (model yalnız parametre + kısıt verir),
tp-vm'e deploy (ayrıca istenecek).

## 2. Kararlar (2026-11-11, ürün sahibi)

| # | Konu | Karar |
|---|---|---|
| K1 | İki tur | Varsayılan iki tur; analist üretimi başlatırken "tek tur (hızlı)" seçebilir. IDE kanalı tek turla çalışmaya devam eder |
| K2 | P9 yeri | Agent Probe portu arkasında, Testing Probe geçidinde ayrı çağrı (gerçek model). İleride aynı port gerçek Agent Probe'a bağlanır |
| K3 | P9 kapısı | Yayın için setin güncel içeriğine ait KABUL zorunlu; `TP_DENETIM_KAPISI=off` ile kapatılabilir |
| K4 | P8 review | Her üretimden sonra otomatik; tavsiye niteliğinde (onayı ve yayını engellemez), P9'a girdi olur |
| K5 | Platform girdisi | Analist üretimi başlatırken seçer; seçim gereksinimle saklanır, sonraki üretimde varsayılan olur |
| K6 | Hazır olmayan case | "Onayla" reddedilir; analist "Düzelt" ile hazır yapar ya da reddeder. Yayın kapısı ayrıca denetler |
| K7 | Derinleştirme (P5/P6) | Mevcut sete ek taslak; mevcut taslak ve onaylar korunur |
| K8 | Modeller | Üretim, tasarım modeli, review, derinleştirme: `claude-sonnet-5-5`. Denetim (P9): `claude-opus-5-5`. Asistan denetimi: `claude-haiku-5-5` |
| K9 | Eski (v2) case'ler | `readiness` alanı olmayan case hazır sayılır, olduğu gibi kalır; düzeltme eski alan kümesiyle doğrulanır; denetim kapısı aranmaz |
| K10 | AI ajan ürünleri | Test Agent Probe'da koşar (Sauce Labs benzeri). Yalnız Agent Probe'da ön tanımları tamamlanmış ürünler Testing Probe'da görünür; Testing Probe sonuçlara göre ilerler. Agent Probe bu sürümde simüle edilir (kayıt atılır, cevap gelir) |
| K11 | Asistan denetimi | Soru asistan modeline gitmeden, cevap kullanıcıya gösterilmeden önce puanlanır (0–100 + kategori). Puanı port arkasında gerçek model çağrısı üretir. Düşük puan: engelle + açıklama; orta puan: uyarı notuyla göster; port erişilemezse kapalı (fail-closed) |
| K12 | Canlı eval bütçesi | Toplam sert tavan 30 USD; aşılacaksa durulur ve sorulur |
| K13 | Kapsam öğeleri | Tek ortak `coverage_items` listesi (kimlik, AC, tanım, geçerli/geçersiz) hem tek turda hem onaylı modelde; kapsam matrisi kodda hesaplanır |
| K14 | Gherkin | Dahil: onaylı ve hazır case'ler için "Gherkin indir" (kodda dönüşüm, model çağrısı yok) |
| K15 | Demo provası | Tam yeni akış kayıtlı çıktılarla (strict REPLAY): model onayı, review, denetim kapısı provada oynanır |

Uygulama sırasında verilen teknik kararlar (ürün kararı değil; gerekçesiyle):

- Başlığa `[Teknik]` öneki yazılmaz: teknik ayrı alandır, portal rozet gösterir; mevcut başlıklar ve
  bunlara bağlı aşağı akış golden'ları (verify-and-map, codegen) bozulmaz.
- Belgedeki `<PLATFORM>-<MODÜL>-<TÜR>-<NNN>` kimliği modele yazdırılmaz; case kimliği bugünkü gibi
  deterministik `uuid5`'tir. Okunur kısa ad gerekiyorsa kodda türetilir.
- Sınırlar korunur: story başına ≤ 10 case, case başına ≤ 8 adım (maliyet, review süresi). Sığmayan
  öğe `not_covered`'a gerekçesiyle yazılır.
- `case_generation.max_tokens` 16000 → 32000 (v3 çıktısı yaklaşık iki kat; düşünme payı dahil).
- Few-shot olarak belgedeki varsayımsal örnek kullanılmaz; gerekirse kendi golden'larımız.

## 3. Hedef akış

```
PO onaylı gereksinim
  └─ Üretimi başlat (form: kip = iki tur | tek tur; platform(lar), test seviyesi,
     benimsenen standartlar, kapsam dışı)                                   [K1, K5]
       ├─ iki tur:  tasarım modeli üretimi → analist düzeltir/onaylar → case üretimi   [F3]
       └─ tek tur:  doğrudan case üretimi                                              [F1]
  └─ Otomatik review (P8) → bulgular portalda (tavsiye)                                [F2]
  └─ (isteğe bağlı) Negatif genişlet / Teknik derinleştir → ek taslaklar → review yenilenir [F4]
  └─ Analist kararları: onayla (yalnız hazır case) | düzelt | reddet                   [K6]
  └─ Review tamamlandı → Denetim (P9, Agent Probe portu) → KABUL | DÜZELTME_GEREKLİ | ENGELLE [F5]
  └─ Yayın (Jira/Xray): hazır + onaylı + (kapı açıksa) setin güncel hash'ine ait KABUL  [K3]
  └─ Gherkin indir                                                                     [F8]

Ürün AI ajanıysa: gereksinim bir Agent Probe ürününe bağlanır → "ajan testi talebi" →
Agent Probe koşusu (simülatör) → sonuç Testing Probe'da; case üretim akışı çalışmaz.   [F6]

Asistan: soru → puan → (engel | uyarı | geç) → asistan modeli → cevap → puan → (engel | uyarı | göster) [F7]
```

Değişmeyen ilkeler: güvenilmeyen girdi blokları, uydurma yasağı, insan onayı (model hiçbir şeyi
onaylayamaz/yayınlayamaz), deterministik kontroller modelden önce gelir, replay/golden, prompt
değişikliği canlı değerlendirmesiz `main`'e girmez.

## 4. Sözleşmeler

### 4.1 Case üretim çıktısı (şema v3) — `rules/schemas/case_generation.schema.json`

Dosya bu dalda yazılıdır ve bağlayıcıdır. Özet:

- Üst düzey (hepsi zorunlu, boş liste olabilir): `open_questions[{id Qn, question, owner}]`,
  `assumptions[{id An, statement, owner}]`, `coverage_items[{id, ac_ref, definition, valid}]`,
  `negative_coverage[{item, decision: tested|covered_by|out_of_scope, rationale}]`,
  `not_covered[{item, reason}]`, `observations[{standard_ref, note}]`,
  `automation_open_points[string]`, `config_matrix{parameters[{name, values[]}], constraints[]}`,
  `testability_gaps[{control, missing}]`, `cases[]`.
- Case: v2 alanları (`title`, `type`, `risk`, `acceptance_criteria_refs`, `preconditions`,
  `steps[{id, action, data, expected}]`, `expected_result`, `tags`) + `technique[]`
  (EP|BVA|DT|ST|PW|UC|EG), `covers[]`, `priority` (P1|P2|P3), `priority_rationale`, `test_level`
  (null olabilir), `verification_point` (UI|API|event|DB|log|other), `readiness`
  (ready|assumption_dependent|blocked), `assumption_refs[]`, `open_question_refs[]`,
  `test_data[{name, value, class, synthetic, is_attack_payload}]`, `teardown[]`, `platform` (null
  olabilir), `requires_real_device`, `standard_refs[]`. `type` enum'una `authorization` ve
  `integration` eklendi.
- Kapsam öğesi kimliği: `EP-V1`, `EP-I2`, `BV-3`, `DT-R2`, `ST-S1>S2`, `PW-1`, `UC-MF|AF1|EF1`, `EG-1`.
- `coverage_matrix` modele yazdırılmaz.

### 4.2 Deterministik kurallar (`features/cases/schema.py`)

`consistency_problems(case, ozet) -> list[str]` (ozet = aynı üretimin üst düzey listeleri):

1. `covers` içindeki her kimlik `coverage_items`'ta tanımlı.
2. `technique` ↔ `covers` öneki uyumlu (EP→`EP-`, BVA→`BV-`, DT→`DT-`, ST→`ST-`, PW→`PW-`, UC→`UC-`, EG→`EG-`).
3. `assumption_refs` / `open_question_refs` üst listelerde tanımlı.
4. `ready`: iki ref listesi boş; `expected_result` ve tüm adım `expected`'ları dolu.
   `assumption_dependent`: `assumption_refs` dolu, beklenenler dolu.
   `blocked`: `open_question_refs` dolu, `expected_result` boş (adım `expected`'ları boş olabilir).
5. `test_data[].synthetic` true olmalı.
6. `is_attack_payload: true` olan değerin metni case'in başka hiçbir alanında (başlık, ön koşul, adım,
   beklenen, temizlik) geçmez.
7. AC atıfları gereksinimde var (mevcut `unknown_ac_refs`).

Set düzeyi `set_problems(cases, ozet, kabul_kriterleri)`: her `valid:false` öğenin tam bir
`negative_coverage` kararı var; `tested|covered_by` kararlı öğe en az bir case'in `covers`'ında;
hiçbir case'in kapsamadığı öğe/AC `not_covered`'da ya da `out_of_scope` kararında gerekçeli.

Uygulama: model çıktısında ihlal → case taslak olarak yazılır, `uyarilar`'da gösterilir, **onay
reddedilir** (bugünkü "bilinmeyen AC" davranışı). İnsan düzeltmesinde ve IDE taslağında ihlal → 422.

`coverage_matrix(cases, ozet, kabul_kriterleri)` kodda hesaplanır:
`[{item, tur: "ac"|"oge", tanim, valid, covered_by: [sira_no…], gerekce}]` + oranlar
(gereksinim kapsamı, öğe kapsamı, negatif karar kapsamı).

Uygulamada netleşenler (T1, kabul edildi):
- Set düzeyi ihlaller (`set_problems`) 422 değil, `uyarilar` + denetim kaydıdır (IDE taslağı parça
  parça gelebilir); 422 yalnız case düzeyi ihlallerdedir.
- Kural 2 çift yönlüdür: `technique`'teki her teknik için `covers`'ta önekli öğe aranır ve
  `covers`'taki her öğenin tekniği `technique`'te olmalıdır (üretim kuralı, eval denetleyicisi ve
  test yardımcısı aynı kuralı uygular; çapraz test `test_case_goldens_v3.py`).
- Prompt netleştirmeleri (T4 önerileri): test verisiyle kurulamayan sınır değer `out_of_scope`;
  kaynağın sessiz olduğu öğe `out_of_scope` + gerekçede soru kimliği; geri alınamayan kayıt için
  tek satırlık temizlik notu; `not_covered.item` = öğe kimliği ya da `ACn`; sınır aşılınca önce
  en riskli öğeler.
- Kural 6 büyük/küçük harf ve boşluk sadeleştirilmiş alt dizgi aramasıdır; adım `data`'sı da kapsanır.
- IDE taslağı `ozet` göndermezse kapsam öğesi tanımlılığı atlanır; Q/A atıflı case 422 alır.
- `coverage_matrix` → `{satirlar, oranlar}`; birden çok üretimde güncel case'i olan üretimlerin
  özetleri birleştirilir (aynı kimlikte sonraki üretim geçerli). Derinleştirme üretimleri (P şeridi)
  mevcut kimliklerle çakışmayan yeni kimlik numaraları kullanmalıdır.
- `serialize_cases` ayrıca `onay_engeli` (approve'un 422 metni ya da null) döner.

Eski case (K9): `readiness` anahtarı yoksa `legacy`; `validate_case(..., legacy=True)` yalnız v2
zorunlu alanlarını arar; `readiness_of(icerik)` `"ready"` döner. IDE taslağı (`submit_drafts`) her
zaman tam v3 ister.

### 4.3 Veri modeli (migrasyon numaraları şeritlere ayrılmıştır)

| Migrasyon | Şerit | İçerik |
|---|---|---|
| 0021 | T (temel) | `case_uretim` (requirement_id, uretim_no, kanal, tur: `uretim`\|`negatif`\|`teknik`, ai_call_id, `ozet` JSONB = üst düzey listeler, olusturma; tekil requirement_id+uretim_no) |
| 0022 | M (tasarım modeli) | `tasarim_modeli` (requirement_id, surum, icerik JSONB, icerik_hash, onaylanan_hash, durum: draft\|approved\|rejected\|superseded, ai_call_id, uretim_modu); gereksinim durumları `modeling`, `model_ready`; `review.nesne_turu` += `design_model` |
| 0023 | D (review + denetim) | `case_set_review` (requirement_id, uretim_no, set_hash, skor, icerik JSONB, ai_call_id); `case_set_audit` (requirement_id, set_hash, karar, icerik JSONB, kaynak: `tp-gecit`\|`agent-probe`, talep_no, ai_call_id) |
| 0024 | P (platform + derinleştirme) | `requirement.uretim_secenekleri` JSONB |
| 0025 | A (Agent Probe) | `ajan_urunu_baglantisi` / `ajan_testi_talebi` (requirement_id, urun_kodu, talep_no, durum, sonuc JSONB); `asistan_denetim` (mesaj_id, yon: soru\|cevap, puan, kategoriler, karar: gec\|uyar\|engelle, ai_call_id) |

Her şerit kendi worktree'sinde `down_revision`'ı temel şeridin başına (0021) bağlar; birleştirmede
zincir 0021→0022→0023→0024→0025 olarak doğrusallaştırılır.

`set_hash` = gereksinimin güncel (superseded/ret olmayan, eski içerik olmayan) v3 case'lerinin
`icerik_hash`'lerinin sıralı birleşiminin hash'i. Bir case değişir, eklenir ya da çıkarsa set hash'i
değişir ve önceki denetim kararı geçersiz olur.

Uygulamada netleşenler (D şeridi):
- `set_hash` = sha256(`"\n".join(sorted(icerik_hash))`) (`features.cases.review.set_hash(session,
  req) -> str | None`; v3 case yoksa None). Onay ve yayın seti değiştirmez (`icerik_hash` aynı).
- İki tabloya ek kolonlar: `durum` (`bekliyor|tamamlandi|hata`), `hata`, `job_id`, `isteyen`,
  `guncelleme`; `case_set_audit`'te ayrıca `model_karari` (modelin kararı; `karar` deterministik
  sertleştirmeden sonraki karar, kapı bunu okur) ve `review_id` (girdi olan P8). Uygulama rolü
  satır silmez (geçmiş korunur).
- "Denetime gönder" koşulu: güncel setin review'u tamamlanmış **ya da** setin en az bir onaylı v3
  case'i var; aynı set için review sürüyorsa beklenir.
- Port hatası/REPLAY-MISS karar üretmez (fail-closed); review hatası gereksinimi etkilemez.

### 4.4 API (core-api) — yeni uçlar

| Yöntem | Yol | Şerit | Açıklama |
|---|---|---|---|
| POST | `/requirements/{id}/generate-cases` (gövde: `{kip, platformlar[], test_seviyesi, benimsenen_standartlar[], kapsam_disi}`; gövdesiz çağrı eski davranış = tek tur) | T, M, P | Üretimi başlatır |
| GET | `/requirements/{id}/case-summary` | T | Üretim başına üst listeler + hesaplanan kapsam matrisi + teknik/readiness dağılımı |
| GET | `/requirements/{id}/design-model` · POST `/design-models/{id}/decision` (approve\|edit\|reject) | M | Tasarım modeli ve kararı |
| GET | `/requirements/{id}/case-review` · POST `/requirements/{id}/case-review` (yeniden çalıştır) | D | P8 sonucu |
| GET | `/requirements/{id}/case-audit` · POST `/requirements/{id}/case-audit` | D | P9 kararı / denetime gönder |
| POST | `/requirements/{id}/deepen` (gövde: `{tur: negatif\|teknik, teknik?}`) | P | P5 / P6 |
| GET | `/requirements/{id}/cases.feature` | G | Gherkin (text/plain) |
| GET | `/agent-probe/products` · POST `/requirements/{id}/agent-test` · GET `/requirements/{id}/agent-test` | A | Ajan ürünleri ve test talebi |

`serialize_cases` her case'e `readiness`, `legacy`, çözülmüş `acik_sorular[]` / `varsayimlar[]`
(atıf yapılan soruların/varsayımların metni) ve tutarlılık `uyarilar`'ını ekler.

### 4.5 Agent Probe portu (`tp_core/ports.py` → `AgentProbePort`)

```
audit_case_set(istek) -> DenetimSonucu      # P9  (bugün: TpGecitAgentProbe → geçit, case-audit, Opus)
score_message(metin, yon, baglam) -> Puan   # F7  (bugün: geçit, assistant-guard, Haiku)
list_products() -> [AjanUrunu]              # F6  (bugün: simülatör; yalnız ön tanımı tamam ürünler)
start_agent_test(urun, gereksinim) -> Talep # F6  (simülatör: kayıt atar, talep no döner)
get_agent_test(talep_no) -> TalepDurumu     # F6  (simülatör: deterministik durum/sonuç)
```

Seçim `TP_AGENT_PROBE=tp|sim|http` (http bu sürümde yok; ayar adı ayrılmıştır). Her çağrı denetim
zincirine (`audit`) yazılır. Simülatör `sims/` altındaki mevcut simülatör düzenini izler.

### 4.6 Prompt paketleri ve modeller

| Paket (`rules/prompts`) | Amaç (`purpose`) | Model | Şerit |
|---|---|---|---|
| `case-generation` v3 (+ onaylı model bölümü, + platform ekleri) | `case_generation` | sonnet-5-5 | T, M, P |
| `design-model` v1 | `design_model` | sonnet-5-5 | M |
| `case-review` v1 | `case_review` | sonnet-5-5 | D |
| `case-audit` v1 | `case_audit` | opus-5-5 | D |
| `case-negative` v1 (P5), `case-technique` v1 (P6) | `case_deepening` | sonnet-5-5 | P |
| `platform-web/-mobile/-desktop/-api/-data` v1 (ek dosyalar) | `case_generation`'a eklenir | — | P |
| `assistant-guard` v1 | `assistant_guard` | haiku-5-5 | A |

Her paket: şema (`rules/schemas`), golden (`rules/replay`), değerlendirme seti
(`rules/evaluation`), `evaluations.yaml` kaydı, canlı değerlendirme. Belgedeki [ISTQB] / [Ekip]
ayrımı prompt'larda korunur; "standarda uy" denmez, kural açık yazılır. Platform rehberi eşikleri
yalnız `benimsenen_standartlar`'da varsa beklenen sonuç olur, yoksa `observations`'a yazılır.

### 4.7 Yayın (`features/publish`, `integrations/testmgmt.py`, Xray)

Engel sırası: durum `approved` → hash eşleşmesi → gereksinim güncel → `readiness_of == ready` →
(v3 case ve kapı açıksa) setin güncel `set_hash`'i için `KABUL`. Jira açıklaması "Scope" bölümüne
teknik, öncelik (+ gerekçe), doğrulama noktası, test seviyesi; "User Flow"a test verisi ve temizlik
eklenir. `CASE_TYPE_TR`'ye `authorization` → "yetki", `integration` → "entegrasyon". Saldırı
verisi (`is_attack_payload`) Jira'ya "güvenlik testi girdisi" etiketiyle, kod bloğu olarak yazılır.

### 4.8 Portal (review-portal)

Case kartı: teknik rozetleri, öncelik, hazır olma rozeti (hazır / varsayıma bağlı / engelli),
atıf yapılan açık sorular ve varsayımlar, doğrulama noktası, test verisi (saldırı verisi işaretli),
temizlik. Gereksinim sayfası: üretim formu (kip + platform seçenekleri), tasarım modeli onay ekranı,
kapsam matrisi ve kapsanmayanlar, açık sorular / varsayımlar listesi, review bulguları, denetim kararı
ve "Denetime gönder", derinleştirme düğmeleri, "Gherkin indir". Yayın sayfası: hazır değil / denetim
bekliyor engelleri. Ajan ürünleri sayfası. Asistan: engel/uyarı gösterimi. Tasarım çizgisi mevcut
portal (Agent Probe çizgisi) ile aynı; yeni bileşen kütüphanesi eklenmez.

### 4.9 Metrikler (§12)

Teknik dağılımı, readiness dağılımı, gereksinim kapsamı, öğe (bölüm) kapsamı, negatif karar kapsamı,
review skoru, denetim kararı dağılımı, asistan denetimi (engel/uyarı oranı). Belgedeki başlangıç
hedefleri ekip hedefidir, standart değildir; eşik olarak kod kapısı yapılmaz, gösterilir.

## 5. Şeritler ve çalışma düzeni

Dalga 1 — temel (tek worktree `tp-wt-v3`, dal `feat/case-gen-v3`, dosya ayrık dört şerit):

| Şerit | Dosyalar | İş |
|---|---|---|
| T1 çekirdek | `features/cases/*`, `models`, `alembic 0021`, `mcp_server`, cases testleri | §4.2, §4.3 (0021), `/case-summary`, K6, K9, metrikler, üretim mesajına test seviyesi |
| T2 yayın | `features/publish/*`, `integrations/testmgmt.py`, `xray.py`, testleri | §4.7 (denetim kapısı kancası hariç: D şeridi bağlar) |
| T3 portal | `review-portal/` | Case kartı v3, özet paneli, mock/fixture'lar |
| T4 golden + eval | `rules/replay/case_generation`, `rules/evaluation`, `gateway/eval_*`, gateway testleri, golden-drift | Golden'lar v3 (mevcut alanlar bayt bayt korunur), eval seti, `coverage_problems` beklentileri |

Dalga 2 — dalga 1 üzerine, her biri kendi worktree'sinde paralel:

| Şerit | Worktree / dal | İş |
|---|---|---|
| M | `tp-wt-model` / `feat/v3-model` | F3 iki tur |
| D | `tp-wt-denetim` / `feat/v3-denetim` | F2 review + F5 denetim kapısı + port iskeleti |
| P | `tp-wt-platform` / `feat/v3-platform` | F4 üretim formu, platform ekleri, P5/P6 |
| A | `tp-wt-agentprobe` / `feat/v3-agentprobe` | F6 ajan ürünleri (simülatör) + F7 asistan denetimi |
| G | `tp-wt-gherkin` / `feat/v3-gherkin` | F8 Gherkin |

Dalga 3 — birleştirme (`tp-wt-v3`): şerit dalları sırayla merge, migrasyon zinciri, tam test paketi,
`make demo-prova` (strict REPLAY), canlı değerlendirmeler (`make eval-live`, tavan 30 USD), Chrome
for Testing ile ekran testi.

Dalga 4 — eleştiri döngüsü: farklı rollerden bağımsız inceleme (test mimarı, güvenlik, UX, backend,
ürün/analist gözü) → bulgular → düzeltme → yeniden inceleme; engelleyici bulgu kalmayana kadar.

Bitiş: `feat/case-gen-v3` → `dev` → `main` (iki dal eşit, force-push yok, push öncesi sır taraması,
imzasız commit). Deploy yok.


### 5.1 Birleştirmede netleşenler (dalga 2 → `feat/case-gen-v3`)

- **Migrasyon zinciri** doğrusal: 0021 `case_uretim` → 0022 `tasarim_modeli` → 0023 review/denetim →
  0024 `uretim_secenekleri` → 0025 Agent Probe + `asistan_denetim`.
- **Üretim başlatma gövdesi** tek modeldir (`UretimBaslatGirdisi`): `kip` + üretim seçenekleri.
  Gövdesiz çağrı tek tur + kayıtlı seçenekler (geriye uyum, prova); gövde varsa `kip` varsayılanı
  `iki_tur`. Seçenekler iki turun model aşamasında da gereksinime yazılır; tur 2 aynı seçenekleri
  kullanır. Portal `caseUret(id, kip, secenekler)`; seçenek formu seçili kipi gönderir.
- **Otomatik review (K4)** hem `run_generation` hem derinleştirme (`run_deepening`) sonrasında
  `review.schedule_review` ile planlanır. IDE taslağından sonra planlanmaz (açık nokta).
- **Yayın kapısı (K3):** `features/publish/__init__.py` yüklenirken `denetim_akisi.bind_gate()`;
  `TP_DENETIM_KAPISI=on|off`. Denetim kararı `model_karari` ve kod kararı ayrı saklanır; kod yalnız
  sertleştirir (Constitution XI).
- **Ek API uçları:** `GET /requirements/{id}/generation-options`, `GET /requirements/{id}/deepen`
  (son derinleştirme durumu), `PUT /requirements/{id}/agent-product`.
- **Durum makinesi:** requirement'a `modeling`, `model_ready` (iki tur) ve `po_approved → done`
  (yalnız Agent Probe testi bu içerik için geçen AI ajan ürünü gereksinimi; case akışı çalışmaz)
  eklendi; `design_model` makinesi (tablo `tasarim_modeli`, `states.ENTITY_BY_TABLE`).
- **Asistan:** `asistan_mesaj.kaynak` += `denetim` (engellenen / denetimsiz kalan mesaj). Soru/cevap
  metni `asistan_denetim`'e yazılmaz; yalnız puan, kategori, karar.
- **Geçit:** `Gateway.call(..., ek=)` — çağıranın `ai_call.ek` alanları (platform ekleri, asistan
  denetiminde kullanıcı kimliği → bütçe).
- **Platform ekleri:** sistem prompt'una değil kullanıcı mesajına "Platform eki" bölümü olarak
  girer (`id@vN (sha256)` başlıklı); her ekin kendi `evaluations.yaml` kaydı ve seti vardır, ev
  sahibi `case-generation` paketiyle çağrılır (`call_bundle`); ev sahibi prompt/şema değişirse
  ekin değerlendirmesi bayatlar.
- **Gherkin 404** asistan hata sözlüğündeki genel `bulunamadi` kodunu kullanır (yeni kod asistan
  kurallarının değerlendirmesini bayatlatırdı).
- **Ürün kararı bekleyen:** TPD-3 golden'ında (açıklamada prompt injection) denetim kararı
  DÜZELTME_GEREKLİ (story temizlenmeden ona bağlı test yayınlanmasın). Agent Probe testi
  başarısız olunca bug taslağı üretilmez (kayıt ve kanıt Agent Probe'da).

## 6. Riskler ve açık noktalar

- **Canlı eval kapısı:** `guardrails`, `consistency-check`, `verify-and-map(-app)` kayıtları bu işten
  önce de `pending`; `evaluation --check` bu yüzden zaten 1 dönüyor. Bu iş kendi paketlerini
  `evaluated` yapar; diğerleri kapsam dışıdır.
- **Aşağı akış golden'ları:** verify-and-map ve codegen girdileri case içeriğinden kurulur; v3 alanları
  eklenince girdi beyanları değişebilir. T4 mevcut alanları korur, etkiyi ölçer, gerekeni yeniden kurar.
- **Çıktı boyutu / süre:** v3 çıktısı büyür; zaman aşımı ve maliyet canlı eval'de ölçülür.
- **Simülasyon:** F6 simülatördür; gerçek Agent Probe bağlanana kadar ajan testi sonuçları temsilidir
  ve portalda "simülasyon" olarak işaretlenir.
- **Asistan gecikmesi:** F7 her mesaja iki ek model çağrısı ekler; süre ölçülür ve raporlanır.
- **Canlı veri:** tp-vm'deki v2 case'ler K9 ile korunur; migrasyonlar yalnız ekleme yapar.

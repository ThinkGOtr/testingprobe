# rules/

AI adımlarının kullandığı **prompt, kural, şema ve replay kayıtları** burada düz dosya olarak
versiyonlanır. Model geçidi (`core/src/tp_core/gateway`) bu dizini çalışma anında okur
(`TP_RULES_DIR`, varsayılan: depo kökündeki `rules/`).

## Neden ayrı bir dizin

- **Ürün opsiyonel kalabilir (constitution IX):** prompt'lar, kurallar ve şemalar üründen bağımsız
  dışa aktarılabilir; Claude Code (`CLAUDE.md`) ve GitHub Copilot
  (`.github/copilot-instructions.md`) kural dosyaları buradan üretilir.
- **Deterministik önce (constitution XI):** bir kuralın verebildiği karar modele bırakılmaz. Triage
  önce deterministik kural setiyle yapılır; model yalnızca kural eşleşmediğinde devreye girer.
- **Yapılandırılmış çıktı (constitution III):** her model çağrısının çıktısı buradaki şemaya göre
  doğrulanır; uymayan çıktı hata listesiyle en fazla 2 kez yeniden istenir, sonra insana düşer.

## Yapı

```text
rules/
├── models.yaml              # amaç → model, max_tokens, params (effort, thinking); fiyat tablosu
├── pii-allowlist.yaml       # maskelenmeyecek sentetik değerler (simülatör kullanıcıları)
├── assistant/               # portal asistanı ve Öneri düğmesi kuralları (modelsiz; aşağıda)
├── prompts/
│   ├── _guardrails.md       # her prompt'a eklenen ortak güvenlik kuralları (<untrusted> blokları)
│   └── <bundle>.md          # YAML ön bilgisi (id, version, purpose) + sistem prompt'u
├── schemas/<purpose>.schema.json   # JSON Schema 2020-12 (çıktı sözleşmesi)
├── fewshot/<bundle>/*.json  # (isteğe bağlı) örnekler; sistem prompt'una eklenir, hash'e girer
└── replay/<purpose>/
    ├── <key>.json           # birebir kayıt (TP_MODEL_MODE=record ile üretilir)
    └── golden/<ad>.json     # adlandırılmış golden kayıt (REPLAY-MISS yedeği)
```

| Amaç (`purpose`) | Bundle | Model | Tür | Çıktı |
|---|---|---|---|---|
| `requirement_review` | `requirement-review` | Sonnet 5.5 | çağrı | §8.2a `questions[]`, `verdict` |
| `consistency_check` | `consistency-check` | Sonnet 5.5 | ajan | §8.2b `findings[]` (kanıtlı) |
| `case_generation` | `case-generation` | Sonnet 5.5 | çağrı | §7 test case şeması `cases[]` |
| `verify_and_map` | `verify-and-map` | Sonnet 5.5 | ajan | §8.4 `step_mapping[]`, `expects[]`, `missing_methods[]` |
| `verify_and_map_app` | `verify-and-map-app` | Sonnet 5.5 | ajan | 009 §2.6 (app-mcp/Appium): `platform`, `step_mapping[]`, `expects[]`, `missing_methods[]` |
| `triage` | `triage` | Haiku 5.5 | çağrı | §8.6 `class`, `signals[]`, `rationale` |
| `bug_draft` | `bug-draft` | Haiku 5.5 | çağrı | §8.12 bug taslağı |
| `dup_rank` | `dup-rank` | Haiku 5.5 | çağrı | §8.12 mükerrer aday sıralaması |
| `assistant` | `assistant` | Haiku 5.5 | ajan | Asistan cevabı (AI-ASISTAN-PLANI §7.2): `cevap_bloklari[]`, `kaynaklar[]`, `oneriler[]` |
| `assistant_deep` | `assistant` | Sonnet 5.5 | ajan | `assistant` ile aynı şema ("Daha ayrıntılı incele", otomatik yükseltme) |

## Portal asistanı kuralları (`assistant/`)

Portal asistanı (AI-ASISTAN-PLANI) modelden önce bu dosyalardaki deterministik kuralları uygular
(constitution XI); hepsi modelsizdir, model kapalıyken de çalışır.

| Dosya | İçerik |
|---|---|
| `assistant/hata-sozlugu.yaml` | Hata `kod`'u (MIMARI-SOZLESME §5) veya `detail`/görünen metin parçası → anlam, neden, çözüm, ekran |
| `assistant/urun-terimleri.yaml` | "Ürüne özgü soru" sınıflandırması için ürün terimleri (genel QA terimleri girmez) |
| `assistant/rotalar.json` | Portalın iç rotaları (`App.tsx` ile birebir); bağlam rotası bunlara indirgenir, cevaptaki iç rota yalnız bunlara uyarsa bağlantı olur |
| `assistant/oneriler.yaml` | Öneri düğmesi kuralları (§17.3 26 kural + 012 son onay kuralı = 27; tek kural tek eylem), olgu sözleşmesi, bilinçli boş ekranlar |
| `assistant/jira-taslaklari.yaml` | Önerilerin Jira kayıt/yorum taslakları (olgu yer tutuculu düz metin; URL yok) |

- `dev` birleştirmesi bayrak arkasıdır (`TP_ASISTAN_MODEL_MODE=off`, `TP_ASISTAN_ONERI`); constitution
  X'teki birleştirme `main`'dir: `assistant` paketi `main`'e canlı değerlendirmeyle (`evaluated`) geçer.
- Öneri kuralları ve taslak şablonları deterministik kural testine
  (`core/tests/unit/gateway/test_rules_asistan.py`: bilinmeyen olgu/operatör/yer tutucu, serbest metin
  olgusu yer tutucu olamaz, taslakta URL yok, sistem hattı olan ekranda Jira eylemi yok, rol hizalama,
  kapsam matrisi) **ve** öneri modu eval vakalarına (`evaluation/assistant.json`) tabidir.
- Asistan golden'ları (`replay/assistant{,_deep}/golden/ornek.json`) yalnız kural testleri içindir;
  asistan çalışma zamanında golden/replay kullanmaz.

## Model geçidi kullanımı (özet)

```python
from tp_core.gateway import (build_gateway, deterministic_call_id, golden_name, load_schema,
                             wrap_untrusted)
gw = build_gateway(recorder, engine=engine)   # PgCallRecorder + kalıcı bütçe + call_id okuyucu
msg = ModelMessage(role="user", content=wrap_untrusted(story_text, source="jira:TPD-1", kind="jira"))
res = gw.call("requirement_review", "requirement-review", [msg],
              load_schema(gw.rules_dir, "requirement_review"),
              replay_key={"name": golden_name("TPD-1"), "jira_key": "TPD-1"}, workflow_id=wf_id,
              call_id=deterministic_call_id(job_id, "requirement_review"))
res.mode   # "live" | "replay" | "replay_miss"  → portalda REPLAY / REPLAY-MISS rozeti
```

- **Güvenilmeyen içerik** (Jira, kod, veri sonucu, snapshot, CI log) prompt'a yalnızca
  `wrap_untrusted(...)` ile girer; `_guardrails.md` bu bloklardaki talimatların uygulanmamasını söyler.
  Her blok içerikten türetilen bir `id` taşır ve yalnızca `</untrusted id="…">` ile kapanır; içerikteki
  `<untrusted`/`</untrusted` benzerleri (sıfır genişlikli/biçim karakterleri, tam genişlikli `＜`,
  NFKC benzerleri dahil) `&lt;` ile etkisizleştirilir.
- **İdempotency:** `call_id` (iş kimliği + adım, `deterministic_call_id`) verilirse kök `ai_call`
  satırı bu kimlikle yazılır; aynı `call_id` ile tekrar çağrıda başarılı sonuç varsa sağlayıcı
  çağrılmaz, bütçe düşülmez, satır yazılmaz (§8.8).
- **Ajanlar** (`run_agent`): yalnızca verilen araç listesi modele sunulur; listede olmayan araç
  çağrısı çalıştırılmaz, `tool_call.izin_verildi=false` ile kaydedilir ve modele hata döner. Son
  sonuç `submit_result` aracıyla (şemaya göre doğrulanır) verilir. Bağlamda yalnızca son sayfa
  snapshot'ı tutulur. Her tur bir `ai_call` (ilk tura `parent_call_id` ile bağlı).
- **Bütçe:** iş akışı başına `TP_WORKFLOW_BUDGET_USD` (2), günlük `TP_DAILY_BUDGET_USD` (30, UTC
  günü); aşılırsa `BudgetExceeded`. `engine` verilirse harcama `ai_call.maliyet` toplamından okunur
  (`PgSpendLedger`): worker yeniden başlasa da tavan korunur. Ajanlarda ayrıca `max_input_tokens`
  (150k).
- **PII maskeleme:** `TP_PII_MASKING=1` ile açılır (müşteri verisi işlenen ortamda zorunlu);
  kapalıyken de kanca çalışır ve `ai_call.maskeleme_farki` yazılır.

## Mod ve replay

| `TP_MODEL_MODE` | Davranış |
|---|---|
| `auto` (varsayılan) | `ANTHROPIC_API_KEY` varsa `live`, yoksa `replay` |
| `live` | Anthropic API; anahtar yoksa açık hata |
| `replay` | `replay/<purpose>/<key>.json`; yoksa `golden/<replay_key.name>.json`: girdi golden'ın `input_match` beyanına uyuyorsa **REPLAY** (köken `golden_matched`), uymuyorsa **REPLAY-MISS**; o da yoksa hata. Ayrıntı ve Demo-A metinleri: `replay/README.md` |
| `record` | `live` + başarılı çıktıyı `replay/<purpose>/<key>.json`'a yazar. Başlangıçta dizin yazılabilir mi bakılır (compose `:ro` → hata); çalışırken yazma hatası ücretli sonucu kaybettirmez, `ai_call.hata`'ya `replay_kaydedilemedi` yazılır |

`TP_REPLAY_STRICT=1` (prova kipi): girdisi beyana uymayan golden'a düşmek yerine `ReplayMiss` hatası
verir. Beyanlı golden'lar senaryodaki Demo-A yolunu yükseltme gerekmeden REPLAY-MISS'siz koşturur.
§13 prova listesindeki "REPLAY-MISS olmadan replay" maddesi demo yolu bu kipte koşturularak
doğrulanır. Birebir kayıtlar iki yolla üretilir:

- **Canlı:** anahtarla `TP_MODEL_MODE=record`.
- **Anahtarsız (golden yükseltme, `tp_core.gateway.promote`):** demo bir kez gevşek kipte koşulur
  (her AI çıktısı REPLAY-MISS); geçidin `ai_call.replay_anahtari`'na yazdığı birebir anahtarlar
  okunur, çıktı golden'la eşleştirilir ve golden birebir kayda yazılır. Sonraki koşu
  `TP_REPLAY_STRICT=1` ile REPLAY-MISS'siz geçer. Kayıt `provenance: "golden_promoted"` ve
  `golden_sha256` taşır; mod `replay` olur (asla `live`), `ai_call.ek.replay_kokeni` kökeni
  gösterir. Golden sonradan değişirse kayıt bayatlar ve kullanılmaz (golden'a düşer).

  ```bash
  cd core && uv run python -m tp_core.gateway.promote --database-url "$TP_DATABASE_URL" \
      [--workflow <uuid>] [--dry-run]       # host'tan: compose'da rules/ salt okunur
  uv run python -m tp_core.gateway.promote --check-stale   # bayat yükseltilmiş kayıtlar
  ```
  Kütüphane: `promote_call` / `promote_agent` aynı anahtarı `Gateway.replay_key_for_call/agent`
  ile (call/run_agent'ın kod yolu) hesaplar.

- `key = sha256(kanonik {purpose, bundle_hash, replay_key, input_hash})`. `input_hash`, zaman
  damgası, UUID ve snapshot `ref=eN` değerleri normalize edilmiş (maskeli) girdiden hesaplanır.
- `bundle_hash = sha256(prompt dosyası + _guardrails + şema + few-shot + model + params + max_tokens)`
  (ajanlarda araç tanımları da girer). Prompt/şema/model değişirse birebir kayıtlar eşleşmez ve
  golden'a düşülür: bu **bilinçli olarak sessiz değildir**; kayıtlar `record` moduyla yenilenir.
- **Golden adı** çağıranın verdiği `replay_key["name"]`'dir; `golden_name()` ile üretilir:
  story düzeyi `TPD-1`; case düzeyi (verify_and_map) `TPD-1-C<sira_no>`; tutarlılık denetiminin
  2. ve sonraki turları `TPD-1-r2` (düzeltilmiş doküman: engelleyici bulgu yok → "son hal");
  triage / bug_draft / dup_rank için sabit kök `HATA` (`defect_replay_key(story_key)`); hangi hata
  olduğu adla değil girdi beyanıyla seçilir (`replay/README.md` "Faz 4").
- TPD-1 golden'ları adım 2 sonrası **düzeltilmiş** dokümana göredir: AC2 "her 6 adette 1 adet
  bedava (5 öde + 1 bedava)",
  AC3 "kampanyasız siparişlerde minimum 750,00 TL", AC6 korunur (kod kampanyalı sepette minimumu
  aramaz), AC4 kod hatasıdır (case `expected-code-defect`, verify_and_map'te `missing_methods`).
- verify_and_map golden'larının tarayıcı adımları gerçek Playwright MCP'ye karşı (doğrulama bayisi
  `bayi3`, `core/tests/unit/gateway/record_verify_goldens.py`) koşturulup kaydedilmiştir; hedefler
  oturumdan bağımsız `data-testid` seçicileridir (snapshot `ref`'leri oturumlar arasında değişir).
  Model çıktısı kısmı elle hazırlanmıştır. Analistin farklı kararıyla varılan belge için senaryo
  golden'ları `golden/<senaryo>/` altındadır (ör. `f2-kod-hatasi/`, Demo-B'nin "defect adayı" yolu);
  ayrıntı `replay/README.md`.
- Ajan replay'inde kayıtlı adımlar **güncel izin listesine göre** yeniden çalıştırılır (portalda
  canlı görüntü için); listede olmayan araç replay'de de çalışmaz.
- Mevcut golden kayıtlar elle hazırlanmıştır (`note` alanı). Canlı anahtar geldiğinde
  `TP_MODEL_MODE=record` ile gerçek model çıktısıyla yenilenmelidir. Kayıt üst verisi
  (`recording`: model, provider, latency_ms, token'lar; `recorded_at`) olmayan replay çıktısı
  `ai_call.model = "golden-elle"` ve `ek.cikti_kokeni = "elle_hazirlanmis"` ile yazılır; model
  kaydı gibi sunulmaz. Kullanıcı etiketi için `tp_core.gateway.mode_label(mode, ai_call.model)`.
- REPLAY-MISS politikası: `replay/<amaç>/on_miss.json` — nötr yedek (`requirement_review`,
  `consistency_check`, `triage` → `unknown`) ya da `"policy": "raise"` (`case_generation`,
  `verify_and_map`, `bug_draft`, `dup_rank`).
  Beyanlı golden girdiye uymazsa golden yerine bu çıktı döner (`ek.replay_kokeni = miss_neutral`);
  ayrıntı `replay/README.md`.

**Ajan araç izin listesi (geçitte, `ALLOWED_AGENT_TOOLS`):** `verify_and_map` yalnızca §8.4
listesi (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`,
`browser_select_option`, `browser_wait_for`, `browser_generate_locator`); `consistency_check`
yalnızca `search_code`, `get_file_contents`, `db_schema`, `db_query`. `assistant` ve `assistant_deep`
yalnızca 13 salt okuma aracı (`product_search`, `product_read`, `probe_get`, `probe_list`, `probe_jobs`,
`probe_audit`, `probe_my_queue`, `jira_issue`, `ci_log`, `search_code`, `get_file_contents`,
`db_schema`, `db_query`). Listesi olmayan amaç ajan
olarak koşamaz; listede olmayan her araç (MCP'nin yeni eklediği araçlar dahil) reddedilir.
`FORBIDDEN_TOOLS` (kod çalıştırma, dosya: `browser_file_upload`, `browser_drop`; ağ, ekran
görüntüsü) ikinci kontroldür. Kayıtlı Playwright MCP `tools/list` fikstürü
(`core/tests/unit/gateway/fixtures/playwright_mcp_tools.json`) her aracın sınıflandığını test eder;
MCP yükseltmesinde fikstür yeniden kaydedilir.

**Demo story kapsamı:** adım 2 golden'ları (requirement_review, consistency_check) TPD-1..4'ün
hepsinde; case_generation golden'ı adım 4'e ulaşan her story'de (TPD-1, TPD-3, TPD-4; TPD-2
kabul kriteri olmadığı için PO'da kalır) vardır. `test_goldens.py` bunu DEMO-VERISI tablosuna karşı
zorlar.

**Golden kayıtların araç adları (tutarlılık ajanı):** `search_code {query}`,
`get_file_contents {path}`, `db_schema {}`, `db_query {sql}`. Özellik şeridi bu adlarla araç verirse
replay adımları da yeniden çalışır.

## Model ve parametre notları

- Görev başına sabit model kimliği: case üretimi ve ajanlar `claude-sonnet-5-5`; triage ve
  özetleme `claude-haiku-5-5`. Fiyatlar `models.yaml`'da.
- `temperature: 0` tasarım gereği kayıtlıdır ve bundle hash'ine girer; ancak Anthropic API'si
  (2026-10-21) ve kurulu SDK örnekleme parametrelerini kabul etmez, Anthropic adaptörü göndermez.
  Determinizm replay ile sağlanır. Azure OpenAI adaptörü (iskelet) bu değeri kullanacaktır.
- Sonnet 5.5 zorunlu `tool_choice` desteklemez; ajan son çıktıyı `auto` seçimiyle ve talimatla
  `submit_result` aracından verir. Tek çağrılarda yerel structured output (`output_config.format`).
- Ajanlarda `thinking: between_tools` (araçlar arası düşünme kapalı): bağlamdan eski snapshot'lar
  çıkarıldığı için geçmiş düzenlenir; thinking blokları bununla uyumsuzdur.

## Kurallar

- Her değişiklik **PR ile** gelir ve review edilir; doğrudan `main`'e yazılmaz.
- Her prompt dosyası **kimlik ve sürüm** taşır (`id`, `version`). Geçit `ai_call.surum`
  (`id@vN`) ve `ai_call.bundle_hash`'i yazar (constitution VIII).
- Prompt veya kural değişikliği, değerlendirme seti canlı modelle koşturulmadan birleştirilmez
  (constitution X).

## Canlı değerlendirme durumu

Makine okunur kayıt: [`evaluations.yaml`](evaluations.yaml) (her prompt paketi için `version` +
`status`: `pending` / `evaluated` / `waived`). Prompt sürümü yükseltilip kayıt güncellenmezse kayıt
**bayat** sayılır. Birleştirme kapısı (constitution X):
`cd core && uv run python -m tp_core.gateway.evaluation --check` → bekleyen, bayat veya eksik kayıt
varsa çıkış 1. Bu tablo kayıtla aynı olmalıdır (`test_evaluation_status.py`).

| Prompt paketi | Sürüm | Durum |
|---|---|---|
| `guardrails` (ortak güvenlik kuralları) | v1 | **canlı değerlendirme bekliyor** |
| `requirement-review` | v3 | **canlı değerlendirildi** (2026-11-01; `evaluation/results/`) |
| `consistency-check` | v4 | **canlı değerlendirme bekliyor** |
| `case-generation` | v2 | **canlı değerlendirme bekliyor** |
| `verify-and-map` (+ `verify_and_map` golden'ları) | v3 | **canlı değerlendirme bekliyor** |
| `verify-and-map-app` (+ `verify_and_map_app` golden'ları; 009 mobil/masaüstü) | v1 | **canlı değerlendirme bekliyor** |
| `triage` (+ Faz 4 golden'ları) | v2 | **canlı değerlendirildi** (2026-11-01; `evaluation/results/`) |
| `bug-draft` (+ Faz 4 golden'ları) | v2 | **canlı değerlendirildi** (2026-11-01; `evaluation/results/`) |
| `dup-rank` (+ Faz 4 golden'ları) | v2 | **canlı değerlendirildi** (2026-11-01; `evaluation/results/`) |
| `assistant` (portal asistanı; `assistant` + `assistant_deep` amaçları, `assistant/*` kuralları) | v1 | **değerlendirme sonrası içerik değişti (içerik hash'i uyuşmuyor)** — 2026-11-04 canlı değerlendirmesi (Haiku 38/40, Sonnet 40/40) 012 rol göçünden önceydi (`assistant/*` rolleri `presenter` → `admin`); `make eval-live` yeniden koşulmalı |

2026-11-01'de `requirement-review` v3, `triage`, `bug-draft` ve `dup-rank` v2 canlı modelle
(`make eval-live A='--bundle … --update-status'`, sert bütçe tavanı 1,50 USD, gerçek harcama
≈0,05 USD) değerlendirildi; raporlar ve çağrı defterleri `evaluation/results/` altındadır. Ajan
paketleri (`consistency-check`, `verify-and-map`), `case-generation` ve bunlara bağlı olarak
geçişli `guardrails` **hâlâ canlı değerlendirme bekliyor**. Golden'lar (REPLAY) değişmedi: demo
çıktısı yine elle hazırlanmış kayıtlardan gelir (replay kayıtlarında `recording` üst verisi yok); Faz 3'te değişen paket `verify-and-map` v3'tür, Faz 4'te `triage`, `bug-draft`
ve `dup-rank` v2'dir (kanonik girdi kurucuları `tp_core.gateway.defects`, yeni golden'lar; ayrıntı
`replay/README.md` "Faz 4"). Geçit her `ai_call.ek.degerlendirme`'ye paketin durumunu yazar
(`{paket, surum, durum, etiket}`; `etiket` = "canlı değerlendirme bekliyor"); portal bunu AI
çıktısının yanında gösterebilir (`tp_core.gateway.evaluation_summary`).

`prompts/verify-and-map.md` v3 ve verify_and_map golden'ları bu ortamda canlı modelle
değerlendirilmedi: API kimlik bilgisi yok (yalnızca REPLAY; golden çıktıları elle hazırlanmıştır,
`ai_call.model = golden-elle`). Golden'ların **tarayıcı adımları** gerçek Playwright MCP'de
kaydedildi ve `python -m tp_core.gateway.replay_check --runs 5` ile canlı yığında tekrarlandı;
bu model değerlendirmesi değildir. Constitution X gereği bu değişiklik `main`'e ancak
(a) değerlendirme seti canlı modelle koşturulduktan sonra ya da (b) onaylı ve kayıtlı bir yönetişim
istisnasıyla birleştirilir. İstisna bu depoda **onaylanmış değildir**; onay yalnızca sahip tarafından,
`evaluations.yaml`'a `status: waived` + `waiver: {approved_by, approved_at, reason, until}` olarak
yazılır (ajanlar/otomasyon istisna yazmaz) ve bu tablo güncellenir. Kimlik bilgisi gelince: `TP_MODEL_MODE=record` ile verify_and_map
yeniden kaydedilir, `usage.cache_read_input_tokens` ile ajan önbelleği doğrulanır ve kayıt
`status: evaluated` + `evaluation: {date, model, provider, results}` olarak güncellenir.

### Canlı değerlendirmeyi koşturmak (`make eval-live`)

`make eval-live` (`scripts/eval-live.sh` → `python -m tp_core.gateway.eval_live`) host'ta, `uv` ile
koşar; `.env`'den yalnızca `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, `TP_EVAL_BUDGET_USD`,
`TP_MODEL_PROVIDER`, `TP_PII_MASKING`'i okur ve hiçbirini yazdırmaz. `TP_MODEL_MODE`'u okumaz: komutun
kendisi canlı çağrı isteğidir; demo yolunun kipi (`.env`'de `replay`) değişmez.

```bash
scripts/eval-live.sh --ping                          # tek küçük çağrı: OK ya da API hata türü/iletisi
scripts/eval-live.sh --dry-run                       # API yok: setler + tahmini maliyet
scripts/eval-live.sh --bundle triage --update-status # set TAMAMEN geçerse evaluations.yaml → evaluated
scripts/eval-live.sh --record                        # kayıt adayları exports/eval-live/<zaman>/replay-adaylari/
```

- Setler (`evaluation/<paket>.json`, `core/tests/unit/gateway/build_eval_sets.py` üretir; elle
  düzenlenmez): `triage`, `bug-draft`, `dup-rank`, `requirement-review` (demo'nun 5 gereksinimi,
  Jira'daki ilk halleriyle: karar, soru türü, belgede olmayan AC'ye soru yok), `case-generation`
  (§12: 5 story × 3 koşu, `runs: 3`; her AC en az bir case'te, uydurma AC yok, düzeltilmiş tutarlar),
  ajanlar `consistency-check` (TPD-1 ve serbest metin 1. tur + tutarlı TPD-4; beklenen belge
  yerleri ve kanıtın üretimin `EvidenceVerifier`'ıyla yeniden doğrulanması) ve `verify-and-map`
  (TPD-1-C3, TPD-4-C1/C2; her adım eşlenmiş, metotlar gerçek sembol tablosunda, beklenen
  assertion'lar). Ajan setleri `"agent": {"tool_env", "max_turns"}` taşır ve araçları ÜRETİMİN
  araç uygulamalarıyla yürütür (`tp_core.gateway.eval_agents`: forge + demo-app salt okuma
  veritabanı; Playwright MCP). Araç ortamı kurulamazsa (yığın kapalı) paket ATLANIR ve durumu
  değişmez — bu ortamlar `make up` ister; host'tan erişilemiyorsa komut core-worker içinde koşar.
- `guardrails`'in ayrı seti yoktur: guardrails'i içeren HER paket aynı guardrails sürümüyle
  (`evaluation.guardrails_version`) `evaluated` olunca `--update-status` onu da geçişli olarak
  `evaluated` yazar (`eval_set.guardrails_coverage`). Bu komut kayıt uydurmaz ve `waived` yazmaz.
  `--update-status` yalnızca set TAMAMEN koşup her vaka geçtiyse yazar; kaydın `note`'u üretilmiş
  satırla değişir ("Canlı değerlendirme <tarih>, <model>, <geçen>/<toplam>: <rapor>").
- `--dry-run` tahmini: token = karakter/3 (yukarı), girdi önbelleğe yazma fiyatıyla (1,25×), çıktı
  tam `max_tokens`; "en kötü durum" şema yeniden istemlerini (2) de sayar; ajanlarda `max_turns` ×
  tam çıktı + amacın girdi tavanı. Yedi setin toplam en kötü durumu ~22 USD'dir (varsayılan 5 USD
  tavanı aşılır; komut `--budget-usd` önerir); hata setleri < 0,10 USD.
- Denetim (constitution VIII): host'ta veritabanı yoktur. Her canlı çağrı (vakalar ve `--ping`)
  geçidin `ai_call` satırı biçiminde, sırlar temizlenmiş olarak ekle-yalnız, hash zincirli deftere
  yazılır: `exports/eval-live/ai_call.jsonl` (`--ledger`; `CallLedger.verify`). Paketin çağrıları
  ayrıca raporun yanına `<rapor>.calls.jsonl` olarak yazılır ve `evaluations.yaml` kaydındaki
  `evaluation.calls` onu gösterir; "evaluated" iddiası rapor + çağrı dosyasıyla birlikte PR'a girer.
- Sert bütçe tavanı `TP_EVAL_BUDGET_USD` (varsayılan 5): her vakadan önce en kötü durum maliyeti
  eklenir, tavan aşılacaksa koşu durur. Rapor `evaluation/results/<paket>-v<n>-<tarih>.json`.
- `--record` commit'li golden'lara (`replay/**`) asla yazmaz (dizin onun içindeyse reddeder); aday
  dizininde `INDEX.json` (vaka → girdi beyanına göre hedef golden) ve `README.md` (inceleme adımları)
  bulunur. Adaylar insan incelemesinden sonra PR ile taşınır; `evaluations.yaml` değişikliği de PR
  ile gelir.
- `--ping` triage modeline `max_tokens` 16'lık tek çağrıdır; çıktı `OK …` ya da
  `HATA: <tür> (HTTP <kod>): <ileti>`; yalnızca "çalışma alanı başlığı gönderildi/gönderilmedi"
  yazılır, değerler asla.
- Anahtar API'de `400` + `anthropic-workspace-id` isterse `ANTHROPIC_WORKSPACE_ID` verilir; geçit bu
  başlığı ekler (değer loglanmaz). Ayrıntı: `docs/GERCEK-SISTEMLER.md` §1.

### Diğer kurallar

- Güvenilmeyen girdi prompt'larda yalnızca etiketli veri bloğunda taşınır; içindeki talimatlar
  uygulanmaz.
- Sağlayıcıya özgü ayrıntı bu dosyalara girmez; sağlayıcı farkları geçit adaptörlerindedir
  (constitution XII). (`models.yaml`'daki `effort`/`thinking` istisnadır; adaptör yorumlar.)
- Müşteri verisi, sır veya gerçek kişisel veri bu dizine konmaz; örnekler sentetiktir.
- `core/tests/unit/gateway/test_rules.py` her amacın prompt/şema/modelinin yüklendiğini ve golden
  kayıtların şemaya uyduğunu doğrular. `test_goldens.py` ayrıca: her amacın golden'ı olduğunu,
  kod/veri kanıtlarının demo-app kaynağıyla (dosya:satır, seed) birebir eşleştiğini, verify_and_map
  eşlemelerinin gerçek page object sembollerine ve §8.4 araç izin listesine bağlı olduğunu ve TPD-1
  case beklentilerinin demo-app fiyat fonksiyonlarıyla aynı olduğunu doğrular. `demo-app/**`
  değişikliği bu testleri koşturmalıdır. `test_consistency_flow.py` adım 2 döngüsünü replay'de
  (bulgular → fix_doc → yeniden kontrol → son hal) uçtan uca koşar.

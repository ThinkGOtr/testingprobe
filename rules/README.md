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
| `triage` | `triage` | Haiku 5.5 | çağrı | §8.6 `class`, `signals[]`, `rationale` |
| `bug_draft` | `bug-draft` | Haiku 5.5 | çağrı | §8.12 bug taslağı |
| `dup_rank` | `dup-rank` | Haiku 5.5 | çağrı | §8.12 mükerrer aday sıralaması |

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
| `replay` | `replay/<purpose>/<key>.json`; yoksa `golden/<replay_key.name>.json` (**REPLAY-MISS**); o da yoksa hata |
| `record` | `live` + başarılı çıktıyı `replay/<purpose>/<key>.json`'a yazar. Başlangıçta dizin yazılabilir mi bakılır (compose `:ro` → hata); çalışırken yazma hatası ücretli sonucu kaybettirmez, `ai_call.hata`'ya `replay_kaydedilemedi` yazılır |

`TP_REPLAY_STRICT=1` (prova kipi): replay'de golden'a düşmek yerine `ReplayMiss` hatası verir.
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
  triage/bug için senaryo adı, ör. `break-campaign`.
- TPD-1 golden'ları adım 2 sonrası **düzeltilmiş** dokümana göredir: AC2 "6 adette 1 bedava",
  AC3 "kampanyasız siparişlerde minimum 750,00 TL", AC6 korunur (kod kampanyalı sepette minimumu
  aramaz), AC4 kod hatasıdır (case `expected-code-defect`, verify_and_map'te `missing_methods`).
- verify_and_map golden'larının tarayıcı adımları çalışan Playwright MCP'ye karşı koşturulup
  kaydedilmiştir; hedefler oturumdan bağımsız `data-testid` seçicileridir (snapshot `ref`'leri
  oturumlar arasında değişir). Model çıktısı kısmı elle hazırlanmıştır.
- Ajan replay'inde kayıtlı adımlar **güncel izin listesine göre** yeniden çalıştırılır (portalda
  canlı görüntü için); listede olmayan araç replay'de de çalışmaz.
- Mevcut golden kayıtlar elle hazırlanmıştır (`note` alanı). Canlı anahtar geldiğinde
  `TP_MODEL_MODE=record` ile gerçek model çıktısıyla yenilenmelidir.

**Ajan araç izin listesi (geçitte, `ALLOWED_AGENT_TOOLS`):** `verify_and_map` yalnızca §8.4
listesi (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`,
`browser_select_option`, `browser_wait_for`, `browser_generate_locator`); `consistency_check`
yalnızca `search_code`, `get_file_contents`, `db_schema`, `db_query`. Listesi olmayan amaç ajan
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

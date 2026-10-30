# rules/

AI adımlarının kullandığı **prompt, kural ve şema dosyaları** burada düz dosya olarak versiyonlanır.
F0'da dizin boştur; dosyalar F2a'dan (model geçidi) itibaren eklenir.

## Neden ayrı bir dizin

- **Ürün opsiyonel kalabilir (constitution IX):** prompt'lar, kurallar ve şemalar üründen bağımsız
  dışa aktarılabilir; Claude Code (`CLAUDE.md`) ve GitHub Copilot
  (`.github/copilot-instructions.md`) kural dosyaları buradan üretilir.
- **Deterministik önce (constitution XI):** bir kuralın verebildiği karar modele bırakılmaz. Triage
  önce buradaki kural setiyle yapılır; model yalnızca kural eşleşmediğinde devreye girer.
- **Yapılandırılmış çıktı (constitution III):** her model çağrısının çıktısı buradaki şemaya göre
  doğrulanır; uymayan çıktı reddedilir.

## Planlanan yapı

```text
rules/
├── prompts/   # model çağrılarının prompt şablonları (ön inceleme, case üretimi, triage yorumu…)
├── schemas/   # yapılandırılmış çıktı şemaları (JSON Schema; Pydantic modelleriyle eşleşir)
├── triage/    # deterministik triage kuralları (ortam / veri / gerçek defect / flaky / locator)
└── export/    # Claude Code ve Copilot için üretilen kural dosyalarının kaynakları
```

## Kurallar

- Her değişiklik **PR ile** gelir ve review edilir; doğrudan `main`'e yazılmaz.
- Her dosya bir **kimlik ve sürüm** taşır (ör. `id: case-generation`, `version: 3`). Model geçidi,
  kullandığı kimlik/sürümü ve dosya içeriğinin hash'ini `ai_call` ve denetim kayıtlarına yazar
  (constitution VIII).
- Prompt veya kural değişikliği, değerlendirme seti canlı modelle koşturulmadan birleştirilmez
  (constitution X).
- Güvenilmeyen girdi (Jira içeriği, sayfa snapshot'ları, CI log'ları) prompt'larda yalnızca etiketli
  veri bloğunda taşınır; içindeki talimatlar uygulanmaz.
- Sağlayıcıya özgü ayrıntı bu dosyalara girmez; sağlayıcı farkları model geçidi adaptörlerindedir
  (constitution XII).
- Müşteri verisi, sır veya gerçek kişisel veri bu dizine konmaz; örnekler sentetiktir.

<!--
Sync Impact Report
- Version change: 1.1.0 → 1.2.0 (MINOR: İlke VII on-prem kurulum ve modelin müşteri ortamında
  çalışması ile genişletildi; maskeleme müşteri verisi işlenen ortamlarda zorunlu)
- Önceki: 1.0.1 → 1.1.0 (MINOR: test edilen uygulamaya salt okuma erişim kısıtları ve kanıt
  doğrulama kuralı eklendi)
- Önceki: 1.0.0 → 1.0.1 (PATCH: İlke I ve Doğruluk kaynağı maddesi iş akışı motorundan
  bağımsız ifade edildi; demo Postgres durum makinesi, ürün Temporal — kural değişmedi)
- Önceki: (template) → 1.0.0
- Modified principles: tümü şablon yer tutucularından ilk kez tanımlandı
- Added sections: Core Principles (I–XII), Güvenlik ve Mimari Kısıtlar, Geliştirme Akışı ve Kalite Kapıları, Governance
- Removed sections: yok
- Templates requiring updates: yok (şablonlar kuralı çalışma anında okur)
- Follow-up TODOs: yok
- Kaynak: docs/TEKNIK-TASARIM.md v1.0 (§3, §5, §4) ve "AI Automation Testing — Geliştirme Ekibi için Ürün Brief'i"
-->

# Testing Probe (AI Automation Testing) Constitution

## Core Principles

### I. AI Üretir, İnsan Onaylar (NON-NEGOTIABLE)
Hiçbir AI çıktısı (test case, test kodu, locator onarımı, defect taslağı) insan onayından geçmeden test
varlığına dönüşmez. Onay adımları iş akışı motorunda zorunludur ve atlanamaz. Onayın doğruluk kaynağı
Postgres'tir: core-api, oturumdaki kullanıcıyla `kullanıcı + nesne_id + içerik_hash` kaydını yazar;
iş akışı motoru (demoda Postgres durum makinesi, ürün fazında Temporal) eşleşen kayıt olmadan kapıyı
açmaz. Yayın ve PR adımları güncel içerik hash'ini
onaylanan hash ile karşılaştırır; onaydan sonra değişen içerik reddedilir.

### II. CI'da AI Yok (NON-NEGOTIABLE)
CI yalnızca onaylanmış, deterministik test kodunu koşturur. CI ortamında model anahtarı, MCP sunucusu
ve ajan bağımlılığı bulunamaz. AI yalnızca tasarım, kod üretimi ve bakım aşamalarında, yalnızca
core-worker içinde çalışır.

### III. Yapılandırılmış Çıktı
Her model çağrısı şemaya uyan yapılandırılmış çıktı üretir ve Pydantic/JSON Schema ile doğrulanır.
Şemaya uymayan çıktı reddedilir; hata mesajıyla en fazla 2 kez yeniden istenir, sonra insana düşer.
Serbest metin, kararın tek dayanağı olamaz.

### IV. Kütüphaneye Bağlı Kod
Üretilen testler yalnızca page object kütüphanesindeki mevcut metotları kullanır. Model TypeScript
yazmaz: kod, uygulamada doğrulanmış adım→page object eşlemesinden şablonla üretilir; değerler yalnızca
`JSON.stringify` ile tür doğrulanmış literal olarak basılır. Assertion değerleri onaylı case'in beklenen
sonuç metninden gelmek zorundadır. `tsc --strict` ve `eslint --no-inline-config` her PR'da zorunludur.

### V. Uygulamayı Gerçekten Gör
Kod yazılmadan önce her adım Playwright MCP ile uygulamanın eleman ağacında doğrulanır. Ekran
görüntüsünden çıkarım yapılmaz; görsel yetenekler (`--caps=vision`) ve ekran görüntüsü aracı ajana
verilmez.

### VI. Onarım Yalnızca Locator'ı Kapsar
Locator onarımı yalnızca `pages/**/locators.ts` içindeki ilgili `testId` değerini değiştirebilir.
Anahtar kümesi, rol, ad ve niyet değişmez; test dosyaları ve assertion'lar asla otomatik değişmez.
Bu kural AST korumasıyla hem çekirdekte hem CI'da zorunlu check olarak uygulanır. Beklenen sonuçtaki
her sapma defect adayıdır.

### VII. Veri Müşteride Kalır
Ürün müşteri ortamında (on-prem) çalışır; müşteri verisi müşteri ortamından çıkmaz. Ürün fazında model
de müşteri ortamında (müşterinin bulut hesabı/tenant'ı veya on-prem) çalışır. Müşteri verisi işlenen
her ortamda model geçidinde PII maskeleme zorunludur; yalnızca sentetik veriyle çalışan geliştirme ve
demo ortamında maskeleme kapalı olabilir. Müşteri verisi model eğitimi veya ince ayar için kullanılmaz.

### VIII. Her Şey Kayıt Altında
Her AI çağrısı, araç çağrısı, onay ve ret kaydedilir: model, sürüm, bundle hash'i, maskeli girdi,
çıktı, token, maliyet, kanal ve kişi. Denetim tabloları append-only'dir ve `prev_hash` zinciriyle
korunur; zincirin son hash'i Jira yorumlarına ve PR açıklamalarına sabitlenir. Replay çıktıları
`replay`/`replay_miss` olarak işaretlenir ve kullanıcıya gösterilir.

### IX. Ürün Opsiyonel Kalabilir
Prompt'lar, kural dosyaları ve şemalar `rules/` altında düz dosya olarak versiyonlanır ve üründen
bağımsız dışa aktarılabilir; Claude Code ve GitHub Copilot için kural dosyaları bunlardan üretilir.
`publish_test_cases` ve `submit_draft_cases` MCP araçları ürünsüz kanaldan da kullanılabilir.

### X. Her Çıktı Ölçülür
Her case ve script için karar, ret nedeni (sabit taksonomi), düzeltme ölçüsü ve ilk review sonucu
kaydedilir. Kabul kapıları: case kabul oranı ≥ %70, script ilk review başarısı ≥ %60. pass@1 ve
düzeltme sonrası sonuçlar ayrı raporlanır. Prompt/kural değişikliği değerlendirme setini canlı modelle
koşturmadan birleştirilmez.

### XI. Deterministik Önce
Deterministik bir kuralın verebildiği karar LLM'e bırakılmaz. Triage önce kural setiyle yapılır;
LLM yalnızca kural eşleşmediğinde devreye girer ve deterministik bir `environment` kararını ezemez.
Kimlikler (`uuid5`) ve replay anahtarları deterministiktir.

### XII. Bağımsız Ürün ve Model Bağımsızlığı
Testing Probe, Agent Probe'dan bağımsız ayrı bir üründür; ortak kod, ekran, veritabanı veya kimlik
paylaşmaz (ortak çekirdek kararı ürün sahibinin ADR'sine bırakılmıştır). Model geçidi sağlayıcıdan
bağımsız bir sözleşme sunar; sağlayıcıya özgü özellikler yalnızca adaptörlerde bulunur.

## Güvenlik ve Mimari Kısıtlar

- **Doğruluk kaynağı:** Alan verisi yalnızca PostgreSQL'dedir; iş akışı motoru (Temporal kullanıldığında)
  yalnızca kimlik ve kapı durumu taşır.
- **Güvenilmeyen girdi:** Jira/Confluence içeriği, sayfa snapshot'ları ve CI log'ları güvenilmez
  kabul edilir; prompt'larda etiketli veri bloğunda taşınır ve içindeki talimatlar uygulanmaz.
- **En az yetki:** Ajan aşama başına araç izin listesiyle çalışır; Playwright MCP yalnızca demo
  uygulaması origin'ine erişir; `browser_evaluate` ve dosya/ağ araçları kapalıdır.
- **İzolasyon:** Üretilen kod yalnızca `test-runner` servisinde çalışır (demo ağı + kontrol ağı;
  Temporal, DB, sır ve internet erişimi yok). toolchain-worker kod çalıştırmaz ve DB kimliği taşımaz.
  Model anahtarı yalnızca core-worker'dadır.
- **Etkili eylemler:** Jira'ya yazma ve PR açma yalnızca deterministik kodla, onaylı kimliklerle ve
  idempotent (`external_ref`) yapılır. Bot `main`'e push edemez ve PR merge etmez; ruleset bypass
  yalnızca insan `demo-admin` hesabındadır.
- **Tedarik zinciri:** İmajlar digest, Action'lar SHA ile sabitlenir; lockfile zorunludur;
  `npm ci --ignore-scripts`; Semgrep her PR'da koşar.
- **Ağ:** Host'a açılan tüm portlar yalnızca `127.0.0.1`; Mac'e dışarıdan gelen bağlantı yoktur.
- **Sırlar:** Sırlar git'e girmez (`.env`, Docker secrets; imza anahtarı Keychain'de).
- **Test edilen uygulamaya erişim:** Kod ve veritabanına yalnızca salt okuma; kod için read-only GitHub
  MCP ve yalnızca ilgili repoda `contents:read`; veri için izin listeli tablolar, tek `SELECT`, zaman
  ve satır sınırı, maskelenmiş sonuç. Genel amaçlı SQL çalıştıran araç kullanılmaz. AI'ın kod/veri
  kanıtına dayanan her bulgusu, gösterilmeden önce deterministik olarak yeniden doğrulanır.

## Geliştirme Akışı ve Kalite Kapıları

- Her kilometre taşı ayrı bir Spec Kit özelliğidir: specify → (clarify) → plan → tasks → (analyze)
  → implement → converge.
- Kaynak tasarım `docs/TEKNIK-TASARIM.md`'dir; tasarımla çelişen spec önce tasarım güncellenmeden
  uygulanmaz.
- `main`'e merge koşulları: CI yeşil (tsc, eslint, AST koruması, Playwright testleri, Semgrep),
  en az 1 insan onayı, CODEOWNERS (`pages/**`, `.github/**`). Zorunlu check'ler her PR'da koşar;
  atlama yerine job içinde no-op kullanılır.
- Yerel kontrol CI ile aynı mekanizmayı kullanır (checkout edilen commit, Playwright `webServer`,
  aynı toolchain imajı, tek `.playwright-version`).
- Birim testleri zorunlu alanlar: şema doğrulama, Jira eşleme, idempotency, AST koruması, PII
  maskeleme/geri açma, onay hash kontrolü, hash zinciri, şablon enjeksiyonu, beklenen değer kaynağı.
- Demo-A (story → case → onay → Jira) ≤ 7 iş günü sabittir; bu tarihi tehdit eden kapsam ertelenir.

## Governance

Bu constitution, projedeki diğer tüm pratiklerin üzerindedir. Her spec, plan ve PR bu kurallara
uyumu doğrular; ihlal gerekçelendirilmeden birleştirilmez. Değişiklikler PR ile önerilir, gerekçesi
ve etkisi yazılır ve teknik lider ile ürün sahibi tarafından onaylanır. Sürümleme semantiktir: ilke
kaldırma veya yeniden tanımlama MAJOR, yeni ilke veya bölüm MINOR, açıklama ve ifade düzeltmeleri
PATCH. Çalışma zamanı rehberi için `docs/TEKNIK-TASARIM.md` ve `CLAUDE.md` kullanılır.

**Version**: 1.2.0 | **Ratified**: 2026-10-30 | **Last Amended**: 2026-10-30

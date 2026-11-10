<!--
Sync Impact Report
- Version change: 2.0.0 → 2.0.1 (PATCH: İlke VII'deki kimlik servisi cümlesi koda uygun hale
  getirildi — giden alanlar tam listelendi (`uid`, `auth_time`, `acr`, `session_epoch_ms`) ve
  bağlama API'sinin rol hesaplarının `kullanici_adi`/`ad_soyad`/`rol`'ünü yalnız aiprobe-home
  yöneticilerine açtığı yazıldı. Kural değişmedi — alan verisi gitmez — yalnız ifade
  kesinleştirildi; 2.0.0 onaylandıktan sonraki metin değişikliği olduğu için ayrı PATCH sürümü)
- Modified principles: VII. Veri Müşteride Kalır (ifade düzeltmesi)
- Added sections: yok · Removed sections: yok
- Templates requiring updates: yok ✅; bağlı belgeler docs/adr/0001-aiprobe-ortak-kimligi.md
  (Karar 4–5) ve specs/010-aiprobe-sso/spec.md aynı dalda güncellendi ✅
- Onay durumu: 2.0.0 onayı (2026-11-10) geçerli; 2.0.1 PATCH teknik lider + ürün sahibi onayı ⏳
  (Governance), onaycı isimleri F0 notuna işlenecek
- Follow-up TODOs: 2.0.1 onayı; onaycı isimlerinin F0 notuna işlenmesi
- Önceki: 1.3.0 → 2.0.0 (MAJOR: İlke XII yeniden tanımlandı — TP, Agent Probe ile kod,
  ekran ve veritabanı paylaşmamaya devam eder; ortak AI Probe kimliğine YALNIZCA belgelenmiş HTTP
  kimlik API'si (giriş devri + oturum kontrolü) üzerinden bağlanabilir; Firebase SDK'sı TP'ye
  girmez. İlke VII'ye on-prem kimlik kuralı eklendi: `TP_AUTH_MODE=local` varsayılan, dış kimlik
  servisine çağrı yok)
- Modified principles: VII. Veri Müşteride Kalır (genişletildi), XII. Bağımsız Ürün ve Model
  Bağımsızlığı → "XII. Bağımsız Ürün, Sözleşmeli Kimlik ve Model Bağımsızlığı" (yeniden tanım)
- Added sections: yok · Removed sections: yok
- Güvenlik ve Mimari Kısıtlar: "Kimlik" maddesi eklendi
- Templates requiring updates: yok (şablonlar kuralı çalışma anında okur) ✅; bağlı belgeler
  docs/TEKNIK-TASARIM.md v1.7 (§3 tablo satırı 12, §8.10, §9, §14) ve docs/MIMARI-SOZLESME.md
  (§5 uçlar, §6 ortam değişkenleri) aynı dalda güncellendi ✅
- Onay durumu: teknik lider ✅ + ürün sahibi ✅ + KVKK sorumlusu ✅ — onaylandı (2026-11-10),
  onaycı isimleri F0 notuna işlenecek (Governance)
- Follow-up TODOs: onaycı isimlerinin F0 notuna işlenmesi
- Kaynak: docs/adr/0001-aiprobe-ortak-kimligi.md; aiprobe-platform-plan/PLAN.md §2.3, §4.2;
  specs/010-aiprobe-sso/
- Önceki: 1.2.0 → 1.3.0 (MINOR: İlke II, portal içi salt okuma bilgi ve yönlendirme
  asistanını AI'ın çalışabileceği dördüncü alan olarak ekledi — eylem yok, çıktısı karar dayanağı
  değildir, model yalnızca core-worker'da; ürün sahibi kararı K7, 2026-11-03)
- Modified principles: II. CI'da AI Yok (genişletildi; mevcut kural değişmedi)
- Added sections: yok · Removed sections: yok
- Templates requiring updates: yok (şablonlar kuralı çalışma anında okur); bağlı belgeler
  docs/TEKNIK-TASARIM.md §8.13 ve docs/MIMARI-SOZLESME.md §5–§6 aynı PR'da güncellendi ✅
- Onay durumu: ürün sahibi ✅ 2026-11-03 (K7); teknik lider ⏳ açık (tasks T007; onay tarihi buraya
  işlenir). Governance iki onayı da istediğinden v1.3.0 onaya dek yalnız `dev`'de, asistan bayrak
  arkasında (`TP_ASISTAN_MODEL_MODE=off`) geçerlidir; teknik lider onayı `main` birleştirme koşuludur
  ve PR açıklamasında öyle yazılır (docs/AI-ASISTAN-PLANI.md §14 kontrol listesi)
- Follow-up TODOs: teknik lider onayı (değişiklik dosyası aynı PR'da; Governance)
- Kaynak: docs/AI-ASISTAN-PLANI.md v6 §1 K7, §4; specs/008-ai-asistan/
- Önceki: 1.1.0 → 1.2.0 (MINOR: İlke VII on-prem kurulum ve modelin müşteri ortamında
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
ve ajan bağımlılığı bulunamaz. AI yalnızca tasarım, kod üretimi ve bakım aşamalarında ve portal
içi asistanda, yalnızca core-worker içinde çalışır. Portal asistanı **salt okuma bilgi ve
yönlendirme asistanıdır**: eylem yapmaz (yazma aracı, onay, yayın, Jira kaydı/yorumu yoktur; eylem
isteğine yalnızca ilgili ekrana bağlantı ve kullanıcının kendisinin uygulayacağı taslakla cevap
verir), çıktısı **karar dayanağı değildir** ve hiçbir karar alanına, onay kaydına veya başka bir AI
adımına girdi olmaz. core-api model anahtarını ve model kipini bilmez.

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
On-prem kurulum kendi kimliğiyle çalışır: `TP_AUTH_MODE=local` varsayılandır ve bu kipte hiçbir dış
kimlik servisine çağrı yapılmaz. Ortak kimlik (`aiprobe`/`both`) yalnızca Antrek'in barındırdığı
ortamda açılır; kimlik servisine yalnızca oturum kimliği gider — `uid`, `auth_time`, `acr`,
`session_epoch_ms` (ve girişte tek kullanımlık devir kodu) — alan verisi gitmez. Ters yönde bağlama
API'si rol hesaplarının `kullanici_adi`, `ad_soyad` ve `rol`'ünü yalnızca `aiprobe-home` servis
kimliğine, dolayısıyla yalnızca aiprobe-home yöneticilerine açar.

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

### XII. Bağımsız Ürün, Sözleşmeli Kimlik ve Model Bağımsızlığı
Testing Probe, Agent Probe'dan bağımsız ayrı bir üründür; Agent Probe ile ortak kod, ekran veya
veritabanı paylaşmaz. Ortak AI Probe kimliğine **yalnızca belgelenmiş HTTP kimlik API'si** (giriş
devri kodunun takası ve oturum kontrolü; ADR-0001) üzerinden bağlanabilir: çağrılar TP kodunda, TP
sahipliğinde yazılır; Firebase SDK'sı (istemci veya Admin) ve platformun ya da Agent Probe'un kodu
TP'ye girmez. TP'nin yetki modeli değişmez: dış kimlik yalnızca TP rol hesaplarına (`kimlik_bagi`)
bağlanır, yetki kararları `app_user.rol` ile verilir. Model geçidi sağlayıcıdan bağımsız bir
sözleşme sunar; sağlayıcıya özgü özellikler yalnızca adaptörlerde bulunur.

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
- **Kimlik:** Yerel kipte argon2 + sunucu tarafı oturum. Ortak kimlik kipinde dış kimlik yalnızca
  sunucudan sunucuya, imzalı servis kimliğiyle doğrulanan çağrılarla gelir; tarayıcıdan gelen
  hiçbir kimlik iddiasına (token, e-posta, rol) güvenilmez. Oturum ve `tpt_` token'ları dış iptali
  en geç 60 sn içinde izler; kimlik servisi erişilemezse açık oturum süre sınırları içinde korunur,
  yeni giriş açılmaz.
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

**Version**: 2.0.1 | **Ratified**: 2026-10-30 | **Last Amended**: 2026-11-10

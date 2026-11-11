# 011 — Üretim dili boyutu (ts | java | csharp | python)

Kaynak: kullanıcı geri bildirimi (2026-11-09, "Kod üretiminde dil seçimi dinamik olabilir") ve
2026-11-11 ürün sahibi kararları. Taban dal: `feat/hakan-geri-bildirim`; birleştirme dalı
`feat/uretim-dili`.

## 1. Kararlar (ürün sahibi, 2026-11-11)

| # | Karar |
|---|---|
| K1 | Üretim dili ayrı bir boyuttur; platformdan türetilmez. Varsayılan, hedef repodaki mevcut testlerden **otomatik algılanır**; kullanıcı Kod üretimi ekranında o üretim için **değiştirebilir**. |
| K2 | Web için Java hattı **Playwright for Java + TestNG**'dir ve **tam hattır**: pom kilidi, AST koruması, derleme, koşu, kırarak doğrulama, sınıflandırma, CI. |
| K3 | C# (Playwright .NET + NUnit) ve Python (pytest-playwright) için kod **üretilir** ama derlenmez/koşulmaz: **"doğrulanmamış"** etiketiyle çıkar; PR açılmaz, merge edilemez. |
| K4 | Canlı model çağrıları (kayıt + değerlendirme) 10 USD tavanla onaylıdır; tavanı yalnız ana oturum harcar, şerit ajanları **canlı model çağrısı yapmaz**. |

## 2. Sözleşmeler (şeritler arası; değiştirmek isteyen şerit raporunda gerekçesiyle yazar)

### 2.1 Dil ve geçerli çiftler
- `Dil = "ts" | "java" | "csharp" | "python"`. Tek kaynak: `core/src/tp_core/features/codegen/platform.py`
  (`DILLER`, `TAM_HAT_DILLERI = ("ts","java")`, `DOGRULANMAMIS_DILLER = ("csharp","python")`).
- Geçerli (platform, dil): `web` × herhangi bir dil; `android|ios|windows` × yalnız `java`.
  Geçersiz çift API'de 422 (Türkçe ileti).
- Varsayılan (algılama yoksa / eski kayıt): `web → ts`, uygulama → `java` (bugünkü davranış; geriye uyum).
- "Platform = dil" çıkarımı yapan **her** dal (`uygulama_mi`, `!= "web"`, `PLATFORM_LANG`, …) iki ayrı
  soruya ayrılır: **araç/ortam** sorusu platforma (`web` → Playwright MCP, tarayıcı; uygulama → app-mcp,
  Appium), **kod/derleme/yama** sorusu dile bakar. Yardımcılar `platform.py`'de:
  `java_mi(dil)`, `tam_hat_mi(dil)`, `gecerli_cift(platform, dil)`, `varsayilan_dil(platform)`.

### 2.2 Veri modeli
- Migration `0021_script_dil.py`: `script.dil TEXT NOT NULL DEFAULT 'ts'` + CHECK (`script_dil_ck`),
  backfill `CASE WHEN platform='web' THEN 'ts' ELSE 'java' END`; `script.dil_kaynagi TEXT NOT NULL
  DEFAULT 'varsayilan'` CHECK in (`algilandi`,`secildi`,`varsayilan`).
- `script_codegen.kaynak_kod TEXT NULL`: yalnız doğrulanmamış dillerde render edilen kaynak (forge'a
  commit edilmez).
- Etkin script anahtarı **(case, platform)** olarak kalır: aynı case+platform için tek etkin script;
  dil değiştirmek = yeniden üretmek. (Sınıf/dosya adı çakışması ve çift PR olmaz.)
- SCRIPT durum makinesine uç durum **`unverified`** eklenir: `verifying → unverified`,
  `unverified → pending` (başka dilde / yeniden üret), `unverified → closed`. Onay kapısı yok,
  `merged`'e geçiş yok. Sözleşme JSON'u (`review-portal/src/api/sozlesme/durum-makineleri.json`)
  `npm run sozlesme:durumlar` ile yeniden üretilir.

### 2.3 Core API
- `POST /code/generate` gövdesi: `{case_ids, platform="web", dil: Dil | null = null}`. `dil` yoksa
  algılanan dil kullanılır (`dil_kaynagi="algilandi"`, algılama sonuçsuzsa `varsayilan`); varsa
  `dil_kaynagi="secildi"`.
- `GET /code/languages?platform=<p>` →
  ```json
  {"platform":"web","algilanan":"ts","kaynak":"algilandi|varsayilan",
   "sayilar":{"ts":9,"java":4,"csharp":0,"python":0},
   "secenekler":[
     {"dil":"ts","etiket":"TypeScript","cati":"Playwright Test","hat":"tam","kullanilabilir":true,"neden":null},
     {"dil":"java","etiket":"Java","cati":"Playwright for Java + TestNG","hat":"tam","kullanilabilir":true,"neden":null},
     {"dil":"csharp","etiket":"C#","cati":"Playwright .NET + NUnit","hat":"dogrulanmamis","kullanilabilir":true,"neden":null},
     {"dil":"python","etiket":"Python","cati":"pytest-playwright","hat":"dogrulanmamis","kullanilabilir":true,"neden":null}]}
  ```
  Uygulama platformlarında tek seçenek `java` (çatı "Appium + TestNG"). Tam hat dili, repoda o dilin
  test projesi yoksa `kullanilabilir=false` + Türkçe `neden` (ör. "Depoda Java web test projesi
  (e2e-java/pom.xml) yok").
- Script serileştirmesi (`views.serialize`) ek alanlar: `dil`, `dil_kaynagi`, `dogrulanmamis: bool`
  (`durum == "unverified"`), doğrulanmamışta `kod` = `kaynak_kod`. `_yerel_kontrol` dile göre adım
  listesi döndürür (ts: tsc/eslint/ast_guard; java: deps/guard/compile) — alan adı `adimlar: [{ad,
  durum}]` eklenir, eski `tsc/eslint/ast_guard` alanları korunur.
- Denetim ve SSE yüklerine `dil` eklenir (`codegen.requested` vb.).

### 2.4 Dil algılama
- `core/src/tp_core/features/codegen/dil_algila.py`: `algila(forge, ref, platform) -> Algilama{dil,
  kaynak, sayilar}`. Saf sayım, model yok. Web için uygulama kökü altında **elle yazılmış** (üretilen
  dizinler hariç) test dosyaları sayılır: ts `<e2e>/tests/**/*.spec.ts` (generated hariç); java
  `<e2e-java>/src/test/java/**/*Test.java` (`uretilen/` ve `birim/` hariç); csharp `**/*Tests.cs` |
  `**/*Test.cs` (bir `*.csproj` varsa); python `**/test_*.py` | `**/*_test.py`. En çok dosyası olan
  dil; eşitlikte öncelik `ts > java > csharp > python`; hiç yoksa `varsayilan`.
- Sonuç `(ref sha, platform)` ile önbelleklenir; forge hatasında `varsayilan` (üretimi engellemez).

### 2.5 Web + Java hedef proje: `demo-app/e2e-java`
- Maven projesi, Java 17, **Playwright for Java** (sürüm depo kökündeki `.playwright-version` ile aynı
  tarayıcı derlemelerini kullanan sürüm; eşitlik bir testle sabitlenir), TestNG, Allure, Extent
  (e2e-app'teki `ExtentRaporu` dinleyicisiyle aynı davranış).
- Paket ve konvansiyon `e2e-app` ile **aynı** (java-araclar değişmeden çalışsın):
  `com.antreklabs.bayi.{altyapi,ekranlar,testler,uretilen,birim}`; `ekranlar/Ekran` taban sınıfı,
  `ekranlar/Kimlikler` (testId sabitleri, saf veri), `altyapi/TestTabani`, `altyapi/Bayiler`.
- **Page object eşitliği:** `ekranlar/` sınıf adları, public metot adları, parametre adları ve sırası
  TS `demo-app/e2e/pages` sembol tablosuyla **birebir** (ör. `LoginPage.login(username, password)`,
  `CatalogPage.addToCart(productCode, quantity)`); tür eşlemesi `string→String`, `number→int|double`,
  `boolean→boolean`. Fikstür adları TS `interface Fixtures` ile aynı. Böylece `verify_and_map`
  REPLAY golden'ları dilden bağımsız kalır. Eşitlik bir testle sabitlenir (TS sembol tablosu ↔ Java
  sembol tablosu).
- Üretilen testler: `src/test/java/com/antreklabs/bayi/uretilen/<Sinif>Test.java`, TestNG grupları
  `[uretilen, web, tp-case-<uuid>]`.
- Kanıt: başarısız testte `target/kanit/<Sinif>.<metot>/{ekran.png, trace.zip, sayfa.html}`.
- Ortam: `BASE_URL`, `API_URL`, `DEMOAPP_TEST_TOKEN` (TS e2e ile aynı adlar); tarayıcı
  `PLAYWRIGHT_BROWSERS_PATH` üzerinden, test sırasında indirme yok.
- Betikler: `demo-app/ci/run-java-checks.sh` (pom kilidi → guard → derleme → koşu),
  `demo-app/ci/break-verify-java.sh`; GitHub iş akışı `.github/workflows/web-java.yml`.

### 2.6 Toolchain
- Ayar `TP_E2E_JAVA_ROOT` (varsayılan `e2e-java`), güvenilir pom `toolchain/e2e-java-deps/pom.xml`
  (hedef pom ile bayt eşit), imajda ısıtılmış ikinci Maven deposu.
- Worker `/symbols` ve `/check`: `lang="java"` + `platform="web"` (ya da platform yok) **kabul
  edilir** ve kök `TP_E2E_JAVA_ROOT`'tur; `lang="java"` + uygulama platformu bugünkü gibi
  `TP_E2E_APP_ROOT`. Java web adımları: `app → deps → guard → compile → run` (uygulama Java ile aynı
  adlar). Rapor `lang:"java"`, `platform:"web"` taşır.
- **Check adı:** web'de dil ne olursa olsun `local-ci` (platformun check'i); uygulamada
  `local-ci-<platform>` (değişmez).
- Runner: `lang="java"`, `platform="web"` → Appium sağlık kontrolü yok; API + web origin sağlık
  kontrolü, `repeat_each` desteklenir (web varsayılanı 3), tarayıcı imajdaki `/ms-playwright`.
- `lang` değerleri yalnız `ts|java`; `csharp|python` toolchain'e **hiç gitmez**.

### 2.7 Codegen akışı
- Ajan ve amaç platforma bağlıdır: web → `verify_and_map` + Playwright MCP (dil ne olursa olsun);
  uygulama → `verify_and_map_app`. REPLAY anahtarı değişmez (web'de dil anahtara girmez; PO
  eşitliği §2.5 bunu güvenli kılar).
- Sembol tablosu **hedef dilin** projesinden alınır (ts → TS tablosu; java → e2e-java tablosu).
  Doğrulanmamış dillerde tablo, repodaki tam hat dilinden (önce ts, yoksa java) alınır
  ("referans tablo").
- Render tek giriş noktası: `render.render_dil(inp, *, dil, platform, rules) -> Rendered`
  (`repo_path`, `kaynak`, `sinif_adi|test_adi`). Şablonlar: `playwright_test.ts.j2` (mevcut),
  `appium_testng.java.j2` (mevcut, uygulama), `playwright_testng.java.j2` (web Java),
  `playwright_nunit.cs.j2`, `pytest_playwright.py.j2`. Literal süzgeçleri: `ts_literal`,
  `java_literal`, `cs_literal`, `py_literal` (hepsi enjeksiyona kapalı; model kod yazmaz ilkesi
  aynen). C#'ta metot adları PascalCase, Python'da snake_case türetilir.
- Tam hat (ts, java): bugünkü sıra (render → commit → yerel kontrol → PR → kırarak doğrula → merge).
  Web tekrar sayısı dile bakmaz (3).
- Doğrulanmamış (csharp, python): doğrulama ajanı adımları tarayıcıda **yine doğrular**; render
  sonrası kaynak `script_codegen.kaynak_kod`'a yazılır, **commit/PR/yerel kontrol yok**, durum
  `unverified`. Portalda kod görüntülenir ve indirilebilir.

### 2.8 CI, forge, triage, onarım
- PR koşusu (`enqueue_ci`) script'in diline göre `/check` gövdesi kurar: web+ts `{}` (bugünkü),
  web+java `{lang:"java", platform:"web"}`.
- Paket koşuları (gece/push/deploy): web için repoda hangi tam hat dillerinin testi varsa hepsi
  koşar; koşu kaydı dili taşır (`run.ortam.dil` ya da eşdeğeri) ve portalda görünür.
- Forge zorunlu check kuralı: yalnız `e2e-java/` (ya da `e2e/`) değişen PR'da `local-ci` gerekir;
  GitHub kipinde web+java için zorunlu check `web-java`.
- Triage: Java mı sorusu **dile/rapora** bakar (`platform=="web"` kısa devresi kalkar). Playwright
  Java kalıpları: `com.microsoft.playwright.TimeoutError` / "waiting for locator" → locator;
  `AssertionFailedError` / `AssertionError` → assertion (ürün hatası adayı); bağlantı hataları →
  ortam. Kanıt web yöntemiyle (trace / sayfa.html), kimlik eşleme `Kimlikler.java` üzerinden.
- Locator onarımı web+java: aday bulma **web yöntemi** (DOM/aria), yama **Java yöntemi**
  (`Kimlikler.java`, `java-araclar locators patch`).

### 2.9 Portal
- `lib/dil.ts`: `DILLER`, `DIL_ETIKETI`, `DIL_CATISI(platform, dil)`, `dogrulanmamisDilMi`.
- Kod üretimi: platform seçicinin yanında **dil seçici**; `GET /code/languages` ile dolar, algılanan
  dil seçili gelir ("repodan algılandı" notu), kullanıcı değiştirince "elle seçildi". Kullanılamayan
  seçenek pasif ve nedeni görünür. Doğrulanmamış dil seçilince üretimden önce açık uyarı.
- Listeler ve script detayı: dil rozeti; doğrulanmamışta kalıcı uyarı bandı + "Kodu indir"; PR /
  kırarak doğrula / merge kartları yerine "bu dilde yok" açıklaması. Java web'de kontrol adımları
  (deps/guard/compile) görünür.
- `lib/vurgula.ts`: `java` ve `csharp` sözdizimi; dil dosya uzantısından (`.java`, `.cs`, `.py`).
- Mock (`api/mock`): dil boyutu, `GET /code/languages`, web+java ve doğrulanmamış örnek scriptler.

## 3. Şeritler

| Şerit | Sahip olduğu yollar |
|---|---|
| Ş1 core-akış | `core/src/tp_core/{models,workflow}`, `core/alembic`, `features/codegen/**` (render.py hariç), `rules/prompts|schemas|replay|evaluations.yaml`, ilgili testler |
| Ş2 render | `features/codegen/render.py`, `rules/templates/**`, `features/codegen/checks.py` tür eşlemesi, şablon golden'ları ve testleri |
| Ş3 toolchain | `toolchain/**`, `docker-compose.yml` toolchain ayarları |
| Ş4 hedef-repo | `demo-app/e2e-java/**`, `demo-app/ci/*java*`, `.github/workflows/web-java.yml`, `.github/CI.md` |
| Ş5 ci-triage | `core/src/tp_core/features/{ci,triage,repair}/**`, `integrations/forge*.py`, ilgili testler |
| Ş6 portal | `review-portal/**` |

Ortak dosyaya dokunmak gereken şerit, değişikliği en küçük tutar ve raporunda belirtir. `Script.dil`
alanı ve `platform.py` yardımcıları Ş1'indir; diğer şeritler §2.1–2.2'deki adlara göre kod yazar
(kendi worktree'lerinde derlenmesi için aynı adlarla **asgari** tanımı ekleyebilir; birleştirmede
Ş1'in sürümü kazanır).

## 4. Anayasa notu
Anayasa IV/V/VI metni TypeScript/Playwright diliyle yazılmıştır. Bu çalışma ilkeleri değiştirmez:
model hiçbir dilde kod yazmaz (deterministik render), tam hat dillerinde derleme + koruma + koşu
PR'da zorunludur, doğrulanmamış diller **PR'a ve merge'e giremez**. Metnin dilden bağımsız hale
getirilmesi birleştirme sonrası doküman şeridinde yapılır.

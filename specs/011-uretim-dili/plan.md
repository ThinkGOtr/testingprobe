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

**İnceleme turu 1 kararları (K-T1..K-T9, bağlayıcı; ayrıntı `inceleme-tur1.md`)** aşağıdaki
sözleşmelere işlendi: K-T1 check adı (§2.6, §2.8), K-T2 push koşusu (§2.8), K-T3 GitHub kapısı
(§2.3, §2.8), K-T4 doğrulanmamış ↔ etkin script (§2.2, §2.7), K-T5 ajan tablosu (§2.7), K-T6
doğrulanmamış çıktı yolu (§2.7), K-T7 Java test dosyası kalıbı (§2.4), K-T8 rol kısıtı (§2.9), K-T9
ertelenenler (§5).

**İnceleme turu 2 kararları (K-T10..K-T12, bağlayıcı; ayrıntı `inceleme-tur2.md`):** K-T10 GitHub
`web-java` check'i her zaman zorunlu (§2.3, §2.8, §6), K-T11 script'siz PR'da test kökleri dışı
değişiklik → tüm tam hat dilleri (§2.8), K-T12 başka dilde merge edilmiş testin kaldırılması ürün
akışı değil, 409 çıkış yolu + toplu yanıtta çakışma sayısı (§2.3, §2.7, §5).

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
- **K-T4:** `unverified` kayıt **etkin script sayılmaz**. Doğrulanmamış üretim aynı case+platformun
  `pr_open`/`merged`/devam eden script'ine DOKUNMAZ (kapatma yok, forge'a yazma yok); eski
  `unverified` kayıtlar yenisi gelince `closed`. Tam hat dilinde istek, aynı case+platformda **başka
  dilde merge edilmiş** script varsa **409** ("Bu case'in web testi TypeScript ile merge edildi; dil
  değiştirmek için önce mevcut testi kaldırın"). `_eski_prlari_kapat` yalnız tam hat yolunda.
- DB'de (platform, dil) çift CHECK'i yoktur (MİM-L4: göç penceresinde eski core'un yazdığı satırlar;
  dağıtım runbook'u backfill yapar: `docs/GCP-KURULUM.md` "011 dağıtım sırası").
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
  {"platform":"web","algilanan":"ts","kaynak":"algilandi|varsayilan","neden":null,
   "sayilar":{"ts":9,"java":4,"csharp":0,"python":0},
   "secenekler":[
     {"dil":"ts","etiket":"TypeScript","cati":"Playwright Test","hat":"tam","kullanilabilir":true,"neden":null},
     {"dil":"java","etiket":"Java","cati":"Playwright for Java + TestNG","hat":"tam","kullanilabilir":true,"neden":null},
     {"dil":"csharp","etiket":"C#","cati":"Playwright .NET + NUnit","hat":"dogrulanmamis","kullanilabilir":true,"neden":null},
     {"dil":"python","etiket":"Python","cati":"pytest-playwright","hat":"dogrulanmamis","kullanilabilir":true,"neden":null}]}
  ```
  Uygulama platformlarında tek seçenek `java` (çatı "Appium + TestNG"). Tam hat dili, repoda o dilin
  test projesi yoksa `kullanilabilir=false` + Türkçe `neden` (ör. "Depoda Java web test projesi
  (e2e-java/pom.xml) yok"). Üst düzey `neden`: algılama yapılamadıysa (depo okunamadı vb.; `kaynak`
  `varsayilan`) Türkçe açıklama ("Dil algılanamadı (…); varsayılan dil önerildi"), yapıldıysa `null`.
  Portal bu durumda "algılandı" demez, nedeni gösterir (MİM-B1 tur 2).
- **K-T12:** Tam hat dilinde istek, aynı case+platformda başka dilde `merged` script varken 409; mesaj
  çıkış yolunu söyler ("mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin").
  Toplu istekte çakışan case sayısı yanıt mesajına yansır ve portal Kod üretimi'nde çakışmaları ve
  nedenlerini gösterir. Kaldırma ürün akışı değildir (backlog); elle adım `docs/GCP-KURULUM.md` §10.2.
- **K-T3 (GitHub kipi):** web + Java üretimi ve Java kardeş koşusu yalnız `java ∈ TP_WEB_DILLERI`
  iken; değilse `/code/languages` Java'yı `kullanilabilir=false` + neden döner. LocalForge'da repodaki
  dosyalar belirler. GitHub kipinde algılama core-api'de `GITHUB_READ_TOKEN`'a bağlıdır.
- **K-T8:** `GET /code/languages` yalnız `engineer|presenter`. `head_sha` 60 sn önbelleklenir,
  başarısız algılama kısa süre önbelleklenir (GÜV-D2).
- Script serileştirmesi (`views.serialize`) ek alanlar: `dil`, `dil_kaynagi`, `dogrulanmamis: bool`
  (`durum == "unverified"`), doğrulanmamışta `kod` = `kaynak_kod`. `_yerel_kontrol` dile göre adım
  listesi döndürür (ts: tsc/eslint/ast_guard; java: deps/guard/compile) — alan adı `adimlar: [{ad,
  durum}]` eklenir, eski `tsc/eslint/ast_guard` alanları korunur.
- Denetim ve SSE yüklerine `dil` eklenir (`codegen.requested` vb.).

### 2.4 Dil algılama
- `core/src/tp_core/features/codegen/dil_algila.py`: `algila(forge, ref, platform) -> Algilama{dil,
  kaynak, sayilar}`. Saf sayım, model yok. Web için uygulama kökü altında **elle yazılmış** (üretilen
  dizinler hariç) test dosyaları sayılır: ts `<e2e>/tests/**/*.spec.ts` (generated hariç); java
  (**K-T7**, tek sabit `platform.py`, `dil_algila` ve `ci/dil` aynı sabiti kullanır)
  `*Test.java | *Testi.java | *Tests.java | *IT.java` (`uretilen/` ve `birim/` hariç; algılama
  sinyali olarak `*Test.kt` de sayılır); csharp `**/*Tests.cs` | `**/*Test.cs` (bir `*.csproj`
  varsa); python `**/test_*.py` | `**/*_test.py` (kök işaretleri yalnız Playwright kullanımı
  gösteriyorsa). Okuma bütçesi dil başınadır; test adı taşıyan dizinler önce okunur. e2e-app /
  e2e-java dosyaları C#/Python sayımına girmez. Sonuç mesajı nereye bakıldığını söyler. En çok dosyası olan
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
- Raporlar (tur 1, D5): Extent test adı = TestNG description, `tp-case-*` kategori süzülür, Extent
  arşivi yalnız tekrar kipinde geri yüklenir; Allure etiketleri `story`, `tp-case`, `tag`
  TestTabani'ndan. Surefire `argLine -Xmx512m -Dfile.encoding=UTF-8` (pom değişince güvenilir pom bayt eşit).
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
- **Check adı (K-T1):** web + TS `local-ci` (değişmez); **web + Java `local-ci-web-java`** (GitHub
  karşılığı `web-java` ile aynı mantık); uygulamada `local-ci-<platform>` (değişmez). Tek kaynak
  `platform.check_adi(platform, dil)`; core, toolchain worker (`check_name`) ve portal bunu
  kullanır/aynalar. (İlk taslaktaki "web'de dil ne olursa olsun `local-ci`" kararı, kardeş koşuların
  aynı sha'ya aynı adla yazıp birbirini ezmesi nedeniyle bırakıldı — MİM-Y3.)
- Runner: `lang="java"`, `platform="web"` → Appium sağlık kontrolü yok; API + web origin sağlık
  kontrolü, `repeat_each` desteklenir (web varsayılanı 3), tarayıcı imajdaki `/ms-playwright`.
- `lang` değerleri yalnız `ts|java`; `csharp|python` toolchain'e **hiç gitmez**.

### 2.7 Codegen akışı
- Ajan ve amaç platforma bağlıdır: web → `verify_and_map` + Playwright MCP (dil ne olursa olsun);
  uygulama → `verify_and_map_app`. REPLAY anahtarı değişmez (web'de dil anahtara girmez; PO
  eşitliği §2.5 bunu güvenli kılar).
- Sembol tablosu **hedef dilin** projesinden alınır (ts → TS tablosu; java → e2e-java tablosu).
  Doğrulanmamış dillerde tablo, repodaki tam hat dilinden (önce ts, yoksa java) alınır
  ("referans tablo"; render başlığı ve denetim `referans_dil`'i aynı kaynaktan yazar).
- **K-T5 (ajan tablosu):** web'de doğrulama ajanına (canlı kip) repoda TS projesi varsa **TS sembol
  tablosu** verilir (PO eşitliği §2.5); Java tablosu deterministik denetim + render içindir. Repoda
  yalnız e2e-java varsa Java tablosu verilir ve audit'e `ajan_tablosu: java` yazılır. Prompt
  değişmez (değerlendirme kapısı etkilenmez).
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
  `unverified`. Portalda kod görüntülenir ve indirilebilir. Etkin script kuralı: §2.2 K-T4.
- **K-T6 (yol):** tek kaynak render: `Rendered.repo_path` doğrulanmamış dillerde
  `<e2e-csharp kökü>/tests/Generated/<Story>WebC<n>_<u8>Tests.cs` (C# metotları `…Async`) · `<e2e-python kökü>/tests/generated/test_<slug>.py`; `baslangic_dosya_yolu` aynı fonksiyonu çağırır (portal
  ve indirme aynı yolu gösterir). Başlık "Elle düzenlemeyin" demez; gereken PO sınıf/metot
  imzalarını listeler; Python'da marker kaydı için `conftest.py` parçası başlıktadır (K-T9 küçük kısım).

### 2.8 CI, forge, triage, onarım
- PR koşusu (`enqueue_ci`) script'in diline göre `/check` gövdesi kurar: web+ts `{}` (bugünkü),
  web+java `{lang:"java", platform:"web"}`.
- Paket koşuları (gece/push/deploy): web için repoda hangi tam hat dillerinin testi varsa hepsi
  koşar; koşu kaydı dili `run.ortam.dil`'de taşır ve portalda görünür. **K-T2:** merge sonrası push
  da paket koşusudur: repodaki tüm tam hat dilleri koşar (script'li push'a da kardeş dağıtımı
  uygulanır).
- Forge zorunlu check kuralı (K-T1): `e2e-java/` değişen PR `local-ci-web-java`, `e2e/` değişen PR
  `local-ci` ister. Script'siz PR CI'ı değişen yollardan dil(ler)i seçer (ikisi de değiştiyse ikisi de
  koşar). **K-T11:** script'siz PR'da web test köklerinin (`e2e/`, `e2e-java/`) **dışında** bir
  değişiklik (uygulama kodu vb.) varsa repodaki **tüm** tam hat dilleri koşar (LocalForge ve GitHub
  tutarlı); merge kapısı aynı kuralla (`local-ci` + varsa `local-ci-web-java`). Kardeş dağıtımı
  `run.ortam.dil_dagitimi`'na yazılır (idempotency; MIMARI-SOZLESME). **K-T10:** GitHub kipinde
  `web-java` check'i `web-java.yml` depoda olduğu sürece **her zaman zorunlu** (iş akışı `changes` +
  no-op ile ilgisiz PR'da hızla yeşil); `TP_WEB_DILLERI` yalnız Java üretimini ve kardeş koşuyu açar
  (K-T3). ci.yml `test-local` yalnız-Java PR'da no-op (OPS-L2). `TP_REQUIRED_CHECKS`'e dil/platform
  check'i yazılmaz (her PR'da zorunlu olur).
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
- Mock (`api/mock`): dil boyutu, `GET /code/languages`, web+java ve doğrulanmamış örnek scriptler
  (gerçek şablon çıktısıyla aynı kod ve yollar).
- **K-T8:** Kod üretimi/Koşular ekranlarındaki rol kısıtı **arayüz düzenidir, yetki sınırı değil**
  (yetki API'dedir: `/code/generate` engineer); belgelenir.

## 3. Şeritler

| Şerit | Sahip olduğu yollar |
|---|---|
| Ş1 core-akış | `core/src/tp_core/{models,workflow}`, `core/alembic`, `features/codegen/**` (render.py hariç), `rules/prompts|schemas|replay|evaluations.yaml`, ilgili testler |
| Ş2 render | `features/codegen/render.py`, `rules/templates/**`, `features/codegen/checks.py` tür eşlemesi, şablon golden'ları ve testleri |
| Ş3 toolchain | `toolchain/**`, `docker-compose.yml` toolchain ayarları |
| Ş4 hedef-repo | `demo-app/e2e-java/**`, `demo-app/ci/{run-java-checks,break-verify-java}.sh`, `.github/workflows/web-java.yml`, `.github/CI.md` |
| Ş5 ci-triage | `core/src/tp_core/features/{ci,triage,repair}/**`, `integrations/forge*.py`, ilgili testler |
| Ş6 portal | `review-portal/**` |

Ortak dosyaya dokunmak gereken şerit, değişikliği en küçük tutar ve raporunda belirtir. `Script.dil`
alanı ve `platform.py` yardımcıları Ş1'indir; diğer şeritler §2.1–2.2'deki adlara göre kod yazar
(kendi worktree'lerinde derlenmesi için aynı adlarla **asgari** tanımı ekleyebilir; birleştirmede
Ş1'in sürümü kazanır).

## 4. Anayasa notu
Bu çalışma ilkeleri değiştirmez: model hiçbir dilde kod yazmaz (deterministik render), tam hat
dillerinde derleme + koruma + koşu PR'da zorunludur, doğrulanmamış diller **PR'a ve merge'e
giremez**. Anayasa IV/V/VI ve "Geliştirme Akışı" metni inceleme turu 1'de (D6) dilden bağımsız hale
getirildi: **v2.1.0** (MINOR; doğrulanmamış dil kuralı yeni madde). Onay: teknik lider + ürün sahibi.

## 5. Ertelenenler (K-T9, backlog)
C#/Python namespace/paket proje ayarı ve PO iskelet indirmesi (QA-Y3'ün büyük kısmı), üretilen Java
metot adının başlıktan türetilmesi (QA-O6), login literal'i yerine `dealer()` erişimcisi (QA-O4),
Test case'leri CSV dışa aktarma ve satır içi adımlar, `@TmsLink` (guard değişikliği gerektirir),
DB'de (platform, dil) CHECK'i (MİM-L4; backfill sonrası ayrı göç), arm64 QEMU altında imaj duman
testi izlemesi (OPS-O5), mvnw 3.9.16 ↔ imaj Maven 3.9.11 hizası (OPS-L4), iki dilli paket
koşularının kapasite izlemesi (OPS-L7). Tur 2: başka dilde merge edilmiş testin ürün içinden
kaldırılması (K-T12).

## 6. Operasyon (D6)
Ortam değişkenleri (`TP_WEB_DILLERI`, `TP_PLATFORMS`, `TP_E2E_JAVA_ROOT`): `.env.example`,
`docker-compose.yml`, `docs/MIMARI-SOZLESME.md` §6. Dağıtım sırası, geri dönüş ve backfill:
`docs/GCP-KURULUM.md` "011 dağıtım sırası". Mevcut LocalForge'a e2e-java eklemek:
`make forge-sync-dizin D=e2e-java B=--baseline` (tur 2: kök konteynerde `safe.directory`
`GIT_CONFIG_GLOBAL`'dan; ref'ler tek atomik fetch ile, yarım durum yok). Ruleset'e `web-java`:
`scripts/github-ruleset.sh --add-checks web-java` (mevcut platform check'leri korunur). GitHub demo deposu: `scripts/github-demo-repo-init.sh`
web-java.yml + `toolchain/java-araclar` + `toolchain/e2e-java-deps` taşır. Playwright yükseltmesi:
`docs/PLAYWRIGHT-YUKSELTME.md`, `make playwright-surum-denetle`.

# 011 inceleme turu 1 — ham bulgular (rol raporlarının özeti)

Kararlar ve şerit ataması: `inceleme-tur1.md`. Satır numaraları `feat/uretim-dili` @ d6f4488 içindir.

## GÜV (güvenlik)
- GÜV-O1 (orta, DOĞRULANDI) `core/src/tp_core/features/triage/java_web.py:240-255` `_TestIdToplayici._zincir()` her testId'li düğüm için kapsayıcı zincirinin tam kopyasını tutuyor; MAX_DUGUM 50.000, MAX_DERINLIK 512. 510 iç içe testId'li div + 49.000 testId'li `<i>` (1,1 MB) → ~410 MB RSS, 1,5–3,5 sn. 4 MB dosya sınırı engellemiyor (düğüm × derinlik). Triage her web+Java hatasında ve onarım `_dom_yeniden` aynı yolu okuyor. Düzeltme: zincir yerine üst düğüm indeksi ya da zinciri son 8–16 testId ile sınırla; testId'li düğüm için ayrı düşük sınır (ör. 5.000); süre/adım bütçesi. Regresyon testi (bellek/süre üst sınırı).
- GÜV-D1 (düşük) `render.py` `_STORY_RE`(49), `_JAVA_IDENT_RE`(294), `_JAVA_GRUP_RE`(296), `_JAVA_BAYI_RE`(297), `_CS_SINIF_RE`(595), `_PY_TEST_RE`(596), `dil_algila._SHA_RE`, `checks.IDENT_RE`(35): `^…$` + `re.match` sondaki `\n`'i geçiriyor (`java_ident("addToCart\n")` kabul). Düzeltme: `re.fullmatch` ya da `\A…\Z`; süzgeç düzeyinde test.
- GÜV-D2 (düşük) `GET /code/languages` (`codegen/api.py`, `service.py:582-589`) her istekte `forge.head_sha("main")`; hata önbelleklenmiyor; tüm rollere açık → GitHub hız sınırı tüketme. Düzeltme: `head_sha` 30–60 sn önbellek, başarısız algılamayı kısa önbellek, ucu engineer|presenter'a daralt.
- GÜV-D3 (düşük) GitHub kipinde `TP_WEB_DILLERI` java içermezse `web-java` zorunlu check olmuyor, `ci.yml` Java'yı koşmuyor ama web+Java üretimi engellenmiyor. Düzeltme: K-T3.
- GÜV-B1 rol kısıtı yalnız arayüz → belgele (K-T8).

## QA (kıdemli test otomasyon mühendisi)
- QA-Y1 `codegen/dil_algila.py:111-120, 128-141`, mesaj `review-portal/src/components/Dil.tsx:89`: kökte standart Maven (`src/test/java/**/*Test.java`, `*IT.java`) → ts varsayilan; `*Tests.java` → 0; Kotlin `*Test.kt` → 0; 25 projeli .NET monorepo + `tests/E2E/E2E.csproj` → C# 0 (`MAX_ISARET_OKUMA=20` derinlik+alfabe sırasıyla src/* projelerine harcanıyor; Python'a da hak kalmıyor). Mesaj "Depoda elle yazılmış test bulunamadı; varsayılan dil TypeScript" yanıltıcı → nereye bakıldığını söylesin. Düzeltme: K-T7.
- QA-Y2 `review-portal/src/pages/Kosular.tsx:71-74` aynı `<DilRozeti>` iki kez (birleştirme kalıntısı) → "Java Java". Tek rozet + test.
- QA-Y3 C#/Python: `render.py:581-582` `CS_PO_NAMESPACE`, `CS_NAMESPACE`, `PY_PO_PAKETI` sabit; şablonlar `playwright_nunit.cs.j2:24`, `pytest_playwright.py.j2:30`; başlıkta gereken PO sınıf/metot imzaları yok; "Elle düzenlemeyin" ifadesi doğrulanmamış dille çelişiyor; tek dosya indirme (`ScriptDetay.tsx:643`). Bu turda K-T9 küçük kısım.
- QA-O1 `dil_algila.py:144-146` (`d == ""` dalı): kökte pyproject'te `pytest-playwright` dev bağımlılığı + 30 `api/tests/test_unit*.py` + 1 TS spec → `python algilandi`. Düzeltme: kök işareti yalnız `conftest.py`'de `page` fikstürü / `from playwright` varsa; ya da test dosyasında `playwright`/`page:` arama.
- QA-O2 `ExtentRaporu.java:220-229` (e2e-java ve e2e-app): arşiv `extent.json` her başlangıçta geri yükleniyor → clean'siz yeniden koşuda eski FAIL + yeni PASS birlikte. Düzeltme: arşivi yalnız `extent.tekrar` verildiğinde geri yükle, aksi halde sil.
- QA-O3 Extent adı `Sınıf › metot` (`ExtentRaporu.java:201-206, 277`), Allure description kullanıyor; Extent'te description yok; adım yok; Allure'da yalnız `suite` etiketi (TestNG grupları/Jira Test anahtarı yok); her `tp-case-<uuid>` ayrı Extent kategorisi. Düzeltme: Extent adı = description (`Sınıf.metot` alt bilgi); `tp-case-*` kategoriden süz; Allure etiketleri (story, tp-case, Jira Test) TestTabani'ndan grup/annotation okuyarak. Adım kancası ertelenebilir.
- QA-O4 (ertelendi, K-T9) üretilen testte `login("bayi1","Demo123!")` düz parola.
- QA-O5 `TestCaseleri.tsx:220` satır bağlantısı story'nin case listesine gidiyor (tekil case'e değil); "otomasyon durumu" sütunu yok (kod üretildi mi, platform/dil, PR, son koşu). CSV/satır içi adım/toplu gönderme ertelendi.
- QA-O6 (ertelendi) metot adı her zaman `senaryo`.
- QA-O7 `pytest_playwright.py.j2:34-42` kayıtsız marker'lar (`uretilen`, `web`, `tp_case`, `story`, `dealer`) → `--strict-markers` kırar. Başlığa `pytest.ini`/`conftest.py` parçası.
- QA-düşük: C# async metotlar `Goto()/Login()` → `GotoAsync/LoginAsync` konvansiyonu; `[Property("dealerUsername")]` okuyan yok. `TestTabani.yuvaAl()` (`:87-98`) boş yuva yoksa hata → semafor ile beklet. `@Bayi` sabit testi ile yuva dengesizliği. `-Dgroups` koşusu seri. `break-verify-java.sh` yalnız `kampanya` grubu (README'de belirt). Her koşuda `file.encoding cannot be set as system property` uyarısı → `argLine`. `SepetTest.java:52` `locator("xpath=..")` → testId. `Kosular.tsx:486` yorumu "Extent yalnız Java (Appium + TestNG)" eski.

## MİM (mimar/bakımcı)
- MİM-Y1 `codegen/service.py:718` (atlama `sc.dil == dil` istiyor), `:735` (`pr_open` → `closed`), `:2190` (`_eski_prlari_kapat` tam_hat kontrolünden önce). A: açık TS PR varken `{dil:"csharp"}` → TS script closed, worker forge PR'ını kapatıyor (§2.7 ihlali). B: TS `merged` iken `{dil:"java"}` → ikinci test, repoda aynı case iki kez. Düzeltme: K-T4.
- MİM-Y2 `control_tower/service.py:613-629` `unverified` → `rv_payda += 1` (ilk review başarısı KPI'ı düşüyor). Düzeltme: ayrı `script_dogrulanmamis` sayacı + `continue`; portal Kontrol Kulesi; test.
- MİM-Y3 `toolchain/worker/check.py:208` her iki dil `local-ci`; `ci/service.py:412` script'siz pr hep `ts`; `ci/service.py:863`. Kardeş koşular aynı sha'ya `local-ci` yazıp birbirini eziyor; yalnız `e2e-java/` değiştiren script'siz PR TS koşup yeşil `local-ci` yazıyor → Java derlenmeden merge. Düzeltme: K-T1.
- MİM-O1 `service.py:2625` `render_dil` çağrısında `referans_dil` yok → yalnız e2e-java olan repoda C# başlığı "TypeScript tablosundan" diyor, audit `referans_tablo: java`. `_render`'a `tablo_dili` geçir; `test_dil_akis` sahte render bunu almıyordu.
- MİM-O2 başlangıç yolu `e2e-csharp/Uretilen/TPD1WebC2_<u>Tests.cs` ↔ render `tests/Generated/TPD1C2_<u>Tests.cs` (Python benzer); `uretim_koku` doğrulanmamışta ölü. K-T6.
- MİM-O3 `dil_algila.py:111` yalnız `*Test.java`; `ci/dil.py` `Test.java|Testi.java`; e2e-app el testleri `*Testi.java` → android algılama 0. dil_algila docstring "e2e-app/e2e-java C#/Python sayımına girmez" ama dışlama kodu yok. K-T7.
- MİM-O4 `ci/service.py:981` script_id varsa dil dağıtımı yok; `codegen/service.py:3315, 4151` push script_id ile. K-T2.
- MİM-O5 `rules/prompts/verify-and-map.md:30-44` rol+ad ile bulma; Java tablosunda role/name boş, anahtarlar `Cart.TOTAL`. K-T5.
- MİM-O6 `.github/CODEOWNERS` yalnız `demo-app/e2e/...`; e2e-java (ekranlar, uretilen, pom.xml, testng.xml) ve e2e-app karşılıkları ekle.
- MİM-O7 `test_dil_akis.py:66-104` sahte `render_dil`; gerçek Java web şablonu + Java tablosu + `check_mapping` + `java_eslemesi` + `_kontrol` hiç birlikte koşmuyor. `demo-app/e2e-java/.../uretilen/TPD1WebC2_3f9b1c2eTest.java` golden'dan farklı (başlık `TPD-1-C2`, şablon `ornek-referans-dosyasi`) → gerçek şablon çıktısı e2e-java'da derlenmiyor. Eksik regresyonlar: Y1, Y2, Y3, O1, golden'ın e2e-java'da derlenmesi.
- MİM-L1 ölü/kopya: `platform.check_adi`, `java_metot_adi`, `DIL_KAYNAKLARI`, `UYGULAMA_CATISI` yalnız testlerde; check adı 3 yerde (`ci/service.py:863`, `codegen/views.py:139`, `toolchain/worker/check.py:208`); dil kümesi kopyaları (`enums.DIL`, `forge.WEB_TAM_HAT_DILLERI`, `ci/dil.TS/JAVA/WEB`, `toolchain java.LANGS`); `UYGULAMA_PLATFORMLARI` `triage/java.py:34` ve `ci/service.py:99`; `PROJE_DOSYASI` `"e2e-java/pom.xml"` sabit; `views.KONTROL_ADIMLARI` ↔ `classify.TS_/JAVA_ADIMLARI`; ad çakışması `platform.gecerli_dil` (raise) ↔ `ci/dil.gecerli_dil` (None).
- MİM-L2 `getattr(sc, "dil", None)` artıkları `ci/dil.py:42`, `triage/service.py:566`, `repair/service.py:227`; `e2e_java_root` üç katmanlı delegasyon.
- MİM-L3 `views.py:309` `durum=="unverified"` ↔ `views.py:492` `or dogrulanmamis_mi(sc.dil)`.
- MİM-L4 DB'de (platform, dil) CHECK yok (OPS-O2 göç penceresi nedeniyle bu turda eklenmiyor; runbook backfill).
- MİM-L5 core `adimlar[].durum` dizge (`passed|failed|skipped`), `types.ts:679` `boolean|null` → sözleşmeyi sabitle.
- MİM-L6 portal "Yeniden üret" `sc.dil` gönderiyor → `dil_kaynagi` `algilandi`→`secildi` kayıyor (`Kod.tsx` `yenidenUret`).
- MİM-L7 GitHub kipinde algılama core-api'de `GITHUB_READ_TOKEN`'a bağlı; yoksa hepsi `kullanilabilir:true`, `varsayilan`; `_eski_prlari_kapat` docstring "core-api forge'a erişemez" artık yanlış.
- MİM-L8 asistan prompt/öneri kuralları "Doğrulanmamış" ve dil seçiciden habersiz.
- Doküman borcu: anayasa IV/V/VI + Geliştirme Akışı; TT §8.4–8.7 + SCRIPT makinesi; MIMARI-SOZLESME (TP_E2E_JAVA_ROOT/DEPS, `/symbols` `/check` kuralları, check adı, `run.ortam.dil`, script alanları); 009 plan K3 notu; 011 plan (K-T1..K-T9, §2.4 kalıp, §2.7 yol); CODEOWNERS; verify-and-map; asistan; docstring'ler (`dil_algila`, `_eski_prlari_kapat`, `test_dil_akis` başlığı).

## OPS (DevOps/SRE)
- OPS-Y1 `scripts/github-demo-repo-init.sh:108-112` copy_tracked listesinde `.github/workflows/web-java.yml`, `toolchain/java-araclar`, `toolchain/e2e-java-deps` yok ama `demo-app/e2e-java` var → GitHub kipinde her push/nightly/deploy Java kardeş koşusu açar, gelmeyen olayı 5400 sn / 12 saat bekleyip `error`; deploy 404; zorunlu check olursa PR süresiz blok. `run-java-checks.sh:55-57` güvenilir pom yoksa yalnız UYARI → kilit sessizce kapanıyor. Düzeltme: listeye ekle + `test_github_demo_repo_init_script.py` beklenenlere ekle + CI'da (`CI=true`) güvenilir pom yoksa `exit 1` + K-T3.
- OPS-O1 `docker-compose.yml` `x-core-env`/core-api/core-worker'da `TP_WEB_DILLERI` (ve `TP_PLATFORMS`) yok; `.env.example` yok; `codegen/views.py:66, :165` `github_required_checks`'e `etkin_web_dilleri` geçmiyor (`forge_github.py:630-634` geçiyor); geçersiz değer `GitHubForge.from_env`'i kırıyor ama portal engel göstermiyor.
- OPS-O2 `0021_script_dil.py:44` + `models/delivery.py:70` sunucu varsayılanı 'ts' → göç penceresinde eski core'un uygulama script'leri `dil='ts'`. Runbook: `UPDATE script SET dil='java' WHERE platform<>'web' AND dil='ts';` (idempotent); downgrade notu (unverified→closed geri dönmez, kaynak_kod silinir, açık Java PR'ları önce kapat).
- OPS-O3 `scripts/forge-init.sh:283` mevcut LocalForge'a e2e-java ekleme yolu yok (`--force` PR kaydını siliyor). Öneri: `forge-init sync-dizin e2e-java` alt komutu (main'e tek commit) + runbook.
- OPS-O4 GitHub kipinde toolchain `TP_E2E_JAVA_ROOT` `demo-app/e2e-java` olmalı; `docs/GERCEK-SISTEMLER.md:485`, `.env.example`, `README.md`, `toolchain/README.md`, `docs/GCP-KURULUM.md`, `docs/DEGISIKLIK-TEST-REHBERI.md`, Makefile güncel değil.
- OPS-O5 arm64 QEMU altında imaj duman testi riski (izlenecek; gerekirse duman yalnız amd64).
- OPS-O6 test-runner 3g limit: Maven JVM + Surefire fork (heap sınırsız) + Node sürücüsü + 2 Chromium → surefire `argLine -Xmx512m`, `MAVEN_OPTS -Xmx384m` (runner `maven_env`), `TMPDIR` koşu dizinine.
- OPS-L1 `web-java.yml:75-85` filtreye `toolchain/e2e-java-deps/**` (ve `demo-app/e2e/package.json`) + CI.md:264.
- OPS-L2 `ci.yml:95` `demo-app/**` → yalnız e2e-java değişince TS test-local da koşuyor (kabul edilebilir / hariç tut).
- OPS-L3 `toolchain/Dockerfile:161-186` Java COPY katmanları ve duman testi Python COPY'lerinin (150-154) arkasında → Java bloğunu `uv sync` öncesine al.
- OPS-L4 e2e-java mvnw 3.9.16 ↔ imaj Maven 3.9.11.
- OPS-L5 Playwright yükseltme kontrol listesi/`make playwright-surum` (değişecek dosyalar: `.playwright-version`, Dockerfile FROM digest, toolchain/package*.json, e2e-deps, mcp, demo-app/e2e/package*.json, iki pom `<playwright.version>` (Java sürüm ≠ npm), `demo-app/.sauce/config.yml`).
- OPS-L7 kapasite: paket koşuları iki dilde (izleme notu).
- Dağıtım sırası: imajı derle → Postgres yedeği → migrate 0021 → toolchain-worker + test-runner birlikte → core-api + core-worker + portal → O2 backfill → (isteğe bağlı) forge'a e2e-java → GitHub'da Y1/O1 düzelmeden TP_WEB_DILLERI/ruleset'e web-java ekleme. Geri dönüş: core eski imaj, şema kalır + backfill.

## EKR (Chrome for Testing 157 ekran testi)
- EKR-E1 (orta) mock web+Java kodu gerçek şablondan farklı (`new CartPage(page())`, `ekranlar.*` import, `login.open()`, sınıf `TPD1C9_…`) — gerçek: golden `TPD1WebC2_3f9b1c2eTest.java` biçimi (`loginPage().goTo()`, 3 import, `TPD1WebC<n>_…`). `review-portal/src/api/mock/diller.ts`.
- EKR-E2 (orta) mock web+Java "Eşlenen adımlar" `LoginPage.goto()` → `goTo`.
- EKR-E3 (düşük) mock Python kodu/yolu gerçek şablondan farklı (K-T6 yolu).
- EKR-E4 (düşük) 390 px'te "Üretilen testler" tablosu yığına dönmüyor, başlık/yol kesiliyor.

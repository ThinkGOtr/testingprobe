# CI (AI'sız) — GitHub Actions

TEKNIK-TASARIM §8.5 ve Constitution II'nin uygulaması. CI'da model anahtarı, MCP sunucusu veya
ajan bağımlılığı **yoktur**; yalnızca onaylanmış, deterministik test kodu koşar.

> Bu dosya `.github/README.md` değil, `CI.md` adını taşır: GitHub `.github/README.md`'yi repo
> ana sayfasında kökteki README'nin yerine gösterir.

## Workflow'lar

| Dosya | Tetik | Yetki |
|---|---|---|
| `workflows/ci.yml` | `pull_request`, `push` (main), gece `0 2 * * *` (02:00 UTC = 05:00 TR), `repository_dispatch` `deploy`, `workflow_dispatch` (`tetik`, `istek_id`) | `contents: read`, `packages: read` (`changes` job'una ek olarak `pull-requests: read`) |
| `workflows/break-verify.yml` | yalnızca elle `workflow_dispatch` (`grep`, `istek_id`) — "kırarak doğrula" kanıtını GitHub Actions'ta üretir; çekirdek tetiklemez (aşağıda "Kırarak doğrula ve GitHub modu") | `contents: read` |
| `workflows/build-toolchain.yml` | `toolchain/**`, `.playwright-version` değişikliği (main'e push → çok mimarili derleyip gönderir; PR → yalnızca amd64 derler), `workflow_dispatch` | `packages: write` **yalnızca burada** |
| `workflows/mobil-android.yml` | `pull_request`, `push` (main), gece `30 2 * * *`, `workflow_dispatch` (`tetik`, `istek_id`) — aşağıda "Uygulama iş akışları" | `contents: read` (`changes`: + `pull-requests: read`) |
| `workflows/mobil-ios.yml` | yalnız ilgili yollar değişen `pull_request` (workflow düzeyinde `paths`), gece `0 3 * * *`, `workflow_dispatch` | `contents: read` |
| `workflows/masaustu-windows.yml` | `pull_request`, `push` (main), gece `30 3 * * *`, `workflow_dispatch` (`tetik`, `istek_id`) | `contents: read` (`changes`: + `pull-requests: read`) |
| `workflows/web-java.yml` | `pull_request`, `push` (main), gece `15 2 * * *`, `workflow_dispatch` (`tetik`, `istek_id`) — aşağıda "Web Java iş akışı (011)" | `contents: read` (`changes`: + `pull-requests: read`) |

Her üçüncü taraf Action tam 40 karakterlik commit SHA'sıyla, sürüm yorumuyla sabitlenmiştir;
Semgrep imajı sürüm + digest ile sabitlenmiştir. `dependabot.yml` bunları aylık günceller.

## ci.yml job'ları

| Job | Zorunlu | Ne yapar |
|---|---|---|
| `changes` | — | PR'da `dorny/paths-filter` ile `demo-app/**` (yalnız `demo-app/e2e-java/**` / `ci/run-java-checks.sh` / `ci/break-verify-java.sh` değişikliği hariç; bkz. "Web Java iş akışı"), `demo-app/e2e/pages/**`, `toolchain/ast-guard/**` (ve ilgili `scripts/github-*.sh`) değişikliğini tespit eder; tetik türünü (`pr`/`push`/`nightly`/`deploy`/`manual`) belirler. PR dışı olaylarda testler her zaman koşar. |
| `test-local` | **evet** | `demo-app/ci/run-checks.sh --retries=1` (elle yazılmış + `e2e/tests/generated/**` üretilen testler); sonuçları yerel koşuyla aynı düzende `test-local-results` artefaktına, HTML raporunu ayrıca `playwright-report`'a yükler. |
| `ast-guard` | **evet** | PR'da `toolchain/ast-guard`'ı `merge-base(base, head)..head` aralığında çalıştırır. `demo-app/e2e/tsconfig.json` değiştiyse tsc --strict kapısının gevşetilmediğini de doğrular (`strict: true`, strict ailesi kapatılamaz, `extends` yok, kapsam değişmez). |
| `semgrep` | **evet** | `semgrep/semgrep` konteynerinde `p/default` + `p/typescript`, token/hesap yok, `--metrics=off`. Kapsam: `demo-app/`, `toolchain/ast-guard/`. |
| `demo-serve-smoke` | hayır | Sauce'un uygulama başlatma yolunu (`scripts/github-demo-serve.sh --smoke`) kimliksiz doğrular: `/api/health` proxy üzerinden 200, izinli Host (`tp-demo.test`) kabul, izinsiz Host 403. |
| `golden-drift` | hayır | AI'sız, **saf veri** (anayasa II): `rules/replay` golden kayıtlarının kanıt satırları, case beklentileri, page object eşlemeleri ve §8.2b düzeltme döngüsünün son hali demo-app kaynağıyla tutarlı mı. `.github/golden-drift/` paketini `uv run --no-project --with-requirements requirements.txt` ile koşar (yalnız pytest + jsonschema + pyyaml); core venv'i, `tp_core.gateway`, `anthropic` ve `mcp` kurulmaz, ayrı bir adım bunlardan biri içe aktarılabiliyorsa job'u kırar. Gateway üzerinden replay ajan döngüsünü koşan `core/tests/unit/gateway/test_consistency_flow.py` yerel birim paketinde kalır. `demo-app/**`, `rules/**`, `docs/DEMO-VERISI.md` veya `.github/golden-drift/**` değişince koşar. |
| `sauce` | hayır (`continue-on-error`) | Aynı testleri Sauce Labs bulut Chromium'unda Sauce Connect tüneliyle koşar; job linkini adım özetine ve `sauce-results/sauce.json`'a yazar (kimlik yoksa `durum: atlandi`). |

**Workflow düzeyinde `paths` filtresi yoktur.** Atlanan zorunlu check PR'ı süresiz bekletir; bu
yüzden zorunlu job'lar her PR'da çalışır ve ilgisiz PR'da "no-op, başarılı" çıkar.

### test-local: toolchain imajı mı, runner mı?

Tasarım, job'un toolchain imajında (`ghcr.io/thinkgotr/tp-toolchain@<digest>`) koşmasını ister.
İmaj henüz yayımlanmadığı için job iki yoldan birini seçer:

- **Yol A — repo değişkeni `TP_TOOLCHAIN_IMAGE` tanımlıysa:** GHCR'a `GITHUB_TOKEN` ile giriş yapılır
  ve `run-checks.sh` bu imajın içinde `docker run --user root` ile koşar. Değer digest içermelidir
  (`…@sha256:…`), aksi halde job hata verir. Bu, yerel kontrolle (test-runner) aynı imajdır.
  İmaj **uv içermez** (`toolchain/Dockerfile` uv'yi yalnızca build sırasında bağlar), ama
  `run-checks.sh` API webServer'ı için `uv sync`/`uv run` ister. Bu yüzden runner'a `setup-uv` ile
  kurulan sabit sürümlü uv imaja salt-okunur bağlanır (`/usr/local/bin/uv`); Python imajdaki
  `UV_PYTHON=/usr/bin/python3.12`'dir. `UV_PROJECT_ENVIRONMENT` imajda toolchain venv'ini gösterdiği
  için `/work/demo-app/api/.venv`'e yönlendirilir. Testlerden önce imajda `uv`, Python ve `node`
  ön kontrolü yapılır; başarısızsa job açık hata ile durur (çözüm: değişkeni boşaltıp Yol B'ye dönmek).
- **Yol B — değişken boşsa (varsayılan):** runner'a `actions/setup-node` (Node 22),
  `astral-sh/setup-uv` (uv 0.8.24) ve `npx playwright@<.playwright-version> install --with-deps chromium`
  kurulur; tarayıcılar `actions/cache` ile önbelleklenir.

Neden `container:` değil de `docker run`: job düzeyinde `container:` boş değerle güvenilir şekilde
"kapatılamıyor" ve imaj `pwuser` ile çalıştığından çalışma alanı izin sorunları çıkarıyor. `docker run`
ile iki yol da aynı job adı (`test-local`) altında, aynı betikle çalışır.

İmaj yayımlandıktan sonra: `build-toolchain` özetindeki komutla
`gh variable set TP_TOOLCHAIN_IMAGE --body 'ghcr.io/thinkgotr/tp-toolchain@sha256:…'`.
GHCR paket ayarlarında bu repoya Actions erişimi verilmelidir.

### run-checks.sh sözleşmesi (demo-app şeridi sağlar)

- Çağrı: `bash demo-app/ci/run-checks.sh --retries=1` (repo kökünden).
- Ortam: `CI=true`, `TP_TRIGGER` (`pr|push|nightly|deploy|manual`), `TP_APP_ROOT` (uygulama kökü),
  `TP_RESULTS_DIR` (sonuç dizini; GitHub'da `$GITHUB_WORKSPACE/results`).
- Çıktılar `TP_RESULTS_DIR` altında: `junit.xml`, `results.json` (Playwright JSON), `allure-results/`,
  `html/` (Playwright HTML raporu; `playwright.config.ts` `outputFolder: results/html`), iz dosyaları
  (`**/trace.zip`). Betik `TP_RESULTS_DIR`'i dikkate almazsa
  `demo-app/e2e/results/` altındaki aynı adlar da yüklenir.
- Çıkış kodu: test başarısızsa ≠ 0.

Sonuçlar `scripts/github-ci-results.sh` ile toplanır (aşağıda "Artefakt sözleşmesi").

### ast-guard

- Araç **taban daldaki** sürümden derlenip çalıştırılır; PR aracı değiştirerek kontrolü atlatamaz
  (taban dalda araç yoksa — ilk kurulum — PR'daki sürüm uyarıyla kullanılır). Araç değiştiyse PR'daki
  sürümün birim testleri ayrıca koşar.
- **Mod** (`scripts/github-ast-guard-mode.sh`, taban daldan çalışır): aşağıdakilerden biri doğruysa
  `repair` (yalnızca `pages/**/locators.ts` içindeki `testId` değerleri değişebilir), aksi halde `pr`
  (değişen `locators.ts` dosyaları saf veri kalmalı; değişen `testId`'ler özette listelenir):
  1. PR dalı `REPAIR_BRANCH_PREFIX` (`tp/repair-`) ile başlar;
  2. PR'da `tp-repair` etiketi vardır;
  3. PR'ı **bot** açmıştır ve dal `CASE_BRANCH_PREFIX` (`tp/case-`) ile başlamaz. Bot =
     `pull_request.user.type == "Bot"` (GitHub App PR'ları) veya giriş adı repo değişkeni
     `TP_BOT_LOGINS`'te (virgülle; `tp-bot` yazılırsa `tp-bot[bot]` de eşleşir). Böylece farklı
     adlı bir onarım dalı veya etiketi kaldırılmış bir bot PR'ı zayıf `pr` moduna düşmez.
  Çekirdek onarım PR'larını `tp/repair-` dalıyla ve `tp-repair` etiketiyle açmalıdır; önekler
  `ci.yml` `env`'indeki değerlerle aynı olmalıdır.
- `pr` modunda `demo-app/e2e/pages/**` değişmediyse no-op (başarılı).
- Rapor: adım özeti + `ast-guard-report` artefaktı (JSON). Ayrıntı: `toolchain/ast-guard/README.md`.

### Sauce

- Secret'lar: `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`. Yoksa (veya fork PR'ında) job özet yazıp atlar.
- Repo değişkeni `SAUCE_REGION` (saucectl adı): `us-west-1` (varsayılan), `eu-central-1`, `us-east-4`.
- Uygulama runner'da `scripts/github-demo-serve.sh` ile başlar: API (`uv sync --frozen --no-dev`,
  uvicorn, SQLite, `DEMOAPP_TEST_MODE=1`) + web (`npm ci`, `vite build`, `vite preview`, `/api` proxy'si).
  `PORT` ve `TP_ALLOWED_HOSTS`'u kullanır; izinli adlar Vite'ın `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS`
  değişkenine geçer (`vite.config.ts` değişmez). Ön planda çalışır; API veya web ölürse ≠0 ile çıkar.
  Hazırlık `http://tp-demo.test:8081/api/health` ile ölçülür (`/health` SPA geri dönüşüyle her zaman
  200 döner). Koşu başına rastgele `DEMOAPP_TEST_TOKEN` üretilir, maskelenir; uygulamaya ve
  `saucectl -e` ile testlere geçer. Yerelde: `TP_ALLOWED_HOSTS=tp-demo.test scripts/github-demo-serve.sh --smoke`.
  Sauce VM'indeki tarayıcı ona `http://tp-demo.test:8081` adresiyle ulaşır: ad runner'ın
  `/etc/hosts` dosyasında `127.0.0.1`'e bağlanır, Sauce Connect 5 DNS'i runner tarafında çözer
  (`proxyLocalhost: allow`). `localhost` kullanılmaz çünkü Chromium localhost'u proxy'den geçirmez.
- `saucectl` (v0.216.4) `demo-app/` dizininden `.sauce/config.yml` ile çalışır;
  `-e BASE_URL=… -e TP_EXTERNAL_SERVER=1` geçirilir. Playwright config'i `TP_EXTERNAL_SERVER=1`
  iken `webServer` başlatmamalıdır.
- **Sürüm farkı:** Sauce şu an en fazla Playwright **1.61.1**'i destekliyor (saucectl v0.216.4 şeması);
  repo 1.64.1 kullanıyor. `config.yml` 1.61.1'e sabitlenmiştir. Sauce 1.64'ü desteklediğinde
  `version: package.json` yapılmalıdır.
- Job linkleri (`saucectl-report.json`, yoksa log) `scripts/github-sauce-summary.sh` ile adım özetine
  ve `sauce.json`'a yazılır; artefakt: `sauce-results` (aşağıda). Kimlik yoksa job yine checkout yapar
  ve `durum: atlandi` kaydı yükler (çekirdek "Sauce koşmadı" ile "Sauce kırmızı"yı ayırır).
- Testler `testMatch` ile `e2e/tests/**/*.spec.ts`; üretilen `tests/generated/**` açıkça listelidir.
- Eşzamanlılık 1 (hesap 1–2 oturum).

## Çekirdek bağlantısı (tetik ve koşu bulma)

- **Deploy:** `POST /repos/{repo}/dispatches` `{event_type: "deploy", client_payload: {istek_id | tp_run_id,
  ref?}}` (`GitHubForge.dispatch_deploy` / `repository_dispatch`). `ref` verilirse o dal/sha checkout
  edilir (test-local, sauce, golden-drift). Koşu adı `ci deploy [<kimlik>]` olur.
- **Gece / elle:** `POST /actions/workflows/ci.yml/dispatches` `{ref, inputs: {tetik: nightly|manual|deploy,
  istek_id?}}` (`GitHubForge.workflow_dispatch`); koşu adı `ci <tetik> [<istek_id>]`. Zamanlanmış gece
  koşusunun olayı `schedule`'dır.
- **Koşuyu bulma:** `GitHubForge.find_dispatched_run(kimlik)` koşu adının sonundaki `[<kimlik>]`'i eşler
  (GitHub dispatch yanıtında koşu kimliği dönmez). PR/push koşuları `list_workflow_runs(head_sha=…)`.
  Kimlik biçimi `[A-Za-z0-9._-]{1,64}` (`changes` job'u doğrular; geçersizse koşu kırmızı).
- **Eşzamanlılık:** yalnızca `pull_request` koşuları iptal edilir; dispatch koşuları kimlikle ayrı
  gruptadır, çekirdeğin beklediği koşu iptal edilmez.
- **Commit:** `repository_dispatch`/`schedule` koşusunun `head_sha`'sı varsayılan dalın ucudur; test
  edilen commit `ci-meta.json` → `sha`'dır (checkout HEAD).
- **Kontroller:** `GitHubForge.check_runs(sha)` (`details_url` → `workflow_run_id`, `job_id`); merge
  kapısı `checks(sha)` ile aynıdır.
- **Portal merge'ü (GitHub modu):** `GitHubForge.merge_pr_detailed` PUT'tan önce ruleset koşullarını
  kendisi değerlendirir: zorunlu kontroller, head commit'ini onaylayan insan GitHub review'u,
  `mergeable_state != blocked`. Tek `GITHUB_MERGE_TOKEN` bypass takımındaki demo-admin'e ait
  olabileceği için GitHub eksikleri sessizce atlayabilir; bu yüzden eksik varsa yalnızca
  `demo-admin` merge eder ve sonuç `bypass=True` + neden (+ GitHub'da merge eden token sahibi)
  olarak döner. Diğer mühendisler önce PR'ı GitHub'da onaylamalı (Approve) ya da GitHub
  arayüzünden merge etmelidir; portal kimse adına GitHub review'u göndermez.

## Artefakt sözleşmesi (ci-runs alımı)

Artefakt kökleri düzdür (tek dizin yüklenir); adlar yerel koşuyla (test-runner
`runs/<id>/src/e2e/results/`) aynıdır. İndirme: `GitHubForge.download_run_artifact(run_id, ad, hedef)`
(yönlendirme kimliksiz izlenir; `safe_extract_zip` zip-slip / sembolik bağ / boyut bombasını reddeder).

| Artefakt | Job | Kökte |
|---|---|---|
| `test-local-results` | test-local | `ci-meta.json`, `junit.xml`, `results.json`, `allure-results/`, `playwright-report/` (yerelde `html/`), `artifacts/` (iz/ekran görüntüsü, yerelde `artifacts/`), `run-checks.log` |
| `playwright-report` | test-local | Playwright HTML raporu (insanlar için; aynı içerik yukarıda da var) |
| `sauce-results` | sauce | `sauce.json`, `junit.xml` (Sauce VM'deki Playwright raporu; yoksa saucectl'inki), `results.json` (varsa), `saucectl-report.json`, `saucectl-junit.xml`, `saucectl.log`, `serve.log`, `artifacts/` |
| `break-verify-results` | break-verify | `break-verify.json`, `break-verify.log`, `results.json` (son adım) |
| `ast-guard-report` · `semgrep-report` | ast-guard · semgrep | `ast-guard-report.json` · `semgrep.json` |

**Portalda yerel kopya:** çekirdek alımda `test-local-results`'ı (raporu taşımıyorsa ayrıca
`playwright-report`'u) aynen `TP_GITHUB_ARTIFACTS_PATH/gh/<run_id>-<deneme>/src/e2e/results/` altına
açar (`tp_gh_artifacts` volume'ü: core-worker yazar, core-api salt okur; `safe_extract_zip`). Portal
Playwright HTML / JUnit / allure-results / `run-checks.log` bağlantılarını GitHub'a gitmeden oturumlu
artefakt ucundan açar; kopya alınamazsa GitHub bağlantısına düşer. Toplam boyut `TP_GITHUB_ARTIFACTS_MAX_GB` (varsayılan 5) ile sınırlı; en yeni `TP_GITHUB_ARTIFACTS_KEEP`
(varsayılan 30) kopya saklanır. Özellikten önce alınmış koşular için (core-worker içinde):
`python -m tp_core.features.ci artefakt-indir <run_id>` (idempotent). Allure HTML raporu CI'da
üretilmez; portal ham `allure-results` listesini gösterir.

**`ci-meta.json`** (`schema_version: 1`, `scripts/github-ci-results.sh`): `kaynak: "github"`, `job`,
`tetik` (`pr|push|nightly|deploy|manual`), `istek_id`, `sha` (test edilen commit), `github_sha`, `ref`,
`event`, `repo`, `run_id`, `run_attempt`, `run_url`, `playwright`, `toolchain_image`, `exit_code`,
`durum` (`passed|failed|error` — `toolchain/runner/results.py` `decide_status` ile aynı kural: rapor yok /
rapor hatası / hiç test koşmadı → `error`; beklenmeyen sonuç → `failed`), `hata`, `stats`
(`expected, unexpected, flaky, skipped, duration_ms` — yerel `run.json` `stats` ile aynı), `results_kok`
(`results.json` içindeki ek yollarının runner'daki kökü; alım bunu artefakt köküne eşler), `dosyalar`
(`junit, json, allure, html, artifacts, log` → göreli yol | null), `generated_tests` (uygulama köküne
göreli `e2e/tests/generated/**.spec.ts`).

**`sauce.json`** (`scripts/github-sauce-summary.sh`): `kaynak: "sauce"`, `durum`
(`passed|failed|error|atlandi`), `neden`, `tetik`, `istek_id`, `sha`, `run_id`, `run_attempt`, `run_url`,
`bolge`, `tunel`, `saucectl_exit`, `job_url` (ilk Sauce job linki), `jobs[{id, url, ad, durum, tarayici,
platform}]` (yalnızca `https://app.*saucelabs.com/tests/<id>` linkleri), `dosyalar{junit, junit_turu:
playwright|saucectl, json, saucectl_report, log}`.

**`break-verify.json`** (`scripts/github-break-verify-result.sh`): `sonuc`
(`kanitlandi|zayif_test|hata`), `adim` (1–3), `neden`, `exit_code`, `grep`, `istek_id`, `sha`, `ref`,
`run_id`, `run_url`. Betik `demo-app/ci/break-verify.sh`'dir (yerel test-runner ile aynı); sınıflandırmanın
dayandığı satırlar `toolchain/ast-guard/test/ci-scripts.test.ts` ile sabitlenir.

### Kırarak doğrula ve GitHub modu

Portaldaki "Kırarak doğrula" (`POST /scripts/{id}/break-verify`) **her iki forge modunda da**
toolchain-worker `/check` (`BREAK_CAMPAIGN`) yolunu kullanır; çekirdek `break-verify.yml`'yi
tetiklemez ve `break-verify-results` artefaktını almaz. GitHub modunda (`TP_FORGE=github`) PR
commit'i toolchain'in forge aynasına yalnızca `TP_FORGE_REMOTE_URL` (+ salt okunur
`TP_FORGE_REMOTE_TOKEN`) verilmişse çekilir. Verilmemişse başlangıç koşusu "atlandı" olur,
kırarak doğrulama "tamamlanamadı" (`failed`) biter ve merge açık kabul notu ister
(`merge_kabul_gerekceleri`). `break-verify.yml` bir mühendisin aynı kanıtı GitHub üzerinde elle
üretmesi içindir (Actions → break-verify → Run workflow, ref = `tp/case-*` dalı); sonucu
`break-verify.json`'dadır ve portala yansımaz.

## Uygulama iş akışları (mobil / masaüstü, 009)

`specs/009-mobil-masaustu/plan.md` §2.7. Üçü de AI'sızdır (Constitution II): app-mcp, model anahtarı
ve ajan yoktur; yalnızca `demo-app/e2e-app` (Java + Appium + TestNG) `demo-app/ci/run-app-checks.sh
<platform>` ile koşar. Appium ve sürücüler `tools/appium` kilit dosyasından kurulur (`npm ci`,
`APPIUM_HOME`), `--relaxed-security` olmadan, `127.0.0.1:4723`'te. Test uçlarının (`/test/*`) sırrı
koşu başına rastgele üretilir, maskelenir ve yalnızca ortamla geçer.

| Job (= check adı) | Runner | Uygulama | Demo API'ye erişim |
|---|---|---|---|
| `mobil-android` | `ubuntu-24.04` + KVM, `reactivecircus/android-emulator-runner` (API 34, `google_apis`, x86_64, animasyonlar kapalı) | `derle-android.sh` (`ANDROID_ABI=x86_64`) → `build/bayi-siparis.apk` | `scripts/github-demo-serve.sh` (API + vite preview `/api` vekili, `127.0.0.1:8081`); emülatör hostun loopback'ine `10.0.2.2` ile ulaşır → APK'nın varsayılan adresi `http://10.0.2.2:8081/api` değişmez |
| `mobil-ios` | `macos-15` (arm64), en yeni kararlı Xcode, simülatör `TP iPhone` (en yeni iOS çalışma zamanı) | `derle-ios.sh` → `build/BayiSiparis.app` (yalnız `demo-app/mobile/**` değişince yeniden derlenir; `actions/cache`) | aynı `github-demo-serve.sh`; simülatör hostun ağını paylaşır → `http://127.0.0.1:8081/api`. WebDriverAgent testlerden önce `appium driver run xcuitest build-wda` ile derlenir |
| `masaustu-windows` | `windows-latest` (x64) | `yayinla.ps1 -Rid win-x64` (self-contained) → `build/win-x64/BayiSiparis.exe`; NovaWindows sürücüsü sabit sürümle geçici `APPIUM_HOME`'a | Windows runner'ında Linux konteyneri yok: API doğrudan `uv run uvicorn` (SQLite, test modu, `127.0.0.1:18000`). Uygulama API'yi yalnızca verilen kökten çağırdığı ve API uçları kökte olduğu için vekil gerekmez: `APP_ARGS=--api-url http://127.0.0.1:18000` |

Java testleri `/test/*` uçlarına her platformda doğrudan API kökünden (`DEMO_API_URL=http://127.0.0.1:18000`)
gider. Artefakt (`<job>-results`): `ci-meta.json` (`job`, `platform`, `sha`, `tetik`, `istek_id`,
`durum` = passed|failed|error), `surefire-reports/TEST-*.xml` (cihaz koşusu JUnit XML),
`birim-raporlari/`, `allure-results/`, `extent-report/index.html` (Extent raporu: tek dosya, indirip
tarayıcıda açılır), `kanit/<Sınıf>.<metot>/` (ekran görüntüsü + sayfa kaynağı; triage), `logs/` (`serve.log`/`api.log`, `appium.log`, `run-app-checks.log`, iOS'ta `wda-derleme.log`).

**Zorunlu check'ler (platform başına).** Varsayılan ruleset ve `TP_REQUIRED_CHECKS` değişmez
(`test-local,ast-guard,semgrep`). Bir platform etkinleştirildiğinde onun job adı iki yere birlikte
eklenir — ikisi aynı tutulmalıdır:

```bash
# ör. Android + Windows etkin (GitHub kipi; mobil/masaüstü iş akışları ilgisiz PR'da no-op):
TP_REQUIRED_CHECKS=test-local,ast-guard,semgrep,mobil-android,masaustu-windows   # core-api + core-worker (.env)
scripts/github-ruleset.sh --add-checks mobil-android,masaustu-windows --apply    # mevcutları korur
```

Kısa yol: core-worker `.env`'inde `TP_PLATFORMS=android,windows` verilirse çekirdek ve portal
`mobil-android` / `masaustu-windows` check'lerini zorunlu listeye kendisi ekler; CI tetikleme ve
sonuç okuma o platformun workflow dosyasını kullanır. `ios` bu listede kabul edilmez (aşağıya bakın);
geçersiz değer portalda "Yapılandırma hatası" engeli olarak görünür. Ruleset yine elle güncellenir.

`mobil-android` ve `masaustu-windows` bu yüzden ci.yml gibi `changes` job'u + "no-op, başarılı"
desenini kullanır (workflow düzeyinde `paths` yok; ilgisiz PR beklemez). `mobil-ios` macOS dakikaları
pahalı olduğundan (plan §5) workflow düzeyinde `paths` filtresiyle yalnız ilgili PR'da, gece ve elle
koşar; **varsayılan olarak zorunlu check değildir** (atlanan zorunlu check PR'ı süresiz bekletirdi).
Zorunlu yapılacaksa önce aynı `changes` + no-op desenine çevrilmelidir.

Demo deposuna (`scripts/github-demo-repo-init.sh`) üç iş akışı ve `tools/appium/package{,-lock}.json`
da kopyalanır.

Doğrulanmamış (GitHub'da koşturulmadı; yalnız `actionlint` + YAML ayrıştırma): emülatör/simülatör
açılış süreleri, runner imajındaki Xcode'un Expo SDK 58 / RN 0.88 için yeterliliği, NovaWindows'un
`windows-latest` etkileşimli masaüstü oturumunda çalışması ve Git Bash altında `mvnw`.

## Web Java iş akışı (011)

`specs/011-uretim-dili/plan.md` §2.5, §2.8. ci.yml `test-local`'in Java karşılığı (AI'sız; Playwright
MCP, model anahtarı ve ajan yoktur): `demo-app/e2e-java` (Playwright for Java + TestNG)
`demo-app/ci/run-java-checks.sh` ile koşar — pom kilidi (`toolchain/e2e-java-deps/pom.xml` ile bayt
eşit) → `java-araclar guard --kimlikler` (üretilen testler) → `./mvnw test-compile` → birim testleri →
tarayıcı koşusu (`testng.xml`, 2 iş parçacığı = 2 bayi).

| Job (= check adı) | Runner | Uygulama | Tarayıcı |
|---|---|---|---|
| `web-java` | `ubuntu-24.04` | `scripts/github-demo-serve.sh` (API `127.0.0.1:18000` + vite preview `/api` vekili `127.0.0.1:8081`); `BASE_URL`, `DEMO_API_URL`, koşu başına `DEMOAPP_TEST_TOKEN` | `npx playwright@<.playwright-version> install --with-deps chromium` (`~/.cache/ms-playwright` önbellekli); testler indirme yapmaz (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`) |

Değişiklik tespiti (`changes` job'u, PR): `demo-app/e2e-java/**`, `demo-app/{api,web}/**`,
`demo-app/kimlikler.json`, `demo-app/ci/*java*` (web-java.yml'de geniş süzgeç zararsız: fazladan koşu), `toolchain/java-araclar/**`,
`toolchain/e2e-java-deps/**` (güvenilir pom), `.playwright-version`, `demo-app/e2e/package.json`
(sürüm tutarlılığı adımı okur), `scripts/github-demo-serve.sh`, iş akışının kendisi; ilgisiz PR'da
"no-op, başarılı" (workflow düzeyinde `paths` yok — zorunlu check yapılabilir).

Tersine, ci.yml `test-local` yalnız Java web projesini değiştiren PR'da (`demo-app/e2e-java/**`,
`demo-app/ci/run-java-checks.sh`, `demo-app/ci/break-verify-java.sh` dışında `demo-app/` değişikliği
yoksa) no-op'tur: `changes` job'unda `predicate-quantifier: every` ile ayrı bir `app` süzgeci
(`demo-app/**` VE `!demo-app/e2e-java/**` VE bu iki dosyanın açık adları) koşar — `*java*` deseni
`*javascript*` adlarını da dışlardı (OPS-L1 tur 2); uygulama dışı tetikler (`.playwright-version`, `ci.yml`,
`toolchain/Dockerfile`, `toolchain/package*.json`, `scripts/github-demo-serve.sh`) `app_ek`
süzgecindedir. `demo-app/` altındaki diğer her değişiklik (api, web, e2e, e2e-app, kimlikler.json,
ci/run-checks.sh, …) TS testlerini tetiklemeye devam eder.

Artefakt `web-java-results`: `ci-meta.json` (`job: web-java`, `platform: web`, `dil: java`, `sha`,
`tetik`, `istek_id`, `durum`), `surefire-reports/TEST-*.xml`, `birim-raporlari/`, `allure-results/`,
`extent-report/index.html`, `kanit/<Sınıf>.<metot>/{ekran.png, trace.zip, sayfa.html}` (triage: web
yöntemi), `guard.json`, `logs/` (`serve.log`, `run-java-checks.log`). Koşu belirteci artefaktta maskelenir.

**Zorunlu check ve dil kapısı (011 K-T1, K-T3, K-T10).** `web-java` check'i `web-java.yml` demo
deposunda olduğu sürece **her zaman zorunludur** (K-T10; ilgisiz PR'da `changes` + no-op ile hızla
yeşil; core `github_required_checks` ekler). GitHub kipinde web + Java üretimi yalnız
`TP_WEB_DILLERI` `java` içerdiğinde açıktır: Kod üretimi ekranında Java seçilebilir olur ve paket koşularında (gece,
push, deploy) Java kardeş koşusu tetiklenir. `java` yoksa `/code/languages` Java'yı
`kullanilabilir=false` + neden ile döner ve kardeş koşu açılmaz (gelmeyen check'i saatlerce beklemez).
Açma sırası: (1) demo deposunda `web-java.yml`, `toolchain/java-araclar/`, `toolchain/e2e-java-deps/`
bulunmalı (`scripts/github-demo-repo-init.sh --push --update` bunları gönderir; CI'da güvenilir pom
yoksa `run-java-checks.sh` hata verir); (2) ruleset'e mevcut check'ler KORUNARAK eklenir
(`scripts/github-ruleset.sh --add-checks web-java`, önce kuru, sonra `--apply`; `--checks` listeyi
tümüyle değiştirir ve yazılmayan platform check'lerini siler) — eklenince açık PR'lar `web-java`'yı
bekler ama iş akışı ancak PR'a yeni olay (push/yeniden açma) gelince koşar: açık PR'lara boş commit
gönderin ya da Actions'tan yeniden tetikleyin; (3) `.env`'de `TP_WEB_DILLERI=ts,java` ve core yeniden
başlatılır. `TP_REQUIRED_CHECKS` elle yazılıyorsa ruleset ile aynı tutulur (`web-java` dahil).

Yerel (LocalForge) kipte check adları: web + TS `local-ci` (değişmez), **web + Java
`local-ci-web-java`**, uygulama `local-ci-<platform>` (tek kaynak `platform.check_adi(platform, dil)`).
Merge kuralı: `e2e-java/` değişen PR `local-ci-web-java`, `e2e/` değişen PR `local-ci` ister;
script'siz PR'da CI değişen yollardan dil(ler)i seçer (ikisi de değiştiyse ikisi de koşar; K-T11: test
kökleri dışında değişiklik varsa repodaki tüm tam hat dilleri). LocalForge'da `TP_WEB_DILLERI`
kullanılmaz; repodaki dosyalar belirler. `TP_REQUIRED_CHECKS`'e `local-ci-web-java` /
`local-ci-<platform>` YAZMAYIN: yapılandırılmış liste her PR'da zorunludur, o check'i hiç almayan
PR'lar kilitlenir; yol kuralı onları gerektiğinde ekler.

## Ruleset

`scripts/github-ruleset.sh` varsayılan olarak **kuru çalışır** (API çağrısı yapmaz, gövdeyi yazdırır):

```bash
scripts/github-ruleset.sh                       # kuru çalışma
scripts/github-ruleset.sh --repo ThinkGOtr/testingprobe --apply
```

İçerik: `main` için silme ve force-push yok; her değişiklik PR ile; 1 onay + CODEOWNERS onayı +
son push'tan sonra onay; zorunlu check'ler `test-local`, `ast-guard`, `semgrep` (kaynak GitHub Actions
uygulamasına sabit). Bypass yalnızca `demo-admin` org takımında (`bypass_mode: always`); repo
ruleset'leri bypass listesine tek tek kullanıcı değil takım/rol/App alır, bu yüzden `demo-admin` insan
hesabını içeren tek üyeli bir takım oluşturulmalıdır. Bot App bypass listesinde **yoktur**.

### Bot App izinleri ve çoklu PR (dal güncelleme / kapatma)

Bot GitHub App'i (`GH_APP_*`) depoda **Contents: write** (dal + commit) ve **Pull requests: write**
(PR açma, yorum, dal güncelleme, kapatma) izni ister; merge izni kullanılmaz (bot merge etmez).
`GitHubForge` LocalForge ile aynı sözleşmeyi sunar, kod üretimi aynı yoldan geçer:

- Bir bot PR'ı merge edilince (`sync_prs`) diğer açık bot PR'ları "main'in gerisinde" işaretlenir ve
  `codegen.update_branch` işi `PUT pulls/{n}/update-branch` (`expected_head_sha` = çekirdeğin bildiği
  head) çağırır. GitHub bunu asenkron işler; yeni head `GET pulls/{n}`'den beklenir ve eski head'in
  üstüne kurulmuş olmalıdır. Yeni head çekirdekte kaydedilir → PR CI yeniden koşar, insan onayı
  yenilenir (ruleset "son push'tan sonra onay"), kırarak doğrulama yeni head'de yeniden yapılır.
  Bu PR sonra GitHub'da merge edilirse "yabancı head" (`kabul_yabanci_head`) **sayılmaz**.
- Mühendisin GitHub arayüzündeki "Update branch" düğmesi yerine portalın "Dalı güncelle" eylemi
  kullanılmalıdır; GitHub arayüzünden yapılan güncelleme çekirdeğin üretmediği bir head'dir ve
  merge'ü yabancı head olarak işaretlenir.
- İnsan reddi / "değişiklik iste" ve yeniden üretimle yerine geçilen PR'lar `PATCH pulls/{n}
  state=closed` ile kapatılır (önce PR'a yorum yazılır).

Testler: `core/tests/unit/integrations/test_forge_github.py` (MockTransport) ve
`test_forge_github_codegen.py` (gerçek Postgres; codegen `sync_prs → update_branch → merge` ve
ret → kapatma yolları gerçek `GitHubForge` ile).

## Yerel doğrulama

```bash
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -color
docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable scripts/github-*.sh
(cd toolchain/ast-guard && npm ci --ignore-scripts && npm test)   # ci.yml + betik sözleşme testleri dahil
(cd core && uv run pytest -q tests/unit/integrations/test_forge_github_actions.py)  # GitHubForge Actions (MockTransport)
make playwright-surum-denetle   # Playwright sürüm sabitleri (TS, MCP, imaj, Java sürücü çekirdeği)
```

Playwright yükseltmesi: `docs/PLAYWRIGHT-YUKSELTME.md` (değişen dosyalar; Java `<playwright.version>`
npm sürümünden farklı olabilir, belirleyici sürücünün paketlediği çekirdektir).

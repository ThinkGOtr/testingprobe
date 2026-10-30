# CI (AI'sız) — GitHub Actions

TEKNIK-TASARIM §8.5 ve Constitution II'nin uygulaması. CI'da model anahtarı, MCP sunucusu veya
ajan bağımlılığı **yoktur**; yalnızca onaylanmış, deterministik test kodu koşar.

> Bu dosya `.github/README.md` değil, `CI.md` adını taşır: GitHub `.github/README.md`'yi repo
> ana sayfasında kökteki README'nin yerine gösterir.

## Workflow'lar

| Dosya | Tetik | Yetki |
|---|---|---|
| `workflows/ci.yml` | `pull_request`, `push` (main), gece `0 2 * * *` (02:00 UTC = 05:00 TR), `repository_dispatch` `deploy`, `workflow_dispatch` | `contents: read`, `packages: read` (`changes` job'una ek olarak `pull-requests: read`) |
| `workflows/build-toolchain.yml` | `toolchain/**`, `.playwright-version` değişikliği (main'e push → çok mimarili derleyip gönderir; PR → yalnızca amd64 derler), `workflow_dispatch` | `packages: write` **yalnızca burada** |

Her üçüncü taraf Action tam 40 karakterlik commit SHA'sıyla, sürüm yorumuyla sabitlenmiştir;
Semgrep imajı sürüm + digest ile sabitlenmiştir. `dependabot.yml` bunları aylık günceller.

## ci.yml job'ları

| Job | Zorunlu | Ne yapar |
|---|---|---|
| `changes` | — | PR'da `dorny/paths-filter` ile `demo-app/**`, `demo-app/e2e/pages/**`, `toolchain/ast-guard/**` (ve ilgili `scripts/github-*.sh`) değişikliğini tespit eder; tetik türünü (`pr`/`push`/`nightly`/`deploy`/`manual`) belirler. PR dışı olaylarda testler her zaman koşar. |
| `test-local` | **evet** | `demo-app/ci/run-checks.sh --retries=1`; sonuçları `test-local-results` artefaktına yükler. |
| `ast-guard` | **evet** | PR'da `toolchain/ast-guard`'ı `merge-base(base, head)..head` aralığında çalıştırır. |
| `semgrep` | **evet** | `semgrep/semgrep` konteynerinde `p/default` + `p/typescript`, token/hesap yok, `--metrics=off`. Kapsam: `demo-app/`, `toolchain/ast-guard/`. |
| `demo-serve-smoke` | hayır | Sauce'un uygulama başlatma yolunu (`scripts/github-demo-serve.sh --smoke`) kimliksiz doğrular: `/api/health` proxy üzerinden 200, izinli Host (`tp-demo.test`) kabul, izinsiz Host 403. |
| `golden-drift` | hayır | AI'sız, **saf veri** (anayasa II): `rules/replay` golden kayıtlarının kanıt satırları, case beklentileri, page object eşlemeleri ve §8.2b düzeltme döngüsünün son hali demo-app kaynağıyla tutarlı mı. `.github/golden-drift/` paketini `uv run --no-project --with-requirements requirements.txt` ile koşar (yalnız pytest + jsonschema + pyyaml); core venv'i, `tp_core.gateway`, `anthropic` ve `mcp` kurulmaz, ayrı bir adım bunlardan biri içe aktarılabiliyorsa job'u kırar. Gateway üzerinden replay ajan döngüsünü koşan `core/tests/unit/gateway/test_consistency_flow.py` yerel birim paketinde kalır. `demo-app/**`, `rules/**`, `docs/DEMO-VERISI.md` veya `.github/golden-drift/**` değişince koşar. |
| `sauce` | hayır (`continue-on-error`) | Aynı testleri Sauce Labs bulut Chromium'unda Sauce Connect tüneliyle koşar. |

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

Workflow ayrıca `results/ci-meta.json` yazar (`kaynak`, `tetik`, `sha`, `ref`, `run_id`, Playwright
sürümü, imaj). Çekirdek artefaktı GitHub API'den `test-local-results` adıyla alır.

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
- Job linkleri (`saucectl-report.json` ve log'dan) adım özetine yazılır; artefakt: `sauce-results`.
- Eşzamanlılık 1 (hesap 1–2 oturum).

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

## Yerel doğrulama

```bash
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -color
docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable scripts/github-*.sh
(cd toolchain/ast-guard && npm ci --ignore-scripts && npm test)
```

# toolchain

One Dockerfile, two targets. `ci` (default, last stage) serves `toolchain-worker` (:8100),
`test-runner` (:8200) and GitHub CI Path A (`test-local`); it contains **no MCP server**
(constitution II: no model key, MCP server or agent dependency in CI). `mcp` = `ci` + `/opt/mcp`
(`@playwright/mcp`, from `mcp/package{,-lock}.json`) and serves only `playwright-mcp` (:8931):
`docker build --target mcp`. `security/no-mcp-in-image.sh image <ref>|compose <service>` fails if
`require.resolve('@playwright/mcp')` (or the `mcp`/`anthropic`/`claude_agent_sdk` Python packages)
resolves in an image; run it on the CI image and on toolchain-worker/test-runner. HTTP API: MIMARI-SOZLESME §2 (details below). Base: `mcr.microsoft.com/playwright:v<.playwright-version>-noble`
(digest-pinned), so browsers come from the image (`/ms-playwright`) and exist only once.

## Playwright version unity (FR-012)

`@playwright/mcp@0.0.83` depends on `playwright@1.64.0-alpha-1790635538000`, whose browsers are
Chromium revision **1247**; the 1.64.1 base image ships revision **1248**, so the MCP could not
launch a browser out of the box. Choice: the `overrides` in `package.json` and `mcp/package.json`
(kept identical; `tests/test_review_fixes_p3.py` checks) force `playwright` and `playwright-core` to
**1.64.1**. Result: one `playwright-core` version per tree (`/opt/toolchain`, `/opt/mcp`), the
MCP reports server version `1.64.1` and uses `/ms-playwright/chromium-1248`; no extra browser
download (~+300 MB avoided). The build fails if the installed `playwright-core` differs from the
`PLAYWRIGHT_VERSION` build arg. When bumping `.playwright-version`, update `@playwright/test` and
the overrides in both manifests, run `npm install --package-lock-only` in `toolchain/` and
`toolchain/mcp/`, and re-check the MCP (`--target mcp`) with an
`initialize` + `browser_navigate` call.

Alternatives not taken: installing Chromium 1247 next to 1248 (disk, two browser versions);
`--executable-path` to the 1248 binary while keeping the alpha core (untested protocol pairing).

## playwright-mcp flags

`bin/playwright-mcp`: `--headless --browser chromium --host 0.0.0.0 --port 8931 --allowed-hosts "$MCP_ALLOWED_HOSTS"
--isolated --caps=testing --allowed-origins "$MCP_ALLOWED_ORIGINS" --output-dir /tmp/playwright-mcp`.

- `--browser chromium` is required: the default is the `chrome` channel (`/opt/google/chrome`), absent here.
- `testing` is not listed under `--caps` in `--help` (only vision, pdf, devtools) but is accepted
  and enables `browser_generate_locator` and `browser_verify_*`. No `vision`.
- `MCP_ALLOWED_ORIGINS` is mandatory (an empty value would mean "allow all"). Origins outside it
  fail with `net::ERR_BLOCKED_BY_CLIENT`; per upstream this is not a security boundary — network
  isolation (research R5) is.
- Endpoint: Streamable HTTP at `/mcp` (legacy SSE at `/sse`).
- `MCP_ALLOWED_HOSTS` (compose: `playwright-mcp:8931,playwright-mcp`; default
  `localhost:8931,127.0.0.1:8931`): Host header allowlist against DNS rebinding.
- Network: compose puts the service only on `demo-net` + `mcp-net` (shared with core-worker) and
  publishes no host port. The MCP exposes tools that cannot be switched off
  (`browser_run_code_unsafe`, `browser_evaluate`, ...); the network boundary limits what they can
  reach, and the core gateway refuses to hand them to an agent (`FORBIDDEN_TOOLS`).

## Image layout

| Path | Content |
|---|---|
| `/opt/toolchain/node_modules` | `@playwright/test`, axe, allure (`make e2e-smoke`, locator probe) — no MCP |
| `/opt/mcp/node_modules` | `@playwright/mcp` — **`mcp` target only** (`bin/playwright-mcp`) |
| `/opt/toolchain/bin/tp-run-lock` | runs a command under test-runner's run lock (see test-runner) |
| `/opt/toolchain/ast-guard/{dist,node_modules}` | ast-guard CLI, built in the `nodebuild` stage (same pinned base) |
| `/opt/toolchain/symbols/{dist,node_modules}` | ts-morph symbol extractor (`symbols/`, built in `nodebuild`) |
| `/opt/toolchain/probe/locator-probe.mjs` | Locator probe (Playwright `chromium`, image browsers) |
| `/opt/e2e/{package.json,package-lock.json,eslint.config.js,node_modules}` | demo-app e2e deps, offline, read-only. Built from `e2e-deps/`, a byte copy of `demo-app/e2e`'s manifests (`tests/test_e2e_deps.py` fails on drift: copy the files and rebuild) |
| `/artifacts` | mount point owned by `pwuser`: an empty named volume takes this ownership on first mount |

No model SDKs, no network installs at run time.

## HTTP API

All endpoints are **synchronous and bounded** (no job ids): each subprocess has its own timeout and
is killed with its whole process group on expiry. Errors are `{"detail": "<Türkçe>"}`; invalid input
is 422, unknown commit 404, busy 409, forge unreadable 503. `sha` accepts a full/short hex sha or a
safe ref name (`main`, `tp/case-…`); responses always carry the resolved full sha.

### toolchain-worker (:8100)

**Auth:** every endpoint except `/health` requires `Authorization: Bearer $TP_TOOLCHAIN_TOKEN`
(constant-time compare; 401 otherwise, checked before body validation). Give the token only to
core-api and core-worker, **never** to test-runner: test-runner sits on runner-net with this
service and runs untrusted commit code, which could otherwise call `/check` and get the merge gate
written. Empty token → endpoints open and `/health` `auth: ok (uyarı: …)`; empty token with
`TP_TOOLCHAIN_REQUIRE_TOKEN=1` → 503 and `auth: error`.

- `POST /symbols {sha}` → `{sha, schema_version, root:"pages", page_objects:[{class, file, doc,
  methods:[{name, params:[{name,type,optional,default?}], returns, kind:"action"|"expect", async, doc, line}],
  locators:{"<export>.<key>": {testId, role, name, intent, within?, prefix, file, line}}}],
  locator_files:[{file, exports}], errors:[{file, line?, message}]}`. Public, non-static methods only;
  `kind` = `expect` iff the name starts with `expect`. `locators` = entries of the locator exports the
  class file imports (CatalogPage gets `catalog.*` and `nav.*`). Code is only parsed (ts-morph), never
  run; non-pure locator values are skipped and listed in `errors`. Cached per sha (commits are immutable).
- `POST /ast-guard {base_sha, head_sha, mode?: "repair"(default)|"pr"}` → `{ok, violations, base_sha,
  head_sha, mode, report}` (`report` = full ast-guard JSON). Runs the CLI in git-ref mode directly on
  the bare forge (`--repo $TP_FORGE_PATH --root e2e`), which reads the same trees two checkouts would.
- `POST /check {sha, test_files?, repeat_each=3, retries=0, env?:{BREAK_CAMPAIGN}, break?, grep?,
  base_sha?, ast_guard_mode="pr", run_id?, record_check?: bool|null, keep?: bool}` → `{sha,
  conclusion:"success"|"failure", ok, failed_steps, summary, saglik, failures, failure_groups,
  test_counts, deps, tsc, eslint, ast_guard, run:{…/run response…, junit_path, json_path}, kapsam,
  check_recorded, checks_path, break_campaign, duration_ms}`. Steps, stopping at the first failure
  (like `ci/run-checks.sh`): every `test_files` entry exists in the commit (else `deps` fails with
  `missing_test_files`) → lockfile equals the image's → `tsc --noEmit` (whole `tsconfig.json`, which
  includes `tests/**/*.ts`, so `tests/generated/*.spec.ts` is compiled) → `eslint --no-inline-config
  --max-warnings=0 .` (the generated-test rules of `eslint.config.js` apply to `tests/generated/**`)
  → ast-guard `pr` against `base_sha` (default: merge-base with `main`, i.e. `main` as the PR saw
  it) → test-runner `/run` with `test_files`/`grep`/`repeat_each`/`retries`/`keep`.
  - `saglik`, `failures`, `failure_groups` are lifted from the run (null/[] when no run happened):
    the inputs for the codegen decision (TEKNIK-TASARIM §8.4 step 5: locator/mapping → one repair
    round; assertion → "defect adayı", no repair) and Phase 4 triage (§8.6). See "Failure inputs".
  - **Single writer of `TP_ARTIFACTS_PATH/checks/<full sha>.json`** (core only reads it via
    `LocalForge.checks()`): `{"schema_version":1, "sha", "guncelleme", "checks":[{"name":"local-ci",
    "status":"in_progress"|"completed","conclusion":…,"url":null}], "report":{…}}` — `in_progress`
    first, `completed` at the end, `failure` on any unexpected exception. Which checks are recorded
    (`record_check`): `null` (default) → only a **full-scope** check (no `test_files`, no `grep`) —
    the local equivalent of the PR CI that runs every test; `true` → same, and **422 with
    `test_files`/`grep`** (a scoped green run must never pass the gate: LocalForge looks only at
    `conclusion`); `false` → never. Scoped requests are never recorded even if the API is bypassed
    (`CheckRequest.records_check()`), and every recorded CheckRun carries `"tam": true`. A `break`
    check is a deliberate red run and is **never** recorded (`record_check:true` with break → 422). Recommended codegen use: scoped
    `repeat_each=3, record_check=false` to decide, then a full check (`repeat_each=1, retries=1`,
    CI parity) on the PR head for the merge gate.
  Client timeout: ≥ `TP_RUN_TIMEOUT_S + TP_RUN_QUEUE_WAIT_S` + static steps (~25 min with defaults).
- `POST /runs/release {run_ids:[…]}` → `{released:[…]}`: removes the `.keep` marker of evidence runs
  whose owner (codegen script) is closed/failed; the run then ages out with `TP_RUNS_KEEP`.
  Idempotent; unknown ids are ignored.
- `POST /locator-probe {sha, role, name, url_path, scope_test_id? (alias within_test_id)}` →
  `{matches, test_id|null, test_ids, test_id_raw, scope_test_id, scope_matches, sha, app_url, url_path,
  final_path, http_status, oneri_uretilebilir, olculen, uygulama_sha, sha_eslesmesi, uyari}`. Opens `DEMO_WEB_URL + url_path` (logged in as
  `TP_PROBE_USER`, default `bayi1`, except under `/giris`), waits ≤5 s for the first match, counts
  `getByRole(role, {name})` (inside `getByTestId(scope_test_id)` when given), reads `data-testid` on a
  single match. The browser may only request the app origin. `test_id` is returned only if it matches
  the testId grammar; `oneri_uretilebilir` = exactly one match with a valid testId (§8.7: 0 or >1 → human).
  **Measured on the running app, not on `sha`:** `olculen` is always `"calisan_uygulama"`. The
  running app's build commit (see "Running app vs commit") is compared with `sha` by app tree:
  `sha_eslesmesi` = `eslesiyor` | `farkli` (then `oneri_uretilebilir=false`, Turkish `uyari`,
  `farkli_yollar`) | `dogrulanamadi` (build sha unknown or not in forge; `uyari` set, suggestion
  still allowed). Phase 4 repair records must store `olculen`, `uygulama_sha`,
  `sha_eslesmesi`, `uyari` verbatim. Pages
  whose target only exists after earlier steps (e.g. a filled cart) yield 0 matches.

### test-runner (:8200)

- `POST /run {sha, run_id, grep?, repeat_each=1, retries=0, env?:{BREAK_CAMPAIGN:"1"}, break_campaign?,
  test_files?, workers?, keep?}` → `{run_id, sha, status:"passed"|"failed"|"error", error, exit_code,
  duration_ms, junit, json, allure_dir, html_dir, traces_dir, log, artifacts_dir, artifacts_rel,
  reports, stats:{expected,unexpected,flaky,skipped,duration_ms}, tests:[{id,title,file,line,column,
  project,status,tags,repeat_index,attempts,attempt_results,duration_ms,error,failure,attachments}],
  failures, failure_groups, report_errors, break_restore, saglik, cleanup}` (see "Failure inputs").
- `saglik` = pre-run health check (TEKNIK-TASARIM §8.6, triage rule 1 → `environment`):
  `{ok, zaman, web:{url,status,ms,hata}, api:{url,status,ms,hata}, hata}`; probes `GET BASE_URL/` and
  `GET DEMO_API_URL/health` (`TP_HEALTH_TIMEOUT_S`, default 5 s; ok = both 2xx). On failure Playwright
  is **not** started, `status:"error"`, `error` = `saglik.hata` (Turkish), `exit_code:null`, `tests:[]`,
  no `src/` copy, no break restore (nothing was broken). `status:null` + `hata:<ExceptionName>` = network error.
- One run at a time (bayi1/bayi2 are shared); a queued request waits ≤ `TP_RUN_QUEUE_WAIT_S`, then 409.
- Layout: `runs/<run_id>/run.json` (summary; `running` while in progress), `runner.log`,
  `src/e2e/` = exact copy of the commit's `e2e/` (evidence), Playwright reports where the commit's
  config puts them: `src/e2e/results/{junit.xml,results.json,allure-results/,html/,artifacts/}`.
  `reports:{html,junit,json,allure,allure_html}` = `{path, rel, exists}` (`rel` relative to `TP_ARTIFACTS_PATH`;
  core mounts the same volume read-only). A reused `run_id` is 409 (evidence is immutable). A
  committed `results/` is deleted before the run.
- Cleanup: after each run only the newest `TP_RUNS_KEEP` (default 50, `0` = off) unmarked run
  directories are kept (by `run.json` mtime, this run included). Runs with a `.keep` marker
  (request `keep:true`; break-verify and triage evidence) are a separate pool, bounded too: older
  than `TP_RUNS_KEEP_EVIDENCE_DAYS` (30) days or beyond the newest `TP_RUNS_KEEP_EVIDENCE_MAX`
  (200) are deleted (`0` = that bound off); core can release them earlier (`POST /runs/release`).
  Never deleted: this run, runs still `running` and younger than 2 × `TP_RUN_TIMEOUT_S`, symlinks
  and names that are not run ids. Result in `cleanup` (`deleted`, `deleted_evidence`).
- One run at a time: in-process `RUN_LOCK` + a cross-process `flock` on `TP_RUN_LOCK_PATH`
  (`/tmp/testingprobe-run.lock`). Anything started by hand in the container (`make e2e-smoke`) must
  take the same lock: `docker compose exec -T test-runner tp-run-lock --wait 600 -- <command>`
  (exit 75 when the wait expires). Runs share dealers bayi1/bayi2, so overlap would reset carts or
  leak `BREAK_CAMPAIGN` into another run.
  `checks/*.json` reports may then point at deleted run paths.
- Playwright gets only `PATH/HOME/LANG/…`, `BASE_URL`, `DEMO_API_URL`, `DEMOAPP_TEST_TOKEN`, `CI=1`,
  `BREAK_CAMPAIGN`, `TP_RUN_ID`. With `BREAK_CAMPAIGN=1` the e2e fixture breaks the campaign for the
  run's dealers via `/test/break`; afterwards the runner **always** (failure, timeout) calls
  `/test/break {kampanya:false}` for each of `TP_RUN_DEALERS` (bayi1,bayi2); if that fails the run is `error`.
- Status: `failed` = some test unexpected; `error` = health check failed, timeout, no/corrupt report, report-level errors,
  no test ran, non-zero exit without failures, or break not restored; else `passed` (flaky counts as passed, see `stats.flaky`).

- Allure report: after every run, `allure-results/` is turned into a static single-file Allure
  report `results/allure-report/index.html` (`reports.allure_html`; the portal's "Allure raporu"
  link should point here, raw `allure-results` stays a secondary link). Generator: the pinned Allure
  3 CLI in the image (`/opt/allure`, `allure2` plugin, `singleFile`, `ALLURE_NO_ANALYTICS=true`),
  run with the image's trusted `allurerc.mjs` in a temp dir (no commit config, no network, no AI).
  A report referencing an external script/style is deleted. Failure to generate never changes the
  run status; it is reported in `allure_report.error`.

### Running app vs commit (`app` step of `/check`)

Local `/check` runs the commit's e2e code against the **running** compose demo-app-web, while
GitHub CI starts the app from the checkout (`webServer`). The running app's build commit is read
from `TP_APP_BUILD_SHA_FILE` (default `/forge/demo-app-web.sha`, written by the scripts that build
or sync demo-app-web), else `DEMO_APP_BUILD_SHA`. Its app trees (`TP_APP_PATHS`, default `web,api`)
are compared by git tree id with the requested commit's: equal → `eslesiyor` (an e2e-only codegen
branch matches `main`); different → step `app` fails with "Uygulama commit ile eşleşmiyor", no
run, `local-ci` = `failure` (validate such PRs in GitHub CI or after rebuilding the app from that
commit); unknown → `dogrulanamadi`, step passes with a warning unless `TP_CHECK_REQUIRE_APP_SHA=1`.

### GitHub mode (same code path)

With `TP_FORGE=github` core gets shas from GitHub that the local bare forge does not have. If
`TP_FORGE_REMOTE_URL` (+ read-only `TP_FORGE_REMOTE_TOKEN`, sent as an `http.extraHeader` via env,
never argv) is set, toolchain-worker fetches the missing commit (and `main`) into the mirror
`TP_FORGE_MIRROR_PATH` (default `/forge-mirror/demo-app.git`; `git fetch` only, https/file
protocols only). `/symbols`, `/ast-guard`, `/check` and `/locator-probe` resolve shas in the forge
first, then the mirror; test-runner reads the same mirror read-only and never fetches. Responses
carry `kaynak: "forge"|"ayna"`. Without a remote URL an unknown sha is 404, as before.

### Failure inputs (`tests[].failure`, `failures`, `failure_groups`)

Deterministic, model-free inputs extracted from the Playwright JSON report (untrusted: clipped,
ANSI stripped, attachment paths only inside the run dir). **No decision is made here**; `type` is
the formal shape of the error, the class (defect candidate / maintenance / environment) is core's.

- `tests[]` gains `column`, `repeat_index` (`--repeat-each` repetitions are separate entries with
  different Playwright ids), `attempt_results:[{retry,status,duration_ms,type}]` and `failure`
  (first non-passing attempt, else null). Tags come without `@` (Playwright JSON).
- `failure = {type, message, messages, first_line, matcher, action, locator, expected, received,
  timeout_ms, signals[], location, test_location, step, attempt, status, evidence, aria_snapshot,
  aria_snapshot_scope}`:
  - `type` (first rule wins): `test_data` (error located in `tests/fixtures.ts` or a known fixture
    message: `/test/reset|break` failed, missing token) · `navigation` (`page.goto/reload…`,
    `net::ERR_*`) · `locator_ambiguous` (strict mode) · `locator_not_found` (`expect(locator)` timed
    out with "element(s) not found") · `locator_timeout` (an action such as `locator.click` timed out
    waiting for a locator, also under the test timeout) · `assertion` (matcher failed on a found
    element / value: expected ≠ received) · `test_timeout` · `other`.
  - `location` = Playwright `errorLocation` relative to `e2e/` (for page object `expect*` methods
    this is `pages/**.page.ts`); `test_location` = first stack frame in `tests/**.spec.ts` (the
    generated test's line = the case step); `step` = deepest failing `test.step` title/path or null.
  - `evidence = {trace, error_context, screenshot, video}`, each `{path, rel, exists}` or null.
  - `aria_snapshot`: YAML from `error-context.md` (≤ 8000 chars), scope `page` ("# Page snapshot")
    or `error_details` (expect failures embed it under the error).
- `failures` = `unexpected`/`flaky` entries (one per repetition). `failure_groups` = repetitions
  merged by file+line+column+title+project: `{ids, title, file, line, project, tags, repeats,
  statuses:{expected:n,…}, types[], failure, consistent}`; `consistent` = every repetition
  `unexpected` with one type (e.g. 3/3 `assertion` → defect candidate); mixed results are not.
- Fixtures for these rules are real Playwright 1.64.1 reports: `tests/data/pw_1_64_*.json`.

### Environment (defaults)

`TP_FORGE_PATH` (/forge/demo-app.git), `TP_ARTIFACTS_PATH` (/artifacts), `TP_E2E_ROOT` (e2e),
`TP_E2E_DEPS` (/opt/e2e), `TOOLCHAIN_HOME` (/opt/toolchain), `TEST_RUNNER_URL`, `BASE_URL`,
`DEMO_API_URL`, `DEMOAPP_TEST_TOKEN`, `DEMO_WEB_URL` (http://demo-app-web:8080, probe target),
`TP_PROBE_USER`/`TP_PROBE_PASSWORD` (bayi1 / Demo123!, DEMO-VERISI.md), `TP_RUN_DEALERS`.
Timeouts (s): `TP_GIT_TIMEOUT_S` 60, `TP_TSC_TIMEOUT_S` 180, `TP_ESLINT_TIMEOUT_S` 240,
`TP_AST_GUARD_TIMEOUT_S` 60, `TP_SYMBOLS_TIMEOUT_S` 60, `TP_PROBE_TIMEOUT_S` 60,
`TP_RUN_TIMEOUT_S` 900, `TP_HEALTH_TIMEOUT_S` 5, `TP_RUN_QUEUE_WAIT_S` 600, `TP_CHECK_QUEUE_WAIT_S` 900.
Retention: `TP_RUNS_KEEP` 50, `TP_RUNS_KEEP_EVIDENCE_DAYS` 30, `TP_RUNS_KEEP_EVIDENCE_MAX` 200.
Run lock: `TP_RUN_LOCK_PATH` (/tmp/testingprobe-run.lock). Auth: `TP_TOOLCHAIN_TOKEN` (empty),
`TP_TOOLCHAIN_REQUIRE_TOKEN` (0). Merge gate: `TP_CHECKS_PATH` (empty → `TP_ARTIFACTS_PATH/checks`),
`TP_CHECKS_REQUIRE_MOUNT` (0). App match: `TP_APP_BUILD_SHA_FILE`, `DEMO_APP_BUILD_SHA`,
`TP_APP_PATHS` (web,api), `TP_CHECK_REQUIRE_APP_SHA` (0). GitHub mirror: `TP_FORGE_REMOTE_URL`,
`TP_FORGE_REMOTE_TOKEN`, `TP_FORGE_MIRROR_PATH`, `TP_FETCH_TIMEOUT_S` 120. Allure: `TP_ALLURE_CLI`,
`TP_ALLURE_CONFIG`, `TP_ALLURE_TIMEOUT_S` 120.

### Security notes

- toolchain-worker never runs test code. tsc only parses. ESLint *loads* `eslint.config.js` as code,
  so the commit's config must be byte-identical to the image's trusted copy, else the step fails
  without starting ESLint. A committed `e2e/node_modules` is replaced by a link to the image deps.
- Checkout = `git archive` + `tarfile` `filter="data"` (no absolute paths, no links leaving the tree).
- Merge gate isolation: `checks/<sha>.json` is written only by toolchain-worker. It must live on
  its own volume (`TP_CHECKS_PATH=/checks`, `tp_checks`), mounted rw only in toolchain-worker, ro
  in core, and **not at all** in test-runner (which executes commit code as the same uid). Health:
  toolchain-worker `checks_volume` (error when not a mount and `TP_CHECKS_REQUIRE_MOUNT=1`, and
  `/check` then refuses to record, 503); test-runner `checks_hidden`. `security/checks-isolation.sh`
  is the `make security-check` item that proves test-runner cannot write the gate on a live stack:
  besides the mounts and a canary write it requires `TP_TOOLCHAIN_TOKEN` in toolchain-worker and
  absent from test-runner, and POSTs `/check` from test-runner (scoped `record_check:true` and full
  scope, dummy sha): the answer must be 401 (422 accepted for the scoped one) or unreachable.
- PID 1 in every toolchain container is `tini -s -g` (image `ENTRYPOINT`), so Chromium helper
  processes re-parented to PID 1 are reaped (no zombie build-up in test-runner / playwright-mcp).
- All inputs are validated before reaching argv (no shell): refs/run ids/test files reject leading
  `-`, `..`, control characters; grep is passed as `--grep=<value>`.

## Tests

```bash
uv run ruff check && uv run ruff format --check && uv run pytest   # Python (real git, fake/real node)
cd symbols && npm ci --ignore-scripts && npm test                   # extractor, node:test on demo-app/e2e/pages
cd ast-guard && npm ci --ignore-scripts && npm test
```

The pytest suite builds a temporary bare forge from `demo-app/e2e`. With `node`, built `ast-guard`/
`symbols` and `demo-app/e2e/node_modules` present, it also runs real tsc/eslint/ast-guard/extractor
(otherwise those tests are skipped).

## Python

`pyproject.toml` + `uv.lock` (Python 3.12 from the base image, `uv sync --frozen`); `uv` is only
mounted at build time. No model SDKs (constitution II). `/health` per
`specs/001-dev-foundation/contracts/health.md`: `playwright` compares the installed
`playwright-core` with env `PLAYWRIGHT_VERSION` (503 on mismatch or if unset).

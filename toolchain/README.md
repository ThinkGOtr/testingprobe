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
  base_sha?, ast_guard_mode="pr", run_id?, record_check?: bool|null, keep?: bool, affected_by?:
  [e2e-relative paths | "@diff"]}` → `{sha,
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
    "status":"in_progress"|"completed","conclusion":…,"url":null}], "report":{…}, "reports":{name:…}}`.
    Check names are **per platform** (spec 009 §2.7): web/TS `local-ci` (unchanged), Java
    `local-ci-android|ios|windows` (`/check` with `lang:"java"` requires `platform`). A write only
    replaces its own entry; other platforms' entries are kept (`report` = last written). `in_progress`
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
  - **Affected tests (Phase 4 repair, §8.7 "local check on all affected tests"):** `affected_by`
    lists changed e2e sources (`pages/catalog/locators.ts`) or `"@diff"` (`base_sha`, default
    merge-base with `main`, `..sha`). Inside the checkout it is turned into `test_files` with the
    same import graph as `/affected-tests` (unknown → full suite). Result in
    `kapsam.etkilenen`. Scoped like `test_files`: never recorded as `local-ci`; 422 together with
    `test_files`, `grep` or `record_check:true`. Recommended repair use: `{sha: <tp/repair-* head>,
    base_sha: <main>, ast_guard_mode: "repair", affected_by: ["@diff"], repeat_each: 1,
    record_check: false}`; the PR's full `ci.run` then writes the gate.
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
  **Phase 4 additions** (optional request fields, response superset):
  - `candidate_test_id` (alias `test_id`): the repair candidate (e.g. `cart-add`). Response `aday =
    {test_id, matches, rol_ad_eslesen, gecerli, yoklanan_ile_ayni}`: `gecerli` = the candidate
    resolves to exactly one element inside the scope **and** that element has the same role + name
    (`getByTestId(c).and(getByRole(role,{name}))`).
  - `aria_snapshot_rel`: a reference aria snapshot under `TP_ARTIFACTS_PATH/runs/` (an
    `error-context.md` or a `.yml/.yaml/.aria` file, e.g. stored from a green run). Response
    `aria_dogrulama` = `/aria-match` result for `role`+`name` (§8.7 validation: the candidate must
    match role + name of the last green snapshot). Invalid path → 422 before the browser starts.
  - Always: `page_matches` (role + name count on the whole page when scoped: tells "wrong
    container" from "element missing"), `aria_snapshot` (≤ 8000 chars, of the scope container when
    it resolved to one element, else of `body`; `aria_snapshot_scope: scope|page`; untrusted data,
    may be stored as evidence), `engeller` (Turkish reasons that block a suggestion).
  - `oneri_uretilebilir` = `engeller == []`: exactly one match with a valid testId, sha not
    `farkli`, and — only when requested — `aria_dogrulama.var` and `aday.gecerli`.
- `POST /aria-match {role, name, aria_snapshot_rel | aria_snapshot, scope_role?, scope_name?}` →
  `{kaynak_rel, rol, ad, kapsam, eslesen, tam_eslesen, var, yollar, dugum_sayisi}`. Deterministic
  search of Playwright aria YAML (`toolchain_common/aria.py`): `eslesen` uses `getByRole`'s default
  name rule (whitespace-normalised, case-insensitive substring), `tam_eslesen` exact; `scope_*`
  restricts to descendants of a container node (e.g. `article "Portakal Gazozu"`). Triage rule 3
  input ("element with role + name exists on the page"). Exactly one source; files only under
  `runs/`, no symlinks, ≤ 2 MB.
- `POST /trace-summary {trace_rel, role?, name?, scope_test_id?}` → `{trace_rel, test_id_ozniteligi,
  uyeler, eylemler[{call_id, metot, secici, secici_test_ids, hata}], basarisiz_eylem{…, log},
  dom{call_id, faz, cerceve_url, kismi, yaklasik, elemanlar[{test_id, tag, rol, ad,
  kapsam_test_ids}]}, rol_ad{eslesen, test_ids, test_id, yaklasik}}`. §8.7 alternative source:
  reads the DOM snapshot of the failing action from `trace.zip` (no re-run) and lists the
  `data-testid` elements with their container chain, so `button "Sepete ekle"` inside
  `product-card-P-001` → `cart-add` can be found offline. Role/name are an **approximation**
  (implicit-role table + aria-label/labelledby/label[for]/text), marked `yaklasik:true`; the
  running-app probe stays primary. Safety: the zip is never extracted to disk; only top-level
  `*.trace` members are read, with limits on archive size (200 MB), members (5000), member size
  (64 MB), compression ratio (200), events (200k), DOM nodes (100k) and depth; self-references in
  the compressed snapshot format are ignored (`kismi:true`). Output strings are clipped.
- `POST /affected-tests {sha, changed?:[e2e-relative paths], base_sha?}` → `{sha, yontem:
  "import_grafi", kaynak, test_files, tam_kapsam, tam_kapsam_nedeni, dosya_sayisi}`: spec files that
  import the changed sources directly or transitively (`worker/affected.py`; text parse of
  `import/export … from`, `import()`, `require()`, relative specifiers only, `.js`→`.ts`,
  `index.ts`). `base_sha` adds `git diff base..sha` under the e2e root. If a changed file is unknown
  or nothing imports it → `tam_kapsam:true` (callers run everything: more tests, never a false
  green). With today's demo e2e every spec imports `tests/fixtures.ts` → `pages/index.ts`, so a
  `locators.ts` change affects all specs.

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

#### Java / Appium runs (spec 009 §2.7, `runner/java_run.py`)

- `POST /run {…, lang:"java", platform:"android"|"ios"|"windows"}` — `platform` is required with
  `lang:"java"` and rejected with `lang:"ts"` (default; the old body is unchanged). `test_files`
  are e2e-app relative `src/test/java/**/<Name>Test.java`; `grep` and `workers` are 422 for Java.
- Same lock, run directory contract, break restore (`/test/break {kampanya:false}` for every
  `TP_RUN_DEALERS`), cleanup and Allure report as Playwright runs. The commit's
  `TP_E2E_APP_ROOT` tree (`e2e-app`, GitHub mode `demo-app/e2e-app`) is copied to
  `runs/<id>/src/e2e-app/`.
- Hardening = toolchain-worker's Java compile path: the commit's `mvnw`/`ci/run-app-checks.sh` are
  **not** executed; the image's pinned Maven (`TP_MVN`) runs offline (`-o`), the warmed repo is a
  read-only `maven.repo.local.tail`, the writable head repo is a per-run temp dir, `pom.xml` and
  `.mvn/` must match the trusted copy (`worker.java.check_deps`, else `error` without running
  Maven), `-Dmaven.compiler.proc=none`, environment is an allow-list (no `MAVEN_*`,
  `JAVA_TOOL_OPTIONS`, …; `MAVEN_SKIP_RC=1`).
- Per repeat (`repeat_each`, sequential): `mvn … [test-compile] surefire:test -Dplatform=<p>` with
  `-Draporlar.dizini`, `-Dkanit.dizini`, `-Dallure.results.directory` per repeat; `test_files` →
  `-Dtest=<path>` (testng.xml ignored), otherwise `testng.xml` (testler + uretilen). Device-free
  unit tests (`birim`) are not run here (GitHub workflows run them via `run-app-checks.sh`).
  `retries` has no Java equivalent: ignored, reported as `retries_yok_sayildi:true`.
- Health (`saglik`): `{ok, zaman, web:null, api, appium, hata}` — `GET DEMO_API_URL/health` and
  Appium `GET APPIUM_URL_<PLATFORM>/status`; failure → `error`, Maven never starts.
- Maven env: `PLATFORM`, `APPIUM_URL`, `DEMO_API_URL`, `DEMOAPP_TEST_TOKEN`, `BREAK_CAMPAIGN`,
  `TP_RUN_ID`, `CI=1` and the app/device settings from `TP_APP_ID_<P>` (default
  `com.antreklabs.bayisiparis` for android/ios), `TP_APP_PATH_<P>` (path on the **Appium host**),
  `TP_APP_ACTIVITY_<P>` (android default `.MainActivity` when no path), `TP_APP_ARGS_<P>`,
  `TP_DEVICE_NAME_<P>`, `TP_DEVICE_UDID_<P>`, `TP_PLATFORM_VERSION_<P>` → e2e-app `APP_ID`, ….
- Result: Surefire `TEST-*.xml` (untrusted: DTD/entities rejected, size-bounded) → the same
  `{stats, tests, failures, failure_groups}` shape as Playwright (`runner/surefire.py`), plus one
  clean `runs/<id>/results/junit.xml` (`junit`; core's JUnit input; `json` is `null`). Extra keys:
  `surefire_dir`, `kanit_dir`, `appium_url`, `compile_diagnostics` (javac errors when Maven failed
  without a report), `kirmizi_denetimi` (break runs: `{ok, kirmizi, kotu}` — the
  `araclar/KirmiziDenetimi.java` rule: every red test is an assertion, at least one red; setup,
  locator, other errors and skipped tests are not "red"). `reports:{junit,surefire,allure,allure_html,kanit}`.
- `failure.type` (same set as Playwright): `assertion` (`<failure type=java.lang.AssertionError>`,
  `Bekle.dogrula`; `expected`/`received`/`timeout_ms` parsed), `locator_not_found` (Timeout "öğe
  görünmedi: kimlik …" / NoSuchElement), `locator_timeout` (other TimeoutException), `test_data`
  (`/test/`, login, token, cart-reset setup messages), `other`. `locator_test_id` /
  `locator_scope_test_id` come from the `kimlik '…'` text; `page_location` is the first
  `ekranlar/` stack frame; `evidence.screenshot` / `evidence.page_source` (+ `page_source_rel`) are
  `target/kanit/<Class>.<method>/{ekran.png,sayfa-kaynagi.xml}`.
- Network: Appium runs on the host; test-runner reaches it **only** through `appium-gw`
  (compose profile `mobil`, see `docs/CIHAZ-ALTYAPISI.md` §5.1).

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
  - Phase 4 shortcuts: `locator_test_ids` (all testIds in the locator chain), `locator_test_id`
    (the last one = the element looked for; `null` when the chain ends in `getByRole`),
    `locator_scope_test_id` (the one before = container, e.g. `product-card-P-001`),
    `locator_role`/`locator_name` (final `getByRole`), `aria_snapshot_rel` / `trace_rel`
    (`TP_ARTIFACTS_PATH`-relative, ready for `/aria-match`, `/trace-summary`), `page_location`
    (first frame under `pages/`, e.g. `pages/catalog/catalog.page.ts` → repair scope). After
    `make break` the add-to-cart step yields `type: locator_timeout`, `locator_test_id:
    "add-to-cart"`, `locator_scope_test_id: "product-card-P-001"`.
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
npm ci --ignore-scripts && npm test                                  # locator-probe.mjs, real Chromium
```

`probe/test/locator-probe.test.mjs` serves a local copy of the catalog markup after `make break`
(`cart-add`) and runs the real probe: scoped single match, unscoped double match, stale candidate,
wrong-role candidate, missing container, failed login. pytest runs it too when
`toolchain/node_modules` exists (`test_locator_probe_script_with_real_browser`). In the image:
`docker run --rm testingprobe-toolchain:local sh -c 'cd /opt/toolchain && node --test probe/test/*.test.mjs'`.
`tests/data/pw_1_64_trace_locator.zip` is a real Playwright 1.64.1 trace of the same failure
(scoped click on `add-to-cart` after the rename; local paths replaced).

The pytest suite builds a temporary bare forge from `demo-app/e2e`. With `node`, built `ast-guard`/
`symbols` and `demo-app/e2e/node_modules` present, it also runs real tsc/eslint/ast-guard/extractor
(otherwise those tests are skipped).

## Python

`pyproject.toml` + `uv.lock` (Python 3.12 from the base image, `uv sync --frozen`); `uv` is only
mounted at build time. No model SDKs (constitution II). `/health` per
`specs/001-dev-foundation/contracts/health.md`: `playwright` compares the installed
`playwright-core` with env `PLAYWRIGHT_VERSION` (503 on mismatch or if unset).

## app-mcp (mobile / desktop agent tool, spec 009)

`app-mcp/` is a separate Node + TypeScript MCP server (own `Dockerfile`, image
`testingprobe-app-mcp:local`, compose service `app-mcp` under profile `mobil`). It is not part of the
`ci`/`mcp` targets above and never enters the CI or test-runner image. Tools, snapshot format,
networking and the local device scripts: `docs/CIHAZ-ALTYAPISI.md`.

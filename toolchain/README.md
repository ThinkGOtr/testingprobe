# toolchain

Single image (`testingprobe-toolchain:local`) shared by `toolchain-worker` (:8100), `test-runner`
(:8200) and `playwright-mcp` (:8931). HTTP API: MIMARI-SOZLESME §2 (details below). Base: `mcr.microsoft.com/playwright:v<.playwright-version>-noble`
(digest-pinned), so browsers come from the image (`/ms-playwright`) and exist only once.

## Playwright version unity (FR-012)

`@playwright/mcp@0.0.83` depends on `playwright@1.64.0-alpha-1790635538000`, whose browsers are
Chromium revision **1247**; the 1.64.1 base image ships revision **1248**, so the MCP could not
launch a browser out of the box. Choice: `package.json` `overrides` force `playwright` and
`playwright-core` to **1.64.1** for the whole tree. Result: one `playwright-core` in the image, the
MCP reports server version `1.64.1` and uses `/ms-playwright/chromium-1248`; no extra browser
download (~+300 MB avoided). The build fails if the installed `playwright-core` differs from the
`PLAYWRIGHT_VERSION` build arg. When bumping `.playwright-version`, update `@playwright/test` and
the overrides in `package.json`, run `npm install --package-lock-only`, and re-check the MCP with an
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
| `/opt/toolchain/node_modules` | `@playwright/mcp`, `@playwright/test`, axe, allure (MCP + `make e2e-smoke`) |
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
  base_sha?, ast_guard_mode="pr", run_id?}` → `{sha, conclusion:"success"|"failure", ok, failed_steps,
  summary, deps, tsc, eslint, ast_guard, run:{…/run response…, junit_path, json_path}, checks_path,
  duration_ms}`. Steps, stopping at the first failure (like `ci/run-checks.sh`): lockfile equals the
  image's → `tsc --noEmit` (diagnostics parsed) → `eslint --no-inline-config --max-warnings=0`
  (JSON messages) → ast-guard `pr` against `base_sha` (default: merge-base with `main`) → test-runner
  `/run`. Writes `TP_ARTIFACTS_PATH/checks/<full sha>.json` = `{"checks":[{"name":"local-ci",
  "status":"in_progress"|"completed","conclusion":…,"url":null}], "report":{…}}` — `in_progress` first,
  `completed` at the end, and `failure` on any unexpected exception (LocalForge.checks() format).
  A `break` check is a deliberate red run, so it does **not** write the checks file.
  Client timeout: ≥ `TP_RUN_TIMEOUT_S + TP_RUN_QUEUE_WAIT_S` + static steps (~25 min with defaults).
- `POST /locator-probe {sha, role, name, url_path, scope_test_id? (alias within_test_id)}` →
  `{matches, test_id|null, test_ids, test_id_raw, scope_test_id, scope_matches, sha, app_url, url_path,
  final_path, http_status, oneri_uretilebilir, olculen, uygulama_sha, sha_eslesmesi, uyari}`. Opens `DEMO_WEB_URL + url_path` (logged in as
  `TP_PROBE_USER`, default `bayi1`, except under `/giris`), waits ≤5 s for the first match, counts
  `getByRole(role, {name})` (inside `getByTestId(scope_test_id)` when given), reads `data-testid` on a
  single match. The browser may only request the app origin. `test_id` is returned only if it matches
  the testId grammar; `oneri_uretilebilir` = exactly one match with a valid testId (§8.7: 0 or >1 → human).
  **Measured on the running app, not on `sha`:** `olculen` is always `"calisan_uygulama"`. If
  `DEMO_APP_BUILD_SHA` (the commit the running demo-app-web was built from) is set, it is resolved in
  the forge and compared with `sha`: `sha_eslesmesi` = `eslesiyor` | `farkli` (then
  `oneri_uretilebilir=false`, Turkish `uyari`) | `dogrulanamadi` (env unset or not in forge; `uyari`
  set, suggestion still allowed). Phase 4 repair records must store `olculen`, `uygulama_sha`,
  `sha_eslesmesi`, `uyari` verbatim. Pages
  whose target only exists after earlier steps (e.g. a filled cart) yield 0 matches.

### test-runner (:8200)

- `POST /run {sha, run_id, grep?, repeat_each=1, retries=0, env?:{BREAK_CAMPAIGN:"1"}, break_campaign?,
  test_files?, workers?}` → `{run_id, sha, status:"passed"|"failed"|"error", error, exit_code,
  duration_ms, junit, json, allure_dir, html_dir, traces_dir, log, artifacts_dir, artifacts_rel,
  stats:{expected,unexpected,flaky,skipped,duration_ms}, tests:[{title,file,line,project,status,
  attempts,duration_ms,error,attachments}], report_errors, break_restore}`.
- One run at a time (bayi1/bayi2 are shared); a queued request waits ≤ `TP_RUN_QUEUE_WAIT_S`, then 409.
- Layout: `runs/<run_id>/run.json` (summary; `running` while in progress), `runner.log`,
  `src/e2e/` = exact copy of the commit's `e2e/` (evidence), Playwright reports where the commit's
  config puts them: `src/e2e/results/{junit.xml,results.json,allure-results/,html/,artifacts/}`.
  A reused `run_id` is 409 (evidence is immutable). A committed `results/` is deleted before the run.
- Playwright gets only `PATH/HOME/LANG/…`, `BASE_URL`, `DEMO_API_URL`, `DEMOAPP_TEST_TOKEN`, `CI=1`,
  `BREAK_CAMPAIGN`, `TP_RUN_ID`. With `BREAK_CAMPAIGN=1` the e2e fixture breaks the campaign for the
  run's dealers via `/test/break`; afterwards the runner **always** (failure, timeout) calls
  `/test/break {kampanya:false}` for each of `TP_RUN_DEALERS` (bayi1,bayi2); if that fails the run is `error`.
- Status: `failed` = some test unexpected; `error` = timeout, no/corrupt report, report-level errors,
  no test ran, non-zero exit without failures, or break not restored; else `passed` (flaky counts as passed, see `stats.flaky`).

### Environment (defaults)

`TP_FORGE_PATH` (/forge/demo-app.git), `TP_ARTIFACTS_PATH` (/artifacts), `TP_E2E_ROOT` (e2e),
`TP_E2E_DEPS` (/opt/e2e), `TOOLCHAIN_HOME` (/opt/toolchain), `TEST_RUNNER_URL`, `BASE_URL`,
`DEMO_API_URL`, `DEMOAPP_TEST_TOKEN`, `DEMO_WEB_URL` (http://demo-app-web:8080, probe target),
`TP_PROBE_USER`/`TP_PROBE_PASSWORD` (bayi1 / Demo123!, DEMO-VERISI.md), `TP_RUN_DEALERS`.
Timeouts (s): `TP_GIT_TIMEOUT_S` 60, `TP_TSC_TIMEOUT_S` 180, `TP_ESLINT_TIMEOUT_S` 240,
`TP_AST_GUARD_TIMEOUT_S` 60, `TP_SYMBOLS_TIMEOUT_S` 60, `TP_PROBE_TIMEOUT_S` 60,
`TP_RUN_TIMEOUT_S` 900, `TP_RUN_QUEUE_WAIT_S` 600, `TP_CHECK_QUEUE_WAIT_S` 900.

### Security notes

- toolchain-worker never runs test code. tsc only parses. ESLint *loads* `eslint.config.js` as code,
  so the commit's config must be byte-identical to the image's trusted copy, else the step fails
  without starting ESLint. A committed `e2e/node_modules` is replaced by a link to the image deps.
- Checkout = `git archive` + `tarfile` `filter="data"` (no absolute paths, no links leaving the tree).
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

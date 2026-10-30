# Uygulama sözleşmesi (paralel geliştirme için)

Bu belge TEKNIK-TASARIM.md'nin **uygulamadaki bağlayıcı karşılığıdır**. Paralel çalışan her şerit
bu sözleşmeye uyar; sözleşme değişikliği yalnızca entegrasyon liderinin işidir. Çelişkide sıra:
constitution → bu belge → TEKNIK-TASARIM.md.

## 1. Dış sistemler: port + adaptör + yerel simülatör

Demo, dış hesaplar olmadan da **uçtan uca** çalışır. Her dış sistem `core/src/tp_core/ports.py`'deki
bir Protocol arkasındadır; gerçek adaptör ve yerel simülatör aynı kodu (aynı HTTP API'yi) kullanır.

| Sistem | Port | Gerçek | Yerel (varsayılan) | Seçim |
|---|---|---|---|---|
| Jira | `JiraPort` | Jira Cloud REST v3 (`RestJira`) | `jira-sim` servisi (REST v3 alt kümesi, aynı `RestJira` istemcisi) | `JIRA_BASE_URL` (varsayılan `http://jira-sim:8090`) |
| Test yönetimi | `TestManagementPort` | Jira Test issue · Xray Cloud | Aynı adaptörler, `jira-sim` üzerinde (`/xray/api/v2/...`) | `TP_TEST_MGMT=jira\|xray` |
| Git forge | `ForgePort` | GitHub (REST, App/token) | `LocalForge`: `tp_forge` volume'ünde bare git + Postgres `pull_request` tablosu; "CI" = test-runner | `TP_FORGE=local\|github` |
| Model | `ModelGateway` | Anthropic (Claude) | `replay` (rules/replay/ altındaki golden kayıtlar) | `TP_MODEL_MODE=auto\|live\|replay` (auto: anahtar varsa live, yoksa replay) |
| Sauce Labs | — | GitHub Actions job'u (`saucectl`) | yok (yerel Chromium job'u) | GitHub secret'ları |

REPLAY kullanılan her çıktı portalda **REPLAY** rozetiyle görünür (Constitution: sahte "canlı" gösterim yok).

## 2. Servisler ve sorumluluklar

| Servis | Sorumluluk | Yazdığı yer |
|---|---|---|
| core-api | HTTP API (§5), oturum, SSE, onay kayıtları | Postgres `tp` |
| core-worker | Durum makinesi + iş kuyruğu (`job`), AI çağrıları, Jira, forge (git) | Postgres `tp`, `tp_forge` |
| toolchain-worker | TypeScript tarafı: sembol tablosu (ts-morph), `tsc`/`eslint`/AST koruması, locator yoklaması; test-runner'a koşu gönderir | `tp_artifacts` |
| test-runner | Verilen commit'i forge'dan alır, demo uygulamasını SQLite ile `webServer` olarak başlatır, Playwright koşturur; internetsiz | `tp_artifacts` |
| playwright-mcp | Doğrulama ajanının tarayıcısı; yalnızca `http://demo-app-web:8080` | — |
| jira-sim | Jira Cloud REST v3 + Xray alt kümesi simülatörü (kalıcı: JSON dosyası) | `tp_jira` |
| demo-app-api / web | Bayi Sipariş Portalı (Postgres `demoapp`) | Postgres `demoapp` |

**Volume'ler:** `tp_forge` (core-worker rw, toolchain-worker rw, test-runner ro) · `tp_artifacts`
(toolchain-worker rw, test-runner rw, core-api ro, core-worker ro) · `tp_jira` (jira-sim).

### toolchain-worker HTTP API (:8100, runner-net + core-net)
- `POST /symbols {sha}` → `{page_objects:[{class, file, methods:[{name, params:[{name,type}], returns, kind:"action"|"expect"}], locators:{key:{testId, role, name, intent}}}]}`
- `POST /check {sha, test_files:[...], repeat_each:3, env:{}}` → `{tsc, eslint, ast_guard, run:{run_id, status, junit_path, json_path, artifacts_dir}}`
- `POST /ast-guard {base_sha, head_sha}` → `{ok, violations:[...]}`
- `POST /locator-probe {sha, role, name, url_path}` → `{matches:int, test_id|null}`

### test-runner HTTP API (:8200, yalnızca runner-net)
- `POST /run {sha, grep?, repeat_each, retries, env:{BREAK_CAMPAIGN?}, run_id}` → `{status: passed|failed|error, junit, json, artifacts_dir, duration_ms}`

## 3. Kod sahipliği (şeritler)

| Dizin | İçerik |
|---|---|
| `core/src/tp_core/ports.py` | Sözleşme (yalnızca lider) |
| `core/src/tp_core/models/` + `core/alembic/versions/` | Tüm tablolar (tek şerit: platform) |
| `core/src/tp_core/{auth,audit,events,workflow,api}/` | Platform |
| `core/src/tp_core/gateway/` + `rules/` | Model geçidi, prompt/şema/replay |
| `core/src/tp_core/integrations/` | Jira, Xray, forge adaptörleri |
| `core/src/tp_core/features/<özellik>/` | Özellik iş mantığı (F3, F4, F5) |
| `sims/jira-sim/` | Jira simülatörü |
| `demo-app/` | Örnek uygulama, page object'ler, e2e |
| `toolchain/` | toolchain-worker, test-runner, MCP |
| `review-portal/` | Portal |
| `.github/` | CI |

Bağımlılık ekleme (`pyproject.toml`, `package.json`) ve `docker-compose.yml` değişikliği lider tarafından
yapılır; şeritler gereksinimi raporlarında bildirir. Çekirdekte şu paketler hazırdır: fastapi, sqlalchemy,
alembic, psycopg, pydantic, anthropic, mcp, httpx, sqlglot, jinja2, sse-starlette, itsdangerous, pyyaml, argon2-cffi.

## 4. Veri modeli
TEKNIK-TASARIM §7'deki tablolar, Türkçe kolon adlarıyla (F0 stili: `kullanici_adi`, `olusturma`).
`workflow_instance.temporal_id` yerine `job_id`. Ek: `pull_request` (LocalForge), `run` için `kaynak`
(`local`/`github`/`sauce`). `ai_call`, `tool_call`, `audit_event` append-only; `audit_event` için
`prev_hash`/`hash` zinciri (sha256(prev_hash + kanonik JSON)).

## 5. HTTP API (core-api, portal `/api/` önekiyle erişir)

Tüm yanıtlar JSON; hata `{"detail": "..."}`. Oturum: `tp_session` çerezi (itsdangerous imzalı, HttpOnly,
SameSite=Lax). Rol yetkisi her uçta kontrol edilir.

| Yöntem | Yol | Rol | Amaç |
|---|---|---|---|
| POST | `/auth/login` `{kullanici_adi, parola}` | — | Oturum |
| POST | `/auth/logout` | herkes | |
| GET | `/auth/me` | herkes | `{id, kullanici_adi, rol}` |
| GET | `/requirements` | herkes | Story listesi (Jira'dan çekilmiş + durum) |
| POST | `/requirements/sync` | analyst | Jira'dan çek |
| POST | `/requirements/free-text` `{baslik, aciklama, ac[]}` | analyst | Serbest metin gereksinim |
| GET | `/requirements/{id}` | herkes | Detay + durum makinesi durumu |
| POST | `/requirements/{id}/review` | analyst | Ön inceleme + tutarlılık denetimi başlat |
| GET | `/requirements/{id}/findings` | herkes | Tutarlılık bulguları (kanıtlı) |
| POST | `/findings/{id}/decision` `{karar, metin?, gerekce?}` | analyst | fix_doc / code_defect / accept_difference |
| POST | `/requirements/{id}/apply-doc-fixes` | analyst | Onaylı düzeltmeleri Jira'ya yaz + yeniden kontrol |
| POST | `/requirements/{id}/po-approve` | po | Serbest metin yolunda PO teyidi (Jira yolunda etiket) |
| POST | `/requirements/{id}/generate-cases` | analyst | Case üretimi |
| GET | `/cases?requirement_id=` | herkes | |
| POST | `/cases/{id}/decision` `{karar: approve\|edit\|reject, icerik?, ret_nedeni?}` | analyst | |
| GET | `/publish/preview?requirement_id=` | analyst | Dry-run |
| POST | `/publish` `{case_ids[]}` | analyst | Yayın |
| POST | `/code/generate` `{case_ids[]}` | engineer | Kod üretimi (CasesToCode) |
| GET | `/scripts` · `/scripts/{id}` | herkes | Üretilen test + PR + adım görüntüleri |
| POST | `/scripts/{id}/break-verify` | engineer | Kırarak doğrula (BREAK_CAMPAIGN) |
| POST | `/prs/{number}/merge` | engineer | LocalForge'da insan onaylı merge |
| POST | `/ci/trigger` `{tetik: deploy\|nightly}` | presenter | Deploy/gece tetiği |
| GET | `/runs` · `/runs/{id}` | herkes | Koşular, test sonuçları |
| GET | `/failures/{id}` | herkes | Triage sonucu |
| POST | `/failures/{id}/fix` | engineer | Locator onarım PR'ı |
| GET | `/bug-drafts` · `/bug-drafts/{id}` | herkes | |
| POST | `/bug-drafts/{id}/decision` `{karar: new\|link, icerik?, link_key?}` | tester | Onay → `publish_bug` |
| GET | `/control-tower` | herkes | Kontrol Kulesi verisi |
| GET | `/audit?verify=true` | herkes | Denetim + zincir doğrulaması |
| GET | `/events` (SSE) | herkes | Olay akışı |
| POST | `/tokens` `{kapsam}` | analyst | MCP (Claude Code) kanalı için 8 saatlik token |
| MCP | `:8000/mcp` → `submit_draft_cases`, `publish_test_cases` | token | Claude Code kanalı |
| POST | `/demo/break-locator` · `/demo/reset` | presenter | Demo kırılması / sıfırlama |

## 6. Ortam değişkenleri (yeni)
`TP_SESSION_SECRET`, `TP_MODEL_MODE`, `JIRA_BASE_URL`, `JIRA_PROJECT` (varsayılan `TPD`),
`TP_TEST_MGMT`, `TP_FORGE`, `GITHUB_REPO`, `TP_DAILY_BUDGET_USD` (30), `TP_WORKFLOW_BUDGET_USD` (2).

## 7. Kalite kapısı (her şerit)
- Python: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` yeşil.
- TypeScript: `npm run build` (tsc strict) ve varsa `npm test` yeşil.
- Kendi dizini dışındaki dosyaya dokunmaz; commit atmaz; tam `make up` yapmaz (entegrasyon liderin).

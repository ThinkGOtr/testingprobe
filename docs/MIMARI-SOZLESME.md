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
| Git forge | `ForgePort` | GitHub (REST, App/token) | `LocalForge`: `tp_forge` volume'ünde bare git (`/forge/demo-app.git`, `scripts/forge-init.sh`) + PR kaydı `/forge/tp-prs.json` (dosya kilidi); "CI" = test-runner, sonuç `TP_ARTIFACTS_PATH/checks/<sha>.json` | `TP_FORGE=local\|github` |
| Model | `ModelGateway` | Anthropic (Claude) | `replay` (rules/replay/ altındaki golden kayıtlar) | `TP_MODEL_MODE=auto\|live\|replay\|record` (auto: anahtar varsa live, yoksa replay; record: live + replay kaydı) |
| Sauce Labs | — | GitHub Actions job'u (`saucectl`) | yok (yerel Chromium job'u) | GitHub secret'ları |

REPLAY kullanılan her çıktı portalda **REPLAY** rozetiyle görünür (Constitution: sahte "canlı" gösterim yok).

## 2. Servisler ve sorumluluklar

| Servis | Sorumluluk | Yazdığı yer |
|---|---|---|
| core-api | HTTP API (§5), oturum, SSE, onay kayıtları | Postgres `tp` |
| core-worker | Durum makinesi + iş kuyruğu (`job`), AI çağrıları, Jira, forge (git) | Postgres `tp`, `tp_forge` |
| toolchain-worker | TypeScript tarafı: sembol tablosu (ts-morph), `tsc`/`eslint`/AST koruması, locator yoklaması; test-runner'a koşu gönderir | `tp_artifacts` |
| test-runner | Verilen commit'in e2e kodunu forge'dan alır, compose'daki demo uygulamasına (`BASE_URL=http://demo-app-web:8080`) Playwright koşturur; bayi kapsamlı sıfırlama/kırılma `DEMO_API_URL` + `DEMOAPP_TEST_TOKEN` ile; internetsiz | `tp_artifacts` |
| playwright-mcp | Doğrulama ajanının tarayıcısı; yalnızca `http://demo-app-web:8080` | — |
| jira-sim | Jira Cloud REST v3 + Xray alt kümesi simülatörü (kalıcı: JSON dosyası) | `tp_jira` |
| demo-app-api / web | Bayi Sipariş Portalı (Postgres `demoapp`) | Postgres `demoapp` |

**Volume'ler:** `tp_forge` (core-worker rw, toolchain-worker rw, test-runner ro) · `tp_artifacts`
(toolchain-worker rw, test-runner rw, core-api ro, core-worker ro) · `tp_jira` (jira-sim).

### toolchain-worker HTTP API (:8100, runner-net + core-net)
- `POST /symbols {sha}` → `{page_objects:[{class, file, methods:[{name, params:[{name,type}], returns, kind:"action"|"expect"}], locators:{key:{testId, role, name, intent}}}]}`
- `POST /check {sha, test_files:[...], repeat_each:3, env:{}}` → `{tsc, eslint, ast_guard, run:{run_id, status, junit_path, json_path, artifacts_dir}}`
- `POST /ast-guard {base_sha, head_sha}` → `{ok, violations:[...]}`
- `POST /symbols` locator'ları isteğe bağlı `within` alanını da taşır: kapsayıcının testId öneki
  (ör. `catalog.addToCart.within = "product-card-"`; aynı rol + ad her kartta tekrarlanır).
- `POST /locator-probe {sha, role, name, url_path, scope_test_id?}` → `{matches:int, test_id|null}`.
  `scope_test_id` (ör. `product-card-P-001` = `within` + başarısız adımdaki ürün kodu) verilirse
  eşleşmeler yalnızca o kapsayıcı içinde sayılır. Kapsam yokken `matches > 1` → öneri yok.

### test-runner HTTP API (:8200, yalnızca runner-net)
- `POST /run {sha, grep?, repeat_each, retries, env:{BREAK_CAMPAIGN?}, run_id}` → `{status: passed|failed|error, junit, json, artifacts_dir, duration_ms}`
- `env.BREAK_CAMPAIGN=1` Playwright sürecine geçer (API konteynerine değil): e2e fixture'ı koşunun
  bayisi için `POST /test/break {kullanici_adi, kampanya:true}` çağırır, teardown'da kapatır; diğer
  bayiler ve ajan tarayıcısı etkilenmez. Yeşil → kırmızı → yeşil kanıtı `demo-app/ci/break-verify.sh`.

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
`workflow_instance.temporal_id` yerine `job_id`. Ek: `pull_request` (çekirdeğin PR durum/onay kaydı; forge'un kendi PR kaydı LocalForge'da `/forge/tp-prs.json`, GitHub'da GitHub), `run` için `kaynak`
(`local`/`github`/`sauce`). `ai_call`, `tool_call`, `audit_event` append-only; `audit_event` için
`prev_hash`/`hash` zinciri (sha256(prev_hash + kanonik JSON)).

## 5. HTTP API (core-api, portal `/api/` önekiyle erişir)

Tüm yanıtlar JSON; hata `{"detail": "..."}`. Oturum: `tp_session` çerezi (itsdangerous imzalı, HttpOnly,
SameSite=Lax). Rol yetkisi her uçta kontrol edilir. Oturum sunucu tarafındadır (`oturum` tablosu):
çıkış o tarayıcının oturumunu iptal eder, kopyalanan çerez de geçersizleşir.

**İnsan kararlarında içerik bağı (TOCTOU):** her karar gövdesi (`/findings/{id}/decision`,
`/cases/{id}/decision`, `/bug-drafts/{id}/decision`, `/requirements/{id}/po-approve`,
`/prs/{number}/merge`) kullanıcının ekranda gördüğü içeriğin `icerik_hash`'ini taşır; router
bunu `record_approval(..., beklenen_hash=icerik_hash)` olarak geçirir. Portal kanalında zorunludur
(eksikse 422); içerik o arada değiştiyse 409 döner ve portal içeriği yeniden yükler. Merge ayrıca
onaylanan head sha'sını `ForgePort.merge_pr(..., expected_head_sha=...)` ile bağlar.

**CSRF / Origin (`OriginGuard`, tüm uçlar):** POST/PUT/PATCH/DELETE isteklerinde `Sec-Fetch-Site`
varsa `same-origin` veya `none` olmalı; yoksa `Origin` varsa `TP_ALLOWED_ORIGINS` listesinde olmalı
(`null` reddedilir). İkisi de yoksa istek tarayıcı dışı istemci (curl, MCP bearer) sayılır ve geçer.
Ret: 403 `{"detail": "İstek başka bir kaynaktan geldi; işlem reddedildi"}`. Kural oturum çerezinden
bağımsızdır (giriş CSRF'i de kapsanır).

**SSE olayları (`GET /events`):** zarf `{data, ts}`. Olay adları: her durum makinesi için
`<entity>.state` (`requirement`, `consistency_finding`, `test_case`, `script`, `bug_draft`,
`workflow_instance`) ve `review.recorded` (`nesne_turu`, `nesne_id`). Portalın ayrıntılı adları
(`agent.step`, `ci.status`, `pr.opened`, `failure.classified`, `case.generated`, `bug.published`)
henüz yalnızca örnek veri (mock) tarafından üretilir; core bunları ilgili özellik şeritleriyle ekler.
Akış her olaydan önce ve boştayken 15 sn'de bir oturumu yeniden denetler; oturum kapatılmış, iptal
edilmiş, süresi dolmuş, parola değişmiş veya kullanıcı silinmişse son olay `event: session.ended`
gönderilir ve akış kapanır. Portal bunu alınca yeniden bağlanmaz, giriş ekranına (`/giris`) döner.

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
| POST | `/tokens` `{kapsam}` → `{id, kapsam, son_kullanma, token, mcp_url}` | analyst | MCP (Claude Code) kanalı için 8 saatlik token; `mcp_url` = `TP_MCP_PUBLIC_URL`. `/mcp` bağlanana kadar **501** ("IDE (MCP) kanalı henüz etkin değil"); token parola değişince geçersizleşir |
| MCP | `:8000/mcp` → `submit_draft_cases`, `publish_test_cases` | token | Claude Code kanalı |
| POST | `/demo/break-locator` · `/demo/reset` | presenter | Demo kırılması / sıfırlama |

## 6. Ortam değişkenleri (yeni)
`TP_SESSION_SECRET`, `TP_MODEL_MODE`, `JIRA_BASE_URL`, `JIRA_PROJECT` (varsayılan `TPD`),
`TP_TEST_MGMT`, `TP_FORGE`, `GITHUB_REPO`, `TP_DAILY_BUDGET_USD` (30), `TP_WORKFLOW_BUDGET_USD` (2).

Faz 1 entegrasyonunda eklenenler (boş = yerel simülatör / güvenli varsayılan):
- Jira/Xray: `JIRA_READ_EMAIL`/`JIRA_READ_TOKEN`, `JIRA_WRITE_EMAIL`/`JIRA_WRITE_TOKEN`,
  `JIRA_BROWSE_URL` (kullanıcıya gösterilen bağlantı kökü; compose varsayılanı jira-sim'in yerel adresi,
  gerçek Jira'da boş → `JIRA_BASE_URL`), `JIRA_TIMEOUT_S` (10), `XRAY_BASE_URL`, `XRAY_CLIENT_ID`/`XRAY_CLIENT_SECRET`.
- Model (yalnızca core-worker): `ANTHROPIC_API_KEY`, `TP_MODEL_PROVIDER` (anthropic), `TP_PII_MASKING` (0);
  core-api ve core-worker: `TP_RULES_DIR` (`/rules`, `./rules` salt okunur bağlanır).
- Forge: `GITHUB_TOKEN`, `GITHUB_MERGE_TOKEN` (insan token'ı; bot asla merge etmez), `GITHUB_API_URL`,
  `GH_APP_ID`, `GH_APP_PRIVATE_KEY` / `GH_APP_PRIVATE_KEY_PATH`, `GH_APP_INSTALLATION_ID`, `TP_FORGE_PRS_PATH`.
- Platform: `TP_MCP_PUBLIC_URL` (IDE'ye gösterilen MCP adresi), `TP_SESSION_MAX_AGE_S`,
  `TP_SESSION_COOKIE_SECURE`, `TP_API_TOKEN_TTL_S`, `TP_WORKER_POLL_S`.
- Demo uygulaması: `DEMOAPP_TEST_MODE=1` (compose), `DEMOAPP_TEST_TOKEN` (`/test/reset` ve
  `/test/break` için; `make env` üretir, yalnızca demo-app-api ve test-runner'a verilir; uçlar yalnızca
  demo-net'ten erişilir, demo-app-web nginx'i `/api/test/*`'i 404'le kapatır; e2e webServer modu her
  koşuda kendi belirtecini üretir), `BREAK_CAMPAIGN` (yalnızca yerel/webServer denemesi için süreç
  geneli; compose'da kullanılmaz, koşu başına kırılma `/test/break`).
- test-runner: `BASE_URL` (`http://demo-app-web:8080`), `DEMO_API_URL` (`http://demo-app-api:8000`),
  `DEMOAPP_TEST_TOKEN`. Belirteçsiz yerel deneme: `TP_E2E_NO_RESET=1` (yalnızca sepet yalıtımı,
  `@sifir-veri` testleri hariç).
- core-api CSRF: `TP_ALLOWED_ORIGINS` (virgülle; compose varsayılanı portalın
  `http://127.0.0.1:${TP_PORTAL_PORT}` ve `http://localhost:${TP_PORTAL_PORT}` adresleri).
- jira-sim: `JIRA_SIM_PO_PASSWORD` (PO girişi `po@sim.local`; UI ve REST), `JIRA_SIM_ADMIN_TOKEN`
  (`/sim/*` için `X-Sim-Admin-Token`); ikisini de `make env` üretir. İsteğe bağlı `JIRA_SIM_SECRET`
  (boş = her açılışta yeni oturum anahtarı), `JIRA_SIM_ALLOWED_HOSTS`.
- Jira PO onayı (yalnızca core-worker): `JIRA_PO_ACCOUNT_IDS` (izinli PO kimlikleri; boş → jira-sim'de
  `po@sim.local`, gerçek Jira'da hiçbiri), `TP_PO_JIRA_USERS` (ek izin listesi; boş = liste denetimi yok),
  `TP_JIRA_BOT_ACCOUNT_IDS` (ürünün bot accountId'leri; onay sayılmaz). Jira kanalındaki onayı kaydeden
  kod `RestJira.po_approvals(key, settings.po_accounts)` sonucunu kullanır ve her onayı
  `check_jira_approver()`'dan geçirir; ham `label_history` onay sayılmaz.
- Forge merge kapısı (yalnızca core-worker): `TP_REQUIRED_CHECKS` (virgülle; boş = `local-ci` /
  GitHub ruleset listesi `test-local,ast-guard,semgrep`).
- Model geçidi: `TP_REPLAY_STRICT` (1 = prova: replay kaydı yoksa golden'a düşmez, hata verir).
- playwright-mcp: `MCP_ALLOWED_ORIGINS`, `MCP_ALLOWED_HOSTS` (Host başlığı izin listesi).

**Ortam dağıtımı (compose):** `x-core-env` ortak bloğu core-api ve core-worker'a gider ve yazma
kimliği içermez. `JIRA_WRITE_*`, `XRAY_CLIENT_*`, `GITHUB_TOKEN`, `GITHUB_MERGE_TOKEN`, `GH_APP_*`,
`ANTHROPIC_API_KEY`, `PLAYWRIGHT_MCP_URL` ve yukarıdaki PO/merge ayarları **yalnızca core-worker**'dadır
(`make security-check` 6 ve 8).

**Ağlar:** `playwright-mcp` yalnızca `agent-net` + `mcp-net`'tedir (`agent-net`: internal, yalnızca
demo-app-web ile; `mcp-net`: internal, yalnızca core-worker ile paylaşılır) ve host'a port açmaz.
test-runner `demo-net` + `runner-net`'tedir; MCP'ye (8931) ulaşamaz. MCP sayfada kod çalıştıran araçları
(`browser_run_code_unsafe`, `browser_evaluate`, …) kapatmaya izin vermediği için sınır ağdır
(`make security-check` 7); ayrıca model geçidi `FORBIDDEN_TOOLS`'taki araçları hiçbir ajana vermez.

**Neden değişti (Faz 1 entegrasyonu):** model anahtarı anayasa gereği yalnızca core-worker'a verildi
(daha önce ortak blokta core-api'ye de geçiyordu; `make security-check` 6. kontrol bunu doğrular);
PR kaydı forge şeridinde Postgres yerine forge volume'ündeki dosyaya taşındı (LocalForge'un git ile aynı
yerde, aynı kilit altında kalması için); `/tokens` yanıtına `mcp_url` eklendi (portal `.mcp.json`
parçacığını üretir, adresi yalnızca sunucu bilir).

**Neden değişti (Faz 1 entegrasyonu, 1. inceleme turu):** inceleme ajan tarayıcısının (MCP) core-net
üzerinden jira-sim ve core-api'ye ulaşabildiğini, core-api'nin hiç kullanmadığı yazma kimliklerini
taşıdığını ve onayın kullanıcının gördüğü içeriğe bağlı olmadığını buldu. Bu yüzden MCP ağı daraltıldı,
ortam bloğu ikiye bölündü, karar gövdelerine `icerik_hash` eklendi. `ports.py`'de
`ModelGateway.call/run_agent` isteğe bağlı `call_id` (iş + adımdan deterministik; yeniden denemede tek
ücretli çağrı) ve `ForgePort.merge_pr` isteğe bağlı `expected_head_sha` aldı; ikisi de varsayılanla
geriye uyumludur. PR dal adları: case PR'ları `tp/case-*`, locator onarımları `tp/repair-*` + etiket
`tp-repair` (`tp_core.integrations.forge`; CI AST koruması modu bunlara bakar).

**Neden değişti (Faz 1 entegrasyonu, 2. inceleme turu):** inceleme, onayın içerik değiştiren
kararlarda bağlanamadığını, PO onayından sonra içeriğin değişip case üretimine gidebildiğini, eski bir
Jira etiketinin içerik değişse de onay sayıldığını, ai_call çapasının yeniden hesaplanamadığını, zaman
aşımının tek worker'da uygulanmadığını ve `make up`'ın idempotent olmadığını buldu. Sonuç:

- **`record_approval(..., degisiklik=...)`:** router'lar içeriği kendileri değiştirmez; düzenlenen
  içeriği `degisiklik` ile geçirir (izinli alanlar `states.DECISION_EDITS`: test_case edit→`icerik`,
  bug_draft new/link→`icerik`, bulgu fix_doc→`onerilen_metin`). Karar gövdesindeki `icerik_hash`
  her zaman **düzenleme öncesi** (kullanıcının gördüğü) hash'tir; `review.onaylanan_hash` düzenleme
  sonrasıdır. `accept_difference` gerekçesiz reddedilir.
- **Gereksinim onayı içeriğe bağlı:** `requirement.onaylanan_hash` (0004) `po_approved`'a girişte
  yazılır; `generating`'e giden her geçiş güncel hash'i buna karşı denetler.
- **Jira kanalında PO onayı:** `record_approval(kanal='jira')` zaman dilimli `onay_zamani` (etiket
  anı, `RestJira.label_events`/`label_history` `at`) ister; `requirement.icerik_degisim` (0004) bundan
  sonraysa `GateClosed` ("yeniden onay"). İsteğe bağlı `beklenen_hash` etiket anındaki hash'le eşleşmeli.
  Jira'dan gereksinim oluşturan/güncelleyen senkron kodu `icerik_degisim`'i changelog'daki açıklama
  değişim anından yazar. `RestJira.po_approvals` içerik değişikliğinden önceki etiketleri saymaz; bot
  `tp-po-approved` etiketini kaldırabilir (yalnızca ekleyemez). Doküman düzeltmesi akışı
  `update_description` sonrasında `remove_labels([tp-po-approved])` + `add_labels([tp-po-pending])`
  çağırır. **Henüz yazılmadı** (apply-doc-fixes iş akışı özellik şeridinde); yazılmazsa onay yine
  sayılmaz (fail-closed), yalnızca panodaki etiket eski kalır.
- **Deterministik case kimliği:** özellik kodu `test_case`'i `id=models.case_id(requirement, sira_no,
  uretim_no)` ile oluşturur (uuid5; varsayılan yok, `(requirement_id, sira_no, uretim_no)` UNIQUE).
- **Denetim çapası:** `GET /audit?verify=true` yanıtında `verify.anchors` (`checked`, `broken`,
  `sabitsiz`, `eski`); herhangi bir ai_call/tool_call çapası tutmazsa `verify.ok=false`.
  `ai_call.ek` (jsonb, 0005): geçidin kolonu olmayan ayrıntıları (`replay_kaynagi`, `replay_kokeni`
  = `recorded|golden_promoted`, `sema_hatalari`, …); `build_gateway` bunları varsayılan olarak yazar.
  `ek` çapaya yalnızca NULL değilse girer (0005'ten önceki çapalar geçerli kalır).
- **Ajan araçları izin listesi:** `gateway.ALLOWED_AGENT_TOOLS` (amaç başına; verify_and_map = §8.4
  listesi, consistency_check = search_code/get_file_contents/db_schema/db_query). İş akışı ajana MCP
  `tools/list`'in bu listeyle süzülmüş halini verir; fazlası `GatewayConfigError`.
- **Yeni ortam değişkenleri:** `TP_TRUSTED_PROXIES` (core-api; X-Forwarded-For'a yalnızca bu
  eşten gelen bağlantıda ve yalnızca en sağdaki girdiye güvenilir; varsayılan `review-portal`; portal
  nginx'i `X-Forwarded-For $remote_addr` gönderir), `TP_WORKER_LIVENESS_FILE` (core-worker canlılık
  dosyası; healthcheck 120 sn'den eskiyse sağlıksız). Worker zaman aşımından sonra **70** koduyla
  çıkar; compose `restart: unless-stopped` yeni süreç başlatır. Giriş denemesi kısıtlaması
  `tp_cihaz` imzalı cihaz çerezine göre ayrılır.
- **Compose:** çekirdek imajını yalnızca `migrate`, toolchain imajını yalnızca `toolchain-worker`
  derler; kardeş servisler aynı yerel imajı `pull_policy: never` ile kullanır (aynı imajın üç kez
  derlenmesi `make up`'ı idempotent olmaktan çıkarıyordu). `core-worker`'ın `hostname`'i sabittir
  (`release_orphans` yeniden oluşturulan worker'ın yarım işlerini adıyla bulur).
- **Paylaşılan sözleşme kopyaları:** `review-portal/src/api/sozlesme/durum-makineleri.json` (portal
  durum birlikleri) ve `.github/golden-drift/drift_sources.py` (CI golden-drift'in tp_core'suz
  kopyaları) çekirdekteki `tests/unit/test_cross_lane_contracts.py` ile `MACHINES` ve
  `tp_core.gateway`'e karşı denetlenir.

**Neden değişti (Faz 1 entegrasyonu, 3. inceleme turu):** inceleme test-runner'ın demo-net
üzerinden playwright-mcp:8931'e ulaşabildiğini (MCP'nin Host denetimi aynı adı kabul ettiği için),
e2e fixture'ının compose'daki uygulamada belirteçsiz çalışamadığını ve `BREAK_CAMPAIGN`'ın süreç
geneli olduğu için kırılmanın ajan tarayıcısını ve diğer koşuları da etkilediğini buldu. Sonuç:
ajan tarayıcısı ayrı `agent-net`'e taşındı (yalnızca demo-app-web; demo-app-api ve test-runner'a
erişemez), `DEMOAPP_TEST_TOKEN` compose'a bağlandı (yalnızca demo-app-api + test-runner), kırılma
bayi kapsamlı `POST /test/break`'e taşındı, test-runner'ın hedefi compose'daki uygulama oldu.
`make security-check` 2 ve 7 bu sınırları (test-runner↛MCP, MCP↛demo-app-api/test-runner) doğrular.
Ayrıca CSRF kuralı (`OriginGuard`, `TP_ALLOWED_ORIGINS`) ve SSE `session.ended` sözleşmeye eklendi.
demo-app'teki kırılma kodu satırları kaydırdığı için golden kanıt satırları güncellendi
(DEMO-VERISI.md).

## 7. Kalite kapısı (her şerit)
- Python: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` yeşil.
- TypeScript: `npm run build` (tsc strict) ve varsa `npm test` yeşil.
- Kendi dizini dışındaki dosyaya dokunmaz; commit atmaz; tam `make up` yapmaz (entegrasyon liderin).

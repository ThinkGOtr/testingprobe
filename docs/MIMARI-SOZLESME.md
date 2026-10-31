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

**Volume'ler:** `tp_forge` (core-worker rw, toolchain-worker ro, test-runner ro) · `tp_artifacts`
(toolchain-worker rw, test-runner rw, core-api ro, core-worker ro) · `tp_codegen` (Faz 3: kod
üretimi ajan ekran görüntüleri `codegen/<script_id>/step-<n>.png`; core-worker rw, core-api ro;
`TP_CODEGEN_ARTIFACTS_PATH=/codegen-artifacts`) · `tp_checks` (Faz 3 entegrasyonu: merge kapısı
`checks/<sha>.json`; toolchain-worker rw, core-api/core-worker ro, **test-runner bağlamaz**;
`TP_CHECKS_PATH=/checks`, toolchain-worker'da `TP_CHECKS_REQUIRE_MOUNT=1`) · `tp_forge_mirror`
(GitHub modu aynası `/forge-mirror`; toolchain-worker rw, test-runner ro) · `tp_jira` (jira-sim).
core-worker paylaşılan `tp_artifacts`'a yazamaz; merge kapısı dosyasının tek yazarı toolchain-worker
`/check`'tir ve üretilen kodu koşturan test-runner kapıyı göremez (`make security-check` 9; CI imajında ajan yok: 10).
`make reset` `tp_codegen`, `tp_checks` ve `tp_forge_mirror`'ı da siler.

### toolchain-worker HTTP API (:8100, runner-net + core-net)
- `POST /symbols {sha}` → `{page_objects:[{class, file, methods:[{name, params:[{name,type}], returns, kind:"action"|"expect"}], locators:{key:{testId, role, name, intent}}}]}`
- `POST /check {sha, test_files:[...], repeat_each:3, env:{}}` → `{tsc, eslint, ast_guard, run:{run_id, status, junit_path, json_path, artifacts_dir}}`
- `POST /ast-guard {base_sha, head_sha}` → `{ok, violations:[...]}`
- `POST /symbols` locator'ları isteğe bağlı `within` alanını da taşır: kapsayıcının testId öneki
  (ör. `catalog.addToCart.within = "product-card-"`; aynı rol + ad her kartta tekrarlanır).
- `POST /locator-probe {sha, role, name, url_path, scope_test_id?}` → `{matches:int, test_id|null}`.
  `scope_test_id` (ör. `product-card-P-001` = `within` + başarısız adımdaki ürün kodu) verilirse
  eşleşmeler yalnızca o kapsayıcı içinde sayılır. Kapsam yokken `matches > 1` → öneri yok.
  Yanıt ayrıca `olculen:"calisan_uygulama"`, `uygulama_sha`, `sha_eslesmesi`
  (`eslesiyor|farkli|dogrulanamadi`) ve `uyari` (Türkçe, ya da null) taşır: ölçüm istenen sha'da değil
  çalışan demo-app-web'de yapılır. Çalışan uygulamanın commit'i `DEMO_APP_BUILD_SHA`'dan okunur;
  `farkli` → `oneri_uretilebilir=false` (case insana gider), boş/çözülemezse `dogrulanamadi` + uyarı.
  Faz 4 onarım kaydı bu dört alanı aynen saklar.

**Faz 3 `/check` ve `/run` (toolchain lane, ayrıntı `toolchain/README.md`):**
- `/check` isteği ek alanlar: `retries`, `run_id`, `grep?`, `break`/`break_campaign` (ya da
  `env.BREAK_CAMPAIGN="1"`), `record_check?: bool|null`, `keep?: bool`. Yanıt üst kümedir:
  `deps`, `saglik`, `failures`, `failure_groups[{…, statuses, types, consistent}]`, `test_counts`,
  `kapsam{tam}`, `check_recorded`, `checks_path` (alan çıkarılmadı).
- `/check` `TP_CHECKS_PATH/<sha>.json`'ın (yoksa `TP_ARTIFACTS_PATH/checks/`) **tek yazarıdır**;
  ilk adımı `app`: çalışan demo-app-web'in commit'i (`/forge/demo-app-web.sha`, forge-init /
  break / baseline / sync-web yazar) ile istenen commit'in `web`+`api` ağaçları karşılaştırılır;
  `farkli` → koşu yok, core `ortam` sayar (defect değil). Varsayılan (`record_check:
  null`) yalnızca tam kapsamlı (test_files/grep yok), kırılmasız kontroller `local-ci` olarak
  kaydedilir (GitHub PR CI'ının yerel eşi); `true` kapsamlı kontrolü de kaydeder, `false` hiç;
  kırılmalı kontrol asla kaydedilmez (`record_check:true` + kırılma → 422). İstenen test dosyası
  commit'te yoksa `deps` adımında `missing_test_files` ile erken başarısız.
- Kod üretiminin yerel kontrolü kapsamlıdır (`test_files=[tests/generated/<dosya>]`,
  `repeat_each=3`, `retries=0`, kaydedilmez); merge kapısı `local-ci`'ı PR açılınca kuyruğa giren
  `ci.run` (tam kapsam, `retries=1`) yazar.
- Hata girdileri (`failure.type`): `test_data|navigation|locator_ambiguous|locator_not_found|
  locator_timeout|assertion|test_timeout|other` + `expected/received`, `location`, `test_location`
  (üretilen spec satırı; üretilen testlerde `test.step` yasak), `evidence{trace,error_context,
  screenshot,video}.rel`, `aria_snapshot`. Sınıflandırma (core): tutarlı `assertion` → `defect_adayi`
  (onarım yok); `locator_*` → tek yeniden eşleme turu; tutarsız/flaky → kararsızlık.
- `/run` isteğinde `keep?`; yanıtta `reports{html,junit,json,allure}`, `failures`,
  `failure_groups`, `cleanup`, `tests[].failure/repeat_index/attempt_results/column/id`.
  Saklama `TP_RUNS_KEEP` (test-runner, 50; 0 = kapalı). `.keep`li kanıt koşuları ayrı havuzdadır:
  `TP_RUNS_KEEP_EVIDENCE_DAYS` (30) ve `TP_RUNS_KEEP_EVIDENCE_MAX` (200) dışındakiler silinir;
  toolchain-worker `POST /runs/release {run_ids}` `.keep`'i kaldırır (belirteç ister).
- **Kimlik:** toolchain-worker uçları (`/health` hariç) `Authorization: Bearer $TP_TOOLCHAIN_TOKEN`
  ister (`TP_TOOLCHAIN_REQUIRE_TOKEN=1`: belirteçsiz başlatma 503). Belirteç core-api ve
  core-worker'da vardır, test-runner'da YOKTUR: üretilen kod `/check` ile kapıyı yazamaz.
  `record_check:true` + `test_files`/`grep` → 422 (kapsamlı kontrol asla `local-ci` olmaz); kayıtlı
  her CheckRun `tam:true` taşır. Smoke koşusu (`make e2e-smoke`) `tp-run-lock` ile `/run` kilidini
  paylaşır.
- **İmajlar (Constitution II):** `toolchain/Dockerfile` `ci` hedefi (varsayılan; toolchain-worker,
  test-runner, yayımlanan CI imajı) MCP içermez; `mcp` hedefi (`testingprobe-toolchain-mcp:local`)
  yalnızca playwright-mcp servisidir. `make security-check` 10 ve ci.yml Yol A
  `toolchain/security/no-mcp-in-image.sh` ile denetler.
- GitHub modunda (`TP_FORGE=github`) sha önce yerel forge'da, sonra `TP_FORGE_MIRROR_PATH`
  aynasında aranır; yoksa ve `TP_FORGE_REMOTE_URL` verilmişse salt okunur `git fetch` ile aynaya
  çekilir (belirteç `http.extraHeader` ortamında, argv'de değil). Kod üretimi `/check` 404'ünü
  yalnızca yerel olmayan forge'da "yerel kontrol atlandı" sayar; yerel forge'da 404 ortam hatasıdır.
- Koşu raporları: test-runner her koşudan sonra statik, tek dosyalık Allure raporu üretir
  (`reports.allure_html`). `GET /runs` `allure_url` önce bu raporu (`…/allure-report/index.html`),
  yoksa ham `allure-results`'ı gösterir; ham dizin `allure_sonuclari_url`'dedir. Rapor CSP sandbox'ında
  (allow-same-origin yok) açılır; core yanıtına bellek içi `localStorage` şimi ekler (Allure açılışta
  depoyu okur; şimsiz boş sayfa kalıyordu).

### test-runner HTTP API (:8200, yalnızca runner-net)
- `POST /run {sha, grep?, repeat_each, retries, env:{BREAK_CAMPAIGN?}, run_id}` → `{status: passed|failed|error, junit, json, artifacts_dir, duration_ms, saglik:{ok, zaman, web:{url,status,ms,hata}, api:{url,status,ms,hata}, hata}}`
- Koşudan önce `GET BASE_URL/` ve `GET DEMO_API_URL/health` (`TP_HEALTH_TIMEOUT_S`, 5 sn) yoklanır.
  `saglik.ok=false` → Playwright başlatılmaz, `status=error`, `tests=[]`. Faz 4 triage
  `saglik.ok == false`'u (ya da `saglik`'sız `error` koşusunu) locator/test bakımı yolundan önce
  deterministik `environment` sinyali sayar (TEKNIK-TASARIM §8.6 kural 1).
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

**Faz 3 tablolar:** 0009 `script_codegen` (script başına üretim kaydı: case/onaylı hash,
`story_key`, `sira_no`, eşleme `eslesme`, `uretim_modu`, `ai_call_ids`, `bundle_hash`,
`engel_turu`/`engel_nedeni`, `kirma_dogrulama`, PR alanları), `script_adim` (ajan adımları:
`sira`, `tur`, `arac`, `arguman` (parola maskeli), `ozet` (sarmalsız kısa özet), `izinli`,
`ekran_goruntusu`), `script_kontrol` (yerel kontrol / kırma koşuları ve sınıfı). Durum makinesinde
`defect_candidate` durumu yoktur: defect adayı = `script.durum='blocked'` +
`script_codegen.engel_turu='defect_candidate'` (portal `yerel_sinif='defect_adayi'`). Grup: case
başına bir script ve bir PR (dal `tp/case-<case uuid>[-n]`, dosya
`e2e/tests/generated/<story>-c<sira>-<uuid8>.spec.ts`). **Yeniden üretim politikası (Faz 3
entegrasyonu): her üretim yeni dal + yeni PR'dır.** Dal sembol tablosunun alındığı main sha'sından
kesilir; önceki script `closed` olur, açık PR'ı her iki kipte yorumlanıp kapatılır (LocalForge
`close_pr`; GitHub `PATCH pulls/{n} state=closed`). Kapatma başarısızsa yorum kalır, `sync_prs`
izlemeye devam eder; sonradan merge edilirse `codegen.superseded_pr_merged`.
Merge sonrası diğer açık bot PR'ları `script_codegen.dal.geride` işaretlenir ve `codegen.update_branch`
işi (LocalForge ve GitHub: `PUT pulls/{n}/update-branch`) dalı main'e taşır: yeni head + yeni
`icerik_hash`, kırma `not_started`, PR CI yeni head'de yeniden. Güncelleme yalnızca onaylı head
üzerinde yapılır: forge'a `expected_head_sha` verilir (PR kilidi altında karşılaştırılır); dalda
yabancı commit varsa iş reddedilir (`codegen.branch_foreign_commit`, `dal.yabanci=true`, merge 409)
ve güncelleme sonrası içerik doğrulanır (spec dosyası birebir aynı; değişen her yol main'deki
haliyle aynı; değişen yollar `changed_paths` ile — GitHub'da tek compare çağrısı). GitHub App
izinleri: Contents: write, Pull requests: write. `script_codegen.dal` JSONB (`geride`,
`guncelleme`, `neden`, `yabanci`).
**Ajan bayisi kilidi:** ajan bayisinin (bayi3) sepeti paylaşılan durumdur; kod üretimi ve
`replay_check` (`make demo-check`) aynı Postgres danışma kilidini
(`pg_advisory_lock(hashtext('agent-dealer:bayi3'))`) tutarak sırayla koşar.
**REPLAY sapması:** replay'de araç canlı koşar; `browser_generate_locator` locator'ı ya da eylem
adımının sayfa yolu (`· URL /giris` ↔ canlı `Page URL`) kayıttakinden farklıysa adım özeti
`REPLAY sapması:` ile başlar (sipariş no gibi oturuma özgü son segment `*` sayılır).
Sınıflar: `script_kontrol.sinif` ∈ {…, `kararsiz`} (aynı test hem geçti hem kırmızı → flaky,
`engel_turu='flaky'`, pass@1=False); `engel_turu` ayrıca `human_rejected` (insan "değişiklik iste"/
"reddet").
0010 `ci_tetik` (tekil `anahtar`, `run_id` FK SET NULL), `test_result_ek` (a11y sayıları, ekler,
deneme sonuçları; test_result ile cascade), `test_result_commit_ix_ci`. `script.insan_review_sonucu`
insan merge'ünde `kabul` (değişiklik istenmeden). `run.tetik` ayrıca `break_verify|local_check|manual`
olabilir; Kontrol Kulesi kırma koşularını (`break_verify`, `ortam.break_campaign`) KPI'lara katmaz.

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
Faz 2–3'te core'un yayınladıkları aşağıda listelenir; `failure.classified` ve `bug.published` henüz
yalnızca örnek veri (mock) tarafından üretilir (Faz 4).
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
| POST | `/requirements/{id}/apply-doc-fixes` `{cakismayi_onayla?}` | analyst | Onaylı düzeltmeleri Jira'ya yaz + yeniden kontrol; yazılacak düzeltme ve açık engelleyici yoksa belgeyi açıkça son hal yapar (portal: "Son hal olarak onayla"). Düzeltme güncel döngüdeki bir `accept_difference` kararının maddesini yeniden yazıyorsa 409 (Türkçe, `F1 (tur 1)` etiketli); `cakismayi_onayla:true` ile uygulanır (`requirement.decision_conflict_confirmed`) |
| POST | `/requirements/{id}/po-approve` | po | Serbest metin yolunda PO teyidi (Jira yolunda etiket) |
| POST | `/requirements/{id}/generate-cases` | analyst | Case üretimi |
| GET | `/requirements/{id}/case-metrics` | herkes | Kabul oranı (ilk karara göre, hedef 0.70), ret nedenleri, AI/review süresi, maliyet, `ai_cagri_modlari`, `kapsanmayan_ac` (hiçbir güncel case'in atıf yapmadığı AC'ler), `manuel_baz_ms` (`TP_MANUAL_BASELINE_S`'den; yoksa null) |
| POST | `/requirements/{id}/review-complete` | analyst | Taslak kalmadıysa review'ı kapatır (denetim olayı); taslak varsa 409 |
| GET | `/cases?requirement_id=` · `/cases/{id}` | herkes | |
| POST | `/cases/{id}/viewed` | analyst | Kartın ilk görüntülenmesi (review süresi ölçümü) |
| POST | `/cases/{id}/decision` `{karar: approve\|edit\|reject\|reopen, icerik_hash, icerik?, ret_nedeni?, gerekce?, beklenen_anlam_degisti?}` | analyst | `reopen` ("Taslağa al"): approved/rejected → draft; kayıtlı, onaylamayan karar |
| GET | `/publish/preview?requirement_id=` | analyst | Dry-run; `hedef`, `proje`, `jira_browse_url`, kalem başına `islem` (`create\|skip_existing\|blocked_not_approved\|blocked_hash_mismatch\|blocked_no_story\|blocked_requirement_changed`), `payload` (`mod_etiketi`, `mod_yorumu` dahil), `uretim_modu`, `icerik_hash`, `onaylayan` |
| POST | `/publish` `{case_ids[]}` | analyst | Yayın: worker işi (`publish.cases`; yazma kimliği yalnızca worker'da), 45 sn beklenir → 200 `YayinSonucu`; bitmezse 202 `{job_id, durum, sonuclar: []}`; iş başarısızsa 502 |
| POST | `/code/generate` `{case_ids[]}` | engineer | Kod üretimi (CasesToCode) |
| GET | `/scripts` · `/scripts/{id}` | herkes | Üretilen test + PR + adım görüntüleri |
| POST | `/scripts/{id}/break-verify` | engineer | Kırarak doğrula (BREAK_CAMPAIGN) |
| POST | `/prs/{number}/merge` | engineer | LocalForge'da insan onaylı merge |
| POST | `/prs/{number}/review` `{karar: degisiklik_iste\|reddet, ret_nedeni, icerik_hash, head_sha, not?}` | engineer | Script review reddi; `ret_nedeni` sabit taksonomiden (422) |
| POST | `/prs/{number}/update-branch` | engineer | Geride kalan bot PR dalını main'e taşır (202) |
| POST | `/ci/trigger` `{tetik: deploy\|nightly}` | presenter | Deploy/gece tetiği |
| GET | `/runs` · `/runs/{id}` | herkes | Koşular, test sonuçları |
| GET | `/failures/{id}` | herkes | Triage sonucu |
| POST | `/failures/{id}/fix` | engineer | Locator onarım PR'ı |
| GET | `/bug-drafts` · `/bug-drafts/{id}` | herkes | |
| POST | `/bug-drafts/{id}/decision` `{karar: new\|link, icerik?, link_key?}` | tester | Onay → `publish_bug` |
| GET | `/control-tower` | herkes | Kontrol Kulesi verisi |
| GET | `/audit?verify=true` | herkes | Denetim + zincir doğrulaması |
| GET | `/events` (SSE) | herkes | Olay akışı |
| GET · DELETE | `/tokens` · `/tokens/{id}` | herkes (kendi token'ları) | Listeleme / iptal |
| POST | `/tokens` `{kapsam}` → `{id, kapsam, son_kullanma, token, mcp_url}` | analyst | MCP (Claude Code) kanalı için 8 saatlik token; `mcp_url` = `TP_MCP_PUBLIC_URL`. `/mcp` bağlanana kadar **501** ("IDE (MCP) kanalı henüz etkin değil"); token parola değişince geçersizleşir |
| MCP | `:8000/mcp` → `get_requirement(requirement_key)` (submit kapsamı; PO onaylı metin güvenilmeyen blokta + `onaylanan_hash`), `submit_draft_cases(requirement_key, cases, onaylanan_hash)` (hash zorunlu; bayatsa ret), `publish_test_cases` | token | Claude Code kanalı (streamable HTTP, durumsuz). Token tek kapsamlıdır (`submit` veya `publish`); iki araç için iki token. Yalnızca 127.0.0.1/localhost Host'u, `X-Forwarded-For` → 403, çerez okunmaz. Her çağrı `tool_call` (kanal `ide`). Ayrıntı: docs/CLAUDE-CODE-KANALI.md |
| POST | `/demo/break-locator` · `/demo/reset` | presenter | Demo kırılması / sıfırlama |

**Faz 2 uç ayrıntıları (Demo-A):** `POST /requirements/sync` → 200 `{durum:"done", mesaj, proje,
sonuc:{<jira_key>: yeni|degismedi|guncellendi|yeniden_kontrol|sifirlandi|mesgul}}`. `review`,
`apply-doc-fixes`, `generate-cases` → 202 `{job_id, workflow_id, durum, mesaj}` (apply-doc-fixes
yazılacak düzeltme ve engelleyici bulgu yoksa belgeyi son hale getirip `durum:"done"` döner).
`GET /requirements/{id}/findings` yalnızca kanıtı doğrulanmış bulguları döner; elenen sayısı
`X-Elenen-Bulgu-Sayisi` başlığında ve detayda `bulgu_sayaclari.elenen`. Detay `po` nesnesi
`{durum, onaylayan, zaman, kanal, onaylanan_hash}`. Jira yolunda `po-approve` 409'dur (onay Jira
etiketiyle). Case `mode` IDE'den gelen case'lerde `null`'dur (model çağrısı yok; "live" yazılmaz).
Serbest metin gereksinimin case'leri story olmadığı için yayınlanamaz (`blocked_no_story`).
Gereksinimin PO onayı güncel değilse (durum `cases_ready|done` değil ya da `onaylanan_hash` güncel
içerikle eşleşmiyor) case kararları 409, yayın önizlemesi `blocked_requirement_changed`, yayın
(portal ve MCP) ret döner. Jira etiketiyle verilen PO onayında `generate-cases` ve IDE
`submit_draft_cases` etiketin Jira'da hâlâ durduğunu eşzamanlı denetler (yoksa/okunamazsa 409);
etiket sonradan kalkarsa PO sorgusu gereksinimi `new`'e döndürür (`requirement.po_withdrawn`).
Son tutarlılık turu güvenilmezse (REPLAY-MISS ya da bulguların hepsi elendi) belge otomatik son hal
olmaz: detayda `denetim_guvenilmez` (neden) + `insan_karari_gerekli=true`; analist apply-doc-fixes ile
açıkça son hal yapar. Önceki turda `code_defect`/`accept_difference` ile kapanmış aynı fark yeniden
raporlanırsa bulgu `stale` + `onceki_karar` ile döner (karar istenmez).
**Bulgu kararı (tur 2):** kanıtı doğrulanmış her bulgu, önem derecesi ne olursa olsun (uyarı dahil)
analist kararı ister; açık kararsız bulgu varken tur otomatik son hal olmaz (`findings_open`, neden
"karar bekleyen uyarı bulgusu var"). `apply-doc-fixes` yazılacak düzeltme yokken kararsız
engelleyici bulgu varsa 409 (mesaj bulguları listeler); yalnızca kararsız uyarılar varsa bunları
`accept_difference` olarak kaydeder (portal kanalı, hash bağlı, gerekçe "son hal onayı"), belgeyi
son hal yapar ve yanıta `kabul_edilen_uyarilar: string[]` (ör. `"F2 (tur 1)"`) ekler; PO yorumu
güncel döngünün `accept_difference` bulgularını listeler. Model önerisi `ACn: ` öneki olmadan
açıklamayı hedefliyorsa ve bulgunun `doc_ref`'i açıklamaya atıf yapmıyorsa `fix_doc` kararı 422
döner (analist metni düzenleyerek verebilir). Değişmeyen içerikte yeniden denetim (re-check) açık
ve uygulanmamış `fix_doc` bulgularını yeni tura taşır (tur belge hash'i güncel içerikle eşleşirse);
yeni turda aynı fark tekrar raporlanırsa yeni kopya `stale` ("aynı bulgu önceki turdan açık") olur.
Tam inceleme ve gerçek içerik değişikliği bulguları yine `stale` yapar. Detayda
`on_inceleme.questions[].kararla_cozuldu: string|null`: soru güncel döngüde `fix_doc` /
`accept_difference` kararıyla kapandıysa açıklama (ör. "doküman düzeltmesiyle cevaplandı: F1 (tur
1)"); bu sorular PO yorumunda sorulmaz, "Çözüldü" başlığında bilgi için listelenir. `failed`
gereksinimde (case üretimi hatası) PO onayı `onaylanan_hash` güncel içerikle eşleşiyorsa `po.durum`
`approved` döner; eşleşmiyorsa `not_requested`. `case-metrics` yanıtında `uyarilar: string[]`
(manuel baz değer yoksa "Manuel baz değer girilmedi…", tüm AI çağrıları REPLAY ve süre 0 ise "AI
süresi REPLAY'de ölçülmez…"). Kanıt SQL'i (`sqlguard`, kanıt modu) yalnızca kayıpsız projeksiyon
kabul eder: düz kolon, `lower/upper`, argümansız `trim`, `CAST` → TEXT/VARCHAR (uzunluksuz) /
NUMERIC/DECIMAL (hassasiyetsiz); toplama yalnızca `count(*)`, `count([DISTINCT] col)`,
`min(col)`, `max(col)` ve projeksiyonda en çok bir toplama, diğer öğeler GROUP BY kolonu. PO soru yorumu Jira'ya belge
son hal olduğunda (`requirements.po_request`) bir kez yazılır; üretim modu `mode_label` ile dürüstçe
etiketlenir (elle hazırlanmış golden "kayıtlı model çıktısı" denmez; REPLAY-MISS'te "sorular var"
denmez). `GET /bug-drafts[?requirement_id=]` · `/bug-drafts/{id}` (salt okuma) core'dadır; karar
ucu Faz 4.

**Faz 2 SSE olayları (core yayınlar):** `requirement.updated`, `finding.verified`, `po.approved`,
`agent.step`, `case.generated`, `publish.completed` (`{job_id, requirement_id, requirement_ids,
hedef, sonuclar}`), `publish.failed` (`{case_id, requirement_id, hedef, hata}`); her olay
`requirement_id` taşır (portal konu eşlemesi).

**Faz 2 iş türleri:** `requirements.review`, `requirements.consistency` (max_deneme 1),
`requirements.apply_doc_fixes`, `requirements.po_request` (son halde PO soru yorumu + `tp-po-pending`),
`requirements.po_poll` (kendini `TP_PO_POLL_S`'de bir yeniden
planlar; worker açılışında `on_worker_start` kancasıyla kuyruğa girer), `cases.generate`,
`publish.cases`. Özellik `jobs` modülü isteğe bağlı `on_worker_start(conn)` tanımlayabilir;
worker açılışta her birini kendi işleminde bir kez çağırır (hata worker'ı düşürmez).

**Faz 2 tablolar:** 0006 `requirement_kontrol`, `consistency_finding_ek` (`ref_metni`,
`onceki_finding_id`), `requirement_akis`, `requirement_review_ek` (inceleme anı AC/açıklama
görüntüsü + model özeti);
0007 `case_goruntuleme` (tp_app SELECT/INSERT); 0008 `review_karar_ck`'ye `reopen` (test_case
kararı; `APPROVING`'de değil → taslağa alınan case eski onayla yeniden onaylanamaz/yayınlanamaz).
0008 downgrade `review` satırı silmez (append-only, Anayasa VIII): var olan `reopen` satırları kalır,
eski kısıt `NOT VALID` olarak yalnızca yeni satırlara uygulanır.

**Faz 3 uç ayrıntıları (Demo-B):**
- `POST /code/generate {case_ids[]}` (engineer) → 202 `{job_id, workflow_id, durum, mesaj,
  script_ids, sonuclar[{case_id, durum, script_id, job_id, workflow_id}]}`. Yalnızca onaylı/yayınlı,
  içerik hash'i onaylı hash'e eşit ve gereksinimin PO onayı güncel case'ler (aksi 409; rol 403).
  Aynı onaylı hash için açık/merge edilmiş PR varsa yeniden üretilmez; blocked/failed yeniden üretilir.
- `GET /scripts` · `/scripts/{id}`: `engel{tur, neden}`, `adimlar[]` (`arguman`, `izinli`,
  `ekran_goruntusu_url`), `eslemeler[]` (doğrulama satırında `verified` = değerin onaylı case
  metninde bulunması, uygulamada gözlem değildir), `yerel_kontrol{…, atlandi}`, `dogrulama[]`,
  `kontroller[]`, `uyarilar[]`, `case_ref`, `test_key`, `break_verify{durum, asamalar, neden}`,
  `merge_engelleri[]` (PR yoksa ya da merge edildiyse `[]`), `merge_kabul_gerekli`,
  `gecikme_butcesi_s`, `pr{…, govde (PR açıklaması: izlenebilirlik, eşleme, yerel kontrol,
  denetim zinciri başı), dal{geride, guncelleme, neden}}`. Adım 5 gecikme bütçesi
  `TP_CODEGEN_STEP5_BUDGET_S` (120) aşılırsa SSE `codegen.latency_budget {script_id, sure_s,
  butce_s, oneri}` ve `uyarilar[0]` "REPLAY'e geçmeyi önerin".
- Locator çapraz kontrolü (canlı + REPLAY): her `browser_generate_locator` sonucu page object
  sembol tablosuyla karşılaştırılır; uyuşmazlık ya da gateway'in `REPLAY sapması` notu → adım
  doğrulanmamış (`unverified_step`), PR yok, insana düşer. Ajan oturumu Postgres advisory lock
  (`ajan_kilidi`) altında koşar.
- `GET /scripts/{id}/screenshots/{n}` (giriş yapmış herkes): `tp_codegen` volume'ünden PNG; yol
  doğrulanır. Ekran görüntüsü model döngüsü DIŞINDA ajanın kendi MCP oturumunda alınır (Playwright
  MCP `--isolated` olduğundan ayrı oturum ajanın sayfasını göremez); çağrı ve görüntü modele/
  `tool_call`'a girmez.
- `POST /scripts/{id}/break-verify` (engineer) → 202; sonuç `passed` (yeşil → kırmızı → yeşil),
  `weak` (kırılmada yeşil kaldı: `zayif_test`; kampanyayla ilgisiz testlerde beklenir) ya da `failed`
  (koşu tamamlanamadı). Zayıf test kapı değil işarettir (TEKNIK-TASARIM §2 adım 6): `passed`
  değilse merge isteği `onay_notu` (açık insan kabulü; `review.gerekce` + `codegen.merge_acknowledged`)
  ister; kırma sürerken merge reddedilir. Üç aşama ayrı koşulardır (`run.tetik='break_verify'`).
- `POST /prs/{number}/merge {icerik_hash, head_sha}` (engineer): insan onayı (review `merge`)
  kaydedilir, `codegen.merge` işi `forge.merge_pr(actor, expected_head_sha)` çağırır; ≤20 sn
  beklenir → 200 `PullRequest`, ret 409 (forge gerekçesi, denetim `codegen.merge_refused`), hâlâ
  sürüyorsa 202 `{…PR, job_id, is_durumu}`. Merge sonrası `enqueue_ci(merge_sha, "push")`.
  `head_sha` yoksa 422; PR zaten merge edildiyse 409. Bilinen engeller (kırmızı local-ci, geride
  dal, süren kırma) review satırı YAZILMADAN reddedilir; forge'un öngörülemeyen reddi review
  satırı bırakır (append-only), denetim `review_id` taşır.
- `POST /ci/trigger {tetik: deploy|nightly}` (presenter) → 202 `{job_id, run_id, durum:
  queued|zaten_kuyrukta, mesaj, kaynak, tetik}`. `GET /runs?tetik&kaynak&sonuc&pr_no&script_id&limit`
  (≤200; süzgeçsiz listede açık defect adayının son kırmızı yerel kontrolü her zaman `sabit:true`
  ile eklenir; koşu ayrıca `junit_url`), `GET /runs/{id}`. İmzalı kısa ömürlü bağlantı
  `GET /artifacts/k/{exp}.{hmac}/runs/{run_id}/{path}` (çerezsiz; `TP_SESSION_SECRET`'tan türetilen
  anahtar, `TP_ARTIFACT_LINK_TTL_S` 7200; `rapor_url` bunu kullanır ki sandbox'taki Playwright
  raporu ekran görüntülerini yükleyebilsin). `GET /artifacts/runs/{run_id}/{path}` (giriş yapmış herkes; yalnızca
  `src/**/results/**`, `run.json`, `runner.log`; HTML CSP sandbox ile; dizin → JSON liste; URL'ler
  `/api` önekli). `GET /control-tower`: her KPI `kaynaklar`'da tablo/süzgeç/pencere; geçme oranı
  **koşu bazlı** (son `TP_CT_SON_KOSU` CI koşusu) + `test` alt nesnesi; `gecme_hedefi=null`;
  manuel baz yalnızca `TP_MANUAL_BASELINE_S` varsa. Karne satırı `alan`/`alanlar` (page object
  sınıfından uygulama alanı; eşleme yoksa null = ölçülmedi), `acik_defect_adayi`; üst düzey
  `alan_karnesi[]`. İlk review başarısı birim bazlıdır: birimdeki herhangi bir script'te
  `degisiklik_istendi`/`reddedildi`/`kabul_yabanci_head` varsa birim kabul sayılmaz.
- **Faz 3 SSE olayları (core yayınlar):** `agent.step {script_id, n, tur, tool, summary, izinli,
  screenshot_url}`, `codegen.check {script_id, tur, sinif, sonuc, run_id}`, `codegen.break_verify
  {script_id, durum, asama, sonuc}`, `pr.opened {script_id, case_id, requirement_id, pr_number, url,
  branch, head_sha, guncellendi}`, `pr.merged {script_id, pr_number, merge_sha, aktor}`, `ci.status
  {id, run_id, durum, tetik, kaynak, commit, pr_no, script_id, +sayılar}`, `codegen.latency_budget`,
  `codegen.branch`, `codegen.reviewed`. CI koşusu son denemede hata verirse `error` olur; worker
  açılışında ve yeni tetikte takılı koşular kapatılır (`recover_stuck_run`). GitHub modunda PR CI
  sonucu core-worker tarafından PR'a tek (idempotent) yorum olarak yazılır.
- **Faz 3 iş türleri:** `codegen.generate` (max_deneme 1; takılı kalanlar worker açılışında
  kurtarılır), `codegen.break_verify`, `codegen.merge`, `ci.run`, `ci.github_poll`, `ci.nightly`
  (`ci.nightly:<tarih>` tekil). `tp_core.features.ci.enqueue_ci(session, sha, trigger, pr_number=None,
  *, isteyen, anahtar, ref, script_id)` çağıranın işleminde koşar.
- **Doğrulama ajanı:** bayi `bayi3` (`TP_AGENT_DEALER`); tarayıcıya yazılan case bayisi araç
  katmanında ajan bayisine çevrilir, üretilen test case'in bayisine `test.use({dealerUsername})` ile
  sabitlenir. Her doğrulamadan önce core-worker ajan bayisinin sepetini uygulamanın herkese açık
  API'siyle (`TP_DEMO_WEB_URL`/api: login → `DELETE /cart` → logout) boşaltır. Araçlar: MCP
  `tools/list` ∩ izinli 7 araç (ekran görüntüsü/evaluate/run_code/dosya hiç verilmez), ≤25 çağrı,
  navigasyon yalnızca demo origin'i. `rules/replay/verify_and_map/on_miss.json` `"policy":"raise"`:
  girdi golden beyanına uymazsa başka case'in eşlemesi asla dönmez (script `replay_miss` ile insana).
- **GitHub modunda arayüz merge'ü:** `codegen.pr_sync` (yalnızca `TP_FORGE=github`) GitHub'da insanın
  yaptığı merge'ü çekirdeğe işler: `GitHubForge.pr_merge_info(n)` → `{merge_commit_sha,
  merged_by:{login}}`; karar `review(kanal='github', user_id NULL, harici_onaylayan=<login>)` (0010
  `review_kanal_ck`'ye `github` ekler), ardından push CI.
- **Ajan adım kartı:** `adimlar[].aciklama` (tek satır Türkçe özet) ve `ham_cikti` (temizlenmiş,
  parola maskeli; portalda "Ham çıktı" altında). `eslemeler[].dogrulama_notu`, `merge_kabul_gerekli[]`
  (zayıf test / kırma yapılmadı: merge `onay_notu` ister; portal bu listeyi aynen gösterir).
- **GitHub modu:** aynı kod yolu; `GitHubForge.request()` (genel) + Actions yardımcıları
  (`list_workflow_runs`, `find_dispatched_run`, `download_run_artifact`/`safe_extract_zip`,
  `repository_dispatch`, `workflow_dispatch`). Artefakt sözleşmesi (`test-local-results`,
  `sauce-results`, `break-verify-results`; `ci-meta.json`/`sauce.json`/`break-verify.json`),
  dispatch yükü (`istek_id` ≡ `tp_run_id`, `ref`) ve `run-name` korelasyonu: `.github/CI.md`.
  Kimlik: Contents rw, Actions rw, Checks r. Yalnızca mock'larla doğrulandı.

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
- Model geçidi: `TP_REPLAY_STRICT` (1 = prova: girdisi beyanla eşleşmeyen golden'a düşmez,
  `ReplayMiss` verir; beyanı (`input_match`) eşleşen golden geçer).
- Gereksinim akışı (Faz 2): `DEMOAPP_RO_DATABASE_URL` yalnızca core-worker'da (demoapp_ro; core-api
  demoapp'e bağlanmaz — MCP `get_requirement`'ın test verisi bloğu bu yüzden core-api'de statik
  bilgiye düşer). Ortak blokta (core-api + core-worker): `TP_PO_POLL_S` (15), `TP_CONSISTENCY_MAX_ROUNDS`
  (3), `TP_FORGE_REPO_NAME` (`demo-app`; kod kanıtındaki `evidence.repo`), `TP_FORGE_CHECK_REF` (`main`),
  `TP_MANUAL_BASELINE_S` (story başına manuel test tasarımı baz süresi, saniye; boş = ölçülmedi;
  `make up` önkoşulu ve `make status` boşken "Manuel baz değer girilmedi" uyarısı verir, değer
  uydurulmaz — F0 ölçümünden girilir).
- toolchain-worker: `TP_APP_BUILD_SHA_FILE` (`/forge/demo-app-web.sha`; forge-init, `make break`,
  `make demo-baseline` ve `make up`'taki sync-web otomatik yazar), yedeği `DEMO_APP_BUILD_SHA`;
  `TP_CHECK_REQUIRE_APP_SHA` (0), `TP_CHECKS_PATH` (/checks), `TP_CHECKS_REQUIRE_MOUNT` (1),
  `TP_FORGE_REMOTE_URL`/`TP_FORGE_REMOTE_TOKEN` (GitHub modu, salt okunur; boş = kapalı),
  `TP_FORGE_MIRROR_PATH` (/forge-mirror/demo-app.git). core ortak blokta `TP_CHECKS_PATH` (/checks).
- `PLAYWRIGHT_VERSION`: tek kaynak `.playwright-version`; `make env` `.env`'e de yazar (düz
  `docker compose ps/logs/exec` çalışsın). Gerçek Jira'da `make reset` önce `jira_seed` planını
  yazdırır, onay (`e`) gelirse uygular; ayrıca `make jira-seed [ONAY=1]`.
  `TP_TEST_MGMT` ortak bloktadır: core-api (`/publish/preview`) ve core-worker (yayın) aynı hedefi görür.
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
  çağırır. Faz 2'de yazıldı: son hal (`requirements.po_request`) ve PO sorgusu son halden önceki /
  bayat onay etiketini kaldırıp `tp-po-pending` koyar; onay ancak son hal anından sonraki etiketse
  sayılır (`fresh_approvals`).
- **Deterministik case kimliği:** özellik kodu `test_case`'i `id=models.case_id(requirement, sira_no,
  uretim_no)` ile oluşturur (uuid5; varsayılan yok, `(requirement_id, sira_no, uretim_no)` UNIQUE).
- **Denetim çapası:** `GET /audit?verify=true` yanıtında `verify.anchors` (`checked`, `broken`,
  `sabitsiz`, `eski`); herhangi bir ai_call/tool_call çapası tutmazsa `verify.ok=false`.
  `ai_call.ek` (jsonb, 0005): geçidin kolonu olmayan ayrıntıları (`replay_kaynagi`, `replay_kokeni`
  = `recorded|golden_promoted|golden_matched|golden`, `replay_eslesme` = REPLAY-MISS nedenleri,
  `sema_hatalari`, …); `build_gateway` bunları varsayılan olarak yazar.
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
- **Portal derlemesi (Faz 2 tur 2):** compose'daki portal imajı canlı derlemedir
  (`review-portal/Dockerfile` `ARG VITE_MOCK=0`). Canlı derlemede core'un `openapi.json`'unda olmayan
  uç istenmez, örnek veriye düşülmez: `ApiError(501, BU_FAZDA_YOK)` → ekran "Bu ekran bu fazda yok",
  menü öğesi pasif (bugün `/scripts`, `/runs`, `/control-tower`). Örnek veri derlemesinde her sayfanın
  üstünde "ÖRNEK VERİ — gerçek değil" bandı vardır.
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

**Neden değişti (Faz 2 entegrasyonu, Demo-A):** özellik şeritleri (requirements, cases/publish/MCP,
goldens, toolchain, portal) birleşti. REPLAY anlamı genişledi: golden `input_match` beyanı gerçek
girdiyle eşleşirse mod `replay` (köken `golden_matched`), eşleşmezse `replay_miss` (nedenler
`ek.replay_eslesme`); mod asla `live` değildir (constitution VIII; küratörlü çıktı, girdisi
doğrulanmış — `golden_promoted` ile aynı ilke). `POST /tokens` `/mcp`'yi `include_router`
sarmalayıcılarının içinde de bulur (önceden 501 dönüyordu). Case "Taslağa al" kayıtlı karar oldu
(0008). Yayın SSE olayları ve önizlemede `jira_browse_url` eklendi. toolchain-worker forge'u salt
okur. Ajan araç adları `ALLOWED_AGENT_TOOLS` ile sabittir (consistency_check: search_code,
get_file_contents (satır aralığı + dizin listesi), db_schema, db_query); PO kimliği yalnızca
e-posta/accountId ile eşlenir (displayName asla). Gereksinim durum makinesinde
`po_approved → pending_po` yoktur: PO etiketi geri alınırsa gereksinim `new`'e döner (tam yeniden
inceleme; eski `po_approve` kaydı kapıyı yeniden açamaz — bilinçli tercih).

**Neden değişti (Faz 2 entegrasyonu, 1. inceleme turu):** inceleme A→B→A düzeltmesinde bayat
idempotens kaydının Jira yazımını atladığını, bulguların inceleme döngüleri arasında karıştığını, golden'ı
olmayan story'nin nedensiz `failed` olduğunu, SQL korumasının (sütun takma adı listesi, LATERAL,
VALUES, birleştirme) kanıt üretmeye açık olduğunu, kalıcı PO yorumu hatasının `pending_po`'yu sessizce
kilitlediğini, yayının Jira PO etiketini yayın anında denetlemediğini ve portalın denetim sürerken
"tutarlı" dediğini buldu. Sözleşmeye yansıyanlar:

- **Gereksinim detayı:** `son_hata {neden, zaman, job_tur, is_hatasi, oneri, yeniden_denemek_ise_yarar}`
  (son başarısız geçiş/iş; `uyarilar`'a da "Son işlem başarısız: …" girer), `po_istegi {durum:
  yazildi|bekliyor|basarisiz, jira_comment_id, hata}` (kalıcı hatada PO sorgusu isteği yeni idempotens
  anahtarıyla yeniden kuyruğa alır: `requirement.po_request_requeued`). Bulgu `bulgu_etiketi`
  (`"F2 (tur 1)"`, Jira düzeltme yorumuyla aynı). Varsayılan `/findings`, `X-Elenen-Bulgu-Sayisi` ve
  `bulgu_sayaclari` **güncel inceleme döngüsüyle** sınırlıdır (sıfırlama / PO geri çekmesi yeni döngü
  açar); `?tumu=true` tüm geçmiş.
- **Jira PO onayı tazeliği:** eşik `max(son hal anı, PO soru yorumunun Jira oluşturma anı)`; yorum
  yokken hiçbir etiket sayılmaz. Bayat etiket kaldırılırken yarış (`remove_stale_approval`) Jira
  yorumuyla PO'ya bildirilir ve `requirement.po_label_removed` (`sonuc=yarista_kaldirildi`) yazılır;
  bot etiketi yeniden ekleyemez (§6).
- **Kanıt SQL'i:** `kanit=True` sorgusu tek tablo, birleştirmesiz, alt sorgusuz olmalı; tablo takma
  adı sütun listesi taşıyamaz ve sütun/tablo adıyla çakışamaz; LATERAL/VALUES/UNNEST/TABLESAMPLE/pencere
  reddedilir. Doğrulayıcı yeniden üretilen SQL'i `dogrulama[].neden`'e yazar; boş sonuç
  "yalnızca bu koşulla satır olmadığını kanıtlar" diye etiketlenir. Kod kanıtında `repo`
  `owner/<repo>` ve `<repo>@<sha>` biçimleri `<repo>`'ya indirgenir (dosya yine denetim commit'inde okunur).
- **Doküman düzeltmesi idempotensi:** açıklama yazım anahtarı
  `jira:update_description:{req}:{workflow|job}:{önceki}->{yeni}`; `created` kaydı varken Jira hash'i
  `yeni` değilse kayıt yeniden yazılır (`external_ref.stale`).
- **Golden'sız story:** gateway, amacın `on_miss.json` çıktısını `replay_miss` (köken `miss_neutral`)
  olarak döner (asla `replay`/`live` değil); `case_generation/on_miss.json` `policy: raise` →
  `ReplayNoOutput` (sıfır taslak, iş kalıcı hata). Başarısız her REPLAY araması çıktısız bir
  `ai_call` (`replay_miss`) satırı yazar (VIII). Aynı anahtar öneki için sonraki tur golden'ları
  (`<KEY>-rN`) içerik eşleşmesine göre seçilir.
- **Case'ler:** case nesnesi `ai_icerik`, `fark[{alan, etiket, once, sonra}]`, `duzeltme_nedeni`,
  `onceki_icerik`; `case-metrics` `review_sure_ms` artık karar aralıklarının **birleşimi** (duvar saati;
  `review_sure_yontemi='aralik_birlesimi'`), eski toplam `kart_sure_toplam_ms`; ayrıca
  `onceki_icerik_case_ids`, `uyarilar`. Portal üretimi karar verilmemiş IDE taslaklarını korur
  (`korunan_ide_taslak`). Bayat PO onaylı içeriğe ait yayınlı case'ler tekrar/kapsam sayılmaz.
- **Yayın:** Jira etiketli PO onayında yayın, Jira'ya yazmadan önce etiketi yeniden okur (yoksa ya da
  okunamazsa kalem `failed`, fail-closed). MCP `publish_test_cases` herhangi bir kalem
  `created|exists` değilse `isError=true` + `ozet`. `publish.anchored` özeti `case_ids`,
  `external_keys`, `kurtarma` taşır (yayın sonrası çöküşte çapa yeniden denemede tamamlanır).
- **Denetim olayları (yeni):** `external_ref.stale`, `requirement.decision_conflict_confirmed`,
  `requirement.po_request_requeued`, `requirement.po_label_removed`, `mcp.auth_failed` (401/403/421;
  ham token yazılmaz, `token_izi`=sha256[:12], 10 sn'de bir hız sınırı).
- **Platform:** PO onayı geri çekildikten sonra eski `po_approve` `failed → generating`'i açamaz
  (`approval_consumers`). Worker açılış kancaları DB hazır olana kadar 10 sn'de bir yeniden denenir.
  `kilitleyen` = `hostname:pid:açılış_kimliği`; `release_orphans` yalnızca önceki sürecin
  (`TP_WORKER_STATE_FILE`) ve kalp atışı 30 sn'den eski işlerini bırakır (ölçeklenmiş kopyalara dokunmaz).
- **Ortam:** core `TP_DATABASE_URL`'e `require_auth=scram-sha-256` ekler (`TP_DB_REQUIRE_AUTH`;
  boş = kapalı); compose `DEMOAPP_DATABASE_URL` ve `DEMOAPP_RO_DATABASE_URL`'de aynısı vardır
  (`make security-check` 5 denetler). `TP_HEALTH_TIMEOUT_S` (test-runner, 5).
  `TP_MANUAL_BASELINE_S` `.env.example`'da belgelendi (boş = ölçülmedi). `rules/models.yaml` amaç
  başına `timeout_s` (bundle hash'ine girmez). `make reset` sonunda `make seed` çalışır.
- **Portal:** publish için nginx `location = /api/publish` 75 sn (`BEKLEME_S`+15); diğer `/api/` 30 sn.
- **Faz 3:** core-worker `TP_AGENT_DEALER` (bayi3), `TP_AGENT_DEALER_PASSWORD` (Demo123!),
  `TP_DEMO_WEB_URL` (http://demo-app-web:8080), `TP_CI_NIGHTLY_SAAT` (02:00 Europe/Istanbul;
  `kapali` kapatır), `TP_CI_GITHUB_POLL_S` (30), `TP_CI_GITHUB_TIMEOUT_S` (5400); core ortak
  `TP_CODEGEN_ARTIFACTS_PATH` (/codegen-artifacts; boşsa `TP_ARTIFACTS_PATH`), `TP_CT_SON_KOSU`
  (20), `TP_CT_FLAKY_GUN` (30), `TP_CT_TREND_GUN` (14); test-runner `TP_RUNS_KEEP` (50, compose'da
  verilmez = varsayılan).

**Neden değişti (Faz 3 entegrasyonu, Demo-B):** inceleme, test-runner'ın (commit'ten gelen kodu
koşturan servis) merge kapısı dosyasının bulunduğu `tp_artifacts`'a yazabildiğini, yerel kontrolün
çalışan uygulamanın commit'ini denetlemediğini, GitHub arayüzünde yapılan merge'ün yanlış kanalla
(`portal`) yazıldığını ve Allure bağlantısının ham JSON listesi olduğunu buldu. Sonuç: kapı ayrı
`tp_checks` volume'üne taşındı (`make security-check` 10/10), `/forge/demo-app-web.sha` betiklerle
yazılıyor ve `/check` `app` adımı uyuşmazlıkta koşmuyor (core: `ortam`), `review.kanal='github'`,
statik Allure raporu. **Demo'nun ana yolu** `f2-kod-hatasi` REPLAY senaryosudur (F2 ve F4
`code_defect`; docs/DEMO-VERISI.md); `make demo-check` sunumdan önce bunu doğrular.

## 7. Kalite kapısı (her şerit)
- Python: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` yeşil.
- TypeScript: `npm run build` (tsc strict) ve varsa `npm test` yeşil.
- Kendi dizini dışındaki dosyaya dokunmaz; commit atmaz; tam `make up` yapmaz (entegrasyon liderin).

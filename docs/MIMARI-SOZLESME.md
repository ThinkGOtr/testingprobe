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
| Mobil/masaüstü cihaz (009) | — (app-mcp / test-runner Appium'a W3C WebDriver ile bağlanır) | GitHub Actions emülatör / simülatör / `windows-latest` | hosttaki Appium 3 + Android emülatörü / iOS simülatörü (`make cihaz-*`); Windows: isteğe bağlı UTM VM | `APPIUM_URL_ANDROID\|IOS\|WINDOWS` (boş = platform kapalı) |

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
| app-mcp (009, `mobil` profili) | Uygulama doğrulama ajanının aracı (`toolchain/app-mcp`): `app_*` araçları, yalnız yapılandırılmış uygulama; core-worker'dan `APP_MCP_URL` (app-mcp-net) | — |
| appium-gw (009, `mobil` profili) | test-runner → hosttaki Appium için sabit hedefli TCP yönlendirici (`host.docker.internal:4723`; appium-net → cihaz-net) | — |

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
- **Faz 4 ekleri (geriye uyumlu):** `/locator-probe` isteğe bağlı `candidate_test_id` (takma ad
  `test_id`) ve `aria_snapshot_rel` (runs/ altında referans snapshot; geçersiz yol tarayıcı açılmadan
  422) alır; yanıt ayrıca `aday{test_id, matches, rol_ad_eslesen, gecerli, yoklanan_ile_ayni}`,
  `aria_dogrulama`, `page_matches`, `aria_snapshot`, `aria_snapshot_scope`, `engeller[]` (Türkçe)
  taşır; `oneri_uretilebilir = engeller == []`. sha eşleşmesi commit değil `web`+`api` ağaçlarıyla
  yapılır (onarım merge'ü yalnızca e2e'yi değiştirir). Yeni uçlar: `POST /aria-match {role, name,
  aria_snapshot_rel|aria_snapshot, scope_role?, scope_name?}`, `POST /trace-summary {trace_rel, role?,
  name?, scope_test_id?}` (zip diske açılmaz; boyut/üye/oran sınırlı; rol+ad `yaklasik:true`),
  `POST /affected-tests {sha, changed?|base_sha?}`. `/check` `affected_by` (`[yollar]` ya da
  `"@diff"`) → `kapsam.etkilenen`; `test_files`/`grep`/`record_check:true` ile birlikte 422; bilinmeyen
  dosyada tam paket (demo'da her spec pages/index.ts'i içe aktardığı için locators.ts değişikliği tam
  pakettir). Hata girdileri ek alanlar: `locator_test_ids`, `locator_test_id`, `locator_scope_test_id`,
  `locator_role`, `locator_name`, `aria_snapshot_rel`, `trace_rel`, `page_location`. `/ast-guard`
  repair modu gerçek forge commit'inde doğrulandı (ad/rol/within değişimi, page object düzenlemesi,
  anahtar/dosya ekleme reddedilir).
- **Çalışan uygulamanın commit'i:** demo-app-web `GET /build.json` → `{service, sha, web_tree}`
  (`DEMO_APP_BUILD_SHA`/`DEMO_APP_WEB_TREE` build arg'ları; hex dışı değer derlemeyi düşürür; boş =
  `""`). `scripts/forge-init.sh` (break/baseline/sync-web) ve `scripts/demo-web-sync.sh` bunları geçirir.

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

**009 Java yolu (ayrıntı `toolchain/README.md`, `toolchain/java-araclar/README.md`):** `/symbols`,
`/check`, `/ast-guard` isteğe bağlı `lang` (`ts|java`) ya da `platform` (`web|android|ios|windows`)
alır; yoksa web/TS (eski gövde değişmez). Java'da sembol tablosu `java-araclar symbols` (aynı şema,
`params[].type` Java türü), statik kapı Maven `test-compile` + `java-araclar guard`, `test_files`
e2e-app köküne göre `src/test/java/…Test.java`. Kayıtlı kontrol adı platform başınadır:
`local-ci-android|ios|windows` (web `local-ci` değişmez).

**011 web + Java yolu (`specs/011-uretim-dili/plan.md` §2.6, inceleme turu 1 K-T1):**
- **Kabul kuralı (`/symbols`, `/check`, `/ast-guard`):** gövde `{lang, platform}`. `lang` yalnız
  `ts|java` (`csharp|python` toolchain'e hiç gitmez → 422). `lang="java"` + `platform="web"` (ya da
  `platform` yok) → web + Java, kök **`TP_E2E_JAVA_ROOT`** (varsayılan `e2e-java`; GitHub kipinde
  `demo-app/e2e-java`), güvenilir pom **`TP_E2E_JAVA_DEPS`** (imajda `/opt/e2e-java`: `pom.xml` +
  ısıtılmış salt okunur `m2`). `lang="java"` + uygulama platformu → `TP_E2E_APP_ROOT` (009,
  değişmez). `lang="ts"` + uygulama platformu → 422. Gövdesiz/eski istek web + TS'dir.
- Java web adımları uygulama Java ile aynı adlardadır: `app → deps (pom kilidi) → guard → compile →
  run`; rapor `lang:"java"`, `platform:"web"` taşır; tarayıcı imajdaki `/ms-playwright` (indirme yok).
- **Check adı (tek kaynak `platform.check_adi(platform, dil)`; core, toolchain worker `check_name`
  ve portal aynalar):** web + TS **`local-ci`** (değişmez) · web + Java **`local-ci-web-java`** ·
  uygulama `local-ci-<platform>`. Kardeş koşular aynı sha'ya farklı adla yazar; birbirini ezmez.
  GitHub karşılığı: `test-local` (TS) · `web-java` (Java) · `mobil-android|masaustu-windows`.
- **Yerel merge kuralı:** `e2e-java/` değişen PR `local-ci-web-java`, `e2e/` değişen PR `local-ci`
  ister; script'siz PR'da CI değişen yollardan dil(ler)i seçer, ikisi de değiştiyse ikisi de koşar.

### test-runner HTTP API (:8200, yalnızca runner-net)
- `POST /run {sha, grep?, repeat_each, retries, env:{BREAK_CAMPAIGN?}, run_id}` → `{status: passed|failed|error, junit, json, artifacts_dir, duration_ms, saglik:{ok, zaman, web:{url,status,ms,hata}, api:{url,status,ms,hata}, hata}}`
- Koşudan önce `GET BASE_URL/` ve `GET DEMO_API_URL/health` (`TP_HEALTH_TIMEOUT_S`, 5 sn) yoklanır.
  `saglik.ok=false` → Playwright başlatılmaz, `status=error`, `tests=[]`. Faz 4 triage
  `saglik.ok == false`'u (ya da `saglik`'sız `error` koşusunu) locator/test bakımı yolundan önce
  deterministik `environment` sinyali sayar (TEKNIK-TASARIM §8.6 kural 1).
- `env.BREAK_CAMPAIGN=1` Playwright sürecine geçer (API konteynerine değil): e2e fixture'ı koşunun
  bayisi için `POST /test/break {kullanici_adi, kampanya:true}` çağırır, teardown'da kapatır; diğer
  bayiler ve ajan tarayıcısı etkilenmez. Yeşil → kırmızı → yeşil kanıtı `demo-app/ci/break-verify.sh`.
- **009:** `POST /run {…, lang:"java", platform}` `demo-app/e2e-app`'i (`TP_E2E_APP_ROOT`) Maven +
  Surefire ile koşturur (`runner/java_run.py`); sağlık adımı ayrıca `APPIUM_URL_<PLATFORM>/status`
  yoklar. Rapor: Surefire JUnit XML, Allure, kanıt `target/kanit/<Sınıf>.<metot>/`.
- **011:** `POST /run {…, lang:"java", platform:"web"}` `demo-app/e2e-java`'yı (`TP_E2E_JAVA_ROOT`)
  koşturur: Appium sağlık kontrolü yok, API + web origin yoklanır, `repeat_each` desteklenir (web
  varsayılanı 3), tarayıcı imajdaki `/ms-playwright`. Kanıt `target/kanit/<Sınıf>.<metot>/{ekran.png,
  trace.zip, sayfa.html}` (triage web yöntemi). Bellek: Surefire `argLine -Xmx512m -Dfile.encoding=UTF-8`.
  Raporlar: Extent test adı = TestNG description (`Sınıf.metot` alt bilgi; `tp-case-*` kategoriye
  girmez), Allure etiketleri `story`, `tp-case`, `tag` TestTabani'ndan.

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

**011 üretim dili (0021 `script_dil`, `specs/011-uretim-dili/plan.md` §2.2):** `script.dil` (`ts|java|csharp|python`,
NOT NULL, sunucu varsayılanı `'ts'`, CHECK `script_dil_ck`; backfill web→`ts`, uygulama→`java`),
`script.dil_kaynagi` (`algilandi|secildi|varsayilan`, varsayılan `varsayilan`), `script_codegen.kaynak_kod`
(TEXT NULL; yalnız doğrulanmamış dillerde render edilen kaynak, forge'a commit edilmez). Geçerli
(platform, dil): web × her dil; uygulama × yalnız `java` (DB'de çift CHECK'i yok — göç penceresi;
runbook backfill'i `docs/GCP-KURULUM.md` §10.2 adım 7). SCRIPT durum makinesine uç durum `unverified`
(`verifying → unverified → pending|closed`; onay/merge yok). Etkin script anahtarı (case, platform)
kalır; **`unverified` etkin sayılmaz** (K-T4): doğrulanmamış üretim aynı case+platformun
`pr_open`/`merged`/devam eden script'ine dokunmaz (kapatma, forge'a yazma yok); eski `unverified`
kayıtlar yenisi gelince `closed`. Tam hat dilinde istek, aynı case+platformda başka dilde
`merged` script varsa 409 — mesaj çıkış yolunu söyler ("mevcut test dosyasını silen bir PR'ı merge
edin, sonra yeniden üretin"); toplu istekte çakışan case sayısı yanıt mesajına ve portala yansır;
kaldırma ürün akışı değildir (K-T12; elle adım `docs/GCP-KURULUM.md` §10.2 adım 12). `_eski_prlari_kapat` yalnız tam hat yolunda çalışır. Koşu kaydı dili
**`run.ortam.dil`**'de taşır (`ts|java`; yoksa `ts` sayılır; idempotency kilidi ve etkin koşu
araması web'de dile göre ayrılır, portal koşu listesinde dil rozeti gösterir). Script'siz web
koşusunda kardeş dil dağıtımı **`run.ortam.dil_dagitimi`**'na yazılır (`["ts","java"]` gibi; ilk
eleman bu koşunun dili, diğerleri `ortam.kardes_kosu` = bu koşu olan kardeş koşulardır). Alanın
varlığı dağıtımın yapıldığını gösterir (yeniden denemede tekrarlanmaz); kardeş koşularda yazılmaz.
K-T11: script'siz PR'da test köklerinin (`e2e/`, `e2e-java/`, `e2e-app/`) DIŞINDA değişiklik varsa
repodaki tüm tam hat dilleri dağıtılır; yalnız test kökü değişen PR'da değişen kökün dili. GitHub'da
`web-java.yml` yol süzgeci daha dardır (ör. yalnız `mobile/`/`desktop/` değişen PR'da Java koşmaz,
`web-java` no-op yeşil; LocalForge koşar).

**Faz 4 tablolar:** 0011 `failure_ek` (failure ile 1:1, cascade: `anahtar` (koşu+test, tekil),
`kaynak` ∈ ci|codegen|kirma, `script_id`, `kanit` (özet + toolchain ham kaydı `ham{failure, statuses,
consistent}`), `kanit_linkleri`, `oneri` (locator önerisi: `locator_key, old_testid, new_testid, dosya,
rol, ad, within, scope_test_id, url_path, sha, probe{dört sha alanı dahil}, aria_satirlari,
son_yesil_run_id`), `oneri_yok_nedeni`, `llm`), `triage_kosu` (koşu başına `done|skipped` + neden).
`failure.id` uuid5(koşu+test) — aynı koşu iki kez sınıflandırılmaz. 0012 `bug_draft_ek` (bug_draft ile
1:1; hash'lenen içeriğin dışında kalanlar: hata imzası, JQL + arama sonucu, dup_rank çağrısı/modu/önerisi,
hazırlık durumu, ham AI taslağı ve uygulanan düzeltmeler, düzenleyen, `ilgili_failure_ids` (aynı imzalı
açık taslağa eklenen hatalar), yayın sonucu). Onarım ayrıntısı ayrı tabloda değil, hash zincirli denetim
özetlerindedir (`repair.proposed/checked/pr_opened/blocked`); script satırı `tur='locator_fix'`,
`failure_id`, `branch`, `head_sha`, `pr_no` taşır.

**Faz 5 tablolar:** 0013 `requirement_baz_deger` (story başına manuel baz değer girişleri,
append-only: `sira`, `islem set|clear`, `deger_s` (`set`'te 0 < x ≤ 144000, `clear`'da NULL),
`onceki_s`, `giren`, `giren_rol`, `not_metni`, `zaman`; güncel değer = en büyük `sira`; tp_app
yalnızca SELECT/INSERT; requirement silinince cascade). Denetim: `requirement.baseline_set` |
`requirement.baseline_cleared` (`once`/`sonra`: `deger_s, kaynak, giren, not, sira` + `jira_key`,
`rol`). Model kipi denetimi: `worker.model_mode` (core-worker açılışında, değiştiyse; `{ayar, mod,
replay_strict, anahtar_var, calisma_alani_var, saglayici}` — anahtar/çalışma alanı DEĞERİ asla).

**Asistan tabloları (0017 `asistan`, ayrıntı `specs/008-ai-asistan/data-model.md`):** `asistan_sohbet`,
`asistan_mesaj` (kısmi tekil indeksler: `unique(ust_mesaj_id)`, kullanıcı başı tek bekleyen
`WHERE rol='assistant' AND tetik='kullanici' AND durum IN ('pending','running')`; `check(tetik='kullanici'
OR (ust_mesaj_id IS NOT NULL AND amac='assistant_deep'))`), `asistan_durum` (tekil satır `id = 1`;
yalnız worker yazar), `asistan_oneri_geri_bildirim`, `asistan_hiz` (`unique nulls not distinct`).
`tool_call.kanal` ∈ `agent|ide|asistan`. `ai_call`'a kolon eklenmez: asistan çağrısının kişi bağı
`ai_call.ek = {kanal:"asistan", kullanici_id, mesaj_id}`. `asistan_mesaj.durum` durum makinesinde değildir
(insan kapısı yok). Saklama 90 gün (`TP_ASISTAN_SAKLAMA_GUN`); `ai_call`/`tool_call` etkilenmez.

**Asistan güvenlik olayı (0023 `asistan_guvenlik`, ayrıntı `specs/013-asistan-guvenlik/ANALIZ.md`
§6):** `asistan_guvenlik_olay(id, kullanici_id, mesaj_id null, tur, ciddi, ayrinti jsonb, zaman)`;
indeksler `(kullanici_id, zaman desc)` ve kısmi `(mesaj_id) WHERE mesaj_id IS NOT NULL`; tp_app
yalnız `SELECT, INSERT, DELETE` (UPDATE yok). `tur` ∈ `sir_icerik|kisisel_veri|kanarya|
istem_sizintisi|sinyal|donduruldu`; `ciddi` = `sir_icerik|kanarya|istem_sizintisi`. `mesaj_id`
olayın kullanıcı sorusudur (derin cevaptaki sızıntı da kök soruya; sızan cevabın kimliği
`ayrinti.cevap`). `ayrinti` yalnız kimlik/sayı (soru metni, değer, eşleşen parça asla). Dondurma
(K11): son temiz kabul edilen sorudan (ilk cevabında ciddi olay olmayan) sonraki ciddi olay ≥ 3 ve
sonuncusu ≤ 10 dk → 429 `donduruldu`; aynı sorudaki tekrarlanan `istem_sizintisi` bir kez sayılır,
derin cevaptaki sızıntı önceki sıfırlamayı geri almaz. Girdide ya da araç sonucunda geçen yabancı
kanarya/iz cümlesi alıntıdır, sızıntı sayılmaz (yalnız bu sürecin kanaryası her zaman). Denetim:
dondurmanın ilk reddinde bir kez `asistan.supheli` (aktör ve nesne `app_user:<uuid>` takma adı;
`{ardisik_ciddi, sure_s}`). Saklama 90 gün (`temizlik.py`).

**012 kalite doğrulama tabloları (0034 `kalite_dogrulama`, `down_revision="0033"`; `feat/case-gen-v3`
birleşmesinde v3 zinciri 0034'ün üstüne gelir — ANALIZ §14; ayrıntı
`specs/012-test-kalite-dogrulama/ANALIZ.md` §5, §11.3, §12, §13.2):** `karar_tablosu` ve `metamorfik_iliski`
(içerik JSONB, `icerik_hash`, `onaylanan_hash`, `durum` draft|pending_po|approved|superseded — iş akışı
makinesi, onay `record_approval` + görülen hash; `gereksinim_hash` ile bayatlık; `UNIQUE
(requirement_id, sira_no)`), `case_oracle_kontrol` (`UNIQUE (test_case_id, icerik_hash)`; `sonuc`
uyumlu|uyumsuz|kapsam_disi|kontrol_edilemedi, `ayrintilar` JSONB, `tablo_hashleri` `{<tablo id
metni>: icerik_hash}` — kayıt yalnız güncel kapsayan tablolarla aynıyken geçerli, `ai_icerik`,
istisna alanları), `metamorfik_turetme` (`UNIQUE (iliski_id, kaynak_case_id)`), `hata_kosusu`
(iş durumu, makinede değil) ve `hata_kosusu_adim` (`asama` temel|hata|kapanis, `sonuc`
bekliyor|yakalandi|kacti|gecersiz|yesil|kirmizi). `tp_app`: SELECT, INSERT, UPDATE (DELETE yok).
Ekilmiş hata koşuları `run.tetik='break_verify'` + `ortam.hata_kodu`, `ortam.hata_kosusu_id`
yazar (KPI'lara girmez, triage sınıflandırmaz).

## 5. HTTP API (core-api, portal `/api/` önekiyle erişir)

Tüm yanıtlar JSON; hata `{"detail": "...", "kod": "..."}` (`kod` sabit enum, aşağıda "Hata `kod`
alanı"; `detail` insan içindir ve korunur). Oturum: `tp_session` çerezi (itsdangerous imzalı, HttpOnly,
SameSite=Lax). Oturum sunucu tarafındadır (`oturum` tablosu): çıkış o tarayıcının oturumunu iptal eder,
kopyalanan çerez de geçersizleşir.

**Yetki (012, `specs/012-rol-yetki/ANALIZ.md` §4):** her uç bir izin anahtarı ister
(`Depends(izin("case.approve"))`); izin → rol eşlemesinin tek kaynağı `tp_core/auth/yetki.py`
(`IZINLER`). Katalogda olmayan izin hiçbir role verilmez (varsayılan ret). Red 403
`{"kod": "yetki_yok"}` döner ve `authz.denied` (`{izin, rol, neden, kanal}`, yol) olarak denetim
kaydına isteğin işleminden ayrı yazılır. Katalog testi her router ucunun bir `izin(...)` taşıdığını
ya da açık istisna olduğunu denetler. İstisnalar (izin anahtarı yok): `/auth/*`, `/api/auth/aiprobe/*`
(giriş akışı), `/admin/kimlik-bagi` (servis kimliği), `/mcp` (bearer token kapsamı), `/health`.
Roller (8): `admin` Sistem Yöneticisi, `auditor` Denetçi, `analyst` Analist, `po` PO, `tester` Testçi,
`engineer` Automation Engineer, `developer` Developer, `viewer` Görüntüleyici. Kaldırılan `presenter`
`admin` sayılır (göç `app_user.rol`'ü çevirir; AI Probe devrinde gelen `presenter` geçiş süresince
`admin`). Görevler ayrılığı role göredir (K2). Aşağıdaki tabloda "İzin" sütunu bu anahtardır.

**İnsan kararlarında içerik bağı (TOCTOU):** her karar gövdesi (`/findings/{id}/decision`,
`/cases/{id}/decision`, `/bug-drafts/{id}/decision`, `/requirements/{id}/po-approve` (serbest metin),
`/prs/{number}/merge`) kullanıcının ekranda gördüğü içeriğin `icerik_hash`'ini taşır; router
bunu `record_approval(..., beklenen_hash=icerik_hash)` olarak geçirir. Portal kanalında zorunludur
(eksikse 422); içerik o arada değiştiyse 409 döner ve portal içeriği yeniden yükler. Merge ayrıca
onaylanan head sha'sını `ForgePort.merge_pr(..., expected_head_sha=...)` ile bağlar.

**CSRF / Origin (`OriginGuard`, tüm uçlar):** POST/PUT/PATCH/DELETE isteklerinde `Sec-Fetch-Site`
varsa `same-origin` veya `none` olmalı; yoksa `Origin` varsa `TP_ALLOWED_ORIGINS` listesinde olmalı
(`null` reddedilir). İkisi de yoksa istek tarayıcı dışı istemci (curl, MCP bearer) sayılır ve geçer.
Ret: 403 `{"detail": "İstek başka bir kaynaktan geldi; işlem reddedildi", "kod": "kaynak_reddi"}`. Kural oturum çerezinden
bağımsızdır (giriş CSRF'i de kapsanır).

**SSE olayları (`GET /events`):** zarf `{data, ts}`. Olay adları: her durum makinesi için
`<entity>.state` (`requirement`, `consistency_finding`, `test_case`, `script`, `bug_draft`,
`workflow_instance`) ve `review.recorded` (`nesne_turu`, `nesne_id`). Portalın ayrıntılı adları
(`agent.step`, `ci.status`, `pr.opened`, `failure.classified`, `case.generated`, `bug.published`)
Faz 2–4'te core'un yayınladıkları aşağıda listelenir (Faz 4'ten beri `failure.classified` ve
`bug.published` de core'dan gelir).
Akış her olaydan önce ve boştayken 15 sn'de bir oturumu yeniden denetler; oturum kapatılmış, iptal
edilmiş, süresi dolmuş, parola değişmiş veya kullanıcı silinmişse son olay `event: session.ended`
gönderilir ve akış kapanır. Portal bunu alınca yeniden bağlanmaz, giriş ekranına (`/giris`) döner.

| Yöntem | Yol | İzin | Amaç |
|---|---|---|---|
| POST | `/auth/login` `{kullanici_adi, parola}` | — | Oturum |
| POST | `/auth/logout` | oturum | AI Probe oturumunda yanıt `{ok, redirect}` (`{AIPROBE_ID_ORIGIN}/logout?product=testing-probe`) |
| GET | `/auth/aiprobe/login?continue=` | — | `aiprobe`/`both`: `state` çerezi + 302 `id.` giriş sayfası (TEKNIK-TASARIM §8.14) |
| GET | `/auth/aiprobe/callback?code=&state=` | — | Devir kodu takası → oturum (302 `continue`) ya da rol seçici (302 `/rol-sec?continue=`); hata `durum_uyusmuyor` 400, `giris_kodu_gecersiz` 400, `kimlik_servisi_yok` 503, `org_reddi`/`rol_yok` 403 |
| GET | `/auth/aiprobe/hesaplar` | — | Seçim çerezi ya da AI Probe oturumu: `{hesaplar: [{id, kullanici_adi, rol, gorunen_ad}], aktif_id, continue}` |
| POST | `/auth/aiprobe/rol-sec` `{app_user_id}` | — | Rol seçici: seçim çereziyle oturum açar |
| POST | `/auth/aiprobe/rol-degistir` `{app_user_id}` | AI Probe oturumu | Bağı ve rolü yeniden doğrular, yeni oturum kimliği |
| GET · PUT · DELETE | `/admin/kimlik-bagi` (`?external_uid=`) · `/admin/kimlik-bagi/{app_user_id}` · `/admin/kimlik-bagi/hesaplar` | `aiprobe-home` servis kimliği | Kişi ↔ rol hesabı bağları (`PUT {external_uid, app_user_id \| kullanici_adi}`) |
| GET | `/auth/me` | `dashboard.read` | `{id, kullanici_adi, rol, gorunen_ad, ad_soyad, kisiler, izinler}` — `izinler` rolün izin anahtarları (sıralı; portal menü/sayfa/düğmeyi buna göre gösterir, kontrol çekirdektedir); `gorunen_ad` ("Cengizhan Gunaydin · Analist"), `kisiler` (`{kullanici_adi: gorunen_ad}`) yalnızca gösterim; yetki `rol` ile (`TP_GORUNEN_ADLAR`) |
| GET | `/requirements` | `requirement.read` | Story listesi (Jira'dan çekilmiş + durum) |
| POST | `/requirements/sync` | `requirement.import` | Jira'dan çek |
| POST | `/requirements/free-text` `{baslik, aciklama, ac[]}` | `requirement.import` | Serbest metin gereksinim |
| GET | `/requirements/{id}` | `requirement.read` | Detay + durum makinesi durumu + `baseline` (aşağıda) |
| GET | `/requirements/{id}/baseline` | `requirement.read` | Story başına manuel baz değer + geçmiş (`gecmis[]`, en yeniden eskiye) |
| PUT | `/requirements/{id}/baseline` `{deger_s: int (saniye, 0 < x ≤ 144000), not: str (zorunlu kaynak notu, ≤500, ör. "F0 ölçümü – İsmail")}` | `baseline.manage` | Ölçüm girer (katı tam sayı; dizge/ondalık/bool 422); aynı değer + not → `degisti:false`, kayıt/denetim yok |
| DELETE | `/requirements/{id}/baseline?not=` | `baseline.manage` | Ölçümü kaldırır (geçmiş kalır; `not` isteğe bağlı) → story varsayılana / ölçülmedi'ye düşer |
| GET | `/baseline-file` | `requirement.read` | `rules/baz-degerler.yaml` durumu: `{yol, var, girdi, hatalar[], girdiler[{story, deger_s, giren, not, requirement_id, etkin_kaynak, etkin_etiket, etkin_deger_s, etkin_giren_rol}]}` (demo öncesi "TPD-1 ölçüm okuyor mu" kontrolü) |
| POST | `/baseline-file/apply` | `baseline.manage` | Dosyayı yeniden uygular (düzenlemeden sonra); portal girişini ezmez (`portal_girisi`) |
| POST | `/requirements/{id}/review` | `requirement.review` | Ön inceleme + tutarlılık denetimi başlat |
| GET | `/requirements/{id}/findings` | `requirement.read` | Tutarlılık bulguları (kanıtlı) |
| POST | `/findings/{id}/decision` `{karar, metin?, gerekce?}` | `requirement.review` | fix_doc / code_defect / accept_difference |
| POST | `/requirements/{id}/apply-doc-fixes` `{cakismayi_onayla?}` | `requirement.review` | Onaylı düzeltmeleri Jira'ya yaz + yeniden kontrol; yazılacak düzeltme ve açık engelleyici yoksa belgeyi açıkça son hal yapar (portal: "Son hal olarak onayla"). Düzeltme güncel döngüdeki bir `accept_difference` kararının maddesini yeniden yazıyorsa 409 (Türkçe, `F1 (tur 1)` etiketli); `cakismayi_onayla:true` ile uygulanır (`requirement.decision_conflict_confirmed`) |
| POST | `/requirements/{id}/po-approve` `{icerik_hash}` | `requirement.po_approve_free_text` | Yalnız serbest metin gereksinimde (`kaynak == free_text`) PO teyidi; içerik hash'i kontrolü. Jira kaynaklı gereksinimde **410 `po_onayi_jira`** (012 K6): PO teyidi Jira etiketiyle (etiketi koyan aktör PO listesinde, içerik hash'i eşleşir; simülatör kipinde simüle Jira'ya etiket) |
| POST | `/requirements/{id}/generate-cases` | `case.generate` | Case üretimi (gereksinim PO onaylı) |
| GET | `/requirements/{id}/case-metrics` | `case.read` | Kabul oranı (ilk karara göre, hedef 0.70), ret nedenleri, AI/review süresi, maliyet, `ai_cagri_modlari`, `kapsanmayan_ac` (hiçbir güncel case'in atıf yapmadığı AC'ler), `manuel_baz_ms` (**yalnızca** story'nin kendi ölçümü; varsayılanda ve ölçülmediğinde null — env değeri yalnız `manuel_baz.varsayilan_s/varsayilan_ms` + `aciklama`'da), `manuel_baz_kaynagi` (`olcum\|varsayilan\|null`), `manuel_baz` (baseline nesnesi), `review_tabani_ms` |
| POST | `/requirements/{id}/review-complete` | `case.approve` | Taslak kalmadıysa review'ı kapatır (denetim olayı); taslak varsa 409 |
| GET | `/cases?requirement_id=` · `/cases/{id}` | `case.read` | `developer` yalnız `approved`/`published` case'i görür; karar geçmişi ve chat yok |
| POST | `/cases/{id}/viewed` | `case.decide` | Kartın ilk görüntülenmesi (review süresi ölçümü) |
| POST | `/cases/{id}/decision` `{karar: accept\|edit\|reject\|reopen\|approve\|send_back, icerik_hash, icerik?, ret_nedeni?, gerekce?, beklenen_anlam_degisti?, oracle_istisna_gerekce?, oracle_istisna_turu?, oracle_kayit_damgasi?}` | `case.decide` (`accept`, `edit`, `reject`, `reopen`) · `case.approve` (`approve`, `send_back`) | Testçi kararı: `accept`/`edit` → `ready`, `reject` (ret nedeni zorunlu), `reopen` ("Taslağa al") → `draft`; onaylı/yayınlı case'te `edit`/`reopen` onayı düşürür. Analist son onayı: `approve` yalnız `ready`'den ve içerik hash'i Testçi kararının hash'iyle eşleşirken (onaylayan hesap son düzenleyenden farklı); `send_back` → `draft`, gerekçe zorunlu (ANALIZ 012 §5). Kalite doğrulama (012-test-kalite §13.2): Testçinin `accept`/`edit`'i ve Analistin `approve`'u karar tablosu onay kapısından geçer (yüksek riskli uyuşmazlık 422 `oracle_uyumsuz`, kontrol edilemeyen 422 `oracle_kontrolsuz`; `oracle_istisna_gerekce` ≥ 20 karakter / 10 harf + `oracle_istisna_turu?: uyumsuz\|kontrolsuz` ile istisna, `oracle_istisna` tablosuna eklenir; aynı tür + tablo kümesiyle verilmiş istisna son onayda yeniden gerekçe istemez; kontrol bitmemişse 409 `oracle_bekleniyor`); case nesneleri `oracle {sonuc, icerik_hash, ozet, karsilastirmalar, karsilastirilamayan, istisna, kontrol_suruyor} \| null` taşır (developer görünümünde yok) |
| POST | `/cases/bulk-decision` `{karar: accept\|approve, ogeler[{case_id, icerik_hash}]}` | `case.decide` (`accept`) · `case.approve` (`approve`) | 013 toplu karar; öğe başına tekli `decide` (tüm kapılar). Öğe sonucu `{case_id, durum: onaylandi\|atlandi\|hata, neden, kod, otomatik_kod}`; `kod` iş kuralı hatasının sabit kodu (012-test-kalite §14.5: karar tablosu kapısı `oracle_uyumsuz`, `oracle_kontrolsuz`, `oracle_bekleniyor`, `oracle_kontrol_siniri`; istisna toplu kararda verilmez, case tekil kararda istisnayla onaylanır) |
| GET | `/cases/{id}/oracle?icerik_hash=` | `case.oracle_read` | 012: güncel (ya da önerilen) içeriğin karar tablosu kontrolü `{case_id, icerik_hash, guncel_icerik, kapsayan_tablolar, oracle}` |
| POST | `/cases/{id}/oracle-check` `{icerik?}` | `case.oracle_check` | 012: önerilen düzeltme içeriği için kontrol (şema denetimli) → 202 `{icerik_hash, job_id}` |
| GET | `/requirements/{id}/decision-tables` | `decision_table.read` | 012: `{tablolar, iliskiler, son_taslak}` (durum, `bayat`, hash, onaylayan) |
| POST | `/requirements/{id}/decision-tables/draft` | `decision_table.edit` | 012: AI taslak işi (`karar_tablosu.draft`) → 202; yalnız PO onaylı gereksinim |
| POST | `/requirements/{id}/decision-tables` `{icerik?}` · `/requirements/{id}/relations` `{icerik, karar_tablosu_id?}` | `decision_table.edit` | 012: elle tablo / ilişki → 201 |
| PUT | `/decision-tables/{id}` · `/relations/{id}` `{icerik, icerik_hash}` | `decision_table.edit` | 012: yalnız `draft`'ta; geçersiz içerik 422 `karar_tablosu_gecersiz` / `iliski_gecersiz` |
| POST | `/decision-tables/{id}/submit\|withdraw\|reopen` (ve `/relations/{id}/…`) | `decision_table.edit` | 012: durum geçişleri; onay ve yeniden açma `oracle.check_requirement` açar |
| POST | `/decision-tables/{id}/approve\|request-changes` (ve `/relations/{id}/…`) `{icerik_hash, gerekce?}` | `decision_table.approve` | 012: görülen hash'le portal PO onayı / gerekçeli değişiklik isteği (Jira kanalı yok; ANALIZ 012-test-kalite §13.3 açık soru) |
| POST | `/decision-tables/{id}/evaluate` `{girdiler, icerik?}` · GET `/decision-tables/{id}/ornekler` | `decision_table.read` | 012: "örnekle dene" önizlemesi (kayıt yok) |
| POST | `/requirements/{id}/metamorphic-cases` `{iliski_id, case_ids?}` | `case.generate` | 012: ilişkiden ek case türetme (case üretimi Testçide); `{turetilen[], atlanan[{sonuc: iliski_gecersiz\|belirsiz_alinti\|olgu_yok\|zaten_turetildi}]}` |
| GET | `/requirements/{id}/metamorphic-derivations` | `case.oracle_read` | 012: türetme kayıtları |
| POST | `/fault-runs` `{platformlar[], hatalar?[]}` | `fault_run.manage` | 012: ekilmiş hata koşusu → 202; süren koşu varsa 409 `hata_kosusu_suruyor` |
| GET | `/fault-runs?limit=` · `/fault-runs/{id}` · `/fault-runs/catalog` | `run.read` | 012: koşular, adımlar, katalog |
| POST | `/fault-runs/{id}/cancel` | `fault_run.manage` | 012: iptal |
| GET | `/publish/preview?requirement_id=` | `case.publish` | Dry-run; `hedef`, `proje`, `jira_browse_url`, kalem başına `islem` (`create\|skip_existing\|blocked_not_approved\|blocked_hash_mismatch\|blocked_no_story\|blocked_requirement_changed`), `payload` (`mod_etiketi`, `mod_yorumu` dahil), `uretim_modu`, `icerik_hash`, `onaylayan` |
| POST | `/publish` `{case_ids[]}` | `case.publish` | Yayın: worker işi (`publish.cases`; yazma kimliği yalnızca worker'da), 45 sn beklenir → 200 `YayinSonucu`; bitmezse 202 `{job_id, durum, sonuclar: []}`; iş başarısızsa 502 |
| POST | `/code/generate` `{case_ids[], platform?, dil?}` | `code.generate` | Kod üretimi (CasesToCode); `dil` yoksa algılanan (011) |
| GET | `/code/languages?platform=` | `code.generate` | Algılanan dil + dil seçenekleri (011 §2.3, K-T3, K-T8); her çağrı forge'u okur, yalnız üretimi başlatan role açık |
| GET | `/scripts` · `/scripts/{id}` · `/scripts/{id}/screenshots/{n}` | `code.read` | Üretilen test + PR + adım görüntüleri |
| POST | `/scripts/{id}/break-verify` | `code.break_verify` | Kırarak doğrula (BREAK_CAMPAIGN) |
| POST | `/prs/{number}/merge` | `code.merge` | İnsan onaylı merge; yeşil CI + korumalı dal (merge kapısı). PR yazarı kuralı yok (K3) |
| POST | `/prs/{number}/review` `{karar: degisiklik_iste\|reddet, ret_nedeni, icerik_hash, head_sha, not?}` | `code.review` | Script review reddi; `ret_nedeni` sabit taksonomiden (422) |
| POST | `/prs/{number}/update-branch` | `code.review` | Geride kalan bot PR dalını main'e taşır (202) |
| POST | `/ci/trigger` `{tetik: deploy\|nightly\|manual}` | `run.trigger_scheduled` (`deploy`, `nightly`) · `run.trigger_manual` (`manual`) | Deploy/gece/manuel tetik. `developer` yalnız `manual` ve `TP_ORTAM≠prod` |
| GET | `/runs` · `/runs/{id}` | `run.read` | Koşular, test sonuçları. `run.artifacts` izni olmayan role imzalı rapor bağlantıları (`rapor_url`, `/artifacts/k/...`) yanıtta dönmez |
| GET | `/artifacts/runs/{run_id}/{path}` | `run.artifacts` | Ham artefakt (ekran görüntüsü, iz, log); `auditor` ve `viewer` göremez |
| GET | `/failures?run_id&sinif&karar_kaynagi&oneri_turu&oneri_durumu&script_id&kaynak&limit` · `/failures/{id}` | `failure.read` | Triage sonuçları (limit ≤200) / tekil (`HataAnalizi`) |
| POST · GET | `/failures/{id}/fix` | `code.repair` · `code.read` | Locator onarım PR'ı (202; başarısız/engellenmiş denemede aynı script'le yeniden deneme) · onarım durumu (`LocatorOnarimi`: `yama` (unified diff), `engellendi`, `deneme`, kardeş hatada `paylasilan`/`paylasilan_failure_id`/`paylasilan_mesaj`, `yerel_kontrol.kirmizi_testler`/`flaky_testler`) |
| GET | `/bug-drafts[?requirement_id]` · `/bug-drafts/{id}` · `/bug-drafts/{id}/detail` | `bug.read` | `developer` yalnız açılmış / bağlanmış bug'ı görür. `bug_draft_view` (Faz 2 `bug_draft_out` üst kümesi; triage kaynaklılar da gereksinim süzgecinde). `jira_silindi: bool` — açtığı Bug demo sıfırlamasında silindiyse `true`, `jira_url` null |
| POST | `/bug-drafts/{id}/decision` `{karar: new\|link\|edit\|dismiss\|reopen, icerik_hash, icerik?, link_key?, gerekce?}` | `bug.decide` | new/link: onay → `publish_bug` (≤20 sn beklenir, `yayin_sonucu`; yoksa 202); edit: yeni hash, onay değil; dismiss gerekçe ister (422) |
| POST | `/bug-drafts/{id}/prepare` · `/bug-drafts/{id}/publish` | `bug.decide` | Mükerrer arama + AI taslağı yeniden (202) · onaylı taslağın yayınını yeniden dene |
| GET | `/control-tower` | `dashboard.read` | Kontrol Kulesi verisi |
| GET | `/audit?verify=true` | `audit.read_all` · `audit.read_own` · `audit.verify` (`verify=true`) | Denetim kaydı + zincir doğrulaması. `admin`/`auditor` tümünü, diğerleri (`viewer` hariç) yalnız kendi olaylarını (`aktor` = kullanıcı adı) görür; doğrulama `admin`/`auditor` |
| GET | `/events` (SSE) | `events.read` | Olay akışı (`auditor` ve `viewer` hariç) |
| GET · DELETE | `/tokens` · `/tokens/{id}` | `token.read` (kendi token'ları) | Listeleme / iptal |
| POST | `/tokens` `{kapsam}` → `{id, kapsam, son_kullanma, token, mcp_url}` | `token.issue` | MCP (Claude Code) kanalı için 8 saatlik token; `mcp_url` = `TP_MCP_PUBLIC_URL`. `/mcp` bağlanana kadar **501** ("IDE (MCP) kanalı henüz etkin değil"); token parola değişince geçersizleşir |
| MCP | `:8000/mcp` → `get_requirement(requirement_key)` (submit kapsamı; PO onaylı metin güvenilmeyen blokta + `onaylanan_hash`), `submit_draft_cases(requirement_key, cases, onaylanan_hash)` (hash zorunlu; bayatsa ret), `publish_test_cases` | token (kapsam dışı) | Claude Code kanalı (streamable HTTP, durumsuz). Token tek kapsamlıdır (`submit` veya `publish`); iki araç için iki token. Yalnızca 127.0.0.1/localhost Host'u, `X-Forwarded-For` → 403, çerez okunmaz. Her çağrı `tool_call` (kanal `ide`). Ayrıntı: docs/CLAUDE-CODE-KANALI.md |
| POST | `/demo/break-locator` · `/demo/reset` | `demo.manage` | Demo kırılması / sıfırlama (200 done / 202 sürüyor / 409). Yalnız `TP_DEMO_MODE=1` iken. Kırılma main için yeşil koşu ister (yoksa 409 + `demo.break_refused`); `?zorla=true` bilerek atlar. GitHub kipinde kırılma/sıfırlama insan kimliğiyle (`GITHUB_MERGE_TOKEN`, demo-admin bypass) PR olarak yapılır (sıfırlama: main üstüne `demo-baseline` ağacı); token yoksa iş düşer → 409 (GERCEK-SISTEMLER §5.7). Sıfırlama jira-sim'i sıfırlamaz; yalnızca `AI-generated` + `tp-<uuid>` etiketli Bug'ları siler |
| GET | `/demo/status` | `dashboard.read` | Faz 5: `model {ayar, mod, replay_strict, anahtar_var, calisma_alani_var, saglayici, aciklama, zaman}` (core-worker'ın son açılış bildirimi, `worker.model_mode` denetimi; kayıt yoksa null = bilinmiyor; anahtar değeri asla) ve `degerlendirme [{paket, surum, durum, etiket}]` (rules/evaluations.yaml; `pending` → "canlı değerlendirme bekliyor"; okunamazsa `{hata}`). main, `forge.testid` (web/src) + `forge.e2e_testid` (e2e page object), `locator_durumu` (`baseline`\|`kirik`\|`onarildi`\|null), baseline, çalışan uygulama sha'sı ve main ile eşleşmesi, `web_yenileme_istegi`, `onarim_on_kosulu {hazir, son_yesil_kosu, yonerge}`, `locator_demo {destekleniyor, neden}` |
| GET | `/assistant/status` | `assistant.use` | `{etkin, neden?, mod, varsayilan_model, degerlendirme, paket_commit, kalan_soru}` — `asistan_durum` satırından (core-api kipi/anahtarı bilmez); kalp atışı > 2 dk → `etkin=false, neden=worker_yok` |
| GET · POST | `/assistant/conversations` | `assistant.use` (kendi) | Son 50 sohbet · yeni sohbet |
| DELETE | `/assistant/conversations/{id}` | `assistant.use` (kendi) | Yumuşak silme |
| GET | `/assistant/conversations/{id}/messages` | `assistant.use` (kendi) | Mesajlar (bekleyen dahil) |
| POST | `/assistant/conversations/{id}/messages` `{soru ≤ 2000, baglam ≤ 2 KB, kip?: soru\|oneri, oneri_kural_id?}` veya `{ust_mesaj_id}` | `assistant.use` (kendi) | 202 `{mesaj_id}`; 422 `gecersiz_istek`/`sir_icerik`/`kisisel_veri`, 404, 409 `bekleyen_var`/`zaten_derin`/`oneri_gecersiz`, 429 `hiz_siniri`/`mesgul`/`donduruldu` (+`kalan_s`), 402 `butce_asildi`, 503 `asistan_kapali` (+`neden`: `worker_yok`\|`maskeleme_kapali`) |
| GET | `/assistant/messages/{id}` | `assistant.use` (kendi) | Tek mesaj (SSE yokken yoklama) |
| POST | `/assistant/messages/{id}/cancel` · `/feedback` `{deger: -1\|1}` | `assistant.use` (kendi) | İptal (`pending` ücretsiz; `running` harcanan yazılır) · 👍/👎 |
| GET | `/assistant/suggestions?rota=&varlik_tur=&varlik_id=` | `assistant.use` | Kural tabanlı öneriler (modelsiz, `ai_call` yazmaz): `{oneriler[{kural_id, baslik, neden, oncelik, eylem}], hesaplandi, ekranda_kural_var, bastirilan, diger_ekranlar}`; varlık yok/role kapalı 404; 60/dk |
| POST | `/assistant/suggestions/{kural_id}/feedback` `{deger: -1\|1\|2, varlik_id?, jira_anahtari?}` | `assistant.use` | Gizle/Faydalı/Yaptım; bilinmeyen kural 422, erişilemeyen varlık 404, `varlik_durum` sunucuda; 30/dk |

**Asistan uç ayrıntıları (`features/assistant/api.py`; sözleşme `specs/008-ai-asistan/contracts/api.md`):**
yalnız çerez oturumu (`tpt_` bearer → 401); başkasının sohbet/mesajına (cancel, feedback, `ust_mesaj_id`
dahil) her uç 404. `{ust_mesaj_id}` ("Daha ayrıntılı incele"): aynı sohbette, `rol='assistant'`,
`durum='done'`, `amac IS DISTINCT FROM 'assistant_deep'`, tekil; soru ve amaç sunucuda üst mesajdan
türetilir. Global bekleyen sınırı 2 × `TP_WORKER_ASISTAN_PARALEL` (varsayılan 6), `job` tablosundaki
bitmemiş `assistant.answer` işlerinden `pg_advisory_xact_lock` altında; kullanıcı başı tek bekleyen
kısmi tekil indeksle atomik (eşzamanlı POST'ta kısıt adına göre 409 `bekleyen_var`); saatlik 30 soru
(iptal/hata dahil, otomatik yükseltme çocukları hariç, `assistant_deep` 2 sayılır). İş yükü daima
`{mesaj_id, kullanici_id, tetik}`. Bütçe: asistan günlük $10, kullanıcı günlük $1, kök soru başı $0.50
(çocuklar dahil). Hız sınırı `asistan_hiz` sabit pencere sayacıyla (`oneri_liste` 60/dk,
`oneri_geri_bildirim` 30/dk, `jira_global` 30/dk). Öneri ucu `TP_ASISTAN_ONERI=0` iken 404.
SSE: `assistant.step {mesaj_id, kullanici_id, adim_kodu}`, `assistant.answered {mesaj_id, kullanici_id,
durum, derin_bekliyor}` — `events/bus.py` `KIMLIK_ALANLARI` += `mesaj_id`, `kullanici_id`; `_akis`
`assistant.*` olayını yalnız `kullanici_id`'si oturum kullanıcısı olan akışa teslim eder (yoksa hiç;
fail-closed); yükte soru/cevap metni yok.

**Hata `kod` alanı (sabit enum; makinece okunur):** `api/errors.py` her hata yanıtına `kod` yazar;
`kod` asla istisna adından veya `str(exc)`'ten türetilmez; 5xx'te `detail` "Sunucu hatası" ve `kod`
`ic_hata` (tek istisna: bilinçli hizmet durumu `asistan_kapali`). Başlıklar (401 `WWW-Authenticate`)
korunur. Yeni değer yalnız bu tabloya eklenerek kullanılır; asistanın hata sözlüğü
(`rules/assistant/hata-sozlugu.yaml`) ve portal `ApiError.kod` bu enum'u kullanır.

| `kod` | HTTP | Kaynak |
|---|---|---|
| `gecersiz_istek` | 400, 415, 422 | genel (durum kodundan; `RequestValidationError` dahil) |
| `yetkisiz` | 401 | genel |
| `yasak` | 403 | genel |
| `yetki_yok` | 403 | izin reddi (`auth/yetki.py` `izin()`; `authz.denied` denetim kaydı) |
| `po_onayi_jira` | 410 | Jira kaynaklı gereksinimde portal PO onayı (onay Jira etiketiyle) |
| `bulunamadi` | 404, 410 | genel |
| `yontem_desteklenmiyor` | 405 | genel |
| `cakisma` | 409 | genel (`kod`'suz `WorkflowError` dahil) |
| `govde_cok_buyuk` | 413 | genel |
| `hiz_siniri` | 429 | genel; asistan saatlik soru ve öneri kovaları |
| `istek_hatasi` | diğer 4xx | genel |
| `ic_hata` | 5xx | genel |
| `gecersiz_gecis` | 409 | `InvalidTransition` |
| `eszamanli_gecis` | 409 | `ConcurrentTransition` |
| `kapi_kapali` | 409 | `GateClosed` |
| `onay_hash_uyusmuyor` | 409 | `OnayHashUyusmuyor` (karar verilen içerik ekranda görülenden farklı) |
| `kosul_saglanmadi` | 422 | `GuardFailed` |
| `onay_yetkisi_yok` | 403 | `ApprovalNotAllowed` |
| `gecersiz_karar` | 422 | `InvalidDecision` |
| `butce_asildi` | 402 | `BudgetExceeded`; asistan bütçe ön kontrolü |
| `kaynak_reddi` | 403 | CSRF/Origin reddi (`api/csrf.py`, ara katman) |
| `sir_icerik` | 422 | asistan: soru/bağlamda sır deseni (değer yanıtta tekrarlanmaz) |
| `donduruldu` | 429 | asistan: ardışık ciddi güvenlik olayı dondurması (specs/013 §6.2); gövdede `kalan_s` |
| `kisisel_veri` | 422 | asistan: soru/bağlamda Luhn'lu, bilinen kart ağı önekli 13–19 haneli numara (herkese açık test kartı ve URL/yol/sorgu dizesi hariç); ekran bağlamında (JSON) ayrıca numaranın yakınında "kart"/"card"/"kredi"/"pan" kelimesi şart (değer yanıtta tekrarlanmaz; spec 013 §5.1) |
| `bekleyen_var` | 409 | asistan: kullanıcının yanıt bekleyen sorusu var |
| `zaten_derin` | 409 | asistan: bu mesaj için ayrıntılı inceleme zaten var |
| `oneri_gecersiz` | 409 | asistan: `oneri_kural_id` artık geçerli değil |
| `mesgul` | 429 | asistan: global bekleyen sınırı dolu |
| `asistan_kapali` | 503 | asistan: `neden` = `worker_yok` \| `maskeleme_kapali` |
| `oracle_uyumsuz` | 422 | 012: yüksek riskli case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor (istisna gerekçesiyle aşılır) |
| `oracle_bekleniyor` | 409 | 012: yüksek riskli, tablo kapsamındaki case'in kontrolü bitmedi (kontrol kuyruğa alındı) |
| `oracle_kontrolsuz` | 422 | 012: yüksek riskli, tablo kapsamındaki case kontrol edilemedi (gerekçeli `kontrolsuz` istisnasıyla aşılır) |
| `oracle_kontrol_siniri` | 429 | 012: `oracle-check` case başına dakikalık iş sınırı aşıldı |
| `karar_tablosu_gecersiz` | 422 | 012: tablo içeriği şemaya / ifade diline uymuyor (`hatalar` mesajda) |
| `iliski_gecersiz` | 422 | 012: metamorfik ilişki geçersiz ya da türetme için uygun değil |
| `hata_kosusu_suruyor` | 409 | 012: süren ekilmiş hata koşusu var |

`asistan_mesaj.hata_kodu` (yanıt değil, mesaj kaydı): `butce_asildi`, `girdi_tavani`, `zaman_asimi`,
`model_hatasi`.

**Faz 2 uç ayrıntıları (Demo-A):** `POST /requirements/sync` → 200 `{durum:"done", mesaj, proje,
sonuc:{<jira_key>: yeni|degismedi|guncellendi|yeniden_kontrol|sifirlandi|mesgul}}`. `review`,
`apply-doc-fixes`, `generate-cases` → 202 `{job_id, workflow_id, durum, mesaj}` (apply-doc-fixes
yazılacak düzeltme ve engelleyici bulgu yoksa belgeyi son hale getirip `durum:"done"` döner).
`GET /requirements/{id}/findings` yalnızca kanıtı doğrulanmış bulguları döner; elenen sayısı
`X-Elenen-Bulgu-Sayisi` başlığında ve detayda `bulgu_sayaclari.elenen`. Detay `po` nesnesi
`{durum, onaylayan, zaman, kanal, onaylanan_hash}`. Jira yolunda `po-approve` 410 `po_onayi_jira`'dır
(012 K6; onay Jira etiketiyle); portal PO onayı yalnız serbest metin gereksinimde. Case `mode` IDE'den gelen case'lerde `null`'dur (model çağrısı yok; "live" yazılmaz).
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
(Faz 5: ölçüm de varsayılan da yoksa "Manuel baz değer girilmedi (bu story için ölçüm yok,
TP_MANUAL_BASELINE_S de boş): Demo-A kazanç gösterilemez."; varsayılan kullanıldıysa "Bu story için
manuel baz ölçümü girilmedi; varsayılan değer (TP_MANUAL_BASELINE_S) kullanıldı — story'ye özel
ölçüm değil."; tüm AI çağrıları REPLAY ve süre 0 ise "AI süresi REPLAY'de ölçülmez…"). Kanıt SQL'i (`sqlguard`, kanıt modu) yalnızca kayıpsız projeksiyon
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

**012 olaylar ve iş türleri:** olaylar `karar_tablosu.state` / `metamorfik_iliski.state` (durum
geçişi), `karar_tablosu.updated` (`eylem` created|updated|ai_draft), `oracle.checked {case_id,
requirement_id, icerik_hash, sonuc}`, `hata_kosusu.ilerleme {id, durum, platform, hata_kodu, asama,
sonuc}`; işler `karar_tablosu.draft` (max_deneme 2), `oracle.check_requirement {requirement_id,
neden}` (anahtar olay başına tekil), `oracle.check_case {case_id, icerik_hash, icerik?}`,
`hata_kosusu.calistir` (uzun şerit). Denetim: `karar_tablosu.*`, `metamorfik_iliski.*`,
`oracle.checked`, `oracle.exception`, `oracle.warning`, `metamorfik.derived`. `GET /control-tower`
ek anahtarlar `beklenti_dogrulugu {oran, uyumlu, uyumsuz, kapsam_disi, kontrol_edilemedi, istisna,
kapsam_orani}` ve `hata_yakalama {son_kosu, oran, yakalanan, kacan, gecersiz, platformlar,
kacanlar} | null` (kaynak metni `kaynaklar`'da); `GET /requirements/{id}/case-metrics` ek
`beklenti_dogrulugu` (+ `kaynak`).

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
- `POST /code/generate {case_ids[]}` (`code.generate`) → 202 `{job_id, workflow_id, durum, mesaj,
  script_ids, sonuclar[{case_id, durum, script_id, job_id, workflow_id}]}`. Yalnızca onaylı/yayınlı,
  içerik hash'i onaylı hash'e eşit ve gereksinimin PO onayı güncel case'ler (aksi 409; izin 403).
  Aynı onaylı hash için açık/merge edilmiş PR varsa yeniden üretilmez; blocked/failed yeniden üretilir.
- **011 dil alanları:** `POST /code/generate {case_ids[], platform="web", dil?: ts|java|csharp|python}`;
  geçersiz (platform, dil) çifti 422 (Türkçe). `dil` yoksa algılanan dil (`dil_kaynagi="algilandi"`,
  algılama sonuçsuzsa `varsayilan`), varsa `secildi`. Yeniden üretim mevcut `dil_kaynagi`'nı korur.
  Tam hat dilinde başka dilde merge edilmiş script → 409 (K-T4). `GET /code/languages?platform=` →
  `{platform, algilanan, kaynak, sayilar{ts,java,csharp,python}, secenekler[{dil, etiket, cati, hat:
  tam|dogrulanmamis, kullanilabilir, neden}]}`; tam hat dili repoda yoksa ya da GitHub kipinde
  `java ∉ TP_WEB_DILLERI` ise `kullanilabilir=false` + Türkçe `neden` (K-T3). Algılama saf sayımdır
  (Java: `*Test.java|*Testi.java|*Tests.java|*IT.java`, `birim/` ve `uretilen/` hariç; `*Test.kt`
  yalnız sinyal; tek sabit `platform.py`, `dil_algila` ve `ci/dil` ortak — K-T7), `(ref sha,
  platform)` ile önbelleklenir, forge hatası üretimi engellemez. Uç `code.generate` iznine açıktır
  (K-T8; 012: ekran görünürlüğü de izin tablosundan, `ROTA_IZINLERI`).
  Script serileştirmesi ek alanlar: `dil`, `dil_kaynagi`, `dogrulanmamis` (`durum == "unverified"`),
  doğrulanmamışta `kod` = `kaynak_kod` (yol K-T6: `<e2e-csharp kökü>/tests/Generated/<Story>WebC<n>_<u8>Tests.cs` (C# metotları `…Async`) · `<e2e-python kökü>/tests/generated/test_<slug>.py`); `yerel_kontrol.adimlar[{ad, durum: passed|failed|skipped}]`
  (ts: tsc/eslint/ast_guard; java: deps/guard/compile; eski alanlar korunur). Denetim ve SSE
  yükleri (`codegen.requested` vb.) `dil` taşır.
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
- `GET /scripts/{id}/screenshots/{n}` (`code.read`): `tp_codegen` volume'ünden PNG; yol
  doğrulanır. Ekran görüntüsü model döngüsü DIŞINDA ajanın kendi MCP oturumunda alınır (Playwright
  MCP `--isolated` olduğundan ayrı oturum ajanın sayfasını göremez); çağrı ve görüntü modele/
  `tool_call`'a girmez.
- `POST /scripts/{id}/break-verify` (`code.break_verify`) → 202; sonuç `passed` (yeşil → kırmızı → yeşil),
  `weak` (kırılmada yeşil kaldı: `zayif_test`; kampanyayla ilgisiz testlerde beklenir) ya da `failed`
  (koşu tamamlanamadı). Zayıf test kapı değil işarettir (TEKNIK-TASARIM §2 adım 6): `passed`
  değilse merge isteği `onay_notu` (açık insan kabulü; `review.gerekce` + `codegen.merge_acknowledged`)
  ister; kırma sürerken merge reddedilir. Üç aşama ayrı koşulardır (`run.tetik='break_verify'`).
- `POST /prs/{number}/merge {icerik_hash, head_sha}` (`code.merge`): insan onayı (review `merge`)
  kaydedilir, `codegen.merge` işi `forge.merge_pr(actor, expected_head_sha)` çağırır; ≤20 sn
  beklenir → 200 `PullRequest`, ret 409 (forge gerekçesi, denetim `codegen.merge_refused`), hâlâ
  sürüyorsa 202 `{…PR, job_id, is_durumu}`. Merge sonrası `enqueue_ci(merge_sha, "push")`.
  `head_sha` yoksa 422; PR zaten merge edildiyse 409. Bilinen engeller (kırmızı local-ci, geride
  dal, süren kırma) review satırı YAZILMADAN reddedilir; forge'un öngörülemeyen reddi review
  satırı bırakır (append-only), denetim `review_id` taşır.
- `POST /ci/trigger {tetik: deploy|nightly|manual}` (`run.trigger_scheduled` / `run.trigger_manual`) → 202 `{job_id, run_id, durum:
  queued|zaten_kuyrukta, mesaj, kaynak, tetik}`. `GET /runs?tetik&kaynak&sonuc&pr_no&script_id&limit`
  (≤200; süzgeçsiz listede açık defect adayının son kırmızı yerel kontrolü her zaman `sabit:true`
  ile eklenir; koşu ayrıca `junit_url`), `GET /runs/{id}`. İmzalı kısa ömürlü bağlantı
  `GET /artifacts/k/{exp}.{hmac}/runs/{run_id}/{path}` (çerezsiz; `TP_SESSION_SECRET`'tan türetilen
  anahtar, `TP_ARTIFACT_LINK_TTL_S` 7200; `rapor_url` bunu kullanır ki sandbox'taki Playwright
  raporu ekran görüntülerini yükleyebilsin). `GET /artifacts/runs/{run_id}/{path}` (`run.artifacts`; yalnızca
  `src/**/results/**`, `run.json`, `runner.log`; HTML CSP sandbox ile; dizin → JSON liste; URL'ler
  `/api` önekli). `GET /control-tower`: her KPI `kaynaklar`'da tablo/süzgeç/pencere; geçme oranı
  **koşu bazlı** (son `TP_CT_SON_KOSU` CI koşusu) + `test` alt nesnesi; `gecme_hedefi=null`;
  manuel baz story başınadır (Faz 5; aşağıda). Karne satırı `alan`/`alanlar` (page object
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

**Faz 4 uç ayrıntıları (FailureToFix, bug, demo kırılması):**
- **Triage (`tp_core.features.triage`):** `ci.service._bitir` her koşu sonunda
  `triage.on_run_finished(session, run)` çağırır (kırmızıysa `triage.classify:<run_id>`); kendini
  `TP_TRIAGE_SWEEP_S`'de yeniden planlayan `triage.sweep` son 2 günün kaçan kırmızı koşularını toplar.
  Kapsam: CI koşuları; `local_check` yalnızca `script_kontrol.sinif='defect_adayi'` (diğer sınıflar kod
  üretiminin insan yolunda kalır; onarımın kendi yerel kontrolü — `run.ortam.onarim=true` — hiç
  sınıflandırılmaz); `break_verify` kırmızıları `kaynak='kirma'` + `kasitli_kirilma` sinyaliyle
  (`TP_TRIAGE_KIRMA=0` kapatır); bunların `product_defect`'i için taslak `TP_TRIAGE_KIRMA_TASLAK`
  (varsayılan 1) ile istenir, 0'da `oneri_turu='none'` ve `/failures` öğesi `jira_yazilmaz: true`; yol
  haritası adım 13 kırma taslağını saymaz (bilerek karara bırakılır). Kurallar sırayla: environment (`saglik.ok=false`, sağlıksız `error`,
  `/check` `app` adımı farkı, ağ/navigasyon) → flaky → test_maintenance/locator (0 eleman + sembol
  tablosundaki niyet rol+ad aria'da + `/locator-probe` kapsamda tek eşleşme farklı testId + sha
  `farkli` değil) → product_defect (expected/received'lı assertion, eleman bulundu, tekrarlar tutarlı)
  → test_data. Kural eşleşmezse LLM yedeği (`gateway.defects` girdileri, REPLAY golden `HATA`);
  LLM `environment`'ı ezemez ve `test_maintenance` dese de onarım önerisi üretmez. Neutral REPLAY-MISS
  → `unknown`, `karar_kaynagi='rule'`, mod `replay_miss`. Her product_defect için
  `bugs.create_draft_from_failure`. Sinyal listesi `{kod, aciklama, kaynak, kanit}`; güven puanı yok.
- **Bug (`tp_core.features.bugs`):** taslak şablonla başlar, `bugs.prepare` imza → güvenli JQL
  (`project = "TPD" AND issuetype = "Bug" AND statusCategory != "Done" AND (text ~ …)`, ≤8 terim,
  kaçışlı) → `dup_rank` → `bug_draft` (yalnızca `gateway.defects` kurucuları, `defect_replay_key`).
  Deterministik korumalar: `actual`/`expected` gerçek literal değerleri içermeli, kanıt yalnızca
  koşunun kendi artefaktı ya da bulgunun kod/veri referansı, uydurma aday anahtarı (`invented_dup_keys`)
  ve diğer sıralama değişmezleri (`dup_rank_problems`: her aday tam bir kez, sıra 1..n, gerekçe
  ≤200) bozulursa tüm sıralama düşer, `link` önerisi yalnızca `high` adayda. İnsan düzenlemesi
  (`edit`/`new`/`link`) story/Test anahtarını ve kanıt kökenini değiştiremez (422); bağlanacak hedef
  karar anında denetlenir (TPD anahtarı, var, Bug, Done değil → aksi 422; Jira erişilemezse 503).
  Jira'ya yazılan kanıt bağlantıları `TP_PUBLIC_BASE_URL` köküyle mutlaktır, kod kanıtı commit'e
  sabittir. Tutarlılık `code_defect` taslakları
  karar anında `adopt_draft` ile aynı hatta girer (açılışta `bugs.adopt_sweep`). `publish_bug`:
  `approved` + onaylı hash eşleşmesi; `external_ref` niyeti önce; `new` → `tp-<uuid>` etiket araması
  (yeniden denemede ikinci Bug yok), ADF açıklama (REPLAY etiketi, onaylayan, hash, zincir başı),
  etiketler `AI-generated`, `tp-<uuid>`, `tp-mod-<mod>`; `link` → hedefin Bug olduğu denetlenir, tek
  kanıt yorumu. İkisinde de story'ye `Relates`, Test issue'ya `Test` (yoksa `Relates`). jira-sim
  `priority` kabul etmez → alan olmadan yeniden denenir.
- **Onarım (`tp_core.features.repair`):** `POST /failures/{id}/fix` uygunluğu önce denetler (environment,
  sağlıksız koşu, locator dışı sınıf → 409 + `repair.refused`); aynı koşuda aynı locator değişikliğini
  öneren kardeş hatalar tek onarımı paylaşır (ikinci PR açılmaz; PR/merge durumu kardeşlere yazılır).
  `repair.fix` deterministiktir (model çağrısı yok): öneri → `/symbols` → kapsamlı `/locator-probe` →
  son yeşil kanıtıyla rol+ad doğrulaması (sıra: öneri aria'sı, son yeşil koşunun
  `<sayfa>.aria.yml` dosyaları — `locators.spec.ts` sözleşme geçince yazar, önce geçerli sayfanınki —,
  kod üretimi ajan snapshot'ları; `sozlesme_testi` geri dönüşü yalnızca
  `TP_REPAIR_ARIA_FALLBACK=sozlesme` ile ve son yeşilde hiç aria dosyası yoksa; kaynak kayıtta ve
  PR'da yazılıdır) → yalnızca
  `pages/**/locators.ts` testId dizgesi (satır farkı ile yeniden denetlenir) → `/ast-guard` repair →
  tam paket `/check` (`local_check`, `ortam.onarim=true`, `retries=1`; etkilenen her spec koşmalı)
  → bot PR (`tp/repair-<failure>`, etiket
  `tp-repair`, gövdede sinyaller/diff/yoklama/aria/AST/kontrol/"AI üretimi: hayır"/zincir başı).
  `/prs/{n}/merge` onarım PR'larını repair şeridine yönlendirir (hash + head bağlı insan onayı →
  `repair.merge` → push CI).
- **Demo kırılması (`tp_core.features.demo`):** `POST /demo/break-locator` `demo/break-locator`'ı
  demo-admin bypass'ıyla merge eder (denetim "demo kırılması" + `fark` özeti + `demo.break` isteyen
  sunucu; bypass yalnızca doğrulanmış head'de, `web/src/**` altında ≤5 dosyada birebir
  `add-to-cart`→`cart-add` değişimine izin verir, merge o head'e sabitlenir), forge
  volume'üne `/forge/demo-web-refresh.json` yazar ve `demo.await_web` işini planlar. core-worker imaj
  derleyemez: host'ta `scripts/demo-web-sync.sh` (`make demo-break` / `make demo-web-sync A=--watch`)
  isteği uygular. `demo.await_web` push CI'ı ancak çalışan uygulama (`/build.json`) **ve** toolchain'in
  okuduğu `/forge/demo-app-web.sha` main'i yansıtınca kuyruğa alır (aksi `/check` `app=farkli` →
  environment koşusu). Uygulama hedef commit'i zaten yansıtsa bile bu commit için yazılmış ve
  host betiğince henüz uygulanmamış (`/forge/demo-web-refresh.done` ≠ `istek_id`) yenileme isteği
  varsa CI `TP_DEMO_WEB_ISTEK_BEKLEME_S` (vars. 180 sn) boyunca bekler: betik konteyneri yeniden
  oluştururken koşan CI sağlıkta düşmesin (Faz 5 prova bulgusu); süre dolunca (betik çalışmıyorsa) CI
  açılır. Aynı forge değişikliği için ikinci CI açılmaz; `TP_DEMO_WEB_WAIT_S` dolarsa CI
  yok + `demo.web_timeout`. `make break`/`make demo-baseline` (forge_demo CLI) de aynı işi kullanır.
  `POST /demo/reset` main'i demo-baseline'a döndürür, açık `tp/*`/`demo/*` PR'larını kapatır, uygulama
  yenileme + baseline CI ister; veritabanına dokunmaz (tam: `make reset`) — tek istisna: silinen AI
  Bug'larını açmış taslaklar `bugs.mark_jira_deleted` ile `bug_draft_ek.yayin.jira_silindi` işareti alır
  (durum/onay değişmez; denetim `bug_draft.jira_deleted`).
- **Koşu ayrıntısı:** `GET /runs/{id}` sonuç başına `triage_sinifi`/`triage_alt_tur`, koşu düzeyinde
  `hatalar[{id, test_adi, sinif, alt_tur, test_result_id}]`; sağlık kontrolü başarısız koşuda rapor
  bağlantıları (`rapor_url`, `junit_url`, `allure_url`) null. `GET /scripts/{id}` `failure_id`
  (defect adayının triage sonucu).
- **Faz 4 SSE:** `failure.classified {id, failure_id, run_id, script_id, test_adi, sinif, alt_tur,
  kural, karar_kaynagi, oneri_turu, mode}`, `repair.requested|started|step|blocked|pr_opened|merged`,
  `bug.draft_created|draft_ready|prepare_failed|draft_edited|dismissed|reopened|published|publish_failed`,
  `demo.break|reset|web_waiting|web_ready|web_timeout`.
- **Faz 4 iş türleri:** `triage.classify`, `triage.sweep`, `bugs.prepare`, `bugs.publish` (3 deneme),
  `bugs.adopt_sweep`, `repair.fix`, `repair.merge`, `demo.break_locator`, `demo.reset`,
  `demo.await_web`.
- **Model girdisi (Faz 4):** triage/bug_draft/dup_rank girdisi yalnızca `tp_core.gateway.defects`
  kurucularıyla (`failure_block`, `case_block`, `finding_block`, `*_messages`, `defect_replay_key`)
  kurulur; değişken değerler (koşu kimliği, yol, test dosyası soneki, aday sırası…) metne girmez, kanıt
  `kanit:<ad>` yer tutucusudur (`resolve_evidence`). Her `ai_call.ek.degerlendirme` prompt paketinin
  değerlendirme durumunu taşır (`{paket, surum, durum, etiket}`; bugün üçü de "canlı değerlendirme
  bekliyor"). Golden adı `HATA`, senaryo dizinleri içerik beyanıyla seçilir.

**Faz 5 uç ayrıntıları (manuel baz, prova, canlı değerlendirme):**
- **Story başına manuel baz (`tp_core.features.requirements.baseline`):** kaynak sırası story'nin
  kendi ölçümü (`olcum`) → `TP_MANUAL_BASELINE_S` (`varsayilan`, "story'ye özel değer değil" notuyla)
  → hiçbiri (`kaynak: null`, "ölçülmedi", sayı yok). `GET /requirements/{id}` ve `GET /requirements`
  öğeleri `baseline {deger_s, deger_ms, kaynak: 'olcum'|'varsayilan'|null, etiket:
  'ölçüm'|'varsayılan'|'ölçülmedi', giren, giren_rol, zaman, not, sira, ust_sinir_s}` taşır.
  PUT/DELETE yanıtı `{requirement_id, jira_key, baseline, degisti, gecmis}`; `baseline.manage` (po) dışı 403,
  oturumsuz 401, bilinmeyen kimlik 404. Kaynak notu PUT'ta zorunludur (boşluklar sadeleşir), DELETE'te
  isteğe bağlıdır. Değişiklikte SSE `requirement.updated {alan:'baseline', baseline{deger_s, kaynak,
  giren, not, sira}}`. Kaynak notu en az 3 boşluk dışı karakter (`NOT_EN_AZ`; portal da aynı kural +
  "gerçek ölçüm" onay kutusu). **Varsayılanda `deger_s/deger_ms` null'dır** (env değeri yalnız
  `varsayilan_s/varsayilan_ms` + `aciklama` "ölçülmedi; varsayılan … ölçüm değil"): başlık sayı değildir.
- **Reset'e dayanıklı baz değer (`baseline_dosya`):** `requirement_baz_deger` gereksinim kimliğine
  bağlıdır (cascade) ve `make reset` gereksinimleri yeni kimlikle yeniden kurar; kalıcı kopya gözden
  geçirilmiş, commit'li `rules/baz-degerler.yaml`'dır (`degerler: [{story, deger_s, giren, not}]`; katı
  tam sayı 0 < x ≤ 144000, adı yazılı `giren`, not ≥3; bilinmeyen alan/geçersiz/mükerrer girdi Türkçe
  hatayla atlanır, eşitleme durmaz). `flow.sync_from_jira` dosyayı her eşitlenen story'ye uygular:
  append-only satır (`giren=<kişi>`, `giren_rol='dosya'`) + hash zincirli `requirement.baseline_set`
  denetimi (aktör `seed`, `{kaynak:'dosya', dosya, tetikleyen}`); portal girişi ezilmez; eşitleme yanıtı
  ve denetimi `baz_dosyasi` taşır. Dosyada olmayan story "ölçülmedi" kalır — değer uydurulmaz.
- **Kontrol Kulesi:** `hazirlik[]` satırı `manuel_baz_kaynagi` + `manuel_baz`, `toplam_yontemi`
  (`ai_arti_review` | `yalniz_review` — REPLAY'de AI süresi ölçülmez, hazırlık süresi yalnız review
  süresidir (DEMO-VERISI) | null) ve `kazanc_orani` (**yalnızca kaynak `olcum`** ve hazırlık süresi
  > 0 ise; varsayılan baz kazanca girmez; `hazirlik[].manuel_baz_ms` varsayılanda null),
  `kazanca_girer` (ölçülmüş baz + `ai_arti_review`). `ai_katkisi.manuel_baz_ms` = **yalnızca ölçülmüş**
  story'lerin ortalaması (`manuel_baz_yontemi='story_ortalamasi'`; hiç ölçüm yoksa null +
  `baz_deger_olculmedi=true`), `manuel_baz_varsayilan_ms` (env; ölçüm sayılmaz), `baz_kapsami{story, olcum, varsayilan,
  olculmedi, metin}` (ör. "4 story'den 3'ünde ölçüm var, 1'inde ölçülmedi"), `kazanc_orani` =
  1 − Σ(hazırlık süresi) / Σ(ölçülmüş baz) yalnızca `kazanca_girer` story'ler üzerinden (REPLAY
  `yalniz_review` satırları başlığa girmez: `kazanc_replay_haric` sayısı + `kazanc_notu` "sunumdaki
  yüzde verimlilik iddiası değildir"; story oranı satırda etiketli kalır), `kazanc_story_sayisi`.
  `kaynaklar` yeni anahtarlar `kazanc_orani`, `baz_kapsami`. Portal aynı kuralı `hazirlik[]`'tan
  yeniden hesaplar (aynı sonuç; başlık REPLAY'de "REPLAY: hesaplanmaz").
- **Geçme oranı:** `gecme_orani` penceresi son n bitmiş CI koşusu; `make demo-break`'in main'e
  merge ettiği commit'lerdeki koşular (`demo kırılması` denetimi → `ozet.main_sonra`) ve kırma
  kampanyası hariç (`haric_kirma`); hazır Türkçe cümle `metin` (portal bunu gösterir). `gunluk_gecme`
  aynı dışlamayı uygular; karne/flaky main'in gerçek durumunu göstermeye devam eder.
- **Canlı değerlendirme (`tp_core.gateway.eval_live`, `make eval-live` / `scripts/eval-live.sh`):**
  host'ta `uv run --frozen`; sert bütçe `TP_EVAL_BUDGET_USD` (5; her vakadan önce en kötü durum
  maliyeti eklenir, aşacaksa durur; 7 setin tamamı için en kötü durum ≈21,5 USD → `--budget-usd 22`),
  `--ping` (tek çağrı, sır maskeli). **Anayasa VIII denetimi (karar):** host tarafı değerlendirme
  araçları PG `ai_call` tablosuna değil, hash zincirli append-only `exports/eval-live/ai_call.jsonl`
  defterine (`--ledger`; `CallLedger.verify` düzenleme/silme yakalar) ve rapor yanındaki commit'li
  `<rapor>.calls.jsonl` dosyalarına yazar (her vaka çağrısı ve her `--ping`, başarılı ya da hatalı),
  `--dry-run`, `--bundle`, `--update-status` (yalnızca tüm set koştu ve geçtiyse `evaluated`; asla
  `waived`), `--record` (aday golden'lar `exports/eval-live/<UTC>/replay-adaylari/`; `rules/replay`
  altına yazmayı reddeder). Değerlendirme setleri 8 paketin 7'si için vardır (requirement-review,
  case-generation, consistency-check, verify-and-map, triage, bug-draft, dup-rank;
  `core/tests/unit/gateway/build_eval_sets.py` üretir); ajan setleri (`agent: {tool_env, max_turns}`)
  üretim araçlarıyla koşar (`eval_agents`), ortam açılamazsa paket atlanır ve `pending` kalır.
  guardrails geçişli kapsanır (diğer hepsi güncel sürümde `evaluated` + aynı guardrails sürümü). Durum
  (2026-11-01): `requirement-review` v3, `triage`/`bug-draft`/`dup-rank` v2 `evaluated` (canlı,
  `rules/evaluation/results/`); `consistency-check`, `verify-and-map`, `case-generation` ve geçişli
  `guardrails` `pending` ("canlı değerlendirme bekliyor"). Tek doğruluk kaynağı `rules/evaluations.yaml`.
- **Canlı hata → REPLAY yedeği (`TP_REPLAY_FALLBACK`):** `Gateway.call`/`run_agent`'ta
  geçici/kalıcı sağlayıcı hatası ya da zaman aşımında (ret, bütçe, şema hatası hariç) başarısız canlı
  satır yazılır, aynı çağrı golden'dan sürer; satır `replay`/`replay_miss` etiketlidir (asla `live`),
  `ek.canli_hata_yedegi {neden, zaman_asimi, durum, canli_cagri, tur}` + `parent_call_id`. `auto`
  kipinde varsayılan açık, `live`'da kapalı, `record`/`replay`'de hiç; eval-live kapatır.
- **Prova (`rehearsal/`, `make demo-prova` / `scripts/demo-prova.sh`):** `make reset` → core-worker
  `TP_REPLAY_STRICT=1` ile yeniden oluşturulur → 25 adım (P0, A1–A8, B1–B5, C1–C5, D1–D5, Z1) API
  üzerinden, her biri beklenen durumu doğrular ve süre bütçesi taşır (ajan adımı ≤120 sn, toplam 25
  dk); Z1 `ai_call` modlarında REPLAY-MISS ya da sahte `live` olmadığını ve denetim zincirini doğrular.
  `--runs N` ardışık koşu, `--ui` portal + jira-sim arayüzüyle (Playwright, video), `--ui-tur` salt
  okuma tur. Raporlar `rehearsal/reports/` (git dışı).

## 6. Ortam değişkenleri (yeni)
`TP_SESSION_SECRET`, `TP_MODEL_MODE`, `JIRA_BASE_URL`, `JIRA_PROJECT` (varsayılan `TPD`),
`TP_TEST_MGMT`, `TP_FORGE`, `GITHUB_REPO`, `TP_DAILY_BUDGET_USD` (30), `TP_WORKFLOW_BUDGET_USD` (2).

Faz 1 entegrasyonunda eklenenler (boş = yerel simülatör / güvenli varsayılan):
- Jira/Xray: `JIRA_READ_EMAIL`/`JIRA_READ_TOKEN`, `JIRA_WRITE_EMAIL`/`JIRA_WRITE_TOKEN`,
  `JIRA_BROWSE_URL` (kullanıcıya gösterilen bağlantı kökü; compose varsayılanı jira-sim'in yerel adresi —
  gerçek Jira'da site adresi AÇIKÇA verilmelidir, boş bırakılırsa bağlantılar jira-sim'e gider), `JIRA_TIMEOUT_S` (10), `XRAY_BASE_URL`, `XRAY_CLIENT_ID`/`XRAY_CLIENT_SECRET`.
- Model (yalnızca core-worker): `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` (Faz 5; doluysa Anthropic
  adaptörü `anthropic-workspace-id` başlığını gönderir; sır sayılır, `make security-check` 6 anahtarla
  aynı denetler), `TP_MODEL_PROVIDER` (anthropic), `TP_PII_MASKING` (0); yalnızca host (compose değil):
  `TP_EVAL_BUDGET_USD` (5, `make eval-live`);
  core-api ve core-worker: `TP_RULES_DIR` (`/rules`, `./rules` salt okunur bağlanır).
- Forge: `GITHUB_TOKEN`, `GITHUB_MERGE_TOKEN` (insan token'ı; bot asla merge etmez), `GITHUB_API_URL`,
  `GH_APP_ID`, `GH_APP_PRIVATE_KEY` / `GH_APP_PRIVATE_KEY_PATH`, `GH_APP_INSTALLATION_ID`, `TP_FORGE_PRS_PATH`.
- Platform: `TP_MCP_PUBLIC_URL` (IDE'ye gösterilen MCP adresi), `TP_SESSION_MAX_AGE_S`,
  `TP_SESSION_COOKIE_SECURE`, `TP_API_TOKEN_TTL_S`, `TP_WORKER_POLL_S`.
- Ortam ve demo bayrakları (012; çekirdek): `TP_ORTAM` (`dev|test|staging|prod`, varsayılan `dev`;
  `prod` iken `developer` koşu başlatamaz), `TP_DEMO_MODE` (varsayılan `0`; `1` iken `/demo/*`
  yazma uçları açılır). `TP_ORTAM=prod` + `TP_DEMO_MODE=1` → çekirdek başlamaz. Canlı demo
  kurulumunun `.env`'ine `TP_DEMO_MODE=1` eklenmelidir.
- Ortak kimlik (ADR-0001, TEKNIK-TASARIM §8.14; yalnız core-api): `TP_AUTH_MODE` (`local` | `aiprobe` |
  `both`, varsayılan `local` — on-prem hep `local`), `AIPROBE_HOME_RUN_URL` (sunucudan sunucuya
  `aiprobe-home` adresi; TP'nin ID token audience'ı), `AIPROBE_ID_ORIGIN` (giriş/çıkış sayfası),
  `AIPROBE_PRODUCT_ID` (`testing-probe`), `AIPROBE_ALLOWED_ORGS` (virgülle; boş = herkes reddedilir),
  `AIPROBE_HOME_SA` (admin ucunu çağırabilecek tek servis hesabı e-postası), `AIPROBE_TP_AUDIENCE`
  (admin ucunda beklenen ID token `aud`'u), `AIPROBE_SESSION_CHECK_S` (60), `AIPROBE_IDLE_S` (1800),
  `AIPROBE_ABSOLUTE_S` (28800), `AIPROBE_HTTP_TIMEOUT_S` (5).
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
- Jira yorumları (yalnızca core-worker): ürünün her yorumu `🤖 AI Testing Probe:` imiyle başlar
  (`RestJira.add_comment`/`add_comment_adf`; yeni Bug açıklamasının ilk satırı da). Rol bahsetmeleri
  `JIRA_HESAP_ANALIST`, `JIRA_HESAP_PO`, `JIRA_HESAP_MUHENDIS`, `JIRA_HESAP_TESTCI` (accountId; boş = o
  rol bahsedilmez) ile ADF `mention` düğümü olarak aynı satıra yazılır: PO soru yorumu → PO + Analist;
  onay etiketi kaldırıldı / doküman düzeltmesi → PO; yayın özeti (story) → Testçi; mevcut Bug'a bağlama
  yorumu ve yeni Bug → Automation Engineer + Testçi (`integrations/jira_notify.py`). Bahsetme yalnızca bildirimdir:
  yetki vermez, onay sayılmaz; idempotency işaretleri gövdede aynen kalır.
- Portal görünen adları (core-api): `TP_GORUNEN_ADLAR` (`kullanici_adi=Ad Soyad`, virgülle; boş = seed
  demo varsayılanları; boş ad = yalnızca rol etiketi). Yalnızca gösterim; yetki kararları roldedir.
- Forge merge kapısı (core-api + core-worker, `x-core-env`): `TP_REQUIRED_CHECKS` (virgülle; boş =
  `local-ci` / GitHub ruleset listesi `test-local,ast-guard,semgrep`). Buraya yazılan her check HER
  PR'da zorunludur; LocalForge'da platform/dil check'leri buraya yazılmaz (aşağıdaki 009/011
  notları); GitHub'da yazılırsa ruleset ile aynı tutulur.
- Model geçidi: `TP_REPLAY_STRICT` (1 = prova: girdisi beyanla eşleşmeyen golden'a düşmez,
  `ReplayMiss` verir; beyanı (`input_match`) eşleşen golden geçer).
- Gereksinim akışı (Faz 2): `DEMOAPP_RO_DATABASE_URL` yalnızca core-worker'da (demoapp_ro; core-api
  demoapp'e bağlanmaz — MCP `get_requirement`'ın test verisi bloğu bu yüzden core-api'de statik
  bilgiye düşer). Ortak blokta (core-api + core-worker): `TP_PO_POLL_S` (15), `TP_CONSISTENCY_MAX_ROUNDS`
  (3), `TP_FORGE_REPO_NAME` (`demo-app`; kod kanıtındaki `evidence.repo`), `TP_FORGE_CHECK_REF` (`main`),
  `TP_MANUAL_BASELINE_S` (Faz 5'ten beri yalnızca story başına ölçümü olmayan story'lerin
  **varsayılanı**, saniye; her yerde "varsayılan" etiketli, kazanca girmez; boş = ölçülmedi; `make up`
  önkoşulu ve `make status` boşken bilgi verir; değer uydurulmaz — story başına ölçüm portaldan /
  `PUT /requirements/{id}/baseline` ile girilir; reset'e dayanıklı kopya `rules/baz-degerler.yaml`).
- Faz 5 integrasyonu: `TP_REPLAY_FALLBACK` (boş = kipe göre; yukarıda), `TP_TRIAGE_KIRMA_TASLAK`
  (1 varsayılan: kırma kırmızısı → taslak → testçi kararı; 0: taslak yok, failure `jira_yazilmaz`).
- toolchain-worker: `TP_APP_BUILD_SHA_FILE` (`/forge/demo-app-web.sha`; forge-init, `make break`,
  `make demo-baseline` ve `make up`'taki sync-web otomatik yazar), yedeği `DEMO_APP_BUILD_SHA`;
  `TP_CHECK_REQUIRE_APP_SHA` (0), `TP_CHECKS_PATH` (/checks), `TP_CHECKS_REQUIRE_MOUNT` (1),
  `TP_FORGE_REMOTE_URL`/`TP_FORGE_REMOTE_TOKEN` (GitHub modu, salt okunur; boş = kapalı),
  `TP_APP_PATHS` (uygulama eşleşmesi yolları; GitHub düzeni `demo-app/web,demo-app/api`),
  `TP_FORGE_MIRROR_PATH` (/forge-mirror/demo-app.git). core ortak blokta `TP_CHECKS_PATH` (/checks).
- `PLAYWRIGHT_VERSION`: tek kaynak `.playwright-version`; `make env` `.env`'e de yazar (düz
  `docker compose ps/logs/exec` çalışsın). Gerçek Jira'da `make reset` önce `jira_seed` planını
  yazdırır, onay (`e`) gelirse uygular; ayrıca `make jira-seed [ONAY=1]`.
  `TP_TEST_MGMT` ortak bloktadır: core-api (`/publish/preview`) ve core-worker (yayın) aynı hedefi görür.
- playwright-mcp: `MCP_ALLOWED_ORIGINS`, `MCP_ALLOWED_HOSTS` (Host başlığı izin listesi).
- Portal asistanı ve Öneri (hepsi isteğe bağlı; ayrıntı `specs/008-ai-asistan/contracts/env.md`):
  `TP_ASISTAN_MODEL_MODE` (`off`; `live` veya `off`, pipeline `TP_MODEL_MODE`'dan bağımsız — **yalnızca
  core-worker**, core-api kipi bilmez), `TP_ASISTAN_OTOMATIK_DERIN` (1; yalnızca core-worker),
  `TP_ASISTAN_MUSTERI_VERISI` (0; 1 iken `TP_PII_MASKING` kapalıysa asistan kapalı — yalnızca
  core-worker), `TP_ASISTAN_VERI_ROLLERI` (boş = `requirement.read` sahibi roller, auditor/viewer hariç; liste
  yalnız daraltır; `db_schema`/`db_query` — yalnızca core-worker), `TP_WORKER_ASISTAN_SERIT` (1; 0 → şerit ve kalp atışı yok → `worker_yok`; kalp atışı
  2 dk'dan eskiyken genel şerit 30 sn'de bir bekleyen asistan işlerini `cancelled`, mesajlarını
  `error/zaman_asimi` yapar — yalnızca core-worker), `GITHUB_ACTIONS_READ_TOKEN` (**sır**, yalnızca core-worker; `ci_log` için yalnız
  `actions:read`, boşsa mevcut okuma kimliği; `make security-check` 6 aynı denetler). Ortak blokta
  (core-api + core-worker): `TP_ASISTAN_ONERI` (1; 0 → öneri uçları/düğmesi kapalı),
  `TP_ASISTAN_SAKLAMA_GUN` (90), `TP_WORKER_ASISTAN_PARALEL` (3; global bekleyen sınırı = 2 × bu),
  `JIRA_CREATE_URL` (boş; "Jira'yı aç" yeni kayıt adresi — `https` (simülatörde `http://127.0.0.1`) ve
  kökeni `JIRA_BROWSE_URL` ile aynı olmalı, değilse yok sayılır + uyarı; boşsa gerçek Jira'da
  `JIRA_BROWSE_URL` + `/secure/CreateIssue!default.jspa`, simülatörde bağlantı yok). Asistan model
  anahtarı mevcut `ANTHROPIC_API_KEY`'dir (yeni anahtar yok). Bütçe/hız tavanları v1'de kod sabitidir.

**Ortam dağıtımı (compose):** `x-core-env` ortak bloğu core-api ve core-worker'a gider ve yazma
kimliği içermez. `JIRA_WRITE_*`, `XRAY_CLIENT_*`, `GITHUB_TOKEN`, `GITHUB_MERGE_TOKEN`, `GH_APP_*`,
`ANTHROPIC_API_KEY`, `PLAYWRIGHT_MCP_URL`, `GITHUB_ACTIONS_READ_TOKEN`, `TP_ASISTAN_MODEL_MODE` ve yukarıdaki
PO/merge ayarları **yalnızca core-worker**'dadır (`make security-check` 6 ve 8). Asistan bilgi paketi
(`./var/tp-bilgi:/opt/tp-bilgi:ro`) yalnızca core-worker'a bağlanır.

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

**Faz 4 ortam değişkenleri (hepsi isteğe bağlı; compose'da verilmez = varsayılan):** core-worker
`TP_TRIAGE_SWEEP_S` (30; 0 kapalı), `TP_TRIAGE_KIRMA` (1; 0 = kırma koşuları triage edilmez),
`TP_DEMO_WEB_REFRESH` (`istek`; `toolchain` henüz uç yok), `TP_DEMO_WEB_WAIT_S` (900),
`TP_DEMO_WEB_POLL_S` (5), `TP_REPAIR_ARIA_FALLBACK` (boş; `sozlesme` = aria dosyası yoksa sözleşme
testi geri dönüşü), `TP_PUBLIC_BASE_URL` (compose'da verilir; varsayılan
`http://127.0.0.1:${TP_PORTAL_PORT:-8080}`), `TP_WORKER_UZUN_SERIT` (1; uzun işler — `ci.run`,
`repair.fix`, `codegen.generate|break_verify`, `demo.break_locator|reset` — ayrı worker şeridinde,
`TP_WORKER_UZUN_TURLER` ile değişir). CI koşu dizini test-runner tarafından budanmışsa koşu
`artefakt_budandi` ile işaretlenir ve bağlantıları null döner. Yeni sır yok; `JIRA_SIM_ADMIN_TOKEN`
core-worker'a verilmedi (jira-sim'i silme yetkisi ajan sürecinde olmasın). `/demo/reset` jira-sim'i
sıfırlamaz (anahtar sayacı geri sarılırsa `external_ref` anahtarları çakışır); yalnızca bu sistemin
açtığı Bug'ları (`AI-generated` + `tp-<uuid>`) `RestJira.delete_issue` ile siler, gerçek Jira'ya dokunmaz.
`publish_bug` Jira'ya yazmadan önce Story/Test issue'larının varlığını denetler (yoksa kalıcı ret,
taslak karara döner). Triage öneri bloğu `{tur:'bug_draft', bug_draft_id, taslak_durumu, jira_key,
karar, sonuc_metni}` taşır. `make break` = `scripts/demo-break.sh --make` (core-worker'da
`python -m tp_core.features.demo on-kosul` ön denetimi; `Z=1` atlar).

**Neden değişti (Faz 4 entegrasyonu, FailureToFix):** triage, repair, bugs, goldens, toolchain,
portal ve demo-app şeritleri birleşti. Entegrasyonda bulunan ve düzeltilenler: (1) `make break` push
CI'ı demo-app-web yeniden derlenmeden kuyruğa alıyordu → koşu `app=farkli` ile environment oluyor,
locator yolu hiç başlamıyordu; şimdi `demo.await_web` bekler. (2) `/build.json` yeni commit'i
beyan ederken `/forge/demo-app-web.sha` birkaç saniye geride kalıyordu (canlıda gözlendi: CI yine
environment) → bekleme her ikisini ister. (3) Aynı kırılma için iki kez basılan "kır" iki push CI
açıyordu. (4) `scripts/demo-common.sh` HTTP kodunu alt kabukta kaybediyordu (`demo-break.sh` ilk
çağrıda düşüyordu). (5) Onarım PR'ları `/prs/{n}/merge`'de 404 veriyordu (codegen yalnızca `tur='test'`
arıyordu). (6) Kırık bir testId'den doğan 19 hata için 19 ayrı onarım açılabiliyordu. (7) Sağlık
kontrolü başarısız koşu var olmayan HTML raporuna bağlantı veriyordu. (8) Portal bug kanıtlarını
(`{ref, kind}`) "bağlantı yok" diye gösteriyordu. Tutarlılık taslakları artık karar anında mükerrer
hattına girer; `GET /bug-drafts` Faz 4 görünümünü döner.

**Neden değişti (Faz 4 son entegrasyon, 2026-11-01):** canlı kanıtta `make demo-reset` jira-sim'den
TPD-18/19'u sildikten sonra taslaklar ve triage öneri bloğu hâlâ "Jira'da açıldı: TPD-19" + ölü bağlantı
gösteriyordu (portal adaptörü `jira_url` null olsa da browse kökünden bağlantıyı yeniden kuruyordu).
Şimdi silinen anahtarlar taslakta işaretlenir (`jira_silindi`), görünüm ve portal bağlantı vermez.

**Neden değişti (Faz 5 entegrasyonu, 2026-11-01):** baseline, live, rehearsal, docs ve portal şeritleri
birleşti. Entegrasyonda kararlaştırılanlar: (1) kazanç kuralı tekleşti — core ve portal yalnızca
story'ye özel **ölçülmüş** baz değerli story'leri sayar, formül 1 − Σ süre / Σ baz (portal önceden
oranların ortalamasını alıyordu; core varsayılanı da sayıyordu). (2) REPLAY'de hazırlık süresi yalnız
review süresidir (`toplam_yontemi='yalniz_review'`; core önceden null döndürüyordu). (3) core-api model
ayarlarını görmediği için `GET /demo/status` → `model` core-worker'ın açılış bildirimini (denetim
`worker.model_mode`) okur; portal "canlı"yı kanıtsız göstermez. (4) `ANTHROPIC_WORKSPACE_ID` yalnızca
core-worker'a verildi. (5) `make demo-prova` ve `make eval-live` hedefleri eklendi. (6) 3'lü provanın 3. koşusunda push CI
35/36 (1 flaky) kaldı: demo-app-api'nin istek başına DB oturumu (FastAPI 0.162 yield bağımlılığı,
varsayılan `scope="request"`) commit'i yanıt gönderildikten SONRA yapıyordu; tarayıcı giriş yanıtından
5 ms sonra `/cart` isteyince oturum satırı henüz commit edilmemişti → 401 → uygulama giriş sayfasına
döndü. `SessionDep` artık `scope="function"` (commit yanıttan önce); satır numaraları değişmedi
(golden kanıt satırları aynı).

**009 mobil/masaüstü ekleri** (`specs/009-mobil-masaustu/plan.md`, [MOBIL-MASAUSTU.md](MOBIL-MASAUSTU.md)):
- core-worker: `APP_MCP_URL` (`http://app-mcp:8932/mcp`).
- app-mcp: `APPIUM_URL_ANDROID|IOS|WINDOWS`, `APP_ANDROID_PACKAGE`, `APP_ANDROID_ACTIVITY`,
  `APP_IOS_BUNDLE_ID`, `APP_IOS_UDID`, `APP_WINDOWS_APP`, `APP_MCP_*` (tam liste
  [CIHAZ-ALTYAPISI.md §6.3](CIHAZ-ALTYAPISI.md)).
- test-runner: `TP_E2E_APP_ROOT` (`e2e-app`), `APPIUM_URL_ANDROID|IOS|WINDOWS` (compose'da
  `TP_RUNNER_APPIUM_URL_*`; varsayılan `http://appium-gw:4723`, Windows boş), `TP_APP_ID_<P>`,
  `TP_APP_PATH_<P>`, `TP_DEVICE_UDID_<P>`.
- Merge kapısı: LocalForge'da platform kontrolleri `TP_REQUIRED_CHECKS`'e YAZILMAZ — yazılan liste
  her PR'da zorunludur, `local-ci,local-ci-android` web PR'larını (android check'i hiç gelmez) kilitler.
  LocalForge'da `local-ci-<platform>` yol kuralıyla (PR o platformun kökünü değiştirdiyse) otomatik
  eklenir; GitHub'da `TP_PLATFORMS` → `mobil-android`/`masaustu-windows` core'ca eklenir (ruleset ile
  aynı tutulur; ruleset güncellemesi `scripts/github-ruleset.sh --add-checks`, mevcutları korur).

**011 üretim dili ekleri** (`specs/011-uretim-dili/plan.md`):
- core-api + core-worker (`x-core-env`): `TP_PLATFORMS` (GitHub kipinde etkin uygulama platformları,
  `android,windows`; boş = yalnız web) ve **`TP_WEB_DILLERI`** (`ts,java`; boş = `ts`; `ts` her zaman
  etkin; yalnız `ts|java` geçerli, başka değer GitHub kipinde forge'u başlatmaz). `java` varsa
  web + Java üretimi ve Java kardeş koşusu açılır (`web-java` check'i ise K-T10'a göre
`web-java.yml` depoda olduğu sürece HER ZAMAN zorunludur; ilgisiz PR'da no-op ile hızla yeşil);
  yoksa `/code/languages` Java'yı kullanılamaz döner (K-T3). core-api de okur (merge kapısı listesi ve
  dil seçenekleri core-worker ile aynı olmalı). LocalForge'da kullanılmaz.
- toolchain-worker + test-runner: `TP_E2E_JAVA_ROOT` (`e2e-java`; GitHub kipinde `demo-app/e2e-java`),
  `TP_E2E_JAVA_DEPS` (imaj içi `/opt/e2e-java`; değiştirilmez).
- Merge kapısı (K-T11): LocalForge'da `local-ci` + (repoda e2e-java varsa ve PR web+Java'yı
  koşturuyorsa) `local-ci-web-java` yol kuralıyla otomatik eklenir. `TP_REQUIRED_CHECKS`'e
  `local-ci,local-ci-web-java` YAZMAYIN: yapılandırılmış liste her PR'da zorunludur ve yalnız TS
  değiştiren PR'ları (Java koşusu gelmez) kilitler. GitHub ruleset'i:
  `test-local,ast-guard,semgrep,web-java` + `TP_PLATFORMS` platform check'leri.
- GitHub merge kapısı (K-T13): zorunlu liste PR'ın **base ∪ head** ağacından (`web-java.yml` birinde
  varsa `web-java`); ağaç okunamaz ya da `truncated` ise kapalı taraf (`web-java` zorunlu). Portal
  aynası listeyi core'dan okur. `web-java.yml`'yi silen PR: önce ruleset'ten çıkar, sonra insan
  merge'ü (`docs/GCP-KURULUM.md` §10.2 adım 11).
- Güvenilir pom (K-T14): toolchain `check_deps` commit'teki pom'u imajdaki kopyayla
  (`TP_E2E_APP_ROOT`/`pom.xml` ↔ `toolchain/e2e-app-deps/pom.xml`; e2e-java için `e2e-java-deps`)
  bayt bayt karşılaştırır. Pom'u değiştiren dağıtımda toolchain imajının hemen ardından depo/forge
  eşitlenir (`docs/GCP-KURULUM.md` §10.2 adım 5; LocalForge `make forge-sync-dizin D=e2e-app
  K=uretilen` — `--koru` merge edilmiş üretilen testleri forge main'deki hâliyle bırakır).

## 7. Kalite kapısı (her şerit)
- Python: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` yeşil.
- TypeScript: `npm run build` (tsc strict) ve varsa `npm test` yeşil.
- Kendi dizini dışındaki dosyaya dokunmaz; commit atmaz; tam `make up` yapmaz (entegrasyon liderin).

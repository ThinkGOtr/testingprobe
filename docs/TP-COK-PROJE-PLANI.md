# Testing Probe — tek sunucuda çok proje: uygulama planı ve paralel şerit sözleşmesi

Durum: plan (kod yok). Dal: `feat/tp-cok-proje`. Tarih: 2026-11-15.
Girdiler: Config R1 (`core/src/tp_core/home_config/`, `auth/aiprobe.py` A3, migrasyon 0043),
`UYGULAMA-PLANI-R1.md` §6 (ürün uçları), `CONFIG-ANALIZI.md` §2.2 #4 ve §3.6 "TP", `envanter/tp_core.md`.

## 0. Kararlar (kullanıcı, bağlayıcı) ve bu planın temel seçimleri

| # | Karar | Planda karşılığı |
|---|---|---|
| K1 | Ağır işler (kod üretimi, e2e/mobil/Windows koşuları, CI) tüm projeler için **ortak kuyrukta sırayla** | Tek `job` tablosu, tek worker, mevcut uzun şerit + toolchain koşu kilidi korunur; iş satırı `project_id` taşır (§5) |
| K2 | Cihazlar (Mac Appium iOS/Android, Windows VM) **paylaşımlı havuz**; projeye özgü olan yalnız uygulama paketi/ayarları | Cihaz uçları D (kurulum) kalır; `TP_APP_*` T olur ve koşu isteğinin `proje` bloğunda gider (§4.4) |
| K3 | Sağ üstte proje seçimi, aynı sekmede geçiş, seçim kullanıcıya kaydedilir, roller **seçili projedeki** rollerdir; arka plan işleri kendi projesinde sürer | `oturum.project_id` + `app_user.secili_proje`, `PUT /api/proje`, istek başına `X-TP-Proje` tutarlılık başlığı, worker işi bağlamı `job.project_id`'den kurar (§2, §6) |
| K4 | Mevcut tüm TP verisi bugünkü projeye (Bayi Portalı, `TP_HOME_PROJECT`) aittir | Migrasyon 0045 tüm satırları `TP_HOME_PROJECT` ile doldurur (hızlı varsayılan; satır yeniden yazılmaz) (§1.4) |

Temel seçimler:

- **Proje kimliği** = Home `pid` (`String(64)`, 0043'teki `oturum.project_id` ile aynı tip). TP kendi proje kimliği üretmez.
- **Bağlam** = `contextvars` tabanlı `ProjeBaglami`; API'de istek bağımlılığı, worker'da iş satırı, CLI'da açık `proje_icinde(pid)` kurar. Bağlamsız proje-kapsamlı erişim **hata** verir (sessizce varsayılan projeye düşmez).
- **Sorgu filtresi merkezde**: ORM için SQLAlchemy `do_orm_execute` + `with_loader_criteria` (otomatik), yükleme anında `load` olay koruyucusu (yanlış projeden satır gelirse istisna), INSERT'te `before_flush` ile `project_id` doldurma. Ham SQL (`text(...)`, ~106 yer) için açık `project_id = :pid` + statik ve dinamik denetim testleri (§2.4).
- **Config**: süreç-global `os.environ` üstüne yazma (R1 `durum._uygula`) yalnız D anahtarları için kalır; T/A/P değerleri **proje başına** önbellekten `proje.ayar(ad)` ile okunur (§3).
- Tek sunucu = tek organizasyon varsayımı (hücre modeli, CONFIG-ANALIZI §3.6). Farklı organizasyonların projelerini aynı TP'de barındırmak kapsam dışı (§8.2).

---

## 1. Veri modeli

### 1.1 Sınıflandırma (tüm tablolar, `core/src/tp_core/models/*.py` + `workflow/service.py`)

**A. Proje kapsamlı — `project_id VARCHAR(64) NOT NULL`, `ProjeKapsamli` mixin'i (otomatik filtre):**

| Alan | Tablolar |
|---|---|
| Gereksinim | `requirement`, `requirement_review`, `requirement_review_ek`, `requirement_kontrol`, `requirement_akis`, `requirement_baz_deger`, `consistency_finding`, `consistency_finding_ek`, `acik_soru` |
| Case / kalite | `test_case`, `review`, `case_goruntuleme`, `case_uretim`, `tasarim_modeli`, `case_set_review`, `case_set_audit`, `case_oracle_kontrol`, `oracle_istisna`, `karar_tablosu`, `metamorfik_iliski`, `metamorfik_turetme` |
| Teslim / CI | `script`, `script_test_case`, `script_codegen`, `script_adim`, `script_kontrol`, `step_mapping`, `pull_request`, `run`, `run_aria`, `test_result`, `test_result_ek`, `failure`, `failure_ek`, `triage_kosu`, `bug_draft`, `bug_draft_ek`, `external_ref`, `ci_tetik`, `hata_kosusu`, `hata_kosusu_adim` |
| Otomasyon / veri | `otomasyon_ayari`, `test_verisi`, `test_verisi_surum` |
| Agent Probe | `ajan_urunu_baglantisi`, `ajan_testi_talebi`, `asistan_denetim` |
| Asistan | `asistan_sohbet`, `asistan_mesaj`, `asistan_oneri_geri_bildirim`, `asistan_guvenlik_olay`, `asistan_durum` |
| Sistem | `workflow_instance`, `ai_call`, `tool_call`, `audit_event` (§1.3), `api_token` (MCP token'ı bir projeye bağlanır) |

Çocuk tablolar da (FK'si `requirement`/`script`/`run` olanlar) sütunu **denormalize** taşır: `session.get(Script, id)`, ham `WHERE id = :id` sorguları ve IDE/MCP uçları çocuk satıra doğrudan id ile ulaşıyor; tek tip kural ("kapsamlı tablo = sütunu var") hem filtreyi hem denetim testini basitleştirir. Tutarlılık için çocuk–ebeveyn proje eşitliği `before_flush` koruyucusunda denetlenir (§2.3); bileşik FK (R2, §8.2) gerekmez.

**B. Proje sütunu var ama boş olabilir:** `job.project_id NULL` = kurulum geneli bakım işi (reap, artefakt temizliği, asistan paket yenileme). Otomatik filtreye **girmez** (worker tüm projelerin işini sırayla alır, K1).

**C. Kurulum geneli (sütun yok):** `app_user`, `kimlik_bagi`, `oturum` (0043'te `project_id` = seçili proje; filtre değil bağlam). `asistan_hiz`: sütun eklenir, kullanıcı kovaları `project_id = '_kurulum'` (maliyet koruması proje sayısıyla katlanmasın), `jira_global` gibi kullanıcısız kovalar proje başına.

### 1.2 Global tekillikler → proje kapsamı

| Bugün | Yeni | Not |
|---|---|---|
| `requirement.jira_key` UNIQUE | `UNIQUE (project_id, jira_key)` | İki proje aynı Jira sitesinde farklı anahtar öneki kullanır, ama aynı Jira projesine bağlanmış iki TP projesi de izinli olmalı |
| `test_verisi.anahtar` (`test_verisi_anahtar_uq`) | `UNIQUE (project_id, anahtar)` | |
| `otomasyon_ayari` PK `anahtar` | PK `(project_id, anahtar)` | `ayarlar.py` okuma/yazma `project_id` alır |
| `ci_tetik.anahtar` UNIQUE | `UNIQUE (project_id, anahtar)` | |
| `failure_ek.anahtar` UNIQUE | `UNIQUE (project_id, anahtar)` | |
| `ajan_testi_talebi.talep_no` UNIQUE + `ajan_testi_talebi_no_seq` | `UNIQUE (project_id, talep_no)`; numara `proje_sayac` (§1.5) | Mevcut dizi Bayi Portalı'nın sayacına taşınır (son değer) |
| `external_ref.idempotency_key` UNIQUE | `UNIQUE (project_id, idempotency_key)` | |
| `job.idempotency_key` kısmi UNIQUE | `UNIQUE NULLS NOT DISTINCT (project_id, idempotency_key) WHERE idempotency_key IS NOT NULL` (PG16) | `enqueue` `ON CONFLICT (project_id, idempotency_key)`; `idempotency_lock` anahtarı `pid:key` |
| `pull_request.number` PK (global autoincrement) | PK `(project_id, number)`; LocalForge numarası `proje_sayac('pr')`; GitHub kipinde GitHub'ın numarası | `script.pr_no`, `run.pr_no`, `ci_tetik.pr_no` FK değil; sorgular `project_id` ile eşlenir. Mevcut sayaç: `max(number)` Bayi Portalı sayacına |
| `asistan_durum` tekil satır `id=1` | PK `project_id` (`id` sütunu düşer) | Asistan dondurma/durum proje başına |
| `asistan_hiz` `asistan_hiz_uq` | tekillik `project_id` dahil (NULLS NOT DISTINCT korunur) | §1.1 C |
| `asistan_mesaj` kısmi unique index'leri | `project_id` öne eklenmez (sohbet zaten projeye bağlı) | değişmez |
| `review.sira` IDENTITY UNIQUE | değişmez (global sıra, kimlik) | |
| `app_user.kullanici_adi` UNIQUE | **değişmez** (kullanıcı kurulum geneli; roller proje başına Home'dan) | |
| `audit_event.prev_hash` UNIQUE | `UNIQUE (project_id, prev_hash)`; `hash` UNIQUE kalır | Her zincir GENESIS ile başladığından global unique ikinci projede çakışır |

Liste/çalışma index'leri: sık listelenen tablolarda (`requirement`, `test_case`, `script`, `run`, `test_result`, `failure`, `bug_draft`, `job`, `ai_call`, `audit_event`, `asistan_sohbet`) `project_id` ilk sütun olan bileşik index eklenir (ör. `run_proje_olusturma_ix (project_id, olusturma)`, `ai_call_proje_olusturma_ix (project_id, olusturma)` — günlük bütçe/maliyet ekranı). Mevcut `job_*` kısmi index'ler `yuk ->> ...` üzerinde kalır (iş türü bazlı; proje sayısı küçük).

### 1.3 `audit_event` zinciri — öneri: **proje başına zincir**

- `project_id NOT NULL`; kurulum geneli olaylar (giriş, config yenileme, proje değiştirme, worker model kipi) `'_kurulum'` zincirine yazılır.
- `append_audit(conn, ..., project_id=None)` → `None` ise bağlamdaki proje, bağlam yoksa `'_kurulum'`. Kilit `pg_advisory_xact_lock(AUDIT_LOCK_KEY, hashtext(pid))` (iki argümanlı biçim; projeler birbirini beklemez). `prev` = o projenin son `hash`'i.
- Hash formülü **değişmez** (`project_id` kanonik JSON'a girmez): mevcut zincir migrasyondan sonra olduğu gibi geçerli kalır; bir satırın projesinin değiştirilmesi zaten append-only trigger'ı ile yasak ve iki zinciri birden kırar.
- `verify_chain(conn, project_id)` ve `chain_tip(conn, project_id)`; `make export-audit` proje başına dosya (`exports/audit-<pid>-*.jsonl`). Gerekçe: proje başına denetim dışa aktarımı/teslimi ve gelecekte proje silme/taşıma (R2) tek zincirde mümkün değil; tek zincir yalnız "tek doğrulama" kolaylığı sağlar.

### 1.4 Migrasyonlar

- **0044 (Şerit 0):** `tp_proje(pid PK varchar64, kod, ad, kaynak IN ('env','kesif'), aktif bool, olusturma, guncelleme)`; `proje_sayac(project_id, ad, deger bigint, PK(project_id, ad))`; `app_user.secili_proje varchar64 NULL`. Grant'ler `tp_app`'e. Varsayılan proje satırı: `TP_HOME_PROJECT` (env), yoksa `'varsayilan'` (yerel/on-prem `CONFIG_SOURCE=env`).
- **0045 (Şerit 1):** her kapsamlı tablo için `ALTER TABLE t ADD COLUMN project_id varchar(64) NOT NULL DEFAULT '<pid>'` sonra `ALTER COLUMN project_id DROP DEFAULT`. PG11+ "hızlı varsayılan" satırı yeniden yazmaz ve UPDATE tetiklemez → `ai_call`/`tool_call`/`audit_event`/`review` append-only trigger'ları devre dışı bırakılmaz, `audit_event` hash'leri bozulmaz. `<pid>` migrasyon anında `TP_HOME_PROJECT` env'den okunur; `CONFIG_SOURCE=home` iken boşsa migrasyon **hata ile durur** (yanlış pid'le kalıcı damgalamayı önler). Ardından §1.2 kısıt değişiklikleri, index'ler, `proje_sayac` tohumları (`pr` = `max(pull_request.number)`, `talep` = `ajan_testi_talebi_no_seq` son değeri), `asistan_durum` PK dönüşümü. `job.project_id` NULL'a izinli; mevcut `queued/retry/running` işler varsayılan pid alır.
- Downgrade: yalnız tek proje varken (`SELECT count(DISTINCT project_id) <= 1` her tabloda) çalışır, aksi halde `RuntimeError`.
- Model ↔ şema eşitliği mevcut `tests/unit/platform/test_migrations.py` ve `features/assistant/test_migration.py` deseniyle doğrulanır.

### 1.5 Proje sayacı

`tp_core/proje/sayac.py: sonraki(conn, ad: str, project_id: str | None = None) -> int` — `INSERT … ON CONFLICT (project_id, ad) DO UPDATE SET deger = proje_sayac.deger + 1 RETURNING deger` (yarışsız, işlem kapsamlı). Kullanıcılar: LocalForge PR numarası (`'pr'`), Agent Probe talep no (`'talep'`).

---

## 2. İstek bağlamı ve sorgu filtresi

### 2.1 Bağlamın kaynağı

| Kanal | Proje nereden | Kim kurar |
|---|---|---|
| Portal (çerez oturumu) | `oturum.project_id` (seçili proje) | `current_user` bağımlılığı → `proje_icinde(pid, kaynak="oturum")` |
| MCP / IDE (`tpt_` token) | `api_token.project_id` | `require_token` |
| Worker işi | `job.project_id` (NULL → bağlam yok, yalnız kurulum işleri) | `worker` iş yürütücüsü |
| Periyodik planlayıcı (açılış kancaları) | `kurulu_projeler()` döngüsü | her proje için `proje_icinde(pid, kaynak="sistem")` |
| CLI (`seed`, `jira_seed`, `demo`, `home_config`) | `--proje` argümanı, yoksa `varsayilan_pid()` | komut girişi |

Bağlam `contextvars.ContextVar` içindedir; FastAPI senkron uçları threadpool'da koşsa da bağımlılık aynı bağlamda çözüldüğü için değişken uca taşınır (Starlette `run_in_threadpool` contextvars'ı kopyalar). Arka plan iş parçacıkları (`threading.Thread`) bağlamı **miras almaz**; açıkça `proje_icinde` kurmaları gerekir (desen testi §2.4).

### 2.2 Çok sekme tutarlılığı

Seçim oturumdadır (K3: aynı sekmede geçiş). İkinci sekme eski projeyi göstermeye devam edip yeni projeye yazmasın diye portal her API isteğinde `X-TP-Proje: <pid>` gönderir; `current_user` başlık ≠ oturum projesi ise **409 `proje_degisti`** döner (GET dahil; yazma güvenliği için yeterli, okuma tutarlılığı için de basit). Portal 409'da `aiprobe:project-change` ile aynı yolu izleyip sayfayı yeni projede yeniden yükler. Başlıksız istekler (eski istemciler, `curl`) oturum projesini kullanır.

### 2.3 Merkezî filtre (Şerit 0)

1. `ProjeKapsamli` mixin'i (`models/base.py`) `project_id` sütununu ve `default=mevcut_pid` tanımlar.
2. `tp_core/proje/orm.py:kur(session_cls)` — `models.new_session` fabrikasında bir kez çağrılır:
   - `do_orm_execute`: `state.is_select` (ve `is_update`/`is_delete` ORM toplu işlemleri) için `with_loader_criteria(ProjeKapsamli, lambda c: c.project_id == mevcut_pid(), include_aliases=True)`. Kaçış: `.execution_options(tum_projeler=True)` (yalnız worker/kurulum kodu; statik testte izinli liste).
   - `load` olayı (`ProjeKapsamli`, `propagate=True`): yüklenen nesnenin `project_id`'si bağlamdakinden farklıysa `ProjeIhlali` (sızıntıyı sessiz yanlış veri yerine 500'e çevirir).
   - `before_flush`: yeni `ProjeKapsamli` nesnelerinde `project_id` yoksa bağlamdan doldurur; varsa ve bağlamla uyuşmazsa `ProjeIhlali`.
3. Ham SQL: `text()` ifadeleri kapsamlı tabloya dokunuyorsa `project_id = :pid` taşır; parametre `proje.pid_param()` (`{"pid": mevcut_pid()}`) ile birleştirilir. `conn.execute(select(Model.__table__))` gibi Core ifadeleri de ham SQL sayılır (loader criteria Core'a uygulanmaz).
4. Derinlemesine savunma olarak Postgres RLS (`SET LOCAL tp.project_id`) R2'ye bırakılır (§8.2): `tp_app` rolüyle uyumlu ama worker'ın çok projeli işleri ve `tum_projeler` kaçışı için ikinci bir rol/ayar gerekir.

### 2.4 Atlanan sorgu riskini azaltan testler (Şerit 0 kurar, şeritler yeşile çeker)

- **Statik (AST) test** `core/tests/unit/platform/test_proje_kapsami.py`:
  - `text(...)`/f-string SQL'de `KAPSAMLI_TABLOLAR` adlarından biri geçip `project_id` geçmeyen her ifade → hata.
  - `.execution_options(tum_projeler=True)` yalnız izinli modüllerde.
  - `threading.Thread(` / `ThreadPoolExecutor` hedefleri `proje_icinde` veya `contextvars.copy_context` kullanmıyorsa → hata.
  - `os.environ`/`os.getenv` ile `PROJE_ANAHTARLARI` (§3.2) içindeki bir adı okumak → hata (yalnız `home_config/` ve `proje/ayar.py` izinli).
  - Geçiş süresince kalan ihlaller **şerit başına** taban dosyalarında: `core/tests/unit/platform/proje_istisna/serit{1..5}.txt` (her şerit yalnız kendi dosyasını küçültür; birleştirme sonunda dosyalar yalnız gerekçeli kalıcı istisnaları içerir; satır biçimi `yol:satır-öncesi-imza  # gerekçe`). Dosyaya yeni satır eklemek review'da reddedilir (cırcır).
- **Dinamik test (SQL yakalama)** `conftest.py` fikstürü `sql_denetimi`: `before_cursor_execute` ile, bağlam varken çalışan ve kapsamlı tabloya dokunan her SQL'de `project_id` yoksa testi düşürür. Tüm `features/*` testleri bu fikstürle çalışır (otomatik `autouse`, `TP_TEST_REQUIRE_DB=1`).
- **İzolasyon testi** `core/tests/unit/platform/test_proje_izolasyonu.py`: `iki_proje` fikstürü (A, B projeleri, aynı tohum verisi, farklı pid) → her GET liste/ayrıntı ucunu (router kayıt defterinden otomatik keşif, `api/registry.py`) B oturumuyla çağırır; yanıtta A'nın id'si/anahtarı geçmemeli; A'nın nesne id'siyle B oturumunda ayrıntı 404 olmalı. Şeritler kendi uç kümeleri için parametre sağlar.

---

## 3. Config

### 3.1 Proje başına etkin config

- `home_config/durum.py` → `ProjeDurumu` haritası `pid → (Yukleyici, EtkinConfig, etag, LKG yolu, kaynak)`. LKG dosyası `/var/lib/tp-config/<servis>-<pid>.json` (bugünkü `<servis>.json` varsayılan proje için okunur ve ilk yazımda yeni ada taşınır).
- Yenileme döngüsü (60 sn) `kurulu_projeler()` üzerinde döner; her proje kendi `If-None-Match`'iyle `GET /v1/config/effective?project=<pid>` çağırır. Home 403/404 (pid artık `allowed_pids`'te değil) → o projenin özellikleri kapalı (fail-closed, R1 N4 kuralı proje başına) ve `tp_proje.aktif=false` önerisi denetime yazılır (otomatik silme yok).
- **`os.environ`'a yazma yalnız D anahtarları için** kalır (bugünkü R1 overlay davranışı; açılışta host betiği varsayılan projenin D değerlerini env dosyasına yazmayı sürdürür). T/A/P değerleri ve sır referansları süreç ortamına **yazılmaz**; sırlar Secret Manager'dan proje başına çözülüp bellekte (TTL'li) tutulur.
- `CONFIG_SOURCE=env` (yerel/on-prem): tek proje (`varsayilan_pid()`), `ayar()` doğrudan `os.environ` okur — bugünkü davranış birebir korunur.

### 3.2 Çalışma anında config erişim API'si (imza Şerit 0'da, gerçek uygulama Şerit 2'de)

```python
# tp_core/proje/ayar.py
def ayar(ad: str, varsayilan: str | None = None, *, pid: str | None = None) -> str | None: ...
def ayar_bool(ad: str, varsayilan: bool = False, *, pid: str | None = None) -> bool: ...
def ayar_int(ad: str, varsayilan: int, *, pid: str | None = None) -> int: ...
def ayar_float(ad: str, varsayilan: float, *, pid: str | None = None) -> float: ...
def sir(ad: str, *, pid: str | None = None) -> str | None: ...        # Secret Manager / env
def ozellik_acik(ad: str, *, pid: str | None = None) -> bool: ...     # web/android/ios/windows/ai_agent
def surum(pid: str | None = None) -> str: ...                          # etag; istemci önbellek anahtarı
PROJE_ANAHTARLARI: frozenset[str]  # T/A/P sınıfı legacy env adları (§3.3); statik test kullanır
```

Çözüm sırası: proje etkin config (`env` legacy adı) → `os.environ` (yalnız `pid == varsayilan_pid()` için; geçiş geriye uyumluluğu) → `varsayilan`. Ayar önbellekli pydantic sınıfları (`JiraSettings`, `RequirementsSettings`, `GatewaySettings`, `Settings`'in proje alanları) `@lru_cache` yerine `(pid, surum(pid))` anahtarlı önbellek kullanır; R1'deki `_onbellekleri_temizle` ve `CALISMA_ANINDA` listesi bu anahtar sayesinde gereksizleşir (liste D anahtarlarına iner).

`home_config/kapi.py` (`ozellik_gerekli`, `platform_gerekli`, `ai_agent_gerekli`) bağlamdaki projeye göre çalışır (imzalar değişmez).

### 3.3 `os.environ` okumalarının sınıflandırması (envanter `tp_core.md`, ~80 ad / 51 dosya)

| Sınıf | Kalır mı | Adlar (özet) |
|---|---|---|
| **D — kurulum (global kalır, `os.environ`/`Settings`)** | evet | `TP_DATABASE_URL`, `TP_DB_REQUIRE_AUTH`, `TP_ORTAM`, `TP_DEMO_MODE`, `TP_SESSION_*`, `TP_API_TOKEN_TTL_S`, `TP_TRUSTED_PROXIES`, `TP_ALLOWED_ORIGINS`, `TP_MCP_PUBLIC_URL`, `TP_PUBLIC_BASE_URL`, `TOOLCHAIN_URL`, `TP_TOOLCHAIN_TOKEN`, `PLAYWRIGHT_MCP_URL`, `APP_MCP_URL`, `TP_ARTIFACTS_PATH`/`TP_CODEGEN_ARTIFACTS_PATH`/`TP_GITHUB_ARTIFACTS_PATH`/`TP_CHECKS_PATH`, `TP_RULES_DIR`, `TP_BILGI_DIZIN`, `TP_WORKER_*`, `TP_AGENT_PROBE`, `TP_AUTH_MODE`, `AIPROBE_*` (HOME_RUN_URL, ID_ORIGIN, PRODUCT_ID, HOME_SA, TP_AUDIENCE, SESSION_CHECK_S, HTTP_TIMEOUT_S), `TP_MODEL_MODE`, `TP_REPLAY_*`, `TP_EVAL_BUDGET_USD`, `JIRA_TIMEOUT_S`, `TP_TEST_TEK_HESAP`, `JIRA_SIM_*`/`SIM_*`, `TP_FORGE_PATH`/`TP_FORGE_PRS_PATH` (artık **kök** dizin; §4.3), `GH_APP_ID`, `GH_APP_PRIVATE_KEY*`, tüm zaman aşımları (`TP_CHECK_QUEUE_WAIT_S`, `TP_GIT_TIMEOUT_S`, `TP_RUN_*`, `TP_CI_DISPATCH_GRACE_S`, `TP_CI_GITHUB_POLL_S`, `TP_CI_GITHUB_BULMA_S`, `TP_CI_CHECK_TIMEOUT_S`), `TP_ARTIFACT_LINK_TTL_S`, `TP_TRIAGE_SWEEP_S`, `TP_PO_POLL_S`, `TP_CODEGEN_PR_SYNC_S`, `TP_DEMO_WEB_*`, `TP_APP_BUILD_SHA_FILE`, `TP_DEMO_DURUM_ONBELLEK_S`, cihaz uçları (`APPIUM_URL*`, `TP_DEVICE_NAME`, `TP_DEVICE_UDID`, Windows VM adresi) — **K2 paylaşımlı havuz** |
| **A — organizasyon (tek org/sunucu; yine `ayar()` ile okunur, Home etkin config'e org değerini katar)** | `ayar()` | `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, `TP_MODEL_PROVIDER`, `AZURE_OPENAI_*`, `TP_PII_MASKING`, `TP_DAILY_BUDGET_USD` (kurulum geneli toplam bütçe olarak uygulanır; §8.2), `JIRA_BASE_URL`, `JIRA_BROWSE_URL`, `JIRA_CREATE_URL`, `JIRA_READ_*`, `JIRA_WRITE_*`, `XRAY_*`, `TP_JIRA_BOT_ACCOUNT_IDS`, `GITHUB_API_URL`, `TP_FORGE_WEB_URL`, `GH_APP_INSTALLATION_ID`, `GITHUB_TOKEN`/`GITHUB_READ_TOKEN`/`GITHUB_ACTIONS_READ_TOKEN`, `TP_FORGE_REMOTE_TOKEN`, `TP_GITHUB_ARTIFACTS_KEEP`/`_MAX_GB`, `TP_CODEGEN_SCREENSHOT_DAYS`, `AIPROBE_IDLE_S`/`ABSOLUTE_S`, `AIPROBE_ALLOWED_ORGS` |
| **T — proje** | `ayar()` | `JIRA_PROJECT`, `TP_TEST_MGMT`, `JIRA_PO_ACCOUNT_IDS`, `TP_PO_JIRA_USERS`, `JIRA_HESAP_*`, issue type/link adları, `CONTENT_FIELDS`, `TP_FORGE`, `GITHUB_REPO`, `TP_FORGE_REMOTE_URL`, `TP_FORGE_APP_ROOT`, `TP_FORGE_REPO_NAME`, `TP_FORGE_CHECK_REF`, `PROTECTED_BRANCHES`, `TP_REQUIRED_CHECKS`, `TP_PLATFORMS`, `TP_WEB_DILLERI`, `TP_FORGE_REQUIRE_UP_TO_DATE`, `BYPASS_ACTOR`, CI iş akışı adları, `TP_CI_NIGHTLY_SAAT`/`_GEC_S`, `TP_MANUAL_BASELINE_S`, `TP_DEMO_WEB_URL`, `TP_AGENT_DEALER`/`_PASSWORD`, `VERIFY_*`, `DEMOAPP_RO_DATABASE_URL`/`_PASSWORD`, testdata sorguları, Java/C# paket ve dizin adları, E2E dizinleri, `TP_APP_*` (paket/kimlik/aktivite/yol/argüman/çalışma dizini — K2), `rules/hata-katalogu.yaml`, `rules/pii-allowlist.yaml`, `rules/baz-degerler.yaml` |
| **P — ürün (proje içinde ürün ayarı)** | `ayar()` | `TP_WORKFLOW_BUDGET_USD`, `TP_CI_KOSU_ZAMAN_ASIMI_S`, `TP_CI_GITHUB_TIMEOUT_S`, `TP_TRIAGE_KIRMA*`, `TP_REPAIR_ARIA_FALLBACK`, `TP_DENETIM_KAPISI`, `TP_DENETIM_GUNLUK_SINIR`, `TP_REVIEW_GUNLUK_SINIR`, `TP_CONSISTENCY_MAX_ROUNDS`, `TP_HATA_KOSUSU_GECERLI_ESIK`, `HEDEFLER`, `TP_CT_*`, `TP_CODEGEN_STEP5_BUDGET_S`, `TP_ASISTAN_*` (R1 `CALISMA_ANINDA` listesindekiler), `TP_KURAL_YENIDEN_ISTEME`, `rules/models.yaml purposes.*.model` |
| **U — profil** | dokunulmaz | `TP_GORUNEN_ADLAR` |

Kural: D dışındaki her ad `PROJE_ANAHTARLARI`'na girer ve `ayar()` ile okunur. Kod sabitleri (K) değişmez.

**Kural dosyaları (T):** `rules/hata-katalogu.yaml`, `pii-allowlist.yaml`, `baz-degerler.yaml` Bayi Portalı'na özgü. R1-çok-proje: varsayılan proje bugünkü dosyaları kullanır; diğer projeler `rules/projeler/<pid>/<dosya>` varsa onu, yoksa **boş** katalog/izin listesi kullanır (Bayi'ye özgü kuralın başka projeye sızmaması). Kural önbellekleri `(pid, dosya mtime)` anahtarlı. Home'dan kural dosyası yönetimi R2.

---

## 4. Entegrasyon istemcileri (Şerit 3)

### 4.1 Fabrika

`tp_core/proje/istemciler.py` (imza Şerit 0'da, mevcut tekillere yönlendiren ince kabuk; Şerit 3 içini doldurur):

```python
def jira() -> JiraClient: ...          # bağlamdaki proje
def xray() -> XrayClient | None: ...   # TP_TEST_MGMT=xray değilse None
def forge() -> Forge: ...              # LocalForge | GitHubForge | DemoForge
def ci() -> GitHubActionsClient | None: ...
def toolchain_proje_blogu() -> dict[str, Any]: ...   # §4.4
def sifirla(pid: str | None = None) -> None: ...     # test + config değişimi
```

Önbellek anahtarı `(pid, ayar.surum(pid))`; config etag'i değişince istemci yeniden kurulur. Modül düzeyi tekiller (`features/requirements/services.py:32` `@lru_cache(maxsize=1)`, `integrations/jira.py` `JiraSettings`, `forge.py` fabrikası, `ci/clients.py`) bu fabrikaya bağlanır.

### 4.2 Jira / Xray

- Kimlik: `baglanti.token_al(tur, pid)` — R1 erişim token önbelleği `(pid, tur)` anahtarlı; `POST /v1/connections/access-token {project: pid, type}`. `token` kipinde proje config'inden sır (`sir("JIRA_READ_TOKEN")`).
- `JIRA_PROJECT`, issue type adları, alanlar, PO hesapları: proje ayarı. Bildirim (`jira_notify.py`) ve tohum (`jira_seed.py`) bağlamdaki projeyi kullanır; `make jira-seed` varsayılan projeye kilitli (demo verisi Bayi'ye özgü).

### 4.3 GitHub / forge / repo klonları

- Yerel forge kökü D (`TP_FORGE_PATH` artık kök): proje deposu `/forge/<pid>/repo.git`, PR kayıtları `/forge/<pid>/prs`, ayna `/forge-mirror/<pid>.git`. **Varsayılan proje geriye uyumlu yol haritası kullanır** (`/forge/demo-app.git`, `/forge-mirror/demo-app.git`): canlı göçte dosya taşınmaz. Yol çözücü tek yerde: `tp_core/integrations/forge_yollari.py: depo_yolu(pid) / pr_dizini(pid) / ayna_yolu(pid)`.
- GitHub kipi: `GITHUB_REPO` proje ayarı, App kurulum token'ı Home'dan proje kapsamlı (repo kapsamı Home'da). PR senkronu (`sync_prs`) ve CI yoklaması proje başına iş (§5).
- `forge-init`, `forge-sync-dizin`, `break`, `demo-*`, `demo-web-sync` Make hedefleri ve host betikleri yalnız varsayılan projeyi bilir (demo-app). Yeni projede demo özellikleri kapalı (`demo` uçları varsayılan proje dışında 404).

### 4.4 Toolchain ve cihazlar (K1, K2)

- toolchain süreç ayarı (`toolchain_common/settings.py`) D olarak kalır; projeye özgü değerler **istek gövdesinde**: `/check`, `/run`, mobil/Windows koşu istekleri `proje` bloğu alır:
  `{"pid", "forge_path", "mirror_path", "remote_url", "base_url", "demo_api_url", "probe_user", "probe_password", "run_dealers", "e2e_root", "app": {"android": {...}, "ios": {...}, "windows": {...}}}` (paket yolu, `app_id`, aktivite, argüman, çalışma dizini). Blok yoksa toolchain bugünkü env değerleriyle çalışır (geriye uyum, toolchain ve core ayrı dağıtılabilir).
- Parola/token toolchain'e yalnız iç ağda ve `TP_TOOLCHAIN_TOKEN` ile korunan uca gider; test-runner loglarında maskelenir (mevcut `SECRET_ENV_NAME_RE` yerine bloktaki alan adları maskeleme listesine eklenir).
- Koşu kilidi (`/tmp/testingprobe-run.lock`) ve worker uzun şeridi **aynen** kalır → tüm projelerin ağır işleri tek sırada (K1). Koşu dizinleri `runs/<run_id>/` (UUID, global tekil) değişmez; artefakt bağlantısı veren uç, koşunun projesini bağlamla karşılaştırır.
- Cihaz havuzu (Mac Appium, `tp-windows` VM) D; app-mcp'nin "tek uygulama" kısıtı oturum başına `app` bloğuyla aşılır (Şerit 3, `toolchain/app-mcp`).

### 4.5 Demo/test ortamı ve test kullanıcıları

`TP_DEMO_WEB_URL`, `TP_AGENT_DEALER*`, `VERIFY_*`, `DEMOAPP_RO_DATABASE_URL`, testdata sorguları proje ayarı. RO DB'si tanımsız projede test verisi kataloğu ve canlı doğrulama "yapılandırılmamış" (409 `proje_ayari_eksik`) döner. Kod üretimi paket/dizin adları (`com/antreklabs/bayi/...`) proje ayarı; varsayılanları yalnız varsayılan proje için bugünkü değerler, diğer projelerde eksikse kod üretimi 409 `proje_ayari_eksik`.

---

## 5. Arka plan

### 5.1 Ortak kuyruk (K1)

- `enqueue(conn, tur, yuk, *, project_id=BAGLAM, ...)`: `BAGLAM` sentinel → `mevcut_pid()`; bağlam yoksa ve tür kurulum işi olarak kayıtlı değilse `ProjeBaglamiYok`. `job_handler(..., kurulum=True)` bayrağı NULL projeli işleri işaretler.
- `claim` değişmez (tek sıra, `ORDER BY run_after, olusturma`); `ClaimedJob.project_id` eklenir. Worker yürütücüsü işleyiciyi `proje_icinde(job.project_id, kaynak="is")` içinde çağırır (NULL ise bağlamsız). Böylece kullanıcı proje değiştirse de iş kendi projesinde sürer (K3).
- `idempotency_lock` anahtarı `f"{pid}:{key}"`; `ON CONFLICT (project_id, idempotency_key)`.
- `start_workflow` `workflow_instance.project_id`'yi bağlamdan yazar.
- `reap_stale`, `release_orphans`, `fail_workflows` proje-genel (`tum_projeler=True`, izinli liste).
- SSE olayları (`events/bus.py publish_tx`) yüke `project_id` ekler; dinleyici (`events/listener.py`) bağlantının projesine göre süzer.

### 5.2 Periyodik işler proje başına

- Proje listesi kaynağı: `tp_proje` tablosu (`aktif=true`). Doldurma: (a) açılışta D env `TP_HOME_PROJECTS` (virgüllü; `TP_HOME_PROJECT` her zaman dahil) → `kaynak='env'`; (b) bir kullanıcının `/v1/projects` yanıtındaki pid için `GET /v1/config/effective` 200 dönerse → `kaynak='kesif'`. Home `allowed_pids` dışındaki pid'i effective 403/404 ile reddettiğinden `allowed_pids` gerçek yetki kaynağı olarak kalır; TP listesi yalnız "hangi projeler için arka plan işi planlansın" sorusunu yanıtlar. Home'a `/v1/config/projects` (kurulumun pid listesi) eklenince (b) yerine o kullanılır (R2).
- `requirements.jira_tetik` (Jira tetik poller'ı), PO etiket sorgusu, `ci` gece koşusu (`plan_nightly`), PR senkronu, triage taraması, artefakt temizliği: açılış kancaları (`worker.acilis_kancalari`) her aktif proje için ayrı iş planlar; `yuk` ve idempotency anahtarı pid içerir (`nightly:<pid>:<tarih>`). Ayar okuması (`aralik_s`, `TP_CI_NIGHTLY_SAAT`) o projenin config'inden.
- Proje pasifleşince (`aktif=false`) kendini yeniden planlayan işler bir sonraki turda planlamayı bırakır.

### 5.3 Asistan

- Sohbet, mesaj, öneri geri bildirimi, güvenlik olayları ve `asistan_durum` proje kapsamlı; asistan araçları (`features/assistant/tools/*`) bağlamdaki projenin verisini okur (ORM filtresi + ham SQL kuralı). Bilgi paketi (`TP_BILGI_DIZIN`) ürün bilgisi olduğundan kurulum geneli.
- Asistan şeridi (`TP_WORKER_ASISTAN_SERIT`) ortak; hız kovaları §1.1 C.

---

## 6. Auth ve rol

### 6.1 A3'ün genellenmesi

- `aiprobe.proje_rolleri(uid, pid, *, taze=False) -> frozenset[str] | None` (bugünkü `home_projesi()` yerine açık `pid`); LKG önbelleği zaten `(uid, proje)` anahtarlı.
- `aiprobe.kullanici_projeleri(uid) -> list[ProjeOzeti]`: `/v1/projects?uid=` ∩ `tp_proje(aktif)`; `ProjeOzeti = {pid, kod, ad, org_ad, roller, ozellikler}`. Home ulaşılamazsa LKG (`PROJE_ROL_LKG_S`) → sonra boş liste (fail-closed).
- İstek başına yetki: `current_user` seçili projenin rollerini çözer; `Principal` alanları `project_id: str | None` ve `roller: frozenset[str]` ile genişler (`rol` geriye uyum için birincil rol olarak kalır). `yetki.izin(...)` `roller`'e bakar. **Seçili projede rol yoksa 403 `proje_rolu_yok`** (portal proje seçiciyi açar).
- Giriş (redeem): `project_id` devirde varsa ve kullanıcının projelerindeyse o; yoksa `app_user.secili_proje` geçerliyse o; yoksa listedeki ilk proje; liste boşsa giriş "projeniz yok" ekranına düşer (oturum açılır ama tüm uçlar 403).
- Yerel kip (`TP_AUTH_MODE=local`): tek proje `varsayilan_pid()`, roller `app_user.rol` — bugünkü davranış.
- MCP token (`api_token`) oluşturulduğu anda seçili projeye bağlanır; token'ın yetkisi o projedeki rollerle sınırlı (her kullanımda `proje_rolleri` kesişimi).

### 6.2 Uçlar (Şerit 2)

| Uç | Davranış |
|---|---|
| `GET /api/projeler` | `[ProjeOzeti]`, `secili: pid` |
| `PUT /api/proje` `{pid}` | Üyelik + `tp_proje.aktif` + o projede ≥1 TP rolü denetlenir; `oturum.project_id` ve `app_user.secili_proje` güncellenir; `'_kurulum'` zincirine `auth.proje_degisti {onceki, yeni}`; yanıt yeni `/auth/me`. CSRF korumalı (mevcut `api/csrf.py`). |
| `GET /auth/me` | `proje: {pid, kod, ad}`, `roller` (seçili projedeki), `projeler_sayisi` |

### 6.3 Portal (Şerit 6, `review-portal/src`)

- `components/ProjeSecici.tsx` (sağ üst, `Kabuk.tsx` başlığı): AI Probe ortak değiştiricisi (`AiprobeDegistirici.tsx` yanında paralelde ekleniyor) bir `aiprobe:project-change` olayı (`CustomEvent<{pid: string}>` `window` üzerinde) yayınlar; ince katman `lib/proje.ts`:
  - `projeyiDegistir(pid)` → `PUT /api/proje` → başarıda sorgu önbelleğini temizler, `X-TP-Proje` değerini günceller, mevcut rotayı yeni projede yeniden yükler (nesne ayrıntı sayfasındaysa liste sayfasına döner — id başka projede yok).
  - `window.addEventListener("aiprobe:project-change", ...)` aynı fonksiyonu çağırır; ortak değiştirici yoksa `ProjeSecici` kendi açılır listesini gösterir (tek proje varsa yalnız ad).
  - `api/http.ts` her isteğe `X-TP-Proje` ekler; 409 `proje_degisti` → `/auth/me`'yi yeniden okuyup sayfayı yeniler; 403 `proje_rolu_yok` → seçiciyi açan bilgi ekranı.
- `auth.tsx` bağlamına `proje` ve `roller` eklenir; rol tabanlı menü/izinler seçili projenin rolleriyle hesaplanır.

---

## 7. Paralel şeritler

Hedefli test komutları repo kökünden; DB gerektirenlerde `TP_TEST_REQUIRE_DB=1` (geçici test Postgres'i, mevcut conftest deseni).

### Şerit 0 — Proje çekirdeği (ÖNCE, küçük; ~1 oturum)

**Dosyalar (yalnız bunlar):** yeni `core/src/tp_core/proje/{__init__,baglam,orm,ayar,sayac,istemciler}.py`; `core/src/tp_core/models/base.py` (mixin); `core/src/tp_core/models/__init__.py` (`new_session` içinde `orm.kur`); `core/alembic/versions/0044_proje_kaydi.py`; `core/tests/unit/conftest.py` (fikstürler); yeni `core/tests/unit/platform/{test_proje_baglam,test_proje_kapsami}.py` ve `proje_istisna/serit{1..5}.txt` (başlangıç tabanı: bugünkü tüm ihlaller, yola göre şeride atanmış).

**Tam imzalar:**

```python
# tp_core/proje/baglam.py  (tp_core/proje/__init__.py hepsini yeniden dışa aktarır)
KURULUM: Final = "_kurulum"
Kaynak = Literal["oturum", "token", "is", "sistem", "cli", "test"]

@dataclass(frozen=True, slots=True)
class ProjeBaglami:
    pid: str
    kaynak: Kaynak

class ProjeBaglamiYok(RuntimeError): ...
class ProjeIhlali(RuntimeError): ...          # yanlış projeden satır / yanlış project_id ile yazma

def varsa() -> ProjeBaglami | None: ...
def mevcut() -> ProjeBaglami: ...             # yoksa ProjeBaglamiYok
def mevcut_pid() -> str: ...
def pid_param(**ek: Any) -> dict[str, Any]: ...   # {"pid": mevcut_pid(), **ek} — ham SQL için

@contextmanager
def proje_icinde(pid: str, *, kaynak: Kaynak = "sistem") -> Iterator[ProjeBaglami]: ...
def baglamla(fn: Callable[P, R]) -> Callable[P, R]: ...   # thread hedefi için copy_context sarmalayıcısı

def varsayilan_pid() -> str: ...              # TP_HOME_PROJECT, yoksa "varsayilan"
def kurulu_projeler(conn: Connection) -> list[str]: ...   # tp_proje WHERE aktif ORDER BY pid
def proje_kaydet(conn: Connection, pid: str, *, kod: str | None, ad: str | None,
                 kaynak: Literal["env", "kesif"]) -> bool: ...   # yeni ise True (idempotent)

# tp_core/models/base.py
class ProjeKapsamli:
    """Mixin: proje kapsamlı tablo. Sütun NOT NULL; INSERT'te bağlamdan dolar."""
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, default=lambda: mevcut_pid())

# tp_core/proje/orm.py
TUM_PROJELER: Final = "tum_projeler"          # .execution_options(tum_projeler=True)
def kur(session_cls: type[Session] | sessionmaker) -> None: ...   # idempotent
def kapsamli_tablolar() -> frozenset[str]: ...                    # Base.metadata'dan, mixin'e göre

# tp_core/proje/ayar.py   (Şerit 0: env'e düşen gerçek davranış; Şerit 2 Home kaynağını bağlar)
PROJE_ANAHTARLARI: frozenset[str]
def ayar(ad: str, varsayilan: str | None = None, *, pid: str | None = None) -> str | None: ...
def ayar_bool(ad: str, varsayilan: bool = False, *, pid: str | None = None) -> bool: ...
def ayar_int(ad: str, varsayilan: int, *, pid: str | None = None) -> int: ...
def ayar_float(ad: str, varsayilan: float, *, pid: str | None = None) -> float: ...
def sir(ad: str, *, pid: str | None = None) -> str | None: ...
def ozellik_acik(ad: str, *, pid: str | None = None) -> bool: ...
def surum(pid: str | None = None) -> str: ...
def kaynak_bagla(cozucu: Callable[[str], Mapping[str, str] | None],
                 surumcu: Callable[[str], str]) -> None: ...   # Şerit 2 çağırır

# tp_core/proje/sayac.py
def sonraki(conn: Connection, ad: str, project_id: str | None = None) -> int: ...

# tp_core/proje/istemciler.py  (Şerit 0: bugünkü tekillere yönlendirir; Şerit 3 değiştirir)
def jira() -> JiraClient: ...
def xray() -> XrayClient | None: ...
def forge() -> Forge: ...
def ci() -> GitHubActionsClient | None: ...
def toolchain_proje_blogu() -> dict[str, Any]: ...
def sifirla(pid: str | None = None) -> None: ...
```

Test fikstürleri (`core/tests/unit/conftest.py`): `proje` (varsayılan bağlam `"test-a"`), `iki_proje` (`("test-a", "test-b")`, tohum), `sql_denetimi` (autouse, DB testlerinde), `proje_ayar(**degerler)` (bağlamdaki projeye ayar enjekte eder).

Kabul: `cd core && uv run pytest tests/unit/platform/test_proje_baglam.py tests/unit/platform/test_proje_kapsami.py -q` (statik test taban dosyalarıyla yeşil); `TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/platform/test_migrations.py -q`.

### Şerit 1 — Şema, denetim zinciri, kuyruk

**Dosyalar:** `core/src/tp_core/models/*.py` (mixin uygulama, kısıt/index), `core/alembic/versions/0045_proje_kapsami.py`, `core/src/tp_core/audit/*`, `core/src/tp_core/workflow/{jobs,service}.py`, `core/src/tp_core/worker/*`, `core/src/tp_core/events/*`, `Makefile` `export-audit` hedefi, `core/tests/unit/platform/{test_migrations,test_audit,test_jobs,test_worker_seritler,test_events}.py`, `proje_istisna/serit1.txt`.
**Sözleşme:** §1 tümü; `append_audit(conn, aktor, eylem, nesne, ozet, *, project_id: str | None = None) -> int`; `verify_chain(conn, project_id: str, batch=1000)`; `chain_tip(conn, project_id: str)`; `enqueue(..., project_id: str | None | _Baglam = BAGLAM)`; `ClaimedJob.project_id: str | None`; `job_handler(..., kurulum: bool = False)`; olay yükünde `project_id`.
**Test:** `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/platform/test_migrations.py tests/unit/platform/test_audit.py tests/unit/platform/test_jobs.py tests/unit/platform/test_worker_seritler.py tests/unit/platform/test_events.py -q`.

### Şerit 2 — Config, auth/rol, API çekirdeği, MCP

**Dosyalar:** `core/src/tp_core/home_config/*`, `core/src/tp_core/proje/ayar.py` (yalnız `kaynak_bagla` sonrası iç doldurma — imza değişmez), `core/src/tp_core/config.py`, `core/src/tp_core/gateway/config.py`, `core/src/tp_core/auth/*`, `core/src/tp_core/api/{deps,csrf,main,kimlik_kipi}.py`, `core/src/tp_core/api/routers/{auth,aiprobe}.py` + yeni `api/routers/proje.py`, `core/src/tp_core/mcp_server/*`, testler `core/tests/unit/home_config/*`, `core/tests/unit/platform/{test_aiprobe_sso,test_yetki,test_api,test_guvenlik}.py`, yeni `test_proje_secimi.py`.
**Sözleşme:** §3, §6.1–6.2; `Principal(project_id: str | None = None, roller: frozenset[str] = frozenset())`; `aiprobe.proje_rolleri(uid, pid, *, taze=False)`; `aiprobe.kullanici_projeleri(uid) -> list[ProjeOzeti]`; `baglanti.token_al(tur, pid: str | None = None)`; `durum.etkin(pid: str | None = None)`, `durum.ozellik_acik(ad, pid=None)`; hata kodları `proje_degisti` (409), `proje_rolu_yok` (403), `proje_ayari_eksik` (409; `api/errors.py`'ye kayıt).
**Test:** `cd core && uv run pytest tests/unit/home_config -q && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/platform/test_aiprobe_sso.py tests/unit/platform/test_yetki.py tests/unit/platform/test_proje_secimi.py tests/unit/platform/test_api.py -q`.

### Şerit 3 — Entegrasyonlar ve toolchain

**Dosyalar:** `core/src/tp_core/integrations/**` (jira, jira_notify, jira_seed, forge*, agent_probe), yeni `integrations/forge_yollari.py`, `core/src/tp_core/proje/istemciler.py` (iç uygulama), `core/src/tp_core/features/ci/clients.py` (yalnız istemci sınıfları; servis Şerit 5), `toolchain/**` (`toolchain_common/settings.py` istek bloğu birleştirme, `runner/`, `worker/`, `app-mcp/`), `docker-compose.yml`/`deploy/` forge birim yolları, testler `core/tests/unit/integrations/*`, `toolchain/tests/*`.
**Sözleşme:** §4; toolchain istek gövdesi `proje` bloğu (§4.4 alan adları bağlayıcı); `forge_yollari.depo_yolu(pid) -> Path`, `pr_dizini(pid) -> Path`, `ayna_yolu(pid) -> Path` (varsayılan proje = eski yollar).
**Test:** `cd core && uv run pytest tests/unit/integrations -q && cd ../toolchain && uv run pytest tests -q -k "proje or settings or run"`.

### Şerit 4 — Özellikler A (gereksinim → case → kalite → otomasyon, asistan)

**Dosyalar:** `core/src/tp_core/features/{requirements,cases,tasarim_modeli,karar_tablosu,metamorfik,oracle,testveri,otomasyon,assistant,publish}/**`, `core/src/tp_core/gateway/**` (bütçe/`ai_call` yazımı, kural önbellekleri, `rules` proje çözümü), `core/src/tp_core/seed.py`, `rules/projeler/.gitkeep` (proje başına kural dizini kökü), testler `core/tests/unit/features/{requirements,cases,karar_tablosu,metamorfik,oracle,testveri,otomasyon,assistant,publish}/*`, `core/tests/unit/gateway/*`, `proje_istisna/serit4.txt`.
**İş:** ham SQL'e `project_id = :pid`, env okumalarını `ayar()`'a, modül tekillerini `proje.istemciler`'e, `jira_tetik`/PO poller'ı proje başına planlama (§5.2), asistan proje kapsamı (§5.3), izolasyon testi parametreleri.
**Test:** `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/requirements tests/unit/features/cases tests/unit/features/otomasyon tests/unit/features/assistant tests/unit/features/testveri tests/unit/features/oracle tests/unit/gateway tests/unit/platform/test_proje_izolasyonu.py -q`.

### Şerit 5 — Özellikler B (kod üretimi → CI → triage → hata, kontrol kulesi, demo, agent probe)

**Dosyalar:** `core/src/tp_core/features/{codegen,ci,triage,repair,bugs,hata_kosusu,control_tower,demo,agent_probe}/**` (ci/clients.py hariç istemci sınıfları — Şerit 3), testler `core/tests/unit/features/{codegen,ci,triage,repair,bugs,hata_kosusu,control_tower,demo,agent_probe,kalite_e2e}/*`, `proje_istisna/serit5.txt`.
**İş:** ham SQL, `ayar()`, PR numarası `proje_sayac('pr')`, talep no `proje_sayac('talep')`, gece koşusu/PR senkronu/triage taraması proje başına, kod üretimi paket adları proje ayarı, demo uçları varsayılan projeye kilitli, artefakt bağlantısı proje denetimi, `toolchain_proje_blogu()` kullanımı.
**Test:** `cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/codegen tests/unit/features/ci tests/unit/features/triage tests/unit/features/bugs tests/unit/features/control_tower tests/unit/features/demo tests/unit/features/agent_probe tests/unit/platform/test_proje_izolasyonu.py -q`.

### Şerit 6 — Portal proje seçici

**Dosyalar:** `review-portal/src/components/{ProjeSecici.tsx,projeSecici.test.tsx,Kabuk.tsx}`, `review-portal/src/lib/proje.ts`, `review-portal/src/api/{http.ts,http.test.ts,types.ts,client.ts}`, `review-portal/src/auth.tsx`, `review-portal/src/api/mock/*` (mock'a `/api/projeler`, `PUT /api/proje`). `AiprobeDegistirici.tsx`'e dokunmaz (paralel ortak iş).
**Sözleşme:** §6.3; olay adı `aiprobe:project-change`, detay `{pid: string}`; başlık `X-TP-Proje`; hata kodları Şerit 2 ile aynı.
**Test:** `cd review-portal && npx vitest run src/components/projeSecici.test.tsx src/api/http.test.ts && npx tsc -p tsconfig.json --noEmit`.

### Birleştirme sırası

1. **Şerit 0** (diğerleri onun dalından başlar).
2. **Şerit 1** (şema; 4/5'in DB testleri buna ihtiyaç duyar — 4/5 kodu paralel yazar, testleri 1 birleşince koşar).
3. **Şerit 2** ve **Şerit 3** (birbirinden bağımsız; ikisi de 0'ın imzalarına uyar).
4. **Şerit 4** ve **Şerit 5** (1, 2, 3'ün üstüne yeniden tabanlanır; istisna tabanları ayrı dosyalarda olduğundan birbirleriyle çakışmaz).
5. **Şerit 6** (2'nin uçları birleştikten sonra; mock ile önceden geliştirilir).
6. Son: `proje_istisna/*.txt` yalnız gerekçeli kalıcı istisnalar; tam paket (`make` hedefi/CI) + izolasyon testi + rol review döngüsü + Chrome for Testing ekran testi (proje değiştirme, iki sekme 409, rol yok ekranı).

Çakışma kuralları: `models/` yalnız Şerit 1; `proje/` yalnız Şerit 0 (Şerit 2 `ayar.py` iç gövdesi, Şerit 3 `istemciler.py` iç gövdesi — imzalar donuk); `api/errors.py` hata kodları Şerit 2; migrasyon numaraları 0044 (Ş0), 0045 (Ş1); başka şerit migrasyon yazmaz — ihtiyaç doğarsa 0046+ Şerit 1 sahibiyle sıralanır.

---

## 8. Riskler, kapsam dışı, canlı göç

### 8.1 Riskler ve azaltma

| Risk | Azaltma |
|---|---|
| Atlanan sorgu → projeler arası veri sızıntısı | ORM otomatik filtre + `load` koruyucusu + statik AST testi + dinamik SQL yakalama + uç keşifli izolasyon testi (§2.4); RLS R2 |
| Bağlamsız iş parçacığı / geç planlanan iş yanlış projede çalışır | Bağlam yoksa hata (varsayılana düşmez); `baglamla()` sarmalayıcı + statik test; iş satırı `project_id` |
| Çok sekmede yanlış projeye yazma | `X-TP-Proje` + 409 `proje_degisti` (§2.2) |
| Ortak kuyrukta bir projenin uzun koşuları diğerini aç bırakır | K1 gereği kabul; Kontrol Kulesi'nde kuyruk görünümü proje adıyla; adil zamanlama R2 |
| Home'a proje sayısı × 60 sn yük; Home kesintisinde tüm projeler | ETag/304; proje başına LKG; kesintide son bilinen config + fail-closed özellik kuralı (R1 ile aynı) |
| Bayi Portalı'na özgü kural/kod sabitlerinin yeni projeye sızması | Varsayılan proje dışında boş kural, eksik ayarda 409 `proje_ayari_eksik` (§3.3, §4.5) |
| `TP_HOME_PROJECT` yanlışken migrasyon tüm veriyi yanlış pid'le damgalar | Migrasyon pid'i Home `/v1/projects` çıktısıyla elle doğrulama adımı (§8.3 adım 2) + boşsa hata |
| Host betikleri (demo-web-sync, forge-init) tek proje | Varsayılan projeye kilitli; diğer projelerde demo uçları 404 |
| Toolchain'e istek gövdesiyle parola gitmesi | İç ağ + token korumalı uç + maskeleme; R2'de toolchain'in Secret Manager'dan çözmesi |

### 8.2 Kapsam dışı (R2)

- Postgres RLS ile derinlemesine savunma; bileşik (project_id, id) FK'ler.
- Farklı organizasyonların projelerini aynı TP'de barındırma (hücre modeli; `AIPROBE_ALLOWED_ORGS` ve A sınıfı değerler tek org varsayar).
- Proje başına LLM bütçesi/BYOK (bugün `TP_DAILY_BUDGET_USD` kurulum toplamı; `ai_call.project_id` ile proje başına raporlama R1'de var).
- Home `/v1/config/projects` (kurulum pid listesi) — gelince `TP_HOME_PROJECTS` + keşif kaldırılır.
- Kural dosyalarının (`hata-katalogu`, `pii-allowlist`, `baz-degerler`) Home'dan yönetimi.
- Proje başına cihaz havuzu, adil kuyruk zamanlaması, proje başına eşzamanlılık.
- Proje verisini dışa aktarma/silme/taşıma; eski forge yollarının `/forge/<pid>/` düzenine taşınması.
- Demo özelliklerinin (break/reset/demo-web) çok projeli hale getirilmesi.

### 8.3 Canlı göç adımları

Dış sistem yazımları (Home Firestore, GCP) her biri için **ayrı kullanıcı onayı** gerektirir.

1. **Hazırlık (salt okuma):** Home'da Bayi Portalı pid'i doğrulanır (`/v1/projects?uid=<operatör>` çıktısı ile VM'deki `TP_HOME_PROJECT` eşit). Yeni projeler Home'da oluşturulmuş ve TP rolleri atanmış olmalı.
2. **Yedek:** `pg_dump` (mevcut migrasyon öncesi otomatik yedek deseni) + `make export-audit` (tek zincir son hali).
3. **Dağıtım:** yeni imajlar; `migrate` 0044 → 0045 (`TP_HOME_PROJECT` env'de dolu; boşsa durur). Kesinti: hızlı varsayılan sayesinde saniyeler; kısıt yeniden kurma tablolar küçük olduğundan dakika altı.
4. **Doğrulama:** her kapsamlı tabloda `count(DISTINCT project_id) = 1` ve değer = Bayi pid; `verify_chain(<Bayi pid>)` geçerli ve eski dışa aktarımla aynı uç hash; `proje_sayac` tohumları; portalda Bayi Portalı verisi aynen görünür; arka plan işleri (`jira_tetik`, gece koşusu) yeni pid'li idempotency anahtarlarıyla planlanmış.
5. **Home güncellemesi (onaylı dış yazma):** `product_installs/tp.allowed_pids` = `[<Bayi pid>, <yeni pid>, …]`; TP'de `TP_HOME_PROJECTS` aynı listeye çekilir (D; compose env + yeniden başlatma) — sıra: önce Home, sonra TP (TP listedeki pid için effective 403 alırsa projeyi pasif işaretler, veri yazmaz).
6. **Yeni proje duman testi:** proje seçici → yeni proje boş listeler; Jira/GitHub bağlantı testi (Home); bir gereksinim içe aktarımı; varsayılan projeye dönüş; iki sekme 409; rol olmayan kullanıcı 403 `proje_rolu_yok`.
7. **Geri dönüş:** 6'dan önce sorun → Home `allowed_pids` eski haline (onaylı), TP önceki release; 0045 downgrade yalnız tek projeli veriyle çalışır, yeni projede veri oluşmuşsa ileri-düzeltme.

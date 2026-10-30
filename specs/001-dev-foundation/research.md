# Research: Geliştirme ve Demo Ortamı Temeli

Tüm teknik bağlam maddeleri çözüldü; açık "NEEDS CLARIFICATION" yok.

## R1. İş akışı motoru
- **Decision:** Temporal yok. Postgres tablosunda durum makinesi + `SELECT … FOR UPDATE SKIP LOCKED` ile çalışan basit Python worker (`core-worker`). F0'da yalnızca iskelet ve sağlık kontrolü.
- **Rationale:** Karar §0-20/§0-25; tek veritabanı, daha az servis, daha düşük bellek; onay kapısı kuralları değişmez.
- **Alternatives:** Temporal `server start-dev` (ürün fazına); Celery/Redis (ek servis, gereksiz).

## R2. Python bağımlılık yönetimi
- **Decision:** `uv` + `uv.lock`; imajda `uv sync --frozen --no-dev`.
- **Rationale:** Hızlı, kilitli, tekrarlanabilir; ekipte zaten kurulu.
- **Alternatives:** pip-tools, Poetry.

## R3. Compose başlatma ve sağlık
- **Decision:** Her servis için `healthcheck`; `depends_on: condition: service_healthy`; tek seferlik `migrate` servisi `service_completed_successfully`; `make up` = `docker compose up -d --wait --wait-timeout 300`.
- **Rationale:** FR-002/FR-003; `--wait` sağlıksız serviste hata kodu döner (edge case: süre aşımı).
- **Alternatives:** Kendi bekleme döngüsü (gereksiz).

## R4. Playwright ve MCP sürüm birliği
- **Decision:** `toolchain/Dockerfile` `FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble` (build arg `.playwright-version`'dan, şu an 1.64.1). Playwright MCP ayrı imajdan değil, aynı imajda `npx @playwright/mcp@0.0.83` (lockfile'lı küçük paket) ile çalışır: `--headless --browser chromium --host 0.0.0.0 --port 8931 --allowed-hosts '*' --allowed-origins http://demo-app-web:8080 --isolated --caps=testing --output-dir /tmp/playwright-mcp`. MCP 0.0.83 alfa bir playwright-core (Chromium r1247) getirdiğinden `package.json` `overrides` ile 1.64.1'e sabitlenir; build, sürüm `.playwright-version`'dan farklıysa başarısız olur.
- **Not:** MCP, vision olmadan da `browser_evaluate`/`browser_run_code_unsafe` araçlarını sunar; `--allowed-origins` güvenlik sınırı değildir, asıl koruma R5 ağ izolasyonudur. Araç allowlist'i F2a'da çekirdek tarafındaki MCP istemcisinde uygulanır.
- **Rationale:** FR-012 tek sürüm kaynağı; tarayıcılar tek kez indirilir (disk); resmi MCP imajının Playwright sürümü bizimkinden kopabilir.
- **Alternatives:** `mcr.microsoft.com/playwright/mcp` imajı (sürüm ayrışması riski).

## R5. Ağ izolasyonu
- **Decision:** Dört ağ: `core-net` (normal; postgres, migrate, core-api, core-worker, toolchain-worker, playwright-mcp, review-portal, demo-app-web), `data-net` (`internal: true`; postgres, demo-app-api), `demo-net` (`internal: true`; demo-app-api, demo-app-web, playwright-mcp, test-runner), `runner-net` (`internal: true`; toolchain-worker, test-runner). Host'a açılan portlar yalnızca `127.0.0.1:` önekiyle.
- **Rationale:** FR-006/FR-007; `internal: true` ağlar internete çıkamaz. test-runner yalnızca demo-net + runner-net'te olduğundan postgres'i, core-api'yi ve interneti DNS düzeyinde bile göremez. Postgres demo-net'te değil; demo-app-api veritabanına ayrı `data-net` üzerinden erişir. demo-app-web, sunucunun tarayıcısından açılabilmesi için core-net'te de bulunur (internal ağlarda port yayınlanamaz).
- **Alternatives:** demo-app için ayrı Postgres konteyneri (+~100 MB bellek; gerekirse F1'de); `pg_hba.conf` ile kısıtlama (ağ ayrımı daha basit ve test edilebilir).

## R6. Denetim kaydı ve rol modeli
- **Decision:** Roller: `tp_owner` (migrasyon, şema sahibi), `tp_app` (uygulama; `audit_event` üzerinde yalnızca INSERT/SELECT, diğer tablolarda DML). Migrasyon `REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM tp_app`.
- **Rationale:** FR-008, Constitution VIII.
- **Alternatives:** Trigger ile engelleme (rol modeli daha basit ve test edilebilir).

## R7. Sıfırlama ve dışa aktarım
- **Decision:** `make reset`: (1) `export-audit.sh` → `exports/audit-<ts>.jsonl` + `.sha256`; başarısızsa çık (silme yok); (2) `docker compose down` + yalnızca `tp_pgdata` volume'ünü sil; (3) `make up`. `make seed` ayrı ve idempotent.
- **Rationale:** FR-009, US2; yarıda kesilirse tekrar çalıştırmak güvenli (dışa aktarım her zaman önce).
- **Alternatives:** İmza (karar §0-23 ile ürün fazına).

## R8. Deterministik seed
- **Decision:** `uuid5(NAMESPACE_TP, "<tür>:<anahtar>")`; seed kullanıcıları `analist`, `muhendis`, `sunucu`, `po`, `testci`; `INSERT … ON CONFLICT DO NOTHING`.
- **Rationale:** FR-010, Constitution XI; tekrarlanan seed aynı kimlikleri üretir.

## R9. Önkoşul kontrolü
- **Decision:** `preflight.sh`: `docker info` çalışıyor mu; `df` ile ≥ 30 GB boş; `docker info` MemTotal ≥ 8 GB; `.env` var ve zorunlu anahtarlar dolu (contracts/env.md); port çakışması `lsof -iTCP:<port> -sTCP:LISTEN` ile (çakışan süreç adıyla bildirilir).
- **Rationale:** FR-004 ve edge case'ler.

## R10. Güvenlik kontrolleri
- **Decision:** `security-check.sh`:
  1. `docker compose ps --format json` ile tüm yayınlanan portların `127.0.0.1` olduğu;
  2. `docker compose exec test-runner` içinden `postgres:5432`, `core-api:8000` ve `https://example.com` bağlantılarının başarısız olduğu;
  3. `tp_app` rolüyle `UPDATE/DELETE audit_event` denemesinin `permission denied` verdiği;
  4. `gitleaks detect` (Docker imajıyla, sabit sürüm) ile depoda sır bulunmadığı.
  Her kontrol PASS/FAIL; biri bile FAIL ise çıkış kodu ≠ 0.
- **Rationale:** FR-015, SC-004.
- **Alternatives:** LAN IP'sinden port taraması (ağdaki başka makine gerektirir; bind adresi kontrolü eşdeğer ve deterministik).

## R11. Portal ve demo-app iskeletleri
- **Decision:** F0'da review-portal ve demo-app-web: Vite ile build edilmiş tek sayfa + `/health` (nginx `return 200`); demo-app-api ve core-api: FastAPI `/health` (DB bağlantısını da kontrol eder).
- **Rationale:** FR-001 "iskelet"; iş mantığı F1–F3.

## R12. Kaynak sınırları
- **Decision:** `deploy.resources.limits.memory`: postgres 1g, core-api 512m, core-worker 512m, toolchain-worker 2g, test-runner 3g, playwright-mcp 2g, review-portal 128m, demo-app-api 256m, demo-app-web 128m (toplam ≤ ~9,6 GB); playwright içerenlerde `shm_size: 1gb`.
- **Rationale:** SC-006.

## R13. Docker Desktop alternatifi
- **Decision:** Varsayılan Docker Desktop; Colima ile uyumluluk için compose'da Docker Desktop'a özgü özellik kullanılmaz (`host.docker.internal` yok).

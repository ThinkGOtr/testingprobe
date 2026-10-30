# Tasks: Geliştirme ve Demo Ortamı Temeli

**Input**: plan.md, research.md, data-model.md, contracts/, quickstart.md

**Paralellik**: Faz 1 tamamlandıktan sonra Faz 2'deki altı şerit (A–F) **aynı anda** geliştirilir.
Her şerit yalnızca kendi dizinine yazar; ortak sözleşme (Faz 1 dosyaları) şeritler tarafından değiştirilmez.
`[P]` = paralel çalışabilir. `[USx]` = ilgili kullanıcı hikâyesi.

## Faz 1: Ortak sözleşme (seri, şeritlerden önce)

- [x] T001 `docker-compose.yml`: servis adları, imajlar (digest), ağlar, portlar, sağlık kontrolleri, bellek sınırları
- [x] T002 `.env.example` (contracts/env.md ile uyumlu)
- [x] T003 `.playwright-version` = 1.64.1
- [x] T004 `.gitignore`: `exports/`

## Faz 2: Paralel şeritler

### Şerit A — `core/`, `infra/postgres/` (US1, US2, US3)
- [x] T010 [P] [US1] `infra/postgres/init/01-init.sh`: roller (`tp_owner`, `tp_app`, `demoapp_owner`, `demoapp`) ve veritabanları (`tp`, `demoapp`)
- [x] T011 [P] [US1] `core/pyproject.toml` + `uv.lock`, `core/Dockerfile` (python + uv digest'li, `uv sync --frozen --no-dev`)
- [x] T012 [P] [US3] Alembic: `app_user`, `audit_event`, `job`; `tp_app` yetkileri, `audit_event` üzerinde yalnızca INSERT/SELECT
- [x] T013 [P] [US1] `tp_core.api.main` → `GET /health` (contracts/health.md)
- [x] T014 [P] [US1] `tp_core.worker` iskeleti (`SKIP LOCKED`, `noop` işi) + `tp_core.worker.healthcheck`
- [x] T015 [P] [US2] `tp_core.seed`: 5 kullanıcı, uuid5, argon2, idempotent, `seed.applied` denetim satırı, çıktı `seed: 5 kullanıcı (yeni: N)`
- [x] T016 [P] Birim testler (`core/tests/unit`)

### Şerit B — `toolchain/` (US1)
- [x] T020 [P] [US1] `toolchain/Dockerfile`: `mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble@digest`, uv, komutlar `toolchain-worker`, `test-runner`, `playwright-mcp`
- [x] T021 [P] [US1] toolchain-worker `/health` :8100 (node, playwright sürümü kontrolü)
- [x] T022 [P] [US1] test-runner `/health` :8200
- [x] T023 [P] [US1] Playwright MCP 0.0.83 (lockfile), :8931, `--isolated --caps=testing --allowed-origins`

### Şerit C — `review-portal/` (US1)
- [x] T030 [P] [US1] React + Vite + TS iskeleti, lockfile, nginx :8080, `/health`, `/api/` → core-api proxy

### Şerit D — `demo-app/` (US1)
- [x] T040 [P] [US1] `demo-app/api`: FastAPI `/health` (demoapp DB kontrolü), Dockerfile
- [x] T041 [P] [US1] `demo-app/web`: React + Vite iskeleti, nginx :8080, `/health`, `/api/` → demo-app-api proxy
- [x] T042 [P] `demo-app/e2e`: Playwright projesi iskeleti (`pages/`, `tests/`), `@playwright/test` 1.64.1

### Şerit E — `Makefile`, `scripts/` (US1, US2, US3)
- [x] T050 [P] [US1] `Makefile`: env, up, status, seed, reset, export-audit, security-check, prune, logs, down (contracts/make-targets.md)
- [x] T051 [P] [US1] `scripts/preflight.sh`, `scripts/status.sh`
- [x] T052 [P] [US2] `scripts/export-audit.sh`, reset akışı
- [x] T053 [P] [US3] `scripts/security-check.sh` (R10, 4 kontrol)

### Şerit F — `README.md`, `rules/`, `docs/ONBOARDING.md` (US4)
- [x] T060 [P] [US4] README: amaç, mimari özet, constitution ve teknik tasarım bağlantıları
- [x] T061 [P] [US4] Onboarding rehberi (quickstart tabanlı), sorun giderme
- [x] T062 [P] `rules/README.md`

## Faz 3: Entegrasyon ve doğrulama (seri)

- [x] T070 `make env && make up`: tüm servisler sağlıklı (SC-001)
- [x] T071 quickstart.md 2–6 adımları; `make security-check` 4/4 (SC-004)
- [x] T072 `make reset && make seed` ×3, süre < 2 dk (SC-003); bellek ≤ 10 GB (SC-006)
- [x] T073 Commit

# AI Testing Probe — yerel geliştirme ve demo ortamı (F0)
# Sözleşme: specs/001-dev-foundation/contracts/make-targets.md
# Tüm hedefler repo kökünden çalışır; `make help` hedefleri listeler.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Tek sürüm kaynağı: docker-compose.yml `${PLAYWRIGHT_VERSION:?}` ister
export PLAYWRIGHT_VERSION := $(strip $(shell cat .playwright-version 2>/dev/null))

S ?=

.PHONY: help env up status seed reset jira-seed forge-init break demo-baseline export-audit security-check e2e-smoke demo-check prune logs down

help: ## Hedefleri listeler
	@echo "Kullanım: make <hedef>"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{ printf "  %-16s %s\n", $$1, $$2 }'

env: ## .env'i üretir, boş F0 parolalarını rastgele doldurur (var olanlara dokunmaz)
	@scripts/env.sh

up: ## Önkoşul kontrolü + tüm servisleri sağlıklı başlatır (idempotent)
	@scripts/up.sh

status: ## Servis / durum / sağlık / yerel adres tablosu
	@scripts/status.sh

seed: ## Deterministik başlangıç verisi (tekrar çalıştırmak güvenli)
	@scripts/seed.sh

reset: ## Denetim kaydını dışa aktarır, çekirdek veriyi siler, yeniden başlatır
	@scripts/reset.sh

jira-seed: ## Gerçek Jira'yı demo başlangıcına döndürür (önce plan; uygulamak için: make jira-seed ONAY=1)
	@docker compose exec -T core-worker python -m tp_core.integrations.jira_seed $(if $(ONAY),--onay,)

forge-init: ## Yerel forge deposunu hazırlar (varsa dokunmaz; yeniden kurmak için: make forge-init F=--force)
	@scripts/forge-init.sh $(F)

break: ## Demo locator kırılması: demo/break-locator PR'ı demo-admin bypass'ıyla merge + demo-app-web yeniden derlenir
	@scripts/forge-init.sh break

demo-baseline: ## Forge main → demo-baseline + demo-app-web yeniden derlenir (PR kaydı korunur)
	@scripts/forge-init.sh baseline

export-audit: ## Denetim kaydını exports/audit-*.jsonl + .sha256 olarak dışa aktarır
	@scripts/export-audit.sh

security-check: ## 10 güvenlik kontrolü (port, izolasyon, denetim rolü, sır, demoapp_ro, model anahtarı, MCP ağı, yazma kimlikleri, merge kapısı, CI imajında ajan yok)
	@scripts/security-check.sh

e2e-smoke: ## demo-app e2e'yi test-runner içinden compose uygulamasına koşturur (E2E_BREAK_VERIFY=1: kırarak doğrula)
	@scripts/e2e-smoke.sh

demo-check: ## Demo-B ön kontrolü: REPLAY golden'larında defect adayı anı hazır mı (STORY=TPD-1) + REPLAY ref çözümü (RUNS=5)
	@docker compose exec -T core-worker python -m tp_core.gateway.demo_check --story $(or $(STORY),TPD-1)
	@docker compose exec -T core-worker python -m tp_core.gateway.replay_check --runs $(or $(RUNS),5)

prune: ## Kullanılmayan (dangling) imajları ve build önbelleğini temizler; volume'lere dokunmaz
	@echo "İmajlar:";        docker image prune -f | tail -n 1
	@echo "Build önbelleği:"; docker builder prune -f | tail -n 1

logs: ## Logları izler (tek servis için: make logs S=core-api)
	@docker compose logs -f --tail 100 $(S)

down: ## Servisleri durdurur (veri korunur)
	@docker compose down

# AI Testing Probe — yerel geliştirme ve demo ortamı (F0)
# Sözleşme: specs/001-dev-foundation/contracts/make-targets.md
# Tüm hedefler repo kökünden çalışır; `make help` hedefleri listeler.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Tek sürüm kaynağı: docker-compose.yml `${PLAYWRIGHT_VERSION:?}` ister
export PLAYWRIGHT_VERSION := $(strip $(shell cat .playwright-version 2>/dev/null))

S ?=

.PHONY: help env up status seed reset export-audit security-check prune logs down

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

export-audit: ## Denetim kaydını exports/audit-*.jsonl + .sha256 olarak dışa aktarır
	@scripts/export-audit.sh

security-check: ## 4 güvenlik kontrolü (port, izolasyon, denetim rolü, sır taraması)
	@scripts/security-check.sh

prune: ## Kullanılmayan (dangling) imajları ve build önbelleğini temizler; volume'lere dokunmaz
	@echo "İmajlar:";        docker image prune -f | tail -n 1
	@echo "Build önbelleği:"; docker builder prune -f | tail -n 1

logs: ## Logları izler (tek servis için: make logs S=core-api)
	@docker compose logs -f --tail 100 $(S)

down: ## Servisleri durdurur (veri korunur)
	@docker compose down

# AI Testing Probe — yerel geliştirme ve demo ortamı (F0)
# Sözleşme: specs/001-dev-foundation/contracts/make-targets.md
# Tüm hedefler repo kökünden çalışır; `make help` hedefleri listeler.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Tek sürüm kaynağı: docker-compose.yml `${PLAYWRIGHT_VERSION:?}` ister
export PLAYWRIGHT_VERSION := $(strip $(shell cat .playwright-version 2>/dev/null))

S ?=

.PHONY: help env up status seed reset jira-seed forge-init break demo-break demo-reset demo-web-sync locator-break-verify demo-baseline export-audit security-check e2e-smoke demo-check demo-prova prova-temizle eval-live prune logs down

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

jira-seed: ## Gerçek Jira'yı demo başlangıcına döndürür (önce plan; uygula: ONAY=1; koşu kayıtlarını sil: SIL=1 — make reset siler)
	@docker compose exec -T core-worker python -m tp_core.integrations.jira_seed $(if $(ONAY),--onay,) $(if $(SIL),--sil,)

forge-init: ## Yerel forge deposunu hazırlar (varsa dokunmaz; yeniden kurmak için: make forge-init F=--force)
	@scripts/forge-init.sh $(F)

break: ## Demo locator kırılması: yeşil temel koşu ön denetimi + demo/break-locator demo-admin bypass merge + demo-app-web (Z=1: denetimi atla)
	@scripts/demo-break.sh --make $(if $(Z),--zorla,)

demo-break: ## Sunucu düğmesinin eşi: POST /demo/break-locator (sunucu, denetimli) + demo-app-web eşitleme
	@scripts/demo-break.sh

demo-reset: ## Sunucu sıfırlaması: POST /demo/reset + demo-app-web eşitleme + AI Bug temizliği (jira-sim sıfırlanmaz; tam: make reset)
	@scripts/demo-reset.sh

demo-web-sync: ## core'un istediği forge commit'inden demo-app-web'i derler (A=--watch: sunum boyunca izle)
	@scripts/demo-web-sync.sh $(A)

locator-break-verify: ## Çevrimdışı ön kontrol: kırılma → yalnızca add-to-cart locator hatası → testId onarımı → yeşil
	@bash demo-app/ci/locator-break-verify.sh

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

demo-prova: ## Tam demo provası: make reset → 14 adım + locator kırma/onarım, strict REPLAY (RUNS=n, varsayılan 1; §13 için RUNS=3; UI=1: arayüzden; UITUR=1: salt okuma arayüz turu + video; KIRMA=1: kırma taslağını yayınla; SAKLA=n: son n rapor)
	@scripts/demo-prova.sh --runs $(or $(RUNS),1) $(if $(UI),--ui,) $(if $(UITUR),--ui-tur,) $(if $(KIRMA),--kirma-yayinla,) $(if $(SAKLA),--sakla $(SAKLA),)

prova-temizle: ## Eski prova raporlarını temizle (N=10: son N koşu klasörü kalır)
	@scripts/demo-prova.sh --temizle $(or $(N),10)

eval-live: ## Prompt değerlendirme setini CANLI modelle koşturur, sert bütçe TP_EVAL_BUDGET_USD (5) (A='--ping' | '--dry-run' | '--bundle triage --update-status' | '--record')
	@scripts/eval-live.sh $(A)

prune: ## Kullanılmayan (dangling) imajları ve build önbelleğini temizler; volume'lere dokunmaz
	@echo "İmajlar:";        docker image prune -f | tail -n 1
	@echo "Build önbelleği:"; docker builder prune -f | tail -n 1

logs: ## Logları izler (tek servis için: make logs S=core-api)
	@docker compose logs -f --tail 100 $(S)

down: ## Servisleri durdurur (veri korunur)
	@docker compose down

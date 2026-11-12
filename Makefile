# AI Testing Probe — yerel geliştirme ve demo ortamı (F0)
# Sözleşme: specs/001-dev-foundation/contracts/make-targets.md
# Tüm hedefler repo kökünden çalışır; `make help` hedefleri listeler.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Tek sürüm kaynağı: docker-compose.yml `${PLAYWRIGHT_VERSION:?}` ister
export PLAYWRIGHT_VERSION := $(strip $(shell cat .playwright-version 2>/dev/null))

S ?=

.PHONY: help env up asistan-paket status seed reset jira-seed forge-init break demo-break demo-reset demo-web-sync locator-break-verify demo-baseline export-audit security-check e2e-smoke demo-check demo-prova prova-temizle eval-live asistan-perf prune logs down cihaz-kur cihaz-baslat cihaz-durdur cihaz-durum cihaz-wda cihaz-ag windows-vm-olustur windows-vm-ac windows-vm-kapat windows-vm-yeniden windows-vm-durum windows-vm-bekle windows-vm-ekran windows-vm-sil windows-vm-ip windows-vm-selftest

help: ## Hedefleri listeler
	@echo "Kullanım: make <hedef>"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{ printf "  %-16s %s\n", $$1, $$2 }'

env: ## .env'i üretir, boş F0 parolalarını rastgele doldurur (var olanlara dokunmaz)
	@scripts/env.sh

up: ## Asistan bilgi paketi + önkoşul kontrolü + tüm servisleri sağlıklı başlatır (idempotent; paketi atla: TP_SKIP_ASISTAN_PAKET=1)
	@mkdir -p var/tp-bilgi  # bağlama noktası yoksa docker root sahipli oluşturmasın
	@if [ "$${TP_SKIP_ASISTAN_PAKET:-0}" != "1" ]; then scripts/asistan-bilgi-paketi.sh; fi
	@scripts/up.sh

asistan-paket: ## Asistanın ürün bilgi paketini üretir: var/tp-bilgi/ (core imajında; sır taraması bulgusunda ≠0)
	@scripts/asistan-bilgi-paketi.sh

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

demo-prova: ## Tam demo provası: make reset → 14 adım (iki tur + review + denetim KABUL) + locator kırma/onarım, strict REPLAY (RUNS=n, varsayılan 1; §13 için RUNS=3; UI=1: arayüzden; UITUR=1: salt okuma arayüz turu + video; KIRMA=1: kırma taslağını yayınla; SAKLA=n: son n rapor)
	@scripts/demo-prova.sh --runs $(or $(RUNS),1) $(if $(UI),--ui,) $(if $(UITUR),--ui-tur,) $(if $(KIRMA),--kirma-yayinla,) $(if $(SAKLA),--sakla $(SAKLA),)

prova-temizle: ## Eski prova raporlarını temizle (N=10: son N koşu klasörü kalır)
	@scripts/demo-prova.sh --temizle $(or $(N),10)

eval-live: ## Prompt değerlendirme setini CANLI modelle koşturur, sert bütçe TP_EVAL_BUDGET_USD (5; asistan seti ≥10) (A='--ping' | '--dry-run' | '--bundle triage --update-status' | '--record' | '--bundle assistant --via-flow')
	@scripts/eval-live.sh $(A)

asistan-perf: ## Asistan süre testleri (§16.12 öneri ucu p95 < 300 ms; T132): TP_TEST_PERF=1 pytest -m perf (geçici test postgres'i; toplu gönderim öncesi)
	@cd core && TP_TEST_PERF=1 TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/assistant -m perf -q

# --- Cihaz altyapısı (009 mobil; docs/CIHAZ-ALTYAPISI.md) ---------------------------------------
PLATFORM ?=

cihaz-kur: ## Appium 3 + sürücüler (tools/appium) + AVD tp-android + simülatör "TP iPhone" + app-mcp (idempotent)
	@scripts/cihaz/kur.sh

cihaz-baslat: ## Cihazı açar, derleme varsa uygulamayı kurar, Appium 127.0.0.1:4723 (PLATFORM=android|ios; GORUNMEZ=1: penceresiz)
	@scripts/cihaz/baslat.sh $(PLATFORM)

cihaz-durdur: ## Appium + kanonik cihazları durdurur (PLATFORM=android|ios: yalnız o cihaz)
	@scripts/cihaz/durdur.sh $(PLATFORM)

cihaz-durum: ## Appium, cihaz ve uygulama derlemesi durumu
	@scripts/cihaz/durum.sh

cihaz-wda: ## iOS WebDriverAgent ön derlemesi (ilk xcuitest oturumu hızlanır; Xcode değişince yeniden)
	@scripts/cihaz/wda.sh

cihaz-ag: ## Konteyner → host.docker.internal:4723 erişimi + LAN'dan erişilemezlik doğrulaması
	@scripts/cihaz/ag-dogrula.sh

# --- GCP Windows VM (009 Windows masaüstü; specs/009-mobil-masaustu/windows-gcp.md) --------------
# Tümü gcloud (Mac). Ortam: TP_GCP_PROJECT, TP_WINDOWS_VM_* ; DRY_RUN=1 yalnızca yazdırır.
windows-vm-olustur: ## tp-windows VM'ini oluşturur (onay ister; EVET=1 atlar; DRY_RUN=1 yalnızca yazdırır)
	@deploy/gcp/windows-vm/vm.sh olustur

windows-vm-ac: ## tp-windows VM'ini başlatır (DRY_RUN=1 yalnızca yazdırır)
	@deploy/gcp/windows-vm/vm.sh ac

windows-vm-kapat: ## tp-windows VM'ini durdurur — kullanılmıyorken kapatın (DRY_RUN=1 yalnızca yazdırır)
	@deploy/gcp/windows-vm/vm.sh kapat

windows-vm-yeniden: ## tp-windows'u yeniden başlatır, yalnızca bu açılışın HAZIR/HATA satırını bekler
	@deploy/gcp/windows-vm/vm.sh yeniden

windows-vm-durum: ## tp-windows durumu, iç IP ve seri porttaki son TP-WINDOWS-HAZIR/HATA satırı
	@deploy/gcp/windows-vm/vm.sh durum

windows-vm-bekle: ## Seri portta TP-WINDOWS-HAZIR bekler; HATA/zaman aşımında ≠0 (TP_WINDOWS_VM_BEKLE_DK=45)
	@deploy/gcp/windows-vm/vm.sh bekle

windows-vm-ekran: ## tp-windows ekran görüntüsünü var/windows-vm/ altına kaydeder, yolu yazar
	@deploy/gcp/windows-vm/vm.sh ekran

windows-vm-sil: ## tp-windows VM'ini ve diskini siler (onay ister; EVET=1 atlar; DRY_RUN=1 yalnızca yazdırır)
	@deploy/gcp/windows-vm/vm.sh sil

windows-vm-ip: ## tp-windows iç IP'sini yazar (tp-demo .env: TP_WINDOWS_VM_APPIUM=<ip>:4723)
	@deploy/gcp/windows-vm/vm.sh ip

windows-vm-selftest: ## vm.sh öz testi (sahte gcloud; GCP'ye dokunmaz)
	@deploy/gcp/windows-vm/vm-selftest.sh

prune: ## Kullanılmayan (dangling) imajları ve build önbelleğini temizler; volume'lere dokunmaz
	@echo "İmajlar:";        docker image prune -f | tail -n 1
	@echo "Build önbelleği:"; docker builder prune -f | tail -n 1

logs: ## Logları izler (tek servis için: make logs S=core-api)
	@docker compose logs -f --tail 100 $(S)

down: ## Servisleri durdurur (veri korunur)
	@docker compose down

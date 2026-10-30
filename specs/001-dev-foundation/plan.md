# Implementation Plan: Geliştirme ve Demo Ortamı Temeli

**Branch**: `001-dev-foundation` | **Date**: 2026-10-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-dev-foundation/spec.md`

**Kaynak tasarım**: [docs/TEKNIK-TASARIM.md](../../docs/TEKNIK-TASARIM.md) v1.5 — §0 kararları, §2.1 demo sadeleştirmeleri, §4 mimari, §6 bileşenler, §11 Compose.

## Summary

Ekipteki herkesin Apple Silicon Mac'te tek komutla (`make up`) ürünün tüm yerel bileşenlerini ayağa
kaldırabildiği, sağlıklarını tek ekranda gördüğü, ortamı tek komutla temiz başlangıç durumuna
döndürebildiği (`make reset`) ve güvenli varsayılanları otomatik doğrulayabildiği (`make
security-check`) temel ortam. Bileşenler bu özellikte **iş mantığı olmayan, sağlık kontrolüne cevap
veren iskeletler** olarak gelir; iş mantığı F1–F5'te eklenir. Teknik yaklaşım: Docker Compose (sağlık
kontrolleriyle `--wait`), Postgres (çekirdek veri + append-only denetim rolü), Python/FastAPI çekirdek,
tek bir "toolchain" imajı (Playwright + Node + Python + uv) üzerinden çalışan toolchain-worker,
test-runner ve Playwright MCP, iç ağlarla izole edilmiş test-runner.

## Technical Context

**Language/Version**: Python 3.12 (çekirdek, demo-app API), TypeScript 5.x / Node 22 (portal ve demo-app web build; toolchain imajında Playwright tabanından gelen Node 24), Bash (make yardımcı script'leri)

**Primary Dependencies**: FastAPI, Uvicorn, SQLAlchemy 2, Alembic, psycopg 3, Pydantic v2 (çekirdek); React + Vite (portal ve demo-app web iskeletleri); `@playwright/test` 1.64.1 ve `@playwright/mcp` 0.0.83 (sürümler `.playwright-version`/`package.json` ile sabit); nginx (statik servis); gitleaks (sır taraması)

**Storage**: PostgreSQL 16 (`postgres:16-alpine`, named volume). İki veritabanı: `tp` (çekirdek) ve `demoapp` (örnek uygulama; F1'de doldurulur, salt okuma rolü F1'de)

**Testing**: pytest (çekirdek birim + `-m integration` ile çalışan compose'a karşı entegrasyon), `make security-check` (otomatik güvenlik kontrolleri), shellcheck (script'ler)

**Target Platform**: macOS Apple Silicon + Docker Desktop 29.x (Colima ile de çalışır); tüm imajlar `linux/arm64` ve `linux/amd64`

**Project Type**: Çok servisli web uygulaması (monorepo: çekirdek servis + portal + örnek uygulama + araç zinciri)

**Performance Goals**: Isınmış imajlarla `make up` → tüm servisler sağlıklı < 3 dk (SC-001); `make reset && make seed` < 2 dk (SC-003)

**Constraints**: Toplam bellek ≤ 10 GB, disk ≤ 30 GB (SC-006); tüm host portları yalnızca `127.0.0.1`; test-runner'ın internet, Postgres, core-api ve sır erişimi yok; imajlar sabit sürüm + digest; dışarıdan gelen bağlantı yok

**Scale/Scope**: Tek geliştirici makinesi, 3 kişilik ekip; 9 uzun ömürlü servis + 1 tek seferlik migrasyon servisi

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| İlke | F0'daki karşılığı | Durum |
|---|---|---|
| I. AI üretir, insan onaylar | F0'da AI yok; onay kayıtlarının tutulacağı Postgres ve `app_user` rolleri hazırlanır | ✅ Uygun |
| II. CI'da AI yok | F0'da CI yok (F1); toolchain imajında model SDK'sı bulunmaz | ✅ Uygun |
| III. Yapılandırılmış çıktı | F0'da model çağrısı yok | — Uygulanmaz |
| IV. Kütüphaneye bağlı kod | F0'da kod üretimi yok | — Uygulanmaz |
| V. Uygulamayı gerçekten gör | Playwright MCP servisi `--caps=vision` olmadan, yalnızca demo-app origin'ine izinli başlatılır | ✅ Uygun |
| VI. Onarım yalnızca locator | F0'da yok | — Uygulanmaz |
| VII. Veri müşteride kalır | Yerel ortam; yalnızca sentetik seed verisi; maskeleme kancası F2a | ✅ Uygun |
| VIII. Her şey kayıt altında | `audit_event` tablosu + yalnızca INSERT/SELECT yetkili uygulama rolü; reset öncesi dışa aktarım | ✅ Uygun (zincir doğrulama ürün fazında, karar §0-23) |
| IX. Ürün opsiyonel | `rules/` dizini oluşturulur | ✅ Uygun |
| X. Her çıktı ölçülür | F0'da yok | — Uygulanmaz |
| XI. Deterministik önce | Seed kimlikleri `uuid5` ile deterministik | ✅ Uygun |
| XII. Bağımsız ürün | Agent Probe'a hiçbir bağımlılık yok; model geçidi F2a | ✅ Uygun |
| Güvenlik/Mimari kısıtlar | localhost portları, iç ağlar, digest sabitleme, lockfile, `npm ci --ignore-scripts`, sırlar `.env`'de | ✅ Uygun |

**Sonuç:** İhlal yok. Post-design kontrolü aşağıda (bkz. "Constitution Check — tasarım sonrası").

## Project Structure

### Documentation (this feature)

```text
specs/001-dev-foundation/
├── plan.md              # Bu dosya
├── research.md          # Phase 0 kararları
├── data-model.md        # Phase 1 veri modeli
├── quickstart.md        # Phase 1 doğrulama rehberi
├── contracts/
│   ├── make-targets.md  # make komutlarının sözleşmesi (girdi, çıktı, çıkış kodu)
│   ├── health.md        # /health uç noktası sözleşmesi
│   └── env.md           # .env anahtarları sözleşmesi
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks çıktısı (bu komutla oluşturulmaz)
```

### Source Code (repository root)

```text
testingprobe/
├── Makefile                     # up, status, seed, reset, prune, security-check, logs, down
├── docker-compose.yml           # tüm servisler, ağlar, sağlık kontrolleri
├── .env.example                 # tüm anahtarlar, açıklamalı (contracts/env.md)
├── .playwright-version          # tek sürüm kaynağı (1.64.1)
├── scripts/
│   ├── lib.sh                   # ortak yardımcılar
│   ├── env.sh                   # .env üretimi (make env)
│   ├── up.sh                    # compose up + sağlık doğrulaması
│   ├── reset.sh                 # dışa aktarım → volume sil → up
│   ├── preflight.sh             # Docker, disk, bellek, port, sır kontrolleri
│   ├── status.sh                # servis sağlık tablosu
│   ├── seed.sh                  # deterministik başlangıç verisi
│   ├── export-audit.sh          # denetim kaydı JSONL + sha256 dışa aktarımı
│   └── security-check.sh        # port, izolasyon, rol ve sır kontrolleri
├── core/                        # çekirdek (Python 3.12, uv)
│   ├── pyproject.toml / uv.lock
│   ├── Dockerfile               # core-api, core-worker, migrate aynı imaj
│   ├── alembic/                 # migrasyonlar (roller, audit_event, app_user)
│   ├── src/tp_core/
│   │   ├── api/                 # FastAPI uygulaması (/health)
│   │   ├── worker/              # arka plan worker iskeleti (Postgres kuyruğu, F2a'da dolar)
│   │   ├── db/                  # bağlantı, oturum
│   │   └── seed.py              # deterministik seed
│   └── tests/{unit,integration}/
├── toolchain/
│   ├── Dockerfile               # FROM mcr.microsoft.com/playwright:v<.playwright-version>-noble + uv + python
│   ├── toolchain_common/        # ortak /health
│   ├── bin/playwright-mcp       # MCP başlatıcı
│   ├── worker/                  # toolchain-worker iskeleti (/health)
│   └── runner/                  # test-runner kontrol API'si iskeleti (/health)
├── review-portal/               # React + Vite iskeleti, nginx ile servis (/health)
├── demo-app/
│   ├── api/                     # FastAPI iskeleti (/health) — iş mantığı F1
│   ├── web/                     # React iskeleti — iş mantığı F1
│   └── e2e/                     # Playwright projesi iskeleti (pages/, tests/) — F1
├── rules/                       # prompt/kural/şema dosyaları (F2a+), README
├── docs/
└── specs/
```

**Structure Decision**: Monorepo, servis başına bir üst dizin. Çekirdek tek Python paketi
(`tp_core`), API/worker/migrasyon aynı imajdan farklı komutlarla çalışır. Playwright kullanan üç
servis (toolchain-worker, test-runner, playwright-mcp) tek `toolchain` imajını paylaşır; böylece
tarayıcı ve Playwright sürümü tek kaynaktan gelir (FR-012) ve disk tasarrufu sağlanır.

## Constitution Check — tasarım sonrası

Phase 1 tasarımı (research, data-model, contracts) yukarıdaki tabloyu değiştirmiyor. Tek not:
denetim dışa aktarımı imza yerine sha256 bütünlük özetiyle yapılıyor (karar §0-23: demoda güvenlik
sertleştirmesi ürün fazına); Constitution VIII'in "değiştirilemez kayıt" şartı DB rolüyle sağlanıyor.
**Sonuç: geçti.**

## Complexity Tracking

| Sapma | Neden | Daha basit alternatif neden reddedildi |
|---|---|---|
| Denetim dışa aktarımı imzasız, yalnızca sha256 bütünlük özetli | Karar §0-23 (on-prem, demoda güvenlik sertleştirmesi öncelik değil); Keychain'de anahtar yönetimi F0'ı uzatır | İmza ürün fazında eklenecek |

# AI Testing Probe

AI destekli test mühendisliği ürünü. Bir gereksinimi (Jira story'si veya serbest metin) alır ve
insan kapılarıyla ilerleyen bir hatta çalıştırılabilir, bakımı yapılabilir otomasyon testine
dönüştürür:

1. **Gereksinim** okunur (Jira / serbest metin).
2. **Ön inceleme ve tutarlılık denetimi**: belirsizlik, eksik kabul kriteri, çelişki; uygulamanın
   kodu ve verisiyle salt okunur karşılaştırma. Her bulgu kanıtlıdır.
3. **Test case'ler** AI tarafından taslak olarak üretilir, **insan onaylar**, test yönetim aracına yayınlanır.
4. **Playwright kodu** onaylı case'lerden, page object kütüphanesine bağlı şablonla üretilir ve
   **PR olarak** açılır; insan review eder.
5. **CI** onaylı, deterministik testleri koşturur — **CI'da AI yoktur**.
6. **Sonuçlar ve triage**: önce deterministik kurallar, sonra AI yorumu; bug taslağı ve locator
   onarım önerisi yine **insan onayından** geçer.

Temel kural: hiçbir AI çıktısı insan onayı olmadan test varlığına dönüşmez; her AI çağrısı, araç
çağrısı, onay ve ret kayıt altındadır. Ayrıntılar: [constitution](.specify/memory/constitution.md).

## Durum

Şu an **F0 — geliştirme ve demo ortamı temeli** üzerinde çalışılıyor: tüm servisler tek komutla
ayağa kalkar, sağlık kontrolüne cevap veren **iskeletler** olarak gelir (iş mantığı yok), ortam tek
komutla sıfırlanır ve güvenli varsayılanlar otomatik doğrulanır.

Sonraki özellikler (ayrıntı: [TEKNIK-TASARIM §17](docs/TEKNIK-TASARIM.md#17-sahipler-ve-teslimat-sırası),
Spec Kit sırası: [§21](docs/TEKNIK-TASARIM.md#21-spec-kit-planı)):

| Özellik | Kapsam |
|---|---|
| F1 | Örnek uygulama, page object kütüphanesi, toolchain imajı, CI, PR botu, ruleset |
| F2a | Çekirdek veri modeli ve durum makinesi, kimlik; model geçidi, maskeleme, replay |
| F3 | Gereksinim okuma, case üretimi, review portal, test yönetimine yayın |
| F4 | Onaylı case → doğrulama → şablonla kod → PR |
| F5 | Triage kuralları, locator onarımı, AST koruması |
| F6 | Seed, REPLAY, prova ve demo hazırlığı |

## Mimari özet (F0)

Tüm servisler [`docker-compose.yml`](docker-compose.yml) içindedir. Host'a açılan portlar
**yalnızca `127.0.0.1`**'e bağlanır; portlar `.env` ile değiştirilebilir.

| Servis | Rol | Yerel adres |
|---|---|---|
| `postgres` | PostgreSQL 16; `tp` (çekirdek) ve `demoapp` (örnek uygulama) veritabanları; alan verisinin tek doğruluk kaynağı | `127.0.0.1:55432` |
| `migrate` | Tek seferlik Alembic migrasyonu (roller, `audit_event`, `app_user`, `job`) | — |
| `core-api` | Çekirdek REST API (FastAPI), `/health` | http://127.0.0.1:8000 |
| `core-worker` | Arka plan worker (Postgres kuyruğu); AI ileride yalnızca burada çalışır | — |
| `toolchain-worker` | Kod araç zinciri (Playwright + Node + Python); kod çalıştırmaz, DB kimliği yok | — |
| `test-runner` | Üretilen testleri koşturan izole servis | — (iç ağ) |
| `playwright-mcp` | Playwright MCP sunucusu; yalnızca demo uygulaması origin'ine izinli, `--caps=vision` yok | http://127.0.0.1:8931 |
| `review-portal` | İnceleme portalı (React + nginx) | http://127.0.0.1:8080 |
| `demo-app-api` | Örnek uygulama API'si (FastAPI) | — (iç ağ) |
| `demo-app-web` | Örnek uygulama arayüzü (React + nginx) | http://127.0.0.1:8081 |

`toolchain-worker`, `test-runner` ve `playwright-mcp` tek bir toolchain imajını paylaşır; Playwright
sürümü tek kaynaktan, [`.playwright-version`](.playwright-version) dosyasından gelir.

### Ağlar ve izolasyon

| Ağ | Tür | Üyeler |
|---|---|---|
| `core-net` | normal | postgres, migrate, core-api, core-worker, toolchain-worker, playwright-mcp, review-portal, demo-app-web |
| `data-net` | `internal` | postgres, demo-app-api |
| `demo-net` | `internal` | demo-app-api, demo-app-web, playwright-mcp, test-runner |
| `runner-net` | `internal` | toolchain-worker, test-runner |

**İzolasyon kuralı:** `test-runner` yalnızca `demo-net` ve `runner-net`'tedir; Postgres'e,
core-api'ye, sırlara ve internete erişemez (DNS düzeyinde bile göremez). `internal` ağlar internete
çıkamaz. Bu kural `make security-check` ile otomatik doğrulanır.

## Hızlı başlangıç

Önkoşullar: Apple Silicon Mac, Docker Desktop (≥ 8 GB bellek), ≥ 30 GB boş disk, `git`, `make`.
Adım adım rehber ve sorun giderme: [docs/ONBOARDING.md](docs/ONBOARDING.md).

```bash
git clone git@github.com:ThinkGOtr/testingprobe.git && cd testingprobe
make env      # .env üretir, F0 parolalarını rastgele doldurur
make up       # önkoşul kontrolü + tüm servisler sağlıklı olana kadar bekler
make status   # servis, durum, sağlık, yerel adres tablosu
make seed     # deterministik başlangıç verisi (5 demo kullanıcısı)
make security-check   # 4/4 PASS beklenir
```

## Make hedefleri

Tüm hedefler repo kökünden çalışır; çıkış kodu `0` = başarı. Sözleşme:
[contracts/make-targets.md](specs/001-dev-foundation/contracts/make-targets.md).

| Hedef | Ne yapar |
|---|---|
| `make env` | `.env` yoksa `.env.example`'dan üretir, boş F0 parolalarını doldurur; varsa dokunmaz |
| `make up` | Önkoşul kontrolü → servisleri başlatır ve sağlıklı olmalarını bekler → `make status`. İdempotent |
| `make status` | Servis adı, durum, sağlık ve yerel adres tablosu; ortam kapalıysa ≠ 0 |
| `make seed` | Deterministik başlangıç verisi; tekrar çalıştırmak güvenli (`seed: 5 kullanıcı (yeni: N)`) |
| `make reset` | Denetim kaydını dışa aktarır → çekirdek veriyi siler → `make up`. Dışa aktarım başarısızsa hiçbir şey silinmez |
| `make export-audit` | Denetim kaydını `exports/audit-*.jsonl` + `.sha256` olarak dışa aktarır |
| `make security-check` | Port, izolasyon, denetim rolü ve sır taraması kontrolleri; her biri `PASS`, özet `4/4` |
| `make prune` | Kullanılmayan imaj ve build önbelleğini temizler (volume'lere dokunmaz) |
| `make logs [S=servis]` | Logları izler (ör. `make logs S=core-api`) |
| `make down` | Servisleri durdurur (veri korunur) |

## Depo yapısı

```text
testingprobe/
├── Makefile               # make hedefleri
├── docker-compose.yml     # servisler, ağlar, sağlık kontrolleri, bellek sınırları
├── .env.example           # tüm anahtarlar, açıklamalı (.env git dışıdır)
├── .playwright-version    # Playwright sürümünün tek kaynağı
├── scripts/               # preflight, status, seed, export-audit, security-check
├── infra/postgres/        # veritabanı ve rol başlatma
├── core/                  # çekirdek (Python 3.12, uv): API, worker, migrasyonlar, seed
├── toolchain/             # toolchain imajı: toolchain-worker, test-runner, playwright-mcp
├── review-portal/         # inceleme portalı (React + Vite, nginx)
├── demo-app/              # örnek uygulama: api/, web/, e2e/ (Playwright projesi)
├── rules/                 # prompt, kural ve şema dosyaları (F2a+) — bkz. rules/README.md
├── docs/                  # teknik tasarım, onboarding
├── specs/                 # Spec Kit özellik spesifikasyonları
└── .specify/              # Spec Kit yapılandırması, şablonlar, constitution
```

## Çalışma şekli (Spec Kit)

Her kilometre taşı ayrı bir [Spec Kit](https://github.com/github/spec-kit) özelliğidir ve
`specs/<numara>-<ad>/` altında yaşar (spec, plan, research, contracts, tasks, quickstart).
Akış: `/speckit-specify` → (`/speckit-clarify`) → `/speckit-plan` → `/speckit-tasks` →
(`/speckit-analyze`) → `/speckit-implement` → `/speckit-converge`. Spec Kit yapılandırması ve
şablonları `.specify/` altındadır.

Kaynak tasarım [docs/TEKNIK-TASARIM.md](docs/TEKNIK-TASARIM.md)'dir; tasarımla çelişen bir spec,
önce tasarım güncellenmeden uygulanmaz.

## Bağlantılar

- [Constitution](.specify/memory/constitution.md) — değişmez kurallar
- [Teknik tasarım](docs/TEKNIK-TASARIM.md)
- [F0 spesifikasyonu](specs/001-dev-foundation/spec.md) · [plan](specs/001-dev-foundation/plan.md) · [doğrulama rehberi](specs/001-dev-foundation/quickstart.md)
- [Yeni ekip üyesi rehberi](docs/ONBOARDING.md)
- [rules/](rules/README.md)

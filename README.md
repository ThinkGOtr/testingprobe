# AI Testing Probe

AI destekli test mühendisliği ürünü. Bir gereksinimi (Jira story'si veya serbest metin) alır ve
insan kapılarıyla ilerleyen bir hatta çalıştırılabilir, bakımı yapılabilir otomasyon testine
dönüştürür:

1. **Gereksinim** okunur (Jira / serbest metin).
2. **Ön inceleme ve tutarlılık denetimi**: belirsizlik, eksik kabul kriteri, çelişki; uygulamanın
   kodu ve verisiyle salt okunur karşılaştırma. Her bulgu kanıtlıdır ve kanıt deterministik olarak
   yeniden doğrulanır. Analist karar verir, düzeltmeler Jira'ya yazılır, **PO Jira'da onaylar**.
3. **Test case'ler** AI tarafından taslak olarak üretilir, **insan onaylar**, test yönetim aracına
   yayınlanır.
4. **Playwright kodu** onaylı case'lerden üretilir: ajan adımları uygulamada doğrular, kod page
   object kütüphanesine bağlı **şablonla** yazılır (model TypeScript yazmaz), **PR olarak** açılır;
   insan review eder, "kırarak doğrula" testin hatayı yakaladığını kanıtlar.
5. **CI** onaylı, deterministik testleri koşturur — **CI'da AI yoktur**. Sonuçlar JUnit XML + Allure
   ve **Kontrol Kulesi**'nde.
6. **Triage**: önce deterministik kurallar, sonra AI; locator kırılmasında yalnızca testId değişen
   onarım PR'ı, gerçek hatada mükerrer aramalı bug taslağı — ikisi de **insan onayından** geçer.

Temel kural: hiçbir AI çıktısı insan onayı olmadan test varlığına dönüşmez; her AI çağrısı, araç
çağrısı, onay ve ret hash zincirli denetim kaydındadır. Ayrıntılar:
[constitution](.specify/memory/constitution.md).

## Durum

| Faz | Kapsam | Durum |
|---|---|---|
| F0 | Geliştirme ve demo ortamı: tek komutla kurulum, sıfırlama, güvenlik kontrolleri | Tamam |
| Faz 1–2 · Demo-A | Story → ön inceleme + kod/veri tutarlılık denetimi → doküman düzeltme → PO teyidi → case → QA onayı → yayın; Claude Code (MCP) kanalı | Tamam |
| Faz 3 · Demo-B | Kod üretimi (Playwright MCP ajanı + şablon) → yerel kontrol → PR → kırarak doğrula → merge → yerel CI (PR/push/gece/deploy) → Kontrol Kulesi | Tamam |
| Faz 4 | Triage (önce kural) → locator onarım PR'ı / mükerrer aramalı bug taslağı → testçi kararı → Jira; demo kontrolleri | Tamam |
| Faz 5 | Prova, gerçek sistemlere geçiş hazırlığı, ölçülmüş baz değer | Sürüyor |

**Bugün dış hesap yoktur ve bu açıkça etiketlenir:**

- **Model: REPLAY.** AI adımlarının çıktısı `rules/replay/` altındaki küratörlü golden kayıtlardan
  gelir; portal her birini **REPLAY** rozetiyle gösterir. 2026-11-01'de 8 prompt paketinden 4'ü
  (`requirement-review`, `triage`, `bug-draft`, `dup-rank`) canlı modelle değerlendirildi; ajan
  paketleri, `case-generation` ve geçişli `guardrails` hâlâ "canlı değerlendirme bekliyor"
  (`rules/evaluations.yaml`). Değerlendirme REPLAY çıktısını canlı yapmaz.
- **Jira → `jira-sim`**, **git → LocalForge**, **CI → yerel test-runner**, **Sauce → yok** (yerel
  Chromium). Gerçek sistemlere geçiş: [docs/GERCEK-SISTEMLER.md](docs/GERCEK-SISTEMLER.md).
- **Kazanç oranı ölçülmeden gösterilmez.** Manuel baz süre story başına ölçülür ve portaldan
  (gereksinim detayı → "Manuel baz değer", giren + kaynak notu) girilir. Ölçümü olmayan story'de
  `TP_MANUAL_BASELINE_S` yalnızca "varsayılan" etiketiyle görünür ve kazanca girmez; ikisi de yoksa
  portal "ölçülmedi" der.

## Mimari

Tüm servisler [`docker-compose.yml`](docker-compose.yml) içindedir. Host'a açılan portlar
**yalnızca `127.0.0.1`**'e bağlanır; portlar `.env` ile değiştirilebilir.

| Servis | Rol | Yerel adres |
|---|---|---|
| `postgres` | PostgreSQL 16; `tp` (çekirdek) ve `demoapp` (örnek uygulama) veritabanları; alan verisinin tek doğruluk kaynağı | `127.0.0.1:55432` |
| `migrate` | Tek seferlik Alembic migrasyonu | — |
| `core-api` | Çekirdek REST API (FastAPI), oturum, SSE olayları, onay kayıtları, MCP (`/mcp`, Claude Code kanalı) | http://127.0.0.1:8000 |
| `core-worker` | Durum makinesi + iş kuyruğu; AI çağrıları **yalnızca burada**; Jira, forge ve test yönetimi yazımı; model anahtarı ve yazma kimlikleri yalnızca burada | — |
| `toolchain-worker` | TypeScript tarafı: sembol tablosu, `tsc`/`eslint`/AST koruması, locator yoklaması; merge kapısının (`local-ci`) tek yazarı; kod çalıştırmaz, DB kimliği yok | — |
| `test-runner` | Üretilen testleri koşturan izole servis (internetsiz, sırsız) | — (iç ağ) |
| `playwright-mcp` | Doğrulama ajanının tarayıcısı; yalnızca demo uygulamasına izinli, `--caps=vision` yok | — (host'a açılmaz) |
| `review-portal` | İnceleme portalı (React + nginx), Türkçe | http://127.0.0.1:8080 |
| `demo-app-api` | Örnek uygulama API'si: Bayi Sipariş Portalı (FastAPI) | — (iç ağ) |
| `demo-app-web` | Örnek uygulama arayüzü (React + nginx) | http://127.0.0.1:8081 |
| `jira-sim` | Jira Cloud REST v3 + Xray alt kümesi simülatörü; gerçek Jira ile aynı istemci kodu | http://127.0.0.1:8090 |

Dış sistemler port + adaptör + yerel simülatör düzenindedir
([MIMARI-SOZLESME §1](docs/MIMARI-SOZLESME.md#1-dış-sistemler-port--adaptör--yerel-simülatör)):

| Sistem | Yerel (varsayılan) | Gerçek | Seçim |
|---|---|---|---|
| Model | REPLAY | Anthropic (Claude); Azure OpenAI adaptörü iskelet | `TP_MODEL_MODE` |
| Jira | `jira-sim` | Jira Cloud | `JIRA_BASE_URL` |
| Test yönetimi | Jira Test issue | Jira Test issue · Xray Cloud | `TP_TEST_MGMT` |
| Git forge + CI | LocalForge (yerel bare git + PR kaydı) + test-runner | GitHub (App, ruleset, Actions) | `TP_FORGE` |
| Bulut tarayıcı | yerel Chromium | Sauce Labs (GitHub Actions job'u) | GitHub secret'ları |

### Ağlar ve izolasyon

| Ağ | Tür | Üyeler |
|---|---|---|
| `core-net` | normal | postgres, migrate, core-api, core-worker, toolchain-worker, jira-sim, review-portal, demo-app-web |
| `data-net` | `internal` | postgres, demo-app-api |
| `demo-net` | `internal` | demo-app-api, demo-app-web, test-runner |
| `agent-net` | `internal` | demo-app-web, playwright-mcp |
| `runner-net` | `internal` | toolchain-worker, test-runner |
| `mcp-net` | `internal` | core-worker, playwright-mcp |

`test-runner` yalnızca `demo-net` ve `runner-net`'tedir: Postgres'e, core-api'ye, playwright-mcp'ye,
merge kapısına, sırlara ve internete erişemez. `playwright-mcp` yalnızca demo-app-web'e ulaşır (nginx
`/api/test/*`'i kapatır). Bu sınırlar `make security-check` ile otomatik doğrulanır.

### Roller (portal kullanıcıları)

Parola: `.env` → `SEED_USER_PASSWORD` (`make seed` yükler).

| Kullanıcı | Rol | Ne yapar |
|---|---|---|
| `analist` | analyst | Jira'dan çeker, ön inceleme/tutarlılık bulgularına karar verir, case üretir ve onaylar, yayınlar; Claude Code token'ı |
| `po` | po | Serbest metin gereksinimde PO teyidi (Jira yolunda PO onayı Jira etiketiyle verilir) |
| `muhendis` | engineer | Kod üretimi, kırarak doğrula, PR review ve merge, locator onarım PR'ı |
| `testci` | tester | Bug taslağı: yeni kayıt aç / mevcut kayda bağla / düzelt / reddet |
| `sunucu` | presenter | Deploy ve gece koşusu tetikleri, demo kontrolleri (locator kırma, demo sıfırlama), Kontrol Kulesi |

jira-sim kullanıcıları: `reader@sim.local` (okuma), `writer@sim.local` (ürünün yazma kullanıcısı),
`po@sim.local` (PO; parola `.env` → `JIRA_SIM_PO_PASSWORD`). Örnek uygulama: `bayi1` / `Demo123!`
(sentetik demo verisi, [docs/DEMO-VERISI.md](docs/DEMO-VERISI.md)).

## Hızlı başlangıç

Önkoşullar: Apple Silicon Mac, Docker Desktop (≥ 8 GB bellek), ≥ 30 GB boş disk, `git`, `make`.
Sunum makinesinde ayrıca `uv` (zorunlu `make demo-prova` ve `make eval-live` için) ve arayüz provası
(`UI=1`, yedek video) için `node` 22 + Chromium.
Adım adım rehber ve sorun giderme: [docs/ONBOARDING.md](docs/ONBOARDING.md).

```bash
git clone git@github.com:ThinkGOtr/testingprobe.git && cd testingprobe   # main = kararlı sürüm; geliştirme dev dalında
make env              # .env üretir, yerel parolaları/belirteçleri rastgele doldurur
make up               # önkoşul kontrolü + tüm servisler sağlıklı olana kadar bekler (forge hazırlanır)
make seed             # deterministik başlangıç verisi (5 portal kullanıcısı)
make status           # servis, durum, sağlık, yerel adres tablosu
make security-check   # Özet: 10/10 beklenir
make e2e-smoke        # demo-app e2e, test-runner içinden
```

Demoyu oynatmak için: `make demo-reset` (baseline CI koşusu kuyruğa girer), ardından
[docs/DEMO-AKISI.md](docs/DEMO-AKISI.md) — sunucu senaryosu, rol başına tarayıcı oturumları ve
aksaklık rehberi.

## Make hedefleri

Tüm hedefler repo kökünden çalışır; çıkış kodu `0` = başarı. `make help` güncel listeyi yazdırır.

**Ortam**

| Hedef | Ne yapar |
|---|---|
| `make env` | `.env` yoksa `.env.example`'dan üretir, boş yerel parolaları doldurur; var olan değerlere dokunmaz |
| `make up` | Önkoşul kontrolü → servisleri başlatır ve sağlıklı olmalarını bekler → `make status`. İdempotent |
| `make status` | Servis, durum, sağlık ve yerel adres; ortam kapalıysa ≠ 0. Varsayılan manuel baz yoksa bilgi verir |
| `make seed` | Deterministik başlangıç verisi; tekrar çalıştırmak güvenli |
| `make reset` | Denetim kaydını dışa aktarır → çekirdek veri, artefaktlar, forge ve jira-sim'i başa alır → `make up` → `make seed`. Dışa aktarım başarısızsa hiçbir şey silinmez. Gerçek Jira'da önce `jira-seed` planını gösterip onay ister |
| `make logs [S=servis]` | Logları izler (ör. `make logs S=core-worker`) |
| `make down` | Servisleri durdurur (veri korunur) |
| `make prune` | Kullanılmayan imaj ve build önbelleğini temizler (volume'lere dokunmaz) |

**Doğrulama ve denetim**

| Hedef | Ne yapar |
|---|---|
| `make security-check` | 10 kontrol: port, test-runner izolasyonu, denetim rolü, sır taraması, `demoapp_ro` en az yetki, model anahtarı yeri, MCP izolasyonu, yazma kimlikleri yeri, merge kapısı yalıtımı, CI imajında ajan yok. Özet `10/10` |
| `make e2e-smoke` | demo-app e2e testlerini forge main'den alıp test-runner içinden koşturur; `E2E_BREAK_VERIFY=1` ile yeşil → kırmızı → yeşil |
| `make export-audit` | Denetim kaydını `exports/audit-*.jsonl` + `.sha256` olarak dışa aktarır |

**Demo**

| Hedef | Ne yapar |
|---|---|
| `make demo-reset` | Sunucu sıfırlaması (`POST /demo/reset`): main → demo-baseline, açık bot PR'ları kapanır, demo-app-web yeniden derlenir, baseline CI kuyruğa girer, yalnızca sistemin açtığı AI Bug'ları jira-sim'den silinir. Veritabanı korunur (tam sıfırlama: `make reset`) |
| `make demo-check` | Demo-B ön kontrolü: onaylı case'lerde "defect adayı" anı REPLAY'de hazır mı (`STORY=TPD-1`) + REPLAY tarayıcı adımları canlı MCP'de tekrarlanıyor mu (`RUNS=5`) |
| `make demo-prova` | Sunum öncesi otomatik prova: her koşudan önce `make reset`, strict REPLAY, 14 adım + locator kırma/onarım. `RUNS=n` (varsayılan 1; TEKNIK-TASARIM §13 için `RUNS=3`, koşu başına ~10,5 dk), host'ta `uv` gerekir, `UI=1` arayüzden (video), `UITUR=1` salt okuma tur. Ayrıntı: [rehearsal/README.md](rehearsal/README.md); arayüz kipleri için bir kez `cd rehearsal/ui && npm ci && npx playwright install chromium` |
| `make demo-break` | Portaldaki "Buton kimliğini değiştir" düğmesinin terminal eşi (`POST /demo/break-locator`) + demo-app-web eşitleme |
| `make break` | Host yolu: yeşil temel koşu ön denetimi + `demo/break-locator` demo-admin bypass merge + demo-app-web derleme (`Z=1` denetimi atlar — önerilmez) |
| `make demo-web-sync [A=--watch]` | core'un istediği forge commit'inden demo-app-web'i derler; portal düğmesi kullanılacaksa sunum boyunca `A=--watch` ile açık kalır |
| `make demo-baseline` | Forge main → demo-baseline + demo-app-web yeniden derleme (PR kaydı korunur) |
| `make locator-break-verify` | Çevrimdışı ön kontrol: kırılma → yalnızca add-to-cart locator hatası → testId onarımı → yeşil |
| `make forge-init [F=--force]` | Yerel forge deposunu hazırlar (`make up` zaten çağırır) |

**Gerçek sistemler**

| Hedef | Ne yapar |
|---|---|
| `make eval-live` | Prompt paketlerinin değerlendirme setini **canlı modelle** koşturur (`scripts/eval-live.sh`; argümanlar `A=`: `make eval-live A=--ping`, `A=--dry-run`, `A="--bundle triage --update-status"`, `A=--record`; sert bütçe `TP_EVAL_BUDGET_USD`, vars. 5 USD). Çalışma alanına bağlı anahtar için `.env`'de `ANTHROPIC_WORKSPACE_ID`. Demo yolunun kipini değiştirmez |
| `make jira-seed [ONAY=1]` | Gerçek Jira'yı demo başlangıcına döndürür (önce plan; `ONAY=1` uygular) |

## Depo yapısı

```text
testingprobe/
├── Makefile               # make hedefleri
├── docker-compose.yml     # servisler, ağlar, volume'ler, sağlık kontrolleri
├── .env.example           # tüm anahtarlar, açıklamalı (.env git dışıdır)
├── .playwright-version    # Playwright sürümünün tek kaynağı
├── scripts/               # up, status, seed, reset, security-check, demo-*, forge-init, github-*, eval-live
├── infra/postgres/        # veritabanı ve rol başlatma
├── core/                  # çekirdek (Python 3.12, uv): API, worker, model geçidi, entegrasyonlar, özellikler
├── toolchain/             # toolchain imajı: toolchain-worker, test-runner, playwright-mcp, AST koruması
├── review-portal/         # inceleme portalı (React + Vite, nginx)
├── demo-app/              # örnek uygulama: api/, web/, e2e/ (page object'ler + testler), ci/
├── sims/jira-sim/         # Jira Cloud REST v3 + Xray alt kümesi simülatörü
├── rules/                 # prompt, şema, replay kayıtları, değerlendirme setleri — bkz. rules/README.md
├── .github/               # CI workflow'ları (AI'sız), CODEOWNERS, ruleset betiği — bkz. .github/CI.md
├── docs/                  # tasarım, sözleşme, demo verisi ve akışı, onboarding
├── specs/                 # Spec Kit özellik spesifikasyonları
└── .specify/              # Spec Kit yapılandırması, şablonlar, constitution
```

## Belgeler

| Belge | Ne için |
|---|---|
| [Constitution](.specify/memory/constitution.md) | Değişmez kurallar |
| [docs/TEKNIK-TASARIM.md](docs/TEKNIK-TASARIM.md) | Kaynak tasarım: başarı ölçütleri, 14 adımlı senaryo, ölçüm, demo güvenilirliği |
| [docs/MIMARI-SOZLESME.md](docs/MIMARI-SOZLESME.md) | Uygulamadaki bağlayıcı sözleşme: servisler, API, veri modeli, ortam değişkenleri |
| [docs/DEMO-VERISI.md](docs/DEMO-VERISI.md) | Demo verisi ve sahne notları (bağlayıcı) |
| [docs/DEMO-AKISI.md](docs/DEMO-AKISI.md) | Canlı demo sunucu senaryosu |
| [docs/GERCEK-SISTEMLER.md](docs/GERCEK-SISTEMLER.md) | Simülatörden Anthropic, Jira Cloud, Xray, Sauce Labs ve GitHub'a geçiş |
| [docs/CLAUDE-CODE-KANALI.md](docs/CLAUDE-CODE-KANALI.md) | IDE (MCP) kanalı |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Yeni ekip üyesi rehberi ve sorun giderme |
| [.github/CI.md](.github/CI.md) | CI job'ları, Sauce, ruleset, artefakt sözleşmesi |
| [rules/README.md](rules/README.md) | Model geçidi, REPLAY, canlı değerlendirme |

## Çalışma şekli (Spec Kit)

Her kilometre taşı ayrı bir [Spec Kit](https://github.com/github/spec-kit) özelliğidir ve
`specs/<numara>-<ad>/` altında yaşar. Akış: `/speckit-specify` → (`/speckit-clarify`) →
`/speckit-plan` → `/speckit-tasks` → (`/speckit-analyze`) → `/speckit-implement` →
`/speckit-converge`. Kaynak tasarım [docs/TEKNIK-TASARIM.md](docs/TEKNIK-TASARIM.md)'dir; tasarımla
çelişen bir spec, önce tasarım güncellenmeden uygulanmaz. `main`'e her değişiklik PR ile gelir.

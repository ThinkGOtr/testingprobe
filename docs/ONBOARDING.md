# Yeni ekip üyesi rehberi

Hedef: repoyu hiç kurmamış biri, yardım almadan **30 dakika içinde** ortamı ayağa kaldırır,
`make security-check` ile **10/10 PASS** görür ve demoyu REPLAY kipinde uçtan uca oynatabilir. İlk
kurulumda imaj indirme ve build süresi ≤ 20 dk, ısınmış imajlarla `make up` ≤ 3 dk'dır.

Genel bakış için önce [README](../README.md)'yi, çalışma kuralları için
[constitution](../.specify/memory/constitution.md)'ı okuyun. Uygulamadaki bağlayıcı sözleşme
[MIMARI-SOZLESME.md](MIMARI-SOZLESME.md)'dir.

## 1. Önkoşullar

| Gereksinim | Not |
|---|---|
| Apple Silicon Mac (arm64) | İmajlar amd64 için de mevcuttur (CI uyumu); birincil hedef Apple Silicon |
| Docker Desktop 29.x | Settings → Resources → **Memory ≥ 8 GB**. Rosetta gerekmez (tüm imajlar `linux/arm64`). Alternatif: Colima (bkz. Sorun giderme) |
| ≥ 30 GB boş disk | `make up` kontrol eder; Docker Desktop disk limiti için 64 GB önerilir |
| `git`, `make`, `curl`, `python3` | macOS'ta Xcode Command Line Tools ile gelir (`xcode-select --install`) |
| `uv` | Ortamı (`make up`) çalıştırmak için gerekmez. **Sunum makinesinde zorunlu:** `make demo-prova` (sunum öncesi zorunlu prova kapısı; `uv` yoksa çıkış `2`) ve `make eval-live` host'ta `uv` ile koşar. Konteyner dışı birim testleri ve `rules/` araçları da `uv` ister |
| `node` 22 + Chromium | Ortamı çalıştırmak için gerekmez. **Arayüz provası için zorunlu** (`make demo-prova UI=1` / `UITUR=1`, yedek video kaydı): bir kez `cd rehearsal/ui && npm ci && npx playwright install chromium`. Portal birim testleri de `node` 22 ister |
| `gh`, `jq` | Yalnızca GitHub modu (ruleset betiği, Sauce secret'ları) için |
| GitHub erişimi | Repoya SSH anahtarıyla clone yetkisi |

Docker'ın çalıştığını doğrulayın:

```bash
docker info --format '{{.MemTotal}}'   # ≥ 8000000000 (yaklaşık 8 GB) olmalı
```

## 2. Kurulum ve doğrulama

### 2.1 Clone ve sırlar dosyası

```bash
git clone git@github.com:ThinkGOtr/testingprobe.git && cd testingprobe
make env
```

> **Dal:** `main` kararlı sürümdür ve varsayılan clone onu getirir. Geliştirme `dev` dalında yürür;
> en son değişiklikler için `git switch dev`. `main`, `dev`'den fast-forward ile güncellenir.
>
> **Bilinen durum (2026-11-02):** ≤ 30 dk / ≤ 20 dk hedefleri soğuk clone'dan (ikinci makinede ya da
> `docker system prune -a` sonrası) henüz ölçülmedi; bu rehber bir kez baştan sona süre tutularak
> izlenmelidir.

**Beklenen:** `.env hazır`. `make env`, `.env.example`'dan `.env` üretir ve "F0: zorunlu" bloğundaki
yerel parola ve belirteçleri (Postgres rolleri, `SEED_USER_PASSWORD`, `TP_SESSION_SECRET`,
`JIRA_SIM_PO_PASSWORD`, `JIRA_SIM_ADMIN_TOKEN`, `DEMOAPP_TEST_TOKEN`, `TP_TOOLCHAIN_TOKEN` …) rastgele
doldurur; Playwright sürümünü `.playwright-version`'dan yazar. `.env` zaten varsa dolu değerlere
dokunmaz, yalnızca boş kalanları doldurur.

### 2.2 Ortamı başlatma

```bash
make up
```

**Beklenen:** komut `0` ile biter ve sonunda `make status` tablosu basılır; tüm servisler
`healthy`. `make up` önce önkoşulları (Docker, disk, bellek, zorunlu sırlar, port çakışması)
kontrol eder; eksik varsa hangisi olduğunu yazar ve **hiçbir servisi başlatmaz**. Yerel forge
(`demo-app` bare git deposu) ilk açılışta hazırlanır. Bir servis 5 dk içinde sağlıklı olmazsa adını
ve son 20 log satırını gösterir. "Varsayılan manuel baz değer yok" bilgisi bilgi amaçlıdır (bkz. §6).

### 2.3 Başlangıç verisi, durum ve adresler

```bash
make seed      # ikinci çalıştırmada "seed: 5 kullanıcı (yeni: 0)"
make status
```

| Adres | Ne |
|---|---|
| http://127.0.0.1:8080 | Review portal — kullanıcılar `analist`, `muhendis`, `sunucu`, `po`, `testci`; parola `.env` → `SEED_USER_PASSWORD` |
| http://127.0.0.1:8000/health | core-api sağlık |
| http://127.0.0.1:8081 | Örnek uygulama (`bayi1` / `Demo123!`, bkz. [DEMO-VERISI.md](DEMO-VERISI.md)) |
| http://127.0.0.1:8090 | Jira simülatörü (PO: `po@sim.local`, parola `.env` → `JIRA_SIM_PO_PASSWORD`) |
| `127.0.0.1:55432` | Postgres |

Roller: **analist** gereksinim, bulgu, case ve yayın; **po** serbest metin gereksinimde PO teyidi
(Jira yolunda PO jira-sim'de onaylar); **muhendis** kod üretimi, kırarak doğrula, merge, locator
onarımı; **testci** bug taslağı kararları; **sunucu** deploy/gece tetikleri, demo kontrolleri,
Kontrol Kulesi.

### 2.4 Eksik sır senaryosu (opsiyonel doğrulama)

```bash
mv .env .env.bak && cp .env.example .env && make up; echo $?   # ≠ 0 beklenir
mv .env.bak .env
```

**Beklenen:** eksik anahtarın adı yazılır, hiçbir servis başlamaz.

### 2.5 İdempotent başlatma ve sıfırlama

```bash
make up && make up          # ikinci çalıştırma çalışan servisleri bozmaz
make reset                  # dışa aktarım → silme → yeniden başlatma → seed
ls exports/                 # audit-*.jsonl ve .sha256
```

**Beklenen:** `make reset` önce denetim kaydını `exports/` altına dışa aktarır (başarısızsa hiçbir
şey silmez), sonra çekirdek veriyi, koşu artefaktlarını, forge'u ve jira-sim'i demo başlangıcına
döndürür, `make seed` çalıştırır ve `ortam temiz` yazar.

### 2.6 Güvenlik kontrolleri

```bash
make security-check
```

**Beklenen:** 10 kontrolün hepsi `PASS`, özet `10/10`:

1. Host'a açılan tüm portlar yalnızca `127.0.0.1`.
2. `test-runner` içinden Postgres, core-api, playwright-mcp ve internete bağlantı başarısız (demo-app-web ve demo-app-api'ye başarılı).
3. `tp_app` rolü `audit_event` tablosunu güncelleyemez/silemez.
4. Depoda sır yok (gitleaks; geçmiş + commit edilmemiş dosyalar).
5. `demoapp_ro` (tutarlılık denetimi) yalnızca izinli tablo/kolonları okur; yazamaz, parola özeti ve sipariş verisi kapalı.
6. Model anahtarı değişkeni yalnızca `core-worker`'da tanımlı.
7. Ajan tarayıcısı (`playwright-mcp`) yalnızca demo-app-web'e erişir; `/api/test/*` kapalı; yalnızca core-worker MCP'ye bağlanır.
8. Jira/Xray/GitHub yazma kimlikleri yalnızca `core-worker`'da; `DEMOAPP_TEST_TOKEN` yalnızca demo-app-api ve test-runner'da.
9. Merge kapısı (`checks/<sha>.json`) ayrı volume'de: yalnızca toolchain-worker yazar, test-runner göremez ve belirteç taşımaz.
10. CI/test imajlarında ajan yok: test-runner ve toolchain-worker'da MCP, `anthropic` ve ajan SDK'sı çözülemez.

Herhangi biri `FAIL` ise komut ≠ 0 döner; çıktıdaki kontrol adıyla §6'ya bakın.

### 2.7 Örnek uygulama testleri

```bash
make e2e-smoke                       # forge main'deki e2e testleri test-runner içinden
E2E_BREAK_VERIFY=1 make e2e-smoke    # ayrıca kampanya kırılması: yeşil → kırmızı → yeşil
make locator-break-verify            # locator kırılması → yalnızca testId onarımı → yeşil (çevrimdışı)
```

### 2.8 Kaynak kullanımı (opsiyonel)

```bash
docker stats --no-stream
```

**Beklenen:** toplam bellek ≤ 10 GB.

## 3. Demoyu oynatmak

Tam sunucu senaryosu, rol başına tarayıcı oturumları ve aksaklık rehberi:
[DEMO-AKISI.md](DEMO-AKISI.md). Kısa yol:

```bash
make reset               # temiz başlangıç
make demo-reset          # main → demo-baseline, demo-app-web derlenir, baseline CI kuyruğa girer
make demo-web-sync A=--watch   # ayrı terminalde, portaldaki "Buton kimliğini değiştir" için açık kalır
```

1. **Demo-A** (analist): Gereksinimler → "Jira'dan çek" → TPD-1 → "Ön incelemeyi başlat" →
   F1 ve F3 **Dokümanı düzelt**, F2 ve F4 **Kod/veri hatalı** → "Düzeltmeleri Jira'ya yaz" → PO
   jira-sim'de onaylar → "Case üret" → onay → yayın.
2. `make demo-check` → çıkış `0` ve `C3 DEFECT ADAYI` (değilse F2 yanlış karar almıştır).
3. **Demo-B** (muhendis): Kod üretimi → C1, C2, C3, C5 → kırarak doğrula → merge → push CI.
4. **Faz 4**: C3 defect adayı → triage → testçi "TPD-5 kaydına bağla"; sunucu "Buton kimliğini değiştir" →
   muhendis "Onarım PR'ı aç" → merge → yeşil.

Bütün AI çıktıları **REPLAY** rozetlidir; bu, dış hesap bağlanana kadar beklenen durumdur.

## 4. Günlük çalışma

| Ne zaman | Komut |
|---|---|
| Güne başlarken | `make up` |
| Durumu görmek | `make status` |
| Bir servisin logları | `make logs S=core-worker` (S verilmezse tümü) |
| Gün sonu (veri korunur) | `make down` |
| Temiz başlangıç (prova öncesi) | `make reset` |
| Demo durumunu başa almak (veri korunur) | `make demo-reset` |
| Sunum öncesi otomatik prova | `make demo-prova RUNS=3` — koşu başına ~10,5 dk makine süresi (`make reset` dahil), 3 koşu ≈ 31–32 dk; `uv` zorunlu (ayrıntı: [rehearsal/README.md](../rehearsal/README.md); `UI=1` / `UITUR=1` için bir kez `cd rehearsal/ui && npm ci && npx playwright install chromium`) |
| Denetim kaydını almak | `make export-audit` |
| Disk temizliği | `make prune` |
| Tüm hedefler | `make help` |

Konteyner dışında test (paket başına kalite kapısı, MIMARI-SOZLESME §7):

```bash
(cd core && uv run ruff check && uv run ruff format --check && uv run pytest -q)
(cd review-portal && npm ci --ignore-scripts && npm run build && npm test)
```

## 5. Sırlar ve gerçek sistemler

- `.env` **asla commit edilmez** (`.gitignore`'da). Depoda yalnızca açıklamalı `.env.example` bulunur.
  Ekran paylaşırken `.env`'i açmayın; değerleri terminale yazdırmayın.
- Yerel parolaları `make env` üretir; elle doldurmanız gerekmez.
- Dış sistem anahtarları (`ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, Jira okuma/yazma
  kullanıcıları, Xray, GitHub App/token) `.env.example`'da listelidir ve boş kalabilir; boşken
  simülatörler ve REPLAY kullanılır. Geçiş ve doğrulama komutları:
  [GERCEK-SISTEMLER.md](GERCEK-SISTEMLER.md).
- **Sauce Labs** kimliği (`SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`) yerel `.env`'de değil, yalnızca
  **GitHub Actions secret** olarak tutulur.
- Model anahtarı ve yazma kimlikleri yalnızca `core-worker`'a verilir; toolchain servislerine ve CI'a
  asla (`make security-check` 6, 8, 10).
- Bir sırrı yanlışlıkla commit ettiyseniz: sırrı hemen iptal edip yenileyin, sonra ekibe haber verin.
  `make security-check` depo taramasını her çalıştırmada yapar.

## 6. Sorun giderme

**Ortam**

| Belirti | Çözüm |
|---|---|
| `make up` port çakışması bildiriyor | Çakışan süreci kapatın (`lsof -iTCP:<port> -sTCP:LISTEN`) veya `.env`'de ilgili portu değiştirin (`PG_PORT`, `TP_API_PORT`, `TP_PORTAL_PORT`, `DEMO_WEB_PORT`, `JIRA_SIM_PORT`) |
| Bellek yetersiz uyarısı | Docker Desktop → Settings → Resources → Memory ≥ 8 GB, Apply & Restart |
| Disk yetersiz (< 30 GB) | `make prune`; gerekirse Docker Desktop disk limitini artırın veya `docker system df` ile büyük öğelere bakın |
| Bir servis `unhealthy` / `make up` süre aşımı | `make logs S=<servis>`; `make status` ile hangi bağımlılığın bozuk olduğunu kontrol edin |
| `migrate` başarısız, DB bozuk/tutarsız | `make reset` (önce denetim kaydını dışa aktarır) |
| `make reset` dışa aktarımda duruyor | Bilerek: dışa aktarım başarısızsa hiçbir şey silinmez. `make logs S=postgres`, sonra tekrar deneyin. Yarıda kesilen reset tekrar çalıştırılabilir |
| `PLAYWRIGHT_VERSION` hatası | `make env` (sürümü `.playwright-version`'dan `.env`'e yazar), sonra `make up` |
| `TP_TOOLCHAIN_TOKEN` / `DEMOAPP_RO_PASSWORD` eksik hatası | Eski bir `.env`: `make env` yalnızca boş anahtarları doldurur, sonra `make up` |
| `make status` "çalışmıyor" | Ortam kapalı; `make up` |
| Docker daemon'a bağlanılamıyor | Docker Desktop'ı (veya Colima'yı) başlatın, `docker info` ile doğrulayın |
| "Manuel baz değer girilmedi" / "Varsayılan manuel baz değer yok" | Bilgi: manuel case hazırlama süresi story başına ölçülmedikçe kazanç oranı gösterilmez. Ölçüm portalda gereksinim detayından (analist/PO) giren ve kaynak notuyla girilir; değer uydurulmaz. `TP_MANUAL_BASELINE_S` yalnızca "varsayılan"dır ve kazanca girmez |

**Demo**

| Belirti | Çözüm |
|---|---|
| Portal "Canlı olaylar" kırmızı / giriş ekranına atıyor | Oturum kapanmış ya da parola değişmiş; yeniden giriş yapın |
| AI çıktısında **REPLAY-MISS** rozeti | Girdi golden beyanıyla eşleşmedi (ör. Jira içeriği elle değişti). Dürüst etikettir; `make reset` ile başa dönün |
| `make demo-check` başarısız ("defect adayı yok") | Demo-A'da F2 "Dokümanı düzelt" seçilmiş; `make reset`, Demo-A'yı F2 ve F4 **Kod/veri hatalı** ile tekrarlayın |
| "Buton kimliğini değiştir" / `make break` 409, "yeşil temel koşu yok" | `make reset` sonrası veritabanında koşu yoktur: `make demo-reset`, baseline koşu yeşil bitince kırın |
| "Demo uygulaması hâlâ yeniden kurulmadı" | core-worker imaj derleyemez: host'ta `make demo-web-sync A=--watch` açık olmalı |
| Kırık locator koşusunda hatalar `environment`/`unknown` | Uygulama koşu ortasında yeniden derlendi; önceki CI koşusu bitmeden kırmayın. `make demo-reset`, sonra tekrar |
| Locator demosundan sonra kod üretimi reddediliyor | REPLAY kod üretimi başlangıç testId'sini (`add-to-cart`) ister: `make demo-baseline` ya da `make demo-reset` |
| PO onayı portala gelmiyor | PO jira-sim'de `po@sim.local` ile giriş yapıp **Story** üzerinde onay düğmesine basmalı; portal 15 sn'de bir sorgular |
| Yayın "Jira'da story yok" hatasıyla duruyor | jira-sim elle sıfırlanmış; `make reset` |
| GitHub kipinde locator kırma 409 | Bilerek: locator demosu yalnızca `TP_FORGE=local` |
| `make eval-live`: "uv bulunamadı" | Host'a `uv` kurun (komut host'ta koşar; compose'da `rules/` salt okunurdur) |
| `scripts/eval-live.sh --ping`: HTTP 400 `anthropic-workspace-id` | `.env`'e `ANTHROPIC_WORKSPACE_ID` ekleyin ya da çalışma alanı anahtarı kullanın (GERCEK-SISTEMLER §1) |

**Colima:** Docker Desktop yerine Colima kullanılabilir; compose dosyası Docker Desktop'a özgü özellik
kullanmaz. Yeterli kaynakla başlatın, ör. `colima start --cpu 4 --memory 8 --disk 64`.

## 7. Hatlar ve sahiplik

| Hat | Kişi | Alan | Dizinler |
|---|---|---|---|
| A | Gökhan | Çekirdek, Jira, portal | `core/`, `review-portal/`, `infra/`, `sims/` |
| B | Hakan | Örnek uygulama, test, CI, Sauce | `demo-app/`, `toolchain/`, `.github/` |
| C | İsmail | AI: model geçidi, ön inceleme, case/kod üretimi, triage | `core/` (model geçidi), `rules/` |

Kendi özelliğinize başlamadan önce:

1. [TEKNIK-TASARIM.md](TEKNIK-TASARIM.md) içinde ilgili bölümü ve
   [MIMARI-SOZLESME.md](MIMARI-SOZLESME.md) §3 kod sahipliğini okuyun.
2. Özelliği Spec Kit ile açın; çıktılar `specs/<numara>-<ad>/` altına yazılır.
3. Her değişiklik PR ile gelir; `main`'e doğrudan push yoktur. Prompt/kural değişikliği canlı
   değerlendirmeden geçmeden birleştirilmez (`rules/README.md`).

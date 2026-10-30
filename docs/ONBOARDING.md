# Yeni ekip üyesi rehberi

Hedef: repoyu hiç kurmamış biri, yardım almadan **30 dakika içinde** ortamı ayağa kaldırır ve
`make security-check` ile **4/4 PASS** görür. İlk kurulumda imaj indirme ve build süresi ≤ 20 dk,
ısınmış imajlarla `make up` ≤ 3 dk'dır.

Genel bakış için önce [README](../README.md)'yi, çalışma kuralları için
[constitution](../.specify/memory/constitution.md)'ı okuyun.

## 1. Önkoşullar

| Gereksinim | Not |
|---|---|
| Apple Silicon Mac (arm64) | İmajlar amd64 için de mevcuttur (CI uyumu); birincil hedef Apple Silicon |
| Docker Desktop 29.x | Settings → Resources → **Memory ≥ 8 GB**. Rosetta gerekmez (tüm imajlar `linux/arm64`). Alternatif: Colima (bkz. Sorun giderme) |
| ≥ 30 GB boş disk | `make up` kontrol eder; Docker Desktop disk limiti için 64 GB önerilir |
| `git`, `make` | macOS'ta Xcode Command Line Tools ile gelir (`xcode-select --install`) |
| `uv`, `node` 22 | **Opsiyonel**; yalnızca konteyner dışında yerel geliştirme/test için. Ortamı çalıştırmak için gerekmez |
| GitHub erişimi | Repoya SSH anahtarıyla clone yetkisi |

Docker'ın çalıştığını doğrulayın:

```bash
docker info --format '{{.MemTotal}}'   # ≥ 8000000000 (yaklaşık 8 GB) olmalı
```

## 2. Kurulum ve doğrulama

Adımlar [quickstart.md](../specs/001-dev-foundation/quickstart.md) ile aynıdır.

### 2.1 Clone ve sırlar dosyası

```bash
git clone git@github.com:ThinkGOtr/testingprobe.git && cd testingprobe
make env
```

**Beklenen:** `.env hazır`. `make env`, `.env.example`'dan `.env` üretir ve F0'da zorunlu
parolaları (`POSTGRES_PASSWORD`, `TP_OWNER_PASSWORD`, `TP_APP_PASSWORD`, `DEMOAPP_OWNER_PASSWORD`,
`DEMOAPP_PASSWORD`, `SEED_USER_PASSWORD`) rastgele doldurur. `.env` zaten varsa dokunmaz.

### 2.2 Ortamı başlatma

```bash
make up
```

**Beklenen:** komut `0` ile biter ve sonunda `make status` tablosu basılır; tüm servisler
`healthy`. `make up` önce önkoşulları (Docker, disk, bellek, zorunlu sırlar, port çakışması)
kontrol eder; eksik varsa hangisi olduğunu yazar ve **hiçbir servisi başlatmaz**. Bir servis
5 dk içinde sağlıklı olmazsa adını ve son 20 log satırını gösterir.

### 2.3 Durum ve adresler

```bash
make status
```

**Beklenen:** her servisin adı, durumu, sağlığı ve yerel adresi:

| Adres | Ne |
|---|---|
| http://127.0.0.1:8080 | Review portal |
| http://127.0.0.1:8000/health | core-api sağlık |
| http://127.0.0.1:8081 | Örnek uygulama |
| http://127.0.0.1:8931 | Playwright MCP |
| `127.0.0.1:55432` | Postgres |

### 2.4 Eksik sır senaryosu (opsiyonel doğrulama)

```bash
mv .env .env.bak && cp .env.example .env && make up; echo $?   # ≠ 0 beklenir
mv .env.bak .env
```

**Beklenen:** eksik anahtarın adı yazılır, hiçbir servis başlamaz.

### 2.5 İdempotent başlatma

```bash
make up && make up
```

**Beklenen:** ikinci çalıştırma çalışan servisleri bozmaz.

### 2.6 Başlangıç verisi ve sıfırlama

```bash
make seed && make seed      # ikinci çalıştırma: "seed: 5 kullanıcı (yeni: 0)"
make reset && make seed
ls exports/                 # audit-*.jsonl ve .sha256
```

**Beklenen:** seed kullanıcıları (`analist`, `muhendis`, `sunucu`, `po`, `testci`) her seferinde
aynı kimliklerle yüklenir. `make reset` önce denetim kaydını `exports/` altına dışa aktarır, sonra
veriyi siler ve ortamı yeniden başlatır; `reset + seed` ≤ 2 dk.

### 2.7 Güvenlik kontrolleri

```bash
make security-check
```

**Beklenen:** 4 kontrolün hepsi `PASS`, özet `4/4`:

1. Host'a açılan tüm portlar yalnızca `127.0.0.1`.
2. `test-runner` içinden Postgres, core-api ve internete bağlantı başarısız.
3. `tp_app` rolü `audit_event` tablosunu güncelleyemez/silemez.
4. Depoda sır yok (gitleaks).

Herhangi biri `FAIL` ise komut ≠ 0 döner; çıktıdaki kontrol adıyla Sorun giderme bölümüne bakın.

### 2.8 Kaynak kullanımı (opsiyonel)

```bash
docker stats --no-stream
```

**Beklenen:** toplam bellek ≤ 10 GB.

## 3. Günlük çalışma

| Ne zaman | Komut |
|---|---|
| Güne başlarken | `make up` |
| Durumu görmek | `make status` |
| Bir servisin logları | `make logs S=core-api` (S verilmezse tümü) |
| Gün sonu (veri korunur) | `make down` |
| Temiz başlangıç (demo/prova öncesi) | `make reset && make seed` |
| Denetim kaydını almak | `make export-audit` |
| Disk temizliği | `make prune` |

Tüm hedeflerin sözleşmesi: [contracts/make-targets.md](../specs/001-dev-foundation/contracts/make-targets.md).

## 4. Sırlar

- `.env` **asla commit edilmez** (`.gitignore`'da). Depoda yalnızca açıklamalı `.env.example` bulunur.
- F0'da yalnızca yerel parolalar zorunludur ve `make env` bunları üretir; elle doldurmanız gerekmez.
- Sonraki özelliklerin anahtarları (`ANTHROPIC_API_KEY`, Jira, Xray, GitHub App, `GITHUB_READ_TOKEN`,
  `DEMOAPP_RO_PASSWORD`) `.env.example`'da listelidir ve F0'da boş kalabilir; ilgili özellik
  başladığında doldurulur. Sözleşme: [contracts/env.md](../specs/001-dev-foundation/contracts/env.md).
- **Sauce Labs** kimliği (`SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`) yerel `.env`'de değil, yalnızca
  **GitHub Actions secret** olarak tutulur.
- Model anahtarı ileride yalnızca `core-worker`'a verilir; toolchain servislerine ve CI'a asla.
- Bir sırrı yanlışlıkla commit ettiyseniz: sırrı hemen iptal edip yenileyin, sonra ekibe haber verin.
  `make security-check` depo taramasını her çalıştırmada yapar.

## 5. Sorun giderme

| Belirti | Çözüm |
|---|---|
| `make up` port çakışması bildiriyor | Çakışan süreci kapatın (`lsof -iTCP:<port> -sTCP:LISTEN`) veya `.env`'de ilgili portu değiştirin (`PG_PORT`, `TP_API_PORT`, `TP_PORTAL_PORT`, `DEMO_WEB_PORT`, `MCP_PORT`) |
| Bellek yetersiz uyarısı | Docker Desktop → Settings → Resources → Memory ≥ 8 GB, Apply & Restart |
| Disk yetersiz (< 30 GB) | `make prune`; gerekirse Docker Desktop disk limitini artırın veya `docker system df` ile büyük öğelere bakın |
| Bir servis `unhealthy` / `make up` süre aşımı | `make logs S=<servis>` ile log'a bakın; `make status` ile hangi servisin bağımlılığının bozuk olduğunu kontrol edin |
| `migrate` başarısız, DB bozuk/tutarsız | `make reset` (önce denetim kaydını dışa aktarır), ardından `make seed` |
| `make reset` dışa aktarımda duruyor | Bilerek: dışa aktarım başarısızsa hiçbir şey silinmez. `make logs S=postgres` ile Postgres'i kontrol edin, sonra tekrar deneyin. Yarıda kesilen reset tekrar çalıştırılabilir |
| `PLAYWRIGHT_VERSION` hatası | `docker compose`'u doğrudan çalıştırmayın; her zaman `make` hedeflerini kullanın |
| `make status` "çalışmıyor" | Ortam kapalı; `make up` |
| Docker daemon'a bağlanılamıyor | Docker Desktop'ı (veya Colima'yı) başlatın, `docker info` ile doğrulayın |

**Colima:** Docker Desktop yerine Colima kullanılabilir; compose dosyası Docker Desktop'a özgü özellik
kullanmaz. Yeterli kaynakla başlatın, ör. `colima start --cpu 4 --memory 8 --disk 64`.

## 6. Hatlar ve sahiplik

| Hat | Kişi | Alan | Dizinler |
|---|---|---|---|
| A | Gökhan | Çekirdek, Jira, portal | `core/`, `review-portal/`, `infra/` |
| B | Hakan | Örnek uygulama, test, CI, Sauce | `demo-app/`, `toolchain/`, `.github/` |
| C | İsmail | AI: model geçidi, ön inceleme, case/kod üretimi, triage | `core/` (model geçidi), `rules/` |

Kendi özelliğinize başlamadan önce:

1. [TEKNIK-TASARIM.md](TEKNIK-TASARIM.md) içinde ilgili bölümü (§17 teslimat sırası) okuyun.
2. Özelliği Spec Kit ile açın; çıktılar `specs/<numara>-<ad>/` altına yazılır.
3. Her değişiklik PR ile gelir; `main`'e doğrudan push yoktur.

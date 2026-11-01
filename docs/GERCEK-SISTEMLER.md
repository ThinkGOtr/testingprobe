# Simülatörden gerçek sisteme geçiş

Demo, dış hesap olmadan **uçtan uca** çalışır: her dış sistem `core/src/tp_core/ports.py`'deki bir
port arkasındadır ve gerçek adaptörle yerel simülatör **aynı kodu** kullanır
([MIMARI-SOZLESME §1](MIMARI-SOZLESME.md#1-dış-sistemler-port--adaptör--yerel-simülatör)). Bu belge
her simülatörün gerçek sisteme nasıl çevrileceğini ve geçişin nasıl doğrulanacağını anlatır.

| Sistem | Bugün (varsayılan) | Gerçek | Seçim |
|---|---|---|---|
| Model | REPLAY (`rules/replay/` golden kayıtları) | Anthropic API (Claude) | `TP_MODEL_MODE`, `ANTHROPIC_API_KEY` |
| Jira | `jira-sim` (REST v3 alt kümesi) | Jira Cloud | `JIRA_BASE_URL` + okuma/yazma kullanıcıları |
| Test yönetimi | Jira Test issue (jira-sim üzerinde) | Jira Test issue · Xray Cloud | `TP_TEST_MGMT=jira\|xray` |
| Git forge + CI | LocalForge + yerel test-runner (`local-ci`) | GitHub (App/token, ruleset, Actions) | `TP_FORGE=local\|github` |
| Bulut tarayıcı | yok (yerel Chromium) | Sauce Labs (yalnızca GitHub Actions'ta) | GitHub secret'ları |

## 0. Her geçişte geçerli kurallar

- **Sırlar yalnızca `.env`'de** (git dışı) ya da GitHub secret'ında durur. Hiçbir komut sırrı
  ekrana, log'a veya komut satırı argümanına yazmamalıdır; aşağıdaki doğrulama komutları buna göre
  yazıldı. Sunum/ekran paylaşımı sırasında `.env` açılmaz.
- **Yazma kimlikleri ve model anahtarı yalnızca `core-worker`'a verilir** (compose bunu zaten
  yapar). Değişiklikten sonra `make security-check` → `Özet: 10/10` (kontrol 6: model anahtarı yeri,
  kontrol 8: yazma kimlikleri yeri).
- `.env` değişikliği `make up` ile uygulanır (değişen servisler yeniden oluşturulur; veri korunur).
- **Dürüst etiket:** canlı olmayan her AI çıktısı portalda REPLAY/REPLAY-MISS olarak görünür; canlıya
  geçilmeden "canlı" denmez.
- Demo sonrası tüm token ve anahtarlar iptal edilir (TEKNIK-TASARIM §14).

Doğrulama komutlarında `.env`'den tek bir değeri **ekrana basmadan** okumak için:

```bash
envv() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-; }   # kullanım: "$(envv JIRA_BASE_URL)"
```

## 1. Anthropic (model)

### 1.1 Durum

`.env` bugün `TP_MODEL_MODE=replay`'e sabitlidir; portaldaki her AI çıktısı REPLAY rozetlidir.
`.env`'deki mevcut anahtar bir çalışma alanıyla (workspace) eşleştirilmemiştir: API bu anahtarla
`400` döner ve `anthropic-workspace-id` başlığını ister. İki çözüm:

- **(a) `ANTHROPIC_WORKSPACE_ID`** — model geçidi değişken doluysa her isteğe
  `anthropic-workspace-id` başlığını ekler (değer sır gibi ele alınır, loglanmaz). Host'ta koşan
  `make eval-live` değeri `.env`'den kendisi okur; compose değişkeni yalnızca core-worker'a verir
  (`ANTHROPIC_API_KEY`'in yanında; `make up` ile uygulanır, `make security-check` 6 başka serviste
  olmadığını denetler). Portal `/yol-haritasi` şeridi core-worker'ın açılışta bildirdiği kipi gösterir;
  "çalışma alanı var/yok" bilgisi `GET /demo/status` → `model.calisma_alani_var`'dadır (değer asla).
- **(b) Yeni anahtar** — Console'da demo için ayrılmış bir çalışma alanında yeni bir anahtar
  oluşturun; API yine başlık isterse (a) ile birlikte kullanın.

### 1.2 Anahtar

1. Anthropic Console → **Workspaces** → demo için ayrı bir çalışma alanı (ör. `testing-probe`) ve
   harcama limiti; o çalışma alanında API anahtarı. Çalışma alanı kimliği Console'daki çalışma alanı
   ayarlarındadır.
2. `.env`:

   ```dotenv
   ANTHROPIC_API_KEY=<anahtar>
   ANTHROPIC_WORKSPACE_ID=<çalışma alanı kimliği>   # anahtar başlık istiyorsa
   TP_MODEL_MODE=replay        # önce doğrulama (1.4); sonra auto | live | record (1.3)
   TP_DAILY_BUDGET_USD=30      # günlük tavan (UTC günü)
   TP_WORKFLOW_BUDGET_USD=2    # iş akışı başına tavan
   TP_EVAL_BUDGET_USD=5        # make eval-live koşusunun sert tavanı
   ```

3. `make up`, sonra `make security-check` (anahtar yalnızca core-worker'da olmalı).

### 1.3 Mod seçimi

| `TP_MODEL_MODE` | Davranış |
|---|---|
| `replay` | Anahtar olsa da kullanılmaz; golden kayıtlar (portal: REPLAY) |
| `auto` | Anahtar varsa `live`, yoksa `replay` |
| `live` | Anthropic API; anahtar yoksa açık hata |
| `record` | `live` + başarılı çıktıyı `rules/replay/<amaç>/<anahtar>.json`'a yazar. Compose `rules/`'u core-worker'a salt okunur bağlar; konteynerde `record` için bu bağlamanın yazılabilir yapılması gerekir (compose değişikliği, entegrasyon liderinin işi). Golden adaylarını commit'li dosyalara dokunmadan üretmek için `make eval-live` `--record` kullanın (1.5) |

`TP_REPLAY_STRICT=1`: REPLAY'de girdisi beyana uymayan golden'a düşmek yerine hata (prova kipi).
`make eval-live` `TP_MODEL_MODE`'u okumaz: komutun kendisi canlı çağrı isteğidir; demo yolunun kipi
değişmez.

### 1.4 Doğrulama

```bash
scripts/eval-live.sh --ping      # make eval-live ile de çağrılır (argüman sözdizimi: make help)
# Beklenen: "Canlı bağlantı denetimi: model …, çalışma alanı başlığı gönderildi|gönderilmedi"
#           ve "OK: yanıt modeli …". Hata: API'nin hata türü ve iletisi (anahtar/kimlik yazdırılmaz).
#           "400 … anthropic-workspace-id" → ANTHROPIC_WORKSPACE_ID eksik (1.1).

docker compose exec -T core-worker python -c \
  "from tp_core.gateway.config import GatewaySettings, resolve_mode; print(resolve_mode(GatewaySettings()))"
# core-worker'ın etkin modu: TP_MODEL_MODE=auto/live iken "live", aksi halde "replay"
```

### 1.5 Canlı değerlendirme (`make eval-live`, constitution X)

Prompt/kural değişikliği, değerlendirme seti **canlı modelle** koşturulmadan birleştirilmez. Bugün
her prompt paketi `rules/evaluations.yaml`'da `pending` ("canlı değerlendirme bekliyor").
`make eval-live` = `scripts/eval-live.sh` (host'ta, `uv` ile; `.env`'den yalnızca
`ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, `TP_EVAL_BUDGET_USD`, `TP_MODEL_PROVIDER`,
`TP_PII_MASKING`'i okur ve yazdırmaz):

```bash
scripts/eval-live.sh --dry-run                       # API çağrısı yok: setler + tahmini maliyet
scripts/eval-live.sh --bundle triage                 # canlı koşu, sert tavan TP_EVAL_BUDGET_USD (5)
scripts/eval-live.sh --bundle triage --update-status # set TAMAMEN geçerse evaluations.yaml → evaluated
scripts/eval-live.sh --record                        # golden adayları exports/eval-live/<zaman>/replay-adaylari/
cd core && uv run python -m tp_core.gateway.evaluation --check   # birleştirme kapısı: pending/bayat → çıkış 1
```

- Bugün set bulunan paketler: `triage`, `bug-draft`, `dup-rank` (`rules/evaluation/*.json`). Seti
  olmayan paketler (requirement-review, consistency-check, case-generation, verify-and-map,
  guardrails) atlanır ve durumları değişmez.
- Rapor `rules/evaluation/results/<paket>-v<sürüm>-<tarih>.json`'a yazılır. Her vakadan önce en kötü
  durum maliyeti tavana eklenir; tavan aşılacaksa koşu durur.
- `--record` commit'li golden'lara (`rules/replay/**`) asla yazmaz; adaylar insan incelemesinden
  sonra PR ile taşınır. `evaluations.yaml` değişikliği de PR ile gelir; `waived` istisnasını yalnızca
  sahip yazar.

### 1.6 Canlıya geçince

- Portalda canlı AI çıktılarının rozeti REPLAY'den çıkar; `ai_call` satırlarında gerçek model, token
  ve maliyet görünür.
- REPLAY'de AI süresi ~0'dır; canlıda "AI + review" süresi gerçek AI süresini de içerir.
- Müşteri verisi işlenecekse `TP_PII_MASKING=1` zorunludur (constitution VII).

## 2. Jira Cloud

### 2.1 Site ve proje

| Gereken | Not |
|---|---|
| Site | `https://<site>.atlassian.net` |
| Proje | Anahtar `TPD` (başka anahtar için `JIRA_PROJECT`). Demo anahtarları sabittir (TPD-1..TPD-7): **boş bir projeyle** başlayın |
| Issue türleri | `Story`, `Bug`; `Test` önerilir (yoksa Test yerine `Task` açılır) |
| Bağlantı türleri | `Relates` (varsayılan Jira'da var); `Test` bağlantı türü önerilir (yoksa `Relates` kullanılır) |
| İş akışı | "Done" kategorisinde bir durum (koşu kayıtlarını kapatmak için) |
| Kabul kriterleri | Açıklamada "Kabul Kriterleri" başlığı + `AC<n>: ...` satırları. Sitede AC ayrı bir özel alandaysa kod uyarlaması gerekir (`RestJira(content_fields=...)`) |

### 2.2 Kullanıcılar (en az yetki)

| Kullanıcı | Yetki | `.env` |
|---|---|---|
| Okuma | Yalnızca TPD'de *Browse projects* | `JIRA_READ_EMAIL`, `JIRA_READ_TOKEN` |
| Yazma (ürünün bot kullanıcısı) | Yalnızca TPD'de: *Browse*, *Create issues*, *Edit issues*, *Add comments*, *Link issues*, *Transition issues*; *Delete issues* yalnızca `jira_seed --sil` için | `JIRA_WRITE_EMAIL`, `JIRA_WRITE_TOKEN` |
| PO (insan) | Story'lere yorum ve etiket | `JIRA_PO_ACCOUNT_IDS` (accountId) |

API token'ları: id.atlassian.com → Security → API tokens (her kullanıcı kendi token'ını üretir).

### 2.3 `.env`

```dotenv
JIRA_BASE_URL=https://<site>.atlassian.net
JIRA_BROWSE_URL=https://<site>.atlassian.net   # zorunlu: boş kalırsa compose jira-sim adresini kullanır
JIRA_PROJECT=TPD
JIRA_READ_EMAIL=<okuma kullanıcısı e-postası>
JIRA_READ_TOKEN=<okuma API token'ı>
JIRA_WRITE_EMAIL=<yazma kullanıcısı e-postası>
JIRA_WRITE_TOKEN=<yazma API token'ı>
JIRA_PO_ACCOUNT_IDS=<PO accountId>[,<ikinci PO>]  # boşsa gerçek Jira'da hiçbir onay kabul edilmez
TP_JIRA_BOT_ACCOUNT_IDS=<yazma kullanıcısının accountId'si>  # bot etiketi onay sayılmaz
TP_PO_JIRA_USERS=                                 # isteğe bağlı ek izin listesi
```

PO onayı yalnızca e-posta/accountId ile eşlenir (görünen ad asla); ürün `tp-po-approved` etiketini
**hiçbir zaman kendisi eklemez**.

accountId'yi bulmak (yalnızca accountId basılır):

```bash
curl -fsS -G -u "$(envv JIRA_READ_EMAIL):$(envv JIRA_READ_TOKEN)" \
  "$(envv JIRA_BASE_URL)/rest/api/3/user/search" --data-urlencode "query=<po e-postası>" \
  | python3 -c 'import json,sys; [print(u["accountId"], u.get("displayName","")) for u in json.load(sys.stdin)]'
```

### 2.4 Demo verisini yükleme

1. Boş TPD projesinde **sırayla** yedi kayıt açın (anahtarlar sırayla verilir):

   | Anahtar | Tür | Özet | Durum |
   |---|---|---|---|
   | TPD-1 | Story | Kampanyalı sepet ve sipariş onayı | To Do |
   | TPD-2 | Story | Sipariş geçmişini tarihe göre filtreleme | To Do |
   | TPD-3 | Story | Ürün arama | To Do |
   | TPD-4 | Story | Bayi girişi | To Do |
   | TPD-5 | Bug | Kampanya indirimi sepette yanlış hesaplanıyor | açık (To Do) |
   | TPD-6 | Bug | Sipariş geçmişinde tarih sıralaması ters görünüyor | In Progress |
   | TPD-7 | Bug | Giriş sayfasında hata mesajı İngilizce görünüyor | Done |

   Bug açıklamalarını simülatörün tohumundan kopyalayın: `sims/jira-sim/src/jira_sim/seed.py`
   (TPD-5'in beklenen/gerçekleşen değerleri mükerrer araması için önemlidir).
2. Story içeriklerini `make jira-seed` ile yükleyin — açıklama ve kabul kriterleri
   `docs/DEMO-VERISI.md`'deki içerikle birebir yazılır, koşu etiketleri temizlenir, `tp-demo`
   eklenir:

   ```bash
   make up
   make jira-seed          # kuru çalışma: yalnızca plan yazdırır
   make jira-seed ONAY=1   # uygular (yazma kullanıcısıyla, core-worker içinden)
   ```

3. Provalar arasında: `make reset` gerçek Jira'da önce planı yazdırır ve onay (`e`) ister; ya da
   doğrudan `make jira-seed ONAY=1` (tp-<uuid> etiketli Test/Bug kayıtları "Done"a geçirilerek
   kapatılır; silmek için `--sil`). `make demo-reset` **gerçek Jira'ya dokunmaz**.

### 2.5 Doğrulama

```bash
make jira-seed
# Beklenen: "Jira demo başlangıcı (https://<site>.atlassian.net, proje TPD):" ve TPD-1..4 için
# "demo içeriğinde, değişiklik yok"; "Jira'da bulunamadı" satırı olmamalı.
make security-check     # 10/10; JIRA_WRITE_* yalnızca core-worker'da
```

Portalda: analist **Gereksinimler → "Jira'dan çek"** → TPD-1..TPD-4 listelenir; story bağlantıları
`https://<site>.atlassian.net/browse/...`'e gider. PO kapısı denemesi: inceleme sonrası PO Jira'da
`tp-po-approved` etiketini koyar → ≤15 sn içinde portalda "PO onaylı"; aynı etiketi yazma (bot)
kullanıcısı koyarsa onay **sayılmaz**.

> Not: Tasarım belgesindeki Rovo MCP okuma yolu bu sürümde yoktur; okuma da Jira REST v3 ve API
> token'ıyla yapılır.

## 3. Xray Cloud

Önkoşul: 2. bölüm (Xray, story bağlantısını Jira REST ile kurar) ve demo sitesinde kurulu Xray Cloud
uygulaması (TPD projesinde etkin).

1. Xray → **Global settings → API Keys** → yazma kullanıcısına bağlı bir anahtar (client id + secret).
2. `.env`:

   ```dotenv
   TP_TEST_MGMT=xray
   XRAY_BASE_URL=https://xray.cloud.getxray.app   # bölgesel veri yerleşimi varsa o bölgenin adresi
   XRAY_CLIENT_ID=<client id>
   XRAY_CLIENT_SECRET=<client secret>
   ```

   Adaptör `XRAY_BASE_URL`'e `/api/v2` ekler; adres `/api/v2` içermemelidir.
3. `make up`, `make security-check`.

Doğrulama:

```bash
docker compose exec -T core-worker python -c \
  "from tp_core.integrations.xray import get_xray_client; get_xray_client().authenticate(); print('Xray: kimlik doğrulandı')"
```

Portalda **Yayın → "Yayın önizleme"** hedefi `xray` göstermeli; ilk yayından sonra Jira'da adımlı bir
*Test* issue'su ve story bağlantısı görünür. **Dürüst not:** Xray adaptörü bugüne kadar yalnızca
jira-sim'in Xray alt kümesine karşı test edildi; ilk gerçek koşuyu bir deneme projesinde yapın.

## 4. Sauce Labs

Sauce yalnızca **GitHub Actions**'taki `sauce` job'unda koşar (`.github/workflows/ci.yml`, ayrıntı
[.github/CI.md](../.github/CI.md#sauce)); yerel CI ve `.env` Sauce kullanmaz. Kimlik **yalnızca GitHub
secret'ı** olarak tutulur.

```bash
gh secret set SAUCE_USERNAME --repo <sahip>/<repo>     # değer istemle sorulur, ekrana basılmaz
gh secret set SAUCE_ACCESS_KEY --repo <sahip>/<repo>
gh variable set SAUCE_REGION --repo <sahip>/<repo> --body eu-central-1   # varsayılan us-west-1
```

Doğrulama:

```bash
gh workflow run ci.yml --repo <sahip>/<repo> -f tetik=manual
gh run list --repo <sahip>/<repo> --workflow ci.yml --limit 1          # koşu kimliği
gh run download <koşu-id> --repo <sahip>/<repo> -n sauce-results -D /tmp/sauce
python3 -c 'import json; d=json.load(open("/tmp/sauce/sauce.json")); print(d["durum"], d.get("job_url"))'
# Beklenen: durum "passed" (ya da "failed") ve bir job_url. "atlandi" = secret'lar okunamadı.
```

Notlar: job `continue-on-error`'dır (zorunlu check değil); eşzamanlılık 1. Sauce şu an Playwright en
fazla **1.61.1**'i desteklediği için `demo-app/.sauce/config.yml` bu sürüme sabitlidir (repo
`.playwright-version`'dan farklı).

## 5. GitHub modu (forge + CI)

### 5.1 GitHub tarafı

1. Repo: `demo-app/` bu repodaki düzenle (forge kökü `demo-app`, e2e kökü `demo-app/e2e`).
2. **Bot GitHub App**: Contents *read & write*, Pull requests *read & write*, Actions *read & write*,
   Checks *read*. Repoya kurun. Merge izni kullanılmaz; bot ruleset bypass listesine **eklenmez**.
3. **`demo-admin`**: insan hesabı + org'da onu içeren tek üyeli `demo-admin` takımı (ruleset bypass).
4. Ruleset (varsayılan kuru çalışma; uygulamak için `--apply`, `gh` org yöneticisi oturumuyla):

   ```bash
   scripts/github-ruleset.sh --repo <sahip>/<repo>            # gövdeyi yazdırır, API çağırmaz
   scripts/github-ruleset.sh --repo <sahip>/<repo> --apply    # tp-main: PR zorunlu, 1 onay + CODEOWNERS,
                                                               # zorunlu check: test-local, ast-guard, semgrep
   ```

5. İsteğe bağlı repo değişkenleri: `TP_BOT_LOGINS` (bot giriş adları, AST koruması modu),
   `TP_TOOLCHAIN_IMAGE` (digest'li toolchain imajı; boşsa runner kurulumu).

### 5.2 `.env`

```dotenv
TP_FORGE=github
GITHUB_REPO=<sahip>/<repo>
# Kimlik: App (önerilen) ...
GH_APP_ID=<app id>
GH_APP_PRIVATE_KEY=<PEM, satır sonları \n kaçışlı tek satır>
GH_APP_INSTALLATION_ID=                 # boşsa repodan bulunur
# ... ya da geliştirme için ince ayarlı token (aynı izinler)
GITHUB_TOKEN=
# Portal merge'ü: demo-admin'in (insan) token'ı. Bot asla merge etmez.
GITHUB_MERGE_TOKEN=<demo-admin token'ı>
# Tutarlılık denetiminin kod okuması (yalnızca contents:read)
GITHUB_READ_TOKEN=<salt okuma token'ı>
# toolchain-worker'ın PR commit'lerini çektiği salt okunur ayna (kırarak doğrulama için gerekli)
TP_FORGE_REMOTE_URL=https://github.com/<sahip>/<repo>.git
TP_FORGE_REMOTE_TOKEN=<salt okuma token'ı>
TP_E2E_ROOT=demo-app/e2e
TP_REQUIRED_CHECKS=                     # boş = test-local,ast-guard,semgrep
```

- `GH_APP_PRIVATE_KEY_PATH` yalnızca dosya core-worker konteynerinde görünürse işe yarar; compose
  böyle bir bağlama içermez, bu yüzden tek satırlık `GH_APP_PRIVATE_KEY` kullanın.
- `TP_FORGE_REMOTE_URL` boşsa GitHub modunda "Kırarak doğrula" tamamlanamaz ve merge açık kabul notu
  ister.
- **Locator kırma/onarım demosu yalnızca `TP_FORGE=local`'dır**: GitHub kipinde "Locator'ı kır" ve
  `make break` 409 `GITHUB_KIRILMA_YOK` ile reddeder (çalışan demo-app-web GitHub main'inden
  derlenmez).
- Portal merge'ü ruleset koşullarını kendisi değerlendirir; eksik varsa yalnızca `demo-admin` merge
  eder ve sonuç `bypass` olarak kaydedilir. Diğer mühendisler önce PR'ı GitHub'da onaylamalı ya da
  GitHub arayüzünden merge etmelidir (core bunu `review.kanal='github'` ile işler).

### 5.3 Tetikler

| Portal | GitHub |
|---|---|
| PR açılması / main'e merge | `pull_request` / `push` |
| Sunucu · Koşular → "Deploy tetikle" | `repository_dispatch` `deploy` (koşu adı `ci deploy [<kimlik>]`) |
| Sunucu · Koşular → "Gece koşusu" | `workflow_dispatch` `ci.yml` `tetik=nightly`; ayrıca zamanlanmış `0 2 * * *` (UTC) |

Core koşuyu adındaki `[<kimlik>]` ile bulur, artefaktları (`test-local-results`, `sauce-results`)
indirir; PR CI sonucu PR'a tek yorum olarak yazılır.

### 5.4 Doğrulama

```bash
docker compose exec -T core-worker python -c \
  "from tp_core.integrations.forge import get_forge; print(type(get_forge()).__name__)"
# Beklenen: GitHubForge

gh api repos/<sahip>/<repo>/rulesets --jq '.[].name'      # Beklenen: tp-main
make security-check                                         # 10/10; GH_APP_*, GITHUB_TOKEN yalnızca core-worker'da
```

Uçtan uca: mühendis bir onaylı case için kod üretir → GitHub'da `tp/case-*` dalında PR → `test-local`,
`ast-guard`, `semgrep` koşar → portalda merge kapısı → merge → `push` koşusu. Sunucu "Deploy tetikle"
→ `gh run list --repo <sahip>/<repo> --workflow ci.yml --limit 3` listesinde `ci deploy [...]`. Prova
listesindeki "bot main'e push dener → reddedilir" maddesi ruleset uygulandıktan sonra bot
kimliğiyle denenir.

## 6. Simülatöre geri dönmek

İlgili değişkenleri `.env`'de boşaltın (ya da `TP_MODEL_MODE=replay`, `TP_TEST_MGMT=jira`,
`TP_FORGE=local`), sonra `make up`. `JIRA_BASE_URL` boşken compose `jira-sim`'i, `JIRA_BROWSE_URL`
boşken jira-sim'in yerel adresini kullanır. Temiz başlangıç için `make reset`.

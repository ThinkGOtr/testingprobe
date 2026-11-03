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
| Kabul kriterleri | Açıklamada "Kabul Kriterleri" başlığı + `AC<n>: ...` satırları, ya da görev şablonunun "🔑 Acceptance Criteria (Kabul Kriterleri)" bölümü (başlık Jira başlığı ya da düz satır olabilir; bölümdeki öneksiz maddeler de AC'dir, "Not applicable" değildir). Sitede AC ayrı bir özel alandaysa kod uyarlaması gerekir (`RestJira(content_fields=...)`) |

### 2.2 Kullanıcılar (en az yetki)

| Kullanıcı | Yetki | `.env` |
|---|---|---|
| Okuma | Yalnızca TPD'de *Browse projects* | `JIRA_READ_EMAIL`, `JIRA_READ_TOKEN` |
| Yazma (ürünün bot kullanıcısı) | Yalnızca TPD'de: *Browse*, *Create issues*, *Edit issues*, *Add comments*, *Link issues*, *Transition issues*, *Delete all comments* (`jira-seed` yorum temizliği); *Delete issues* yalnızca `jira_seed --sil` için | `JIRA_WRITE_EMAIL`, `JIRA_WRITE_TOKEN` |
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
JIRA_HESAP_ANALIST=<accountId>                    # yorumlarda @bahsetme (boş = yok; 2.7)
JIRA_HESAP_PO=<accountId>
JIRA_HESAP_MUHENDIS=<accountId>
JIRA_HESAP_TESTCI=<accountId>
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
   kapatılır; silmek için `--sil`; TPD-1..7'deki **tüm yorumlar** silinir — tohumda yorum yoktur,
   hepsi koşuların izidir, elle yazılmış PO cevapları dahil). Kayıtlar arası bağlantılar
   (`Test`, `Relates`) kalır. `make demo-reset` **gerçek Jira'ya dokunmaz**.

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

### 2.6 Gerçek Jira Cloud'da gözlenenler (2026-11-01, iyzitrace.atlassian.net / TPD)

Doğrulama koşusu: TPD **team-managed** proje, Xray kurulu (Xray'in `Test` iş türü ve `Test`
bağlantı türü mevcut), REPLAY. Sonuçlar:

| Adım | Sonuç |
|---|---|
| `make jira-seed ONAY=1` | TPD-1..4 DEMO-VERISI içeriğine döndü, `tp-demo` eklendi |
| A1–A4 (çek → ön inceleme → F1/F3 `fix_doc`, F2/F4 `code_defect` → düzeltme Jira'ya → 2. tur) | Geçti: TPD-1 AC3 güncellendi, düzeltme ve PO soru yorumu yazıldı, `tp-po-pending` kondu |
| A5 PO etiketi (PO = yazma hesabı) | **Beklendiği gibi reddedildi**; etiket ürün tarafından kaldırıldı (aşağıdaki 1. madde) |
| F2 taslağı → mükerrer araması → TPD-5 | Geçti: JQL `text ~` yalnızca TPD-5'i buldu (high); testçi "bağla" → TPD-5'e kanıt yorumu + `Relates` TPD-1 |
| F4 → yeni Bug | Geçti: yeni Bug (`AI-generated`, `tp-<uuid>`, `tp-mod-replay`), `Relates` TPD-1 |
| Yayın adaptörü (`jira` ve `xray`), ürün akışı dışında doğrudan | Geçti: `jira` → Xray'in `Test` türünde issue (Xray'de Manual, Xray adımı yok; adımlar açıklama tablosunda); `xray` → Manual Test + Xray adımları; ikisi de story'ye `Test` bağlantısıyla bağlandı |

1. **PO, ürünün okuma ve yazma hesaplarından farklı bir Atlassian hesabı olmalıdır.** Ürün bot
   kimliğini `TP_JIRA_BOT_ACCOUNT_IDS`'ten değil, öncelikle **yazma kimliğinin `/myself`
   yanıtından** (e-posta + accountId) çıkarır; `TP_JIRA_BOT_ACCOUNT_IDS` yalnızca ek liste. Ayrıca
   `check_jira_approver` okuma/yazma e-postalarını ayrılmış sayar. PO = yazma (ya da okuma)
   hesabıyken PO'nun koyduğu `tp-po-approved` onay sayılmaz ve bir sonraki PO sorgusunda etiket
   (yorum yazılmadan, yalnızca denetim kaydıyla) kaldırılır. Bu doğru davranıştır (constitution I:
   ürün kendi onayını veremez); tek hesapla gerçek Jira'da Demo-A 3. adımdan ileri gidilemez.
   Çözüm: ürün için ayrı bir bot hesabı açın (okuma + yazma), PO insan hesabı olarak kalsın.
2. **E-posta görünürlüğü:** Jira Cloud, kullanıcının e-postasını (ör. kendi hesabı ya da aynı
   kuruluş) gösterebilir; o zaman changelog/yorum yazarı e-postadır. PO izin listesi accountId ile
   yazılmışsa eşleşme eskiden başarısız oluyordu. Düzeltildi: yetki eşlemesi yazarın e-postasına
   **ve** accountId'sine bakar (görünen ad asla); bot denetimi de her ikisine.
3. **Test iş türü:** Xray kurulu projede `Test` türü Xray'e aittir. `TP_TEST_MGMT=jira` bu türde
   issue açar; Xray onu adımsız Manual test olarak görür (adımlar yalnızca açıklama tablosunda).
   Adımların Xray'de görünmesi için `TP_TEST_MGMT=xray`. `Task` yedeği (`test-case` etiketi)
   yalnızca projede `Test` türü yoksa devreye girer; TPD'de devreye girmedi.
4. **Arama indeksi gecikmesi:** Jira Cloud'da yeni açılan bir issue JQL aramasında birkaç saniye
   görünmez. Yayının asıl idempotency'si veritabanındaki `external_ref` kaydıdır (ikinci "Yayınla"
   yeni kayıt açmaz); `tp-<uuid>` etiket araması yalnızca çökme/yeniden deneme yedeğidir. Bir
   yayın denemesi Jira'da oluşturup başarısız sayıldıysa, yeniden denemeyi birkaç saniye sonra
   yapın; aksi halde aynı case için ikinci issue açılabilir (adaptör düzeyinde gözlendi).
5. `make jira-seed ONAY=1` koşu kayıtlarını (`tp-<uuid>` etiketli Test/Bug) kapatır ve TPD-1..7'deki
   yorumları siler; story'lerdeki bağlantılar kalır (kapalı kayıtlara bağlantı olarak görünür).
   Yorum silme yazma hesabının *Delete all comments* iznini ister; izin yoksa her yorum `HATA`
   satırıyla raporlanır.

### 2.7 Yorum imi ve rol @bahsetmeleri

Ürün Jira'ya bir insan hesabının token'ıyla yazabilir (pilotta yazma kimliği Gokhan Sipahi); yorumlar
Jira'da o kişinin adıyla görünür. Bu yüzden ürünün **her yorumu** `🤖 AI Testing Probe:` satırıyla
başlar; yeni açılan Bug'ın açıklamasının ilk satırı da aynıdır. Rol hesapları `.env`'de accountId
olarak verilir ve ilgili kişiler aynı satırda ADF `mention` düğümüyle **@bahsedilir** (Jira bildirim
gönderir). Anahtar boşsa o rol bahsedilmez; aynı kişi iki rolde ise bir kez bahsedilir.

| Yorum (yer) | Bahsedilen |
|---|---|
| PO soru yorumu (story; ön inceleme son hal) | PO + Analist |
| Onay etiketi kaldırıldı bildirimi (story) | PO |
| Onaylı doküman düzeltmesi yazıldı, yeniden teyit (story) | PO |
| Onaylı case'ler Jira/Xray'e yayınlandı — zincir hash yorumu (story) | Testçi |
| Hata mevcut Bug'a bağlandı — kanıt yorumu (Bug) | Mühendis + Testçi |
| Yeni Bug açıldı (açıklamanın ilk satırı; ayrı yorum yazılmaz) | Mühendis + Testçi |

Test issue'sundaki üretim modu yorumu yalnızca imlidir (bahsetme yok). Locator onarımı Jira'ya yazmaz
(PR yorumları forge'dadır); bu yüzden onarım için Jira bahsetmesi yoktur.

Bahsetme **yalnızca bildirimdir**: yetki vermez, PO onayı sayılmaz; `tp-po-approved` etiketini yine
yalnızca PO kendisi koyar (constitution I). Idempotency işaretleri (`Kayıt: …`, `tp-<uuid>`, hash
satırları) gövdede aynen kalır; im yalnızca başa eklendiği için yeniden denemeler aynı yorumu bulur.
accountId'yi bulmak için 2.3'teki komut kullanılır.

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
*Test* issue'su ve story bağlantısı görünür. **Durum (2026-11-01):** Xray adaptörü gerçek Xray
Cloud'a karşı doğrudan doğrulandı (TPD, team-managed): toplu içe aktarım Manual Test + adımlar
oluşturdu, story'ye `Test` bağlantısı kuruldu; Xray GraphQL `getTests(jql: "project = TPD")` →
`testType.name = Manual`, adımlar dolu. Ürün akışı üzerinden (onaylı case → Yayınla) gerçek Xray
yayını henüz yapılmadı: PO kapısı ayrı PO hesabı ister (2.6, madde 1).

Xray tarafını doğrulamak (sır basmadan; `XRAY_*` `.env`'den okunur):

```bash
python3 - <<'PY'
import json, urllib.request
env = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
base = env.get("XRAY_BASE_URL", "https://xray.cloud.getxray.app").rstrip("/")
def post(path, body, tok=None):
    h = {"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})}
    return json.loads(urllib.request.urlopen(urllib.request.Request(base + path, json.dumps(body).encode(), h)).read())
tok = post("/api/v2/authenticate", {"client_id": env["XRAY_CLIENT_ID"], "client_secret": env["XRAY_CLIENT_SECRET"]})
q = 'query { getTests(jql: "project = TPD", limit: 50) { total results { testType { name } steps { action } jira(fields: ["key"]) } } }'
for t in post("/api/v2/graphql", {"query": q}, tok)["data"]["getTests"]["results"]:
    print(t["jira"]["key"], t["testType"]["name"], len(t["steps"]), "adım")
PY
```

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

Hedef depo: **`ThinkGOtr/testingprobe-demo-app`** (özel). Kimlikler — anayasa gereği bot PR açar ama
**asla merge etmez**; ruleset bypass yalnızca insan `demo-admin` takımındadır:

| Kimlik | Ne yapar | `.env` / nerede |
|---|---|---|
| **Bot: GitHub App** (ör. `tp-bot`) | Kod üretimi ve **locator onarımı** dalı + PR, PR yorumu, PR kapatma, "Update branch", Actions tetikleme ve artefakt okuma | `GH_APP_ID`, `GH_APP_PRIVATE_KEY`, `GH_APP_INSTALLATION_ID` (yalnızca core-worker) |
| **İnsan: Gokhan** (`gokhansipahi`, `demo-admin` takımının tek üyesi) | Portal merge'ü; demo **kırılması** ve **sıfırlaması** (dal + commit + PR + bypass merge) | `GITHUB_MERGE_TOKEN` (yalnızca core-worker) |
| Salt okuma token'ı | Tutarlılık denetiminin kod okuması | `GITHUB_READ_TOKEN` (core) |
| Salt okuma token'ı | toolchain-worker aynası: GitHub commit'lerini çeker (kırarak doğrula, demo-app-web eşitleme) | `TP_FORGE_REMOTE_TOKEN` (yalnızca toolchain-worker) |

### 5.1 Demo deposunu kurun (bir kez)

1. GitHub'da **boş, özel** `ThinkGOtr/testingprobe-demo-app` deposunu açın (README/.gitignore
   eklemeden).
2. İçeriği hazırlayın ve gözden geçirin — varsayılan **kuru çalışma**dır, ağa çıkmaz:

   ```bash
   scripts/github-demo-repo-init.sh                      # ağacı geçici dizinde kurar, özet + komutları yazar
   scripts/github-demo-repo-init.sh --out ~/tp-demo-repo # aynı, incelemek için kalıcı dizine
   ```

   Düzen (ürünün GitHub kipinin beklediği): `demo-app/` (uygulama; `TP_FORGE_APP_ROOT` varsayılanı
   `demo-app`, `TP_E2E_ROOT=demo-app/e2e`), `.github/workflows/ci.yml` (zorunlu check'ler
   `test-local`, `ast-guard`, `semgrep`; GitHub-hosted `ubuntu-24.04`; ürün deposundaki ci.yml'den
   golden-drift job'u çıkarılmış — golden kayıtlar ve `rules/` ürün deposunda kalır),
   `break-verify.yml`, `CODEOWNERS` (`@gokhansipahi`; `--codeowner` ile değişir), `dependabot.yml`,
   `scripts/github-*.sh` (CI yardımcıları), `toolchain/ast-guard/`, `.playwright-version`. Tek ve
   deterministik bir ilk commit ve onun üzerinde **`demo-baseline`** etiketi oluşturulur (GitHub
   kipindeki demo sıfırlamasının hedef ağacı). `.env*` ve anahtar/token kalıpları bulunursa betik durur.
3. Gönderin (sizin git kimlik bilgilerinizle; ör. `gh auth setup-git` — workflow dosyaları için
   token'da `workflow` izni gerekir; betik token okumaz):

   ```bash
   scripts/github-demo-repo-init.sh --push            # boş depoya: main + demo-baseline
   ```

   Depo doluysa betik durur. Ürün deposundaki değişiklikleri sonradan taşımak için
   `--push --update`: yeni ağaç uzak main'in üstüne tek commit olarak `altyapi/bootstrap-<zaman>`
   dalına gider; PR'ı siz açar, insan olarak merge edersiniz. `demo-baseline`'ı yeni içeriğe
   taşımak ayrı, bilinçli bir yönetici adımıdır (betik komutu yazdırır).

### 5.2 GitHub App (bot)

1. Org ayarları → Developer settings → **GitHub Apps → New GitHub App**: ad (ör. `tp-bot`),
   webhook **kapalı**. *Repository permissions*:
   - **Contents: Read and write** (dal + commit; "Update branch")
   - **Pull requests: Read and write** (PR açma/kapatma, yorum, etiket)
   - **Actions: Read and write** (`repository_dispatch`/`workflow_dispatch`, koşu ve artefakt okuma)
   - **Checks: Read-only**, **Metadata: Read-only** (zorunlu)
   - *Workflows* izni **vermeyin** (bot `.github/**` değiştiremez). Merge için ayrı izin yoktur;
     ruleset bot'u bypass listesine **eklemez**, CODEOWNERS insan onayı ister.
2. Private key oluşturun (`.pem`). App'i **yalnızca** `testingprobe-demo-app` deposuna kurun
   (*Only select repositories*). Kurulum kimliği kurulum sayfasının URL'sindedir (boş bırakılırsa
   core depodan bulur).
3. Depo → Settings → *Variables → Actions*: `TP_BOT_LOGINS=tp-bot[bot]` (App adına göre; AST
   koruması bot PR'larını onarım/üretim kipine alır). `TP_TOOLCHAIN_IMAGE` **boş** kalsın
   (runner kurulumu; ürünün GHCR imajı başka depodan çekilemez). Sauce isteğe bağlı:
   `SAUCE_USERNAME`/`SAUCE_ACCESS_KEY` secret'ları yoksa `sauce` job'u "atlandi" yazar.

### 5.3 `demo-admin` takımı ve insan token'ı

1. Org → Teams → **`demo-admin`** (slug tam bu) takımı; tek üye **`gokhansipahi`**. Takıma depoda
   **Write** (ya da Maintain) yetkisi verin.
2. Gokhan'ın **ince ayarlı kişisel token'ı** (`GITHUB_MERGE_TOKEN`): *Resource owner* ThinkGOtr,
   *Only select repositories* → `testingprobe-demo-app`; **Contents: Read and write**, **Pull
   requests: Read and write**, Metadata: Read. Org ince ayarlı token onayı istiyorsa org yöneticisi
   onaylar. Bu token yalnızca core-worker'a verilir; bypass yetkisi token'dan değil, sahibinin
   `demo-admin` üyeliğinden gelir.
3. Salt okuma token'ları (`GITHUB_READ_TOKEN`, `TP_FORGE_REMOTE_TOKEN`): aynı depo, yalnızca
   **Contents: Read-only** (aynı token iki değişkene de yazılabilir).

### 5.4 Ruleset

Varsayılan kuru çalışma; uygulamak için `--apply` (`gh` org yöneticisi oturumuyla; takım 5.3'te
oluşturulmuş olmalı):

```bash
scripts/github-ruleset.sh --repo ThinkGOtr/testingprobe-demo-app            # gövdeyi yazdırır
scripts/github-ruleset.sh --repo ThinkGOtr/testingprobe-demo-app --apply    # tp-main
```

`tp-main`: main'e yalnızca PR; 1 onay + CODEOWNERS + son push onayı; zorunlu check'ler
`test-local`, `ast-guard`, `semgrep` (kaynak GitHub Actions'a sabit); force-push ve silme yok;
bypass yalnızca `demo-admin` takımı (`always`). İlk `--push` ruleset'ten ÖNCE yapılır (boş depo).

### 5.5 `.env`

```dotenv
TP_FORGE=github
GITHUB_REPO=ThinkGOtr/testingprobe-demo-app
# Bot: GitHub App (5.2)
GH_APP_ID=<app id>
GH_APP_PRIVATE_KEY=<PEM, satır sonları \n kaçışlı tek satır>
GH_APP_INSTALLATION_ID=                 # boşsa repodan bulunur
GITHUB_TOKEN=                           # App varken boş (yalnızca geliştirme yedeği)
# İnsan: demo-admin üyesinin token'ı (5.3). Portal merge'ü + demo kırılması/sıfırlaması.
GITHUB_MERGE_TOKEN=<gokhansipahi ince ayarlı token>
GITHUB_READ_TOKEN=<salt okuma>
# toolchain-worker aynası (kırarak doğrula + demo-app-web'in GitHub main'inden derlenmesi)
TP_FORGE_REMOTE_URL=https://github.com/ThinkGOtr/testingprobe-demo-app.git
TP_FORGE_REMOTE_TOKEN=<salt okuma>
TP_E2E_ROOT=demo-app/e2e
TP_APP_PATHS=demo-app/web,demo-app/api
TP_REQUIRED_CHECKS=                     # boş = test-local,ast-guard,semgrep
```

- `GH_APP_PRIVATE_KEY_PATH` yalnızca dosya core-worker konteynerinde görünürse işe yarar; compose
  böyle bir bağlama içermez, bu yüzden tek satırlık `GH_APP_PRIVATE_KEY` kullanın.
- `TP_FORGE_REMOTE_URL` boşsa GitHub modunda "Kırarak doğrula" tamamlanamaz (merge açık kabul notu
  ister) ve `scripts/demo-web-sync.sh` GitHub kipinde açık hatayla durur.
- `TP_APP_PATHS`, toolchain'in "çalışan uygulama istenen commit'in uygulamasını mı taşıyor"
  karşılaştırmasıdır (`/check` `app` adımı, `/locator-probe`); GitHub düzeninde `demo-app/...`
  olmalıdır, yoksa karşılaştırma var olmayan `web/` yolunu kıyaslar.
- Portal merge'ü ruleset koşullarını kendisi değerlendirir; eksik varsa yalnızca `demo-admin`
  merge eder ve sonuç `bypass` olarak kaydedilir. Diğer mühendisler önce PR'ı GitHub'da onaylamalı
  ya da GitHub arayüzünden merge etmelidir (core bunu `review.kanal='github'` ile işler).
- `make security-check`: `GH_APP_*`, `GITHUB_TOKEN`, `GITHUB_MERGE_TOKEN` yalnızca core-worker'da;
  `TP_FORGE_REMOTE_TOKEN` yalnızca toolchain-worker'da (salt okuma).

### 5.6 Tetikler

| Portal | GitHub |
|---|---|
| PR açılması / main'e merge | `pull_request` / `push` |
| Sunucu · Koşular → "Deploy sonrası testleri koş" | `repository_dispatch` `deploy` (koşu adı `ci deploy [<kimlik>]`) |
| Sunucu · Koşular → "Gece koşusunu şimdi başlat" | `workflow_dispatch` `ci.yml` `tetik=nightly`; ayrıca zamanlanmış `0 2 * * *` (UTC) |

Core koşuyu adındaki `[<kimlik>]` ile bulur, artefaktları (`test-local-results`, `sauce-results`)
indirir; PR CI sonucu PR'a tek yorum olarak yazılır.

### 5.7 Locator kırılması/onarımı GitHub kipinde

Kırılma ve sıfırlama **bot ile değil, insan kimliğiyle** (`GITHUB_MERGE_TOKEN`) yapılır;
onarımı bot önerir, insan merge eder:

1. **Kır** (Sunucu · "Buton kimliğini değiştir" ya da `make break`): core-worker, main'in o anki head'inden
   `demo/break-locator-<main12>` dalına tek commit yazar (yalnızca `demo-app/web/src` altındaki
   tırnaklı `add-to-cart` → `cart-add`), PR'ı açar, farkı yerel kipteki aynı kuralla doğrular
   (yalnızca `web/src`, satır sayısı aynı, yalnızca testid) ve PR head'ine bağlı olarak
   **demo-admin bypass**'ıyla merge eder. Denetim: "demo kırılması" (`kimlik.github_login`,
   `bypass`, fark özeti) + `demo.break`. Token yoksa iş düşer (`demo.break_failed`, yönerge).
2. GitHub `push` koşusu main'de **kırmızı** olur; core onu doğrudan izler (Actions koşusu,
   `test-local-results` artefaktı). Aynı anda çalışan **demo-app-web**'in GitHub main'inden
   derlenmesi istenir: `make demo-break` / `make break` bunu kendisi uygular
   (`scripts/demo-web-sync.sh`; web arşivi toolchain-worker aynasından). Portal düğmesi
   kullanılıyorsa sunum boyunca `make demo-web-sync A=--watch` açık olsun.
3. Triage `test_maintenance/locator` → mühendis "Onarım PR'ı aç": **bot** (App) `tp/repair-*`
   dalında yalnızca `demo-app/e2e/pages/catalog/locators.ts` testId'sini değiştiren PR'ı açar;
   `ast-guard` onarım kipinde koşar.
4. **İnsan merge eder**: portalda "Merge et" (`GITHUB_MERGE_TOKEN`) ya da GitHub arayüzünde onay +
   merge. `push` CI'ı **yeşil**.
5. **Sıfırla** (Sunucu · "Demoyu sıfırla" / `make demo-reset`): force-push YOK. Insan kimliğiyle
   main'in üstüne ağacı `demo-baseline` etiketinin ağacıyla birebir aynı tek commit
   (`demo/reset-baseline-<main12>`), PR ve bypass merge. Böylece kırılma, onarım ve üretilen
   testler birlikte geri alınır (yalnızca kırılmayı `git revert` etmek onarılmış e2e'yi bırakır ve
   ters yönde kırık bir main üretirdi); geçmiş korunur, denetlenir. Merge sonrası main ağacı
   baseline ağacına eşit değilse iş hata verir. Açık `tp/*`, `demo/*` PR'ları yorumlanıp kapatılır.
   Sonra demo-app-web baseline'a eşitlenir ve push CI izlenir.

`make up` GitHub kipinde demo-app-web'i çalışma ağacından derler; main baseline ağacında değilse
`forge-init.sh sync-web` onu `scripts/demo-web-sync.sh --main` ile GitHub main'ine eşitler
(eşitleyemezse uyarır, `make up`'ı düşürmez).

### 5.8 Doğrulama

```bash
docker compose exec -T core-worker python -c \
  "from tp_core.integrations.forge import get_forge; print(type(get_forge()).__name__)"
# Beklenen: GitHubForge
docker compose exec -T core-worker python -m tp_core.integrations.forge_demo status
# Beklenen: "kip": "github", "web_yolu": "demo-app/web", "testid": "add-to-cart", "main_baseline_mi": true

gh api repos/ThinkGOtr/testingprobe-demo-app/rulesets --jq '.[].name'   # Beklenen: tp-main
gh api repos/ThinkGOtr/testingprobe-demo-app/git/ref/tags/demo-baseline --jq .object.sha
make security-check                                          # GH_APP_*, GITHUB_TOKEN yalnızca core-worker'da

scripts/demo-web-sync.sh --main     # demo-app-web = GitHub main (toolchain aynası); "GitHub aynası" yazmalı
```

Uçtan uca: (1) mühendis bir onaylı case için kod üretir → `tp/case-*` dalında bot PR'ı →
`test-local`, `ast-guard`, `semgrep` → portalda merge kapısı → insan merge → `push` koşusu.
(2) Locator yolu 5.7 adımlarıyla: yeşil temel `push` koşusu → kır → kırmızı → onarım PR'ı (bot)
→ insan merge → yeşil → sıfırla. Sunucu "Deploy sonrası testleri koş" →
`gh run list --repo ThinkGOtr/testingprobe-demo-app --workflow ci.yml --limit 3` listesinde
`ci deploy [...]`. Prova listesindeki "bot main'e push dener → reddedilir" maddesi ruleset
uygulandıktan sonra bot kimliğiyle denenir.

## 6. Simülatöre geri dönmek

İlgili değişkenleri `.env`'de boşaltın (ya da `TP_MODEL_MODE=replay`, `TP_TEST_MGMT=jira`,
`TP_FORGE=local`), sonra `make up`. `JIRA_BASE_URL` boşken compose `jira-sim`'i, `JIRA_BROWSE_URL`
boşken jira-sim'in yerel adresini kullanır. Temiz başlangıç için `make reset`.

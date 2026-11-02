# jira-sim

Jira Cloud REST v3 ve Xray Cloud alt kümesini sunan yerel simülatör. Çekirdekteki `RestJira`,
`JiraTestManagement` ve `XrayTestManagement` adaptörleri gerçek sitede de burada da **aynı kodla**
çalışır; seçim yalnızca `JIRA_BASE_URL` / `XRAY_BASE_URL` ile yapılır. Arayüz: <http://127.0.0.1:8090/>.

## Veri

Bağlayıcı içerik `docs/DEMO-VERISI.md`: proje `TPD`, `TPD-1`..`TPD-4` story'leri (açıklama ADF,
"Kabul Kriterleri" başlığı + `AC<n>:` maddeleri). Mükerrer araması için ek Bug'lar:

| Anahtar | Özet | Durum |
|---|---|---|
| TPD-5 | Kampanya indirimi sepette yanlış hesaplanıyor | To Do (açık) |
| TPD-6 | Sipariş geçmişinde tarih sıralaması ters görünüyor | In Progress (açık) |
| TPD-7 | Giriş sayfasında hata mesajı İngilizce görünüyor | Done |

Durum `JIRA_SIM_DATA` (compose'da `/data/jira.json`, `tp_jira` volume'ü) dosyasına atomik olarak
yazılır (geçici dosya → fsync → rename). Değişken boşsa durum yalnızca bellekte tutulur.

## Kimlik

Basic auth. Bilinmeyen kullanıcı → 401.

| Kullanıcı | Token | Yetki |
|---|---|---|
| `reader@sim.local` | herhangi | yalnızca okuma (yazma uçları 403) |
| `writer@sim.local` | herhangi | ürünün yazma (bot) kullanıcısı: yorum, etiket, açıklama, issue, bağlantı |
| `po@sim.local` | **`JIRA_SIM_PO_PASSWORD`** | PO (insan onayı); arayüzdeki "PO olarak" bölümü bu kullanıcı adına yazar |

### PO onay kapısının korunması (anayasa I)

`tp-po-approved` etiketini PO adına yalnızca PO parolasını bilen kişi koyabilir:

- Arayüzün yazma uçları (`POST /browse/{key}/labels|comment|description`, `/cikis`) **PO girişi**
  (`/giris`, imzalı `HttpOnly; SameSite=Strict` çerez), formda gizli **CSRF belirteci** ve
  **aynı köken** ister. `Origin`/`Referer`/`Sec-Fetch-Site` başka bir kökeni (aynı makinedeki
  başka port dahil) gösteriyorsa ya da `Host` izin listesinde değilse (DNS rebinding) → 403;
  oturum yoksa → 401. Giriş yapılmamışken sayfada PO formları gösterilmez.
- REST'te `po@sim.local` yalnızca PO parolasıyla kimlik doğrular.
- `/sim/*` yazma uçları: başka kökenli tarayıcı isteği → 403; `application/json` dışındaki gövde
  → 415 (basit form gönderimi engellenir); `JIRA_SIM_ADMIN_TOKEN` tanımlıysa
  `X-Sim-Admin-Token` başlığı zorunlu.

| Ortam değişkeni | Anlamı |
|---|---|
| `JIRA_SIM_PO_PASSWORD` | PO parolası. Boşsa her açılışta rastgele üretilir ve loga yazılır (`docker compose logs jira-sim`). |
| `JIRA_SIM_ADMIN_TOKEN` | `/sim/*` yazma uçları için belirteç (boşsa yalnızca köken denetimi). |
| `JIRA_SIM_SECRET` | Oturum imza anahtarı (boşsa açılış başına rastgele; yeniden başlatma oturumu kapatır). |
| `JIRA_SIM_ALLOWED_HOSTS` | Virgülle ek `Host` adları (varsayılan: `127.0.0.1`, `localhost`, `jira-sim`, `JIRA_SIM_BASE_URL` host'u). |

Not: Simülatör, gerçek Jira gibi, bot kullanıcısının `tp-po-approved` eklemesini engellemez.
Bu engel çekirdekte: `RestJira` ayrılmış etiketi yazmayı reddeder, `authorized_po_approvals`
changelog yazarını PO izin listesiyle (`JIRA_PO_ACCOUNT_IDS`; e-posta ya da accountId, görünen ad
asla) karşılaştırır ve bot hesabının koyduğu etiketi saymaz.

Xray: `POST /xray/api/v2/authenticate` boş olmayan her `client_id`/`client_secret` için token verir.

## Uçlar

- `GET /rest/api/3/myself`
- `GET|POST /rest/api/3/search/jql` (`jql`, `fields`, `maxResults`, `nextPageToken`; `fields`
  verilmezse yalnızca `id` döner — yeni arama ucunun davranışı)
- `GET /rest/api/3/issue/{key}` (`fields`, `expand=changelog`), `PUT` (`fields.summary|description|labels`,
  `update.labels[add|remove|set]`; değişiklikler yazar bilgisiyle changelog'a), `DELETE`
- `POST /rest/api/3/issue`
- `GET /rest/api/3/issue/{key}/changelog`, `GET|POST /rest/api/3/issue/{key}/comment` (ADF gövde), `DELETE /rest/api/3/issue/{key}/comment/{id}`
- `GET|POST /rest/api/3/issue/{key}/transitions` (basit iş akışı: her durumdan To Do / In Progress /
  Done'a; geçiş changelog'a `status` olarak yazılır)
- `POST /rest/api/3/issueLink`, `GET /rest/api/3/issueLinkType` (`Test`: inward "is tested by",
  outward "tests"; `Relates`; `Blocks`; `Duplicate`)
- `GET /rest/api/3/issue/createmeta/{project}/issuetypes`, `GET /rest/api/3/issue/createmeta?projectKeys=`,
  `GET /rest/api/3/project/{key}` (Story, Task, Bug, Test)
- `POST /xray/api/v2/authenticate`, `POST /xray/api/v2/import/test/bulk`,
  `GET /xray/api/v2/import/test/bulk/{jobId}/status` (ilk sorguda `working`, sonra sonuç)

Arayüzde "PO olarak" bölümündeki onay düğmesi (`tp-po-approved`) ve "Yeniden onayla" yalnızca
**Story** kayıtlarında gösterilir; Test/Bug/Task kayıtlarında PO yalnızca yorum yazar, açıklama
düzenler ve onay dışı etiket koyar (arayüzden bu kayıtlara onay etiketi eklenemez).

Arayüz saatleri `Europe/Istanbul` yerel saatiyle gösterilir (API UTC `+0000` döner). Arayüzdeki
hata iletileri Türkçedir; REST API Jira uyumu için İngilizce iletileri korur.

JQL alt kümesi: `project`, `key`/`issuekey`, `labels`, `text`, `summary`, `description`, `status`,
`statusCategory`, `issuetype`/`type`, `reporter`; `= != ~ !~ in, not in, is [not] EMPTY`,
`AND/OR/NOT`, parantez, `ORDER BY created|updated|key|summary [ASC|DESC]`.

## Yönetim uçları (yalnızca simülatör)

Yazma uçları köken denetimli; `JIRA_SIM_ADMIN_TOKEN` tanımlıysa `X-Sim-Admin-Token` ister.

- `POST /sim/reset` — tohum verisine döner.
- `GET|POST /sim/config` — `{"issue_types": [...], "link_types": [...]}`; ör. Test türü olmayan
  site provası (adaptör `Task` + `test-case` etiketine, `Relates` bağlantısına düşer).
- `POST /sim/faults` — `{"path_prefix", "status", "count", "retry_after"?, "method"?}`; 429/5xx
  yeniden deneme provası. Boş liste (`[]`) temizler.

## Gerçek Jira'da demo başlangıcı (`jira-seed`)

`/sim/reset` yalnızca simülatörde vardır. Gerçek sitede bir provadan sonra TPD-1..TPD-4'ü
DEMO-VERISI içeriğine döndürmek, `tp-po-*`/`AI-generated`/`tp-<uuid>` etiketlerini kaldırmak ve
`tp-<uuid>` etiketli Test/Bug kayıtlarını kapatmak için çekirdekteki komut kullanılır (yazma
kullanıcısıyla, aynı `RestJira` kod yolu):

```sh
docker compose exec core python -m tp_core.integrations.jira_seed          # plan (kuru)
docker compose exec core python -m tp_core.integrations.jira_seed --onay   # uygula (--sil: kapatmak yerine sil)
```

## Geliştirme

```sh
uv sync
uv run ruff check && uv run ruff format --check && uv run pytest
uv run uvicorn jira_sim.app:app --port 8090
```

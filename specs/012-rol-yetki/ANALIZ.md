# 012 — Rol ve yetki modeli v2 — Analiz

Tarih: 2026-11-11 · Dal: `feat/rol-yetki` (origin/dev'den) · Durum: kararlar alındı, geliştirme başlıyor

Kaynak: "AI Testing Probe Rol ve Yetki Paketi v2" (Excel matris, Word/PDF rehber, `rbac.ts`, 4 görsel;
`.docs/` altında, repoya girmez). Excel karar kaynağıdır. `rbac.ts` referans taslaktır: çekirdek
Python olduğu ve taslakta çalışmayan guard'lar bulunduğu için kopyalanmaz.

Bu doküman kapsamı, kararları, izin kataloğunu ve geliştirme şeritlerini sabitler. Sözleşme
değişikliği önce buraya yazılır.

## 1. Amaç

Bugün 5 rol var (`analyst`, `po`, `tester`, `engineer`, `presenter`) ve izinler router'lara dağılmış
`require_role(...)` çağrılarıyla veriliyor. Okuma uçlarının çoğu oturum açan herkese açık.

Hedef:

- Paketteki rol setine geçmek ve görev sahipliklerini pakete göre değiştirmek (case kararı ve
  yayını Testçi'ye geçer, Analist son onayı verir).
- Tek bir izin kataloğu: her uç bir izin anahtarı ister. Katalogda olmayan izin reddedilir
  (yazma ve okuma).
- Reddedilen her istek 403 ile döner ve `authz.denied` olarak denetim kaydına yazılır.
- Portal aynı kataloğu kullanır: menü, sayfa ve düğmeler `/auth/me`'nin döndürdüğü izinlerle
  gösterilir. UI gizlemesi kontrol değildir; kontrol çekirdektedir.

## 2. Kararlar (2026-11-11, ürün sahibi)

| # | Konu | Karar |
|---|---|---|
| K1 | Çoklu rol | Bir kişi birden fazla rol alabilir. Rol hesapları arasında geçişle her rol gibi davranır (bugünkü "Rol değiştir") |
| K2 | Görevler ayrılığı | Kişiye göre değil **role göre**. Testçi + Analist rolü olan kişi case'i düzenleyip onaylayabilir; tek kişilik demo çalışır |
| K3 | PR kuralı | "PR yazarı kendi PR'ını onaylayamaz" kaldırıldı. Automation Engineer rolü yeterli; yeşil CI ve korumalı dal (bugünkü merge kapısı) kalır |
| K4 | Proje kapsamı | Tek proje. Proje/tenant filtresi ve proje bazlı rol bu fazda yok |
| K5 | Rol ataması | AI Probe platformunda. Paketteki "Kullanıcı ve rol yönetimi" sayfası ve `access.assign` TP'ye yazılmaz; Erişim Yöneticisi rolü TP'de yoktur |
| K6 | PO onayı | Dokümandaki gibi Jira: etiketi koyan aktör PO listesinde, içerik hash'i eşleşir. Jira kaynaklı gereksinimde portal PO onay ucu 410 döner, düğmesi kalkar. İstisna (2026-11-11 ek karar): serbest metin gereksinimde (`kaynak == free_text`, Jira'da story yok) portal PO onayı kalır (`requirement.po_approve_free_text`, hash kontrolü bugünkü gibi) |
| K7 | Paketin kapsamadığı özellikler | Sahibi PO (baz değer). Doküman düzeltmesini Jira'ya uygulama ve "Son hal olarak onayla" Analist'te kalır (2026-11-11 ek karar; `requirement.review`). İstisna: locator onarımı → Automation Engineer, Claude Code yayın token'ı → Testçi |
| K8 | Yayınlanmış case'te değişiklik | Paketteki T09 "yayınlanmış case'ten yeni sürüm" uygulanmaz: yayınlanmış sürüm değişmez, değişiklik gereksinimden yeniden üretimle gelir (2026-11-12) |

Uygulama sırasında verilen teknik kararlar (ürün kararı değil; gerekçesiyle):

- **Rol kimlikleri İngilizce kalır**, mevcutlar korunur: `engineer` = Automation Engineer.
  Yeni: `admin` (Sistem Yöneticisi), `auditor` (Denetçi), `developer`, `viewer` (Görüntüleyici).
  TP'deki rol sayısı 8'dir (Erişim Yöneticisi AI Probe'dadır, K5).
- **`presenter` kalkar → `admin`.** Göç `app_user.rol`'ü çevirir; kimlik bağları korunur. Devirde
  gelen `presenter` rolü geçiş süresince `admin` sayılır (AI Probe'daki canlı rol kayıtları
  güncellenene kadar sunucu erişimini kaybetmez).
- **Mevcut durum makineleri korunur**; paketin `IMPORTED/REVIEWED/...` adları öneridir. Tek yeni
  durum case'teki `ready` (paketteki `READY_FOR_APPROVAL`).
- **İzin anahtarları paketteki adlardır** (`case.approve` vb.); okuma için paketin `read.*`
  fikri `<nesne>.read` anahtarlarıyla tamamlanır.
- **Ortam ve demo bayrakları yenidir:** `TP_ORTAM` (`dev|test|staging|prod`, varsayılan `dev`) ve
  `TP_DEMO_MODE` (varsayılan `0`). `TP_ORTAM=prod` iken `TP_DEMO_MODE=1` ise çekirdek başlamaz.
  Canlı demo kurulumunun `.env`'ine `TP_DEMO_MODE=1` eklenmelidir (deploy notu, §9).
- **Developer koşusu:** koşu hedefi kurulum genelinde tektir; "prod" kararı `TP_ORTAM`'a bakar.
  Developer `TP_ORTAM=prod` iken koşu başlatamaz.
- **Denetçi ve Görüntüleyici "maskeli" görünüm:** koşu özetlerini görür, ham artefaktları
  (ekran görüntüsü, iz, log dosyası) göremez.
- **Asistan:** tüm rollerin kullanımına açık kalır (araçları zaten rolün okuma izinlerine göre
  süzülür, §4.3). "Sahibi PO" kararı asistanın yönetim ayarları için geçerlidir; bugün portalda
  böyle bir ayar yoktur.

## 3. Roller

| Rol (`id`) | Etiket | Ana görev |
|---|---|---|
| `admin` | Sistem Yöneticisi | Sistem ayarı ve demo işletimi; iş akışında onay vermez |
| `auditor` | Denetçi | Denetim kaydını ve zincir doğrulamasını salt okunur inceler |
| `analyst` | Analist | Gereksinim içe aktarma ve ön inceleme; case son onayı |
| `po` | PO | Gereksinim teyidi (Jira; serbest metinde portal); baz değer |
| `tester` | Testçi | Case üretimi, kararı, düzenlemesi, yayını; bug kararı; yayın token'ı |
| `engineer` | Automation Engineer | Test kodu, kırarak doğrulama, PR inceleme/merge, locator onarımı, koşular |
| `developer` | Developer | Onaylı case ve koşuları görür; non-prod'da manuel koşu başlatır |
| `viewer` | Görüntüleyici | Kontrol Kulesi ve koşu özetleri |

AI / sistem hiçbir insan kapısını geçemez (bugün de böyle: `record_approval` yalnız portal
oturumu ve Jira PO kanalını kabul eder).

## 4. İzin kataloğu (tek kaynak: `tp_core/auth/yetki.py`)

### 4.1 Aksiyonlar

| İzin | Roller | Uçlar | Ek koşul |
|---|---|---|---|
| `requirement.import` | analyst | `POST /requirements/sync`, `POST /requirements/free-text` | |
| `requirement.review` | analyst | `POST /requirements/{id}/review`, `POST /findings/{id}/decision`, `POST /requirements/{id}/apply-doc-fixes` (düzeltmeleri Jira'ya yaz / "Son hal olarak onayla") | |
| `requirement.po_approve_free_text` | po | `POST /requirements/{id}/po-approve` | yalnız `kaynak == free_text`; hash kontrolü (mevcut). Jira kaynaklı gereksinimde 410 `po_onayi_jira` (izin kontrolünden sonra) |
| `requirement.po_reject_free_text` | po | `POST /requirements/{id}/po-reject` `{gerekce (1..2000), icerik_hash}` | T04: yalnız `kaynak == free_text` ve `pending_po`; `review` kararı `po_reject` (gerekçe + hash), `pending_po` → `new` (Analist yeniden inceler; ön inceleme kayıtları geçersizlenir), denetim + `po.rejected` olayı. Jira kaynaklı 410 `po_onayi_jira` |
| `baseline.manage` | po | `PUT/DELETE /requirements/{id}/baseline`, `POST /baseline-file/apply` | K7 |
| `case.generate` | tester | `POST /requirements/{id}/generate-cases` | gereksinim PO onaylı (mevcut kapı) |
| `case.decide` | tester | `POST /cases/{id}/decision` karar ∈ `accept`, `edit`, `reject`, `reopen`; `POST /cases/bulk-decision` karar = `accept` (013 toplu kabul); `POST /cases/{id}/viewed` | ret nedeni zorunlu (mevcut) |
| `case.approve` | analyst | `POST /cases/{id}/decision` karar ∈ `approve`, `send_back`; `POST /cases/bulk-decision` karar = `approve` (013 toplu son onay); `POST /requirements/{id}/review-complete` | yalnız `ready` case; `send_back` gerekçe ister |
| `case.publish` | tester | `POST /publish` | onaylı + hash değişmemiş (mevcut kapı) |
| `token.issue` | tester | `POST /tokens` | yayın / IDE gönderim kanalı |
| `code.generate` | engineer | `POST /code/generate`, `GET /code/languages` | onaylı case (mevcut). `GET /code/languages` (011 üretim dili, K-T8) her çağrıda forge'u okur; yalnız üretimi başlatan role açık, portal 403'ü "dil seçici yok" sayar |
| `code.break_verify` | engineer | `POST /scripts/{id}/break-verify` | |
| `code.review` | engineer | `POST /prs/{n}/review`, `POST /prs/{n}/update-branch` | |
| `code.merge` | engineer | `POST /prs/{n}/merge` | yeşil CI + korumalı dal (mevcut merge kapısı); K3 |
| `code.repair` | engineer | `POST /failures/{id}/fix` | K7 istisnası |
| `run.trigger_scheduled` | engineer | `POST /ci/trigger` tetik ∈ `deploy`, `nightly` | |
| `run.trigger_manual` | engineer, developer | `POST /ci/trigger` tetik = `manual` | developer: `TP_ORTAM≠prod` |
| `bug.decide` | tester | `POST /bug-drafts/{id}/decision`, `/prepare`, `/publish` | |
| `demo.manage` | admin, engineer | `POST /demo/break-locator`, `POST /demo/reset`, `POST /demo/jira-status` (013) | `TP_DEMO_MODE=1`; kapalıyken 403 `demo_kapali` ("Demo kipi kapalı (TP_DEMO_MODE=0)", denetimde `authz.denied` `neden: demo_kapali`); worker işleri (`demo.break`/`demo.reset`) ve host CLI (`python -m tp_core.features.demo on-kosul`, `web-istek --eylem break\|baseline`) da reddeder |
| `audit.verify` | admin, auditor | `GET /audit?verify=true` | |
| `automation.manage` | analyst, engineer | `PUT /automation-settings/{anahtar}` (013 Y3) | `jira_tetik` gövdesinde `durum` varsa ayrıca `automation.jira_status` |
| `automation.jira_status` | engineer | `PUT /automation-settings/jira_tetik` gövdesinde `durum` (013 K14) | |
| `testdata.manage` | analyst, tester, engineer | `POST /test-data`, `PUT/DELETE /test-data/{id}` (013 K11) | Testçi (012'de case'i düzelten rol) de düzenler: düzeltmedeki `{veri:…}` atfı katalogda olmalı |

### 4.2 Okuma

| İzin | Roller | Uçlar / not |
|---|---|---|
| `dashboard.read` | hepsi | Kontrol Kulesi uçları, `GET /demo/status`, `GET /auth/me`, `GET /automation-settings` (013) |
| `requirement.read` | admin, analyst, po, tester, engineer, developer | gereksinim listesi/detayı, bulgular, baz değer okuma, Jira tetik durumu (`GET /automation/jira-trigger`; portal `/otomasyon`, 013) |
| `case.read` | admin, analyst, po, tester, engineer, developer* | case listesi/detayı (portal `/caseler` Test case'leri ekranı dahil, 011 dev birleştirmesi), `GET /requirements/{id}/case-metrics`, test verisi kataloğu (`GET /test-data`, `GET /test-data/{id}/history`; portal `/test-verisi`, 013); *developer yalnız `approved`/`published` case; karar geçmişi ve chat yok |
| `code.read` | admin, analyst, tester, engineer | script listesi/detayı, ekran görüntüleri (`GET /scripts/{id}/screenshots/{n}`), onarım durumu (`GET /failures/{id}/fix`), toplu onayın kod işi (`GET /automation/codegen-jobs/{job_id}`, 013) |
| `run.read` | hepsi | koşu listesi/detayı |
| `run.artifacts` | admin, analyst, po, tester, engineer, developer | ham artefaktlar, `GET /artifacts/runs/{run_id}/{yol}` (auditor ve viewer hariç) |
| `failure.read` | admin, analyst, po, tester, engineer, developer | hata sınıflaması |
| `bug.read` | admin, analyst, po, tester, engineer, developer* | *developer yalnız açılmış / bağlanmış bug |
| `audit.read_all` | admin, auditor | tüm denetim kaydı |
| `audit.read_own` | analyst, po, tester, engineer, developer | yalnız kendi olayları (`aktor` = kullanıcı adı) |
| `events.read` | admin, analyst, po, tester, engineer, developer | `GET /events` (SSE) |
| `assistant.use` | hepsi | asistan ve öneriler |
| `token.read` | hepsi | kendi token'ları (`GET/DELETE /tokens`) |
| `publish.preview` | admin, analyst, po, tester, engineer | `GET /publish/preview` (dry-run gövde; yayın `case.publish`) |
| `claude_code.read` | admin, analyst, tester, engineer | Claude Code sayfası (portal; çekirdek ucu yok, token'lar `token.read` ile yalnız kendi) |
| `demo.read` | admin, analyst, po, tester, engineer | Demo yol haritası sayfası (portal; çekirdek ucu yok) |

Not (dev birleştirmesi, 2026-11-12): dev'deki "Kod üretimi / Koşular listeleri yalnız engineer + presenter" menü/rota kısıtı (`OTOMASYON_ROLLERI`, Hakan geri bildirimi) bu tabloya çevrildi: `/kod` → `code.read`, `/kosular` → `run.read`; ayrı rol listesi tutulmaz.

Not (013 sprint otomasyonu birleştirmesi, 2026-11-12): dev'in `require_role("analyst", "engineer")`
uçları (otomasyon ayarları, test verisi) `automation.manage` / `testdata.manage` izinlerine,
`/demo/jira-status` (presenter) `demo.manage` + demo kipine çevrildi. Toplu onay (`POST
/cases/bulk-decision`) iki adıma eşlendi: Testçi `accept` (taslak → `ready`, "Toplu kabul"),
Analist `approve` (`ready` → `approved`, "Toplu onayla"); izin tekli kararla aynı tablodan
(`TEST_CASE_KARAR_IZNI`), her öğe tekli `decide`'ın tüm kapılarından (hash, durum, gereksinim,
görevler ayrılığı) geçer. Onay sonrası otomatik kod yalnız Analist son onayından sonra kuyruğa
alınır. Jira tetiğiyle PO onayı sonrası otomatik case üretimi sistem aktörüyle başlar ve case'ler
`draft` kalır (Testçi kabulü + Analist son onayı gerekir; AI/sistem insan kapısını geçemez).

Ayar izinleri: `integration.manage` / `system.settings` bu kurulumda uygulanmaz — entegrasyon ve
sistem ayarları `.env` / sır yöneticisiyle yapılır, portalda ayar ekranı yoktur.

İmzalı, oturumsuz rapor bağlantıları (`GET /artifacts/k/{token}/runs/...`, koşu yanıtındaki `rapor_url`)
uç düzeyinde izin taşımaz (imza kanıttır); `run.artifacts` izni olmayan role koşu yanıtlarında bu
bağlantılar hiç dönmez (alan boş/yok). Maskeleme yapısaldır: `serialize_runs` / `run_detail` /
`control_tower` `artefakt` bayrağını zorunlu alır, her çağıran rolden karar verir (`/runs`,
`/runs/{id}`, `/control-tower` `son_kosular`, asistan `probe_get`). Maskeli yanıtta her düzeydeki
`*url` alanı boşalır (artefakt, imzalı rapor, `ci_url`, Sauce, GitHub iş bağlantıları), ekler boş
liste olur ve denemelerin `stdout`/`stderr`'i çıkarılır.

Denetçi görünümü: `GET /audit` auditor rolünde `ozet` alanını mevcut PII maskeleyicisinden geçirir
(`features/assistant/maskeleme.py`, `TP_PII_MASKING`'den bağımsız açık; yanıt başına tek oturum).
Zincir alanları (`hash`, `prev_hash`) ham kayda aittir; doğrulama (`verify=true`) etkilenmez.

Red kaydı (`authz.denied`): aynı (kullanıcı, rol, izin, neden, nesne, karar) 60 sn içinde bir kez
yazılır; ayrı bağlantıyla yazım eşzamanlı en çok 2'dir (dolu ise beklemeden atlanır, log'a düşer),
kilit beklemesi 1 sn ile sınırlıdır. `nesne` kontrol karakterlerinden arındırılır ve 200 karaktere
kırpılır. HTTP katmanını aşan rol retleri de yazılır: `record_approval` (karar rolü; mesaj etiketli,
ör. "Testçi rolü case için 'Onayla' kararı veremez") ve MCP araç reddi (rol / token kapsamı;
`nesne: mcp:<araç>`).

Developer okuma süzgeci ayrıca: `GET /failures[/{id}]` yalnız yayınlanmış bug taslağını gösterir;
SSE akışında `case.generated` ve case / bug taslağı `review.recorded` olayları gitmez,
`test_case.state` yalnız `approved`/`published`, `bug_draft.state` yalnız `published` hedefinde
gider; asistan `probe_get` case detayı API'nin kısıtlı görünümüdür (karar/ret nedeni yok) ve öneri
olgularında taslak / son onay bekleyen case ile karar bekleyen bug taslağı yer almaz. Asistan araç
izinleri: `jira_issue` anahtarın türüne göre `requirement.read` / `bug.read` / `case.read`;
`search_code` / `get_file_contents` `code.read`; `db_schema` / `db_query` `requirement.read`
(auditor/viewer hariç; `TP_ASISTAN_VERI_ROLLERI` yalnız daraltır).

Kapsam dışı kalan uçlar: `/auth/*`, `/api/auth/aiprobe/*` (giriş akışı), `/admin/kimlik-bagi`
(servis kimliği; değişmez), `/mcp` (bearer token kapsamı; değişmez), `/health`.

### 4.3 Mekanizma

- `tp_core/auth/yetki.py`: `Rol` sabitleri, `IZINLER: dict[str, frozenset[str]]`, `izinli(rol, izin)`,
  FastAPI bağımlılığı `izin("case.approve")` → `Principal` döner; değilse `authz.denied` denetim
  kaydı + 403 (`kod: "yetki_yok"`). `require_role` kaldırılır.
- Katalog testi: her router ucu ya bir `izin(...)` bağımlılığı taşır ya da §4.2 sonundaki açık
  istisna listesindedir. Yeni uç eklenip izin verilmezse test kırılır (varsayılan ret).
- Durum makinesindeki `APPROVER_ROLES` aynı katalogdan türetilir (derinlemesine savunma).
- `GET /auth/me` yanıtına `izinler: list[str]` eklenir. Portal `useIzin("case.approve")` ile düğme
  gösterir; rota koruması `RolGerekli` yerine `IzinGerekli`.
- Asistan araçları (`features/assistant/tools/probe.py`'deki uç → rol tablosu) izin kataloğundan
  türetilir; asistanın okuyabildiği veri rolün okuma izinlerini aşamaz.

## 5. Case akışı (değişen tek durum makinesi)

```
                 tester: accept | edit            analyst: approve          tester: publish
   draft ─────────────────────────────▶ ready ───────────────────▶ approved ──────────────▶ published
     ▲ │ tester: reject                    │ analyst: send_back (gerekçe)   │
     │ ▼                                   ▼                                │ tester: edit / reopen
  rejected ── tester: reopen ──▶ draft ◀───┘ ◀───────────────────────────────┘ (onay düşer)
```

- `ready` yeni durumdur. `accept` (olduğu gibi kabul) ve `edit` (düzelterek kabul) case'i `ready`
  yapar; ikisi de `review` tablosuna içerik hash'iyle yazılır.
- `approve` yalnız `ready`'den, güncel içerik hash'i Testçi kararının hash'iyle eşleşiyorsa.
  Onaylayan hesap son düzenleyen hesaptan farklı olmalıdır (rol farklı olduğu için K2'yle uyumlu).
- `send_back` `ready` → `draft`, gerekçe zorunlu.
- Yayın kapısı (`approved` → `published`) yalnız `approve` kararını onaylayan sayar
  (bugün `edit` de sayılıyordu).
- Onaylı veya yayınlanmış case'te Testçi `edit` / `reopen` yaparsa onay düşer, case `draft`'a döner
  (yayınlanmış sürüm değişmez; mevcut `superseded`/yeni sürüm davranışı korunur).
- Eski kayıtlar: göç anında `approved` / `published` case'ler olduğu gibi kalır. `draft` case'ler
  `draft` kalır. Eski `approve` kayıtları (Analist kararı) yayın kapısı için geçerli kalır.
- Ölçümler (`metrics.py`, kabul/düzeltme oranları) Testçi kararlarını (`accept`/`edit`/`reject`)
  sayar; `approve` / `send_back` ayrı "son onay" metriği olur.
- Eski analist onayı (0033): göç anında var olan, analist hesabının test_case `edit` kayıtları
  `review.eski_onay = true` işaretlenir ve yayın / kod üretimi kapısında `approve` sayılır;
  kararı verenin güncel rolüne bakılmaz.
- Gösterilen son onay (`son_onay`): en son Analist kararı, ancak ondan sonra Testçi kararı
  (`accept`/`edit`/`reject`/`reopen`) yoksa. "Taslağa al" ya da yeni kabul eski `approve`'u gizler;
  `send_back` gerekçesi Testçinin bir sonraki kararına kadar görünür.
- **Paketten sapma — K8 (ürün sahibi kararı, 2026-11-12):** paketteki T09 "yayınlanmış case
  yeniden açılır" uygulanmaz. Yayınlanmış sürüm değişmezdir (Jira/Xray'deki test ile bağ korunur);
  değişiklik yeniden üretimle (yeni sürüm, eskisi `superseded`) gelir.

## 6. Diğer akış değişiklikleri

| Konu | Bugün | Yeni |
|---|---|---|
| PO onayı | Jira etiketi veya portal | Jira kaynaklı gereksinim: yalnız Jira etiketi (`POST /requirements/{id}/po-approve` → 410 `po_onayi_jira`; simülatör kipinde simüle Jira'ya etiket). Serbest metin gereksinim (`kaynak == free_text`): portal PO onayı (`requirement.po_approve_free_text`, po; hash kontrolü) |
| CI tetik | presenter | engineer (`deploy`/`nightly`), engineer + developer (`manual`) |
| Demo kontrolleri | presenter, her kipte | admin + engineer, yalnız `TP_DEMO_MODE=1` |
| Denetim kaydı | oturum açan herkes tümünü görür | admin/auditor tümünü; diğerleri kendi olaylarını; doğrulama admin/auditor |
| Canlı olaylar | herkes | auditor ve viewer hariç |
| Yayın token'ı | analyst | tester |
| Baz değer | analyst (+po) | po |

## 7. AI Probe tarafı (`aiprobe-platform` reposu)

- `products/testing-probe.yaml`: `roles: [admin, analyst, auditor, developer, engineer, po, tester, viewer]`,
  `admin_roles: [admin, po]` (MFA zorunlu roller).
- Kişilerin AI Probe'daki canlı rol kayıtlarını (`presenter` → `admin`) güncellemek dış sisteme
  yazmadır; ayrı onayla yapılır. O zamana kadar TP `presenter`'ı `admin` sayar.

## 8. Geliştirme şeritleri

Ortak sözleşme (`yetki.py` iskeleti, katalog, `izin()` imzası, `/auth/me.izinler`) şeritler
ayrılmadan önce `feat/rol-yetki`'ye işlenir. Her şerit kendi worktree'sinde çalışır.

| Şerit | Dal | Kapsam | Dosyalar (sahip) |
|---|---|---|---|
| S1 çekirdek | `feat/rol-s1-cekirdek` | rol enum + göç (`presenter`→`admin`, `rol` check), `izin()` + `authz.denied`, `TP_ORTAM`/`TP_DEMO_MODE` + açılış kontrolü, tüm router'ların izne geçmesi (cases/publish hariç), okuma süzgeçleri (developer, audit kapsamı, artefakt), PO portal ucunun kaldırılması, `manual` tetik, asistan rol tabloları, seed hesapları, katalog testi | `auth/`, `api/routers/`, `config.py`, `models/`, `alembic/`, `seed.py`, `features/{requirements,codegen,repair,ci,bugs,demo,triage,control_tower,assistant}/` |
| S2 case akışı | `feat/rol-s2-case` | `ready` durumu, `accept`/`send_back`, kapı değişiklikleri, case/publish/tokens uçlarının izinleri, developer case süzgeci, metrikler | `workflow/states.py`, `workflow/service.py`, `features/cases/`, `features/publish/`, `api/routers/tokens.py`, case durum göçü |
| S3 portal | `feat/rol-s3-portal` | rol etiketleri, `useIzin`/`IzinGerekli`, menü ve sayfa erişimi, case inceleme ekranı (Testçi kararı / Analist son onayı), PO onay düğmesinin kaldırılması, Claude Code ve demo sayfaları, mock'lar ve testler | `review-portal/` |
| S4 platform ve doküman | `feat/rol-s4-dok` | `aiprobe-platform` ürün kaydı (yerel commit), MIMARI-SOZLESME §5, TEKNIK-TASARIM rol bölümleri, demo senaryosu/akışı, `.env.example` | `docs/`, `.env.example`, `../aiprobe-platform/products/` |

Birleştirme sırası: S1 → S2 → S3 → S4, sonra rol bazlı review döngüsü (güvenlik, ürün/analist,
QA, frontend), hedefli testler, tam paket, Chrome for Testing ile rol rol ekran turu.

## 9. Riskler ve notlar

- **011 ile çakışma:** `feat/case-gen-v3` (birleşmedi) `features/cases/` ve case inceleme ekranını
  yoğun değiştiriyor. 012 dev'den ayrılır; hangisi sonra birleşirse case karar akışını
  (`accept`/`approve` ayrımı) diğerine uyarlar.
- **Canlı demo:** deploy bu işin kapsamında değil. Deploy edilirken `.env`'e `TP_DEMO_MODE=1`
  eklenmezse demo kontrolleri kapanır; sunucu hesabı `admin` olur; demo senaryosunda case adımı
  Testçi kararı + Analist onayı olarak ikiye ayrılır (tek kişi rol değiştirerek yürütür, K2).
- **Paket önerisi dışında kalan:** acil erişim (break-glass), proje kapsamı, Erişim Yöneticisi
  ekranı, bildirim tablosunun yeniden yazımı (Jira bahsetmeleri bugünkü roller üzerinden kalır,
  yalnız yayın bildirimi Testçi'ye gider).

### Deploy notları

- **Göç kendiliğinden koşar:** `make up` (tp-vm'de `deploy/aiprobe/bin/up.sh` → `make up`) compose'un
  `migrate` servisini (`alembic upgrade head`) çalıştırır; `core-api` ve `core-worker`
  `migrate: service_completed_successfully` koşuluyla başlar. `presenter` → `admin` ve case durum
  göçleri için elle adım yoktur.
- **Ortam değişkenleri:** tp-vm'de `.env` her açılışta `tp-env` sırrından (`/run/tp/tp.env`) yazılır;
  `TP_DEMO_MODE=1` (ve gerekiyorsa `TP_ORTAM`) bu sırra eklenmelidir. Sır güncellemesi GCP'ye
  yazmadır, ayrı onayla yapılır. Compose `x-core-env` değişkenleri tek tek listeler (`env_file` yok):
  `TP_ORTAM` ve `TP_DEMO_MODE` `docker-compose.yml`'a eklenmeden `.env` değeri konteynere ulaşmaz
  (şerit tablosunda sahibi yok; S1 `config.py` ile birlikte ekler).
- **AI Probe:** ürün kaydı değişikliği (`products/testing-probe.yaml`, üretilen
  `products_config.json` aiprobe-home imajına gömülür) ancak aiprobe-home yeniden deploy edilince
  etkinleşir. Kişilerin canlı rol kayıtlarının (`presenter` → `admin`) güncellenmesi ayrı onaylı
  yazmadır; o zamana kadar TP `presenter`'ı `admin` sayar (`yetki.ESKI_ROLLER`). `admin` artık
  `admin_roles`'tadır: MFA'sız (`acr=1`) devirde `admin` rolü dönmez.
- **`docs/CANLI-DEMO-SENARYOSU.md` elle güncellenmeli:** dosya `.gitignore`'dadır (yalnız ana
  checkout'ta), şeritlerin commit'leriyle değişmez. DEMO-AKISI'na yazılan değişiklikler aynen
  uygulanır: "Sunucu" profili → Sistem Yöneticisi (`sunucu` hesabı, rol `admin`); case adımı ikiye
  ayrılır — "Case üret" ve kabul/düzelt/reddet Testçi profilinde, son onay ("Onayla" / gerekçeli
  "Geri gönder") Analist profilinde; yayın ve Claude Code token'ı Testçi; "Deploy sonrası testleri
  koş" / "Gece koşusu" Automation Engineer; demo kontrolleri ("Buton kimliğini değiştir", sıfırlama)
  Sistem Yöneticisi ya da Automation Engineer ve `.env`'de `TP_DEMO_MODE=1` gerekir; bulgu kararları
  ve "Düzeltmeleri Jira'ya yaz" Analist'te kalır; Jira story'sinde PO onayı Jira etiketiyle (değişmez).

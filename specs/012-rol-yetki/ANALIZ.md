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
| K6 | PO onayı | Dokümandaki gibi yalnız Jira: etiketi koyan aktör PO listesinde, içerik hash'i eşleşir. Portaldaki PO onay ucu ve düğmesi kalkar |
| K7 | Paketin kapsamadığı özellikler | Sahibi PO (baz değer, Jira'ya doküman düzeltmesi). İstisna: locator onarımı → Automation Engineer, Claude Code yayın token'ı → Testçi |

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
| `po` | PO | Gereksinim teyidi (yalnız Jira); baz değer ve doküman düzeltmesi |
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
| `requirement.review` | analyst | `POST /requirements/{id}/review`, `POST /findings/{id}/decision` | |
| `requirement.doc_fix` | po | `POST /requirements/{id}/apply-doc-fixes` | K7 |
| `baseline.manage` | po | `PUT/DELETE /requirements/{id}/baseline`, `POST /baseline-file/apply` | K7 |
| `case.generate` | tester | `POST /requirements/{id}/cases/generate` | gereksinim PO onaylı (mevcut kapı) |
| `case.decide` | tester | `POST /cases/{id}/decision` karar ∈ `accept`, `edit`, `reject`, `reopen`; `POST /cases/{id}/viewed` | ret nedeni zorunlu (mevcut) |
| `case.approve` | analyst | `POST /cases/{id}/decision` karar ∈ `approve`, `send_back`; `POST /requirements/{id}/review-complete` | yalnız `ready` case; `send_back` gerekçe ister |
| `case.publish` | tester | `POST /publish`, `GET /publish/preview` | onaylı + hash değişmemiş (mevcut kapı) |
| `token.issue` | tester | `POST /tokens` | yayın / IDE gönderim kanalı |
| `code.generate` | engineer | `POST /code/generate` | onaylı case (mevcut) |
| `code.break_verify` | engineer | `POST /scripts/{id}/break-verify` | |
| `code.review` | engineer | `POST /prs/{n}/review`, `POST /prs/{n}/update-branch` | |
| `code.merge` | engineer | `POST /prs/{n}/merge` | yeşil CI + korumalı dal (mevcut merge kapısı); K3 |
| `code.repair` | engineer | `POST /failures/{id}/fix` | K7 istisnası |
| `run.trigger_scheduled` | engineer | `POST /ci/trigger` tetik ∈ `deploy`, `nightly` | |
| `run.trigger_manual` | engineer, developer | `POST /ci/trigger` tetik = `manual` | developer: `TP_ORTAM≠prod` |
| `bug.decide` | tester | `POST /bug-drafts/{id}/decision`, `/prepare`, `/publish` | |
| `demo.manage` | admin, engineer | `POST /demo/break-locator`, `POST /demo/reset` | `TP_DEMO_MODE=1` |
| `audit.verify` | admin, auditor | `GET /audit?verify=true` | |

### 4.2 Okuma

| İzin | Roller | Uçlar / not |
|---|---|---|
| `dashboard.read` | hepsi | Kontrol Kulesi uçları, `GET /demo/status`, `GET /auth/me` |
| `requirement.read` | admin, analyst, po, tester, engineer, developer | gereksinim listesi/detayı, bulgular, baz değer okuma |
| `case.read` | admin, analyst, po, tester, engineer, developer* | *developer yalnız `approved`/`published` case; karar geçmişi ve chat yok |
| `code.read` | admin, analyst, tester, engineer | script listesi/detayı, ekran görüntüleri, onarım durumu |
| `run.read` | hepsi | koşu listesi/detayı |
| `run.artifacts` | admin, analyst, po, tester, engineer, developer | ham artefaktlar (auditor ve viewer hariç) |
| `failure.read` | admin, analyst, po, tester, engineer, developer | hata sınıflaması |
| `bug.read` | admin, analyst, po, tester, engineer, developer* | *developer yalnız açılmış / bağlanmış bug |
| `audit.read_all` | admin, auditor | tüm denetim kaydı |
| `audit.read_own` | analyst, po, tester, engineer, developer | yalnız kendi olayları (`aktor` = kullanıcı adı) |
| `events.read` | admin, analyst, po, tester, engineer, developer | `GET /events` (SSE) |
| `assistant.use` | hepsi | asistan ve öneriler |
| `token.read` | hepsi | kendi token'ları (`GET/DELETE /tokens`) |

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

## 6. Diğer akış değişiklikleri

| Konu | Bugün | Yeni |
|---|---|---|
| PO onayı | Jira etiketi veya portal | Yalnız Jira (`POST /requirements/{id}/po-approve` → 410). Simülatör kipinde PO onayı simüle Jira'ya etiket koyarak verilir |
| CI tetik | presenter | engineer (`deploy`/`nightly`), engineer + developer (`manual`) |
| Demo kontrolleri | presenter, her kipte | admin + engineer, yalnız `TP_DEMO_MODE=1` |
| Denetim kaydı | oturum açan herkes tümünü görür | admin/auditor tümünü; diğerleri kendi olaylarını; doğrulama admin/auditor |
| Canlı olaylar | herkes | auditor ve viewer hariç |
| Yayın token'ı | analyst | tester |
| Baz değer, doküman düzeltmesi | analyst (+po) | po |

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

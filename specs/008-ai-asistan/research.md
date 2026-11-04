# Research: Portal Asistanı ve Öneri — koda karşı doğrulama (Şerit S)

**Tarih**: 2026-11-03 · **Dal**: `feat/ai-asistan` (taban `dev`, 443a668)

Plan v6 §17.2–17.3 olgu kaynaklarının ve uç yollarının "Şerit S'de koda karşı kesinleşir" maddesi
bu belgede kapatılır. Rol ve eylem türü değişmedi; olgu kaynakları ve kural 15'in `yetki` ucu
düzeltildi. **Düzeltme (inceleme turu 1):** uygulamada iki kural koşulu daraltıldı (kural 8
`ac_eksik_esit:false`, kural 11 `onayli_case_gte:1`) ve kimlikler/operatör biçimi değişti; ayrıntı
`contracts/oneri-kurallari.md` "İlk kural seti" altındaki fark listesinde. İki daraltma için K10
kapsamında ürün sahibinin tek satırlık onayı **gerekir** (açık).

## R1. Spec numarası

- **Karar**: `specs/008-ai-asistan/`.
- **Gerekçe**: depoda yalnız `001-dev-foundation` var, ancak TEKNIK-TASARIM §21 `002-core` …
  `007-demo-readiness` adlarını sıraya ayırmıştır. 002–007'yi kullanmak bu planla çakışır.
- **Alternatif**: `002-ai-asistan` (Spec Kit betiğinin üreteceği numara) — §21 ile çeliştiği için reddedildi.

## R2. Olgu kaynakları (plan §17.2 tablosu) — doğrulama sonucu

| Olgu | Plan | Kod gerçeği | Karar |
|---|---|---|---|
| `durum` | `workflow/states.MACHINES` | `states.py:316`; requirement `new, in_review, findings_open, doc_final, pending_po, po_approved, generating, cases_ready, done, failed`; script `pending, verifying, checking, pr_open, blocked, failed, merged, closed`; bug_draft `draft, approved, dismissed, published` | Doğru |
| `po_bekleme_saat` | son `RequirementReview.olusturma` | **Yanlış kaynak**: `RequirementReview` ön inceleme sırasında (`in_review`, `features/requirements/flow.py:990`) yaratılır; bulgu/düzeltme turları sürerken bekleme fazla görünür | **Düzeltildi**: son `audit_event` (`eylem='requirement.transition'`, `nesne='requirement:<id>'`, `ozet->>'to'='pending_po'`) `zaman`'ı. `audit_event`'te `nesne` indeksi yok → Şerit R sorguyu varlık başına tek satır (`ORDER BY id DESC LIMIT 1`) yapar; p95 300 ms aşılırsa Şerit B 0017'de `audit_event(nesne)` indeksi ekler (append-only tetikleyicisine dokunmadan) |
| `po_kanal` | serileştirmedeki `po.kanal` | `serialize.po_status`: `"jira" if req.kaynak == "jira" else "portal"` | Doğru (`kaynak`'tan türetilir) |
| `ac_eksik` | `Requirement.ac_missing` | `models/requirements.py:61` | Doğru |
| `acik_bulgu_sayisi` | `consistency_finding` `open` | durum `open` var | Doğru (güncel `kontrol_turu`'ndaki `open`) |
| `inceleme_bekleyen_case`, `onayli_case` | `test_case` `draft`/`approved` | durumlar var | Doğru (`superseded` hariç) |
| `kirarak_dogrulama` | `models/codegen_feature.BREAK_DURUM` | `ScriptCodegen.break_durum` (`codegen_feature.py:119`), portal `break_verify.durum` (`lib/kapi.ts`) | Doğru; alan `script_codegen.break_durum` |
| `ci_sonuc`, `basarisiz_adimlar` | `Run.sonuc`, `Run.artefaktlar` | `RUN_SONUC = {queued, running, passed, failed, error}` | Doğru |
| `hata_sinifi` | `FAILURE_SINIF` | `{environment, flaky, test_maintenance, product_defect, test_data, unknown}` | Doğru |
| `onarim_durumu` | `ONERI_DURUMU` | `Failure.oneri_durumu`, `{none, proposed, pr_open, merged, rejected}` | Doğru |
| `flaky_tekrar` | son 10 koşuda `flaky` | `TEST_SONUC` `flaky` içerir; `test_result(run_id, test_adi, durum)` | Doğru (aynı `test_adi`, son 10 `run`) |
| `bug_taslagi_var` | ilişkili `BugDraft` | `BugDraft.failure_id`, `bug_draft_ek.ilgili_failure_ids` | Doğru (ikisi birlikte) |
| `jira_key` | varlığın anahtarı | requirement `jira_key`, bug_draft `jira_key` | Doğru |
| `butce_orani` | genel günlük bütçe | `TP_DAILY_BUDGET_USD` `x-core-env`'de → core-api görür; bugünkü `ai_call` maliyet toplamı / tavan | Doğru |
| `son_kosu_saat` | (olgu eki) | `Run.bitis` | Doğru (`tetik` `break_verify`/`local_check` hariç — Kontrol Kulesi kuralı) |
| **`bulgu_kaynakli`** | **yok** | Kural 24 ("kaynak tutarlılık bulgusu") bir olgu ister | **Eklendi**: `BugDraft.finding_id IS NOT NULL` → bool |

## R3. Rol hizalama — `yetki` uçları

Tüm `rota` eylemli kuralların `roller` kümesi uçtaki `require_role` ile eşleşir:

| Kural | Uç | Kodda rol |
|---|---|---|
| 1 | `POST /findings/{id}/decision` | analyst (`requirements/api.py`) · `APPROVER_ROLES[consistency_finding]={analyst}` |
| 6 | `POST /requirements/{id}/po-approve` | po · `APPROVER_ROLES[requirement]={po}` |
| 8 | `POST /requirements/{id}/generate-cases` | analyst (`cases/api.py`) |
| 10 | `POST /cases/{id}/decision` | analyst · `APPROVER_ROLES[test_case]={analyst}` |
| 11 | `POST /publish` | analyst |
| 13 | `POST /scripts/{id}/break-verify` | engineer |
| 14 | `POST /prs/{number}/merge` | engineer · `APPROVER_ROLES[script]={engineer}` |
| 15 | **`POST /code/generate`** (plan: break-verify) | engineer |
| 18 | `POST /failures/{id}/fix` | engineer |
| 19, 23 | `POST /bug-drafts/{id}/decision` | tester · `APPROVER_ROLES[bug_draft]={tester}` |
| 26 | `POST /ci/trigger` | presenter |

**Kural 15 düzeltmesi**: `start_break_verify` yalnız `pr_open` script'te çalışır
(`codegen/service.py:2091`); `blocked` script için anlamlı eylem yeniden üretimdir
(`POST /code/generate`, engineer). Rol değişmedi, kural hizalama testi geçer.

## R4. Portal rotaları (`rotalar.json` tohumu)

`App.tsx`: `/gereksinimler`, `/gereksinimler/:id`, `/gereksinimler/:id/caseler`,
`/gereksinimler/:id/yayin`, `/kod`, `/kod/:id`, `/kosular`, `/kosular/:id`, `/hatalar/:id`,
`/bug-taslaklari`, `/bug-taslaklari/:id`, `/kontrol-kulesi`, `/denetim`, `/claude-code`, `/demo`,
`/yol-haritasi` (+ `/giris`, `*`). Öneri ekranları: Gereksinim detay `/gereksinimler/:id`, Case
inceleme `/gereksinimler/:id/caseler`, Script detay `/kod/:id`, Koşu detay `/kosular/:id`, Hata
detay `/hatalar/:id`, Bug taslağı `/bug-taslaklari/:id`, Kontrol Kulesi `/kontrol-kulesi`, Koşular
`/kosular`.

## R5. Hata `kod` alanı — mevcut kod

- `WorkflowError.kod` sınıf başına sabit (Şerit E bu dalda yazıyor, `workflow/service.py`):
  `gecersiz_gecis` (InvalidTransition, 409), `eszamanli_gecis` (ConcurrentTransition, 409),
  `kapi_kapali` (GateClosed, 409), `onay_hash_uyusmuyor` (`OnayHashUyusmuyor(GateClosed)`, 409),
  `kosul_saglanmadi` (GuardFailed, 422), `onay_yetkisi_yok` (ApprovalNotAllowed, 403),
  `gecersiz_karar` (InvalidDecision, 422); `kod=None` → durum kodundan genel kod.
- **Plan farkı**: plan §9 "GateClosed → `onay_hash_uyusmuyor`" diyor; kodda ayrı alt sınıf var ve
  `GateClosed` kendisi `kapi_kapali`. Sözleşme koda uyar (MIMARI-SOZLESME §5 enum).
- `BudgetExceeded.status_code = 402` → `butce_asildi`.
- CSRF reddi ara katmanda (`api/csrf.py`) → `kaynak_reddi` doğrudan gövdeye yazılır.

## R6. Migrasyon numarası ve kanal

Son migrasyon `0016_run_aria` → asistan migrasyonu `0017_asistan` doğru. `models/enums.TOOL_KANAL`
bu dalda `asistan`'ı içeriyor (Şerit B sürüyor).

## R7. "Jira'yı aç" — yeni kayıt sayfası

- `JIRA_BROWSE_URL` `x-core-env`'de (compose varsayılanı jira-sim'in yerel adresi);
  `RestJira.issue_url` (`integrations/jira.py:488`) mevcut.
- `/secure/CreateIssue!default.jspa` Jira Server/DC'de belgelenmiş; Jira Cloud'da da oluşturma
  ekranına yönlendirdiği bilinen davranıştır, ancak bu oturumda dış ağ erişimi olmadığından **canlı
  doğrulanamadı**. Karar: varsayılan yol bu; Şerit H gerçek Jira Cloud'a karşı bir kez dener
  (GERCEK-SISTEMLER kontrol listesi). Çalışmazsa operatör `JIRA_CREATE_URL` verir; o da yoksa kart
  yalnız "Kopyala" gösterir. Simülatörde bağlantı hiç yok.

## R8. Ortam değişkenleri yeri

- core-api'nin görmesi gerekenler (öneri ucu, status, hız sınırı): `TP_ASISTAN_ONERI`,
  `TP_ASISTAN_SAKLAMA_GUN`, `TP_WORKER_ASISTAN_PARALEL` (global sınır hesabı), `JIRA_CREATE_URL`
  → `x-core-env`. Status gerekçesi (`worker_yok`, `maskeleme_kapali`) worker'ın `asistan_durum`
  satırından okunur; core-api bunun için ortam değişkeni okumaz.
- Yalnız core-worker: `TP_ASISTAN_MODEL_MODE`, `TP_ASISTAN_MUSTERI_VERISI`,
  `TP_ASISTAN_OTOMATIK_DERIN`, `TP_ASISTAN_VERI_ROLLERI`,
  `TP_WORKER_ASISTAN_SERIT`, `GITHUB_ACTIONS_READ_TOKEN` (sır), `ANTHROPIC_API_KEY` (mevcut).
  `TP_ASISTAN_MODEL_MODE` core-api'ye **verilmez** (İlke II/K7: core-api kipi bilmez).

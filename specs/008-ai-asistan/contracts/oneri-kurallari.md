# Sözleşme: Öneri kural şeması, olgu arayüzü ve ilk kural seti

Kaynak: plan §17.2–17.4 (kural matrisi K10 ile onaylı). Kod doğrulaması: [research.md](../research.md)
R2–R4. Dosyalar (Şerit A): `rules/assistant/oneriler.yaml`, `rules/assistant/jira-taslaklari.yaml`,
`rules/assistant/rotalar.json`. Değerlendirici (Şerit R): `core/src/tp_core/features/assistant/oneri.py`.

## Kural dosyası

```yaml
kurallar:
  - id: gereksinim-po-bekliyor-jira     # tekil, kebab-case
    ekran: /gereksinimler/:id           # rotalar.json kalıbı; "*" = ekran dışı özet
    varlik: requirement                 # requirement|consistency_finding|test_case|script|run|failure|bug_draft|null
    roller: [analyst]                   # analyst|po|engineer|tester|presenter
    kosul:                              # kapalı operatör kümesi; hepsi VE; ifade değerlendirme YOK
      durum_in: [pending_po]
      po_bekleme_saat_gte: 24
      po_kanal_esit: jira
    oncelik: 80                         # 0–100; panelde azalan
    baslik: "PO onayı {po_bekleme_gun} gündür bekliyor"
    neden: "Case üretimi PO onayı olmadan başlamaz. …"
    eylem:
      tur: jira_yorum                   # rota | jira_taslak | jira_yorum | jira_kaydi | bilgi
      sablon: po-hatirlatma             # jira_taslak / jira_yorum için zorunlu
      rota: null                        # rota için zorunlu (rotalar.json kalıbı, :id varlıktan doldurulur; isteğe bağlı #çapa)
      yetki: null                       # rota için zorunlu: {uc: "POST /…"}
    aciklama: "…"                       # "Açıklamayı göster" (model kapalı) uzun metni; neden'den uzun
    tekrar_saat: 24                     # "Yaptım" sonrası aynı varlık+durumda yeniden gösterme
bos_ekranlar:                           # kapsam matrisi: bilinçli boş (rota × rol)
  - {ekran: /denetim, roller: [analyst, po, engineer, tester, presenter]}
```

Bilinmeyen alan, olgu, operatör, yer tutucu, eylem türü, rota veya şablon → kural testi düşer.

## Olgu arayüzü (Şerit R uygular; Şerit D1 öneri modunda aynı fonksiyonu çağırır)

```python
def olgular(
    session: Session,
    kullanici: Principal,
    varlik_tur: str | None,
    varlik_id: uuid.UUID | None,
    *,
    simdi: datetime,
) -> dict[str, object]:
    """Varlık okuma kuralları `probe_get` ile aynı (uç düzeyi rol kısıtı); erişim yoksa
    `VarlikBulunamadi` (API 404). Dönen sözlük yalnız aşağıdaki anahtarları taşır; varlık türüne
    uymayan olgu anahtarı dönmez (koşulda kullanılırsa kural eşleşmez)."""

def oneriler(
    session: Session, kullanici: Principal, rota: str, varlik_tur: str | None,
    varlik_id: uuid.UUID | None, *, simdi: datetime,
) -> OneriSonucu:  # {oneriler, ekranda_kural_var, bastirilan, diger_ekranlar}
```

| Olgu | Varlık | Tür | Kaynak (koda karşı doğrulandı) |
|---|---|---|---|
| `durum` | requirement, consistency_finding, test_case, script, bug_draft | str | varlığın `durum` alanı (`workflow/states.MACHINES`); `run` ve `failure`'da `durum` yoktur (koşu için `ci_sonuc`) |
| `po_bekleme_saat` | requirement | int (saat) | `durum='pending_po'` iken son `audit_event` (`eylem='requirement.transition'`, `nesne='requirement:<id>'`, `ozet->>'to'='pending_po'`) `zaman`'ından beri; iz yoksa son `RequirementReview.olusturma` |
| `po_kanal` | requirement | `portal`\|`jira` | `serialize.po_status` (`"jira" if kaynak=="jira" else "portal"`) |
| `ac_eksik` | requirement | bool | `Requirement.ac_missing` |
| `acik_bulgu_sayisi` | requirement | int | `consistency_finding.durum='open'` ve `kanit_dogrulandi=true` (tur filtresi yok: önceki turların bulguları kararlaşmış olduğundan `open` değildir) |
| `inceleme_bekleyen_case` | requirement | int | `test_case.durum='draft'` (superseded hariç) |
| `onayli_case` | requirement | int | `test_case.durum='approved'` |
| `kirarak_dogrulama` | script | `not_started`\|`running`\|`passed`\|`weak`\|`failed` | `ScriptCodegen.break_durum` (`BREAK_DURUM`) |
| `defect_adayi` | script | bool | `ScriptCodegen.engel_turu='defect_candidate'` ya da `yerel_kontrol.sinif='defect_adayi'` (atlanmamış); üretim kaydı yoksa olgu yok (Kod.tsx "Yeniden üret" koşuluyla aynı) |
| `ci_sonuc` | run | `RUN_SONUC` | `Run.sonuc` |
| `basarisiz_adimlar` | run | list[str] | `Run.artefaktlar["basarisiz_adimlar"]` (yalnız `_var`/`_yok`) |
| `hata_sinifi` | failure | `FAILURE_SINIF` | `Failure.sinif` |
| `onarim_durumu` | failure | `ONERI_DURUMU` | `Failure.oneri_durumu` |
| `flaky_tekrar` | failure | int | aynı `test_adi`'nın son 10 koşusunda `test_result.durum='flaky'` sayısı |
| `bug_taslagi_var` | failure | bool | `BugDraft.failure_id` veya `bug_draft_ek.ilgili_failure_ids` |
| `bulgu_kaynakli` | bug_draft | bool | `BugDraft.finding_id IS NOT NULL` (**S'de eklendi**, kural 24) |
| `jira_key` | requirement, bug_draft | str\|None | varlığın `jira_key` alanı |
| `butce_orani` | — | float 0–1 | bugünkü `ai_call` maliyet toplamı / `TP_DAILY_BUDGET_USD` |
| `son_kosu_saat` | — | int\|None | son `Run.bitis`'ten beri (tetik `break_verify`/`local_check` hariç); koşu yoksa None |

**Türev yer tutucular** (yalnız metinde): `{po_bekleme_gun}` = `po_bekleme_saat // 24` (en az 1),
`{butce_yuzde}` = `round(butce_orani*100)`, `{N}` yerine olgu adı kullanılır
(`{acik_bulgu_sayisi}`, `{inceleme_bekleyen_case}`, `{flaky_tekrar}`). Serbest metin taşıyan varlık
alanı (başlık, Jira özeti) **yer tutucu olamaz**. Yerleştirme tek geçişli güvenli değiştirmedir
(`str.format` değil; değerdeki `{…}` yeniden açılmaz); çıktı düz metin.

## Operatörler

`durum_in: [..]` ve genel hâli `<olgu>_in: [..]` (sayısal olmayan olgular), `<olgu>_gte: sayı`, `<olgu>_lte: sayı`, `<olgu>_esit: değer`, `<olgu>_var: true`,
`<olgu>_yok: true` (bool olguda `_var` = True, liste/metinde boş değil). Hepsi VE.

## Jira taslak şablonları (`rules/assistant/jira-taslaklari.yaml`)

`{id, tur: Task|Bug|Story|yorum, ozet, aciklama, etiketler}`; metinler olgu yer tutuculu, **URL
içermez** (şema testi). Tohum: `po-hatirlatma`, `ac-eksik`, `flaky-task`, `ortam-hatasi-task`,
`test-verisi-task`.

## Kural testleri (Şerit A şema, Şerit R davranış)

- **Sistem hattı yasağı**: `/bug-taslaklari/*` (`bug_draft`), `/gereksinimler/:id/yayin`,
  `consistency_finding` ekran/varlıklarında `jira_taslak`/`jira_yorum` eylemi yasak (yalnız `rota`/
  `bilgi`). Hata detayı listede değildir.
- **Rol hizalama**: `rota` eylemli her kuralın `roller` ⊆ `eylem.yetki.uc` rotasının `require_role`
  kümesi (FastAPI rotasından okunur) ∩ varsa `APPROVER_ROLES[varlik]`.
- **Kapsam matrisi**: her (rota × rol) için ≥ 1 kural veya `bos_ekranlar` kaydı. Kuralsız (rota ×
  rol) → `ekranda_kural_var=false` → düğme gizli.
- Her kural için ≥ 1 olumlu + 1 olumsuz tohum vakası; 5 rol parametrize.

## Bağlantı ("Jira'yı aç") — yalnız sunucu

- `jira_yorum`, `jira_kaydi` → `RestJira.issue_url(anahtar)` (bilinen anahtar; jira-sim'de de çalışır).
- `jira_taslak` → `JIRA_CREATE_URL` (açılışta doğrulanır: `https` — simülatörde `http://127.0.0.1` —
  ve kökeni `JIRA_BROWSE_URL` ile aynı; değilse yok sayılır + uyarı) varsa o; yoksa gerçek Jira'da
  `JIRA_BROWSE_URL` kökü + `/secure/CreateIssue!default.jspa`; simülatörde bağlantı yok (kartta "Demo
  Jira'sında kayıt oluşturma sayfası yok"). Taslak metni URL'e konmaz.
- Yanıttaki `eylem` (kural kartı): `{tur, rota?, anahtar?, taslak?: {proje, tur, ozet, aciklama,
  etiketler}, baglanti?: string, adim_notu?: "Proje: {JIRA_PROJECT}, Tür: {tur} seçin; metni
  yapıştırın."}`.

## İlk kural seti (26 kural)

Ekranlar: GD `/gereksinimler/:id`, CI `/gereksinimler/:id/caseler`, SD `/kod/:id`, KD `/kosular/:id`,
HD `/hatalar/:id`, BT `/bug-taslaklari/:id`, KK `/kontrol-kulesi`, K `/kosular`.

| # | `id` | Ekran | Rol | Koşul | Eylem | `yetki.uc` |
|---|---|---|---|---|---|---|
| 1 | `gereksinim-bulgu-karari` | GD | analyst | `durum_in:[findings_open]`, `acik_bulgu_sayisi_gte:1` | rota GD | `POST /findings/{finding_id}/decision` |
| 2 | `gereksinim-ac-eksik-jira` | GD | analyst | `ac_eksik_esit:true`, `jira_key_var` | jira_yorum `ac-eksik` | — |
| 3 | `gereksinim-ac-eksik` | GD | analyst | `ac_eksik_esit:true`, `jira_key_yok` | bilgi | — |
| 4 | `gereksinim-po-hatirlatma-jira` | GD | analyst | `durum_in:[pending_po]`, `po_bekleme_saat_gte:24`, `po_kanal_esit:jira`, `jira_key_var` | jira_yorum `po-hatirlatma` | — |
| 5 | `gereksinim-po-bekliyor-portal` | GD | analyst | `durum_in:[pending_po]`, `po_bekleme_saat_gte:24`, `po_kanal_esit:portal` | bilgi | — |
| 6 | `gereksinim-po-onayi-portal` | GD | po | `durum_in:[pending_po]`, `po_kanal_esit:portal` | rota GD | `POST /requirements/{req_id}/po-approve` |
| 7 | `gereksinim-po-onayi-jira` | GD | po | `durum_in:[pending_po]`, `po_kanal_esit:jira`, `jira_key_var` | jira_kaydi | — |
| 8 | `gereksinim-case-uret` | GD | analyst | `durum_in:[po_approved]`, `ac_eksik_esit:false` (bkz. not) | rota GD | `POST /requirements/{requirement_id}/generate-cases` |
| 9 | `gereksinim-basarisiz` | GD | analyst | `durum_in:[failed]` | bilgi | — |
| 10 | `case-inceleme-bekliyor` | CI | analyst | `inceleme_bekleyen_case_gte:1` | rota CI | `POST /cases/{case_id}/decision` |
| 11 | `case-yayina-hazir` | CI | analyst | `durum_in:[cases_ready]`, `inceleme_bekleyen_case_esit:0`, `onayli_case_gte:1` | rota `/gereksinimler/:id/yayin` | `POST /publish` |
| 12 | `case-inceleme-analistte` | CI | tester | `inceleme_bekleyen_case_gte:1` | bilgi | — |
| 13 | `script-kirarak-dogrula` | SD | engineer | `durum_in:[pr_open]`, `kirarak_dogrulama_in:[not_started, weak, failed]` (bkz. not) | rota SD | `POST /scripts/{script_id}/break-verify` |
| 14 | `script-merge-karari` | SD | engineer | `durum_in:[pr_open]`, `kirarak_dogrulama_esit:passed` | rota SD | `POST /prs/{number}/merge` |
| 15 | `script-insana-dustu` | SD | engineer | `durum_in:[blocked]`, `defect_adayi_esit:false` | rota `/kod` | **`POST /code/generate`** (research R3) |
| 16 | `kosu-ortam-hatasi-task` | KD | engineer | `ci_sonuc_esit:error` | jira_taslak `ortam-hatasi-task` | — |
| 17 | `kosu-ortam-hatasi-bilgi` | KD | presenter | `ci_sonuc_esit:error` | bilgi | — |
| 18 | `hata-bakim-onarim` | HD | engineer | `hata_sinifi_esit:test_maintenance`, `onarim_durumu_esit:none` | rota HD | `POST /failures/{failure_id}/fix` |
| 19 | `hata-bug-taslagi-karari` | HD | tester | `hata_sinifi_esit:product_defect`, `bug_taslagi_var_esit:true` | rota `/bug-taslaklari/:id` | `POST /bug-drafts/{draft_id}/decision` |
| 20 | `hata-flaky-task` | HD | engineer | `hata_sinifi_esit:flaky`, `flaky_tekrar_gte:3` | jira_taslak `flaky-task` | — |
| 21 | `hata-test-verisi-task` | HD | tester | `hata_sinifi_esit:test_data` | jira_taslak `test-verisi-task` | — |
| 22 | `hata-test-verisi-bilgi` | HD | engineer | `hata_sinifi_esit:test_data` | bilgi | — |
| 23 | `bug-taslagi-karari` | BT | tester | `durum_in:[draft]` | rota BT | `POST /bug-drafts/{draft_id}/decision` |
| 24 | `bug-taslagi-bulgudan` | BT | analyst | `durum_in:[draft]`, `bulgu_kaynakli_esit:true` | bilgi | — |
| 25 | `butce-uyarisi` | KK | presenter | `butce_orani_gte:0.8` | bilgi | — |
| 26 | `guncel-kosu-yok` | K | presenter | `son_kosu_saat_gte:24` | rota K | `POST /ci/trigger` |

Tablo `rules/assistant/oneriler.yaml` ile birebirdir (kaynak dosyadır; çelişkide dosya geçerlidir).
Plan v6 §17.3 tablosundan farklar ve nedenleri:

- **Kimlikler** (2026-11-03 Şerit S): 4, 6, 7, 12, 14, 16, 18–21, 23, 24 `id`'leri dosyadaki adlarla
  yeniden adlandırıldı; rol, ekran ve eylem türü aynı.
- **Operatör biçimi (davranış aynı):** bool olgular `_var` yerine `_esit:true` ile yazılır (2, 3, 19,
  24) — `_var` "değer tanımlı" demektir, `false` da tanımlı sayılır; `inceleme_bekleyen_case_lte:0`
  yerine `_esit:0` (11); 4 ve 7'deki `jira_key_var` eylemin (jira_yorum/jira_kaydi) zaten istediği
  ön koşulun açık yazımıdır. Çapalar eylemde ayrı `capa` alanıdır (`rota` yalnız rota kalıbıdır,
  `lib/rotalar.ts` ile eşleşir): 1 `bulgular`, 6 `po-onay`, 8 `case-uret`, 13 `kirarak-dogrula`,
  14 `pr`, 18 `onarim`. Portal hedef öğeleri bu id'lerle taşır ve hash'e kaydırır
  (`review-portal/src/lib/capa.ts`; `capa.test.tsx` her çapanın sayfada bulunduğunu sınar).
- **Davranış daraltmaları (K10 ürün sahibi onayı gerekir, açık):**
  - Kural 8 `ac_eksik_esit:false`: AC eksik bir `po_approved` gereksinimde analist "case üret"
    önerisini **görmez**; yerine kural 2/3 (AC eksik) görünür. Gerekçe: eksik AC ile üretilen case'ler
    incelemede geri döner.
  - Kural 11 `onayli_case_gte:1`: hiç onaylı case yokken (hepsi reddedilmiş) "yayına hazır" denmez.
  - Kural 1 `acik_bulgu_sayisi_gte:1`: `findings_open` durumunda kanıtı doğrulanmış açık bulgu yoksa
    (hepsi kararlaşmış ya da kanıtsız) "N bulgu kararınızı bekliyor" denmez; başlıktaki `{acik_bulgu_sayisi}`
    yer tutucusu 0 olamaz. (2026-11-04, inceleme tur 2'de fark listesine eklendi.)
  - Kural 15 `defect_adayi_esit:false` (2026-11-04): defect adayında test doğrudur (uygulama farklı
    davranıyor); yeniden üretim önerilmez, karar triage'dadır (Kod.tsx "Yeniden üret" düğmesiyle aynı
    ayrım). Üretim kaydı olmayan (onarım) script'te olgu yoktur ve kural düşmez.
- **Kural 15 eylemi:** `yetki.uc` `POST /code/generate` (research R3); rol (engineer) değişmedi.
  Eylem rotası `/kod/:id` yerine **`/kod`** (2026-11-04): "Yeniden üret" düğmesi yalnız Kod listesinde
  var, script detayında yok; `/kod/:id` hedefi mühendisi bulunduğu ekranda bırakıyordu. Bu bir eylem
  hedefi değişikliğidir, aşağıdaki K10 yeniden onay listesine girer.
- **K10 yeniden onay (açık, 2026-11-04):** kural 1, 8, 11 ve 15'teki daraltmalar ile kural 15'in eylem
  rotası ürün sahibinin onayını bekler (plan §2 K10: "kural içeriği değişirse yeniden onay"). Onay
  verildiğinde plan K10 satırı tarihle güncellenir; verilene dek bu sözleşme ve `oneriler.yaml` geçerli
  kabul edilir, yalnız `dev`'de bayrak arkasındadır.

**Not (kural 13):** "`kirarak_dogrulama ∈ {not_started, weak, failed}`" kapalı operatör kümesinde
`_in` yalnız `durum` içindir; kural 13 üç ayrı kuralla değil, `kirarak_dogrulama_in: [not_started,
weak, failed]` ile ifade edilir → operatör kümesine **`<olgu>_in`** (sayısal olmayan olgular için)
eklenir; `durum_in` bunun özel hâlidir. Kural içeriği değişmez.

`*` (ekran dışı) özet: "Diğer ekranlarda sizi bekleyen N iş → Git" — yanıtta `diger_ekranlar
{sayi, rota}` (`probe_my_queue` sayımı), rozete sayılmaz.

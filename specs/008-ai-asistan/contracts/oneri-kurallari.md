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
| `po_bekleme_saat` | requirement | int (saat) | `durum='pending_po'` iken son `audit_event` (`eylem='requirement.transition'`, `nesne='requirement:<id>'`, `ozet->>'to'='pending_po'`) `zaman`'ından beri |
| `po_kanal` | requirement | `portal`\|`jira` | `serialize.po_status` (`"jira" if kaynak=="jira" else "portal"`) |
| `ac_eksik` | requirement | bool | `Requirement.ac_missing` |
| `acik_bulgu_sayisi` | requirement | int | güncel `kontrol_turu`'nda `consistency_finding.durum='open'` |
| `inceleme_bekleyen_case` | requirement | int | `test_case.durum='draft'` (superseded hariç) |
| `onayli_case` | requirement | int | `test_case.durum='approved'` |
| `kirarak_dogrulama` | script | `not_started`\|`running`\|`passed`\|`weak`\|`failed` | `ScriptCodegen.break_durum` (`BREAK_DURUM`) |
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
| 1 | `gereksinim-bulgu-karari` | GD | analyst | `durum_in:[findings_open]`, `acik_bulgu_sayisi_gte:1` | rota GD `#bulgular` | `POST /findings/{id}/decision` |
| 2 | `gereksinim-ac-eksik-jira` | GD | analyst | `ac_eksik_var`, `jira_key_var` | jira_yorum `ac-eksik` | — |
| 3 | `gereksinim-ac-eksik` | GD | analyst | `ac_eksik_var`, `jira_key_yok` | bilgi | — |
| 4 | `gereksinim-po-bekliyor-jira` | GD | analyst | `durum_in:[pending_po]`, `po_bekleme_saat_gte:24`, `po_kanal_esit:jira` | jira_yorum `po-hatirlatma` | — |
| 5 | `gereksinim-po-bekliyor-portal` | GD | analyst | `durum_in:[pending_po]`, `po_bekleme_saat_gte:24`, `po_kanal_esit:portal` | bilgi | — |
| 6 | `po-onay-portal` | GD | po | `durum_in:[pending_po]`, `po_kanal_esit:portal` | rota GD `#po-onay` | `POST /requirements/{id}/po-approve` |
| 7 | `po-onay-jira` | GD | po | `durum_in:[pending_po]`, `po_kanal_esit:jira` | jira_kaydi | — |
| 8 | `gereksinim-case-uret` | GD | analyst | `durum_in:[po_approved]` | rota GD | `POST /requirements/{id}/generate-cases` |
| 9 | `gereksinim-basarisiz` | GD | analyst | `durum_in:[failed]` | bilgi | — |
| 10 | `case-inceleme-bekliyor` | CI | analyst | `inceleme_bekleyen_case_gte:1` | rota CI | `POST /cases/{id}/decision` |
| 11 | `case-yayina-hazir` | CI | analyst | `durum_in:[cases_ready]`, `inceleme_bekleyen_case_lte:0` | rota `/gereksinimler/:id/yayin` | `POST /publish` |
| 12 | `case-analistte` | CI | tester | `inceleme_bekleyen_case_gte:1` | bilgi | — |
| 13 | `script-kirarak-dogrula` | SD | engineer | `durum_in:[pr_open]`, `kirarak_dogrulama_in:[not_started, weak, failed]` (bkz. not) | rota SD | `POST /scripts/{id}/break-verify` |
| 14 | `script-merge-bekliyor` | SD | engineer | `durum_in:[pr_open]`, `kirarak_dogrulama_esit:passed` | rota SD `#pr` | `POST /prs/{number}/merge` |
| 15 | `script-insana-dustu` | SD | engineer | `durum_in:[blocked]` | rota SD | **`POST /code/generate`** (research R3) |
| 16 | `kosu-ortam-hatasi` | KD | engineer | `ci_sonuc_esit:error` | jira_taslak `ortam-hatasi-task` | — |
| 17 | `kosu-ortam-hatasi-bilgi` | KD | presenter | `ci_sonuc_esit:error` | bilgi | — |
| 18 | `hata-onarim-baslat` | HD | engineer | `hata_sinifi_esit:test_maintenance`, `onarim_durumu_esit:none` | rota HD | `POST /failures/{id}/fix` |
| 19 | `hata-bug-taslagi` | HD | tester | `hata_sinifi_esit:product_defect`, `bug_taslagi_var` | rota `/bug-taslaklari/:id` | `POST /bug-drafts/{id}/decision` |
| 20 | `hata-flaky-takip` | HD | engineer | `hata_sinifi_esit:flaky`, `flaky_tekrar_gte:3` | jira_taslak `flaky-task` | — |
| 21 | `hata-test-verisi` | HD | tester | `hata_sinifi_esit:test_data` | jira_taslak `test-verisi-task` | — |
| 22 | `hata-test-verisi-bilgi` | HD | engineer | `hata_sinifi_esit:test_data` | bilgi | — |
| 23 | `bug-taslak-karari` | BT | tester | `durum_in:[draft]` | rota BT | `POST /bug-drafts/{id}/decision` |
| 24 | `bug-taslak-bulgudan` | BT | analyst | `durum_in:[draft]`, `bulgu_kaynakli_var` | bilgi | — |
| 25 | `butce-uyarisi` | KK | presenter | `butce_orani_gte:0.8` | bilgi | — |
| 26 | `guncel-kosu-yok` | K | presenter | `son_kosu_saat_gte:24` | rota K | `POST /ci/trigger` |

**Not (kural 13):** "`kirarak_dogrulama ∈ {not_started, weak, failed}`" kapalı operatör kümesinde
`_in` yalnız `durum` içindir; kural 13 üç ayrı kuralla değil, `kirarak_dogrulama_in: [not_started,
weak, failed]` ile ifade edilir → operatör kümesine **`<olgu>_in`** (sayısal olmayan olgular için)
eklenir; `durum_in` bunun özel hâlidir. Kural içeriği değişmez.

`*` (ekran dışı) özet: "Diğer ekranlarda sizi bekleyen N iş → Git" — yanıtta `diger_ekranlar
{sayi, rota}` (`probe_my_queue` sayımı), rozete sayılmaz.

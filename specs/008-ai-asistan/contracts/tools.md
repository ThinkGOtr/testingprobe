# Sözleşme: Asistan araçları

Kaynak: plan §5, §10.3. `ALLOWED_AGENT_TOOLS["assistant"]` = `ALLOWED_AGENT_TOOLS["assistant_deep"]`
= aşağıdaki **13 araç** (Şerit A; `FORBIDDEN_TOOLS` ile kesişmez, adlar
`test_allowed_agent_tool_names_are_valid` kuralına uyar). Tüm roller aynı listeyi görür; rol kısıtı
araç uygulamasında, iş yükündeki `kullanici_id`/rol ile (asla argümandan).

| Araç | Girdi | Çıktı (özet) | Rol kısıtı | Şerit |
|---|---|---|---|---|
| `product_search` | `{query: string, kapsam?: "portal"\|"core"\|"docs"}` | ≤ 50 sonuç `yol:satır: metin` (sabit metin araması, MANIFEST dosyaları) | yok | C1 |
| `product_read` | `{path: string, start_line?: int, end_line?: int}` | ≤ 400 satır; boş `path` → dosya listesi; MANIFEST anahtarıyla **birebir** | yok | C1 |
| `probe_get` | `{tur: "requirement"\|"case"\|"script"\|"run"\|"failure"\|"bug_draft", id_or_key: string}` | durum, bekleyen kapı, sorumlu rol, son hata, ekran rotası; requirement'ta Jira anahtarı + PO cevapları özeti | uç-düzeyi rol kısıtı aynen (ör. `GET /publish/preview` yalnız analist) | C2 |
| `probe_list` | `{tur, durum?: string, limit?: 1–20}` | kısa liste | aynı | C2 |
| `probe_jobs` | `{varlik_id: uuid}` | son 10 iş: tür/durum/kısa hata | aynı | C2 |
| `probe_audit` | `{varlik_id: uuid, limit?: 1–20}` | onay/ret/AI çağrısı izi (özet) | aynı | C2 |
| `probe_my_queue` | `{}` | çağıranın rolüne düşen bekleyen işler | rol oturumdan | C2 |
| `jira_issue` | `{anahtar: string, yorum_limit?: 1–10 (vars. 5)}` | özet, tür, durum, etiketler, açıklama ≤ 3000, son N yorum (yazar **etiketi**, tarih, metin ≤ 1500), toplam yorum, kısıtlı yorum sayısı | yok (kısıtlı yorumlar zaten elenir) | J |
| `ci_log` | `{run_id: uuid, ara?: string ≤ 80 (sabit metin), satir?: 20–200 (vars. 120)}` | ≤ 16 KB metin + kaynak (`db_ozet`\|`yerel`\|`github`) + satır aralığı | yok | J |
| `search_code` | mevcut | mevcut (`CodeTools`) | yok | mevcut |
| `get_file_contents` | mevcut | mevcut (`CodeTools`) | yok | mevcut |
| `db_schema` | mevcut | mevcut (`DataTools`) | `TP_ASISTAN_VERI_ROLLERI` (boş = tüm roller) | mevcut |
| `db_query` | mevcut | mevcut (`DataTools`/`sqlguard`) | `TP_ASISTAN_VERI_ROLLERI` | mevcut |

Hiçbir araç `issue_url`, ham ad/e-posta/accountId, token, parola veya oturum alanı döndürmez.

## Ortak sarmalayıcı (`features/assistant/tools/base.py`, Şerit C2)

- Mesaj başına **tek maskeleme oturumu**: `masker = PiiMasker(enabled=TP_PII_MASKING,
  allowlist=load_pii_allowlist(rules_dir))`, `oturum = masker.new_session()`; geçide
  `run_agent(..., masking_session=oturum)`, `DataTools(..., session=oturum)`.
- **Yeni araçlar** (`product_*`, `probe_*`, `jira_issue`, `ci_log`): (1) sonuç → (2)
  `scrub_secret_patterns` (+ çalışma anı sır değerleri) → (3) `oturum.mask_text` → (4) kanıt havuzu
  kaydı → (5) `wrap_tool_result` (`<untrusted kind=…>`).
- **Mevcut dört araç** zaten sarıyor/maskeliyor: yalnız (2) ve (4) uygulanır (çift maske/sarma yok).
- **Kanıt havuzu** (iş belleği, kalıcı değil): `kN` → `{tur, metin (modele giden), sha256, sql?,
  result_digest?}`; ham (maskesiz) sonuç **tutulmaz**; iş bitince temizlenir; hata kayıtlarına
  `str(exc)` veya araç sonucu yazılmaz. Modele giden sonuç `[kanit:kN]` ile başlar.
- Araç hatası işi düşürmez: sınıf metni döner ("Jira şu an yanıt vermiyor", "Jira meşgul", "log
  alınamadı", "bilinmeyen anahtar", "log yok").

## `jira_issue` kuralları (Şerit J)

- Anahtar `re.fullmatch(r"[A-Z][A-Z0-9]+-[0-9]+", s, re.ASCII)` **ve** Testing Probe'da kayıtlı
  (`Requirement.jira_key`, `BugDraft.jira_key`, `ExternalRef` `sistem IN ('jira','xray') AND
  durum='created' AND external_key IS NOT NULL`); değilse istek yok. Mesaj başına ≤ 3 farklı anahtar;
  aynı anahtar mesajda tek istek.
- Okuyucu: `integrations/jira.JiraOkuyucu` (`get_issue`, `son_yorumlar`, `issue_url`; yazma metodu
  yok), `get_jira_okuma(timeout_s, toplam_sure_s)`, `JIRA_READ_*` kimliği; httpx transport'u GET dışını
  istisnayla reddeder.
- `son_yorumlar(key, n)`: `GET /issue/{k}/comment?maxResults=1` (toplam) → `startAt=max(0,total-n)
  &maxResults=n` (en çok 2 istek).
- Süre: istek başı `min(8, kalan)` sn, araç toplamı `min(12, kalan)`, `max_retries=1`; kalan süreyi
  aşan bekleme → `JiraUnavailable`. 401/403/5xx → yalnız sınıf ("Jira erişim hatası").
- Global kova `jira_global` 30/dk → "Jira meşgul".
- Kısıtlı yorum (`visibility` dolu veya `jsdPublic=false`) elenir. Yazar etiketi: bot (`has_bot_header`)
  → "Testing Probe botu"; `JiraSettings.po_accounts` → "PO"; `JIRA_HESAP_*` → portal rol etiketi;
  diğerleri → "Kişi-1" …; ADF mention'ları aynı kuralla.

## `ci_log` kuralları (Şerit J)

- Kaynak sırası: (0) `run.artefaktlar` adım özetleri (`adimlar[*].error/reason`, `basarisiz_adimlar`,
  `runner_hata`, `uyarilar`, `conclusion`); (1) `features/ci/service.log_yolu(run) -> (kok, yol) | None`
  + `features/ci/artifacts.coz`; (2) `GitHubCiOkuyucu.jobs(run.github_run_id)` → `job_logs` (başarısız
  işler önce; `GITHUB_ACTIONS_READ_TOKEN` varsa o, yoksa mevcut okuma kimliği).
- Güvenli açma: `os.open(yol, O_RDONLY | O_NOFOLLOW)`, `fstat` `S_ISREG` + `coz` sonrası
  `st_dev/st_ino` eşitliği.
- Akış: son 256 KB halka tampon, toplam ≤ 20 MB, `min(10, kalan)` sn, çapraz köken yönlendirmede
  `Authorization` düşer.
- İşleme: kuyruk → ilk yarım satır atılır → UTF-8 `replace` → ANSI + GitHub zaman damgası temizliği →
  sır temizliği → maskeleme → `ara` (±3 bağlam, ≤ 50 eşleşme) veya son `satir` satır → ≤ 16 KB.

## `scrub_secret_patterns` (Şerit C1, `gateway/masking.py`)

Desenler: `github_pat_`, `gh[pousr]_[A-Za-z0-9]{20,}`, `sk-ant-`, `ATATT`, `AIza`,
`AKIA[0-9A-Z]{16}`, `xox[abposr]-`, `npm_[A-Za-z0-9]{20,}`, JWT `eyJ[\w-]+\.[\w-]+\.[\w-]+`,
`PRIVATE KEY`, `tpt_[A-Za-z0-9]{8,}`, `tpk_`, `Authorization: (Bearer|Basic|token) …`,
`(SEED_USER_PASSWORD|TP_SESSION_SECRET|JIRA_[A-Z_]*TOKEN)=…`, URL içi kimlik
`[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s]+@` + `known_secret_values` + çalışma anı sır değerleri
(`SECRET_ENV_VARS` genişler: `ANTHROPIC_API_KEY`, `GITHUB_*TOKEN`, `GH_APP_PRIVATE_KEY`,
`JIRA_*_TOKEN`, `TP_APP_PASSWORD`, `TP_SESSION_SECRET` …; ≥ 8 karakter). Testlerdeki sahte token'lar
çalışma anında birleştirilir (`"gh" + "p_" + …`).

## Ekran bağlamı (POST gövdesindeki `baglam`)

```json
{
  "rota_kalibi": "/gereksinimler/:id/caseler",
  "ekran": "Case inceleme",
  "varlik": {"tur": "requirement", "id": "<uuid>", "anahtar": "TPD-3"},
  "son_hata": {"uc": "POST /cases/:id/review", "status": 409, "kod": "onay_hash_uyusmuyor",
               "detail": "…", "gorunen_metin": "…", "yas_s": 42},
  "secili_eleman": {"ad": "…", "rol": "button", "devre_disi": true, "ipucu": "…",
                    "kart_basligi": "…", "test_id": null}
}
```

Sunucuda şemayla doğrulanır (≤ 2 KB; bilinmeyen alan reddedilir, `rol` alanı varsa yok sayılır);
rota `rotalar.json` kalıbına indirgenir; `soru` ve `baglam` `scrub_secret_patterns` ile taranır →
422 `sir_icerik`. Modele ilk kullanıcı mesajında `<untrusted kind=ekran>` olarak gider. Öneriden
açılan sohbette sunucu `oneri {kural_id, baslik, neden}`'i `kural_id`'den yeniden üretip ekler.

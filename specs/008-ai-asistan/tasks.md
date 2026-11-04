# Tasks: Portal Asistanı ve Öneri Düğmesi

**Input**: plan.md, research.md, data-model.md, contracts/, quickstart.md · plan v6 §14 (şeritler),
§13 (testler)

**Paralellik**: Faz 1 (Şerit S) bitince Faz 2 şeritleri bağımlılık sırasına göre **aynı anda**
geliştirilir. Her şerit yalnız kendi dosyalarına yazar; sözleşme dosyaları (Faz 1) şeritlerce
değiştirilmez — değişiklik ihtiyacı raporla bildirilir. `[P]` = paralel çalışabilir. `[USx]` = spec
hikâyesi. Her şerit kendi hedefli testleriyle yeşil; tam paket yalnız Faz 3'te.

**İşaret durumu (2026-11-03, inceleme turu 1):** `[x]` = kodu ve hedefli testi `feat/ai-asistan`
dalında. Açık kalanlar bilinçlidir: T007 (teknik lider onayı — PR açıklamasında istenir), T062 (p95
ölçümü), T131 (canlı değerlendirme + K2 kararı; `assistant` paketi `pending`), T132–T135 (E2E,
gerçek Jira, son inceleme, tam paket). `main`'e birleştirme ve sunucuda `TP_ASISTAN_MODEL_MODE=live`
T131 `evaluated` olmadan yapılmaz (İlke X).

## Faz 1: Süreç ve sözleşme (Şerit S, seri)

- [x] T001 `specs/008-ai-asistan/` spec, plan, research, data-model, contracts, quickstart, tasks
- [x] T002 Constitution v1.3.0 (İlke II'ye K7; Sync Impact Report)
- [x] T003 TEKNIK-TASARIM v1.6: §8.13 Portal asistanı ve Öneri + §4, §7, §8.8, §9 güncellemeleri
- [x] T004 MIMARI-SOZLESME §5 hata `kod` enum'u + asistan uçları + SSE; §6 yeni ortam değişkenleri
- [x] T005 ONBOARDING kısa asistan/öneri bölümü
- [x] T006 Olgu kaynakları, uç yolları ve rol hizalaması koda karşı doğrulandı (research R2–R4)
- [ ] T007 Teknik lider onayı (constitution değişikliği aynı PR'da)

## Faz 2: Paralel şeritler

### Şerit A — `rules/` (US1, US2, US5)
- [x] T010 [P] [US1] `rules/prompts/assistant.md` (öneri modu dahil, `_guardrails.md`)
- [x] T011 [P] [US1] `rules/schemas/assistant.schema.json` = `assistant_deep.schema.json` (`oneriler` dahil; `anyOf` null; tip dizisi yok)
- [x] T012 [P] `rules/models.yaml` `assistant`, `assistant_deep` (+ `max_retries`, `max_timeout_retries`, `fallbacks`)
- [x] T013 [P] `evaluations.yaml` `pending` + `rules/README.md` satırı; `rules/evaluation/assistant.json` iskeleti
- [x] T014 [P] [US1] `rules/assistant/hata-sozlugu.yaml` (MIMARI-SOZLESME §5 `kod`'ları), `urun-terimleri.yaml`, `rotalar.json`
- [x] T015 [P] [US2] `rules/assistant/oneriler.yaml` (26 kural, contracts/oneri-kurallari.md) + `jira-taslaklari.yaml` + şema testi
- [x] T016 [P] İki golden (`ornek.json`, `oneriler: []`) + `ALLOWED_AGENT_TOOLS` (13 araç); `test_rules`, `test_schema_compat`, `test_goldens` yeşil

### Şerit B — veri (US1, US2)
- [x] T020 [P] Migrasyon `0017_asistan` (data-model.md) + SQLAlchemy modelleri + `TOOL_KANAL`
- [x] T021 [P] Migrasyon testleri: kanal kabul/ret, kısmi tekil indeksler, `check`, GRANT, `audit?verify=true`

### Şerit C1 — sır ve ürün bilgisi (US1)
- [x] T030 [P] `gateway/masking.scrub_secret_patterns` + çalışma anı sır değerleri (her desen için test)
- [x] T031 [P] Bilgi paketi: `scripts/asistan-bilgi-paketi.sh`, `features/assistant/paket.py`, mount, `.gitignore`, `make asistan-paket`
- [x] T032 [P] `product_search`, `product_read` (`..`, symlink, NUL, büyük/küçük harf, manifest dışı)

### Şerit C2 — Probe araçları (US1) — C1'den sonra
- [x] T040 Ortak sarmalayıcı, tek maskeleme oturumu, kanıt havuzu (`tools/base.py`)
- [x] T041 `probe_get`, `probe_list`, `probe_jobs`, `probe_audit`, `probe_my_queue` (uç-düzeyi rol kısıtı)

### Şerit J — Jira ve CI araçları (US3) — C1 + C2'den sonra
- [x] T050 `JiraOkuyucu` + `get_jira_okuma` (yalnız-GET transport, `son_yorumlar`, yazar etiketleme, kısıtlı yorum filtresi), `jira_issue`, `jira_global` kovası
- [x] T051 `log_yolu`, forge akışlı okuma, `GitHubCiOkuyucu`, `ci_log` (güvenli açma)
- [x] T052 jira-sim istek sayacı + `/sim/istekler`; eval tohumu (injection'lı yorumlar, sentetik kişiler), örnek koşu logu
- [x] T053 `security-check`: Jira okuma hesabı yazma izni taşımıyor (`mypermissions`)

### Şerit R — öneri motoru (US2) — C2 + A'dan sonra; uç E'den sonra
- [x] T060 `features/assistant/oneri.py`: `olgular()`, `oneriler()` (contracts/oneri-kurallari.md), güvenli yer tutucu
- [x] T061 `GET /assistant/suggestions`, `POST /assistant/suggestions/{kural_id}/feedback`, bağlantı kurgusu (`JIRA_CREATE_URL` doğrulaması)
- [x] T062 Kural testleri: her kural olumlu/olumsuz, 5 rol, rol hizalama, kapsam matrisi, sistem hattı yasağı, p95 < 300 ms
  (`test_oneri_motoru.py`, `test_rules_asistan.py`, `test_oneri_api.py::test_oneri_ucu_tohumlu_veride_p95_300ms_alti`)

### Şerit E — API (US1, US4) — B + C1 + R(motor)'dan sonra
- [x] T070 Mesaj uçları (atomik bekleme, `ust_mesaj_id`, `kip`/`oneri_kural_id`, sayaçlar, advisory lock)
- [x] T071 `budget.py` (kök soru + çocuklar, kullanıcı/asistan günlük)
- [x] T072 SSE filtresi (`KIMLIK_ALANLARI`, `_akis` fail-closed)
- [x] T073 Hata `kod`: `api/errors.py` genel eşleme + `KodluHata` (`asistan_kapali` 5xx istisnası), `WorkflowError.kod`, CSRF `kaynak_reddi`, `test_api.py`/`test_guvenlik.py` güncellemeleri
- [x] T074 Compose ortam değişkenleri (contracts/env.md), `.env.example` değersiz satırlar

### Şerit D1 — worker (US1, US2) — A + B + C2 + E + R(motor)'dan sonra
- [x] T080 Asistan şeridi (3 iş parçacığı), `ASISTAN_SERIT`, zaman aşımı süreci kapatmaz
- [x] T081 Kalp atışı zamanlayıcısı (`asistan_durum`), uzlaştırma, yarış korumaları
- [x] T082 İşleyici: sözlük / şablon / kapalı / öneri-kapalı dalları; geçit enjeksiyon noktası

### Şerit D2 — canlı ajan (US1, US3, US4, US5) — D1 + C1 + J'den sonra
- [x] T090 §10.3 geçit değişiklikleri (varsayılanla eski davranış; mevcut geçit testleri değişmeden yeşil)
- [x] T091 Canlı dal; süre (`bitis`), `should_stop`, toparlama
- [x] T092 Son işlem (contracts/assistant-schema.md; `jira`/`ci_log`, `oneriler`)
- [x] T093 "Daha ayrıntılı incele" + otomatik yükseltme (transaction sırası, ön koşullar, kilit/yarış testleri)

### Şerit F — portal paneli (US1, US3, US4)
- [x] T100 [P] `ApiError` (`kod`, `method`, `yol`, `kayitId`), `sonHata` deposu, `HataKutusu kaynak` + "Asistana sor"
- [x] T101 [P] Panel, mock (11 uç + `assistant.*` olayları), yetenek kapısı, bağlam çipleri, "? Bu ne?"
- [x] T102 [P] Cevap kartı (güven, kaynaklar, Jira/CI), otomatik yükseltme kartı + "Durdur", `rotalar.json` ↔ `rotalar.ts` eşitliği

### Şerit G — portal Öneri (US2, US5) — F + R'den sonra
- [x] T110 Öneri düğmesi (üst çubuk, rozet, debounce), panel sekmesi, kartlar, taslak kopyalama, "Neden? Sor", "Başka ne yapabilirim?", Gizle/Yaptım

### Şerit K — Kabuk (en son portal işi)
- [x] T120 `KabukDurumu`, "Asistanı aç" atlama düğmesi, bildirim konumu, `Olculmedi` taşıma

## Faz 3: Değerlendirme ve kapanış (Şerit H, seri)

**Birleştirme kapısı:** dal `dev`'e yalnız bayrak arkasında (`TP_ASISTAN_MODEL_MODE=off`) girer. `main`'e
birleştirme ve sunucuda `live` için T007 (teknik lider onayı, anayasa v1.3.0), T131 (`assistant` paketi
`evaluated` + içerik hash'i + K2 kararı; medyan maliyet, yükseltme oranı ≤ %35, p90 süre raporu), T132,
T133 ve T136 kapanmış olmalı (plan §16 madde 2, 5, 9, 14). `evaluation --check` CI'da koşmadığından kapı
prosedüreldir: `main` PR'ı plan §14'teki birleştirme kontrol listesiyle açılır.

- [x] T130 Eval düzeneği (`check_output` `assistant` dalı, `--via-flow`, `ENVS["assistant:<rol>"]`, içerik hash'i)
- [ ] T131 Canlı set ≥ 30 soru + matris (Haiku low/medium, Sonnet low/medium) → K2 kararı → `evaluated`
- [ ] T132 E2E: mock duman + `canli.spec.ts` (`TP_ASISTAN_MODEL_MODE=off`); prova dürüstlük kilidi yeşil
- [ ] T133 Gerçek Jira Cloud'da "Jira'yı aç" yeni kayıt yolu kontrolü (research R7)
- [ ] T134 Çok rollü inceleme döngüsü; KRİTİK/ÖNEMLİ bulgu yok
- [ ] T136 K10 yeniden onayı: kural 1, 8, 11 daraltmaları ve kural 15 (defect adayı hariç, eylem `/kod`); onayla plan K10 satırı tarihlenir (contracts/oneri-kurallari.md fark listesi)
- [ ] T135 Tam paket yeşil → `main` → sunucu `.env`'de `TP_ASISTAN_MODEL_MODE=live`

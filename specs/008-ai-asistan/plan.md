# Implementation Plan: Portal Asistanı ve Öneri Düğmesi

**Branch**: `feat/ai-asistan` (hedef `dev`) | **Date**: 2026-11-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-ai-asistan/spec.md`

**Kaynak plan**: [docs/AI-ASISTAN-PLANI.md](../../docs/AI-ASISTAN-PLANI.md) v6 (K1–K10 onaylı) ·
**Kaynak tasarım**: [docs/TEKNIK-TASARIM.md](../../docs/TEKNIK-TASARIM.md) v1.6 §8.13 · **Sözleşme**:
[docs/MIMARI-SOZLESME.md](../../docs/MIMARI-SOZLESME.md) §5–§6.

## Summary

Portalın her ekranında Türkçe soru-cevap yapan, **salt okuma** araçlarla (ürün kodu/dokümanı bilgi
paketi, Testing Probe verisi, test edilen uygulamanın kodu/verisi, canlı Jira kaydı + yorumları, CI
logu) kanıt toplayıp **deterministik doğrulanmış kaynak** gösteren bir asistan ve her ana ekranda
o rolün bekleyen işlerini kural tabanlı (modelsiz) listeleyen bir **Öneri** düğmesi. Teknik
yaklaşım: core-worker'da ayrı `asistan` şeridi (3 iş parçacığı), mevcut model geçidinin
`run_agent` döngüsü (yeni parametreler varsayılanla eski davranışı korur), Haiku sınıfı varsayılan +
"Emin değil" durumunda ayrı çocuk mesajla Sonnet sınıfı otomatik yükseltme, core-api'de modelsiz
mesaj/öneri uçları, Postgres'te 5 yeni tablo (0017), portalda bindirme paneli + üst çubukta Öneri
düğmesi. Teslim tek seferdir (K9); şeritler bayrak arkasında `dev`'e girer, canlı değerlendirme
`main`'den önce.

## Technical Context

**Language/Version**: Python 3.12 (core), TypeScript 5.x / React (review-portal)

**Primary Dependencies**: mevcut — FastAPI, SQLAlchemy 2, Alembic, psycopg 3, Pydantic v2, httpx,
anthropic, sqlglot, pyyaml; portal React + Vite. **Yeni bağımlılık yok.**

**Storage**: PostgreSQL 16 `tp` veritabanı; migrasyon `0017_asistan` (5 tablo + `tool_call` kanal
kısıtı). Bilgi paketi `var/tp-bilgi/` (git dışı, yalnız core-worker'a `:ro`).

**Testing**: pytest (`TP_TEST_REQUIRE_DB=1`, geçici postgres), vitest, Playwright e2e (mock + canlı
`TP_ASISTAN_MODEL_MODE=off`), `make eval-live` (asistan canlı seti, elle).

**Target Platform**: mevcut docker compose (Apple Silicon + Linux GCP sunucusu)

**Project Type**: mevcut monorepo (core + review-portal + rules)

**Performance Goals**: öneri ucu p95 < 300 ms; asistan p90 uçtan uca ≤ 30 sn (`assistant`), ≤ 60 sn
(`assistant_deep`); iş süresi bütçesi 75 sn (emniyet 120 sn).

**Constraints**: model anahtarı yalnız core-worker'da; core-api kipi bilmez; asistan çıktısı hiçbir
karar alanına girmez; maliyet tavanları K3; tüm araç çıktıları sır temizlenmiş + maskeli + `<untrusted>`.

**Scale/Scope**: 5 rol, günde ≈ 150 soru (≈ $4.7), global 6 eşzamanlı iş; 11 HTTP ucu, 13 araç,
26 öneri kuralı.

## Constitution Check (v1.3.0)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| İlke | Bu özellikteki karşılığı | Durum |
|---|---|---|
| I. AI üretir, insan onaylar | Asistanın yazma/eylem aracı yok; eylem isteğinde `eylem_reddi` + ekran linki; Jira taslağını kullanıcı kendisi açar; yan etkisizlik testi | ✅ |
| II. CI'da AI yok (+K7) | Model yalnız core-worker'da; core-api anahtar/kip bilmez (`asistan_durum`); "salt okuma bilgi ve yönlendirme asistanı; eylem yok; çıktısı karar dayanağı değildir" — v1.3.0 ile ilke metnine girdi | ✅ (v1.3.0) |
| III. Yapılandırılmış çıktı | `submit_result` + iki eşit şema; son işlem deterministik; kartta "Bilgi amaçlıdır" | ✅ |
| IV. Kütüphaneye bağlı kod | Kod üretimi yok | — |
| V. Uygulamayı gerçekten gör | Görsel girdi yok; bağlam yalnız metin | ✅ |
| VI. Onarım yalnız locator | Onarım yok | — |
| VII. Veri müşteride kalır | Mesaj başına tek maskeleme oturumu; müşteri verisi kurulumunda maskeleme kapalıysa asistan kapalı; saklamadan önce yeniden maskeleme | ✅ |
| VIII. Her şey kayıt altında | `ai_call.ek` kişi + mesaj; `tool_call` `kanal='asistan'` + `cagiran_user_id`; sohbet silinse de iz kalır | ✅ |
| IX. Ürün opsiyonel | Prompt, iki şema, `models.yaml`, `rules/assistant/*` düz dosya | ✅ |
| X. Her çıktı ölçülür | Paket `pending` girer; `main` öncesi canlı set (≥ 30 soru, eşikler §13) → `evaluated` + içerik hash'i | ✅ (Şerit H kapısı) |
| XI. Deterministik önce | Sözlük, şablon, öneri kuralları modelsiz; link/kaynak doğrulama ve yükseltme kararı deterministik | ✅ |
| XII. Bağımsız ürün | Agent Probe bağımlılığı yok; sağlayıcıya özgü `fallbacks` yalnız adaptörde | ✅ |
| Güvenlik/Mimari | Güvenilmeyen girdi `<untrusted>`; en az yetki (`ALLOWED_AGENT_TOOLS`, dar `JiraOkuyucu`, yalnız-GET transport); anahtar yalnız worker | ✅ |

**Sonuç:** İhlal yok; v1.3.0 değişikliği (K7) aynı PR'da, teknik lider onayına bağlı.

## Project Structure

### Documentation (this feature)

```text
specs/008-ai-asistan/
├── spec.md
├── plan.md                 # bu dosya
├── research.md             # koda karşı doğrulama (olgu kaynakları, rol hizalama, kod enum'u)
├── data-model.md           # 0017_asistan
├── quickstart.md
├── contracts/
│   ├── api.md              # 11 uç, hata kod enum'u, SSE, hız sınırı
│   ├── assistant-schema.md # §7.2 şema + §7.3 son işlem
│   ├── tools.md            # 13 araç, sarmalayıcı, ekran bağlamı
│   ├── oneri-kurallari.md  # kural şeması, olgular(), 26 kural
│   └── env.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code

```text
core/
├── alembic/versions/0017_asistan.py
├── src/tp_core/
│   ├── models/asistan.py, models/enums.py (TOOL_KANAL, ASISTAN_*)
│   ├── api/errors.py (KodluHata, genel kod), api/csrf.py (kaynak_reddi)
│   ├── workflow/service.py (WorkflowError.kod), workflow/jobs.py (ASISTAN_SERIT)
│   ├── worker/ (asistan şeridi, kalp atışı zamanlayıcısı, uzlaştırma)
│   ├── gateway/ (factory, core, config, masking.scrub_secret_patterns, providers)
│   ├── integrations/jira.py (JiraOkuyucu), integrations/forge_github.py (akışlı okuma)
│   ├── features/ci/ (service.log_yolu, clients.GitHubCiOkuyucu)
│   ├── features/requirements/datatools.py (session=)
│   └── features/assistant/
│       ├── api.py, flow.py, jobs.py, budget.py, oneri.py, paket.py, sonislem.py
│       └── tools/ (base.py, product.py, probe.py, jira.py, ci.py)
└── tests/unit/features/assistant/, tests/unit/platform/test_hata_kodlari.py
rules/
├── prompts/assistant.md, schemas/assistant{,_deep}.schema.json, models.yaml, evaluations.yaml
├── assistant/ (rotalar.json, hata-sozlugu.yaml, urun-terimleri.yaml, oneriler.yaml, jira-taslaklari.yaml)
├── replay/assistant{,_deep}/golden/ornek.json
└── evaluation/assistant.json
review-portal/src/
├── api/http.ts (ApiError.kod/method/yol/kayitId), api/client.ts, api/events.tsx, api/mock/
├── lib/rotalar.ts (ROTA_DESENLERI), lib/sonHata.ts, lib/ekranBaglami.ts, lib/etiketler.ts
└── components/asistan/ (Panel, Oneri, BuNe, kartlar)
scripts/asistan-bilgi-paketi.sh · Makefile (asistan-paket) · docker-compose.yml · .env.example
```

**Structure Decision**: Özellik tek `features/assistant/` paketi altında; geçit, worker ve hata
biçimi değişiklikleri mevcut modüllerde varsayılanı koruyan parametrelerle. Portal paneli kabuktan
bağımsız bileşen; Kabuk dokunuşu en son (Şerit K).

## Şeritler ve bağımlılıklar

Plan §14 aynen geçerlidir. S → hepsi; A, B, C1, F, K paralel; C2 → C1; R(motor) → C2 + A; J → C1 +
C2; E → B + C1 + R(motor); R(uç) → B + E; D1 → A + B + C2 + E + R(motor); D2 → D1 + C1 + J; G → F + R;
H → hepsi. En uzun yol C1 → C2 → R → E → D1 → D2.

## Şerit S kararları (bu PR)

1. Spec klasörü `008-ai-asistan` (research R1).
2. `po_bekleme_saat` kaynağı `audit_event` geçişi (R2); `bulgu_kaynakli` olgusu eklendi; `<olgu>_in`
   operatörü genelleştirildi (kural 13).
3. Kural 15 `yetki` ucu `POST /code/generate` (R3).
4. Hata `kod` enum'u koda hizalandı (`GateClosed`=`kapi_kapali`, `OnayHashUyusmuyor`=
   `onay_hash_uyusmuyor`); `asistan_kapali` 5xx'te korunan tek özel kod (contracts/api.md).
5. `asistan_durum` tekil satırı `id = 1` CHECK'iyle (Şerit B ile hizalı).
6. Öneri yanıtına `diger_ekranlar {sayi, rota}` alanı (plan §17.3 `*` özetinin taşıyıcısı).
7. Ortam değişkenlerinin dağıtımı (`x-core-env` / yalnız core-worker) contracts/env.md'de sabitlendi.

## Constitution Check — tasarım sonrası

Phase 1 sözleşmeleri tabloyu değiştirmiyor. Not: `jira_issue` canlı Jira okur — İlke I'in "etkili
eylem" sınırı korunur (yalnız GET, dar okuyucu, `security-check` izin kontrolü). **Sonuç: geçti.**

## Complexity Tracking

| Sapma | Neden | Daha basit alternatif neden reddedildi |
|---|---|---|
| Asistan şeridinde 3 iş parçacığı | Bir asistan işi 120 sn'ye kadar sürebilir; tek iş parçacığı sırayı kilitler | Ayrı worker servisi: compose ve sır dağıtımını çoğaltır |
| Otomatik yükseltme ayrı çocuk mesaj | Tek işte iki kademe 75 sn bütçesini aşar | Aynı işte zincir: süre ve iptal yarışları |
| `asistan_hiz` tablosu | core-api çok süreçli; bellekte sayaç atomik değil | Redis: yeni bileşen |

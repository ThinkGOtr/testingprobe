---

description: "AI Probe ortak girişi (SSO) görev listesi"
---

# Tasks: AI Probe Ortak Girişi (SSO)

**Input**: spec.md, plan.md · ADR-0001 · TEKNIK-TASARIM §8.14 · CONTRACT v1

**Tests**: İstendi (spec SC-001…SC-004). Yeni testler sahte `aiprobe-home` ile.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Yönetişim (F4a — kod öncesi, zorunlu)

- [x] T001 ADR-0001 `docs/adr/0001-aiprobe-ortak-kimligi.md` — onaylandı (2026-11-10)
- [x] T002 Constitution v2.0.0 (İlke XII yeniden tanım, VII on-prem kimlik; Sync Impact Report)
- [x] T003 TEKNIK-TASARIM v1.7 §8.14 (+ §3, §8.10, §9, §14); MIMARI-SOZLESME §5–§6
- [ ] T004 Onaycı isimlerinin F0 notuna işlenmesi

## Phase 2: Foundational

- [x] T010 `core/src/tp_core/config.py` `TP_AUTH_MODE` + `AIPROBE_*`
- [x] T011 Göç `core/alembic/versions/0019_aiprobe_kimlik.py` + `models/identity.py` (`KimlikBagi`, yeni kolonlar)
- [x] T012 `auth/sessions.py` kip yardımcıları, çerez adı/Secure, `ae` alanı
- [x] T013 `auth/aiprobe.py` home istemcisi, ID token sağlayıcı/doğrulayıcı, önbellek, iptal

## Phase 3: US1 — AI Probe ile giriş (P1) 🎯 MVP

- [x] T020 [US1] `api/routers/aiprobe.py` `/auth/aiprobe/login`, `/auth/aiprobe/callback`
- [x] T021 [US1] JIT `app_user` + bağ, denetim `auth.jit_user`
- [x] T022 [US1] `/auth/logout` AI Probe oturumunda `redirect`; `/auth/login` `aiprobe` kipinde 404
- [x] T023 [P] [US1] Testler: giriş turu, state uyuşmazlığı, JIT, `local` kipte uçlar yok

## Phase 4: US2 — Rol seçici ve Rol değiştir (P1)

- [x] T030 [US2] `GET /auth/aiprobe/hesaplar`, `POST /auth/aiprobe/rol-sec`, `POST /auth/aiprobe/rol-degistir`
- [x] T031 [P] [US2] Testler: rol seçici, rol değiştir (yeni sid, bağsız hesap 403)

## Phase 5: US3/US4 — İptal ve süreler (P1/P2)

- [x] T035 [US3] `session_valid` / `verify_bearer` içinde 60 sn kontrol; epoch artışı; degraded başlığı
- [x] T036 [US4] Boşta 30 dk kayan / mutlak 8 sa (yalnız kullanıcı istekleri uzatır)
- [x] T037 [P] [US3] Testler: iptal → 401 + `tpt_` red; home erişilemez → oturum korunur

## Phase 6: US6 — Yönetim ucu (P2)

- [x] T038 [US6] `api/routers/admin_kimlik.py` `/admin/kimlik-bagi` (yalnız `AIPROBE_HOME_SA`)
- [x] T039 [P] [US6] Testler: home olmayan çağıran reddedilir; bağ/kaldırma

## Phase 7: Portal (ayrı şerit, açık)

- [x] T040 Portal 401'de kip `aiprobe` ise `/api/auth/aiprobe/login?continue=` (form verisi
  `sessionStorage` yedeğiyle korunur; yönlendirme döngüsü koruması). Kip core'un `X-TP-Kimlik`
  yanıt başlığından (`local`'de başlık yok → arayüz değişmez). `both`: `/giris` yerel form + AI Probe
- [x] T041 Portal `/rol-sec` sayfası (`GET /api/auth/aiprobe/hesaplar` + `rol-sec`; açık oturumda
  `rol-degistir`). Asistan bağlamı dışında (`rotalar.json`'a girmez; core `ASISTAN_DISI`)
- [x] T042 `<aiprobe-switcher>` 1.0.1 vendor (`review-portal/src/vendor/aiprobe-switcher/`, platform
  `dist/switcher-1.0.1.js` = `web/home/sdk/switcher-1.0.1.js` ile bayt bayt aynı, sha384 testte), yalnız aiprobe/both'ta dinamik
  yüklenir; `product-menu` yuvasında "Rol değiştir"; `X-Aiprobe-Degraded` bandı. CSP kipe göre
  (`docker/40-tp-kimlik-csp.sh`: aiprobe/both → `connect-src`/`img-src` + home kökeni; local aynen)
- [x] T043 Çıkışta `redirect`'e gitme (yalnız home/aynı köken); `GET /auth/me` → `product`, `roles`,
  `products` (oturumda saklanan ürün→rol haritası). Callback/login hataları tarayıcıda Türkçe sayfa
  ("Tekrar dene"), API istemcisine JSON
- [x] T044 CONTRACT v1.2: oturum ve `tpt_` token `auth_time`, `acr`, `session_epoch_ms` saklar ve
  `/v1/session/check`'e gönderir (MFA'lı `po` oturumu `admin_roles` süzgecine takılmaz; token
  üreten oturumun alanlarını taşır → üretimden önceki iptal de token'ı düşürür)
- [x] T045 `/api/health` → core `/health` (on-demand hazırlık yoklaması); compose `x-core-env`
  `TP_AUTH_MODE` + `AIPROBE_*`, portal `TP_AUTH_MODE` + `AIPROBE_HOME_ORIGIN`

## Phase 8: Taşıma ve e2e (F4b, PLAN §6)

- [ ] T050 `products/testing-probe.yaml` `callback_url` = `{app_url}/api/auth/aiprobe/callback` (platform şeridi)
- [ ] T051 `feat/mobil-masaustu` göçü birleşince `0019.down_revision = "0018"` — o dalda
  `0018_script_platform` (down_revision `0017`) var. Birleştirmede: `0019_aiprobe_kimlik.py`'de
  `down_revision = "0018"` + başlıktaki `Revises:` satırı; `test_aiprobe_sso.py::test_alembic_tek_bas`
  iki baş kalırsa başarısız olur
- [ ] T052 CI'da emülatörlü `aiprobe-home` ile `both` e2e (yolculuk 6, 11, 13, 14)
- [ ] T053 Taşımada `home` taslak bağ listesi → `PUT /admin/kimlik-bagi` (bulunamayan ad = no-go)

## Dependencies & Execution Order

Phase 1 → Phase 2 → (Phase 3 → Phase 4) ∥ Phase 5 ∥ Phase 6 → Phase 7 → Phase 8.

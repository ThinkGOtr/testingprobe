# Implementation Plan: AI Probe Ortak Girişi (SSO)

**Branch**: `feat/010-aiprobe-sso` | **Date**: 2026-11-10 | **Spec**: [spec.md](./spec.md)

**Input**: `specs/010-aiprobe-sso/spec.md`; ADR-0001; TEKNIK-TASARIM §8.14; CONTRACT v1.

## Summary

core-api'ye kip anahtarı (`TP_AUTH_MODE`) ve AI Probe giriş devri eklenir. Dış kimlik yalnızca iki
sunucu çağrısıyla gelir (`/v1/handoff/redeem`, `/v1/session/check`); TP'nin yetki modeli değişmez,
kişi `kimlik_bagi` ile tek-rollü `app_user` hesaplarına bağlanır. Oturum kontrolü mevcut
`session_valid` / `verify_bearer` içine 60 sn önbellekli olarak girer; iptal `auth_epoch` ile
çerezleri ve `tpt_` token'larını düşürür. Platform istemcisi vendor edilmez (ADR-0001): HTTP
çağrıları TP kodunda (`tp_core/auth/aiprobe.py`).

## Technical Context

**Language/Version**: Python 3.12 (core)

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, httpx (mevcut), itsdangerous (mevcut),
PyJWT[crypto] (mevcut; Google ID token doğrulama) — yeni bağımlılık yok, Firebase/google-auth yok.

**Storage**: PostgreSQL; göç `0019_aiprobe_kimlik` (down_revision `0017`; `feat/mobil-masaustu`'nun
`0018`'i birleşince `0018`'e yeniden ebeveynlenir).

**Testing**: `cd core && uv run pytest` (docker'lı geçici Postgres; `tests/unit/conftest.py`);
yeni testler `tests/unit/platform/test_aiprobe_sso.py` — sahte `aiprobe-home` `httpx.MockTransport`,
sahte ID token sağlayıcı/doğrulayıcı, sahte saat.

**Target Platform**: Linux container (core-api), tek süreç uvicorn.

**Project Type**: web-service (core-api) + portal (ayrı görev).

**Performance Goals**: Home çağrısı oturum başına ≤ 1/60 sn; zaman aşımı 5 sn.

**Constraints**: `local` kipte sıfır dış çağrı ve davranış farkı; Firebase SDK yok; `__Host-`
çerezleri Secure.

**Scale/Scope**: Onlarca kullanıcı (demo/pilot).

## Constitution Check

| İlke | Durum |
|---|---|
| I (insan onayı) | Değişmez: onay kaydı oturumdaki `app_user` ile; JIT hesabı da gerçek kişiye bağlı. ✅ |
| VII (veri müşteride) | `local` varsayılan, on-prem dış çağrı yok; home'a yalnız `uid`, `auth_time`. ✅ |
| VIII (kayıt) | `auth.login` (kanal aiprobe), `auth.jit_user`, `auth.role_switch`, `auth.aiprobe_revoked`, `admin.kimlik_bagi.*` denetimde. ✅ |
| XI (deterministik) | Rol eşlemesi küme kesişimi; LLM yok. ✅ |
| XII (sözleşmeli kimlik, v2.0.0) | Yalnız CONTRACT v1 HTTP uçları; Firebase/AP kodu yok; vendor yok. ✅ |
| Güvenlik — CSRF | Yeni POST uçları `OriginGuard` arkasında; callback GET ama `state` ile korunur. ✅ |

## Project Structure

### Documentation (this feature)

```text
specs/010-aiprobe-sso/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
core/src/tp_core/
├── config.py                      # TP_AUTH_MODE + AIPROBE_* ayarları
├── models/identity.py             # KimlikBagi; AppUser.auth_epoch/ad_soyad; Oturum.*; ApiToken.auth_epoch
├── auth/
│   ├── aiprobe.py                 # YENİ: home istemcisi (redeem/check), ID token sağlayıcı/doğrulayıcı,
│   │                              #        60 sn önbellek, iptal (epoch), bağ/JIT yardımcıları
│   ├── sessions.py                # çerez adı/Secure kipe göre; `ae` alanı; session_valid kontrolü
│   ├── tokens.py                  # api_token.auth_epoch; verify_bearer kontrolü
│   └── deps.py                    # current_user: degraded başlığı, uzatma
├── api/routers/
│   ├── auth.py                    # /auth/login kip kapısı; /auth/logout redirect
│   ├── aiprobe.py                 # YENİ: /auth/aiprobe/* (login, callback, hesaplar, rol-sec, rol-degistir)
│   ├── admin_kimlik.py            # YENİ: /admin/kimlik-bagi
│   └── events.py                  # çerez adı
├── api/main.py                    # router kaydı + degraded başlığı ara katmanı
core/alembic/versions/0019_aiprobe_kimlik.py
core/tests/unit/platform/test_aiprobe_sso.py
```

**Structure Decision**: Kimlik kodu mevcut `tp_core/auth` paketinde kalır (sahiplik: platform
şeridi, MIMARI-SOZLESME §3). Yeni router'lar `PLATFORM_ROUTERS`'a eklenir.

## Tasarım ayrıntıları

- **Kip yardımcıları** (`sessions.py`): `cookie_name()`, `cookie_secure()`, `aiprobe_acik()`.
- **Çerez yükü**: `{"uid","pv","sid","ae"}`; `ae` yoksa 0 (eski çerezler `local`'de geçerli kalır).
- **Oturum kontrolü** (`aiprobe.kontrol_et`): yalnız `oturum.external_uid` doluysa; kip `local` ise
  böyle oturum reddedilir. `son_kontrol` + 60 sn dolmadıysa çağrı yok. Süreç içi önbellek
  `(uid, auth_time) → sonuç` 60 sn. Geçersiz/rol düşmüş → ayrı işlemde (`session_scope`) epoch artışı
  + oturum iptali + denetim (istek 401 ile geri alınsa da kalıcı). Erişilemez → korunur, degraded.
- **Token kontrolü**: `api_token.auth_epoch == app_user.auth_epoch`; sahip bağlıysa aynı önbellekli
  kontrol, üreten AI Probe oturumunun `auth_time`/`acr`/`session_epoch_ms`'i ile (token üretiminde
  kopyalanır; üretimden önceki iptal de görülür). Yerel oturumdan üretilen token: üretim anı, acr 1.
- **CONTRACT v1.2**: `oturum.acr`, `oturum.session_epoch_ms` devirden saklanır, her
  `/v1/session/check` `{uid, auth_time, acr, session_epoch_ms}` gönderir (acr yoksa home `po`'yu
  süzer). `oturum.urunler` (ürün→rol) devir/kontrol yanıtından; `/auth/me` `products`.
- **Portal kipi**: core `aiprobe|both`'ta her yanıta `X-TP-Kimlik: kip=…; home=…; urun=…` ekler
  (saf ASGI ara katmanı); portal ek istek atmadan kipi öğrenir. `local`'de başlık yok.
- **Boşta/mutlak**: AI Probe oturumunda `son_kullanma = min(olusturma + mutlak, şimdi + boşta)`;
  yalnız `current_user` uzatır (≥ 60 sn fark varsa yazılır).
- **Seçim çerezi** (`tp_rol_secimi`, itsdangerous, 10 dk): `{x: uid, t: auth_time, r: roller,
  h: aday hesap id'leri, c: continue, n: ad}`.
- **JIT kullanıcı adı**: e-posta yerel kısmı + rol (`[a-z0-9._-]`, ≤ 48), çakışmada `-xxxx`;
  `parola_hash` = `!aiprobe` (argon2 değil → `verify_password` False).
- **ID token sağlayıcı** (TP → home): GCE metadata `identity?audience=AIPROBE_HOME_RUN_URL&format=full`,
  50 dk önbellek. **Doğrulayıcı** (home → TP): Google JWKS (`PyJWKClient`), `aud`, `iss`,
  `email_verified`, `email`. İkisi de `aiprobe.configure(...)` ile testte değiştirilir.

## Complexity Tracking

Yok.

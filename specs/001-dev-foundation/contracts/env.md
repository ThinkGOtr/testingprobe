# Contract: .env anahtarları

`.env` git dışıdır; `.env.example` tüm anahtarları açıklamalı listeler. `make env` eksik `.env`'i üretir ve F0 zorunlu parolalarını rastgele doldurur; `preflight.sh` F0 zorunlularını kontrol eder.

| Anahtar | F0'da zorunlu | Açıklama |
|---|---|---|
| `POSTGRES_PASSWORD` | ✅ | Postgres süper kullanıcı parolası (yalnızca yerel) |
| `TP_OWNER_PASSWORD` | ✅ | `tp_owner` rolü |
| `TP_APP_PASSWORD` | ✅ | `tp_app` rolü |
| `DEMOAPP_OWNER_PASSWORD` | ✅ | `demoapp_owner` rolü (demoapp şema sahibi) |
| `DEMOAPP_PASSWORD` | ✅ | `demoapp` rolü |
| `SEED_USER_PASSWORD` | ✅ | Seed kullanıcılarının ortak demo parolası |
| `PG_PORT`, `TP_API_PORT`, `TP_PORTAL_PORT`, `DEMO_WEB_PORT`, `MCP_PORT` | — (varsayılan 55432/8000/8080/8081/8931) | Host portları, yalnızca 127.0.0.1 |
| `ANTHROPIC_API_KEY` | — (F2a) | Model geçidi |
| `JIRA_SITE`, `JIRA_READ_EMAIL`, `JIRA_READ_TOKEN`, `JIRA_WRITE_EMAIL`, `JIRA_WRITE_TOKEN` | — (F3) | Rovo okuma ve Jira yazma |
| `JIRA_HESAP_ANALIST`, `JIRA_HESAP_PO`, `JIRA_HESAP_MUHENDIS`, `JIRA_HESAP_TESTCI` | — (boş = bahsetme yok) | Rol → Jira accountId; ürün yorumlarında @bahsetme (yalnızca bildirim, yalnızca core-worker) |
| `TP_GORUNEN_ADLAR` | — (boş = seed demo varsayılanları) | Portal kişi adları `kullanici_adi=Ad Soyad,…` (yalnızca gösterim; yalnızca core-api) |
| `XRAY_CLIENT_ID`, `XRAY_CLIENT_SECRET` | — (hafta 2) | Xray Cloud |
| `GITHUB_READ_TOKEN` | — (hafta 1, tutarlılık denetimi) | Test edilen uygulama reposu, `contents:read` |
| `GH_APP_ID`, `GH_APP_PRIVATE_KEY_PATH` | — (F1) | PR açan bot |
| `DEMOAPP_RO_PASSWORD` | — (F1) | `demoapp_ro` salt okuma rolü |

Sauce Labs kimliği (`SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`) yereldeki `.env`'de değil, GitHub Actions secret olarak tutulur.

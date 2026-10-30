# Data Model: Geliştirme ve Demo Ortamı Temeli

F0 yalnızca ortamın kendisi için gereken minimum şemayı kurar. Alan modelinin tamamı
(`requirement`, `test_case`, `review` …) F2a ve sonrasında eklenir (bkz. docs/TEKNIK-TASARIM.md §7).

## Veritabanları ve roller

| Veritabanı | Sahip rol | Uygulama rolü | Not |
|---|---|---|---|
| `tp` | `tp_owner` | `tp_app` | Çekirdek |
| `demoapp` | `demoapp_owner` | `demoapp` (F1), `demoapp_ro` (F1, salt okuma) | Örnek uygulama; F0'da boş |

## Tablolar (`tp`)

### `app_user`
| Alan | Tür | Kural |
|---|---|---|
| id | uuid PK | `uuid5(NAMESPACE_TP, "user:<kullanıcı_adı>")` |
| kullanici_adi | text unique not null | `analist`, `muhendis`, `sunucu`, `po`, `testci` |
| rol | text not null | `analyst` · `engineer` · `presenter` · `po` · `tester` |
| parola_hash | text not null | argon2; seed parolaları `.env`'den |
| olusturma | timestamptz default now() | |

### `audit_event` (append-only)
| Alan | Tür | Kural |
|---|---|---|
| id | bigserial PK | |
| zaman | timestamptz default now() | |
| aktor | text not null | kullanıcı adı veya `system` |
| eylem | text not null | ör. `seed.applied`, `reset.exported` |
| nesne | text | etkilenen nesne kimliği |
| ozet | jsonb | önce/sonra özeti |

**Yetki kuralı:** `tp_app` yalnızca `INSERT, SELECT`; `UPDATE, DELETE, TRUNCATE` geri alınmış.

### `job` (worker kuyruğu iskeleti)
| Alan | Tür | Kural |
|---|---|---|
| id | uuid PK | |
| tur | text not null | F0'da yalnızca `noop` (sağlık testi) |
| durum | text not null | `queued` → `running` → `done` \| `failed` |
| yuk | jsonb | |
| deneme | int default 0 | |
| olusturma / guncelleme | timestamptz | |

**Durum geçişleri:** `queued → running` (worker, `FOR UPDATE SKIP LOCKED`), `running → done|failed`; başka geçiş yok.

## Varlıklar (dosya/çalışma zamanı)

- **Bileşen** (docker-compose.yml): ad, imaj (digest), ağlar, yayınlanan port (127.0.0.1), sağlık kontrolü, bağımlılıklar, bellek sınırı.
- **Sırlar dosyası** (`.env`): anahtarlar ve zorunluluk durumu — bkz. [contracts/env.md](./contracts/env.md).
- **Denetim dışa aktarımı**: `exports/audit-<UTC zaman damgası>.jsonl` (her satır bir `audit_event`) + `.sha256`.
- **Başlangıç verisi**: yukarıdaki 5 kullanıcı + `audit_event` satırı `seed.applied`.

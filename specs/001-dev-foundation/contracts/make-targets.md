# Contract: make hedefleri

Tüm hedefler repo kökünden çalışır. Çıkış kodu `0` = başarı.

| Hedef | Ne yapar | Başarı çıktısı | Hata davranışı |
|---|---|---|---|
| `make env` | `.env` yoksa `.env.example`'dan üretir, boş F0 parolalarını `openssl rand -hex 24` ile doldurur; varsa dokunmaz | `.env hazır` | — |
| `make up` | `preflight.sh` → `docker compose up -d --build --wait --wait-timeout 300` (`scripts/up.sh`) → `make status` | Tüm servisler `healthy`, tablo | Önkoşul eksikse hangi önkoşul olduğunu yazar, hiçbir servisi başlatmaz (≠0). Sağlık süresi aşılırsa sağlıksız servis adı + son 20 log satırı (≠0). İdempotent: çalışan ortamda tekrar çalıştırılınca yalnızca eksikleri başlatır |
| `make status` | Servis adı, durum, sağlık, yerel adres tablosu | Tablo | Ortam kapalıysa "çalışmıyor" ve ≠0 |
| `make seed` | Deterministik başlangıç verisi | `seed: 5 kullanıcı (yeni: N)` | DB erişilemezse ≠0; tekrar çalıştırmak güvenli |
| `make reset` | `export-audit.sh` → çekirdek veriyi sil → `make up` | `exports/audit-*.jsonl` yolu + "ortam temiz" | Dışa aktarım başarısızsa hiçbir şey silinmez (≠0) |
| `make export-audit` | Denetim kaydını dışa aktarır | Dosya yolu + sha256 | ≠0 |
| `make security-check` | R10'daki 4 kontrol | Her kontrol `PASS`, özet `4/4` | Herhangi bir `FAIL` → ≠0 |
| `make prune` | Kullanılmayan imaj ve build önbelleğini temizler (volume'lere dokunmaz) | Kazanılan alan | — |
| `make logs [S=servis]` | Logları izler | — | — |
| `make down` | Servisleri durdurur (veri korunur) | — | — |

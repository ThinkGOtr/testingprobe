# Quickstart: Geliştirme ve Demo Ortamı Temeli — doğrulama rehberi

## Önkoşullar
- Apple Silicon Mac, Docker Desktop 29.x (veya Colima), ≥ 30 GB boş disk, Docker'a ≥ 8 GB bellek
- `git`, `make`

## 1. Kurulum
```bash
git clone git@github.com:ThinkGOtr/testingprobe.git && cd testingprobe
make env                  # .env üretir, F0 parolalarını rastgele doldurur (contracts/env.md)
make up
```
**Beklenen:** komut 0 ile biter; `make status` tüm servisleri `healthy` gösterir (US1-1, US1-2). İlk kurulum ≤ 20 dk (SC-002), ısınmış imajlarla ≤ 3 dk (SC-001).

## 2. Eksik sır senaryosu (US1-3)
```bash
mv .env .env.bak && cp .env.example .env && make up; echo $?   # ≠ 0 (parolalar boş)
mv .env.bak .env
```
**Beklenen:** hangi anahtarın eksik olduğunu yazar; hiçbir servis başlamaz.

## 3. İdempotent başlatma
```bash
make up && make up
```
**Beklenen:** ikinci çalıştırma çalışan servisleri bozmaz.

## 4. Başlangıç verisi ve sıfırlama (US2)
```bash
make seed && make seed          # ikinci çalıştırma "yeni: 0"
make reset && make seed
ls exports/                     # audit-*.jsonl ve .sha256
```
**Beklenen:** dışa aktarım dosyası oluşur; ortam sağlıklı ve aynı kimliklerle seed edilir; toplam ≤ 2 dk (SC-003). Üç kez tekrarla, sonuç aynı.

## 5. Güvenlik kontrolleri (US3)
```bash
make security-check
```
**Beklenen:** 4/4 PASS (SC-004): yalnızca 127.0.0.1 portları; test-runner'dan Postgres/core-api/internete erişim yok; `tp_app` denetim kaydını güncelleyemez/silemez; depoda sır yok.

## 6. Kaynak kullanımı (SC-006)
```bash
docker stats --no-stream
```
**Beklenen:** toplam bellek ≤ 10 GB.

## 7. Yeni ekip üyesi (US4, SC-005)
Ortamı kurmamış bir ekip üyesi yalnızca `README.md`'yi izleyerek 1–6. adımları ≤ 30 dk'da tamamlar.

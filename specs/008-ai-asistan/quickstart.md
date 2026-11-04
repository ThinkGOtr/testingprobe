# Quickstart: Portal Asistanı ve Öneri doğrulaması

Önkoşul: ortam çalışıyor (`make up`), `make seed` yapılmış. Bu adımlar özellik birleştikten sonra
geçerlidir.

## 1. Model kapalı (varsayılan, ücretsiz)

1. `make asistan-paket` (ya da `make up`'ın ön adımı) → `var/tp-bilgi/MANIFEST` oluşur.
2. Portala analist olarak girin → sağ altta "Asistan" görünür; başlıkta "HAZIR CEVAPLAR" rozeti.
3. Bir case kararında 409 alın → "Asistana sor" → sözlük cevabı (S2), `kaynak=sozluk`.
4. "TPD-3 neden bekliyor?" → şablon cevabı (S3); "Bugün ne yapmalıyım?" → kuyruk (S6).
5. Gereksinim detayında üst çubuktaki "Öneri" → kural önerileri (S12); "Açıklamayı göster".
6. Doğrulama: `GET /api/audit?verify=true` geçerli; `ai_call` satır sayısı değişmedi.

## 2. Model açık (sunucu)

1. `.env`'ye `TP_ASISTAN_MODEL_MODE=live` ekleyin (anahtar `.env`'de mevcut `ANTHROPIC_API_KEY`).
2. `make up` → `curl -s localhost:${TP_API_PORT}/assistant/status` (oturumla) → `mod: "live"`, `etkin: true`.
3. S1 ("? Bu ne?" + disabled düğme), S10 (Jira yorumu), S11 (CI logu), S13 (otomatik yükseltme).
4. Kontrol Kulesi maliyet raporunda `assistant*` amaçları ayrı grupta.

## 3. Hedefli testler

```bash
(cd core && TP_TEST_REQUIRE_DB=1 uv run pytest tests/unit/features/assistant -q)
(cd review-portal && npx vitest run src/components/asistan src/lib)
```

## 4. Geri alma

`.env`'de `TP_ASISTAN_MODEL_MODE=off` (model), `TP_ASISTAN_ONERI=0` (öneri),
`TP_ASISTAN_OTOMATIK_DERIN=0` (otomatik yükseltme); `make up`.

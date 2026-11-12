# Playwright yükseltme kontrol listesi

Tek sürüm kaynağı depo kökündeki `.playwright-version`'dır (npm `@playwright/test` /
`playwright-core` sürümü). TS hattı, Java web hattı (011), Playwright MCP ve toolchain imajı aynı
tarayıcı derlemelerini kullanır; sürümlerden biri kayarsa testler imajdaki `/ms-playwright`
tarayıcısını bulamaz ya da farklı Chromium'la koşar. Denetim (ağ yok):

```bash
make playwright-surum-denetle          # = scripts/playwright-surum.sh denetle; uyuşmazlıkta çıkış 1
scripts/playwright-surum.sh liste      # değişmesi gereken dosyalar
```

## Java sürümü npm sürümünden farklı olabilir

Playwright for Java'nın Maven sürümü (`<playwright.version>`, ör. **1.64.0**) npm sürümüyle (ör.
**1.64.1**) aynı olmak zorunda değildir; Java yamaları npm'in ardından ve farklı numarayla çıkar.
Belirleyici olan, Java sürücüsünün paketlediği çekirdektir: `com.microsoft.playwright:driver`
jar'ındaki `driver/package/package.json` dosyasının `"version"` alanı `.playwright-version`'a eşit
olmalıdır. Bunu e2e-java derlemesinde `SurumBirimTesti` denetler; `scripts/playwright-surum.sh` yerel
Maven deposunda (`~/.m2` ya da `TP_M2_REPO`) jar varsa aynı denetimi çevrimdışı yapar. Uygun Java
sürümünü seçmek için aday sürümün sürücü jar'ını indirip bu alanı okuyun:

```bash
unzip -p ~/.m2/repository/com/microsoft/playwright/driver/<jv>/driver-<jv>.jar \
  driver/package/package.json | grep '"version"'
```

## Adımlar

1. **`.playwright-version`** → yeni npm sürümü (ör. `1.65.0`).
2. **`toolchain/Dockerfile`** → `FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble@sha256:<digest>`
   satırındaki digest'i yeni etiketin digest'iyle değiştirin (`docker buildx imagetools inspect
   mcr.microsoft.com/playwright:v<sürüm>-noble`); üstteki "pins v…-noble" yorumunu güncelleyin.
3. **`toolchain/package.json`** → `@playwright/test` ve `overrides.playwright` /
   `overrides.playwright-core`; `npm install --package-lock-only` ile `package-lock.json`.
4. **`demo-app/e2e/package.json`** → `@playwright/test`; kilidi yenileyin. Ardından
   **`toolchain/e2e-deps/package.json` + `package-lock.json`** bu iki dosyanın birebir kopyası olur
   (`toolchain/tests/test_e2e_deps.py` denetler).
5. **`toolchain/mcp/package.json`** → `overrides.playwright` / `overrides.playwright-core`
   (`@playwright/mcp` sürümünün yeni çekirdekle uyumunu sürüm notlarından doğrulayın); kilidi yenileyin.
6. **Java hattı:** `demo-app/e2e-java/pom.xml` `<playwright.version>` → çekirdeği yeni npm sürümü olan
   Java sürümü (yukarıdaki bölüm). **`toolchain/e2e-java-deps/pom.xml` bayt eşit kopyadır** (pom kilidi;
   `cp demo-app/e2e-java/pom.xml toolchain/e2e-java-deps/pom.xml`). Uygulama hattı
   (`demo-app/e2e-app`, Appium) Playwright kullanmaz.
7. **`make playwright-surum-denetle`** yeşil olmalı.
8. **İmaj:** toolchain imajını yeniden derleyin (`make up` ya da `docker compose build toolchain-worker`).
   Derleme Node `playwright-core` sürümünü ve ağsız Java duman testini (ısıtılmış Maven deposu +
   `/ms-playwright` tarayıcısı) denetler; uyuşmazlıkta imaj derlenmez.
9. **Testler:** `cd demo-app/e2e && npx playwright test` (yerel), `demo-app/ci/run-java-checks.sh`
   (Java web; `SurumBirimTesti` dahil), toolchain ve core birim paketleri.
10. **Bilgi amaçlı:** `demo-app/.sauce/config.yml` Sauce'un desteklediği en yeni sürüme sabittir
    (`.github/CI.md` "Sauce"); Sauce yeni sürümü destekliyorsa güncelleyin. `review-portal` ve
    `rehearsal/ui` bağımsız UI test projeleridir; aynı sürüme çekilmeleri önerilir, zorunlu değildir.
11. **Kayıtlar:** Playwright MCP'nin araç şeması/çıktısı değişebilir. `core/tests/unit/gateway/fixtures/
    playwright_mcp_*.json` ve `rules/replay/verify_and_map/golden/*.json` notlarındaki sürüm,
    gerekirse canlı yığında yeniden kaydedilir (`core/tests/unit/gateway/record_verify_goldens.py`).
12. **GitHub:** `ci.yml` ve `web-java.yml` tarayıcıyı `npx playwright@<.playwright-version>` ile
    kurar ve önbellek anahtarı `.playwright-version`'a bağlıdır; ek değişiklik gerekmez. Demo
    deposunu güncelleyin (`scripts/github-demo-repo-init.sh --push --update`).

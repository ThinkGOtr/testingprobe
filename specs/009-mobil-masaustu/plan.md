# Uygulama Planı: Mobil (iOS, Android) ve Windows Masaüstü Test Yeteneği

**Dal**: `feat/mobil-masaustu` (hedef `dev`) · **Tarih**: 2026-11-08 · **Durum**: uygulamada

## 1. Amaç

Bugün hat yalnız web için çalışıyor: gereksinim → case → Playwright MCP ajanıyla doğrulama ve eşleme →
şablonla TypeScript test → PR → kırarak doğrula → CI → triage → onarım/bug. Bu özellik aynı hattı
**Android, iOS ve Windows masaüstü** uygulamalarına genişletir. Hat, insan kapıları, denetim kaydı ve
anayasa ilkeleri değişmez; yalnız alttaki sürücü, üretilen kodun dili ve koşum ortamı değişir.

### Kararlar (kullanıcı onaylı, 2026-11-08)

| # | Karar | Seçim |
|---|---|---|
| K1 | Hedef uygulama | Kendi demo uygulamalarımız: Bayi Sipariş Portalı'nın mobil (iOS + Android) ve Windows sürümleri, aynı demo API |
| K2 | Cihaz altyapısı | Android emülatörü ve iOS simülatörü bu Mac'te. Windows: CI'da `windows-latest`; canlı ajan için Mac'te UTM/Parallels içinde Windows 11 ARM sanal makinesi (Docker'da Windows Apple Silicon'da KVM olmadığı için olmaz) |
| K3 | Üretilen kod dili | **Java 17 + Appium java-client + TestNG** (Maven) |

### Teknik seçimler (bu planla sabitlenir)

| Konu | Seçim | Gerekçe |
|---|---|---|
| Otomasyon protokolü | **Appium 3** sunucusu, sürücüler: `uiautomator2` (Android), `xcuitest` (iOS), `novawindows` (Windows, UI Automation) | Üç platform tek W3C WebDriver protokolü; tek ekran nesnesi kütüphanesi |
| Mobil demo uygulaması | **Expo (React Native)**, `demo-app/mobile/` | Tek kod tabanı → iOS + Android; `testID` erişilebilirlik kimliğine dönüşür |
| Windows demo uygulaması | **WPF, .NET 8**, `demo-app/desktop/` | Kurumsal Windows masaüstünün tipik teknolojisi; `AutomationProperties.AutomationId` |
| Doğrulama ajanının aracı | Kendi MCP sunucumuz **`app-mcp`** (`toolchain/app-mcp/`, Node + TypeScript, Appium'a WebdriverIO ile bağlanır) | Hazır Appium MCP'ler ekran görüntüsü, kod çalıştırma, dosya araçları açar ve kapatılamaz; anayasa V ve araç izin listesi için dar, bizim kontrolümüzde bir yüzey gerekir |
| Java araçları | **`toolchain/java-araclar/`** (Maven, JavaParser): sembol tablosu çıkarıcı + üretilen test AST koruması + locator yoklaması | TS tarafındaki `symbols` / `ast-guard` ile aynı JSON sözleşmesi |

## 2. Ortak sözleşmeler (tüm şeritler buna uyar)

### 2.1 Platform

`platform ∈ {web, android, ios, windows}`. Case platformdan bağımsızdır (iş dilinde yazılır, bir kez
onaylanır). Kod üretimi **(case, platform)** çiftinedir: bir onaylı case'ten her platform için ayrı
script, ayrı dal, ayrı PR. `web` mevcut davranışın aynısıdır; varsayılan `web` (geriye uyum).

### 2.2 Erişilebilirlik kimlikleri (locator sözleşmesi)

Mobil ve Windows uygulamaları web'deki `data-testid` değerlerinin **aynısını** kullanır (tek liste:
`demo-app/kimlikler.json`, web kaynağından üretilir ve testle kilitlenir):

| Platform | Uygulamada | Appium'da |
|---|---|---|
| iOS | RN `testID` → `accessibilityIdentifier` | `AppiumBy.accessibilityId(id)` |
| Android | RN `testID` → `resource-id` | `AppiumBy.id(id)` (gerekirse `accessibilityId`) |
| Windows | `AutomationProperties.AutomationId` | `AppiumBy.accessibilityId(id)` |

Platform farkı yalnız `Kimlik.bul(id)` yardımcısındadır; ekran nesneleri platformdan bağımsızdır.
Onarım PR'ı kuralı aynen geçerlidir: **yalnızca kimlik değeri değişir**.

### 2.3 Java test projesi — `demo-app/e2e-app/`

```
demo-app/e2e-app/
  pom.xml                              # Java 17, io.appium:java-client, testng, allure-testng
  testng.xml                           # grup: kampanya, duman, uretilen
  src/test/java/com/antreklabs/bayi/
    altyapi/                           # SurucuFabrikasi (platform → Options), Kimlik, Bayi, TestTabani
    ekranlar/                          # ekran nesneleri: GirisEkrani, KatalogEkrani, SepetEkrani, SiparisEkrani, OnayEkrani
      Kimlikler.java                   # SAF VERİ: ekran başına kimlik sabitleri + Javadoc niyeti
    testler/                           # elle yazılmış referans testler
    uretilen/                          # şablondan üretilen testler (tek yazar: Testing Probe)
```

- Platform seçimi: `-Dplatform=android|ios|windows` (TestNG parametresi de kabul edilir); uygulama
  yolu, Appium adresi, cihaz adı sistem özelliği/ortamdan.
- Bayi sabitleme: `@Bayi("bayi2")` sınıf notasyonu (web'deki `test.use({ dealerUsername })` karşılığı).
- Ekran nesnesi metotları: eylem (`void`, ad fiil) ve beklenti (`dogrula…` ön eki, `kind=expect`);
  Javadoc ilk cümlesi = `doc`.
- Raporlar: Surefire JUnit XML (`target/surefire-reports/`) + Allure sonuçları — mevcut `core/src/tp_core/features/ci/parse.py`
  JUnit yolu kullanılır.
- Kırarak doğrula: web ile aynı `POST /test/break` (bayi kapsamlı); grup `kampanya`.

### 2.4 Üretilen test sözleşmesi

Şablon `rules/templates/appium_testng.java.j2`. Dosya:
`src/test/java/com/antreklabs/bayi/uretilen/<Story><Platform>C<sira>_<uuid8>Test.java` (ör.
`TPD1AndroidC3_0a1b2c3dTest.java`; platform adı, aynı case'in platform script'leri ayrı dosya/dal/PR
olsun diye — guard'ın dosya adı kuralına uyar). İçerik yalnızca:
`package`, izinli `import`'lar, `@Bayi` (opsiyonel), `TestTabani`'ndan türeyen tek sınıf, tek `@Test`
metot (`groups = {"uretilen", <etiketler>}`), gövdede yalnızca `<ekranAlanı>.<metot>(<literal>…);`
satırları. Dal, döngü, lambda, ham `driver`, `Thread.sleep`, yansıma, dosya/ağ erişimi yasak; bunu
`java-araclar guard` (JavaParser) denetler. Değerler `java` süzgeciyle Java literali olarak basılır.

### 2.5 Sembol tablosu

`java-araclar symbols --root demo-app/e2e-app` çıktısı TS `tp-symbols` ile **aynı şemadır**
(`SCHEMA_VERSION=1`, `page_objects[].class/methods/locators`, `errors`). `checks.SymbolTable` değişmeden
çalışır; `params[].type` Java türüdür (`String`, `int`, `boolean`, `double`).

### 2.6 app-mcp araçları

| Araç | Karşılığı (Playwright MCP) | Not |
|---|---|---|
| `app_launch` | `browser_navigate` | Uygulamayı sıfırdan başlatır (yalnızca yapılandırılmış uygulama kimliği) |
| `app_snapshot` | `browser_snapshot` | Sayfa kaynağından sadeleştirilmiş erişilebilirlik ağacı, `ref` atanmış satırlar |
| `app_click` | `browser_click` | `ref` ile |
| `app_type` | `browser_type` | `ref` + metin; parola alanları maskeli döner |
| `app_select_option` | `browser_select_option` | Seçici/picker |
| `app_wait_for` | `browser_wait_for` | metin göründü/kayboldu, zaman aşımı üst sınırlı |
| `app_generate_locator` | `browser_generate_locator` | `ref` → `{platform, id}` |
| `app_screenshot` | — | **Yalnızca çekirdeğin canlı görünüm kanalı**; ajanın izin listesinde yok, `FORBIDDEN_TOOLS`'ta |

Kod çalıştırma, dosya, sürücü komutu (`mobile:*` ve `execute`), uygulama kurma/kaldırma aracı **yoktur**.
Bağlantı: streamable HTTP, `APP_MCP_URL` (yalnızca core-worker). Platform başına Appium adresi
`APPIUM_URL_ANDROID|IOS|WINDOWS`.

### 2.7 Koşum ortamı

- **Yerel (Mac):** `make cihaz-kur` (Appium 3 + sürücüler, tek sefer), `make cihaz-baslat PLATFORM=android|ios`
  (emülatör/simülatör açılır, uygulama derlenip kurulur, Appium `127.0.0.1:4723`). Konteynerler hosta
  `host.docker.internal` ile ulaşır. Uygulama demo API'ye Android'de `10.0.2.2:8081`, iOS'ta
  `127.0.0.1:8081` üzerinden bağlanır.
- **Windows (yerel, isteğe bağlı):** UTM içinde Windows 11 ARM; içinde Appium + NovaWindows + uygulama;
  `APPIUM_URL_WINDOWS` VM adresi. Kurulum rehberi `docs/WINDOWS-VM.md`.
- **CI (GitHub forge kipi):** demo deposunda üç iş akışı — `mobil-android` (ubuntu + KVM emülatör),
  `mobil-ios` (macOS + simülatör), `masaustu-windows` (`windows-latest`). Zorunlu check listesine platform
  başına eklenir.
- **CI (LocalForge kipi):** test-runner Java testlerini hosttaki Appium'a karşı koşturur; test-runner
  için tek ağ istisnası `host.docker.internal:4723`.

### 2.8 Java biçim sözleşmesi (Ş3 yazar, Ş5 ayrıştırır, Ş6 render eder)

**Kimlikler (saf veri)** — `ekranlar/Kimlikler.java`; yalnızca iç içe `public static final class` ve
`public static final String` sabitleri; başka kod yok. Javadoc ilk cümlesi = `intent`. `_ONEK` ile biten
sabit önektir (`prefix: true`, ör. `URUN_KARTI_ONEK = "product-card-"`).

```java
public final class Kimlikler {
  private Kimlikler() {}
  /** Giriş ekranı. */
  public static final class Giris {
    /** Kullanıcı adı alanı. */
    public static final String KULLANICI_ADI = "login-username";
  }
}
```

Sembol tablosunda locator anahtarı `Giris.KULLANICI_ADI` → `{testId, role:"", name:"", intent, prefix, file}`.

**Ekran nesnesi** — `ekranlar/<Ad>Ekrani.java`, `Ekran` taban sınıfından türer. Sembol tablosuna yalnız
`public`, statik olmayan, kurucu olmayan metotlar girer. `dogrula` ile başlayan metot `kind: "expect"`,
diğerleri `"action"`; `async: false`; dönüş `void`. Parametre türleri yalnız `String`, `int`, `long`,
`double`, `boolean`.

```java
public class GirisEkrani extends Ekran {
  /** Bayi kullanıcı adı ve parolasıyla giriş yapar. */
  public void girisYap(String kullaniciAdi, String parola) { ... }
  /** Hata mesajının göründüğünü ve metnini doğrular. */
  public void dogrulaHataMesaji(String beklenen) { ... }
}
```

**Fikstür erişimi** — `TestTabani` her ekran için `lowerCamel(SınıfAdı)()` erişimcisi sağlar
(`girisEkrani()`, `katalogEkrani()` …). Fikstür adı = bu erişimcinin adı.

**Üretilen test** — tam biçim (başka hiçbir şey yok):

```java
// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; …
// Case: … · Story: … · Jira Test: …  (web şablonundaki başlık satırlarının aynısı)
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi2")
public class DEMO12C1_ab12cd34Test extends TestTabani {
  @Test(groups = {"uretilen", "kampanya"}, description = "…")
  public void senaryo() {
    // <adım etiketi>
    girisEkrani().girisYap("bayi2", "…");
    // Beklenen sonuç (değerler onaylı case metninden)
    sepetEkrani().dogrulaToplam("1.250,00 TL");
  }
}
```

`guard` kuralları: tek üst düzey sınıf; izinli import'lar yalnız yukarıdaki üçü; `@Bayi` en çok bir kez,
tek string literal; tek `@Test` metot, parametresiz, `void`; gövdede yalnız ifade deyimleri, her biri
`<erişimci>().<metot>(<literal>, …)` ve erişimci + metot sembol tablosunda var; argümanlar yalnız
string/int/long/double/boolean literal (negatif sayı için tekli eksi); dal, döngü, lambda, `new`, alan,
statik çağrı, `this`, `super`, dizi, metin bloğu yasak.

Ş6 çıktısının ek kuralları: TestNG grupları `{"uretilen", "<platform>", "tp-case-<case uuid>",
"<story>"}` (CI platform koşusu yalnız kendi platformunun üretilen testlerini `-Dgroups` ile
seçebilir); adım yorumu `// S<n> — <eylem>`; yorum ve literallerde Unicode kaçışı yoktur.

### 2.9 Çekirdek arayüzleri (Ş6 → Ş7, Ş8)

- **API:** `POST /code/generate {case_ids[], platform?: "web"|"android"|"ios"|"windows"}` (yoksa
  `web`; başka değer 422). Yanıt ve `sonuclar[]` öğeleri `platform` taşır. `GET /scripts`,
  `GET /scripts/{id}` → `platform`. Aynı case için platform başına ayrı script; "PR zaten var"
  ve yeniden üretimde eski PR'ı kapatma yalnız aynı platformda.
- **SSE / denetim:** `agent.step`, `pr.opened`, `codegen.check` yükleri ve `codegen.requested`,
  `codegen.committed`, `codegen.pr_opened` denetim kayıtları `platform` taşır. Uygulama
  adımlarında `tool` = `app_*`; ekran görüntüsü aynı `screenshot_url` (app-mcp `app_screenshot`).
- **Dal / dosya / PR:** dal `tp/case-<platform>-<uuid>[-n]`, dosya `<app root>/e2e-app/src/test/
  java/com/antreklabs/bayi/uretilen/<Story><Platform>C<n>_<uuid8>Test.java`, PR etiketi
  `platform:<platform>`, başlık `[<STORY>-C<n> · <platform>] …`.
- **toolchain (Ş5 uyumlu):** `/symbols {sha, platform}`; `/check {…, platform, test_files:
  ["src/test/java/…Test.java"]}` (e2e-app köküne göre; kırarak doğrulama aynı gövde +
  `env.BREAK_CAMPAIGN=1`, `repeat_each=1`). Web istek gövdeleri değişmez.
- **Ş8 (test-runner / CI) beklentisi:** `/run` gövdesinde `lang:"java"`, `platform`; rapor
  `run.tests[]` başına `title` (tekrarlarda aynı), `status` (`expected|unexpected|flaky|skipped`),
  `error` (tam istisna metni; ilk satır istisna sınıfı), isteğe bağlı `failure.type`
  (`locator_not_found|locator_timeout|assertion|navigation|test_data`), kanıt
  `target/kanit/<Sınıf>.<metot>/{ekran.png,sayfa-kaynagi.xml}`; CI koşularında
  `run.ortam.platform`. `enqueue_ci(script_id=…)` platformu `script.platform`'dan almalı; Java
  PR'ları için platform başına zorunlu check.

## 3. Şeritler

İlk dalga (bağımsız, paralel):

| Şerit | Kapsam | Çıktı |
|---|---|---|
| **Ş1 Mobil uygulama** | `demo-app/mobile/` Expo RN: giriş, katalog, sepet, sipariş, onay, siparişlerim; web ile aynı API ve kimlikler; iOS sim + Android emülatör derleme betikleri | Çalışan `.app` ve `.apk`, `demo-app/kimlikler.json` |
| **Ş2 Windows uygulaması** | `demo-app/desktop/` WPF .NET 8, aynı ekranlar ve AutomationId'ler; Mac'te `EnableWindowsTargeting` ile derlenir | Derlenen win-x64 + win-arm64 çıktısı |
| **Ş3 Java test projesi** | `demo-app/e2e-app/` (§2.3): altyapı, ekran nesneleri, referans testler, `ci/` betikleri (`run-app-checks.sh`, `break-verify-app.sh`) | Android ve iOS'ta yeşil referans koşu |
| **Ş4 Cihaz altyapısı + app-mcp** | `scripts/cihaz/` + Makefile hedefleri; `toolchain/app-mcp/` (§2.6) + birim testleri; compose servisi `app-mcp` | Ajan aracı canlı emülatörde çalışır |
| **Ş5 Java araçları** | `toolchain/java-araclar/`: `symbols`, `guard`, `locators` alt komutları (§2.4–2.5); toolchain-worker'a `/symbols?lang=java`, `/check` Java yolu (javac/maven test-compile + guard) | TS çıktısıyla aynı şema; golden testleri |

İkinci dalga (ilk dalganın sözleşmelerine bağlı):

| Şerit | Kapsam |
|---|---|
| **Ş6 Çekirdek** | `platform` boyutu (migrasyon, API, iş yükü), codegen'de platforma göre ajan aracı + şablon + kontrol yolu, gateway izin listesi (`verify_and_map_app`), `rules/prompts/verify-and-map-app.md`, REPLAY golden'ları, onarım (Java kimlik sabiti değişimi), triage kanıtı (sayfa kaynağı XML + ekran görüntüsü) |
| **Ş7 Portal** | "Kod üret" platform seçimi, platform rozeti, Kontrol Kulesi platform süzgeci, canlı görünüm (app-mcp ekran görüntüsü) |
| **Ş8 CI** | Demo deposu iş akışları (§2.7), LocalForge test-runner Java yolu, zorunlu check'ler |
| **Ş9 Doküman + demo** | `docs/WINDOWS-VM.md`, `docs/MOBIL-MASAUSTU.md`, README durum tablosu, canlı demo senaryosuna mobil bölüm |

Her şerit: hedefli test + çok rollü inceleme döngüsü (doğruluk, güvenlik/anayasa, sözleşme uyumu).
Tam paket yalnızca `dev`'e toplu gönderimden önce.

## 4. Anayasa kontrolü

| İlke | Karşılığı | Durum |
|---|---|---|
| I. AI üretir, insan onaylar | Değişmez: PR + insan onayı + kırarak doğrula | ✅ |
| II. CI'da AI yok | CI imajlarında app-mcp/model yok; Java testleri deterministik | ✅ |
| III. Yapılandırılmış çıktı | `verify_and_map_app` şeması mevcut şemanın platform alanlı hali | ✅ |
| IV. Kütüphaneye bağlı kod | Model Java yazmaz; şablon + sembol tablosu + AST koruması | ✅ |
| V. Uygulamayı gerçekten gör | app-mcp ile canlı cihaz; ajan ekran görüntüsü görmez, yalnız erişilebilirlik ağacı | ✅ |

## 5. Riskler

| Risk | Önlem |
|---|---|
| RN Android'de `testID` → `resource-id` eşlemesi sürüme bağlı | `Kimlik.bul` platform stratejisi + Ş3 referans testinde kilit |
| NovaWindows sürücüsünün Windows ARM'da davranışı | CI `windows-latest` (x64) birincil; ARM VM yalnız canlı ajan için |
| iOS derlemesi yavaş (pod install, xcodebuild) | Derlenmiş `.app` önbelleği; yalnız kaynak değişince yeniden derleme |
| GitHub macOS runner dakikaları pahalı | iOS iş akışı yalnız PR'da ilgili yol değişince + gece |
| Emülatör/simülatör kararsızlığı (flaky) | Uygulama sıfırlama her testte; deterministik bekleme yardımcıları; `Thread.sleep` yasak |

# demo-app/mobile — Bayi Sipariş Portalı (iOS + Android)

Web uygulamasının (`demo-app/web`) Expo / React Native sürümü. Aynı ekranlar, aynı davranış, aynı iş
kuralları ve **aynı demo API** (backend değişikliği yok). Appium ile test edilir (Java + TestNG,
`demo-app/e2e-app/`; plan: `specs/009-mobil-masaustu/plan.md`).

| Konu | Değer |
|---|---|
| Çatı | Expo SDK 58, React Native 0.88 (Yeni Mimari / Fabric, Hermes), TypeScript |
| Uygulama kimliği | `com.antreklabs.bayisiparis` (Android paketi ve iOS bundle id) |
| Bağımlılıklar | `package.json`'da tam sürümle sabit; `package-lock.json` depodadır |
| Yerel dizinler | `android/`, `ios/` **depoda yok** (`.gitignore`); her derlemede `expo prebuild --clean` ile yeniden üretilir. Yerel ayarlar yalnızca `app.json` ve `plugins/` içindedir |

## Ekranlar (web ↔ mobil)

| Web | Mobil | Kaynak |
|---|---|---|
| `/giris` | Giriş | `src/ekranlar/GirisEkrani.tsx` |
| Üst menü (`Layout`) | Üst çubuk (bayi adı, çıkış) + alt sekmeler (Katalog, Sepet + sayaç, Siparişlerim) | `src/bilesenler/Kabuk.tsx` |
| `/katalog` | Katalog | `src/ekranlar/KatalogEkrani.tsx` |
| `/sepet` | Sepet | `src/ekranlar/SepetEkrani.tsx` |
| `/siparis/<no>` | Sipariş onayı | `src/ekranlar/OnayEkrani.tsx` |
| `/siparisler` | Siparişlerim | `src/ekranlar/SiparislerEkrani.tsx` |

API istemcisi (`src/api.ts`) web'dekinin aynısıdır (uçlar, tipler, hata metinleri). Tutarlar
`1.250,00 TL` biçimindedir (`src/bicim.ts`, Intl'e bağımlı değil — her cihazda aynı metin). Android
geri tuşu bir önceki ekrana döner. Oturum, web'deki gibi HttpOnly `bayi_oturum` çerezindedir
(RN'nin yerel çerez deposu).

## API adresi

Uygulama web ile aynı yolu kullanır: `demo-app-web` nginx'i (host `127.0.0.1:8081`) `/api/*`
isteklerini `demo-app-api`'ye vekiller (`demo-app/web/nginx.conf`; `/api/test/*` kapalıdır).

| Platform | Varsayılan | Neden |
|---|---|---|
| Android emülatörü | `http://10.0.2.2:8081/api` | `10.0.2.2` emülatörden hostun geri döngü adresidir |
| iOS simülatörü | `http://127.0.0.1:8081/api` | Simülatör hostun ağını paylaşır |

Değiştirmek için **derleme anında** ortam değişkeni verin (Expo `EXPO_PUBLIC_*` değerlerini JS
paketine gömer; çalışma anında okunmaz):

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.20:8081/api scripts/derle-android.sh   # iki platform
EXPO_PUBLIC_API_URL_ANDROID=… / EXPO_PUBLIC_API_URL_IOS=…                    # platforma özel (öncelikli)
```

**Düz HTTP izni** (`plugins/ag-guvenligi.js`): demo API TLS'sizdir. Android'de
`network_security_config.xml` yalnızca `10.0.2.2`, `127.0.0.1`, `localhost` (ve verilmişse
`EXPO_PUBLIC_API_URL*` hostu) için cleartext açar; genel `usesCleartextTraffic` kullanılmaz. iOS'ta
aynı hostlar için ATS `NSExceptionDomains` istisnası eklenir.

## Derleme

Önkoşul: Node 22, JDK 17, Android SDK (`~/Library/Android/sdk` ya da `ANDROID_HOME`), Xcode,
CocoaPods. Çıktılar `build/` altındadır (depoda yok).

```bash
cd demo-app/mobile
npm ci
scripts/derle-android.sh   # → build/bayi-siparis.apk
scripts/derle-ios.sh       # → build/BayiSiparis.app
```

| Betik | Ne yapar | Not |
|---|---|---|
| `derle-android.sh` | kimlik + tip denetimi → `expo prebuild --platform android --clean` → `gradlew assembleRelease` | Release varyantı Expo şablonunda **debug anahtarıyla** imzalanır: `adb install` ile kurulur, JS paketi (Hermes bayt kodu) gömülüdür, Metro gerekmez, geliştirici menüsü/LogBox yoktur. `ANDROID_ABI` (varsayılan `arm64-v8a,x86_64`) |
| `derle-ios.sh` | kimlik + tip denetimi → `expo prebuild --platform ios --clean` → `pod install` → `xcodebuild -configuration Release -sdk iphonesimulator` | Yalnızca simülatör, imzasız; `main.jsbundle` `.app` içindedir. `IOS_ARCHS` (varsayılan `arm64`), `POD` (çalışan `pod` yolu) |

Kurulum ve açılış:

```bash
# Android (emülatör açıkken)
adb install -r build/bayi-siparis.apk
adb shell am start -n com.antreklabs.bayisiparis/.MainActivity

# iOS (simülatör açıkken)
xcrun simctl install booted build/BayiSiparis.app
xcrun simctl launch booted com.antreklabs.bayisiparis
```

Demo API'nin çalışıyor olması gerekir (depo kökünde `make up`; `curl http://127.0.0.1:8081/health`).
Giriş için demo bayileri: `demo-app/README.md` → "Demo bayileri".

Geliştirme sırasında Metro ile canlı yenileme: `npx expo run:android` / `npx expo run:ios`
(debug derlemesi; testte kullanılmaz).

## Kimlik sözleşmesi (locator'lar)

Her etkileşimli / doğrulanan eleman, web'deki `data-testid` değerinin **aynısını** taşır. Tek liste:
[`demo-app/kimlikler.json`](../kimlikler.json) (kimlik, ekran, önek mi). Önek kimliklerin sonuna ürün
kodu / sipariş numarası eklenir: `product-card-P-001`, `cart-line-qty-P-001`, `order-row-SP-000001`.

| Platform | Uygulamada | Appium'da |
|---|---|---|
| iOS | RN `testID` → `accessibilityIdentifier` (XCUITest `name`/`identifier`) | `AppiumBy.accessibilityId(id)` |
| Android | RN `testID` → `AccessibilityNodeInfo.viewIdResourceName` (UiAutomator2 `resource-id`) | `AppiumBy.id(id)` |

Kimlikler yalnızca `src/kimlik.ts`'deki `tid()` yardımcısıyla verilir: `{...tid("login-username")}`,
dinamik olanlar `{...tid(`product-card-${p.kod}`)}`. `tid()` `testID` ve `collapsable: false` koyar:

- **Android:** RN 0.88'de `testID`, `ReactAccessibilityDelegate` tarafından `resource-id` olarak
  yayımlanır — **paket öneki olmadan** (`resource-id="login-username"`).
  ⚠ UiAutomator2 sürücüsü `id` stratejisinde varsayılan olarak paket öneki ekler
  (`com.antreklabs.bayisiparis:id/login-username`) ve elemanı bulamaz. Oturumda
  **`appium:disableIdLocatorAutocompletion: true`** verilmelidir; o zaman `AppiumBy.id("login-username")`
  çalışır (denendi). Alternatif: `-android uiautomator` `new UiSelector().resourceId("login-username")`.
- **`collapsable: false` neden:** Fabric, yalnızca `testID` taşıyan bir View'ı yerel görünüm yapar ama
  çocuklarını onun içine değil en yakın "yığın bağlamlı" ataya koyar. Önlem alınmazsa erişilebilirlik
  ağacında `product-card-P-001` boş bir kardeş olur ve "Sepete ekle" kartın içinde aranamaz (ilk
  derlemede uiautomator dump'ında gözlendi). `collapsable: false` kapsayıcıyı gerçek ata yapar.
- **Düğme metni (Android):** Pressable `android.widget.Button` olarak görünür; görünen metin
  `content-desc`'tedir (`Sepete ekle`), `text` boştur (metin çocuk TextView'dadır).
- **accessibilityLabel kimliğe eşitlenmez:** ekran okuyucu "login-username" okurdu. Etiketler Türkçe
  ve anlamlıdır (Kullanıcı adı, Sepete ekle, "… ürününü sepetten kaldır").
- **iOS katlanma kuralı:** dokunulabilir bir elemanın (Pressable) çocukları XCUITest'te ayrı eleman
  olmaz. Bu yüzden kimlikli elemanlar düğme içine konmaz: sepet sayacı `cart-count`, `nav-cart`
  sekmesinin kardeşidir; sipariş satırı `order-row-…` dokunulabilir değildir (bağlantı numaradadır).
- **İç içe `<Text>` yok:** iç metin kendi görünümünü oluşturmaz, kimliği kaybolur. `order-number`
  gibi değerler ayrı `<Text>`'tir. Kimlikli metinlerin içeriği web ile birebir aynıdır
  (`cart-discount` = `125,00 TL`; eksi işareti ayrı, kimliksiz bir metindir — web'deki gibi).
- `product-status-<kod>` boşken de ağaçta bulunur (en az yükseklik), web'deki boş `<p role=status>` gibi.
- `add-to-cart` web'deki gibi her kartta tekrarlanır; kartın (`product-card-<kod>`) içinde aranır.

Denetim — web, liste ve mobil kaynak birebir mi:

```bash
npm run kimlik-kontrol   # ≠0: liste web'den sapmış, mobilde eksik/fazla/yanlış ekranda kimlik var,
                         #     testID'ye literal yazılmış ya da e2e locator'ı web'de yok
npm run kimlik-uret      # web data-testid'leri değişince listeyi yeniden üretir (sonra mobil uyarlanır)
npm run tip-kontrol      # tsc --noEmit
```

Derleme betikleri ikisini de önce çalıştırır; sözleşme bozuksa derleme yapılmaz.

## Doğrulama

```bash
# Android (Appium'suz): resource-id'ler
adb shell uiautomator dump /sdcard/pencere.xml && adb pull /sdcard/pencere.xml
grep -o 'resource-id="[^"]*"' pencere.xml | sort -u

# Ekran görüntüsü
adb exec-out screencap -p > ekran.png
xcrun simctl io booted screenshot ekran.png
```

iOS'ta `accessibilityIdentifier` yalnızca XCUITest üzerinden görülür (Appium XCUITest sürücüsü ya da
doğrudan WebDriverAgent). Sayfa kaynağında `name="<kimlik>"`, `label` ise Türkçe erişilebilirlik
adıdır (ör. `name="add-to-cart" label="Sepete ekle"`).

İlk doğrulama (2026-11-08, Android 16 emülatörü + iOS 18.5 simülatörü, bayi1): giriş hatası, giriş,
7 adet kampanyalı ürün (1 bedava, 25,00 TL indirim), sepet tutarları, sipariş onayı, siparişlerim,
boş sepet, minimum tutar uyarısı (onay düğmesi pasif), satır kaldırma ve çıkış her iki platformda
kimliklerle bulunarak yürütüldü; 39 kimliğin 37'si ağaçta görüldü (`checkout-error` ve `orders-empty`
yalnızca hata / hiç siparişi olmayan bayi durumunda çıkar).

**Bilinen davranışlar**

- iOS sayı klavyesinde "Bitti" tuşu yoktur; açık klavye alt sekmeleri ve alttaki kartların
  düğmelerini örter. Uygulama "Sepete ekle"de klavyeyi kapatır ve kaydırınca kapanır; testte adet
  yazıldıktan sonra aynı kartın düğmesine basılır (başka karta geçmeden).

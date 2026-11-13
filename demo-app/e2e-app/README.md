# demo-app/e2e-app — uygulama uçtan uca testleri (Android, iOS, Windows)

Bayi Sipariş Portalı'nın mobil (`demo-app/mobile`, Expo RN) ve Windows (`demo-app/desktop`, WPF)
sürümlerinin testleri: **Java 17 + Appium java-client + TestNG**, Maven. Web karşılığı
`demo-app/e2e` (Playwright); ekranlar, metotlar, bayi kuralları ve test verisi kancaları onunla aynı
anlamdadır. Plan ve bağlayıcı biçim sözleşmesi: `specs/009-mobil-masaustu/plan.md` §2.2–2.4, §2.8.

## Yapı

```
pom.xml, testng.xml, mvnw (+ .mvn/wrapper)   sürümler sabit; sistemde Maven gerekmez
araclar/KirmiziDenetimi.java                 kırarak doğrula kırmızı adım denetimi (tek dosya Java)
src/test/java/com/antreklabs/bayi/
  altyapi/    SurucuFabrikasi, Kimlik, Kaydirma, Klavye, Bekle, Bayi, Bayiler, BayiKilidi, TestVerisi,
              Kanit, OturumAcik, UygulamaOturumu, Ayarlar, Platform, TestTabani
  ekranlar/   Kimlikler (saf veri), Ekran (taban), GirisEkrani, KatalogEkrani, SepetEkrani,
              OnayEkrani, SiparisEkrani
  testler/    elle yazılmış referans testler (web tests/*.spec.ts karşılıkları)
  uretilen/   şablondan üretilen testler — tek yazar Testing Probe; TPD1C3_0a1b2c3dTest altın örnek
  birim/      cihazsız birim testleri (grup "birim")
```

## Koşum

```bash
cd demo-app/e2e-app
./mvnw -q test-compile                      # derleme (ilk sefer bağımlılıkları indirir; sonra -o ile çevrimdışı)
./mvnw -q test -Dgroups=birim               # birim testleri: cihaz, Appium, API gerekmez

# Cihaz koşusu (Appium 3 sunucusu + emülatör/simülatör/Windows VM hazır; demo API çalışıyor):
export DEMOAPP_TEST_TOKEN=…                 # ORTAMDAN; depoya ve komut satırına yazmayın
export DEMO_API_URL=http://127.0.0.1:18000  # /test/* uçlarına doğrudan erişilen API kökü
# Compose demo-app-api'yi hosta açmaz ve demo-net internal'dır (port yayımlanamaz). Yerelde geçici vekil:
#   docker run -d --rm --name tp-demo-api-vekil -p 127.0.0.1:18000:8000 alpine/socat \
#     tcp-listen:8000,fork,reuseaddr tcp:demo-app-api:8000
#   docker network connect testingprobe_demo-net tp-demo-api-vekil
../ci/run-app-checks.sh android -Dapp.path=../mobile/build/bayi-siparis.apk
DEVICE_UDID="$(cat ../../var/cihaz/ios.udid)" \
  ../ci/run-app-checks.sh ios -Dapp.path=../mobile/build/BayiSiparis.app   # iOS: simülatör UDID ile (make cihaz-baslat PLATFORM=ios yazar)
../ci/run-app-checks.sh android -Dgroups=duman          # yalnız bir grup (testng.xml devre dışı kalır)
../ci/break-verify-app.sh android -Dapp.path=…          # yeşil → kırmızı (yalnız assertion) → yeşil
```

`run-app-checks.sh`: `test-compile` → birim (`target/birim-raporlari/`) → cihaz koşusu. Sonuçlar
`target/surefire-reports/TEST-*.xml` (JUnit XML; `core/src/tp_core/features/ci/parse.py`), `target/allure-results/`,
`target/extent-report/index.html` (Extent raporu), başarısız
testin kanıtı `target/kanit/<Sınıf>.<metot>/{ekran.png,sayfa-kaynagi.xml}` (triage okur).

### Raporlar: Allure ve Extent

Her koşu iki okunur rapor kaynağı üretir; ikisi de test kodunda ek çağrı istemez:

- **Allure** — `allure-testng` `target/allure-results/` yazar; HTML raporu test-runner üretir.
- **Extent (Spark)** — `altyapi/ExtentRaporu` TestNG dinleyicisi (`src/test/resources/META-INF/services/
  org.testng.ITestNGListener` ile kendiliğinden yüklenir; testng.xml ve `-Dgroups` koşusunda aynı)
  `target/extent-report/index.html` yazar. Rapor **tek dosyadır ve dış kaynak yüklemez** (css/js/simge
  yazı tipi gömülü): tarayıcıda doğrudan, ağ olmadan ve portalın sandbox'ında açılır. Başarısız testin
  kanıt ekran görüntüsü modele ve arşive dosya yolu olarak girer, koşu sonunda rapora gömülür (en çok 50,
  koşu geneli — önceki tekrarlar dahil; fazlası `../kanit/…` bağlantısı). Ara yazım her 25 testte / 30 sn'de
  bir; kesintide (SIGTERM) kapanış kancası son durumu yazar. Rapor ve arşiv atomik taşınır: yazım yarıda
  kalırsa önceki geçerli `index.html` kalır ve yanına `index.uyari.txt` yazılır.

| Özellik | Varsayılan | Not |
| --- | --- | --- |
| `extent.rapor.dizini` | `target/extent-report` | boş verilirse (`-Dextent.rapor.dizini=`) rapor üretilmez; birim adımı `target/birim-raporlari/extent-report`'a yazar |
| `extent.tekrar` | — | tekrarlı koşuda `<i>/<n>` (test-runner verir): test adına `(tekrar 2/3)` eklenir |

Tekrarlar (test-runner'ın `repeat_each` koşuları, `extent.tekrar` `i > 1`) dizindeki `extent.json`
arşivi üzerinden **tek raporda birleşir**. `extent.tekrar` verilmeyen koşu ve ilk tekrar arşivi siler:
`clean`'siz yeniden koşuda eski sonuçlar rapora karışmaz.

Test adı `@Test(description)` (yoksa `Sınıf › metot`), altında `Sınıf.metot`; kategoriler TestNG
gruplarıdır, `tp-case-*` hariç (case kimliği ayrıntıda `Testing Probe case: <uuid>` satırı). Allure:
`TestTabani` gruplardan etiket ekler — her grup `tag`, Jira anahtarı (`TPD-1`) `story`,
`tp-case-<uuid>` ayrıca `tp-case=<uuid>` (`altyapi/TestGruplari`). Test JVM'i: pom `argLine` =
`-Xmx512m -Dfile.encoding=UTF-8`.
Raporlama hatası testi ya da koşuyu düşürmez: uyarı günlüğe yazılır, o koşuda Extent raporu kapanır.

## Ayarlar

Önce sistem özelliği (`-Dad=…`), yoksa ortam değişkeni, yoksa varsayılan (`altyapi/Ayarlar.java`).

| Özellik | Ortam | Varsayılan | Not |
|---|---|---|---|
| `platform` | `PLATFORM` | — | `android` \| `ios` \| `windows` (TestNG parametresi `platform` da kabul) |
| `appium.url` | `APPIUM_URL` | `http://127.0.0.1:4723` | Appium 3 (temel yol `/`) |
| `app.path` | `APP_PATH` | — | `.apk` / `.app` / `.exe`; yoksa `app.id` kurulu uygulamayı açar |
| `app.id`, `app.activity` | `APP_ID`, `APP_ACTIVITY` | — | Android paket / iOS bundle id (`com.antreklabs.bayisiparis`) / Windows AUMID |
| `app.args` | `APP_ARGS` | — | Windows: uygulama argümanları (NovaWindows `appArguments`) |
| `app.workdir` | `APP_WORKDIR` | — | Windows: uygulamanın çalışma dizini (NovaWindows `appWorkingDir`). Windows uygulama yolu/argüman/dizininde tek tırnak ve denetim karakteri reddedilir (sürücü PowerShell'e kaçışsız geçirir) |
| `device.name`, `device.udid`, `platform.version` | `DEVICE_NAME`, `DEVICE_UDID`, `PLATFORM_VERSION` | — | |
| `demo.api.url` | `DEMO_API_URL` | `http://127.0.0.1:8081/api` | `/test/*` kökü. Compose'daki nginx `/api/test/`'i açmaz: orada doğrudan API adresi verin |
| `demoapp.test.token` | `DEMOAPP_TEST_TOKEN` | — | **Sır.** Yalnızca ortamdan; başlıkta taşınır, rapora/kanıta yazılmaz |
| `break.campaign` | `BREAK_CAMPAIGN` | — | `1`: bayi kapsamlı kampanya kırılması |
| `tp.fault` | `TP_FAULT` | — | Ekilmiş hata kodu (`^[a-z0-9_]{1,40}$`, demo API `faults.py`): bayi kapsamlı `/test/break {hata}`; `BREAK_CAMPAIGN` ile birlikteyse bu geçerlidir |
| `tp.e2e.no.reset` | `TP_E2E_NO_RESET` | — | `1` + token yok: yalnızca sepet yalıtımı |
| `bekleme.ms` | `BEKLEME_MS` | `10000` | eylem/beklenti üst sınırı |
| `bayi.kilit.ms` | `BAYI_KILIT_MS` | `40000` | bayi kilidi bekleme |
| `kimlik.android` / `.ios` / `.windows` | `KIMLIK_*` | plan §2.2 | `id` \| `erisilebilirlik` \| `uiautomator` (yalnız Android) |

## Altyapı kuralları

- **Kimlik → seçici yalnızca `Kimlik.bul(id)`** (plan §2.2): Android `AppiumBy.id` (RN testID →
  resource-id), iOS ve Windows `AppiumBy.accessibilityId`. RN sürümü kimliği başka yere yazarsa kod
  değişmeden `-Dkimlik.android=erisilebilirlik` (content-desc) ya da `uiautomator` (öneksiz/önekli
  resource-id tam eşleşmesi). Ekran nesneleri platform bilmez.
- **Bekleme**: yalnızca açık bekleme (`Bekle`), örtük bekleme 0, `Thread.sleep` yasak (birim testi
  denetler). Eylem ön koşulu sağlanmazsa `TimeoutException` (locator/kurulum), beklenti sağlanmazsa
  `AssertionError` (`dogrula…`). Kırarak doğrula ve triage bu ayrıma dayanır.
- **Ekran dışı öğe**: `Kaydirma` — Android `UiScrollable.scrollIntoView`; iOS'ta kaydırma kabının
  kenar boşluğundan öğeye doğru `mobile: dragFromToForDuration` sürüklemesi (WDA'nın
  `mobile: scroll toVisible`'ı RN `ScrollView`'da çalışmaz). Klavye altında kalan öğe de aynı
  sürüklemeyle açılır (katalog `keyboardDismissMode="on-drag"`).
- **Klavye**: `Klavye.kapat` — Android `hideKeyboard`; iOS'ta `hideKeyboard` yalnız "done" tuşuyla
  kapatabildiğinden (sayı klavyesinde yok; giriş ekranındaki "next"/"go" eylem tetikler) klavyenin
  üstünde kısa bir sürükleme.
- **Uygulama sıfırlama**: her test yeni Appium oturumu (`noReset=false`); oturum taşınmaz.
- **Hazırlık testin içinde** (`TestTabani` TestNG `IHookable`): bayi kilidi → `/test/reset` (ya da
  sepet boşaltma) → `TP_FAULT` ya da `BREAK_CAMPAIGN` ise `/test/break` → oturum → `@OturumAcik` ise arayüzden giriş →
  `hazirlikSonrasi()`. Hazırlık hatası testin kendi hatasıdır; JUnit XML'de test başına tek satır.
- **Bayi**: varsayılan `bayi1`; `@Bayi("bayi2")` sınıfı sabitler (web `test.use({ dealerUsername })`).
  `bayi3` doğrulama ajanınındır, e2e'ye kapalıdır. Aynı demo API'ye karşı koşan Java süreçleri (ör.
  Android + iOS aynı anda) bayiyi işletim sistemi dosya kilidiyle sırayla alır
  (`$TMPDIR/demoapp-e2e-app-kilit-<api özeti>/`). **Web e2e ile kilit ortak değildir:** web
  (`demo-app/e2e/tests/fixtures.ts`) kendi dizininde (`$TMPDIR/demoapp-e2e-kilit-<özet>/`, O_EXCL
  dosyası) kilitler; ikisi birbirini görmez. Aynı demo API'ye karşı web e2e ile uygulama e2e'sini
  (ya da break-verify'larını) aynı anda koşturmayın — `/test/reset` ve `/test/break` bayi verisini
  diğerinin altından değiştirir. Sıra: önce biri, sonra diğeri (CI'da ayrı demo ortamları).
- **Gruplar**: `duman` (temel akışlar), `kampanya` (kırarak doğrula kümesi), `uretilen`,
  `sifir-veri` (sıfırlanmış veri ister; `TP_E2E_NO_RESET=1`'de atlanır), `birim` (cihazsız).

## Ekranlar (web ↔ uygulama)

| Web page object | Ekran nesnesi | Metotlar (web karşılığı) |
|---|---|---|
| `LoginPage` | `GirisEkrani` | `ac` (goto), `girisYap` (login), `cikisYap` (logout), `dogrulaHataMesaji` (expectLoginError), `dogrulaGirisYapildi` (expectLoggedIn), `dogrulaGirisEkraninda` (expectOnLoginPage) |
| `CatalogPage` | `KatalogEkrani` | `ac` (goto), `menudenAc` (openFromMenu), `adetGir` (setQuantity), `sepeteEkle` (addToCart), `sepetiAc` (openCart), `dogrulaUrunGorunur` (expectProductVisible), `dogrulaUrunFiyati` (expectProductPrice), `dogrulaKampanya` (expectCampaign), `dogrulaSepetSayaci` (expectCartCount) |
| `CartPage` | `SepetEkrani` | `ac` (goto), `urunuKaldir` (removeProduct), `siparisiOnayla` (checkout), `dogrulaSatirAdedi`, `dogrulaBedavaAdet`, `dogrulaSatirToplami`, `dogrulaAraToplam`, `dogrulaIndirim`, `dogrulaToplam`, `dogrulaMinimumSiparisUyarisi`, `dogrulaMinimumSiparisUyarisiYok`, `dogrulaOnayPasif`, `dogrulaOnayAktif`, `dogrulaUrunSepetteYok`, `dogrulaSepetSayaci`, `dogrulaSepetBos` (expect… sırasıyla) |
| `OrderPage` (onay) | `OnayEkrani` | `dogrulaSiparisOnayi` (expectConfirmation), `dogrulaOnaylananToplam` (expectConfirmedTotal), `dogrulaOnaylananSiparisGecmiste` (expectConfirmedOrderInHistory), `dogrulaOnaylananIndirim`, `siparislerimeGit`, `alisveriseDevamEt` |
| `OrderPage` (geçmiş) | `SiparisEkrani` | `ac` (gotoHistory), `menudenAc` (openHistory), `dogrulaSiparisGecmiste` (expectOrderInHistory), `dogrulaSiparisToplami` (expectOrderTotalInHistory), `dogrulaSiparisYok` (expectNoOrders), `dogrulaOnaylananSiparisToplami` |

Web'deki `readOrderNumber()` değer döndürür; sözleşmede yalnız `void` metot olduğundan onay ekranında
okunan numara oturumda saklanır (`dogrulaOnaylananSiparisToplami`).

## Üretilen testler

`uretilen/<Story><Platform>C<sira>_<uuid8>Test.java` (ör. `TPD1AndroidC3_0a1b2c3dTest.java`; plan
§2.4), şablon `rules/templates/appium_testng.java.j2`. İçerik
yalnızca başlık yorumları, `package`, üç izinli import, en çok bir `@Bayi("…")`, `TestTabani`'ndan
türeyen tek sınıf, tek `@Test(groups = {"uretilen", …})` `senaryo()` metodu ve gövdede
`<erişimci>().<metot>(<literal>, …);` satırları (plan §2.4, §2.8). Elle düzenlenmez;
`toolchain/java-araclar guard` denetler. Elle yazılmış `TPD1C3_0a1b2c3dTest` biçim (gövde ve
yapı) için altın örnektir ve bilerek platformdan bağımsızdır (adında platform yoktur; guard'ın
dosya adı kuralı `[A-Za-z][A-Za-z0-9]*C<n>_<uuid8>Test.java` iki biçimi de kabul eder). Testing Probe'un ürettiği
dosyalar adında her zaman platformu taşır (`…AndroidC3…`, `…IosC3…`, `…WindowsC3…`): aynı case'in
platform script'leri ayrı dosya/dal/PR olur.

## Onarım (locator)

Uygulamada kimlik değişirse onarım PR'ı **yalnızca** `ekranlar/Kimlikler.java`'daki değeri değiştirir.
`Kimlikler` saf veridir: iç içe `public static final class` + `public static final String`; Javadoc ilk
cümlesi niyet; `_ONEK` ile biten sabit önektir (değeri `-` ile biter). Birim testi Kimlikler'in web
`data-testid` kümesiyle birebir aynı olduğunu (ve varsa `demo-app/kimlikler.json` ile uyumunu) kilitler.

// Expo yapılandırma eklentisi: Espresso (AndroidX Test) testlerini prebuild'de Android projesine
// bağlar (TASARIM test-dilleri §3.3; Kotlin/Espresso müşteri CI hattı, demo hedefi).
//
// `android/` depoda yok (her derlemede `expo prebuild --clean`); bu yüzden androidTest ayarları
// elle değil bu eklentiyle gelir. Yaptığı (yalnız `android/app/build.gradle`):
//   - androidTest kaynak kökü: `demo-app/mobile/android-test/java` (ekran nesnesi kütüphanesi
//     `com.antreklabs.bayisiparis.tp` + TP'nin ürettiği testler `…tp.uretilen`). Dosyalar
//     kopyalanmaz, kaynak kümesi depodaki dizini gösterir.
//   - `testInstrumentationRunner` = AndroidJUnitRunner; Test Orchestrator + `clearPackageData`
//     (her test temiz uygulama verisiyle; oturum çerezi taşınmaz) ve Test Storage (kanıt dosyaları
//     `connected_android_test_additional_output/` altına çekilir).
//   - Ayrı `tpTest` derleme türü (`initWith release`, R8 KAPALI) ve `testBuildType "tpTest"`:
//     RN debug varyantı JS'i Metro'dan yükler (8081; demo API ile çakışır, CI'da Metro yok);
//     release ise R8 ile küçültülür ve AGP, test APK'sından uygulamada da bulunan kütüphane
//     sınıflarını çıkarır — R8'in uygulamadan sildiği bir sınıf (ör. `androidx.tracing.Trace`)
//     iki APK'da da kalmaz ve AndroidJUnitRunner açılışta çöker (yerel emülatör denemesinde
//     gözlendi). `tpTest` release ile aynıdır (gömülü JS paketi, debug anahtarı) ama küçültülmez;
//     kütüphane modülleri `matchingFallbacks` ile release varyantını kullanır. Görevler:
//     `assembleTpTest`, `assembleTpTestAndroidTest`, `connectedTpTestAndroidTest`.
//   - androidTest bağımlılıkları (sürümler sabit; `ESPRESSO_SURUMLERI`).
//
// Uygulamanın kendisi (release APK içeriği) DEĞİŞMEZ: yalnız androidTest yapılandırması eklenir.
// İşaretli blok idempotenttir (prebuild yeniden koşarsa çift eklenmez).
const ISARET_BAS = "// @tp-espresso başlangıç (plugins/espresso.js; elle düzenlemeyin)";
const ISARET_SON = "// @tp-espresso bitiş";

// AndroidX Test sürümleri (2026-11; Espresso 3.6 / Test 1.6 ailesi, minSdk 21+).
const ESPRESSO_SURUMLERI = {
  "androidx.test:core-ktx": "1.6.1",
  "androidx.test:runner": "1.6.2",
  "androidx.test:rules": "1.6.1",
  "androidx.test.ext:junit-ktx": "1.2.1",
  "androidx.test.espresso:espresso-core": "3.6.1",
  "androidx.test.services:storage": "1.5.0",
  "junit:junit": "4.13.2",
};
const ORCHESTRATOR = "androidx.test:orchestrator:1.5.1";
const TEST_SERVICES = "androidx.test.services:test-services:1.5.0";

// Gradle'a giden kaynak kökü: android/app'e göre (expo prebuild düzeni sabittir).
const KAYNAK_KOKU = "../../android-test/java";

function blok() {
  const bagimliliklar = Object.entries(ESPRESSO_SURUMLERI)
    .map(([ad, surum]) => `    androidTestImplementation("${ad}:${surum}")`)
    .join("\n");
  return `${ISARET_BAS}
android {
    defaultConfig {
        testInstrumentationRunner "androidx.test.runner.AndroidJUnitRunner"
        testInstrumentationRunnerArguments clearPackageData: "true"
        testInstrumentationRunnerArguments useTestStorageService: "true"
    }
    buildTypes {
        tpTest {
            initWith release
            minifyEnabled false
            shrinkResources false
            matchingFallbacks = ["release"]
        }
    }
    testBuildType "tpTest"
    testOptions {
        execution "ANDROIDX_TEST_ORCHESTRATOR"
        animationsDisabled true
    }
    sourceSets {
        androidTest.java.srcDirs += "${KAYNAK_KOKU}"
    }
}
dependencies {
${bagimliliklar}
    androidTestUtil("${ORCHESTRATOR}")
    androidTestUtil("${TEST_SERVICES}")
}
${ISARET_SON}
`;
}

/** build.gradle metnine işaretli bloğu ekler (varsa yeniler). Saf işlev: birim testi için dışa açık. */
function espressoBlogunuUygula(metin) {
  const bas = metin.indexOf(ISARET_BAS);
  if (bas !== -1) {
    const son = metin.indexOf(ISARET_SON, bas);
    if (son === -1) {
      throw new Error("plugins/espresso.js: build.gradle'da bitiş işareti yok (elle düzenlenmiş)");
    }
    metin = metin.slice(0, bas) + metin.slice(son + ISARET_SON.length).replace(/^\n/, "");
  }
  if (!/apply plugin: "com\.android\.application"|id\s*\(?\s*["']com\.android\.application["']/.test(metin)) {
    throw new Error("plugins/espresso.js: android/app/build.gradle bir Android uygulama modülü değil");
  }
  return `${metin.replace(/\s*$/, "\n")}\n${blok()}`;
}

function withEspresso(config) {
  // Geç yükleme: saf `espressoBlogunuUygula` node_modules olmadan da test edilebilir.
  const { withAppBuildGradle } = require("expo/config-plugins");
  return withAppBuildGradle(config, (cfg) => {
    if (cfg.modResults.language !== "groovy") {
      throw new Error("plugins/espresso.js: yalnız Groovy build.gradle desteklenir");
    }
    cfg.modResults.contents = espressoBlogunuUygula(cfg.modResults.contents);
    return cfg;
  });
}

module.exports = withEspresso;
module.exports.espressoBlogunuUygula = espressoBlogunuUygula;
module.exports.ESPRESSO_SURUMLERI = ESPRESSO_SURUMLERI;

// Expo yapılandırma eklentisi: belirli pod'ları Swift 5 dil kipinde derler.
//
// Neden: GitHub macOS runner'ındaki Xcode 26.x derleyicisi expo-modules-jsi'deki
// (ExpoModulesJSI) bir Swift 6 eşzamanlılık denetimini hata sayıyor ("sending 'slot' risks
// causing data races"); yerel Xcode 27 aynı kodu kabul ediyor. Swift 5 kipinde bu denetim uyarıdır.
// Yalnızca listelenen pod'lar etkilenir; uygulama hedefi ve diğer pod'lar değişmez.
// Podfile `expo prebuild` ile her seferinde yeniden üretilir (ios/ depoda yok); ekleme idempotenttir.
const fs = require("node:fs");
const path = require("node:path");
const { withDangerousMod } = require("expo/config-plugins");

const PODLAR = ["ExpoModulesJSI"];
const ISARET = "# tp: swift5-uyumluluk";

function ekle(podfile) {
  if (podfile.includes(ISARET)) return podfile;
  const blok = [
    `  ${ISARET}`,
    "  installer.pods_project.targets.each do |t|",
    `    next unless ${JSON.stringify(PODLAR)}.include?(t.name)`,
    "    t.build_configurations.each do |c|",
    "      c.build_settings['SWIFT_VERSION'] = '5.0'",
    "      c.build_settings['SWIFT_STRICT_CONCURRENCY'] = 'minimal'",
    "    end",
    "  end",
  ].join("\n");
  const desen = /post_install do \|installer\|\n/;
  if (!desen.test(podfile)) throw new Error("swift5-uyumluluk: Podfile'da post_install bloğu bulunamadı");
  return podfile.replace(desen, (m) => `${m}${blok}\n`);
}

module.exports = function swift5Uyumluluk(config) {
  return withDangerousMod(config, [
    "ios",
    (cfg) => {
      const yol = path.join(cfg.modRequest.platformProjectRoot, "Podfile");
      fs.writeFileSync(yol, ekle(fs.readFileSync(yol, "utf8")));
      return cfg;
    },
  ]);
};

module.exports.ekle = ekle;

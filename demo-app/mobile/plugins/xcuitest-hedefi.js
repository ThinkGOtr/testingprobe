// Expo yapılandırma eklentisi: XCUITest UI test hedefi (TASARIM §3.4, Ş4 — demo için tek seferlik
// "pbxproj hedef eklemesi").
//
// Neden eklenti: demo uygulamasının `ios/` dizini depoda yok; `expo prebuild --clean` her derlemede
// yeniden üretir (scripts/derle-ios.sh). Bu yüzden müşteri projesinde Xcode'da BİR KEZ elle yapılan
// "UI Testing Bundle hedefi ekle (eşitlenmiş klasörle)" adımı burada prebuild'e bağlanır:
//
//   - `BayiSiparisUITests` hedefi (com.apple.product-type.bundle.ui-testing, TEST_TARGET_NAME =
//     uygulama hedefi) eklenir;
//   - kaynakları Xcode 16+ EŞİTLENMİŞ KLASÖR (PBXFileSystemSynchronizedRootGroup) olarak
//     `../ios-test/BayiSiparisUITests` dizinine bağlanır → klasöre eklenen her `.swift` dosyası
//     (TP'nin ürettiği `TPTPUretilen/*Tests.swift` dahil) pbxproj'a DOKUNMADAN hedefe girer. TP'nin
//     müşteri deposunda yaptığı da yalnız budur: klasöre dosya ekler, pbxproj'a dokunmaz;
//   - proje biçimi `objectVersion = 77`'ye (Xcode 16 biçimi; eşitlenmiş klasörün ön koşulu) yükselir;
//   - paylaşılan şemanın Test eylemi bu hedefe çevrilir (şablondaki var olmayan `BayiSiparisTests`
//     yerine) → `xcodebuild test -scheme BayiSiparis -only-testing:BayiSiparisUITests/…`.
//
// Kimlikler sabittir (her prebuild aynı pbxproj'u üretir; idempotent: hedef varsa dokunulmaz).
const fs = require("node:fs");
const path = require("node:path");
const { withXcodeProject, withDangerousMod } = require("expo/config-plugins");

const HEDEF = "BayiSiparisUITests";
const KAYNAK_DIZINI = `../ios-test/${HEDEF}`; // ios/ köküne göre
const NESNE_SURUMU = 77;
// 24 onaltılık; Xcode/CocoaPods kimlikleriyle çakışmaması için sabit "7E57" öneki.
const K = {
  hedef: "7E5700000000000000000001",
  grup: "7E5700000000000000000002",
  urun: "7E5700000000000000000003",
  kaynaklar: "7E5700000000000000000004",
  cerceveler: "7E5700000000000000000005",
  kaynakDosyalar: "7E5700000000000000000006",
  vekil: "7E5700000000000000000007",
  bagimlilik: "7E5700000000000000000008",
  ayarListesi: "7E5700000000000000000009",
  debug: "7E570000000000000000000A",
  release: "7E570000000000000000000B",
};

function bolum(objects, ad) {
  if (!objects[ad]) objects[ad] = {};
  return objects[ad];
}

function ekle(objects, isa, id, deger, yorum) {
  const b = bolum(objects, isa);
  b[id] = { isa, ...deger };
  b[`${id}_comment`] = yorum;
}

function ayarlar(uygulamaAdi, bundleId, ayar) {
  return {
    CODE_SIGN_STYLE: "Automatic",
    CURRENT_PROJECT_VERSION: "1",
    GENERATE_INFOPLIST_FILE: "YES",
    IPHONEOS_DEPLOYMENT_TARGET: "17.0",
    MARKETING_VERSION: "1.0",
    PRODUCT_BUNDLE_IDENTIFIER: `"${bundleId}.uitests"`,
    PRODUCT_NAME: '"$(TARGET_NAME)"',
    SDKROOT: "iphoneos",
    SWIFT_EMIT_LOC_STRINGS: "NO",
    SWIFT_VERSION: "5.0",
    TARGETED_DEVICE_FAMILY: "1",
    TEST_TARGET_NAME: uygulamaAdi,
    ...(ayar === "Debug" ? { SWIFT_OPTIMIZATION_LEVEL: '"-Onone"' } : {}),
  };
}

/** pbxproj nesnelerine UI test hedefini ekler (saf; birim testi `scripts/xcuitest-hedefi.test.mjs`). */
function hedefiEkle(proje, { bundleId }) {
  const objects = proje.hash.project.objects;
  const yerel = bolum(objects, "PBXNativeTarget");
  if (yerel[K.hedef]) return proje; // zaten eklenmiş
  const projeId = proje.hash.project.rootObject;
  const kok = objects.PBXProject[projeId];
  const uygulama = Object.entries(yerel).find(
    ([id, t]) => !id.endsWith("_comment") && t.productType === '"com.apple.product-type.application"',
  );
  if (!uygulama) throw new Error("xcuitest-hedefi: uygulama hedefi bulunamadı");
  const [uygulamaId, uygulamaHedefi] = uygulama;
  const uygulamaAdi = String(uygulamaHedefi.name).replace(/"/g, "");

  proje.hash.project.objectVersion = NESNE_SURUMU;

  ekle(objects, "PBXFileSystemSynchronizedRootGroup", K.grup, {
    path: `"${KAYNAK_DIZINI}"`,
    name: HEDEF,
    sourceTree: '"<group>"',
  }, HEDEF);
  ekle(objects, "PBXFileReference", K.urun, {
    explicitFileType: "wrapper.cfbundle",
    includeInIndex: 0,
    path: `${HEDEF}.xctest`,
    sourceTree: "BUILT_PRODUCTS_DIR",
  }, `${HEDEF}.xctest`);
  for (const [isa, id, yorum] of [
    ["PBXSourcesBuildPhase", K.kaynaklar, "Sources"],
    ["PBXFrameworksBuildPhase", K.cerceveler, "Frameworks"],
    ["PBXResourcesBuildPhase", K.kaynakDosyalar, "Resources"],
  ]) {
    ekle(objects, isa, id, { buildActionMask: 2147483647, files: [], runOnlyForDeploymentPostprocessing: 0 }, yorum);
  }
  ekle(objects, "PBXContainerItemProxy", K.vekil, {
    containerPortal: projeId,
    containerPortal_comment: "Project object",
    proxyType: 1,
    remoteGlobalIDString: uygulamaId,
    remoteInfo: uygulamaAdi,
  }, "PBXContainerItemProxy");
  ekle(objects, "PBXTargetDependency", K.bagimlilik, {
    target: uygulamaId,
    target_comment: uygulamaAdi,
    targetProxy: K.vekil,
    targetProxy_comment: "PBXContainerItemProxy",
  }, "PBXTargetDependency");
  ekle(objects, "XCBuildConfiguration", K.debug, { buildSettings: ayarlar(uygulamaAdi, bundleId, "Debug"), name: "Debug" }, "Debug");
  ekle(objects, "XCBuildConfiguration", K.release, { buildSettings: ayarlar(uygulamaAdi, bundleId, "Release"), name: "Release" }, "Release");
  ekle(objects, "XCConfigurationList", K.ayarListesi, {
    buildConfigurations: [
      { value: K.debug, comment: "Debug" },
      { value: K.release, comment: "Release" },
    ],
    defaultConfigurationIsVisible: 0,
    defaultConfigurationName: "Release",
  }, `Build configuration list for PBXNativeTarget "${HEDEF}"`);
  ekle(objects, "PBXNativeTarget", K.hedef, {
    buildConfigurationList: K.ayarListesi,
    buildConfigurationList_comment: `Build configuration list for PBXNativeTarget "${HEDEF}"`,
    buildPhases: [
      { value: K.kaynaklar, comment: "Sources" },
      { value: K.cerceveler, comment: "Frameworks" },
      { value: K.kaynakDosyalar, comment: "Resources" },
    ],
    buildRules: [],
    dependencies: [{ value: K.bagimlilik, comment: "PBXTargetDependency" }],
    fileSystemSynchronizedGroups: [{ value: K.grup, comment: HEDEF }],
    name: HEDEF,
    productName: HEDEF,
    productReference: K.urun,
    productReference_comment: `${HEDEF}.xctest`,
    productType: '"com.apple.product-type.bundle.ui-testing"',
  }, HEDEF);

  kok.targets.push({ value: K.hedef, comment: HEDEF });
  const nit = (kok.attributes.TargetAttributes = kok.attributes.TargetAttributes || {});
  nit[K.hedef] = { CreatedOnToolsVersion: "16.0", TestTargetID: uygulamaId };

  const gruplar = objects.PBXGroup;
  gruplar[kok.mainGroup].children.push({ value: K.grup, comment: HEDEF });
  const urunler = gruplar[kok.productRefGroup];
  if (urunler) urunler.children.push({ value: K.urun, comment: `${HEDEF}.xctest` });
  return proje;
}

const TEST_EYLEMI = (projeAdi) => `<Testables>
         <TestableReference
            skipped = "NO"
            parallelizable = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "${K.hedef}"
               BuildableName = "${HEDEF}.xctest"
               BlueprintName = "${HEDEF}"
               ReferencedContainer = "container:${projeAdi}.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>`;

/** Paylaşılan şemanın Test eylemini UI test hedefine çevirir (saf). */
function semayiGuncelle(xml, projeAdi) {
  if (!/<Testables>[\s\S]*?<\/Testables>/.test(xml)) {
    throw new Error("xcuitest-hedefi: şemada <Testables> yok");
  }
  return xml.replace(/<Testables>[\s\S]*?<\/Testables>/, TEST_EYLEMI(projeAdi));
}

function withXcuitestHedefi(config) {
  config = withXcodeProject(config, (cfg) => {
    hedefiEkle(cfg.modResults, { bundleId: cfg.ios?.bundleIdentifier || "com.example.app" });
    return cfg;
  });
  return withDangerousMod(config, [
    "ios",
    async (cfg) => {
      const kok = cfg.modRequest.platformProjectRoot;
      const proje = fs.readdirSync(kok).find((f) => f.endsWith(".xcodeproj"));
      if (!proje) throw new Error("xcuitest-hedefi: .xcodeproj bulunamadı");
      const projeAdi = proje.replace(/\.xcodeproj$/, "");
      const sema = path.join(kok, proje, "xcshareddata", "xcschemes", `${projeAdi}.xcscheme`);
      fs.writeFileSync(sema, semayiGuncelle(fs.readFileSync(sema, "utf8"), projeAdi));
      return cfg;
    },
  ]);
}

module.exports = withXcuitestHedefi;
module.exports.hedefiEkle = hedefiEkle;
module.exports.semayiGuncelle = semayiGuncelle;
module.exports.HEDEF = HEDEF;
module.exports.KIMLIKLER = K;

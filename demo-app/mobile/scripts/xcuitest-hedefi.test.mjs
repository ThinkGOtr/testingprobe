// plugins/xcuitest-hedefi.js birim testi (node --test scripts/xcuitest-hedefi.test.mjs).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const eklenti = require("../plugins/xcuitest-hedefi.js");

function sahteProje() {
  return {
    hash: {
      project: {
        objectVersion: 54,
        rootObject: "KOK",
        objects: {
          PBXProject: {
            KOK: { targets: [{ value: "APP", comment: "BayiSiparis" }], attributes: {}, mainGroup: "ANA", productRefGroup: "URUN" },
          },
          PBXNativeTarget: {
            APP: { name: "BayiSiparis", productType: '"com.apple.product-type.application"' },
            APP_comment: "BayiSiparis",
          },
          PBXGroup: { ANA: { children: [] }, URUN: { children: [] } },
        },
      },
    },
  };
}

test("UI test hedefi eşitlenmiş klasörle eklenir ve idempotenttir", () => {
  const p = eklenti.hedefiEkle(sahteProje(), { bundleId: "com.antreklabs.bayisiparis" });
  const o = p.hash.project.objects;
  const K = eklenti.KIMLIKLER;
  assert.equal(p.hash.project.objectVersion, 77);
  assert.equal(o.PBXFileSystemSynchronizedRootGroup[K.grup].path, '"../ios-test/BayiSiparisUITests"');
  const hedef = o.PBXNativeTarget[K.hedef];
  assert.equal(hedef.productType, '"com.apple.product-type.bundle.ui-testing"');
  assert.deepEqual(hedef.fileSystemSynchronizedGroups.map((g) => g.value), [K.grup]);
  assert.equal(o.XCBuildConfiguration[K.debug].buildSettings.TEST_TARGET_NAME, "BayiSiparis");
  assert.equal(o.PBXContainerItemProxy[K.vekil].remoteGlobalIDString, "APP");
  assert.equal(o.PBXProject.KOK.targets.length, 2);
  eklenti.hedefiEkle(p, { bundleId: "x" });
  assert.equal(o.PBXProject.KOK.targets.length, 2);
  assert.equal(o.PBXGroup.ANA.children.length, 1);
});

test("şemanın Test eylemi UI test hedefine çevrilir", () => {
  const xml = '<TestAction>\n      <Testables>\n         <X/>\n      </Testables>\n   </TestAction>';
  const yeni = eklenti.semayiGuncelle(xml, "BayiSiparis");
  assert.match(yeni, /BlueprintName = "BayiSiparisUITests"/);
  assert.match(yeni, /container:BayiSiparis\.xcodeproj/);
  assert.throws(() => eklenti.semayiGuncelle("<Scheme/>", "BayiSiparis"));
});

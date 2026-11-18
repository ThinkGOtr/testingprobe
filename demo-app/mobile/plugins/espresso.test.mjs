// plugins/espresso.js birim testi (Ş3): `node --test demo-app/mobile/plugins/espresso.test.mjs`.
// Gerçek prebuild + Gradle derlemesi ayrıca doğrulanır (mobil-android-kotlin.yml).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { espressoBlogunuUygula, ESPRESSO_SURUMLERI } = require("./espresso.js");

const GRADLE = `apply plugin: "com.android.application"
apply plugin: "org.jetbrains.kotlin.android"

android {
    namespace "com.antreklabs.bayisiparis"
}
`;

test("blok eklenir: kaynak kökü, runner, orchestrator, küçültülmemiş tpTest varyantı, bağımlılıklar", () => {
  const out = espressoBlogunuUygula(GRADLE);
  assert.ok(out.startsWith(GRADLE.trimEnd()));
  assert.match(out, /androidTest\.java\.srcDirs \+= "\.\.\/\.\.\/android-test\/java"/);
  assert.match(out, /testInstrumentationRunner "androidx\.test\.runner\.AndroidJUnitRunner"/);
  assert.match(out, /clearPackageData: "true"/);
  assert.match(out, /useTestStorageService: "true"/);
  assert.match(out, /execution "ANDROIDX_TEST_ORCHESTRATOR"/);
  assert.match(out, /testBuildType "tpTest"/);
  assert.match(out, /tpTest \{\s+initWith release\s+minifyEnabled false\s+shrinkResources false\s+matchingFallbacks = \["release"\]/);
  for (const [ad, surum] of Object.entries(ESPRESSO_SURUMLERI)) {
    assert.ok(out.includes(`androidTestImplementation("${ad}:${surum}")`), ad);
    assert.match(surum, /^\d+\.\d+\.\d+$/);
  }
  assert.match(out, /androidTestUtil\("androidx\.test:orchestrator:\d+\.\d+\.\d+"\)/);
});

test("idempotent: ikinci uygulama bloğu çoğaltmaz", () => {
  const bir = espressoBlogunuUygula(GRADLE);
  const iki = espressoBlogunuUygula(bir);
  assert.equal(iki, bir);
  assert.equal(iki.split("@tp-espresso başlangıç").length, 2);
});

test("uygulama modülü değilse ve bitiş işareti silinmişse hata", () => {
  assert.throws(() => espressoBlogunuUygula('apply plugin: "com.android.library"\n'), /uygulama modülü değil/);
  const bozuk = espressoBlogunuUygula(GRADLE).replace("// @tp-espresso bitiş", "");
  assert.throws(() => espressoBlogunuUygula(bozuk), /bitiş işareti yok/);
});

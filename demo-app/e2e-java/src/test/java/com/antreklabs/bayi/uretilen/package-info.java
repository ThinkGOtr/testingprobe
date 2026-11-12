/**
 * Şablondan üretilen web testleri (Java) — tek yazarı AI Testing Probe'dur (009 §2.4, §2.8; 011 §2.5).
 *
 * <p>Dosyalar {@code rules/templates/playwright_testng.java.j2} şablonundan, onaylı test case'i ve
 * tarayıcıda (Playwright MCP) doğrulanmış page object eşlemesinden render edilir (model Java
 * yazmaz). Elle düzenlenmez; değişiklik case'in yeniden onayı ve yeniden üretimle yapılır.
 *
 * <p>Dosya adı {@code <Story><Platform>C<sira>_<uuid8>Test.java}. İçerik yalnızca: başlık
 * yorumları, {@code package}, üç izinli import ({@code Bayi}, {@code TestTabani},
 * {@code org.testng.annotations.Test}), en çok bir {@code @Bayi("…")}, {@code TestTabani}'ndan
 * türeyen tek sınıf, tek parametresiz {@code void} {@code @Test} metodu
 * ({@code groups = {"uretilen", "web", "tp-case-<uuid>", …}}) ve gövdede yalnızca
 * {@code <erişimci>().<metot>(<literal>, …);} satırları ile adım yorumları. Dal, döngü, lambda,
 * {@code new}, alan, statik çağrı, ham sayfa ({@code page()}), {@code Thread.sleep} yasaktır;
 * {@code java-araclar guard} (JavaParser) denetler.
 *
 * <p>{@code TPD1WebC2_3f9b1c2eTest} biçim için altın referanstır: TypeScript altını
 * {@code core/tests/unit/features/codegen/golden/tpd-1-c2.spec.ts}'nin birebir karşılığı.
 */
package com.antreklabs.bayi.uretilen;

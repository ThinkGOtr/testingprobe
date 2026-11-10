/**
 * Şablondan üretilen testler — tek yazarı AI Testing Probe'dur (plan §2.4, §2.8).
 *
 * <p>Dosyalar {@code rules/templates/appium_testng.java.j2} şablonundan, onaylı test case'i ve
 * uygulamada doğrulanmış ekran nesnesi eşlemesinden render edilir (model Java yazmaz). Elle
 * düzenlenmez; değişiklik case'in yeniden onayı ve yeniden üretimle yapılır.
 *
 * <p>Dosya adı {@code <Story>C<sira>_<uuid8>Test.java}. İçerik yalnızca: başlık yorumları,
 * {@code package}, üç izinli import ({@code Bayi}, {@code TestTabani}, {@code org.testng.annotations.Test}),
 * en çok bir {@code @Bayi("…")}, {@code TestTabani}'ndan türeyen tek sınıf, tek parametresiz
 * {@code void} {@code @Test} metodu ({@code groups = {"uretilen", …}}) ve gövdede yalnızca
 * {@code <erişimci>().<metot>(<literal>, …);} satırları ile adım yorumları. Dal, döngü, lambda,
 * {@code new}, alan, statik çağrı, ham sürücü, {@code Thread.sleep} yasaktır;
 * {@code java-araclar guard} (JavaParser) denetler.
 *
 * <p>{@code TPD1C3_0a1b2c3dTest} biçim için altın referanstır (şablon çıktısı bununla aynı yapıda olmalı).
 */
package com.antreklabs.bayi.uretilen;

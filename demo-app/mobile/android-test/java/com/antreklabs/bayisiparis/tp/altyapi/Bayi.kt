package com.antreklabs.bayisiparis.tp.altyapi

/**
 * Test sınıfını belirli bir e2e bayisine sabitler: `@Bayi("bayi2")`.
 *
 * Web'deki `test.use({ dealerUsername: "bayi2" })` karşılığıdır: case metni bayiye özgü giriş
 * bilgisi ya da değer içeriyorsa üretilen test bu bayiyle koşar. İzinli bayiler [Bayiler.E2E];
 * doğrulama ajanının bayisi ([Bayiler.AJAN_BAYISI]) sabitlenemez.
 */
@MustBeDocumented
@java.lang.annotation.Inherited
@Retention(AnnotationRetention.RUNTIME)
@Target(AnnotationTarget.CLASS)
annotation class Bayi(val value: String)

/** Sınıftaki testler arayüzden giriş yapılmış olarak başlar (web: `signedIn` fikstürü). */
@MustBeDocumented
@java.lang.annotation.Inherited
@Retention(AnnotationRetention.RUNTIME)
@Target(AnnotationTarget.CLASS)
annotation class OturumAcik

package com.antreklabs.bayi.altyapi;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Test sınıfını belirli bir e2e bayisine sabitler: {@code @Bayi("bayi2")}.
 *
 * <p>Web'deki {@code test.use({ dealerUsername: "bayi2" })} karşılığıdır: case metni bayiye özgü
 * giriş bilgisi ya da değer içeriyorsa üretilen test bu bayiyle koşar. İzinli bayiler
 * {@link Bayiler#E2E}; doğrulama ajanının bayisi ({@link Bayiler#AJAN_BAYISI}) sabitlenemez.
 */
@Documented
@Inherited
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
public @interface Bayi {
  /** Bayi kullanıcı adı (ör. "bayi2"). */
  String value();
}

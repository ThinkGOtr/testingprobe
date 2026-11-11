package com.antreklabs.bayi.altyapi;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Her test, testin bayisiyle oturum açmış olarak başlar.
 *
 * <p>TypeScript'teki {@code signedInTest} karşılığı: bayi API ile giriş yapar, oturum çerezi sayfa
 * bağlamıyla paylaşılır (arayüzden giriş adımı yok). Yalnızca elle yazılmış referans testler
 * içindir; üretilen testler girişi case adımı olarak içerir (AST koruması bu notasyona izin vermez).
 */
@Documented
@Inherited
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
public @interface OturumAcik {}

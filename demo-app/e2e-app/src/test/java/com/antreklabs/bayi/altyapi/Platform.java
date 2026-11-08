package com.antreklabs.bayi.altyapi;

import java.util.Arrays;
import java.util.Locale;
import java.util.stream.Collectors;

/** Testin koştuğu uygulama platformu (web karşılığı Playwright projesidir, burada yoktur). */
public enum Platform {
  ANDROID("android"),
  IOS("ios"),
  WINDOWS("windows");

  private final String ad;

  Platform(String ad) {
    this.ad = ad;
  }

  /** Komut satırı / ortamdaki adı: android, ios, windows. */
  public String ad() {
    return ad;
  }

  /** {@code -Dplatform} değerini çözer; geçersizse izinli değerleri sayan bir hata verir. */
  public static Platform coz(String deger) {
    if (deger == null || deger.isBlank()) {
      throw new IllegalArgumentException(
          "platform verilmedi: -Dplatform=" + izinliler() + " (ya da PLATFORM ortam değişkeni)");
    }
    String aranan = deger.trim().toLowerCase(Locale.ROOT);
    for (Platform p : values()) {
      if (p.ad.equals(aranan)) {
        return p;
      }
    }
    throw new IllegalArgumentException("geçersiz platform '" + deger + "'; izinli: " + izinliler());
  }

  private static String izinliler() {
    return Arrays.stream(values()).map(Platform::ad).collect(Collectors.joining("|"));
  }
}

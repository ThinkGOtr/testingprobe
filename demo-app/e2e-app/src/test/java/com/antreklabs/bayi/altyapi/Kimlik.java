package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumBy;
import java.util.Locale;
import java.util.Objects;
import java.util.regex.Pattern;
import org.openqa.selenium.By;

/**
 * Erişilebilirlik kimliği → Appium seçicisi (plan §2.2). Platform farkı YALNIZCA burada.
 *
 * <p>Ekran nesneleri {@code Kimlikler} sabitleriyle {@link #bul(String)} çağırır; platform bilmez.
 *
 * <table>
 *   <caption>Varsayılan strateji</caption>
 *   <tr><th>Platform</th><th>Uygulamada</th><th>Seçici</th></tr>
 *   <tr><td>Android</td><td>RN testID → resource-id</td><td>{@code AppiumBy.id}</td></tr>
 *   <tr><td>iOS</td><td>RN testID → accessibilityIdentifier</td><td>{@code AppiumBy.accessibilityId}</td></tr>
 *   <tr><td>Windows</td><td>AutomationProperties.AutomationId</td><td>{@code AppiumBy.accessibilityId}</td></tr>
 * </table>
 *
 * <p>RN sürümü Android'de testID'yi resource-id yerine content-desc'e yazarsa strateji kod
 * değişmeden {@code -Dkimlik.android=erisilebilirlik} ile değiştirilir.
 */
public final class Kimlik {

  /** Seçici stratejisi. */
  public enum Strateji {
    /** {@code AppiumBy.id}: Android resource-id. */
    ID,
    /** {@code AppiumBy.accessibilityId}: iOS accessibilityIdentifier, Windows AutomationId, Android content-desc. */
    ERISILEBILIRLIK,
    /**
     * Yalnız Android: UiSelector ile paket önekli ya da öneksiz resource-id tam eşleşmesi
     * ({@code AppiumBy.id} sürücü sürümüne göre öneksiz kimliği bulamazsa).
     */
    UIAUTOMATOR;

    /** {@code id} | {@code erisilebilirlik} (ya da {@code accessibilityId}) | {@code uiautomator}. */
    public static Strateji coz(String deger) {
      switch (deger.trim().toLowerCase(Locale.ROOT)) {
        case "id":
          return ID;
        case "erisilebilirlik":
        case "accessibilityid":
          return ERISILEBILIRLIK;
        case "uiautomator":
          return UIAUTOMATOR;
        default:
          throw new IllegalArgumentException(
              "geçersiz kimlik stratejisi '" + deger + "'; izinli: id | erisilebilirlik | uiautomator");
      }
    }
  }

  private static volatile Platform etkinPlatform;
  private static volatile Strateji etkinStrateji;

  private Kimlik() {}

  /** Platformun varsayılan stratejisi (plan §2.2). */
  public static Strateji varsayilanStrateji(Platform platform) {
    return platform == Platform.ANDROID ? Strateji.ID : Strateji.ERISILEBILIRLIK;
  }

  /** Ayarlardaki geçersiz kılma varsa onu, yoksa varsayılanı döndürür. */
  public static Strateji strateji(Platform platform, Ayarlar ayarlar) {
    Strateji s = ayarlar.kimlikStratejisi(platform).map(Strateji::coz).orElse(varsayilanStrateji(platform));
    if (s == Strateji.UIAUTOMATOR && platform != Platform.ANDROID) {
      throw new IllegalArgumentException("uiautomator kimlik stratejisi yalnızca Android içindir");
    }
    return s;
  }

  /** Etkin strateji; {@link #kur} çağrılmadıysa hata. */
  public static Strateji etkinStrateji() {
    platform();
    return etkinStrateji;
  }

  /** Android UiSelector ifadesi: kimliğe uyan öğe (strateji ne olursa olsun aynı öğeyi seçer). */
  public static String uiSelector(Strateji strateji, String id) {
    if (strateji == Strateji.ERISILEBILIRLIK) {
      return "new UiSelector().description(\"" + javaDizesi(id) + "\")";
    }
    // Paket önekli (com.x:id/kimlik) ya da öneksiz (RN testID) resource-id.
    return "new UiSelector().resourceIdMatches(\"" + javaDizesi("(.+:id/)?" + duzIfade(id)) + "\")";
  }

  private static final String REGEX_OZEL = ".$*+?(){}|";

  /**
   * Kimliği düzenli ifadede birebir eşleşecek biçime getirir. {@code Pattern.quote}'un
   * {@code \Q…\E}'si Appium'un UiSelector ayrıştırıcısından sağlam geçmez (emülatörde
   * {@code scrollIntoView} hiç eşleşmeyip listenin sonuna kadar kaydı — 2026-11-08). Bu yüzden ters
   * bölü kullanılmaz: özel karakter {@code [c]} sınıfına alınır. Sınıfa sığmayan karakterler
   * ({@code [ ] \ ^}) kimliklerde yoktur; olursa yine {@code Pattern.quote}'a düşülür.
   */
  static String duzIfade(String id) {
    StringBuilder b = new StringBuilder();
    for (char c : id.toCharArray()) {
      if (c == '[' || c == ']' || c == '\\' || c == '^') {
        return Pattern.quote(id);
      }
      if (REGEX_OZEL.indexOf(c) >= 0) {
        b.append('[').append(c).append(']');
      } else {
        b.append(c);
      }
    }
    return b.toString();
  }

  private static String javaDizesi(String s) {
    return s.replace("\\", "\\\\").replace("\"", "\\\"");
  }

  /** Koşunun platformunu ve stratejisini sabitler ({@code TestTabani} oturum açarken çağırır). */
  public static void kur(Platform platform, Ayarlar ayarlar) {
    etkinStrateji = strateji(platform, ayarlar);
    etkinPlatform = platform;
  }

  /** Etkin platform; {@link #kur} çağrılmadıysa hata. */
  public static Platform platform() {
    Platform p = etkinPlatform;
    if (p == null) {
      throw new IllegalStateException("Kimlik.kur(...) çağrılmadı: platform bilinmiyor");
    }
    return p;
  }

  /** Kimliğin etkin platformdaki seçicisi. */
  public static By bul(String id) {
    platform();
    return bul(etkinStrateji, id);
  }

  /** Kimliğin verilen platformdaki (varsayılan stratejiyle) seçicisi. */
  public static By bul(Platform platform, String id) {
    return bul(varsayilanStrateji(platform), id);
  }

  /** Kimliğin verilen stratejiyle seçicisi. */
  public static By bul(Strateji strateji, String id) {
    Objects.requireNonNull(id, "kimlik");
    if (id.isBlank()) {
      throw new IllegalArgumentException("boş kimlik");
    }
    switch (strateji) {
      case ID:
        return AppiumBy.id(id);
      case UIAUTOMATOR:
        return AppiumBy.androidUIAutomator(uiSelector(strateji, id));
      default:
        return AppiumBy.accessibilityId(id);
    }
  }

  /**
   * Önek kimliğe sonek ekler: {@code ekli("product-card-", "P-001") = "product-card-P-001"}.
   * Web'deki {@code testIdOf} ile aynı kurallar: önek {@code -} ile biter, sonek boş olamaz.
   */
  public static String ekli(String onek, String sonek) {
    if (!onek.endsWith("-")) {
      throw new IllegalArgumentException("'" + onek + "' önek kimlik değil ('-' ile bitmeli)");
    }
    if (sonek == null || sonek.isBlank()) {
      throw new IllegalArgumentException("'" + onek + "' önek kimliği için sonek (ürün kodu / sipariş no) gerekli");
    }
    return onek + sonek;
  }
}

package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumDriver;
import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.android.options.UiAutomator2Options;
import io.appium.java_client.ios.IOSDriver;
import io.appium.java_client.ios.options.XCUITestOptions;
import io.appium.java_client.remote.options.BaseOptions;
import io.appium.java_client.windows.options.WindowsOptions;
import java.net.MalformedURLException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;
import java.time.Duration;

/**
 * Platform → Appium seçenekleri ve sürücü (plan §1 teknik seçimler: Appium 3; uiautomator2,
 * xcuitest, novawindows).
 *
 * <p>Uygulama sıfırlama: her test YENİ bir oturum açar ({@code noReset=false}); Android'de
 * uygulama verisi oturum başında silinir, iOS'ta ve Windows'ta uygulama sıfırdan başlar. Oturum
 * bilgisi (giriş) testler arasında taşınmaz.
 */
public final class SurucuFabrikasi {

  /** NovaWindows sürücüsünün automationName değeri. */
  public static final String NOVA_WINDOWS = "NovaWindows";

  /** Appium komutları arasında oturumun kapanmadan bekleyeceği süre. */
  static final Duration KOMUT_ZAMAN_ASIMI = Duration.ofSeconds(120);

  private SurucuFabrikasi() {}

  /** Platformun Appium seçenekleri (oturum açmadan; birim testleri bunu doğrular). */
  public static BaseOptions<?> secenekler(Platform platform, Ayarlar ayarlar) {
    switch (platform) {
      case ANDROID:
        return android(ayarlar);
      case IOS:
        return ios(ayarlar);
      case WINDOWS:
        return windows(ayarlar);
      default:
        throw new IllegalArgumentException("desteklenmeyen platform: " + platform);
    }
  }

  private static UiAutomator2Options android(Ayarlar a) {
    UiAutomator2Options o = new UiAutomator2Options();
    o.setNoReset(false);
    o.setFullReset(false);
    o.setAutoGrantPermissions(true);
    o.setNewCommandTimeout(KOMUT_ZAMAN_ASIMI);
    // Animasyonlar kapalı: bekleme yardımcıları geçiş animasyonuna takılmaz.
    o.setDisableWindowAnimation(true);
    // RN testID, resource-id'ye paket öneki OLMADAN yazılır ("login-username"). UiAutomator2 `id`
    // stratejisinde varsayılan olarak "<paket>:id/" önekini ekler ve öğeyi bulamaz; kapatılır.
    o.setCapability("appium:disableIdLocatorAutocompletion", true);
    a.deviceName().ifPresent(o::setDeviceName);
    a.udid().ifPresent(o::setUdid);
    a.platformVersion().ifPresent(o::setPlatformVersion);
    if (a.appPath().isPresent()) {
      o.setApp(a.appPath().get());
      // Cihazdaki eski (aynı sürüm kodlu) APK'yı korumak yerine verilen derlemeyi her oturumda kurar.
      o.setEnforceAppInstall(true);
    } else {
      String paket = a.appId().orElseThrow(() -> eksik("android", "app.path ya da app.id (paket adı)"));
      o.setAppPackage(paket);
      a.appActivity().ifPresent(o::setAppActivity);
    }
    return o;
  }

  private static XCUITestOptions ios(Ayarlar a) {
    XCUITestOptions o = new XCUITestOptions();
    o.setNoReset(false);
    o.setFullReset(false);
    o.setNewCommandTimeout(KOMUT_ZAMAN_ASIMI);
    a.deviceName().ifPresent(o::setDeviceName);
    a.udid().ifPresent(o::setUdid);
    a.platformVersion().ifPresent(o::setPlatformVersion);
    if (a.appPath().isPresent()) {
      o.setApp(a.appPath().get());
    } else {
      o.setBundleId(a.appId().orElseThrow(() -> eksik("ios", "app.path ya da app.id (bundle id)")));
    }
    return o;
  }

  private static WindowsOptions windows(Ayarlar a) {
    WindowsOptions o = new WindowsOptions();
    o.setAutomationName(NOVA_WINDOWS);
    o.setNewCommandTimeout(KOMUT_ZAMAN_ASIMI);
    String uygulama = a.appPath().or(a::appId).orElseThrow(() -> eksik("windows", "app.path (exe) ya da app.id (AUMID)"));
    o.setApp(powershellGuvenli("app.path/app.id", uygulama));
    a.appArgs().map(v -> powershellGuvenli("app.args", v)).ifPresent(o::setAppArguments);
    a.appWorkdir().map(v -> powershellGuvenli("app.workdir", v)).ifPresent(o::setAppWorkingDir);
    return o;
  }

  /**
   * NovaWindows 1.5.0 {@code app} ve {@code appArguments} değerlerini PowerShell'de tek tırnak içine
   * kaçışsız gömer ({@code Start-Process '<app>' -ArgumentList '<args>'}); tek tırnak (PowerShell'in
   * akıllı tırnakları dahil) ya da denetim karakteri VM'de keyfi komuta dönüşür, reddedilir.
   * app-mcp {@code yapilandirma.ts} aynı kuralı uygular.
   */
  static String powershellGuvenli(String ad, String deger) {
    if (deger.matches("(?s).*['‘’‚‛\\p{Cntrl}].*")) {
      throw new IllegalArgumentException(
          ad + " tek tırnak ya da denetim karakteri içeremez (NovaWindows PowerShell'e kaçışsız geçirir)");
    }
    return deger;
  }

  private static IllegalArgumentException eksik(String platform, String ne) {
    return new IllegalArgumentException(platform + " için " + ne + " gerekir (-D ya da ortam; bkz. README)");
  }

  /** Yeni Appium oturumu açar; örtük bekleme kapalıdır (yalnızca açık beklemeler, bkz. {@link Bekle}). */
  public static AppiumDriver olustur(Platform platform, Ayarlar ayarlar) {
    BaseOptions<?> secenek = secenekler(platform, ayarlar);
    URL adres = adres(ayarlar.appiumUrl());
    AppiumDriver surucu;
    switch (platform) {
      case ANDROID:
        surucu = new AndroidDriver(adres, secenek);
        break;
      case IOS:
        surucu = new IOSDriver(adres, secenek);
        break;
      default:
        surucu = new AppiumDriver(adres, secenek);
        break;
    }
    surucu.manage().timeouts().implicitlyWait(Duration.ZERO);
    return surucu;
  }

  static URL adres(String url) {
    try {
      return new URI(url).toURL();
    } catch (URISyntaxException | MalformedURLException | IllegalArgumentException e) {
      throw new IllegalArgumentException("geçersiz appium.url '" + url + "'", e);
    }
  }
}

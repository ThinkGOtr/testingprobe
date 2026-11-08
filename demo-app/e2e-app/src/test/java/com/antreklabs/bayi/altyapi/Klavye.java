package com.antreklabs.bayi.altyapi;

import io.appium.java_client.HasOnScreenKeyboard;
import io.appium.java_client.HidesKeyboard;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebDriverException;

/**
 * Ekran klavyesi: metin yazıldıktan sonra kapatılır, altındaki butonu (ör. "Sepete ekle",
 * "Giriş yap") örtmesin. Windows'ta ekran klavyesi yoktur.
 */
public final class Klavye {

  private Klavye() {}

  /** Klavye açıksa kapatır; kapatılamazsa sessizce geçer (sonraki dokunma kendi beklemesini yapar). */
  public static void kapat(WebDriver surucu) {
    if (!(surucu instanceof HidesKeyboard)) {
      return;
    }
    try {
      if (surucu instanceof HasOnScreenKeyboard && !((HasOnScreenKeyboard) surucu).isKeyboardShown()) {
        return;
      }
      ((HidesKeyboard) surucu).hideKeyboard();
    } catch (WebDriverException e) {
      // iOS'ta klavyede kapatma tuşu yoksa hideKeyboard başarısız olabilir
    }
  }
}

package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumDriver;
import org.openqa.selenium.By;

/** Ekran nesnelerinin tabanı. */
public abstract class Ekran {
  protected final AppiumDriver surucu;

  protected Ekran(AppiumDriver surucu) {
    this.surucu = surucu;
  }

  protected void dokun(By by) {}

  protected void yaz(By by, String metin) {}

  protected void metinDogrula(By by, String beklenen) {}
}

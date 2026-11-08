package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumBy;
import org.openqa.selenium.By;

/** Platforma göre kimlik → By (009 §2.2). */
public final class Kimlik {
  private Kimlik() {}

  public static By bul(String id) {
    return AppiumBy.accessibilityId(id);
  }
}

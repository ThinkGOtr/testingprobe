package com.antreklabs.bayi.altyapi;

import com.antreklabs.bayi.ekranlar.GirisEkrani;
import com.antreklabs.bayi.ekranlar.KatalogEkrani;
import com.antreklabs.bayi.ekranlar.SepetEkrani;
import io.appium.java_client.AppiumDriver;

/** Testlerin tabanı: sürücü yaşam döngüsü ve ekran erişimcileri. */
public abstract class TestTabani {
  protected AppiumDriver driver;

  protected GirisEkrani girisEkrani() {
    return new GirisEkrani(driver);
  }

  protected KatalogEkrani katalogEkrani() {
    return new KatalogEkrani(driver);
  }

  protected SepetEkrani sepetEkrani() {
    return new SepetEkrani(driver);
  }

  /** Ekran erişimcisi değil (adı sınıfla uyuşmuyor). */
  protected SepetEkrani sepet() {
    return new SepetEkrani(driver);
  }

  protected AppiumDriver driver() {
    return driver;
  }
}

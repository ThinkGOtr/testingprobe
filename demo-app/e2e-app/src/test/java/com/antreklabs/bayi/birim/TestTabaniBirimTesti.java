package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.ITestResult;
import org.testng.TestListenerAdapter;
import org.testng.TestNG;
import org.testng.annotations.Test;

/**
 * Hazırlık hatası testin kendi hatası olur (ayrı yapılandırma kaydı yok) ve test gövdesi koşmaz.
 * Cihaz gerekmez: hata Appium oturumundan önce (bayi çözümünde) oluşur.
 */
public class TestTabaniBirimTesti {

  /** Doğrulama ajanının bayisine sabitlenmiş (yasak) örnek test. */
  @Bayi("bayi3")
  public static class AjanBayisineSabit extends TestTabani {
    static boolean govdeKostu;

    @Test
    public void senaryo() {
      govdeKostu = true;
    }
  }

  @Test(groups = "birim")
  public void hazirlikHatasiTestinHatasidir() {
    String onceki = System.getProperty("platform");
    System.setProperty("platform", "android");
    try {
      TestNG testng = new TestNG(false);
      testng.setUseDefaultListeners(false);
      // İç koşunun sahte testi birim Allure sonuçlarına sızmasın (service loader ile yüklenen dinleyici).
      testng.setListenersToSkipFromBeingWiredInViaServiceLoaders("io.qameta.allure.testng.AllureTestNg");
      testng.setVerbose(0);
      testng.setTestClasses(new Class<?>[] {AjanBayisineSabit.class});
      TestListenerAdapter dinleyici = new TestListenerAdapter();
      testng.addListener(dinleyici);
      AjanBayisineSabit.govdeKostu = false;
      testng.run();

      assertEquals(dinleyici.getConfigurationFailures().size(), 0, "yapılandırma hatası kaydı olmamalı");
      assertEquals(dinleyici.getFailedTests().size(), 1);
      ITestResult r = dinleyici.getFailedTests().get(0);
      assertEquals(r.getMethod().getMethodName(), "senaryo");
      assertTrue(r.getThrowable() instanceof IllegalArgumentException, String.valueOf(r.getThrowable()));
      assertTrue(r.getThrowable().getMessage().contains("doğrulama ajanına ayrılmıştır"));
      assertTrue(!AjanBayisineSabit.govdeKostu, "hazırlık başarısızken test gövdesi koşmamalı");
    } finally {
      if (onceki == null) {
        System.clearProperty("platform");
      } else {
        System.setProperty("platform", onceki);
      }
    }
  }
}

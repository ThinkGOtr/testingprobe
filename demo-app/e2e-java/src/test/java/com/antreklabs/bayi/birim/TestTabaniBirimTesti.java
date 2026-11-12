package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertThrows;
import static org.testng.Assert.expectThrows;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.Bayiler;
import com.antreklabs.bayi.altyapi.TestTabani;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.testng.ITestResult;
import org.testng.TestListenerAdapter;
import org.testng.TestNG;
import org.testng.annotations.Test;

/**
 * Hazırlık hatası testin kendi hatasıdır (yapılandırma satırı olmaz); işçi yuvası semaforu —
 * tarayıcı gerekmez.
 */
public class TestTabaniBirimTesti {

  /** Doğrulama ajanının bayisine sabitlenmiş sınıf: hazırlık, tarayıcı açılmadan reddeder. */
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
    String onceki = System.getProperty("tp.e2e.no.reset");
    System.setProperty("tp.e2e.no.reset", "1");
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
        System.clearProperty("tp.e2e.no.reset");
      } else {
        System.setProperty("tp.e2e.no.reset", onceki);
      }
    }
  }

  @Test(groups = "birim")
  public void yuvaYoksaBirBosalanaDekBeklenir() throws Exception {
    List<Integer> alinan = new ArrayList<>();
    try {
      for (int i = 0; i < Bayiler.E2E.size(); i++) {
        alinan.add(TestTabani.yuvaAl(Duration.ZERO));
      }
      // Tüm yuvalar dolu: süre dolunca açıklayıcı hata (eskiden beklemeden hata).
      IllegalStateException e = expectThrows(IllegalStateException.class, () -> TestTabani.yuvaAl(Duration.ofMillis(50)));
      assertTrue(e.getMessage().contains("thread-count"), e.getMessage());

      // Bekleyen test, bir yuva boşalınca onu alır.
      CompletableFuture<Integer> bekleyen = CompletableFuture.supplyAsync(() -> TestTabani.yuvaAl(Duration.ofSeconds(10)));
      Thread.sleep(100);
      assertFalse(bekleyen.isDone(), "yuva boşalmadan almamalı");
      int birakilan = alinan.remove(0);
      TestTabani.yuvaBirak(birakilan);
      assertEquals((int) bekleyen.get(5, TimeUnit.SECONDS), birakilan);
      alinan.add(birakilan);
      TestTabani.yuvaBirak(-1); // alınmamış yuva: etkisiz
    } finally {
      for (int y : alinan) {
        TestTabani.yuvaBirak(y);
      }
    }
    // Hepsi geri bırakıldı: yeniden alınabilir; aynı yuvayı iki kez bırakmak sayacı şişirmez.
    int y = TestTabani.yuvaAl(Duration.ZERO);
    TestTabani.yuvaBirak(y);
    TestTabani.yuvaBirak(y);
    List<Integer> tekrar = new ArrayList<>();
    try {
      for (int i = 0; i < Bayiler.E2E.size(); i++) {
        tekrar.add(TestTabani.yuvaAl(Duration.ZERO));
      }
      assertThrows(IllegalStateException.class, () -> TestTabani.yuvaAl(Duration.ZERO));
    } finally {
      for (int t : tekrar) {
        TestTabani.yuvaBirak(t);
      }
    }
  }
}

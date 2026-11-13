package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertThrows;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Ayarlar;
import com.antreklabs.bayi.altyapi.TestVerisi;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import org.testng.annotations.Test;

/** Ayar önceliği ve yalıtım kipi — tarayıcı gerekmez. */
public class AyarlarBirimTesti {

  @Test(groups = "birim")
  public void ozellikOrtamVarsayilanOnceligi() {
    Ayarlar bos = Ayarlar.haritadan(Map.of(), Map.of());
    assertEquals(bos.baseUrl(), "http://127.0.0.1:8081");
    assertEquals(bos.demoApiUrl(), "http://127.0.0.1:8081/api", "API verilmezse web vekili");
    assertEquals(bos.bekleme(), Duration.ofSeconds(5));
    assertEquals(bos.gezinme(), Duration.ofSeconds(10));
    assertEquals(bos.testToken(), Optional.empty());
    assertTrue(bos.headless(), "varsayılan penceresiz");
    assertFalse(bos.kampanyaKirik());

    Ayarlar ortam =
        Ayarlar.haritadan(
            Map.of(), Map.of("BASE_URL", "http://web:8080/", "API_URL", "http://api:8000/", "BREAK_CAMPAIGN", "1", "HEADLESS", "false"));
    assertEquals(ortam.baseUrl(), "http://web:8080");
    assertEquals(ortam.demoApiUrl(), "http://api:8000", "API_URL kabul edilir");
    assertTrue(ortam.kampanyaKirik());
    assertFalse(ortam.headless());

    Ayarlar ikisi =
        Ayarlar.haritadan(Map.of(), Map.of("DEMO_API_URL", "http://demo-api:8000", "API_URL", "http://api:8000"));
    assertEquals(ikisi.demoApiUrl(), "http://demo-api:8000", "DEMO_API_URL (TS adı) önceliklidir");

    Ayarlar ozellik = Ayarlar.haritadan(Map.of("base.url", "http://a:1"), Map.of("BASE_URL", "http://b:2"));
    assertEquals(ozellik.baseUrl(), "http://a:1", "sistem özelliği ortamı ezer");
    assertThrows(IllegalArgumentException.class, () -> Ayarlar.haritadan(Map.of("bekleme.ms", "x"), Map.of()).bekleme());
  }

  @Test(groups = "birim")
  public void yalitimKipi() {
    assertEquals(TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of("DEMOAPP_TEST_TOKEN", "t"))), TestVerisi.Kip.SIFIRLAMA);
    assertEquals(TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of("TP_E2E_NO_RESET", "1"))), TestVerisi.Kip.YALNIZ_SEPET);
    assertTrue(
        org.testng.Assert.expectThrows(
                IllegalStateException.class,
                () -> TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of("BREAK_CAMPAIGN", "1", "TP_E2E_NO_RESET", "1"))))
            .getMessage()
            .contains("BREAK_CAMPAIGN=1 için DEMOAPP_TEST_TOKEN gerekir"));
    assertThrows(IllegalStateException.class, () -> TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of())));
  }
}

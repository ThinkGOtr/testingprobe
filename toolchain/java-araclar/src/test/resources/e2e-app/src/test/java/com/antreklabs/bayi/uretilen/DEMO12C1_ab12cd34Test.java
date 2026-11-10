// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case üzerinden yapılır.
// Case: Kampanyalı ürün sepete eklenir · Story: DEMO-12 · Jira Test: DEMO-34
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi2")
public class DEMO12C1_ab12cd34Test extends TestTabani {
  @Test(groups = {"uretilen", "kampanya"}, description = "Kampanyalı ürün sepete eklenir")
  public void senaryo() {
    // Adım 1: Giriş yap
    girisEkrani().girisYap("bayi2", "Demo123!");
    // Adım 2: Ürünü sepete ekle
    katalogEkrani().sepeteEkle("P-001", 7);
    katalogEkrani().urunAc(12345678901L);
    katalogEkrani().urunAc(5);
    katalogEkrani().dogrulaIndirim(-12.5, true);
    katalogEkrani().dogrulaIndirim(10, false);
    // Beklenen sonuç (değerler onaylı case metninden)
    sepetEkrani().dogrulaToplam("1.250,00 TL");
    sepetEkrani().dogrulaAdet(-1);
  }
}

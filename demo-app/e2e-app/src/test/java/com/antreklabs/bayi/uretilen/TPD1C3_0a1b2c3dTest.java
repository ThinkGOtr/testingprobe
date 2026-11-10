// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C3 (0a1b2c3d-0000-4000-8000-000000000003) · Story: TPD-1 · Jira Test: TPD-T3
// Onaylı case hash: ornek-referans-dosyasi
// Eşleme: verify_and_map_app · mod: ornek · bundle: ornek
// Eşleme hash: ornek · şablon: ornek
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi2")
public class TPD1C3_0a1b2c3dTest extends TestTabani {
  @Test(groups = {"uretilen", "kampanya"}, description = "7 adet P-001 alan bayiye 1 adet bedava verilir")
  public void senaryo() {
    // bayi2 / Demo123! ile giriş yapılır
    girisEkrani().girisYap("bayi2", "Demo123!");
    // Katalogda P-001 ürününden 7 adet sepete eklenir
    katalogEkrani().sepeteEkle("P-001", 7);
    // Sepet açılır
    katalogEkrani().sepetiAc();
    // Beklenen sonuç (değerler onaylı case metninden)
    sepetEkrani().dogrulaBedavaAdet("P-001", 1);
    sepetEkrani().dogrulaIndirim("25,00 TL");
    sepetEkrani().dogrulaToplam("150,00 TL");
  }
}

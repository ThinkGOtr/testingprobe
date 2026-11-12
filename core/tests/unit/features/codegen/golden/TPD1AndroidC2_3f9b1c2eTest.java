// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map_app · platform: android · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 46175a46bd07b3e2b3e31ca480890fd9846f06f5c3276a5a93846e227326987b · şablon: 3c72755b5b39a2dbe08ba773cdf752e587d1e95f96adc48fb634ececb834ec65
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi1")
public class TPD1AndroidC2_3f9b1c2eTest extends TestTabani {
  @Test(groups = {"uretilen", "android", "tp-case-3f9b1c2e-0000-5000-8000-0000000000c2", "TPD-1"}, description = "7 adet kampanyalı üründe 1 adet bedava verilir")
  public void senaryo() {
    // S1 — Giriş sayfasını aç
    girisEkrani().ac();
    // S2 — Bayi kullanıcısıyla giriş yap
    girisEkrani().girisYap("bayi1", "Demo123!");
    // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
    katalogEkrani().sepeteEkle("P-001", 7);
    // S4 — Üst menüden sepete git
    katalogEkrani().sepetiAc();
    // Beklenen sonuç (değerler onaylı case metninden)
    sepetEkrani().dogrulaSatirAdedi("P-001", 7);
    sepetEkrani().dogrulaBedavaAdet("P-001", 1);
    sepetEkrani().dogrulaAraToplam("175,00 TL");
    sepetEkrani().dogrulaIndirim("25,00 TL");
    sepetEkrani().dogrulaToplam("150,00 TL");
  }
}

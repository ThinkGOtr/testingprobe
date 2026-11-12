// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: 945c89ca5f30204174eb8922157a74aa16ea6d05258f1a073abb49005814dffd
// Eşleme: verify_and_map · platform: web · dil: java · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 4b3b68b7674af3882857ddb5feb392d744db588ce7fa4950d1bf85c536e80a0e · şablon: 5f2e3c8c1f5cd881b55072e014251629eeb61260e5d7ec6c6b4221463ffd3f34
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi1")
public class TPD1WebC2_3f9b1c2eTest extends TestTabani {
  @Test(groups = {"uretilen", "web", "tp-case-3f9b1c2e-0000-5000-8000-0000000000c2", "TPD-1"}, description = "7 adet kampanyalı üründe 1 adet bedava verilir")
  public void senaryo() {
    // S1 — Giriş sayfasını aç
    loginPage().goTo();
    // S2 — Bayi kullanıcısıyla giriş yap
    loginPage().login("bayi1", "Demo123!");
    // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
    catalogPage().addToCart("P-001", 7);
    // S4 — Üst menüden sepete git
    catalogPage().openCart();
    // Beklenen sonuç (değerler onaylı case metninden)
    cartPage().expectLineQuantity("P-001", 7);
    cartPage().expectFreeQuantity("P-001", 1);
    cartPage().expectSubtotal("175,00 TL");
    cartPage().expectDiscount("25,00 TL");
    cartPage().expectTotal("150,00 TL");
  }
}

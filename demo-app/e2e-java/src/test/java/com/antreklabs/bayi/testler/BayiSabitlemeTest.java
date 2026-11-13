package com.antreklabs.bayi.testler;

import static org.testng.Assert.assertEquals;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/**
 * Bayiye (bayi2) sabitlenmiş test — TypeScript: tests/dealers.spec.ts "Bayiye sabitlenmiş test (bayi2)".
 * Üretilen testler case metnindeki bayiye bu yolla ({@code @Bayi}) sabitlenir.
 */
@Bayi("bayi2")
public class BayiSabitlemeTest extends TestTabani {

  @Test(groups = {"duman"}, description = "case metnindeki bayi (bayi2) ile arayüzden giriş yapılır")
  public void bayi2IleGiris() {
    assertEquals(dealer().kullaniciAdi(), "bayi2");
    loginPage().goTo();
    loginPage().login("bayi2", "Demo123!");
    loginPage().expectLoggedIn("Sahil Bayi");
    catalogPage().expectCartCount(0);
  }
}

package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.OturumAcik;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/** Çıkış (TPD-4) — TypeScript: tests/login.spec.ts {@code signedInTest} "çıkış yapınca…". */
@OturumAcik
public class CikisTest extends TestTabani {

  @Test(groups = {"duman"}, description = "çıkış yapınca giriş sayfasına dönülür")
  public void cikisYapinca() {
    catalogPage().goTo();
    loginPage().logout();
    loginPage().expectOnLoginPage();
  }
}

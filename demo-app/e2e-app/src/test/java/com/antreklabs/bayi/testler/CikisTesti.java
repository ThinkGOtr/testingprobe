package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.OturumAcik;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/** Çıkış (TPD-4) — web: tests/login.spec.ts "çıkış yapınca giriş sayfasına dönülür". */
@OturumAcik
public class CikisTesti extends TestTabani {

  @Test(groups = {"duman"}, description = "çıkış yapınca giriş ekranına dönülür")
  public void cikisYapinca() {
    katalogEkrani().ac();
    girisEkrani().cikisYap();
    girisEkrani().dogrulaGirisEkraninda();
  }
}

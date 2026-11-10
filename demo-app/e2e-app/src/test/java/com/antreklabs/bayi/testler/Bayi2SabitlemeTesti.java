package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * Bayiye (bayi2) sabitlenmiş test — web: tests/dealers.spec.ts "Bayiye sabitlenmiş test (bayi2)".
 * Üretilen testler case metnindeki bayiye bu yolla ({@code @Bayi}) sabitlenir.
 */
@Bayi("bayi2")
public class Bayi2SabitlemeTesti extends TestTabani {

  @Test(groups = {"duman"}, description = "case metnindeki bayi (bayi2) ile arayüzden giriş yapılır")
  public void bayi2IleGiris() {
    Assert.assertEquals(bayi().kullaniciAdi(), "bayi2");
    girisEkrani().ac();
    girisEkrani().girisYap("bayi2", "Demo123!");
    girisEkrani().dogrulaGirisYapildi("Sahil Bayi");
    katalogEkrani().dogrulaSepetSayaci(0);
  }
}

package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.Assert;
import org.testng.annotations.Test;

/** Bayiye (bayi1) sabitlenmiş test — web: tests/dealers.spec.ts "Bayiye sabitlenmiş test (bayi1)". */
@Bayi("bayi1")
public class Bayi1SabitlemeTesti extends TestTabani {

  @Test(description = "case metnindeki bayi (bayi1) ile arayüzden giriş yapılır")
  public void bayi1IleGiris() {
    Assert.assertEquals(bayi().kullaniciAdi(), "bayi1");
    girisEkrani().ac();
    girisEkrani().girisYap("bayi1", "Demo123!");
    girisEkrani().dogrulaGirisYapildi("Merkez Bayi");
    katalogEkrani().sepeteEkle("P-002", 1);
    katalogEkrani().dogrulaSepetSayaci(1);
  }
}

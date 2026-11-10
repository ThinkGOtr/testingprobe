package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/** Elle yazılmış referans test: sembol tablosuna girmez, koruyucu denetlemez. */
public class ElleYazilmisTest extends TestTabani {
  @Test(groups = {"duman"})
  public void giris() {
    for (int i = 0; i < 2; i++) {
      girisEkrani().girisYap("bayi1", "Demo123!");
    }
  }
}

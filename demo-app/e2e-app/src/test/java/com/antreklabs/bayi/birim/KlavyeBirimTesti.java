package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertNull;

import com.antreklabs.bayi.altyapi.Kaydirma;
import com.antreklabs.bayi.altyapi.Klavye;
import org.openqa.selenium.Rectangle;
import org.testng.annotations.Test;

/** iOS klavye kapatma ve kaydırma sürüklemelerinin geometrisi — cihaz gerekmez. */
public class KlavyeBirimTesti {

  @Test(groups = "birim")
  public void klavyeninUstundenKenarBoslugundaYukariSurukler() {
    // Katalog kabı (iPhone 16, 393x852): y=130..769; sayı klavyesi y=561'de başlar.
    int[] c = Klavye.surukleme(new Rectangle(0, 130, 639, 393), 561);
    assertEquals(c, new int[] {4, 545, 505});
  }

  @Test(groups = "birim")
  public void kabinAltiKlavyedenYukaridaysaKabaGoreHesaplar() {
    int[] c = Klavye.surukleme(new Rectangle(10, 100, 300, 200), 700);
    assertEquals(c, new int[] {14, 384, 344});
  }

  @Test(groups = "birim")
  public void iosKaydirmaHedefinYonundeSurukler() {
    // Katalog kabı y=155..764 (yükseklik 609): alt nokta 155+456, üst nokta 155+213.
    Rectangle kap = new Rectangle(0, 155, 609, 393);
    assertEquals(Kaydirma.iosSurukleme(kap, new Rectangle(100, 765, 22, 261)), new int[] {4, 611, 368});
    assertEquals(Kaydirma.iosSurukleme(kap, new Rectangle(33, 600, 43, 79)), new int[] {4, 611, 368});
    assertEquals(Kaydirma.iosSurukleme(kap, new Rectangle(100, 90, 22, 261)), new int[] {4, 368, 611});
    assertNull(Kaydirma.iosSurukleme(new Rectangle(0, 155, 40, 393), new Rectangle(0, 900, 20, 20)));
  }

  @Test(groups = "birim")
  public void yerYoksaSuruklemez() {
    assertNull(Klavye.surukleme(new Rectangle(0, 520, 300, 393), 561));
    assertNull(Klavye.surukleme(new Rectangle(0, 100, 300, 8), 561));
  }
}

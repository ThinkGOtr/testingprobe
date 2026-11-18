package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertNull;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Kaydirma;
import com.antreklabs.bayi.altyapi.Klavye;
import org.openqa.selenium.Rectangle;
import org.testng.annotations.Test;

/** iOS klavye kapatma ve kaydırma sürüklemelerinin geometrisi — cihaz gerekmez. */
public class KlavyeBirimTesti {

  @Test(groups = "birim")
  public void klavyeninUstundenKenarBoslugundaYukariSurukler() {
    // Katalog kabı (iPhone 16, iOS 27, 393x852): y=155..764; sayı klavyesi öğesi y=567'de, görünen
    // cam kabı y=550'de başlar → sürükleme kabın üst bölümünde, klavyeden uzakta.
    int[] c = Klavye.surukleme(new Rectangle(0, 155, 609, 393), 567);
    assertEquals(c, new int[] {4, 251, 211});
    // Bayat çerçeve (y=764) okunsa da nokta aynı kalır: tuşlara düşmez.
    assertEquals(Klavye.surukleme(new Rectangle(0, 155, 609, 393), 764), new int[] {4, 251, 211});
  }

  @Test(groups = "birim")
  public void kabinAltiKlavyedenYukaridaysaKabaGoreHesaplar() {
    int[] c = Klavye.surukleme(new Rectangle(10, 100, 300, 200), 700);
    assertEquals(c, new int[] {14, 196, 156});
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
    assertNull(Klavye.surukleme(new Rectangle(0, 460, 300, 393), 561));
    assertNull(Klavye.surukleme(new Rectangle(0, 100, 300, 8), 561));
  }

  @Test(groups = "birim")
  public void yazilanDegerDogrulamasi() {
    assertTrue(Klavye.degerTutuyor("bayi2", "bayi2"));
    assertFalse(Klavye.degerTutuyor("ba", "bayi2"));
    assertFalse(Klavye.degerTutuyor("bayi1q", "bayi1"));
    assertTrue(Klavye.degerTutuyor("•••••", "abcde"));
    assertFalse(Klavye.degerTutuyor("••", "abcde"));
    assertTrue(Klavye.degerTutuyor("", "gizli"));
    assertTrue(Klavye.degerTutuyor(null, "gizli"));
  }
}

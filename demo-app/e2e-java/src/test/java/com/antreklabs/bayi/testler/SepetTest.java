package com.antreklabs.bayi.testler;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.antreklabs.bayi.altyapi.OturumAcik;
import com.antreklabs.bayi.altyapi.TestTabani;
import com.antreklabs.bayi.ekranlar.Kimlikler;
import com.microsoft.playwright.Locator;
import com.microsoft.playwright.options.AriaRole;
import org.testng.annotations.Test;

/**
 * Katalog ve sepet (TPD-1) — TypeScript: tests/cart.spec.ts.
 *
 * <p>6 adet sınırı bilerek doğrulanmaz (TypeScript ile aynı gerekçe: demo senaryosuna bağlıdır);
 * yalnızca iki senaryoda da doğru olan davranış (7 → 1 bedava) doğrulanır.
 */
@OturumAcik
public class SepetTest extends TestTabani {

  /** TypeScript: {@code test.beforeEach(catalogPage.goto)}. */
  @Override
  protected void hazirlikSonrasi() {
    catalogPage().goTo();
  }

  @Test(groups = {"duman"}, description = "katalog ürünleri ve fiyatları tr-TR biçiminde gösterir")
  public void katalogFiyatlari() {
    catalogPage().expectProductPrice("P-001", "25,00 TL");
    catalogPage().expectProductPrice("P-002", "15,00 TL");
    catalogPage().expectProductPrice("P-003", "8,00 TL");
    catalogPage().expectProductPrice("P-004", "30,00 TL");
    catalogPage().expectCampaign("P-001", "6 al 1 bedava");
  }

  @Test(groups = {"duman"}, description = "AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar")
  public void sepeteEkleSayaciArtirir() {
    catalogPage().expectCartCount(0);
    catalogPage().addToCart("P-002", 1);
    catalogPage().expectCartCount(1);
    catalogPage().addToCart("P-003", 2);
    catalogPage().expectCartCount(3);
  }

  @Test(groups = {"kampanya"}, description = "kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL")
  public void kampanyaYediAdet() {
    catalogPage().addToCart("P-001", 7);
    catalogPage().openCart();
    cartPage().expectLineQuantity("P-001", 7);
    cartPage().expectFreeQuantity("P-001", 1);
    cartPage().expectSubtotal("175,00 TL");
    cartPage().expectDiscount("25,00 TL");
    // İndirim varsa özet değeri eksi işaretiyle gösterilir (işaret kimliksiz ayrı metindir): indirim
    // kimliğini içeren tanım değeri (<dd>, ARIA "definition") — DOM üst düğümüne (xpath) bağlı değil.
    assertThat(
            page()
                .getByRole(AriaRole.DEFINITION)
                .filter(new Locator.FilterOptions().setHas(page().getByTestId(Kimlikler.Cart.DISCOUNT))))
        .hasText("−25,00 TL");
    cartPage().expectTotal("150,00 TL");
  }

  @Test(groups = {"kampanya"}, description = "kampanyasız üründe bedava adet verilmez")
  public void kampanyasizUrundeBedavaYok() {
    catalogPage().addToCart("P-002", 12);
    catalogPage().openCart();
    cartPage().expectFreeQuantity("P-002", 0);
    cartPage().expectDiscount("0,00 TL");
  }

  @Test(
      groups = {"kampanya"},
      description = "kampanyasız siparişte minimum tutar altında uyarı gösterilir ve onay pasif olur")
  public void kampanyasizMinimumUyarisi() {
    catalogPage().addToCart("P-002", 10);
    catalogPage().openCart();
    cartPage().expectTotal("150,00 TL");
    cartPage().expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");
    cartPage().expectCheckoutDisabled();
  }

  @Test(groups = {"kampanya"}, description = "kampanyalı siparişte minimum tutar aranmaz")
  public void kampanyalidaMinimumYok() {
    // 7 x P-001: toplam minimum tutarın (750,00 TL) çok altında; indirim tutarından bağımsız.
    catalogPage().addToCart("P-001", 7);
    catalogPage().openCart();
    cartPage().expectLineQuantity("P-001", 7);
    cartPage().expectNoMinOrderWarning();
    cartPage().expectCheckoutEnabled();
  }

  @Test(description = "minimum tutara ulaşınca uyarı kalkar ve onay aktif olur")
  public void minimumTutaraUlasinca() {
    catalogPage().addToCart("P-004", 25);
    catalogPage().openCart();
    cartPage().expectTotal("750,00 TL");
    cartPage().expectNoMinOrderWarning();
    cartPage().expectCheckoutEnabled();
  }

  @Test(description = "ürün sepetten kaldırılabilir")
  public void urunKaldirma() {
    catalogPage().addToCart("P-002", 1);
    catalogPage().addToCart("P-003", 1);
    catalogPage().openCart();
    cartPage().removeProduct("P-002");
    cartPage().expectProductNotInCart("P-002");
    cartPage().expectLineQuantity("P-003", 1);
    cartPage().removeProduct("P-003");
    cartPage().expectEmpty();
  }
}

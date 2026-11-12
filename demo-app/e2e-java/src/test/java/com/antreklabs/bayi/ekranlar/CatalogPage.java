package com.antreklabs.bayi.ekranlar;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.antreklabs.bayi.ekranlar.Kimlikler.Catalog;
import com.antreklabs.bayi.ekranlar.Kimlikler.Nav;
import com.microsoft.playwright.Locator;
import com.microsoft.playwright.Page;
import com.microsoft.playwright.Response;

/** Ürün kataloğu sayfası. */
public class CatalogPage extends Ekran {

  /** Sepete ekleme isteğinin yanıtını bekleme üst sınırı (TypeScript ile aynı: 10 sn). */
  private static final double SEPET_YANITI_MS = 10_000;

  public CatalogPage(Page page) {
    super(page);
  }

  private Locator card(String productCode) {
    return kapsam(Catalog.PRODUCT_CARD_ONEK, productCode);
  }

  /** Katalog sayfasını açar. */
  public void goTo() {
    git(CATALOG_YOLU);
    assertThat(kimlik(Catalog.PRODUCT_LIST)).isVisible();
  }

  /** Üst menüden kataloğa gider. */
  public void openFromMenu() {
    kimlik(Nav.CATALOG).click();
    dogrulaYol(CATALOG_YOLU);
  }

  /** Ürün kartındaki adet alanına değer yazar. */
  public void setQuantity(String productCode, int quantity) {
    kapsamda(card(productCode), Catalog.ProductCard.QUANTITY_INPUT_ONEK, productCode).fill(String.valueOf(quantity));
  }

  /** Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler. */
  public void addToCart(String productCode, int quantity) {
    setQuantity(productCode, quantity);
    // Yanıt beklemesi tıklamadan önce kurulur; tıklama hatası (ör. kırık locator) olduğu gibi
    // yükselir, yanıt zaman aşımı onu gölgelemez: triage tek ve doğru hatayı görür.
    Response response =
        page.waitForResponse(
            r -> r.url().endsWith("/api/cart/lines") && "POST".equals(r.request().method()),
            new Page.WaitForResponseOptions().setTimeout(SEPET_YANITI_MS),
            () -> kapsamda(card(productCode), Catalog.ProductCard.ADD_TO_CART, productCode).click());
    if (!response.ok()) {
      throw new AssertionError("sepete ekleme isteği başarısız: " + response.status());
    }
  }

  /** Üst menüden sepete gider. */
  public void openCart() {
    kimlik(Nav.CART).click();
    dogrulaYol(CART_YOLU);
  }

  /** Ürün kartının katalogda göründüğünü doğrular. */
  public void expectProductVisible(String productCode) {
    assertThat(card(productCode)).isVisible();
  }

  /** Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL"). */
  public void expectProductPrice(String productCode, String price) {
    assertThat(kimlik(Catalog.PRODUCT_PRICE_ONEK, productCode)).hasText(price);
  }

  /** Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava"). */
  public void expectCampaign(String productCode, String campaignName) {
    assertThat(card(productCode)).containsText(campaignName);
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular. */
  public void expectCartCount(int count) {
    assertThat(kimlik(Nav.CART_COUNT)).hasText(String.valueOf(count));
  }
}

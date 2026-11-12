package com.antreklabs.bayi.ekranlar;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.antreklabs.bayi.ekranlar.Kimlikler.Cart;
import com.antreklabs.bayi.ekranlar.Kimlikler.Nav;
import com.microsoft.playwright.Page;
import java.util.regex.Pattern;

/** Sepet sayfası: satırlar, kampanya, toplamlar ve sipariş onayı. */
public class CartPage extends Ekran {

  private static final Pattern ONAY_ADRESI = Pattern.compile("/siparis/[^/]+$");

  public CartPage(Page page) {
    super(page);
  }

  /** Sepet sayfasını açar. */
  public void goTo() {
    git(CART_YOLU);
    assertThat(kimlik(Cart.TABLE).or(kimlik(Cart.EMPTY))).isVisible();
  }

  /** Ürünü sepetten kaldırır. */
  public void removeProduct(String productCode) {
    kimlik(Cart.LINE_REMOVE_ONEK, productCode).click();
    assertThat(kimlik(Cart.LINE_ONEK, productCode)).hasCount(0);
  }

  /** "Siparişi onayla" butonuna basar ve onay sayfasının açılmasını bekler. */
  public void checkout() {
    kimlik(Cart.CHECKOUT_SUBMIT).click();
    assertThat(page).hasURL(ONAY_ADRESI);
  }

  /** Sepet satırındaki adedi doğrular. */
  public void expectLineQuantity(String productCode, int quantity) {
    assertThat(kimlik(Cart.LINE_QUANTITY_ONEK, productCode)).hasText(String.valueOf(quantity));
  }

  /** Sepet satırında kampanyayla bedava verilen adedi doğrular. */
  public void expectFreeQuantity(String productCode, int quantity) {
    assertThat(kimlik(Cart.LINE_FREE_ONEK, productCode)).hasText(String.valueOf(quantity));
  }

  /** Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL"). */
  public void expectLineTotal(String productCode, String amount) {
    assertThat(kimlik(Cart.LINE_TOTAL_ONEK, productCode)).hasText(amount);
  }

  /** Ara toplamı doğrular (ör. "175,00 TL"). */
  public void expectSubtotal(String amount) {
    assertThat(kimlik(Cart.SUBTOTAL)).hasText(amount);
  }

  /** Kampanya indirimi tutarını doğrular (ör. "25,00 TL"). */
  public void expectDiscount(String amount) {
    assertThat(kimlik(Cart.DISCOUNT)).hasText(amount);
  }

  /** İndirim sonrası genel toplamı doğrular (ör. "150,00 TL"). */
  public void expectTotal(String amount) {
    assertThat(kimlik(Cart.TOTAL)).hasText(amount);
  }

  /** Minimum sipariş uyarısının verilen metni içerdiğini doğrular (ör. "Minimum sipariş tutarı 750,00 TL"). */
  public void expectMinOrderWarning(String message) {
    assertThat(kimlik(Cart.MIN_ORDER_WARNING)).containsText(message);
  }

  /** Minimum sipariş uyarısının gösterilmediğini doğrular. */
  public void expectNoMinOrderWarning() {
    assertThat(kimlik(Cart.MIN_ORDER_WARNING)).hasCount(0);
  }

  /** "Siparişi onayla" butonunun pasif olduğunu doğrular. */
  public void expectCheckoutDisabled() {
    assertThat(kimlik(Cart.CHECKOUT_SUBMIT)).isDisabled();
  }

  /** "Siparişi onayla" butonunun aktif olduğunu doğrular. */
  public void expectCheckoutEnabled() {
    assertThat(kimlik(Cart.CHECKOUT_SUBMIT)).isEnabled();
  }

  /** Sepette ürünün bulunmadığını doğrular. */
  public void expectProductNotInCart(String productCode) {
    assertThat(kimlik(Cart.LINE_ONEK, productCode)).hasCount(0);
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet sayfasında). */
  public void expectCartCount(int count) {
    assertThat(kimlik(Nav.CART_COUNT)).hasText(String.valueOf(count));
  }

  /** Sepetin boş olduğunu doğrular. */
  public void expectEmpty() {
    assertThat(kimlik(Cart.EMPTY)).isVisible();
  }
}

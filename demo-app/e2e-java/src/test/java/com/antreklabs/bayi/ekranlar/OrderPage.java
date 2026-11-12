package com.antreklabs.bayi.ekranlar;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.antreklabs.bayi.ekranlar.Kimlikler.Nav;
import com.antreklabs.bayi.ekranlar.Kimlikler.Order;
import com.microsoft.playwright.Locator;
import com.microsoft.playwright.Page;
import java.util.regex.Pattern;

/** Sipariş onayı ve sipariş geçmişi. */
public class OrderPage extends Ekran {

  private static final Pattern ORDER_NUMBER = Pattern.compile("^SP-\\d{6}$");

  public OrderPage(Page page) {
    super(page);
  }

  /** Sipariş geçmişi sayfasını açar. */
  public void gotoHistory() {
    git(ORDERS_YOLU);
    assertThat(kimlik(Order.ORDERS_TABLE).or(kimlik(Order.ORDERS_EMPTY))).isVisible();
  }

  /** Üst menüden sipariş geçmişine gider. */
  public void openHistory() {
    kimlik(Nav.ORDERS).click();
    dogrulaYol(ORDERS_YOLU);
  }

  /**
   * Onay sayfasındaki sipariş numarasını okur. TypeScript'teki gibi değer döner; bu yüzden üretilen
   * testler kullanamaz (sözleşme: page object metodu {@code void} döner) — yalnız elle yazılmış testler.
   */
  public String readOrderNumber() {
    Locator el = kimlik(Order.ORDER_NUMBER);
    assertThat(el).hasText(ORDER_NUMBER);
    return el.innerText().trim();
  }

  /** Sipariş onayının ve sipariş numarasının gösterildiğini doğrular. */
  public void expectConfirmation() {
    assertThat(kimlik(Order.CONFIRMATION)).isVisible();
    assertThat(kimlik(Order.ORDER_NUMBER)).hasText(ORDER_NUMBER);
  }

  /** Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL"). */
  public void expectConfirmedTotal(String amount) {
    assertThat(kimlik(Order.ORDER_TOTAL)).hasText(amount);
  }

  /** Onay sayfasında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular. */
  public void expectConfirmedOrderInHistory() {
    String orderNumber = readOrderNumber();
    openHistory();
    expectOrderInHistory(orderNumber);
  }

  /** Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular. */
  public void expectOrderInHistory(String orderNumber) {
    assertThat(kimlik(Order.ORDER_ROW_ONEK, orderNumber)).isVisible();
  }

  /** Sipariş geçmişindeki siparişin genel toplamını doğrular. */
  public void expectOrderTotalInHistory(String orderNumber, String amount) {
    assertThat(kimlik(Order.ORDER_ROW_TOTAL_ONEK, orderNumber)).hasText(amount);
  }

  /** Sipariş geçmişinin boş olduğunu doğrular. */
  public void expectNoOrders() {
    assertThat(kimlik(Order.ORDERS_EMPTY)).isVisible();
  }
}

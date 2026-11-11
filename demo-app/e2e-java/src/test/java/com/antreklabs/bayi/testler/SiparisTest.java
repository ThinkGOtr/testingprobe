package com.antreklabs.bayi.testler;

import static org.testng.Assert.assertEquals;

import com.antreklabs.bayi.altyapi.OturumAcik;
import com.antreklabs.bayi.altyapi.TestTabani;
import com.microsoft.playwright.APIResponse;
import org.testng.annotations.Test;

/** Sipariş onayı ve geçmiş (TPD-1 AC5) — TypeScript: tests/order.spec.ts. */
@OturumAcik
public class SiparisTest extends TestTabani {

  /** Sıfırlanmış veri gerektirir; TP_E2E_NO_RESET=1 (yalnızca sepet yalıtımı) kipinde atlanır. */
  @Test(groups = {SIFIR_VERI}, description = "siparişi olmayan bayide boş geçmiş bilgisi gösterilir")
  public void bosGecmis() {
    orderPage().gotoHistory();
    orderPage().expectNoOrders();
  }

  @Test(description = "onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir")
  public void siparisOnayiVeGecmis() {
    catalogPage().goTo();
    catalogPage().addToCart("P-004", 30);
    catalogPage().addToCart("P-001", 7);
    catalogPage().openCart();
    cartPage().expectTotal("1.050,00 TL");
    cartPage().checkout();
    orderPage().expectConfirmation();
    orderPage().expectConfirmedTotal("1.050,00 TL");
    catalogPage().expectCartCount(0);
    String orderNumber = orderPage().readOrderNumber();
    orderPage().expectConfirmedOrderInHistory();
    orderPage().expectOrderTotalInHistory(orderNumber, "1.050,00 TL");
  }

  @Test(description = "minimum tutarın altındaki sepet API'de de reddedilir")
  public void minimumAltiApiReddi() {
    catalogPage().goTo();
    catalogPage().addToCart("P-003", 1);
    APIResponse resp = page().request().post("/api/orders");
    assertEquals(resp.status(), 422);
    assertEquals(resp.text().replace(" ", ""), "{\"detail\":\"Minimumsipariştutarı750,00TL\"}");
  }
}

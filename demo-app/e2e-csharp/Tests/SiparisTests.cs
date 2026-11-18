using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Sipariş onayı ve geçmiş (TPD-1 AC5) — TypeScript: tests/order.spec.ts.</summary>
[OturumAcik]
public class SiparisTests : TestTabani
{
    /// <summary>Sıfırlanmış veri gerektirir; TP_E2E_NO_RESET=1 (yalnızca sepet yalıtımı) kipinde atlanır.</summary>
    [Test]
    [Category(SifirVeri)]
    [Description("siparişi olmayan bayide boş geçmiş bilgisi gösterilir")]
    public async Task BosGecmis()
    {
        await OrderPage.GotoHistoryAsync();
        await OrderPage.ExpectNoOrdersAsync();
    }

    [Test]
    [Description("onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir")]
    public async Task SiparisOnayiVeGecmis()
    {
        await CatalogPage.GotoAsync();
        await CatalogPage.AddToCartAsync("P-004", 30);
        await CatalogPage.AddToCartAsync("P-001", 7);
        await CatalogPage.OpenCartAsync();
        await CartPage.ExpectTotalAsync("1.050,00 TL");
        await CartPage.CheckoutAsync();
        await OrderPage.ExpectConfirmationAsync();
        await OrderPage.ExpectConfirmedTotalAsync("1.050,00 TL");
        await CatalogPage.ExpectCartCountAsync(0);
        var orderNumber = await OrderPage.ReadOrderNumberAsync();
        await OrderPage.ExpectConfirmedOrderInHistoryAsync();
        await OrderPage.ExpectOrderTotalInHistoryAsync(orderNumber, "1.050,00 TL");
    }

    [Test]
    [Description("minimum tutarın altındaki sepet API'de de reddedilir")]
    public async Task MinimumAltiApiReddi()
    {
        await CatalogPage.GotoAsync();
        await CatalogPage.AddToCartAsync("P-003", 1);
        var resp = await Page.APIRequest.PostAsync("/api/orders");
        Assert.That(resp.Status, Is.EqualTo(422));
        Assert.That((await resp.TextAsync()).Replace(" ", ""), Is.EqualTo("{\"detail\":\"Minimumsipariştutarı750,00TL\"}"));
    }
}

using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Playwright;
using static Antreklabs.Bayi.Pages.Kimlikler;
using static Microsoft.Playwright.Assertions;

namespace Antreklabs.Bayi.Pages;

/// <summary>Sipariş onayı ve sipariş geçmişi.</summary>
public class OrderPage : Ekran
{
    private static readonly Regex OrderNumber = new("^SP-\\d{6}$");

    public OrderPage(IPage page)
        : base(page)
    {
    }

    /// <summary>Sipariş geçmişi sayfasını açar.</summary>
    public async Task GotoHistoryAsync()
    {
        await GitAsync(OrdersYolu);
        await DogrulaAsync(() => Expect(Kimlik(Order.ORDERS_TABLE).Or(Kimlik(Order.ORDERS_EMPTY))).ToBeVisibleAsync());
    }

    /// <summary>Üst menüden sipariş geçmişine gider.</summary>
    public async Task OpenHistoryAsync()
    {
        await Kimlik(Nav.ORDERS).ClickAsync();
        await DogrulaYolAsync(OrdersYolu);
    }

    /// <summary>
    /// Onay sayfasındaki sipariş numarasını okur. TypeScript'teki gibi değer döner; bu yüzden üretilen
    /// testler kullanamaz (sözleşme: page object metodu <c>Task</c> döner) — yalnız elle yazılmış testler.
    /// </summary>
    public async Task<string> ReadOrderNumberAsync()
    {
        var el = Kimlik(Order.ORDER_NUMBER);
        await DogrulaAsync(() => Expect(el).ToHaveTextAsync(OrderNumber));
        return (await el.InnerTextAsync()).Trim();
    }

    /// <summary>Sipariş onayının ve sipariş numarasının gösterildiğini doğrular.</summary>
    public async Task ExpectConfirmationAsync()
    {
        await DogrulaAsync(() => Expect(Kimlik(Order.CONFIRMATION)).ToBeVisibleAsync());
        await DogrulaAsync(() => Expect(Kimlik(Order.ORDER_NUMBER)).ToHaveTextAsync(OrderNumber));
    }

    /// <summary>Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL").</summary>
    public async Task ExpectConfirmedTotalAsync(string amount)
    {
        await DogrulaAsync(() => Expect(Kimlik(Order.ORDER_TOTAL)).ToHaveTextAsync(amount));
    }

    /// <summary>Onay sayfasında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular.</summary>
    public async Task ExpectConfirmedOrderInHistoryAsync()
    {
        var orderNumber = await ReadOrderNumberAsync();
        await OpenHistoryAsync();
        await ExpectOrderInHistoryAsync(orderNumber);
    }

    /// <summary>Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular.</summary>
    public async Task ExpectOrderInHistoryAsync(string orderNumber)
    {
        await DogrulaAsync(() => Expect(Kimlik(Order.ORDER_ROW_ONEK, orderNumber)).ToBeVisibleAsync());
    }

    /// <summary>Sipariş geçmişindeki siparişin genel toplamını doğrular.</summary>
    public async Task ExpectOrderTotalInHistoryAsync(string orderNumber, string amount)
    {
        await DogrulaAsync(() => Expect(Kimlik(Order.ORDER_ROW_TOTAL_ONEK, orderNumber)).ToHaveTextAsync(amount));
    }

    /// <summary>Sipariş geçmişinin boş olduğunu doğrular.</summary>
    public async Task ExpectNoOrdersAsync()
    {
        await DogrulaAsync(() => Expect(Kimlik(Order.ORDERS_EMPTY)).ToBeVisibleAsync());
    }
}

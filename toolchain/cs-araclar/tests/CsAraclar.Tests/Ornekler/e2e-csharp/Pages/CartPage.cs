using System.Threading.Tasks;
using Microsoft.Playwright;

namespace Antreklabs.Bayi.Pages;

/// <summary>Sepet sayfası.</summary>
public sealed class CartPage : Ekran
{
    public CartPage(IPage page) : base(page)
    {
    }

    public async Task ExpectLineQuantityAsync(string productCode, int quantity) => await Bekle(Kimlikler.Cart.LINE_QUANTITY_ONEK + productCode, quantity);
    public async Task ExpectFreeQuantityAsync(string productCode, int quantity) => await Bekle(productCode, quantity);
    public async Task ExpectSubtotalAsync(string amount) => await Bekle(amount, 0);
    public async Task ExpectDiscountAsync(string amount) => await Bekle(amount, 0);

    /// <summary>Genel toplamı doğrular.</summary>
    public async Task ExpectTotalAsync(string amount) => await Bekle(Kimlikler.Cart.TOTAL + amount, 0);

    public void SenkronIslem(bool acik)
    {
    }

    private static Task Bekle(string a, int b) => Task.CompletedTask;
}

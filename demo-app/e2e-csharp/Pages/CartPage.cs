using System.Globalization;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Playwright;
using static Antreklabs.Bayi.Pages.Kimlikler;
using static Microsoft.Playwright.Assertions;

namespace Antreklabs.Bayi.Pages;

/// <summary>Sepet sayfası: satırlar, kampanya, toplamlar ve sipariş onayı.</summary>
public class CartPage : Ekran
{
    private static readonly Regex OnayAdresi = new("/siparis/[^/]+$");

    public CartPage(IPage page)
        : base(page)
    {
    }

    private static string Sayi(int n) => n.ToString(CultureInfo.InvariantCulture);

    /// <summary>Sepet sayfasını açar.</summary>
    public async Task GotoAsync()
    {
        await GitAsync(CartYolu);
        await DogrulaAsync(() => Expect(Kimlik(Cart.TABLE).Or(Kimlik(Cart.EMPTY))).ToBeVisibleAsync());
    }

    /// <summary>Ürünü sepetten kaldırır.</summary>
    public async Task RemoveProductAsync(string productCode)
    {
        await Kimlik(Cart.LINE_REMOVE_ONEK, productCode).ClickAsync();
        await DogrulaAsync(() => Expect(Kimlik(Cart.LINE_ONEK, productCode)).ToHaveCountAsync(0));
    }

    /// <summary>"Siparişi onayla" butonuna basar ve onay sayfasının açılmasını bekler.</summary>
    public async Task CheckoutAsync()
    {
        await Kimlik(Cart.CHECKOUT_SUBMIT).ClickAsync();
        await DogrulaAsync(() => Expect(Page).ToHaveURLAsync(OnayAdresi));
    }

    /// <summary>Sepet satırındaki adedi doğrular.</summary>
    public async Task ExpectLineQuantityAsync(string productCode, int quantity)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.LINE_QUANTITY_ONEK, productCode)).ToHaveTextAsync(Sayi(quantity)));
    }

    /// <summary>Sepet satırında kampanyayla bedava verilen adedi doğrular.</summary>
    public async Task ExpectFreeQuantityAsync(string productCode, int quantity)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.LINE_FREE_ONEK, productCode)).ToHaveTextAsync(Sayi(quantity)));
    }

    /// <summary>Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL").</summary>
    public async Task ExpectLineTotalAsync(string productCode, string amount)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.LINE_TOTAL_ONEK, productCode)).ToHaveTextAsync(amount));
    }

    /// <summary>Ara toplamı doğrular (ör. "175,00 TL").</summary>
    public async Task ExpectSubtotalAsync(string amount)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.SUBTOTAL)).ToHaveTextAsync(amount));
    }

    /// <summary>Kampanya indirimi tutarını doğrular (ör. "25,00 TL").</summary>
    public async Task ExpectDiscountAsync(string amount)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.DISCOUNT)).ToHaveTextAsync(amount));
    }

    /// <summary>İndirim sonrası genel toplamı doğrular (ör. "150,00 TL").</summary>
    public async Task ExpectTotalAsync(string amount)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.TOTAL)).ToHaveTextAsync(amount));
    }

    /// <summary>Minimum sipariş uyarısının verilen metni içerdiğini doğrular (ör. "Minimum sipariş tutarı 750,00 TL").</summary>
    public async Task ExpectMinOrderWarningAsync(string message)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.MIN_ORDER_WARNING)).ToContainTextAsync(message));
    }

    /// <summary>Minimum sipariş uyarısının gösterilmediğini doğrular.</summary>
    public async Task ExpectNoMinOrderWarningAsync()
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.MIN_ORDER_WARNING)).ToHaveCountAsync(0));
    }

    /// <summary>"Siparişi onayla" butonunun pasif olduğunu doğrular.</summary>
    public async Task ExpectCheckoutDisabledAsync()
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.CHECKOUT_SUBMIT)).ToBeDisabledAsync());
    }

    /// <summary>"Siparişi onayla" butonunun aktif olduğunu doğrular.</summary>
    public async Task ExpectCheckoutEnabledAsync()
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.CHECKOUT_SUBMIT)).ToBeEnabledAsync());
    }

    /// <summary>Sepette ürünün bulunmadığını doğrular.</summary>
    public async Task ExpectProductNotInCartAsync(string productCode)
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.LINE_ONEK, productCode)).ToHaveCountAsync(0));
    }

    /// <summary>Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet sayfasında).</summary>
    public async Task ExpectCartCountAsync(int count)
    {
        await DogrulaAsync(() => Expect(Kimlik(Nav.CART_COUNT)).ToHaveTextAsync(Sayi(count)));
    }

    /// <summary>Sepetin boş olduğunu doğrular.</summary>
    public async Task ExpectEmptyAsync()
    {
        await DogrulaAsync(() => Expect(Kimlik(Cart.EMPTY)).ToBeVisibleAsync());
    }
}

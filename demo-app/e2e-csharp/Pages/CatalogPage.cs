using System.Globalization;
using System.Threading.Tasks;
using Microsoft.Playwright;
using static Antreklabs.Bayi.Pages.Kimlikler;
using static Microsoft.Playwright.Assertions;

namespace Antreklabs.Bayi.Pages;

/// <summary>Ürün kataloğu sayfası.</summary>
public class CatalogPage : Ekran
{
    /// <summary>Sepete ekleme isteğinin yanıtını bekleme üst sınırı (TypeScript ile aynı: 10 sn).</summary>
    private const float SepetYanitiMs = 10_000;

    public CatalogPage(IPage page)
        : base(page)
    {
    }

    private ILocator Card(string productCode) => Kapsam(Catalog.PRODUCT_CARD_ONEK, productCode);

    /// <summary>Katalog sayfasını açar.</summary>
    public async Task GotoAsync()
    {
        await GitAsync(CatalogYolu);
        await DogrulaAsync(() => Expect(Kimlik(Catalog.PRODUCT_LIST)).ToBeVisibleAsync());
    }

    /// <summary>Üst menüden kataloğa gider.</summary>
    public async Task OpenFromMenuAsync()
    {
        await Kimlik(Nav.CATALOG).ClickAsync();
        await DogrulaYolAsync(CatalogYolu);
    }

    /// <summary>Ürün kartındaki adet alanına değer yazar.</summary>
    public async Task SetQuantityAsync(string productCode, int quantity)
    {
        await Kapsamda(Card(productCode), Catalog.ProductCard.QUANTITY_INPUT_ONEK, productCode)
            .FillAsync(quantity.ToString(CultureInfo.InvariantCulture));
    }

    /// <summary>Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler.</summary>
    public async Task AddToCartAsync(string productCode, int quantity)
    {
        await SetQuantityAsync(productCode, quantity);
        // Yanıt beklemesi tıklamadan önce kurulur; tıklama hatası (ör. kırık locator) olduğu gibi
        // yükselir, yanıt zaman aşımı onu gölgelemez: triage tek ve doğru hatayı görür.
        var response = await Page.RunAndWaitForResponseAsync(
            () => Kapsamda(Card(productCode), Catalog.ProductCard.ADD_TO_CART, productCode).ClickAsync(),
            r => r.Url.EndsWith("/api/cart/lines", System.StringComparison.Ordinal) && r.Request.Method == "POST",
            new PageRunAndWaitForResponseOptions { Timeout = SepetYanitiMs });
        Dogrula(response.Ok, $"sepete ekleme isteği başarısız: {response.Status}");
    }

    /// <summary>Üst menüden sepete gider.</summary>
    public async Task OpenCartAsync()
    {
        await Kimlik(Nav.CART).ClickAsync();
        await DogrulaYolAsync(CartYolu);
    }

    /// <summary>Ürün kartının katalogda göründüğünü doğrular.</summary>
    public async Task ExpectProductVisibleAsync(string productCode)
    {
        await DogrulaAsync(() => Expect(Card(productCode)).ToBeVisibleAsync());
    }

    /// <summary>Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL").</summary>
    public async Task ExpectProductPriceAsync(string productCode, string price)
    {
        await DogrulaAsync(() => Expect(Kimlik(Catalog.PRODUCT_PRICE_ONEK, productCode)).ToHaveTextAsync(price));
    }

    /// <summary>Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava").</summary>
    public async Task ExpectCampaignAsync(string productCode, string campaignName)
    {
        await DogrulaAsync(() => Expect(Card(productCode)).ToContainTextAsync(campaignName));
    }

    /// <summary>Üst menüdeki sepet sayacının verilen adet olduğunu doğrular.</summary>
    public async Task ExpectCartCountAsync(int count)
    {
        await DogrulaAsync(() => Expect(Kimlik(Nav.CART_COUNT)).ToHaveTextAsync(count.ToString(CultureInfo.InvariantCulture)));
    }
}

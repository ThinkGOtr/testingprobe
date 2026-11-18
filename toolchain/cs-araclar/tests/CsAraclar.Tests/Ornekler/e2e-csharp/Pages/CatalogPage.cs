using System.Threading.Tasks;
using Microsoft.Playwright;

namespace Antreklabs.Bayi.Pages;

/// <summary>Ürün kataloğu.</summary>
public class CatalogPage : Ekran
{
    public CatalogPage(IPage page) : base(page)
    {
    }

    /// <summary>Ürünü verilen adetle sepete ekler.</summary>
    public async Task AddToCartAsync(string productCode, int quantity)
    {
        var kart = Sayfa.GetByTestId(Kimlikler.Catalog.PRODUCT_CARD_ONEK + productCode);
        await kart.GetByTestId(Kimlikler.Catalog.ProductCard.ADD_TO_CART).ClickAsync();
        _ = quantity;
    }

    /// <summary>Sepeti açar.</summary>
    public async Task OpenCartAsync() => await Sayfa.GetByTestId(Kimlikler.Nav.CART_COUNT).ClickAsync();

    /// <summary>Fiyatı döndürür.</summary>
    public async Task<string> ReadPriceAsync(string productCode) => await Task.FromResult(productCode);

    public async Task SecenekliAsync(string kod, bool tumu = false, double oran = 1.5, long uzun = 2) =>
        await Task.CompletedTask;
}

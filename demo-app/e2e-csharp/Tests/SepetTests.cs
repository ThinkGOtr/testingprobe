using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using Antreklabs.Bayi.Pages;
using Microsoft.Playwright;
using NUnit.Framework;
using static Microsoft.Playwright.Assertions;

namespace Antreklabs.Bayi.Tests;

/// <summary>
/// Katalog ve sepet (TPD-1) — TypeScript: tests/cart.spec.ts. 6 adet sınırı bilerek doğrulanmaz
/// (demo senaryosuna bağlıdır); yalnız iki senaryoda da doğru olan davranış (7 → 1 bedava) doğrulanır.
/// <c>kampanya</c> kategorisi kırarak doğrulamanın (ci/break-verify-csharp.sh) alt kümesidir.
/// </summary>
[OturumAcik]
public class SepetTests : TestTabani
{
    /// <summary>TypeScript: <c>test.beforeEach(catalogPage.goto)</c>.</summary>
    protected override Task HazirlikSonrasiAsync() => CatalogPage.GotoAsync();

    [Test]
    [Category("duman")]
    [Description("katalog ürünleri ve fiyatları tr-TR biçiminde gösterir")]
    public async Task KatalogFiyatlari()
    {
        await CatalogPage.ExpectProductPriceAsync("P-001", "25,00 TL");
        await CatalogPage.ExpectProductPriceAsync("P-002", "15,00 TL");
        await CatalogPage.ExpectProductPriceAsync("P-003", "8,00 TL");
        await CatalogPage.ExpectProductPriceAsync("P-004", "30,00 TL");
        await CatalogPage.ExpectCampaignAsync("P-001", "6 al 1 bedava");
    }

    [Test]
    [Category("duman")]
    [Description("AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar")]
    public async Task SepeteEkleSayaciArtirir()
    {
        await CatalogPage.ExpectCartCountAsync(0);
        await CatalogPage.AddToCartAsync("P-002", 1);
        await CatalogPage.ExpectCartCountAsync(1);
        await CatalogPage.AddToCartAsync("P-003", 2);
        await CatalogPage.ExpectCartCountAsync(3);
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL")]
    public async Task KampanyaYediAdet()
    {
        await CatalogPage.AddToCartAsync("P-001", 7);
        await CatalogPage.OpenCartAsync();
        await CartPage.ExpectLineQuantityAsync("P-001", 7);
        await CartPage.ExpectFreeQuantityAsync("P-001", 1);
        await CartPage.ExpectSubtotalAsync("175,00 TL");
        await CartPage.ExpectDiscountAsync("25,00 TL");
        // İndirim varsa özet değeri eksi işaretiyle gösterilir (işaret kimliksiz ayrı metindir): indirim
        // kimliğini içeren tanım değeri (<dd>, ARIA "definition").
        try
        {
            await Expect(Page.GetByRole(AriaRole.Definition)
                    .Filter(new LocatorFilterOptions { Has = Page.GetByTestId(Kimlikler.Cart.DISCOUNT) }))
                .ToHaveTextAsync("−25,00 TL");
        }
        catch (PlaywrightException e) when (Ekran.DogrulamaHatasiMi(e))
        {
            throw new AssertionException(e.Message, e);
        }
        await CartPage.ExpectTotalAsync("150,00 TL");
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanyasız üründe bedava adet verilmez")]
    public async Task KampanyasizUrundeBedavaYok()
    {
        await CatalogPage.AddToCartAsync("P-002", 12);
        await CatalogPage.OpenCartAsync();
        await CartPage.ExpectFreeQuantityAsync("P-002", 0);
        await CartPage.ExpectDiscountAsync("0,00 TL");
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanyasız siparişte minimum tutar altında uyarı gösterilir ve onay pasif olur")]
    public async Task KampanyasizMinimumUyarisi()
    {
        await CatalogPage.AddToCartAsync("P-002", 10);
        await CatalogPage.OpenCartAsync();
        await CartPage.ExpectTotalAsync("150,00 TL");
        await CartPage.ExpectMinOrderWarningAsync("Minimum sipariş tutarı 750,00 TL");
        await CartPage.ExpectCheckoutDisabledAsync();
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanyalı siparişte minimum tutar aranmaz")]
    public async Task KampanyalidaMinimumYok()
    {
        // 7 x P-001: toplam minimum tutarın (750,00 TL) çok altında; indirim tutarından bağımsız.
        await CatalogPage.AddToCartAsync("P-001", 7);
        await CatalogPage.OpenCartAsync();
        await CartPage.ExpectLineQuantityAsync("P-001", 7);
        await CartPage.ExpectNoMinOrderWarningAsync();
        await CartPage.ExpectCheckoutEnabledAsync();
    }

    [Test]
    [Description("minimum tutara ulaşınca uyarı kalkar ve onay aktif olur")]
    public async Task MinimumTutaraUlasinca()
    {
        await CatalogPage.AddToCartAsync("P-004", 25);
        await CatalogPage.OpenCartAsync();
        await CartPage.ExpectTotalAsync("750,00 TL");
        await CartPage.ExpectNoMinOrderWarningAsync();
        await CartPage.ExpectCheckoutEnabledAsync();
    }

    [Test]
    [Description("ürün sepetten kaldırılabilir")]
    public async Task UrunKaldirma()
    {
        await CatalogPage.AddToCartAsync("P-002", 1);
        await CatalogPage.AddToCartAsync("P-003", 1);
        await CatalogPage.OpenCartAsync();
        await CartPage.RemoveProductAsync("P-002");
        await CartPage.ExpectProductNotInCartAsync("P-002");
        await CartPage.ExpectLineQuantityAsync("P-003", 1);
        await CartPage.RemoveProductAsync("P-003");
        await CartPage.ExpectEmptyAsync();
    }
}

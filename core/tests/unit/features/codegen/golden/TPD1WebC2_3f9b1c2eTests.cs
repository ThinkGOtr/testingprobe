// AI-generated — AI Testing Probe (CasesToCode). Hedef projeye uyarlanmak üzere verilir:
// page object adlarını ve imzalarını projenize göre düzenleyebilirsiniz.
// Doğrulanmamış çıktı: adımlar tarayıcıda doğrulandı; bu kod derlenmedi ve koşulmadı; page object kütüphanesi TypeScript tablosundan türetilen adları varsayar.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: 945c89ca5f30204174eb8922157a74aa16ea6d05258f1a073abb49005814dffd
// Eşleme: verify_and_map · platform: web · dil: csharp (Playwright .NET + NUnit) · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: cf31f88a3e9573641b0cbbbbbedc4af4af58f8eee0c9432845c6a88b9611c17f · şablon: ec12586748d391e83017df7a5c21c160a93195b7173faab8267ea29175eb00fc
//
// Varsayılan page object imzaları (Antreklabs.Bayi.Pages; kurucu: new <Sınıf>(IPage page)):
//   CartPage
//     Task ExpectLineQuantityAsync(string productCode, double quantity)
//     Task ExpectFreeQuantityAsync(string productCode, double quantity)
//     Task ExpectSubtotalAsync(string amount)
//     Task ExpectDiscountAsync(string amount)
//     Task ExpectTotalAsync(string amount)
//   CatalogPage
//     Task AddToCartAsync(string productCode, double quantity)
//     Task OpenCartAsync()
//   LoginPage
//     Task GotoAsync()
//     Task LoginAsync(string username, string password)
using System.Threading.Tasks;
using Antreklabs.Bayi.Pages;
using Microsoft.Playwright.NUnit;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests.Generated;

[TestFixture]
[Category("uretilen")]
[Category("web")]
[Category("tp-case-3f9b1c2e-0000-5000-8000-0000000000c2")]
[Category("TPD-1")]
[Property("dealerUsername", "bayi1")]
public class TPD1WebC2_3f9b1c2eTests : PageTest
{
    [Test]
    [Description("7 adet kampanyalı üründe 1 adet bedava verilir")]
    public async Task Senaryo()
    {
        var cartPage = new CartPage(Page);
        var catalogPage = new CatalogPage(Page);
        var loginPage = new LoginPage(Page);

        // S1 — Giriş sayfasını aç
        await loginPage.GotoAsync();
        // S2 — Bayi kullanıcısıyla giriş yap
        await loginPage.LoginAsync("bayi1", "Demo123!");
        // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
        await catalogPage.AddToCartAsync("P-001", 7);
        // S4 — Üst menüden sepete git
        await catalogPage.OpenCartAsync();
        // Beklenen sonuç (değerler onaylı case metninden)
        await cartPage.ExpectLineQuantityAsync("P-001", 7);
        await cartPage.ExpectFreeQuantityAsync("P-001", 1);
        await cartPage.ExpectSubtotalAsync("175,00 TL");
        await cartPage.ExpectDiscountAsync("25,00 TL");
        await cartPage.ExpectTotalAsync("150,00 TL");
    }
}

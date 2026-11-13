// AI-generated — AI Testing Probe (CasesToCode). Hedef projeye uyarlanmak üzere verilir:
// page object adlarını ve imzalarını projenize göre düzenleyebilirsiniz.
// Doğrulanmamış çıktı: adımlar tarayıcıda doğrulandı; bu kod derlenmedi ve koşulmadı; page object kütüphanesi TypeScript tablosundan türetilen adları varsayar.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map · platform: web · dil: csharp (Playwright .NET + NUnit) · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: cf31f88a3e9573641b0cbbbbbedc4af4af58f8eee0c9432845c6a88b9611c17f · şablon: e24458169a8242f032cb780a7f503819586c0053d20dc6ef4b384d3610dbb7b6
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
//
// Taban adres: PageTest kullanıyorsanız göreli GotoAsync() çağrıları için ContextOptions() içinde
// BaseURL verin, ör.:
//   public override BrowserNewContextOptions ContextOptions() =>
//       new() { BaseURL = Environment.GetEnvironmentVariable("BASE_URL") };
// [Property("dealerUsername")] testin sabitlendiği e2e bayisidir (giriş bilgisi değil); kendi
// fikstürünüzde TestContext.CurrentContext.Test.Properties.Get("dealerUsername") ile okuyun.
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

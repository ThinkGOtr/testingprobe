// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Doğrulanmamış çıktı: adımlar tarayıcıda doğrulandı; bu kod derlenmedi ve koşulmadı; page object kütüphanesi TypeScript tablosundan türetilen adları varsayar.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: 945c89ca5f30204174eb8922157a74aa16ea6d05258f1a073abb49005814dffd
// Eşleme: verify_and_map · platform: web · dil: csharp (Playwright .NET + NUnit) · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: cf31f88a3e9573641b0cbbbbbedc4af4af58f8eee0c9432845c6a88b9611c17f · şablon: f5eecaf86ece0ac56a78b7c22eb709406d44079b3319143159c55a0f3a9fb568
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
public class TPD1C2_3f9b1c2eTests : PageTest
{
    [Test]
    [Description("7 adet kampanyalı üründe 1 adet bedava verilir")]
    public async Task Senaryo()
    {
        var cartPage = new CartPage(Page);
        var catalogPage = new CatalogPage(Page);
        var loginPage = new LoginPage(Page);

        // S1 — Giriş sayfasını aç
        await loginPage.Goto();
        // S2 — Bayi kullanıcısıyla giriş yap
        await loginPage.Login("bayi1", "Demo123!");
        // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
        await catalogPage.AddToCart("P-001", 7);
        // S4 — Üst menüden sepete git
        await catalogPage.OpenCart();
        // Beklenen sonuç (değerler onaylı case metninden)
        await cartPage.ExpectLineQuantity("P-001", 7);
        await cartPage.ExpectFreeQuantity("P-001", 1);
        await cartPage.ExpectSubtotal("175,00 TL");
        await cartPage.ExpectDiscount("25,00 TL");
        await cartPage.ExpectTotal("150,00 TL");
    }
}

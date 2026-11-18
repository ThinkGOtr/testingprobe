// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map · platform: web · dil: csharp · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: cf31f88a3e9573641b0cbbbbbedc4af4af58f8eee0c9432845c6a88b9611c17f · şablon: 9ea27220b4d7433748f8304e185b3db3bc627c604e8427509deca842fb8af589
using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests.Generated;

[Bayi("bayi1")]
public class TPD1WebC2_3f9b1c2eTests : TestTabani
{
    [Test]
    [Category("uretilen")]
    [Category("web")]
    [Category("tp-case-3f9b1c2e-0000-5000-8000-0000000000c2")]
    [Category("TPD-1")]
    [Description("7 adet kampanyalı üründe 1 adet bedava verilir")]
    public async Task Senaryo()
    {
        // S1 — Giriş sayfasını aç
        await LoginPage.GotoAsync();
        // S2 — Bayi kullanıcısıyla giriş yap
        await LoginPage.LoginAsync("bayi1", "Demo123!");
        // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
        await CatalogPage.AddToCartAsync("P-001", 7);
        // S4 — Üst menüden sepete git
        await CatalogPage.OpenCartAsync();
        // Beklenen sonuç (değerler onaylı case metninden)
        await CartPage.ExpectLineQuantityAsync("P-001", 7);
        await CartPage.ExpectFreeQuantityAsync("P-001", 1);
        await CartPage.ExpectSubtotalAsync("175,00 TL");
        await CartPage.ExpectDiscountAsync("25,00 TL");
        await CartPage.ExpectTotalAsync("150,00 TL");
    }
}

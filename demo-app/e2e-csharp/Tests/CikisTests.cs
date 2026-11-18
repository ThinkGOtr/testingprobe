using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Çıkış (TPD-4) — TypeScript: tests/login.spec.ts <c>signedInTest</c> "çıkış yapınca…".</summary>
[OturumAcik]
public class CikisTests : TestTabani
{
    [Test]
    [Category("duman")]
    [Description("çıkış yapınca giriş sayfasına dönülür")]
    public async Task CikisYapinca()
    {
        await CatalogPage.GotoAsync();
        await LoginPage.LogoutAsync();
        await LoginPage.ExpectOnLoginPageAsync();
    }
}

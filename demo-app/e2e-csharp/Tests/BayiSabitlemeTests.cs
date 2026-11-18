using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>
/// Bayiye (bayi2) sabitlenmiş test — TypeScript: tests/dealers.spec.ts "Bayiye sabitlenmiş test (bayi2)".
/// Üretilen testler case metnindeki bayiye bu yolla (<c>[Bayi]</c>) sabitlenir.
/// </summary>
[Bayi("bayi2")]
public class BayiSabitlemeTests : TestTabani
{
    [Test]
    [Category("duman")]
    [Description("case metnindeki bayi (bayi2) ile arayüzden giriş yapılır")]
    public async Task Bayi2IleGiris()
    {
        Assert.That(Dealer.KullaniciAdi, Is.EqualTo("bayi2"));
        await LoginPage.GotoAsync();
        await LoginPage.LoginAsync("bayi2", "Demo123!");
        await LoginPage.ExpectLoggedInAsync("Sahil Bayi");
        await CatalogPage.ExpectCartCountAsync(0);
    }
}

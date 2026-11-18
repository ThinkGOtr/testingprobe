using System.Collections.Generic;
using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Bayi girişi (TPD-4) — TypeScript: tests/login.spec.ts.</summary>
public class GirisTests : TestTabani
{
    [Test]
    [Category("duman")]
    [Description("doğru bilgilerle giriş yapılır ve katalog açılır")]
    public async Task DogruBilgilerleGiris()
    {
        await LoginPage.GotoAsync();
        await LoginPage.LoginAsync(Dealer.KullaniciAdi, Dealer.Parola);
        await LoginPage.ExpectLoggedInAsync(Dealer.Ad);
        await CatalogPage.ExpectProductVisibleAsync("P-001");
    }

    [Test]
    [Category("duman")]
    [Description("hatalı parolada hata mesajı gösterilir")]
    public async Task HataliParola()
    {
        await LoginPage.GotoAsync();
        await LoginPage.LoginAsync(Dealer.KullaniciAdi, "YanlisParola1");
        await LoginPage.ExpectLoginErrorAsync("Kullanıcı adı veya parola hatalı");
        await LoginPage.ExpectOnLoginPageAsync();
    }

    [Test]
    [Description("oturumsuz kullanıcı giriş sayfasına yönlendirilir")]
    public async Task OturumsuzYonlendirme()
    {
        await Page.GotoAsync("/sepet");
        await LoginPage.ExpectOnLoginPageAsync();
    }

    /// <summary>Oturumsuz açılış yoklaması ve giriş akışı tarayıcı konsoluna hata düşürmemeli.</summary>
    [Test]
    [Description("oturumsuz açılış ve giriş konsola hata yazmaz")]
    public async Task KonsolaHataYazilmaz()
    {
        var hatalar = new List<string>();
        Page.Console += (_, m) =>
        {
            if (m.Type == "error")
            {
                lock (hatalar)
                {
                    hatalar.Add(m.Text);
                }
            }
        };
        Page.PageError += (_, e) =>
        {
            lock (hatalar)
            {
                hatalar.Add(e);
            }
        };
        await LoginPage.GotoAsync();
        await LoginPage.ExpectOnLoginPageAsync();
        await LoginPage.LoginAsync(Dealer.KullaniciAdi, Dealer.Parola);
        await LoginPage.ExpectLoggedInAsync(Dealer.Ad);
        await CatalogPage.ExpectProductVisibleAsync("P-001");
        lock (hatalar)
        {
            Assert.That(hatalar, Is.Empty);
        }
    }
}

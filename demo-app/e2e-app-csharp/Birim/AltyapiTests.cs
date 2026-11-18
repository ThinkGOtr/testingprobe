using System;
using System.IO;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;
using OpenQA.Selenium;
using OpenQA.Selenium.Appium;

namespace Antreklabs.Bayi.Birim;

[TestFixture]
[Category("birim")]
public class AltyapiTests
{
    private sealed class GizliErisim : TestTabani
    {
        public static string Oku(string ad) => Gizli(ad);
    }

    [Test]
    public void GizliAdBicimiVeTanimsiz()
    {
        Assert.Throws<ArgumentException>(() => GizliErisim.Oku("PATH"));
        Assert.Throws<ArgumentException>(() => GizliErisim.Oku("TP_TESTVERI_kucuk"));
        var e = Assert.Throws<InvalidOperationException>(() => GizliErisim.Oku("TP_TESTVERI_YOK_BOYLE_BIR_SIR_" + Guid.NewGuid().ToString("N").ToUpperInvariant()));
        Assert.That(e!.Message, Does.Contain("tanımsız"));
        Environment.SetEnvironmentVariable("TP_TESTVERI_BIRIM_DENEME", "deger-1");
        try
        {
            Assert.That(GizliErisim.Oku("TP_TESTVERI_BIRIM_DENEME"), Is.EqualTo("deger-1"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("TP_TESTVERI_BIRIM_DENEME", null);
        }
    }

    [Test]
    public void BayiSecimi()
    {
        Assert.That(Bayiler.Sec(null, 0).KullaniciAdi, Is.EqualTo("bayi1"));
        Assert.That(Bayiler.Sec("bayi2", 0).Ad, Is.EqualTo("Sahil Bayi"));
        var e = Assert.Throws<ArgumentException>(() => Bayiler.Sec("bayi3", 0));
        Assert.That(e!.Message, Does.Contain("doğrulama ajanına"));
        Assert.Throws<ArgumentException>(() => Bayiler.Sec(null, 2));
        Assert.That(Bayiler.SinifIcin(typeof(Tests.Bayi2SabitlemeTests), 0).KullaniciAdi, Is.EqualTo("bayi2"));
        Assert.That(Bayiler.SinifIcin(typeof(Tests.Generated.TPD1WindowsC2_3f9b1c2eTests), 0).KullaniciAdi, Is.EqualTo("bayi1"));
    }

    [Test]
    public void KosuParolaAdiVeSeedYedegi()
    {
        Assert.That(Bayiler.KosuParolaAdi("bayi1"), Is.EqualTo("TP_TESTVERI_KOSU_BAYI1"));
        Assert.That(Bayiler.KosuParolaAdi("test.k-2"), Is.EqualTo("TP_TESTVERI_KOSU_TEST_K_2"));
        Assert.That(Bayiler.KosuParolaAdi(new string('x', 60)), Is.Null);
        Assert.That(Bayiler.KosuParolasiAdla("TP_TESTVERI_KOSU_BAYI1"), Is.EqualTo(Bayiler.Sec("bayi1", 0).Parola));
        Assert.That(Bayiler.KosuParolasiAdla("TP_TESTVERI_KOSU_YOK"), Is.Null);
    }

    [Test]
    public void KosuParolasi()
    {
        Assert.That(Bayiler.KosuParolalari(null), Is.Empty);
        Assert.That(Bayiler.KosuParolalari(" "), Is.Empty);
        var p = Bayiler.KosuParolalari("{\"bayi2\": \"Bayi2 özel!\", \"bos\": \"\", \"sayi\": 1}");
        Assert.That(p, Is.EquivalentTo(new System.Collections.Generic.Dictionary<string, string> { ["bayi2"] = "Bayi2 özel!" }));
        var b2 = Bayiler.E2E[1];
        Assert.That(Bayiler.KosuParolasiyla(b2, p).Parola, Is.EqualTo("Bayi2 özel!"));
        Assert.That(Bayiler.KosuParolasiyla(b2, p).Ad, Is.EqualTo(b2.Ad));
        Assert.That(Bayiler.KosuParolasiyla(Bayiler.E2E[0], p), Is.SameAs(Bayiler.E2E[0]));
        Assert.Throws<ArgumentException>(() => Bayiler.KosuParolalari("{x"));
        Assert.Throws<ArgumentException>(() => Bayiler.KosuParolalari("[\"a\"]"));
    }

    [Test]
    public void BeklemeHataTurleri()
    {
        var b = new Bekle(TimeSpan.FromMilliseconds(300));
        var zaman = Assert.Throws<WebDriverTimeoutException>(() => b.Kosul("öğe görünmedi: kimlik 'x'", () => false));
        Assert.That(zaman!.Message, Does.StartWith("Expected condition failed: öğe görünmedi: kimlik 'x' (tried for 0 second(s)"));
        var dogrula = Assert.Throws<AssertionException>(() => b.Dogrula("'cart-total' metni", "150,00 TL", () => "175,00 TL", () => false));
        Assert.That(dogrula!.Message, Is.EqualTo("'cart-total' metni: beklenen <150,00 TL>, görülen <175,00 TL> (300 ms)"));
        Assert.That(b.Kosul<string>("x", () => "tamam"), Is.EqualTo("tamam"));
    }

    [Test]
    public void SurucuSecenekleriNovaWindows()
    {
        var a = Ayarlar.Haritadan(new System.Collections.Generic.Dictionary<string, string>
        {
            ["APP_PATH"] = @"C:\uygulama\BayiSiparis.exe",
            ["APP_ARGS"] = "--api-url http://127.0.0.1:18000",
        });
        AppiumOptions o = SurucuFabrikasi.Secenekler(a);
        Assert.That(o.AutomationName, Is.EqualTo("NovaWindows"));
        Assert.That(o.App, Is.EqualTo(@"C:\uygulama\BayiSiparis.exe"));
        var yetenekler = o.ToCapabilities();
        Assert.That(yetenekler.GetCapability("appium:appArguments"), Is.EqualTo("--api-url http://127.0.0.1:18000"));
        Assert.That(yetenekler.GetCapability("appium:automationName"), Is.EqualTo("NovaWindows"));
        Assert.Throws<ArgumentException>(() => SurucuFabrikasi.PowershellGuvenli("APP_ARGS", "a'; calc"));
        Assert.Throws<ArgumentException>(() => SurucuFabrikasi.Secenekler(Ayarlar.Haritadan(new System.Collections.Generic.Dictionary<string, string>())));
        Assert.Throws<ArgumentException>(() => SurucuFabrikasi.Adres("ftp://x"));
    }

    [Test]
    public void KimlikOneki()
    {
        Assert.That(Kimlik.Ekli("product-card-", "P-001"), Is.EqualTo("product-card-P-001"));
        Assert.Throws<ArgumentException>(() => Kimlik.Ekli("cart-total", "P-001"));
        Assert.Throws<ArgumentException>(() => Kimlik.Ekli("product-card-", ""));
    }

    [Test]
    public void KanitDiziniGuvenliAd()
    {
        string d = Kanit.Dizin("kanit", "Sinif", "Metot<1>");
        Assert.That(Path.GetFileName(d), Is.EqualTo("Sinif.Metot_1_"));
    }

    [Test]
    public void BayiKilidiAlinirVeBirakilir()
    {
        string dizin = Path.Combine(Path.GetTempPath(), "e2e-app-csharp-birim-" + Guid.NewGuid().ToString("N"));
        try
        {
            using (BayiKilidi.Al(dizin, "bayi1", TimeSpan.FromSeconds(2)))
            {
                Assert.That(File.Exists(Path.Combine(dizin, "bayi1.kilit")), Is.True);
            }
            using (BayiKilidi.Al(dizin, "bayi1", TimeSpan.FromSeconds(2)))
            {
                // yeniden alınabilir
            }
        }
        finally
        {
            Directory.Delete(dizin, true);
        }
    }
}

using System;
using System.Linq;
using System.Reflection;
using Antreklabs.Bayi.Altyapi;
using Antreklabs.Bayi.Pages;
using Antreklabs.Bayi.Tests.Generated;
using NUnit.Framework;

namespace Antreklabs.Bayi.Birim;

/// <summary>TestTabani yardımcıları, bayi seçimi, gizli test verisi ve üretilen test biçimi (tarayıcısız).</summary>
[Category("birim")]
[NonParallelizable]
public class TabanTests
{
    private static string Gizli(string ad)
    {
        var m = typeof(TestTabani).GetMethod("Gizli", BindingFlags.NonPublic | BindingFlags.Static)!;
        try
        {
            return (string)m.Invoke(null, new object[] { ad })!;
        }
        catch (TargetInvocationException e) when (e.InnerException is not null)
        {
            throw e.InnerException;
        }
    }

    [Test]
    public void GizliOrtamdanOkur()
    {
        Environment.SetEnvironmentVariable("TP_TESTVERI_BIRIM_DENEME", "s3cr3t");
        try
        {
            Assert.That(Gizli("TP_TESTVERI_BIRIM_DENEME"), Is.EqualTo("s3cr3t"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("TP_TESTVERI_BIRIM_DENEME", null);
        }
    }

    [TestCase("PATH")]
    [TestCase("TP_TESTVERI_")]
    [TestCase("tp_testveri_x")]
    [TestCase("TP_TESTVERI_A-B")]
    public void GizliGecersizAdReddedilir(string ad)
    {
        Assert.Throws<ArgumentException>(() => Gizli(ad));
    }

    [Test]
    public void GizliTanimsizAciklayiciHata()
    {
        var e = Assert.Throws<InvalidOperationException>(() => Gizli("TP_TESTVERI_BIRIM_YOK"));
        Assert.That(e!.Message, Does.Contain("TP_TESTVERI_BIRIM_YOK"));
    }

    [Test]
    public void BayiSecimi()
    {
        Assert.That(Bayiler.Sec(null, 0).KullaniciAdi, Is.EqualTo("bayi1"));
        Assert.That(Bayiler.Sec(null, 1).KullaniciAdi, Is.EqualTo("bayi2"));
        Assert.That(Bayiler.Sec("bayi2", 0).Ad, Is.EqualTo("Sahil Bayi"));
        var e = Assert.Throws<ArgumentException>(() => Bayiler.Sec(Bayiler.AjanBayisi, 0));
        Assert.That(e!.Message, Does.Contain("doğrulama ajanına ayrılmıştır"));
        Assert.Throws<ArgumentException>(() => Bayiler.Sec(null, 2));
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
    public void BayiOzniteligiSinifBayisiniSabitler()
    {
        Assert.That(Bayiler.SinifIcin(typeof(TPD1WebC2_3f9b1c2eTests), 1).KullaniciAdi, Is.EqualTo("bayi1"));
        Assert.That(Bayiler.SinifIcin(typeof(Antreklabs.Bayi.Tests.BayiSabitlemeTests), 0).KullaniciAdi, Is.EqualTo("bayi2"));
    }

    [Test]
    public void YuvaAlBirak()
    {
        var a = TestTabani.YuvaAl(TimeSpan.FromSeconds(1));
        var b = TestTabani.YuvaAl(TimeSpan.FromSeconds(1));
        Assert.That(new[] { a, b }, Is.EquivalentTo(new[] { 0, 1 }));
        Assert.Throws<InvalidOperationException>(() => TestTabani.YuvaAl(TimeSpan.FromMilliseconds(50)));
        TestTabani.YuvaBirak(a);
        TestTabani.YuvaBirak(a); // ikinci bırakma etkisiz
        Assert.That(TestTabani.YuvaAl(TimeSpan.FromSeconds(1)), Is.EqualTo(a));
        TestTabani.YuvaBirak(a);
        TestTabani.YuvaBirak(b);
    }

    [Test]
    public void KimlikDegeri()
    {
        Assert.That(Ekran.KimlikDegeri("product-card-", "P-001"), Is.EqualTo("product-card-P-001"));
        Assert.That(Ekran.KimlikDegeri("cart-total", null), Is.EqualTo("cart-total"));
        Assert.Throws<ArgumentException>(() => Ekran.KimlikDegeri("product-card-", null));
        Assert.Throws<ArgumentException>(() => Ekran.KimlikDegeri("cart-total", "x"));
    }

    [Test]
    public void DogrulamaHatasiAyirimi()
    {
        Assert.That(Ekran.DogrulamaHatasiMi(new Microsoft.Playwright.PlaywrightException("Locator expected to have text 'y'\nBut was: 'x'")), Is.True);
        Assert.That(Ekran.DogrulamaHatasiMi(new Microsoft.Playwright.PlaywrightException("Page URL expected to match regex '/z$'")), Is.True);
        Assert.That(Ekran.DogrulamaHatasiMi(new Microsoft.Playwright.PlaywrightException("net::ERR_CONNECTION_REFUSED at http://x")), Is.False);
    }

    [Test]
    public void UretilenTestBicimi()
    {
        var uretilenler = typeof(TestTabani).Assembly.GetTypes()
            .Where(t => t.Namespace == "Antreklabs.Bayi.Tests.Generated" && !t.IsNested).ToList();
        Assert.That(uretilenler, Is.Not.Empty);
        foreach (var t in uretilenler)
        {
            Assert.That(t.BaseType, Is.EqualTo(typeof(TestTabani)), $"{t.Name} TestTabani'ndan türemeli");
            Assert.That(t.Name, Does.Match("^[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests$"));
            var testler = t.GetMethods().Where(m => m.GetCustomAttribute<TestAttribute>() is not null).ToList();
            Assert.That(testler.Select(m => m.Name), Is.EqualTo(new[] { "Senaryo" }));
            var kategoriler = testler[0].GetCustomAttributes<CategoryAttribute>().Select(c => c.Name).ToList();
            Assert.That(kategoriler, Does.Contain("uretilen").And.Contain("web"));
            Assert.That(kategoriler.Any(k => k.StartsWith("tp-case-", StringComparison.Ordinal)), Is.True);
        }
    }
}

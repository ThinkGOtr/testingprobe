using System;
using System.Collections.Generic;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Birim;

[Category("birim")]
public class AyarlarTests
{
    private static Ayarlar A(params (string, string)[] ortam)
    {
        var d = new Dictionary<string, string>();
        foreach (var (k, v) in ortam)
        {
            d[k] = v;
        }
        return Ayarlar.Haritadan(d);
    }

    [Test]
    public void Varsayilanlar()
    {
        var a = A();
        Assert.That(a.BaseUrl, Is.EqualTo("http://127.0.0.1:8081"));
        Assert.That(a.DemoApiUrl, Is.EqualTo("http://127.0.0.1:8081/api"));
        Assert.That(a.TestToken, Is.Null);
        Assert.That(a.KampanyaKirik, Is.False);
        Assert.That(a.HataKodu, Is.Null);
        Assert.That(a.Headless, Is.True);
        Assert.That(a.Bekleme, Is.EqualTo(TimeSpan.FromSeconds(5)));
        Assert.That(a.Gezinme, Is.EqualTo(TimeSpan.FromSeconds(10)));
        Assert.That(a.BayiKilidiBekleme, Is.EqualTo(TimeSpan.FromSeconds(40)));
        Assert.That(a.KanitDizini, Is.EqualTo("results/kanit"));
    }

    [Test]
    public void OrtamDegerleri()
    {
        var a = A(("BASE_URL", "http://web:80/"), ("API_URL", "http://api:8000/"), ("HEADLESS", "false"),
            ("BEKLEME_MS", "1500"), ("BREAK_CAMPAIGN", "1"), ("TP_FAULT", "sepet_500"), ("KANIT_DIZINI", "/tmp/k"));
        Assert.That(a.BaseUrl, Is.EqualTo("http://web:80"));
        Assert.That(a.DemoApiUrl, Is.EqualTo("http://api:8000"));
        Assert.That(a.Headless, Is.False);
        Assert.That(a.Bekleme, Is.EqualTo(TimeSpan.FromMilliseconds(1500)));
        Assert.That(a.KampanyaKirik, Is.True);
        Assert.That(a.HataKodu, Is.EqualTo("sepet_500"));
        Assert.That(a.KanitDizini, Is.EqualTo("/tmp/k"));
    }

    [Test]
    public void DemoApiUrlOnceligi()
    {
        Assert.That(A(("DEMO_API_URL", "http://a"), ("API_URL", "http://b")).DemoApiUrl, Is.EqualTo("http://a"));
    }

    [Test]
    public void GecersizDegerlerAciklayiciHata()
    {
        Assert.Throws<ArgumentException>(() => _ = A(("BEKLEME_MS", "beş")).Bekleme);
        Assert.Throws<ArgumentException>(() => _ = A(("TP_FAULT", "Kötü Kod")).HataKodu);
    }

    [Test]
    public void YalitimKipi_()
    {
        Assert.That(TestVerisi.Kip(A(("DEMOAPP_TEST_TOKEN", "t"))), Is.EqualTo(YalitimKipi.Sifirlama));
        Assert.That(TestVerisi.Kip(A(("TP_E2E_NO_RESET", "1"))), Is.EqualTo(YalitimKipi.YalnizSepet));
        Assert.Throws<InvalidOperationException>(() => TestVerisi.Kip(A()));
        Assert.Throws<InvalidOperationException>(() => TestVerisi.Kip(A(("BREAK_CAMPAIGN", "1"), ("TP_E2E_NO_RESET", "1"))));
        Assert.Throws<InvalidOperationException>(() => TestVerisi.Kip(A(("TP_FAULT", "x"), ("TP_E2E_NO_RESET", "1"))));
    }

    [Test]
    public void Kirilma()
    {
        Assert.That(TestVerisi.Kirilma(A()), Is.Null);
        Assert.That(TestVerisi.Kirilma(A(("BREAK_CAMPAIGN", "1"))), Is.EqualTo(("\"kampanya\":true", "\"kampanya\":false")));
        // İkisi birlikteyse TP_FAULT geçerlidir (TS dealerBreak ile aynı).
        Assert.That(TestVerisi.Kirilma(A(("BREAK_CAMPAIGN", "1"), ("TP_FAULT", "sepet_500"))),
            Is.EqualTo(("\"hata\":\"sepet_500\"", "\"hata\":null")));
        Assert.That(TestVerisi.TestUcu("http://api:8000/", "reset"), Is.EqualTo("http://api:8000/test/reset"));
    }

    [Test]
    public void KanitDizini()
    {
        Assert.That(Kanit.Dizin("k", "Sinif", "Metot(\"x/y\")"), Is.EqualTo(System.IO.Path.Combine("k", "Sinif.Metot__x_y__")));
    }
}

using System;
using System.Collections.Generic;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Birim;

[TestFixture]
[Category("birim")]
public class AyarlarTests
{
    private static Ayarlar A(params (string Ad, string Deger)[] ciftler)
    {
        var h = new Dictionary<string, string>();
        foreach (var (ad, deger) in ciftler)
        {
            h[ad] = deger;
        }
        return Ayarlar.Haritadan(h);
    }

    [Test]
    public void Varsayilanlar()
    {
        Ayarlar a = A();
        Assert.That(a.Platform(), Is.EqualTo("windows"));
        Assert.That(a.AppiumUrl, Is.EqualTo("http://127.0.0.1:4723"));
        Assert.That(a.DemoApiUrl, Is.EqualTo("http://127.0.0.1:8081/api"));
        Assert.That(a.Bekleme, Is.EqualTo(TimeSpan.FromSeconds(10)));
        Assert.That(a.BayiKilidiBekleme, Is.EqualTo(TimeSpan.FromSeconds(40)));
        Assert.That(a.KanitDizini, Is.EqualTo("kanit"));
        Assert.That(a.TestToken, Is.Null);
        Assert.That(a.KampanyaKirik, Is.False);
    }

    [Test]
    public void YalnizWindows()
    {
        Assert.That(A(("PLATFORM", "WINDOWS")).Platform(), Is.EqualTo("windows"));
        var hata = Assert.Throws<ArgumentException>(() => A(("PLATFORM", "android")).Platform());
        Assert.That(hata!.Message, Does.Contain("yalnız Windows"));
    }

    [Test]
    public void OrtamDegerleriVeKirpma()
    {
        Ayarlar a = A(("DEMO_API_URL", " http://x:18000/ "), ("BEKLEME_MS", "2500"), ("BREAK_CAMPAIGN", "1"));
        Assert.That(a.DemoApiUrl, Is.EqualTo("http://x:18000"));
        Assert.That(a.Bekleme, Is.EqualTo(TimeSpan.FromMilliseconds(2500)));
        Assert.That(a.KampanyaKirik, Is.True);
        Assert.Throws<ArgumentException>(() => _ = A(("BEKLEME_MS", "on")).Bekleme);
    }

    [Test]
    public void EkilmisHataBicimi()
    {
        Assert.That(A(("TP_FAULT", "sepet_500")).EkilmisHata, Is.EqualTo("sepet_500"));
        Assert.Throws<ArgumentException>(() => _ = A(("TP_FAULT", "Kötü kod")).EkilmisHata);
    }

    [Test]
    public void YalitimKipi()
    {
        Assert.That(TestVerisi.KipSec(A(("DEMOAPP_TEST_TOKEN", "t"))), Is.EqualTo(TestVerisi.Kip.Sifirlama));
        Assert.That(TestVerisi.KipSec(A(("TP_E2E_NO_RESET", "1"))), Is.EqualTo(TestVerisi.Kip.YalnizSepet));
        var e = Assert.Throws<InvalidOperationException>(() => TestVerisi.KipSec(A()));
        Assert.That(e!.Message, Does.Contain("DEMOAPP_TEST_TOKEN"));
        Assert.Throws<InvalidOperationException>(() => TestVerisi.KipSec(A(("BREAK_CAMPAIGN", "1"), ("TP_E2E_NO_RESET", "1"))));
    }

    [Test]
    public void KirilmaGovdeleri()
    {
        Assert.That(TestVerisi.KirilmaSec(A()), Is.Null);
        Assert.That(TestVerisi.KirilmaSec(A(("BREAK_CAMPAIGN", "1")))!.Govde("bayi1", true),
            Is.EqualTo("{\"kullanici_adi\":\"bayi1\",\"kampanya\":true}"));
        var hata = TestVerisi.KirilmaSec(A(("BREAK_CAMPAIGN", "1"), ("TP_FAULT", "x_1")))!;
        Assert.That(hata.Govde("bayi1", true), Is.EqualTo("{\"kullanici_adi\":\"bayi1\",\"hata\":\"x_1\"}"));
        Assert.That(hata.Govde("bayi1", false), Is.EqualTo("{\"kullanici_adi\":\"bayi1\",\"hata\":null}"));
        Assert.That(TestVerisi.TestUcu("http://a/api/", "reset"), Is.EqualTo("http://a/api/test/reset"));
    }
}

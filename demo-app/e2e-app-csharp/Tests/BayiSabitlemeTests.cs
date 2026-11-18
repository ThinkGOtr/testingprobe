using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Bayiye (bayi1) sabitlenmiş test — Java <c>testler/Bayi1SabitlemeTesti</c>.</summary>
[Bayi("bayi1")]
public class Bayi1SabitlemeTests : TestTabani
{
    [Test]
    [Description("case metnindeki bayi (bayi1) ile arayüzden giriş yapılır")]
    public void Bayi1IleGiris()
    {
        Assert.That(SeciliBayi.KullaniciAdi, Is.EqualTo("bayi1"));
        GirisEkrani.Ac();
        GirisEkrani.GirisYap("bayi1", "Demo123!");
        GirisEkrani.DogrulaGirisYapildi("Merkez Bayi");
        KatalogEkrani.SepeteEkle("P-002", 1);
        KatalogEkrani.DogrulaSepetSayaci(1);
    }
}

/// <summary>Bayiye (bayi2) sabitlenmiş test — Java <c>testler/Bayi2SabitlemeTesti</c>.</summary>
[Bayi("bayi2")]
public class Bayi2SabitlemeTests : TestTabani
{
    [Test]
    [Category("duman")]
    [Description("case metnindeki bayi (bayi2) ile arayüzden giriş yapılır")]
    public void Bayi2IleGiris()
    {
        Assert.That(SeciliBayi.KullaniciAdi, Is.EqualTo("bayi2"));
        GirisEkrani.Ac();
        GirisEkrani.GirisYap("bayi2", "Demo123!");
        GirisEkrani.DogrulaGirisYapildi("Sahil Bayi");
        KatalogEkrani.DogrulaSepetSayaci(0);
    }
}

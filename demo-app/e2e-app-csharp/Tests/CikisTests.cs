using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Çıkış (TPD-4) — Java <c>testler/CikisTesti</c>.</summary>
[OturumAcik]
public class CikisTests : TestTabani
{
    [Test]
    [Category("duman")]
    [Description("çıkış yapınca giriş ekranına dönülür")]
    public void CikisYapinca()
    {
        KatalogEkrani.Ac();
        GirisEkrani.CikisYap();
        GirisEkrani.DogrulaGirisEkraninda();
    }
}

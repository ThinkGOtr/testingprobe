using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>
/// Katalog ve sepet (TPD-1) — Java <c>testler/SepetTesti</c>, web tests/cart.spec.ts. Kırarak
/// doğrulama kümesi <c>kampanya</c> kategorisidir (break-verify-app-csharp.sh).
/// </summary>
[OturumAcik]
public class SepetTests : TestTabani
{
    /// <summary>Web: <c>test.beforeEach(catalogPage.goto)</c>.</summary>
    protected override void HazirlikSonrasi() => KatalogEkrani.Ac();

    [Test]
    [Category("duman")]
    [Description("katalog ürünleri ve fiyatları tr-TR biçiminde gösterir")]
    public void KatalogFiyatlari()
    {
        KatalogEkrani.DogrulaUrunFiyati("P-001", "25,00 TL");
        KatalogEkrani.DogrulaUrunFiyati("P-002", "15,00 TL");
        KatalogEkrani.DogrulaUrunFiyati("P-003", "8,00 TL");
        KatalogEkrani.DogrulaUrunFiyati("P-004", "30,00 TL");
        KatalogEkrani.DogrulaKampanya("P-001", "6 al 1 bedava");
    }

    [Test]
    [Category("duman")]
    [Description("AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar")]
    public void SepeteEkleSayaciArtirir()
    {
        KatalogEkrani.DogrulaSepetSayaci(0);
        KatalogEkrani.SepeteEkle("P-002", 1);
        KatalogEkrani.DogrulaSepetSayaci(1);
        KatalogEkrani.SepeteEkle("P-003", 2);
        KatalogEkrani.DogrulaSepetSayaci(3);
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL")]
    public void KampanyaYediAdet()
    {
        KatalogEkrani.SepeteEkle("P-001", 7);
        KatalogEkrani.SepetiAc();
        SepetEkrani.DogrulaSatirAdedi("P-001", 7);
        SepetEkrani.DogrulaBedavaAdet("P-001", 1);
        SepetEkrani.DogrulaAraToplam("175,00 TL");
        SepetEkrani.DogrulaIndirim("25,00 TL");
        SepetEkrani.DogrulaToplam("150,00 TL");
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanyasız üründe bedava adet verilmez")]
    public void KampanyasizUrundeBedavaYok()
    {
        KatalogEkrani.SepeteEkle("P-002", 12);
        KatalogEkrani.SepetiAc();
        SepetEkrani.DogrulaBedavaAdet("P-002", 0);
        SepetEkrani.DogrulaIndirim("0,00 TL");
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanyasız siparişte minimum tutar altında uyarı gösterilir ve onay pasif olur")]
    public void KampanyasizMinimumUyarisi()
    {
        KatalogEkrani.SepeteEkle("P-002", 10);
        KatalogEkrani.SepetiAc();
        SepetEkrani.DogrulaToplam("150,00 TL");
        SepetEkrani.DogrulaMinimumSiparisUyarisi("Minimum sipariş tutarı 750,00 TL");
        SepetEkrani.DogrulaOnayPasif();
    }

    [Test]
    [Category("kampanya")]
    [Description("kampanyalı siparişte minimum tutar aranmaz")]
    public void KampanyalidaMinimumYok()
    {
        KatalogEkrani.SepeteEkle("P-001", 7);
        KatalogEkrani.SepetiAc();
        SepetEkrani.DogrulaSatirAdedi("P-001", 7);
        SepetEkrani.DogrulaMinimumSiparisUyarisiYok();
        SepetEkrani.DogrulaOnayAktif();
    }

    [Test]
    [Description("minimum tutara ulaşınca uyarı kalkar ve onay aktif olur")]
    public void MinimumTutaraUlasinca()
    {
        KatalogEkrani.SepeteEkle("P-004", 25);
        KatalogEkrani.SepetiAc();
        SepetEkrani.DogrulaToplam("750,00 TL");
        SepetEkrani.DogrulaMinimumSiparisUyarisiYok();
        SepetEkrani.DogrulaOnayAktif();
    }

    [Test]
    [Description("ürün sepetten kaldırılabilir")]
    public void UrunKaldirma()
    {
        KatalogEkrani.SepeteEkle("P-002", 1);
        KatalogEkrani.SepeteEkle("P-003", 1);
        KatalogEkrani.SepetiAc();
        SepetEkrani.UrunuKaldir("P-002");
        SepetEkrani.DogrulaUrunSepetteYok("P-002");
        SepetEkrani.DogrulaSatirAdedi("P-003", 1);
        SepetEkrani.UrunuKaldir("P-003");
        SepetEkrani.DogrulaSepetBos();
    }
}

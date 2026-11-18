using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Sipariş onayı ve geçmiş (TPD-1 AC5) — Java <c>testler/SiparisTesti</c>.</summary>
[OturumAcik]
public class SiparisTests : TestTabani
{
    // Sıfırlanmış veri gerektirir; TP_E2E_NO_RESET=1 kipinde atlanır.
    [Test]
    [Category(SifirVeri)]
    [Description("siparişi olmayan bayide boş geçmiş bilgisi gösterilir")]
    public void BosGecmis()
    {
        SiparisEkrani.Ac();
        SiparisEkrani.DogrulaSiparisYok();
    }

    [Test]
    [Category("duman")]
    [Description("onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir")]
    public void SiparisOnayVeGecmis()
    {
        KatalogEkrani.Ac();
        KatalogEkrani.SepeteEkle("P-004", 30);
        KatalogEkrani.SepeteEkle("P-001", 7);
        KatalogEkrani.SepetiAc();
        SepetEkrani.DogrulaToplam("1.050,00 TL");
        SepetEkrani.SiparisiOnayla();
        OnayEkrani.DogrulaSiparisOnayi();
        OnayEkrani.DogrulaOnaylananToplam("1.050,00 TL");
        KatalogEkrani.DogrulaSepetSayaci(0);
        OnayEkrani.DogrulaOnaylananSiparisGecmiste();
        SiparisEkrani.DogrulaOnaylananSiparisToplami("1.050,00 TL");
    }
}

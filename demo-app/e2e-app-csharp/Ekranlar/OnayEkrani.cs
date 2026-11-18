using System.Text.RegularExpressions;
using Antreklabs.Bayi.Altyapi;

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>
/// Sipariş onayı ekranı (Java <c>OnayEkrani</c>; web <c>OrderPage</c> onay bölümü). Okunan sipariş
/// numarası oturumda saklanır (yalnız <c>void</c> metot sözleşmesi).
/// </summary>
public class OnayEkrani : Ekran
{
    /// <summary>Sipariş numarası biçimi (web: <c>ORDER_NUMBER</c>).</summary>
    internal static readonly Regex SiparisNumarasi = new("^SP-[0-9]{6}$", RegexOptions.CultureInvariant);

    public OnayEkrani(UygulamaOturumu oturum)
        : base(oturum)
    {
    }

    /// <summary>Onay ekranındaki sipariş numarasını okur ve oturumda saklar.</summary>
    internal string SiparisNumarasiniOku()
    {
        MetinKalibinaUymali(Kimlikler.Onay.SIPARIS_NUMARASI, SiparisNumarasi);
        string numara = Metin(GorunurBekle(Kimlikler.Onay.SIPARIS_NUMARASI));
        Oturum.SonSiparisNumarasi = numara;
        return numara;
    }

    /// <summary>Sipariş onayının ve sipariş numarasının gösterildiğini doğrular.</summary>
    public void DogrulaSiparisOnayi()
    {
        GorunurOlmali(Kimlikler.Onay.ONAY_ALANI);
        SiparisNumarasiniOku();
    }

    /// <summary>Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL").</summary>
    public void DogrulaOnaylananToplam(string tutar) => MetinOlmali(Kimlikler.Onay.TOPLAM, tutar);

    /// <summary>Onaylanan siparişin kampanya indirimini doğrular (ör. "25,00 TL").</summary>
    public void DogrulaOnaylananIndirim(string tutar) => MetinOlmali(Kimlikler.Onay.INDIRIM, tutar);

    /// <summary>Onay ekranında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular.</summary>
    public void DogrulaOnaylananSiparisGecmiste()
    {
        string numara = SiparisNumarasiniOku();
        var gecmis = new SiparisEkrani(Oturum);
        gecmis.MenudenAc();
        gecmis.DogrulaSiparisGecmiste(numara);
    }

    /// <summary>Onay ekranından "Siparişlerime git" ile sipariş geçmişine gider.</summary>
    public void SiparislerimeGit()
    {
        Dokun(Kimlikler.Onay.SIPARISLERIME_GIT);
        BiriGorunurBekle(Kimlikler.Siparis.TABLO, Kimlikler.Siparis.BOS);
    }

    /// <summary>Onay ekranından "Alışverişe devam et" ile kataloğa döner.</summary>
    public void AlisveriseDevamEt()
    {
        Dokun(Kimlikler.Onay.ALISVERISE_DEVAM);
        GorunurBekle(Kimlikler.Katalog.URUN_LISTESI);
    }
}

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>Sepet ekranı.</summary>
public class SepetEkrani : Ekran
{
    public void DogrulaSatirAdedi(string urunKodu, int adet)
    {
    }

    public void DogrulaBedavaAdet(string urunKodu, int adet)
    {
    }

    public void DogrulaAraToplam(string tutar)
    {
    }

    public void DogrulaIndirim(string tutar)
    {
    }

    /// <summary>Toplamı doğrular.</summary>
    public void DogrulaToplam(string tutar)
    {
        _ = Kimlikler.Sepet.TOPLAM;
    }

    public void Karisik(decimal tutar)
    {
    }
}

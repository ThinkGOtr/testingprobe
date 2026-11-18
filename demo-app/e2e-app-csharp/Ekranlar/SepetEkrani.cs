using Antreklabs.Bayi.Altyapi;

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>Sepet ekranı: satırlar, kampanya, toplamlar ve sipariş onayı (Java <c>SepetEkrani</c>; web <c>CartPage</c>).</summary>
public class SepetEkrani : Ekran
{
    public SepetEkrani(UygulamaOturumu oturum)
        : base(oturum)
    {
    }

    /// <summary>Sepet ekranını açar.</summary>
    public void Ac()
    {
        Dokun(Kimlikler.Menu.SEPET);
        BiriGorunurBekle(Kimlikler.Sepet.TABLO, Kimlikler.Sepet.BOS);
    }

    /// <summary>Ürünü sepetten kaldırır.</summary>
    public void UrunuKaldir(string urunKodu)
    {
        Dokun(Kimlik.Ekli(Kimlikler.Sepet.SATIRI_KALDIR_ONEK, urunKodu));
        string satir = Kimlik.Ekli(Kimlikler.Sepet.SATIR_ONEK, urunKodu);
        Bekle.Kosul($"satır sepetten kalkmadı: kimlik '{satir}'", () => HemenBul(null, satir) is null);
    }

    /// <summary>"Siparişi onayla" butonuna basar ve onay ekranının açılmasını bekler.</summary>
    public void SiparisiOnayla()
    {
        Dokun(Kimlikler.Sepet.SIPARISI_ONAYLA);
        GorunurBekle(Kimlikler.Onay.ONAY_ALANI);
    }

    /// <summary>Sepet satırındaki adedi doğrular.</summary>
    public void DogrulaSatirAdedi(string urunKodu, int adet) =>
        MetinOlmali(Kimlik.Ekli(Kimlikler.Sepet.SATIR_ADEDI_ONEK, urunKodu), Sayi(adet));

    /// <summary>Sepet satırında kampanyayla bedava verilen adedi doğrular.</summary>
    public void DogrulaBedavaAdet(string urunKodu, int adet) =>
        MetinOlmali(Kimlik.Ekli(Kimlikler.Sepet.BEDAVA_ADET_ONEK, urunKodu), Sayi(adet));

    /// <summary>Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL").</summary>
    public void DogrulaSatirToplami(string urunKodu, string tutar) =>
        MetinOlmali(Kimlik.Ekli(Kimlikler.Sepet.SATIR_TOPLAMI_ONEK, urunKodu), tutar);

    /// <summary>Ara toplamı doğrular (ör. "175,00 TL").</summary>
    public void DogrulaAraToplam(string tutar) => MetinOlmali(Kimlikler.Sepet.ARA_TOPLAM, tutar);

    /// <summary>Kampanya indirimi tutarını doğrular (ör. "25,00 TL").</summary>
    public void DogrulaIndirim(string tutar) => MetinOlmali(Kimlikler.Sepet.INDIRIM, tutar);

    /// <summary>Sepetin indirim sonrası genel toplamını doğrular (ör. "150,00 TL").</summary>
    public void DogrulaToplam(string tutar) => MetinOlmali(Kimlikler.Sepet.TOPLAM, tutar);

    /// <summary>Minimum sipariş uyarısının verilen metni içerdiğini doğrular.</summary>
    public void DogrulaMinimumSiparisUyarisi(string mesaj) => MetinIcermeli(Kimlikler.Sepet.MIN_SIPARIS_UYARISI, mesaj);

    /// <summary>Minimum sipariş uyarısının gösterilmediğini doğrular.</summary>
    public void DogrulaMinimumSiparisUyarisiYok() => YokOlmali(Kimlikler.Sepet.MIN_SIPARIS_UYARISI);

    /// <summary>"Siparişi onayla" butonunun pasif olduğunu doğrular.</summary>
    public void DogrulaOnayPasif() => EtkinOlmali(Kimlikler.Sepet.SIPARISI_ONAYLA, false);

    /// <summary>"Siparişi onayla" butonunun aktif olduğunu doğrular.</summary>
    public void DogrulaOnayAktif() => EtkinOlmali(Kimlikler.Sepet.SIPARISI_ONAYLA, true);

    /// <summary>Sepette ürünün bulunmadığını doğrular.</summary>
    public void DogrulaUrunSepetteYok(string urunKodu) => YokOlmali(Kimlik.Ekli(Kimlikler.Sepet.SATIR_ONEK, urunKodu));

    /// <summary>Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet ekranında).</summary>
    public void DogrulaSepetSayaci(int adet) => MetinOlmali(Kimlikler.Menu.SEPET_SAYACI, Sayi(adet));

    /// <summary>Sepetin boş olduğunu doğrular.</summary>
    public void DogrulaSepetBos() => GorunurOlmali(Kimlikler.Sepet.BOS);
}

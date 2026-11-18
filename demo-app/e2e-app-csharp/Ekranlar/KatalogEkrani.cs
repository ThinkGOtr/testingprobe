using System;
using System.Globalization;
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;
using OpenQA.Selenium;

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>Ürün kataloğu ekranı (Java <c>KatalogEkrani</c>; web <c>CatalogPage</c>).</summary>
public class KatalogEkrani : Ekran
{
    /// <summary>Başarılı eklemede ürün kartındaki bilgi mesajının parçası.</summary>
    private const string Eklendi = "sepete eklendi";

    public KatalogEkrani(UygulamaOturumu oturum)
        : base(oturum)
    {
    }

    private static string Kart(string urunKodu) => Kimlik.Ekli(Kimlikler.Katalog.URUN_KARTI_ONEK, urunKodu);

    /// <summary>Katalog ekranını açar.</summary>
    public void Ac()
    {
        Dokun(Kimlikler.Menu.KATALOG);
        GorunurBekle(Kimlikler.Katalog.URUN_LISTESI);
    }

    /// <summary>Üst menüden kataloğa gider.</summary>
    public void MenudenAc() => Ac();

    /// <summary>Ürün kartındaki adet alanına değer yazar.</summary>
    public void AdetGir(string urunKodu, int adet) =>
        Yaz(Kimlik.Ekli(Kimlikler.Katalog.ADET_ONEK, urunKodu), Sayi(adet));

    /// <summary>Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler.</summary>
    public void SepeteEkle(string urunKodu, int adet)
    {
        int once = SepetSayaci();
        AdetGir(urunKodu, adet);
        Dokun(Kart(urunKodu), Kimlikler.Katalog.SEPETE_EKLE);
        string durum = Kimlik.Ekli(Kimlikler.Katalog.EKLEME_DURUMU_ONEK, urunKodu);
        Bekle.Kosul(
            $"sepete ekleme tamamlanmadı: '{durum}' mesajı ve sepet sayacı {once + adet}",
            () =>
            {
                IWebElement? mesajOgesi = HemenBul(null, durum);
                string mesaj = mesajOgesi is null ? "" : Metin(mesajOgesi);
                if (mesaj.Length > 0 && !mesaj.Contains(Eklendi, StringComparison.Ordinal))
                {
                    throw new AssertionException("sepete ekleme başarısız: " + mesaj);
                }
                return mesaj.Contains(Eklendi, StringComparison.Ordinal) && SayacHemen() == once + adet;
            });
    }

    /// <summary>Üst menüden sepete gider.</summary>
    public void SepetiAc()
    {
        Dokun(Kimlikler.Menu.SEPET);
        BiriGorunurBekle(Kimlikler.Sepet.TABLO, Kimlikler.Sepet.BOS);
    }

    /// <summary>Ürün kartının katalogda göründüğünü doğrular.</summary>
    public void DogrulaUrunGorunur(string urunKodu) => GorunurOlmali(Kart(urunKodu));

    /// <summary>Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL").</summary>
    public void DogrulaUrunFiyati(string urunKodu, string fiyat) =>
        MetinOlmali(Kimlik.Ekli(Kimlikler.Katalog.URUN_FIYATI_ONEK, urunKodu), fiyat);

    /// <summary>Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava").</summary>
    public void DogrulaKampanya(string urunKodu, string kampanyaAdi) => TumMetinIcermeli(Kart(urunKodu), kampanyaAdi);

    /// <summary>Üst menüdeki sepet sayacının verilen adet olduğunu doğrular.</summary>
    public void DogrulaSepetSayaci(int adet) => MetinOlmali(Kimlikler.Menu.SEPET_SAYACI, Sayi(adet));

    // ---------------------------------------------------------------- yardımcılar (sembol tablosu dışı)

    private int SepetSayaci()
    {
        GorunurBekle(Kimlikler.Menu.SEPET_SAYACI);
        string okunan = Bekle.Kosul(
            $"sepet sayacı okunamadı: kimlik '{Kimlikler.Menu.SEPET_SAYACI}'",
            () => SayacHemen() < 0 ? null : SayacHemen().ToString(CultureInfo.InvariantCulture));
        return int.Parse(okunan, CultureInfo.InvariantCulture);
    }

    /// <summary>Sayacı beklemeden okur; yoksa ya da sayı değilse -1.</summary>
    private int SayacHemen()
    {
        IWebElement? e = HemenBul(null, Kimlikler.Menu.SEPET_SAYACI);
        if (e is null)
        {
            return -1;
        }
        return int.TryParse(Metin(e), NumberStyles.Integer, CultureInfo.InvariantCulture, out int n) ? n : -1;
    }
}

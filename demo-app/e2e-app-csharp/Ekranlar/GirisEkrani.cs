using Antreklabs.Bayi.Altyapi;

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>Bayi giriş ekranı (Java <c>GirisEkrani</c>; web <c>LoginPage</c>).</summary>
public class GirisEkrani : Ekran
{
    public GirisEkrani(UygulamaOturumu oturum)
        : base(oturum)
    {
    }

    /// <summary>Giriş ekranını açar (uygulama her testte sıfırdan, giriş ekranında başlar).</summary>
    public void Ac() => GorunurBekle(Kimlikler.Giris.KULLANICI_ADI);

    /// <summary>Bayi kullanıcı adı ve parolasıyla giriş yapar.</summary>
    public void GirisYap(string kullaniciAdi, string parola)
    {
        Yaz(Kimlikler.Giris.KULLANICI_ADI, kullaniciAdi);
        Yaz(Kimlikler.Giris.PAROLA, parola);
        Dokun(Kimlikler.Giris.GIRIS_YAP);
    }

    /// <summary>Oturumu kapatır.</summary>
    public void CikisYap() => Dokun(Kimlikler.Menu.CIKIS);

    /// <summary>Hata mesajının göründüğünü ve metnini doğrular.</summary>
    public void DogrulaHataMesaji(string beklenen) => MetinOlmali(Kimlikler.Giris.HATA, beklenen);

    /// <summary>Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular.</summary>
    public void DogrulaGirisYapildi(string bayiAdi)
    {
        MetinOlmali(Kimlikler.Menu.BAYI_ADI, bayiAdi);
        GorunurOlmali(Kimlikler.Katalog.URUN_LISTESI);
    }

    /// <summary>Giriş ekranında olunduğunu doğrular.</summary>
    public void DogrulaGirisEkraninda()
    {
        GorunurOlmali(Kimlikler.Giris.GIRIS_YAP);
        YokOlmali(Kimlikler.Menu.BAYI_ADI);
    }
}

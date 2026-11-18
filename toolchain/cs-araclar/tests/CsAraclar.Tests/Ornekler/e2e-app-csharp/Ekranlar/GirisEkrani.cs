namespace Antreklabs.Bayi.Ekranlar;

/// <summary>Bayi giriş ekranı.</summary>
public class GirisEkrani : FormEkrani
{
    /// <summary>Giriş ekranını açar.</summary>
    public void Ac()
    {
    }

    /// <summary>Giriş yapar.</summary>
    public void GirisYap(string kullaniciAdi, string parola)
    {
        _ = Kimlikler.Giris.KULLANICI_ADI + Kimlikler.Giris.PAROLA + kullaniciAdi + parola;
    }
}

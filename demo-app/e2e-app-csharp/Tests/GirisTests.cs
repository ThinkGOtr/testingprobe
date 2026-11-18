using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests;

/// <summary>Bayi girişi (TPD-4) — Java <c>testler/GirisTesti</c>, web tests/login.spec.ts.</summary>
public class GirisTests : TestTabani
{
    [Test]
    [Category("duman")]
    [Description("doğru bilgilerle giriş yapılır ve katalog açılır")]
    public void DogruBilgilerleGiris()
    {
        GirisEkrani.Ac();
        GirisEkrani.GirisYap(SeciliBayi.KullaniciAdi, SeciliBayi.Parola);
        GirisEkrani.DogrulaGirisYapildi(SeciliBayi.Ad);
        KatalogEkrani.DogrulaUrunGorunur("P-001");
    }

    [Test]
    [Category("duman")]
    [Description("hatalı parolada hata mesajı gösterilir")]
    public void HataliParola()
    {
        GirisEkrani.Ac();
        GirisEkrani.GirisYap(SeciliBayi.KullaniciAdi, "YanlisParola1");
        GirisEkrani.DogrulaHataMesaji("Kullanıcı adı veya parola hatalı");
        GirisEkrani.DogrulaGirisEkraninda();
    }

    [Test]
    [Description("oturumsuz açılışta giriş ekranı gösterilir")]
    public void OturumsuzAcilis()
    {
        // Sıfırlanmış uygulama giriş ekranında açılmalı (önceki testin oturumu taşınmamalı).
        GirisEkrani.DogrulaGirisEkraninda();
    }
}

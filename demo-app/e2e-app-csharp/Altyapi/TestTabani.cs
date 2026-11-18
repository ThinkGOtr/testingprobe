using System;
using System.Collections;
using System.Text.RegularExpressions;
using Allure.NUnit;
using Antreklabs.Bayi.Ekranlar;
using NUnit.Framework;
using NUnit.Framework.Interfaces;
using OpenQA.Selenium;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Tüm Windows uygulama testlerinin tabanı (Java <c>altyapi/TestTabani</c>; web fixtures.ts).
///
/// Her test için, sırasıyla: bayi seçilir (<see cref="BayiAttribute"/> ya da işçi bayisi) ve süreçler
/// arası kilitle alınır → bayinin verisi sıfırlanır (<c>/test/reset</c>) ya da yalnız sepeti boşaltılır
/// → <c>TP_FAULT</c> / <c>BREAK_CAMPAIGN=1</c> ise <c>/test/break</c> → uygulama sıfırdan başlatılır
/// (yeni Appium/NovaWindows oturumu) → <see cref="OturumAcikAttribute"/> sınıflarda arayüzden giriş →
/// <see cref="HazirlikSonrasi"/>. Test bitince: başarısızsa kanıt, oturum kapanır, kırılma geri alınır,
/// kilit bırakılır. Hazırlık <c>[SetUp]</c>'tadır: NUnit hazırlık hatasını testin kendi sonucu yazar
/// (JUnit XML'de test başına tek satır).
///
/// Fikstür erişimi (üretilen testler): her ekran için sınıf adıyla aynı adlı özellik
/// (<c>GirisEkrani</c>, <c>KatalogEkrani</c>, …); üretilen testler yalnız bunları çağırır.
/// </summary>
[AllureNUnit]
public abstract class TestTabani
{
    /// <summary>Yalnızca sıfırlanmış veriyle anlamlı testlerin kategorisi (web: <c>@sifir-veri</c>).</summary>
    public const string SifirVeri = "sifir-veri";

    /// <summary>Gizli test verisi ortam değişkeni adı (013 K19; core <c>SIR_ADI_RE</c>).</summary>
    public static readonly Regex SirAdi = new("^TP_TESTVERI_[A-Z0-9_]{1,64}$", RegexOptions.CultureInvariant);

    private Ayarlar? ayarlar;
    private Bayiler.BayiBilgisi? bayi;
    private BayiKilidi? kilit;
    private TestVerisi? veri;
    private TestVerisi.Kirilma? kirilma;
    private IWebDriver? surucu;
    private UygulamaOturumu? oturum;

    private GirisEkrani? girisEkrani;
    private KatalogEkrani? katalogEkrani;
    private SepetEkrani? sepetEkrani;
    private OnayEkrani? onayEkrani;
    private SiparisEkrani? siparisEkrani;

    /// <summary>
    /// Gizli test verisini ortamdan okur (üretilen testte <c>Gizli("TP_TESTVERI_…")</c>). Ad biçimi
    /// bozuksa <see cref="ArgumentException"/>, tanımsızsa <see cref="InvalidOperationException"/>
    /// (değer iletide yer almaz).
    /// </summary>
    protected static string Gizli(string ad)
    {
        if (ad is null || !SirAdi.IsMatch(ad))
        {
            throw new ArgumentException($"gizli test verisi adı geçersiz: '{ad}' (beklenen: {SirAdi})");
        }
        string? deger = Environment.GetEnvironmentVariable(ad);
        if (string.IsNullOrEmpty(deger))
        {
            // Koşu hesabı parolası (TP_TESTVERI_KOSU_<KULLANICI>): runner vermediyse bayinin koşu/seed parolası.
            deger = Bayiler.KosuParolasiAdla(ad);
        }
        if (string.IsNullOrEmpty(deger))
        {
            throw new InvalidOperationException($"gizli test verisi tanımsız: {ad} (koşu ortamında verilmeli)");
        }
        return deger;
    }

    /// <summary>Metot <paramref name="kategori"/> kategorisinde mi?</summary>
    protected static bool Kategoride(string kategori)
    {
        IList? kategoriler = TestContext.CurrentContext.Test.Properties["Category"] as IList;
        return kategoriler is not null && kategoriler.Contains(kategori);
    }

    [SetUp]
    public void TabanHazirla()
    {
        ayarlar = Ayarlar.Oku();
        ayarlar.Platform();
        bayi = Bayiler.SinifIcin(GetType(), 0);

        TestVerisi.Kip kip = TestVerisi.KipSec(ayarlar);
        if (kip == TestVerisi.Kip.YalnizSepet && Kategoride(SifirVeri))
        {
            Assert.Ignore($"TP_E2E_NO_RESET=1: sipariş geçmişi silinemez, '{SifirVeri}' testi atlandı");
        }

        kilit = BayiKilidi.Al(BayiKilidi.Dizin(ayarlar.DemoApiUrl), bayi.KullaniciAdi, ayarlar.BayiKilidiBekleme);
        veri = new TestVerisi(ayarlar);
        if (kip == TestVerisi.Kip.Sifirlama)
        {
            veri.Sifirla(bayi.KullaniciAdi);
            TestVerisi.Kirilma? istenen = TestVerisi.KirilmaSec(ayarlar);
            if (istenen is not null)
            {
                kirilma = istenen;
                veri.Kir(kirilma, bayi.KullaniciAdi, true);
            }
        }
        else
        {
            veri.SepetiBosalt(bayi);
        }

        surucu = SurucuFabrikasi.Olustur(ayarlar);
        oturum = new UygulamaOturumu(surucu, new Bekle(ayarlar.Bekleme));

        if (Attribute.IsDefined(GetType(), typeof(OturumAcikAttribute), inherit: true))
        {
            GirisEkrani.Ac();
            GirisEkrani.GirisYap(bayi.KullaniciAdi, bayi.Parola);
            oturum.Bekle.Kosul(
                $"arayüzden giriş tamamlanmadı: giriş başarısız (kimlik '{Kimlikler.Menu.BAYI_ADI}')",
                () => surucu.FindElements(Kimlik.Bul(Kimlikler.Menu.BAYI_ADI)).Count > 0);
        }
        HazirlikSonrasi();
    }

    /// <summary>Alt sınıf için: hazırlıktan sonra, testten önce ortak adım (web: <c>test.beforeEach</c>).</summary>
    protected virtual void HazirlikSonrasi()
    {
    }

    [TearDown]
    public void TabanKapat()
    {
        bool basarisiz = TestContext.CurrentContext.Result.Outcome.Status == TestStatus.Failed;
        try
        {
            if (surucu is not null && basarisiz && ayarlar is not null)
            {
                Kanit.Topla(surucu, ayarlar.KanitDizini, GetType().Name, TestContext.CurrentContext.Test.MethodName ?? "test");
            }
        }
        finally
        {
            try
            {
                if (surucu is not null)
                {
                    try
                    {
                        surucu.Quit();
                    }
                    catch (WebDriverException e)
                    {
                        TestContext.Progress.WriteLine($"uyarı: Appium oturumu kapatılamadı ({e.GetType().Name})");
                    }
                }
                if (kirilma is not null && veri is not null && bayi is not null)
                {
                    try
                    {
                        veri.Kir(kirilma, bayi.KullaniciAdi, false);
                    }
                    catch (InvalidOperationException e)
                    {
                        // Sonraki testin /test/reset'i kırılmayı da kaldırır.
                        TestContext.Progress.WriteLine($"uyarı: kırılma geri alınamadı ({e.Message})");
                    }
                }
            }
            finally
            {
                kilit?.Dispose();
                veri?.Dispose();
                surucu = null;
                oturum = null;
                kilit = null;
                veri = null;
                kirilma = null;
                girisEkrani = null;
                katalogEkrani = null;
                sepetEkrani = null;
                onayEkrani = null;
                siparisEkrani = null;
            }
        }
    }

    private UygulamaOturumu Oturum =>
        oturum ?? throw new InvalidOperationException("uygulama oturumu yok (TestTabani hazırlığı başarısız)");

    /// <summary>Testin bayisi (elle yazılmış testler için; web: <c>dealer</c> fikstürü).</summary>
    protected Bayiler.BayiBilgisi SeciliBayi =>
        bayi ?? throw new InvalidOperationException("bayi seçilmedi (TestTabani hazırlığı başarısız)");

    /// <summary>Giriş ekranı.</summary>
    protected GirisEkrani GirisEkrani => girisEkrani ??= new GirisEkrani(Oturum);

    /// <summary>Ürün kataloğu ekranı.</summary>
    protected KatalogEkrani KatalogEkrani => katalogEkrani ??= new KatalogEkrani(Oturum);

    /// <summary>Sepet ekranı.</summary>
    protected SepetEkrani SepetEkrani => sepetEkrani ??= new SepetEkrani(Oturum);

    /// <summary>Sipariş onayı ekranı.</summary>
    protected OnayEkrani OnayEkrani => onayEkrani ??= new OnayEkrani(Oturum);

    /// <summary>Sipariş geçmişi ekranı.</summary>
    protected SiparisEkrani SiparisEkrani => siparisEkrani ??= new SiparisEkrani(Oturum);
}

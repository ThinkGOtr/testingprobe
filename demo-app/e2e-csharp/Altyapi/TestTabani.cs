using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Allure.NUnit;
using Antreklabs.Bayi.Pages;
using Microsoft.Playwright;
using NUnit.Framework;
using NUnit.Framework.Interfaces;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Tüm web testlerinin tabanı (TS: tests/fixtures.ts <c>test</c> fikstürleri; Java: <c>TestTabani</c>).
///
/// Her test için, sırasıyla: işçi yuvası alınır (en çok <see cref="Bayiler.E2E"/> kadar eşzamanlı test);
/// bayi seçilir (<see cref="BayiAttribute"/> ya da yuvanın bayisi) ve süreçler arası kilitle alınır;
/// bayinin verisi sıfırlanır (<c>POST /test/reset</c>) ya da yalnız sepeti boşaltılır;
/// <c>TP_FAULT</c> / <c>BREAK_CAMPAIGN=1</c> ise bayi kapsamlı kırılma açılır (<c>POST /test/break</c>);
/// yeni <see cref="IBrowserContext"/> + <see cref="IPage"/> açılır (baseURL, tr-TR, Europe/Istanbul) ve
/// trace kaydı başlar; <see cref="OturumAcikAttribute"/> sınıflarda bayi API ile oturum açar; sonra
/// <see cref="HazirlikSonrasiAsync"/> (TS: <c>test.beforeEach</c>).
/// Test bitince: başarısızsa kanıt (<c>&lt;KANIT_DIZINI&gt;/&lt;Sınıf&gt;.&lt;Metot&gt;/</c>), bağlam kapanır,
/// kırılma geri alınır, kilit ve yuva bırakılır.
///
/// Fikstür erişimi (014 §3.2): erişimci adı page object sınıf adıdır — <see cref="LoginPage"/>,
/// <see cref="CatalogPage"/>, <see cref="CartPage"/>, <see cref="OrderPage"/>. Üretilen testler
/// yalnız bu erişimcileri ve <see cref="Gizli"/>'yi kullanır.
/// </summary>
[AllureNUnit]
public abstract class TestTabani
{
    /// <summary>Yalnız sıfırlanmış veriyle anlamlı testlerin kategorisi (TS: <c>@sifir-veri</c>).</summary>
    public const string SifirVeri = "sifir-veri";

    /// <summary>Gizli test verisi ortam değişkeni adı (013 K19; core <c>SIR_ADI_RE</c> ile aynı).</summary>
    public static readonly Regex SirAdi = new("^TP_TESTVERI_[A-Z0-9_]{1,64}$", RegexOptions.CultureInvariant);

    private const int Genislik = 1280;
    private const int Yukseklik = 720;

    private static readonly bool[] Yuvalar = new bool[Bayiler.E2E.Count];
    private static readonly SemaphoreSlim BosYuva = new(Yuvalar.Length, Yuvalar.Length);

    private Ayarlar? _ayarlar;
    private int _yuva = -1;
    private BayiBilgisi? _bayi;
    private BayiKilidi? _kilit;
    private TestVerisi? _veri;
    private string? _kirilmaKapat;
    private IBrowserContext? _baglam;
    private IPage? _page;
    private LoginPage? _loginPage;
    private CatalogPage? _catalogPage;
    private CartPage? _cartPage;
    private OrderPage? _orderPage;

    /// <summary>
    /// Gizli test verisi (013 K19): <c>TP_TESTVERI_*</c> ortam değişkenini okur. Ad biçimi bozuksa ya da
    /// değişken tanımsız/boşsa açıklayıcı hata (null geçmez; değer hata iletisine yazılmaz).
    /// </summary>
    protected static string Gizli(string ad)
    {
        if (ad is null || !SirAdi.IsMatch(ad))
        {
            throw new ArgumentException($"gizli test verisi adı geçersiz: '{ad}' (beklenen: {SirAdi})");
        }
        var deger = Environment.GetEnvironmentVariable(ad);
        if (string.IsNullOrEmpty(deger))
        {
            throw new InvalidOperationException(
                $"gizli test verisi tanımsız: {ad} ortam değişkeni yok (TP test verisi sırrı koşu ortamına verilmeli)");
        }
        return deger;
    }

    /// <summary>Boş işçi yuvası; hepsi doluysa bir yuva boşalana dek en çok <paramref name="bekleme"/> bekler.</summary>
    public static int YuvaAl(TimeSpan bekleme)
    {
        if (!BosYuva.Wait(bekleme < TimeSpan.Zero ? TimeSpan.Zero : bekleme))
        {
            throw new InvalidOperationException(
                $"Boş işçi yuvası {(long)bekleme.TotalMilliseconds} ms içinde açılmadı: en fazla {Yuvalar.Length} "
                + "eşzamanlı test (bayi kullanıcısı sayısı); LevelOfParallelism değerini düşürün.");
        }
        lock (Yuvalar)
        {
            for (var i = 0; i < Yuvalar.Length; i++)
            {
                if (!Yuvalar[i])
                {
                    Yuvalar[i] = true;
                    return i;
                }
            }
        }
        BosYuva.Release();
        throw new InvalidOperationException("işçi yuvası sayacı tutarsız");
    }

    /// <summary>Yuvayı bırakır; <c>yuva &lt; 0</c> ya da zaten boşsa etkisiz.</summary>
    public static void YuvaBirak(int yuva)
    {
        if (yuva < 0)
        {
            return;
        }
        lock (Yuvalar)
        {
            if (!Yuvalar[yuva])
            {
                return;
            }
            Yuvalar[yuva] = false;
        }
        BosYuva.Release();
    }

    /// <summary>Testin NUnit kategorileri (metot + sınıf).</summary>
    protected static bool Kategoride(string kategori)
    {
        var props = TestContext.CurrentContext.Test.Properties;
        foreach (var k in props[NUnit.Framework.Internal.PropertyNames.Category])
        {
            if (Equals(k, kategori))
            {
                return true;
            }
        }
        return false;
    }

    [SetUp]
    public async Task TabanHazirlaAsync()
    {
        var ayarlar = _ayarlar = Ayarlar.Oku();
        var kip = TestVerisi.Kip(ayarlar);
        if (kip == YalitimKipi.YalnizSepet && Kategoride(SifirVeri))
        {
            Assert.Ignore($"TP_E2E_NO_RESET=1: sipariş geçmişi silinemez, '{SifirVeri}' testi atlandı");
        }
        _yuva = YuvaAl(ayarlar.BayiKilidiBekleme);
        _bayi = Bayiler.SinifIcin(GetType(), _yuva);
        _kilit = BayiKilidi.Al(BayiKilidi.Dizin(ayarlar.BaseUrl, ayarlar.DemoApiUrl), _bayi.KullaniciAdi, ayarlar.BayiKilidiBekleme);
        _veri = new TestVerisi(ayarlar);
        if (kip == YalitimKipi.Sifirlama)
        {
            await _veri.SifirlaAsync(_bayi.KullaniciAdi);
            var kirilma = TestVerisi.Kirilma(ayarlar);
            if (kirilma is { } k)
            {
                _kirilmaKapat = k.Kapat;
                await _veri.KirAsync(_bayi.KullaniciAdi, k.Ac);
            }
        }
        else
        {
            await _veri.SepetiBosaltAsync(_bayi);
        }

        Assertions.SetDefaultExpectTimeout((float)ayarlar.Bekleme.TotalMilliseconds);
        var browser = await Tarayici.BrowserAsync(ayarlar);
        _baglam = await browser.NewContextAsync(new BrowserNewContextOptions
        {
            BaseURL = ayarlar.BaseUrl,
            Locale = "tr-TR",
            TimezoneId = "Europe/Istanbul",
            ViewportSize = new ViewportSize { Width = Genislik, Height = Yukseklik },
        });
        _baglam.SetDefaultTimeout((float)ayarlar.Bekleme.TotalMilliseconds);
        _baglam.SetDefaultNavigationTimeout((float)ayarlar.Gezinme.TotalMilliseconds);
        await Kanit.IzlemeyiBaslatAsync(_baglam);
        _page = await _baglam.NewPageAsync();

        if (GetType().GetCustomAttribute<OturumAcikAttribute>(inherit: true) is not null)
        {
            await SignedInAsync();
        }
        await HazirlikSonrasiAsync();
    }

    /// <summary>Alt sınıf için: hazırlıktan sonra, testten önce ortak adım (TS: <c>test.beforeEach</c>).</summary>
    protected virtual Task HazirlikSonrasiAsync() => Task.CompletedTask;

    [TearDown]
    public async Task TabanKapatAsync()
    {
        var sonuc = TestContext.CurrentContext.Result.Outcome.Status;
        var basarisiz = sonuc == TestStatus.Failed;
        try
        {
            if (_baglam is not null && _ayarlar is not null)
            {
                if (basarisiz && _page is not null)
                {
                    await Kanit.ToplaAsync(_page, _baglam, _ayarlar.KanitDizini, GetType().Name,
                        TestContext.CurrentContext.Test.MethodName ?? TestContext.CurrentContext.Test.Name);
                }
                else
                {
                    await Kanit.IzlemeyiBirakAsync(_baglam);
                }
            }
        }
        finally
        {
            try
            {
                if (_baglam is not null)
                {
                    try
                    {
                        await _baglam.CloseAsync();
                    }
                    catch (PlaywrightException e)
                    {
                        TestContext.Progress.WriteLine($"UYARI: tarayıcı bağlamı kapatılamadı: {e.Message}");
                    }
                }
                if (_kirilmaKapat is not null && _veri is not null && _bayi is not null)
                {
                    try
                    {
                        await _veri.KirAsync(_bayi.KullaniciAdi, _kirilmaKapat);
                    }
                    catch (InvalidOperationException e)
                    {
                        // Sonraki testin /test/reset'i kırılmayı da kaldırır.
                        TestContext.Progress.WriteLine($"UYARI: kırılma geri alınamadı: {e.Message}");
                    }
                }
            }
            finally
            {
                _veri?.Dispose();
                _kilit?.Dispose();
                YuvaBirak(_yuva);
                _yuva = -1;
            }
        }
    }

    private IPage Hazir() =>
        _page ?? throw new InvalidOperationException("tarayıcı sayfası yok (TestTabani hazırlığı başarısız)");

    /// <summary>Testin bayisi (TS: <c>dealer</c> fikstürü).</summary>
    protected BayiBilgisi Dealer =>
        _bayi ?? throw new InvalidOperationException("bayi seçilmedi (TestTabani hazırlığı başarısız)");

    /// <summary>
    /// Bayi API ile oturum açar; çerez sayfa bağlamıyla paylaşılır (TS: <c>signedIn</c> fikstürü).
    /// <see cref="OturumAcikAttribute"/> sınıflarda hazırlıkta kendiliğinden çağrılır.
    /// </summary>
    protected async Task SignedInAsync()
    {
        var yanit = await Hazir().APIRequest.PostAsync("/api/auth/login", new APIRequestContextOptions
        {
            DataObject = new Dictionary<string, string>
            {
                ["kullanici_adi"] = Dealer.KullaniciAdi,
                ["parola"] = Dealer.Parola,
            },
        });
        if (!yanit.Ok)
        {
            throw new InvalidOperationException($"API ile giriş başarısız: {yanit.Status}");
        }
    }

    /// <summary>Ham sayfa (yalnız elle yazılmış testler; TS: <c>page</c> fikstürü).</summary>
    protected IPage Page => Hazir();

    /// <summary>Giriş sayfası.</summary>
    protected LoginPage LoginPage => _loginPage ??= new LoginPage(Hazir());

    /// <summary>Ürün kataloğu sayfası.</summary>
    protected CatalogPage CatalogPage => _catalogPage ??= new CatalogPage(Hazir());

    /// <summary>Sepet sayfası.</summary>
    protected CartPage CartPage => _cartPage ??= new CartPage(Hazir());

    /// <summary>Sipariş onayı ve sipariş geçmişi.</summary>
    protected OrderPage OrderPage => _orderPage ??= new OrderPage(Hazir());
}

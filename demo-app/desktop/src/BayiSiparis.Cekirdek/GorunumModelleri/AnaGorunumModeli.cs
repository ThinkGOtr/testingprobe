// Uygulama kabuğu (web: App.tsx + Layout.tsx): oturum, üst menü, sepet sayacı ve ekranlar arası gezinme.
// Kurallar web ile aynı: oturumsuz → giriş; giriş sonrası → katalog; 401 → giriş ekranı.
using BayiSiparis.Cekirdek.Api;
using BayiSiparis.Cekirdek.Mvvm;

namespace BayiSiparis.Cekirdek.GorunumModelleri;

public sealed class AnaGorunumModeli : GozlemlenebilirNesne
{
    public const string UygulamaAdi = "Bayi Sipariş Portalı";

    private readonly SynchronizationContext? _arayuzBaglami;
    private Kullanici? _kullanici;
    private bool _oturumKontrolEdiliyor = true;
    private SayfaGorunumModeli? _sayfa;
    private Sepet? _sonSepet;

    public AnaGorunumModeli(IApiIstemcisi api, MesgulTakipcisi? mesgul = null)
    {
        Api = api;
        Mesgul = mesgul ?? new MesgulTakipcisi();
        _arayuzBaglami = SynchronizationContext.Current;
        Api.YetkisizErisim += (_, _) => ArayuzdeCalistir(OturumKapandi);

        KatalogaGitKomutu = new Komut(_ => KatalogaGit(), _ => OturumAcik);
        SepeteGitKomutu = new Komut(_ => SepeteGit(), _ => OturumAcik);
        SiparislereGitKomutu = new Komut(_ => SiparislereGit(), _ => OturumAcik);
        // CanExecute parametreye bakmaz: WPF, CommandParameter bağlanmadan önce null ile sorar ve sonra yeniden sormaz.
        SiparisAcKomutu = new Komut(p => { if (p is string n) { SiparisOnayinaGit(n); } }, _ => OturumAcik);
        CikisKomutu = new AsenkronKomut(_ => CikisAsync(), _ => OturumAcik);
    }

    public IApiIstemcisi Api { get; }

    public MesgulTakipcisi Mesgul { get; }

    public Kullanici? Kullanici
    {
        get => _kullanici;
        private set
        {
            if (Ayarla(ref _kullanici, value))
            {
                Bildir(nameof(OturumAcik));
                Bildir(nameof(BayiAdi));
                KatalogaGitKomutu.YenidenDegerlendir();
                SepeteGitKomutu.YenidenDegerlendir();
                SiparislereGitKomutu.YenidenDegerlendir();
                SiparisAcKomutu.YenidenDegerlendir();
                CikisKomutu.YenidenDegerlendir();
            }
        }
    }

    public bool OturumAcik => _kullanici is not null;

    /// <summary>Üst menüdeki bayi adı ("current-dealer").</summary>
    public string BayiAdi => _kullanici?.Ad ?? "";

    /// <summary>Açılıştaki oturum yoklaması sürüyor ("Yükleniyor…").</summary>
    public bool OturumKontrolEdiliyor
    {
        get => _oturumKontrolEdiliyor;
        private set => Ayarla(ref _oturumKontrolEdiliyor, value);
    }

    /// <summary>Sepetteki toplam ürün adedi ("cart-count").</summary>
    public int SepetAdedi => _sonSepet?.AdetToplam ?? 0;

    public Sepet? SonSepet => _sonSepet;

    public SayfaGorunumModeli? Sayfa
    {
        get => _sayfa;
        private set
        {
            if (Ayarla(ref _sayfa, value))
            {
                Bildir(nameof(PencereBasligi));
                Bildir(nameof(AktifMenu));
            }
        }
    }

    public string PencereBasligi => _sayfa is null ? UygulamaAdi : $"{_sayfa.Baslik} · {UygulamaAdi}";

    /// <summary>Üst menüde etkin öğe: "catalog", "cart", "orders" ya da "" (web: aria-current="page").</summary>
    public string AktifMenu => _sayfa switch
    {
        KatalogGorunumModeli => "catalog",
        SepetGorunumModeli => "cart",
        SiparislerimGorunumModeli or SiparisOnayGorunumModeli => "orders",
        _ => "",
    };

    public Komut KatalogaGitKomutu { get; }

    public Komut SepeteGitKomutu { get; }

    public Komut SiparislereGitKomutu { get; }

    /// <summary>Parametre: sipariş numarası.</summary>
    public Komut SiparisAcKomutu { get; }

    public AsenkronKomut CikisKomutu { get; }

    /// <summary>Açılış: oturum yoklaması, ardından giriş ya da katalog ekranı.</summary>
    public async Task BaslatAsync()
    {
        Kullanici? k;
        try
        {
            k = await Mesgul.IzleAsync(Api.OturumAsync());
        }
        catch (Exception)
        {
            k = null;
        }

        OturumKontrolEdiliyor = false;
        if (k is null)
        {
            OturumKapandi();
        }
        else
        {
            await GirisYapildiAsync(k);
        }
    }

    /// <summary>Başarılı giriş: kataloğa geç ve sepet sayacını yükle.</summary>
    public Task GirisYapildiAsync(Kullanici kullanici)
    {
        Kullanici = kullanici;
        KatalogaGit();
        return SepetiTazeleAsync();
    }

    public async Task SepetiTazeleAsync()
    {
        try
        {
            SepetDegisti(await Mesgul.IzleAsync(Api.SepetAsync()));
        }
        catch (Exception)
        {
            // Web ile aynı: sayaç yüklenemezse 0 gösterilir.
            _sonSepet = null;
            Bildir(nameof(SepetAdedi));
            Bildir(nameof(SonSepet));
        }
    }

    /// <summary>Ekranlar sepet değiştiğinde çağırır (sayaç güncellenir).</summary>
    public void SepetDegisti(Sepet sepet)
    {
        _sonSepet = sepet;
        Bildir(nameof(SepetAdedi));
        Bildir(nameof(SonSepet));
    }

    public void KatalogaGit()
    {
        if (OturumAcik)
        {
            Ac(new KatalogGorunumModeli(this));
        }
    }

    public void SepeteGit()
    {
        if (OturumAcik)
        {
            Ac(new SepetGorunumModeli(this));
        }
    }

    public void SiparislereGit()
    {
        if (OturumAcik)
        {
            Ac(new SiparislerimGorunumModeli(this));
        }
    }

    public void SiparisOnayinaGit(string numara)
    {
        if (OturumAcik)
        {
            Ac(new SiparisOnayGorunumModeli(this, numara));
        }
    }

    public async Task CikisAsync()
    {
        try
        {
            await Mesgul.IzleAsync(Api.CikisAsync());
        }
        catch (Exception)
        {
            // Web ile aynı: çıkış isteği başarısız olsa da yerel oturum kapatılır.
        }
        finally
        {
            OturumKapandi();
        }
    }

    /// <summary>Oturum yok/düştü: giriş ekranı.</summary>
    public void OturumKapandi()
    {
        Kullanici = null;
        _sonSepet = null;
        Bildir(nameof(SepetAdedi));
        Bildir(nameof(SonSepet));
        if (Sayfa is not GirisGorunumModeli)
        {
            Ac(new GirisGorunumModeli(this));
        }
    }

    /// <summary>Ekranı etkinleştirir, ardından yüklemesini başlatır (sıra önemli; bkz. SayfaGorunumModeli.Baslat).</summary>
    private void Ac(SayfaGorunumModeli sayfa)
    {
        Sayfa = sayfa;
        _ = sayfa.Baslat();
    }

    private void ArayuzdeCalistir(Action is_)
    {
        if (_arayuzBaglami is null || SynchronizationContext.Current == _arayuzBaglami)
        {
            is_();
        }
        else
        {
            _arayuzBaglami.Post(_ => is_(), null);
        }
    }
}

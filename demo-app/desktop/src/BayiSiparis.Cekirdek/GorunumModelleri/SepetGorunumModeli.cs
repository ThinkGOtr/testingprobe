// Sepet (web: CartPage.tsx): satırlar, kampanya, toplamlar, minimum sipariş uyarısı ve sipariş onayı.
using BayiSiparis.Cekirdek.Api;
using BayiSiparis.Cekirdek.Mvvm;

namespace BayiSiparis.Cekirdek.GorunumModelleri;

public sealed class SepetGorunumModeli : SayfaGorunumModeli
{
    private Sepet? _sepet;
    private IReadOnlyList<SepetSatiriGorunumModeli> _satirlar = [];
    private string? _hata;
    private bool _onaylaniyor;

    public SepetGorunumModeli(AnaGorunumModeli kabuk)
        : base(kabuk)
    {
        OnaylaKomutu = new AsenkronKomut(_ => OnaylaAsync(), _ => Onaylanabilir);
        // Web ile aynı: kabuktaki son sepet hemen gösterilir, ardından sunucudan tazelenir.
        if (kabuk.SonSepet is { } s)
        {
            SepetAyarla(s);
        }
    }

    public override string Baslik => "Sepet";

    public Sepet? Sepet => _sepet;

    /// <summary>"Sepet yükleniyor…" gösterilir.</summary>
    public bool Yukleniyor => _sepet is null && _hata is null;

    /// <summary>Sepet yüklenemedi (sepet hiç yok): kimliksiz hata alanı.</summary>
    public bool YuklemeHatasiVar => _sepet is null && _hata is not null;

    /// <summary>"cart-empty" görünür.</summary>
    public bool Bos => _sepet is { Satirlar.Count: 0 };

    /// <summary>"cart-table" ve özet paneli görünür.</summary>
    public bool Dolu => _sepet is { Satirlar.Count: > 0 };

    public IReadOnlyList<SepetSatiriGorunumModeli> Satirlar
    {
        get => _satirlar;
        private set => Ayarla(ref _satirlar, value);
    }

    public string AraToplamMetni => _sepet is null ? "" : Bicim.TL(_sepet.AraToplam);

    public string IndirimMetni => _sepet is null ? "" : Bicim.TL(_sepet.Indirim);

    /// <summary>İndirim varsa tutarın önünde "−" işareti gösterilir (web'de aria-hidden; kimliksiz).</summary>
    public bool IndirimVar => _sepet is not null && Bicim.Sayi(_sepet.Indirim) > 0;

    public string ToplamMetni => _sepet is null ? "" : Bicim.TL(_sepet.Toplam);

    /// <summary>"min-order-warning" metni; null iken eleman ağaçta yoktur.</summary>
    public string? MinSiparisUyarisi => _sepet?.Uyarilar.FirstOrDefault(u => u.Kod == "min_siparis")?.Mesaj;

    /// <summary>Son hata mesajı.</summary>
    public string? Hata
    {
        get => _hata;
        private set
        {
            if (Ayarla(ref _hata, value))
            {
                DurumlariBildir();
            }
        }
    }

    /// <summary>"checkout-error": sepet doluyken özet panelinde gösterilen hata.</summary>
    public string? OnayHatasi => Dolu ? _hata : null;

    /// <summary>Sepet boşken gösterilen kimliksiz hata.</summary>
    public string? BosSepetHatasi => Bos ? _hata : null;

    public bool Onaylaniyor
    {
        get => _onaylaniyor;
        private set
        {
            if (Ayarla(ref _onaylaniyor, value))
            {
                Bildir(nameof(OnayDugmesiMetni));
                OnaylaKomutu.YenidenDegerlendir();
            }
        }
    }

    /// <summary>"checkout-submit" pasif/aktif durumu (web: disabled={!onaylanabilir || busy}).</summary>
    public bool Onaylanabilir => _sepet is { Onaylanabilir: true } && !_onaylaniyor;

    public string OnayDugmesiMetni => _onaylaniyor ? "Onaylanıyor…" : "Siparişi onayla";

    public AsenkronKomut OnaylaKomutu { get; }

    protected override async Task YukleAsync()
    {
        try
        {
            var sepet = await Mesgul.IzleAsync(Api.SepetAsync());
            Kabuk.SepetDegisti(sepet);
            SepetAyarla(sepet);
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Sepet yüklenemedi.");
        }
    }

    internal async Task KaldirAsync(string urunKod)
    {
        Hata = null;
        try
        {
            var sepet = await Mesgul.IzleAsync(Api.SatirKaldirAsync(urunKod));
            Kabuk.SepetDegisti(sepet);
            SepetAyarla(sepet);
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Ürün kaldırılamadı.");
        }
    }

    public async Task OnaylaAsync()
    {
        if (!Onaylanabilir)
        {
            return;
        }

        Hata = null;
        Onaylaniyor = true;
        try
        {
            var siparis = await Mesgul.IzleAsync(Api.SiparisVerAsync());
            var sepet = await Mesgul.IzleAsync(Api.SepetAsync());
            Kabuk.SepetDegisti(sepet);
            // Web ile aynı: başarıda düğme "Onaylanıyor…" kalır; onay ekranına geçilir.
            Kabuk.SiparisOnayinaGit(siparis.Numara);
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Sipariş onaylanamadı.");
            Onaylaniyor = false;
        }
    }

    private void SepetAyarla(Sepet sepet)
    {
        _sepet = sepet;
        Satirlar = sepet.Satirlar.Select(s => new SepetSatiriGorunumModeli(this, s)).ToList();
        Bildir(nameof(Sepet));
        Bildir(nameof(AraToplamMetni));
        Bildir(nameof(IndirimMetni));
        Bildir(nameof(IndirimVar));
        Bildir(nameof(ToplamMetni));
        Bildir(nameof(MinSiparisUyarisi));
        DurumlariBildir();
    }

    private void DurumlariBildir()
    {
        Bildir(nameof(Yukleniyor));
        Bildir(nameof(YuklemeHatasiVar));
        Bildir(nameof(Bos));
        Bildir(nameof(Dolu));
        Bildir(nameof(OnayHatasi));
        Bildir(nameof(BosSepetHatasi));
        Bildir(nameof(Onaylanabilir));
        OnaylaKomutu.YenidenDegerlendir();
    }
}

/// <summary>Sepetteki tek satır ("cart-line-&lt;kod&gt;").</summary>
public sealed class SepetSatiriGorunumModeli
{
    internal SepetSatiriGorunumModeli(SepetGorunumModeli sepet, SepetSatiri satir)
    {
        Satir = satir;
        KaldirKomutu = new AsenkronKomut(_ => sepet.KaldirAsync(satir.UrunKod));
    }

    public SepetSatiri Satir { get; }

    public string UrunKod => Satir.UrunKod;

    public string UrunAd => Satir.UrunAd;

    public bool KampanyaVar => Satir.Kampanya is not null;

    public string Kampanya => Satir.Kampanya ?? "";

    public string BirimFiyatMetni => Bicim.TL(Satir.BirimFiyat);

    /// <summary>"cart-line-qty-&lt;kod&gt;" metni.</summary>
    public string AdetMetni => Satir.Adet.ToString(System.Globalization.CultureInfo.InvariantCulture);

    /// <summary>"cart-line-free-&lt;kod&gt;" metni.</summary>
    public string BedavaAdetMetni => Satir.BedavaAdet.ToString(System.Globalization.CultureInfo.InvariantCulture);

    /// <summary>"cart-line-total-&lt;kod&gt;" metni.</summary>
    public string SatirTutariMetni => Bicim.TL(Satir.SatirTutari);

    /// <summary>"cart-line-remove-&lt;kod&gt;" düğmesinin erişilebilir adı (web: aria-label).</summary>
    public string KaldirEtiketi => $"{Satir.UrunAd} ürününü sepetten kaldır";

    public AsenkronKomut KaldirKomutu { get; }

    public override string ToString() => UrunKod;
}

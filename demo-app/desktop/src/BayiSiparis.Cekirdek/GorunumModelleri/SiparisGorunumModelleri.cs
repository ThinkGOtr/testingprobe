// Sipariş onayı (web: OrderConfirmationPage.tsx) ve sipariş geçmişi (web: OrdersPage.tsx).
using System.Globalization;
using BayiSiparis.Cekirdek.Api;
using BayiSiparis.Cekirdek.Mvvm;

namespace BayiSiparis.Cekirdek.GorunumModelleri;

public sealed class SiparisOnayGorunumModeli : SayfaGorunumModeli
{
    private Siparis? _siparis;
    private string? _hata;

    public SiparisOnayGorunumModeli(AnaGorunumModeli kabuk, string numara)
        : base(kabuk)
    {
        Numara = numara;
    }

    public override string Baslik => "Sipariş onayı";

    public string Numara { get; }

    public Siparis? Siparis
    {
        get => _siparis;
        private set
        {
            if (Ayarla(ref _siparis, value))
            {
                Bildir(nameof(Yuklendi));
                Bildir(nameof(Yukleniyor));
                Bildir(nameof(SiparisNumarasi));
                Bildir(nameof(AdetToplamMetni));
                Bildir(nameof(IndirimMetni));
                Bildir(nameof(ToplamMetni));
            }
        }
    }

    public string? Hata
    {
        get => _hata;
        private set
        {
            if (Ayarla(ref _hata, value))
            {
                Bildir(nameof(Yukleniyor));
                Bildir(nameof(Yuklendi));
            }
        }
    }

    public bool Yukleniyor => _siparis is null && _hata is null;

    /// <summary>"order-confirmation" alanı görünür.</summary>
    public bool Yuklendi => _siparis is not null && _hata is null;

    /// <summary>"order-number" metni.</summary>
    public string SiparisNumarasi => _siparis?.Numara ?? "";

    public string AdetToplamMetni => _siparis?.AdetToplam.ToString(CultureInfo.InvariantCulture) ?? "";

    /// <summary>"order-discount" metni.</summary>
    public string IndirimMetni => _siparis is null ? "" : Bicim.TL(_siparis.Indirim);

    /// <summary>"order-total" metni.</summary>
    public string ToplamMetni => _siparis is null ? "" : Bicim.TL(_siparis.Toplam);

    protected override async Task YukleAsync()
    {
        try
        {
            Siparis = await Mesgul.IzleAsync(Api.SiparisAsync(Numara));
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Sipariş yüklenemedi.");
        }
    }
}

public sealed class SiparislerimGorunumModeli : SayfaGorunumModeli
{
    private readonly TimeZoneInfo? _saatDilimi;
    private IReadOnlyList<SiparisSatiriOzetiGorunumModeli>? _siparisler;
    private string? _hata;

    public SiparislerimGorunumModeli(AnaGorunumModeli kabuk, TimeZoneInfo? saatDilimi = null)
        : base(kabuk)
    {
        _saatDilimi = saatDilimi;
    }

    public override string Baslik => "Siparişlerim";

    /// <summary>"orders-table" satırları ("order-row-&lt;numara&gt;"); yüklenene kadar null.</summary>
    public IReadOnlyList<SiparisSatiriOzetiGorunumModeli>? Siparisler
    {
        get => _siparisler;
        private set
        {
            if (Ayarla(ref _siparisler, value))
            {
                DurumlariBildir();
            }
        }
    }

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

    public bool Yukleniyor => _siparisler is null && _hata is null;

    /// <summary>"orders-empty" görünür.</summary>
    public bool Bos => _siparisler is { Count: 0 };

    /// <summary>"orders-table" görünür.</summary>
    public bool Dolu => _siparisler is { Count: > 0 };

    protected override async Task YukleAsync()
    {
        try
        {
            var liste = await Mesgul.IzleAsync(Api.SiparislerAsync());
            Siparisler = liste.Select(o => new SiparisSatiriOzetiGorunumModeli(o, _saatDilimi)).ToList();
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Siparişler yüklenemedi.");
        }
    }

    private void DurumlariBildir()
    {
        Bildir(nameof(Yukleniyor));
        Bildir(nameof(Bos));
        Bildir(nameof(Dolu));
    }
}

/// <summary>Sipariş geçmişindeki tek satır.</summary>
public sealed class SiparisSatiriOzetiGorunumModeli
{
    internal SiparisSatiriOzetiGorunumModeli(SiparisOzeti ozet, TimeZoneInfo? saatDilimi)
    {
        Ozet = ozet;
        TarihMetni = Bicim.TarihSaat(ozet.Olusturma, saatDilimi);
    }

    public SiparisOzeti Ozet { get; }

    public string Numara => Ozet.Numara;

    public string TarihMetni { get; }

    public string AdetMetni => Ozet.AdetToplam.ToString(CultureInfo.InvariantCulture);

    public string IndirimMetni => Bicim.TL(Ozet.Indirim);

    /// <summary>"order-total-&lt;numara&gt;" metni.</summary>
    public string ToplamMetni => Bicim.TL(Ozet.Toplam);

    public override string ToString() => Numara;
}

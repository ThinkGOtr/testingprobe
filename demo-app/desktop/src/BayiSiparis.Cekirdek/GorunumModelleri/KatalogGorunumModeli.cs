// Ürün kataloğu (web: CatalogPage.tsx).
using System.Globalization;
using BayiSiparis.Cekirdek.Api;
using BayiSiparis.Cekirdek.Mvvm;

namespace BayiSiparis.Cekirdek.GorunumModelleri;

public sealed class KatalogGorunumModeli : SayfaGorunumModeli
{
    public const int AzamiAdet = 999;

    private IReadOnlyList<UrunKartiGorunumModeli>? _urunler;
    private string? _hata;

    public KatalogGorunumModeli(AnaGorunumModeli kabuk)
        : base(kabuk)
    {
    }

    public override string Baslik => "Katalog";

    /// <summary>Ürün kartları ("product-list" içinde "product-card-&lt;kod&gt;"); yüklenene kadar null.</summary>
    public IReadOnlyList<UrunKartiGorunumModeli>? Urunler
    {
        get => _urunler;
        private set
        {
            if (Ayarla(ref _urunler, value))
            {
                Bildir(nameof(Yukleniyor));
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
            }
        }
    }

    /// <summary>"Ürünler yükleniyor…" gösterilir.</summary>
    public bool Yukleniyor => _urunler is null && _hata is null;

    protected override async Task YukleAsync()
    {
        try
        {
            var urunler = await Mesgul.IzleAsync(Api.UrunlerAsync());
            Urunler = urunler.Select(u => new UrunKartiGorunumModeli(this, u)).ToList();
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Ürünler yüklenemedi.");
        }
    }

    /// <summary>Web'deki Number(raw) kuralı: boşluk kırpılır, tam sayı ve 1..999 aralığında olmalı.</summary>
    internal static int? AdetCoz(string? metin)
    {
        var m = (metin ?? "").Trim();
        if (m.Length == 0
            || !decimal.TryParse(
                m,
                NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint | NumberStyles.AllowExponent,
                CultureInfo.InvariantCulture,
                out var d)
            || d != decimal.Truncate(d)
            || d < 1
            || d > AzamiAdet)
        {
            return null;
        }

        return (int)d;
    }

    internal async Task EkleAsync(UrunKartiGorunumModeli kart)
    {
        var adet = AdetCoz(kart.AdetMetni);
        if (adet is null)
        {
            BildirimGoster(kart, $"Adet 1 ile {AzamiAdet} arasında olmalıdır.", basarili: false);
            return;
        }

        kart.Ekleniyor = true;
        BildirimGoster(null, "", basarili: false);
        try
        {
            var sepet = await Mesgul.IzleAsync(Api.SepeteEkleAsync(kart.Kod, adet.Value));
            Kabuk.SepetDegisti(sepet);
            BildirimGoster(kart, $"{adet} adet sepete eklendi.", basarili: true);
        }
        catch (Exception e)
        {
            BildirimGoster(kart, Mesaj(e, "Sepete eklenemedi."), basarili: false);
        }
        finally
        {
            kart.Ekleniyor = false;
        }
    }

    /// <summary>Web ile aynı: aynı anda tek kartta bildirim görünür; diğer kartların metni boşalır.</summary>
    private void BildirimGoster(UrunKartiGorunumModeli? hedef, string metin, bool basarili)
    {
        foreach (var k in _urunler ?? [])
        {
            if (ReferenceEquals(k, hedef))
            {
                k.BildirimAyarla(metin, basarili ? "ok" : "err");
            }
            else
            {
                k.BildirimAyarla("", "");
            }
        }
    }
}

/// <summary>Tek ürün kartı.</summary>
public sealed class UrunKartiGorunumModeli : GozlemlenebilirNesne
{
    private readonly KatalogGorunumModeli _katalog;
    private string _adetMetni = "1";
    private bool _ekleniyor;
    private string _bildirim = "";
    private string _bildirimDurumu = "";

    internal UrunKartiGorunumModeli(KatalogGorunumModeli katalog, Urun urun)
    {
        _katalog = katalog;
        Urun = urun;
        EkleKomutu = new AsenkronKomut(_ => _katalog.EkleAsync(this), _ => !_ekleniyor);
    }

    public Urun Urun { get; }

    public string Kod => Urun.Kod;

    public string Ad => Urun.Ad;

    /// <summary>Görsel yer tutucudaki baş harf.</summary>
    public string BasHarf => Urun.Ad.Length > 0 ? Urun.Ad[..1] : "";

    /// <summary>"product-price-&lt;kod&gt;" metni, ör. "150,00 TL".</summary>
    public string FiyatMetni => Bicim.TL(Urun.Fiyat);

    public bool KampanyaVar => Urun.Kampanya is not null;

    public string KampanyaMetni => Urun.Kampanya is null ? "" : $"Kampanya: {Urun.Kampanya}";

    /// <summary>"qty-input-&lt;kod&gt;" değeri.</summary>
    public string AdetMetni
    {
        get => _adetMetni;
        set => Ayarla(ref _adetMetni, value ?? "");
    }

    public bool Ekleniyor
    {
        get => _ekleniyor;
        internal set
        {
            if (Ayarla(ref _ekleniyor, value))
            {
                EkleKomutu.YenidenDegerlendir();
            }
        }
    }

    /// <summary>"product-status-&lt;kod&gt;" metni (boş olabilir; eleman her zaman ağaçtadır).</summary>
    public string Bildirim
    {
        get => _bildirim;
        private set => Ayarla(ref _bildirim, value);
    }

    /// <summary>"ok", "err" ya da "" — UI Automation ItemStatus olarak da yayınlanır.</summary>
    public string BildirimDurumu
    {
        get => _bildirimDurumu;
        private set => Ayarla(ref _bildirimDurumu, value);
    }

    public AsenkronKomut EkleKomutu { get; }

    internal void BildirimAyarla(string metin, string durum)
    {
        Bildirim = metin;
        BildirimDurumu = durum;
    }

    public override string ToString() => Kod;
}

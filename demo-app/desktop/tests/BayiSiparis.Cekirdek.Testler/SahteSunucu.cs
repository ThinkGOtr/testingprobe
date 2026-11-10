// Sahte demo API: HttpMessageHandler düzeyinde istekleri yanıtlar ve kaydeder (ağ yok).
using System.Net;
using System.Text;
using System.Text.Json;
using BayiSiparis.Cekirdek.Api;

namespace BayiSiparis.Cekirdek.Testler;

internal sealed class SahteSunucu : HttpMessageHandler
{
    public const string Taban = "http://demo.test/api";

    private readonly Dictionary<string, Queue<Func<HttpRequestMessage, Task<HttpResponseMessage>>>> _sirali = new();
    private readonly Dictionary<string, Func<HttpRequestMessage, Task<HttpResponseMessage>>> _kalici = new();

    public List<(string Anahtar, string? Govde)> Istekler { get; } = [];

    /// <summary>"GET /cart" gibi anahtara kalıcı yanıt.</summary>
    public SahteSunucu Yanit(string anahtar, int durum, object? govde = null)
    {
        _kalici[anahtar] = _ => Task.FromResult(Olustur(durum, govde));
        return this;
    }

    /// <summary>Tek seferlik yanıt (kalıcı yanıttan önce tüketilir).</summary>
    public SahteSunucu BirKez(string anahtar, int durum, object? govde = null)
    {
        Kuyruk(anahtar).Enqueue(_ => Task.FromResult(Olustur(durum, govde)));
        return this;
    }

    /// <summary>Test elle tamamlayana kadar bekleyen tek seferlik yanıt.</summary>
    public TaskCompletionSource<HttpResponseMessage> Bekleyen(string anahtar)
    {
        var tcs = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
        Kuyruk(anahtar).Enqueue(_ => tcs.Task);
        return tcs;
    }

    /// <summary>Bağlantı hatası (sunucu kapalı).</summary>
    public SahteSunucu Kopuk(string anahtar)
    {
        _kalici[anahtar] = _ => throw new HttpRequestException("bağlantı reddedildi");
        return this;
    }

    public static HttpResponseMessage Olustur(int durum, object? govde)
    {
        var yanit = new HttpResponseMessage((HttpStatusCode)durum);
        if (govde is not null)
        {
            var metin = govde as string ?? JsonSerializer.Serialize(govde);
            yanit.Content = new StringContent(metin, Encoding.UTF8, "application/json");
        }

        return yanit;
    }

    public ApiIstemcisi Istemci() => new(Taban, this);

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage istek, CancellationToken iptal)
    {
        var yol = istek.RequestUri!.AbsolutePath;
        Assert.StartsWith("/api/", yol);
        var anahtar = $"{istek.Method} {Uri.UnescapeDataString(yol["/api".Length..])}";
        var govde = istek.Content is null ? null : await istek.Content.ReadAsStringAsync(iptal);
        Istekler.Add((anahtar, govde));

        if (_sirali.TryGetValue(anahtar, out var q) && q.Count > 0)
        {
            return await q.Dequeue()(istek);
        }

        if (_kalici.TryGetValue(anahtar, out var f))
        {
            return await f(istek);
        }

        return Olustur(404, new { detail = $"Sahte sunucuda yok: {anahtar}" });
    }

    private Queue<Func<HttpRequestMessage, Task<HttpResponseMessage>>> Kuyruk(string anahtar)
    {
        if (!_sirali.TryGetValue(anahtar, out var q))
        {
            _sirali[anahtar] = q = new();
        }

        return q;
    }
}

/// <summary>API yanıt gövdeleri (demo API'nin gerçek JSON şekli).</summary>
internal static class Veri
{
    public static object Kullanici(string ad = "Bayi İki") => new { kullanici_adi = "bayi2", ad };

    public static object[] Urunler() =>
    [
        new { kod = "P-001", ad = "Portakal Gazozu 1L", fiyat = "25.00", kampanya = "6 al 1 bedava" },
        new { kod = "P-002", ad = "Limonata 330ml", fiyat = "15.00", kampanya = (string?)null },
    ];

    public static object SepetSatiri(string kod, int adet, int bedava, string tutar, string? kampanya = null) => new
    {
        urun_kod = kod,
        urun_ad = kod == "P-001" ? "Portakal Gazozu 1L" : "Limonata 330ml",
        birim_fiyat = "25.00",
        adet,
        kampanya,
        bedava_adet = bedava,
        ucretli_adet = adet - bedava,
        ara_tutar = "175.00",
        indirim = "25.00",
        satir_tutari = tutar,
    };

    public static object Sepet(
        object[] satirlar,
        int adet = 0,
        string ara = "0.00",
        string indirim = "0.00",
        string toplam = "0.00",
        bool onaylanabilir = false,
        string? minUyari = null) => new
    {
        satirlar,
        adet_toplam = adet,
        ara_toplam = ara,
        indirim,
        toplam,
        min_siparis_tutari = "750.00",
        min_siparis_saglandi = minUyari is null,
        onaylanabilir,
        uyarilar = minUyari is null ? Array.Empty<object>() : [new { kod = "min_siparis", mesaj = minUyari }],
    };

    public static object BosSepet() => Sepet([]);

    public static object Siparis(string numara = "SP-000001") => new
    {
        numara,
        olusturma = "2026-11-08T11:30:00+00:00",
        adet_toplam = 7,
        ara_toplam = "175.00",
        indirim = "25.00",
        toplam = "1250.00",
        satirlar = new[]
        {
            new { urun_kod = "P-001", urun_ad = "Portakal Gazozu 1L", birim_fiyat = "25.00", adet = 7, bedava_adet = 1, satir_tutari = "150.00" },
        },
    };
}

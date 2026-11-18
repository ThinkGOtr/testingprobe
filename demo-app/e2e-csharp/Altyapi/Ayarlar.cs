using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Koşum ayarları: ortam değişkeni, yoksa varsayılan. Ortam adları TypeScript e2e ve e2e-java ile
/// aynıdır (<c>BASE_URL</c>, <c>DEMO_API_URL</c> / <c>API_URL</c>, <c>DEMOAPP_TEST_TOKEN</c>,
/// <c>BREAK_CAMPAIGN</c>, <c>TP_FAULT</c>, <c>TP_E2E_NO_RESET</c>, …). Sır (demo test token'ı)
/// yalnız ortamdan gelir; depoda varsayılanı yoktur.
/// </summary>
public sealed class Ayarlar
{
    /// <summary>Ayar → ortam değişkenleri (öncelik sırasıyla; README tablosu bununla aynıdır).</summary>
    public static readonly IReadOnlyDictionary<string, string[]> OrtamKarsiligi = new Dictionary<string, string[]>
    {
        ["base.url"] = new[] { "BASE_URL" },
        ["demo.api.url"] = new[] { "DEMO_API_URL", "API_URL" },
        ["demoapp.test.token"] = new[] { "DEMOAPP_TEST_TOKEN" },
        ["break.campaign"] = new[] { "BREAK_CAMPAIGN" },
        ["tp.fault"] = new[] { "TP_FAULT" },
        ["tp.e2e.no.reset"] = new[] { "TP_E2E_NO_RESET" },
        ["headless"] = new[] { "HEADLESS" },
        ["bekleme.ms"] = new[] { "BEKLEME_MS" },
        ["gezinme.ms"] = new[] { "GEZINME_MS" },
        ["bayi.kilit.ms"] = new[] { "BAYI_KILIT_MS" },
        ["kanit.dizini"] = new[] { "KANIT_DIZINI" },
    };

    /// <summary>Ekilmiş hata kodunun biçimi (toolchain <c>/run</c> <c>fault</c> ve TS FAULT_PATTERN ile aynı).</summary>
    public static readonly Regex HataKoduKalibi = new("^[a-z0-9_]{1,40}$", RegexOptions.CultureInvariant);

    private readonly Func<string, string?> _ortam;

    private Ayarlar(Func<string, string?> ortam) => _ortam = ortam;

    /// <summary>Süreç ortamından ayarlar.</summary>
    public static Ayarlar Oku() => new(Environment.GetEnvironmentVariable);

    /// <summary>Birim testleri için: verilen ortam haritasından ayar.</summary>
    public static Ayarlar Haritadan(IReadOnlyDictionary<string, string> ortam) =>
        new(ad => ortam.TryGetValue(ad, out var v) ? v : null);

    private string? Deger(string ad)
    {
        foreach (var o in OrtamKarsiligi[ad])
        {
            var v = _ortam(o);
            if (!string.IsNullOrWhiteSpace(v))
            {
                return v.Trim();
            }
        }
        return null;
    }

    private long Sayi(string ad, long varsayilan)
    {
        var v = Deger(ad);
        if (v is null)
        {
            return varsayilan;
        }
        if (!long.TryParse(v, NumberStyles.Integer, CultureInfo.InvariantCulture, out var n))
        {
            throw new ArgumentException($"{ad} sayı olmalı: '{v}'");
        }
        return n;
    }

    /// <summary>Web uygulamasının kökü; varsayılan compose'daki demo-app-web.</summary>
    public string BaseUrl => (Deger("base.url") ?? "http://127.0.0.1:8081").TrimEnd('/');

    /// <summary>/test/* uçlarının kökü; verilmezse web vekili (<c>&lt;BASE_URL&gt;/api</c>).</summary>
    public string DemoApiUrl => Deger("demo.api.url")?.TrimEnd('/') ?? BaseUrl + "/api";

    /// <summary>/test/* paylaşılan sırrı; yalnız ortamdan.</summary>
    public string? TestToken => Deger("demoapp.test.token");

    /// <summary>"Kırarak doğrula": BREAK_CAMPAIGN=1 iken bayinin kampanya kuralı test süresince bozulur.</summary>
    public bool KampanyaKirik => Deger("break.campaign") == "1";

    /// <summary>Ekilmiş hata kodu (TP_FAULT); biçimi bozuksa açıklayıcı hata.</summary>
    public string? HataKodu
    {
        get
        {
            var v = Deger("tp.fault");
            if (v is not null && !HataKoduKalibi.IsMatch(v))
            {
                throw new ArgumentException($"TP_FAULT geçersiz: '{v}' (beklenen biçim: {HataKoduKalibi})");
            }
            return v;
        }
    }

    /// <summary>TP_E2E_NO_RESET=1: token yokken yalnızca sepet yalıtımı.</summary>
    public bool SifirlamaYok => Deger("tp.e2e.no.reset") == "1";

    /// <summary>Tarayıcı penceresiz mi; varsayılan evet (<c>HEADLESS=false</c> ya da <c>0</c> ile pencereli).</summary>
    public bool Headless
    {
        get
        {
            var v = (Deger("headless") ?? "true").ToLowerInvariant();
            return !(v == "false" || v == "0");
        }
    }

    /// <summary>Beklenti ve eylem bekleme üst sınırı (TS: expect.timeout / actionTimeout = 5 sn).</summary>
    public TimeSpan Bekleme => TimeSpan.FromMilliseconds(Sayi("bekleme.ms", 5_000));

    /// <summary>Sayfa gezinme üst sınırı (TS: navigationTimeout = 10 sn).</summary>
    public TimeSpan Gezinme => TimeSpan.FromMilliseconds(Sayi("gezinme.ms", 10_000));

    /// <summary>Bayi kilidini bekleme üst sınırı (TS: LOCK_WAIT_MS).</summary>
    public TimeSpan BayiKilidiBekleme => TimeSpan.FromMilliseconds(Sayi("bayi.kilit.ms", 40_000));

    /// <summary>Başarısız test kanıtlarının dizini (ekran görüntüsü + trace + sayfa HTML'i).</summary>
    public string KanitDizini => Deger("kanit.dizini") ?? "results/kanit";
}

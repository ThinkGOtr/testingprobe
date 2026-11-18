using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Koşum ayarları: önce ortam değişkeni, yoksa varsayılan (Java <c>altyapi/Ayarlar.java</c> ile aynı
/// adlar; .NET'te sistem özelliği yoktur, yalnız ortam). Sır (demo test token'ı) yalnız ortamdan gelir.
/// </summary>
public sealed class Ayarlar
{
    /// <summary>Ekilmiş hata kodunun biçimi (Java <c>HATA_KODU</c>).</summary>
    public static readonly Regex HataKodu = new("^[a-z0-9_]{1,40}$", RegexOptions.CultureInvariant);

    /// <summary>README tablosundaki ortam adları (sıra: README).</summary>
    public static readonly IReadOnlyList<string> OrtamAdlari = new[]
    {
        "PLATFORM", "APPIUM_URL", "APP_PATH", "APP_ID", "APP_ARGS", "APP_WORKDIR", "DEVICE_NAME",
        "DEMO_API_URL", "DEMOAPP_TEST_TOKEN", "BREAK_CAMPAIGN", "TP_FAULT", "TP_E2E_NO_RESET",
        "BEKLEME_MS", "BAYI_KILIT_MS", "KANIT_DIZINI",
    };

    private readonly Func<string, string?> ortam;

    private Ayarlar(Func<string, string?> ortam)
    {
        this.ortam = ortam;
    }

    /// <summary>Süreç ortamı.</summary>
    public static Ayarlar Oku() => new(Environment.GetEnvironmentVariable);

    /// <summary>Birim testleri için: verilen haritadan ayar.</summary>
    public static Ayarlar Haritadan(IReadOnlyDictionary<string, string> harita) =>
        new(ad => harita.TryGetValue(ad, out var v) ? v : null);

    private string? Deger(string ad)
    {
        string? v = ortam(ad);
        return string.IsNullOrWhiteSpace(v) ? null : v.Trim();
    }

    private long Sayi(string ad, long varsayilan)
    {
        string? v = Deger(ad);
        if (v is null)
        {
            return varsayilan;
        }
        if (!long.TryParse(v, NumberStyles.Integer, CultureInfo.InvariantCulture, out long n))
        {
            throw new ArgumentException($"{ad} sayı olmalı: '{v}'");
        }
        return n;
    }

    /// <summary>Hedef platform: bu proje yalnız <c>windows</c>'tur; başka değer açık hatadır.</summary>
    public string Platform()
    {
        string? p = Deger("PLATFORM");
        if (p is null)
        {
            return "windows";
        }
        if (!string.Equals(p, "windows", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                $"PLATFORM='{p}': e2e-app-csharp yalnız Windows masaüstü uygulamasını test eder (PLATFORM=windows)");
        }
        return "windows";
    }

    /// <summary>Appium sunucusu (Appium 3: temel yol "/").</summary>
    public string AppiumUrl => Deger("APPIUM_URL") ?? "http://127.0.0.1:4723";

    /// <summary>Uygulama dosyası (.exe); boşsa <see cref="AppId"/>.</summary>
    public string? AppPath => Deger("APP_PATH");

    /// <summary>Kurulu uygulamanın kimliği (AUMID ya da exe yolu).</summary>
    public string? AppId => Deger("APP_ID");

    /// <summary>Uygulama komut satırı argümanları (NovaWindows <c>appArguments</c>).</summary>
    public string? AppArgs => Deger("APP_ARGS");

    /// <summary>Uygulamanın çalışma dizini (NovaWindows <c>appWorkingDir</c>).</summary>
    public string? AppWorkdir => Deger("APP_WORKDIR");

    /// <summary>Cihaz (Windows makinesi) adı; bilgi amaçlı.</summary>
    public string? DeviceName => Deger("DEVICE_NAME");

    /// <summary>/test/* uçlarının kökü (sonundaki / kırpılır).</summary>
    public string DemoApiUrl => (Deger("DEMO_API_URL") ?? "http://127.0.0.1:8081/api").TrimEnd('/');

    /// <summary>/test/* paylaşılan sırrı; yalnızca ortamdan.</summary>
    public string? TestToken => Deger("DEMOAPP_TEST_TOKEN");

    /// <summary>BREAK_CAMPAIGN=1: bayi kapsamlı kampanya kırılması.</summary>
    public bool KampanyaKirik => Deger("BREAK_CAMPAIGN") == "1";

    /// <summary>TP_FAULT=&lt;kod&gt;: bayi kapsamlı ekilmiş hata; biçimi bozuksa açık hata.</summary>
    public string? EkilmisHata
    {
        get
        {
            string? kod = Deger("TP_FAULT");
            if (kod is not null && !HataKodu.IsMatch(kod))
            {
                throw new ArgumentException($"TP_FAULT geçersiz: '{kod}' (beklenen biçim: {HataKodu})");
            }
            return kod;
        }
    }

    /// <summary>TP_E2E_NO_RESET=1: token yokken yalnızca sepet yalıtımı.</summary>
    public bool SifirlamaYok => Deger("TP_E2E_NO_RESET") == "1";

    /// <summary>Eylem/beklenti üst sınırı (varsayılan 10 sn).</summary>
    public TimeSpan Bekleme => TimeSpan.FromMilliseconds(Sayi("BEKLEME_MS", 10_000));

    /// <summary>Bayi kilidini bekleme üst sınırı (varsayılan 40 sn).</summary>
    public TimeSpan BayiKilidiBekleme => TimeSpan.FromMilliseconds(Sayi("BAYI_KILIT_MS", 40_000));

    /// <summary>Başarısız test kanıtlarının dizini.</summary>
    public string KanitDizini => Deger("KANIT_DIZINI") ?? "kanit";
}

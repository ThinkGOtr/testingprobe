using System;
using System.Text.RegularExpressions;
using OpenQA.Selenium.Appium;
using OpenQA.Selenium.Appium.Windows;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Windows Appium seçenekleri ve sürücü (Java <c>SurucuFabrikasi.windows</c>): NovaWindows
/// (<c>automationName=NovaWindows</c>; WinAppDriver kullanılmaz). Her test YENİ oturum açar.
/// </summary>
public static class SurucuFabrikasi
{
    /// <summary>NovaWindows sürücüsünün automationName değeri.</summary>
    public const string NovaWindows = "NovaWindows";

    /// <summary>Appium komutları arasında oturumun kapanmadan bekleyeceği süre (sn).</summary>
    public const int KomutZamanAsimiSn = 120;

    private static readonly Regex Tehlikeli = new("['‘’‚‛\\p{Cc}]", RegexOptions.CultureInvariant);

    /// <summary>Appium seçenekleri (oturum açmadan; birim testleri bunu doğrular).</summary>
    public static AppiumOptions Secenekler(Ayarlar a)
    {
        a.Platform();
        string uygulama = a.AppPath ?? a.AppId
            ?? throw new ArgumentException("windows için APP_PATH (exe) ya da APP_ID (AUMID) gerekir (ortam; bkz. README)");
        var o = new AppiumOptions
        {
            PlatformName = "Windows",
            AutomationName = NovaWindows,
            App = PowershellGuvenli("APP_PATH/APP_ID", uygulama),
        };
        o.AddAdditionalAppiumOption("newCommandTimeout", KomutZamanAsimiSn);
        if (a.AppArgs is { } args)
        {
            o.AddAdditionalAppiumOption("appArguments", PowershellGuvenli("APP_ARGS", args));
        }
        if (a.AppWorkdir is { } dizin)
        {
            o.AddAdditionalAppiumOption("appWorkingDir", PowershellGuvenli("APP_WORKDIR", dizin));
        }
        return o;
    }

    /// <summary>
    /// NovaWindows <c>app</c>/<c>appArguments</c> değerlerini PowerShell'de tek tırnak içine kaçışsız
    /// gömer; tek tırnak (akıllı tırnaklar dahil) ya da denetim karakteri reddedilir (Java ile aynı kural).
    /// </summary>
    public static string PowershellGuvenli(string ad, string deger)
    {
        if (Tehlikeli.IsMatch(deger))
        {
            throw new ArgumentException($"{ad} tek tırnak ya da denetim karakteri içeremez (NovaWindows PowerShell'e kaçışsız geçirir)");
        }
        return deger;
    }

    /// <summary>Appium adresi; geçersizse açık hata.</summary>
    public static Uri Adres(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out Uri? adres) || (adres.Scheme != "http" && adres.Scheme != "https"))
        {
            throw new ArgumentException($"geçersiz APPIUM_URL '{url}'");
        }
        return adres;
    }

    /// <summary>Yeni Appium oturumu açar; örtük bekleme kapalıdır.</summary>
    public static WindowsDriver Olustur(Ayarlar a)
    {
        var surucu = new WindowsDriver(Adres(a.AppiumUrl), Secenekler(a), TimeSpan.FromSeconds(KomutZamanAsimiSn));
        surucu.Manage().Timeouts().ImplicitWait = TimeSpan.Zero;
        return surucu;
    }
}

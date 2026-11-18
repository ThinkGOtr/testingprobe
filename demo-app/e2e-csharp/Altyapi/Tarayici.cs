using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Playwright;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Süreç başına tek Playwright + Chromium (TS: işçi başına tarayıcı; Java: iş parçacığı başına).
/// Playwright .NET istemcisi eşzamansızdır ve tek örnek birden çok bağlamı güvenle sürer; testler
/// arasında yalnız tarayıcı paylaşılır, her test yeni bir <see cref="IBrowserContext"/> + <see cref="IPage"/>
/// alır (çerez/oturum sızmaz). Kapanış: <see cref="Montaj"/> (<c>OneTimeTearDown</c>).
///
/// Tarayıcı <c>PLAYWRIGHT_BROWSERS_PATH</c>'ten (yoksa Playwright'ın varsayılan önbelleğinden) açılır;
/// test sırasında indirme yapılmaz — tarayıcı yoksa açıklayıcı hata verilir (README "Tarayıcı kurulumu").
/// </summary>
public static class Tarayici
{
    private static readonly SemaphoreSlim Kilit = new(1, 1);
    private static IPlaywright? _playwright;
    private static IBrowser? _browser;

    /// <summary>Paylaşılan tarayıcı (ilk çağrıda açılır; bağlantı koptuysa yeniden açılır).</summary>
    public static async Task<IBrowser> BrowserAsync(Ayarlar ayarlar)
    {
        await Kilit.WaitAsync();
        try
        {
            if (_browser is { IsConnected: true })
            {
                return _browser;
            }
            await KapatIcAsync();
            _playwright = await Playwright.CreateAsync();
            try
            {
                _browser = await _playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
                {
                    Headless = ayarlar.Headless,
                    Env = new Dictionary<string, string> { ["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1" },
                });
            }
            catch (PlaywrightException e)
            {
                _playwright.Dispose();
                _playwright = null;
                var yol = Environment.GetEnvironmentVariable("PLAYWRIGHT_BROWSERS_PATH") ?? "<varsayılan önbellek>";
                throw new InvalidOperationException(
                    $"Chromium açılamadı (PLAYWRIGHT_BROWSERS_PATH={yol}). Tarayıcı test sırasında indirilmez; "
                    + "README 'Tarayıcı kurulumu'na bakın.", e);
            }
            return _browser;
        }
        finally
        {
            Kilit.Release();
        }
    }

    /// <summary>Tarayıcıyı ve Playwright'ı kapatır (koşu sonu).</summary>
    public static async Task KapatAsync()
    {
        await Kilit.WaitAsync();
        try
        {
            await KapatIcAsync();
        }
        finally
        {
            Kilit.Release();
        }
    }

    private static async Task KapatIcAsync()
    {
        if (_browser is not null)
        {
            try
            {
                await _browser.CloseAsync();
            }
            catch (PlaywrightException)
            {
                // zaten kapanmış
            }
            _browser = null;
        }
        _playwright?.Dispose();
        _playwright = null;
    }
}

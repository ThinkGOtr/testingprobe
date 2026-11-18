using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Allure.Net.Commons;
using Microsoft.Playwright;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Başarısız testin kanıtı: ekran görüntüsü, Playwright trace'i ve sayfa HTML'i
/// (<c>&lt;KANIT_DIZINI&gt;/&lt;Sınıf&gt;.&lt;Metot&gt;/{ekran.png, trace.zip, sayfa.html}</c>; e2e-java ile aynı
/// düzen). Triage bunları okur; Allure raporuna da eklenir. Kanıt toplanamazsa testin asıl hatası
/// gölgelenmez: yalnız <c>kanit-hatasi.txt</c> yazılır.
/// </summary>
public static class Kanit
{
    public const string Ekran = "ekran.png";
    public const string Trace = "trace.zip";
    public const string Sayfa = "sayfa.html";

    private static readonly Regex Guvensiz = new("[^A-Za-z0-9._-]", RegexOptions.CultureInvariant);

    /// <summary>Testin kanıt dizini: güvenli karakterlere indirgenmiş <c>Sınıf.Metot</c>.</summary>
    public static string Dizin(string kok, string sinif, string metot) =>
        Path.Combine(kok, Guvensiz.Replace(sinif + "." + metot, "_"));

    /// <summary>Trace kaydını başlatır (her test; yalnız başarısızlıkta dosyaya yazılır).</summary>
    public static Task IzlemeyiBaslatAsync(IBrowserContext baglam) =>
        baglam.Tracing.StartAsync(new TracingStartOptions { Screenshots = true, Snapshots = true, Sources = false });

    /// <summary>Başarılı testte trace'i yazmadan kapatır.</summary>
    public static async Task IzlemeyiBirakAsync(IBrowserContext baglam)
    {
        try
        {
            await baglam.Tracing.StopAsync();
        }
        catch (PlaywrightException)
        {
            // bağlam kapanmış olabilir; kayıt zaten atılır
        }
    }

    /// <summary>Kanıtı toplar (trace kaydını da kapatır); yazılan dizini döndürür.</summary>
    public static async Task<string> ToplaAsync(IPage page, IBrowserContext baglam, string kok, string sinif, string metot)
    {
        var hedef = Dizin(kok, sinif, metot);
        var hatalar = new StringBuilder();
        try
        {
            Directory.CreateDirectory(hedef);
        }
        catch (IOException)
        {
            await IzlemeyiBirakAsync(baglam);
            return hedef;
        }
        try
        {
            var png = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
            await File.WriteAllBytesAsync(Path.Combine(hedef, Ekran), png);
            Ekle("Ekran görüntüsü", "image/png", png, ".png");
        }
        catch (Exception e) when (e is PlaywrightException or IOException)
        {
            hatalar.Append("ekran görüntüsü: ").Append(e.GetType().Name).Append('\n');
        }
        try
        {
            var html = await page.ContentAsync();
            await File.WriteAllTextAsync(Path.Combine(hedef, Sayfa), html, Encoding.UTF8);
            Ekle("Sayfa HTML'i", "text/html", Encoding.UTF8.GetBytes(html), ".html");
        }
        catch (Exception e) when (e is PlaywrightException or IOException)
        {
            hatalar.Append("sayfa HTML'i: ").Append(e.GetType().Name).Append('\n');
        }
        try
        {
            var trace = Path.Combine(hedef, Trace);
            await baglam.Tracing.StopAsync(new TracingStopOptions { Path = trace });
            Ekle("Playwright trace", "application/zip", await File.ReadAllBytesAsync(trace), ".zip");
        }
        catch (Exception e) when (e is PlaywrightException or IOException)
        {
            hatalar.Append("trace: ").Append(e.GetType().Name).Append('\n');
        }
        if (hatalar.Length > 0)
        {
            try
            {
                await File.WriteAllTextAsync(Path.Combine(hedef, "kanit-hatasi.txt"), hatalar.ToString(), Encoding.UTF8);
            }
            catch (IOException)
            {
                // kanıt yazılamadı; asıl test hatası yine raporlanır
            }
        }
        return hedef;
    }

    private static void Ekle(string ad, string tur, byte[] icerik, string uzanti)
    {
        try
        {
            AllureApi.AddAttachment(ad, tur, icerik, uzanti);
        }
        catch (Exception)
        {
            // Allure bağlamı yoksa (ör. Allure dışı koşu) rapor eki atlanır; test etkilenmez.
        }
    }
}

using System.IO;
using System.Text.RegularExpressions;
using NUnit.Framework;

namespace Antreklabs.Bayi.Birim;

/// <summary>Microsoft.Playwright sürümü = depo kökündeki .playwright-version (tarayıcı derlemeleri TS/Java ile ortak).</summary>
[Category("birim")]
public class SurumTests
{
    private static string Beklenen() => File.ReadAllText(Path.Combine(Kok.Depo, ".playwright-version")).Trim();

    [Test]
    public void PaketSabitlemesiPlaywrightSurumuIleAyni()
    {
        var props = File.ReadAllText(Path.Combine(Kok.Proje, "Directory.Packages.props"));
        var m = Regex.Match(props, "<PackageVersion Include=\"Microsoft\\.Playwright\" Version=\"([^\"]+)\"");
        Assert.That(m.Success, Is.True, "Directory.Packages.props Microsoft.Playwright sabitlemesi yok");
        Assert.That(m.Groups[1].Value, Is.EqualTo(Beklenen()));
    }

    /// <summary>Derleme çıktısındaki Playwright sürücüsü (<c>.playwright/package</c>) aynı çekirdek sürümü.</summary>
    [Test]
    public void SurucuCekirdegiAyniSurum()
    {
        var paket = Path.Combine(System.AppContext.BaseDirectory, ".playwright", "package", "package.json");
        Assert.That(File.Exists(paket), Is.True, $"Playwright sürücüsü yok: {paket}");
        var m = Regex.Match(File.ReadAllText(paket), "\"version\"\\s*:\\s*\"([^\"]+)\"");
        Assert.That(m.Groups[1].Value, Is.EqualTo(Beklenen()));
    }

    [Test]
    public void TumPaketlerTamSabit()
    {
        var props = File.ReadAllText(Path.Combine(Kok.Proje, "Directory.Packages.props"));
        foreach (Match m in Regex.Matches(props, "Version=\"([^\"]+)\""))
        {
            Assert.That(m.Groups[1].Value, Does.Match(@"^\d+\.\d+\.\d+$"), "sürüm aralığı/joker kullanılmaz");
        }
    }
}

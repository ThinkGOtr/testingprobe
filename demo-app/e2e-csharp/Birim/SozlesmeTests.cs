using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Antreklabs.Bayi.Altyapi;
using Antreklabs.Bayi.Pages;
using NUnit.Framework;

namespace Antreklabs.Bayi.Birim;

/// <summary>
/// 014 §3.2 C# biçim sözleşmesinin yerel kilidi (asıl denetim: toolchain/cs-araclar; TS ↔ C# sembol
/// tablosu eşitliği core'da). Kimlikler saf veridir, TypeScript locators.ts ve kimlikler.json ile
/// birebir aynıdır; page object metotları TS page object'leriyle (PascalCase + Async) birebirdir;
/// TestTabani her page object için sınıf adıyla aynı adlı erişimci sağlar.
/// </summary>
[Category("birim")]
public class SozlesmeTests
{
    private static readonly HashSet<Type> IzinliParametre = new() { typeof(string), typeof(int), typeof(long), typeof(double), typeof(bool) };

    /// <summary>Değer döndüren tek TS metodu: yalnız elle yazılmış testler kullanır.</summary>
    private static readonly HashSet<string> DegerDonduren = new() { "OrderPage.ReadOrderNumberAsync" };

    /// <summary>Kimlikler: grup yolu + sabit adı → değer (iç içe gruplar dahil).</summary>
    internal static SortedDictionary<string, string> Kimlikler_()
    {
        var m = new SortedDictionary<string, string>(StringComparer.Ordinal);
        Topla(typeof(Kimlikler), "", m);
        return m;
    }

    private static void Topla(Type t, string yol, SortedDictionary<string, string> m)
    {
        foreach (var g in t.GetNestedTypes())
        {
            Topla(g, yol + g.Name + ".", m);
        }
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            m[yol + f.Name] = (string)f.GetRawConstantValue()!;
        }
    }

    /// <summary>TS locators.ts: testId → within (yoksa "").</summary>
    internal static SortedDictionary<string, string> TsKimlikleri()
    {
        var m = new SortedDictionary<string, string>(StringComparer.Ordinal);
        var nesne = new Regex(@"\{([^{}]*testId:[^{}]*)\}");
        var testId = new Regex("testId:\\s*\"([^\"]+)\"");
        var within = new Regex("within:\\s*\"([^\"]+)\"");
        foreach (var f in Directory.EnumerateFiles(Path.Combine(Kok.DemoApp, "e2e", "pages"), "locators.ts", SearchOption.AllDirectories))
        {
            foreach (Match mt in nesne.Matches(File.ReadAllText(f)))
            {
                var t = testId.Match(mt.Groups[1].Value);
                var w = within.Match(mt.Groups[1].Value);
                if (t.Success)
                {
                    m[t.Groups[1].Value] = w.Success ? w.Groups[1].Value : "";
                }
            }
        }
        return m;
    }

    /// <summary>TS page object'leri: sınıf → metot → parametre adları.</summary>
    internal static SortedDictionary<string, SortedDictionary<string, string[]>> TsPageObjectleri()
    {
        var sinif = new Regex(@"export class (\w+)");
        var metot = new Regex(@"^\s+async (\w+)\(([^)]*)\)", RegexOptions.Multiline);
        var m = new SortedDictionary<string, SortedDictionary<string, string[]>>(StringComparer.Ordinal);
        foreach (var f in Directory.EnumerateFiles(Path.Combine(Kok.DemoApp, "e2e", "pages"), "*.page.ts", SearchOption.AllDirectories))
        {
            var kaynak = File.ReadAllText(f);
            var ad = sinif.Match(kaynak).Groups[1].Value;
            var metotlar = new SortedDictionary<string, string[]>(StringComparer.Ordinal);
            foreach (Match mt in metot.Matches(kaynak))
            {
                var parametreler = mt.Groups[2].Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                    .Select(p => p.Split(':')[0].Trim().TrimEnd('?'))
                    .ToArray();
                metotlar[mt.Groups[1].Value] = parametreler;
            }
            m[ad] = metotlar;
        }
        return m;
    }

    /// <summary>TS adı → C# adı: PascalCase + Async.</summary>
    internal static string CsAdi(string ts) => char.ToUpperInvariant(ts[0]) + ts[1..] + "Async";

    internal static IEnumerable<Type> PageObjectler() =>
        typeof(Ekran).Assembly.GetTypes()
            .Where(t => t.Namespace == "Antreklabs.Bayi.Pages" && !t.IsAbstract && typeof(Ekran).IsAssignableFrom(t))
            .OrderBy(t => t.Name, StringComparer.Ordinal);

    [Test]
    public void KimliklerSafVeri()
    {
        var kuyruk = new Queue<Type>(new[] { typeof(Kimlikler) });
        while (kuyruk.Count > 0)
        {
            var t = kuyruk.Dequeue();
            Assert.That(t.IsAbstract && t.IsSealed, Is.True, $"{t} static class olmalı");
            Assert.That(t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly), Is.Empty, $"{t} metot içeremez");
            Assert.That(t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static), Is.Empty, $"{t} özellik içeremez");
            foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
            {
                Assert.That(f.IsLiteral && f.IsPublic && f.FieldType == typeof(string), Is.True, $"{f.Name} public const string olmalı");
            }
            foreach (var g in t.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic))
            {
                kuyruk.Enqueue(g);
            }
        }
        Assert.That(typeof(Kimlikler).GetFields(), Is.Empty, "Kimlikler üst düzeyde sabit içeremez");
    }

    [Test]
    public void KimliklerTsLocatorlariIleAyni()
    {
        var cs = Kimlikler_();
        var ts = TsKimlikleri();
        Assert.That(cs.Values.ToHashSet(), Is.EquivalentTo(ts.Keys), "Kimlikler değerleri = TS locators.ts testId'leri");
        Assert.That(cs.Count, Is.EqualTo(ts.Count), "aynı değer iki kez tanımlanmamalı");
        foreach (var (anahtar, deger) in cs)
        {
            Assert.That(anahtar.EndsWith("_ONEK", StringComparison.Ordinal), Is.EqualTo(deger.EndsWith('-')), $"{anahtar}: _ONEK ⇔ değer '-' ile biter");
            var w = ts[deger];
            var yol = anahtar.Split('.');
            if (w.Length == 0)
            {
                Assert.That(yol, Has.Length.EqualTo(2), $"{anahtar}: kapsamsız kimlik tek düzey grupta olmalı");
            }
            else
            {
                Assert.That(yol, Has.Length.EqualTo(3), $"{anahtar}: kapsamlı kimlik (within {w}) iç grupta olmalı");
                var kapsayici = yol[0] + "." + Regex.Replace(yol[1], "([a-z])([A-Z])", "$1_$2").ToUpperInvariant() + "_ONEK";
                Assert.That(cs.GetValueOrDefault(kapsayici), Is.EqualTo(w), $"{anahtar}: kapsayıcı sabiti {kapsayici}");
            }
        }
    }

    [Test]
    public void KimliklerJsonIleAyni()
    {
        var json = File.ReadAllText(Path.Combine(Kok.DemoApp, "kimlikler.json"));
        var sozlesme = new Dictionary<string, bool>();
        foreach (Match m in Regex.Matches(json, "\"id\"\\s*:\\s*\"([^\"]+)\"[^}]*\"onek\"\\s*:\\s*(true|false)"))
        {
            sozlesme[m.Groups[1].Value] = m.Groups[2].Value == "true";
        }
        Assert.That(sozlesme.Count, Is.GreaterThan(20), "kimlikler.json okunamadı");
        foreach (var (anahtar, deger) in Kimlikler_())
        {
            Assert.That(sozlesme.ContainsKey(deger), Is.True, $"{anahtar}={deger} kimlikler.json'da yok");
            Assert.That(sozlesme[deger], Is.EqualTo(anahtar.EndsWith("_ONEK", StringComparison.Ordinal)), $"{anahtar}: önek bilgisi");
        }
    }

    [Test]
    public void KimliklerJavaIleAyni()
    {
        var java = File.ReadAllText(Path.Combine(Kok.DemoApp, "e2e-java", "src", "test", "java", "com", "antreklabs", "bayi", "ekranlar", "Kimlikler.java"));
        var sabitler = Regex.Matches(java, "public static final String (\\w+) = \"([^\"]+)\";")
            .Select(m => (m.Groups[1].Value, m.Groups[2].Value)).OrderBy(x => x.Item2, StringComparer.Ordinal).ToList();
        var cs = Kimlikler_().Select(kv => (kv.Key.Split('.')[^1], kv.Value)).OrderBy(x => x.Value, StringComparer.Ordinal).ToList();
        Assert.That(cs, Is.EqualTo(sabitler), "sabit adları ve değerleri Java Kimlikler.java ile birebir");
    }

    [Test]
    public void PageObjectlerTsIleBirebir()
    {
        var ts = TsPageObjectleri();
        var cs = PageObjectler().ToList();
        Assert.That(cs.Select(t => t.Name), Is.EquivalentTo(ts.Keys), "page object sınıfları = TS sınıfları");
        foreach (var t in cs)
        {
            var metotlar = t.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                .Where(m => !m.IsSpecialName).ToList();
            var beklenen = ts[t.Name].ToDictionary(kv => CsAdi(kv.Key), kv => kv.Value);
            Assert.That(metotlar.Select(m => m.Name), Is.EquivalentTo(beklenen.Keys), $"{t.Name}: public metotlar = TS metotları (PascalCase + Async)");
            Assert.That(metotlar.Select(m => m.Name).Distinct().Count(), Is.EqualTo(metotlar.Count), $"{t.Name}: aşırı yükleme yok");
            foreach (var m in metotlar)
            {
                var ps = m.GetParameters();
                Assert.That(ps.Select(p => p.Name), Is.EqualTo(beklenen[m.Name]), $"{t.Name}.{m.Name}: parametre adları ve sırası TS ile aynı");
                foreach (var p in ps)
                {
                    Assert.That(IzinliParametre.Contains(p.ParameterType), Is.True, $"{t.Name}.{m.Name}({p.Name}): tür {p.ParameterType}");
                }
                var donus = DegerDonduren.Contains($"{t.Name}.{m.Name}") ? typeof(Task<string>) : typeof(Task);
                Assert.That(m.ReturnType, Is.EqualTo(donus), $"{t.Name}.{m.Name}: dönüş");
            }
        }
    }

    [Test]
    public void TestTabaniHerPageObjectIcinErisimciSaglar()
    {
        foreach (var t in PageObjectler())
        {
            var p = typeof(TestTabani).GetProperty(t.Name, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            Assert.That(p, Is.Not.Null, $"TestTabani.{t.Name} erişimcisi yok");
            Assert.That(p!.PropertyType, Is.EqualTo(t));
            Assert.That(p.GetMethod!.IsFamily || p.GetMethod.IsPublic, Is.True, $"TestTabani.{t.Name} protected/public olmalı");
        }
    }
}

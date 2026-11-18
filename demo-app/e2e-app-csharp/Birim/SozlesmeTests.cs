using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;
using Antreklabs.Bayi.Altyapi;
using Antreklabs.Bayi.Ekranlar;
using NUnit.Framework;

namespace Antreklabs.Bayi.Birim;

/// <summary>
/// Plan §2.8 / 014 §3.2 C# biçim sözleşmesinin yerel kilidi (asıl denetim: toolchain/cs-araclar):
/// Kimlikler saf veridir, Java Kimlikler.java ve demo-app/kimlikler.json ile birebirdir; ekran
/// metotları Java e2e-app ekranlarıyla ad (PascalCase) ve parametre olarak birebirdir; TestTabani her
/// ekran için erişimci sağlar; örnek üretilen test biçimdedir.
/// </summary>
[TestFixture]
[Category("birim")]
public class SozlesmeTests
{
    private static readonly HashSet<Type> IzinliParametre = new() { typeof(string), typeof(int), typeof(long), typeof(double), typeof(bool) };

    private static readonly Dictionary<string, Type> JavaTuru = new()
    {
        ["String"] = typeof(string),
        ["int"] = typeof(int),
        ["long"] = typeof(long),
        ["double"] = typeof(double),
        ["boolean"] = typeof(bool),
    };

    private static string JavaEkranlar =>
        Path.Combine(ProjeYolu.DemoApp, "e2e-app", "src", "test", "java", "com", "antreklabs", "bayi", "ekranlar");

    /// <summary>Kimlikler: grup + sabit adı → değer.</summary>
    private static SortedDictionary<string, string> Kimlikler()
    {
        var m = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (Type grup in typeof(Kimlikler).GetNestedTypes())
        {
            foreach (FieldInfo f in grup.GetFields(BindingFlags.Public | BindingFlags.Static))
            {
                m[grup.Name + "." + f.Name] = (string)f.GetRawConstantValue()!;
            }
        }
        return m;
    }

    private static IEnumerable<Type> EkranSiniflari() =>
        typeof(Ekran).Assembly.GetTypes()
            .Where(t => t.Namespace == "Antreklabs.Bayi.Ekranlar" && t.IsClass && !t.IsAbstract && t.IsSubclassOf(typeof(Ekran)))
            .OrderBy(t => t.Name, StringComparer.Ordinal);

    [Test]
    public void KimliklerSafVeri()
    {
        Type k = typeof(Kimlikler);
        Assert.That(k.IsAbstract && k.IsSealed, Is.True, "Kimlikler static class olmalı");
        Assert.That(k.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly), Is.Empty);
        Assert.That(k.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static), Is.Empty);
        foreach (Type grup in k.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic))
        {
            Assert.That(grup.IsNestedPublic && grup.IsAbstract && grup.IsSealed, Is.True, grup + " public static olmalı");
            Assert.That(grup.GetNestedTypes(), Is.Empty, grup + " iç içe en çok bir düzey");
            Assert.That(grup.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly), Is.Empty);
            foreach (FieldInfo f in grup.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
            {
                Assert.That(f.IsLiteral && f.IsPublic && f.FieldType == typeof(string), Is.True, $"{grup.Name}.{f.Name} public const string olmalı");
                Assert.That(f.Name, Does.Match("^[A-Z][A-Z0-9_]*$"));
            }
        }
    }

    [Test]
    public void OnekAdlandirmasi()
    {
        foreach (var (ad, deger) in Kimlikler())
        {
            Assert.That(ad.EndsWith("_ONEK", StringComparison.Ordinal), Is.EqualTo(deger.EndsWith('-')), $"{ad} = \"{deger}\": _ONEK ⇔ değer '-' ile biter");
        }
    }

    [Test]
    public void KimliklerJavaKimliklerJavaIleBirebir()
    {
        string kaynak = File.ReadAllText(Path.Combine(JavaEkranlar, "Kimlikler.java"));
        var java = new SortedDictionary<string, string>(StringComparer.Ordinal);
        string? grup = null;
        foreach (string satir in kaynak.Split('\n'))
        {
            Match g = Regex.Match(satir, @"public static final class (\w+)");
            if (g.Success)
            {
                grup = g.Groups[1].Value;
                continue;
            }
            Match s = Regex.Match(satir, "public static final String (\\w+) = \"([^\"]*)\";");
            if (s.Success && grup is not null)
            {
                java[grup + "." + s.Groups[1].Value] = s.Groups[2].Value;
            }
        }
        Assert.That(java, Is.Not.Empty);
        Assert.That(Kimlikler(), Is.EqualTo(java));
    }

    [Test]
    public void KimliklerKimliklerJsondaVar()
    {
        using JsonDocument d = JsonDocument.Parse(File.ReadAllText(Path.Combine(ProjeYolu.DemoApp, "kimlikler.json")));
        var idler = d.RootElement.GetProperty("kimlikler").EnumerateArray()
            .Select(e => (e.GetProperty("id").GetString()!, e.GetProperty("onek").GetBoolean()))
            .ToHashSet();
        foreach (var (ad, deger) in Kimlikler())
        {
            Assert.That(idler.Contains((deger, deger.EndsWith('-'))), Is.True, $"{ad} = \"{deger}\" kimlikler.json'da yok");
        }
    }

    [Test]
    public void EkranMetotlariSozlesmeye()
    {
        foreach (Type ekran in EkranSiniflari())
        {
            var adlar = new HashSet<string>();
            foreach (MethodInfo m in ekran.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                Assert.That(adlar.Add(m.Name), Is.True, $"{ekran.Name}.{m.Name}: aşırı yükleme yasak");
                Assert.That(m.ReturnType, Is.EqualTo(typeof(void)), $"{ekran.Name}.{m.Name} void dönmeli");
                Assert.That(m.Name, Does.Not.EndWith("Async"), "Appium .NET eşzamanlı: Async soneki yok");
                foreach (ParameterInfo p in m.GetParameters())
                {
                    Assert.That(IzinliParametre, Does.Contain(p.ParameterType), $"{ekran.Name}.{m.Name}({p.Name})");
                }
            }
        }
    }

    /// <summary>Java ekran metodu → C# imzası (PascalCase ad; parametre adları ve türleri birebir).</summary>
    private static SortedSet<string> JavaImzalari(string sinif)
    {
        string kaynak = File.ReadAllText(Path.Combine(JavaEkranlar, sinif + ".java"));
        var imzalar = new SortedSet<string>(StringComparer.Ordinal);
        foreach (Match m in Regex.Matches(kaynak, @"^\s{2}public void (\w+)\(([^)]*)\)", RegexOptions.Multiline))
        {
            string ad = char.ToUpperInvariant(m.Groups[1].Value[0]) + m.Groups[1].Value[1..];
            var parametreler = m.Groups[2].Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .Select(p => p.Split(' '))
                .Select(p => JavaTuru[p[0]].Name + " " + p[1]);
            imzalar.Add($"{ad}({string.Join(", ", parametreler)})");
        }
        return imzalar;
    }

    private static SortedSet<string> CsImzalari(Type ekran) =>
        new(
            ekran.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                .Select(m => $"{m.Name}({string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name))})"),
            StringComparer.Ordinal);

    [Test]
    public void EkranlarJavaEkranlariylaBirebir()
    {
        var javaEkranlari = Directory.GetFiles(JavaEkranlar, "*Ekrani.java")
            .Select(Path.GetFileNameWithoutExtension).OrderBy(x => x, StringComparer.Ordinal).ToList();
        Assert.That(EkranSiniflari().Select(t => t.Name).ToList(), Is.EqualTo(javaEkranlari));
        foreach (Type ekran in EkranSiniflari())
        {
            Assert.That(CsImzalari(ekran), Is.EqualTo(JavaImzalari(ekran.Name)), ekran.Name);
        }
    }

    [Test]
    public void TestTabaniHerEkranIcinErisimci()
    {
        foreach (Type ekran in EkranSiniflari())
        {
            PropertyInfo? p = typeof(TestTabani).GetProperty(ekran.Name, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            Assert.That(p, Is.Not.Null, $"TestTabani.{ekran.Name} erişimcisi yok");
            Assert.That(p!.PropertyType, Is.EqualTo(ekran));
            Assert.That(p.GetMethod!.IsFamily || p.GetMethod.IsPublic, Is.True);
        }
    }

    [Test]
    public void UretilenOrnekBicimde()
    {
        Type t = typeof(Tests.Generated.TPD1WindowsC2_3f9b1c2eTests);
        Assert.That(t.BaseType, Is.EqualTo(typeof(TestTabani)));
        MethodInfo[] testler = t.GetMethods().Where(m => m.GetCustomAttribute<TestAttribute>() is not null).ToArray();
        Assert.That(testler.Select(m => m.Name), Is.EqualTo(new[] { "Senaryo" }));
        var kategoriler = testler[0].GetCustomAttributes<CategoryAttribute>().Select(c => c.Name).ToList();
        Assert.That(kategoriler, Does.Contain("uretilen").And.Contain("windows").And.Contain("tp-case-3f9b1c2e-0000-5000-8000-0000000000c2"));
        string kaynak = File.ReadAllText(Path.Combine(ProjeYolu.Kok, "Tests", "Generated", "TPD1WindowsC2_3f9b1c2eTests.cs"));
        Assert.That(kaynak, Does.StartWith("// AI-generated — AI Testing Probe (CasesToCode)."));
    }

    [Test]
    public void SabitBeklemeYok()
    {
        foreach (string dosya in Directory.GetFiles(ProjeYolu.Kok, "*.cs", SearchOption.AllDirectories)
                     .Where(f => !f.Contains(Path.DirectorySeparatorChar + "obj" + Path.DirectorySeparatorChar)
                                 && !f.Contains(Path.DirectorySeparatorChar + "bin" + Path.DirectorySeparatorChar)
                                 && !f.EndsWith("SozlesmeTests.cs", StringComparison.Ordinal)))
        {
            string metin = File.ReadAllText(dosya);
            Assert.That(metin, Does.Not.Contain("Thread.Sleep").And.Not.Contain("Task.Delay"), dosya);
        }
    }
}

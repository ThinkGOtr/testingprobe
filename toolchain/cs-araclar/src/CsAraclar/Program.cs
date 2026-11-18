using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Antreklabs.Tp.CsAraclar;

/// <summary>
/// cs-araclar CLI (java-araclar ile aynı sözleşme).
///
///   dotnet cs-araclar.dll symbols  --root &lt;proje&gt; [--platform web|windows]
///   dotnet cs-araclar.dll guard    --root &lt;proje&gt; [--platform …] [--kimlikler] [--out rapor.json] [--quiet] [--] &lt;dosya.cs&gt;…
///   dotnet cs-araclar.dll locators find  --root &lt;proje&gt; --test-id &lt;id&gt;
///   dotnet cs-araclar.dll locators patch --root &lt;proje&gt; --old &lt;id&gt; --new &lt;id&gt; [--key Grup.SABIT] [--path-prefix p]
///   dotnet cs-araclar.dll locators diff  --base &lt;Kimlikler.cs&gt; --head &lt;Kimlikler.cs&gt; [--file &lt;etiket&gt;]
///
/// Çıkış: symbols / locators find 0 üretildi · 2 hata; guard / locators diff 0 geçti · 1 ihlal · 2 hata;
/// locators patch 0 yama · 1 reddedildi · 2 hata. JSON stdout'a; hatada {"ok": false, "error": …}.
/// </summary>
public static class Program
{
    public const int OK = 0;
    public const int IHLAL = 1;
    public const int HATA = 2;

    const string KULLANIM = "Kullanım:\n"
        + "  cs-araclar symbols  --root <proje> [--platform web|windows]\n"
        + "  cs-araclar guard    --root <proje> [--platform web|windows] [--kimlikler] [--out rapor.json] [--quiet] [--] <dosya.cs>...\n"
        + "  cs-araclar locators find  --root <proje> --test-id <id>\n"
        + "  cs-araclar locators patch --root <proje> --old <id> --new <id> [--key Grup.SABIT] [--path-prefix <yol>]\n"
        + "  cs-araclar locators diff  --base <Kimlikler.cs> --head <Kimlikler.cs> [--file <etiket>]\n"
        + "Çıkış: 0 tamam · 1 ihlal/ret · 2 hata";

    public static int Main(string[] args)
    {
        var utf8 = new UTF8Encoding(false);
        var out_ = new StreamWriter(Console.OpenStandardOutput(), utf8) { AutoFlush = true };
        var err = new StreamWriter(Console.OpenStandardError(), utf8) { AutoFlush = true };
        return Calistir(args, out_, err);
    }

    sealed record Argumanlar(Dictionary<string, string> Secenekler, HashSet<string> Bayraklar, List<string> Konumsal);

    static Argumanlar Ayir(string[] args, int bas, ISet<string> degerli, ISet<string> bayrakAdlari)
    {
        var s = new Dictionary<string, string>(StringComparer.Ordinal);
        var b = new HashSet<string>(StringComparer.Ordinal);
        var k = new List<string>();
        bool son = false;
        for (int i = bas; i < args.Length; i++)
        {
            var a = args[i];
            if (!son && a == "--") son = true;
            else if (!son && a.StartsWith("--", StringComparison.Ordinal))
            {
                var ad = a[2..];
                string? deger = null;
                int eq = ad.IndexOf('=');
                if (eq >= 0)
                {
                    deger = ad[(eq + 1)..];
                    ad = ad[..eq];
                }
                if (degerli.Contains(ad))
                {
                    if (deger == null)
                    {
                        if (i + 1 >= args.Length) throw new ArgumentException($"--{ad} bir değer ister");
                        deger = args[++i];
                    }
                    if (!s.TryAdd(ad, deger)) throw new ArgumentException($"--{ad} iki kez verildi");
                }
                else if (bayrakAdlari.Contains(ad) && deger == null) b.Add(ad);
                else throw new ArgumentException("bilinmeyen seçenek: " + a);
            }
            else if (!son && a.StartsWith('-') && a.Length > 1) throw new ArgumentException("bilinmeyen seçenek: " + a);
            else k.Add(a);
        }
        return new Argumanlar(s, b, k);
    }

    public static int Calistir(string[] args, TextWriter out_, TextWriter err)
    {
        if (args.Length == 0)
        {
            err.WriteLine(KULLANIM);
            return HATA;
        }
        if (args[0] is "-h" or "--help")
        {
            out_.WriteLine(KULLANIM);
            return OK;
        }
        try
        {
            return args[0] switch
            {
                "symbols" => Semboller(args, out_, err),
                "guard" => Koru(args, out_, err),
                "locators" => Kimlikler(args, out_, err),
                _ => Bilinmeyen(args[0], err),
            };
        }
        catch (ArgumentException e)
        {
            err.WriteLine(e.Message + "\n" + KULLANIM);
            return HATA;
        }
    }

    static int Bilinmeyen(string ad, TextWriter err)
    {
        err.WriteLine("bilinmeyen alt komut: " + ad + "\n" + KULLANIM);
        return HATA;
    }

    static string Kok(Argumanlar a)
    {
        if (!a.Secenekler.TryGetValue("root", out var r) || r.Length == 0) throw new ArgumentException("--root zorunludur");
        return r;
    }

    static int Hata(TextWriter out_, TextWriter err, string arac, Exception e)
    {
        out_.WriteLine(Kaynaklar.Json(new Harita { ["ok"] = false, ["error"] = e.Message }));
        err.WriteLine(arac + " hata: " + e.Message);
        return HATA;
    }

    static bool CalismaHatasi(Exception e) => e is IOException or UnauthorizedAccessException or InvalidOperationException
        or ArgumentException or FormatException or NotSupportedException;

    static int Semboller(string[] args, TextWriter out_, TextWriter err)
    {
        var a = Ayir(args, 1, new HashSet<string> { "root", "platform" }, new HashSet<string>());
        if (a.Konumsal.Count > 0) throw new ArgumentException("beklenmeyen argüman: " + a.Konumsal[0]);
        var kok = Kok(a);
        try
        {
            var t = SembolCikarici.Cikar(kok, a.Secenekler.GetValueOrDefault("platform"));
            out_.WriteLine(Kaynaklar.Json(t.Json()));
            return OK;
        }
        catch (Exception e) when (CalismaHatasi(e))
        {
            return Hata(out_, err, "cs-araclar symbols", e);
        }
    }

    static int Koru(string[] args, TextWriter out_, TextWriter err)
    {
        var a = Ayir(args, 1, new HashSet<string> { "root", "out", "platform" }, new HashSet<string> { "kimlikler", "quiet" });
        var kok = Kok(a);
        Harita rapor;
        try
        {
            rapor = UretilenTestKoruyucu.Denetle(kok, a.Konumsal, a.Bayraklar.Contains("kimlikler"),
                a.Secenekler.GetValueOrDefault("platform"));
        }
        catch (Exception e) when (CalismaHatasi(e))
        {
            out_.WriteLine(Kaynaklar.JsonGirintili(new Harita
            {
                ["tool"] = "cs-araclar", ["schema_version"] = 1, ["ok"] = false, ["error"] = e.Message,
            }));
            err.WriteLine("cs-araclar guard hata: " + e.Message);
            return HATA;
        }
        var json = Kaynaklar.JsonGirintili(rapor) + "\n";
        if (a.Secenekler.TryGetValue("out", out var dosya))
        {
            try
            {
                File.WriteAllText(dosya, json, new UTF8Encoding(false));
            }
            catch (Exception e) when (CalismaHatasi(e))
            {
                return Hata(out_, err, "cs-araclar guard", e);
            }
        }
        if (!a.Bayraklar.Contains("quiet")) out_.Write(json);
        err.WriteLine(rapor["summary"]);
        foreach (var v in (List<Harita>)rapor["violations"]!)
            err.WriteLine($"  ✗ [{v["code"]}] {v["file"]}{(v.ContainsKey("line") ? ":" + v["line"] : "")} {v["message"]}");
        return (bool)rapor["ok"]! ? OK : IHLAL;
    }

    static int Kimlikler(string[] args, TextWriter out_, TextWriter err)
    {
        if (args.Length < 2) throw new ArgumentException("locators alt komutu gerekli (find | patch | diff)");
        switch (args[1])
        {
            case "find":
            {
                var a = Ayir(args, 2, new HashSet<string> { "root", "test-id" }, new HashSet<string>());
                var kok = Kok(a);
                if (!a.Secenekler.TryGetValue("test-id", out var id) || id.Length == 0) throw new ArgumentException("--test-id zorunludur");
                try
                {
                    out_.WriteLine(Kaynaklar.Json(KimlikYamasi.Bul(kok, id)));
                    return OK;
                }
                catch (Exception e) when (CalismaHatasi(e))
                {
                    return Hata(out_, err, "cs-araclar locators find", e);
                }
            }
            case "patch":
            {
                var a = Ayir(args, 2, new HashSet<string> { "root", "old", "new", "key", "path-prefix" }, new HashSet<string>());
                var kok = Kok(a);
                try
                {
                    var m = KimlikYamasi.Yamala(kok, a.Secenekler.GetValueOrDefault("old"), a.Secenekler.GetValueOrDefault("new"),
                        a.Secenekler.GetValueOrDefault("key"), a.Secenekler.GetValueOrDefault("path-prefix"));
                    out_.WriteLine(Kaynaklar.Json(m));
                    return OK;
                }
                catch (KimlikYamasi.YamaHatasi e)
                {
                    out_.WriteLine(Kaynaklar.Json(new Harita { ["ok"] = false, ["error"] = e.Message }));
                    err.WriteLine("yama reddedildi: " + e.Message);
                    return IHLAL;
                }
                catch (Exception e) when (CalismaHatasi(e))
                {
                    return Hata(out_, err, "cs-araclar locators patch", e);
                }
            }
            case "diff":
            {
                var a = Ayir(args, 2, new HashSet<string> { "base", "head", "file" }, new HashSet<string>());
                if (!a.Secenekler.TryGetValue("base", out var b) || !a.Secenekler.TryGetValue("head", out var h))
                    throw new ArgumentException("--base ve --head zorunludur");
                try
                {
                    var r = KimlikYamasi.Fark(Kaynaklar.Oku(b), Kaynaklar.Oku(h), a.Secenekler.GetValueOrDefault("file") ?? h);
                    out_.Write(Kaynaklar.JsonGirintili(r) + "\n");
                    err.WriteLine(r["summary"]);
                    return (bool)r["ok"]! ? OK : IHLAL;
                }
                catch (Exception e) when (CalismaHatasi(e))
                {
                    return Hata(out_, err, "cs-araclar locators diff", e);
                }
            }
            default:
                throw new ArgumentException("bilinmeyen locators alt komutu: " + args[1]);
        }
    }
}

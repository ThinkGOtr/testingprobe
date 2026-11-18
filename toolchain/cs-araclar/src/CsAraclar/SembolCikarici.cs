using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Antreklabs.Tp.CsAraclar;

/// <summary>
/// Sembol tablosu (TS `tp-symbols` / java-araclar şeması; `lang: "csharp"`).
///
/// - Page object (web, `Pages/`) / ekran (windows, `Ekranlar/`): o dizindeki dosyalarda
///   `Ekran`'dan (doğrudan ya da başka bir page object üzerinden) türeyen üst düzey sınıf.
/// - Yalnız `public`, statik olmayan, sınıfta bildirilmiş metotlar. `Expect`/`Dogrula` ile başlayan →
///   `kind: "expect"`. Parametre türleri `string|int|long|double|boolean` olarak normalleşir;
///   başkası sözleşme dışıdır (`errors`). Dönüş `void`/`Task` → "void", `T`/`Task&lt;T&gt;` → normal tür.
/// - `locators`: page object dosyasının başvurduğu Kimlikler sabitleri (`Kimlikler.Login.X` ya da
///   `using static …Kimlikler;` ile `Login.X`).
/// - `fixtures`: `Altyapi/TestTabani` içindeki statik olmayan public/protected özellikler (türü bir
///   page object). Erişimcisi olmayan page object `errors`'a yazılır.
/// </summary>
public static class SembolCikarici
{
    public sealed record Metot(string Ad, List<Harita> Parametreler, string Donus, bool Async, string Doc, int Satir);

    public sealed record Nesne(string Sinif, string Dosya, string Doc, List<Metot> Metotlar, Harita Kimlikler, string? Taban);

    public sealed class Tablo
    {
        public string Platform = "";
        public List<Nesne> Nesneler = new();
        public List<Harita> KimlikDosyalari = new();
        public List<Harita> Hatalar = new();
        public List<string> Fikstürler = new();
        public Dictionary<string, KimlikDosyasi.Sonuc> KimlikSonuclari = new();

        public Nesne? Bul(string sinif) => Nesneler.FirstOrDefault(n => n.Sinif == sinif);

        public Harita Json()
        {
            var pos = new List<Harita>();
            foreach (var n in Nesneler)
            {
                pos.Add(new Harita
                {
                    ["class"] = n.Sinif,
                    ["file"] = n.Dosya,
                    ["doc"] = n.Doc,
                    ["methods"] = n.Metotlar.Select(m => new Harita
                    {
                        ["name"] = m.Ad,
                        ["params"] = m.Parametreler,
                        ["returns"] = m.Donus,
                        ["kind"] = BeklentiMi(m.Ad) ? "expect" : "action",
                        ["async"] = m.Async,
                        ["doc"] = m.Doc,
                        ["line"] = m.Satir,
                    }).ToList(),
                    ["locators"] = n.Kimlikler,
                });
            }
            return new Harita
            {
                ["schema_version"] = 1,
                ["lang"] = "csharp",
                ["platform"] = Platform,
                ["root"] = ".",
                ["page_objects"] = pos,
                ["locator_files"] = KimlikDosyalari,
                ["errors"] = Hatalar,
                ["fixtures"] = Fikstürler,
            };
        }
    }

    public static bool BeklentiMi(string ad) =>
        ad.StartsWith("Expect", StringComparison.Ordinal) || ad.StartsWith("Dogrula", StringComparison.Ordinal);

    static readonly Dictionary<string, string> Turler = new()
    {
        ["string"] = "string", ["String"] = "string", ["System.String"] = "string",
        ["int"] = "int", ["Int32"] = "int", ["System.Int32"] = "int",
        ["long"] = "long", ["Int64"] = "long", ["System.Int64"] = "long",
        ["double"] = "double", ["Double"] = "double", ["System.Double"] = "double",
        ["bool"] = "boolean", ["Boolean"] = "boolean", ["System.Boolean"] = "boolean",
    };

    public static string? NormalTur(TypeSyntax t) => Turler.TryGetValue(t.ToString(), out var n) ? n : null;

    static Harita Hata(string dosya, int satir, string mesaj)
    {
        var m = new Harita { ["file"] = dosya };
        if (satir > 0) m["line"] = satir;
        m["message"] = mesaj;
        return m;
    }

    public static Tablo Cikar(string kok, string? platformVerilen)
    {
        kok = Path.GetFullPath(kok);
        if (!Directory.Exists(kok)) throw new IOException("kök dizini okunamadı: " + kok);
        var t = new Tablo { Platform = Kaynaklar.Platform(kok, platformVerilen) };
        var nesneDizini = Kaynaklar.NesneDizini(t.Platform) + "/";
        var kimlikYolu = KimlikDosyasi.Yol(t.Platform);

        // 1) Kimlikler
        var kimlikler = new Dictionary<string, (string dosya, KimlikDosyasi.Kimlik k)>();
        var tumDosyalar = Kaynaklar.CsDosyalari(kok);
        foreach (var g in tumDosyalar.Where(d => d == kimlikYolu))
        {
            var s = KimlikDosyasi.Coz(Kaynaklar.Oku(Path.Combine(kok, g)));
            t.KimlikSonuclari[g] = s;
            foreach (var h in s.Hatalar) t.Hatalar.Add(Hata(g, h.Satir, h.Mesaj));
            foreach (var k in s.Kimlikler.Values) kimlikler[k.Anahtar] = (g, k);
            t.KimlikDosyalari.Add(new Harita { ["file"] = g, ["exports"] = s.Gruplar });
        }

        // 2) Aday sınıflar (nesne dizini) + taban sınıf
        var adaylar = new List<(string dosya, ClassDeclarationSyntax c, CompilationUnitSyntax cu)>();
        ClassDeclarationSyntax? taban = null;
        string? tabanDosya = null;
        foreach (var g in tumDosyalar)
        {
            bool nesne = g.StartsWith(nesneDizini, StringComparison.Ordinal) && g != kimlikYolu;
            bool altyapi = g.StartsWith(Kaynaklar.ALTYAPI + "/", StringComparison.Ordinal);
            if (!nesne && !altyapi) continue;
            var agac = Kaynaklar.Ayristir(Kaynaklar.Oku(Path.Combine(kok, g)), g);
            foreach (var (satir, mesaj) in Kaynaklar.SozdizimiHatalari(agac)) t.Hatalar.Add(Hata(g, satir, mesaj));
            var cu = (CompilationUnitSyntax)agac.GetRoot();
            foreach (var c in UstDuzeySiniflar(cu))
            {
                if (nesne) adaylar.Add((g, c, cu));
                else if (c.Identifier.Text == Kaynaklar.TABAN_SINIF && taban == null)
                {
                    taban = c;
                    tabanDosya = g;
                }
            }
        }

        // 3) Ekran'dan türeyenler (geçişli)
        var tabanAdi = adaylar.ToDictionary(a => a.c.Identifier.Text, a => TabanAdi(a.c), StringComparer.Ordinal);
        bool Tureyen(string ad, int derinlik)
        {
            if (derinlik > 32 || !tabanAdi.TryGetValue(ad, out var b) || b == null) return false;
            return b == Kaynaklar.EKRAN_SINIF || Tureyen(b, derinlik + 1);
        }
        foreach (var (dosya, c, cu) in adaylar.OrderBy(a => a.dosya, StringComparer.Ordinal)
                     .ThenBy(a => a.c.Identifier.Text, StringComparer.Ordinal))
        {
            var ad = c.Identifier.Text;
            if (ad == Kaynaklar.EKRAN_SINIF || !Tureyen(ad, 0)) continue;
            if (c.Modifiers.Any(SyntaxKind.AbstractKeyword)) continue;
            if (t.Bul(ad) != null)
            {
                t.Hatalar.Add(Hata(dosya, Kaynaklar.Satir(c), $"{ad}: page object birden çok kez tanımlı"));
                continue;
            }
            t.Nesneler.Add(new Nesne(ad, dosya, Kaynaklar.IlkCumle(c), Metotlar(dosya, c, t.Hatalar),
                Kimlikleri(dosya, c, kimlikler), TabanAdi(c)));
        }

        // 4) Fikstürler
        if (taban == null)
        {
            t.Hatalar.Add(Hata(Kaynaklar.ALTYAPI + "/" + Kaynaklar.TABAN_SINIF + ".cs", 0,
                "TestTabani bulunamadı (Altyapi/ altında)"));
        }
        else
        {
            var fikstur = new SortedSet<string>(StringComparer.Ordinal);
            foreach (var p in taban.Members.OfType<PropertyDeclarationSyntax>())
            {
                if (p.Modifiers.Any(SyntaxKind.StaticKeyword)) continue;
                bool gorunur = p.Modifiers.Any(SyntaxKind.PublicKeyword) || p.Modifiers.Any(SyntaxKind.ProtectedKeyword);
                if (!gorunur || p.Modifiers.Any(SyntaxKind.PrivateKeyword)) continue;
                var tur = SonAd(p.Type);
                if (tur != null && t.Bul(tur) != null) fikstur.Add(p.Identifier.Text);
            }
            t.Fikstürler = fikstur.ToList();
            foreach (var n in t.Nesneler)
            {
                if (!ErisimciVar(taban, n.Sinif))
                    t.Hatalar.Add(Hata(tabanDosya!, Kaynaklar.Satir(taban),
                        $"{n.Sinif}: TestTabani'nda erişimcisi yok (beklenen: özellik {n.Sinif} {n.Sinif})"));
            }
        }
        return t;
    }

    /// <summary>Erişimci adı → page object sınıfı (TestTabani özelliğinin türü).</summary>
    public static Dictionary<string, string> Erisimciler(string kok, Tablo t)
    {
        var sonuc = new Dictionary<string, string>(StringComparer.Ordinal);
        var yol = Kaynaklar.CsDosyalari(kok).Where(g => g.StartsWith(Kaynaklar.ALTYAPI + "/", StringComparison.Ordinal));
        foreach (var g in yol)
        {
            var cu = (CompilationUnitSyntax)Kaynaklar.Ayristir(Kaynaklar.Oku(Path.Combine(kok, g)), g).GetRoot();
            var taban = UstDuzeySiniflar(cu).FirstOrDefault(c => c.Identifier.Text == Kaynaklar.TABAN_SINIF);
            if (taban == null) continue;
            foreach (var p in taban.Members.OfType<PropertyDeclarationSyntax>())
            {
                var tur = SonAd(p.Type);
                if (tur != null && t.Fikstürler.Contains(p.Identifier.Text)) sonuc[p.Identifier.Text] = tur;
            }
            break;
        }
        return sonuc;
    }

    static bool ErisimciVar(ClassDeclarationSyntax taban, string sinif) =>
        taban.Members.OfType<PropertyDeclarationSyntax>().Any(p =>
            !p.Modifiers.Any(SyntaxKind.StaticKeyword) && !p.Modifiers.Any(SyntaxKind.PrivateKeyword)
            && (p.Modifiers.Any(SyntaxKind.PublicKeyword) || p.Modifiers.Any(SyntaxKind.ProtectedKeyword))
            && SonAd(p.Type) == sinif);

    public static IEnumerable<ClassDeclarationSyntax> UstDuzeySiniflar(CompilationUnitSyntax cu)
    {
        foreach (var m in cu.Members)
        {
            if (m is ClassDeclarationSyntax c) yield return c;
            else if (m is BaseNamespaceDeclarationSyntax ns)
                foreach (var c2 in ns.Members.OfType<ClassDeclarationSyntax>()) yield return c2;
        }
    }

    static string? TabanAdi(ClassDeclarationSyntax c) =>
        c.BaseList?.Types.Count > 0 ? SonAd(c.BaseList.Types[0].Type) : null;

    static string? SonAd(TypeSyntax t) => t switch
    {
        IdentifierNameSyntax i => i.Identifier.Text,
        QualifiedNameSyntax q => q.Right.Identifier.Text,
        AliasQualifiedNameSyntax a => a.Name.Identifier.Text,
        _ => null,
    };

    static List<Metot> Metotlar(string dosya, ClassDeclarationSyntax c, List<Harita> hatalar)
    {
        var cikti = new List<Metot>();
        var gorulen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var m in c.Members.OfType<MethodDeclarationSyntax>())
        {
            if (!m.Modifiers.Any(SyntaxKind.PublicKeyword) || m.Modifiers.Any(SyntaxKind.StaticKeyword)) continue;
            var ad = m.Identifier.Text;
            int satir = Kaynaklar.Satir(m);
            if (!gorulen.Add(ad))
            {
                hatalar.Add(Hata(dosya, satir, $"{c.Identifier.Text}.{ad}: aşırı yükleme sözleşme dışı (ilki kullanılır)"));
                continue;
            }
            if (m.TypeParameterList != null)
            {
                hatalar.Add(Hata(dosya, satir, $"{c.Identifier.Text}.{ad}: genel (generic) metot sözleşme dışı"));
                continue;
            }
            var (donus, async, donusOk) = Donus(m.ReturnType);
            if (!donusOk)
            {
                hatalar.Add(Hata(dosya, satir, $"{c.Identifier.Text}.{ad}: dönüş türü sözleşme dışı ({m.ReturnType})"));
                continue;
            }
            var ps = new List<Harita>();
            bool ok = true;
            foreach (var p in m.ParameterList.Parameters)
            {
                var tur = p.Type == null ? null : NormalTur(p.Type);
                bool ozel = p.Modifiers.Count > 0;
                if (tur == null || ozel)
                {
                    hatalar.Add(Hata(dosya, satir,
                        $"{c.Identifier.Text}.{ad}: parametre {p.Identifier.Text} sözleşme dışı ({p}); yalnız string/int/long/double/bool"));
                    ok = false;
                    break;
                }
                ps.Add(new Harita { ["name"] = p.Identifier.Text, ["type"] = tur, ["optional"] = p.Default != null });
            }
            if (!ok) continue;
            cikti.Add(new Metot(ad, ps, donus, async, Kaynaklar.IlkCumle(m), satir));
        }
        return cikti;
    }

    static (string donus, bool async, bool ok) Donus(TypeSyntax t)
    {
        if (t is PredefinedTypeSyntax p && p.Keyword.IsKind(SyntaxKind.VoidKeyword)) return ("void", false, true);
        var ad = t.ToString();
        if (ad is "Task" or "System.Threading.Tasks.Task") return ("void", true, true);
        if (t is GenericNameSyntax g && g.Identifier.Text == "Task" && g.TypeArgumentList.Arguments.Count == 1)
        {
            var n = NormalTur(g.TypeArgumentList.Arguments[0]);
            return (n ?? "", true, n != null);
        }
        var d = NormalTur(t);
        return (d ?? "", false, d != null);
    }

    static Harita Kimlikleri(string dosya, ClassDeclarationSyntax c,
        Dictionary<string, (string dosya, KimlikDosyasi.Kimlik k)> kimlikler)
    {
        var bulunan = new SortedDictionary<string, Harita>(StringComparer.Ordinal);
        foreach (var ma in c.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
        {
            if (ma.Parent is MemberAccessExpressionSyntax ust && ust.Expression == ma) continue; // en dış zincir
            var metin = string.Concat(ma.ToString().Where(ch => !char.IsWhiteSpace(ch)));
            string? anahtar = null;
            var parcalar = metin.Split('.');
            for (int i = 0; i < parcalar.Length; i++)
            {
                var aday = string.Join(".", parcalar.Skip(i));
                if (kimlikler.ContainsKey(aday) && (i == 0 || parcalar[i - 1] == KimlikDosyasi.SINIF))
                {
                    anahtar = aday;
                    break;
                }
            }
            if (anahtar == null) continue;
            var (kd, k) = kimlikler[anahtar];
            bulunan[anahtar] = new Harita
            {
                ["testId"] = k.TestIdDegeri,
                ["role"] = "",
                ["name"] = "",
                ["intent"] = k.Niyet,
                ["prefix"] = k.Onek,
                ["file"] = kd,
                ["line"] = k.Satir,
            };
        }
        var h = new Harita();
        foreach (var (a, v) in bulunan) h[a] = v;
        return h;
    }
}

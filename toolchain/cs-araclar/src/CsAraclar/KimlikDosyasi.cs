using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Antreklabs.Tp.CsAraclar;

/// <summary>
/// `Pages/Kimlikler.cs` (web) / `Ekranlar/Kimlikler.cs` (windows) — SAF VERİ.
///
/// Dosyada yalnızca: isteğe bağlı dosya kapsamlı `namespace X;`, tek üst düzey
/// `public static class Kimlikler`, iç içe `public static class` grupları ve
/// `public const string AD = "literal";` sabitleri (düz literal; verbatim, ham, enterpolasyonlu ya da
/// kaçışlı değil). Başka her şey (using, metot, alan, özellik, öznitelik, başka tür, birleştirme …)
/// bir HATA'dır ve o öğe atlanır. Belge yorumu ilk cümlesi = `intent`; `_ONEK` ile biten sabit
/// önektir. Anahtar: grup yolu + sabit adı, noktayla (`Login.USERNAME`, `Catalog.ProductCard.ADD_TO_CART`).
/// </summary>
public static class KimlikDosyasi
{
    public const string DOSYA_ADI = "Kimlikler.cs";
    public const string SINIF = "Kimlikler";
    public const string ONEK_SONEKI = "_ONEK";

    /// <summary>data-testid / erişilebilirlik kimliği biçimi (TS ast-guard ile aynı).</summary>
    public static readonly Regex TestId = new(@"\A[A-Za-z0-9][A-Za-z0-9_.:-]*\z", RegexOptions.CultureInvariant);

    public sealed record Kimlik(string Anahtar, string TestIdDegeri, bool Onek, string Niyet, int Satir, SyntaxToken Literal);

    public sealed record Hata(string Kod, int Satir, string Mesaj);

    public sealed record Sonuc(List<string> Gruplar, Dictionary<string, Kimlik> Kimlikler, List<Hata> Hatalar)
    {
        public bool Saf => Hatalar.Count == 0;
    }

    public static string Yol(string platform) => $"{Kaynaklar.NesneDizini(platform)}/{DOSYA_ADI}";

    public static Sonuc Coz(string metin)
    {
        var hatalar = KarakterDenetimi.Denetle(metin).Select(b => new Hata(b.kod, b.satir, b.mesaj)).ToList();
        var agac = Kaynaklar.Ayristir(metin, DOSYA_ADI);
        foreach (var (satir, mesaj) in Kaynaklar.SozdizimiHatalari(agac))
            hatalar.Add(new Hata("parse_error", satir, mesaj));
        var s = Coz((CompilationUnitSyntax)agac.GetRoot());
        hatalar.AddRange(s.Hatalar);
        return s with { Hatalar = hatalar };
    }

    public static Sonuc Coz(CompilationUnitSyntax cu)
    {
        var hatalar = new List<Hata>();
        var kimlikler = new Dictionary<string, Kimlik>();
        var gruplar = new List<string>();
        foreach (var t in cu.DescendantTrivia(descendIntoTrivia: true))
        {
            if (t.IsDirective || t.IsKind(SyntaxKind.DisabledTextTrivia))
                hatalar.Add(new Hata("forbidden_statement", Kaynaklar.Satir(t.Token), "önişlemci yönergesi yasak"));
        }
        foreach (var u in cu.Usings)
            hatalar.Add(new Hata("forbidden_statement", Kaynaklar.Satir(u), $"Kimlikler saf veridir: using yasak ({u.Name})"));
        foreach (var e in cu.Externs)
            hatalar.Add(new Hata("forbidden_statement", Kaynaklar.Satir(e), "extern alias yasak"));
        foreach (var a in cu.AttributeLists)
            hatalar.Add(new Hata("forbidden_statement", Kaynaklar.Satir(a), "derleme düzeyi öznitelik yasak"));

        IEnumerable<MemberDeclarationSyntax> uyeler = cu.Members;
        if (cu.Members.Count > 0 && cu.Members[0] is FileScopedNamespaceDeclarationSyntax ns)
        {
            if (ns.Usings.Count > 0 || ns.Externs.Count > 0 || ns.AttributeLists.Count > 0)
                hatalar.Add(new Hata("forbidden_statement", Kaynaklar.Satir(ns), "ad alanında using/öznitelik yasak"));
            uyeler = ns.Members.Concat(cu.Members.Skip(1));
        }
        ClassDeclarationSyntax? kok = null;
        foreach (var t in uyeler)
        {
            if (kok == null && t is ClassDeclarationSyntax c && c.Identifier.Text == SINIF) kok = c;
            else
                hatalar.Add(new Hata("forbidden_statement", Kaynaklar.Satir(t),
                    "Kimlikler.cs'de tek üst düzey tür olmalı: public static class Kimlikler"));
        }
        if (kok == null)
        {
            hatalar.Add(new Hata("forbidden_statement", 1, "public static class Kimlikler bulunamadı"));
            return new Sonuc(gruplar, kimlikler, hatalar);
        }
        SinifBasligi(kok, SINIF, hatalar);
        Uyeler(kok, new List<string>(), true, gruplar, kimlikler, hatalar);
        return new Sonuc(gruplar, kimlikler, hatalar);
    }

    static void SinifBasligi(ClassDeclarationSyntax c, string yol, List<Hata> hatalar)
    {
        int satir = Kaynaklar.Satir(c);
        var nit = c.Modifiers.Select(m => m.Text).OrderBy(x => x, System.StringComparer.Ordinal).ToList();
        if (!nit.SequenceEqual(new[] { "public", "static" }))
            hatalar.Add(new Hata("forbidden_statement", satir, yol + ": niteleyiciler 'public static' olmalı"));
        if (c.AttributeLists.Count > 0) hatalar.Add(new Hata("forbidden_statement", satir, yol + ": öznitelik yasak"));
        if (c.BaseList != null) hatalar.Add(new Hata("forbidden_statement", satir, yol + ": taban tür yasak"));
        if (c.TypeParameterList != null || c.ConstraintClauses.Count > 0 || c.ParameterList != null)
            hatalar.Add(new Hata("forbidden_statement", satir, yol + ": tür parametresi / birincil kurucu yasak"));
    }

    static void Uyeler(ClassDeclarationSyntax sinif, List<string> yol, bool kok, List<string> gruplar,
        Dictionary<string, Kimlik> kimlikler, List<Hata> hatalar)
    {
        var konum = yol.Count == 0 ? SINIF : string.Join(".", yol);
        foreach (var uye in sinif.Members)
        {
            int satir = Kaynaklar.Satir(uye);
            if (uye is ClassDeclarationSyntax g)
            {
                var altYol = new List<string>(yol) { g.Identifier.Text };
                var ad = string.Join(".", altYol);
                int once = hatalar.Count;
                SinifBasligi(g, ad, hatalar);
                if (hatalar.Count > once) continue;
                if (kok)
                {
                    if (gruplar.Contains(g.Identifier.Text))
                    {
                        hatalar.Add(new Hata("duplicate_key", satir, ad + ": grup birden çok kez tanımlı"));
                        continue;
                    }
                    gruplar.Add(g.Identifier.Text);
                }
                Uyeler(g, altYol, false, gruplar, kimlikler, hatalar);
            }
            else if (uye is FieldDeclarationSyntax f)
            {
                Sabit(f, yol, konum, kimlikler, hatalar);
            }
            else
            {
                hatalar.Add(new Hata("forbidden_statement", satir,
                    konum + ": beklenmeyen öğe (yalnızca iç içe public static class ve public const string sabiti)"));
            }
        }
    }

    static void Sabit(FieldDeclarationSyntax f, List<string> yol, string konum,
        Dictionary<string, Kimlik> kimlikler, List<Hata> hatalar)
    {
        int satir = Kaynaklar.Satir(f);
        var nit = f.Modifiers.Select(m => m.Text).OrderBy(x => x, System.StringComparer.Ordinal).ToList();
        if (!nit.SequenceEqual(new[] { "const", "public" }) || f.AttributeLists.Count > 0)
        {
            hatalar.Add(new Hata("forbidden_statement", satir, konum + ": sabit 'public const string' olmalı (özniteliksiz)"));
            return;
        }
        if (f.Declaration.Variables.Count != 1)
        {
            hatalar.Add(new Hata("forbidden_statement", satir, konum + ": bildirim başına tek sabit"));
            return;
        }
        var v = f.Declaration.Variables[0];
        var ad = v.Identifier.Text;
        if (f.Declaration.Type is not PredefinedTypeSyntax p || !p.Keyword.IsKind(SyntaxKind.StringKeyword))
        {
            hatalar.Add(new Hata("forbidden_statement", satir, $"{konum}.{ad}: tür string olmalı"));
            return;
        }
        if (v.Initializer?.Value is not LiteralExpressionSyntax lit
            || !lit.Token.IsKind(SyntaxKind.StringLiteralToken)
            || !lit.Token.Text.StartsWith('"'))
        {
            hatalar.Add(new Hata("non_literal_value", satir, $"{konum}.{ad}: değer yalnızca düz string literal olabilir"));
            return;
        }
        var anahtar = string.Join(".", yol.Append(ad));
        if (kimlikler.ContainsKey(anahtar))
        {
            hatalar.Add(new Hata("duplicate_key", satir, anahtar + ": birden çok kez tanımlı"));
            return;
        }
        var deger = lit.Token.ValueText;
        if (!TestId.IsMatch(deger) || lit.Token.Text != "\"" + deger + "\"")
            hatalar.Add(new Hata("invalid_testid", satir,
                $"{anahtar}: geçersiz kimlik değeri '{Kaynaklar.TekSatir(lit.Token.Text, 80)}'"));
        kimlikler[anahtar] = new Kimlik(anahtar, deger, ad.EndsWith(ONEK_SONEKI, System.StringComparison.Ordinal),
            Kaynaklar.IlkCumle(f), satir, lit.Token);
    }
}

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Antreklabs.Tp.CsAraclar;

/// <summary>Sıralı JSON nesnesi (ekleme sırası korunur).</summary>
public sealed class Harita : Dictionary<string, object?>
{
}

/// <summary>Kaynak okuma, ayrıştırma ve küçük yardımcılar (yalnız AYRIŞTIRMA; derleme yok).</summary>
public static class Kaynaklar
{
    public const string WEB = "web";
    public const string WINDOWS = "windows";

    /// <summary>Platformun page object / ekran dizini.</summary>
    public static string NesneDizini(string platform) => platform == WEB ? "Pages" : "Ekranlar";

    public const string ALTYAPI = "Altyapi";
    public const string TABAN_SINIF = "TestTabani";
    public const string EKRAN_SINIF = "Ekran";
    public const string URETILEN_DIZIN = "Tests/Generated";
    public const string URETILEN_AD_ALANI = "Antreklabs.Bayi.Tests.Generated";

    static readonly string[] HaricDizinler = { "bin", "obj", "TestResults", "node_modules" };

    public static readonly CSharpParseOptions Secenekler =
        new(LanguageVersion.Latest, DocumentationMode.Parse, SourceCodeKind.Regular);

    static readonly UTF8Encoding KatiUtf8 = new(false, true);

    public static string Oku(string yol)
    {
        var bayt = File.ReadAllBytes(yol);
        try
        {
            var metin = KatiUtf8.GetString(bayt);
            return metin.Length > 0 && metin[0] == '﻿' ? metin[1..] : metin;
        }
        catch (DecoderFallbackException e)
        {
            throw new IOException($"{yol}: UTF-8 değil ({e.Message})");
        }
    }

    public static SyntaxTree Ayristir(string metin, string yol = "") =>
        CSharpSyntaxTree.ParseText(metin, Secenekler, yol);

    /// <summary>Ayrıştırma hataları (yalnız Error önem düzeyi).</summary>
    public static List<(int satir, string mesaj)> SozdizimiHatalari(SyntaxTree agac) =>
        agac.GetDiagnostics()
            .Where(d => d.Severity == DiagnosticSeverity.Error)
            .Select(d => (d.Location.GetLineSpan().StartLinePosition.Line + 1, d.GetMessage()))
            .ToList();

    public static int Satir(SyntaxNode n) => n.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    public static int Satir(SyntaxToken t) => t.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    /// <summary>Platform: açıkça verilmişse o; yoksa `Pages/` → web, `Ekranlar/` → windows.</summary>
    public static string Platform(string kok, string? verilen)
    {
        if (!string.IsNullOrEmpty(verilen))
        {
            if (verilen != WEB && verilen != WINDOWS)
                throw new ArgumentException("--platform yalnızca web ya da windows olabilir");
            return verilen;
        }
        bool web = Directory.Exists(Path.Combine(kok, "Pages"));
        bool win = Directory.Exists(Path.Combine(kok, "Ekranlar"));
        if (web && !win) return WEB;
        if (win && !web) return WINDOWS;
        throw new ArgumentException(web
            ? "kökte hem Pages/ hem Ekranlar/ var; --platform verin"
            : "kökte Pages/ (web) ya da Ekranlar/ (windows) bulunamadı");
    }

    /// <summary>Kök altındaki .cs dosyaları (göreli, `/` ayraçlı, sıralı; bin/obj hariç, sembolik bağlar izlenmez).</summary>
    public static List<string> CsDosyalari(string kok)
    {
        var tam = Path.GetFullPath(kok);
        var cikti = new List<string>();
        Gez(tam, tam, cikti);
        cikti.Sort(StringComparer.Ordinal);
        return cikti;
    }

    static void Gez(string kok, string dizin, List<string> cikti)
    {
        foreach (var d in Directory.GetDirectories(dizin))
        {
            var ad = Path.GetFileName(d);
            if (HaricDizinler.Contains(ad) || ad.StartsWith('.')) continue;
            if (new DirectoryInfo(d).LinkTarget != null) continue;
            Gez(kok, d, cikti);
        }
        foreach (var f in Directory.GetFiles(dizin, "*.cs"))
        {
            if (new FileInfo(f).LinkTarget != null) continue;
            cikti.Add(Gorel(kok, f));
        }
    }

    public static string Gorel(string kok, string yol) =>
        Path.GetRelativePath(kok, yol).Replace('\\', '/');

    /// <summary>Kökün içinde kalan, normalize edilmiş göreli yol mu?</summary>
    public static bool GuvenliGorel(string yol) =>
        !string.IsNullOrEmpty(yol)
        && !yol.StartsWith('/')
        && !yol.Contains('\\')
        && !yol.Contains(':')
        && yol.Split('/').All(p => p.Length > 0 && p != "." && p != "..");

    /// <summary>`/// &lt;summary&gt;` ilk cümlesi (boşluklar sadeleştirilir; yoksa "").</summary>
    public static string IlkCumle(SyntaxNode dugum)
    {
        foreach (var trivia in dugum.GetLeadingTrivia())
        {
            if (trivia.GetStructure() is not DocumentationCommentTriviaSyntax doc) continue;
            var ozet = doc.Content.OfType<XmlElementSyntax>()
                .FirstOrDefault(e => e.StartTag.Name.LocalName.Text == "summary");
            var sb = new StringBuilder();
            IEnumerable<XmlNodeSyntax> icerik = ozet != null ? ozet.Content : doc.Content;
            foreach (var n in icerik) MetniTopla(n, sb);
            var metin = Regex.Replace(sb.ToString(), @"\s+", " ").Trim();
            var m = Regex.Match(metin, @"^.*?[.!?](?=\s|$)");
            return m.Success ? m.Value : metin;
        }
        return "";
    }

    static void MetniTopla(XmlNodeSyntax n, StringBuilder sb)
    {
        switch (n)
        {
            case XmlTextSyntax t:
                foreach (var tok in t.TextTokens)
                    sb.Append(tok.IsKind(SyntaxKind.XmlTextLiteralNewLineToken) ? " " : tok.Text);
                break;
            case XmlElementSyntax e:
                foreach (var c in e.Content) MetniTopla(c, sb);
                break;
            case XmlEmptyElementSyntax bos:
                var cref = bos.Attributes.OfType<XmlCrefAttributeSyntax>().FirstOrDefault();
                var adAttr = bos.Attributes.OfType<XmlNameAttributeSyntax>().FirstOrDefault();
                if (cref != null) sb.Append(cref.Cref.ToString());
                else if (adAttr != null) sb.Append(adAttr.Identifier.ToString());
                break;
        }
    }

    public static string TekSatir(string s, int azami)
    {
        var t = Regex.Replace(s, @"\s+", " ");
        return t.Length <= azami ? t : t[..azami] + "…";
    }

    static readonly JsonSerializerOptions TekSatirJson = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = false,
    };

    static readonly JsonSerializerOptions GirintiliJson = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = true,
    };

    public static string Json(object deger) => JsonSerializer.Serialize(deger, TekSatirJson);

    public static string JsonGirintili(object deger) => JsonSerializer.Serialize(deger, GirintiliJson);

    public static Harita Ihlal(string kod, string dosya, int satir, string mesaj)
    {
        var m = new Harita { ["code"] = kod, ["file"] = dosya };
        if (satir > 0) m["line"] = satir;
        m["message"] = mesaj;
        return m;
    }
}

/// <summary>
/// Kaynak metin düzeyinde karakter denetimi (AST'den ÖNCE): görünmez biçim karakterleri (yön
/// denetimi — "Trojan Source", sıfır genişlik), satır/paragraf ayırıcıları, sekme ve satır sonu
/// dışındaki kontrol karakterleri reddedilir. İnsan incelemesinde görülen metin derlenen metinle
/// aynı olmalıdır. (C#'ta `\uXXXX` kaçışı yalnız literal ve tanımlayıcıda işlenir; literal içinde
/// serbesttir — üretici görünmez karakterleri böyle basar —, tanımlayıcıdaki kaçış koruyucuda
/// ayrıca reddedilir.)
/// </summary>
public static class KarakterDenetimi
{
    public static List<(string kod, int satir, string mesaj)> Denetle(string metin)
    {
        var cikti = new List<(string, int, string)>();
        int satir = 1;
        for (int i = 0; i < metin.Length;)
        {
            int cp = KodNoktasi(metin, i, out int n);
            if (cp == '\n') satir++;
            else if (Yasak(cp))
            {
                cikti.Add(("forbidden_character", satir, $"görünmez/kontrol karakteri yasak (U+{cp:X4})"));
                break;
            }
            i += n;
        }
        return cikti;
    }

    /// <summary>`i` konumundaki kod noktası (yedek çift birleşir; eşsiz yedek kendisi döner).</summary>
    public static int KodNoktasi(string s, int i, out int n)
    {
        if (char.IsHighSurrogate(s[i]) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]))
        {
            n = 2;
            return char.ConvertToUtf32(s[i], s[i + 1]);
        }
        n = 1;
        return s[i];
    }

    public static bool Yasak(int cp)
    {
        if (cp == '\n' || cp == '\r' || cp == '\t') return false;
        if (cp is >= 0xD800 and <= 0xDFFF) return true; // eşsiz yedek
        var tur = System.Globalization.CharUnicodeInfo.GetUnicodeCategory(cp);
        return tur is System.Globalization.UnicodeCategory.Control
            or System.Globalization.UnicodeCategory.Format
            or System.Globalization.UnicodeCategory.LineSeparator
            or System.Globalization.UnicodeCategory.ParagraphSeparator
            or System.Globalization.UnicodeCategory.PrivateUse
            or System.Globalization.UnicodeCategory.Surrogate
            or System.Globalization.UnicodeCategory.OtherNotAssigned;
    }
}

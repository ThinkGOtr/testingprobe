using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Antreklabs.Tp.CsAraclar;

/// <summary>
/// Üretilen test izin listesi (014 §3.2; java-araclar guard karşılığı). Şablonlar:
/// `rules/templates/playwright_nunit.cs.j2` (web) ve `appium_nunit.cs.j2` (windows).
/// Yalnız `//` yorumları, sabit `using` kümesi, dosya kapsamlı `Antreklabs.Bayi.Tests.Generated`
/// ad alanı, en çok bir `[Bayi("…")]`, TestTabani'ndan türeyen tek `public class &lt;DosyaAdı&gt;`, tek
/// parametresiz `[Test]` metodu `Senaryo` ve gövdede yalnız
/// `await &lt;Erişimci&gt;.&lt;Metot&gt;(&lt;literal&gt;…);` (web) / `&lt;Erişimci&gt;.&lt;Metot&gt;(&lt;literal&gt;…);` (windows).
/// </summary>
public static class UretilenTestKoruyucu
{
    public const string BASLIK = "// AI-generated — AI Testing Probe (CasesToCode).";
    public const string TEST_METODU = "Senaryo";

    static readonly Regex DosyaAdi = new(@"\A[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests\.cs\z", RegexOptions.CultureInvariant);
    static readonly Regex BayiRe = new(@"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\z", RegexOptions.CultureInvariant);
    static readonly Regex KategoriRe = new(@"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\z", RegexOptions.CultureInvariant);
    public static readonly Regex SirAdi = new(@"\ATP_TESTVERI_[A-Z0-9_]{1,64}\z", RegexOptions.CultureInvariant);

    static readonly string[] WebUsing = { "System.Threading.Tasks", "Antreklabs.Bayi.Altyapi", "NUnit.Framework" };
    static readonly string[] WinUsing = { "Antreklabs.Bayi.Altyapi", "NUnit.Framework" };

    /// <summary>Ham sürücü / tarayıcı tutamaçları (üretilen test yalnız erişimcileri çağırır).</summary>
    static readonly HashSet<string> HamSurucu = new(StringComparer.Ordinal)
    {
        "Page", "Context", "Browser", "Playwright", "Driver", "Surucu", "Sayfa", "Tarayici", "Baglam",
        "page", "context", "browser", "playwright", "driver", "surucu", "sayfa", "tarayici", "baglam",
    };

    /// <summary>Statik çağrı sayılan bilinen tür / ad alanı kökleri.</summary>
    static readonly HashSet<string> StatikTurler = new(StringComparer.Ordinal)
    {
        "System", "Console", "Environment", "File", "Directory", "Path", "Process", "Assert", "TestContext",
        "Activator", "Type", "AppDomain", "Assembly", "Marshal", "GC", "Math", "Convert", "Task", "Thread",
        "Gizli", "Microsoft", "NUnit", "Antreklabs", "TestTabani", "Kimlikler", "Bayi",
    };

    sealed class Bulgular
    {
        public readonly List<Harita> Liste = new();
        public void Ekle(string kod, string dosya, int satir, string mesaj) => Liste.Add(Kaynaklar.Ihlal(kod, dosya, satir, mesaj));
    }

    public static Harita Denetle(string kok, IList<string> dosyalar, bool kimlikler, string? platformVerilen)
    {
        kok = Path.GetFullPath(kok);
        if (!Directory.Exists(kok)) throw new IOException("kök dizini okunamadı: " + kok);
        var tablo = SembolCikarici.Cikar(kok, platformVerilen);
        var erisimci = SembolCikarici.Erisimciler(kok, tablo);
        var b = new Bulgular();
        var denetlenen = new List<string>();
        foreach (var d in dosyalar)
        {
            denetlenen.Add(d);
            Dosya(kok, d, tablo, erisimci, b);
        }
        var kimlikDosyalari = new List<string>();
        if (kimlikler)
        {
            var yol = KimlikDosyasi.Yol(tablo.Platform);
            var tam = Path.Combine(kok, yol);
            if (!File.Exists(tam) || new FileInfo(tam).LinkTarget != null)
            {
                b.Ekle("locator_file_missing", yol, 0, "Kimlikler.cs bulunamadı");
            }
            else
            {
                kimlikDosyalari.Add(yol);
                foreach (var h in KimlikDosyasi.Coz(Kaynaklar.Oku(tam)).Hatalar) b.Ekle(h.Kod, yol, h.Satir, h.Mesaj);
            }
        }
        var ok = b.Liste.Count == 0;
        return new Harita
        {
            ["tool"] = "cs-araclar",
            ["schema_version"] = 1,
            ["mode"] = "generated",
            ["platform"] = tablo.Platform,
            ["ok"] = ok,
            ["noop"] = denetlenen.Count == 0 && !kimlikler && ok,
            ["root"] = ".",
            ["files"] = denetlenen,
            ["locator_files"] = kimlikDosyalari,
            ["changed_files"] = new List<object>(),
            ["testid_changes"] = new List<object>(),
            ["added_entries"] = new List<object>(),
            ["removed_entries"] = new List<object>(),
            ["violations"] = b.Liste,
            ["summary"] = (ok ? "Üretilen test koruması geçti" : "Üretilen test koruması başarısız")
                + $" (C#, {tablo.Platform}) · dosya: {denetlenen.Count}" + (ok ? "" : $" · ihlal: {b.Liste.Count}"),
        };
    }

    static void Dosya(string kok, string d, SembolCikarici.Tablo tablo, Dictionary<string, string> erisimci, Bulgular b)
    {
        bool web = tablo.Platform == Kaynaklar.WEB;
        var ad = d.Split('/').Last();
        if (!Kaynaklar.GuvenliGorel(d) || !d.StartsWith(Kaynaklar.URETILEN_DIZIN + "/", StringComparison.Ordinal)
            || d.Count(c => c == '/') != 2 || !DosyaAdi.IsMatch(ad))
        {
            b.Ekle("file_location", d, 0,
                $"üretilen test yalnızca {Kaynaklar.URETILEN_DIZIN}/<Story><Platform>C<sıra>_<uuid8>Tests.cs olabilir");
            return;
        }
        var tam = Path.Combine(kok, d);
        if (!File.Exists(tam) || new FileInfo(tam).LinkTarget != null
            || new DirectoryInfo(Path.GetDirectoryName(tam)!).LinkTarget != null)
        {
            b.Ekle("file_location", d, 0, "dosya yok ya da sembolik bağ");
            return;
        }
        string metin;
        try
        {
            metin = Kaynaklar.Oku(tam);
        }
        catch (IOException e)
        {
            b.Ekle("parse_error", d, 0, e.Message);
            return;
        }
        int once = b.Liste.Count;
        foreach (var (kod, satir, mesaj) in KarakterDenetimi.Denetle(metin)) b.Ekle(kod, d, satir, mesaj);
        var ilk = metin.Split('\n')[0];
        if (!ilk.StartsWith(BASLIK, StringComparison.Ordinal))
            b.Ekle("missing_header", d, 1, "ilk satır '" + BASLIK + "' ile başlamalı");
        var agac = Kaynaklar.Ayristir(metin, d);
        var hatalar = Kaynaklar.SozdizimiHatalari(agac);
        if (hatalar.Count > 0)
        {
            foreach (var (satir, mesaj) in hatalar.Take(5)) b.Ekle("parse_error", d, satir, mesaj);
            return;
        }
        if (b.Liste.Count > once && b.Liste.Skip(once).Any(v => (string)v["code"]! == "forbidden_character")) return;
        var cu = (CompilationUnitSyntax)agac.GetRoot();

        // Yorum ve önişlemci
        foreach (var t in cu.DescendantTrivia(descendIntoTrivia: true))
        {
            if (t.IsKind(SyntaxKind.WhitespaceTrivia) || t.IsKind(SyntaxKind.EndOfLineTrivia)
                || t.IsKind(SyntaxKind.SingleLineCommentTrivia))
                continue;
            if (t.IsDirective || t.IsKind(SyntaxKind.DisabledTextTrivia) || t.IsKind(SyntaxKind.PreprocessingMessageTrivia))
            {
                b.Ekle("forbidden_statement", d, Satir(t), "önişlemci yönergesi (#…) yasak");
                return;
            }
            if (t.Token.Parent is DocumentationCommentTriviaSyntax || t.IsKind(SyntaxKind.SingleLineDocumentationCommentTrivia)
                || t.IsKind(SyntaxKind.MultiLineDocumentationCommentTrivia) || t.IsKind(SyntaxKind.MultiLineCommentTrivia))
            {
                b.Ekle("comment_form", d, Satir(t), "yalnızca // yorumlarına izin verilir");
                return;
            }
        }
        foreach (var tok in cu.DescendantTokens())
        {
            if (tok.IsKind(SyntaxKind.IdentifierToken) && (tok.Text.Contains('\\') || tok.Text.StartsWith('@')))
            {
                b.Ekle("unicode_escape", d, Kaynaklar.Satir(tok), $"kaçışlı/verbatim tanımlayıcı yasak ({tok.Text})");
                return;
            }
        }

        // using
        if (cu.Externs.Count > 0 || cu.AttributeLists.Count > 0)
            b.Ekle("forbidden_statement", d, Kaynaklar.Satir(cu), "extern alias / derleme düzeyi öznitelik yasak");
        var izinli = web ? WebUsing : WinUsing;
        var gorulen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var u in cu.Usings)
        {
            var isim = u.Name?.ToString() ?? "";
            if (u.StaticKeyword != default || u.Alias != null || u.GlobalKeyword != default || u.UnsafeKeyword != default
                || !izinli.Contains(isim) || !gorulen.Add(isim))
                b.Ekle("forbidden_import", d, Kaynaklar.Satir(u), $"izin verilmeyen using: {u.ToString().Trim()}");
        }
        foreach (var e in izinli.Where(x => !gorulen.Contains(x)))
            b.Ekle("missing_import", d, 0, "eksik using: " + e);

        // ad alanı
        if (cu.Members.Count != 1 || cu.Members[0] is not FileScopedNamespaceDeclarationSyntax ns)
        {
            b.Ekle(cu.Members.Any(m => m is BaseNamespaceDeclarationSyntax) ? "wrong_package" : "top_level_type", d,
                cu.Members.Count > 0 ? Kaynaklar.Satir(cu.Members[0]) : 0,
                $"tek dosya kapsamlı ad alanı olmalı: namespace {Kaynaklar.URETILEN_AD_ALANI};");
            return;
        }
        if (ns.Name.ToString() != Kaynaklar.URETILEN_AD_ALANI)
            b.Ekle("wrong_package", d, Kaynaklar.Satir(ns), $"ad alanı {Kaynaklar.URETILEN_AD_ALANI} olmalı ({ns.Name})");
        if (ns.Usings.Count > 0 || ns.Externs.Count > 0 || ns.AttributeLists.Count > 0)
            b.Ekle("forbidden_import", d, Kaynaklar.Satir(ns), "ad alanı içinde using yasak");
        if (ns.Members.Count != 1 || ns.Members[0] is not ClassDeclarationSyntax c)
        {
            b.Ekle("top_level_type", d, ns.Members.Count > 0 ? Kaynaklar.Satir(ns.Members[0]) : 0,
                "tek üst düzey tür olmalı: public class <DosyaAdı> : TestTabani");
            return;
        }
        Sinif(c, ad[..^3], web, tablo, erisimci, d, b);
    }

    static int Satir(SyntaxTrivia t) => t.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    static void Sinif(ClassDeclarationSyntax c, string beklenenAd, bool web, SembolCikarici.Tablo tablo,
        Dictionary<string, string> erisimci, string d, Bulgular b)
    {
        int satir = Kaynaklar.Satir(c);
        var nit = c.Modifiers.Select(m => m.Text).ToList();
        if (c.Identifier.Text != beklenenAd || !nit.SequenceEqual(new[] { "public" })
            || c.TypeParameterList != null || c.ConstraintClauses.Count > 0 || c.ParameterList != null
            || c.BaseList == null || c.BaseList.Types.Count != 1
            || c.BaseList.Types[0] is not SimpleBaseTypeSyntax { Type: IdentifierNameSyntax { Identifier.Text: Kaynaklar.TABAN_SINIF } })
        {
            b.Ekle("class_shape", d, satir, $"sınıf 'public class {beklenenAd} : TestTabani' olmalı");
        }
        var attrs = c.AttributeLists.SelectMany(l => l.Attributes).ToList();
        bool bicim = c.AttributeLists.All(l => l.Target == null && l.Attributes.Count == 1);
        if (!bicim || attrs.Count > 1 || attrs.Any(a => !BayiOzniteligi(a)))
            b.Ekle("annotation", d, satir, "sınıfta yalnızca tek [Bayi(\"<bayi>\")] özniteliği olabilir");

        var metotlar = new List<MethodDeclarationSyntax>();
        foreach (var uye in c.Members)
        {
            if (uye is MethodDeclarationSyntax m) metotlar.Add(m);
            else if (uye is FieldDeclarationSyntax or PropertyDeclarationSyntax or EventFieldDeclarationSyntax)
                b.Ekle("field", d, Kaynaklar.Satir(uye), "alan/özellik yasak");
            else b.Ekle("forbidden_member", d, Kaynaklar.Satir(uye), "yalnızca tek test metodu olabilir");
        }
        if (metotlar.Count != 1)
        {
            b.Ekle("test_method_count", d, satir, $"tam olarak bir test metodu olmalı ({metotlar.Count})");
            if (metotlar.Count == 0) return;
        }
        foreach (var m in metotlar) Metot(m, web, tablo, erisimci, d, b);
    }

    static bool BayiOzniteligi(AttributeSyntax a) =>
        a.Name is IdentifierNameSyntax { Identifier.Text: "Bayi" }
        && a.ArgumentList is { Arguments.Count: 1 } al
        && al.Arguments[0].NameEquals == null && al.Arguments[0].NameColon == null
        && DuzDize(al.Arguments[0].Expression, out var v) && BayiRe.IsMatch(v);

    /// <summary>Düz (verbatim/ham/enterpolasyonsuz) string literal mı; değeri.</summary>
    static bool DuzDize(ExpressionSyntax e, out string deger)
    {
        deger = "";
        if (e is not LiteralExpressionSyntax lit || !lit.Token.IsKind(SyntaxKind.StringLiteralToken)
            || !lit.Token.Text.StartsWith('"'))
            return false;
        deger = lit.Token.ValueText;
        return true;
    }

    static void Metot(MethodDeclarationSyntax m, bool web, SembolCikarici.Tablo tablo,
        Dictionary<string, string> erisimci, string d, Bulgular b)
    {
        int satir = Kaynaklar.Satir(m);
        var nit = m.Modifiers.Select(x => x.Text).OrderBy(x => x, StringComparer.Ordinal).ToList();
        var beklenenNit = web ? new[] { "async", "public" } : new[] { "public" };
        bool donus = web
            ? m.ReturnType is IdentifierNameSyntax { Identifier.Text: "Task" }
            : m.ReturnType is PredefinedTypeSyntax p && p.Keyword.IsKind(SyntaxKind.VoidKeyword);
        if (m.Identifier.Text != TEST_METODU || !nit.SequenceEqual(beklenenNit) || !donus
            || m.ParameterList.Parameters.Count > 0 || m.TypeParameterList != null || m.ConstraintClauses.Count > 0
            || m.ExplicitInterfaceSpecifier != null || m.Body == null || m.ExpressionBody != null)
        {
            b.Ekle("test_method", d, satir,
                web ? "test metodu 'public async Task Senaryo() { … }' olmalı" : "test metodu 'public void Senaryo() { … }' olmalı");
        }
        int test = 0, aciklama = 0;
        bool kotu = false;
        foreach (var l in m.AttributeLists)
        {
            if (l.Target != null || l.Attributes.Count != 1) { kotu = true; continue; }
            var a = l.Attributes[0];
            var ad = a.Name is IdentifierNameSyntax i ? i.Identifier.Text : "";
            var args = a.ArgumentList?.Arguments ?? default;
            bool tekDize(Regex? re) => args.Count == 1 && args[0].NameEquals == null && args[0].NameColon == null
                && DuzDize(args[0].Expression, out var v) && (re == null || re.IsMatch(v));
            switch (ad)
            {
                case "Test" when a.ArgumentList == null || a.ArgumentList.Arguments.Count == 0: test++; break;
                case "Category" when tekDize(KategoriRe): break;
                case "Description" when tekDize(null): aciklama++; break;
                default: kotu = true; break;
            }
        }
        if (kotu || test != 1 || aciklama > 1)
            b.Ekle("test_annotation", d, satir, "metot öznitelikleri yalnızca [Test], [Category(\"…\")], [Description(\"…\")]");
        if (m.Body == null) return;
        foreach (var st in m.Body.Statements) Deyim(st, web, tablo, erisimci, d, b);
    }

    static void Deyim(StatementSyntax st, bool web, SembolCikarici.Tablo tablo,
        Dictionary<string, string> erisimci, string d, Bulgular b)
    {
        int satir = Kaynaklar.Satir(st);
        switch (st)
        {
            case IfStatementSyntax or SwitchStatementSyntax:
                b.Ekle("branch", d, satir, "dallanma yasak");
                return;
            case ForStatementSyntax or ForEachStatementSyntax or WhileStatementSyntax or DoStatementSyntax
                or ForEachVariableStatementSyntax:
                b.Ekle("loop", d, satir, "döngü yasak");
                return;
            case LocalDeclarationStatementSyntax or LocalFunctionStatementSyntax:
                b.Ekle("local_variable", d, satir, "yerel değişken/işlev yasak");
                return;
            case ExpressionStatementSyntax es:
                break;
            default:
                b.Ekle("forbidden_statement", d, satir, $"izin verilmeyen deyim: {st.Kind()}");
                return;
        }
        var ifade = ((ExpressionStatementSyntax)st).Expression;
        // İçerikte yasak düğümler (biçimden bağımsız, daha anlamlı kod)
        foreach (var n in ifade.DescendantNodesAndSelf())
        {
            switch (n)
            {
                case LambdaExpressionSyntax or AnonymousMethodExpressionSyntax:
                    b.Ekle("lambda", d, satir, "lambda/anonim metot yasak");
                    return;
                case BaseObjectCreationExpressionSyntax or ArrayCreationExpressionSyntax
                    or ImplicitArrayCreationExpressionSyntax or CollectionExpressionSyntax or AnonymousObjectCreationExpressionSyntax:
                    b.Ekle("new", d, satir, "nesne/dizi oluşturma yasak");
                    return;
                case AssignmentExpressionSyntax or PostfixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.PostIncrementExpression or (int)SyntaxKind.PostDecrementExpression }
                    or PrefixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.PreIncrementExpression or (int)SyntaxKind.PreDecrementExpression }:
                    b.Ekle("assignment", d, satir, "atama yasak");
                    return;
                case ThisExpressionSyntax or BaseExpressionSyntax:
                    b.Ekle("forbidden_statement", d, satir, "this/base yasak");
                    return;
                case ConditionalExpressionSyntax or ConditionalAccessExpressionSyntax or SwitchExpressionSyntax:
                    b.Ekle("branch", d, satir, "koşullu ifade yasak");
                    return;
            }
        }
        InvocationExpressionSyntax? cagri;
        if (web)
        {
            if (ifade is not AwaitExpressionSyntax aw || aw.Expression is not InvocationExpressionSyntax iw)
            {
                if (ifade is InvocationExpressionSyntax ic && ThreadSleep(ic)) { b.Ekle("thread_sleep", d, satir, "Thread.Sleep/Task.Delay yasak"); return; }
                b.Ekle("call_shape", d, satir, "deyim 'await <Erişimci>.<Metot>(<literal>…);' olmalı");
                return;
            }
            cagri = iw;
        }
        else
        {
            if (ifade is not InvocationExpressionSyntax iw)
            {
                b.Ekle("call_shape", d, satir, "deyim '<Erişimci>.<Metot>(<literal>…);' olmalı");
                return;
            }
            cagri = iw;
        }
        if (ThreadSleep(cagri)) { b.Ekle("thread_sleep", d, satir, "Thread.Sleep/Task.Delay yasak"); return; }
        if (cagri.Expression is IdentifierNameSyntax tek)
        {
            b.Ekle("static_call", d, satir, $"niteliksiz çağrı yasak: {tek.Identifier.Text}(…)");
            return;
        }
        if (cagri.Expression is not MemberAccessExpressionSyntax ma || !ma.IsKind(SyntaxKind.SimpleMemberAccessExpression)
            || ma.Name is not IdentifierNameSyntax metotAd)
        {
            b.Ekle("call_shape", d, satir, "çağrı '<Erişimci>.<Metot>(…)' biçiminde olmalı");
            return;
        }
        if (ma.Expression is not IdentifierNameSyntax acc)
        {
            bool ham = ma.Expression.DescendantNodesAndSelf().OfType<IdentifierNameSyntax>().Any(i => HamSurucu.Contains(i.Identifier.Text));
            b.Ekle(ham ? "raw_driver" : (ma.Expression is MemberAccessExpressionSyntax ? "field_access" : "call_shape"),
                d, satir, "çağrı yalnızca bir ekran erişimcisi üzerinden olabilir (zincir yok)");
            return;
        }
        var erisimAdi = acc.Identifier.Text;
        if (HamSurucu.Contains(erisimAdi)) { b.Ekle("raw_driver", d, satir, $"ham sürücü/tarayıcı kullanımı yasak: {erisimAdi}"); return; }
        if (!erisimci.TryGetValue(erisimAdi, out var sinif))
        {
            b.Ekle(StatikTurler.Contains(erisimAdi) ? "static_call" : "unknown_accessor", d, satir,
                $"bilinmeyen erişimci: {erisimAdi} (TestTabani fikstürleri: {string.Join(", ", tablo.Fikstürler)})");
            return;
        }
        var nesne = tablo.Bul(sinif);
        var metot = nesne?.Metotlar.FirstOrDefault(x => x.Ad == metotAd.Identifier.Text);
        if (metot == null)
        {
            b.Ekle("unknown_method", d, satir, $"{sinif}.{metotAd.Identifier.Text} sembol tablosunda yok");
            return;
        }
        if (web && !metot.Async)
            b.Ekle("call_shape", d, satir, $"{sinif}.{metot.Ad} Task döndürmüyor; await edilemez");
        if (!web && metot.Async)
            b.Ekle("call_shape", d, satir, $"{sinif}.{metot.Ad} Task döndürüyor; windows ekranları eşzamanlıdır");
        var argumanlar = cagri.ArgumentList.Arguments;
        int zorunlu = metot.Parametreler.Count(p => !(bool)p["optional"]!);
        if (argumanlar.Count < zorunlu || argumanlar.Count > metot.Parametreler.Count)
        {
            b.Ekle("arg_count", d, satir, $"{sinif}.{metot.Ad}: {metot.Parametreler.Count} argüman bekleniyor ({argumanlar.Count})");
            return;
        }
        for (int i = 0; i < argumanlar.Count; i++)
        {
            var a = argumanlar[i];
            var beklenenTur = (string)metot.Parametreler[i]["type"]!;
            if (a.NameColon != null || a.RefKindKeyword != default)
            {
                b.Ekle("non_literal_argument", d, satir, "adlı/ref argüman yasak");
                continue;
            }
            var tur = LiteralTuru(a.Expression);
            if (tur == null)
            {
                b.Ekle("non_literal_argument", d, satir, $"argüman yalnızca literal ya da Gizli(\"TP_TESTVERI_…\") olabilir: {Kaynaklar.TekSatir(a.ToString(), 60)}");
                continue;
            }
            if (!Uyumlu(tur, beklenenTur))
                b.Ekle("arg_type", d, satir, $"{sinif}.{metot.Ad}: {i + 1}. argüman {beklenenTur} bekler ({tur})");
        }
    }

    static bool ThreadSleep(InvocationExpressionSyntax c) =>
        c.Expression is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax t, Name: IdentifierNameSyntax n }
        && ((t.Identifier.Text == "Thread" && n.Identifier.Text == "Sleep") || (t.Identifier.Text == "Task" && n.Identifier.Text == "Delay"));

    /// <summary>Literal türü: string | integer | long | real | boolean | null | secret; değilse null.</summary>
    static string? LiteralTuru(ExpressionSyntax e)
    {
        if (e is PrefixUnaryExpressionSyntax u && u.IsKind(SyntaxKind.UnaryMinusExpression)
            && u.Operand is LiteralExpressionSyntax { RawKind: (int)SyntaxKind.NumericLiteralExpression } sayi)
            return SayiTuru(sayi.Token);
        if (e is InvocationExpressionSyntax inv && inv.Expression is IdentifierNameSyntax { Identifier.Text: "Gizli" }
            && inv.ArgumentList.Arguments.Count == 1 && inv.ArgumentList.Arguments[0] is var ga
            && ga.NameColon == null && ga.RefKindKeyword == default
            && DuzDize(ga.Expression, out var sir) && SirAdi.IsMatch(sir)
            && ((LiteralExpressionSyntax)ga.Expression).Token.Text == "\"" + sir + "\"")
            return "secret";
        if (e is not LiteralExpressionSyntax lit) return null;
        switch (lit.Kind())
        {
            case SyntaxKind.StringLiteralExpression:
                return DuzDize(lit, out _) ? "string" : null;
            case SyntaxKind.NumericLiteralExpression:
                return SayiTuru(lit.Token);
            case SyntaxKind.TrueLiteralExpression:
            case SyntaxKind.FalseLiteralExpression:
                return "boolean";
            case SyntaxKind.NullLiteralExpression:
                return "null";
            default:
                return null;
        }
    }

    static string? SayiTuru(SyntaxToken t) => t.Value switch
    {
        int => "integer",
        long => t.Text.EndsWith('L') || t.Text.EndsWith('l') ? "long" : null,
        double => t.Text.EndsWith('d') || t.Text.EndsWith('D') ? null : "real",
        _ => null, // uint/ulong/float/decimal sonekleri şablonun üretmediği biçimlerdir
    };

    static bool Uyumlu(string literal, string beklenen) => (literal, beklenen) switch
    {
        ("string", "string") or ("secret", "string") or ("null", "string") => true,
        ("integer", "int" or "long" or "double") => true,
        ("long", "long" or "double") => true,
        ("real", "double") => true,
        ("boolean", "boolean") => true,
        _ => false,
    };
}

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using Antreklabs.Tp.CsAraclar;
using NUnit.Framework;

namespace CsAraclar.Tests;

/// <summary>Örnek proje kopyası (geçici dizin) ve CLI yardımcıları.</summary>
public static class Yardimci
{
    public static string Ornek(string ad) => Path.Combine(TestContext.CurrentContext.TestDirectory, "Ornekler", ad);

    public static string Beklenen(string ad) => Path.Combine(TestContext.CurrentContext.TestDirectory, "beklenen", ad);

    public const string WEB_TEST = "Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs";
    public const string WIN_TEST = "Tests/Generated/TPD1WindowsC2_3f9b1c2eTests.cs";

    public static string Kopya(string ad)
    {
        var hedef = Path.Combine(Path.GetTempPath(), "cs-araclar-" + Guid.NewGuid().ToString("N"));
        Kopyala(Ornek(ad), hedef);
        return hedef;
    }

    static void Kopyala(string kaynak, string hedef)
    {
        Directory.CreateDirectory(hedef);
        foreach (var f in Directory.GetFiles(kaynak)) File.Copy(f, Path.Combine(hedef, Path.GetFileName(f)));
        foreach (var d in Directory.GetDirectories(kaynak)) Kopyala(d, Path.Combine(hedef, Path.GetFileName(d)));
    }

    public static (int kod, string cikti, string hata) Cli(params string[] args)
    {
        var o = new StringWriter();
        var e = new StringWriter();
        var kod = Program.Calistir(args, o, e);
        return (kod, o.ToString(), e.ToString());
    }

    public static string Oku(string yol) => File.ReadAllText(yol, new UTF8Encoding(false));

    public static void Yaz(string yol, string metin)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(yol)!);
        File.WriteAllText(yol, metin, new UTF8Encoding(false));
    }

    public static List<string> Kodlar(Harita rapor) =>
        ((List<Harita>)rapor["violations"]!).Select(v => (string)v["code"]!).ToList();
}

[TestFixture]
public class SembolTests
{
    [TestCase("e2e-csharp", "semboller-web.json")]
    [TestCase("e2e-app-csharp", "semboller-windows.json")]
    public void Sembol_tablosu_beklenenle_ayni(string ornek, string beklenen)
    {
        var (kod, cikti, _) = Yardimci.Cli("symbols", "--root", Yardimci.Ornek(ornek));
        Assert.That(kod, Is.EqualTo(0));
        var normal = JsonSerializer.Serialize(JsonDocument.Parse(cikti).RootElement,
            new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }) + "\n";
        var dosya = Yardimci.Beklenen(beklenen);
        if (Environment.GetEnvironmentVariable("CS_ARACLAR_GUNCELLE") == "1")
        {
            var kaynak = Path.GetFullPath(Path.Combine(TestContext.CurrentContext.TestDirectory, "../../../beklenen", beklenen));
            File.WriteAllText(kaynak, normal, new UTF8Encoding(false));
            Assert.Pass("güncellendi: " + kaynak);
        }
        Assert.That(normal, Is.EqualTo(Yardimci.Oku(dosya)));
    }

    [Test]
    public void Tek_satir_json_ve_alanlar()
    {
        var (kod, cikti, _) = Yardimci.Cli("symbols", "--root", Yardimci.Ornek("e2e-csharp"));
        Assert.That(kod, Is.EqualTo(0));
        Assert.That(cikti.TrimEnd('\n'), Does.Not.Contain("\n"));
        var d = JsonDocument.Parse(cikti).RootElement;
        Assert.That(d.GetProperty("lang").GetString(), Is.EqualTo("csharp"));
        Assert.That(d.GetProperty("fixtures").EnumerateArray().Select(x => x.GetString()),
            Is.EqualTo(new[] { "CartPage", "CatalogPage", "LoginPage" }));
        var login = d.GetProperty("page_objects").EnumerateArray().Single(p => p.GetProperty("class").GetString() == "LoginPage");
        Assert.That(login.GetProperty("methods").EnumerateArray().Select(m => m.GetProperty("name").GetString()),
            Is.EqualTo(new[] { "GotoAsync", "LoginAsync" }), "statik ve private metotlar dışarıda");
        Assert.That(login.GetProperty("locators").GetProperty("Login.USERNAME").GetProperty("intent").GetString(),
            Is.EqualTo("Kullanıcı adı alanı."));
    }

    [Test]
    public void Sozlesme_disi_imzalar_errors_a_yazilir()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        Yardimci.Yaz(Path.Combine(kok, "Pages/OrderPage.cs"), """
            using System.Threading.Tasks;
            namespace Antreklabs.Bayi.Pages;
            public class OrderPage : Ekran
            {
                public OrderPage() : base(null!) { }
                public Task SecAsync(string a) => Task.CompletedTask;
                public Task SecAsync(int a) => Task.CompletedTask;
                public Task ListeAsync(params string[] a) => Task.CompletedTask;
                public System.Collections.Generic.List<int> Liste() => new();
                public void Genel<T>() { }
            }
            """);
        var t = SembolCikarici.Cikar(kok, null);
        var mesajlar = t.Hatalar.Select(h => (string)h["message"]!).ToList();
        Assert.That(mesajlar, Has.Some.Contains("aşırı yükleme"));
        Assert.That(mesajlar, Has.Some.Contains("parametre a sözleşme dışı"));
        Assert.That(mesajlar, Has.Some.Contains("dönüş türü sözleşme dışı"));
        Assert.That(mesajlar, Has.Some.Contains("genel (generic)"));
        Assert.That(mesajlar, Has.Some.Contains("OrderPage: TestTabani'nda erişimcisi yok"));
        Assert.That(t.Bul("OrderPage")!.Metotlar.Select(m => m.Ad), Is.EqualTo(new[] { "SecAsync" }));
    }

    [Test]
    public void Platform_belirsizse_hata_kodu_2()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        Directory.CreateDirectory(Path.Combine(kok, "Ekranlar"));
        var (kod, cikti, _) = Yardimci.Cli("symbols", "--root", kok);
        Assert.That(kod, Is.EqualTo(2));
        Assert.That(cikti, Does.Contain("\"ok\":false"));
        Assert.That(Yardimci.Cli("symbols", "--root", kok, "--platform", "web").kod, Is.EqualTo(0));
    }
}

[TestFixture]
public class KoruyucuTests
{
    [TestCase("e2e-csharp", Yardimci.WEB_TEST)]
    [TestCase("e2e-app-csharp", Yardimci.WIN_TEST)]
    public void Golden_uretilen_test_gecer(string ornek, string dosya)
    {
        var (kod, cikti, _) = Yardimci.Cli("guard", "--root", Yardimci.Ornek(ornek), "--kimlikler", "--", dosya);
        Assert.That(kod, Is.EqualTo(0), cikti);
        var d = JsonDocument.Parse(cikti).RootElement;
        Assert.That(d.GetProperty("tool").GetString(), Is.EqualTo("cs-araclar"));
        Assert.That(d.GetProperty("ok").GetBoolean(), Is.True);
        Assert.That(d.GetProperty("files").GetArrayLength(), Is.EqualTo(1));
    }

    [Test]
    public void Dosyasiz_cagri_noop()
    {
        var r = UretilenTestKoruyucu.Denetle(Yardimci.Ornek("e2e-csharp"), Array.Empty<string>(), false, null);
        Assert.That(r["noop"], Is.True);
        Assert.That(r["ok"], Is.True);
    }

    static string Web(Func<string, string> degistir) => degistir(Yardimci.Oku(Path.Combine(Yardimci.Ornek("e2e-csharp"), Yardimci.WEB_TEST)));

    static string Win(Func<string, string> degistir) => degistir(Yardimci.Oku(Path.Combine(Yardimci.Ornek("e2e-app-csharp"), Yardimci.WIN_TEST)));

    const string LOGIN = "await LoginPage.LoginAsync(\"bayi1\", \"Demo123!\");";

    public static IEnumerable<TestCaseData> WebIhlalleri()
    {
        TestCaseData D(string ad, Func<string, string> f, string kod) => new TestCaseData(f, kod).SetName("web_" + ad);
        yield return D("baslik", s => s.Replace("// AI-generated", "// el yazımı"), "missing_header");
        yield return D("blok_yorum", s => s.Replace(LOGIN, LOGIN + " /* x */"), "comment_form");
        yield return D("belge_yorumu", s => s.Replace("    [Test]", "    /// <summary>x</summary>\n    [Test]"), "comment_form");
        yield return D("pragma", s => s.Replace("using NUnit.Framework;", "using NUnit.Framework;\n#pragma warning disable CS1998"), "forbidden_statement");
        yield return D("if_onislemci", s => s.Replace(LOGIN, "#if DEBUG\n" + LOGIN + "\n#endif"), "forbidden_statement");
        yield return D("bidi", s => s.Replace("Giriş sayfasını aç", "Giriş ‮ sayfasını aç"), "forbidden_character");
        yield return D("kacisli_tanimlayici", s => s.Replace("LoginPage.LoginAsync", "LoginP\\u0061ge.LoginAsync"), "unicode_escape");
        yield return D("verbatim_tanimlayici", s => s.Replace("LoginPage.LoginAsync", "@LoginPage.LoginAsync"), "unicode_escape");
        yield return D("using_fazla", s => s.Replace("using NUnit.Framework;", "using NUnit.Framework;\nusing System.IO;"), "forbidden_import");
        yield return D("using_static", s => s.Replace("using NUnit.Framework;", "using NUnit.Framework;\nusing static System.Console;"), "forbidden_import");
        yield return D("using_takma", s => s.Replace("using NUnit.Framework;", "using NUnit.Framework;\nusing IO = System.IO;"), "forbidden_import");
        yield return D("global_using", s => s.Replace("using NUnit.Framework;", "global using NUnit.Framework;"), "forbidden_import");
        yield return D("using_eksik", s => s.Replace("using System.Threading.Tasks;\n", ""), "missing_import");
        yield return D("yanlis_ad_alani", s => s.Replace("namespace Antreklabs.Bayi.Tests.Generated;", "namespace Antreklabs.Bayi.Baska;"), "wrong_package");
        yield return D("blok_ad_alani", s => s.Replace("namespace Antreklabs.Bayi.Tests.Generated;", "namespace Antreklabs.Bayi.Tests.Generated {") + "}\n", "wrong_package");
        yield return D("ikinci_tur", s => s + "public class Ek { }\n", "top_level_type");
        yield return D("sinif_adi", s => s.Replace("class TPD1WebC2_3f9b1c2eTests", "class Baska"), "class_shape");
        yield return D("taban", s => s.Replace(": TestTabani", ": Object"), "class_shape");
        yield return D("partial", s => s.Replace("public class", "public partial class"), "class_shape");
        yield return D("bayi_iki", s => s.Replace("[Bayi(\"bayi1\")]", "[Bayi(\"bayi1\")]\n[Bayi(\"bayi2\")]"), "annotation");
        yield return D("baska_oznitelik", s => s.Replace("[Bayi(\"bayi1\")]", "[Parallelizable]"), "annotation");
        yield return D("bayi_gecersiz", s => s.Replace("[Bayi(\"bayi1\")]", "[Bayi(\"bayi 1\")]"), "annotation");
        yield return D("alan", s => s.Replace("    [Test]", "    private int x = 1;\n    [Test]"), "field");
        yield return D("kurucu", s => s.Replace("    [Test]", "    public TPD1WebC2_3f9b1c2eTests() { }\n    [Test]"), "forbidden_member");
        yield return D("ikinci_metot", s => s.Replace("    [Test]", "    public void Yardim() { }\n    [Test]"), "test_method_count");
        yield return D("metot_adi", s => s.Replace("Task Senaryo()", "Task Baska()"), "test_method");
        yield return D("async_degil", s => s.Replace("public async Task", "public Task"), "test_method");
        yield return D("parametre", s => s.Replace("Senaryo()", "Senaryo(int x)"), "test_method");
        yield return D("test_yok", s => s.Replace("    [Test]\n", ""), "test_annotation");
        yield return D("ignore", s => s.Replace("    [Test]", "    [Test]\n    [Ignore(\"x\")]"), "test_annotation");
        yield return D("kategori_gecersiz", s => s.Replace("[Category(\"uretilen\")]", "[Category(\"üretilen x\")]"), "test_annotation");
        yield return D("if", s => s.Replace(LOGIN, "if (true) { " + LOGIN + " }"), "branch");
        yield return D("dongu", s => s.Replace(LOGIN, "for (;;) { }"), "loop");
        yield return D("yerel", s => s.Replace(LOGIN, "var x = 1;"), "local_variable");
        yield return D("lambda", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(\"a\", ((System.Func<string>)(() => \"b\"))());"), "lambda");
        yield return D("new", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(new string('a', 1), \"b\");"), "new");
        yield return D("atama", s => s.Replace(LOGIN, "System.Environment.ExitCode = 1;"), "assignment");
        yield return D("await_yok", s => s.Replace(LOGIN, "LoginPage.LoginAsync(\"bayi1\", \"Demo123!\");"), "call_shape");
        yield return D("sleep", s => s.Replace(LOGIN, "System.Threading.Thread.Sleep(5);"), "call_shape");
        yield return D("delay", s => s.Replace(LOGIN, "await Task.Delay(5);"), "thread_sleep");
        yield return D("ham_surucu", s => s.Replace(LOGIN, "await Page.GotoAsync(\"/\");"), "raw_driver");
        yield return D("statik", s => s.Replace(LOGIN, "await System.IO.File.ReadAllTextAsync(\"x\");"), "field_access");
        yield return D("statik_tur", s => s.Replace(LOGIN, "await Console.Out.FlushAsync();"), "field_access");
        yield return D("statik_cagri", s => s.Replace(LOGIN, "await Environment.Foo();"), "static_call");
        yield return D("niteliksiz", s => s.Replace(LOGIN, "await Gizli(\"TP_TESTVERI_X\");"), "static_call");
        yield return D("zincir", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(\"a\", \"b\").ConfigureAwait(false);"), "call_shape");
        yield return D("bilinmeyen_erisimci", s => s.Replace("LoginPage.LoginAsync", "OrderPage.LoginAsync"), "unknown_accessor");
        yield return D("bilinmeyen_metot", s => s.Replace("LoginPage.LoginAsync", "LoginPage.LogoutAsync"), "unknown_method");
        yield return D("arg_sayisi", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(\"bayi1\");"), "arg_count");
        yield return D("arg_turu", s => s.Replace("AddToCartAsync(\"P-001\", 7)", "AddToCartAsync(\"P-001\", \"7\")"), "arg_type");
        yield return D("arg_ondalik", s => s.Replace("AddToCartAsync(\"P-001\", 7)", "AddToCartAsync(\"P-001\", 7.5)"), "arg_type");
        yield return D("arg_degisken", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(\"bayi1\", System.Environment.UserName);"), "non_literal_argument");
        yield return D("arg_enterpolasyon", s => s.Replace(LOGIN, "await LoginPage.LoginAsync($\"bayi{1}\", \"x\");"), "non_literal_argument");
        yield return D("arg_verbatim", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(@\"bayi1\", \"x\");"), "non_literal_argument");
        yield return D("arg_adli", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(username: \"bayi1\", \"x\");"), "non_literal_argument");
        yield return D("gizli_ad", s => s.Replace(LOGIN, "await LoginPage.LoginAsync(\"bayi1\", Gizli(\"PATH\"));"), "non_literal_argument");
        yield return D("dosya_konumu", s => s, "file_location");
    }

    [TestCaseSource(nameof(WebIhlalleri))]
    public void Web_ihlali_yakalanir(Func<string, string> degistir, string kod)
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var dosya = kod == "file_location" ? "Tests/Baska.cs" : Yardimci.WEB_TEST;
        Yardimci.Yaz(Path.Combine(kok, dosya), Web(degistir));
        var r = UretilenTestKoruyucu.Denetle(kok, new[] { dosya }, false, null);
        Assert.That(Yardimci.Kodlar(r), Does.Contain(kod), Kaynaklar.JsonGirintili(r["violations"]!));
        Assert.That(r["ok"], Is.False);
    }

    [Test]
    public void Web_gecerli_varyantlar_gecer()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var metin = Web(s => s
            .Replace(LOGIN, "await LoginPage.LoginAsync(\"bayi1\", Gizli(\"TP_TESTVERI_BAYI1_PAROLA\"));")
            .Replace("[Bayi(\"bayi1\")]\n", "")
            + "")
            .Replace("await CatalogPage.OpenCartAsync();",
                "await CatalogPage.OpenCartAsync();\n        await CatalogPage.SecenekliAsync(\"k\", true, -1.25, 3000000000L);\n        await CatalogPage.SecenekliAsync(\"k\");");
        Yardimci.Yaz(Path.Combine(kok, Yardimci.WEB_TEST), metin);
        var r = UretilenTestKoruyucu.Denetle(kok, new[] { Yardimci.WEB_TEST }, true, null);
        Assert.That(r["ok"], Is.True, Kaynaklar.JsonGirintili(r["violations"]!));
    }

    public static IEnumerable<TestCaseData> WinIhlalleri()
    {
        TestCaseData D(string ad, Func<string, string> f, string kod) => new TestCaseData(f, kod).SetName("win_" + ad);
        yield return D("await", s => s.Replace("GirisEkrani.Ac();", "await GirisEkrani.Ac();"), "call_shape");
        yield return D("async_metot", s => s.Replace("public void Senaryo", "public async System.Threading.Tasks.Task Senaryo"), "test_method");
        yield return D("tasks_using", s => s.Replace("using NUnit.Framework;", "using NUnit.Framework;\nusing System.Threading.Tasks;"), "forbidden_import");
        yield return D("ham_surucu", s => s.Replace("GirisEkrani.Ac();", "Driver.Quit();"), "raw_driver");
        yield return D("arg_turu", s => s.Replace("SepeteEkle(\"P-001\", 7)", "SepeteEkle(\"P-001\", true)"), "arg_type");
        yield return D("bilinmeyen_metot", s => s.Replace("GirisEkrani.Ac();", "GirisEkrani.Kapat();"), "unknown_method");
    }

    [TestCaseSource(nameof(WinIhlalleri))]
    public void Windows_ihlali_yakalanir(Func<string, string> degistir, string kod)
    {
        var kok = Yardimci.Kopya("e2e-app-csharp");
        Yardimci.Yaz(Path.Combine(kok, Yardimci.WIN_TEST), Win(degistir));
        var r = UretilenTestKoruyucu.Denetle(kok, new[] { Yardimci.WIN_TEST }, false, null);
        Assert.That(Yardimci.Kodlar(r), Does.Contain(kod), Kaynaklar.JsonGirintili(r["violations"]!));
    }

    [Test]
    public void Web_testi_windows_kokunde_reddedilir()
    {
        var kok = Yardimci.Kopya("e2e-app-csharp");
        Yardimci.Yaz(Path.Combine(kok, Yardimci.WEB_TEST), Web(s => s));
        var r = UretilenTestKoruyucu.Denetle(kok, new[] { Yardimci.WEB_TEST }, false, null);
        Assert.That(r["ok"], Is.False);
    }

    [Test]
    public void Yol_kacisi_ve_eksik_dosya()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var r = UretilenTestKoruyucu.Denetle(kok,
            new[] { "Tests/Generated/../Generated/TPD1WebC2_3f9b1c2eTests.cs", "Tests/Generated/XC1_00000000Tests.cs" }, false, null);
        Assert.That(Yardimci.Kodlar(r), Is.EqualTo(new[] { "file_location", "file_location" }));
    }

    public static IEnumerable<TestCaseData> KimlikIhlalleri()
    {
        TestCaseData D(string ad, Func<string, string> f, string kod) => new TestCaseData(f, kod).SetName("kimlik_" + ad);
        yield return D("using", s => "using System;\n" + s, "forbidden_statement");
        yield return D("metot", s => s.Replace("    public static class Nav", "    public static string F() => \"x\";\n    public static class Nav"), "forbidden_statement");
        yield return D("birlestirme", s => s.Replace("\"login-submit\"", "\"login-\" + \"submit\""), "non_literal_value");
        yield return D("verbatim", s => s.Replace("\"login-submit\"", "@\"login-submit\""), "non_literal_value");
        yield return D("gecersiz_kimlik", s => s.Replace("\"login-submit\"", "\"login submit\""), "invalid_testid");
        yield return D("tekrar_grup", s => s.Replace("    public static class Cart", "    public static class Login { }\n    public static class Cart"), "duplicate_key");
        yield return D("readonly", s => s.Replace("public const string SUBMIT", "public static readonly string SUBMIT"), "forbidden_statement");
    }

    [TestCaseSource(nameof(KimlikIhlalleri))]
    public void Kimlikler_safligi(Func<string, string> degistir, string kod)
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var yol = Path.Combine(kok, "Pages/Kimlikler.cs");
        Yardimci.Yaz(yol, degistir(Yardimci.Oku(yol)));
        var r = UretilenTestKoruyucu.Denetle(kok, Array.Empty<string>(), true, null);
        Assert.That(Yardimci.Kodlar(r), Does.Contain(kod), Kaynaklar.JsonGirintili(r["violations"]!));
    }

    [Test]
    public void Kimlikler_yoksa_locator_file_missing()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        File.Delete(Path.Combine(kok, "Pages/Kimlikler.cs"));
        var r = UretilenTestKoruyucu.Denetle(kok, Array.Empty<string>(), true, null);
        Assert.That(Yardimci.Kodlar(r), Does.Contain("locator_file_missing"));
    }
}

[TestFixture]
public class KimlikYamasiTests
{
    [Test]
    public void Bul_tam_ve_onek()
    {
        var r = KimlikYamasi.Bul(Yardimci.Ornek("e2e-csharp"), "product-card-P-001");
        var m = (List<Harita>)r["matches"]!;
        Assert.That(m.Select(x => x["key"]), Is.EqualTo(new[] { "Catalog.PRODUCT_CARD_ONEK" }));
    }

    [Test]
    public void Yama_yalniz_literali_degistirir()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var yol = Path.Combine(kok, "Pages/Kimlikler.cs");
        var once = Yardimci.Oku(yol);
        var (kod, cikti, _) = Yardimci.Cli("locators", "patch", "--root", kok, "--old", "login-submit", "--new", "login-giris",
            "--path-prefix", "demo-app/e2e-csharp");
        Assert.That(kod, Is.EqualTo(0), cikti);
        var d = JsonDocument.Parse(cikti).RootElement;
        Assert.That(d.GetProperty("key").GetString(), Is.EqualTo("Login.SUBMIT"));
        var icerik = d.GetProperty("content").GetString()!;
        Assert.That(icerik, Is.EqualTo(once.Replace("\"login-submit\"", "\"login-giris\"")));
        Assert.That(d.GetProperty("diff").GetString(), Does.StartWith("--- a/demo-app/e2e-csharp/Pages/Kimlikler.cs\n"));
        Assert.That(Yardimci.Oku(yol), Is.EqualTo(once), "dosyaya yazılmaz");
    }

    [TestCase("product-card-", "x-")]
    [TestCase("yok-boyle", "x")]
    [TestCase("login-submit", "login-username")]
    [TestCase("login-submit", "kotu deger")]
    public void Yama_reddi_cikis_1(string eski, string yeni)
    {
        var (kod, cikti, _) = Yardimci.Cli("locators", "patch", "--root", Yardimci.Ornek("e2e-csharp"), "--old", eski, "--new", yeni);
        Assert.That(kod, Is.EqualTo(1));
        Assert.That(cikti, Does.Contain("\"ok\":false"));
    }

    static string Taban => Yardimci.Oku(Path.Combine(Yardimci.Ornek("e2e-csharp"), "Pages/Kimlikler.cs"));

    [Test]
    public void Fark_yalniz_literal_gecer()
    {
        var r = KimlikYamasi.Fark(Taban, Taban.Replace("\"login-submit\"", "\"login-go\""), "Pages/Kimlikler.cs");
        Assert.That(r["ok"], Is.True);
        var d = (List<Harita>)r["testid_changes"]!;
        Assert.That(d.Single()["entry"], Is.EqualTo("Login.SUBMIT"));
    }

    [TestCase("public const string SUBMIT", "public const string GONDER", "non_testid_change")]
    [TestCase("/// <summary>Parola alanı.</summary>", "/// <summary>Parola.</summary>", "non_testid_change")]
    [TestCase("\"product-card-\"", "\"urun-karti-\"", "prefix_changed")]
    [TestCase("        public const string SUBMIT = \"login-submit\";\n", "", "non_testid_change")]
    public void Fark_ihlalleri(string eski, string yeni, string kod)
    {
        var bas = Taban.Replace(eski, yeni);
        Assert.That(bas, Is.Not.EqualTo(Taban));
        var r = KimlikYamasi.Fark(Taban, bas, "Pages/Kimlikler.cs");
        Assert.That(Yardimci.Kodlar(r), Does.Contain(kod));
    }

    [Test]
    public void Fark_cli_cikis_kodlari()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var a = Path.Combine(kok, "a.txt");
        var b = Path.Combine(kok, "b.txt");
        Yardimci.Yaz(a, Taban);
        Yardimci.Yaz(b, Taban);
        Assert.That(Yardimci.Cli("locators", "diff", "--base", a, "--head", b).kod, Is.EqualTo(0));
        Yardimci.Yaz(b, Taban.Replace("SUBMIT", "GONDER"));
        Assert.That(Yardimci.Cli("locators", "diff", "--base", a, "--head", b).kod, Is.EqualTo(1));
        Assert.That(Yardimci.Cli("locators", "diff", "--base", a, "--head", b + ".yok").kod, Is.EqualTo(2));
    }
}

[TestFixture]
public class CliTests
{
    [Test]
    public void Kullanim_ve_hatalar()
    {
        Assert.That(Yardimci.Cli().kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("--help").kod, Is.EqualTo(0));
        Assert.That(Yardimci.Cli("yok").kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("symbols").kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("symbols", "--root", "/yok/boyle/dizin").kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("symbols", "--root", Yardimci.Ornek("e2e-csharp"), "--bilinmeyen").kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("locators").kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("locators", "find", "--root", Yardimci.Ornek("e2e-csharp")).kod, Is.EqualTo(2));
        Assert.That(Yardimci.Cli("guard", "--root", "/yok/boyle").kod, Is.EqualTo(2));
    }

    [Test]
    public void Guard_ihlal_1_out_ve_quiet()
    {
        var kok = Yardimci.Kopya("e2e-csharp");
        var rapor = Path.Combine(kok, "rapor.json");
        var (kod, cikti, hata) = Yardimci.Cli("guard", "--root", kok, "--out", rapor, "--quiet", "--", "Tests/Baska.cs");
        Assert.That(kod, Is.EqualTo(1));
        Assert.That(cikti, Is.Empty);
        Assert.That(hata, Does.Contain("[file_location]"));
        Assert.That(JsonDocument.Parse(Yardimci.Oku(rapor)).RootElement.GetProperty("ok").GetBoolean(), Is.False);
    }

    [Test]
    public void Find_cikisi()
    {
        var (kod, cikti, _) = Yardimci.Cli("locators", "find", "--root", Yardimci.Ornek("e2e-app-csharp"), "--test-id", "login-username");
        Assert.That(kod, Is.EqualTo(0));
        Assert.That(cikti, Does.Contain("\"key\":\"Giris.KULLANICI_ADI\""));
        Assert.That(cikti, Does.Contain("\"file\":\"Ekranlar/Kimlikler.cs\""));
    }
}

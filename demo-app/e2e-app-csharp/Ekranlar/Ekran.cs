using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Antreklabs.Bayi.Altyapi;
using OpenQA.Selenium;

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>
/// Ekran nesnelerinin tabanı (Java <c>ekranlar/Ekran</c>): kimlik sabitleriyle çalışan yardımcılar.
///
/// Sözleşme (plan §2.8, 014 §3.2): alt sınıfların <c>public</c> metotları sembol tablosuna girer —
/// eylem (fiil, <c>void</c>) ya da beklenti (<c>Dogrula</c> ön eki, <c>void</c>); parametreler yalnız
/// <c>string</c>, <c>int</c>, <c>long</c>, <c>double</c>, <c>bool</c>. Ad ve parametreler Java ekranıyla
/// birebirdir (PascalCase: <c>girisYap</c> → <c>GirisYap</c>); Appium .NET eşzamanlıdır, <c>Async</c> yok.
/// Bu sınıfın yardımcıları <c>protected</c>'dır, sembol tablosuna girmez.
///
/// Hata türleri: eylem ön koşulu sağlanmazsa <see cref="WebDriverTimeoutException"/> ("öğe görünmedi:
/// kimlik '…'" / "öğe tıklanabilir olmadı: kimlik '…'"); beklenti sağlanmazsa
/// <c>NUnit.Framework.AssertionException</c> ("…: beklenen &lt;x&gt;, görülen &lt;y&gt; (N ms)").
/// </summary>
public abstract class Ekran
{
    private const string Yok = "(öğe yok)";
    private static readonly string[] MetinNitelikleri = { "Name", "Value.Value", "label", "value", "text" };

    protected Ekran(UygulamaOturumu oturum)
    {
        Oturum = oturum ?? throw new ArgumentNullException(nameof(oturum));
    }

    protected UygulamaOturumu Oturum { get; }

    protected IWebDriver Surucu => Oturum.Surucu;

    protected Bekle Bekle => Oturum.Bekle;

    // ------------------------------------------------------------------ bulma

    private IWebElement? IlkGorunur(string? kapsayici, string kimlik)
    {
        IEnumerable<ISearchContext> kokler = kapsayici is null
            ? new ISearchContext[] { Surucu }
            : Surucu.FindElements(Kimlik.Bul(kapsayici));
        foreach (ISearchContext kok in kokler)
        {
            foreach (IWebElement e in kok.FindElements(Kimlik.Bul(kimlik)))
            {
                if (e.Displayed)
                {
                    return e;
                }
            }
        }
        return null;
    }

    /// <summary>Öğeyi beklemeden bir kez arar; görünür değilse null.</summary>
    protected IWebElement? HemenBul(string? kapsayici, string kimlik) => IlkGorunur(kapsayici, kimlik);

    private static string Ad(string? kapsayici, string kimlik) =>
        kapsayici is null ? $"'{kimlik}'" : $"'{kapsayici}' içinde '{kimlik}'";

    /// <summary>Öğe görünür olana kadar bekler; olmazsa <see cref="WebDriverTimeoutException"/>.</summary>
    protected IWebElement GorunurBekle(string kimlik) => GorunurBekle(null, kimlik);

    /// <summary>Kapsayıcı içindeki öğe görünür olana kadar bekler.</summary>
    protected IWebElement GorunurBekle(string? kapsayici, string kimlik) =>
        Bekle.Kosul("öğe görünmedi: kimlik " + Ad(kapsayici, kimlik), () => HemenBul(kapsayici, kimlik));

    /// <summary>İki öğeden biri görünene kadar bekler.</summary>
    protected void BiriGorunurBekle(string kimlik1, string kimlik2) =>
        Bekle.Kosul(
            $"öğe görünmedi: kimlik '{kimlik1}' ya da '{kimlik2}'",
            () => IlkGorunur(null, kimlik1) is not null || IlkGorunur(null, kimlik2) is not null);

    // ------------------------------------------------------------------ eylemler

    /// <summary>Öğeye dokunur (görünür ve etkin olmasını bekler).</summary>
    protected void Dokun(string kimlik) => Dokun(null, kimlik);

    /// <summary>Kapsayıcı içindeki öğeye dokunur.</summary>
    protected void Dokun(string? kapsayici, string kimlik)
    {
        IWebElement e = Bekle.Kosul(
            "öğe tıklanabilir olmadı: kimlik " + Ad(kapsayici, kimlik),
            () =>
            {
                IWebElement? g = HemenBul(kapsayici, kimlik);
                return g is not null && g.Enabled ? g : null;
            });
        e.Click();
    }

    /// <summary>Alana metin yazar (önce temizler).</summary>
    protected void Yaz(string kimlik, string metin)
    {
        IWebElement e = GorunurBekle(kimlik);
        e.Clear();
        e.SendKeys(metin);
    }

    // ------------------------------------------------------------------ metin

    /// <summary>Boşlukları sadeleştirir: NBSP / dar NBSP → boşluk, ardışık boşluk → tek, kırpılır.</summary>
    protected internal static string Sade(string? s) =>
        s is null ? "" : Regex.Replace(s.Replace(' ', ' ').Replace(' ', ' '), "\\s+", " ").Trim();

    private static string KendiMetni(IWebElement e)
    {
        string t = e.Text;
        if (!string.IsNullOrWhiteSpace(t))
        {
            return Sade(t);
        }
        foreach (string nitelik in MetinNitelikleri)
        {
            try
            {
                string? v = e.GetAttribute(nitelik);
                if (!string.IsNullOrWhiteSpace(v) && v != "null")
                {
                    return Sade(v);
                }
            }
            catch (WebDriverException)
            {
                // nitelik bu platformda yok
            }
        }
        return "";
    }

    /// <summary>Öğenin görünen metni: kendi metni, yoksa alt öğelerin metinleri.</summary>
    protected string Metin(IWebElement e)
    {
        string kendi = KendiMetni(e);
        return kendi.Length == 0 ? AltMetinler(e) : kendi;
    }

    /// <summary>Öğenin ve tüm alt öğelerinin metinleri, boşlukla birleşik.</summary>
    protected string TumMetin(IWebElement e) => Sade(KendiMetni(e) + " " + AltMetinler(e));

    private static string AltMetinler(IWebElement e)
    {
        var parcalar = new List<string>();
        foreach (IWebElement alt in e.FindElements(By.XPath(".//*")))
        {
            string t = KendiMetni(alt);
            if (t.Length > 0 && !parcalar.Contains(t))
            {
                parcalar.Add(t);
            }
        }
        return Sade(string.Join(" ", parcalar));
    }

    private string GorulenMetin(string kimlik, bool tum)
    {
        IWebElement? e = HemenBul(null, kimlik);
        if (e is null)
        {
            return Yok;
        }
        return tum ? TumMetin(e) : Metin(e);
    }

    /// <summary>Tam sayı metni (kültürden bağımsız).</summary>
    protected static string Sayi(int n) => n.ToString(CultureInfo.InvariantCulture);

    // ------------------------------------------------------------------ beklentiler (AssertionException)

    /// <summary>Öğenin metni tam olarak beklenen (sadeleştirilmiş) olmalı.</summary>
    protected void MetinOlmali(string kimlik, string beklenen)
    {
        string b = Sade(beklenen);
        Bekle.Dogrula($"'{kimlik}' metni", b, () => GorulenMetin(kimlik, false), () => b == GorulenMetin(kimlik, false));
    }

    /// <summary>Öğenin metni kalıba tam uymalı.</summary>
    protected void MetinKalibinaUymali(string kimlik, Regex kalip) =>
        Bekle.Dogrula(
            $"'{kimlik}' metni",
            "/" + kalip + "/",
            () => GorulenMetin(kimlik, false),
            () => kalip.IsMatch(GorulenMetin(kimlik, false)));

    /// <summary>Öğenin metni beklenen parçayı içermeli.</summary>
    protected void MetinIcermeli(string kimlik, string parca)
    {
        string p = Sade(parca);
        Bekle.Dogrula(
            $"'{kimlik}' metni", "… " + p + " …", () => GorulenMetin(kimlik, false),
            () => GorulenMetin(kimlik, false).Contains(p, StringComparison.Ordinal));
    }

    /// <summary>Öğe ve alt öğelerinin metni beklenen parçayı içermeli.</summary>
    protected void TumMetinIcermeli(string kimlik, string parca)
    {
        string p = Sade(parca);
        Bekle.Dogrula(
            $"'{kimlik}' içeriği", "… " + p + " …", () => GorulenMetin(kimlik, true),
            () => GorulenMetin(kimlik, true).Contains(p, StringComparison.Ordinal));
    }

    /// <summary>Öğe görünür olmalı.</summary>
    protected void GorunurOlmali(string kimlik) =>
        Bekle.Dogrula($"'{kimlik}' görünürlüğü", "görünür", () => Yok, () => HemenBul(null, kimlik) is not null);

    /// <summary>Öğe ekranda olmamalı (web: <c>toHaveCount(0)</c>).</summary>
    protected void YokOlmali(string kimlik) =>
        Bekle.Dogrula($"'{kimlik}' yokluğu", Yok, () => "görünür", () => HemenBul(null, kimlik) is null);

    /// <summary>Öğe etkin (true) ya da pasif (false) olmalı.</summary>
    protected void EtkinOlmali(string kimlik, bool etkin)
    {
        string beklenen = etkin ? "etkin" : "pasif";
        Bekle.Dogrula(
            $"'{kimlik}' durumu",
            beklenen,
            () =>
            {
                IWebElement? e = HemenBul(null, kimlik);
                return e is null ? Yok : e.Enabled ? "etkin" : "pasif";
            },
            () =>
            {
                IWebElement? e = HemenBul(null, kimlik);
                return e is not null && e.Enabled == etkin;
            });
    }

    /// <summary>Kimliklerden biri ekranda var mı (beklemeden).</summary>
    protected bool Var(params string[] kimlikler) => kimlikler.Any(k => HemenBul(null, k) is not null);
}

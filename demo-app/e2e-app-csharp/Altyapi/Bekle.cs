using System;
using System.Diagnostics;
using System.Threading;
using NUnit.Framework;
using OpenQA.Selenium;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Deterministik bekleme (Java <c>Bekle</c>): koşul sağlanana ya da üst sınır dolana kadar sorgular.
/// Yalnızca açık bekleme; örtük bekleme 0; sabit uyku (sleep) yasak. İki hata türü bilerek ayrıdır —
/// triage ve kırarak doğrula buna dayanır:
/// <list type="bullet">
///   <item><see cref="Kosul{T}"/>: eylem ön koşulu → <see cref="WebDriverTimeoutException"/>
///     (iletisi açıklamadır, ör. "öğe görünmedi: kimlik 'login-username'").</item>
///   <item><see cref="Dogrula"/>: beklenen sonuç → <see cref="AssertionException"/>
///     ("&lt;açıklama&gt;: beklenen &lt;x&gt;, görülen &lt;y&gt; (N ms)").</item>
/// </list>
/// </summary>
public sealed class Bekle
{
    /// <summary>Sorgu aralığı.</summary>
    public static readonly TimeSpan Aralik = TimeSpan.FromMilliseconds(250);

    public Bekle(TimeSpan ustSinir)
    {
        UstSinir = ustSinir;
    }

    public TimeSpan UstSinir { get; }

    private static void Uyu(TimeSpan sure)
    {
        using var olay = new ManualResetEventSlim(false);
        olay.Wait(sure);
    }

    /// <summary>Koşul null/false dışında bir değer döndürene kadar bekler ve o değeri döndürür.</summary>
    /// <exception cref="WebDriverTimeoutException">süre dolarsa (açıklama iletide)</exception>
    public T Kosul<T>(string aciklama, Func<T?> kosul)
        where T : class
    {
        var saat = Stopwatch.StartNew();
        while (true)
        {
            try
            {
                T? sonuc = kosul();
                if (sonuc is not null && !(sonuc is bool b && !b))
                {
                    return sonuc;
                }
            }
            catch (NoSuchElementException)
            {
                // yoksay: yeniden dene
            }
            catch (StaleElementReferenceException)
            {
                // yoksay: yeniden dene
            }
            if (saat.Elapsed >= UstSinir)
            {
                throw new WebDriverTimeoutException(ZamanAsimiIletisi(aciklama, UstSinir));
            }
            Uyu(Aralik);
        }
    }

    /// <summary>
    /// Selenium Java <c>FluentWait</c> iletisiyle aynı biçim (triage kalıpları ortak):
    /// "Expected condition failed: &lt;açıklama&gt; (tried for N second(s) with 250 milliseconds interval)".
    /// </summary>
    public static string ZamanAsimiIletisi(string aciklama, TimeSpan ustSinir) =>
        $"Expected condition failed: {aciklama} (tried for {(long)ustSinir.TotalSeconds} second(s) with "
        + $"{(long)Aralik.TotalMilliseconds} milliseconds interval)";

    /// <summary>Koşul doğru olana kadar bekler (<see cref="Kosul{T}"/>'un bool biçimi).</summary>
    public void Kosul(string aciklama, Func<bool> kosul) =>
        Kosul<object>(aciklama, () => kosul() ? (object)true : null);

    /// <summary>Beklenen sonuç sağlanana kadar bekler; sağlanmazsa son görülen değerle
    /// <see cref="AssertionException"/>.</summary>
    public void Dogrula(string aciklama, string beklenen, Func<string> gorulen, Func<bool> saglandi)
    {
        try
        {
            Kosul(aciklama, saglandi);
        }
        catch (WebDriverTimeoutException)
        {
            string son;
            try
            {
                son = gorulen();
            }
            catch (Exception okumaHatasi)
            {
                son = $"(okunamadı: {okumaHatasi.GetType().Name})";
            }
            throw new AssertionException(
                $"{aciklama}: beklenen <{beklenen}>, görülen <{son}> ({(long)UstSinir.TotalMilliseconds} ms)");
        }
    }
}

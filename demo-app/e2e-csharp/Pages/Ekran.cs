using System;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Playwright;
using NUnit.Framework;
using static Microsoft.Playwright.Assertions;

namespace Antreklabs.Bayi.Pages;

/// <summary>
/// Page object'lerin tabanı (TS: <c>../e2e/pages/support.ts</c>; Java: e2e-java <c>ekranlar/Ekran</c>).
///
/// Sözleşme (014 §3.2): page object <c>Pages/</c> altında bu sınıftan türer; sınıf adı, parametre adları
/// ve sırası TypeScript page object'iyle birebirdir; metot adı TS adının PascalCase + <c>Async</c>
/// biçimidir (<c>login</c> → <c>LoginAsync</c>, <c>goto</c> → <c>GotoAsync</c>). Metotlar <c>Task</c>
/// döner (yalnız <c>OrderPage.ReadOrderNumberAsync</c> <c>Task&lt;string&gt;</c>); parametreler yalnız
/// <c>string/int/long/double/bool</c>. Elemanlar yalnız <see cref="Kimlikler"/> sabitleriyle
/// (data-testid) bulunur; beklentiler Playwright'ın kendiliğinden yeniden deneyen doğrulamalarıdır,
/// sabit bekleme yoktur.
///
/// Hata türleri (triage ve kırarak doğrulamanın kırmızı denetimi bunlara dayanır):
/// beklenti karşılanmadı → <see cref="AssertionException"/> (Playwright doğrulama iletisi aynen korunur:
/// <c>Locator expected to have text '…'</c> / <c>But was: …</c> / <c>Call log:</c> …); eylem
/// sırasında eleman bulunamadı ya da süre aşıldı → <c>Microsoft.Playwright.TimeoutException</c>
/// (<c>Timeout 5000ms exceeded.</c> + <c>waiting for GetByTestId("…")</c>); gezinme hatası →
/// <c>Microsoft.Playwright.PlaywrightException</c> (<c>net::ERR_…</c>).
/// </summary>
public abstract class Ekran
{
    /// <summary>Sayfa yolları (TS: <c>paths</c>).</summary>
    protected const string LoginYolu = "/giris";
    protected const string CatalogYolu = "/katalog";
    protected const string CartYolu = "/sepet";
    protected const string OrdersYolu = "/siparisler";

    protected Ekran(IPage page)
    {
        Page = page ?? throw new ArgumentNullException(nameof(page), "page boş olamaz");
    }

    /// <summary>Sayfa (alt sınıflar doğrudan kullanır; TS: <c>this.page</c>).</summary>
    protected IPage Page { get; }

    /// <summary>
    /// Kimliğin data-testid değeri (TS: <c>testIdOf</c>). Önek kimliklerde (sonu <c>-</c>) sonek zorunludur;
    /// sabit kimliklerde sonek verilmez.
    /// </summary>
    public static string KimlikDegeri(string kimlik, string? sonek)
    {
        var onek = kimlik.EndsWith('-');
        var sonekVar = !string.IsNullOrEmpty(sonek);
        if (onek && !sonekVar)
        {
            throw new ArgumentException($"'{kimlik}' önek kimliği için sonek (ürün kodu / sipariş no) gerekli");
        }
        if (!onek && sonekVar)
        {
            throw new ArgumentException($"'{kimlik}' sabit kimliktir; sonek verilmemeli");
        }
        return onek ? kimlik + sonek : kimlik;
    }

    /// <summary>Sabit kimlikli eleman (<c>GetByTestId</c>).</summary>
    protected ILocator Kimlik(string kimlik) => Page.GetByTestId(KimlikDegeri(kimlik, null));

    /// <summary>Önek kimlikli eleman: <c>onek + sonek</c> (ör. "product-price-" + "P-001").</summary>
    protected ILocator Kimlik(string onek, string sonek) => Page.GetByTestId(KimlikDegeri(onek, sonek));

    /// <summary>Kapsayıcı eleman (TS: <c>within</c> + <c>scopeTestIdOf</c>).</summary>
    protected ILocator Kapsam(string kapsamOneki, string sonek)
    {
        if (!kapsamOneki.EndsWith('-'))
        {
            throw new ArgumentException($"'{kapsamOneki}' kapsam öneki '-' ile bitmeli");
        }
        return Page.GetByTestId(KimlikDegeri(kapsamOneki, sonek));
    }

    /// <summary>Kapsayıcının içindeki eleman; önek kimlikse aynı sonek eklenir.</summary>
    protected static ILocator Kapsamda(ILocator kapsayici, string kimlik, string sonek) =>
        kapsayici.GetByTestId(KimlikDegeri(kimlik, kimlik.EndsWith('-') ? sonek : null));

    /// <summary>Yola gider (bağlamın <c>BaseURL</c>'ine göre).</summary>
    protected async Task GitAsync(string yol) => await Page.GotoAsync(yol);

    /// <summary>
    /// Beklentiyi koşar; Playwright doğrulama hatası (<c>Expect(…).To…Async</c>) NUnit doğrulama
    /// hatasına (<see cref="AssertionException"/>) çevrilir, ileti aynen korunur. Eylem/zaman aşımı
    /// hataları (<c>Microsoft.Playwright.TimeoutException</c>) olduğu gibi yükselir.
    /// </summary>
    protected static async Task DogrulaAsync(Func<Task> beklenti)
    {
        try
        {
            await beklenti();
        }
        catch (PlaywrightException e) when (DogrulamaHatasiMi(e))
        {
            throw new AssertionException(e.Message, e);
        }
    }

    /// <summary>Playwright'ın doğrulama (expect) hatası mı (eylem/zaman aşımı hatası değil)?</summary>
    public static bool DogrulamaHatasiMi(PlaywrightException e) =>
        e.Message.StartsWith("Locator expected", StringComparison.Ordinal)
        || e.Message.StartsWith("Page expected", StringComparison.Ordinal)
        || e.Message.StartsWith("Page URL expected", StringComparison.Ordinal);

    /// <summary>Koşul doğrulaması (Playwright dışı; ör. yanıt durumu): başarısızsa <see cref="AssertionException"/>.</summary>
    protected static void Dogrula(bool kosul, string ileti)
    {
        if (!kosul)
        {
            throw new AssertionException(ileti);
        }
    }

    /// <summary>Adresin verilen yolla bittiğini doğrular (yeniden denemeli).</summary>
    protected Task DogrulaYolAsync(string yol) =>
        DogrulaAsync(() => Expect(Page).ToHaveURLAsync(new Regex(Regex.Escape(yol) + "$")));
}

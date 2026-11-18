using System;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>Veri yalıtım kipi.</summary>
public enum YalitimKipi
{
    /// <summary>Her testten önce bayinin verisi <c>POST /test/reset</c> ile silinir (token gerekir).</summary>
    Sifirlama,

    /// <summary><c>TP_E2E_NO_RESET=1</c>, token yok: yalnız sepet herkese açık API ile boşaltılır.</summary>
    YalnizSepet,
}

/// <summary>
/// Test verisi yalıtımı ve "kırarak doğrula" kancaları (TS: tests/fixtures.ts <c>isolationMode</c>,
/// <c>dealerBreak</c>, <c>testApi</c>; Java: <c>TestVerisi</c>).
/// <list type="bullet">
/// <item><description>Sıfırlama: <c>POST /test/reset</c> (<c>X-Demoapp-Test-Token</c>).</description></item>
/// <item><description><c>BREAK_CAMPAIGN=1</c>: bayi kapsamlı <c>POST /test/break {kampanya:true}</c>; test sonunda geri alınır.</description></item>
/// <item><description><c>TP_FAULT=&lt;kod&gt;</c> (ekilmiş hata): <c>POST /test/break {hata:kod}</c>; ikisi birlikteyse TP_FAULT geçerlidir.</description></item>
/// </list>
/// Token yalnız istek başlığında taşınır; çağrılar bilerek Playwright'ın istek bağlamıyla DEĞİL
/// <see cref="HttpClient"/> ile yapılır (Playwright istekleri trace'e başlıkla birlikte yazılırdı).
/// </summary>
public sealed class TestVerisi : IDisposable
{
    /// <summary>Paylaşılan sırrın başlığı (API: main.py TEST_TOKEN_HEADER).</summary>
    public const string TokenBasligi = "X-Demoapp-Test-Token";

    private static readonly TimeSpan ZamanAsimi = TimeSpan.FromSeconds(10);

    private readonly Ayarlar _ayarlar;
    private readonly HttpClient _istemci;

    public TestVerisi(Ayarlar ayarlar)
    {
        _ayarlar = ayarlar;
        _istemci = new HttpClient(new HttpClientHandler { CookieContainer = new CookieContainer(), UseCookies = true })
        {
            Timeout = ZamanAsimi,
            DefaultRequestVersion = HttpVersion.Version11,
            DefaultVersionPolicy = HttpVersionPolicy.RequestVersionExact,
        };
    }

    /// <summary>Ortamdan yalıtım kipi; geçersiz birleşimlerde açıklayıcı hata.</summary>
    public static YalitimKipi Kip(Ayarlar ayarlar)
    {
        if (ayarlar.TestToken is not null)
        {
            return YalitimKipi.Sifirlama;
        }
        if (ayarlar.HataKodu is not null)
        {
            throw new InvalidOperationException(
                "TP_FAULT için DEMOAPP_TEST_TOKEN gerekir (ekilmiş hata POST /test/break ile bayi kapsamında açılır).");
        }
        if (ayarlar.KampanyaKirik)
        {
            throw new InvalidOperationException(
                "BREAK_CAMPAIGN=1 için DEMOAPP_TEST_TOKEN gerekir (kırılma POST /test/break ile bayi kapsamında açılır).");
        }
        if (ayarlar.SifirlamaYok)
        {
            return YalitimKipi.YalnizSepet;
        }
        throw new InvalidOperationException(
            "DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz. Ya token ile DEMO_API_URL verin "
            + "(ör. http://demo-app-api:8000) ya da yalnızca sepet yalıtımı için TP_E2E_NO_RESET=1 verin.");
    }

    /// <summary>Koşunun kırılması (açma, kapama gövdeleri) ya da yoksa null: TP_FAULT, sonra BREAK_CAMPAIGN.</summary>
    public static (string Ac, string Kapat)? Kirilma(Ayarlar ayarlar)
    {
        var hata = ayarlar.HataKodu;
        if (hata is not null)
        {
            return ($"\"hata\":{JsonSerializer.Serialize(hata)}", "\"hata\":null");
        }
        return ayarlar.KampanyaKirik ? ("\"kampanya\":true", "\"kampanya\":false") : null;
    }

    /// <summary><c>/test/&lt;yol&gt;</c> adresi.</summary>
    public static string TestUcu(string apiKoku, string yol) => apiKoku.TrimEnd('/') + "/test/" + yol;

    /// <summary>Bayinin verisini sıfırlar (sepet, siparişler, demo kırılması).</summary>
    public Task SifirlaAsync(string kullaniciAdi) =>
        TestUcunuCagirAsync("reset", "{\"kullanici_adi\":" + JsonSerializer.Serialize(kullaniciAdi) + "}");

    /// <summary>Bayi kapsamlı kırılmayı açar ya da kapatır (gövde parçası: <see cref="Kirilma"/>).</summary>
    public Task KirAsync(string kullaniciAdi, string govdeParcasi) =>
        TestUcunuCagirAsync("break", "{\"kullanici_adi\":" + JsonSerializer.Serialize(kullaniciAdi) + "," + govdeParcasi + "}");

    private async Task TestUcunuCagirAsync(string yol, string govde)
    {
        var token = _ayarlar.TestToken
            ?? throw new InvalidOperationException($"/test/{yol} için DEMOAPP_TEST_TOKEN gerekir");
        using var istek = new HttpRequestMessage(HttpMethod.Post, TestUcu(_ayarlar.DemoApiUrl, yol))
        {
            Content = new StringContent(govde, Encoding.UTF8, "application/json"),
        };
        istek.Headers.Add(TokenBasligi, token);
        using var yanit = await GonderAsync(istek, $"POST /test/{yol}");
        var durum = (int)yanit.StatusCode;
        if (durum / 100 != 2)
        {
            var ipucu = durum == 404
                ? " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok ya da demo.api.url web vekili ve /api/test/ yolunu açmıyor; DEMO_API_URL verin)"
                : "";
            throw new InvalidOperationException($"POST /test/{yol} başarısız: {durum}{ipucu}");
        }
    }

    /// <summary>Token olmadan: bayinin sepetini herkese açık API ile boşaltır ve oturumu kapatır.</summary>
    public async Task SepetiBosaltAsync(BayiBilgisi bayi)
    {
        var api = _ayarlar.DemoApiUrl;
        var giris = JsonSerializer.Serialize(new { kullanici_adi = bayi.KullaniciAdi, parola = bayi.Parola });
        using (var r = await DurumBekleAsync(new HttpRequestMessage(HttpMethod.Post, api + "/auth/login")
               {
                   Content = new StringContent(giris, Encoding.UTF8, "application/json"),
               }, "sepet temizliği için giriş"))
        {
        }
        using (var bosalt = await DurumBekleAsync(new HttpRequestMessage(HttpMethod.Delete, api + "/cart"), "sepet boşaltma"))
        {
            var govde = (await bosalt.Content.ReadAsStringAsync()).Replace(" ", "");
            if (!govde.Contains("\"satirlar\":[]", StringComparison.Ordinal))
            {
                throw new InvalidOperationException("sepet boşaltılamadı: yanıtta satırlar kaldı");
            }
        }
        using (var r = await DurumBekleAsync(new HttpRequestMessage(HttpMethod.Post, api + "/auth/logout"), "çıkış"))
        {
        }
    }

    private async Task<HttpResponseMessage> DurumBekleAsync(HttpRequestMessage istek, string ne)
    {
        using (istek)
        {
            var yanit = await GonderAsync(istek, ne);
            if ((int)yanit.StatusCode / 100 != 2)
            {
                var kod = (int)yanit.StatusCode;
                yanit.Dispose();
                throw new InvalidOperationException($"{ne} başarısız: {kod}");
            }
            return yanit;
        }
    }

    private async Task<HttpResponseMessage> GonderAsync(HttpRequestMessage istek, string ne)
    {
        try
        {
            return await _istemci.SendAsync(istek);
        }
        catch (HttpRequestException e)
        {
            throw new InvalidOperationException($"{ne}: demo API'ye ulaşılamadı ({istek.RequestUri?.Host})", e);
        }
        catch (TaskCanceledException e)
        {
            throw new InvalidOperationException($"{ne}: demo API'ye ulaşılamadı ({istek.RequestUri?.Host}; zaman aşımı)", e);
        }
    }

    public void Dispose() => _istemci.Dispose();
}

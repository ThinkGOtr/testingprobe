using System;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Test verisi yalıtımı ve "kırarak doğrula" kancaları (Java <c>TestVerisi</c>, web fixtures.ts):
/// sıfırlama (<c>POST /test/reset</c>, token ister), yalnız sepet (<c>TP_E2E_NO_RESET=1</c>),
/// <c>BREAK_CAMPAIGN=1</c> / <c>TP_FAULT=&lt;kod&gt;</c> için bayi kapsamlı <c>POST /test/break</c>.
/// Token yalnızca <see cref="HttpClient"/> istek başlığında taşınır; günlüğe/rapora/kanıta yazılmaz.
/// </summary>
public sealed class TestVerisi : IDisposable
{
    /// <summary>Paylaşılan sırrın başlığı (API: main.py TEST_TOKEN_HEADER).</summary>
    public const string TokenBasligi = "X-Demoapp-Test-Token";

    /// <summary>Veri yalıtım kipi.</summary>
    public enum Kip
    {
        Sifirlama,
        YalnizSepet,
    }

    /// <summary>Bayi kapsamlı kırılma: <see cref="HataKodu"/> doluysa ekilmiş hata, boşsa kampanya.</summary>
    public sealed record Kirilma(string? HataKodu)
    {
        /// <summary><c>POST /test/break</c> gövdesi: açma ya da geri alma.</summary>
        public string Govde(string kullaniciAdi, bool acik) =>
            HataKodu is null ? KampanyaGovdesi(kullaniciAdi, acik) : HataGovdesi(kullaniciAdi, acik ? HataKodu : null);
    }

    private static readonly TimeSpan ZamanAsimi = TimeSpan.FromSeconds(10);

    private readonly Ayarlar ayarlar;
    private readonly HttpClient istemci;

    public TestVerisi(Ayarlar ayarlar)
    {
        this.ayarlar = ayarlar;
        istemci = new HttpClient(new HttpClientHandler { CookieContainer = new CookieContainer() })
        {
            Timeout = ZamanAsimi,
            DefaultRequestVersion = HttpVersion.Version11,
        };
    }

    /// <summary>Ortamdan yalıtım kipi; geçersiz birleşimlerde açıklayıcı hata.</summary>
    public static Kip KipSec(Ayarlar ayarlar)
    {
        if (ayarlar.TestToken is not null)
        {
            return Kip.Sifirlama;
        }
        if (ayarlar.EkilmisHata is not null)
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
            return Kip.YalnizSepet;
        }
        throw new InvalidOperationException(
            "DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz. Ya token ile DEMO_API_URL verin "
            + "(ör. http://127.0.0.1:18000) ya da yalnızca sepet yalıtımı için TP_E2E_NO_RESET=1 verin.");
    }

    /// <summary>Bu koşunun kırılması: TP_FAULT varsa o, yoksa BREAK_CAMPAIGN=1, yoksa null.</summary>
    public static Kirilma? KirilmaSec(Ayarlar ayarlar)
    {
        string? kod = ayarlar.EkilmisHata;
        if (kod is not null)
        {
            return new Kirilma(kod);
        }
        return ayarlar.KampanyaKirik ? new Kirilma(null) : null;
    }

    /// <summary><c>/test/&lt;yol&gt;</c> adresi.</summary>
    public static string TestUcu(string apiKoku, string yol) => apiKoku.TrimEnd('/') + "/test/" + yol;

    /// <summary>JSON dize literali.</summary>
    public static string JsonDize(string s) => JsonSerializer.Serialize(s);

    public static string KampanyaGovdesi(string kullaniciAdi, bool acik) =>
        "{\"kullanici_adi\":" + JsonDize(kullaniciAdi) + ",\"kampanya\":" + (acik ? "true" : "false") + "}";

    public static string HataGovdesi(string kullaniciAdi, string? kod) =>
        "{\"kullanici_adi\":" + JsonDize(kullaniciAdi) + ",\"hata\":" + (kod is null ? "null" : JsonDize(kod)) + "}";

    /// <summary>Bayinin verisini sıfırlar (sepet, siparişler, demo kırılması).</summary>
    public void Sifirla(string kullaniciAdi) =>
        TestUcunuCagir("reset", "{\"kullanici_adi\":" + JsonDize(kullaniciAdi) + "}");

    /// <summary>Bu koşunun kırılmasını bayi için açar ya da geri alır.</summary>
    public void Kir(Kirilma kirilma, string kullaniciAdi, bool acik) =>
        TestUcunuCagir("break", kirilma.Govde(kullaniciAdi, acik));

    private void TestUcunuCagir(string yol, string govde)
    {
        string token = ayarlar.TestToken
            ?? throw new InvalidOperationException($"/test/{yol} için DEMOAPP_TEST_TOKEN gerekir");
        using var istek = new HttpRequestMessage(HttpMethod.Post, TestUcu(ayarlar.DemoApiUrl, yol))
        {
            Content = new StringContent(govde, Encoding.UTF8, "application/json"),
        };
        istek.Headers.Add(TokenBasligi, token);
        using HttpResponseMessage yanit = Gonder(istek, "POST /test/" + yol);
        int durum = (int)yanit.StatusCode;
        if (durum / 100 != 2)
        {
            string ipucu = durum == 404
                ? " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok ya da DEMO_API_URL web vekili ve /api/test/ yolunu açmıyor; DEMO_API_URL verin)"
                : "";
            throw new InvalidOperationException($"POST /test/{yol} başarısız: {durum}{ipucu}");
        }
    }

    /// <summary>Token olmadan: bayinin sepetini herkese açık API ile boşaltır ve oturumu kapatır.</summary>
    public void SepetiBosalt(Bayiler.BayiBilgisi bayi)
    {
        string api = ayarlar.DemoApiUrl;
        string giris = "{\"kullanici_adi\":" + JsonDize(bayi.KullaniciAdi) + ",\"parola\":" + JsonDize(bayi.Parola) + "}";
        using (var istek = new HttpRequestMessage(HttpMethod.Post, api + "/auth/login")
        {
            Content = new StringContent(giris, Encoding.UTF8, "application/json"),
        })
        {
            DurumBekle(istek, "sepet temizliği için giriş").Dispose();
        }
        using (var istek = new HttpRequestMessage(HttpMethod.Delete, api + "/cart"))
        {
            using HttpResponseMessage yanit = DurumBekle(istek, "sepet boşaltma");
            string govde = yanit.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            if (!govde.Replace(" ", "").Contains("\"satirlar\":[]", StringComparison.Ordinal))
            {
                throw new InvalidOperationException("sepet boşaltılamadı: yanıtta satırlar kaldı");
            }
        }
        using (var istek = new HttpRequestMessage(HttpMethod.Post, api + "/auth/logout"))
        {
            DurumBekle(istek, "çıkış").Dispose();
        }
    }

    private HttpResponseMessage DurumBekle(HttpRequestMessage istek, string ne)
    {
        HttpResponseMessage yanit = Gonder(istek, ne);
        if ((int)yanit.StatusCode / 100 != 2)
        {
            int durum = (int)yanit.StatusCode;
            yanit.Dispose();
            throw new InvalidOperationException($"{ne} başarısız: {durum}");
        }
        return yanit;
    }

    private HttpResponseMessage Gonder(HttpRequestMessage istek, string ne)
    {
        try
        {
            return istemci.Send(istek);
        }
        catch (Exception e) when (e is HttpRequestException or System.Threading.Tasks.TaskCanceledException)
        {
            throw new InvalidOperationException($"{ne}: demo API'ye ulaşılamadı ({istek.RequestUri?.Host})", e);
        }
    }

    public void Dispose() => istemci.Dispose();
}

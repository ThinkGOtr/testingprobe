// API kök adresinin çözümü. Öncelik: komut satırı (--api-url) > ortam değişkeni BAYI_API_URL >
// appsettings.json ("BayiApi": {"TabanAdres": ...}) > varsayılan http://127.0.0.1:8081/api.
// Varsayılan, docker compose'daki demo-app-web nginx'idir (/api/* → demo API).
using System.Text.Json;

namespace BayiSiparis.Cekirdek;

public static class ApiAyarlari
{
    public const string Varsayilan = "http://127.0.0.1:8081/api";
    public const string OrtamDegiskeni = "BAYI_API_URL";
    public const string KomutSatiriAnahtari = "--api-url";

    /// <summary>Kaynakları öncelik sırasıyla değerlendirip doğrulanmış kök adresi döner.</summary>
    /// <exception cref="ArgumentException">Seçilen değer geçerli bir http(s) adresi değilse.</exception>
    public static string Coz(IReadOnlyList<string> argumanlar, string? ortamDegeri, string? appsettingsJson)
    {
        var (deger, kaynak) =
            KomutSatirindan(argumanlar) is { } a ? (a, KomutSatiriAnahtari)
            : !string.IsNullOrWhiteSpace(ortamDegeri) ? (ortamDegeri.Trim(), OrtamDegiskeni)
            : AyarDosyasindan(appsettingsJson) is { } d ? (d, "appsettings.json")
            : (Varsayilan, "varsayılan");

        if (!Uri.TryCreate(deger, UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
        {
            throw new ArgumentException($"API adresi geçersiz ({kaynak}): '{deger}'. Örnek: {Varsayilan}");
        }

        return deger.TrimEnd('/');
    }

    private static string? KomutSatirindan(IReadOnlyList<string> argumanlar)
    {
        for (var i = 0; i < argumanlar.Count; i++)
        {
            var a = argumanlar[i];
            if (a == KomutSatiriAnahtari && i + 1 < argumanlar.Count)
            {
                return argumanlar[i + 1].Trim();
            }

            if (a.StartsWith(KomutSatiriAnahtari + "=", StringComparison.Ordinal))
            {
                return a[(KomutSatiriAnahtari.Length + 1)..].Trim();
            }
        }

        return null;
    }

    private static string? AyarDosyasindan(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return null;
        }

        try
        {
            using var belge = JsonDocument.Parse(json, new JsonDocumentOptions { CommentHandling = JsonCommentHandling.Skip });
            if (belge.RootElement.TryGetProperty("BayiApi", out var bolum)
                && bolum.ValueKind == JsonValueKind.Object
                && bolum.TryGetProperty("TabanAdres", out var adres)
                && adres.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(adres.GetString()))
            {
                return adres.GetString()!.Trim();
            }
        }
        catch (JsonException e)
        {
            throw new ArgumentException($"appsettings.json okunamadı: {e.Message}");
        }

        return null;
    }
}

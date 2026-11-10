// Demo API istemcisi (web: demo-app/web/src/api.ts). Oturum, API'nin verdiği HttpOnly çerezdedir;
// HttpClient çerez kabıyla çerezi saklar ve sonraki isteklere ekler (tarayıcıdaki davranışın aynısı).
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace BayiSiparis.Cekirdek.Api;

public interface IApiIstemcisi
{
    /// <summary>401 alındığında (giriş isteği hariç) tetiklenir: oturum düştü → giriş ekranı.</summary>
    event EventHandler? YetkisizErisim;

    Task<Kullanici> GirisAsync(string kullaniciAdi, string parola, CancellationToken iptal = default);
    Task CikisAsync(CancellationToken iptal = default);
    /// <summary>Oturum yoklaması: oturum yoksa null döner (API 200 + {"oturum": null}).</summary>
    Task<Kullanici?> OturumAsync(CancellationToken iptal = default);
    Task<IReadOnlyList<Urun>> UrunlerAsync(CancellationToken iptal = default);
    Task<Sepet> SepetAsync(CancellationToken iptal = default);
    Task<Sepet> SepeteEkleAsync(string urunKod, int adet, CancellationToken iptal = default);
    Task<Sepet> SatirKaldirAsync(string urunKod, CancellationToken iptal = default);
    Task<Siparis> SiparisVerAsync(CancellationToken iptal = default);
    Task<IReadOnlyList<SiparisOzeti>> SiparislerAsync(CancellationToken iptal = default);
    Task<Siparis> SiparisAsync(string numara, CancellationToken iptal = default);
}

public sealed class ApiIstemcisi : IApiIstemcisi, IDisposable
{
    public const string UlasilamadiMesaji = "Sunucuya ulaşılamadı. Lütfen tekrar deneyin.";
    private const string GirisYolu = "/auth/login";

    internal static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = false,
    };

    private readonly HttpClient _http;
    private readonly string _taban;

    /// <param name="tabanAdres">API kökü, ör. "http://127.0.0.1:8081/api" (sonunda "/" olabilir).</param>
    /// <param name="isleyici">Testler için sahte işleyici; null ise çerez kaplı gerçek işleyici kullanılır.</param>
    public ApiIstemcisi(string tabanAdres, HttpMessageHandler? isleyici = null, TimeSpan? zamanAsimi = null)
    {
        _taban = tabanAdres.TrimEnd('/');
        isleyici ??= new HttpClientHandler
        {
            UseCookies = true,
            CookieContainer = new CookieContainer(),
            AllowAutoRedirect = false,
        };
        _http = new HttpClient(isleyici, disposeHandler: true) { Timeout = zamanAsimi ?? TimeSpan.FromSeconds(30) };
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
    }

    public event EventHandler? YetkisizErisim;

    public string TabanAdres => _taban;

    public Task<Kullanici> GirisAsync(string kullaniciAdi, string parola, CancellationToken iptal = default) =>
        IsteAsync<Kullanici>(HttpMethod.Post, GirisYolu, new { kullanici_adi = kullaniciAdi, parola }, iptal);

    public Task CikisAsync(CancellationToken iptal = default) =>
        IsteAsync<object>(HttpMethod.Post, "/auth/logout", null, iptal);

    public async Task<Kullanici?> OturumAsync(CancellationToken iptal = default) =>
        (await IsteAsync<OturumYaniti>(HttpMethod.Get, "/auth/session", null, iptal).ConfigureAwait(false)).Oturum;

    public Task<IReadOnlyList<Urun>> UrunlerAsync(CancellationToken iptal = default) =>
        IsteAsync<IReadOnlyList<Urun>>(HttpMethod.Get, "/products", null, iptal);

    public Task<Sepet> SepetAsync(CancellationToken iptal = default) =>
        IsteAsync<Sepet>(HttpMethod.Get, "/cart", null, iptal);

    public Task<Sepet> SepeteEkleAsync(string urunKod, int adet, CancellationToken iptal = default) =>
        IsteAsync<Sepet>(HttpMethod.Post, "/cart/lines", new { urun_kod = urunKod, adet }, iptal);

    public Task<Sepet> SatirKaldirAsync(string urunKod, CancellationToken iptal = default) =>
        IsteAsync<Sepet>(HttpMethod.Delete, $"/cart/lines/{Uri.EscapeDataString(urunKod)}", null, iptal);

    public Task<Siparis> SiparisVerAsync(CancellationToken iptal = default) =>
        IsteAsync<Siparis>(HttpMethod.Post, "/orders", null, iptal);

    public Task<IReadOnlyList<SiparisOzeti>> SiparislerAsync(CancellationToken iptal = default) =>
        IsteAsync<IReadOnlyList<SiparisOzeti>>(HttpMethod.Get, "/orders", null, iptal);

    public Task<Siparis> SiparisAsync(string numara, CancellationToken iptal = default) =>
        IsteAsync<Siparis>(HttpMethod.Get, $"/orders/{Uri.EscapeDataString(numara)}", null, iptal);

    private async Task<T> IsteAsync<T>(HttpMethod yontem, string yol, object? govde, CancellationToken iptal)
    {
        using var istek = new HttpRequestMessage(yontem, _taban + yol);
        if (govde is not null)
        {
            istek.Content = new StringContent(JsonSerializer.Serialize(govde), Encoding.UTF8, "application/json");
        }

        HttpResponseMessage yanit;
        string metin;
        try
        {
            yanit = await _http.SendAsync(istek, iptal).ConfigureAwait(false);
            metin = await yanit.Content.ReadAsStringAsync(iptal).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (iptal.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException)
        {
            // Bağlantı hatası veya zaman aşımı: web'deki fetch hatasıyla aynı mesaj.
            throw new ApiHatasi(0, UlasilamadiMesaji);
        }

        using (yanit)
        {
            var durum = (int)yanit.StatusCode;
            if (yanit.StatusCode == HttpStatusCode.NoContent)
            {
                return default!;
            }

            if (!yanit.IsSuccessStatusCode)
            {
                if (durum == 401 && yol != GirisYolu)
                {
                    YetkisizErisim?.Invoke(this, EventArgs.Empty);
                }

                throw new ApiHatasi(durum, HataMesaji(metin, durum));
            }

            try
            {
                return JsonSerializer.Deserialize<T>(metin, Json)
                    ?? throw new ApiHatasi(durum, "Beklenmeyen bir hata oluştu.");
            }
            catch (JsonException)
            {
                throw new ApiHatasi(durum, "Beklenmeyen bir hata oluştu.");
            }
        }
    }

    /// <summary>Hata gövdesinden kullanıcıya gösterilecek mesaj (web: errorMessage).</summary>
    internal static string HataMesaji(string? govde, int durum)
    {
        if (!string.IsNullOrWhiteSpace(govde))
        {
            try
            {
                using var belge = JsonDocument.Parse(govde);
                if (belge.RootElement.ValueKind == JsonValueKind.Object
                    && belge.RootElement.TryGetProperty("detail", out var ayrinti))
                {
                    if (ayrinti.ValueKind == JsonValueKind.String)
                    {
                        return ayrinti.GetString()!;
                    }

                    if (ayrinti.ValueKind == JsonValueKind.Array)
                    {
                        return "Girilen değer geçersiz.";
                    }
                }
            }
            catch (JsonException)
            {
                // JSON değilse genel mesaj.
            }
        }

        return durum >= 500 ? "Beklenmeyen bir hata oluştu." : $"İstek başarısız ({durum}).";
    }

    public void Dispose() => _http.Dispose();
}

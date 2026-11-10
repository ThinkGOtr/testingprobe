using System.Net;
using System.Text;
using System.Text.Json;
using BayiSiparis.Cekirdek.Api;

namespace BayiSiparis.Cekirdek.Testler;

public class ApiIstemcisiTestleri
{
    [Fact]
    public async Task Giris_govdesi_snake_case_ve_yanit_cozulur()
    {
        var s = new SahteSunucu().Yanit("POST /auth/login", 200, Veri.Kullanici());
        using var api = s.Istemci();

        var k = await api.GirisAsync("bayi2", "gizli");

        Assert.Equal(new Kullanici("bayi2", "Bayi İki"), k);
        using var govde = JsonDocument.Parse(s.Istekler.Single().Govde!);
        Assert.Equal("bayi2", govde.RootElement.GetProperty("kullanici_adi").GetString());
        Assert.Equal("gizli", govde.RootElement.GetProperty("parola").GetString());
    }

    [Fact]
    public async Task Giriste_401_detail_mesaji_doner_ve_yetkisiz_olayi_tetiklenmez()
    {
        var s = new SahteSunucu().Yanit("POST /auth/login", 401, new { detail = "Kullanıcı adı veya parola hatalı" });
        using var api = s.Istemci();
        var tetiklendi = false;
        api.YetkisizErisim += (_, _) => tetiklendi = true;

        var e = await Assert.ThrowsAsync<ApiHatasi>(() => api.GirisAsync("x", "y"));

        Assert.Equal(401, e.Durum);
        Assert.Equal("Kullanıcı adı veya parola hatalı", e.Message);
        Assert.False(tetiklendi);
    }

    [Fact]
    public async Task Diger_isteklerde_401_yetkisiz_olayini_tetikler()
    {
        var s = new SahteSunucu().Yanit("GET /cart", 401, new { detail = "Oturum gerekli" });
        using var api = s.Istemci();
        var tetiklendi = 0;
        api.YetkisizErisim += (_, _) => tetiklendi++;

        await Assert.ThrowsAsync<ApiHatasi>(() => api.SepetAsync());

        Assert.Equal(1, tetiklendi);
    }

    [Theory]
    [InlineData(422, """{"detail":[{"loc":["body","adet"],"msg":"x"}]}""", "Girilen değer geçersiz.")]
    [InlineData(500, "Internal Server Error", "Beklenmeyen bir hata oluştu.")]
    [InlineData(404, "{}", "İstek başarısız (404).")]
    [InlineData(422, """{"detail":"Sepetiniz boş"}""", "Sepetiniz boş")]
    public async Task Hata_mesajlari_web_ile_ayni(int durum, string govde, string beklenen)
    {
        var s = new SahteSunucu().Yanit("POST /orders", durum, govde);
        using var api = s.Istemci();

        var e = await Assert.ThrowsAsync<ApiHatasi>(() => api.SiparisVerAsync());

        Assert.Equal(beklenen, e.Message);
        Assert.Equal(durum, e.Durum);
    }

    [Fact]
    public async Task Baglanti_hatasi_durum_0_ve_ulasilamadi_mesaji()
    {
        var s = new SahteSunucu().Kopuk("GET /products");
        using var api = s.Istemci();

        var e = await Assert.ThrowsAsync<ApiHatasi>(() => api.UrunlerAsync());

        Assert.Equal(0, e.Durum);
        Assert.Equal(ApiIstemcisi.UlasilamadiMesaji, e.Message);
    }

    [Fact]
    public async Task Oturum_yoksa_null_varsa_kullanici()
    {
        var s = new SahteSunucu().BirKez("GET /auth/session", 200, new { oturum = (object?)null })
            .BirKez("GET /auth/session", 200, new { oturum = Veri.Kullanici() });
        using var api = s.Istemci();

        Assert.Null(await api.OturumAsync());
        Assert.Equal("Bayi İki", (await api.OturumAsync())!.Ad);
    }

    [Fact]
    public async Task Cikis_204_bos_govdeyle_basarili()
    {
        var s = new SahteSunucu().Yanit("POST /auth/logout", 204);
        using var api = s.Istemci();
        await api.CikisAsync();
        Assert.Equal("POST /auth/logout", s.Istekler.Single().Anahtar);
    }

    [Fact]
    public async Task Sepet_ve_siparis_json_cozulur_yol_parcalari_kodlanir()
    {
        var s = new SahteSunucu()
            .Yanit("DELETE /cart/lines/P 001/x", 200, Veri.Sepet([Veri.SepetSatiri("P-001", 7, 1, "150.00", "6 al 1 bedava")], adet: 7))
            .Yanit("GET /orders/SP-000001", 200, Veri.Siparis());
        using var api = s.Istemci();

        var sepet = await api.SatirKaldirAsync("P 001/x");
        var siparis = await api.SiparisAsync("SP-000001");

        Assert.Equal(7, sepet.AdetToplam);
        var satir = Assert.Single(sepet.Satirlar);
        Assert.Equal(("P-001", 1, 6, "150.00", "6 al 1 bedava"), (satir.UrunKod, satir.BedavaAdet, satir.UcretliAdet, satir.SatirTutari, satir.Kampanya));
        Assert.Equal("SP-000001", siparis.Numara);
        Assert.Equal(DateTimeOffset.Parse("2026-11-08T11:30:00+00:00"), siparis.Olusturma);
        Assert.Single(siparis.Satirlar);
    }

    [Fact]
    public async Task Taban_adresin_sonundaki_egik_cizgi_yok_sayilir()
    {
        var s = new SahteSunucu().Yanit("GET /products", 200, Veri.Urunler());
        using var api = new ApiIstemcisi(SahteSunucu.Taban + "/", s);
        Assert.Equal(2, (await api.UrunlerAsync()).Count);
    }

    /// <summary>Gerçek işleyiciyle: girişte gelen HttpOnly çerez sonraki isteklerde gönderilir.</summary>
    [Fact]
    public async Task Oturum_cerezi_saklanir_ve_gonderilir()
    {
        var port = BosPort();
        using var dinleyici = new HttpListener();
        dinleyici.Prefixes.Add($"http://127.0.0.1:{port}/");
        dinleyici.Start();
        string? gelenCerez = null;
        var sunucu = Task.Run(async () =>
        {
            for (var i = 0; i < 2; i++)
            {
                var b = await dinleyici.GetContextAsync();
                string govde;
                if (b.Request.Url!.AbsolutePath == "/api/auth/login")
                {
                    b.Response.AppendHeader("Set-Cookie", "bayi_oturum=abc123; HttpOnly; Max-Age=3600; Path=/; SameSite=lax");
                    govde = """{"kullanici_adi":"bayi2","ad":"Bayi İki"}""";
                }
                else
                {
                    gelenCerez = b.Request.Headers["Cookie"];
                    govde = """{"oturum":{"kullanici_adi":"bayi2","ad":"Bayi İki"}}""";
                }

                var bayt = Encoding.UTF8.GetBytes(govde);
                b.Response.ContentType = "application/json";
                b.Response.ContentLength64 = bayt.Length;
                await b.Response.OutputStream.WriteAsync(bayt);
                b.Response.Close();
            }
        });

        using var api = new ApiIstemcisi($"http://127.0.0.1:{port}/api");
        await api.GirisAsync("bayi2", "p");
        await api.OturumAsync();
        await sunucu;

        Assert.Equal("bayi_oturum=abc123", gelenCerez);
    }

    private static int BosPort()
    {
        var l = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
        l.Start();
        var p = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return p;
    }
}

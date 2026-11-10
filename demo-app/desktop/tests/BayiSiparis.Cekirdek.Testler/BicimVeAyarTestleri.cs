namespace BayiSiparis.Cekirdek.Testler;

public class BicimTestleri
{
    [Theory]
    [InlineData("1250.00", "1.250,00 TL")]
    [InlineData("150", "150,00 TL")]
    [InlineData("0.00", "0,00 TL")]
    [InlineData("25.5", "25,50 TL")]
    [InlineData("1234567.89", "1.234.567,89 TL")]
    [InlineData("-1234567.5", "-1.234.567,50 TL")]
    public void TL_web_ile_ayni_bicimi_uretir(string deger, string beklenen) =>
        Assert.Equal(beklenen, Bicim.TL(deger));

    [Fact]
    public void TarihSaat_web_Intl_tr_TR_medium_short_bicimiyle_ayni()
    {
        var istanbul = TimeZoneInfo.CreateCustomTimeZone("TR", TimeSpan.FromHours(3), "TR", "TR");
        var an = DateTimeOffset.Parse("2026-11-08T11:05:00+00:00");
        Assert.Equal("8 Kas 2026 14:05", Bicim.TarihSaat(an, istanbul));
        Assert.Equal("5 Ağu 2026 09:07", Bicim.TarihSaat(DateTimeOffset.Parse("2026-08-05T09:07:00+00:00"), TimeZoneInfo.Utc));
        Assert.Equal("1 Şub 2026 00:00", Bicim.TarihSaat(DateTimeOffset.Parse("2026-02-01T00:00:00+00:00"), TimeZoneInfo.Utc));
    }
}

public class ApiAyarlariTestleri
{
    private const string Json = """{ "BayiApi": { "TabanAdres": "http://dosya:1/api" } }""";

    [Fact]
    public void Oncelik_komut_satiri_ortam_dosya_varsayilan()
    {
        Assert.Equal("http://arg:1/api", ApiAyarlari.Coz(["--api-url", "http://arg:1/api/"], "http://env:1/api", Json));
        Assert.Equal("http://arg:2/api", ApiAyarlari.Coz(["--api-url=http://arg:2/api"], "http://env:1/api", Json));
        Assert.Equal("http://env:1/api", ApiAyarlari.Coz([], "http://env:1/api", Json));
        Assert.Equal("http://dosya:1/api", ApiAyarlari.Coz([], "  ", Json));
        Assert.Equal(ApiAyarlari.Varsayilan, ApiAyarlari.Coz([], null, null));
        Assert.Equal(ApiAyarlari.Varsayilan, ApiAyarlari.Coz([], null, "{}"));
    }

    [Theory]
    [InlineData("ftp://x/api")]
    [InlineData("127.0.0.1:8081/api")]
    [InlineData("yok")]
    public void Gecersiz_adres_hata_verir(string adres) =>
        Assert.Throws<ArgumentException>(() => ApiAyarlari.Coz([], adres, null));

    [Fact]
    public void Bozuk_appsettings_hata_verir() =>
        Assert.Throws<ArgumentException>(() => ApiAyarlari.Coz([], null, "{ bozuk"));
}

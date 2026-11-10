// Görünüm modelleri: web uygulamasının davranışıyla aynı akışlar (sahte API ile).
using BayiSiparis.Cekirdek.GorunumModelleri;

namespace BayiSiparis.Cekirdek.Testler;

public class KabukTestleri
{
    [Fact]
    public async Task Oturum_yoksa_giris_ekrani_acilir()
    {
        var s = new SahteSunucu().Yanit("GET /auth/session", 200, new { oturum = (object?)null });
        var kabuk = new AnaGorunumModeli(s.Istemci());
        Assert.True(kabuk.OturumKontrolEdiliyor);

        await kabuk.BaslatAsync();

        Assert.False(kabuk.OturumKontrolEdiliyor);
        Assert.IsType<GirisGorunumModeli>(kabuk.Sayfa);
        Assert.False(kabuk.OturumAcik);
        Assert.Equal("Giriş · Bayi Sipariş Portalı", kabuk.PencereBasligi);
        Assert.False(kabuk.KatalogaGitKomutu.CanExecute(null));
    }

    [Fact]
    public async Task Oturum_yoklamasi_hata_verirse_giris_ekrani()
    {
        var s = new SahteSunucu().Kopuk("GET /auth/session");
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        Assert.IsType<GirisGorunumModeli>(kabuk.Sayfa);
    }

    [Fact]
    public async Task Oturum_varsa_katalog_acilir_ve_sepet_sayaci_yuklenir()
    {
        var s = Oturumlu();
        var kabuk = new AnaGorunumModeli(s.Istemci());

        await kabuk.BaslatAsync();

        var katalog = Assert.IsType<KatalogGorunumModeli>(kabuk.Sayfa);
        await katalog.Yukleme;
        Assert.Equal("Bayi İki", kabuk.BayiAdi);
        Assert.Equal(7, kabuk.SepetAdedi);
        Assert.Equal("catalog", kabuk.AktifMenu);
        Assert.Equal("Katalog · Bayi Sipariş Portalı", kabuk.PencereBasligi);
        Assert.False(kabuk.Mesgul.Mesgul);
    }

    [Fact]
    public async Task Menu_gezinmesi_ve_etkin_menu()
    {
        var s = Oturumlu().Yanit("GET /orders", 200, Array.Empty<object>());
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();

        kabuk.SepeteGitKomutu.Execute(null);
        Assert.IsType<SepetGorunumModeli>(kabuk.Sayfa);
        Assert.Equal("cart", kabuk.AktifMenu);

        kabuk.SiparislereGitKomutu.Execute(null);
        Assert.IsType<SiparislerimGorunumModeli>(kabuk.Sayfa);
        Assert.Equal("orders", kabuk.AktifMenu);

        kabuk.SiparisAcKomutu.Execute("SP-000001");
        var onay = Assert.IsType<SiparisOnayGorunumModeli>(kabuk.Sayfa);
        Assert.Equal("SP-000001", onay.Numara);
        Assert.Equal("orders", kabuk.AktifMenu);
    }

    [Fact]
    public async Task Cikis_basarisiz_olsa_da_giris_ekranina_doner()
    {
        var s = Oturumlu().Yanit("POST /auth/logout", 500, "x");
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();

        await kabuk.CikisKomutu.CalistirAsync();

        Assert.IsType<GirisGorunumModeli>(kabuk.Sayfa);
        Assert.Equal(0, kabuk.SepetAdedi);
        Assert.Equal("", kabuk.BayiAdi);
    }

    [Fact]
    public Task Oturum_duserse_401_giris_ekranina_goturur() =>
        // Bağlamsız (Task.Run) koşulur: kabuk 401 bildirimini yakaladığı bağlama Post eder; xUnit'in
        // eşzamanlılık bağlamında bu Post sırasız olabilir. Uygulamada bağlam tek iş parçacıklı Dispatcher'dır.
        Task.Run(OturumDuserseGovde);

    private static async Task OturumDuserseGovde()
    {
        var s = Oturumlu();
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        s.Yanit("GET /orders", 401, new { detail = "Oturum gerekli" });

        kabuk.SiparislereGit();
        await kabuk.Sayfa!.Yukleme;

        Assert.IsType<GirisGorunumModeli>(kabuk.Sayfa);
        Assert.False(kabuk.OturumAcik);
    }

    internal static SahteSunucu Oturumlu() => new SahteSunucu()
        .Yanit("GET /auth/session", 200, new { oturum = Veri.Kullanici() })
        .Yanit("GET /products", 200, Veri.Urunler())
        .Yanit("GET /cart", 200, Veri.Sepet([Veri.SepetSatiri("P-001", 7, 1, "150.00", "6 al 1 bedava")], adet: 7, ara: "175.00", indirim: "25.00", toplam: "150.00", minUyari: "Minimum sipariş tutarı 750,00 TL"));
}

public class GirisTestleri
{
    [Fact]
    public async Task Alanlar_bosken_giris_pasif()
    {
        var kabuk = await GirisEkraninda(new SahteSunucu());
        var g = (GirisGorunumModeli)kabuk.Sayfa!;

        Assert.False(g.GirisKomutu.CanExecute(null));
        g.KullaniciAdi = "bayi2";
        Assert.False(g.GirisKomutu.CanExecute(null));
        g.Parola = "p";
        Assert.True(g.GirisKomutu.CanExecute(null));
        Assert.Equal("Giriş yap", g.GirisDugmesiMetni);
    }

    [Fact]
    public async Task Hatali_giriste_hata_mesaji_gosterilir()
    {
        var s = new SahteSunucu().Yanit("POST /auth/login", 401, new { detail = "Kullanıcı adı veya parola hatalı" });
        var kabuk = await GirisEkraninda(s);
        var g = (GirisGorunumModeli)kabuk.Sayfa!;
        g.KullaniciAdi = "bayi2";
        g.Parola = "yanlis";

        await g.GirisKomutu.CalistirAsync();

        Assert.Equal("Kullanıcı adı veya parola hatalı", g.Hata);
        Assert.False(g.Gonderiliyor);
        Assert.True(g.GirisKomutu.CanExecute(null));
        Assert.Same(g, kabuk.Sayfa);
    }

    [Fact]
    public async Task Basarili_giris_kullanici_adini_kirpar_ve_kataloga_gecer()
    {
        var s = KabukTestleri.Oturumlu().Yanit("POST /auth/login", 200, Veri.Kullanici());
        s.BirKez("GET /auth/session", 200, new { oturum = (object?)null });
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        var g = Assert.IsType<GirisGorunumModeli>(kabuk.Sayfa);
        g.KullaniciAdi = "  bayi2 ";
        g.Parola = "p";

        await g.GirisYapAsync();

        Assert.Contains(s.Istekler, i => i.Anahtar == "POST /auth/login" && i.Govde!.Contains("\"kullanici_adi\":\"bayi2\""));
        Assert.IsType<KatalogGorunumModeli>(kabuk.Sayfa);
        Assert.Equal(7, kabuk.SepetAdedi);
    }

    [Fact]
    public async Task Gonderim_surerken_dugme_metni_ve_mesgul_gostergesi()
    {
        var s = new SahteSunucu();
        var kabuk = await GirisEkraninda(s);
        var bekleyen = s.Bekleyen("POST /auth/login");
        var g = (GirisGorunumModeli)kabuk.Sayfa!;
        g.KullaniciAdi = "bayi2";
        g.Parola = "p";

        var is_ = g.GirisYapAsync();
        Assert.True(g.Gonderiliyor);
        Assert.Equal("Giriş yapılıyor…", g.GirisDugmesiMetni);
        Assert.False(g.GirisKomutu.CanExecute(null));
        Assert.True(kabuk.Mesgul.Mesgul);

        bekleyen.SetResult(SahteSunucu.Olustur(401, new { detail = "hata" }));
        await is_;
        Assert.False(kabuk.Mesgul.Mesgul);
    }

    private static async Task<AnaGorunumModeli> GirisEkraninda(SahteSunucu s)
    {
        s.BirKez("GET /auth/session", 200, new { oturum = (object?)null });
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        return kabuk;
    }
}

public class KatalogTestleri
{
    [Theory]
    [InlineData("1", 1)]
    [InlineData(" 12 ", 12)]
    [InlineData("999", 999)]
    [InlineData("5.0", 5)]
    [InlineData("1e2", 100)]
    [InlineData("", null)]
    [InlineData("0", null)]
    [InlineData("1000", null)]
    [InlineData("2.5", null)]
    [InlineData("-3", null)]
    [InlineData("abc", null)]
    public void Adet_kurali_webdeki_Number_kuraliyla_ayni(string metin, int? beklenen) =>
        Assert.Equal(beklenen, KatalogGorunumModeli.AdetCoz(metin));

    [Fact]
    public async Task Urun_kartlari_fiyat_ve_kampanya_metinleri()
    {
        var katalog = await Katalogda(KabukTestleri.Oturumlu());

        Assert.Collection(
            katalog.Urunler!,
            k =>
            {
                Assert.Equal("P-001", k.Kod);
                Assert.Equal("25,00 TL", k.FiyatMetni);
                Assert.Equal("Kampanya: 6 al 1 bedava", k.KampanyaMetni);
                Assert.Equal("1", k.AdetMetni);
                Assert.Equal("", k.Bildirim);
            },
            k =>
            {
                Assert.Equal("15,00 TL", k.FiyatMetni);
                Assert.False(k.KampanyaVar);
            });
        Assert.False(katalog.Yukleniyor);
    }

    [Fact]
    public async Task Gecersiz_adet_istek_atmadan_uyari_verir()
    {
        var s = KabukTestleri.Oturumlu();
        var katalog = await Katalogda(s);
        var kart = katalog.Urunler![0];
        kart.AdetMetni = "0";

        await kart.EkleKomutu.CalistirAsync();

        Assert.Equal("Adet 1 ile 999 arasında olmalıdır.", kart.Bildirim);
        Assert.Equal("err", kart.BildirimDurumu);
        Assert.DoesNotContain(s.Istekler, i => i.Anahtar == "POST /cart/lines");
    }

    [Fact]
    public async Task Sepete_ekleme_sayaci_gunceller_ve_tek_kartta_bildirim_gosterir()
    {
        var s = KabukTestleri.Oturumlu()
            .Yanit("POST /cart/lines", 200, Veri.Sepet([Veri.SepetSatiri("P-001", 10, 1, "225.00")], adet: 10));
        var katalog = await Katalogda(s);
        var (k1, k2) = (katalog.Urunler![0], katalog.Urunler[1]);
        k2.AdetMetni = "abc";
        await k2.EkleKomutu.CalistirAsync();
        Assert.NotEqual("", k2.Bildirim);

        k1.AdetMetni = "3";
        await k1.EkleKomutu.CalistirAsync();

        Assert.Equal("3 adet sepete eklendi.", k1.Bildirim);
        Assert.Equal("ok", k1.BildirimDurumu);
        Assert.Equal("", k2.Bildirim);
        Assert.Equal(10, katalog.Kabuk.SepetAdedi);
        Assert.Contains(s.Istekler, i => i.Anahtar == "POST /cart/lines" && i.Govde == """{"urun_kod":"P-001","adet":3}""");
        Assert.False(k1.Ekleniyor);
    }

    [Fact]
    public async Task Ekleme_hatasi_kartta_gosterilir()
    {
        var s = KabukTestleri.Oturumlu().Yanit("POST /cart/lines", 404, new { detail = "Ürün bulunamadı" });
        var katalog = await Katalogda(s);
        var kart = katalog.Urunler![1];

        await kart.EkleKomutu.CalistirAsync();

        Assert.Equal("Ürün bulunamadı", kart.Bildirim);
        Assert.Equal("err", kart.BildirimDurumu);
    }

    [Fact]
    public async Task Urunler_yuklenemezse_hata()
    {
        var s = KabukTestleri.Oturumlu().Kopuk("GET /products");
        var katalog = await Katalogda(s);
        Assert.Equal("Sunucuya ulaşılamadı. Lütfen tekrar deneyin.", katalog.Hata);
        Assert.Null(katalog.Urunler);
        Assert.False(katalog.Yukleniyor);
    }

    internal static async Task<KatalogGorunumModeli> Katalogda(SahteSunucu s)
    {
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        var katalog = Assert.IsType<KatalogGorunumModeli>(kabuk.Sayfa);
        await katalog.Yukleme;
        return katalog;
    }
}

public class SepetTestleri
{
    [Fact]
    public async Task Toplamlar_kampanya_ve_minimum_siparis_uyarisi()
    {
        var sepet = await Sepette(KabukTestleri.Oturumlu());

        Assert.True(sepet.Dolu);
        Assert.False(sepet.Bos);
        var satir = Assert.Single(sepet.Satirlar);
        Assert.Equal(("7", "1", "150,00 TL", "25,00 TL"), (satir.AdetMetni, satir.BedavaAdetMetni, satir.SatirTutariMetni, satir.BirimFiyatMetni));
        Assert.Equal("Portakal Gazozu 1L ürününü sepetten kaldır", satir.KaldirEtiketi);
        Assert.Equal("175,00 TL", sepet.AraToplamMetni);
        Assert.Equal("25,00 TL", sepet.IndirimMetni);
        Assert.True(sepet.IndirimVar);
        Assert.Equal("150,00 TL", sepet.ToplamMetni);
        Assert.Equal("Minimum sipariş tutarı 750,00 TL", sepet.MinSiparisUyarisi);
        Assert.False(sepet.OnaylaKomutu.CanExecute(null));
        Assert.Equal("Siparişi onayla", sepet.OnayDugmesiMetni);
    }

    [Fact]
    public async Task Bos_sepet()
    {
        var s = KabukTestleri.Oturumlu().Yanit("GET /cart", 200, Veri.BosSepet());
        var sepet = await Sepette(s);
        Assert.True(sepet.Bos);
        Assert.False(sepet.Dolu);
        Assert.Null(sepet.MinSiparisUyarisi);
        Assert.False(sepet.IndirimVar);
    }

    [Fact]
    public async Task Satir_kaldirma_sepeti_ve_sayaci_gunceller()
    {
        var s = KabukTestleri.Oturumlu().Yanit("DELETE /cart/lines/P-001", 200, Veri.BosSepet());
        var sepet = await Sepette(s);

        await sepet.Satirlar[0].KaldirKomutu.CalistirAsync();

        Assert.True(sepet.Bos);
        Assert.Empty(sepet.Satirlar);
        Assert.Equal(0, sepet.Kabuk.SepetAdedi);
    }

    [Fact]
    public async Task Siparis_onayi_sepeti_tazeler_ve_onay_ekranina_gecer()
    {
        var s = Onaylanabilir()
            .Yanit("POST /orders", 201, Veri.Siparis("SP-000042"))
            .Yanit("GET /orders/SP-000042", 200, Veri.Siparis("SP-000042"));
        var sepet = await Sepette(s);
        Assert.True(sepet.OnaylaKomutu.CanExecute(null));
        s.Yanit("GET /cart", 200, Veri.BosSepet());

        await sepet.OnaylaKomutu.CalistirAsync();

        var onay = Assert.IsType<SiparisOnayGorunumModeli>(sepet.Kabuk.Sayfa);
        await onay.Yukleme;
        Assert.Equal(0, sepet.Kabuk.SepetAdedi);
        Assert.True(onay.Yuklendi);
        Assert.Equal("SP-000042", onay.SiparisNumarasi);
        Assert.Equal("1.250,00 TL", onay.ToplamMetni);
        Assert.Equal("25,00 TL", onay.IndirimMetni);
        Assert.Equal("7", onay.AdetToplamMetni);
        Assert.Equal("Sipariş onayı · Bayi Sipariş Portalı", sepet.Kabuk.PencereBasligi);
    }

    [Fact]
    public async Task Siparis_onayi_hatasi_checkout_error_olarak_gosterilir()
    {
        var s = Onaylanabilir().Yanit("POST /orders", 422, new { detail = "Minimum sipariş tutarı sağlanmadı" });
        var sepet = await Sepette(s);

        await sepet.OnaylaAsync();

        Assert.Equal("Minimum sipariş tutarı sağlanmadı", sepet.OnayHatasi);
        Assert.Null(sepet.BosSepetHatasi);
        Assert.False(sepet.Onaylaniyor);
        Assert.True(sepet.OnaylaKomutu.CanExecute(null));
        Assert.Same(sepet, sepet.Kabuk.Sayfa);
    }

    [Fact]
    public async Task Onay_surerken_dugme_pasif_ve_metin_degisir()
    {
        var s = Onaylanabilir();
        var sepet = await Sepette(s);
        var bekleyen = s.Bekleyen("POST /orders");

        var is_ = sepet.OnaylaAsync();
        Assert.Equal("Onaylanıyor…", sepet.OnayDugmesiMetni);
        Assert.False(sepet.OnaylaKomutu.CanExecute(null));

        bekleyen.SetResult(SahteSunucu.Olustur(500, "x"));
        await is_;
        Assert.Equal("Beklenmeyen bir hata oluştu.", sepet.OnayHatasi);
    }

    [Fact]
    public async Task Sepet_yuklenemezse_yukleme_hatasi()
    {
        var s = KabukTestleri.Oturumlu();
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        s.Kopuk("GET /cart");
        await kabuk.SepetiTazeleAsync();

        kabuk.SepeteGit();
        var sepet = Assert.IsType<SepetGorunumModeli>(kabuk.Sayfa);
        await sepet.Yukleme;

        Assert.True(sepet.YuklemeHatasiVar);
        Assert.False(sepet.Yukleniyor);
        Assert.Equal("Sunucuya ulaşılamadı. Lütfen tekrar deneyin.", sepet.Hata);
    }

    private static SahteSunucu Onaylanabilir() => KabukTestleri.Oturumlu()
        .Yanit("GET /cart", 200, Veri.Sepet([Veri.SepetSatiri("P-001", 40, 6, "850.00")], adet: 40, ara: "1000.00", indirim: "150.00", toplam: "850.00", onaylanabilir: true));

    private static async Task<SepetGorunumModeli> Sepette(SahteSunucu s)
    {
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        kabuk.SepeteGit();
        var sepet = Assert.IsType<SepetGorunumModeli>(kabuk.Sayfa);
        await sepet.Yukleme;
        return sepet;
    }
}

public class SiparislerimTestleri
{
    [Fact]
    public async Task Siparis_listesi_satirlari()
    {
        var s = KabukTestleri.Oturumlu().Yanit("GET /orders", 200, new[] { Veri.Siparis("SP-000002"), Veri.Siparis("SP-000001") });
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        var gm = new SiparislerimGorunumModeli(kabuk, TimeZoneInfo.Utc);
        await gm.Baslat();

        Assert.True(gm.Dolu);
        Assert.False(gm.Bos);
        Assert.Equal(["SP-000002", "SP-000001"], gm.Siparisler!.Select(o => o.Numara));
        var o = gm.Siparisler![0];
        Assert.Equal(("8 Kas 2026 11:30", "7", "25,00 TL", "1.250,00 TL"), (o.TarihMetni, o.AdetMetni, o.IndirimMetni, o.ToplamMetni));
    }

    [Fact]
    public async Task Bos_siparis_listesi()
    {
        var s = KabukTestleri.Oturumlu().Yanit("GET /orders", 200, Array.Empty<object>());
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        kabuk.SiparislereGit();
        var gm = Assert.IsType<SiparislerimGorunumModeli>(kabuk.Sayfa);
        await gm.Yukleme;
        Assert.True(gm.Bos);
        Assert.False(gm.Dolu);
    }

    [Fact]
    public async Task Bulunamayan_siparis_onay_ekraninda_hata()
    {
        var s = KabukTestleri.Oturumlu().Yanit("GET /orders/SP-9", 404, new { detail = "Sipariş bulunamadı" });
        var kabuk = new AnaGorunumModeli(s.Istemci());
        await kabuk.BaslatAsync();
        kabuk.SiparisOnayinaGit("SP-9");
        var onay = Assert.IsType<SiparisOnayGorunumModeli>(kabuk.Sayfa);
        await onay.Yukleme;
        Assert.Equal("Sipariş bulunamadı", onay.Hata);
        Assert.False(onay.Yuklendi);
    }
}

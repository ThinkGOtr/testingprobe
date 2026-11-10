// Giriş ekranı (web: LoginPage.tsx).
using BayiSiparis.Cekirdek.Mvvm;

namespace BayiSiparis.Cekirdek.GorunumModelleri;

public sealed class GirisGorunumModeli : SayfaGorunumModeli
{
    private string _kullaniciAdi = "";
    private string _parola = "";
    private string? _hata;
    private bool _gonderiliyor;

    public GirisGorunumModeli(AnaGorunumModeli kabuk)
        : base(kabuk)
    {
        GirisKomutu = new AsenkronKomut(_ => GirisYapAsync(), _ => Gonderilebilir);
    }

    public override string Baslik => "Giriş";

    public string KullaniciAdi
    {
        get => _kullaniciAdi;
        set
        {
            if (Ayarla(ref _kullaniciAdi, value ?? ""))
            {
                GirisKomutu.YenidenDegerlendir();
            }
        }
    }

    /// <summary>PasswordBox bağlanamadığı için görünüm kodu PasswordChanged'de ayarlar.</summary>
    public string Parola
    {
        get => _parola;
        set
        {
            if (Ayarla(ref _parola, value ?? ""))
            {
                GirisKomutu.YenidenDegerlendir();
            }
        }
    }

    /// <summary>"login-error" metni; null iken eleman ağaçta yoktur.</summary>
    public string? Hata
    {
        get => _hata;
        private set => Ayarla(ref _hata, value);
    }

    public bool Gonderiliyor
    {
        get => _gonderiliyor;
        private set
        {
            if (Ayarla(ref _gonderiliyor, value))
            {
                Bildir(nameof(GirisDugmesiMetni));
                GirisKomutu.YenidenDegerlendir();
            }
        }
    }

    public string GirisDugmesiMetni => _gonderiliyor ? "Giriş yapılıyor…" : "Giriş yap";

    /// <summary>Web ile aynı: gönderim sürerken ya da alanlardan biri boşken pasif.</summary>
    public bool Gonderilebilir => !_gonderiliyor && _kullaniciAdi.Length > 0 && _parola.Length > 0;

    public AsenkronKomut GirisKomutu { get; }

    public async Task GirisYapAsync()
    {
        if (!Gonderilebilir)
        {
            return;
        }

        Hata = null;
        Gonderiliyor = true;
        try
        {
            var kullanici = await Mesgul.IzleAsync(Api.GirisAsync(_kullaniciAdi.Trim(), _parola));
            // Başarıda düğme "Giriş yapılıyor…" kalır; ekran zaten değişir (web ile aynı).
            await Kabuk.GirisYapildiAsync(kullanici);
        }
        catch (Exception e)
        {
            Hata = Mesaj(e, "Giriş yapılamadı.");
            Gonderiliyor = false;
        }
    }
}

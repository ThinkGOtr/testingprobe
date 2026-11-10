using BayiSiparis.Cekirdek.Api;
using BayiSiparis.Cekirdek.Mvvm;

namespace BayiSiparis.Cekirdek.GorunumModelleri;

/// <summary>Ekran (sayfa) görünüm modeli tabanı. Pencere başlığı = "{Baslik} · Bayi Sipariş Portalı".</summary>
public abstract class SayfaGorunumModeli : GozlemlenebilirNesne
{
    protected SayfaGorunumModeli(AnaGorunumModeli kabuk)
    {
        Kabuk = kabuk;
    }

    public AnaGorunumModeli Kabuk { get; }

    protected IApiIstemcisi Api => Kabuk.Api;

    protected MesgulTakipcisi Mesgul => Kabuk.Mesgul;

    /// <summary>Pencere başlığındaki ekran adı (web: document.title).</summary>
    public abstract string Baslik { get; }

    /// <summary>Ekran açılışındaki yükleme; testler bunu bekler.</summary>
    public Task Yukleme { get; private set; } = Task.CompletedTask;

    /// <summary>
    /// Yüklemeyi başlatır (bir kez). Kabuk bunu ekranı etkinleştirdikten SONRA çağırır: yükleme sırasında
    /// oturum düşerse (401 → giriş ekranı) bu geçiş, ekran ataması tarafından ezilmez.
    /// </summary>
    public Task Baslat()
    {
        if (!_basladi)
        {
            _basladi = true;
            Yukleme = YukleAsync();
        }

        return Yukleme;
    }

    /// <summary>Ekrana özgü açılış yüklemesi.</summary>
    protected virtual Task YukleAsync() => Task.CompletedTask;

    private bool _basladi;

    protected static string Mesaj(Exception e, string yedek) => e is ApiHatasi a ? a.Message : yedek;
}

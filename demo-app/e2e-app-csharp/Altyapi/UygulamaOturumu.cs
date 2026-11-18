using OpenQA.Selenium;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Bir testin uygulama oturumu: sürücü, bekleme yardımcısı ve ekranlar arası paylaşılan durum (Java
/// <c>UygulamaOturumu</c>). Test kodu sürücüye doğrudan erişmez.
/// </summary>
public sealed class UygulamaOturumu
{
    public UygulamaOturumu(IWebDriver surucu, Bekle bekle)
    {
        Surucu = surucu;
        Bekle = bekle;
    }

    public IWebDriver Surucu { get; }

    public Bekle Bekle { get; }

    /// <summary>Onay ekranında en son doğrulanan sipariş numarası.</summary>
    public string? SonSiparisNumarasi { get; set; }
}

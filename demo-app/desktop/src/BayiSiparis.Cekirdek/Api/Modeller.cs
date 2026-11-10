// Demo API'nin JSON sözleşmesi (web istemcisi demo-app/web/src/api.ts ile birebir).
// Alan adları snake_case olarak serileştirilir (ör. UrunKod → "urun_kod"). Tutarlar API'de metindir ("150.00").
namespace BayiSiparis.Cekirdek.Api;

public sealed record Kullanici(string KullaniciAdi, string Ad);

public sealed record Urun(string Kod, string Ad, string Fiyat, string? Kampanya);

public sealed record SepetSatiri(
    string UrunKod,
    string UrunAd,
    string BirimFiyat,
    int Adet,
    string? Kampanya,
    int BedavaAdet,
    int UcretliAdet,
    string AraTutar,
    string Indirim,
    string SatirTutari);

public sealed record Uyari(string Kod, string Mesaj);

public sealed record Sepet(
    IReadOnlyList<SepetSatiri> Satirlar,
    int AdetToplam,
    string AraToplam,
    string Indirim,
    string Toplam,
    string MinSiparisTutari,
    bool MinSiparisSaglandi,
    bool Onaylanabilir,
    IReadOnlyList<Uyari> Uyarilar);

public sealed record SiparisSatiri(
    string UrunKod,
    string UrunAd,
    string BirimFiyat,
    int Adet,
    int BedavaAdet,
    string SatirTutari);

/// <summary>Sipariş geçmişindeki özet (GET /orders).</summary>
public record SiparisOzeti(
    string Numara,
    DateTimeOffset Olusturma,
    int AdetToplam,
    string AraToplam,
    string Indirim,
    string Toplam);

/// <summary>Sipariş ayrıntısı (POST /orders, GET /orders/{numara}).</summary>
public sealed record Siparis(
    string Numara,
    DateTimeOffset Olusturma,
    int AdetToplam,
    string AraToplam,
    string Indirim,
    string Toplam,
    IReadOnlyList<SiparisSatiri> Satirlar)
    : SiparisOzeti(Numara, Olusturma, AdetToplam, AraToplam, Indirim, Toplam);

internal sealed record OturumYaniti(Kullanici? Oturum);

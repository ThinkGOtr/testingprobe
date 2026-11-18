using System;
using Antreklabs.Bayi.Altyapi;

namespace Antreklabs.Bayi.Ekranlar;

/// <summary>Sipariş geçmişi (Siparişlerim) ekranı (Java <c>SiparisEkrani</c>; web <c>OrderPage</c> geçmiş bölümü).</summary>
public class SiparisEkrani : Ekran
{
    public SiparisEkrani(UygulamaOturumu oturum)
        : base(oturum)
    {
    }

    /// <summary>Sipariş geçmişi ekranını açar.</summary>
    public void Ac()
    {
        Dokun(Kimlikler.Menu.SIPARISLER);
        BiriGorunurBekle(Kimlikler.Siparis.TABLO, Kimlikler.Siparis.BOS);
    }

    /// <summary>Üst menüden sipariş geçmişine gider.</summary>
    public void MenudenAc() => Ac();

    /// <summary>Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular.</summary>
    public void DogrulaSiparisGecmiste(string siparisNo) => GorunurOlmali(Kimlik.Ekli(Kimlikler.Siparis.SATIR_ONEK, siparisNo));

    /// <summary>Sipariş geçmişindeki siparişin genel toplamını doğrular.</summary>
    public void DogrulaSiparisToplami(string siparisNo, string tutar) =>
        MetinOlmali(Kimlik.Ekli(Kimlikler.Siparis.SATIR_TOPLAMI_ONEK, siparisNo), tutar);

    /// <summary>Bu testte onay ekranında görülen son siparişin geçmişteki genel toplamını doğrular.</summary>
    public void DogrulaOnaylananSiparisToplami(string tutar)
    {
        string numara = Oturum.SonSiparisNumarasi
            ?? throw new InvalidOperationException("bu testte onaylanmış sipariş yok (önce onay ekranı doğrulanmalı)");
        DogrulaSiparisToplami(numara, tutar);
    }

    /// <summary>Sipariş geçmişinin boş olduğunu doğrular.</summary>
    public void DogrulaSiparisYok() => GorunurOlmali(Kimlikler.Siparis.BOS);
}

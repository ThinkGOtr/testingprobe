// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map_app · platform: windows · dil: csharp · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 46175a46bd07b3e2b3e31ca480890fd9846f06f5c3276a5a93846e227326987b · şablon: 6a8e43c193ef6015c194a35b671ead1b4be625bbecf752eced4de6a0371c3f48
using Antreklabs.Bayi.Altyapi;
using NUnit.Framework;

namespace Antreklabs.Bayi.Tests.Generated;

[Bayi("bayi1")]
public class TPD1WindowsC2_3f9b1c2eTests : TestTabani
{
    [Test]
    [Category("uretilen")]
    [Category("windows")]
    [Category("tp-case-3f9b1c2e-0000-5000-8000-0000000000c2")]
    [Category("TPD-1")]
    [Description("7 adet kampanyalı üründe 1 adet bedava verilir")]
    public void Senaryo()
    {
        // S1 — Giriş sayfasını aç
        GirisEkrani.Ac();
        // S2 — Bayi kullanıcısıyla giriş yap
        GirisEkrani.GirisYap("bayi1", "Demo123!");
        // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
        KatalogEkrani.SepeteEkle("P-001", 7);
        // S4 — Üst menüden sepete git
        KatalogEkrani.SepetiAc();
        // Beklenen sonuç (değerler onaylı case metninden)
        SepetEkrani.DogrulaSatirAdedi("P-001", 7);
        SepetEkrani.DogrulaBedavaAdet("P-001", 1);
        SepetEkrani.DogrulaAraToplam("175,00 TL");
        SepetEkrani.DogrulaIndirim("25,00 TL");
        SepetEkrani.DogrulaToplam("150,00 TL");
    }
}

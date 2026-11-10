package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.OturumAcik;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/**
 * Katalog ve sepet (TPD-1) — web: tests/cart.spec.ts.
 *
 * <p>6 adet sınırı bilerek doğrulanmaz (web ile aynı gerekçe: demo senaryosuna bağlıdır); yalnızca
 * iki senaryoda da doğru olan davranış (7 → 1 bedava) doğrulanır.
 */
@OturumAcik
public class SepetTesti extends TestTabani {

  /** Web: {@code test.beforeEach(catalogPage.goto)}. */
  @Override
  protected void hazirlikSonrasi() {
    katalogEkrani().ac();
  }

  @Test(groups = {"duman"}, description = "katalog ürünleri ve fiyatları tr-TR biçiminde gösterir")
  public void katalogFiyatlari() {
    katalogEkrani().dogrulaUrunFiyati("P-001", "25,00 TL");
    katalogEkrani().dogrulaUrunFiyati("P-002", "15,00 TL");
    katalogEkrani().dogrulaUrunFiyati("P-003", "8,00 TL");
    katalogEkrani().dogrulaUrunFiyati("P-004", "30,00 TL");
    katalogEkrani().dogrulaKampanya("P-001", "6 al 1 bedava");
  }

  @Test(groups = {"duman"}, description = "AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar")
  public void sepeteEkleSayaciArtirir() {
    katalogEkrani().dogrulaSepetSayaci(0);
    katalogEkrani().sepeteEkle("P-002", 1);
    katalogEkrani().dogrulaSepetSayaci(1);
    katalogEkrani().sepeteEkle("P-003", 2);
    katalogEkrani().dogrulaSepetSayaci(3);
  }

  @Test(groups = {"kampanya"}, description = "kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL")
  public void kampanyaYediAdet() {
    katalogEkrani().sepeteEkle("P-001", 7);
    katalogEkrani().sepetiAc();
    sepetEkrani().dogrulaSatirAdedi("P-001", 7);
    sepetEkrani().dogrulaBedavaAdet("P-001", 1);
    sepetEkrani().dogrulaAraToplam("175,00 TL");
    sepetEkrani().dogrulaIndirim("25,00 TL");
    sepetEkrani().dogrulaToplam("150,00 TL");
  }

  @Test(groups = {"kampanya"}, description = "kampanyasız üründe bedava adet verilmez")
  public void kampanyasizUrundeBedavaYok() {
    katalogEkrani().sepeteEkle("P-002", 12);
    katalogEkrani().sepetiAc();
    sepetEkrani().dogrulaBedavaAdet("P-002", 0);
    sepetEkrani().dogrulaIndirim("0,00 TL");
  }

  @Test(
      groups = {"kampanya"},
      description = "kampanyasız siparişte minimum tutar altında uyarı gösterilir ve onay pasif olur")
  public void kampanyasizMinimumUyarisi() {
    katalogEkrani().sepeteEkle("P-002", 10);
    katalogEkrani().sepetiAc();
    sepetEkrani().dogrulaToplam("150,00 TL");
    sepetEkrani().dogrulaMinimumSiparisUyarisi("Minimum sipariş tutarı 750,00 TL");
    sepetEkrani().dogrulaOnayPasif();
  }

  @Test(groups = {"kampanya"}, description = "kampanyalı siparişte minimum tutar aranmaz")
  public void kampanyalidaMinimumYok() {
    // 7 x P-001: toplam minimum tutarın (750,00 TL) çok altında; indirim tutarından bağımsız.
    katalogEkrani().sepeteEkle("P-001", 7);
    katalogEkrani().sepetiAc();
    sepetEkrani().dogrulaSatirAdedi("P-001", 7);
    sepetEkrani().dogrulaMinimumSiparisUyarisiYok();
    sepetEkrani().dogrulaOnayAktif();
  }

  @Test(description = "minimum tutara ulaşınca uyarı kalkar ve onay aktif olur")
  public void minimumTutaraUlasinca() {
    katalogEkrani().sepeteEkle("P-004", 25);
    katalogEkrani().sepetiAc();
    sepetEkrani().dogrulaToplam("750,00 TL");
    sepetEkrani().dogrulaMinimumSiparisUyarisiYok();
    sepetEkrani().dogrulaOnayAktif();
  }

  @Test(description = "ürün sepetten kaldırılabilir")
  public void urunKaldirma() {
    katalogEkrani().sepeteEkle("P-002", 1);
    katalogEkrani().sepeteEkle("P-003", 1);
    katalogEkrani().sepetiAc();
    sepetEkrani().urunuKaldir("P-002");
    sepetEkrani().dogrulaUrunSepetteYok("P-002");
    sepetEkrani().dogrulaSatirAdedi("P-003", 1);
    sepetEkrani().urunuKaldir("P-003");
    sepetEkrani().dogrulaSepetBos();
  }
}

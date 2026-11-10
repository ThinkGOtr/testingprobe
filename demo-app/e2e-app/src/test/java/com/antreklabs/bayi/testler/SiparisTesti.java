package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.OturumAcik;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/**
 * Sipariş onayı ve geçmiş (TPD-1 AC5) — web: tests/order.spec.ts.
 *
 * <p>Web'deki "minimum tutarın altındaki sepet API'de de reddedilir" testi yalnızca API'yi sınar,
 * uygulama arayüzüne özgü değildir; burada yoktur.
 */
@OturumAcik
public class SiparisTesti extends TestTabani {

  // Sıfırlanmış veri gerektirir; TP_E2E_NO_RESET=1 (yalnızca sepet yalıtımı) kipinde atlanır.
  @Test(groups = {SIFIR_VERI}, description = "siparişi olmayan bayide boş geçmiş bilgisi gösterilir")
  public void bosGecmis() {
    siparisEkrani().ac();
    siparisEkrani().dogrulaSiparisYok();
  }

  @Test(groups = {"duman"}, description = "onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir")
  public void siparisOnayVeGecmis() {
    katalogEkrani().ac();
    katalogEkrani().sepeteEkle("P-004", 30);
    katalogEkrani().sepeteEkle("P-001", 7);
    katalogEkrani().sepetiAc();
    sepetEkrani().dogrulaToplam("1.050,00 TL");
    sepetEkrani().siparisiOnayla();
    onayEkrani().dogrulaSiparisOnayi();
    onayEkrani().dogrulaOnaylananToplam("1.050,00 TL");
    katalogEkrani().dogrulaSepetSayaci(0);
    onayEkrani().dogrulaOnaylananSiparisGecmiste();
    siparisEkrani().dogrulaOnaylananSiparisToplami("1.050,00 TL");
  }
}

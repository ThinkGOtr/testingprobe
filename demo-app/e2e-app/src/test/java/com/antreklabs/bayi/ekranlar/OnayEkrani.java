package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.UygulamaOturumu;
import java.util.regex.Pattern;

/**
 * Sipariş onayı ekranı (web: pages/order/order.page.ts {@code OrderPage}'in onay bölümü).
 *
 * <p>Web'deki {@code readOrderNumber()} değer döndürür; ekran nesnesi sözleşmesinde yalnız
 * {@code void} metot olduğundan okunan numara oturumda saklanır ve
 * {@link SiparisEkrani#dogrulaOnaylananSiparisToplami} gibi metotlar onu kullanır.
 */
public class OnayEkrani extends Ekran {

  /** Sipariş numarası biçimi (web: {@code ORDER_NUMBER}). */
  static final Pattern SIPARIS_NUMARASI = Pattern.compile("^SP-\\d{6}$");

  public OnayEkrani(UygulamaOturumu oturum) {
    super(oturum);
  }

  /** Onay ekranındaki sipariş numarasını okur ve oturumda saklar. */
  String siparisNumarasiniOku() {
    metinKalibinaUymali(Kimlikler.Onay.SIPARIS_NUMARASI, SIPARIS_NUMARASI);
    String numara = metin(gorunurBekle(Kimlikler.Onay.SIPARIS_NUMARASI));
    oturum().sonSiparisNumarasi(numara);
    return numara;
  }

  /** Sipariş onayının ve sipariş numarasının gösterildiğini doğrular. */
  public void dogrulaSiparisOnayi() {
    gorunurOlmali(Kimlikler.Onay.ONAY_ALANI);
    siparisNumarasiniOku();
  }

  /** Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL"). */
  public void dogrulaOnaylananToplam(String tutar) {
    metinOlmali(Kimlikler.Onay.TOPLAM, tutar);
  }

  /** Onaylanan siparişin kampanya indirimini doğrular (ör. "25,00 TL"). */
  public void dogrulaOnaylananIndirim(String tutar) {
    metinOlmali(Kimlikler.Onay.INDIRIM, tutar);
  }

  /** Onay ekranında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular. */
  public void dogrulaOnaylananSiparisGecmiste() {
    String numara = siparisNumarasiniOku();
    SiparisEkrani gecmis = new SiparisEkrani(oturum());
    gecmis.menudenAc();
    gecmis.dogrulaSiparisGecmiste(numara);
  }

  /** Onay ekranından "Siparişlerime git" ile sipariş geçmişine gider. */
  public void siparislerimeGit() {
    dokun(Kimlikler.Onay.SIPARISLERIME_GIT);
    biriGorunurBekle(Kimlikler.Siparis.TABLO, Kimlikler.Siparis.BOS);
  }

  /** Onay ekranından "Alışverişe devam et" ile kataloğa döner. */
  public void alisveriseDevamEt() {
    dokun(Kimlikler.Onay.ALISVERISE_DEVAM);
    gorunurBekle(Kimlikler.Katalog.URUN_LISTESI);
  }
}

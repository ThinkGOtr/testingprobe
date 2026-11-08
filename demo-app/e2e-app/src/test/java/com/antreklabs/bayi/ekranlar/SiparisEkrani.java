package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Kimlik;
import com.antreklabs.bayi.altyapi.UygulamaOturumu;

/** Sipariş geçmişi (Siparişlerim) ekranı (web: pages/order/order.page.ts {@code OrderPage}'in geçmiş bölümü). */
public class SiparisEkrani extends Ekran {

  public SiparisEkrani(UygulamaOturumu oturum) {
    super(oturum);
  }

  /** Sipariş geçmişi ekranını açar. */
  public void ac() {
    dokun(Kimlikler.Menu.SIPARISLER);
    biriGorunurBekle(Kimlikler.Siparis.TABLO, Kimlikler.Siparis.BOS);
  }

  /** Üst menüden sipariş geçmişine gider. */
  public void menudenAc() {
    ac();
  }

  /** Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular. */
  public void dogrulaSiparisGecmiste(String siparisNo) {
    gorunurOlmali(Kimlik.ekli(Kimlikler.Siparis.SATIR_ONEK, siparisNo));
  }

  /** Sipariş geçmişindeki siparişin genel toplamını doğrular. */
  public void dogrulaSiparisToplami(String siparisNo, String tutar) {
    metinOlmali(Kimlik.ekli(Kimlikler.Siparis.SATIR_TOPLAMI_ONEK, siparisNo), tutar);
  }

  /** Bu testte onay ekranında görülen son siparişin geçmişteki genel toplamını doğrular. */
  public void dogrulaOnaylananSiparisToplami(String tutar) {
    String numara =
        oturum()
            .sonSiparisNumarasi()
            .orElseThrow(() -> new IllegalStateException("bu testte onaylanmış sipariş yok (önce onay ekranı doğrulanmalı)"));
    dogrulaSiparisToplami(numara, tutar);
  }

  /** Sipariş geçmişinin boş olduğunu doğrular. */
  public void dogrulaSiparisYok() {
    gorunurOlmali(Kimlikler.Siparis.BOS);
  }
}

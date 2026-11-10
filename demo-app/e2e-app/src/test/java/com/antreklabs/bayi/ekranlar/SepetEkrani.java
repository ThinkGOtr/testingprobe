package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Kimlik;
import com.antreklabs.bayi.altyapi.UygulamaOturumu;

/** Sepet ekranı: satırlar, kampanya, toplamlar ve sipariş onayı (web: pages/cart/cart.page.ts {@code CartPage}). */
public class SepetEkrani extends Ekran {

  public SepetEkrani(UygulamaOturumu oturum) {
    super(oturum);
  }

  /** Sepet ekranını açar. */
  public void ac() {
    dokun(Kimlikler.Menu.SEPET);
    biriGorunurBekle(Kimlikler.Sepet.TABLO, Kimlikler.Sepet.BOS);
  }

  /** Ürünü sepetten kaldırır. */
  public void urunuKaldir(String urunKodu) {
    dokun(Kimlik.ekli(Kimlikler.Sepet.SATIRI_KALDIR_ONEK, urunKodu));
    String satir = Kimlik.ekli(Kimlikler.Sepet.SATIR_ONEK, urunKodu);
    bekle().kosul("satır sepetten kalkmadı: kimlik '" + satir + "'", s -> hemenBul(null, satir) == null ? Boolean.TRUE : null);
  }

  /** "Siparişi onayla" butonuna basar ve onay ekranının açılmasını bekler. */
  public void siparisiOnayla() {
    dokun(Kimlikler.Sepet.SIPARISI_ONAYLA);
    gorunurBekle(Kimlikler.Onay.ONAY_ALANI);
  }

  /** Sepet satırındaki adedi doğrular. */
  public void dogrulaSatirAdedi(String urunKodu, int adet) {
    metinOlmali(Kimlik.ekli(Kimlikler.Sepet.SATIR_ADEDI_ONEK, urunKodu), String.valueOf(adet));
  }

  /** Sepet satırında kampanyayla bedava verilen adedi doğrular. */
  public void dogrulaBedavaAdet(String urunKodu, int adet) {
    metinOlmali(Kimlik.ekli(Kimlikler.Sepet.BEDAVA_ADET_ONEK, urunKodu), String.valueOf(adet));
  }

  /** Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL"). */
  public void dogrulaSatirToplami(String urunKodu, String tutar) {
    metinOlmali(Kimlik.ekli(Kimlikler.Sepet.SATIR_TOPLAMI_ONEK, urunKodu), tutar);
  }

  /** Ara toplamı doğrular (ör. "175,00 TL"). */
  public void dogrulaAraToplam(String tutar) {
    metinOlmali(Kimlikler.Sepet.ARA_TOPLAM, tutar);
  }

  /** Kampanya indirimi tutarını doğrular (ör. "25,00 TL"). */
  public void dogrulaIndirim(String tutar) {
    metinOlmali(Kimlikler.Sepet.INDIRIM, tutar);
  }

  /** Sepetin indirim sonrası genel toplamını doğrular (ör. "150,00 TL"). */
  public void dogrulaToplam(String tutar) {
    metinOlmali(Kimlikler.Sepet.TOPLAM, tutar);
  }

  /** Minimum sipariş uyarısının verilen metni içerdiğini doğrular (ör. "Minimum sipariş tutarı 750,00 TL"). */
  public void dogrulaMinimumSiparisUyarisi(String mesaj) {
    metinIcermeli(Kimlikler.Sepet.MIN_SIPARIS_UYARISI, mesaj);
  }

  /** Minimum sipariş uyarısının gösterilmediğini doğrular. */
  public void dogrulaMinimumSiparisUyarisiYok() {
    yokOlmali(Kimlikler.Sepet.MIN_SIPARIS_UYARISI);
  }

  /** "Siparişi onayla" butonunun pasif olduğunu doğrular. */
  public void dogrulaOnayPasif() {
    etkinOlmali(Kimlikler.Sepet.SIPARISI_ONAYLA, false);
  }

  /** "Siparişi onayla" butonunun aktif olduğunu doğrular. */
  public void dogrulaOnayAktif() {
    etkinOlmali(Kimlikler.Sepet.SIPARISI_ONAYLA, true);
  }

  /** Sepette ürünün bulunmadığını doğrular. */
  public void dogrulaUrunSepetteYok(String urunKodu) {
    yokOlmali(Kimlik.ekli(Kimlikler.Sepet.SATIR_ONEK, urunKodu));
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet ekranında). */
  public void dogrulaSepetSayaci(int adet) {
    metinOlmali(Kimlikler.Menu.SEPET_SAYACI, String.valueOf(adet));
  }

  /** Sepetin boş olduğunu doğrular. */
  public void dogrulaSepetBos() {
    gorunurOlmali(Kimlikler.Sepet.BOS);
  }
}

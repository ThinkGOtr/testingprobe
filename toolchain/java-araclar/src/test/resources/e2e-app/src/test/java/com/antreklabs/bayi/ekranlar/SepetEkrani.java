package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Ekran;
import com.antreklabs.bayi.altyapi.Kimlik;
import com.antreklabs.bayi.ekranlar.Kimlikler.Sepet;
import io.appium.java_client.AppiumDriver;

/** Sepet ekranı. */
public class SepetEkrani extends Ekran {
  public SepetEkrani(AppiumDriver surucu) {
    super(surucu);
  }

  /** Sepet toplamını doğrular. */
  public void dogrulaToplam(String beklenen) {
    metinDogrula(Kimlik.bul(Sepet.TOPLAM), beklenen);
  }

  /** Satır adedini doğrular. */
  public void dogrulaAdet(int adet) {
    metinDogrula(Kimlik.bul(Sepet.Satir.ADET), String.valueOf(adet));
  }

  /** Sepeti onaylar. */
  public void onayla() {}
}

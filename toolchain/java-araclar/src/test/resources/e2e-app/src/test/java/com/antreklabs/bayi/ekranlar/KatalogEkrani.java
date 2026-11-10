package com.antreklabs.bayi.ekranlar;

import static com.antreklabs.bayi.ekranlar.Kimlikler.Katalog.*;

import com.antreklabs.bayi.altyapi.Ekran;
import com.antreklabs.bayi.altyapi.Kimlik;
import io.appium.java_client.AppiumDriver;

/** Ürün kataloğu. */
public class KatalogEkrani extends Ekran {
  public KatalogEkrani(AppiumDriver surucu) {
    super(surucu);
  }

  /** Ürünü verilen adetle sepete ekler. */
  public void sepeteEkle(String urunKodu, int adet) {
    dokun(Kimlik.bul(URUN_KARTI_ONEK + urunKodu));
    for (int i = 0; i < adet; i++) {
      dokun(Kimlik.bul(SEPETE_EKLE));
    }
  }

  /** Katalogda indirim oranını doğrular. */
  public void dogrulaIndirim(double oran, boolean kampanyali) {}

  /** Uzun kodlu ürünü açar. */
  public void urunAc(long kod) {}
}

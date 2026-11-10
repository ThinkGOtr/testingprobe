package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumDriver;
import java.util.Optional;

/**
 * Bir testin uygulama oturumu: sürücü, bekleme yardımcısı ve ekranlar arası paylaşılan durum.
 *
 * <p>Ekran nesneleri bunu {@code TestTabani}'ndan alır; test kodu sürücüye doğrudan erişmez.
 */
public final class UygulamaOturumu {

  private final AppiumDriver surucu;
  private final Bekle bekle;
  private String sonSiparisNumarasi;

  public UygulamaOturumu(AppiumDriver surucu, Bekle bekle) {
    this.surucu = surucu;
    this.bekle = bekle;
  }

  public AppiumDriver surucu() {
    return surucu;
  }

  public Bekle bekle() {
    return bekle;
  }

  /** Onay ekranında en son doğrulanan sipariş numarası (web: readOrderNumber sonucu). */
  public Optional<String> sonSiparisNumarasi() {
    return Optional.ofNullable(sonSiparisNumarasi);
  }

  public void sonSiparisNumarasi(String numara) {
    this.sonSiparisNumarasi = numara;
  }
}

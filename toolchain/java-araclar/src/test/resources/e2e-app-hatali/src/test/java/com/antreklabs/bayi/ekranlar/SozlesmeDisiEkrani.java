package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Ekran;
import java.util.List;

/** Sözleşme dışı imzalar: tabloda kalır, errors'a yazılır. */
public class SozlesmeDisiEkrani extends Ekran {
  /** Liste parametresi desteklenmez. */
  public void topluEkle(List<String> kodlar) {}

  /** Değer döndürür. */
  public String toplam() {
    return Kimlikler.Sepet.TOPLAM;
  }

  /** Aşırı yükleme 1. */
  public void temizle() {}

  /** Aşırı yükleme 2. */
  public void temizle(int satir) {}

  /** Varargs desteklenmez. */
  public void ekle(String... kodlar) {}
}

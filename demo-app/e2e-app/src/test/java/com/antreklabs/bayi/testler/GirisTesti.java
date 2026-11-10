package com.antreklabs.bayi.testler;

import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

/** Bayi girişi (TPD-4) — web: tests/login.spec.ts. */
public class GirisTesti extends TestTabani {

  @Test(groups = {"duman"}, description = "doğru bilgilerle giriş yapılır ve katalog açılır")
  public void dogruBilgilerleGiris() {
    girisEkrani().ac();
    girisEkrani().girisYap(bayi().kullaniciAdi(), bayi().parola());
    girisEkrani().dogrulaGirisYapildi(bayi().ad());
    katalogEkrani().dogrulaUrunGorunur("P-001");
  }

  @Test(groups = {"duman"}, description = "hatalı parolada hata mesajı gösterilir")
  public void hataliParola() {
    girisEkrani().ac();
    girisEkrani().girisYap(bayi().kullaniciAdi(), "YanlisParola1");
    girisEkrani().dogrulaHataMesaji("Kullanıcı adı veya parola hatalı");
    girisEkrani().dogrulaGirisEkraninda();
  }

  @Test(description = "oturumsuz açılışta giriş ekranı gösterilir")
  public void oturumsuzAcilis() {
    // Web: oturumsuz /sepet → /giris yönlendirmesi. Uygulamada adres yok; sıfırlanmış uygulama
    // giriş ekranında açılmalı (önceki testin oturumu taşınmamalı).
    girisEkrani().dogrulaGirisEkraninda();
  }
}

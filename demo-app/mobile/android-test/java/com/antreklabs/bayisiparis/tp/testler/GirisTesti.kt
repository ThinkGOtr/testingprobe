package com.antreklabs.bayisiparis.tp.testler

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.antreklabs.bayisiparis.tp.altyapi.TestTabani
import org.junit.Test
import org.junit.runner.RunWith

/** Bayi girişi (TPD-4) — web: tests/login.spec.ts; Java: testler/GirisTesti.java. */
@RunWith(AndroidJUnit4::class)
class GirisTesti : TestTabani() {

  /** Doğru bilgilerle giriş yapılır ve katalog açılır. */
  @Test
  fun dogruBilgilerleGiris() {
    girisEkrani().ac()
    girisEkrani().girisYap(bayi().kullaniciAdi, bayi().parola)
    girisEkrani().dogrulaGirisYapildi(bayi().ad)
    katalogEkrani().dogrulaUrunGorunur("P-001")
  }

  /** Hatalı parolada hata mesajı gösterilir. */
  @Test
  fun hataliParola() {
    girisEkrani().ac()
    girisEkrani().girisYap(bayi().kullaniciAdi, "YanlisParola1")
    girisEkrani().dogrulaHataMesaji("Kullanıcı adı veya parola hatalı")
    girisEkrani().dogrulaGirisEkraninda()
  }

  /** Oturumsuz açılışta giriş ekranı gösterilir (önceki testin oturumu taşınmamalı). */
  @Test
  fun oturumsuzAcilis() {
    girisEkrani().dogrulaGirisEkraninda()
  }
}

// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map_app · platform: android · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 46175a46bd07b3e2b3e31ca480890fd9846f06f5c3276a5a93846e227326987b · şablon: a074fd6fcaebaec9b2a719cce8353732aa7c70cb02d0c8a53211cffcd7be49a4
// Hat: müşteri CI (derleme ve koşu GitHub Actions'ta) · kırarak doğrulanmadı
package com.antreklabs.bayisiparis.tp.uretilen

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.antreklabs.bayisiparis.tp.altyapi.Bayi
import com.antreklabs.bayisiparis.tp.altyapi.TestTabani
import org.junit.Test
import org.junit.runner.RunWith

// 7 adet kampanyalı üründe 1 adet bedava verilir
@RunWith(AndroidJUnit4::class)
@Bayi("bayi1")
class TPD1AndroidC2_3f9b1c2eTest : TestTabani() {
  @Test
  fun senaryo() {
    // S1 — Giriş sayfasını aç
    girisEkrani().ac()
    // S2 — Bayi kullanıcısıyla giriş yap
    girisEkrani().girisYap("bayi1", "Demo123!")
    // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
    katalogEkrani().sepeteEkle("P-001", 7)
    // S4 — Üst menüden sepete git
    katalogEkrani().sepetiAc()
    // Beklenen sonuç (değerler onaylı case metninden)
    sepetEkrani().dogrulaSatirAdedi("P-001", 7)
    sepetEkrani().dogrulaBedavaAdet("P-001", 1)
    sepetEkrani().dogrulaAraToplam("175,00 TL")
    sepetEkrani().dogrulaIndirim("25,00 TL")
    sepetEkrani().dogrulaToplam("150,00 TL")
  }
}

package com.antreklabs.bayisiparis.tp.altyapi

import android.app.Activity
import android.content.Context
import android.util.Log
import android.webkit.CookieManager
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.antreklabs.bayisiparis.tp.ekranlar.GirisEkrani
import com.antreklabs.bayisiparis.tp.ekranlar.KatalogEkrani
import com.antreklabs.bayisiparis.tp.ekranlar.OnayEkrani
import com.antreklabs.bayisiparis.tp.ekranlar.SepetEkrani
import com.antreklabs.bayisiparis.tp.ekranlar.SiparisEkrani
import org.junit.Rule
import org.junit.rules.TestRule
import org.junit.runner.Description
import org.junit.runners.model.Statement

/**
 * Tüm Espresso testlerinin tabanı (Java `altyapi/TestTabani.java` karşılığı).
 *
 * Her test için, sırasıyla (JUnit4 kuralı, testin içinde):
 * 1. bayi seçilir ([Bayi] notasyonu, yoksa ilk e2e bayisi);
 * 2. token varsa bayinin verisi sıfırlanır (`/test/reset`) ve istenen kırılma açılır
 *    (`/test/break`); yoksa yalnız sepeti boşaltılır;
 * 3. uygulamanın çerezleri silinir (oturum yok) ve uygulama başlatıcı etkinliğiyle sıfırdan açılır
 *    (`ActivityScenario`; MainActivity sınıfına derleme zamanında bağlı değildir);
 * 4. [OturumAcik] sınıflarda arayüzden giriş yapılır.
 *
 * Test bitince: başarısızsa kanıt ([Kanit]), etkinlik kapanır, kırılma geri alınır. Testler
 * arasında uygulama verisi ayrıca Test Orchestrator `clearPackageData` ile silinir (Expo eklentisi
 * `plugins/espresso.js`).
 *
 * Fikstür erişimi: her ekran için `lowerCamel(SınıfAdı)()` erişimcisi; üretilen testler yalnızca
 * bu erişimcileri ve [testVerisi] işlevini çağırır.
 */
abstract class TestTabani {

  private var ayarlar: Ayarlar? = null
  private var bayi: Bayiler.BayiBilgisi? = null
  private var oturum: UygulamaOturumu? = null
  private var senaryo: ActivityScenario<Activity>? = null

  private var girisEkrani: GirisEkrani? = null
  private var katalogEkrani: KatalogEkrani? = null
  private var sepetEkrani: SepetEkrani? = null
  private var onayEkrani: OnayEkrani? = null
  private var siparisEkrani: SiparisEkrani? = null

  /** Hazırlık → test → kapanış (hazırlık hatası testin kendi hatası olur; JUnit XML'de tek satır). */
  @get:Rule
  val tpKurali: TestRule = TestRule { govde, aciklama ->
    object : Statement() {
      override fun evaluate() {
        calistir(govde, aciklama)
      }
    }
  }

  private fun calistir(govde: Statement, aciklama: Description) {
    var veri: TestVerisi? = null
    var kirilma: TestVerisi.Kirilma? = null
    var basarisiz = false
    try {
      val a = Ayarlar.oku()
      ayarlar = a
      val b = Bayiler.sinifIcin(javaClass)
      bayi = b
      veri = TestVerisi(a)
      if (veri.sifirlamaVar) {
        veri.sifirla(b.kullaniciAdi)
        kirilma = veri.kirilma()
        kirilma?.let { veri.kir(it, b.kullaniciAdi, true) }
      } else {
        veri.sepetiBosalt(b)
      }
      cerezleriSil()
      senaryo = ActivityScenario.launch(baslaticiNiyeti())
      oturum = UygulamaOturumu(Bekle(a.beklemeMs))
      if (javaClass.isAnnotationPresent(OturumAcik::class.java)) {
        girisEkrani().ac()
        girisEkrani().girisYap(b.kullaniciAdi, b.parola)
        girisEkrani().dogrulaGirisYapildi(b.ad)
      }
      govde.evaluate()
    } catch (e: Throwable) {
      basarisiz = true
      throw e
    } finally {
      try {
        if (basarisiz) {
          Kanit.topla(aciklama.testClass?.simpleName ?: "Test", aciklama.methodName ?: "test")
        }
      } finally {
        try {
          senaryo?.close()
        } catch (e: RuntimeException) {
          Log.w(ETIKET, "etkinlik kapatılamadı", e)
        }
        val k = kirilma
        val v = veri
        val b = bayi
        if (k != null && v != null && b != null) {
          try {
            v.kir(k, b.kullaniciAdi, false)
          } catch (e: RuntimeException) {
            Log.w(ETIKET, "kırılma (kampanya / ekilmiş hata) geri alınamadı", e)
          }
        }
        senaryo = null
        oturum = null
        girisEkrani = null
        katalogEkrani = null
        sepetEkrani = null
        onayEkrani = null
        siparisEkrani = null
      }
    }
  }

  private fun baslaticiNiyeti(): android.content.Intent {
    val ctx = ApplicationProvider.getApplicationContext<Context>()
    return ctx.packageManager.getLaunchIntentForPackage(ctx.packageName)
      ?: throw IllegalStateException("uygulamanın başlatıcı etkinliği yok: ${ctx.packageName}")
  }

  /** RN'nin çerez deposu (`ForwardingCookieHandler`) WebView CookieManager'dır: oturum çerezi silinir. */
  private fun cerezleriSil() {
    try {
      InstrumentationRegistry.getInstrumentation().runOnMainSync {
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
      }
    } catch (e: RuntimeException) {
      Log.w(ETIKET, "çerezler silinemedi (Orchestrator clearPackageData yine de temizler)", e)
    }
  }

  private fun oturum(): UygulamaOturumu =
    oturum ?: throw IllegalStateException("uygulama oturumu yok (TestTabani hazırlığı başarısız)")

  /** Testin bayisi (elle yazılmış testler için; web: `dealer` fikstürü). */
  protected fun bayi(): Bayiler.BayiBilgisi =
    bayi ?: throw IllegalStateException("bayi seçilmedi (TestTabani hazırlığı başarısız)")

  /** Gizli test verisi (CI sırrı; enstrümantasyon argümanı `TP_TESTVERI_<AD>`). */
  protected fun testVerisi(ad: String): String =
    (ayarlar ?: throw IllegalStateException("ayarlar okunmadı")).testVerisi(ad)

  /** Giriş ekranı. */
  protected fun girisEkrani(): GirisEkrani = girisEkrani ?: GirisEkrani(oturum()).also { girisEkrani = it }

  /** Ürün kataloğu ekranı. */
  protected fun katalogEkrani(): KatalogEkrani =
    katalogEkrani ?: KatalogEkrani(oturum()).also { katalogEkrani = it }

  /** Sepet ekranı. */
  protected fun sepetEkrani(): SepetEkrani = sepetEkrani ?: SepetEkrani(oturum()).also { sepetEkrani = it }

  /** Sipariş onayı ekranı. */
  protected fun onayEkrani(): OnayEkrani = onayEkrani ?: OnayEkrani(oturum()).also { onayEkrani = it }

  /** Sipariş geçmişi ekranı. */
  protected fun siparisEkrani(): SiparisEkrani =
    siparisEkrani ?: SiparisEkrani(oturum()).also { siparisEkrani = it }

  private companion object {
    const val ETIKET = "TpTestTabani"
  }
}

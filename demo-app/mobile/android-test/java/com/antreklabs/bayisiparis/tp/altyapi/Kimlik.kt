package com.antreklabs.bayisiparis.tp.altyapi

import android.view.View
import org.hamcrest.Description
import org.hamcrest.Matcher
import org.hamcrest.TypeSafeMatcher

/**
 * Erişilebilirlik kimliği → Espresso eşleyicisi. Kimlik → eşleyici kuralı YALNIZCA buradadır;
 * ekran nesneleri `Kimlikler` sabitleriyle çalışır, üretilen testler eşleyici görmez.
 *
 * | Uygulama türü | Kimliğin yeri | Eşleşme |
 * |---|---|---|
 * | React Native (bu demo) | `testID` → `R.id.react_test_id` etiketi (+ eski sürümlerde `View.tag`) | etiket |
 * | Yerel Android | `android:id="@+id/<kimlik>"` | kaynak adı (`resources.getResourceEntryName`) |
 *
 * Üçü de aynı eşleyicide denenir: kütüphane hem RN hem yerel uygulamada kod değişmeden çalışır.
 * RN etiket anahtarı (`react_test_id`) çalışma anında kaynak adından çözülür; RN bağımlılığı
 * derleme zamanında gerekmez.
 */
object Kimlik {

  @Volatile private var rnEtiketAnahtari: Int? = null

  /** Önekli kimlik: `ekli("product-card-", "P-001") = "product-card-P-001"`. */
  fun ekli(onek: String, ek: String): String = onek + ek

  /** Görünümün kimliği (RN testID, etiket ya da kaynak adı); yoksa null. */
  fun kimligi(view: View): String? {
    val anahtar = rnAnahtari(view)
    if (anahtar != 0) {
      (view.getTag(anahtar) as? String)?.let { return it }
    }
    (view.tag as? String)?.let { return it }
    if (view.id != View.NO_ID) {
      return try {
        view.resources.getResourceEntryName(view.id)
      } catch (e: android.content.res.Resources.NotFoundException) {
        null
      }
    }
    return null
  }

  private fun rnAnahtari(view: View): Int {
    rnEtiketAnahtari?.let { return it }
    val ctx = view.context.applicationContext
    // RN kütüphanesi kaynakları uygulama paketine birleştirilir (R sınıfı yansıması yok).
    val id = ctx.resources.getIdentifier("react_test_id", "id", ctx.packageName)
    rnEtiketAnahtari = id
    return id
  }

  /** Kimliği `kimlik` olan görünüm. */
  fun eslestirici(kimlik: String): Matcher<View> =
    object : TypeSafeMatcher<View>() {
      override fun describeTo(description: Description) {
        description.appendText("kimlik '$kimlik'")
      }

      override fun matchesSafely(view: View): Boolean = kimligi(view) == kimlik
    }
}

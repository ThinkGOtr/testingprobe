package com.antreklabs.bayisiparis.tp.ekranlar

import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.NoMatchingViewException
import androidx.test.espresso.PerformException
import androidx.test.espresso.UiController
import androidx.test.espresso.ViewAction
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.closeSoftKeyboard
import androidx.test.espresso.action.ViewActions.replaceText
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.matcher.ViewMatchers.Visibility
import androidx.test.espresso.matcher.ViewMatchers.isAssignableFrom
import androidx.test.espresso.matcher.ViewMatchers.isDescendantOfA
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withEffectiveVisibility
import com.antreklabs.bayisiparis.tp.altyapi.Bekle
import com.antreklabs.bayisiparis.tp.altyapi.Kimlik
import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu
import org.hamcrest.Description
import org.hamcrest.Matcher
import org.hamcrest.Matchers.allOf
import org.hamcrest.TypeSafeMatcher

/**
 * Ekran nesnelerinin tabanı: platformdan bağımsız, kimlik sabitleriyle çalışan Espresso
 * yardımcıları (Java `ekranlar/Ekran.java` karşılığı; aynı davranış, aynı hata metinleri).
 *
 * Sözleşme: alt sınıfların `public` (Kotlin varsayılanı) metotları sembol tablosuna girer — eylem
 * (fiil, `Unit`) ya da beklenti (`dogrula` ön eki, `Unit`); parametreler yalnız `String`, `Int`,
 * `Long`, `Double`, `Boolean`. Bu sınıfın yardımcıları bilerek `protected`'dır; `internal` /
 * `private` metotlar da sembol tablosuna girmez.
 *
 * Hata türleri: eylem ön koşulu sağlanmazsa (öğe yok, tıklanamıyor) `TimeoutException`; beklenti
 * sağlanmazsa `AssertionError`. Metin karşılaştırması web'deki `toHaveText` gibi boşlukları
 * sadeleştirir (NBSP dahil).
 *
 * Eşzamanlama: Espresso eylemleri ana iş parçacığının boşalmasını bekler; React Native'in JS
 * iş parçacığı görünmediği için her koşul [Bekle] ile yoklanır (TASARIM risk R4).
 */
abstract class Ekran protected constructor(private val oturum: UygulamaOturumu) {

  protected fun oturum(): UygulamaOturumu = oturum

  protected fun bekle(): Bekle = oturum.bekle

  // ------------------------------------------------------------------ bulma

  /** İlk eşleşen görünüm (aynı kimlikli birden çok görünümde Espresso belirsizlik hatası vermez). */
  private fun ilk(m: Matcher<View>): Matcher<View> =
    object : TypeSafeMatcher<View>() {
      private var bulunan: View? = null

      override fun describeTo(description: Description) {
        description.appendText("ilk ")
        m.describeTo(description)
      }

      override fun matchesSafely(view: View): Boolean {
        if (bulunan == null && m.matches(view)) {
          bulunan = view
        }
        return bulunan === view
      }
    }

  private fun eslestirici(kapsayici: String?, kimlik: String, vararg ek: Matcher<View>): Matcher<View> {
    val parcalar = mutableListOf<Matcher<in View>>(Kimlik.eslestirici(kimlik))
    if (kapsayici != null) {
      parcalar.add(isDescendantOfA(Kimlik.eslestirici(kapsayici)))
    }
    parcalar.addAll(ek)
    return ilk(allOf(parcalar))
  }

  /** Eşleşen ilk görünümde ana iş parçacığında `oku` çalıştırır; görünüm yoksa null. */
  private fun <T : Any> oku(m: Matcher<View>, oku: (View) -> T): T? {
    var sonuc: T? = null
    try {
      onView(m)
        .perform(
          object : ViewAction {
            override fun getConstraints(): Matcher<View> = isAssignableFrom(View::class.java)

            override fun getDescription(): String = "görünümü oku"

            override fun perform(uiController: UiController, view: View) {
              sonuc = oku(view)
            }
          }
        )
    } catch (e: NoMatchingViewException) {
      return null
    }
    return sonuc
  }

  /** Öğe (gerekirse bir kez kaydırılarak) görünür mü; beklemez. */
  private fun gorunur(kapsayici: String?, kimlik: String): Boolean {
    if (oku(eslestirici(kapsayici, kimlik, isDisplayed())) { true } == true) {
      return true
    }
    kaydir(kapsayici, kimlik)
    return oku(eslestirici(kapsayici, kimlik, isDisplayed())) { true } == true
  }

  /** Görünüm ağaçta ama ekran dışındaysa kaydırılabilir atasında görünür alana getirir. */
  private fun kaydir(kapsayici: String?, kimlik: String) {
    try {
      onView(eslestirici(kapsayici, kimlik, withEffectiveVisibility(Visibility.VISIBLE))).perform(scrollTo())
    } catch (e: NoMatchingViewException) {
      // ağaçta yok (henüz çizilmedi): yoklama sürer
    } catch (e: PerformException) {
      // kaydırılabilir ata yok ya da zaten görünür
    }
  }

  private fun ad(kapsayici: String?, kimlik: String): String =
    if (kapsayici == null) "'$kimlik'" else "'$kapsayici' içinde '$kimlik'"

  /** Öğe görünür olana kadar (gerekirse kaydırarak) bekler; olmazsa TimeoutException. */
  protected fun gorunurBekle(kimlik: String) {
    gorunurBekle(null, kimlik)
  }

  /** Kapsayıcı (ör. ürün kartı) içindeki öğe görünür olana kadar bekler. */
  protected fun gorunurBekle(kapsayici: String?, kimlik: String) {
    bekle().kosul("öğe görünmedi: kimlik ${ad(kapsayici, kimlik)}") { if (gorunur(kapsayici, kimlik)) true else null }
  }

  /** İki öğeden biri görünene kadar bekler (web: `expect(a.or(b)).toBeVisible()`). */
  protected fun biriGorunurBekle(kimlik1: String, kimlik2: String) {
    bekle().kosul("öğe görünmedi: kimlik '$kimlik1' ya da '$kimlik2'") {
      if (gorunur(null, kimlik1) || gorunur(null, kimlik2)) true else null
    }
  }

  /** Öğe ağaçta (kaydırılabilir alan dahil) görünür durumda var mı; beklemez. */
  private fun var_(kimlik: String): Boolean =
    oku(eslestirici(null, kimlik, withEffectiveVisibility(Visibility.VISIBLE))) { true } == true

  // ------------------------------------------------------------------ eylemler

  /** Öğeye dokunur (görünür ve etkin olmasını bekler). */
  protected fun dokun(kimlik: String) {
    dokun(null, kimlik)
  }

  /** Kapsayıcı içindeki öğeye dokunur. */
  protected fun dokun(kapsayici: String?, kimlik: String) {
    bekle().kosul("öğe tıklanabilir olmadı: kimlik ${ad(kapsayici, kimlik)}") {
      if (!gorunur(kapsayici, kimlik)) {
        return@kosul null
      }
      if (oku(eslestirici(kapsayici, kimlik, isDisplayed())) { etkin(it) } != true) {
        return@kosul null
      }
      try {
        onView(eslestirici(kapsayici, kimlik, isDisplayed())).perform(click())
        true
      } catch (e: PerformException) {
        null // ör. %90'dan azı görünür: yeniden kaydır ve dene
      } catch (e: NoMatchingViewException) {
        null
      }
    }
  }

  /** Alana metin yazar (öncekini değiştirir), sonra ekran klavyesini kapatır. */
  protected fun yaz(kimlik: String, metin: String) {
    gorunurBekle(kimlik)
    onView(eslestirici(null, kimlik, isDisplayed())).perform(replaceText(metin), closeSoftKeyboard())
  }

  // ------------------------------------------------------------------ metin

  private fun kendiMetni(v: View): String {
    val t = (v as? TextView)?.text?.toString()
    if (!t.isNullOrBlank()) {
      return sade(t)
    }
    val d = v.contentDescription?.toString()
    return if (!d.isNullOrBlank()) sade(d) else ""
  }

  private fun altMetinler(v: View, parcalar: MutableList<String>) {
    val grup = v as? ViewGroup ?: return
    for (i in 0 until grup.childCount) {
      val alt = grup.getChildAt(i)
      val t = kendiMetni(alt)
      if (t.isNotEmpty() && t !in parcalar) {
        parcalar.add(t)
      }
      altMetinler(alt, parcalar)
    }
  }

  /** Görünen metin: kendi metni, yoksa alt öğelerin metinleri (RN'de testID View'daysa metin alt Text'tedir). */
  private fun metin(v: View): String {
    val kendi = kendiMetni(v)
    if (kendi.isNotEmpty()) {
      return kendi
    }
    val parcalar = mutableListOf<String>()
    altMetinler(v, parcalar)
    return sade(parcalar.joinToString(" "))
  }

  /** Öğenin ve tüm alt öğelerinin metinleri (web: `toContainText` kapsamı). */
  private fun tumMetin(v: View): String {
    val parcalar = mutableListOf(kendiMetni(v))
    altMetinler(v, parcalar)
    return sade(parcalar.joinToString(" "))
  }

  /** Öğenin görünen metni (beklemeden); öğe yoksa `(öğe yok)`. */
  protected fun gorulenMetin(kapsayici: String?, kimlik: String, tum: Boolean = false): String {
    if (!gorunur(kapsayici, kimlik)) {
      return YOK
    }
    return oku(eslestirici(kapsayici, kimlik, isDisplayed())) { if (tum) tumMetin(it) else metin(it) } ?: YOK
  }

  private fun etkin(v: View): Boolean {
    if (!v.isEnabled) {
      return false
    }
    // RN `accessibilityState.disabled` görünümün değil erişilebilirlik düğümünün durumudur.
    val bilgi = v.createAccessibilityNodeInfo()
    return bilgi.isEnabled
  }

  // ------------------------------------------------------------------ beklentiler (AssertionError)

  /** Öğenin metni tam olarak beklenen (sadeleştirilmiş) olmalı. */
  protected fun metinOlmali(kimlik: String, beklenen: String) {
    val b = sade(beklenen)
    bekle().dogrula("'$kimlik' metni", b, { gorulenMetin(null, kimlik) }) { gorulenMetin(null, kimlik) == b }
  }

  /** Öğenin metni kalıba tam uymalı. */
  protected fun metinKalibinaUymali(kimlik: String, kalip: Regex) {
    bekle().dogrula("'$kimlik' metni", "/${kalip.pattern}/", { gorulenMetin(null, kimlik) }) {
      kalip.matches(gorulenMetin(null, kimlik))
    }
  }

  /** Öğenin metni beklenen parçayı içermeli. */
  protected fun metinIcermeli(kimlik: String, parca: String) {
    val p = sade(parca)
    bekle().dogrula("'$kimlik' metni", "… $p …", { gorulenMetin(null, kimlik) }) {
      gorulenMetin(null, kimlik).contains(p)
    }
  }

  /** Öğe ve alt öğelerinin metni beklenen parçayı içermeli (ör. ürün kartında kampanya adı). */
  protected fun tumMetinIcermeli(kimlik: String, parca: String) {
    val p = sade(parca)
    bekle().dogrula("'$kimlik' içeriği", "… $p …", { gorulenMetin(null, kimlik, tum = true) }) {
      gorulenMetin(null, kimlik, tum = true).contains(p)
    }
  }

  /** Öğe görünür olmalı. */
  protected fun gorunurOlmali(kimlik: String) {
    bekle().dogrula("'$kimlik' görünürlüğü", "görünür", { YOK }) { gorunur(null, kimlik) }
  }

  /** Öğe ekranda olmamalı (web: `toHaveCount(0)`); kaydırılabilir alanın tamamına bakılır. */
  protected fun yokOlmali(kimlik: String) {
    bekle().dogrula("'$kimlik' yokluğu", YOK, { "görünür" }) { !var_(kimlik) }
  }

  /** Öğe etkin (true) ya da pasif (false) olmalı. */
  protected fun etkinOlmali(kimlik: String, etkin: Boolean) {
    val beklenen = if (etkin) "etkin" else "pasif"
    fun durum(): String {
      if (!gorunur(null, kimlik)) {
        return YOK
      }
      return when (oku(eslestirici(null, kimlik, isDisplayed())) { etkin(it) }) {
        true -> "etkin"
        false -> "pasif"
        null -> YOK
      }
    }
    bekle().dogrula("'$kimlik' durumu", beklenen, { durum() }) { durum() == beklenen }
  }

  protected companion object {
    const val YOK = "(öğe yok)"

    /** Boşlukları sadeleştirir: NBSP / dar NBSP → boşluk, ardışık boşluk → tek, baş/son kırpılır. */
    fun sade(s: String?): String =
      (s ?: "").replace(' ', ' ').replace(' ', ' ').replace(Regex("\\s+"), " ").trim()
  }
}

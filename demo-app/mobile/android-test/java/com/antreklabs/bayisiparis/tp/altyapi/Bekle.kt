package com.antreklabs.bayisiparis.tp.altyapi

import android.os.SystemClock
import java.util.concurrent.TimeoutException

/**
 * Yoklamalı bekleme (Appium `Bekle.java` karşılığı). Espresso yalnız ana iş parçacığının boşta
 * olmasını bekler; React Native'in JS iş parçacığı ve ağ çağrıları Espresso'ya görünmez (TASARIM
 * risk R4). Bu yüzden ekran durumu bir koşul sağlanana dek yoklanır.
 *
 * Hata türleri (triage sözleşmesi, Java ile aynı metin):
 * - [kosul]: süre dolarsa `TimeoutException(<açıklama>)` → locator / zaman aşımı;
 * - [dogrula]: beklenen sonuç sağlanmazsa
 *   `AssertionError("<açıklama>: beklenen <X>, görülen <Y> (N ms)")` → assertion.
 */
class Bekle(val ustSinirMs: Long = 15_000L, private val aralikMs: Long = 250L) {

  /** Koşul null olmayan bir değer döndürene kadar yoklar; süre dolarsa TimeoutException. */
  fun <T : Any> kosul(aciklama: String, kosul: () -> T?): T {
    val son = SystemClock.uptimeMillis() + ustSinirMs
    var sonHata: Throwable? = null
    while (true) {
      try {
        val deger = kosul()
        if (deger != null) {
          return deger
        }
      } catch (e: AssertionError) {
        throw e // ekranda kesin bir hata görüldü (ör. "sepete ekleme başarısız")
      } catch (e: RuntimeException) {
        sonHata = e // görünüm henüz yok / geçiş sürüyor: yeniden dene
      }
      if (SystemClock.uptimeMillis() >= son) {
        val hata = TimeoutException(aciklama)
        if (sonHata != null) {
          hata.initCause(sonHata)
        }
        throw hata
      }
      SystemClock.sleep(aralikMs)
    }
  }

  /** Beklenen sonucu süre boyunca yoklar; sağlanmazsa AssertionError (görülen son değerle). */
  fun dogrula(aciklama: String, beklenen: String, gorulen: () -> String, saglandi: () -> Boolean) {
    val son = SystemClock.uptimeMillis() + ustSinirMs
    var sonGorulen = ""
    while (true) {
      try {
        if (saglandi()) {
          return
        }
        sonGorulen = gorulen()
      } catch (e: RuntimeException) {
        sonGorulen = "(okunamadı: ${e.javaClass.simpleName})"
      }
      if (SystemClock.uptimeMillis() >= son) {
        throw AssertionError("$aciklama: beklenen <$beklenen>, görülen <$sonGorulen> ($ustSinirMs ms)")
      }
      SystemClock.sleep(aralikMs)
    }
  }
}

package com.antreklabs.bayisiparis.tp.altyapi

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry

/**
 * Koşu ayarları: enstrümantasyon argümanlarından okunur
 * (`./gradlew connected…AndroidTest -Pandroid.testInstrumentationRunnerArguments.<ad>=<değer>`).
 * Cihazda süreç ortamı (`System.getenv`) CI ortamını görmez; tüm değerler buradan gelir.
 *
 * | Argüman | Anlam | Varsayılan |
 * |---|---|---|
 * | `tpApiUrl` | Demo API kökü (test uçları `/test/reset`, `/test/break`) | `http://10.0.2.2:18000` (emülatörden host) |
 * | `tpTestToken` | `X-Demoapp-Test-Token` (yoksa yalnız sepet yalıtımı) | — |
 * | `tpBeklemeMs` | Ekran koşulu üst sınırı (ms) | `15000` |
 * | `BREAK_CAMPAIGN` | `1`: bayi kapsamlı kampanya kırılması | — |
 * | `TP_FAULT` | Ekilmiş hata kodu | — |
 * | `TP_TESTVERI_<AD>` | Gizli test verisi (CI sırrından; üretilen test `testVerisi("…")` ile okur) | — |
 */
class Ayarlar(private val argumanlar: Bundle) {

  val demoApiUrl: String
    get() = (deger("tpApiUrl") ?: VARSAYILAN_API).trimEnd('/')

  val testToken: String?
    get() = deger("tpTestToken")

  val beklemeMs: Long
    get() = deger("tpBeklemeMs")?.toLongOrNull()?.coerceIn(1_000L, 120_000L) ?: 15_000L

  val kampanyaKirik: Boolean
    get() = deger("BREAK_CAMPAIGN") == "1"

  val ekilmisHata: String?
    get() = deger("TP_FAULT")?.takeIf { HATA_KODU.matches(it) }

  /** Gizli test verisi (`TP_TESTVERI_[A-Z0-9_]+`); tanımsızsa açık hata. */
  fun testVerisi(ad: String): String {
    require(SIR_ADI.matches(ad)) { "geçersiz test verisi adı: $ad" }
    return deger(ad)
      ?: throw IllegalStateException(
        "test verisi '$ad' tanımsız: CI sırrını -Pandroid.testInstrumentationRunnerArguments.$ad=… ile verin"
      )
  }

  private fun deger(ad: String): String? = argumanlar.getString(ad)?.trim()?.takeIf { it.isNotEmpty() }

  companion object {
    const val VARSAYILAN_API = "http://10.0.2.2:18000"
    private val SIR_ADI = Regex("^TP_TESTVERI_[A-Z0-9_]{1,64}\$")
    private val HATA_KODU = Regex("^[A-Za-z0-9._-]{1,64}\$")

    fun oku(): Ayarlar = Ayarlar(InstrumentationRegistry.getArguments())
  }
}

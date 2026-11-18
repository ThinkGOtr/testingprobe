package com.antreklabs.bayisiparis.tp.altyapi

import android.app.Activity
import android.graphics.Bitmap
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.services.storage.TestStorage
import java.io.OutputStream

/**
 * Başarısız testin kanıtı (triage): `kanit/<Sınıf>.<metot>/ekran.png` ve `sayfa-kaynagi.xml`
 * (görünüm ağacı; her düğümde `resource-id` = erişilebilirlik kimliği, Appium sayfa kaynağıyla
 * aynı nitelik adı). Dosyalar AndroidX Test Storage ile yazılır; Gradle koşu sonunda
 * `build/outputs/connected_android_test_additional_output/` altına çeker (iş akışı `tp-results/ekler/`e
 * kopyalar). Kanıt toplanamazsa test sonucu değişmez (yalnız log).
 */
object Kanit {

  private const val ETIKET = "TpKanit"
  private val GUVENSIZ = Regex("[^A-Za-z0-9._-]")
  private const val MAX_DUGUM = 5_000

  /** `Sınıf.metot` → güvenli dizin adı (Java `Kanit.dizin` ile aynı indirgeme). */
  fun dizin(sinif: String, metot: String): String = GUVENSIZ.replace("$sinif.$metot", "_")

  fun topla(sinif: String, metot: String) {
    val kok = "kanit/${dizin(sinif, metot)}"
    try {
      val ekran: Bitmap? = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
      if (ekran != null) {
        yaz("$kok/ekran.png") { ekran.compress(Bitmap.CompressFormat.PNG, 100, it) }
      }
    } catch (e: Throwable) {
      Log.w(ETIKET, "ekran görüntüsü alınamadı", e)
    }
    try {
      val xml = StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<hierarchy>\n")
      InstrumentationRegistry.getInstrumentation().runOnMainSync {
        etkinlik()?.window?.decorView?.let { dok(it, xml, 1, intArrayOf(0)) }
      }
      xml.append("</hierarchy>\n")
      yaz("$kok/sayfa-kaynagi.xml") { it.write(xml.toString().toByteArray(Charsets.UTF_8)) }
    } catch (e: Throwable) {
      Log.w(ETIKET, "görünüm ağacı yazılamadı", e)
    }
  }

  private fun etkinlik(): Activity? =
    ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).firstOrNull()

  private fun yaz(yol: String, govde: (OutputStream) -> Unit) {
    TestStorage().openOutputFile(yol).use(govde)
  }

  private fun dok(view: View, xml: StringBuilder, derinlik: Int, sayac: IntArray) {
    if (sayac[0]++ >= MAX_DUGUM) {
      return
    }
    val girinti = "  ".repeat(derinlik)
    xml
      .append(girinti)
      .append("<node class=\"")
      .append(kacis(view.javaClass.name))
      .append("\" resource-id=\"")
      .append(kacis(Kimlik.kimligi(view) ?: ""))
      .append("\" text=\"")
      .append(kacis((view as? TextView)?.text?.toString() ?: ""))
      .append("\" content-desc=\"")
      .append(kacis(view.contentDescription?.toString() ?: ""))
      .append("\" displayed=\"")
      .append(view.isShown)
      .append("\" enabled=\"")
      .append(view.isEnabled)
      .append("\"")
    val grup = view as? ViewGroup
    if (grup == null || grup.childCount == 0) {
      xml.append("/>\n")
      return
    }
    xml.append(">\n")
    for (i in 0 until grup.childCount) {
      dok(grup.getChildAt(i), xml, derinlik + 1, sayac)
    }
    xml.append(girinti).append("</node>\n")
  }

  private fun kacis(s: String): String {
    val b = StringBuilder(s.length)
    for (c in s) {
      when {
        c == '<' -> b.append("&lt;")
        c == '>' -> b.append("&gt;")
        c == '&' -> b.append("&amp;")
        c == '"' -> b.append("&quot;")
        c.code < 0x20 && c != '\n' && c != '\t' -> b.append(' ')
        else -> b.append(c)
      }
    }
    return b.toString()
  }
}

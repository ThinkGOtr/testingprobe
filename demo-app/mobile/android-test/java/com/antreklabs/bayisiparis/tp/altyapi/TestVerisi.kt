package com.antreklabs.bayisiparis.tp.altyapi

import java.net.HttpURLConnection
import java.net.URL

/**
 * Demo API test uçları (Java `altyapi/TestVerisi.java` karşılığı; aynı uçlar, aynı gövdeler).
 *
 * - Token varsa: `POST /test/reset` (bayinin sepeti, siparişleri, kırılması silinir) ve gerekirse
 *   `POST /test/break` (kampanya kırılması ya da ekilmiş hata). Başlık `X-Demoapp-Test-Token`.
 * - Token yoksa: bayinin sepeti herkese açık API ile boşaltılır (giriş → `DELETE /cart` → çıkış).
 *
 * İstekler cihazdan host'a gider (emülatör: `10.0.2.2`); düz HTTP izni uygulamanın ağ güvenliği
 * yapılandırmasındadır (`plugins/ag-guvenligi.js`; enstrümantasyon uygulamanın sürecinde koşar).
 */
class TestVerisi(private val ayarlar: Ayarlar) {

  /** Bayi kapsamlı kırılma: `hataKodu` doluysa ekilmiş hata, boşsa kampanya kırılması. */
  data class Kirilma(val hataKodu: String?) {
    fun govde(kullaniciAdi: String, acik: Boolean): String =
      if (hataKodu == null) {
        "{\"kullanici_adi\":${jsonDize(kullaniciAdi)},\"kampanya\":$acik}"
      } else {
        "{\"kullanici_adi\":${jsonDize(kullaniciAdi)},\"hata\":${if (acik) jsonDize(hataKodu) else "null"}}"
      }
  }

  /** Token varsa veri sıfırlanır; yoksa yalnız sepet boşaltılır. */
  val sifirlamaVar: Boolean
    get() = ayarlar.testToken != null

  /** Bu koşunun kırılması (TP_FAULT önce, sonra BREAK_CAMPAIGN=1); yoksa null. */
  fun kirilma(): Kirilma? =
    ayarlar.ekilmisHata?.let { Kirilma(it) } ?: if (ayarlar.kampanyaKirik) Kirilma(null) else null

  /** Bayinin verisini sıfırlar (sepet, siparişler, demo kırılması). */
  fun sifirla(kullaniciAdi: String) {
    testUcu("reset", "{\"kullanici_adi\":${jsonDize(kullaniciAdi)}}")
  }

  /** Bu koşunun kırılmasını bayi için açar ya da geri alır. */
  fun kir(kirilma: Kirilma, kullaniciAdi: String, acik: Boolean) {
    testUcu("break", kirilma.govde(kullaniciAdi, acik))
  }

  /** Token olmadan: bayinin sepetini herkese açık API ile boşaltır ve oturumu kapatır. */
  fun sepetiBosalt(bayi: Bayiler.BayiBilgisi) {
    val giris = "{\"kullanici_adi\":${jsonDize(bayi.kullaniciAdi)},\"parola\":${jsonDize(bayi.parola)}}"
    val girisYaniti = istek("POST", "/auth/login", giris, emin = "sepet temizliği için giriş")
    val cerez = girisYaniti.cerez ?: throw IllegalStateException("sepet temizliği: oturum çerezi gelmedi")
    val bosalt = istek("DELETE", "/cart", null, cerez = cerez, emin = "sepet boşaltma")
    check(bosalt.govde.replace(" ", "").contains("\"satirlar\":[]")) { "sepet boşaltılamadı: yanıtta satırlar kaldı" }
    istek("POST", "/auth/logout", "", cerez = cerez, emin = "çıkış")
  }

  private fun testUcu(yol: String, govde: String) {
    val token = ayarlar.testToken ?: throw IllegalStateException("/test/$yol için tpTestToken gerekir")
    val yanit = istek("POST", "/test/$yol", govde, token = token)
    if (yanit.durum / 100 != 2) {
      val ipucu = if (yanit.durum == 404) " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok)" else ""
      throw IllegalStateException("POST /test/$yol başarısız: ${yanit.durum}$ipucu")
    }
  }

  private class Yanit(val durum: Int, val govde: String, val cerez: String?)

  private fun istek(
    yontem: String,
    yol: String,
    govde: String?,
    token: String? = null,
    cerez: String? = null,
    emin: String? = null,
  ): Yanit {
    val baglanti = URL(ayarlar.demoApiUrl + yol).openConnection() as HttpURLConnection
    try {
      baglanti.requestMethod = yontem
      baglanti.connectTimeout = ZAMAN_ASIMI_MS
      baglanti.readTimeout = ZAMAN_ASIMI_MS
      baglanti.instanceFollowRedirects = false
      token?.let { baglanti.setRequestProperty(TOKEN_BASLIGI, it) }
      cerez?.let { baglanti.setRequestProperty("Cookie", it) }
      if (govde != null) {
        baglanti.doOutput = true
        baglanti.setRequestProperty("Content-Type", "application/json")
        baglanti.outputStream.use { it.write(govde.toByteArray(Charsets.UTF_8)) }
      }
      val durum = baglanti.responseCode
      val akis = if (durum >= 400) baglanti.errorStream else baglanti.inputStream
      val metin = akis?.use { it.readBytes().toString(Charsets.UTF_8) } ?: ""
      val yeniCerez =
        baglanti.headerFields["Set-Cookie"]?.joinToString("; ") { it.substringBefore(';') }
      if (emin != null && durum / 100 != 2) {
        throw IllegalStateException("$emin başarısız: $durum")
      }
      return Yanit(durum, metin, yeniCerez)
    } finally {
      baglanti.disconnect()
    }
  }

  companion object {
    const val TOKEN_BASLIGI = "X-Demoapp-Test-Token"
    private const val ZAMAN_ASIMI_MS = 15_000

    /** JSON dize literali (yalnızca kullanıcı adı gibi kısa değerler için). */
    fun jsonDize(s: String): String {
      val b = StringBuilder("\"")
      for (c in s) {
        when {
          c == '"' -> b.append("\\\"")
          c == '\\' -> b.append("\\\\")
          c.code < 0x20 -> b.append(String.format("\\u%04x", c.code))
          else -> b.append(c)
        }
      }
      return b.append('"').toString()
    }
  }
}

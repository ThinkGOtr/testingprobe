package com.antreklabs.bayisiparis.tp.altyapi

/**
 * e2e bayi kullanıcıları ve testin bayisini seçme kuralı (web: tests/fixtures.ts `DEALERS`;
 * Java: `altyapi/Bayiler.java`). TP bayi sabitlemesi için bu listeyi sözdizimsel okur
 * (`BayiBilgisi("<kullanıcı>", "<parola>", "<ad>")`).
 */
object Bayiler {

  /** Bir bayi kullanıcısı. */
  data class BayiBilgisi(val kullaniciAdi: String, val parola: String, val ad: String) {
    override fun toString(): String = kullaniciAdi
  }

  /** e2e bayileri. Parola seed verisidir (demo-app/api seed.py), sır değildir; web e2e ile aynıdır. */
  val E2E: List<BayiBilgisi> =
    listOf(
      BayiBilgisi("bayi1", "Demo123!", "Merkez Bayi"),
      BayiBilgisi("bayi2", "Demo123!", "Sahil Bayi"),
    )

  /** Doğrulama ajanının (app-mcp) bayisi; e2e testleri kullanamaz ve sıfırlamaz. */
  const val AJAN_BAYISI = "bayi3"

  /** Testin bayisi: `sabit` verilmişse o, yoksa ilk e2e bayisi (tek cihaz, sıralı koşu). */
  fun sec(sabit: String?): BayiBilgisi {
    if (sabit == null) {
      return E2E.first()
    }
    E2E.firstOrNull { it.kullaniciAdi == sabit }?.let { return it }
    val ayrilmis = if (sabit == AJAN_BAYISI) " (doğrulama ajanına ayrılmıştır)" else ""
    throw IllegalArgumentException(
      "@Bayi(\"$sabit\") bir e2e bayisi değil$ayrilmis; izinli: ${E2E.joinToString(", ") { it.kullaniciAdi }}"
    )
  }

  /** Test sınıfının bayisi: sınıftaki (ya da üst sınıftaki) [Bayi] notasyonu, yoksa ilk bayi. */
  fun sinifIcin(testSinifi: Class<*>): BayiBilgisi = sec(testSinifi.getAnnotation(Bayi::class.java)?.value)
}

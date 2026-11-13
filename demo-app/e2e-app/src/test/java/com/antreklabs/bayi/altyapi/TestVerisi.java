package com.antreklabs.bayi.altyapi;

import java.io.IOException;
import java.net.CookieManager;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Optional;

/**
 * Test verisi yalıtımı ve "kırarak doğrula" kancaları (web: tests/fixtures.ts {@code isolationMode},
 * {@code testApi}, {@code clearCartViaPublicApi}).
 *
 * <ul>
 *   <li>Sıfırlama (varsayılan): her testten önce yalnızca o bayinin sepeti, siparişleri ve demo
 *       kırılması {@code POST /test/reset} ile silinir; {@code X-Demoapp-Test-Token} ister.
 *   <li>Yalnızca sepet ({@code TP_E2E_NO_RESET=1}, token yok): bayinin sepeti herkese açık API ile
 *       (giriş + {@code DELETE /cart}) boşaltılır; {@code sifir-veri} gruplu testler atlanır.
 *   <li>{@code BREAK_CAMPAIGN=1}: bayi kapsamlı {@code POST /test/break} (kampanya kuralı bozulur),
 *       test sonunda geri alınır. Token gerekir.
 *   <li>{@code TP_FAULT=<kod>}: aynı uçla bayi kapsamlı ekilmiş hata ({@code {"hata": kod}});
 *       test sonunda kaldırılır. Token gerekir; {@code BREAK_CAMPAIGN=1} ile birlikteyse geçerli olan
 *       budur.
 * </ul>
 *
 * <p>Token yalnızca istek başlığında taşınır; günlüğe, rapora ya da kanıt dosyasına yazılmaz.
 */
public final class TestVerisi {

  /** Paylaşılan sırrın başlığı (API: main.py TEST_TOKEN_HEADER). */
  public static final String TOKEN_BASLIGI = "X-Demoapp-Test-Token";

  /** Veri yalıtım kipi. */
  public enum Kip {
    SIFIRLAMA,
    YALNIZ_SEPET
  }

  private static final Duration ZAMAN_ASIMI = Duration.ofSeconds(10);

  private final Ayarlar ayarlar;
  private final HttpClient istemci;

  public TestVerisi(Ayarlar ayarlar) {
    this.ayarlar = ayarlar;
    // HTTP/1.1: varsayılan HTTP/2 düz http üzerinde h2c yükseltmesi dener; vite preview vekili
    // (<BASE_URL>/api) bu isteği yanıtsız bırakıp zaman aşımına düşürür.
    this.istemci =
        HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(ZAMAN_ASIMI)
            .cookieHandler(new CookieManager())
            .build();
  }

  /** Ortamdan yalıtım kipi; geçersiz birleşimlerde açıklayıcı hata (web: isolationMode). */
  public static Kip kip(Ayarlar ayarlar) {
    if (ayarlar.testToken().isPresent()) {
      return Kip.SIFIRLAMA;
    }
    if (ayarlar.ekilmisHata().isPresent()) {
      throw new IllegalStateException(
          "TP_FAULT için DEMOAPP_TEST_TOKEN gerekir (ekilmiş hata POST /test/break ile bayi kapsamında açılır).");
    }
    if (ayarlar.kampanyaKirik()) {
      throw new IllegalStateException(
          "BREAK_CAMPAIGN=1 için DEMOAPP_TEST_TOKEN gerekir (kırılma POST /test/break ile bayi kapsamında açılır).");
    }
    if (ayarlar.sifirlamaYok()) {
      return Kip.YALNIZ_SEPET;
    }
    throw new IllegalStateException(
        "DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz. Ya token ile DEMO_API_URL verin "
            + "(ör. http://127.0.0.1:18000) ya da yalnızca sepet yalıtımı için TP_E2E_NO_RESET=1 verin.");
  }

  /** {@code /test/<yol>} adresi. */
  static String testUcu(String apiKoku, String yol) {
    return apiKoku.replaceAll("/+$", "") + "/test/" + yol;
  }

  /** JSON dize literali (yalnızca kullanıcı adı gibi kısa değerler için). */
  static String jsonDize(String s) {
    StringBuilder b = new StringBuilder("\"");
    for (char c : s.toCharArray()) {
      switch (c) {
        case '"':
          b.append("\\\"");
          break;
        case '\\':
          b.append("\\\\");
          break;
        default:
          if (c < 0x20) {
            b.append(String.format("\\u%04x", (int) c));
          } else {
            b.append(c);
          }
      }
    }
    return b.append('"').toString();
  }

  /** Bayinin verisini sıfırlar (sepet, siparişler, demo kırılması). */
  public void sifirla(String kullaniciAdi) {
    testUcunuCagir("reset", "{\"kullanici_adi\":" + jsonDize(kullaniciAdi) + "}");
  }

  /** Bayi kapsamlı kampanya kırılmasını açar ya da kapatır. */
  public void kampanyayiKir(String kullaniciAdi, boolean acik) {
    testUcunuCagir("break", kampanyaGovdesi(kullaniciAdi, acik));
  }

  /**
   * Bu koşunun bayi kapsamlı kırılması: TP_FAULT (ekilmiş hata) varsa o, yoksa BREAK_CAMPAIGN=1
   * (kampanya), hiçbiri yoksa boş (web: fixtures.ts {@code dealerBreak}).
   */
  public static Optional<Kirilma> kirilma(Ayarlar ayarlar) {
    Optional<String> kod = ayarlar.ekilmisHata();
    if (kod.isPresent()) {
      return Optional.of(new Kirilma(kod.get()));
    }
    return ayarlar.kampanyaKirik() ? Optional.of(new Kirilma(null)) : Optional.empty();
  }

  /** Bayi kapsamlı kırılma: {@code hataKodu} doluysa ekilmiş hata, boşsa kampanya kırılması. */
  public record Kirilma(String hataKodu) {

    /** {@code POST /test/break} gövdesi: açma ({@code acik}) ya da geri alma. */
    public String govde(String kullaniciAdi, boolean acik) {
      return hataKodu == null ? kampanyaGovdesi(kullaniciAdi, acik) : hataGovdesi(kullaniciAdi, acik ? hataKodu : null);
    }
  }

  static String kampanyaGovdesi(String kullaniciAdi, boolean acik) {
    return "{\"kullanici_adi\":" + jsonDize(kullaniciAdi) + ",\"kampanya\":" + acik + "}";
  }

  static String hataGovdesi(String kullaniciAdi, String kod) {
    return "{\"kullanici_adi\":" + jsonDize(kullaniciAdi) + ",\"hata\":" + (kod == null ? "null" : jsonDize(kod)) + "}";
  }

  /** Bu koşunun kırılmasını bayi için açar ya da geri alır. */
  public void kir(Kirilma kirilma, String kullaniciAdi, boolean acik) {
    testUcunuCagir("break", kirilma.govde(kullaniciAdi, acik));
  }

  private void testUcunuCagir(String yol, String govde) {
    String token =
        ayarlar.testToken().orElseThrow(() -> new IllegalStateException("/test/" + yol + " için DEMOAPP_TEST_TOKEN gerekir"));
    HttpRequest istek =
        HttpRequest.newBuilder(URI.create(testUcu(ayarlar.demoApiUrl(), yol)))
            .timeout(ZAMAN_ASIMI)
            .header("Content-Type", "application/json")
            .header(TOKEN_BASLIGI, token)
            .POST(HttpRequest.BodyPublishers.ofString(govde))
            .build();
    int durum = gonder(istek, "POST /test/" + yol).statusCode();
    if (durum / 100 != 2) {
      String ipucu =
          durum == 404
              ? " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok ya da demo.api.url web vekili ve /api/test/ yolunu açmıyor; DEMO_API_URL verin)"
              : "";
      throw new IllegalStateException("POST /test/" + yol + " başarısız: " + durum + ipucu);
    }
  }

  /** Token olmadan: bayinin sepetini herkese açık API ile boşaltır ve oturumu kapatır. */
  public void sepetiBosalt(Bayiler.BayiBilgisi bayi) {
    String api = ayarlar.demoApiUrl();
    String giris =
        "{\"kullanici_adi\":" + jsonDize(bayi.kullaniciAdi()) + ",\"parola\":" + jsonDize(bayi.parola()) + "}";
    durumBekle(
        HttpRequest.newBuilder(URI.create(api + "/auth/login"))
            .timeout(ZAMAN_ASIMI)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(giris))
            .build(),
        "sepet temizliği için giriş");
    HttpResponse<String> bosalt =
        durumBekle(
            HttpRequest.newBuilder(URI.create(api + "/cart")).timeout(ZAMAN_ASIMI).DELETE().build(), "sepet boşaltma");
    if (!bosalt.body().replace(" ", "").contains("\"satirlar\":[]")) {
      throw new IllegalStateException("sepet boşaltılamadı: yanıtta satırlar kaldı");
    }
    durumBekle(
        HttpRequest.newBuilder(URI.create(api + "/auth/logout"))
            .timeout(ZAMAN_ASIMI)
            .POST(HttpRequest.BodyPublishers.noBody())
            .build(),
        "çıkış");
  }

  private HttpResponse<String> durumBekle(HttpRequest istek, String ne) {
    HttpResponse<String> yanit = gonder(istek, ne);
    if (yanit.statusCode() / 100 != 2) {
      throw new IllegalStateException(ne + " başarısız: " + yanit.statusCode());
    }
    return yanit;
  }

  private HttpResponse<String> gonder(HttpRequest istek, String ne) {
    try {
      return istemci.send(istek, HttpResponse.BodyHandlers.ofString());
    } catch (IOException e) {
      throw new IllegalStateException(ne + ": demo API'ye ulaşılamadı (" + istek.uri().getHost() + ")", e);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException(ne + " kesildi", e);
    }
  }
}

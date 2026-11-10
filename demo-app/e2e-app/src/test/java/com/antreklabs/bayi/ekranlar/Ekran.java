package com.antreklabs.bayi.ekranlar;

import com.antreklabs.bayi.altyapi.Bekle;
import com.antreklabs.bayi.altyapi.Kaydirma;
import com.antreklabs.bayi.altyapi.Kimlik;
import com.antreklabs.bayi.altyapi.Klavye;
import com.antreklabs.bayi.altyapi.UygulamaOturumu;
import io.appium.java_client.AppiumDriver;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import org.openqa.selenium.By;
import org.openqa.selenium.SearchContext;
import org.openqa.selenium.WebDriverException;
import org.openqa.selenium.WebElement;

/**
 * Ekran nesnelerinin tabanı: platformdan bağımsız, kimlik sabitleriyle çalışan yardımcılar.
 *
 * <p>Sözleşme (plan §2.8): alt sınıfların {@code public} metotları sembol tablosuna girer — eylem
 * (fiil, {@code void}) ya da beklenti ({@code dogrula} ön eki, {@code void}); parametreler yalnız
 * {@code String}, {@code int}, {@code long}, {@code double}, {@code boolean}. Bu sınıfın yardımcıları
 * bilerek {@code protected}'dır, sembol tablosuna girmez.
 *
 * <p>Hata türleri: eylem ön koşulu sağlanmazsa (öğe yok, tıklanamıyor) {@code TimeoutException};
 * beklenti sağlanmazsa {@link AssertionError}. Metin karşılaştırması web'deki {@code toHaveText}
 * gibi boşlukları sadeleştirir (NBSP dahil).
 */
public abstract class Ekran {

  private static final String YOK = "(öğe yok)";
  private static final String[] METIN_NITELIKLERI = {"label", "value", "Name", "content-desc", "text"};

  private final UygulamaOturumu oturum;

  protected Ekran(UygulamaOturumu oturum) {
    this.oturum = oturum;
  }

  protected final UygulamaOturumu oturum() {
    return oturum;
  }

  protected final AppiumDriver surucu() {
    return oturum.surucu();
  }

  protected final Bekle bekle() {
    return oturum.bekle();
  }

  /** Kimliğin etkin platformdaki seçicisi. */
  protected final By bul(String kimlik) {
    return Kimlik.bul(kimlik);
  }

  // ------------------------------------------------------------------ bulma

  private WebElement ilkGorunur(String kapsayici, String kimlik) {
    List<SearchContext> kokler = new ArrayList<>();
    if (kapsayici == null) {
      kokler.add(surucu());
    } else {
      kokler.addAll(surucu().findElements(bul(kapsayici)));
    }
    for (SearchContext kok : kokler) {
      for (WebElement e : kok.findElements(bul(kimlik))) {
        if (e.isDisplayed()) {
          return e;
        }
      }
    }
    return null;
  }

  /** Öğeyi beklemeden bir kez arar (gerekirse bir kez kaydırır); görünür değilse null. */
  protected final WebElement hemenBul(String kapsayici, String kimlik) {
    WebElement e = ilkGorunur(kapsayici, kimlik);
    if (e != null) {
      return e;
    }
    Kaydirma.getir(surucu(), kapsayici, kimlik);
    return ilkGorunur(kapsayici, kimlik);
  }

  private static String ad(String kapsayici, String kimlik) {
    return kapsayici == null ? "'" + kimlik + "'" : "'" + kapsayici + "' içinde '" + kimlik + "'";
  }

  /** Öğe görünür olana kadar (gerekirse kaydırarak) bekler; olmazsa TimeoutException. */
  protected final WebElement gorunurBekle(String kimlik) {
    return gorunurBekle(null, kimlik);
  }

  /** Kapsayıcı (ör. ürün kartı) içindeki öğe görünür olana kadar bekler. */
  protected final WebElement gorunurBekle(String kapsayici, String kimlik) {
    return bekle().kosul("öğe görünmedi: kimlik " + ad(kapsayici, kimlik), s -> hemenBul(kapsayici, kimlik));
  }

  /** İki öğeden biri görünene kadar bekler (web: {@code expect(a.or(b)).toBeVisible()}). */
  protected final void biriGorunurBekle(String kimlik1, String kimlik2) {
    bekle()
        .kosul(
            "öğe görünmedi: kimlik '" + kimlik1 + "' ya da '" + kimlik2 + "'",
            s -> ilkGorunur(null, kimlik1) != null || ilkGorunur(null, kimlik2) != null ? Boolean.TRUE : null);
  }

  /** Öğe ekranda (ya da kaydırılabilir alanda) var mı; beklemez. */
  private boolean var(String kimlik) {
    return hemenBul(null, kimlik) != null;
  }

  // ------------------------------------------------------------------ eylemler

  /** Öğeye dokunur (görünür ve etkin olmasını bekler). */
  protected final void dokun(String kimlik) {
    dokun(null, kimlik);
  }

  /** Kapsayıcı içindeki öğeye dokunur. */
  protected final void dokun(String kapsayici, String kimlik) {
    WebElement e =
        bekle()
            .kosul(
                "öğe tıklanabilir olmadı: kimlik " + ad(kapsayici, kimlik),
                s -> {
                  WebElement g = hemenBul(kapsayici, kimlik);
                  return g != null && g.isEnabled() ? g : null;
                });
    e.click();
  }

  /** Alana metin yazar (önce temizler), sonra ekran klavyesini kapatır. */
  protected final void yaz(String kimlik, String metin) {
    WebElement e = gorunurBekle(kimlik);
    e.clear();
    e.sendKeys(metin);
    Klavye.kapat(surucu());
  }

  // ------------------------------------------------------------------ metin

  /** Boşlukları sadeleştirir: NBSP / dar NBSP → boşluk, ardışık boşluk → tek, baş/son kırpılır. */
  protected static String sade(String s) {
    return s == null ? "" : s.replace(' ', ' ').replace(' ', ' ').replaceAll("\\s+", " ").trim();
  }

  private static String kendiMetni(WebElement e) {
    String t = e.getText();
    if (t != null && !t.isBlank()) {
      return sade(t);
    }
    for (String nitelik : METIN_NITELIKLERI) {
      try {
        String v = e.getAttribute(nitelik);
        if (v != null && !v.isBlank() && !"null".equals(v)) {
          return sade(v);
        }
      } catch (WebDriverException ignored) {
        // nitelik bu platformda yok
      }
    }
    return "";
  }

  /**
   * Öğenin görünen metni: kendi metni, yoksa alt öğelerin metinleri (RN'de testID bir View'daysa
   * metin alt Text öğesindedir).
   */
  protected final String metin(WebElement e) {
    String kendi = kendiMetni(e);
    return kendi.isEmpty() ? altMetinler(e) : kendi;
  }

  /** Öğenin ve tüm alt öğelerinin metinleri, boşlukla birleşik (web: {@code toContainText} kapsamı). */
  protected final String tumMetin(WebElement e) {
    String kendi = kendiMetni(e);
    String alt = altMetinler(e);
    return sade(kendi + " " + alt);
  }

  private String altMetinler(WebElement e) {
    List<String> parcalar = new ArrayList<>();
    for (WebElement alt : e.findElements(By.xpath(".//*"))) {
      String t = kendiMetni(alt);
      if (!t.isEmpty() && !parcalar.contains(t)) {
        parcalar.add(t);
      }
    }
    return sade(String.join(" ", parcalar));
  }

  private String gorulenMetin(String kapsayici, String kimlik, boolean tum) {
    WebElement e = hemenBul(kapsayici, kimlik);
    if (e == null) {
      return YOK;
    }
    return tum ? tumMetin(e) : metin(e);
  }

  // ------------------------------------------------------------------ beklentiler (AssertionError)

  /** Öğenin metni tam olarak beklenen (sadeleştirilmiş) olmalı. */
  protected final void metinOlmali(String kimlik, String beklenen) {
    String b = sade(beklenen);
    bekle()
        .dogrula(
            "'" + kimlik + "' metni",
            b,
            () -> gorulenMetin(null, kimlik, false),
            () -> b.equals(gorulenMetin(null, kimlik, false)));
  }

  /** Öğenin metni kalıba tam uymalı. */
  protected final void metinKalibinaUymali(String kimlik, Pattern kalip) {
    bekle()
        .dogrula(
            "'" + kimlik + "' metni",
            "/" + kalip.pattern() + "/",
            () -> gorulenMetin(null, kimlik, false),
            () -> kalip.matcher(gorulenMetin(null, kimlik, false)).matches());
  }

  /** Öğenin metni beklenen parçayı içermeli. */
  protected final void metinIcermeli(String kimlik, String parca) {
    String p = sade(parca);
    bekle()
        .dogrula(
            "'" + kimlik + "' metni",
            "… " + p + " …",
            () -> gorulenMetin(null, kimlik, false),
            () -> gorulenMetin(null, kimlik, false).contains(p));
  }

  /** Öğe ve alt öğelerinin metni beklenen parçayı içermeli (ör. ürün kartında kampanya adı). */
  protected final void tumMetinIcermeli(String kimlik, String parca) {
    String p = sade(parca);
    bekle()
        .dogrula(
            "'" + kimlik + "' içeriği",
            "… " + p + " …",
            () -> gorulenMetin(null, kimlik, true),
            () -> gorulenMetin(null, kimlik, true).contains(p));
  }

  /** Öğe görünür olmalı. */
  protected final void gorunurOlmali(String kimlik) {
    bekle().dogrula("'" + kimlik + "' görünürlüğü", "görünür", () -> YOK, () -> hemenBul(null, kimlik) != null);
  }

  /** Öğe ekranda olmamalı (web: {@code toHaveCount(0)}); kaydırılabilir alanın tamamına bakılır. */
  protected final void yokOlmali(String kimlik) {
    bekle().dogrula("'" + kimlik + "' yokluğu", YOK, () -> "görünür", () -> !var(kimlik));
  }

  /** Öğe etkin (true) ya da pasif (false) olmalı. */
  protected final void etkinOlmali(String kimlik, boolean etkin) {
    String beklenen = etkin ? "etkin" : "pasif";
    bekle()
        .dogrula(
            "'" + kimlik + "' durumu",
            beklenen,
            () -> {
              WebElement e = hemenBul(null, kimlik);
              return e == null ? YOK : e.isEnabled() ? "etkin" : "pasif";
            },
            () -> {
              WebElement e = hemenBul(null, kimlik);
              return e != null && e.isEnabled() == etkin;
            });
  }
}

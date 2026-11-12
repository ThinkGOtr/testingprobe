package com.antreklabs.bayi.ekranlar;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.microsoft.playwright.Locator;
import com.microsoft.playwright.Page;
import java.util.regex.Pattern;

/**
 * Page object'lerin tabanı (TypeScript: {@code ../e2e/pages/support.ts}).
 *
 * <p>Sözleşme (009 plan §2.8, 011 plan §2.5): page object {@code ekranlar/} altında bu sınıftan
 * türer; sınıf adı, {@code public} metot adları, parametre adları ve sırası TypeScript page
 * object'iyle birebir aynıdır ({@code LoginPage.login(username, password)}). Metotlar {@code void}
 * döner; parametreler yalnızca {@code String/int/long/double/boolean}. Elemanlar yalnızca
 * {@link Kimlikler} sabitleriyle (data-testid) bulunur; beklentiler Playwright'ın kendiliğinden
 * yeniden deneyen doğrulamalarıdır ({@code assertThat}), sabit bekleme yoktur.
 *
 * <p>Tek ad farkı: TS metot adı Java ayrılmış sözcüğüyse Java adı sabit bir tablodan gelir
 * (011 koordinatör kararı; core: {@code tp_core.features.codegen.platform.JAVA_AD_ESLEME}). Bugün
 * tek giriş: {@code goto} → {@code goTo}.
 */
public abstract class Ekran {

  /** Sayfa yolları (TypeScript: {@code paths}). */
  protected static final String LOGIN_YOLU = "/giris";
  protected static final String CATALOG_YOLU = "/katalog";
  protected static final String CART_YOLU = "/sepet";
  protected static final String ORDERS_YOLU = "/siparisler";

  /** Sayfa (alt sınıflar doğrudan kullanır; TypeScript: {@code this.page}). */
  protected final Page page;

  protected Ekran(Page page) {
    if (page == null) {
      throw new IllegalArgumentException("page boş olamaz");
    }
    this.page = page;
  }

  /**
   * Kimliğin data-testid değeri (TypeScript: {@code testIdOf}). Önek kimliklerde (sonu {@code -})
   * sonek zorunludur; sabit kimliklerde sonek verilmez.
   */
  public static String kimlikDegeri(String kimlik, String sonek) {
    boolean onek = kimlik.endsWith("-");
    boolean sonekVar = sonek != null && !sonek.isEmpty();
    if (onek && !sonekVar) {
      throw new IllegalArgumentException("'" + kimlik + "' önek kimliği için sonek (ürün kodu / sipariş no) gerekli");
    }
    if (!onek && sonekVar) {
      throw new IllegalArgumentException("'" + kimlik + "' sabit kimliktir; sonek verilmemeli");
    }
    return onek ? kimlik + sonek : kimlik;
  }

  /** Sabit kimlikli eleman ({@code getByTestId}). */
  protected final Locator kimlik(String kimlik) {
    return page.getByTestId(kimlikDegeri(kimlik, null));
  }

  /** Önek kimlikli eleman: {@code onek + sonek} (ör. "product-price-" + "P-001"). */
  protected final Locator kimlik(String onek, String sonek) {
    return page.getByTestId(kimlikDegeri(onek, sonek));
  }

  /**
   * Kapsayıcı eleman (TypeScript: {@code within} + {@code scopeTestIdOf}): kapsamlı kimlikler bunun
   * içinde aranır — {@code kapsam(Catalog.PRODUCT_CARD_ONEK, "P-001").getByTestId(...)}.
   */
  protected final Locator kapsam(String kapsamOneki, String sonek) {
    if (!kapsamOneki.endsWith("-")) {
      throw new IllegalArgumentException("'" + kapsamOneki + "' kapsam öneki '-' ile bitmeli");
    }
    return page.getByTestId(kimlikDegeri(kapsamOneki, sonek));
  }

  /** Kapsayıcının içindeki eleman; önek kimlikse aynı sonek eklenir. */
  protected final Locator kapsamda(Locator kapsayici, String kimlik, String sonek) {
    return kapsayici.getByTestId(kimlikDegeri(kimlik, kimlik.endsWith("-") ? sonek : null));
  }

  /** Yola gider (bağlamın {@code baseURL}'ine göre). */
  protected final void git(String yol) {
    page.navigate(yol);
  }

  /**
   * Adresin verilen yolla bittiğini doğrular (yeniden denemeli). Desen tarayıcıda (JavaScript
   * RegExp) değerlendirilir: Java'ya özgü {@code Pattern.quote} ({@code \\Q…\\E}) kullanılamaz,
   * özel karakterler tek tek kaçırılır.
   */
  protected final void dogrulaYol(String yol) {
    assertThat(page).hasURL(Pattern.compile(yol.replaceAll("[\\\\^$.|?*+()\\[\\]{}]", "\\\\$0") + "$"));
  }
}

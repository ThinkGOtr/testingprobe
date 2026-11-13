package com.antreklabs.bayi.testler;

import static org.testng.Assert.assertEquals;

import com.antreklabs.bayi.altyapi.TestTabani;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.testng.annotations.Test;

/** Bayi girişi (TPD-4) — TypeScript: tests/login.spec.ts. */
public class GirisTest extends TestTabani {

  @Test(groups = {"duman"}, description = "doğru bilgilerle giriş yapılır ve katalog açılır")
  public void dogruBilgilerleGiris() {
    loginPage().goTo();
    loginPage().login(dealer().kullaniciAdi(), dealer().parola());
    loginPage().expectLoggedIn(dealer().ad());
    catalogPage().expectProductVisible("P-001");
  }

  @Test(groups = {"duman"}, description = "hatalı parolada hata mesajı gösterilir")
  public void hataliParola() {
    loginPage().goTo();
    loginPage().login(dealer().kullaniciAdi(), "YanlisParola1");
    loginPage().expectLoginError("Kullanıcı adı veya parola hatalı");
    loginPage().expectOnLoginPage();
  }

  @Test(description = "oturumsuz kullanıcı giriş sayfasına yönlendirilir")
  public void oturumsuzYonlendirme() {
    page().navigate("/sepet");
    loginPage().expectOnLoginPage();
  }

  /**
   * Ajanın "Ham çıktı"sında "Console: N errors" görünmesin: oturumsuz açılış yoklaması ve giriş
   * akışı tarayıcı konsoluna hata düşürmemeli.
   */
  @Test(description = "oturumsuz açılış ve giriş konsola hata yazmaz")
  public void konsolaHataYazilmaz() {
    List<String> hatalar = Collections.synchronizedList(new ArrayList<>());
    page().onConsoleMessage(m -> {
      if ("error".equals(m.type())) {
        hatalar.add(m.text());
      }
    });
    page().onPageError(hatalar::add);
    loginPage().goTo();
    loginPage().expectOnLoginPage();
    loginPage().login(dealer().kullaniciAdi(), dealer().parola());
    loginPage().expectLoggedIn(dealer().ad());
    catalogPage().expectProductVisible("P-001");
    assertEquals(new ArrayList<>(hatalar), List.of());
  }
}

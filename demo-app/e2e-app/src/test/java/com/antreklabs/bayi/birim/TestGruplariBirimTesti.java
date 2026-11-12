package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.TestGruplari;
import java.util.List;
import java.util.Map;
import org.testng.annotations.Test;

/** TestNG gruplarının Extent kategorisi ve Allure etiketi karşılıkları. */
public class TestGruplariBirimTesti {

  private static final String UUID = "3f9b1c2e-0000-5000-8000-0000000000c2";
  /** Üretilen testin grupları (Java web şablonu). */
  private static final String[] URETILEN = {"uretilen", "web", "tp-case-" + UUID, "TPD-1"};

  @Test(groups = "birim")
  public void caseGrubuKategoriOlmaz() {
    assertEquals(TestGruplari.kategoriler(URETILEN), List.of("uretilen", "web", "TPD-1"));
    assertEquals(TestGruplari.caseler(URETILEN), List.of(UUID));
    assertEquals(TestGruplari.kategoriler(null), List.of());
    assertEquals(TestGruplari.kategoriler(new String[] {"duman", "duman", " "}), List.of("duman"));
    assertFalse(TestGruplari.caseGrubu("tp-case-"), "kimliksiz önek case değildir");
  }

  @Test(groups = "birim")
  public void storyJiraAnahtaridir() {
    assertTrue(TestGruplari.storyGrubu("TPD-1"));
    assertTrue(TestGruplari.storyGrubu("AB2_C-120"));
    assertFalse(TestGruplari.storyGrubu("tp-case-1"));
    assertFalse(TestGruplari.storyGrubu("sifir-veri"));
    assertFalse(TestGruplari.storyGrubu("TPD-"));
  }

  @Test(groups = "birim")
  public void allureEtiketleri() {
    assertEquals(
        TestGruplari.allureEtiketleri(URETILEN),
        List.of(
            Map.entry("tag", "uretilen"),
            Map.entry("tag", "web"),
            Map.entry("tag", "tp-case-" + UUID),
            Map.entry(TestGruplari.CASE_ETIKETI, UUID),
            Map.entry("tag", "TPD-1"),
            Map.entry("story", "TPD-1")));
    assertEquals(TestGruplari.allureEtiketleri(new String[] {"duman"}), List.of(Map.entry("tag", "duman")));
    // QA-Y5: elle yazılmış testin Jira biçimli grubu story değildir (yalnız uretilen grubunda).
    assertEquals(
        TestGruplari.allureEtiketleri(new String[] {"kampanya", "TPD-1"}),
        List.of(Map.entry("tag", "kampanya"), Map.entry("tag", "TPD-1")));
    assertEquals(TestGruplari.allureEtiketleri(null), List.of());
  }

  @Test(groups = "birim")
  public void allureTestDisindaHataVermez() {
    // Koşan Allure testi yokken (ör. iç içe koşu) etiket eklemek testi düşürmez.
    TestGruplari.allureyeEkle(URETILEN);
  }
}

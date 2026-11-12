package com.antreklabs.bayi.altyapi;

import io.qameta.allure.Allure;
import java.util.AbstractMap.SimpleImmutableEntry;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.regex.Pattern;

/**
 * TestNG gruplarının rapor karşılıkları (Extent ve Allure için tek kaynak).
 *
 * <p>Testing Probe'un ürettiği testler kimliklerini gruplarda taşır (guard kuralı; üretilen dosyaya
 * notasyon eklenmez): {@code tp-case-<uuid>} (onaylı case) ve Jira story anahtarı ({@code TPD-1}).
 * Elle yazılmış testlerin grupları ({@code duman}, {@code kampanya} …) olduğu gibi kalır.
 *
 * <ul>
 *   <li><b>Extent:</b> kategori = {@code tp-case-*} dışındaki gruplar (her case ayrı kategori
 *       olmasın); case kimliği test ayrıntısında ayrı bir satırdır ({@link ExtentRaporu}).
 *   <li><b>Allure:</b> her grup {@code tag}; Jira anahtarı biçimindeki grup — yalnız
 *       {@value #URETILEN} grubundaki (Testing Probe'un ürettiği) testte — {@code story}; elle
 *       yazılmış testin {@code ABC-1} biçimli grubu yalnız {@code tag}'dir. {@code tp-case-<uuid>}
 *       ayrıca {@code tp-case=<uuid>} etiketi ({@link #allureyeEkle}).
 * </ul>
 */
public final class TestGruplari {

  /** Onaylı case grubunun öneki (üretilen testler: {@code tp-case-<uuid>}). */
  public static final String CASE_ONEK = "tp-case-";
  /** Allure'da case kimliğinin etiket adı (makine okunur; değer yalnız uuid). */
  public static final String CASE_ETIKETI = "tp-case";
  /** Testing Probe'un ürettiği testlerin grubu; story etiketi yalnız bu gruptaki testlere verilir. */
  public static final String URETILEN = "uretilen";

  /** Jira anahtarı (story): {@code PROJE-123}. */
  private static final Pattern JIRA_ANAHTARI = Pattern.compile("[A-Z][A-Z0-9_]*-[0-9]+");

  private static final Logger LOG = Logger.getLogger(TestGruplari.class.getName());

  private TestGruplari() {}

  /** {@code tp-case-<uuid>} grubu mu. */
  public static boolean caseGrubu(String grup) {
    return grup != null && grup.startsWith(CASE_ONEK) && grup.length() > CASE_ONEK.length();
  }

  /** Jira anahtarı biçimindeki (story) grup mu. */
  public static boolean storyGrubu(String grup) {
    return grup != null && JIRA_ANAHTARI.matcher(grup).matches();
  }

  /** Extent kategorileri: {@code tp-case-*} dışındaki gruplar (sıra korunur, boşlar atlanır). */
  public static List<String> kategoriler(String[] gruplar) {
    List<String> out = new ArrayList<>();
    if (gruplar != null) {
      for (String g : gruplar) {
        if (g != null && !g.isBlank() && !caseGrubu(g) && !out.contains(g)) {
          out.add(g);
        }
      }
    }
    return out;
  }

  /** Case kimlikleri ({@code tp-case-} öneki olmadan). */
  public static List<String> caseler(String[] gruplar) {
    List<String> out = new ArrayList<>();
    if (gruplar != null) {
      for (String g : gruplar) {
        if (caseGrubu(g) && !out.contains(g.substring(CASE_ONEK.length()))) {
          out.add(g.substring(CASE_ONEK.length()));
        }
      }
    }
    return out;
  }

  /**
   * Allure etiketleri (ad, değer): her grup {@code tag}; üretilen testte Jira anahtarı
   * {@code story}; case {@code tp-case}=uuid.
   */
  public static List<Map.Entry<String, String>> allureEtiketleri(String[] gruplar) {
    List<Map.Entry<String, String>> out = new ArrayList<>();
    if (gruplar == null) {
      return out;
    }
    boolean uretilen = Arrays.asList(gruplar).contains(URETILEN);
    for (String g : gruplar) {
      if (g == null || g.isBlank()) {
        continue;
      }
      ekle(out, "tag", g);
      if (uretilen && storyGrubu(g)) {
        ekle(out, "story", g);
      }
      if (caseGrubu(g)) {
        ekle(out, CASE_ETIKETI, g.substring(CASE_ONEK.length()));
      }
    }
    return out;
  }

  private static void ekle(List<Map.Entry<String, String>> out, String ad, String deger) {
    Map.Entry<String, String> e = new SimpleImmutableEntry<>(ad, deger);
    if (!out.contains(e)) {
      out.add(e);
    }
  }

  /**
   * Etiketleri o anki Allure test sonucuna ekler (TestNG {@code onTestStart} sonrası, test iş
   * parçacığında çağrılır). Raporlama hatası testi düşürmez.
   */
  public static void allureyeEkle(String[] gruplar) {
    try {
      for (Map.Entry<String, String> e : allureEtiketleri(gruplar)) {
        Allure.label(e.getKey(), e.getValue());
      }
    } catch (RuntimeException | LinkageError e) {
      LOG.log(Level.WARNING, "Allure etiketleri eklenemedi", e);
    }
  }
}

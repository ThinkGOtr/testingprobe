import java.io.File;
import java.util.ArrayList;
import java.util.List;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

/**
 * "Kırarak doğrula" kırmızı adımının denetimi (ci/break-verify-app.sh; AI yok). Tek dosyalık Java
 * kaynağı olarak koşar, bağımlılığı yoktur: {@code java araclar/KirmiziDenetimi.java <rapor-dizini>}.
 *
 * <p>Surefire JUnit XML'lerinde (TEST-*.xml) kırmızı testlerin HEPSİ doğrulama (assertion) hatası
 * olmalı: {@code <failure type="java.lang.AssertionError">}. Kurulum hatası ({@code /test/*} çağrısı,
 * Appium oturumu, giriş), locator hatası (TimeoutException), {@code <error>} ya da atlanan test
 * kırmızı sayılmaz. En az bir kırmızı test olmalı.
 *
 * <p>Çıkış kodu: 0 geçti, 1 denetim başarısız, 2 kullanım / rapor yok.
 */
public final class KirmiziDenetimi {

  private static final String ASSERTION = "java.lang.AssertionError";
  /** Assertion türünde olsa da kurulum kaynaklı sayılan mesajlar (web betiğindeki süzgeç). */
  private static final String KURULUM = "(?s).*(/test/|giriş başarısız|DEMOAPP_TEST_TOKEN).*";

  private KirmiziDenetimi() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 1) {
      System.err.println("kullanım: java KirmiziDenetimi.java <surefire-rapor-dizini>");
      System.exit(2);
    }
    File[] dosyalar = new File(args[0]).listFiles((d, ad) -> ad.startsWith("TEST-") && ad.endsWith(".xml"));
    if (dosyalar == null || dosyalar.length == 0) {
      System.err.println("HATA: JUnit XML yok: " + args[0]);
      System.exit(2);
    }
    DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
    f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
    f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
    DocumentBuilder b = f.newDocumentBuilder();

    List<String> kirmizi = new ArrayList<>();
    List<String> yesil = new ArrayList<>();
    List<String> kotu = new ArrayList<>();
    for (File dosya : dosyalar) {
      NodeList satirlar = b.parse(dosya).getElementsByTagName("testcase");
      for (int i = 0; i < satirlar.getLength(); i++) {
        Element tc = (Element) satirlar.item(i);
        String ad = tc.getAttribute("classname").replaceFirst(".*\\.", "") + "." + tc.getAttribute("name");
        Element sonuc = ilkAlt(tc);
        if (sonuc == null) {
          yesil.add(ad);
          continue;
        }
        String etiket = sonuc.getTagName();
        String tur = sonuc.getAttribute("type");
        String mesaj = sonuc.getAttribute("message");
        if (etiket.equals("failure") && ASSERTION.equals(tur) && !mesaj.matches(KURULUM)) {
          kirmizi.add(ad);
        } else {
          kotu.add(ad + " [" + etiket + (tur.isEmpty() ? "" : " " + tur) + "] " + ilkSatir(mesaj));
        }
      }
    }
    System.out.println("kırmızı: " + String.join(" | ", kirmizi));
    System.out.println("yeşil kalan: " + String.join(" | ", yesil));
    if (!kotu.isEmpty()) {
      for (String k : kotu) {
        System.err.println("  ✗ " + k);
      }
      System.err.println("HATA: " + kotu.size() + " sonuç doğrulama (assertion) hatası değil (kurulum/locator hatası ya da atlandı)");
      System.exit(1);
    }
    if (kirmizi.isEmpty()) {
      System.err.println("HATA: kırmızı test yok — testler kuralı yakalamıyor");
      System.exit(1);
    }
  }

  private static Element ilkAlt(Element tc) {
    for (Node n = tc.getFirstChild(); n != null; n = n.getNextSibling()) {
      if (n instanceof Element) {
        String t = ((Element) n).getTagName();
        if (t.equals("failure") || t.equals("error") || t.equals("skipped")) {
          return (Element) n;
        }
      }
    }
    return null;
  }

  private static String ilkSatir(String s) {
    int i = s.indexOf('\n');
    return i < 0 ? s : s.substring(0, i);
  }
}

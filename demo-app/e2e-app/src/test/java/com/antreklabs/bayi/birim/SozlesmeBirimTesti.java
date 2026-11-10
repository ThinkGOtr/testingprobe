package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertTrue;
import static org.testng.Assert.fail;

import com.antreklabs.bayi.altyapi.TestTabani;
import com.antreklabs.bayi.ekranlar.Ekran;
import com.antreklabs.bayi.ekranlar.Kimlikler;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.testng.annotations.Test;

/**
 * Plan §2.8 Java biçim sözleşmesinin yerel kilidi (asıl denetim: toolchain/java-araclar).
 * Kimlikler saf veridir ve web data-testid'leriyle birebir aynıdır; ekran nesnesi metotları
 * sözleşmeye uyar; TestTabani her ekran için erişimci sağlar; altın üretilen test biçimdedir.
 */
public class SozlesmeBirimTesti {

  private static final Path KOK = Path.of("src/test/java/com/antreklabs/bayi");
  private static final Path WEB_SRC = Path.of("../web/src");
  private static final Set<Class<?>> IZINLI_PARAMETRE =
      Set.of(String.class, int.class, long.class, double.class, boolean.class);

  /** Kimlikler: alt sınıf adı + sabit adı → değer. */
  static TreeMap<String, String> kimlikler() throws IllegalAccessException {
    TreeMap<String, String> m = new TreeMap<>();
    for (Class<?> c : Kimlikler.class.getDeclaredClasses()) {
      for (Field f : c.getDeclaredFields()) {
        m.put(c.getSimpleName() + "." + f.getName(), (String) f.get(null));
      }
    }
    return m;
  }

  static List<Class<?>> ekranSiniflari() throws IOException {
    try (Stream<Path> s = Files.list(KOK.resolve("ekranlar"))) {
      List<Class<?>> l = new ArrayList<>();
      for (Path p : s.filter(p -> p.getFileName().toString().endsWith("Ekrani.java")).sorted().collect(Collectors.toList())) {
        String ad = p.getFileName().toString().replace(".java", "");
        try {
          l.add(Class.forName("com.antreklabs.bayi.ekranlar." + ad));
        } catch (ClassNotFoundException e) {
          fail("ekran sınıfı yüklenemedi: " + ad);
        }
      }
      return l;
    }
  }

  @Test(groups = "birim")
  public void kimliklerSafVeri() {
    int ust = Kimlikler.class.getModifiers();
    assertTrue(Modifier.isPublic(ust) && Modifier.isFinal(ust));
    for (Method m : Kimlikler.class.getDeclaredMethods()) {
      fail("Kimlikler metot içeremez: " + m.getName());
    }
    for (Field f : Kimlikler.class.getDeclaredFields()) {
      fail("Kimlikler üst düzeyde alan içeremez: " + f.getName());
    }
    for (Class<?> c : Kimlikler.class.getDeclaredClasses()) {
      int mod = c.getModifiers();
      assertTrue(Modifier.isPublic(mod) && Modifier.isStatic(mod) && Modifier.isFinal(mod), c + " public static final olmalı");
      assertEquals(c.getDeclaredMethods().length, 0, c + " metot içeremez");
      assertEquals(c.getDeclaredClasses().length, 0, c + " iç içe en çok bir düzey");
      for (Field f : c.getDeclaredFields()) {
        int fm = f.getModifiers();
        assertTrue(
            Modifier.isPublic(fm) && Modifier.isStatic(fm) && Modifier.isFinal(fm) && f.getType() == String.class,
            c.getSimpleName() + "." + f.getName() + " public static final String olmalı");
        assertTrue(f.getName().matches("[A-Z][A-Z0-9_]*"), f.getName() + " SABIT_ADI biçiminde olmalı");
      }
    }
  }

  @Test(groups = "birim")
  public void onekAdlandirmasi() throws IllegalAccessException {
    kimlikler()
        .forEach(
            (ad, deger) ->
                assertEquals(
                    ad.endsWith("_ONEK"), deger.endsWith("-"), ad + " = \"" + deger + "\": _ONEK ⇔ değer '-' ile biter"));
  }

  /** Web kaynağındaki data-testid değerleri; şablon dizeleri önek olarak ("product-card-"). */
  static Set<String> webTestIdleri() throws IOException {
    Pattern sabit = Pattern.compile("data-testid=\"([^\"]+)\"");
    Pattern sablon = Pattern.compile("data-testid=\\{`([^`$]+)\\$\\{");
    Set<String> idler = new TreeSet<>();
    try (Stream<Path> s = Files.walk(WEB_SRC)) {
      for (Path p : s.filter(p -> p.toString().endsWith(".tsx")).collect(Collectors.toList())) {
        String metin = Files.readString(p, StandardCharsets.UTF_8);
        for (Pattern k : List.of(sabit, sablon)) {
          Matcher m = k.matcher(metin);
          while (m.find()) {
            idler.add(m.group(1));
          }
        }
      }
    }
    return idler;
  }

  @Test(groups = "birim")
  public void kimliklerWebDataTestidleriyleBirebir() throws IOException, IllegalAccessException {
    if (!Files.isDirectory(WEB_SRC)) {
      fail("web kaynağı bulunamadı: " + WEB_SRC.toAbsolutePath() + " (testler demo-app/e2e-app dizininden koşar)");
    }
    Set<String> web = webTestIdleri();
    Set<String> java = new TreeSet<>(kimlikler().values());
    assertEquals(java.size(), kimlikler().size(), "Kimlikler değerleri tekil olmalı");
    assertEquals(java, web, "Kimlikler.java ile web data-testid kümesi aynı olmalı (plan §2.2)");
  }

  @Test(groups = "birim")
  public void kimliklerJsonVarsaUyumlu() throws IOException, IllegalAccessException {
    // Tek liste demo-app/kimlikler.json (Ş1 üretir); varsa her Java değeri orada bulunmalı.
    Path json = Path.of("../kimlikler.json");
    if (!Files.exists(json)) {
      return;
    }
    String metin = Files.readString(json, StandardCharsets.UTF_8);
    for (String deger : kimlikler().values()) {
      assertTrue(metin.contains("\"" + deger + "\""), "kimlikler.json'da yok: " + deger);
    }
  }

  @Test(groups = "birim")
  public void ekranMetotlariSozlesmeye() throws IOException {
    List<Class<?>> ekranlar = ekranSiniflari();
    assertEquals(
        ekranlar.stream().map(Class::getSimpleName).collect(Collectors.toList()),
        List.of("GirisEkrani", "KatalogEkrani", "OnayEkrani", "SepetEkrani", "SiparisEkrani"));
    for (Class<?> c : ekranlar) {
      assertEquals(c.getSuperclass(), Ekran.class, c + " Ekran'dan türemeli");
      int sayac = 0;
      for (Method m : c.getDeclaredMethods()) {
        if (!Modifier.isPublic(m.getModifiers()) || Modifier.isStatic(m.getModifiers()) || m.isSynthetic()) {
          continue;
        }
        sayac++;
        String ad = c.getSimpleName() + "." + m.getName();
        assertEquals(m.getReturnType(), void.class, ad + " void olmalı");
        assertTrue(Character.isLowerCase(m.getName().charAt(0)), ad + " lowerCamel olmalı");
        for (Class<?> p : m.getParameterTypes()) {
          assertTrue(IZINLI_PARAMETRE.contains(p), ad + " parametre türü izinli değil: " + p);
        }
      }
      assertTrue(sayac > 0, c + " en az bir public metot");
    }
    // Taban sınıfın public metodu olmamalı (sembol tablosuna kalıtımla sızmasın).
    for (Method m : Ekran.class.getDeclaredMethods()) {
      assertTrue(!Modifier.isPublic(m.getModifiers()), "Ekran." + m.getName() + " public olmamalı");
    }
  }

  @Test(groups = "birim")
  public void testTabaniHerEkranIcinErisimci() throws IOException, NoSuchMethodException {
    for (Class<?> c : ekranSiniflari()) {
      String ad = Character.toLowerCase(c.getSimpleName().charAt(0)) + c.getSimpleName().substring(1);
      Method m = TestTabani.class.getDeclaredMethod(ad);
      assertEquals(m.getReturnType(), c, ad + "() dönüş türü");
      assertEquals(m.getParameterCount(), 0);
      assertTrue(Modifier.isProtected(m.getModifiers()) || Modifier.isPublic(m.getModifiers()), ad + "() alt sınıftan erişilmeli");
    }
  }

  @Test(groups = "birim")
  public void uretilenAltinOrnekBicimde() throws IOException {
    List<Path> dosyalar;
    try (Stream<Path> s = Files.list(KOK.resolve("uretilen"))) {
      dosyalar = s.filter(p -> p.getFileName().toString().endsWith("Test.java")).collect(Collectors.toList());
    }
    assertTrue(!dosyalar.isEmpty(), "uretilen/ altında altın örnek yok");
    Pattern adKalibi = Pattern.compile("[A-Z][A-Z0-9]*C\\d+_[0-9a-f]{8}Test\\.java");
    Pattern cagri = Pattern.compile("\\s{4}[a-z][A-Za-z]*Ekrani\\(\\)\\.[a-z][A-Za-z]*\\((\"([^\"\\\\]|\\\\.)*\"|-?\\d+(\\.\\d+)?L?|true|false|, )*\\);");
    for (Path p : dosyalar) {
      assertTrue(adKalibi.matcher(p.getFileName().toString()).matches(), "dosya adı: " + p.getFileName());
      List<String> satirlar = Files.readAllLines(p, StandardCharsets.UTF_8);
      List<String> importlar = satirlar.stream().filter(l -> l.startsWith("import ")).collect(Collectors.toList());
      assertEquals(
          importlar,
          List.of(
              "import com.antreklabs.bayi.altyapi.Bayi;",
              "import com.antreklabs.bayi.altyapi.TestTabani;",
              "import org.testng.annotations.Test;"),
          p + " import'ları");
      assertTrue(satirlar.get(0).startsWith("// AI-generated — AI Testing Probe (CasesToCode)."), p + " başlık");
      assertEquals(satirlar.stream().filter(l -> l.trim().startsWith("@Test(")).count(), 1L, p + " tek @Test");
      assertTrue(satirlar.stream().anyMatch(l -> l.contains("groups = {\"uretilen\"")), p + " uretilen grubu");
      boolean govde = false;
      for (String l : satirlar) {
        if (l.equals("  public void senaryo() {")) {
          govde = true;
          continue;
        }
        if (govde && l.equals("  }")) {
          break;
        }
        if (govde) {
          assertTrue(l.trim().startsWith("// ") || cagri.matcher(l).matches(), p + " gövde satırı sözleşme dışı: " + l);
        }
      }
      assertTrue(govde, p + " senaryo() metodu yok");
    }
  }

  @Test(groups = "birim")
  public void threadSleepYok() throws IOException {
    try (Stream<Path> s = Files.walk(KOK)) {
      for (Path p : s.filter(p -> p.toString().endsWith(".java")).collect(Collectors.toList())) {
        if (p.endsWith("SozlesmeBirimTesti.java")) {
          continue;
        }
        String metin = Files.readString(p, StandardCharsets.UTF_8);
        assertTrue(
            !Pattern.compile("Thread\\s*\\.\\s*sleep\\s*\\(|implicitlyWait\\(Duration\\.of(Seconds|Millis)").matcher(metin).find(),
            p + ": Thread.sleep / örtük bekleme yasak");
      }
    }
  }
}

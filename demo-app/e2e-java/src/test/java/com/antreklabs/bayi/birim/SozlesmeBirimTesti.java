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
import java.util.Locale;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.testng.annotations.Test;

/**
 * 009 §2.8 / 011 §2.5 Java biçim sözleşmesinin yerel kilidi (asıl denetim: toolchain/java-araclar;
 * TS ↔ Java sembol tablosu eşitliği: core/tests/unit/features/codegen/test_e2e_java_esitlik.py).
 * Kimlikler saf veridir, TypeScript locators.ts ve kimlikler.json ile birebir aynıdır; page object
 * metotları sözleşmeye uyar; TestTabani her page object için erişimci sağlar.
 */
public class SozlesmeBirimTesti {

  private static final Path KOK = Path.of("src/test/java/com/antreklabs/bayi");
  private static final Path TS_PAGES = Path.of("../e2e/pages");
  private static final Path KIMLIK_JSON = Path.of("../kimlikler.json");
  private static final Set<Class<?>> IZINLI_PARAMETRE =
      Set.of(String.class, int.class, long.class, double.class, boolean.class);
  /** Değer döndüren tek TS metodu (OrderPage.readOrderNumber): yalnız elle yazılmış testler kullanır. */
  private static final Set<String> DEGER_DONDUREN = Set.of("OrderPage.readOrderNumber");

  /** Kimlikler: grup yolu + sabit adı → değer (iç içe gruplar dahil). */
  static TreeMap<String, String> kimlikler() throws IllegalAccessException {
    TreeMap<String, String> m = new TreeMap<>();
    topla(Kimlikler.class, "", m);
    return m;
  }

  private static void topla(Class<?> c, String yol, TreeMap<String, String> m) throws IllegalAccessException {
    for (Class<?> g : c.getDeclaredClasses()) {
      topla(g, yol + g.getSimpleName() + ".", m);
    }
    for (Field f : c.getDeclaredFields()) {
      m.put(yol + f.getName(), (String) f.get(null));
    }
  }

  /** TS locators.ts: testId → within (yoksa ""). */
  static TreeMap<String, String> tsKimlikleri() throws IOException {
    Pattern p = Pattern.compile("\\{([^{}]*testId:[^{}]*)\\}");
    Pattern testId = Pattern.compile("testId:\\s*\"([^\"]+)\"");
    Pattern within = Pattern.compile("within:\\s*\"([^\"]+)\"");
    TreeMap<String, String> m = new TreeMap<>();
    try (Stream<Path> s = Files.walk(TS_PAGES)) {
      for (Path f : s.filter(x -> x.getFileName().toString().equals("locators.ts")).collect(Collectors.toList())) {
        Matcher mt = p.matcher(Files.readString(f, StandardCharsets.UTF_8));
        while (mt.find()) {
          Matcher t = testId.matcher(mt.group(1));
          Matcher w = within.matcher(mt.group(1));
          if (t.find()) {
            m.put(t.group(1), w.find() ? w.group(1) : "");
          }
        }
      }
    }
    return m;
  }

  static List<Class<?>> ekranSiniflari() throws IOException {
    try (Stream<Path> s = Files.list(KOK.resolve("ekranlar"))) {
      List<Class<?>> l = new ArrayList<>();
      for (Path p : s.filter(p -> p.getFileName().toString().endsWith("Page.java")).sorted().collect(Collectors.toList())) {
        String ad = p.getFileName().toString().replace(".java", "");
        try {
          l.add(Class.forName("com.antreklabs.bayi.ekranlar." + ad));
        } catch (ClassNotFoundException e) {
          fail("page object yüklenemedi: " + ad);
        }
      }
      return l;
    }
  }

  @Test(groups = "birim")
  public void kimliklerSafVeri() {
    int ust = Kimlikler.class.getModifiers();
    assertTrue(Modifier.isPublic(ust) && Modifier.isFinal(ust));
    assertEquals(Kimlikler.class.getDeclaredMethods().length, 0, "Kimlikler metot içeremez");
    assertEquals(Kimlikler.class.getDeclaredFields().length, 0, "Kimlikler üst düzeyde alan içeremez");
    List<Class<?>> gruplar = new ArrayList<>(List.of(Kimlikler.class.getDeclaredClasses()));
    for (int i = 0; i < gruplar.size(); i++) {
      Class<?> c = gruplar.get(i);
      int mod = c.getModifiers();
      assertTrue(Modifier.isPublic(mod) && Modifier.isStatic(mod) && Modifier.isFinal(mod), c + " public static final olmalı");
      assertEquals(c.getDeclaredMethods().length, 0, c + " metot içeremez");
      gruplar.addAll(List.of(c.getDeclaredClasses()));
      for (Field f : c.getDeclaredFields()) {
        int fm = f.getModifiers();
        assertTrue(Modifier.isPublic(fm) && Modifier.isStatic(fm) && Modifier.isFinal(fm) && f.getType() == String.class,
            f + " public static final String olmalı");
      }
    }
  }

  @Test(groups = "birim")
  public void kimliklerTsLocatorlariIleAyni() throws Exception {
    TreeMap<String, String> java = kimlikler();
    TreeMap<String, String> ts = tsKimlikleri();
    assertEquals(new TreeSet<>(java.values()), new TreeSet<>(ts.keySet()), "Kimlikler değerleri = TS locators.ts testId'leri");
    assertEquals(java.size(), ts.size(), "aynı değer iki kez tanımlanmamalı");
    for (var e : java.entrySet()) {
      assertEquals(e.getKey().endsWith("_ONEK"), e.getValue().endsWith("-"), e.getKey() + ": _ONEK ⇔ değer '-' ile biter");
      // Kapsamlı (within) kimlik: kapsayıcının adını taşıyan iç grupta; kapsayıcı öneki üst gruptaki sabit.
      String within = ts.get(e.getValue());
      String[] yol = e.getKey().split("\\.");
      if (within.isEmpty()) {
        assertEquals(yol.length, 2, e.getKey() + ": kapsamsız kimlik tek düzey grupta olmalı");
      } else {
        assertEquals(yol.length, 3, e.getKey() + ": kapsamlı kimlik (within " + within + ") iç grupta olmalı");
        String kapsayici = yol[0] + "." + yol[1].replaceAll("([a-z])([A-Z])", "$1_$2").toUpperCase(Locale.ROOT) + "_ONEK";
        assertEquals(java.get(kapsayici), within, e.getKey() + ": kapsayıcı sabiti " + kapsayici);
      }
    }
  }

  @Test(groups = "birim")
  public void kimliklerJsonIleAyni() throws Exception {
    String json = Files.readString(KIMLIK_JSON, StandardCharsets.UTF_8);
    Matcher m = Pattern.compile("\"id\"\\s*:\\s*\"([^\"]+)\"[^}]*\"onek\"\\s*:\\s*(true|false)").matcher(json);
    TreeMap<String, Boolean> sozlesme = new TreeMap<>();
    while (m.find()) {
      sozlesme.put(m.group(1), Boolean.parseBoolean(m.group(2)));
    }
    assertTrue(sozlesme.size() > 20, "kimlikler.json okunamadı");
    for (var e : kimlikler().entrySet()) {
      assertTrue(sozlesme.containsKey(e.getValue()), e.getKey() + "=" + e.getValue() + " kimlikler.json'da yok");
      assertEquals(e.getKey().endsWith("_ONEK"), (boolean) sozlesme.get(e.getValue()), e.getKey() + ": önek bilgisi");
    }
  }

  @Test(groups = "birim")
  public void pageObjectMetotlariSozlesmeye() throws Exception {
    List<Class<?>> ekranlar = ekranSiniflari();
    assertEquals(ekranlar.size(), 4);
    for (Class<?> c : ekranlar) {
      assertEquals(c.getSuperclass(), Ekran.class, c + " Ekran'dan türemeli");
      Set<String> adlar = new TreeSet<>();
      for (Method m : c.getDeclaredMethods()) {
        if (!Modifier.isPublic(m.getModifiers()) || Modifier.isStatic(m.getModifiers())) {
          continue;
        }
        assertTrue(adlar.add(m.getName()), c.getSimpleName() + "." + m.getName() + ": aşırı yükleme yok");
        String ad = c.getSimpleName() + "." + m.getName();
        if (!DEGER_DONDUREN.contains(ad)) {
          assertEquals(m.getReturnType(), void.class, ad + " void dönmeli");
        }
        for (Class<?> p : m.getParameterTypes()) {
          assertTrue(IZINLI_PARAMETRE.contains(p), ad + " parametre türü " + p);
        }
      }
    }
  }

  @Test(groups = "birim")
  public void testTabaniErisimcileri() throws Exception {
    for (Class<?> c : ekranSiniflari()) {
      String ad = Character.toLowerCase(c.getSimpleName().charAt(0)) + c.getSimpleName().substring(1);
      Method m = TestTabani.class.getDeclaredMethod(ad);
      assertEquals(m.getReturnType(), c);
      assertTrue(Modifier.isProtected(m.getModifiers()) && Modifier.isFinal(m.getModifiers()), ad + " protected final olmalı");
    }
    // TS interface Fixtures adları (dealer, signedIn, …) TestTabani'nda aynı adla bulunur.
    String fixtures = Files.readString(Path.of("../e2e/tests/fixtures.ts"), StandardCharsets.UTF_8);
    Matcher blok = Pattern.compile("interface Fixtures \\{([^}]*)\\}").matcher(fixtures);
    assertTrue(blok.find(), "fixtures.ts interface Fixtures bulunamadı");
    Matcher alan = Pattern.compile("(\\w+)\\s*:").matcher(blok.group(1));
    int n = 0;
    while (alan.find()) {
      TestTabani.class.getDeclaredMethod(alan.group(1));
      n++;
    }
    assertEquals(n, 6);
  }

  @Test(groups = "birim")
  public void kimlikDegeriOnekKurali() {
    assertEquals(Ekran.kimlikDegeri(Kimlikler.Catalog.PRODUCT_CARD_ONEK, "P-001"), "product-card-P-001");
    assertEquals(Ekran.kimlikDegeri(Kimlikler.Cart.TOTAL, null), "cart-total");
    org.testng.Assert.assertThrows(IllegalArgumentException.class, () -> Ekran.kimlikDegeri(Kimlikler.Cart.LINE_ONEK, null));
    org.testng.Assert.assertThrows(IllegalArgumentException.class, () -> Ekran.kimlikDegeri(Kimlikler.Cart.TOTAL, "P-001"));
  }
}

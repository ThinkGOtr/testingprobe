package com.antreklabs.tp.javaaraclar;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * java-araclar CLI.
 *
 * <pre>
 *   java -jar java-araclar.jar symbols  --root &lt;e2e-app&gt; [--src src/test/java]
 *   java -jar java-araclar.jar guard    --root &lt;e2e-app&gt; [--kimlikler] [--out rapor.json] &lt;dosya.java&gt;…
 *   java -jar java-araclar.jar locators find  --root &lt;e2e-app&gt; --test-id &lt;id&gt;
 *   java -jar java-araclar.jar locators patch --root &lt;e2e-app&gt; --old &lt;id&gt; --new &lt;id&gt; [--key Grup.SABIT] [--path-prefix p]
 *   java -jar java-araclar.jar locators diff  --base &lt;Kimlikler.java&gt; --head &lt;Kimlikler.java&gt; [--file &lt;etiket&gt;]
 * </pre>
 *
 * Çıkış kodları: {@code symbols}/{@code locators find} 0 = üretildi, 2 = kullanım/çalışma hatası;
 * {@code guard}/{@code locators diff} 0 = geçti, 1 = ihlal, 2 = hata; {@code locators patch} 0 =
 * yama, 1 = reddedildi, 2 = hata. JSON stdout'a; hata durumunda {@code {"ok": false, "error": …}}.
 */
public final class Main {
  public static final int OK = 0;
  public static final int IHLAL = 1;
  public static final int HATA = 2;

  static final String KULLANIM = String.join("\n",
      "Kullanım:",
      "  java-araclar symbols  --root <e2e-app> [--src src/test/java]",
      "  java-araclar guard    --root <e2e-app> [--kimlikler] [--out rapor.json] <dosya.java>...",
      "  java-araclar locators find  --root <e2e-app> --test-id <id>",
      "  java-araclar locators patch --root <e2e-app> --old <id> --new <id> [--key Grup.SABIT] [--path-prefix <yol>]",
      "  java-araclar locators diff  --base <Kimlikler.java> --head <Kimlikler.java> [--file <etiket>]",
      "Çıkış: 0 tamam · 1 ihlal/ret · 2 hata");

  private Main() {}

  public static void main(String[] args) {
    PrintStream out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true, StandardCharsets.UTF_8);
    PrintStream err = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.err), true, StandardCharsets.UTF_8);
    System.exit(calistir(args, out, err));
  }

  /** Argümanlar: --ad değer çiftleri, bayraklar ve konumsal argümanlar. */
  record Argumanlar(Map<String, String> secenekler, Set<String> bayraklar, List<String> konumsal) {}

  static Argumanlar ayir(String[] args, int bas, Set<String> degerli, Set<String> bayrakAdlari) {
    Map<String, String> s = new LinkedHashMap<>();
    Set<String> b = new java.util.LinkedHashSet<>();
    List<String> k = new ArrayList<>();
    boolean sonSecenek = false;
    for (int i = bas; i < args.length; i++) {
      String a = args[i];
      if (!sonSecenek && a.equals("--")) {
        sonSecenek = true;
      } else if (!sonSecenek && a.startsWith("--")) {
        String ad = a.substring(2);
        String deger = null;
        int eq = ad.indexOf('=');
        if (eq >= 0) {
          deger = ad.substring(eq + 1);
          ad = ad.substring(0, eq);
        }
        if (degerli.contains(ad)) {
          if (deger == null) {
            if (i + 1 >= args.length) throw new IllegalArgumentException("--" + ad + " bir değer ister");
            deger = args[++i];
          }
          if (s.put(ad, deger) != null) throw new IllegalArgumentException("--" + ad + " iki kez verildi");
        } else if (bayrakAdlari.contains(ad) && deger == null) {
          b.add(ad);
        } else {
          throw new IllegalArgumentException("bilinmeyen seçenek: " + a);
        }
      } else if (!sonSecenek && a.startsWith("-") && a.length() > 1) {
        throw new IllegalArgumentException("bilinmeyen seçenek: " + a);
      } else {
        k.add(a);
      }
    }
    return new Argumanlar(s, b, k);
  }

  public static int calistir(String[] args, PrintStream out, PrintStream err) {
    if (args.length == 0) {
      err.println(KULLANIM);
      return HATA;
    }
    if (args[0].equals("-h") || args[0].equals("--help")) {
      out.println(KULLANIM);
      return OK;
    }
    try {
      return switch (args[0]) {
        case "symbols" -> semboller(args, out, err);
        case "guard" -> koru(args, out, err);
        case "locators" -> kimlikler(args, out, err);
        default -> {
          err.println("bilinmeyen alt komut: " + args[0] + "\n" + KULLANIM);
          yield HATA;
        }
      };
    } catch (IllegalArgumentException e) {
      err.println(e.getMessage() + "\n" + KULLANIM);
      return HATA;
    }
  }

  private static Path kok(Argumanlar a) {
    String root = a.secenekler().get("root");
    if (root == null || root.isEmpty()) throw new IllegalArgumentException("--root zorunludur");
    return Path.of(root);
  }

  private static int hata(PrintStream out, PrintStream err, String arac, Exception e) {
    Map<String, Object> m = new LinkedHashMap<>();
    m.put("ok", false);
    m.put("error", String.valueOf(e.getMessage()));
    out.println(Json.yaz(m));
    err.println(arac + " hata: " + e.getMessage());
    return HATA;
  }

  static int semboller(String[] args, PrintStream out, PrintStream err) {
    Argumanlar a = ayir(args, 1, Set.of("root", "src"), Set.of());
    if (!a.konumsal().isEmpty()) throw new IllegalArgumentException("beklenmeyen argüman: " + a.konumsal().get(0));
    Path kok = kok(a);
    try {
      SembolCikarici.Tablo t = SembolCikarici.cikar(kok, a.secenekler().getOrDefault("src", Kaynaklar.TEST_KAYNAK));
      out.println(Json.yaz(t.json()));
      return OK;
    } catch (IOException | RuntimeException e) {
      return hata(out, err, "java-araclar symbols", e);
    }
  }

  static int koru(String[] args, PrintStream out, PrintStream err) {
    Argumanlar a = ayir(args, 1, Set.of("root", "out"), Set.of("kimlikler", "quiet"));
    Path kok = kok(a);
    Map<String, Object> rapor;
    try {
      rapor = UretilenTestKoruyucu.denetle(kok, a.konumsal(), a.bayraklar().contains("kimlikler"));
    } catch (IOException | RuntimeException e) {
      Map<String, Object> m = new LinkedHashMap<>();
      m.put("tool", "java-araclar");
      m.put("schema_version", 1);
      m.put("ok", false);
      m.put("error", String.valueOf(e.getMessage()));
      out.println(Json.yazGirintili(m));
      err.println("java-araclar guard hata: " + e.getMessage());
      return HATA;
    }
    String json = Json.yazGirintili(rapor) + "\n";
    if (a.secenekler().containsKey("out")) {
      try {
        Files.writeString(Path.of(a.secenekler().get("out")), json, StandardCharsets.UTF_8);
      } catch (IOException e) {
        return hata(out, err, "java-araclar guard", e);
      }
    }
    if (!a.bayraklar().contains("quiet")) out.print(json);
    err.println(rapor.get("summary"));
    @SuppressWarnings("unchecked")
    List<Map<String, Object>> ihlaller = (List<Map<String, Object>>) rapor.get("violations");
    for (Map<String, Object> v : ihlaller) {
      err.println("  ✗ [" + v.get("code") + "] " + v.get("file") + (v.containsKey("line") ? ":" + v.get("line") : "") + " " + v.get("message"));
    }
    return Boolean.TRUE.equals(rapor.get("ok")) ? OK : IHLAL;
  }

  static int kimlikler(String[] args, PrintStream out, PrintStream err) {
    if (args.length < 2) throw new IllegalArgumentException("locators alt komutu gerekli (find | patch | diff)");
    switch (args[1]) {
      case "find" -> {
        Argumanlar a = ayir(args, 2, Set.of("root", "test-id"), Set.of());
        Path kok = kok(a);
        String id = a.secenekler().get("test-id");
        if (id == null || id.isEmpty()) throw new IllegalArgumentException("--test-id zorunludur");
        try {
          out.println(Json.yaz(KimlikYamasi.bul(kok, id)));
          return OK;
        } catch (IOException | RuntimeException e) {
          return hata(out, err, "java-araclar locators find", e);
        }
      }
      case "patch" -> {
        Argumanlar a = ayir(args, 2, Set.of("root", "old", "new", "key", "path-prefix"), Set.of());
        Path kok = kok(a);
        try {
          Map<String, Object> m = KimlikYamasi.yamala(kok, a.secenekler().get("old"), a.secenekler().get("new"),
              a.secenekler().get("key"), a.secenekler().get("path-prefix"));
          out.println(Json.yaz(m));
          return OK;
        } catch (KimlikYamasi.YamaHatasi e) {
          Map<String, Object> m = new LinkedHashMap<>();
          m.put("ok", false);
          m.put("error", e.getMessage());
          out.println(Json.yaz(m));
          err.println("yama reddedildi: " + e.getMessage());
          return IHLAL;
        } catch (IOException | RuntimeException e) {
          return hata(out, err, "java-araclar locators patch", e);
        }
      }
      case "diff" -> {
        Argumanlar a = ayir(args, 2, Set.of("base", "head", "file"), Set.of());
        String base = a.secenekler().get("base");
        String head = a.secenekler().get("head");
        if (base == null || head == null) throw new IllegalArgumentException("--base ve --head zorunludur");
        try {
          String etiket = a.secenekler().getOrDefault("file", head);
          Map<String, Object> r = KimlikYamasi.fark(Kaynaklar.oku(Path.of(base)), Kaynaklar.oku(Path.of(head)), etiket);
          out.print(Json.yazGirintili(r) + "\n");
          err.println(r.get("summary"));
          return Boolean.TRUE.equals(r.get("ok")) ? OK : IHLAL;
        } catch (IOException | RuntimeException e) {
          return hata(out, err, "java-araclar locators diff", e);
        }
      }
      default -> throw new IllegalArgumentException("bilinmeyen locators alt komutu: " + args[1]);
    }
  }
}

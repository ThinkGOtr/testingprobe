package com.antreklabs.tp.javaaraclar;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** Sembol tablosu: golden çıktı, TS şeması, hatalı ağaç, CLI çıkış kodları. */
class SembolCikariciTest {
  static final Path KOK = Path.of("src/test/resources/e2e-app");
  static final Path HATALI = Path.of("src/test/resources/e2e-app-hatali");
  static final Path GOLDEN = Path.of("src/test/resources/beklenen/semboller.json");

  static String cli(String... args) {
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    int kod = Main.calistir(args, new PrintStream(out, true, StandardCharsets.UTF_8),
        new PrintStream(new ByteArrayOutputStream(), true, StandardCharsets.UTF_8));
    return kod + "|" + out.toString(StandardCharsets.UTF_8);
  }

  @Test
  void goldenCiktiylaBaytBaytAyni() throws IOException {
    String sonuc = cli("symbols", "--root", KOK.toString());
    assertTrue(sonuc.startsWith("0|"), sonuc);
    String json = sonuc.substring(2);
    if (Boolean.getBoolean("golden.guncelle")) Files.writeString(GOLDEN, json, StandardCharsets.UTF_8);
    assertEquals(Files.readString(GOLDEN, StandardCharsets.UTF_8), json);
    // Deterministik: ikinci çalıştırma aynı.
    assertEquals(sonuc, cli("symbols", "--root", KOK.toString()));
  }

  @SuppressWarnings("unchecked")
  @Test
  void tsSemasiyleAyniAnahtarlar() throws IOException {
    Map<String, Object> t = SembolCikarici.cikar(KOK, Kaynaklar.TEST_KAYNAK).json();
    // TS tp-symbols (toolchain/symbols/src/extract.ts) arayüzleri + ek `fixtures`.
    assertEquals(List.of("schema_version", "root", "page_objects", "locator_files", "errors", "fixtures"), List.copyOf(t.keySet()));
    assertEquals(1, t.get("schema_version"));
    List<Map<String, Object>> pos = (List<Map<String, Object>>) t.get("page_objects");
    assertEquals(List.of("GirisEkrani", "KatalogEkrani", "SepetEkrani"), pos.stream().map(p -> p.get("class")).toList());
    for (Map<String, Object> po : pos) {
      assertEquals(List.of("class", "file", "doc", "methods", "locators"), List.copyOf(po.keySet()));
      for (Map<String, Object> m : (List<Map<String, Object>>) po.get("methods")) {
        assertEquals(List.of("name", "params", "returns", "kind", "async", "doc", "line"), List.copyOf(m.keySet()));
        for (Map<String, Object> p : (List<Map<String, Object>>) m.get("params")) {
          assertEquals(List.of("name", "type", "optional"), List.copyOf(p.keySet()));
          assertTrue(SembolCikarici.PARAMETRE_TURLERI.contains((String) p.get("type")));
        }
      }
      for (Object l : ((Map<String, Object>) po.get("locators")).values()) {
        assertEquals(List.of("testId", "role", "name", "intent", "prefix", "file", "line"), List.copyOf(((Map<String, Object>) l).keySet()));
      }
    }
    assertEquals(List.of(), t.get("errors"));
    assertEquals(List.of("girisEkrani", "katalogEkrani", "sepetEkrani"), t.get("fixtures"));
  }

  @Test
  void webPageObjectExpectMetotlariDogrulamadir() {
    assertEquals("expect", SembolCikarici.tur("expectTotal"));
    assertEquals("expect", SembolCikarici.tur("expect"));
    assertEquals("expect", SembolCikarici.tur("expect2"));
    assertEquals("expect", SembolCikarici.tur("dogrulaToplam"));
    assertEquals("action", SembolCikarici.tur("expected"));
    assertEquals("action", SembolCikarici.tur("expectedTotal"));
    assertEquals("action", SembolCikarici.tur("addToCart"));
  }

  @SuppressWarnings("unchecked")
  @Test
  void kindVeDocVeKimlikCozumu() throws IOException {
    Map<String, Object> t = SembolCikarici.cikar(KOK, Kaynaklar.TEST_KAYNAK).json();
    List<Map<String, Object>> pos = (List<Map<String, Object>>) t.get("page_objects");
    Map<String, Object> giris = pos.get(0);
    List<Map<String, Object>> ms = (List<Map<String, Object>>) giris.get("methods");
    // private ve statik metotlar tabloya girmez.
    assertEquals(List.of("girisYap", "dogrulaHataMesaji"), ms.stream().map(m -> m.get("name")).toList());
    assertEquals("action", ms.get(0).get("kind"));
    assertEquals("expect", ms.get(1).get("kind"));
    assertEquals("Hata mesajının göründüğünü ve metnini doğrular.", ms.get(1).get("doc"));
    assertEquals("Bayi giriş ekranı.", giris.get("doc"));
    Map<String, Map<String, Object>> loc = (Map<String, Map<String, Object>>) giris.get("locators");
    assertEquals("login-username", loc.get("Giris.KULLANICI_ADI").get("testId"));
    assertEquals("Kullanıcı adı alanı.", loc.get("Giris.KULLANICI_ADI").get("intent"));
    // Statik joker içe aktarma (KatalogEkrani) ve iç sınıf içe aktarma (SepetEkrani) çözülür.
    Map<String, Map<String, Object>> katalog = (Map<String, Map<String, Object>>) pos.get(1).get("locators");
    assertEquals(Set.of("Katalog.URUN_KARTI_ONEK", "Katalog.SEPETE_EKLE"), katalog.keySet());
    assertEquals(true, katalog.get("Katalog.URUN_KARTI_ONEK").get("prefix"));
    assertEquals(false, katalog.get("Katalog.SEPETE_EKLE").get("prefix"));
    Map<String, Map<String, Object>> sepet = (Map<String, Map<String, Object>>) pos.get(2).get("locators");
    assertEquals(Set.of("Sepet.TOPLAM", "Sepet.Satir.ADET"), sepet.keySet());
  }

  @SuppressWarnings("unchecked")
  @Test
  void hataliAgacHatalariListeler() throws IOException {
    Map<String, Object> t = SembolCikarici.cikar(HATALI, Kaynaklar.TEST_KAYNAK).json();
    List<Map<String, Object>> errors = (List<Map<String, Object>>) t.get("errors");
    String hepsi = errors.toString();
    assertTrue(hepsi.contains("BozukEkrani.java") && hepsi.contains("sözdizimi:"), hepsi);
    for (String beklenen : List.of(
        "içe aktarma yasak", "tek üst düzey tür", "beklenmeyen öğe", "Giris.PAROLA: değer yalnızca string literal",
        "Giris.GONDER: değer yalnızca string literal", "Giris.SAYI: tür String olmalı", "bildirim başına tek sabit",
        "geçersiz kimlik değeri", "Giris.BLOK: değer yalnızca string literal", "Katalog: niteleyiciler",
        "Sepet.TOPLAM: birden çok kez tanımlı", "desteklenmeyen parametre türü List<String>", "void dönmeli",
        "aşırı yükleme", "String...", "fikstür erişimcisi yok")) {
      assertTrue(hepsi.contains(beklenen), beklenen + " yok: " + hepsi);
    }
    // Saf olmayan girişler atlanır, geçerli olanlar kalır (TS ile aynı davranış).
    List<Map<String, Object>> pos = (List<Map<String, Object>>) t.get("page_objects");
    assertEquals(1, pos.size());
    assertEquals(Set.of("Sepet.TOPLAM"), ((Map<String, Object>) pos.get(0).get("locators")).keySet());
    assertEquals(List.of(), t.get("fixtures"));
    for (Map<String, Object> e : errors) {
      assertEquals(Set.of("file", "line", "message"), e.keySet());
    }
  }

  @Test
  void cliCikisKodlari() {
    String r = cli("symbols", "--root", "yok/boyle/bir/dizin");
    assertTrue(r.startsWith("2|{\"ok\":false,\"error\":"), r);
    assertTrue(cli("symbols").startsWith("2|"));
    assertTrue(cli("symbols", "--root", KOK.toString(), "--src", "../../..").startsWith("2|"));
    assertTrue(cli("symbols", "--root", KOK.toString(), "fazla").startsWith("2|"));
    assertTrue(cli("--help").startsWith("0|Kullanım"));
    assertFalse(cli("bilinmez").startsWith("0|"));
  }
}

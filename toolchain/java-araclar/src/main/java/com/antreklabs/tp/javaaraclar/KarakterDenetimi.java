package com.antreklabs.tp.javaaraclar;

import java.util.ArrayList;
import java.util.List;

/**
 * Kaynak metin düzeyinde karakter denetimi (AST'den ÖNCE).
 *
 * <p>javac Unicode kaçışlarını ({@code \u000a}, {@code "} …) sözcük çözümlemesinden önce
 * işler: bir yorumun içindeki {@code \u000a} yorumu bitirir ve ardından gelen metin KOD olur;
 * ayrıştırıcı ise (ön işleme kapalıyken) onu yorum olarak görür. Bu yüzden kaçışlı Unicode tümden
 * reddedilir. Görünmez biçim karakterleri (yön denetimi — "Trojan Source", sıfır genişlikli
 * karakterler), satır/paragraf ayırıcıları ve sekme, satır sonu dışındaki kontrol karakterleri de
 * reddedilir: insan incelemesinde görülen metin derlenen metinle aynı olmalıdır.
 */
public final class KarakterDenetimi {
  private KarakterDenetimi() {}

  /** Bulgu: kod, 1 tabanlı satır, mesaj. */
  public record Bulgu(String kod, int satir, String mesaj) {}

  public static List<Bulgu> denetle(String metin) {
    List<Bulgu> out = new ArrayList<>();
    int satir = 1;
    boolean kacisBildirildi = false;
    boolean karakterBildirildi = false;
    for (int i = 0; i < metin.length(); ) {
      int cp = metin.codePointAt(i);
      int n = Character.charCount(cp);
      if (cp == '\\') {
        // Ardışık ters bölüleri say: tek sayıdaysa ardından gelen 'u' bir Unicode kaçışıdır
        // (JLS §3.3: "\\u" kaçış değildir).
        int j = i;
        while (j < metin.length() && metin.charAt(j) == '\\') j++;
        int adet = j - i;
        if (adet % 2 == 1 && j < metin.length() && metin.charAt(j) == 'u' && !kacisBildirildi) {
          out.add(new Bulgu("unicode_escape", satir,
              "Unicode kaçışı (\\uXXXX) yasak: javac onu yorum ve literal içinde bile kod olarak işler"));
          kacisBildirildi = true;
        }
        i = j;
        continue;
      }
      if (cp == '\n') {
        satir++;
      } else if (!karakterBildirildi && yasak(cp)) {
        out.add(new Bulgu("forbidden_character", satir,
            String.format("görünmez/kontrol karakteri yasak (U+%04X)", cp)));
        karakterBildirildi = true;
      }
      i += n;
    }
    return out;
  }

  static boolean yasak(int cp) {
    if (cp == '\n' || cp == '\r' || cp == '\t') return false;
    int tur = Character.getType(cp);
    return tur == Character.CONTROL
        || tur == Character.FORMAT
        || tur == Character.LINE_SEPARATOR
        || tur == Character.PARAGRAPH_SEPARATOR
        || tur == Character.PRIVATE_USE
        || tur == Character.SURROGATE
        || tur == Character.UNASSIGNED;
  }
}

package com.antreklabs.tp.javaaraclar;

import java.util.List;
import java.util.Map;

/**
 * Küçük, bağımlılıksız JSON yazıcı.
 *
 * <p>Çıktı JavaScript {@code JSON.stringify} ile aynı kaçış kurallarını izler (TS {@code tp-symbols}
 * ile bayt düzeyinde karşılaştırılabilir olsun diye): yalnızca {@code "}, {@code \}, kontrol
 * karakterleri ve eşi olmayan vekil (surrogate) karakterler kaçışlanır; diğer Unicode karakterler
 * olduğu gibi yazılır. Anahtar sırası {@link Map} sırasıdır (çağıran {@code LinkedHashMap}
 * kullanır).
 */
public final class Json {
  private Json() {}

  /** Tek satır (TS {@code JSON.stringify(x)}). */
  public static String yaz(Object deger) {
    StringBuilder sb = new StringBuilder();
    yaz(sb, deger, -1, 0);
    return sb.toString();
  }

  /** İki boşluk girintili (TS {@code JSON.stringify(x, null, 2)}). */
  public static String yazGirintili(Object deger) {
    StringBuilder sb = new StringBuilder();
    yaz(sb, deger, 2, 0);
    return sb.toString();
  }

  private static void yaz(StringBuilder sb, Object deger, int girinti, int derinlik) {
    if (deger == null) {
      sb.append("null");
    } else if (deger instanceof String s) {
      metin(sb, s);
    } else if (deger instanceof Boolean b) {
      sb.append(b ? "true" : "false");
    } else if (deger instanceof Integer || deger instanceof Long) {
      sb.append(deger);
    } else if (deger instanceof Map<?, ?> m) {
      if (m.isEmpty()) {
        sb.append("{}");
        return;
      }
      sb.append('{');
      boolean ilk = true;
      for (Map.Entry<?, ?> e : m.entrySet()) {
        if (!ilk) sb.append(',');
        ilk = false;
        satir(sb, girinti, derinlik + 1);
        metin(sb, String.valueOf(e.getKey()));
        sb.append(girinti >= 0 ? ": " : ":");
        yaz(sb, e.getValue(), girinti, derinlik + 1);
      }
      satir(sb, girinti, derinlik);
      sb.append('}');
    } else if (deger instanceof List<?> l) {
      if (l.isEmpty()) {
        sb.append("[]");
        return;
      }
      sb.append('[');
      boolean ilk = true;
      for (Object o : l) {
        if (!ilk) sb.append(',');
        ilk = false;
        satir(sb, girinti, derinlik + 1);
        yaz(sb, o, girinti, derinlik + 1);
      }
      satir(sb, girinti, derinlik);
      sb.append(']');
    } else {
      throw new IllegalArgumentException("JSON'a yazılamayan tür: " + deger.getClass());
    }
  }

  private static void satir(StringBuilder sb, int girinti, int derinlik) {
    if (girinti < 0) return;
    sb.append('\n');
    sb.append(" ".repeat(girinti * derinlik));
  }

  static void metin(StringBuilder sb, String s) {
    sb.append('"');
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      switch (c) {
        case '"' -> sb.append("\\\"");
        case '\\' -> sb.append("\\\\");
        case '\b' -> sb.append("\\b");
        case '\f' -> sb.append("\\f");
        case '\n' -> sb.append("\\n");
        case '\r' -> sb.append("\\r");
        case '\t' -> sb.append("\\t");
        default -> {
          if (c < 0x20) {
            sb.append(String.format("\\u%04x", (int) c));
          } else if (Character.isHighSurrogate(c)) {
            if (i + 1 < s.length() && Character.isLowSurrogate(s.charAt(i + 1))) {
              sb.append(c).append(s.charAt(++i));
            } else {
              sb.append(String.format("\\u%04x", (int) c));
            }
          } else if (Character.isLowSurrogate(c)) {
            sb.append(String.format("\\u%04x", (int) c));
          } else {
            sb.append(c);
          }
        }
      }
    }
    sb.append('"');
  }
}

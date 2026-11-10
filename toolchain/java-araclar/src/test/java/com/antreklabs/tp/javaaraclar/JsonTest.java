package com.antreklabs.tp.javaaraclar;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** JSON yazıcı JavaScript JSON.stringify kaçışlarıyla aynı. */
class JsonTest {
  @Test
  void kacislar() {
    assertEquals("\"a\\\"b\\\\c\\n\\t\\r\\b\\f\\u0001\\u001f\"", Json.yaz("a\"b\\c\n\t\r\b\f\u0001\u001f"));
    assertEquals("\"ğüşİ€😀\u2028\"", Json.yaz("ğüşİ€😀\u2028"));
    assertEquals("\"\\ud800x\"", Json.yaz("\ud800x"));
    assertEquals("\"\\udc00\"", Json.yaz("\udc00"));
  }

  @Test
  void yapilar() {
    Map<String, Object> m = new LinkedHashMap<>();
    m.put("b", List.of(1, true, "x"));
    m.put("a", new LinkedHashMap<>());
    m.put("c", null);
    m.put("d", List.of());
    assertEquals("{\"b\":[1,true,\"x\"],\"a\":{},\"c\":null,\"d\":[]}", Json.yaz(m));
    assertEquals("{\n  \"b\": [\n    1,\n    true,\n    \"x\"\n  ],\n  \"a\": {},\n  \"c\": null,\n  \"d\": []\n}", Json.yazGirintili(m));
  }
}

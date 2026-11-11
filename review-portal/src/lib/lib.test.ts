import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { GEREKSINIM_DURUMLARI } from "../api/types";
import { akisAdimi, DURUM_ADIMI } from "./akis";
import { AKIS_ADIMLARI, gereksinimDurumu } from "./etiketler";
import { baglantiTuru, uygulamaRotasiMi } from "./rotalar";
import { describe, expect, it } from "vitest";
import { duzeltmeOlcusu, kelimeFarki } from "./diff";
import { kisaHash, sure, tl, yuzde } from "./format";
import { kanonikJson, sha256Hex } from "./sha256";
import { belirtecle, satirlaraBol } from "./vurgula";

describe("sha256Hex", () => {
  it("bilinen test vektörlerini üretir", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    // 64 baytı aşan, çok bloklu ve UTF-8 girdi
    expect(sha256Hex("ş".repeat(40))).toHaveLength(64);
    expect(sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")).toBe(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    );
  });

  it("kanonik JSON anahtarları sıralar ve undefined alanları atar", () => {
    expect(kanonikJson({ b: 1, a: [true, null, { d: "x", c: undefined }] })).toBe('{"a":[true,null,{"d":"x"}],"b":1}');
  });
});

describe("kelimeFarki", () => {
  it("değişen sayıyı silindi/eklendi olarak işaretler ve metni korur", () => {
    const eski = "minimum sipariş tutarı 500,00 TL'dir";
    const yeni = "minimum sipariş tutarı 750,00 TL'dir";
    const f = kelimeFarki(eski, yeni);
    expect(f.filter((p) => p.tur === "silindi").map((p) => p.metin)).toEqual(["500,00"]);
    expect(f.filter((p) => p.tur === "eklendi").map((p) => p.metin)).toEqual(["750,00"]);
    expect(f.filter((p) => p.tur !== "silindi").map((p) => p.metin).join("")).toBe(yeni);
    expect(f.filter((p) => p.tur !== "eklendi").map((p) => p.metin).join("")).toBe(eski);
  });

  it("aynı metinde tek 'ayni' parçası döner", () => {
    expect(kelimeFarki("a b", "a b")).toEqual([{ tur: "ayni", metin: "a b" }]);
  });
});

describe("duzeltmeOlcusu", () => {
  it("aynı metin 0, tamamen farklı 1'e yakın, boşluk/büyük harf farkı 0", () => {
    expect(duzeltmeOlcusu("Sepete ekle", "  sepete   EKLE ")).toBe(0);
    expect(duzeltmeOlcusu("abc", "xyz")).toBe(1);
    const k = duzeltmeOlcusu("İndirim 25,00 TL", "İndirim 25,00 TL gösterilir");
    expect(k).toBeGreaterThan(0);
    expect(k).toBeLessThan(0.5);
  });
});

describe("format", () => {
  it("tutarı tr-TR biçiminde basar (DEMO-VERISI)", () => {
    expect(tl(1250)).toBe("1.250,00 TL");
    expect(tl(25)).toBe("25,00 TL");
  });
  it("yüzde, süre ve hash", () => {
    expect(yuzde(0.734)).toBe("%73");
    expect(sure(6800)).toBe("6,8 sn");
    expect(sure(95000)).toBe("1 dk 35 sn");
    expect(sure(null)).toBe("—");
    expect(kisaHash("sha256:abcdef0123456789", 6)).toBe("abcdef…");
  });
});

describe("vurgula", () => {
  it("anahtar kelime, metin, yorum, tip ve fonksiyonları ayırır", () => {
    const b = belirtecle('import { test } from "@playwright/test"; // yorum\nawait cart.expectTotal("125,00 TL");');
    const tur = (m: string) => b.find((x) => x.metin === m)?.tur;
    expect(tur("import")).toBe("anahtar");
    expect(tur('"@playwright/test"')).toBe("metin");
    expect(tur("// yorum")).toBe("yorum");
    expect(tur("expectTotal")).toBe("fonksiyon");
    expect(b.map((x) => x.metin).join("")).toContain("cart.expectTotal");
  });

  it("satırlara böler ve HTML üretmez", () => {
    const satirlar = satirlaraBol(belirtecle('const a = "<img onerror=x>";\nconst b = 2;'));
    expect(satirlar).toHaveLength(2);
    expect(satirlar[0].some((x) => x.metin === '"<img onerror=x>"')).toBe(true);
  });
});

describe("gereksinim durum etiketleri (core-api durum makinesi)", () => {
  it("core'un REQUIREMENT durumlarının hepsi Türkçe etiketlenir", async () => {
    const { gereksinimDurumu } = await import("./etiketler");
    // tp_core/workflow/states.py REQUIREMENT.states
    const core = ["new", "in_review", "findings_open", "doc_final", "pending_po", "po_approved", "generating", "cases_ready", "done", "failed"];
    for (const d of core) expect(gereksinimDurumu(d).etiket).not.toBe(d);
  });
});

describe("akış adımı core durum makinesinden türetilir", () => {
  const statesYolu = resolve(__dirname, "../../../core/src/tp_core/workflow/states.py");

  /** states.py'deki REQUIREMENT = Machine(... transitions=_t(a=(...), ...)) bloğundaki durumlar. */
  function coreGereksinimDurumlari(): string[] {
    const kaynak = readFileSync(statesYolu, "utf8");
    const blok = /REQUIREMENT = Machine\(([\s\S]*?)\n\)/.exec(kaynak)?.[1] ?? "";
    const gecisler = /transitions=_t\(([\s\S]*?)\n {4}\),/.exec(blok)?.[1] ?? "";
    const durumlar = new Set<string>();
    for (const m of gecisler.matchAll(/^\s*([a-z_]+)=\(([^)]*)\)/gm)) {
      durumlar.add(m[1]);
      for (const h of m[2].matchAll(/"([a-z_]+)"/g)) durumlar.add(h[1]);
    }
    return [...durumlar].sort();
  }

  it.skipIf(!existsSync(statesYolu))("portalın durum kümesi core REQUIREMENT kümesiyle birebir aynı ve her durum bir adıma eşlenir", () => {
    const core = coreGereksinimDurumlari();
    expect(core).toHaveLength(12); // 011 F3: + modeling, model_ready
    expect([...GEREKSINIM_DURUMLARI].sort()).toEqual(core);
    for (const d of core) {
      expect(DURUM_ADIMI).toHaveProperty(d);
      const adim = akisAdimi(d, 7);
      expect(adim).toBeGreaterThanOrEqual(1);
      expect(adim).toBeLessThanOrEqual(AKIS_ADIMLARI.length);
      expect(gereksinimDurumu(d).etiket).not.toBe(d);
    }
  });

  it("adımlar akış sırasını izler; ipucu yalnızca done/failed için kullanılır", () => {
    expect(["new", "in_review", "findings_open", "doc_final", "pending_po", "po_approved", "generating", "cases_ready", "done"].map((d) => akisAdimi(d))).toEqual([
      1, 2, 2, 2, 3, 4, 4, 4, 5,
    ]);
    expect(akisAdimi("pending_po", 9)).toBe(3);
    expect(akisAdimi("done", 6)).toBe(6);
    expect(akisAdimi("done", 2)).toBe(5);
    expect(akisAdimi("done", 99)).toBe(14);
    expect(akisAdimi("failed", 4)).toBe(4);
    expect(akisAdimi("failed")).toBe(1);
    expect(akisAdimi("bilinmeyen")).toBe(1);
  });
});

describe("bağlantı çözümleme", () => {
  it("App.tsx'teki her rota uygulamaRotasiMi ile tanınır", () => {
    const app = readFileSync(resolve(__dirname, "../App.tsx"), "utf8");
    const yollar = [...app.matchAll(/path="([^"*]+)"/g)].map((m) => `/${m[1].replace(/^\//, "").replace(/:[a-z]+/g, "x")}`);
    expect(yollar.length).toBeGreaterThanOrEqual(15);
    for (const y of yollar) expect(uygulamaRotasiMi(y), y).toBe(true);
  });

  it("ölü yollar metin olur; ekranlar iç, http ve /api/ dış bağlantıdır", () => {
    expect(baglantiTuru("/kosular/run-107")).toBe("ic");
    expect(baglantiTuru("/hatalar/fail-1?x=1")).toBe("ic");
    expect(baglantiTuru("/forge/pulls/12")).toBe("metin");
    expect(baglantiTuru("/artifacts/run-107/trace.zip")).toBe("metin");
    expect(baglantiTuru("/kosular/run-1/fazla")).toBe("metin");
    expect(baglantiTuru("#fnd-3")).toBe("metin");
    expect(baglantiTuru(null)).toBe("metin");
    expect(baglantiTuru("http://127.0.0.1:8090/browse/TPD-1")).toBe("dis");
    expect(baglantiTuru("/api/artifacts/run-1/allure/index.html")).toBe("dis");
  });
});

describe("Python renklendirme", () => {
  it("`//` tam sayı bölmesidir, yorum `#` ile başlar", async () => {
    const { belirtecle, dilBul } = await import("./vurgula");
    expect(dilBul("api/src/demoapp_api/campaign.py")).toBe("py");
    expect(dilBul("tests/a.spec.ts")).toBe("ts");
    const b = belirtecle("    return adet // 6", "py");
    expect(b.some((x) => x.tur === "yorum")).toBe(false);
    expect(b.find((x) => x.metin === "return")?.tur).toBe("anahtar");
    const y = belirtecle("min_aranir = not any(x)  # kampanyalı siparişte aranmaz", "py");
    expect(y.filter((x) => x.tur === "yorum").map((x) => x.metin)).toEqual(["# kampanyalı siparişte aranmaz"]);
    expect(belirtecle("a // b", "ts").some((x) => x.tur === "yorum")).toBe(true);
  });
});

// Portal durum birlikleri ↔ core durum makineleri (tp_core.workflow.states.MACHINES).
//
// Yetkili kaynak core'dur. `sozlesme/durum-makineleri.json` core'dan üretilmiş, depoda tutulan
// dışa aktarımdır (`npm run sozlesme:durumlar`). Bu test iki şeyi denetler:
//   1. Portalın her durum birliği dışa aktarımla birebir aynı küme (fazla/eksik durum yok).
//   2. core erişilebilirse (uv + ../core) dışa aktarım güncel: core'dan yeniden üretilen JSON aynı.
// Örnek verinin (mock) ürettiği her durum da bu kümelerde olmalı (sahte durum yok).
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { api } from "./client";
import { ayar, mockVerisi } from "./mock/handlers";
import { ilkVeri } from "./mock/fixtures";
import makineler from "./sozlesme/durum-makineleri.json";
import { BUG_DURUMLARI, BULGU_DURUMLARI, CASE_DURUMLARI, GEREKSINIM_DURUMLARI, SCRIPT_DURUMLARI } from "./types";
import { BUG_DURUMU, BULGU_DURUMU, CASE_DURUMU, GEREKSINIM_DURUMU, SCRIPT_DURUMU } from "../lib/etiketler";
import { oturumAc } from "../test/yardimci";

type Makine = { initial: string; states: string[]; transitions: Record<string, string[]> };
const M = makineler as Record<string, Makine>;

const ESLEME: [string, readonly string[], Record<string, unknown>][] = [
  ["requirement", GEREKSINIM_DURUMLARI, GEREKSINIM_DURUMU],
  ["consistency_finding", BULGU_DURUMLARI, BULGU_DURUMU],
  ["test_case", CASE_DURUMLARI, CASE_DURUMU],
  ["script", SCRIPT_DURUMLARI, SCRIPT_DURUMU],
  ["bug_draft", BUG_DURUMLARI, BUG_DURUMU],
];

const sirali = (x: readonly string[]) => [...x].sort();

describe("portal durum birlikleri core makineleriyle aynı", () => {
  it.each(ESLEME)("%s", (ad, portal, etiketler) => {
    expect(M[ad], `core'da ${ad} makinesi yok`).toBeDefined();
    expect(sirali(portal)).toEqual(sirali(M[ad].states));
    expect(portal).toContain(M[ad].initial);
    // Her durumun Türkçe etiketi var, etiket haritasında core'da olmayan durum yok.
    expect(sirali(Object.keys(etiketler))).toEqual(sirali(M[ad].states));
  });
});

const CORE = resolve(__dirname, "../../../core");
const uvVar = (() => {
  if (!existsSync(resolve(CORE, "src/tp_core/workflow/states.py"))) return false;
  try {
    execFileSync("uv", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

describe("dışa aktarım güncel", () => {
  it.skipIf(!uvVar)("core'dan yeniden üretilen MACHINES dışa aktarımı depodakiyle aynı", () => {
    const cikti = execFileSync("uv", ["run", "--quiet", "--project", CORE, "python", resolve(__dirname, "../../scripts/durum_makineleri.py")], {
      encoding: "utf8",
      timeout: 60_000,
    });
    expect(JSON.parse(cikti), "core durumları değişti: `npm run sozlesme:durumlar` çalıştırın").toEqual(makineler);
  });
});

function durumlar(v: ReturnType<typeof ilkVeri>): Record<string, Set<string>> {
  return {
    requirement: new Set(v.gereksinimler.map((x) => x.durum)),
    consistency_finding: new Set(v.bulgular.map((x) => x.durum)),
    test_case: new Set(v.caseler.map((x) => x.durum)),
    script: new Set(v.scriptler.map((x) => x.durum)),
    bug_draft: new Set(v.bugTaslaklari.map((x) => x.durum)),
  };
}

describe("örnek veri yalnızca core durumlarını üretir", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("ilk veri", () => {
    for (const [ad, kume] of Object.entries(durumlar(ilkVeri()))) {
      for (const d of kume) expect(M[ad].states, `${ad}: ${d}`).toContain(d);
    }
  });

  it("akış boyunca (kod üretimi, kırma, merge, bug kararı) üretilen durumlar", async () => {
    const gorulen: Record<string, Set<string>> = {};
    const topla = () => {
      for (const [ad, kume] of Object.entries(durumlar(mockVerisi()))) {
        gorulen[ad] ??= new Set();
        kume.forEach((d) => gorulen[ad].add(d));
      }
    };
    // Arka plan adımları setTimeout zinciri: koşul sağlanana dek her adımda durumları topla.
    const izle = async (kosul: () => boolean) => {
      for (let i = 0; i < 500 && !kosul(); i++) {
        topla();
        await new Promise((r) => setTimeout(r, 1));
      }
      topla();
      expect(kosul()).toBe(true);
    };
    await oturumAc("muhendis");
    await api.kodUret(["case-1-2", "case-1-3", "case-1-1"]);
    // 009: örnek veride ayrıca uygulama platformlarının script'leri var (scr-and, scr-ios, scr-win);
    // 011: dil örnekleri (scr-java, scr-py).
    const ESKI = ["scr-1", "scr-2", "scr-3", "scr-and", "scr-ios", "scr-win", "scr-java", "scr-py"];
    const yeni = () => mockVerisi().scriptler.filter((s) => !ESKI.includes(s.id));
    await izle(() => yeni().length === 3 && yeni().every((s) => ["pr_open", "failed", "blocked"].includes(s.durum)));
    // 011: doğrulanmamış dil (Python) — verifying → unverified; başka dilde yeniden üretimde unverified → closed.
    await api.kodUret(["case-1-4"], "web", "python");
    const py = () => mockVerisi().scriptler.find((s) => s.case_ids.includes("case-1-4") && s.dil === "python");
    await izle(() => py()?.durum === "unverified");
    await api.kodUret(["case-1-4"], "web", "java");
    await izle(() => py()?.durum === "closed" && mockVerisi().scriptler.some((s) => s.case_ids.includes("case-1-4") && s.dil === "java" && s.durum === "pr_open"));
    await api.kirarakDogrula("scr-2");
    await izle(() => mockVerisi().scriptler.find((s) => s.id === "scr-2")!.break_verify.durum === "passed");
    await api.prBirlestir((await api.script("scr-2")).pr!);
    await api.logout();
    await oturumAc("testci");
    await api.bugKarari("bug-1", { icerik_hash: (await api.bugTaslagi("bug-1")).icerik_hash, karar: "dismiss", gerekce: "hata değil" });
    topla();
    for (const [ad, kume] of Object.entries(gorulen)) {
      for (const d of kume) expect(M[ad].states, `${ad}: ${d}`).toContain(d);
    }
    // Ara durumlar gerçekten gözlendi (test boşa geçmiyor).
    expect([...gorulen.script]).toEqual(expect.arrayContaining(["verifying", "checking", "pr_open", "merged", "failed", "blocked", "unverified", "closed"]));
    expect(gorulen.bug_draft.has("dismissed")).toBe(true);
  });
});

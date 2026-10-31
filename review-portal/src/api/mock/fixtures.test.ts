// Örnek verinin bağlayıcı kaynaklarla tutarlılığı: demo-app kaynak kodu, golden REPLAY kayıtları,
// jira-sim seed'i, page object'ler ve portal rotaları. Kaynak değişip örnek veri geride kalırsa
// (ör. campaign.py satırı kayarsa) bu testler kırılır.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import ts from "typescript";
import { api } from "../client";
import { baglantiTuru, uygulamaRotasiMi } from "../../lib/rotalar";
import type { Kanit } from "../types";
import { mockVerisi } from "./handlers";
import { goldenKoku, ilkVeri, KAMPANYA_KOD, KAMPANYA_TEST_KODU, KAYNAK, MIN_SIPARIS_VERI, refsiz, SEPET_TEST_KODU, TPD1_GOLDEN_CASELER } from "./fixtures";
import { oturumAc } from "../../test/yardimci";

const KOK = resolve(__dirname, "../../../..");
const yol = (...p: string[]) => resolve(KOK, ...p);
const json = (p: string) => JSON.parse(readFileSync(yol(p), "utf8")) as Record<string, unknown>;
const demoApp = existsSync(yol("demo-app/api/src/demoapp_api/campaign.py"));
const goldenVar = existsSync(yol("rules/replay/consistency_check/golden/TPD-1.json"));
const seedYolu = yol("sims/jira-sim/src/jira_sim/seed.py");
const e2eModulleri = existsSync(yol("demo-app/e2e/node_modules/@playwright/test"));

function tumKodKanitlari(): Extract<Kanit, { kind: "code" }>[] {
  const v = ilkVeri();
  return [...v.bulgular.flatMap((b) => b.evidence), KAMPANYA_KOD].filter((k): k is Extract<Kanit, { kind: "code" }> => k.kind === "code");
}

const pythonVar = (() => {
  try {
    execFileSync("python3", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

describe("golden/kaynaklar.json kopyası kaynaklarla aynı", () => {
  it.skipIf(!pythonVar || !goldenVar || !existsSync(seedYolu))("seed.py + golden'lardan yeniden üretilen JSON depodakiyle aynı", () => {
    const cikti = execFileSync("python3", ["-I", yol("review-portal/scripts/golden_esitle.py")], { encoding: "utf8", timeout: 30_000 });
    expect(JSON.parse(cikti), "kaynak değişti: `npm run sozlesme:golden` çalıştırın").toEqual(KAYNAK);
  });

  it.skipIf(!goldenVar)("kopyadaki golden çıktıları rules/replay dosyalarıyla birebir", () => {
    for (const [amac, kayitlar] of [
      ["requirement_review", KAYNAK.requirement_review],
      ["consistency_check", KAYNAK.consistency_check],
    ] as const) {
      for (const [ad, cikti] of Object.entries(kayitlar)) {
        expect(cikti, `${amac}/${ad}`).toEqual(json(`rules/replay/${amac}/golden/${ad}.json`).output);
      }
    }
  });
});

describe("örnek veri jira-sim seed'i ve golden çıktılarla çelişmez", () => {
  const v = ilkVeri();
  const jira = v.gereksinimler.filter((g) => g.kaynak === "jira");

  it("Jira story'lerinin başlık, açıklama ve AC'leri seed'den (TPD-1'de yalnızca kabul edilen golden önerileri)", () => {
    expect(jira.map((g) => g.jira_key)).toEqual(["TPD-1", "TPD-2", "TPD-3", "TPD-4"]);
    for (const g of jira) {
      const s = KAYNAK.jira_seed[g.jira_key!];
      expect([g.baslik, g.aciklama], g.jira_key!).toEqual([s.summary, s.aciklama]);
      // Jira'ya yazılan düzeltmeler: fix_doc kararlı bulguların karar metni AC'nin yeni hâli.
      const duzeltilen = new Map(
        v.bulgular
          .filter((b) => b.requirement_id === g.id && b.karar === "fix_doc" && b.durum === "resolved")
          .map((b) => [b.doc_ref.split(/\s*↔\s*/)[0], b.karar_metni]),
      );
      expect(g.kabul_kriterleri, g.jira_key!).toEqual(s.ac.map((a) => ({ ...a, metin: duzeltilen.get(a.ref) ?? a.metin })));
    }
    // TPD-3 ve TPD-4 metinleri seed'le harfiyen aynı (bulgu raporundaki kayma).
    expect(jira.find((g) => g.jira_key === "TPD-3")!.kabul_kriterleri[0].metin).toBe(
      "Bayi katalogda ürün adının bir bölümünü yazdığında yalnızca eşleşen ürünler listelenir.",
    );
    expect(jira.find((g) => g.jira_key === "TPD-4")!.kabul_kriterleri[0].metin).toBe(
      "Bayi geçerli kullanıcı adı ve parolayla giriş yaptığında ürün kataloğu açılır.",
    );
  });

  it("TPD-1 AC2/AC3 düzeltmesi golden önerisinin kendisi", () => {
    const tpd1 = jira.find((g) => g.jira_key === "TPD-1")!;
    const f = KAYNAK.consistency_check["TPD-1"].findings;
    expect(tpd1.kabul_kriterleri[1].metin).toBe(refsiz(f.find((x) => x.id === "F2")!.suggested_doc_text!));
    expect(tpd1.kabul_kriterleri[1].metin).toContain("(6 adette 1, 12 adette 2 bedava)");
    expect(tpd1.kabul_kriterleri[2].metin).toBe(refsiz(f.find((x) => x.id === "F3")!.suggested_doc_text!));
  });

  it("ön inceleme soruları ve verdict golden ile aynı küme ve metin (serbest metin: SERBEST)", () => {
    for (const g of v.gereksinimler) {
      if (!g.on_inceleme) continue;
      const kok = goldenKoku(g);
      const golden = kok ? KAYNAK.requirement_review[kok] : undefined;
      // Golden'ı olmayan çıktı REPLAY-MISS olmalı; olan ise REPLAY.
      expect(g.on_inceleme.mode, g.id).toBe(golden ? "replay" : "replay_miss");
      if (!golden) continue;
      expect(g.on_inceleme.verdict).toBe(golden.verdict);
      expect(g.on_inceleme.questions.map(({ cevap: _c, ...q }) => q), g.jira_key!).toEqual(golden.questions);
    }
    expect(jira.find((g) => g.jira_key === "TPD-1")!.on_inceleme!.questions).toHaveLength(4);
    expect(jira.find((g) => g.jira_key === "TPD-3")!.on_inceleme!.questions.map((q) => q.type)).toEqual(["ambiguity", "missing_ac"]);
  });

  it("her kontrol turunun bulguları o turun golden bulgularıyla aynı (bulgu yok demek de dahil)", () => {
    for (const g of v.gereksinimler) {
      const kok = goldenKoku(g) ?? `yok:${g.id}`;
      for (let tur = 1; tur <= g.kontrol_turu; tur++) {
        const ad = tur === 1 ? kok : `${kok}-r${tur}`;
        const golden = KAYNAK.consistency_check[ad];
        const ornek = v.bulgular.filter((b) => b.requirement_id === g.id && b.kontrol_turu === tur);
        if (!golden) {
          expect(ornek, `${ad}: golden yok, örnek veri bulgu uyduramaz`).toEqual([]);
          continue;
        }
        const beklenen = golden.findings.map((f) => ({
          type: f.type,
          doc_ref: f.doc_ref,
          ozet: f.observed,
          severity: f.severity,
          evidence: f.evidence,
          suggested_doc_text: f.suggested_doc_text === null ? null : refsiz(f.suggested_doc_text),
        }));
        const gercek = ornek.map((b) => ({
          type: b.type,
          doc_ref: b.doc_ref,
          ozet: b.ozet,
          severity: b.severity,
          // Veri kanıtına portal deterministik yeniden sorgunun önizlemesini ekler; golden alanları aynen.
          evidence: b.evidence.map((e) => (e.kind === "data" ? { kind: e.kind, query: e.query, result_digest: e.result_digest } : e)),
          suggested_doc_text: b.suggested_doc_text,
        }));
        const sirala = (x: { doc_ref: string; type: string }[]) => [...x].sort((a, b) => `${a.type}${a.doc_ref}`.localeCompare(`${b.type}${b.doc_ref}`));
        expect(sirala(gercek), ad).toEqual(sirala(beklenen));
      }
    }
    // TPD-3: "Bulgu yok" değil, main.py kanıtlı missing_in_code uyarısı.
    const tpd3 = v.bulgular.filter((b) => b.requirement_id === "req-tpd-3");
    expect(tpd3.map((b) => [b.type, b.severity])).toEqual([["missing_in_code", "warning"]]);
  });
});

describe("kanıtlar demo-app kaynağına karşılık gelir", () => {
  // Golden kanıt parçası satırın kodudur (girinti ve satır sonu yorumu hariç). Satır kayarsa golden
  // (rules lane) güncellenmeli; core gerçek koşuda kanıtı aynı şekilde yeniden çeker.
  it.skipIf(!demoApp)("her kod kanıtının dosyası var ve belirtilen satır kod parçasıyla başlar", () => {
    const kanitlar = tumKodKanitlari();
    expect(kanitlar.length).toBeGreaterThanOrEqual(3);
    const kaymalar: string[] = [];
    for (const k of kanitlar) {
      expect(k.repo).toBe("demo-app");
      const dosya = yol("demo-app", k.path);
      expect(existsSync(dosya), dosya).toBe(true);
      const satirlar = readFileSync(dosya, "utf8").split("\n");
      if (!(satirlar[k.line - 1] ?? "").trim().startsWith(k.snippet.trim())) {
        const gercek = satirlar.findIndex((s) => s.trim().startsWith(k.snippet.trim())) + 1;
        kaymalar.push(`${k.path}:${k.line} → ${gercek || "yok"} (${k.snippet.trim()})`);
      }
      expect(k.snippet.trim().length).toBeGreaterThan(5);
    }
    expect([...new Set(kaymalar)], "golden kanıt satırları demo-app ile kaymış").toEqual([]);
  });

  it("veri kanıtı golden sorgusuyla aynı", () => {
    const golden = KAYNAK.consistency_check["TPD-1"].findings.flatMap((f) => f.evidence);
    const veri = MIN_SIPARIS_VERI.kind === "data" ? MIN_SIPARIS_VERI.query : "";
    expect(golden.some((x) => x.kind === "data" && x.query === veri)).toBe(true);
  });
});

describe("case ve bug taslakları golden kayıtlardan", () => {
  it.skipIf(!goldenVar)("TPD-1 case içerikleri case_generation golden çıktısıyla birebir", () => {
    const g = json("rules/replay/case_generation/golden/TPD-1.json") as { output: { cases: unknown[] } };
    expect(TPD1_GOLDEN_CASELER).toEqual(g.output.cases);
  });

  it.skipIf(!goldenVar)("örnek veride TPD-1 case başlıklarının hepsi golden'dan; yalnızca insan düzeltmesi (edit) içerik değiştirir", () => {
    const basliklar = new Set(TPD1_GOLDEN_CASELER.map((c) => c.title));
    const caseler = ilkVeri().caseler.filter((c) => c.requirement_id === "req-tpd-1");
    expect(caseler).toHaveLength(TPD1_GOLDEN_CASELER.length);
    for (const c of caseler) expect(basliklar.has(c.icerik.title), c.icerik.title).toBe(true);
    for (const c of caseler) {
      const g = TPD1_GOLDEN_CASELER[c.sira_no - 1];
      expect(c.icerik.title).toBe(g.title);
      if (c.karar === "edit") expect(c.icerik).not.toEqual(g);
      else expect(c.icerik).toEqual(g);
    }
    expect(caseler.filter((c) => c.karar === "edit").map((c) => c.sira_no)).toEqual([3]);
  });

  it.skipIf(!goldenVar)("bug taslakları bug_draft golden özet/adım/beklenen ile aynı", () => {
    const v = ilkVeri();
    const eslesme: [string, string][] = [
      ["bug-1", "rules/replay/bug_draft/golden/break-campaign.json"],
      ["bug-2", "rules/replay/bug_draft/golden/credit-limit.json"],
    ];
    for (const [id, dosya] of eslesme) {
      const g = (json(dosya) as { output: { summary: string; steps: string[]; expected: string; actual: string; severity_suggestion: string } }).output;
      const b = v.bugTaslaklari.find((x) => x.id === id)!;
      expect(b.icerik.summary).toBe(g.summary);
      expect(b.icerik.steps).toEqual(g.steps.map((s) => s.replace(/^\d+\.\s*/, "")));
      expect([b.icerik.expected, b.icerik.actual, b.icerik.severity_suggestion]).toEqual([g.expected, g.actual, g.severity_suggestion]);
    }
  });
});

describe("Jira anahtarları jira-sim seed'iyle uyumlu", () => {
  function seedAnahtarlari(): Map<string, string> {
    const kaynak = readFileSync(seedYolu, "utf8");
    const m = new Map<string, string>();
    for (const x of kaynak.matchAll(/"key": "(TPD-\d+)",\s*"type": "\w+",\s*"summary": "([^"]+)"/g)) m.set(x[1], x[2]);
    return m;
  }

  it.skipIf(!existsSync(seedYolu))("mükerrer adayı seed'deki kayıt; oluşturulan anahtarlar TPD-8'den kesintisiz", () => {
    const seed = seedAnahtarlari();
    expect([...seed.keys()]).toEqual(["TPD-1", "TPD-2", "TPD-3", "TPD-4", "TPD-5", "TPD-6", "TPD-7"]);
    const v = ilkVeri();
    for (const b of v.bugTaslaklari) {
      for (const a of b.mukerrer_adaylari) {
        expect(seed.get(a.key), a.key).toBe(a.summary);
      }
    }
    expect(v.bugTaslaklari.find((b) => b.id === "bug-1")!.mukerrer_adaylari.map((a) => a.key)).toEqual(["TPD-5"]);
    for (const g of v.gereksinimler) if (g.jira_key) expect(seed.has(g.jira_key), g.jira_key).toBe(true);
    // Ürünün oluşturduğu kayıtlar (Test issue'ları, yayınlanan bug'lar) zaman sırasıyla TPD-8, 9, …
    const olusan = [
      ...v.bugTaslaklari.filter((b) => b.durum === "published").map((b) => ({ k: b.jira_key!, z: b.onay_zamani! })),
      ...v.caseler.filter((c) => c.jira_test_key).map((c) => ({ k: c.jira_test_key!, z: `${c.karar_zamani}#${c.sira_no}` })),
    ]
      .sort((a, b) => a.z.localeCompare(b.z))
      .map((x) => x.k);
    expect(olusan).toEqual(olusan.map((_, i) => `TPD-${8 + i}`));
    // Story/test anahtarı referansları ya seed'de ya da oluşturulanlar arasında.
    const bilinen = new Set([...seed.keys(), ...olusan]);
    for (const b of v.bugTaslaklari) {
      if (b.icerik.story_key) expect(bilinen.has(b.icerik.story_key)).toBe(true);
      if (b.icerik.test_case_key) expect(bilinen.has(b.icerik.test_case_key)).toBe(true);
    }
  });

  it("yeni yayın ve bug sıradaki anahtarı alır (seed + mevcutlar üstüne)", async () => {
    await oturumAc("testci");
    const b = await api.bugKarari("bug-1", { icerik_hash: (await api.bugTaslagi("bug-1")).icerik_hash, karar: "new" });
    expect(b.jira_key).toBe("TPD-12");
  });
});

describe("iç bağlantılar ölü değil", () => {
  /** Örnek verideki "/" ile başlayan her dizge (adres olarak kullanılabilecek her şey). */
  function yollar(x: unknown, yolAdi = "", cikti: [string, string][] = []): [string, string][] {
    if (typeof x === "string") {
      if (x.startsWith("/")) cikti.push([yolAdi, x]);
    } else if (Array.isArray(x)) {
      x.forEach((e, i) => yollar(e, `${yolAdi}[${i}]`, cikti));
    } else if (x && typeof x === "object") {
      for (const [k, e] of Object.entries(x)) yollar(e, `${yolAdi}.${k}`, cikti);
    }
    return cikti;
  }

  it("örnek verideki her mutlak yol bir portal ekranı ya da core /api adresi", () => {
    for (const [nerede, adres] of yollar(ilkVeri())) {
      expect(baglantiTuru(adres) !== "metin", `${nerede} = ${adres}`).toBe(true);
    }
  });

  it("her URL alanı null, sayfa içi çapa, http(s) ya da çözülen bir yol", () => {
    const v = ilkVeri();
    const adresler = [
      ...v.scriptler.map((s) => s.pr?.url ?? null),
      ...v.kosular.flatMap((k) => [k.allure_url, k.sauce_url, k.ci_url]),
      ...v.hatalar.flatMap((h) => h.kanit_linkleri.map((l) => l.url)),
      ...v.bugTaslaklari.flatMap((b) => b.icerik.evidence.map((e) => e.url)),
      ...v.gereksinimler.map((g) => g.jira_url),
    ];
    for (const a of adresler) {
      if (a === null) continue;
      expect(a.startsWith("#") || baglantiTuru(a) !== "metin", a).toBe(true);
    }
  });

  it("kırarak doğrulama, triage ve bug bağlantılarının hedefleri örnek veride var", () => {
    const v = ilkVeri();
    const kosu = new Set(v.kosular.map((k) => k.id));
    const hata = new Set(v.hatalar.map((h) => h.id));
    const bug = new Set(v.bugTaslaklari.map((b) => b.id));
    const kase = new Set(v.caseler.map((c) => c.id));
    for (const s of v.scriptler) {
      for (const a of s.break_verify.asamalar) if (a.run_id) expect(kosu.has(a.run_id), `${s.id} → ${a.run_id}`).toBe(true);
      for (const c of s.case_ids) expect(kase.has(c)).toBe(true);
      expect(uygulamaRotasiMi(`/kod/${s.id}`)).toBe(true);
    }
    for (const k of v.kosular) {
      for (const r of k.sonuclar) {
        if (r.failure_id) expect(hata.has(r.failure_id), r.failure_id).toBe(true);
        if (r.case_id) expect(kase.has(r.case_id), r.case_id).toBe(true);
      }
    }
    for (const h of v.hatalar) {
      expect(kosu.has(h.run_id)).toBe(true);
      if (h.oneri?.tur === "bug_draft") expect(bug.has(h.oneri.bug_draft_id)).toBe(true);
    }
    for (const b of v.bulgular) if (b.bug_draft_id) expect(bug.has(b.bug_draft_id)).toBe(true);
  });
});

describe("ajan adımları ve sayaçlar", () => {
  it("her script'in ajan adımları 1'den sıralı ve tekil; case adımı referansı ayrı", () => {
    for (const s of ilkVeri().scriptler) {
      expect(s.adimlar.map((a) => a.sira)).toEqual(s.adimlar.map((_, i) => i + 1));
      for (const a of s.adimlar) expect(a.step_id).toMatch(/^S\d+$/);
    }
  });

  it("gereksinim listesi ve Kontrol Kulesi karnesi aynı case sayısını gösterir", async () => {
    await oturumAc("sunucu");
    const [liste, kule] = await Promise.all([api.gereksinimler(), api.kontrolKulesi()]);
    for (const k of kule.karne) {
      const g = liste.find((x) => x.jira_key === k.story_key)!;
      expect(k.case_sayisi, k.story_key).toBe(g.sayaclar.case_toplam);
    }
    const tpd1 = liste.find((g) => g.jira_key === "TPD-1")!;
    // 9 golden case, 1 reddedildi → süitte 8; 4'ü onaylı/yayında.
    expect(tpd1.sayaclar).toMatchObject({ case_toplam: 8, case_onayli: 4 });
    // Henüz merge edilmiş script yok (scr-2 merge'e hazır, scr-1 zayıf test): otomasyon %0.
    expect(kule.karne.find((k) => k.story_key === "TPD-1")!.otomasyon_kapsami).toBe(0);
  });

  it("merge sonrası karne otomasyon kapsamı aynı case sayısına göre güncellenir", async () => {
    await oturumAc("muhendis");
    await api.prBirlestir((await api.script("scr-2")).pr!);
    const kule = await api.kontrolKulesi();
    expect(kule.karne.find((k) => k.story_key === "TPD-1")!.otomasyon_kapsami).toBeCloseTo(1 / 8);
    expect(mockVerisi().scriptler.find((s) => s.id === "scr-2")!.durum).toBe("merged");
  });
});

describe("üretilen test kodu gerçek page object'lerle derlenir", () => {
  const e2e = yol("demo-app/e2e");
  let tani: string[] = [];

  beforeAll(() => {
    if (!e2eModulleri) return;
    // Dosyalar diske yazılmaz: derleyici sanal olarak tests/tpd-1/ altına konmuş gibi görür.
    const sanal = new Map<string, string>([
      [resolve(e2e, "tests/tpd-1/__portal_ornek_c2.spec.ts"), KAMPANYA_TEST_KODU],
      [resolve(e2e, "tests/tpd-1/__portal_ornek_c1.spec.ts"), SEPET_TEST_KODU],
    ]);
    const secenekler: ts.CompilerOptions = {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      strict: true,
      noEmit: true,
      skipLibCheck: true,
      noUnusedLocals: true,
      noUncheckedIndexedAccess: true,
      types: ["node"],
      typeRoots: [resolve(e2e, "node_modules/@types")],
    };
    const ev = ts.createCompilerHost(secenekler);
    const host: ts.CompilerHost = {
      ...ev,
      fileExists: (f) => sanal.has(resolve(f)) || ev.fileExists(f),
      readFile: (f) => sanal.get(resolve(f)) ?? ev.readFile(f),
      getSourceFile: (f, dil, ...geri) => {
        const icerik = sanal.get(resolve(f));
        return icerik !== undefined ? ts.createSourceFile(f, icerik, dil) : ev.getSourceFile(f, dil, ...geri);
      },
      getCurrentDirectory: () => e2e,
    };
    const program = ts.createProgram([...sanal.keys()], secenekler, host);
    tani = ts
      .getPreEmitDiagnostics(program)
      .filter((d) => !d.file || sanal.has(resolve(d.file.fileName)) || d.file.fileName.startsWith(resolve(e2e, "pages")))
      .map((d) => `${d.file ? `${dirname(d.file.fileName)}/…:${d.file.getLineAndCharacterOfPosition(d.start ?? 0).line + 1}` : ""} ${ts.flattenDiagnosticMessageText(d.messageText, "\n")}`);
  }, 60_000);

  it.skipIf(!e2eModulleri)("KAMPANYA_TEST_KODU ve SEPET_TEST_KODU tsc hatasız (ekrandaki 'tsc ✓' doğru)", () => {
    expect(tani).toEqual([]);
  });

  it("yanlış imza yakalanır (test gerçekten derliyor)", () => {
    if (!e2eModulleri) return;
    const bozuk = KAMPANYA_TEST_KODU.replace('login.login("bayi1", "Demo123!")', 'login.loginAs("bayi1", "Demo123!")');
    const dosya = resolve(e2e, "tests/tpd-1/__portal_bozuk.spec.ts");
    const secenekler: ts.CompilerOptions = {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      strict: true,
      noEmit: true,
      skipLibCheck: true,
      types: [],
    };
    const ev = ts.createCompilerHost(secenekler);
    const host: ts.CompilerHost = {
      ...ev,
      fileExists: (f) => resolve(f) === dosya || ev.fileExists(f),
      readFile: (f) => (resolve(f) === dosya ? bozuk : ev.readFile(f)),
      getSourceFile: (f, dil, ...geri) => (resolve(f) === dosya ? ts.createSourceFile(f, bozuk, dil) : ev.getSourceFile(f, dil, ...geri)),
    };
    const program = ts.createProgram([dosya], secenekler, host);
    const mesajlar = ts.getPreEmitDiagnostics(program).map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
    expect(mesajlar.some((m) => m.includes("loginAs"))).toBe(true);
  }, 60_000);
});

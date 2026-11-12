// Örnek veri: üretim seçenekleri (011 K5) ve derinleştirme (P5/P6, K7) uçları.
//   GET  /requirements/{id}/generation-options  → kayıtlı son seçenekler + varsayılan + katalog
//   POST /requirements/{id}/deepen              → {tur, teknik?}; yalnız analist, yalnız cases_ready
//   GET  /requirements/{id}/deepen              → son derinleştirmenin durumu
// generate-cases gövdesinin doğrulaması/saklanması ve platform golden seçimi de buradadır
// (handlers.ts `caseUret` çağırır). Model çağrısı yoktur: çıktılar golden kopyasından
// (golden/kaynaklar.json `case_deepening`, `case_generation` `platform-*/<kök>`); kayıt yoksa
// REPLAY-MISS (core gibi: iş başarısız, sıfır case).
import { ApiError } from "../http";
import type {
  CaseUretimOzeti,
  DerinlestirmeDurumu,
  DerinlestirmeTeknigi,
  DerinlestirmeYaniti,
  GereksinimDetay,
  Kullanici,
  Rol,
  TestCase,
  TestCaseIcerik,
  UretimSecenekleri,
  UretimSecenekleriYaniti,
} from "../types";
import { uretimOzetiUyarla } from "../uyum";
import {
  derinlestirmeReplayAdi,
  EK_BILGI_ALANLARI,
  platformReplayAdi,
  secenekHatalari,
  seceneklerUyarla,
  URETIM_PLATFORMLARI,
  URETIM_TEST_SEVIYELERI,
  varsayilanSecenekler,
} from "../../lib/uretimSecenekleri";
import { goldenKoku, icerikHash, KAYNAK, type MockVeri } from "./fixtures";
import { mockOlayYayinla } from "./olaylar";

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

export const REPLAY_MISS_DERINLESTIRME = "REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok";
export const DERINLESTIRME_DURUM_HATASI = "Derinleştirme yalnız \"Case review aşamasında\" olan gereksinimde başlatılabilir.";
export const DERINLESTIRME_SURUYOR_HATASI = "Bu gereksinimde süren bir derinleştirme var; bitmesini bekleyin.";
const TEKNIKLER: DerinlestirmeTeknigi[] = ["EP", "BVA", "DT", "ST", "PW", "UC", "EG"];

/** handlers.ts iç yardımcıları (mock durumu tek yerde kalır). */
export interface MockBaglami {
  veri: () => MockVeri;
  girisGerekli: () => Kullanici;
  rolGerekli: (...roller: Rol[]) => Kullanici;
  gereksinim: (id: string) => GereksinimDetay;
  arkaPlan: (adimlar: (() => void)[]) => void;
  yeniId: (onek: string) => string;
  kaydet: () => void;
  denetimEkle: (eylem: string, nesne: string, ozet: string, aktor?: string) => void;
  gereksinimOlayi: (g: GereksinimDetay) => void;
}

// ------------------------------------------------------------------ üretim seçenekleri

/** `GET generation-options` (core biçimi). */
export function uretimSecenekleriYaniti(v: MockVeri, id: string): UretimSecenekleriYaniti {
  const kayitli = v.uretimSecenekleri?.[id];
  const kip = v.uretimKipleri?.[id];
  return {
    // D1: kayıtlı kip tercihi (core `kayitli.kip`); uyarlayıcı `kip` alanına çevirir.
    ...(kip ? ({ kayitli: { kip } } as object) : {}),
    secenekler: kayitli ? JSON.parse(JSON.stringify(kayitli)) : null,
    varsayilan: varsayilanSecenekler(),
    platformlar: [...URETIM_PLATFORMLARI],
    test_seviyeleri: [...URETIM_TEST_SEVIYELERI],
    ek_bilgi_alanlari: JSON.parse(JSON.stringify(EK_BILGI_ALANLARI)),
  };
}

/**
 * generate-cases gövdesindeki seçenekleri doğrular (core 422) ve tam nesneye tamamlar. Gövdede
 * seçenek alanı yoksa (gövdesiz / yalnız başka alan) null: eski davranış, hiçbir şey saklanmaz.
 */
export function uretimGovdesiniDogrula(govde: unknown): UretimSecenekleri | null {
  if (!govde || typeof govde !== "object" || Array.isArray(govde)) return null;
  const g = govde as Record<string, unknown>;
  const alanlar = ["platformlar", "test_seviyesi", "benimsenen_standartlar", "kapsam_disi", "roller", "ek_bilgi"];
  if (!alanlar.some((k) => k in g)) return null;
  const tipHatasi =
    ("platformlar" in g && !(Array.isArray(g.platformlar) && g.platformlar.every((x) => typeof x === "string"))) ||
    ("benimsenen_standartlar" in g && !(Array.isArray(g.benimsenen_standartlar) && g.benimsenen_standartlar.every((x) => typeof x === "string"))) ||
    ("test_seviyesi" in g && typeof g.test_seviyesi !== "string") ||
    ("kapsam_disi" in g && typeof g.kapsam_disi !== "string") ||
    ("roller" in g && typeof g.roller !== "string") ||
    ("ek_bilgi" in g && (!g.ek_bilgi || typeof g.ek_bilgi !== "object" || Array.isArray(g.ek_bilgi)));
  if (tipHatasi) throw new ApiError(422, "Üretim seçenekleri geçersiz: alan tipleri uymuyor.");
  const hatalar = secenekHatalari(g as Partial<UretimSecenekleri>);
  if (hatalar.length) throw new ApiError(422, `Üretim seçenekleri geçersiz — ${hatalar.join(" ")}`);
  return seceneklerUyarla(g);
}

/**
 * Platform seçilen üretimin golden adı (core `platform-<ekler>/<kök>`); platform yoksa null.
 * Kök yoksa (golden'ı olmayan serbest metin) adı yine kurulur: kayıt bulunmaz → REPLAY-MISS.
 */
export function platformGoldenAdi(g: Pick<GereksinimDetay, "jira_key" | "aciklama">, platformlar: string[]): string | null {
  return platformReplayAdi(platformlar, goldenKoku(g) ?? "SERBEST-YOK");
}

/** Platform golden kaydı: ad kayıtlıysa ve (beyan varsa) güncel AC'ler girdiyle birebir aynıysa. */
export function platformGoldeni(ad: string, g: Pick<GereksinimDetay, "kabul_kriterleri">): TestCaseIcerik[] | undefined {
  const k = KAYNAK.case_generation[ad];
  if (!k) return undefined;
  const acler = g.kabul_kriterleri.map((a) => `${a.ref}: ${a.metin}`);
  if (k.girdi_ac.length > 0 && (k.girdi_ac.length !== acler.length || k.girdi_ac.some((x, i) => x !== acler[i]))) return undefined;
  return JSON.parse(JSON.stringify(k.cases)) as TestCaseIcerik[];
}

export const PLATFORM_REPLAY_MISS = (ad: string) =>
  `REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok (${ad}); canlı model gerekir. Case'ler IDE (Claude Code) kanalından gönderilebilir.`;

// ------------------------------------------------------------------ derinleştirme

/** case_deepening golden kopyası (kaynaklar.json'da anahtar yoksa boş). */
export function derinlestirmeGoldenlari(): NonNullable<typeof KAYNAK.case_deepening> {
  return KAYNAK.case_deepening ?? {};
}

/** Sıradaki üretim numarası: kayıtlı üretimlerin ve case'lerin en büyüğü + 1. */
function sonrakiUretimNo(v: MockVeri, id: string): number {
  const nolar = [
    ...(v.caseUretimleri?.[id] ?? []).map((u) => u.uretim_no),
    ...v.caseler.filter((c) => c.requirement_id === id).map((c) => c.uretim_no ?? 1),
  ];
  return Math.max(0, ...nolar) + 1;
}

function govdeDogrula(govde: unknown): { tur: "negatif" | "teknik"; teknik: DerinlestirmeTeknigi | null } {
  const g = (govde && typeof govde === "object" ? govde : {}) as { tur?: unknown; teknik?: unknown };
  if (g.tur !== "negatif" && g.tur !== "teknik") throw new ApiError(422, "tur 'negatif' ya da 'teknik' olmalı.");
  if (g.tur === "negatif") {
    if (g.teknik !== undefined && g.teknik !== null) throw new ApiError(422, "teknik yalnız tur=teknik ile gönderilir.");
    return { tur: "negatif", teknik: null };
  }
  if (typeof g.teknik !== "string" || !TEKNIKLER.includes(g.teknik as DerinlestirmeTeknigi)) {
    throw new ApiError(422, `tur=teknik için teknik zorunlu: ${TEKNIKLER.join(", ")}.`);
  }
  return { tur: "teknik", teknik: g.teknik as DerinlestirmeTeknigi };
}

function derinlestir(b: MockBaglami, id: string, govde: unknown): DerinlestirmeYaniti {
  b.rolGerekli("analyst");
  const g = b.gereksinim(id);
  const { tur, teknik } = govdeDogrula(govde);
  const v = b.veri();
  if (g.durum !== "cases_ready") throw new ApiError(409, DERINLESTIRME_DURUM_HATASI);
  if (v.derinlestirmeler?.[id]?.durum === "calisiyor") throw new ApiError(409, DERINLESTIRME_SURUYOR_HATASI);
  const uretimNo = sonrakiUretimNo(v, id);
  const durum: DerinlestirmeDurumu = { durum: "calisiyor", tur, teknik, uretim_no: uretimNo, yeni_case_sayisi: null, uyarilar: [], hata: null };
  (v.derinlestirmeler ??= {})[id] = durum;
  b.denetimEkle("cases.deepen", g.id, `Derinleştirme başlatıldı: ${tur}${teknik ? ` (${teknik})` : ""}`);
  b.kaydet();
  const ad = derinlestirmeReplayAdi(tur, teknik, goldenKoku(g) ?? "SERBEST-YOK");
  b.arkaPlan([
    () => {
      const kayit = derinlestirmeGoldenlari()[ad];
      // Gereksinim arada değiştiyse (ör. yeniden üretim) sonuç eklenmez.
      const guncel = b.veri().derinlestirmeler?.[id];
      if (!guncel || guncel !== durum) return;
      if (!kayit) {
        Object.assign(durum, { durum: "hata", yeni_case_sayisi: 0, uyarilar: [REPLAY_MISS_DERINLESTIRME], hata: REPLAY_MISS_DERINLESTIRME });
        b.denetimEkle("ai_call", g.id, `Derinleştirme: ${REPLAY_MISS_DERINLESTIRME} (${ad})`, "core-worker");
        b.gereksinimOlayi(g);
        return;
      }
      const vv = b.veri();
      const mevcut = vv.caseler.filter((c) => c.requirement_id === id).length;
      const icerikler = JSON.parse(JSON.stringify(kayit.cases)) as TestCaseIcerik[];
      icerikler.forEach((icerik, i) => {
        const tc: TestCase = {
          id: b.yeniId("case"),
          requirement_id: id,
          jira_key: g.jira_key,
          sira_no: mevcut + i + 1,
          kanal: "portal",
          surum: 1,
          icerik,
          durum: "draft",
          karar: null,
          ret_nedeni: null,
          karar_veren: null,
          karar_zamani: null,
          duzeltme_olcusu: null,
          icerik_hash: icerikHash(icerik),
          onaylanan_hash: null,
          ai_generated: true,
          ai_sure_ms: 4800 + i * 300,
          review_sure_ms: null,
          maliyet_usd: 0,
          jira_test_key: null,
          mode: "replay",
          uretim_no: uretimNo,
        };
        vv.caseler.push(tc);
        mockOlayYayinla({ type: "case.generated", id: tc.id, data: { requirement_id: id, title: icerik.title } });
      });
      const ozet: CaseUretimOzeti = uretimOzetiUyarla({ ...(kayit.ozet ?? {}), uretim_no: uretimNo, kanal: "portal", tur });
      (vv.caseUretimleri ??= {})[id] = [...(vv.caseUretimleri?.[id] ?? []), ozet];
      Object.assign(durum, { durum: "tamam", yeni_case_sayisi: icerikler.length, uyarilar: [], hata: null });
      b.denetimEkle("ai_call", g.id, `Derinleştirme: ${icerikler.length} yeni taslak (replay, ${ad})`, "core-worker");
      // Gereksinim cases_ready'de kalır (K7); sayaçlar ve olay güncellenir.
      b.gereksinimOlayi(g);
    },
  ]);
  return { job_id: b.yeniId("job"), workflow_id: b.yeniId("wf"), uretim_no: uretimNo, durum: "started", mesaj: "Derinleştirme başlatıldı." };
}

function derinlestirmeDurumu(b: MockBaglami, id: string): DerinlestirmeDurumu {
  b.girisGerekli();
  b.gereksinim(id);
  const d = b.veri().derinlestirmeler?.[id];
  return d
    ? { ...d, uyarilar: [...d.uyarilar] }
    : { durum: "yok", tur: null, teknik: null, uretim_no: null, yeni_case_sayisi: null, uyarilar: [], hata: null };
}

export function derinlestirmeRotalari(b: MockBaglami): Rota[] {
  return [
    [
      "GET",
      /^\/requirements\/([^/]+)\/generation-options$/,
      (m) => {
        b.girisGerekli();
        const id = decodeURIComponent(m[1]);
        b.gereksinim(id);
        return uretimSecenekleriYaniti(b.veri(), id);
      },
    ],
    ["POST", /^\/requirements\/([^/]+)\/deepen$/, (m, _q, g) => derinlestir(b, decodeURIComponent(m[1]), g)],
    ["GET", /^\/requirements\/([^/]+)\/deepen$/, (m) => derinlestirmeDurumu(b, decodeURIComponent(m[1]))],
  ];
}

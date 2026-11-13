// 013 sprint otomasyonu (specs/013-sprint-otomasyonu §3.1–§3.4): toplu onay, otomatik kod, test verisi
// kataloğu ve Jira tetiği yanıtlarının portal biçimine uyarlanması. Bu modül uyum.ts'e bağlı değildir
// (uyum.ts case uyarlamasında buradan alır; döngüsel içe aktarma yok).
import type {
  AtifYapanCase,
  CaseVeriAtfi,
  JiraTetikDurumu,
  JiraTetikTurSonucu,
  KodUretimIsi,
  OtomasyonAyarlari,
  OtomatikAkis,
  OtomatikKodSonucu,
  Script,
  TestCase,
  TestVerisi,
  TestVerisiSurumu,
  TopluKararSonucu,
  TopluKararYaniti,
  TopluOtomatikKod,
} from "./types";

type Ham = Record<string, unknown>;
const nesneMi = (x: unknown): x is Ham => !!x && typeof x === "object" && !Array.isArray(x);
const metin = (x: unknown, v = ""): string => (typeof x === "string" ? x : v);
const metinYaDaNull = (x: unknown): string | null => (typeof x === "string" && x !== "" ? x : null);
const sayi = (x: unknown, v = 0): number => (typeof x === "number" && Number.isFinite(x) ? x : v);
const sayiYaDaNull = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const kimlik = (x: unknown): string => (typeof x === "string" || typeof x === "number" ? String(x) : "");
const dizi = (x: unknown): Ham[] => (Array.isArray(x) ? x.filter(nesneMi) : []);

/** core testveri: gizli kaydın ortam sırrı adı. */
export const SIR_ADI_RE = /^TP_TESTVERI_[A-Z0-9_]+$/;
/** core atif.py ANAHTAR_DESEN ile aynı: `[a-z0-9_]+(\.[a-z0-9_]+){0,5}`. */
export const ANAHTAR_DESENI = "[a-z0-9_]+(?:\\.[a-z0-9_]+){0,5}";
export const ANAHTAR_RE = new RegExp(`^${ANAHTAR_DESENI}$`);
/** Metindeki `{veri:anahtar}` atıfları (global; her kullanımda yeni örnek alın). */
export const atifDeseni = () => new RegExp(`\\{veri:(${ANAHTAR_DESENI})\\}`, "g");
export const atifMetni = (anahtar: string) => `{veri:${anahtar}}`;

/** Metni düz metin ve atıf parçalarına böler (sırayla). */
export function atifParcalari(m: string | null | undefined): ({ tur: "metin"; metin: string } | { tur: "atif"; anahtar: string })[] {
  const parcalar: ({ tur: "metin"; metin: string } | { tur: "atif"; anahtar: string })[] = [];
  if (!m) return parcalar;
  let son = 0;
  for (const e of m.matchAll(atifDeseni())) {
    const i = e.index ?? 0;
    if (i > son) parcalar.push({ tur: "metin", metin: m.slice(son, i) });
    parcalar.push({ tur: "atif", anahtar: e[1] });
    son = i + e[0].length;
  }
  if (son < m.length) parcalar.push({ tur: "metin", metin: m.slice(son) });
  return parcalar;
}

const OTOKOD_DURUMLARI = new Set(["kuyrukta", "reddedildi", "kapali", "atlandi", "hata"]);

export function otomatikKodUyarla(x: unknown): OtomatikKodSonucu | null {
  if (!nesneMi(x)) return null;
  const d = metin(x.durum);
  if (!OTOKOD_DURUMLARI.has(d)) return null;
  return { durum: d as OtomatikKodSonucu["durum"], neden: metinYaDaNull(x.neden), script_id: metinYaDaNull(kimlik(x.script_id)) };
}

/** `veri: {anahtar: {deger, gizli, surum, var}}`; nesne değilse `undefined` (alan eklenmez). */
export function caseVeriUyarla(x: unknown): Record<string, CaseVeriAtfi> | undefined {
  if (!nesneMi(x)) return undefined;
  const out: Record<string, CaseVeriAtfi> = {};
  for (const [anahtar, v] of Object.entries(x)) {
    const k = nesneMi(v) ? v : {};
    out[anahtar] = {
      deger: typeof k.deger === "string" ? k.deger : null,
      gizli: k.gizli === true,
      surum: sayiYaDaNull(k.surum),
      var: k.var !== false && nesneMi(v),
    };
  }
  return out;
}

/** `onay_engeli`: metin (neden) ya da bool; boş/false → null. */
export function onayEngeliUyarla(x: unknown): string | null {
  if (typeof x === "string") return x.trim() ? x : null;
  if (x === true) return "Bu case'in onayına engel var.";
  if (nesneMi(x)) return metinYaDaNull(x.neden) ?? metinYaDaNull(x.mesaj) ?? "Bu case'in onayına engel var.";
  return null;
}

/** Case uyarlayıcısına eklenen 013 alanları (yalnız core gönderdiyse). */
export function caseOtomasyonAlanlari(c: Ham): Pick<TestCase, "goruldu" | "onay_engeli" | "veri" | "otomatik_kod" | "veri_onaydan_sonra_degisen"> {
  const veri = caseVeriUyarla(c.veri);
  const degisen = Array.isArray(c.veri_onaydan_sonra_degisen)
    ? c.veri_onaydan_sonra_degisen.filter((x): x is string => typeof x === "string" && x !== "")
    : null;
  return {
    ...(degisen && degisen.length > 0 ? { veri_onaydan_sonra_degisen: degisen } : {}),
    ...(typeof c.goruldu === "boolean" ? { goruldu: c.goruldu } : {}),
    ...(c.onay_engeli !== undefined ? { onay_engeli: onayEngeliUyarla(c.onay_engeli) } : {}),
    ...(veri ? { veri } : {}),
    ...(c.otomatik_kod !== undefined ? { otomatik_kod: otomatikKodUyarla(c.otomatik_kod) } : {}),
  };
}

/**
 * Script uyarlayıcısına eklenen 013 alanları (yalnız core gönderdiyse). §9: `veri_izi` değer özeti
 * taşır (`{anahtar: "<sha256[:12]>"}`); özet ekranda gösterilmez, yalnız anahtarlar kullanılır.
 * `veri_degisti` gelmezse `veri_degisen`den türetilir.
 */
export function scriptOtomasyonAlanlari(s: Ham): Pick<Script, "tetik" | "veri_degisti" | "veri_izi" | "veri_degisen"> {
  const iz: Record<string, string> = {};
  if (nesneMi(s.veri_izi)) for (const [k, v] of Object.entries(s.veri_izi)) if (typeof v === "string" || typeof v === "number") iz[k] = String(v);
  const degisen = Array.isArray(s.veri_degisen) ? s.veri_degisen.filter((x): x is string => typeof x === "string" && x !== "") : null;
  const degisti = typeof s.veri_degisti === "boolean" ? s.veri_degisti : degisen ? degisen.length > 0 : undefined;
  return {
    ...(s.tetik === "otomatik" || s.tetik === "elle" ? { tetik: s.tetik } : {}),
    ...(degisti !== undefined ? { veri_degisti: degisti } : {}),
    ...(nesneMi(s.veri_izi) ? { veri_izi: iz } : {}),
    ...(degisen ? { veri_degisen: degisen } : {}),
  };
}

const AKIS_DURUMLARI = new Set(["suruyor", "durdu", "tamam"]);

/** Gereksinim `otomatik_akis` (013 §9); geçersiz/eksikse null. */
export function otomatikAkisUyarla(x: unknown): OtomatikAkis | null {
  if (!nesneMi(x)) return null;
  const d = metin(x.durum);
  if (!AKIS_DURUMLARI.has(d)) return null;
  return { tetik_zamani: metinYaDaNull(x.tetik_zamani), durum: d as OtomatikAkis["durum"], neden: metinYaDaNull(x.neden) };
}

const TOPLU_OTOKOD = new Set(["kuyrukta", "kapali", "yok"]);

/** Toplu onay yanıtının üst düzey `otomatik_kod`u (K16); yoksa ya da tanınmazsa null. */
export function topluOtomatikKodUyarla(x: unknown): TopluOtomatikKod | null {
  if (!nesneMi(x)) return null;
  const d = metin(x.durum);
  if (!TOPLU_OTOKOD.has(d)) return null;
  const atlanan = Array.isArray(x.atlanan)
    ? dizi(x.atlanan).map((a) => ({ case_id: kimlik(a.case_id), neden: metinYaDaNull(a.neden) })).filter((a) => a.case_id !== "")
    : undefined;
  return {
    durum: d as TopluOtomatikKod["durum"],
    job_id: metinYaDaNull(kimlik(x.job_id)),
    case_sayisi: sayi(x.case_sayisi),
    ...(atlanan ? { atlanan } : {}),
  };
}

/** core iş durumu (queued/running/retry/done/failed/cancelled) ya da Türkçe karşılığı → portal durumu. */
const IS_DURUMU: Record<string, KodUretimIsi["durum"]> = {
  queued: "kuyrukta",
  retry: "kuyrukta",
  kuyrukta: "kuyrukta",
  running: "calisiyor",
  calisiyor: "calisiyor",
  done: "tamam",
  tamam: "tamam",
  failed: "hata",
  cancelled: "hata",
  hata: "hata",
};

/**
 * `GET /automation/codegen-jobs/{job_id}`: toplu onayın kod üretimi işi. Sonuç alanları üst düzeyde
 * ya da `sonuc` içinde gelebilir (`{case_sayisi, ozet, sonuclar[{case_id, durum, neden, script_id}]}`).
 */
export function kodUretimIsiUyarla(govde: unknown, jobId = ""): KodUretimIsi {
  const g = nesneMi(govde) ? govde : {};
  const ic = nesneMi(g.sonuc) ? g.sonuc : g;
  const sonuclar = dizi(ic.sonuclar).map((o) => {
    const ok = otomatikKodUyarla(o);
    return {
      case_id: kimlik(o.case_id),
      durum: ok?.durum ?? ("hata" as const),
      neden: ok ? ok.neden : metinYaDaNull(o.neden),
      script_id: ok ? ok.script_id : null,
    };
  });
  const ozet: Record<string, number> = {};
  if (nesneMi(ic.ozet)) {
    for (const [k, v] of Object.entries(ic.ozet)) if (typeof v === "number") ozet[k] = v;
  } else {
    for (const o of sonuclar) ozet[o.durum] = (ozet[o.durum] ?? 0) + 1;
  }
  return {
    job_id: metinYaDaNull(kimlik(g.job_id ?? g.id)) ?? jobId,
    durum: IS_DURUMU[metin(g.durum)] ?? (sonuclar.length ? "tamam" : "kuyrukta"),
    case_sayisi: sayi(ic.case_sayisi, sonuclar.length),
    ozet,
    sonuclar,
    hata: metinYaDaNull(g.hata) ?? metinYaDaNull(g.son_hata),
  };
}

const TOPLU_DURUMLAR = new Set(["onaylandi", "atlandi", "hata"]);

export function topluKararUyarla(govde: unknown): TopluKararYaniti {
  const g = nesneMi(govde) ? govde : {};
  const sonuclar: TopluKararSonucu[] = dizi(g.sonuclar).map((s) => {
    const d = metin(s.durum);
    return {
      case_id: kimlik(s.case_id),
      durum: (TOPLU_DURUMLAR.has(d) ? d : "hata") as TopluKararSonucu["durum"],
      neden: metinYaDaNull(s.neden),
      otomatik_kod: otomatikKodUyarla(s.otomatik_kod),
    };
  });
  const o = nesneMi(g.ozet) ? g.ozet : null;
  const say = (d: TopluKararSonucu["durum"]) => sonuclar.filter((s) => s.durum === d).length;
  return {
    sonuclar,
    ozet: {
      onaylandi: o ? sayi(o.onaylandi, say("onaylandi")) : say("onaylandi"),
      atlandi: o ? sayi(o.atlandi, say("atlandi")) : say("atlandi"),
      hata: o ? sayi(o.hata, say("hata")) : say("hata"),
    },
    otomatik_kod: topluOtomatikKodUyarla(g.otomatik_kod),
  };
}

export function testVerisiUyarla(x: Ham): TestVerisi {
  const gizli = x.gizli === true;
  return {
    id: kimlik(x.id),
    anahtar: metin(x.anahtar),
    grup: metinYaDaNull(x.grup),
    aciklama: metinYaDaNull(x.aciklama),
    // Gizli kaydın değeri hiçbir koşulda gösterilmez (core null gönderir; yine de süzülür).
    deger: gizli ? null : typeof x.deger === "string" ? x.deger : null,
    gizli,
    sir_adi: metinYaDaNull(x.sir_adi),
    sir_tanimli: x.sir_tanimli === true,
    surum: sayi(x.surum, 1),
    guncelleyen: metinYaDaNull(x.guncelleyen),
    guncelleme: metinYaDaNull(x.guncelleme),
    kullanim: sayi(x.kullanim),
  };
}

export function testVerileriUyarla(govde: unknown): TestVerisi[] {
  const liste = Array.isArray(govde) ? govde : nesneMi(govde) ? (govde.kayitlar ?? govde.items) : [];
  return dizi(liste).map(testVerisiUyarla);
}

const ISLEMLER = new Set(["olustur", "guncelle", "sil"]);

export function surumlerUyarla(govde: unknown): TestVerisiSurumu[] {
  const liste = Array.isArray(govde) ? govde : nesneMi(govde) ? (govde.surumler ?? govde.items) : [];
  return dizi(liste)
    .map((s) => {
      const islem = metin(s.islem);
      const gizli = s.gizli === true;
      return {
        surum: sayi(s.surum),
        islem: (ISLEMLER.has(islem) ? islem : "guncelle") as TestVerisiSurumu["islem"],
        deger: gizli ? null : typeof s.deger === "string" ? s.deger : null,
        gizli,
        sir_adi: metinYaDaNull(s.sir_adi),
        degistiren: metinYaDaNull(s.degistiren),
        zaman: metinYaDaNull(s.zaman),
      };
    })
    .sort((a, b) => b.surum - a.surum);
}

/**
 * Silme 409'unun atıf yapan case listesi. Core (Ş3): `{detail, kod: "cakisma", kullanan: [{case_id,
 * case_ref, baslik, durum}]}`; eski/alternatif adlar (`caseler`, `atif_yapanlar`, `cases`, `detail` içinde) da okunur.
 */
export function atifYapanlarUyarla(govde: unknown): AtifYapanCase[] {
  const g = nesneMi(govde) ? govde : {};
  const d = nesneMi(g.detail) ? g.detail : {};
  const ham = [g, d].map((o) => o.kullanan ?? o.caseler ?? o.atif_yapanlar ?? o.cases).find(Array.isArray);
  return dizi(ham).map((c) => ({
    id: kimlik(c.case_id ?? c.id),
    case_ref: metinYaDaNull(c.case_ref),
    durum: metinYaDaNull(c.durum),
    requirement_id: metinYaDaNull(kimlik(c.requirement_id)),
    jira_key: metinYaDaNull(c.jira_key),
    sira_no: sayiYaDaNull(c.sira_no),
    baslik: metin(c.baslik ?? c.title, ""),
  }));
}

/** K23: ayar gövdesinden REPLAY kipi (`replay: bool` ya da `model_kipi: "replay"|…`); yoksa undefined. */
function replayKipi(g: Record<string, unknown>): boolean | undefined {
  if (typeof g.replay === "boolean") return g.replay;
  const kip = typeof g.model_kipi === "string" ? g.model_kipi : nesneMi(g.model_kipi) && typeof g.model_kipi.mod === "string" ? g.model_kipi.mod : null;
  return kip ? kip.trim().toLowerCase() === "replay" : undefined;
}

export function otomasyonAyarlariUyarla(govde: unknown): OtomasyonAyarlari {
  const g = nesneMi(govde) ? govde : {};
  const k = nesneMi(g.otomatik_kod_uretimi) ? g.otomatik_kod_uretimi : {};
  const j = nesneMi(g.jira_tetik) ? g.jira_tetik : {};
  const replay = replayKipi(g);
  return {
    ...(replay !== undefined ? { replay } : {}),
    // K14: eksik ya da bozuk `acik` açık sayılmaz (bilinmiyorsa kapalı gösterilir).
    otomatik_kod_uretimi: { acik: k.acik === true, guncelleyen: metinYaDaNull(k.guncelleyen), guncelleme: metinYaDaNull(k.guncelleme) },
    jira_tetik: {
      acik: j.acik === true,
      durum: metin(j.durum, "QA To Do") || "QA To Do",
      aralik_s: sayi(j.aralik_s, 60),
      otomatik_case: j.otomatik_case === true,
      guncelleyen: metinYaDaNull(j.guncelleyen),
      guncelleme: metinYaDaNull(j.guncelleme),
    },
  };
}

export function jiraTetikDurumuUyarla(govde: unknown): JiraTetikDurumu {
  const g = nesneMi(govde) ? govde : {};
  const t = nesneMi(g.son_tur) ? g.son_tur : null;
  const taban =
    typeof g.taban_bekleniyor === "boolean" ? g.taban_bekleniyor : typeof g.taban_kurulu === "boolean" ? g.acik === true && !g.taban_kurulu : undefined;
  return {
    ...(taban !== undefined ? { taban_bekleniyor: taban } : {}),
    acik: g.acik === true,
    durum: metin(g.durum, "QA To Do") || "QA To Do",
    aralik_s: sayi(g.aralik_s, 60),
    son_tur: t
      ? {
          zaman: metinYaDaNull(t.zaman),
          bulunan: sayi(t.bulunan),
          tetiklenen: sayi(t.tetiklenen),
          ertelenen: sayi(t.ertelenen),
          taban: t.taban === true,
          hata: metinYaDaNull(t.hata),
          sonuclar: dizi(t.sonuclar).map(
            (r): JiraTetikTurSonucu => ({ jira_key: metin(r.jira_key), sonuc: metin(r.sonuc), neden: metinYaDaNull(r.neden) }),
          ),
        }
      : null,
    son_tetiklenenler: dizi(g.son_tetiklenenler).map((s) => ({
      jira_key: metin(s.jira_key),
      zaman: metinYaDaNull(s.zaman),
      sonuc: metinYaDaNull(s.sonuc),
      neden: metinYaDaNull(s.neden),
    })),
  };
}

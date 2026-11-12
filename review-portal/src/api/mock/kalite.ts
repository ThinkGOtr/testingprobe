// 012 Ş7 — mock arka uç: karar tabloları, metamorfik ilişkiler, beklenen sonuç kontrolü (oracle)
// ve onay kapısı (specs/012 ANALIZ §4.1, §4.3, §4.5, §6). Sözleşmedeki gibi davranır: roller, hash
// çakışması (409), 422 `karar_tablosu_gecersiz` / `oracle_uyumsuz`, 409 `oracle_bekleniyor`, durum
// makinesi ve §4.3 kapı tablosu. Durum `MockVeri.kalite` altında tutulur (oturum deposuna ve demo
// sıfırlamaya handlers.ts'in mevcut yolu ile girer).
import { ApiError } from "../http";
import type {
  BeklentiDogrulugu,
  CaseKararGirdisi,
  CaseMetrikleri,
  CaseOracle,
  CiktiModu,
  GereksinimDetay,
  KaliteTaslakIsi,
  KaliteTaslakYaniti,
  KaliteGecisi,
  KararTablosu,
  KararTablosuDurumu,
  KararTablosuIcerik,
  Kullanici,
  MetamorfikIliski,
  MetamorfikIliskiIcerik,
  OracleIstisnasi,
  OracleKarsilastirma,
  OracleSonucu,
  Rol,
  TabloDegerlendirmesi,
  TestCase,
  TestCaseIcerik,
  TuretmeAtlamaSonucu,
  TuretmeYaniti,
} from "../types";
import { kanonikJson, sha256Hex } from "../../lib/sha256";
import { icerikHash, type MockVeri } from "./fixtures";
import {
  adGecerli,
  ayristir,
  degerYaz,
  esitMi,
  hesapla,
  IfadeHatasi,
  sayiAyristir,
  sayiBicimle,
  turCikar,
  type Dugum,
  type IfadeDegeri,
  type IfadeTuru,
} from "./kaliteIfade";
import { CIKARMA_KURALLARI, ILK_ILISKILER, ILK_TABLOLAR, KALITE_REQ, taslakCiktisi } from "./kaliteVerisi";
import { mockOlayYayinla } from "./olaylar";

// ------------------------------------------------------------------ durum

/** İç kayıt: yanıt öğesi + onay anındaki gereksinim hash'i (yanıta girmez; `bayat` ondan hesaplanır). */
type TabloKaydi = Omit<KararTablosu, "bayat"> & { gereksinim_hash: string | null };
type IliskiKaydi = Omit<MetamorfikIliski, "bayat"> & { gereksinim_hash: string | null };

interface Olgu {
  column: string;
  value: IfadeDegeri;
  field: string;
  quote: string;
  index: number;
}

interface Grup {
  tablo_id: string;
  tablo_ad: string;
  satir_id: string | null;
  girdiler: Olgu[];
  karsilastirmalar: OracleKarsilastirma[];
  /** Seçilen satırda eksik girdiye dayanan çıktıların beklenen olguları (sonuca girmez; çekirdek aynı adla). */
  karsilastirilamayan: (Omit<Olgu, "index"> & { neden: string })[];
  durum: "uyumlu" | "uyumsuz" | "cikarilamadi" | "satir_yok" | "hata" | "karsilastirma_yok";
  neden: string | null;
}

export interface OracleKaydi {
  test_case_id: string;
  icerik_hash: string;
  sonuc: OracleSonucu;
  ozet: string;
  ayrintilar: { gruplar: Grup[]; atilan_olgular: number };
  /** Kontrolde kullanılan tabloların kimlik + içerik hash imzası (tablolar değişince kayıt eskir). */
  tablo_imzasi: string;
  /** AI'ın ürettiği (insan düzeltmesinden önceki) içerik mi (§4.7 metriği bunları sayar). */
  ai_icerik: boolean;
  istisna: OracleIstisnasi | null;
  olusturma: string;
}

/** `metamorfik_turetme` satırı (§5). */
interface TuretmeKaydi {
  id?: string;
  olusturan_id?: string | null;
  olusturma?: string;
  iliski_id: string;
  kaynak_case_id: string;
  sonuc: TuretmeSonucu;
  neden: string | null;
  turetilen_case_id: string | null;
  turetilen_baslik: string | null;
}
type TuretmeSonucu = "turetildi" | "iliski_gecersiz" | "belirsiz_alinti" | "olgu_yok";

export interface KaliteVerisi {
  tablolar: TabloKaydi[];
  iliskiler: IliskiKaydi[];
  kontroller: OracleKaydi[];
  turetmeler: TuretmeKaydi[];
  /** Gereksinim başına son AI taslak işi (`son_taslak`). */
  taslaklar?: Record<string, KaliteTaslakIsi>;
}

export interface KaliteBagimliliklari {
  veri: () => MockVeri;
  girisGerekli: () => Kullanici;
  rolGerekli: (...roller: Rol[]) => Kullanici;
  kaydet: () => void;
  arkaPlan: (adimlar: (() => void)[]) => void;
  denetimEkle: (eylem: string, nesne: string, ozet: string, aktor?: string) => void;
  yeniId: (onek: string) => string;
  /** handlers.ts'in özgün karar ucu (durum makinesi, hash, ölçümler). */
  caseKarari: (id: string, govde: unknown) => TestCase;
  caseMetrikleri: (rid: string) => CaseMetrikleri;
}

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

const simdi = () => new Date().toISOString();
const kopya = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const hash = (x: unknown) => `sha256:${sha256Hex(kanonikJson(x)).slice(0, 16)}`;
const acAnahtari = (r: string) => r.replace(/\s/g, "").toUpperCase();

/** Süren kontrol işleri (`case|hash`); bellek içi — sayfa yenilenirse kontrol okuma anında tamamlanır. */
const bekleyen = new Set<string>();
let bekleyenSahibi: MockVeri | null = null;

/** Mock verisinin kalite bölümü; yoksa (ilk açılış, sıfırlama, eski oturum verisi) TPD-1 tohumundan kurulur. */
export function kaliteVerisi(v: MockVeri): KaliteVerisi {
  const x = v as MockVeri & { kalite?: KaliteVerisi };
  if (bekleyenSahibi !== v) {
    bekleyen.clear();
    bekleyenSahibi = v;
  }
  if (!x.kalite) {
    x.kalite = { tablolar: [], iliskiler: [], kontroller: [], turetmeler: [], taslaklar: {} };
    const g = v.gereksinimler.find((r) => r.id === KALITE_REQ);
    if (g) {
      const ortak = (i: number, onayli: boolean) => ({
        requirement_id: g.id,
        sira_no: i + 1,
        onaylanan_hash: null as string | null,
        durum: (onayli ? "approved" : "draft") as KararTablosuDurumu,
        gereksinim_hash: onayli ? g.icerik_hash : null,
        ai_generated: true,
        uretim_modu: "replay" as CiktiModu,
        onaylayan: onayli ? "po" : null,
        onay_zamani: onayli ? "2026-10-30T10:20:00+03:00" : null,
        son_karar: onayli ? { karar: "approve", gerekce: null, kullanici: "po", zaman: "2026-10-30T10:20:00+03:00" } : null,
        olusturma: "2026-10-30T10:05:00+03:00",
        guncelleme: "2026-10-30T10:20:00+03:00",
      });
      ILK_TABLOLAR.forEach((t, i) => {
        const h = hash(t.icerik);
        x.kalite!.tablolar.push({ ...ortak(i, t.durum === "approved"), tur: "karar_tablosu", id: `kt-${i + 1}`, icerik: kopya(t.icerik), icerik_hash: h, onaylanan_hash: t.durum === "approved" ? h : null });
      });
      ILK_ILISKILER.forEach((r, i) => {
        const h = hash(r.icerik);
        const tablo = x.kalite!.tablolar.find((t) => `T${t.sira_no}` === r.icerik.tablo_ref);
        x.kalite!.iliskiler.push({
          ...ortak(i, r.durum === "approved"),
          tur: "metamorfik_iliski",
          id: `mi-${i + 1}`,
          karar_tablosu_id: tablo?.id ?? null,
          ...(r.elle ? { ai_generated: false, uretim_modu: null } : {}),
          icerik: kopya(r.icerik),
          icerik_hash: h,
          onaylanan_hash: r.durum === "approved" ? h : null,
        });
      });
    }
  }
  return x.kalite;
}

// ------------------------------------------------------------------ tablo doğrulama ve değerlendirme

const TURLER: IfadeTuru[] = ["sayi", "metin", "mantiksal"];

function ifadeDenetle(yol: string, metin: string, adlar: Record<string, IfadeTuru> | null, beklenen: IfadeTuru | null, hatalar: string[]): void {
  try {
    const d = ayristir(metin ?? "");
    if (adlar) {
      const t = turCikar(d, adlar);
      if (beklenen && t !== beklenen) hatalar.push(`${yol}: tür uyuşmazlığı: sonuç ${beklenen} olmalı (${t} verildi)`);
    }
  } catch (e) {
    if (!(e instanceof IfadeHatasi)) throw e;
    hatalar.push(`${yol}: ${e.message} (konum ${e.konum})`);
  }
}

/** core `ifade.dogrula` karşılığı: `"<alan yolu>: <mesaj>"` biçiminde hata metinleri. */
export function tabloDogrula(icerik: KararTablosuIcerik, g?: GereksinimDetay): string[] {
  const h: string[] = [];
  if (!icerik.ad?.trim()) h.push("ad: tablo adı boş olamaz");
  if (g) {
    const var_ = new Set(g.kabul_kriterleri.map((a) => acAnahtari(a.ref)));
    const yok = icerik.ac_refs.filter((r) => !var_.has(acAnahtari(r)));
    if (yok.length) h.push(`ac_refs: gereksinimde olmayan kabul kriteri: ${yok.join(", ")}`);
  }
  if (icerik.girdiler.length > 12) h.push("girdiler: en çok 12 girdi olabilir");
  if (icerik.ciktilar.length > 12) h.push("ciktilar: en çok 12 çıktı olabilir");
  if (icerik.satirlar.length > 60) h.push("satirlar: en çok 60 satır olabilir");
  const gorulen = new Set<string>();
  const kolon = (liste: "girdiler" | "ciktilar") =>
    icerik[liste].forEach((k, i) => {
      if (!adGecerli(k.ad ?? "")) h.push(`${liste}[${i}].ad: ad harfle başlamalı; harf, rakam ve alt çizgi içerebilir (ayrılmış sözcük olamaz)`);
      else if (gorulen.has(k.ad)) h.push(`${liste}[${i}].ad: '${k.ad}' adı birden çok kez kullanılmış`);
      gorulen.add(k.ad);
      if (!TURLER.includes(k.tur)) h.push(`${liste}[${i}].tur: tür sayi, metin ya da mantiksal olmalı`);
    });
  kolon("girdiler");
  kolon("ciktilar");
  icerik.ciktilar.forEach((c, i) => {
    if (c.tolerans === undefined || c.tolerans === "") return;
    const t = Number(String(c.tolerans).replace(",", "."));
    if (!Number.isFinite(t) || t < 0) h.push(`ciktilar[${i}].tolerans: tolerans sıfır ya da pozitif sayı olmalı`);
    else if (c.tur !== "sayi") h.push(`ciktilar[${i}].tolerans: tolerans yalnız sayı çıktıda kullanılır`);
  });
  const adlar = Object.fromEntries(icerik.girdiler.filter((x) => adGecerli(x.ad)).map((x) => [x.ad, x.tur]));
  icerik.satirlar.forEach((s, i) => {
    ifadeDenetle(`satirlar[${i}].kosul`, s.kosul, adlar, "mantiksal", h);
    for (const c of icerik.ciktilar) {
      if (!adGecerli(c.ad)) continue;
      const ifade = s.cikti?.[c.ad];
      if (ifade === undefined || !ifade.trim()) h.push(`satirlar[${i}].cikti.${c.ad}: çıktı ifadesi boş`);
      else ifadeDenetle(`satirlar[${i}].cikti.${c.ad}`, ifade, adlar, c.tur, h);
    }
  });
  return h;
}

function eksikler(icerik: KararTablosuIcerik): string[] {
  const h: string[] = [];
  if (icerik.girdiler.length === 0) h.push("girdiler: en az bir girdi gerekir");
  if (icerik.ciktilar.length === 0) h.push("ciktilar: en az bir çıktı gerekir");
  if (icerik.satirlar.length === 0) h.push("satirlar: en az bir satır gerekir");
  if (icerik.ac_refs.length === 0) h.push("ac_refs: en az bir kabul kriteri atfı gerekir");
  return h;
}

function girdiDegeri(tur: IfadeTuru, ham: unknown): IfadeDegeri | undefined {
  if (tur === "sayi") {
    if (typeof ham === "number" && Number.isFinite(ham)) return ham;
    if (typeof ham === "string") return sayiAyristir(ham) ?? undefined;
    return undefined;
  }
  if (tur === "mantiksal") return typeof ham === "boolean" ? ham : ham === "dogru" ? true : ham === "yanlis" ? false : undefined;
  return typeof ham === "string" ? ham : undefined;
}

/** core `ifade.degerlendir` karşılığı (ham değerlerle; yanıt gövdesine `degerlendirmeCiktisi` ile yazılır). */
export function tabloDegerlendir(
  icerik: KararTablosuIcerik,
  girdiler: Record<string, unknown>,
): { satir_id: string | null; ciktilar: Record<string, IfadeDegeri>; eksik_girdiler: string[]; hata: string | null } {
  const ortam: Record<string, IfadeDegeri> = {};
  const eksik: string[] = [];
  for (const g of icerik.girdiler) {
    const ham = girdiler[g.ad];
    if (ham === undefined || ham === null || ham === "") {
      eksik.push(g.ad);
      continue;
    }
    const d = girdiDegeri(g.tur, ham);
    if (d === undefined) return { satir_id: null, ciktilar: {}, eksik_girdiler: [], hata: `'${g.ad}' girdisi ${g.tur} türünde olmalı` };
    ortam[g.ad] = d;
  }
  if (eksik.length) return { satir_id: null, ciktilar: {}, eksik_girdiler: eksik, hata: null };
  try {
    for (const s of icerik.satirlar) {
      if (hesapla(ayristir(s.kosul), ortam) !== true) continue;
      const ciktilar: Record<string, IfadeDegeri> = {};
      for (const c of icerik.ciktilar) ciktilar[c.ad] = hesapla(ayristir(s.cikti[c.ad] ?? ""), ortam);
      return { satir_id: s.id, ciktilar, eksik_girdiler: [], hata: null };
    }
  } catch (e) {
    if (!(e instanceof IfadeHatasi)) throw e;
    return { satir_id: null, ciktilar: {}, eksik_girdiler: [], hata: e.message };
  }
  return { satir_id: null, ciktilar: {}, eksik_girdiler: [], hata: null };
}

// ------------------------------------------------------------------ değer çıkarma ve kontrol (§4.3)

function alanlar(icerik: TestCaseIcerik): { yol: string; metin: string }[] {
  return [
    { yol: "title", metin: icerik.title },
    ...icerik.preconditions.map((m, i) => ({ yol: `preconditions[${i}]`, metin: m })),
    ...icerik.steps.flatMap((s, i) => [
      { yol: `steps[${i}].action`, metin: s.action },
      { yol: `steps[${i}].data`, metin: s.data ?? "" },
      { yol: `steps[${i}].expected`, metin: s.expected },
    ]),
    { yol: "expected_result", metin: icerik.expected_result },
  ];
}

/** Değer çıkarma + deterministik doğrulama: alıntı alanda birebir geçer ve değere eşittir. */
export function olgulariCikar(icerik: TestCaseIcerik, kolonlar: { ad: string; tur: IfadeTuru }[]): Olgu[] {
  const cikti: Olgu[] = [];
  const gorulen = new Set<string>();
  for (const k of kolonlar) {
    for (const a of alanlar(icerik)) {
      for (const kural of CIKARMA_KURALLARI[k.ad] ?? []) {
        for (const m of a.metin.matchAll(kural.kalip)) {
          const mantiksal = kural.deger !== undefined;
          if (mantiksal !== (k.tur === "mantiksal")) continue;
          const quote = mantiksal ? m[0] : m[1];
          const index = (m.index ?? 0) + (mantiksal ? 0 : m[0].indexOf(quote));
          const value = mantiksal ? kural.deger! : sayiAyristir(quote);
          const anahtar = `${k.ad}|${a.yol}|${index}`;
          if (value === null || gorulen.has(anahtar) || a.metin.slice(index, index + quote.length) !== quote) continue;
          gorulen.add(anahtar);
          cikti.push({ column: k.ad, value, field: a.yol, quote, index });
        }
      }
    }
  }
  return cikti;
}

/** Kolonun tek değeri; olgu yoksa `undefined`, çelişen değerler varsa `null`. */
function tekDeger(olgular: Olgu[], kolon: string): IfadeDegeri | null | undefined {
  const d = [...new Set(olgular.filter((o) => o.column === kolon).map((o) => o.value))];
  return d.length === 0 ? undefined : d.length === 1 ? d[0] : null;
}

/**
 * core `yeniden_yazim._baslik`: başlık + ` (ilişki: <ad>)`; 120 karakteri aşarsa önce başlık (en az 20
 * karakter kalır), sonra ilişki adı `…` ile kısaltılır.
 */
export function turetilenBaslik(baslik: string, ad: string): string {
  const AZAMI = 120;
  let ek = ` (ilişki: ${ad})`;
  if (baslik.length + ek.length <= AZAMI) return baslik + ek;
  const pay = Math.max(20, AZAMI - ek.length);
  if (baslik.length > pay) baslik = `${baslik.slice(0, pay - 1).trimEnd()}…`;
  const kalan = AZAMI - baslik.length;
  if (ek.length > kalan) ek = `${ek.slice(0, kalan - 2)}…)`;
  return baslik + ek;
}

/** İfadede geçen adlar (`ifade.adlar` karşılığı). */
export function ifadeAdlari(metin: string): Set<string> {
  const kume = new Set<string>();
  const gez = (d: Dugum): void => {
    if (d.tur === "ad") kume.add(d.ad);
    else if (d.tur === "tekli") gez(d.sag);
    else if (d.tur === "ikili") {
      gez(d.sol);
      gez(d.sag);
    } else if (d.tur === "cagri") d.arglar.forEach(gez);
  };
  gez(ayristir(metin));
  return kume;
}

/**
 * core `dogrulama.kismi_degerlendir` karşılığı: eksik girdi yalnız onu kullanan koşulu/çıktıyı etkiler.
 * Satırlar sırayla denenir; koşulu eksik girdi kullanan ilk satırda durulur (`eksik_girdiler`). Seçilen
 * satırın eksik girdiye dayanan çıktıları `hesaplanamayan`'a (çıktı → eksik girdiler) yazılır.
 */
export function kismiDegerlendir(
  icerik: KararTablosuIcerik,
  girdiler: Record<string, IfadeDegeri>,
): { satir_id: string | null; ciktilar: Record<string, IfadeDegeri>; hesaplanamayan: Record<string, string[]>; eksik_girdiler: string[]; hata: string | null } {
  const eksik = icerik.girdiler.map((g) => g.ad).filter((ad) => girdiler[ad] === undefined);
  const sirali = (adlar: Set<string>) => eksik.filter((a) => adlar.has(a));
  for (const s of icerik.satirlar) {
    try {
      const gerekli = sirali(ifadeAdlari(s.kosul));
      if (gerekli.length) return { satir_id: null, ciktilar: {}, hesaplanamayan: {}, eksik_girdiler: gerekli, hata: null };
      if (hesapla(ayristir(s.kosul), girdiler) !== true) continue;
    } catch (e) {
      if (!(e instanceof IfadeHatasi)) throw e;
      return { satir_id: null, ciktilar: {}, hesaplanamayan: {}, eksik_girdiler: [], hata: `satır ${s.id} koşul: ${e.message}` };
    }
    const ciktilar: Record<string, IfadeDegeri> = {};
    const hesaplanamayan: Record<string, string[]> = {};
    for (const c of icerik.ciktilar) {
      const metin = s.cikti[c.ad] ?? "";
      try {
        const gerekli = sirali(ifadeAdlari(metin));
        if (gerekli.length) hesaplanamayan[c.ad] = gerekli;
        else ciktilar[c.ad] = hesapla(ayristir(metin), girdiler);
      } catch (e) {
        if (!(e instanceof IfadeHatasi)) throw e;
        return { satir_id: s.id, ciktilar: {}, hesaplanamayan: {}, eksik_girdiler: [], hata: `satır ${s.id} çıktı '${c.ad}': ${e.message}` };
      }
    }
    return { satir_id: s.id, ciktilar, hesaplanamayan, eksik_girdiler: [], hata: null };
  }
  return { satir_id: null, ciktilar: {}, hesaplanamayan: {}, eksik_girdiler: [], hata: null };
}

const olguKaydi = ({ index: _i, ...o }: Olgu) => o;

/** core `dogrulama._grup_degerlendir` karşılığı (neden metinleri çekirdekle aynı). */
function grupHesapla(icerik: TestCaseIcerik, t: TabloKaydi): Grup {
  const girdiOlgulari = olgulariCikar(icerik, t.icerik.girdiler);
  const beklenen = olgulariCikar(icerik, t.icerik.ciktilar);
  const g: Grup = {
    tablo_id: t.id,
    tablo_ad: t.icerik.ad,
    satir_id: null,
    girdiler: girdiOlgulari,
    karsilastirmalar: [],
    karsilastirilamayan: [],
    durum: "cikarilamadi",
    neden: null,
  };
  const girdiler: Record<string, IfadeDegeri> = {};
  for (const k of t.icerik.girdiler) {
    const d = tekDeger(girdiOlgulari, k.ad);
    if (d === null) return { ...g, neden: `çelişkili girdi: ${k.ad}` };
    if (d !== undefined) girdiler[k.ad] = d;
  }
  const s = kismiDegerlendir(t.icerik, girdiler);
  if (s.eksik_girdiler.length) return { ...g, neden: `case'te bulunamayan girdi: ${s.eksik_girdiler.join(", ")}` };
  if (s.hata) return { ...g, satir_id: s.satir_id, durum: "hata", neden: s.hata };
  if (!s.satir_id) return { ...g, durum: "satir_yok", neden: "bu girdilerle eşleşen tablo satırı yok" };
  const karsilastirilamayan = beklenen
    .filter((o) => o.column in s.hesaplanamayan)
    .map((o) => ({ ...olguKaydi(o), neden: `case'te bulunamayan girdi: ${s.hesaplanamayan[o.column].join(", ")}` }));
  const hesaplanan = beklenen.filter((o) => !(o.column in s.hesaplanamayan));
  if (hesaplanan.length === 0) {
    if (karsilastirilamayan.length) return { ...g, satir_id: s.satir_id, karsilastirilamayan, neden: karsilastirilamayan[0].neden };
    return { ...g, satir_id: s.satir_id, durum: "karsilastirma_yok", neden: "case'te doğrulanan beklenen değer yok" };
  }
  const karsilastirmalar = hesaplanan.map((o) => {
    const c = t.icerik.ciktilar.find((x) => x.ad === o.column)!;
    const tolerans = c.tolerans ? Number(String(c.tolerans).replace(",", ".")) || 0 : 0;
    return {
      column: o.column,
      alan: o.field,
      alinti: o.quote,
      case_degeri: degerYaz(o.value),
      tablo_degeri: degerYaz(s.ciktilar[o.column]),
      uyumlu: esitMi(o.value, s.ciktilar[o.column], tolerans),
      tablo_id: t.id,
      tablo_ad: t.icerik.ad,
      satir_id: s.satir_id,
    };
  });
  return {
    ...g,
    satir_id: s.satir_id,
    karsilastirmalar,
    karsilastirilamayan,
    durum: karsilastirmalar.every((k) => k.uyumlu) ? "uyumlu" : "uyumsuz",
  };
}

/** Python `repr(str)` (çekirdek özet metni alıntıyı `!r` ile yazar). */
function pyRepr(x: string): string {
  return x.includes("'") && !x.includes('"') ? `"${x}"` : `'${x.replaceAll("'", "\\'")}'`;
}
/** Python `str()` (çekirdek özet metninde tablo değeri): mantıksal `True`/`False`. */
const pyStr = (x: unknown): string => (x === true ? "True" : x === false ? "False" : String(x));

/** core `dogrulama.ozet` karşılığı: portal çipinin yanındaki tek cümle (metinler çekirdekle aynı). */
export function oracleOzeti(sonuc: OracleSonucu | null, gruplar: Grup[]): string {
  if (sonuc === "kapsam_disi") return "Bu case'i kapsayan onaylı karar tablosu yok.";
  const karsilastirmalar = gruplar.flatMap((g) => g.karsilastirmalar);
  const disarida = gruplar.flatMap((g) => g.karsilastirilamayan);
  const ek = disarida.length ? ` ${disarida.length} değer karşılaştırılamadı (${disarida[0].neden}).` : "";
  if (sonuc === "uyumlu") return `${karsilastirmalar.length} beklenen değer onaylı karar tablosuyla uyumlu.${ek}`;
  if (sonuc === "uyumsuz") {
    const bozuk = karsilastirmalar.filter((k) => !k.uyumlu);
    const ilk = bozuk[0];
    return `${bozuk.length} beklenen değer tabloyla uyuşmuyor; ör. ${ilk.column}: case ${pyRepr(ilk.alinti)}, tablo ${pyStr(ilk.tablo_degeri)}.${ek}`;
  }
  if (sonuc === "kontrol_edilemedi") {
    const neden = gruplar.find((g) => g.neden)?.neden;
    return neden ? `Kontrol edilemedi: ${neden}.` : "Kontrol edilemedi: case'ten tabloyla karşılaştırılabilir değer çıkarılamadı.";
  }
  return "Tablo kontrolü sürüyor.";
}

/** `oracle.check`: case içeriğini kapsayan onaylı tablolarla karşılaştırır (case içeriğini değiştirmez). */
export function kontrolEt(icerik: TestCaseIcerik, tablolar: TabloKaydi[]): Pick<OracleKaydi, "sonuc" | "ozet" | "ayrintilar"> {
  if (tablolar.length === 0) return { sonuc: "kapsam_disi", ozet: oracleOzeti("kapsam_disi", []), ayrintilar: { gruplar: [], atilan_olgular: 0 } };
  const gruplar = tablolar.map((t) => grupHesapla(icerik, t));
  const hepsi = gruplar.flatMap((g) => g.karsilastirmalar);
  const sonuc: OracleSonucu = hepsi.some((k) => !k.uyumlu) ? "uyumsuz" : hepsi.length ? "uyumlu" : "kontrol_edilemedi";
  return { sonuc, ozet: oracleOzeti(sonuc, gruplar), ayrintilar: { gruplar, atilan_olgular: 0 } };
}

// ------------------------------------------------------------------ uçlar

const GECIS_ADI: Record<KaliteGecisi, string> = {
  submit: "PO onayına gönderme",
  withdraw: "geri çekme",
  reopen: "yeniden açma",
  approve: "PO onayı",
  "request-changes": "değişiklik isteği",
};
const DURUM_ADI: Record<KararTablosuDurumu, string> = { draft: "Taslak", pending_po: "PO onayı bekliyor", approved: "Onaylı", superseded: "Yerini yenisi aldı" };
/** ANALIZ §4.1 durum makinesi: geçiş → [önceki durum, sonraki durum, rol]. */
export const KALITE_GECISLERI: Record<KaliteGecisi, { once: KararTablosuDurumu; sonra: KararTablosuDurumu; rol: Rol }> = {
  submit: { once: "draft", sonra: "pending_po", rol: "analyst" },
  withdraw: { once: "pending_po", sonra: "draft", rol: "analyst" },
  reopen: { once: "approved", sonra: "draft", rol: "analyst" },
  approve: { once: "pending_po", sonra: "approved", rol: "po" },
  "request-changes": { once: "pending_po", sonra: "draft", rol: "po" },
};
const URETIM_DURUMLARI = new Set(["po_approved", "generating", "cases_ready", "done"]);

export function kaliteRotalari(b: KaliteBagimliliklari): Rota[] {
  const K = () => kaliteVerisi(b.veri());
  const gereksinim = (id: string): GereksinimDetay => {
    const g = b.veri().gereksinimler.find((r) => r.id === id);
    if (!g) throw new ApiError(404, `Gereksinim bulunamadı: ${id}`);
    return g;
  };
  const bayat = (x: { durum: string; gereksinim_hash: string | null; requirement_id: string }) =>
    x.durum === "approved" && x.gereksinim_hash !== b.veri().gereksinimler.find((r) => r.id === x.requirement_id)?.icerik_hash;
  // Yanıt öğesi gerçek çekirdek şeklidir: iç `gereksinim_hash` yanıta girmez.
  const tabloCikti = (t: TabloKaydi): KararTablosu => {
    const { gereksinim_hash: _g, ...y } = kopya(t);
    return { ...y, bayat: bayat(t) };
  };
  const iliskiCikti = (r: IliskiKaydi): MetamorfikIliski => {
    const { gereksinim_hash: _g, ...y } = kopya(r);
    return { ...y, bayat: bayat(r) };
  };
  const tabloBul = (id: string) => {
    const t = K().tablolar.find((x) => x.id === id);
    if (!t) throw new ApiError(404, `Karar tablosu bulunamadı: ${id}`);
    return t;
  };
  const iliskiBul = (id: string) => {
    const r = K().iliskiler.find((x) => x.id === id);
    if (!r) throw new ApiError(404, `İlişki bulunamadı: ${id}`);
    return r;
  };
  /** Görülen hash: `zorunlu` değilse yalnız verildiğinde denetlenir (submit). Eski hash → 409 `onay_hash_uyusmuyor`. */
  const hashGerekli = (govde: unknown, guncel: string, zorunlu = true) => {
    const verilen = (govde as { icerik_hash?: unknown } | null | undefined)?.icerik_hash;
    if (!zorunlu && (verilen === undefined || verilen === null)) return;
    if (typeof verilen !== "string" || !verilen) throw new ApiError(422, "İstek, görüntülenen içeriğin hash'ini (icerik_hash) taşımalı.", { kod: "gecersiz_karar" });
    if (verilen !== guncel) throw new ApiError(409, "İçerik siz görüntüledikten sonra değişmiş; yenileyip tekrar deneyin.", { kod: "onay_hash_uyusmuyor" });
  };
  const yalnizTaslak = (x: { durum: KararTablosuDurumu }) => {
    if (x.durum !== "draft") throw new ApiError(409, `İçerik yalnız taslakta değişir (durum: ${DURUM_ADI[x.durum]}).`, { kod: "cakisma" });
  };
  const gecersiz = (kod: string, hatalar: string[]) =>
    new ApiError(422, `${hatalar.length} doğrulama hatası: ${hatalar.join("; ")}`, { kod, hatalar });
  const olay = (tur: "karar_tablosu" | "metamorfik_iliski", x: { id: string; requirement_id: string; durum: string }, ek: Record<string, unknown> = {}) =>
    mockOlayYayinla({ type: `${tur}.state`, id: x.id, data: { id: x.id, requirement_id: x.requirement_id, durum: x.durum, ...ek } });
  /** İçerik düzenleme / oluşturma / AI taslağı: `karar_tablosu.updated {id, tur, requirement_id, durum, eylem}`. */
  const guncellendiOlayi = (tur: "karar_tablosu" | "metamorfik_iliski", x: { id: string; requirement_id: string; durum: string }, eylem: string) =>
    mockOlayYayinla({ type: "karar_tablosu.updated", id: x.id, data: { id: x.id, tur, requirement_id: x.requirement_id, durum: x.durum, eylem } });

  // ---- kontrol kayıtları
  const kapsayanlar = (rid: string, icerik: TestCaseIcerik): TabloKaydi[] => {
    const refs = new Set(icerik.acceptance_criteria_refs.map(acAnahtari));
    return K().tablolar.filter((t) => t.requirement_id === rid && t.durum === "approved" && !bayat(t) && t.icerik.ac_refs.some((r) => refs.has(acAnahtari(r))));
  };
  const imza = (ts: TabloKaydi[]) => ts.map((t) => `${t.id}:${t.icerik_hash}`).join("|");
  const kayitBul = (c: TestCase, icerik: TestCaseIcerik, h: string) => {
    const i = imza(kapsayanlar(c.requirement_id, icerik));
    return K().kontroller.find((r) => r.test_case_id === c.id && r.icerik_hash === h && r.tablo_imzasi === i) ?? null;
  };
  const kayitYaz = (c: TestCase, icerik: TestCaseIcerik, h: string): OracleKaydi => {
    const ts = kapsayanlar(c.requirement_id, icerik);
    const k = K();
    const aiHash = c.ai_icerik ? icerikHash(c.ai_icerik) : c.karar === "edit" ? null : c.icerik_hash;
    const kayit: OracleKaydi = { ...kontrolEt(icerik, ts), test_case_id: c.id, icerik_hash: h, tablo_imzasi: imza(ts), ai_icerik: c.ai_generated && aiHash === h, istisna: null, olusturma: simdi() };
    k.kontroller = k.kontroller.filter((r) => !(r.test_case_id === c.id && r.icerik_hash === h));
    k.kontroller.push(kayit);
    bekleyen.delete(`${c.id}|${h}`);
    return kayit;
  };
  /** Gereksinimin kontrolde kullanılabilecek tabloları (onaylı, bayat değil). Yoksa kontrol işi açılmaz. */
  const gecerliTabloVar = (rid: string) => K().tablolar.some((t) => t.requirement_id === rid && t.durum === "approved" && !bayat(t));
  /**
   * Güncel içeriğin kaydı; iş sürüyorsa null, hiç iş yoksa (worker bitirmiş sayılır) okuma anında yazılır.
   * Çekirdek gibi: gereksinimde geçerli tablo yoksa kayıt yazılmaz (`oracle: null`).
   */
  const hazirKayit = (c: TestCase): OracleKaydi | null =>
    kayitBul(c, c.icerik, c.icerik_hash) ??
    (bekleyen.has(`${c.id}|${c.icerik_hash}`) || !gecerliTabloVar(c.requirement_id) ? null : kayitYaz(c, c.icerik, c.icerik_hash));
  const oracleCikti = (r: OracleKaydi | null): CaseOracle | null =>
    r && {
      sonuc: r.sonuc,
      ozet: r.ozet,
      karsilastirmalar: kopya(r.ayrintilar.gruplar.flatMap((g) => g.karsilastirmalar)),
      // core `karsilastirilamayanlar`: olgu alanları (`field`/`quote`/`value`) görünümde `alan`/`alinti`/`case_degeri`.
      karsilastirilamayan: r.ayrintilar.gruplar.flatMap((g) =>
        g.karsilastirilamayan.map((o) => ({ tablo_id: g.tablo_id, tablo_ad: g.tablo_ad, column: o.column, alan: o.field, alinti: o.quote, case_degeri: degerYaz(o.value), neden: o.neden })),
      ),
      istisna: r.istisna && { ...r.istisna },
      icerik_hash: r.icerik_hash,
      kontrol_suruyor: false,
    };
  /** İş kuyruktayken: sonuçsuz kayıt (`kontrol_suruyor: true`). */
  const suruyor = (h: string): CaseOracle => ({
    sonuc: null,
    ozet: oracleOzeti(null, []),
    karsilastirmalar: [],
    karsilastirilamayan: [],
    istisna: null,
    icerik_hash: h,
    kontrol_suruyor: true,
  });
  /** core `oracle_gorunumu`: kayıt yoksa iş sürüyorsa "sürüyor", gereksinimde geçerli tablo yoksa null. */
  const guncelOracle = (c: TestCase): CaseOracle | null => {
    const r = hazirKayit(c);
    if (r) return oracleCikti(r);
    return bekleyen.has(`${c.id}|${c.icerik_hash}`) ? suruyor(c.icerik_hash) : null;
  };
  /** `GET /cases/{id}/oracle` gövdesi (core `case_oracle`): `{case_id, icerik_hash, guncel_icerik, kapsayan_tablolar, oracle}`. */
  const oracleYaniti = (c: TestCase, h: string, oracle: CaseOracle | null, icerik: TestCaseIcerik | null) => ({
    case_id: c.id,
    icerik_hash: h,
    guncel_icerik: h === c.icerik_hash,
    kapsayan_tablolar: (icerik ? kapsayanlar(c.requirement_id, icerik) : []).map((t) => ({ id: t.id, ref: `T${t.sira_no}`, ad: t.icerik.ad, icerik_hash: t.icerik_hash })),
    oracle,
  });
  const oracleli = (c: TestCase): TestCase => ({ ...c, oracle: guncelOracle(c) });
  const kontrolOlayi = (c: TestCase, r: OracleKaydi) =>
    mockOlayYayinla({ type: "oracle.checked", id: c.id, data: { case_id: c.id, requirement_id: c.requirement_id, icerik_hash: r.icerik_hash, sonuc: r.sonuc } });
  /** Tablo onaylanınca: gereksinimin `draft` ve `approved` case'leri yeniden kontrol edilir (iş). */
  const kontrolleriKuyrukla = (rid: string) => {
    const cs = b.veri().caseler.filter((c) => c.requirement_id === rid && (c.durum === "draft" || c.durum === "approved"));
    for (const c of cs) bekleyen.add(`${c.id}|${c.icerik_hash}`);
    if (cs.length)
      b.arkaPlan(
        cs.map((c) => () => {
          const guncel = b.veri().caseler.find((x) => x.id === c.id);
          if (guncel) kontrolOlayi(guncel, kayitYaz(guncel, guncel.icerik, guncel.icerik_hash));
        }),
      );
  };

  // ---- karar kapısı (§4.3 tablosu)
  function kararKapisi(id: string, govde: unknown): TestCase {
    const k = b.rolGerekli("analyst");
    const c = b.veri().caseler.find((x) => x.id === id);
    const g = (govde ?? {}) as Partial<CaseKararGirdisi>;
    let istisnaKaydi: OracleKaydi | null = null;
    let uyariKaydi: OracleKaydi | null = null;
    const duzeltme = g.karar === "edit";
    if (c && c.durum === "draft" && g.icerik_hash === c.icerik_hash && (g.karar === "approve" || (duzeltme && g.icerik?.steps?.length && g.icerik.title?.trim()))) {
      const icerik = duzeltme ? g.icerik! : c.icerik;
      const h = duzeltme ? icerikHash(icerik) : c.icerik_hash;
      const yuksek = icerik.risk === "high";
      if (kapsayanlar(c.requirement_id, icerik).length) {
        let kayit = kayitBul(c, icerik, h);
        // Düzeltmede önerilen içerik için kontrol istenmemişse ya da iş sürüyorsa kayıt yoktur (V3).
        if (!kayit && (duzeltme || bekleyen.has(`${c.id}|${h}`))) {
          if (yuksek) throw new ApiError(409, "Beklenen sonuç kontrolü henüz bitmedi; kontrol bitince yeniden deneyin.", { kod: "oracle_bekleniyor" });
        } else if (!kayit) kayit = kayitYaz(c, icerik, h);
        if (kayit?.sonuc === "uyumsuz" && yuksek && !kayit.istisna) {
          const gerekce = (g.oracle_istisna_gerekce ?? "").trim();
          if (!gerekce)
            throw new ApiError(422, "Beklenen değer onaylı karar tablosuyla uyuşmuyor; yüksek riskli case gerekçeli istisna olmadan onaylanamaz.", { kod: "oracle_uyumsuz" });
          if (gerekce.length < 20) throw new ApiError(422, "İstisna gerekçesi en az 20 karakter olmalı.", { kod: "oracle_uyumsuz" });
          istisnaKaydi = kayit;
        } else if (kayit && ((kayit.sonuc === "uyumsuz" && !yuksek) || (kayit.sonuc === "kontrol_edilemedi" && yuksek))) uyariKaydi = kayit;
      }
    }
    const sonuc = b.caseKarari(id, govde);
    if (istisnaKaydi) {
      istisnaKaydi.istisna = { gerekce: g.oracle_istisna_gerekce!.trim(), veren: k.kullanici_adi, zaman: simdi() };
      b.denetimEkle("oracle.exception", id, `Tablo uyuşmazlığına rağmen onay · gerekçe: ${istisnaKaydi.istisna.gerekce}`);
    } else if (uyariKaydi) {
      b.denetimEkle("oracle.warning", id, uyariKaydi.sonuc === "uyumsuz" ? "Tabloyla uyuşmayan case onaylandı (orta/düşük risk)" : "Kontrol edilemeyen yüksek riskli case onaylandı");
    }
    b.kaydet();
    return oracleli(b.veri().caseler.find((x) => x.id === id) ?? sonuc);
  }

  // ---- geçişler (tablo ve ilişki aynı makine)
  function gecis<T extends TabloKaydi | IliskiKaydi>(tur: "karar_tablosu" | "metamorfik_iliski", x: T, eylem: KaliteGecisi, govde: unknown, eksik: () => string[]): T {
    const kural = KALITE_GECISLERI[eylem];
    const k = b.rolGerekli(kural.rol);
    if (x.durum !== kural.once) throw new ApiError(409, `Bu durumda ${GECIS_ADI[eylem]} yapılamaz (durum: ${DURUM_ADI[x.durum]}).`, { kod: "eszamanli_gecis" });
    // withdraw / reopen gövdesiz; submit'te hash isteğe bağlı; PO kararlarında zorunlu.
    if (eylem === "submit") hashGerekli(govde, x.icerik_hash, false);
    if (eylem === "approve" || eylem === "request-changes") hashGerekli(govde, x.icerik_hash);
    if (eylem === "submit") {
      const h = eksik();
      if (h.length) throw gecersiz(tur === "karar_tablosu" ? "karar_tablosu_gecersiz" : "iliski_gecersiz", h);
    }
    const gerekce = String((govde as { gerekce?: unknown } | null | undefined)?.gerekce ?? "").trim();
    if (eylem === "request-changes") {
      if (!gerekce) throw new ApiError(422, "Değişiklik isteği için gerekçe yazılmalı.", { kod: "gecersiz_karar" });
      x.son_karar = { karar: "request_changes", gerekce, kullanici: k.kullanici_adi, zaman: simdi() };
    }
    if (eylem === "approve") x.son_karar = { karar: "approve", gerekce: gerekce || null, kullanici: k.kullanici_adi, zaman: simdi() };
    x.durum = kural.sonra;
    if (eylem === "approve") {
      x.onaylanan_hash = x.icerik_hash;
      x.gereksinim_hash = gereksinim(x.requirement_id).icerik_hash;
      x.onaylayan = k.kullanici_adi;
      x.onay_zamani = simdi();
    } else {
      x.onaylanan_hash = null;
      x.gereksinim_hash = null;
      x.onaylayan = null;
      x.onay_zamani = null;
    }
    x.guncelleme = simdi();
    b.denetimEkle(`${tur}.${eylem}`, x.id, `${x.icerik.ad} · ${DURUM_ADI[x.durum]} · ${x.icerik_hash}`);
    b.kaydet();
    olay(tur, x);
    return x;
  }

  /** Yetkili bağ `karar_tablosu_id`'dir (§11.3); `icerik.tablo_ref` yalnız okunur bilgidir. */
  function iliskiDogrula(icerik: MetamorfikIliskiIcerik, rid: string, tabloId: string | null): { hatalar: string[]; tablo: TabloKaydi | null } {
    const h: string[] = [];
    if (!icerik.ad?.trim()) h.push("ad: ilişki adı boş olamaz");
    const var_ = new Set(gereksinim(rid).kabul_kriterleri.map((a) => acAnahtari(a.ref)));
    const yok = icerik.ac_refs.filter((r) => !var_.has(acAnahtari(r)));
    if (yok.length) h.push(`ac_refs: gereksinimde olmayan kabul kriteri: ${yok.join(", ")}`);
    const tablo = tabloId ? (K().tablolar.find((t) => t.requirement_id === rid && t.durum !== "superseded" && t.id === tabloId) ?? null) : null;
    if (tabloId && !tablo) h.push(`karar_tablosu_id: bilinmeyen tablo '${tabloId}'`);
    const girdi = tablo ? Object.fromEntries(tablo.icerik.girdiler.map((x) => [x.ad, x.tur])) : null;
    const cikti = tablo ? Object.fromEntries(tablo.icerik.ciktilar.map((x) => [x.ad, x.tur])) : null;
    const adlar = girdi && cikti ? { ...girdi, ...cikti } : null;
    ifadeDenetle("on_kosul", icerik.on_kosul, adlar, "mantiksal", h);
    if (Object.keys(icerik.donusum).length === 0) h.push("donusum: en az bir girdi dönüşümü gerekir");
    if (Object.keys(icerik.iliski).length === 0) h.push("iliski: en az bir beklenen çıktı ilişkisi gerekir");
    for (const [ad, ifade] of Object.entries(icerik.donusum)) {
      if (girdi && !(ad in girdi)) h.push(`donusum.${ad}: '${ad}' bağlı tablonun girdisi değil`);
      else ifadeDenetle(`donusum.${ad}`, ifade, adlar, girdi?.[ad] ?? null, h);
    }
    for (const [ad, ifade] of Object.entries(icerik.iliski)) {
      if (cikti && !(ad in cikti)) h.push(`iliski.${ad}: '${ad}' bağlı tablonun çıktısı değil`);
      else ifadeDenetle(`iliski.${ad}`, ifade, adlar, cikti?.[ad] ?? null, h);
    }
    return { hatalar: h, tablo };
  }

  // ---- AI taslağı (amaç `decision_table_draft`)
  function taslakUret(rid: string): KaliteTaslakYaniti {
    b.rolGerekli("analyst");
    const g = gereksinim(rid);
    if (!URETIM_DURUMLARI.has(g.durum)) throw new ApiError(409, "Karar tablosu taslağı için gereksinim PO onaylı olmalı.", { kod: "cakisma" });
    const k = K();
    const isler = (k.taslaklar ??= {});
    const suren = isler[rid];
    // Bir taslak işi sürerken aynı iş döner (ikinci iş açılmaz).
    if (suren && (suren.durum === "started" || suren.durum === "running")) {
      return { job_id: suren.job_id, workflow_id: suren.workflow_id, durum: suren.durum, mesaj: "Karar tablosu taslağı zaten üretiliyor.", uretim_no: null };
    }
    const is: KaliteTaslakIsi = { job_id: b.yeniId("job"), workflow_id: b.yeniId("wf"), durum: "started", sonuc: null, hata: null, olusturma: simdi() };
    isler[rid] = is;
    b.kaydet();
    b.arkaPlan([
      () => {
        const k = K();
        const c = taslakCiktisi(g.jira_key);
        if (c.tablolar.length) {
          // Yeni taslak üretimi eskileri geçersiz kılar (her durumdan `superseded`).
          for (const t of k.tablolar.filter((x) => x.requirement_id === rid && x.durum !== "superseded")) {
            t.durum = "superseded";
            olay("karar_tablosu", t);
          }
          for (const r of k.iliskiler.filter((x) => x.requirement_id === rid && x.durum !== "superseded")) {
            r.durum = "superseded";
            olay("metamorfik_iliski", r);
          }
        }
        const ortak = () => ({
          requirement_id: rid,
          onaylanan_hash: null,
          durum: "draft" as const,
          gereksinim_hash: null,
          ai_generated: true,
          uretim_modu: c.mod,
          onaylayan: null,
          onay_zamani: null,
          son_karar: null,
          olusturma: simdi(),
          guncelleme: simdi(),
        });
        const taban = Math.max(0, ...k.tablolar.filter((x) => x.requirement_id === rid).map((x) => x.sira_no));
        const yeniler = c.tablolar.map((icerik, i) => {
          const t: TabloKaydi = { ...ortak(), tur: "karar_tablosu", id: b.yeniId("kt"), sira_no: taban + i + 1, icerik: kopya(icerik), icerik_hash: hash(icerik) };
          k.tablolar.push(t);
          return t;
        });
        const iTaban = Math.max(0, ...k.iliskiler.filter((x) => x.requirement_id === rid).map((x) => x.sira_no));
        const iliskiler = c.iliskiler.map((ham, i) => {
          const sira = /^T(\d+)$/.exec(ham.tablo_ref ?? "")?.[1];
          const tablo = sira ? yeniler[Number(sira) - 1] : undefined;
          const icerik = { ...kopya(ham), tablo_ref: tablo ? `T${tablo.sira_no}` : null };
          const r: IliskiKaydi = { ...ortak(), tur: "metamorfik_iliski", id: b.yeniId("mi"), sira_no: iTaban + i + 1, karar_tablosu_id: tablo?.id ?? null, icerik, icerik_hash: hash(icerik) };
          k.iliskiler.push(r);
          return r;
        });
        const isKaydi = K().taslaklar?.[rid];
        if (isKaydi) {
          isKaydi.durum = "done";
          isKaydi.sonuc = { mod: c.mod, tablo: yeniler.length, iliski: iliskiler.length, atilan: [] };
        }
        b.denetimEkle("ai_call", rid, `Karar tablosu taslağı: ${c.tablolar.length} tablo, ${c.iliskiler.length} ilişki (${c.mod})`, "core-worker");
        b.kaydet();
        for (const t of yeniler) guncellendiOlayi("karar_tablosu", t, "ai_taslak");
        for (const r of iliskiler) guncellendiOlayi("metamorfik_iliski", r, "ai_taslak");
        // Taslak kaydı olmasa da (REPLAY-MISS) iş bitti olayı sayfayı yeniler.
        if (!yeniler.length && !iliskiler.length) guncellendiOlayi("karar_tablosu", { id: is.job_id ?? "", requirement_id: rid, durum: "draft" }, "ai_taslak");
      },
    ]);
    return { job_id: is.job_id, workflow_id: is.workflow_id, durum: "started", mesaj: "Karar tablosu taslağı üretiliyor.", uretim_no: null };
  }

  // ---- ilişki tabanlı ek case (§4.5)
  function adlariTopla(d: Dugum, kume: Set<string>): void {
    if (d.tur === "ad") kume.add(d.ad);
    else if (d.tur === "tekli") adlariTopla(d.sag, kume);
    else if (d.tur === "ikili") {
      adlariTopla(d.sol, kume);
      adlariTopla(d.sag, kume);
    } else if (d.tur === "cagri") d.arglar.forEach((a) => adlariTopla(a, kume));
  }

  function turetBir(r: IliskiKaydi, c: TestCase): { sonuc: TuretmeSonucu; neden: string | null; yeni?: TestCase } {
    const tablo = K().tablolar.find((t) => t.id === r.karar_tablosu_id);
    const ifadeler = [r.icerik.on_kosul, ...Object.values(r.icerik.donusum), ...Object.values(r.icerik.iliski)];
    const gereken = new Set<string>([...Object.keys(r.icerik.donusum), ...Object.keys(r.icerik.iliski)]);
    ifadeler.forEach((i) => adlariTopla(ayristir(i), gereken));
    const kolonlar = tablo
      ? [...tablo.icerik.girdiler, ...tablo.icerik.ciktilar]
      : [...gereken].map((ad) => ({ ad, tur: (CIKARMA_KURALLARI[ad]?.[0]?.deger !== undefined ? "mantiksal" : "sayi") as IfadeTuru }));
    const olgular = olgulariCikar(c.icerik, kolonlar);
    const ortam: Record<string, IfadeDegeri> = {};
    for (const ad of gereken) {
      const d = tekDeger(olgular, ad);
      if (d === undefined || d === null) return { sonuc: "olgu_yok", neden: `Kaynak case'te '${ad}' için doğrulanmış olgu yok` };
      ortam[ad] = d;
    }
    let yeniDegerler: Record<string, IfadeDegeri>;
    try {
      if (hesapla(ayristir(r.icerik.on_kosul), ortam) !== true) {
        const degerler = [...gereken].filter((a) => r.icerik.on_kosul.includes(a)).map((a) => `${a} = ${String(ortam[a])}`);
        return { sonuc: "iliski_gecersiz", neden: `Ön koşul sağlanmıyor: ${r.icerik.on_kosul} (${degerler.join(", ")})` };
      }
      yeniDegerler = Object.fromEntries(
        [...Object.entries(r.icerik.donusum), ...Object.entries(r.icerik.iliski)].map(([ad, ifade]) => [ad, hesapla(ayristir(ifade), ortam)]),
      );
    } catch (e) {
      if (!(e instanceof IfadeHatasi)) throw e;
      return { sonuc: "iliski_gecersiz", neden: `İlişki hesaplanamadı: ${e.message}` };
    }
    const degisen = olgular.filter((o) => o.column in yeniDegerler);
    if (degisen.some((o) => typeof o.value !== "number" || typeof yeniDegerler[o.column] !== "number")) {
      return { sonuc: "olgu_yok", neden: "Yalnız sayısal olgular yeni değerle değiştirilebilir" };
    }
    for (const o of degisen) {
      if (degisen.some((x) => x.field === o.field && x.quote === o.quote && x.column !== o.column)) {
        return { sonuc: "belirsiz_alinti", neden: `"${o.quote}" alıntısı ${o.field} alanında birden çok olguya ait` };
      }
    }
    const icerik = kopya(c.icerik);
    const oku = (yol: string): string => {
      const m = /^(\w+)(?:\[(\d+)\])?(?:\.(\w+))?$/.exec(yol)!;
      const kok = (icerik as unknown as Record<string, unknown>)[m[1]];
      const oge = m[2] === undefined ? kok : (kok as unknown[])[Number(m[2])];
      return String((m[3] ? (oge as Record<string, unknown>)[m[3]] : oge) ?? "");
    };
    const yaz = (yol: string, deger: string) => {
      const m = /^(\w+)(?:\[(\d+)\])?(?:\.(\w+))?$/.exec(yol)!;
      const ust = icerik as unknown as Record<string, unknown>;
      if (m[2] === undefined) ust[m[1]] = deger;
      else if (m[3]) ((ust[m[1]] as Record<string, unknown>[])[Number(m[2])] as Record<string, unknown>)[m[3]] = deger;
      else (ust[m[1]] as unknown[])[Number(m[2])] = deger;
    };
    // Sondan başa: önceki değişiklik sonraki alıntının konumunu kaydırmasın.
    for (const o of [...degisen].sort((a, z) => z.index - a.index)) {
      const metin = oku(o.field);
      yaz(o.field, metin.slice(0, o.index) + sayiBicimle(yeniDegerler[o.column] as number, o.quote) + metin.slice(o.index + o.quote.length));
    }
    icerik.title = turetilenBaslik(icerik.title, r.icerik.ad);
    icerik.tags = [...new Set([...icerik.tags, "metamorfik"])];
    const kardesler = b.veri().caseler.filter((x) => x.requirement_id === c.requirement_id);
    const yeni: TestCase = {
      id: b.yeniId("case"),
      requirement_id: c.requirement_id,
      jira_key: c.jira_key,
      sira_no: Math.max(0, ...kardesler.map((x) => x.sira_no)) + 1,
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
      // Deterministik türetme: model çağrısı yok (AI kabul oranı ve beklenti doğruluğu metriğine girmez).
      ai_generated: false,
      ai_sure_ms: 0,
      review_sure_ms: null,
      maliyet_usd: 0,
      jira_test_key: null,
      mode: null,
    };
    return { sonuc: "turetildi", neden: null, yeni };
  }

  function ekCaseTuret(rid: string, govde: unknown) {
    b.rolGerekli("analyst");
    const gr = gereksinim(rid);
    const g = (govde ?? {}) as { iliski_id?: unknown; case_ids?: unknown };
    if (typeof g.iliski_id !== "string" || !g.iliski_id) throw new ApiError(422, "iliski_id zorunludur.");
    const r = iliskiBul(g.iliski_id);
    if (r.requirement_id !== rid) throw new ApiError(404, `İlişki bulunamadı: ${g.iliski_id}`);
    if (r.durum !== "approved" || bayat(r) || !r.karar_tablosu_id)
      throw new ApiError(422, "Ek case yalnız PO onaylı, güncel ve bir karar tablosuna bağlı ilişkiden türetilir.", { kod: "iliski_gecersiz" });
    if (gr.durum !== "cases_ready" && gr.durum !== "done") throw new ApiError(409, "Ek case için gereksinim case review aşamasında olmalı.", { kod: "cakisma" });
    const refs = new Set(r.icerik.ac_refs.map(acAnahtari));
    const adaylar = b.veri().caseler.filter((c) => c.requirement_id === rid);
    const secim = Array.isArray(g.case_ids) ? g.case_ids.filter((x): x is string => typeof x === "string") : null;
    const kaynaklar = secim
      ? secim.map((id) => {
          const c = adaylar.find((x) => x.id === id);
          if (!c) throw new ApiError(404, `Case bulunamadı: ${id}`);
          return c;
        })
      : adaylar.filter((c) => (c.durum === "approved" || c.durum === "published") && c.icerik.acceptance_criteria_refs.some((a) => refs.has(acAnahtari(a))));
    const k = K();
    const yanit: TuretmeYaniti = { turetilen: [], atlanan: [] };
    for (const c of kaynaklar) {
      // Aynı kaynak + ilişki çifti ikinci kez türetilmez (UNIQUE (iliski_id, kaynak_case_id)). Önceki
      // türetme başarılıysa "zaten türetildi" (+ case bağlantısı); atlanmışsa yeniden denenir.
      const onceki = k.turetmeler.find((t) => t.iliski_id === r.id && t.kaynak_case_id === c.id);
      if (onceki?.turetilen_case_id) {
        yanit.atlanan.push({ kaynak_case_id: c.id, sonuc: "zaten_turetildi", neden: `Bu ilişkiyle daha önce türetildi: ${onceki.turetilen_baslik ?? onceki.turetilen_case_id}`, case_id: onceki.turetilen_case_id });
        continue;
      }
      const s = c.durum === "approved" || c.durum === "published" ? turetBir(r, c) : { sonuc: "olgu_yok" as const, neden: "Kaynak case onaylı değil" };
      if (s.yeni) {
        b.veri().caseler.push(s.yeni);
        const yeni = s.yeni;
        bekleyen.add(`${yeni.id}|${yeni.icerik_hash}`);
        b.arkaPlan([() => kontrolOlayi(yeni, kayitYaz(yeni, yeni.icerik, yeni.icerik_hash))]);
        mockOlayYayinla({ type: "case.generated", id: yeni.id, data: { requirement_id: rid, title: yeni.icerik.title } });
      }
      const kalem: TuretmeKaydi = {
        id: b.yeniId("mt"),
        olusturan_id: b.girisGerekli().kullanici_adi,
        olusturma: simdi(),
        iliski_id: r.id,
        kaynak_case_id: c.id,
        sonuc: s.sonuc,
        neden: s.neden,
        turetilen_case_id: s.yeni?.id ?? null,
        turetilen_baslik: s.yeni?.icerik.title ?? null,
      };
      k.turetmeler = k.turetmeler.filter((t) => !(t.iliski_id === r.id && t.kaynak_case_id === c.id));
      k.turetmeler.push(kalem);
      if (s.yeni) yanit.turetilen.push({ case_id: s.yeni.id, kaynak_case_id: c.id, baslik: s.yeni.icerik.title });
      else yanit.atlanan.push({ kaynak_case_id: c.id, sonuc: s.sonuc as TuretmeAtlamaSonucu, neden: s.neden });
    }
    b.denetimEkle("metamorfik.derive", r.id, `${yanit.turetilen.length} türetildi, ${yanit.atlanan.length} atlandı`);
    b.kaydet();
    return yanit;
  }

  /** §4.7: AI'ın ürettiği içeriğin kontrol sonuçları (insan düzeltmesinden önceki hash). */
  function beklentiDogrulugu(rid: string): BeklentiDogrulugu {
    const cs = b.veri().caseler.filter((c) => c.requirement_id === rid && c.ai_generated && c.durum !== "superseded");
    const say: Record<OracleSonucu, number> = { uyumlu: 0, uyumsuz: 0, kapsam_disi: 0, kontrol_edilemedi: 0 };
    let istisna = 0;
    for (const c of cs) {
      if (c.karar !== "edit" && !c.ai_icerik) hazirKayit(c);
      const kayitlar = K().kontroller.filter((r) => r.test_case_id === c.id);
      const ai = [...kayitlar].reverse().find((r) => r.ai_icerik);
      if (ai) say[ai.sonuc] += 1;
      if (kayitlar.some((r) => r.istisna)) istisna += 1;
    }
    const sayilan = say.uyumlu + say.uyumsuz + say.kontrol_edilemedi + say.kapsam_disi;
    return {
      oran: say.uyumlu + say.uyumsuz > 0 ? say.uyumlu / (say.uyumlu + say.uyumsuz) : null,
      ...say,
      istisna,
      kapsam_orani: sayilan > 0 ? (sayilan - say.kapsam_disi) / sayilan : null,
    };
  }

  const kimlik = (m: RegExpMatchArray) => decodeURIComponent(m[1]);

  return [
    [
      "GET",
      /^\/requirements\/([^/]+)\/decision-tables$/,
      (m, q) => {
        b.girisGerekli();
        const rid = kimlik(m);
        gereksinim(rid);
        const k = K();
        const tumu = q.get("tumu") === "true";
        const gorunur = (x: { requirement_id: string; durum: string }) => x.requirement_id === rid && (tumu || x.durum !== "superseded");
        return {
          tablolar: k.tablolar.filter(gorunur).map(tabloCikti),
          iliskiler: k.iliskiler.filter(gorunur).map(iliskiCikti),
          son_taslak: k.taslaklar?.[rid] ? kopya(k.taslaklar[rid]) : null,
        };
      },
    ],
    ["POST", /^\/requirements\/([^/]+)\/decision-tables\/draft$/, (m) => taslakUret(kimlik(m))],
    [
      "POST",
      /^\/requirements\/([^/]+)\/decision-tables$/,
      (m, _q, govde) => {
        b.rolGerekli("analyst");
        const rid = kimlik(m);
        const g = gereksinim(rid);
        if (!URETIM_DURUMLARI.has(g.durum)) throw new ApiError(409, "Karar tablosu için gereksinim PO onaylı olmalı.", { kod: "cakisma" });
        const k = K();
        const verilen = (govde as { icerik?: KararTablosuIcerik } | null | undefined)?.icerik;
        const icerik: KararTablosuIcerik = verilen ?? { ad: "Yeni karar tablosu", ac_refs: [], girdiler: [], ciktilar: [], satirlar: [] };
        if (verilen) {
          const h = tabloDogrula(verilen, g);
          if (h.length) throw gecersiz("karar_tablosu_gecersiz", h);
        }
        const t: TabloKaydi = {
          tur: "karar_tablosu",
          id: b.yeniId("kt"),
          requirement_id: rid,
          sira_no: Math.max(0, ...k.tablolar.filter((x) => x.requirement_id === rid).map((x) => x.sira_no)) + 1,
          icerik,
          icerik_hash: hash(icerik),
          onaylanan_hash: null,
          durum: "draft",
          gereksinim_hash: null,
          ai_generated: false,
          uretim_modu: null,
          onaylayan: null,
          onay_zamani: null,
          son_karar: null,
          olusturma: simdi(),
          guncelleme: simdi(),
        };
        k.tablolar.push(t);
        b.denetimEkle("karar_tablosu.create", t.id, "Elle tablo");
        b.kaydet();
        guncellendiOlayi("karar_tablosu", t, "olustur");
        return tabloCikti(t);
      },
    ],
    [
      "PUT",
      /^\/decision-tables\/([^/]+)$/,
      (m, _q, govde) => {
        b.rolGerekli("analyst");
        const t = tabloBul(kimlik(m));
        yalnizTaslak(t);
        hashGerekli(govde, t.icerik_hash);
        const icerik = (govde as { icerik?: KararTablosuIcerik }).icerik;
        if (!icerik || !Array.isArray(icerik.girdiler) || !Array.isArray(icerik.ciktilar) || !Array.isArray(icerik.satirlar) || !Array.isArray(icerik.ac_refs)) {
          throw gecersiz("karar_tablosu_gecersiz", ["icerik: tablo içeriği eksik"]);
        }
        const h = tabloDogrula(icerik, gereksinim(t.requirement_id));
        if (h.length) throw gecersiz("karar_tablosu_gecersiz", h);
        t.icerik = kopya(icerik);
        t.icerik_hash = hash(t.icerik);
        t.guncelleme = simdi();
        b.denetimEkle("karar_tablosu.update", t.id, `${t.icerik.ad} · ${t.icerik_hash}`);
        b.kaydet();
        guncellendiOlayi("karar_tablosu", t, "duzenle");
        return tabloCikti(t);
      },
    ],
    [
      "POST",
      /^\/decision-tables\/([^/]+)\/(submit|withdraw|reopen|approve|request-changes)$/,
      (m, _q, govde) => {
        const t = tabloBul(kimlik(m));
        gecis("karar_tablosu", t, m[2] as KaliteGecisi, govde, () => [...tabloDogrula(t.icerik, gereksinim(t.requirement_id)), ...eksikler(t.icerik)]);
        // Tablo onaylanınca o gereksinimin taslak ve onaylı case'leri yeniden kontrol edilir (§4.3).
        if (m[2] === "approve") kontrolleriKuyrukla(t.requirement_id);
        return tabloCikti(t);
      },
    ],
    [
      "POST",
      /^\/decision-tables\/([^/]+)\/evaluate$/,
      (m, _q, govde) => {
        b.girisGerekli();
        const t = tabloBul(kimlik(m));
        const g = (govde ?? {}) as { girdiler?: unknown; icerik?: KararTablosuIcerik };
        if (!g.girdiler || typeof g.girdiler !== "object") throw new ApiError(422, "girdiler nesnesi zorunludur.");
        // `icerik` verilirse kaydedilmemiş içerik değerlendirilir (düzenleyiciden önizleme).
        let icerik = t.icerik;
        if (g.icerik) {
          const h = tabloDogrula(g.icerik);
          if (h.length) throw gecersiz("karar_tablosu_gecersiz", h);
          icerik = g.icerik;
        }
        const s = tabloDegerlendir(icerik, g.girdiler as Record<string, unknown>);
        return { ...s, ciktilar: Object.fromEntries(Object.entries(s.ciktilar).map(([k, v]) => [k, degerYaz(v)])) } satisfies TabloDegerlendirmesi;
      },
    ],
    [
      "PUT",
      /^\/relations\/([^/]+)$/,
      (m, _q, govde) => {
        b.rolGerekli("analyst");
        const r = iliskiBul(kimlik(m));
        yalnizTaslak(r);
        hashGerekli(govde, r.icerik_hash);
        const g = govde as { icerik?: MetamorfikIliskiIcerik; karar_tablosu_id?: string | null };
        const icerik = g.icerik;
        // `karar_tablosu_id` yoksa bağ korunur; null bağı kaldırır.
        const tabloId = "karar_tablosu_id" in g ? (g.karar_tablosu_id ?? null) : r.karar_tablosu_id;
        if (!icerik || typeof icerik.donusum !== "object" || typeof icerik.iliski !== "object" || !Array.isArray(icerik.ac_refs)) {
          throw gecersiz("iliski_gecersiz", ["icerik: ilişki içeriği eksik"]);
        }
        const d = iliskiDogrula(icerik, r.requirement_id, tabloId);
        if (d.hatalar.length) throw gecersiz("iliski_gecersiz", d.hatalar);
        r.icerik = { ...kopya(icerik), tablo_ref: d.tablo ? `T${d.tablo.sira_no}` : null };
        r.karar_tablosu_id = d.tablo?.id ?? null;
        r.icerik_hash = hash(r.icerik);
        r.guncelleme = simdi();
        b.denetimEkle("metamorfik_iliski.update", r.id, `${r.icerik.ad} · ${r.icerik_hash}`);
        b.kaydet();
        guncellendiOlayi("metamorfik_iliski", r, "duzenle");
        return iliskiCikti(r);
      },
    ],
    [
      "POST",
      /^\/requirements\/([^/]+)\/relations$/,
      (m, _q, govde) => {
        b.rolGerekli("analyst");
        const rid = kimlik(m);
        const gr = gereksinim(rid);
        if (!URETIM_DURUMLARI.has(gr.durum)) throw new ApiError(409, "İlişki için gereksinim PO onaylı olmalı.", { kod: "cakisma" });
        const g = (govde ?? {}) as { icerik?: MetamorfikIliskiIcerik; karar_tablosu_id?: string | null };
        if (!g.icerik || typeof g.icerik.donusum !== "object" || typeof g.icerik.iliski !== "object" || !Array.isArray(g.icerik.ac_refs)) {
          throw gecersiz("iliski_gecersiz", ["icerik: ilişki içeriği eksik"]);
        }
        const tabloId = g.karar_tablosu_id ?? null;
        const d = iliskiDogrula(g.icerik, rid, tabloId);
        if (d.hatalar.length) throw gecersiz("iliski_gecersiz", d.hatalar);
        const k = K();
        const icerik = { ...kopya(g.icerik), tablo_ref: d.tablo ? `T${d.tablo.sira_no}` : null };
        const r: IliskiKaydi = {
          tur: "metamorfik_iliski",
          id: b.yeniId("mi"),
          requirement_id: rid,
          karar_tablosu_id: d.tablo?.id ?? null,
          sira_no: Math.max(0, ...k.iliskiler.filter((x) => x.requirement_id === rid).map((x) => x.sira_no)) + 1,
          icerik,
          icerik_hash: hash(icerik),
          onaylanan_hash: null,
          durum: "draft",
          gereksinim_hash: null,
          ai_generated: false,
          uretim_modu: null,
          onaylayan: null,
          onay_zamani: null,
          son_karar: null,
          olusturma: simdi(),
          guncelleme: simdi(),
        };
        k.iliskiler.push(r);
        b.denetimEkle("metamorfik_iliski.create", r.id, "Elle ilişki");
        b.kaydet();
        guncellendiOlayi("metamorfik_iliski", r, "olustur");
        return iliskiCikti(r);
      },
    ],
    [
      "POST",
      /^\/relations\/([^/]+)\/(submit|withdraw|reopen|approve|request-changes)$/,
      (m, _q, govde) => {
        const r = iliskiBul(kimlik(m));
        return iliskiCikti(gecis("metamorfik_iliski", r, m[2] as KaliteGecisi, govde, () => iliskiDogrula(r.icerik, r.requirement_id, r.karar_tablosu_id).hatalar));
      },
    ],
    ["POST", /^\/requirements\/([^/]+)\/metamorphic-cases$/, (m, _q, govde) => ekCaseTuret(kimlik(m), govde)],
    [
      "GET",
      /^\/requirements\/([^/]+)\/metamorphic-derivations$/,
      (m) => {
        b.girisGerekli();
        const rid = kimlik(m);
        gereksinim(rid);
        const iliskiIdleri = new Set(K().iliskiler.filter((r) => r.requirement_id === rid).map((r) => r.id));
        return K()
          .turetmeler.filter((t) => iliskiIdleri.has(t.iliski_id))
          .map((t) => ({
            id: t.id ?? `${t.iliski_id}:${t.kaynak_case_id}`,
            iliski_id: t.iliski_id,
            kaynak_case_id: t.kaynak_case_id,
            turetilen_case_id: t.turetilen_case_id,
            sonuc: t.sonuc,
            neden: t.neden,
            olusturan_id: t.olusturan_id ?? null,
            olusturma: t.olusturma ?? null,
          }));
      },
    ],
    [
      "GET",
      /^\/cases$/,
      (_m, q) => {
        b.girisGerekli();
        const rid = q.get("requirement_id");
        const liste = b
          .veri()
          .caseler.filter((c) => !rid || c.requirement_id === rid)
          .sort((a, z) => a.sira_no - z.sira_no)
          .map(oracleli);
        b.kaydet();
        return liste;
      },
    ],
    [
      "GET",
      /^\/cases\/([^/]+)\/oracle$/,
      (m, q) => {
        b.girisGerekli();
        const c = b.veri().caseler.find((x) => x.id === kimlik(m));
        if (!c) throw new ApiError(404, `Case bulunamadı: ${kimlik(m)}`);
        const h = q.get("icerik_hash");
        if (!h || h === c.icerik_hash) return oracleYaniti(c, c.icerik_hash, guncelOracle(c), c.icerik);
        // Önerilen içerik saklanmaz: kayıt yoksa kontrol beklenir (çekirdek: `kapsayan_var = True`).
        const kayit = [...K().kontroller].reverse().find((r) => r.test_case_id === c.id && r.icerik_hash === h) ?? null;
        return oracleYaniti(c, h, kayit ? oracleCikti(kayit) : suruyor(h), null);
      },
    ],
    [
      "POST",
      /^\/cases\/([^/]+)\/oracle-check$/,
      (m, _q, govde) => {
        b.rolGerekli("analyst");
        const c = b.veri().caseler.find((x) => x.id === kimlik(m));
        if (!c) throw new ApiError(404, `Case bulunamadı: ${kimlik(m)}`);
        const onerilen = (govde as { icerik?: TestCaseIcerik } | null)?.icerik;
        if (onerilen && (!onerilen.title?.trim() || !Array.isArray(onerilen.steps) || !Array.isArray(onerilen.acceptance_criteria_refs))) {
          throw new ApiError(422, "Önerilen içerik case şemasına uymuyor.");
        }
        const icerik = kopya(onerilen ?? c.icerik);
        const h = icerikHash(icerik);
        bekleyen.add(`${c.id}|${h}`);
        b.arkaPlan([() => kontrolOlayi(c, kayitYaz(c, icerik, h))]);
        return { job_id: b.yeniId("job"), icerik_hash: h };
      },
    ],
    ["POST", /^\/cases\/([^/]+)\/decision$/, (m, _q, govde) => kararKapisi(kimlik(m), govde)],
    ["GET", /^\/requirements\/([^/]+)\/case-metrics$/, (m) => ({ ...b.caseMetrikleri(kimlik(m)), beklenti_dogrulugu: beklentiDogrulugu(kimlik(m)) })],
  ];
}

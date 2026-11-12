// 012 Ş7 — karar tablosu / ilişki / oracle yanıt uyarlayıcıları (specs/012 ANALIZ §6).
// Çekirdek yanıtı portal tiplerine indirgenir; eksik alanlar güvenli varsayılana düşer ("uydurma" yok:
// bilinmeyen kişi/zaman null kalır).
import type {
  BeklentiDogrulugu,
  CaseOracle,
  CiktiModu,
  KaliteSonKarar,
  KaliteTaslakIsi,
  KaliteTaslakYaniti,
  MetamorfikTuretme,
  KararTablolariYaniti,
  KararTablosu,
  KararTablosuDurumu,
  KararTablosuIcerik,
  KolonTuru,
  MetamorfikIliski,
  MetamorfikIliskiIcerik,
  OracleDegerSayimi,
  OracleIstisnasi,
  OracleKarsilastirma,
  OracleSonucu,
  OracleKontrolYaniti,
  TabloDegerlendirmesi,
  TabloOrnekleri,
  TuretmeYaniti,
} from "./types";
import { KARAR_TABLOSU_DURUMLARI } from "./types";

type Ham = Record<string, unknown>;
const nesneMi = (x: unknown): x is Ham => !!x && typeof x === "object" && !Array.isArray(x);
const metin = (x: unknown, varsayilan = ""): string => (typeof x === "string" ? x : typeof x === "number" ? String(x) : varsayilan);
const metinYaDaNull = (x: unknown): string | null => (typeof x === "string" && x ? x : null);
const dizi = (x: unknown): unknown[] => (Array.isArray(x) ? x : []);
const metinler = (x: unknown): string[] => dizi(x).filter((m): m is string => typeof m === "string");
const ifadeler = (x: unknown): Record<string, string> =>
  nesneMi(x) ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, metin(v)])) : {};
const kolonTuru = (x: unknown): KolonTuru => (x === "metin" || x === "mantiksal" ? x : "sayi");
const secmeli = (x: unknown): string | undefined => (typeof x === "string" && x ? x : undefined);
const deger = (x: unknown): string | number | boolean | null =>
  typeof x === "string" || typeof x === "number" || typeof x === "boolean" ? x : null;

export function tabloIcerikUyarla(x: unknown): KararTablosuIcerik {
  const h = nesneMi(x) ? x : {};
  return {
    ad: metin(h.ad),
    ac_refs: metinler(h.ac_refs),
    ...(secmeli(h.aciklama) ? { aciklama: secmeli(h.aciklama) } : {}),
    girdiler: dizi(h.girdiler)
      .filter(nesneMi)
      .map((g) => ({
        ad: metin(g.ad),
        tur: kolonTuru(g.tur),
        ...(secmeli(g.birim) ? { birim: secmeli(g.birim) } : {}),
        ...(secmeli(g.aciklama) ? { aciklama: secmeli(g.aciklama) } : {}),
      })),
    ciktilar: dizi(h.ciktilar)
      .filter(nesneMi)
      .map((c) => ({
        ad: metin(c.ad),
        tur: kolonTuru(c.tur),
        ...(secmeli(c.birim) ? { birim: secmeli(c.birim) } : {}),
        ...(c.tolerans !== undefined && c.tolerans !== null && c.tolerans !== "" ? { tolerans: metin(c.tolerans) } : {}),
        ...(secmeli(c.aciklama) ? { aciklama: secmeli(c.aciklama) } : {}),
      })),
    satirlar: dizi(h.satirlar)
      .filter(nesneMi)
      .map((s, i) => ({ id: metin(s.id, `R${i + 1}`), kosul: metin(s.kosul), cikti: ifadeler(s.cikti) })),
  };
}

export function iliskiIcerikUyarla(x: unknown): MetamorfikIliskiIcerik {
  const h = nesneMi(x) ? x : {};
  return {
    ad: metin(h.ad),
    ac_refs: metinler(h.ac_refs),
    tablo_ref: metinYaDaNull(h.tablo_ref),
    on_kosul: metin(h.on_kosul),
    donusum: ifadeler(h.donusum),
    iliski: ifadeler(h.iliski),
    ...(secmeli(h.aciklama) ? { aciklama: secmeli(h.aciklama) } : {}),
    ...(Array.isArray(h.degismez) ? { degismez: metinler(h.degismez) } : {}),
  };
}

function durum(x: unknown): KararTablosuDurumu {
  return (KARAR_TABLOSU_DURUMLARI as readonly string[]).includes(x as string) ? (x as KararTablosuDurumu) : "draft";
}

function sonKarar(x: unknown): KaliteSonKarar | null {
  if (!nesneMi(x) || !metin(x.karar)) return null;
  return { karar: metin(x.karar), gerekce: metinYaDaNull(x.gerekce), kullanici: metinYaDaNull(x.kullanici), zaman: metinYaDaNull(x.zaman) };
}

function ortak(h: Ham) {
  const mod = h.uretim_modu ?? h.mode;
  const d = durum(h.durum);
  return {
    id: metin(h.id),
    tur: (h.tur === "metamorfik_iliski" ? "metamorfik_iliski" : "karar_tablosu") as "karar_tablosu" | "metamorfik_iliski",
    requirement_id: metin(h.requirement_id),
    sira_no: typeof h.sira_no === "number" ? h.sira_no : 0,
    icerik_hash: metin(h.icerik_hash),
    onaylanan_hash: metinYaDaNull(h.onaylanan_hash),
    durum: d,
    bayat: h.bayat === true,
    ai_generated: h.ai_generated === true,
    uretim_modu: (mod === "live" || mod === "replay" || mod === "replay_miss" ? mod : null) as CiktiModu | null,
    // Onay bilgisi yalnız onaylı kayıtta anlamlıdır (geri dönüşte eski onay gösterilmez).
    onaylayan: d === "approved" ? metinYaDaNull(h.onaylayan) : null,
    onay_zamani: d === "approved" ? metinYaDaNull(h.onay_zamani) : null,
    son_karar: sonKarar(h.son_karar),
    olusturma: metinYaDaNull(h.olusturma),
    guncelleme: metinYaDaNull(h.guncelleme),
    ...("son_duzenleyen" in h ? { son_duzenleyen: metinYaDaNull(h.son_duzenleyen) } : {}),
  };
}

export function kararTablosuUyarla(x: unknown): KararTablosu {
  const h = nesneMi(x) ? x : {};
  return {
    ...ortak(h),
    tur: "karar_tablosu",
    icerik: tabloIcerikUyarla(h.icerik),
    ...(nesneMi(h.ai_icerik) ? { ai_icerik: tabloIcerikUyarla(h.ai_icerik) } : {}),
  };
}

/** `GET /decision-tables/{id}/ornekler` → `{ornekler: [{girdiler, satir_id, ciktilar}], uyarilar}`. */
export function tabloOrnekleriUyarla(x: unknown): TabloOrnekleri {
  const h = nesneMi(x) ? x : {};
  const kayit = (y: unknown) => (nesneMi(y) ? Object.fromEntries(Object.entries(y).map(([k, v]) => [k, deger(v)])) : {});
  return {
    ornekler: dizi(h.ornekler)
      .filter(nesneMi)
      .map((o) => ({ girdiler: kayit(o.girdiler), satir_id: metinYaDaNull(o.satir_id), ciktilar: kayit(o.ciktilar), hata: metinYaDaNull(o.hata) })),
    // Uyarı nesnesi `{tur, mesaj, satirlar?, girdiler?}`; düz metin gelirse tür "bilgi" sayılır.
    uyarilar: dizi(h.uyarilar).flatMap((u) => {
      if (typeof u === "string") return u ? [{ tur: "bilgi", mesaj: u }] : [];
      if (!nesneMi(u) || !metin(u.mesaj)) return [];
      return [
        {
          tur: metin(u.tur, "bilgi"),
          mesaj: metin(u.mesaj),
          ...(Array.isArray(u.satirlar) ? { satirlar: metinler(u.satirlar) } : {}),
          ...(nesneMi(u.girdiler) ? { girdiler: kayit(u.girdiler) } : {}),
        },
      ];
    }),
  };
}

export function iliskiUyarla(x: unknown): MetamorfikIliski {
  const h = nesneMi(x) ? x : {};
  return {
    ...ortak(h),
    tur: "metamorfik_iliski",
    karar_tablosu_id: metinYaDaNull(h.karar_tablosu_id),
    icerik: iliskiIcerikUyarla(h.icerik),
    ...("tablo_engeli" in h ? { tablo_engeli: metinYaDaNull(h.tablo_engeli) } : {}),
  };
}

function taslakIsi(x: unknown): KaliteTaslakIsi | null {
  if (!nesneMi(x)) return null;
  const s = nesneMi(x.sonuc) ? x.sonuc : null;
  return {
    job_id: metinYaDaNull(x.job_id),
    workflow_id: metinYaDaNull(x.workflow_id),
    durum: metin(x.durum),
    sonuc: s
      ? {
          ...s,
          atilan: dizi(s.atilan)
            .filter(nesneMi)
            .map((a) => ({ tur: metin(a.tur), ref: metinYaDaNull(a.ref), ad: metinYaDaNull(a.ad), hatalar: metinler(a.hatalar) })),
        }
      : null,
    hata: metinYaDaNull(x.hata),
    ...("hata_kodu" in x ? { hata_kodu: metinYaDaNull(x.hata_kodu) } : {}),
    olusturma: metinYaDaNull(x.olusturma),
  };
}

/** `{tablolar, iliskiler, son_taslak}`; yalın dizi gelirse tablo listesi sayılır. */
export function kararTablolariUyarla(x: unknown): KararTablolariYaniti {
  if (Array.isArray(x)) return { tablolar: x.map(kararTablosuUyarla), iliskiler: [], son_taslak: null };
  const h = nesneMi(x) ? x : {};
  const sirala = <T extends { sira_no: number }>(l: T[]) => l.sort((a, b) => a.sira_no - b.sira_no);
  return {
    tablolar: sirala(dizi(h.tablolar ?? h.tables).map(kararTablosuUyarla)),
    iliskiler: sirala(dizi(h.iliskiler ?? h.relations).map(iliskiUyarla)),
    son_taslak: taslakIsi(h.son_taslak),
  };
}

export function kaliteTaslakUyarla(x: unknown): KaliteTaslakYaniti {
  const h = nesneMi(x) ? x : {};
  return {
    job_id: metinYaDaNull(h.job_id),
    workflow_id: metinYaDaNull(h.workflow_id),
    durum: metin(h.durum, "started"),
    ...(secmeli(h.mesaj) ? { mesaj: secmeli(h.mesaj) } : {}),
    uretim_no: typeof h.uretim_no === "number" ? h.uretim_no : null,
  };
}

export function turetmelerUyarla(x: unknown): MetamorfikTuretme[] {
  return dizi(x)
    .filter(nesneMi)
    .map((k) => ({
      id: metin(k.id),
      iliski_id: metin(k.iliski_id),
      kaynak_case_id: metin(k.kaynak_case_id),
      turetilen_case_id: metinYaDaNull(k.turetilen_case_id),
      sonuc: metin(k.sonuc),
      neden: metinYaDaNull(k.neden),
      olusturan_id: metinYaDaNull(k.olusturan_id),
      olusturma: metinYaDaNull(k.olusturma),
    }));
}

export function degerlendirmeUyarla(x: unknown): TabloDegerlendirmesi {
  const h = nesneMi(x) ? x : {};
  return {
    satir_id: metinYaDaNull(h.satir_id),
    ciktilar: nesneMi(h.ciktilar) ? Object.fromEntries(Object.entries(h.ciktilar).map(([k, v]) => [k, deger(v)])) : {},
    eksik_girdiler: metinler(h.eksik_girdiler),
    hata: metinYaDaNull(h.hata),
  };
}

const ORACLE_SONUCLARI: readonly OracleSonucu[] = ["uyumlu", "uyumsuz", "kismen", "kapsam_disi", "kontrol_edilemedi"];

const sayiMi = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** §13.2 `degerler`: nesne değilse alan eklenmez (eski çekirdek; sayı uydurulmaz). */
function degerSayimiUyarla(x: unknown): { degerler?: OracleDegerSayimi } {
  if (!nesneMi(x)) return {};
  const s = (a: unknown) => (sayiMi(a) ? a : 0);
  return { degerler: { uyumlu: s(x.uyumlu), uyumsuz: s(x.uyumsuz), karsilastirilamayan: s(x.karsilastirilamayan), atilan: s(x.atilan) } };
}

function istisnaUyarla(i: Ham): OracleIstisnasi {
  return {
    gerekce: metin(i.gerekce),
    veren: metinYaDaNull(i.veren),
    zaman: metinYaDaNull(i.zaman),
    ...(i.tur === "uyumsuz" || i.tur === "kontrolsuz" ? { tur: i.tur } : {}),
    ...("icerik_hash" in i ? { icerik_hash: metinYaDaNull(i.icerik_hash) } : {}),
  };
}

function karsilastirmaUyarla(k: Ham): OracleKarsilastirma {
  return {
    column: metin(k.column),
    alan: metin(k.alan),
    alinti: metin(k.alinti),
    case_degeri: deger(k.case_degeri),
    tablo_degeri: deger(k.tablo_degeri),
    uyumlu: k.uyumlu === true,
    tablo_id: metinYaDaNull(k.tablo_id),
    tablo_ad: metinYaDaNull(k.tablo_ad),
    satir_id: metinYaDaNull(k.satir_id),
  };
}

/**
 * Kontrol kaydı. Tanınmayan/eksik sonuç `null` (kayıt yok sayılır, "uyumlu" uydurulmaz); yalnız
 * `kontrol_suruyor: true` ise sonuçsuz kayıt kabul edilir ("Kontrol sürüyor").
 */
export function oracleUyarla(x: unknown): CaseOracle | null {
  if (!nesneMi(x)) return null;
  const suruyor = x.kontrol_suruyor === true;
  const sonuc = ORACLE_SONUCLARI.includes(x.sonuc as OracleSonucu) ? (x.sonuc as OracleSonucu) : null;
  if (!sonuc && !suruyor) return null;
  const i = nesneMi(x.istisna) && metin(x.istisna.gerekce) ? x.istisna : null;
  return {
    sonuc,
    ozet: metin(x.ozet),
    karsilastirmalar: dizi(x.karsilastirmalar).filter(nesneMi).map(karsilastirmaUyarla),
    karsilastirilamayan: dizi(x.karsilastirilamayan)
      .filter(nesneMi)
      .map((k) => ({
        tablo_id: metinYaDaNull(k.tablo_id),
        tablo_ad: metinYaDaNull(k.tablo_ad),
        column: metin(k.column),
        alan: metin(k.alan),
        alinti: metin(k.alinti),
        case_degeri: deger(k.case_degeri),
        neden: metin(k.neden),
      })),
    istisna: i ? istisnaUyarla(i) : null,
    icerik_hash: metinYaDaNull(x.icerik_hash),
    kontrol_suruyor: suruyor,
    ...degerSayimiUyarla(x.degerler),
    ...("neden" in x ? { neden: metinYaDaNull(x.neden) } : {}),
  };
}

/** Case yanıtındaki `oracle` alanı: alan yoksa `{}` (çekirdek sunmuyor), varsa kayıt ya da null. */
export function caseOracleAlani(ham: unknown): { oracle?: CaseOracle | null } {
  if (!nesneMi(ham) || !("oracle" in ham)) return {};
  return { oracle: oracleUyarla(ham.oracle) };
}

/**
 * `GET /cases/{id}/oracle` yanıtı: çekirdek `{case_id, icerik_hash, guncel_icerik, kapsayan_tablolar,
 * oracle}` sarmalar; kontrol nesnesi `oracle` alanındadır (null: kapsayan tablo yok). Sarmalanmamış
 * (yalın kontrol nesnesi) gövde de okunur.
 */
export function caseOracleYanitiUyarla(x: unknown): CaseOracle | null {
  if (nesneMi(x) && ("oracle" in x || "case_id" in x || "kapsayan_tablolar" in x)) return oracleUyarla(x.oracle);
  return oracleUyarla(x);
}

export function oracleKontrolUyarla(x: unknown): OracleKontrolYaniti {
  const h = nesneMi(x) ? x : {};
  return { job_id: metinYaDaNull(h.job_id), icerik_hash: metinYaDaNull(h.icerik_hash) };
}

/** `{turetilen: [{case_id, kaynak_case_id, baslik}], atlanan: [{kaynak_case_id, sonuc, neden}]}`. */
export function turetmeUyarla(x: unknown): TuretmeYaniti {
  const h = nesneMi(x) ? x : {};
  return {
    turetilen: dizi(h.turetilen)
      .filter(nesneMi)
      .map((k) => ({ case_id: metin(k.case_id), kaynak_case_id: metin(k.kaynak_case_id), baslik: metin(k.baslik) })),
    atlanan: dizi(h.atlanan)
      .filter(nesneMi)
      .map((k) => {
        // Tanınmayan kod başka bir nedene çevrilmez (ekranda yalın "Atlandı" + `neden` metni). Çekirdek yeni
        // kodu sabitlenene dek `belirsiz_alinti` + `neden: "tutarsiz_kalan_deger: …"` gönderebilir: o kod okunur.
        let sonuc = metin(k.sonuc);
        let neden = metinYaDaNull(k.neden);
        const on = "tutarsiz_kalan_deger:";
        if (neden?.startsWith(on)) {
          sonuc = "tutarsiz_kalan_deger";
          neden = neden.slice(on.length).trim() || null;
        }
        return { kaynak_case_id: metin(k.kaynak_case_id), sonuc, neden, ...(metinYaDaNull(k.case_id) ? { case_id: metinYaDaNull(k.case_id) } : {}) };
      }),
  };
}

const sayi = (x: unknown): number => (typeof x === "number" && Number.isFinite(x) ? x : 0);
const oran = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);

/** §4.7 beklenti doğruluğu; alan yoksa `undefined` (çekirdek bildirmiyor), null ise null. */
export function beklentiDogruluguUyarla(x: unknown): BeklentiDogrulugu | null | undefined {
  if (x === undefined) return undefined;
  if (!nesneMi(x)) return null;
  return {
    oran: oran(x.oran),
    uyumlu: sayi(x.uyumlu),
    uyumsuz: sayi(x.uyumsuz),
    kapsam_disi: sayi(x.kapsam_disi),
    kontrol_edilemedi: sayi(x.kontrol_edilemedi),
    istisna: sayi(x.istisna),
    kapsam_orani: oran(x.kapsam_orani),
    // §13.2 ekleri: anahtar yoksa alan eklenmez (sayı uydurulmaz).
    ...Object.fromEntries(
      (["kismen", "kontrolsuz_onay", "n_case", "n_story", "tablolu_story", "toplam_story", "golden_kaynakli"] as const)
        .filter((a) => sayiMi(x[a]))
        .map((a) => [a, x[a] as number]),
    ),
  };
}

/** Triage kaydının case bağı (`case_id` | `test_case_id`, `requirement_id`); alan yoksa eklenmez. */
export function triageCaseBagi(h: unknown): { case_id?: string | null; requirement_id?: string | null } {
  if (!nesneMi(h)) return {};
  const c = metinYaDaNull(h.case_id ?? h.test_case_id);
  const r = metinYaDaNull(h.requirement_id);
  return { ...(c ? { case_id: c } : {}), ...(r ? { requirement_id: r } : {}) };
}

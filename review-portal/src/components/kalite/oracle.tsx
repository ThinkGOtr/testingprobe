// 012 Ş7 — case review: beklenen sonuç kontrolü (oracle) çipi, karşılaştırma tablosu, onay kapısı,
// istisna formu, düzeltme ön kontrolü ve "Beklenti doğruluğu" metriği (specs/012 ANALIZ §4.3, §7).
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useOlay } from "../../api/events";
import { ApiError } from "../../api/http";
import type {
  CaseMetrikleri,
  CaseOracle,
  KararTablosu,
  OracleIstisnasi,
  OracleIstisnaTuru,
  OracleKarsilastirilamayan,
  OracleKarsilastirma,
  TestCase,
  TestCaseIcerik,
} from "../../api/types";
import { beklentiDogruluguUyarla } from "../../api/uyumKalite";
import { useKisiAdi } from "../../auth";
import type { Izin } from "../../lib/yetki";
import { useGeciktirilmis, useVeri } from "../../hooks";
import { kismenNedeniMetni, ORACLE_DURUMU, ORACLE_NEDENI, ORACLE_NEDENI_ACIKLAMA, type OracleGorunumu } from "../../lib/etiketler";
import { alintiMetni, mantiksalMi, mantiksalOku } from "../../lib/ifadeAciklama";
import { tarih, yuzde } from "../../lib/format";
import { AlanHatasi, Cip, IslemDugmesi, Metrik, Olculmedi, Uyari } from "../ui";
import { beklentiNParcalari, beklentiParcalari, CEKIRDEK_BILDIRMIYOR, GOSTERGE_ESIGI } from "../kule/KaliteKpilari";
import "./kalite.css";

export const ISTISNA_EN_AZ = 20;
/** §13.2: gerekçede en az bu kadar harf (boşluk, rakam, noktalama dolgusu sayılmaz). */
export const ISTISNA_EN_AZ_HARF = 10;

/** §13.2 gerekçe kuralı (sunucuyla aynı): ≥ 20 karakter ve ≥ 10 harf; uygunsa null, değilse neden. */
export function gerekceSorunu(g: string): string | null {
  const t = g.trim();
  const harf = (t.match(/\p{L}/gu) ?? []).length;
  if (t.length < ISTISNA_EN_AZ) return `Gerekçe en az ${ISTISNA_EN_AZ} karakter olmalı (şu an ${t.length}).`;
  if (harf < ISTISNA_EN_AZ_HARF) return `Gerekçe en az ${ISTISNA_EN_AZ_HARF} harf içermeli (şu an ${harf}); neden onayladığınızı cümleyle yazın.`;
  return null;
}

/** V11: yüksek risk = saklı, AI özgün ya da gönderilen içerikten biri yüksek (risk düşürülerek kapı aşılmaz). */
export function yuksekRisk(tc: Pick<TestCase, "icerik"> & { ai_icerik?: TestCaseIcerik | null }, onerilen?: Pick<TestCaseIcerik, "risk">): boolean {
  return [tc.icerik.risk, tc.ai_icerik?.risk, onerilen?.risk].includes("high");
}

export const kararTablolariYolu = (requirementId: string, tabloId?: string | null) =>
  `/gereksinimler/${encodeURIComponent(requirementId)}/karar-tablolari${tabloId ? `#tablo-${tabloId}` : ""}`;

// ------------------------------------------------------------------ kapsayan tablolar (bağlam)

interface KaliteBaglami {
  /** Gereksinimin karar tabloları; `null`: bilinmiyor (yüklenmedi ya da çekirdek sunmuyor). */
  tablolar: KararTablosu[] | null;
}
const Baglam = createContext<KaliteBaglami>({ tablolar: null });

/** Case listesini sarar: kartlar "kapsayan onaylı tablo var mı" sorusunu buradan yanıtlar. */
export function KaliteSaglayici({ requirementId, children }: { requirementId: string; children: ReactNode }) {
  const veri = useVeri(() => api.kararTablolari(requirementId).then((y) => y.tablolar, () => null), [requirementId]);
  const sessiz = useGeciktirilmis(() => void veri.yenile(true));
  useOlay((o) => {
    if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== requirementId) return;
    sessiz();
  }, ["karar_tablosu.updated", "requirement.updated"]);
  const deger = useMemo(() => ({ tablolar: veri.veri ?? null }), [veri.veri]);
  return <Baglam.Provider value={deger}>{children}</Baglam.Provider>;
}

const acAnahtari = (r: string) => r.replace(/\s/g, "").toUpperCase();

/** İçeriğin kabul kriterlerini kapsayan onaylı ve bayat olmayan tablolar (§4.3 adım 1). */
export function kapsayanTablolar(icerik: Pick<TestCaseIcerik, "acceptance_criteria_refs">, tablolar: KararTablosu[]): KararTablosu[] {
  const refs = new Set(icerik.acceptance_criteria_refs.map(acAnahtari));
  return tablolar.filter((t) => t.durum === "approved" && !t.bayat && t.icerik.ac_refs.some((r) => refs.has(acAnahtari(r))));
}

/**
 * Kartta gösterilecek kontrol durumu. `null`: gösterilecek bilgi yok (çekirdek `oracle` alanını ve
 * tablo listesini sunmuyor) — "Tablo yok" uydurulmaz.
 */
export function oracleGorunumu(tc: Pick<TestCase, "oracle" | "icerik">, tablolar: KararTablosu[] | null): OracleGorunumu | null {
  const o = tc.oracle;
  if (o?.kontrol_suruyor) return "suruyor";
  if (o?.sonuc && o.sonuc !== "kapsam_disi") return o.sonuc;
  // Kayıt yok (ya da tablo onayından önceki "kapsam dışı" kaydı) ama kapsayan onaylı tablo var: iş sürüyor.
  if (tablolar && kapsayanTablolar(tc.icerik, tablolar).length > 0) return "suruyor";
  // Kayıt "kapsam dışı" diyor ya da tablo listesi biliniyor ve kapsayan yok.
  if (o || tablolar !== null) return "tablo_yok";
  return null;
}

export interface OracleKapisiDurumu {
  gorunum: OracleGorunumu | null;
  /** "Onayla"nın görünür pasiflik nedeni (yüksek risk: uyuşmazlık, kontrol edilemedi ya da sunucunun bildirdiği süren kontrol). */
  engel: string | null;
  /** Onay açık ama uyarı gösterilir (orta/düşük risk uyuşmazlığı ya da kontrol edilemedi; her riskte kısmen uyumlu). */
  uyari: string | null;
  /** Yüksek riskli uyuşmazlık ya da kontrol edilemedi: gerekçeli onay önerilir. */
  istisnaGerekli: boolean;
  /** §13.2 gerekçeli onayın türü (`uyumsuz`: tabloya rağmen; `kontrolsuz`: kontrol edilemeden). */
  istisnaTuru: OracleIstisnaTuru | null;
  /** Sunucu "kontrol sürüyor" diyor: "Kontrolü yeniden iste" önerilir. */
  suruyor: boolean;
  /** Tur 2 (S1): aynı tür + içerik + tablo kümesiyle verilmiş geçerli saklı istisna; kapı gerekçeyi yeniden istemez. */
  sakliIstisna: OracleIstisnasi | null;
  /** Tur 2: kısmen sonucun nedenleri (düz Türkçe gösterilir); yoksa boş. */
  kismenNedenleri: string[];
}

export const ENGEL_UYUMSUZ = "Beklenen değer onaylı karar tablosuyla uyuşmuyor. Yüksek riskli case gerekçeli istisna olmadan onaylanamaz.";
export const ENGEL_SURUYOR = "Beklenen sonuç kontrolü sürüyor; bitince onaylanabilir.";
export const ENGEL_KONTROLSUZ =
  "Beklenen değer onaylı karar tablosuyla kontrol edilemedi. Yüksek riskli case, değerleri elle doğruladığınızı söyleyen bir gerekçe olmadan onaylanamaz.";
export const UYARI_KISMEN = "Karşılaştırılan değerler tabloyla aynı; bazı değerler kontrol edilemedi. Onay engellenmez; o değerleri elle doğrulayın.";
export const ENGEL_KISMEN =
  "Karşılaştırılan değerler tabloyla aynı, ama bazı beklenen değerler doğrulanamadı. Yüksek riskli case, o değerleri elle doğruladığınızı söyleyen bir gerekçe olmadan onaylanamaz.";
/** Tur 2 (Y4): `eksik_girdi` dışındaki kısmen nedenleri zorunlu kapıda gerekçe ister (nedenler yoksa eski davranış: uyarı). */
export const kismenGerekceIster = (o: CaseOracle | null | undefined): boolean => (o?.kismen_nedeni ?? []).some((n) => n !== "eksik_girdi");
export const UYARI_UYUMSUZ = "Beklenen değer onaylı karar tablosuyla uyuşmuyor. Onay engellenmez; uyarı kayda geçer.";
export const UYARI_KONTROL_EDILEMEDI = "Beklenen değer tabloyla karşılaştırılamadı. Onaylamadan önce değerleri elle doğrulayın; onay uyarıyla kayda geçer.";

/** Kısmen uyumlu sonuçta kontrol edilemeyen değer sayısı: `degerler` varsa oradan, yoksa listeden. */
export function kontrolEdilemeyenSayisi(o: CaseOracle | null | undefined): number {
  if (!o) return 0;
  return o.degerler ? o.degerler.karsilastirilamayan + o.degerler.atilan : o.karsilastirilamayan.length;
}

/**
 * ANALIZ §4.3 kapı tablosu + §13 (K10, K11, V11) + tur 2 — ekran tarafı; sunucu aynı kuralı uygular (mock/core
 * uyumu `oracle.test.tsx`'te §13.2 tablosuyla denetlenir). Aynı tür + içerik + tablo kümesiyle verilmiş geçerli
 * saklı istisna (`istisna.gecerli`) kapıyı açar (S1, çekirdekle tek kural). Yüksek riskte kısmen sonuç, nedeni
 * eksik girdi dışındaysa gerekçe ister (tür `kontrolsuz`). "Sürüyor" yalnız sunucu `kontrol_suruyor` dediğinde engeller.
 */
export function oracleKapisi(tc: Pick<TestCase, "oracle" | "icerik"> & { ai_icerik?: TestCaseIcerik | null }, tablolar: KararTablosu[] | null): OracleKapisiDurumu {
  const gorunum = oracleGorunumu(tc, tablolar);
  const yuksek = yuksekRisk(tc);
  const o = tc.oracle;
  const d: OracleKapisiDurumu = {
    gorunum,
    engel: null,
    uyari: null,
    istisnaGerekli: false,
    istisnaTuru: null,
    suruyor: false,
    sakliIstisna: null,
    kismenNedenleri: gorunum === "kismen" ? [...(o?.kismen_nedeni ?? [])] : [],
  };
  const zorunlu = (tur: OracleIstisnaTuru, engel: string) => {
    const i = o?.istisna;
    // Saklı istisna yalnız aynı içeriğe (hash biliniyorsa), aynı türe ve geçerliyse kapıyı açar.
    if (i && i.gecerli === true && (i.tur ?? tur) === tur && (!i.icerik_hash || !o?.icerik_hash || i.icerik_hash === o.icerik_hash)) {
      d.sakliIstisna = i;
      return;
    }
    d.engel = engel;
    d.istisnaGerekli = true;
    d.istisnaTuru = tur;
  };
  if (gorunum === "uyumsuz") {
    if (!yuksek) d.uyari = UYARI_UYUMSUZ;
    else zorunlu("uyumsuz", ENGEL_UYUMSUZ);
  } else if (gorunum === "kismen") {
    if (yuksek && kismenGerekceIster(o)) zorunlu("kontrolsuz", ENGEL_KISMEN);
    else d.uyari = UYARI_KISMEN;
  } else if (gorunum === "kontrol_edilemedi") {
    if (!yuksek) d.uyari = UYARI_KONTROL_EDILEMEDI;
    else zorunlu("kontrolsuz", ENGEL_KONTROLSUZ);
  } else if (gorunum === "suruyor") {
    d.suruyor = true;
    if (yuksek && tc.oracle?.kontrol_suruyor) d.engel = ENGEL_SURUYOR;
  }
  return d;
}

export function useOracleKapisi(tc: TestCase): OracleKapisiDurumu {
  const { tablolar } = useContext(Baglam);
  return useMemo(() => oracleKapisi(tc, tablolar), [tc, tablolar]);
}

/** Sunucunun kapı hataları (422 `oracle_uyumsuz` / `oracle_kontrolsuz`, 409 `oracle_bekleniyor`). */
export function oracleHatasi(e: unknown): e is ApiError {
  return e instanceof ApiError && (e.kod === "oracle_uyumsuz" || e.kod === "oracle_bekleniyor" || e.kod === "oracle_kontrolsuz" || e.kod === "oracle_kayit_degisti");
}

/** Tur 2 (Y9): karar gövdesine kontrol kaydının damgası (çekirdek vermezse alan yok). */
export function damgaAlani(o: CaseOracle | null | undefined): { oracle_kayit_damgasi?: string } {
  // Q1: kayıt yokken çekirdek damgayı "yok" yazar; o zaman gönderilmez.
  return o?.damga && o.damga !== "yok" ? { oracle_kayit_damgasi: o.damga } : {};
}

/** Q1: tamlık denetimi nedenleri (kapsanmayan sayı türleri) düz Türkçe; diğer nedenler aynen. */
export function karsilastirilamamaNedeni(neden: string): string {
  if (/^Beklenen alandaki sayı/.test(neden)) return "case metninde karşılaştırılmayan sayı";
  if (/^Girdi alanındaki sayı/.test(neden) || /^çelişkili girdi/.test(neden)) return "girdi değeri çelişiyor";
  if (/^Yazıyla yazılmış sayı/i.test(neden)) return "yazıyla yazılmış sayı";
  return neden;
}

/**
 * Karar isteğini sarar: sunucu kapı hatası verirse (ekran eski kontrol sonucunu gösteriyordu) liste
 * yenilenir; hata yine fırlatılır ve kartta gösterilir.
 */
export function oracleHatasindaYenile<T>(fn: () => Promise<T>, yenile?: () => void): () => Promise<T> {
  return async () => {
    try {
      return await fn();
    } catch (e) {
      if (oracleHatasi(e)) yenile?.();
      throw e;
    }
  };
}

// ------------------------------------------------------------------ çip ve karşılaştırma

/** Çip metni: kısmen uyumluda kontrol edilemeyen sayı; model hatasında neden (§13.2). */
export function oracleCipMetni(gorunum: OracleGorunumu, o: CaseOracle | null | undefined): string {
  if (gorunum === "kismen") {
    const n = kontrolEdilemeyenSayisi(o);
    return n > 0 ? `Kısmen uyumlu — ${n} değer kontrol edilemedi` : "Kısmen uyumlu";
  }
  if (gorunum === "kontrol_edilemedi" && o?.neden && ORACLE_NEDENI[o.neden]) return ORACLE_NEDENI[o.neden];
  return ORACLE_DURUMU[gorunum].etiket;
}

export function OracleCipi({ tc }: { tc: TestCase }) {
  const { gorunum } = useOracleKapisi(tc);
  if (!gorunum) return null;
  const d = ORACLE_DURUMU[gorunum];
  return (
    <span data-testid="oracle-cip">
      <Cip ton={d.ton} title={d.aciklama}>
        {oracleCipMetni(gorunum, tc.oracle)}
      </Cip>
    </span>
  );
}

const ALAN_ADI: Record<string, string> = { title: "Başlık", expected_result: "Beklenen sonuç" };

/** `steps[3].expected` → "S4 beklenen"; `preconditions[0]` → "Ön koşul 1". */
export function alanEtiketi(yol: string): string {
  if (ALAN_ADI[yol]) return ALAN_ADI[yol];
  const adim = /^steps\[(\d+)\]\.(action|data|expected)$/.exec(yol);
  if (adim) return `S${Number(adim[1]) + 1} ${{ action: "eylem", data: "veri", expected: "beklenen" }[adim[2] as "action" | "data" | "expected"]}`;
  const on = /^preconditions\[(\d+)\]$/.exec(yol);
  return on ? `Ön koşul ${Number(on[1]) + 1}` : yol;
}

/** Karşılaştırma değeri: sayı metni ondalık virgülle, mantıksal "doğru"/"yanlış". */
export function degerMetni(d: string | number | boolean | null | undefined): string {
  if (d === null || d === undefined || d === "") return "—";
  if (typeof d === "boolean") return d ? "doğru" : "yanlış";
  if (typeof d === "number") return d.toLocaleString("tr-TR", { maximumFractionDigits: 6 });
  return /^-?\d+\.\d+$/.test(d) ? d.replace(".", ",") : d;
}

/** Sayısal çıktının toleransı (tablo tanımından; "± 0,01"). Tolerans 0 ya da bilinmiyorsa çizilmez. */
function toleransMetni(k: OracleKarsilastirma, toleranslar: Record<string, string>): ReactNode {
  const t = toleranslar[`${k.tablo_id ?? ""}|${k.column}`];
  if (!t || Number(t.replace(",", ".")) === 0) return null;
  return <span className="soluk kucuk"> ± {t.replace(".", ",")}</span>;
}

/** Bağlamdaki tablolardan `tablo_id|kolon` → tolerans. */
function useToleranslar(): Record<string, string> {
  const { tablolar } = useContext(Baglam);
  return useMemo(
    () => Object.fromEntries((tablolar ?? []).flatMap((t) => t.icerik.ciktilar.filter((c) => c.tur === "sayi" && c.tolerans).map((c) => [`${t.id}|${c.ad}`, String(c.tolerans)]))),
    [tablolar],
  );
}

/**
 * Çekirdek özeti alıntıyı “…” ile sarar; alıntı zaten tırnakla başlıyor/bitiyorsa çift tırnak (““…”) olur.
 * Ekranda bitişik tırnak çifti teke indirilir (koordinatör ekran turu 1).
 */
export function ozetMetni(ozet: string): string {
  // Tırnakla başlayan alıntının dış “…” sarmalı kaldırılır (içerik aynen kalır).
  return ozet.replace(/“(["'][^”]*)”/g, "$1");
}

/** Karşılaştırma hücresi: mantıksal çıktı iş dilinde (u2 N18), diğerleri `degerMetni`. */
export function karsilastirmaDegeri(column: string, d: string | number | boolean | null | undefined): string {
  return mantiksalMi(d) ? mantiksalOku(column, d) : degerMetni(d);
}

/** Bağlamdaki tablolardan `tablo_id` → "T2". */
function useTabloRefleri(): Record<string, string> {
  const { tablolar } = useContext(Baglam);
  return useMemo(() => Object.fromEntries((tablolar ?? []).map((t) => [t.id, `T${t.sira_no}`])), [tablolar]);
}

export function KarsilastirmaTablosu({
  satirlar,
  baslik,
  karsilastirilamayan = [],
}: {
  satirlar: OracleKarsilastirma[];
  baslik: string;
  /** Eksik girdi yüzünden karşılaştırılamayan değerler: ayrı, soluk grup; sonuca girmez. */
  karsilastirilamayan?: OracleKarsilastirilamayan[];
}) {
  const toleranslar = useToleranslar();
  const refler = useTabloRefleri();
  const nedenler = [...new Set(karsilastirilamayan.map((k) => k.neden))];
  return (
    <div className="tablo-sarici" tabIndex={0} role="region" aria-label={baslik}>
      <table className="tablo tablo-sik tablo-yigin">
        <caption className="gorunmez">{baslik}</caption>
        <thead>
          <tr>
            <th scope="col">Alan</th>
            <th scope="col">Case metnindeki ifade</th>
            <th scope="col">Case değeri</th>
            <th scope="col">Tablo değeri</th>
            <th scope="col">Sonuç</th>
          </tr>
        </thead>
        <tbody>
          {satirlar.map((k, i) => (
            <tr key={`${k.alan}-${k.column}-${i}`} className={k.uyumlu ? undefined : "oracle-farkli"}>
              <td data-etiket="Alan">
                <span className="mono">{k.column}</span> <span className="soluk kucuk">· {alanEtiketi(k.alan)}</span>
              </td>
              <td data-etiket="Case metnindeki ifade">{alintiMetni(k.alinti)}</td>
              <td className="mono" data-etiket="Case değeri">
                {karsilastirmaDegeri(k.column, k.case_degeri)}
              </td>
              <td className="mono" data-etiket="Tablo değeri">
                {karsilastirmaDegeri(k.column, k.tablo_degeri)}
                {toleransMetni(k, toleranslar)}
                {k.satir_id && (
                  <span className="soluk kucuk">
                    {" "}
                    · {k.tablo_id && refler[k.tablo_id] ? `${refler[k.tablo_id]} · ` : "satır "}
                    {k.satir_id}
                  </span>
                )}
              </td>
              <td data-etiket="Sonuç" className={k.uyumlu ? undefined : "hata-metin"}>
                {k.uyumlu ? "Aynı ✓" : "Farklı ✗"}
              </td>
            </tr>
          ))}
        </tbody>
        {nedenler.map((neden) => (
          <tbody key={neden} className="oracle-karsilastirilamadi" data-testid="oracle-karsilastirilamadi">
            <tr>
              <th scope="rowgroup" colSpan={5} className="kucuk" title={neden}>
                Karşılaştırılamadı: {karsilastirilamamaNedeni(neden)}
              </th>
            </tr>
            {karsilastirilamayan
              .filter((k) => k.neden === neden)
              .map((k, i) => (
                <tr key={`${k.alan}-${k.column}-${i}`}>
                  <td data-etiket="Alan">
                    <span className="mono">{k.column}</span> <span className="kucuk">· {alanEtiketi(k.alan)}</span>
                  </td>
                  <td data-etiket="Case metnindeki ifade">{alintiMetni(k.alinti)}</td>
                  <td className="mono" data-etiket="Case değeri">
                    {karsilastirmaDegeri(k.column, k.case_degeri)}
                  </td>
                  <td className="mono" data-etiket="Tablo değeri">
                    —
                  </td>
                  <td data-etiket="Sonuç">Sonuca girmez</td>
                </tr>
              ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

function IstisnaNotu({ oracle, kapidaGosteriliyor = false }: { oracle: CaseOracle; kapidaGosteriliyor?: boolean }) {
  const kisiAdi = useKisiAdi();
  if (!oracle.istisna) return null;
  const i = oracle.istisna;
  const kunye = (
    <span className="soluk">
      {i.veren && ` — ${kisiAdi(i.veren)}`}
      {i.zaman && `, ${tarih(i.zaman)}`}
    </span>
  );
  // Taslak case'te geçerli saklı istisna kapı bölümünde gösterilir ("Saklı istisna geçerli", Onayla açık).
  if (i.gecerli === true && kapidaGosteriliyor) return null;
  return (
    <p className="kucuk" data-testid="oracle-istisna">
      <strong>{i.tur === "kontrolsuz" ? "Kontrol edilemeden onay gerekçesi:" : "Gerekçeli istisna:"}</strong> {i.gerekce}
      {kunye}
      <span className="soluk">
        {i.gecerli === false
          ? " Bu istisna artık geçerli değil (tablo ya da içerik değişti); onayda gerekçe yeniden istenir."
          : i.gecerli === true
            ? " Aynı içerik ve aynı onaylı tablolarla geçerli; yeniden onayda gerekçe istenmez."
            : " Saklı gerekçe bu içerik ve aynı tablolarla geçerli olduğu sürece yeniden kullanılır."}
      </span>
    </p>
  );
}

/** Tur 2 (S1): geçerli saklı istisna — "Saklı istisna geçerli: <gerekçe> — <veren>, <zaman>"; Onayla açıktır. */
export function SakliIstisnaNotu({ istisna }: { istisna: OracleIstisnasi }) {
  const kisiAdi = useKisiAdi();
  return (
    <p className="kucuk oracle-sakli" data-testid="oracle-sakli-istisna">
      <strong>Saklı istisna geçerli:</strong> {istisna.gerekce}
      {istisna.veren && ` — ${kisiAdi(istisna.veren)}`}
      {istisna.zaman && `, ${tarih(istisna.zaman)}`}
      <span className="soluk"> · Aynı içerik ve aynı onaylı tablolarla verildi; onay gerekçesiz verilebilir, yeniden kullanım denetime yazılır.</span>
    </p>
  );
}

/** "Kontrolü yeniden iste" (analist): güncel içerik için kontrol işi açar; sonuç `oracle.checked` ile gelir. */
export function KontrolYenidenIste({ tc }: { tc: TestCase }) {
  const [durum, setDurum] = useState<"bos" | "istendi" | "hata">("bos");
  const [calisiyor, setCalisiyor] = useState(false);
  async function iste() {
    setCalisiyor(true);
    try {
      await api.caseOracleKontrol(tc.id);
      setDurum("istendi");
    } catch {
      setDurum("hata");
    } finally {
      setCalisiyor(false);
    }
  }
  return (
    <span className="satir-ogeler" data-testid="oracle-yeniden-iste">
      <IslemDugmesi izin="case.oracle_check" kucuk tur="ikincil" calisiyor={calisiyor} onClick={() => void iste()}>
        Kontrolü yeniden iste
      </IslemDugmesi>
      <span role="status" className="soluk kucuk">
        {durum === "istendi" ? "Kontrol istendi; sonuç gelince kart güncellenir." : durum === "hata" ? "Kontrol istenemedi; yeniden deneyin." : ""}
      </span>
    </span>
  );
}

/** Kartın gövdesindeki açılır karşılaştırma ve tabloya bağlantı. */
export function OracleAyrinti({ tc }: { tc: TestCase }) {
  const { gorunum } = useOracleKapisi(tc);
  if (!gorunum) return null;
  const o = tc.oracle;
  const satirlar = o?.karsilastirmalar ?? [];
  const disarida = o?.karsilastirilamayan ?? [];
  const tabloId = satirlar[0]?.tablo_id ?? disarida[0]?.tablo_id;
  const baglanti = <Link to={kararTablolariYolu(tc.requirement_id, tabloId)}>Karar tablolarını aç</Link>;
  if (gorunum === "tablo_yok" || gorunum === "suruyor") {
    return (
      <div className="oracle-ozet-satir">
        <p className="soluk kucuk oracle-ozet" data-testid="oracle-ozet">
          {ORACLE_DURUMU[gorunum].aciklama}
          {gorunum === "suruyor" && !o?.kontrol_suruyor && " Sunucuda bu içerik için kontrol kaydı görünmüyor; gerekirse kontrolü yeniden isteyin."} {baglanti}
        </p>
        {gorunum === "suruyor" && tc.durum === "draft" && <KontrolYenidenIste tc={tc} />}
      </div>
    );
  }
  const d = o?.degerler;
  return (
    <details className="oracle-ayrinti" data-testid="oracle-ayrinti" open={gorunum === "uyumsuz" || gorunum === "kismen" || undefined}>
      <summary className="kucuk">
        Tablo karşılaştırması{satirlar.length > 0 && ` (${satirlar.length} değer, ${satirlar.filter((k) => !k.uyumlu).length} farklı`}
        {satirlar.length > 0 && (disarida.length > 0 ? `, ${disarida.length} karşılaştırılamadı)` : ")")}
      </summary>
      {o?.ozet && <p className="kucuk">{ozetMetni(o.ozet)}</p>}
      {d && (
        <p className="kucuk soluk" data-testid="oracle-degerler">
          Değer düzeyinde: {d.uyumlu} uyumlu · {d.uyumsuz} farklı · {d.karsilastirilamayan} karşılaştırılamadı{d.atilan > 0 ? ` · ${d.atilan} doğrulanamadığı için atıldı` : ""}
        </p>
      )}
      {gorunum === "kismen" && (o?.kismen_nedeni?.length ?? 0) > 0 && (
        <div className="kucuk" data-testid="oracle-kismen-nedeni">
          Neden kısmen:
          <ul className="duz-liste">
            {[...new Set(o!.kismen_nedeni)].map((n) => (
              <li key={n}>{kismenNedeniMetni(n)}</li>
            ))}
          </ul>
        </div>
      )}
      {o?.neden && ORACLE_NEDENI[o.neden] && (
        <p className="kucuk" data-testid="oracle-neden">
          {ORACLE_NEDENI[o.neden]}: {ORACLE_NEDENI_ACIKLAMA[o.neden] ?? "tablo ile case karşılaştırılmadı."}
        </p>
      )}
      {(satirlar.length > 0 || disarida.length > 0) && (
        <KarsilastirmaTablosu satirlar={satirlar} karsilastirilamayan={disarida} baslik={`Tablo karşılaştırması: ${tc.icerik.title}`} />
      )}
      {o && <IstisnaNotu oracle={o} kapidaGosteriliyor={tc.durum === "draft"} />}
      <p className="kucuk">{baglanti}</p>
      {gorunum === "kontrol_edilemedi" && tc.durum === "draft" && <KontrolYenidenIste tc={tc} />}
    </details>
  );
}

// ------------------------------------------------------------------ istisna formu

export function IstisnaFormu({
  gonder,
  vazgec,
  calisiyor,
  dugmeMetni = "İstisnayla onayla",
  tur = "uyumsuz",
  izin = "case.decide",
}: {
  gonder: (gerekce: string) => void;
  vazgec: () => void;
  calisiyor: boolean;
  dugmeMetni?: string;
  tur?: OracleIstisnaTuru;
  /** Kararı veren rolün izni: Testçi kabulü/düzeltmesi `case.decide`, Analist son onayı `case.approve`. */
  izin?: Izin;
}) {
  const [gerekce, setGerekce] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  const alan = useRef<HTMLTextAreaElement | null>(null);
  // Satır içi form açılınca odak gerekçe alanına geçer (klavye kullanıcısı formu aramaz).
  useEffect(() => alan.current?.focus(), []);
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const sorun = gerekceSorunu(gerekce);
    if (sorun) {
      setUyari(sorun);
      alan.current?.focus();
      return;
    }
    setUyari(null);
    gonder(gerekce.trim());
  }
  return (
    <form className="ret-formu istisna-formu" onSubmit={onSubmit} noValidate data-testid="istisna-formu" data-tur={tur}>
      <div className="alan">
        <label htmlFor={`${id}-gerekce`}>{tur === "kontrolsuz" ? "Neden kontrolsüz onaylıyorsunuz?" : "İstisna gerekçesi"}</label>
        <textarea
          ref={alan}
          id={`${id}-gerekce`}
          rows={3}
          value={gerekce}
          aria-required="true"
          aria-invalid={uyari ? true : undefined}
          aria-describedby={`${id}-ipucu`}
          onChange={(e) => setGerekce(e.target.value)}
        />
        <span id={`${id}-ipucu`} className="soluk kucuk">
          En az {ISTISNA_EN_AZ} karakter ve {ISTISNA_EN_AZ_HARF} harf.{" "}
          {tur === "kontrolsuz"
            ? "Değerleri elle nasıl doğruladığınızı yazın. Gerekçe, adınız ve zaman denetim kaydına ve Kontrol Kulesi “kontrolsüz onay” sayacına düşer."
            : "Gerekçe, adınız ve zaman denetim kaydına ve Kontrol Kulesi istisna sayacına düşer."}
        </span>
      </div>
      {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
      <div className="eylemler">
        <IslemDugmesi izin={izin} type="submit" kucuk calisiyor={calisiyor}>
          {dugmeMetni}
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** "Tablo yanlış" etkisi: tablonun kabul kriterine atıf yapan, kontrolü süren (taslak/onaylı/yayınlı) case sayısı. */
export function etkilenenCaseSayisi(tablo: KararTablosu, caseler: TestCase[]): number {
  const refs = new Set(tablo.icerik.ac_refs.map(acAnahtari));
  return caseler.filter(
    (c) => c.requirement_id === tablo.requirement_id && ["draft", "approved", "published"].includes(c.durum) && c.icerik.acceptance_criteria_refs.some((r) => refs.has(acAnahtari(r))),
  ).length;
}

/**
 * V10 "Tablo yanlış" yolu (u2 N5): case'i kapsayan onaylı tabloyu yeniden açar (taslağa döner, PO onayı yeniden
 * gerekir); case onaylanmaz. Önce etki onayı ("N case'in kontrolü durur") ve zorunlu gerekçe; gerekçe ve case
 * tablonun geçmişine yazılır, PO tablo yeniden gelince görür. Tablo bağlamda bilinmiyorsa yalnız bağlantı verilir.
 */
function TabloYanlisYolu({ tc }: { tc: TestCase }) {
  const { tablolar } = useContext(Baglam);
  const farkliTabloId = tc.oracle?.karsilastirmalar.find((k) => !k.uyumlu)?.tablo_id ?? null;
  const tablo =
    (tablolar ?? []).find((t) => t.id === farkliTabloId && t.durum === "approved") ?? (tablolar ? kapsayanTablolar(tc.icerik, tablolar)[0] : undefined) ?? null;
  const [durum, setDurum] = useState<"bos" | "onay" | "acildi" | "hata">("bos");
  const [hata, setHata] = useState<string | null>(null);
  const [calisiyor, setCalisiyor] = useState(false);
  const [etki, setEtki] = useState<number | null>(null);
  const [gerekce, setGerekce] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  const alan = useRef<HTMLTextAreaElement | null>(null);
  const acan = useRef<HTMLSpanElement | null>(null);
  const yolu = kararTablolariYolu(tc.requirement_id, tablo?.id ?? farkliTabloId);
  useEffect(() => {
    if (durum !== "onay" || !tablo) return;
    alan.current?.focus();
    let iptal = false;
    api.caseler(tc.requirement_id).then(
      (l) => !iptal && setEtki(etkilenenCaseSayisi(tablo, l)),
      () => !iptal && setEtki(null),
    );
    return () => {
      iptal = true;
    };
  }, [durum, tablo, tc.requirement_id]);
  async function yenidenAc(e: FormEvent) {
    e.preventDefault();
    if (!tablo) return;
    const g = gerekce.trim();
    const sorun = gerekceSorunu(g);
    if (sorun) {
      setUyari(sorun.replace("Gerekçe", "Tablonun neden yanlış olduğu"));
      alan.current?.focus();
      return;
    }
    setUyari(null);
    setCalisiyor(true);
    try {
      await api.kararTablosuGecis(tablo.id, "reopen", { icerik_hash: tablo.icerik_hash, gerekce: g, case_id: tc.id });
      setDurum("acildi");
    } catch (err) {
      setHata(err instanceof Error ? err.message : "Tablo yeniden açılamadı.");
      setDurum("hata");
    } finally {
      setCalisiyor(false);
    }
  }
  return (
    <div className="oracle-yol" data-testid="oracle-tablo-yanlis">
      <p className="kucuk">
        <strong>Tablo yanlış:</strong> case doğru ama onaylı tablo kuralı yanlış yazıyorsa tabloyu yeniden açın; düzeltilip PO onayından geçince kontrol yeniden
        yapılır. Case bu yolla onaylanmaz.
      </p>
      {durum === "acildi" ? (
        <p className="kucuk" role="status">
          Tablo taslağa döndü; gerekçeniz tablonun geçmişine yazıldı. <Link to={yolu}>Tabloyu düzeltin ve PO onayına gönderin</Link>.
        </p>
      ) : durum === "onay" && tablo ? (
        <form className="ret-formu" onSubmit={(e) => void yenidenAc(e)} noValidate data-testid="tablo-yanlis-onay">
          <p className="kucuk" role="status" data-testid="tablo-yanlis-etki">
            <strong>
              T{tablo.sira_no} yeniden açılırsa{" "}
              {etki === null ? "bu tabloyla kontrol edilen case'lerin" : `${etki} case'in`} kontrolü durur
            </strong>{" "}
            (tablo yeniden PO onayından geçene dek kapsam dışı sayılırlar).
          </p>
          <div className="alan">
            <label htmlFor={`${id}-gerekce`}>Tablo neden yanlış?</label>
            <textarea
              ref={alan}
              id={`${id}-gerekce`}
              rows={2}
              value={gerekce}
              aria-required="true"
              aria-invalid={uyari ? true : undefined}
              aria-describedby={`${id}-ipucu`}
              onChange={(e) => setGerekce(e.target.value)}
            />
            <span id={`${id}-ipucu`} className="soluk kucuk">
              En az {ISTISNA_EN_AZ} karakter. Gerekçe ve bu case tablonun geçmişine yazılır; PO tabloyu yeniden onaylarken görür.
            </span>
          </div>
          {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
          <div className="eylemler">
            <IslemDugmesi izin="decision_table.edit" type="submit" kucuk tur="tehlike" calisiyor={calisiyor}>
              Tabloyu yeniden aç
            </IslemDugmesi>
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              onClick={() => {
                setDurum("bos");
                requestAnimationFrame(() => acan.current?.querySelector("button")?.focus());
              }}
            >
              Vazgeç
            </button>
          </div>
        </form>
      ) : tablo ? (
        <span ref={acan} className="satir-ogeler">
          <IslemDugmesi izin="decision_table.edit" kucuk tur="ikincil" onClick={() => setDurum("onay")}>
            Tablo yanlış → tabloyu yeniden aç
          </IslemDugmesi>
          <Link className="kucuk" to={yolu}>
            T{tablo.sira_no} · {tablo.icerik.ad}
          </Link>
        </span>
      ) : (
        <Link className="dugme dugme-ikincil dugme-kucuk" to={yolu}>
          Tablo yanlış → karar tablosunu aç
        </Link>
      )}
      {durum === "hata" && hata && <AlanHatasi>{hata}</AlanHatasi>}
    </div>
  );
}

/**
 * Kartın altındaki kapı bölümü: uyarı (orta/düşük risk, kısmen uyumlu) ya da yüksek riskte gerekçeli onay.
 * Uyuşmazlıkta iki yol (V10): "Case doğru, istisnayla onayla" ve "Tablo yanlış → tabloyu yeniden aç".
 * Kontrol edilemediğinde (K10): "Kontrol edilemedi, yine de onayla" (gerekçe, tür `kontrolsuz`).
 */
export function OracleKapisi({
  kapi,
  calisiyor,
  onayla,
  tc,
  izin = "case.decide",
}: {
  kapi: OracleKapisiDurumu;
  calisiyor: boolean;
  onayla: (gerekce: string, tur: OracleIstisnaTuru) => void;
  /** Verilirse uyuşmazlıkta "Tablo yanlış" yolu ve süren kontrolde "Kontrolü yeniden iste" sunulur. */
  tc?: TestCase;
  /** 012 rol modeli: kapı Testçi kabulünde (`case.decide`) ve Analist son onayında (`case.approve`). */
  izin?: Izin;
}) {
  const [acik, setAcik] = useState(false);
  const dugme = useRef<HTMLSpanElement | null>(null);
  if (kapi.sakliIstisna) {
    return (
      <div className="oracle-kapi" data-testid="oracle-kapi" data-tur="sakli">
        <SakliIstisnaNotu istisna={kapi.sakliIstisna} />
      </div>
    );
  }
  if (kapi.uyari) {
    return (
      <div data-testid="oracle-uyari">
        <Uyari baslik={kapi.gorunum === "uyumsuz" ? "Tabloyla uyuşmuyor" : kapi.gorunum === "kismen" ? "Kısmen uyumlu" : "Kontrol edilemedi"}>{kapi.uyari}</Uyari>
      </div>
    );
  }
  if (kapi.engel && kapi.suruyor && tc) {
    return (
      <div className="oracle-kapi" data-testid="oracle-kapi">
        <KontrolYenidenIste tc={tc} />
      </div>
    );
  }
  if (!kapi.istisnaGerekli || !kapi.istisnaTuru) return null;
  const tur = kapi.istisnaTuru;
  const kismen = kapi.gorunum === "kismen";
  const metin = tur === "kontrolsuz" ? (kismen ? "Değerleri elle doğruladım, onayla" : "Kontrol edilemedi, yine de onayla") : "Case doğru, istisnayla onayla";
  return (
    <div className="oracle-kapi" data-testid="oracle-kapi" data-tur={tur}>
      {acik ? (
        <IstisnaFormu
          calisiyor={calisiyor}
          tur={tur}
          dugmeMetni={metin}
          izin={izin}
          gonder={(g) => onayla(g, tur)}
          vazgec={() => {
            setAcik(false);
            // Form kapanınca odak onu açan düğmeye döner.
            requestAnimationFrame(() => dugme.current?.querySelector("button")?.focus());
          }}
        />
      ) : null}
      <span ref={dugme} className="satir-ogeler" hidden={acik}>
        <IslemDugmesi izin={izin} kucuk tur="ikincil" onClick={() => setAcik(true)}>
          {metin}
        </IslemDugmesi>
        <span className="soluk kucuk">
          {tur === "kontrolsuz"
            ? kismen
              ? `Doğrulanamayan değerler: ${kapi.kismenNedenleri.map(kismenNedeniMetni).join("; ") || "nedeni bildirilmedi"}. Elle doğruladıysanız gerekçe yazarak onaylayın.`
              : "Değerleri elle doğruladıysanız gerekçe yazarak onaylayabilir ya da kontrolü yeniden isteyebilirsiniz."
            : "Uyuşmazlık bilinçliyse gerekçe yazarak onaylayabilir ya da “Düzelt” ile değeri tabloya getirebilirsiniz."}
        </span>
      </span>
      {tc && !acik && tur === "uyumsuz" && <TabloYanlisYolu tc={tc} />}
      {tc && !acik && tur === "kontrolsuz" && !kismen && <KontrolYenidenIste tc={tc} />}
    </div>
  );
}

// ------------------------------------------------------------------ düzeltme ön kontrolü

/** Bekleme ayarları (testler kısaltır). */
export const ON_KONTROL = { araMs: 1000, zamanAsimiMs: 20000 };

type OnKontrolDurumu =
  | { asama: "bos" }
  | { asama: "bekliyor" }
  | { asama: "engel"; oracle: CaseOracle; icerik: TestCaseIcerik; anlam: boolean | undefined; tur: OracleIstisnaTuru; damga?: string }
  | { asama: "zaman_asimi"; icerik: TestCaseIcerik; anlam: boolean | undefined }
  | { asama: "hata"; mesaj: string };

export interface DuzeltmeOnKontrolu {
  durum: OnKontrolDurumu;
  bekliyor: boolean;
  /** Düzeltme formunun gönderimi: kapsamdaysa önce kontrol, sonra karar. */
  gonder: (icerik: TestCaseIcerik, beklenenAnlamDegisti?: boolean) => void;
  istisnaylaGonder: (gerekce: string) => void;
  yenidenDene: () => void;
  sifirla: () => void;
  /**
   * Düzeltme formu engelden sonra değişti: engel ve zaman aşımı durumu düşer (eski içerik istisnayla
   * gönderilmez; analist yeniden gönderince yeni içerik kontrol edilir).
   */
  icerikDegisti: () => void;
}

/**
 * "Düzelterek kabul et" ön kontrolü (§7): case bir tabloyla kapsanıyorsa önerilen içerik için kontrol
 * istenir (`POST /cases/{id}/oracle-check`), o içerik hash'inin sonucu beklenir (`oracle.checked` olayı
 * + yoklama, zaman aşımlı), sonra karar gönderilir. Yüksek riskli uyuşmazlıkta ya da kontrol
 * edilemediğinde karar gönderilmez; gerekçe formu sunulur.
 */
export function useDuzeltmeOnKontrolu(
  tc: TestCase,
  karar: (icerik: TestCaseIcerik, beklenenAnlamDegisti: boolean | undefined, istisnaGerekce?: string, istisnaTuru?: OracleIstisnaTuru, damga?: string) => void,
): DuzeltmeOnKontrolu {
  const { tablolar } = useContext(Baglam);
  const [durum, setDurum] = useState<OnKontrolDurumu>({ asama: "bos" });
  const kosu = useRef(0);
  const uyandir = useRef<(() => void) | null>(null);
  const kararRef = useRef(karar);
  kararRef.current = karar;
  useEffect(
    () => () => {
      kosu.current++;
    },
    [],
  );
  // Kontrol bitti olayı beklemeyi hemen uyandırır (yoklama aralığını beklemez).
  useOlay((o) => {
    if (o.data.case_id === tc.id || o.id === tc.id) uyandir.current?.();
  }, ["oracle.checked"]);

  const gonder = useCallback(
    (icerik: TestCaseIcerik, anlam?: boolean) => {
      // Kapsam: önerilen içeriğin kabul kriterleri (analist atfı değiştirmiş olabilir). Tablo listesi
      // bilinmiyorsa case'in bugünkü kontrol sonucuna bakılır.
      const kapsamda = tablolar ? kapsayanTablolar(icerik, tablolar).length > 0 : !!tc.oracle && tc.oracle.sonuc !== "kapsam_disi";
      if (!kapsamda) {
        setDurum({ asama: "bos" });
        kararRef.current(icerik, anlam);
        return;
      }
      const benim = ++kosu.current;
      setDurum({ asama: "bekliyor" });
      void (async () => {
        let hash: string | undefined;
        try {
          hash = (await api.caseOracleKontrol(tc.id, icerik)).icerik_hash ?? undefined;
        } catch (e) {
          if (benim !== kosu.current) return;
          // Çekirdek bu ucu henüz sunmuyorsa (501) ön kontrol atlanır; kapı sunucudadır.
          if (e instanceof ApiError && e.status === 501) {
            setDurum({ asama: "bos" });
            kararRef.current(icerik, anlam);
          } else setDurum({ asama: "hata", mesaj: e instanceof Error ? e.message : "Beklenen sonuç kontrolü başlatılamadı." });
          return;
        }
        const son = Date.now() + ON_KONTROL.zamanAsimiMs;
        let oracle: CaseOracle | null = null;
        while (benim === kosu.current && Date.now() < son) {
          try {
            oracle = await api.caseOracle(tc.id, hash);
          } catch {
            oracle = null;
          }
          if ((oracle && !oracle.kontrol_suruyor && oracle.sonuc) || benim !== kosu.current) break;
          oracle = null;
          await new Promise<void>((r) => {
            const z = setTimeout(r, ON_KONTROL.araMs);
            uyandir.current = () => {
              clearTimeout(z);
              r();
            };
          });
        }
        uyandir.current = null;
        if (benim !== kosu.current) return;
        if (!oracle) return setDurum({ asama: "zaman_asimi", icerik, anlam });
        // K10 + V11 + tur 2: yüksek riskte uyuşmazlık, kontrol edilemedi ya da gerekçe isteyen kısmen → gerekçe;
        // aynı tür + içerik + tablo kümesiyle geçerli saklı istisna varsa gerekçe istenmez (S1).
        const damga = damgaAlani(oracle).oracle_kayit_damgasi;
        if (yuksekRisk(tc, icerik)) {
          const tur: OracleIstisnaTuru | null =
            oracle.sonuc === "uyumsuz" ? "uyumsuz" : oracle.sonuc === "kontrol_edilemedi" || (oracle.sonuc === "kismen" && kismenGerekceIster(oracle)) ? "kontrolsuz" : null;
          const sakli = oracle.istisna?.gecerli === true && (oracle.istisna.tur ?? tur) === tur;
          if (tur && !sakli) return setDurum({ asama: "engel", oracle, icerik, anlam, tur, ...(damga ? { damga } : {}) });
        }
        setDurum({ asama: "bos" });
        kararRef.current(icerik, anlam, undefined, undefined, damga);
      })();
    },
    [tablolar, tc],
  );

  return {
    durum,
    bekliyor: durum.asama === "bekliyor",
    gonder,
    istisnaylaGonder: (gerekce) => {
      if (durum.asama === "engel") kararRef.current(durum.icerik, durum.anlam, gerekce, durum.tur, durum.damga);
    },
    yenidenDene: () => {
      if (durum.asama === "zaman_asimi") gonder(durum.icerik, durum.anlam);
    },
    sifirla: () => {
      kosu.current++;
      setDurum({ asama: "bos" });
    },
    icerikDegisti: () => {
      if (durum.asama === "engel" || durum.asama === "zaman_asimi") {
        kosu.current++;
        setDurum({ asama: "bos" });
      }
    },
  };
}

/** Düzeltme formunun altındaki ön kontrol durumu. */
export function DuzeltmeOnKontrolPaneli({ kontrol, calisiyor }: { kontrol: DuzeltmeOnKontrolu; calisiyor: boolean }) {
  const d = kontrol.durum;
  if (d.asama === "bos") return null;
  if (d.asama === "bekliyor") {
    return (
      <div className="yukleniyor on-kontrol" role="status" aria-live="polite" data-testid="on-kontrol">
        <span className="donen" aria-hidden="true" />
        Beklenen sonuç kontrol ediliyor…
      </div>
    );
  }
  if (d.asama === "hata") {
    return (
      <div data-testid="on-kontrol">
        <Uyari ton="hata" baslik="Beklenen sonuç kontrolü başlatılamadı">
          {d.mesaj}
        </Uyari>
      </div>
    );
  }
  if (d.asama === "zaman_asimi") {
    return (
      <div data-testid="on-kontrol">
        <Uyari baslik="Kontrol zamanında bitmedi">
          Önerilen içeriğin beklenen sonuç kontrolü {Math.round(ON_KONTROL.zamanAsimiMs / 1000)} saniyede tamamlanmadı. Düzeltmeniz kaybolmadı.{" "}
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={kontrol.yenidenDene}>
            Yeniden dene
          </button>
        </Uyari>
      </div>
    );
  }
  const kontrolsuz = d.tur === "kontrolsuz";
  return (
    <div className="on-kontrol" data-testid="on-kontrol">
      {kontrolsuz ? (
        <Uyari baslik="Önerilen içerik tabloyla kontrol edilemedi">
          {ENGEL_KONTROLSUZ} Değeri tablonun okuyabileceği biçimde yazıp yeniden gönderin ya da gerekçeyle onaylayın.
        </Uyari>
      ) : (
        <Uyari ton="hata" baslik="Önerilen içerik tabloyla uyuşmuyor ✗">
          {ENGEL_UYUMSUZ} Değeri tabloya getirip yeniden gönderin ya da gerekçeli istisna açın.
        </Uyari>
      )}
      {d.oracle.karsilastirmalar.length > 0 && (
        <KarsilastirmaTablosu satirlar={d.oracle.karsilastirmalar} karsilastirilamayan={d.oracle.karsilastirilamayan} baslik="Önerilen içeriğin tablo karşılaştırması" />
      )}
      <p className="soluk kucuk">Bu sonuç gönderdiğiniz içeriğe aittir. Formda değişiklik yaparsanız bu kutu kapanır; yeniden gönderince yeni içerik kontrol edilir.</p>
      <IstisnaFormu
        calisiyor={calisiyor}
        tur={d.tur}
        gonder={kontrol.istisnaylaGonder}
        vazgec={kontrol.sifirla}
        dugmeMetni={kontrolsuz ? "Kontrol edilemedi, yine de düzeltip onayla" : "İstisnayla düzeltip onayla"}
      />
    </div>
  );
}

// ------------------------------------------------------------------ Özet metriği

/** Case review "Özet" kartı: §4.7 + §13.2 beklenti doğruluğu. Payda 0 ya da alan yoksa "ölçülmedi". */
export function BeklentiDogruluguMetrigi({ m }: { m: CaseMetrikleri | null | undefined }) {
  const b = beklentiDogruluguUyarla(m?.beklenti_dogrulugu);
  const parcalar: string[] = [];
  if (b) {
    parcalar.push(...beklentiParcalari(b));
    if (b.kontrol_edilemedi) parcalar.push(`${b.kontrol_edilemedi} kontrol edilemedi`);
    if (b.istisna) parcalar.push(`${b.istisna} istisna`);
    if (b.kontrolsuz_onay) parcalar.push(`${b.kontrolsuz_onay} kontrolsüz onay`);
  }
  const n = b ? b.uyumlu + b.uyumsuz : undefined;
  const nMetni = b && b.n_case !== undefined ? beklentiNParcalari(b).join(" · ") : null;
  return (
    <Metrik
      etiket="Beklenti doğruluğu"
      deger={<span data-testid="beklenti-dogrulugu">{b && b.oran !== null ? yuzde(b.oran) : <Olculmedi />}</span>}
      alt={
        <>
          {b ? parcalar.join(" · ") : CEKIRDEK_BILDIRMIYOR}
          {nMetni && (
            <span className="kule-n oracle-n" data-testid="beklenti-n">
              {nMetni}
              {n !== undefined && n < GOSTERGE_ESIGI && (
                <>
                  {" "}
                  <Cip ton="uyari" title={`n < ${GOSTERGE_ESIGI}: oran istatistiksel sonuç değil, gösterge niteliğindedir.`}>
                    gösterge
                  </Cip>
                </>
              )}
            </span>
          )}
        </>
      }
      ton={b && b.oran !== null && b.uyumsuz > 0 ? "uyari" : undefined}
    />
  );
}

// ------------------------------------------------------------------ ilişkiden türetilen case

/** İlişkiden deterministik türetilen case (etiket `metamorfik`): AI çıktısı değil, mor kullanılmaz. */
export function TuretmeCipi({ tc }: { tc: TestCase }) {
  if (!tc.icerik.tags?.includes("metamorfik")) return null;
  return (
    <span data-testid="turetme-cip">
      <Cip ton="notr" title="Onaylı metamorfik ilişkiden, kaynak case'in değerleriyle deterministik türetildi (model çağrısı yok).">
        İlişkiden türetildi
      </Cip>
    </span>
  );
}

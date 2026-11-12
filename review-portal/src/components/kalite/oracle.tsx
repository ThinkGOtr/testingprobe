// 012 Ş7 — case review: beklenen sonuç kontrolü (oracle) çipi, karşılaştırma tablosu, onay kapısı,
// istisna formu, düzeltme ön kontrolü ve "Beklenti doğruluğu" metriği (specs/012 ANALIZ §4.3, §7).
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useOlay } from "../../api/events";
import { ApiError } from "../../api/http";
import type { CaseMetrikleri, CaseOracle, KararTablosu, OracleKarsilastirilamayan, OracleKarsilastirma, TestCase, TestCaseIcerik } from "../../api/types";
import { beklentiDogruluguUyarla } from "../../api/uyumKalite";
import { useKisiAdi } from "../../auth";
import { useGeciktirilmis, useVeri } from "../../hooks";
import { ORACLE_DURUMU, type OracleGorunumu } from "../../lib/etiketler";
import { tarih, yuzde } from "../../lib/format";
import { AlanHatasi, Cip, IslemDugmesi, Metrik, Olculmedi, Uyari } from "../ui";
import "./kalite.css";

export const ISTISNA_EN_AZ = 20;

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
  /** "Onayla"nın görünür pasiflik nedeni (yüksek risk: uyuşmazlık ya da süren kontrol). */
  engel: string | null;
  /** Onay açık ama uyarı gösterilir (orta/düşük risk uyuşmazlığı; kontrol edilemeyen yüksek risk). */
  uyari: string | null;
  /** Yüksek riskli uyuşmazlık: gerekçeli istisnayla onay önerilir. */
  istisnaGerekli: boolean;
}

export const ENGEL_UYUMSUZ = "Beklenen değer onaylı karar tablosuyla uyuşmuyor. Yüksek riskli case gerekçeli istisna olmadan onaylanamaz.";
export const ENGEL_SURUYOR = "Beklenen sonuç kontrolü sürüyor; bitince onaylanabilir.";
export const UYARI_UYUMSUZ = "Beklenen değer onaylı karar tablosuyla uyuşmuyor. Onay engellenmez; uyarı kayda geçer.";
export const UYARI_KONTROL_EDILEMEDI = "Beklenen değer tabloyla karşılaştırılamadı. Onaylamadan önce değerleri elle doğrulayın; onay uyarıyla kayda geçer.";

/** ANALIZ §4.3 kapı tablosu (ekran tarafı; sunucu aynı kuralı uygular). */
export function oracleKapisi(tc: Pick<TestCase, "oracle" | "icerik">, tablolar: KararTablosu[] | null): OracleKapisiDurumu {
  const gorunum = oracleGorunumu(tc, tablolar);
  const yuksek = tc.icerik.risk === "high";
  const d: OracleKapisiDurumu = { gorunum, engel: null, uyari: null, istisnaGerekli: false };
  if (gorunum === "uyumsuz") {
    if (!yuksek) d.uyari = UYARI_UYUMSUZ;
    else if (!tc.oracle?.istisna) {
      d.engel = ENGEL_UYUMSUZ;
      d.istisnaGerekli = true;
    }
  } else if (gorunum === "kontrol_edilemedi" && yuksek) d.uyari = UYARI_KONTROL_EDILEMEDI;
  else if (gorunum === "suruyor" && yuksek) d.engel = ENGEL_SURUYOR;
  return d;
}

export function useOracleKapisi(tc: TestCase): OracleKapisiDurumu {
  const { tablolar } = useContext(Baglam);
  return useMemo(() => oracleKapisi(tc, tablolar), [tc, tablolar]);
}

/** Sunucunun kapı hataları (422 `oracle_uyumsuz`, 409 `oracle_bekleniyor`). */
export function oracleHatasi(e: unknown): e is ApiError {
  return e instanceof ApiError && (e.kod === "oracle_uyumsuz" || e.kod === "oracle_bekleniyor");
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

export function OracleCipi({ tc }: { tc: TestCase }) {
  const { gorunum } = useOracleKapisi(tc);
  if (!gorunum) return null;
  const d = ORACLE_DURUMU[gorunum];
  return (
    <span data-testid="oracle-cip">
      <Cip ton={d.ton} title={d.aciklama}>
        {d.etiket}
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
  const nedenler = [...new Set(karsilastirilamayan.map((k) => k.neden))];
  return (
    <div className="tablo-sarici" tabIndex={0} role="region" aria-label={baslik}>
      <table className="tablo tablo-sik tablo-yigin">
        <caption className="gorunmez">{baslik}</caption>
        <thead>
          <tr>
            <th scope="col">Alan</th>
            <th scope="col">Alıntı</th>
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
              <td data-etiket="Alıntı">“{k.alinti}”</td>
              <td className="mono" data-etiket="Case değeri">
                {degerMetni(k.case_degeri)}
              </td>
              <td className="mono" data-etiket="Tablo değeri">
                {degerMetni(k.tablo_degeri)}
                {k.satir_id && <span className="soluk kucuk"> · satır {k.satir_id}</span>}
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
              <th scope="rowgroup" colSpan={5} className="kucuk">
                Karşılaştırılamadı: {neden}
              </th>
            </tr>
            {karsilastirilamayan
              .filter((k) => k.neden === neden)
              .map((k, i) => (
                <tr key={`${k.alan}-${k.column}-${i}`}>
                  <td data-etiket="Alan">
                    <span className="mono">{k.column}</span> <span className="kucuk">· {alanEtiketi(k.alan)}</span>
                  </td>
                  <td data-etiket="Alıntı">“{k.alinti}”</td>
                  <td className="mono" data-etiket="Case değeri">
                    {degerMetni(k.case_degeri)}
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

function IstisnaNotu({ oracle }: { oracle: CaseOracle }) {
  const kisiAdi = useKisiAdi();
  if (!oracle.istisna) return null;
  const i = oracle.istisna;
  return (
    <p className="kucuk" data-testid="oracle-istisna">
      <strong>Gerekçeli istisna:</strong> {i.gerekce}
      <span className="soluk">
        {i.veren && ` · ${kisiAdi(i.veren)}`}
        {i.zaman && `, ${tarih(i.zaman)}`}
      </span>
    </p>
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
      <p className="soluk kucuk oracle-ozet" data-testid="oracle-ozet">
        {ORACLE_DURUMU[gorunum].aciklama} {baglanti}
      </p>
    );
  }
  return (
    <details className="oracle-ayrinti" data-testid="oracle-ayrinti" open={gorunum === "uyumsuz" || undefined}>
      <summary className="kucuk">
        Tablo karşılaştırması{satirlar.length > 0 && ` (${satirlar.length} değer, ${satirlar.filter((k) => !k.uyumlu).length} farklı`}
        {satirlar.length > 0 && (disarida.length > 0 ? `, ${disarida.length} karşılaştırılamadı)` : ")")}
      </summary>
      {o?.ozet && <p className="kucuk">{o.ozet}</p>}
      {(satirlar.length > 0 || disarida.length > 0) && (
        <KarsilastirmaTablosu satirlar={satirlar} karsilastirilamayan={disarida} baslik={`Tablo karşılaştırması: ${tc.icerik.title}`} />
      )}
      {o && <IstisnaNotu oracle={o} />}
      <p className="kucuk">{baglanti}</p>
    </details>
  );
}

// ------------------------------------------------------------------ istisna formu

export function IstisnaFormu({
  gonder,
  vazgec,
  calisiyor,
  dugmeMetni = "İstisnayla onayla",
}: {
  gonder: (gerekce: string) => void;
  vazgec: () => void;
  calisiyor: boolean;
  dugmeMetni?: string;
}) {
  const [gerekce, setGerekce] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  const alan = useRef<HTMLTextAreaElement | null>(null);
  // Satır içi form açılınca odak gerekçe alanına geçer (klavye kullanıcısı formu aramaz).
  useEffect(() => alan.current?.focus(), []);
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (gerekce.trim().length < ISTISNA_EN_AZ) {
      setUyari(`Gerekçe en az ${ISTISNA_EN_AZ} karakter olmalı (şu an ${gerekce.trim().length}).`);
      alan.current?.focus();
      return;
    }
    setUyari(null);
    gonder(gerekce.trim());
  }
  return (
    <form className="ret-formu istisna-formu" onSubmit={onSubmit} noValidate data-testid="istisna-formu">
      <div className="alan">
        <label htmlFor={`${id}-gerekce`}>İstisna gerekçesi</label>
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
          En az {ISTISNA_EN_AZ} karakter. Gerekçe, adınız ve zaman denetim kaydına ve Kontrol Kulesi istisna sayacına düşer.
        </span>
      </div>
      {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
      <div className="eylemler">
        <IslemDugmesi roller={["analyst"]} type="submit" kucuk calisiyor={calisiyor}>
          {dugmeMetni}
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** Kartın altındaki kapı bölümü: uyarı (orta/düşük risk) ya da "İstisnayla onayla" (yüksek risk). */
export function OracleKapisi({ kapi, calisiyor, onayla }: { kapi: OracleKapisiDurumu; calisiyor: boolean; onayla: (gerekce: string) => void }) {
  const [acik, setAcik] = useState(false);
  const dugme = useRef<HTMLSpanElement | null>(null);
  if (kapi.uyari) {
    return (
      <div data-testid="oracle-uyari">
        <Uyari baslik={kapi.gorunum === "uyumsuz" ? "Tabloyla uyuşmuyor" : "Kontrol edilemedi"}>{kapi.uyari}</Uyari>
      </div>
    );
  }
  if (!kapi.istisnaGerekli) return null;
  return (
    <div className="oracle-kapi" data-testid="oracle-kapi">
      {acik ? (
        <IstisnaFormu
          calisiyor={calisiyor}
          gonder={onayla}
          vazgec={() => {
            setAcik(false);
            // Form kapanınca odak onu açan düğmeye döner.
            requestAnimationFrame(() => dugme.current?.querySelector("button")?.focus());
          }}
        />
      ) : null}
      <span ref={dugme} className="satir-ogeler" hidden={acik}>
        <IslemDugmesi roller={["analyst"]} kucuk tur="ikincil" onClick={() => setAcik(true)}>
          İstisnayla onayla
        </IslemDugmesi>
        <span className="soluk kucuk">Uyuşmazlık bilinçliyse gerekçe yazarak onaylayabilir ya da “Düzelt” ile değeri tabloya getirebilirsiniz.</span>
      </span>
    </div>
  );
}

// ------------------------------------------------------------------ düzeltme ön kontrolü

/** Bekleme ayarları (testler kısaltır). */
export const ON_KONTROL = { araMs: 1000, zamanAsimiMs: 20000 };

type OnKontrolDurumu =
  | { asama: "bos" }
  | { asama: "bekliyor" }
  | { asama: "engel"; oracle: CaseOracle; icerik: TestCaseIcerik; anlam: boolean | undefined }
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
}

/**
 * "Düzeltip onayla" ön kontrolü (§7): case bir tabloyla kapsanıyorsa önerilen içerik için kontrol
 * istenir (`POST /cases/{id}/oracle-check`), o içerik hash'inin sonucu beklenir (`oracle.checked` olayı
 * + yoklama, zaman aşımlı), sonra karar gönderilir. Yüksek riskli uyuşmazlıkta karar gönderilmez;
 * istisna formu sunulur.
 */
export function useDuzeltmeOnKontrolu(
  tc: TestCase,
  karar: (icerik: TestCaseIcerik, beklenenAnlamDegisti: boolean | undefined, istisnaGerekce?: string) => void,
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
        if (oracle.sonuc === "uyumsuz" && icerik.risk === "high" && !oracle.istisna) return setDurum({ asama: "engel", oracle, icerik, anlam });
        setDurum({ asama: "bos" });
        kararRef.current(icerik, anlam);
      })();
    },
    [tablolar, tc.id, tc.oracle],
  );

  return {
    durum,
    bekliyor: durum.asama === "bekliyor",
    gonder,
    istisnaylaGonder: (gerekce) => {
      if (durum.asama === "engel") kararRef.current(durum.icerik, durum.anlam, gerekce);
    },
    yenidenDene: () => {
      if (durum.asama === "zaman_asimi") gonder(durum.icerik, durum.anlam);
    },
    sifirla: () => {
      kosu.current++;
      setDurum({ asama: "bos" });
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
  return (
    <div className="on-kontrol" data-testid="on-kontrol">
      <Uyari ton="hata" baslik="Önerilen içerik tabloyla uyuşmuyor ✗">
        {ENGEL_UYUMSUZ} Değeri tabloya getirip yeniden gönderin ya da gerekçeli istisna açın.
      </Uyari>
      {d.oracle.karsilastirmalar.length > 0 && (
        <KarsilastirmaTablosu satirlar={d.oracle.karsilastirmalar} karsilastirilamayan={d.oracle.karsilastirilamayan} baslik="Önerilen içeriğin tablo karşılaştırması" />
      )}
      <IstisnaFormu calisiyor={calisiyor} gonder={kontrol.istisnaylaGonder} vazgec={kontrol.sifirla} dugmeMetni="İstisnayla düzeltip onayla" />
    </div>
  );
}

// ------------------------------------------------------------------ Özet metriği

/** Case review "Özet" kartı: §4.7 beklenti doğruluğu. Payda 0 ya da alan yoksa "ölçülmedi". */
export function BeklentiDogruluguMetrigi({ m }: { m: CaseMetrikleri | null | undefined }) {
  const b = beklentiDogruluguUyarla(m?.beklenti_dogrulugu);
  const alt = !b
    ? "çekirdek bu ölçümü bildirmiyor"
    : b.oran === null
      ? `tabloyla karşılaştırılan case yok${b.kontrol_edilemedi ? ` · ${b.kontrol_edilemedi} kontrol edilemedi` : ""}`
      : `${b.uyumlu} uyumlu · ${b.uyumsuz} uyuşmuyor${b.kontrol_edilemedi ? ` · ${b.kontrol_edilemedi} kontrol edilemedi` : ""}${b.istisna ? ` · ${b.istisna} istisna` : ""}`;
  return (
    <Metrik
      etiket="Beklenti doğruluğu"
      deger={<span data-testid="beklenti-dogrulugu">{b && b.oran !== null ? yuzde(b.oran) : <Olculmedi />}</span>}
      alt={alt}
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

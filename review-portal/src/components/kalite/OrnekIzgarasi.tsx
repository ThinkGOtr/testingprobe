// 012 review turu 1 (analist/PO 5, 17): sınır değerlerinden örnek ızgarası. PO, `<` mı `<=` mü sorusunu
// ifadeden değil örnekten görür: adet 6 / 7 / 12 / 13 / 14, tutar 749,99 / 750,00 / 750,01. Örnekler
// çekirdekte tabloyla değerlendirilir (`GET /decision-tables/{id}/ornekler`; kayıt yok).
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ApiError } from "../../api/http";
import type { KararTablosu, TabloOrnekleri } from "../../api/types";
import { mantiksalMi, mantiksalOku } from "../../lib/ifadeAciklama";
import { Cip, Uyari } from "../ui";
import { degerMetni } from "./oracle";

const UYARI_TURU: Record<string, string> = {
  ortusme: "Satırlar örtüşüyor",
  hic_eslesmez: "Hiç seçilmeyen satır",
  golgede: "Gölgede kalan satır",
  satir_yok: "Eşleşen satır yok",
  hata: "Değerlendirme hatası",
  ornek_sinirli: "Örnekler sınırlı",
  gecersiz: "Tablo geçersiz",
};

/** Mobil yığın etiketinde uzun kolon adı alt çizgiden sarabilsin (sözcük ortasından bölünmesin). */
const kirilabilir = (ad: string) => ad.replace(/_/g, "_\u200b");

/** Koşullardaki sabitler: girdi adı → eşik değerleri (`sepet_tutari < 750` → 750). */
export function esikler(t: KararTablosu["icerik"]): Record<string, number[]> {
  const e: Record<string, number[]> = {};
  for (const s of t.satirlar)
    for (const m of s.kosul.matchAll(/\b([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<|>|==|!=)\s*(-?\d+(?:\.\d+)?)/g)) (e[m[1]] ??= []).push(Number(m[3]));
  return e;
}

/** Örnek girdisi sayı: çekirdek ondalık sayıları metin verir ("750.00"), mock sayı verir; ikisi de sayıya çevrilir. */
export function sayiDegeri(d: unknown): number | null {
  if (typeof d === "number") return Number.isFinite(d) ? d : null;
  if (typeof d === "string" && /^-?\d+(?:\.\d+)?$/.test(d.trim())) return Number(d.trim());
  return null;
}

/** Sayının story metnindeki yazımları: 750 → "750,00" ve "750"; 7 → "7". */
const yazimlar = (n: number) => [n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }), String(n).replace(".", ",")];

/**
 * u2 N19: eşik satırında "story ne diyor" — tablonun kabul kriterlerinde eşik sayısının geçtiği cümle (yoksa null).
 * Kriter metni gereksinimden okunur; anlam uydurulmaz, cümle olduğu gibi alıntılanır.
 */
export function storyCumlesi(deger: number, refs: string[], kriterler: { ref: string; metin: string }[] | null): string | null {
  for (const ref of refs) {
    const k = kriterler?.find((x) => x.ref.replace(/\s/g, "").toUpperCase() === ref.replace(/\s/g, "").toUpperCase());
    if (!k) continue;
    const cumle = k.metin
      .split(/(?<=\.)\s+/)
      .find((c) => yazimlar(deger).some((y) => new RegExp(`(^|[^0-9,.])${y.replace(/[.,]/g, (x) => `\\${x}`)}(?![0-9]|,[0-9])`).test(c)));
    if (cumle) return `${k.ref}: ${cumle.trim()}`;
  }
  return null;
}

export function OrnekIzgarasi({ tablo, kriterler = null }: { tablo: KararTablosu; kriterler?: { ref: string; metin: string }[] | null }) {
  const [acik, setAcik] = useState(tablo.durum === "pending_po");
  const [veri, setVeri] = useState<TabloOrnekleri | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [yok, setYok] = useState(false);
  useEffect(() => {
    if (!acik) return;
    let iptal = false;
    setHata(null);
    api.kararTablosuOrnekleri(tablo.id).then(
      (v) => !iptal && setVeri(v),
      (e: unknown) => {
        if (iptal) return;
        // Çekirdek ucu sunmuyorsa (404/501) bölüm sessizce "sunulmuyor" der.
        if (e instanceof ApiError && (e.status === 404 || e.status === 501)) setYok(true);
        else setHata(e instanceof Error ? e.message : "Örnekler yüklenemedi.");
      },
    );
    return () => {
      iptal = true;
    };
  }, [acik, tablo.id, tablo.icerik_hash]);
  const t = tablo.icerik;
  const esik = esikler(t);
  const esikSatiri = (girdiler: Record<string, unknown>) =>
    Object.entries(esik).flatMap(([ad, degerler]) => {
      const n = sayiDegeri(girdiler[ad]);
      return n !== null && degerler.includes(n) ? [n] : [];
    })[0] ?? null;
  const hucre = (ad: string, d: string | number | boolean | null | undefined) => (mantiksalMi(d) ? mantiksalOku(ad, d) : degerMetni(d));
  return (
    <details className="kt-ornek" data-testid="kt-ornek" open={acik || undefined} onToggle={(e) => setAcik((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>Sınır örnekleri</summary>
      <p className="soluk kucuk">
        Koşullardaki sınır değerleri ve çevresi tabloyla hesaplandı. Her satırı iş kuralına göre okuyun: beklediğiniz sonuç bu değilse tablo düzeltilmelidir.
        “Eşik” işaretli satırları story cümlesiyle karşılaştırın (ör. “altında” sınırı dahil etmez).
      </p>
      {yok ? (
        <p className="soluk kucuk">Bu sürüm örnek ızgarasını sunmuyor; “Örnekle dene” ile tek tek deneyebilirsiniz.</p>
      ) : hata ? (
        <Uyari ton="hata" baslik="Örnekler yüklenemedi">
          {hata}
        </Uyari>
      ) : !veri ? (
        acik && <p className="soluk kucuk">Yükleniyor…</p>
      ) : (
        <>
          {veri.ornekler.length > 0 && (
            <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`${t.ad}: sınır örnekleri`}>
              <table className="tablo tablo-sik tablo-yigin kt-ornek-tablo">
                <thead>
                  <tr>
                    {t.girdiler.map((g) => (
                      <th key={g.ad} scope="col" className="mono">
                        {g.ad}
                      </th>
                    ))}
                    <th scope="col">Satır</th>
                    {t.ciktilar.map((c) => (
                      <th key={c.ad} scope="col" className="mono">
                        {c.ad}
                      </th>
                    ))}
                    <th scope="col">Story ne diyor</th>
                  </tr>
                </thead>
                <tbody>
                  {veri.ornekler.map((o, i) => {
                    const e = esikSatiri(o.girdiler);
                    const story = e !== null ? storyCumlesi(e, t.ac_refs, kriterler) : null;
                    return (
                    <tr key={i} className={[o.hata || !o.satir_id ? "oracle-farkli" : "", e !== null ? "kt-esik" : ""].filter(Boolean).join(" ") || undefined} data-esik={e !== null || undefined}>
                      {t.girdiler.map((g) => (
                        <td key={g.ad} className="mono" data-etiket={kirilabilir(g.ad)}>
                          {hucre(g.ad, o.girdiler[g.ad])}
                          {e !== null && o.girdiler[g.ad] === e && (
                            <>
                              {" "}
                              <Cip ton="uyari" title="Koşuldaki sınır değeri: < mı ≤ mü sorusunu bu satır yanıtlar.">
                                eşik
                              </Cip>
                            </>
                          )}
                        </td>
                      ))}
                      <td className="mono" data-etiket="Satır">
                        {o.hata ? "hata" : (o.satir_id ?? "yok")}
                      </td>
                      {t.ciktilar.map((c) => (
                        <td key={c.ad} className="mono" data-etiket={kirilabilir(c.ad)}>
                          {hucre(c.ad, o.ciktilar[c.ad])}
                        </td>
                      ))}
                      <td className="kt-story" data-etiket="Story ne diyor">
                        {story ?? <span className="soluk">—</span>}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {veri.uyarilar.length > 0 && (
            <ul className="duz-liste kt-ornek-uyari" data-testid="kt-ornek-uyari">
              {veri.uyarilar.map((u, i) => (
                <li key={i} className={`kucuk${u.onem === "bilgi" ? " soluk kt-ornek-bilgi" : ""}`} data-onem={u.onem}>
                  {/* Q1: `onem: bilgi` örtüşme yalnız öncelik notudur (ör. "R1 önceliklidir"), uyarı değil. */}
                  <strong>{u.onem === "bilgi" ? "Bilgi" : (UYARI_TURU[u.tur] ?? u.tur)}:</strong> {u.mesaj}
                  {u.satirlar?.length ? <span className="soluk"> (satır {u.satirlar.join(", ")})</span> : null}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </details>
  );
}

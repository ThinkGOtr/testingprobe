// 012 Ş7 — "Örnekle dene": kayıtlı tablo içeriğini verilen girdilerle değerlendirir
// (`POST /decision-tables/{id}/evaluate`; önizleme, kayıt yok). Sonuç: eşleşen satır + çıktılar,
// "eşleşen satır yok", eksik girdiler ya da değerlendirme hatası.
import { useId, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { KararTablosu, KararTablosuIcerik, TabloDegerlendirmesi } from "../../api/types";
import { useIslem } from "../../hooks";
import { KOLON_TURU } from "../../lib/etiketler";
import { AlanHatasi, IslemDugmesi, Uyari } from "../ui";
import { degerMetni } from "./oracle";

/** `icerik`: düzenleyicideki kaydedilmemiş içerik; verilirse o değerlendirilir (`evaluate {girdiler, icerik}`). */
export function OrnekleDene({ tablo, icerik }: { tablo: KararTablosu; icerik?: KararTablosuIcerik }) {
  const [degerler, setDegerler] = useState<Record<string, string>>({});
  const [sonuc, setSonuc] = useState<TabloDegerlendirmesi | null>(null);
  const islem = useIslem();
  const id = useId();
  const sonucRef = useRef<HTMLDivElement | null>(null);
  const girdiler = (icerik ?? tablo.icerik).girdiler.filter((g) => g.ad.trim());

  async function dene(e: FormEvent) {
    e.preventDefault();
    // Boş bırakılan girdi gönderilmez: sunucu `eksik_girdiler` ile bildirir. Sayı metni olduğu gibi
    // gider (core "25,00 TL" / "25.00" kabul eder); mantıksal değer boolean.
    const govde: Record<string, string | boolean> = {};
    for (const g of girdiler) {
      const v = (degerler[g.ad] ?? "").trim();
      if (!v) continue;
      govde[g.ad] = g.tur === "mantiksal" ? v === "dogru" : v;
    }
    setSonuc(null);
    const s = await islem.calistir(() => api.kararTablosuDene(tablo.id, govde, icerik));
    if (s) {
      setSonuc(s);
      requestAnimationFrame(() => sonucRef.current?.focus());
    }
  }

  return (
    <details className="kt-dene" data-testid="kt-dene">
      <summary>Örnekle dene</summary>
      {icerik && <p className="soluk kucuk">Düzenleyicideki kaydedilmemiş içerikle denenir.</p>}
      {girdiler.length === 0 ? (
        <p className="soluk kucuk">Tabloda girdi yok; denemek için önce girdi ve satır ekleyin.</p>
      ) : (
        <form onSubmit={dene} noValidate aria-label={`${tablo.icerik.ad} örnekle dene`}>
          <div className="kt-dene-form">
            {girdiler.map((g) => {
              const alanId = `${id}-${g.ad}`;
              const etiket = (
                <>
                  <span className="mono">{g.ad}</span>
                  {g.birim ? ` (${g.birim})` : ""} <span className="soluk kucuk">· {KOLON_TURU[g.tur]}</span>
                </>
              );
              return (
                <div key={g.ad} className="alan">
                  <label htmlFor={alanId}>{etiket}</label>
                  {g.tur === "mantiksal" ? (
                    <select id={alanId} value={degerler[g.ad] ?? ""} onChange={(e) => setDegerler({ ...degerler, [g.ad]: e.target.value })}>
                      <option value="">— (boş)</option>
                      <option value="dogru">doğru</option>
                      <option value="yanlis">yanlış</option>
                    </select>
                  ) : (
                    <input
                      id={alanId}
                      className={g.tur === "sayi" ? "mono" : undefined}
                      inputMode={g.tur === "sayi" ? "decimal" : undefined}
                      autoComplete="off"
                      value={degerler[g.ad] ?? ""}
                      onChange={(e) => setDegerler({ ...degerler, [g.ad]: e.target.value })}
                    />
                  )}
                </div>
              );
            })}
          </div>
          <div className="eylemler">
            <IslemDugmesi type="submit" tur="ikincil" kucuk calisiyor={islem.calisiyor}>
              Dene
            </IslemDugmesi>
          </div>
        </form>
      )}
      {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
      {sonuc && (
        <div ref={sonucRef} tabIndex={-1} className="kt-dene-sonuc" data-testid="kt-dene-sonuc" aria-live="polite">
          <DegerlendirmeSonucu ciktilar={(icerik ?? tablo.icerik).ciktilar} sonuc={sonuc} />
        </div>
      )}
    </details>
  );
}

function DegerlendirmeSonucu({ ciktilar, sonuc }: { ciktilar: KararTablosuIcerik["ciktilar"]; sonuc: TabloDegerlendirmesi }) {
  if (sonuc.hata) {
    return (
      <Uyari ton="hata" baslik="Değerlendirilemedi">
        {sonuc.hata}
      </Uyari>
    );
  }
  if (sonuc.eksik_girdiler.length > 0) {
    return (
      <Uyari baslik="Eksik girdi">
        Değerlendirme için şu girdiler gerekli: <span className="mono">{sonuc.eksik_girdiler.join(", ")}</span>
      </Uyari>
    );
  }
  if (!sonuc.satir_id) {
    return (
      <Uyari ton="bilgi" baslik="Eşleşen satır yok">
        Bu girdilerle hiçbir satırın koşulu sağlanmıyor. Bu bir uyuşmazlık değildir; kontrol bu durumda karar vermez.
      </Uyari>
    );
  }
  return (
    <>
      <p className="kucuk">
        <strong>Eşleşen satır:</strong> <span className="mono">{sonuc.satir_id}</span>
      </p>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Deneme çıktıları">
        <table className="tablo tablo-sik">
          <thead>
            <tr>
              <th scope="col">Çıktı</th>
              <th scope="col">Değer</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(sonuc.ciktilar).map(([ad, d]) => {
              const c = ciktilar.find((x) => x.ad === ad);
              return (
                <tr key={ad}>
                  <td className="mono">{ad}</td>
                  <td className="mono">
                    {degerMetni(d)}
                    {c?.birim ? ` ${c.birim}` : ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

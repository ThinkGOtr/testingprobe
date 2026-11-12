// 012 Ş7 — karar tablosu kartı: görünüm (girdiler, çıktılar, satırlar), düzenleyici (analist,
// yalnız taslak), "Örnekle dene" ve durum geçişleri (ANALIZ §4.1, §7).
import { useState } from "react";
import { api } from "../../api/client";
import type { KararTablosu, KararTablosuIcerik } from "../../api/types";
import { KOLON_TURU } from "../../lib/etiketler";
import { IslemDugmesi, Kart } from "../ui";
import { DurumEylemleri, KayitCipleri, KayitNotlari } from "./ortak";
import { OrnekleDene } from "./OrnekleDene";
import { TabloDuzenleyici } from "./TabloDuzenleyici";

export const tabloCapasi = (id: string) => `tablo-${id}`;

/** Kart şeridi: mor yalnız insan kapısından geçmemiş AI taslağı; yeşil yalnız PO onayı; amber PO bekliyor. */
export function kayitSinifi(k: { durum: string; ai_generated: boolean; bayat: boolean }): string {
  const s = ["kt-kart"];
  if (k.ai_generated) s.push("kt-ai");
  if (k.durum === "approved" && !k.bayat) s.push("insan-kapisi", "kapi-gecti");
  else if (k.durum === "pending_po") s.push("insan-kapisi", "kapi-bekliyor");
  return s.join(" ");
}

export function KararTablosuKarti({
  tablo,
  kriterler,
  guncellendi,
  yenile,
  duzenleAcik = false,
}: {
  tablo: KararTablosu;
  kriterler: { ref: string; metin: string }[];
  guncellendi: (t: KararTablosu) => void;
  yenile: () => void;
  duzenleAcik?: boolean;
}) {
  const [duzenle, setDuzenle] = useState(duzenleAcik);
  const [taslakIcerik, setTaslakIcerik] = useState<KararTablosuIcerik | null>(null);
  const t = tablo.icerik;
  const taslak = tablo.durum === "draft";
  const baslik = (
    <>
      <span className="mono soluk">T{tablo.sira_no}</span> · {t.ad || "Adsız tablo"}
    </>
  );
  const duzenleId = `${tabloCapasi(tablo.id)}-duzenle`;
  return (
    <Kart id={tabloCapasi(tablo.id)} baslik={baslik} className={kayitSinifi(tablo)}>
      <div data-testid="kt-kart" data-tablo-id={tablo.id}>
        <KayitCipleri k={tablo} />
        <KayitNotlari k={tablo} ad="Tablo" />
        {t.aciklama && <p>{t.aciklama}</p>}

        {duzenle && taslak ? (
          <TabloDuzenleyici
            tablo={tablo}
            kriterler={kriterler}
            yenile={yenile}
            degisti={setTaslakIcerik}
            vazgec={() => {
              setDuzenle(false);
              requestAnimationFrame(() => document.getElementById(duzenleId)?.focus());
            }}
            kaydedildi={(y) => {
              setDuzenle(false);
              guncellendi(y);
              requestAnimationFrame(() => document.getElementById(duzenleId)?.focus());
            }}
          />
        ) : (
          <TabloGorunumu tablo={tablo} />
        )}

        {tablo.durum !== "superseded" && <OrnekleDene tablo={tablo} icerik={duzenle && taslak ? (taslakIcerik ?? undefined) : undefined} />}

        {tablo.durum !== "superseded" && (
          <DurumEylemleri
            kayit={tablo}
            gecis={(g, govde) => api.kararTablosuGecis(tablo.id, g, govde)}
            guncellendi={guncellendi}
            yenile={yenile}
            engel={duzenle && taslak ? "Önce düzenlemeyi kaydedin ya da vazgeçin." : undefined}
            ek={
              taslak && !duzenle ? (
                <IslemDugmesi id={duzenleId} roller={["analyst"]} kucuk tur="ikincil" onClick={() => setDuzenle(true)}>
                  Düzenle
                </IslemDugmesi>
              ) : null
            }
          />
        )}
      </div>
    </Kart>
  );
}

export function TabloGorunumu({ tablo }: { tablo: KararTablosu }) {
  const t = tablo.icerik;
  const ad = t.ad || "Karar tablosu";
  return (
    <>
      <h3 className="kt-bolum">Girdiler</h3>
      {t.girdiler.length === 0 ? (
        <p className="soluk kucuk">Girdi tanımlanmadı.</p>
      ) : (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`${ad}: girdiler`}>
          <table className="tablo tablo-sik tablo-yigin">
            <thead>
              <tr>
                <th scope="col">Ad</th>
                <th scope="col">Tür</th>
                <th scope="col">Birim</th>
                <th scope="col">Açıklama</th>
              </tr>
            </thead>
            <tbody>
              {t.girdiler.map((g) => (
                <tr key={g.ad}>
                  <td className="mono" data-etiket="Ad">
                    {g.ad}
                  </td>
                  <td data-etiket="Tür">{KOLON_TURU[g.tur]}</td>
                  <td data-etiket="Birim">{g.birim ?? "—"}</td>
                  <td data-etiket="Açıklama">{g.aciklama ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="kt-bolum">Çıktılar</h3>
      {t.ciktilar.length === 0 ? (
        <p className="soluk kucuk">Çıktı tanımlanmadı.</p>
      ) : (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`${ad}: çıktılar`}>
          <table className="tablo tablo-sik tablo-yigin">
            <thead>
              <tr>
                <th scope="col">Ad</th>
                <th scope="col">Tür</th>
                <th scope="col">Birim</th>
                <th scope="col">Tolerans</th>
              </tr>
            </thead>
            <tbody>
              {t.ciktilar.map((c) => (
                <tr key={c.ad}>
                  <td className="mono" data-etiket="Ad">
                    {c.ad}
                  </td>
                  <td data-etiket="Tür">{KOLON_TURU[c.tur]}</td>
                  <td data-etiket="Birim">{c.birim ?? "—"}</td>
                  <td className="mono" data-etiket="Tolerans">
                    {c.tur === "sayi" ? (c.tolerans ?? "0") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="kt-bolum">Satırlar</h3>
      {t.satirlar.length === 0 ? (
        <p className="soluk kucuk">Satır tanımlanmadı.</p>
      ) : (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`${ad}: satırlar`}>
          <table className="tablo tablo-sik tablo-yigin">
            <caption className="gorunmez">Koşulu ilk sağlayan satır geçerlidir.</caption>
            <thead>
              <tr>
                <th scope="col">Satır</th>
                <th scope="col">Koşul</th>
                {t.ciktilar.map((c) => (
                  <th key={c.ad} scope="col" className="mono">
                    {c.ad}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.satirlar.map((s) => (
                <tr key={s.id}>
                  <td className="mono" data-etiket="Satır">
                    {s.id}
                  </td>
                  <td className="kt-ifade" data-etiket="Koşul">
                    {s.kosul}
                  </td>
                  {t.ciktilar.map((c) => (
                    <td key={c.ad} className="kt-ifade" data-etiket={c.ad}>
                      {s.cikti[c.ad] ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

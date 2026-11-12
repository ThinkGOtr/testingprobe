// 012 Ş7 — karar tablosu kartı: görünüm (girdiler, çıktılar, satırlar), düzenleyici (analist,
// yalnız taslak), "Örnekle dene" ve durum geçişleri (ANALIZ §4.1, §7).
import { useState } from "react";
import { api } from "../../api/client";
import type { KararTablosu, KararTablosuIcerik } from "../../api/types";
import { KOLON_TURU } from "../../lib/etiketler";
import { ifadeGosterimi, satiriOku } from "../../lib/ifadeAciklama";
import { Cip, IslemDugmesi, Kart } from "../ui";
import { OrnekIzgarasi } from "./OrnekIzgarasi";
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
  /** `null`: gereksinim okunamadı (kabul kriterleri bilinmiyor; düzenleme kapalı). */
  kriterler: { ref: string; metin: string }[] | null;
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

        {tablo.durum !== "superseded" && !(duzenle && taslak) && <OrnekIzgarasi tablo={tablo} kriterler={kriterler} />}

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
                <IslemDugmesi
                id={duzenleId}
                roller={["analyst"]}
                kucuk
                tur="ikincil"
                disabled={kriterler === null}
                title={kriterler === null ? "Gereksinim okunamadı; kabul kriterleri bilinmeden düzenlenemez." : undefined}
                onClick={() => setDuzenle(true)}
              >
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

/**
 * AI taslağından (çekirdek `ai_icerik` verirse) farklılaşan satırlar: koşulu ya da bir çıktısı değişen,
 * ya da taslakta olmayan satır kimlikleri. `ai_icerik` yoksa boş (işaret uydurulmaz).
 */
export function analistDegistirdi(tablo: Pick<KararTablosu, "icerik" | "ai_icerik" | "ai_generated">): Set<string> {
  const ai = tablo.ai_icerik;
  if (!ai || !tablo.ai_generated) return new Set();
  return new Set(
    tablo.icerik.satirlar
      .filter((s) => {
        const o = ai.satirlar.find((x) => x.id === s.id);
        if (!o) return true;
        const anahtarlar = new Set([...Object.keys(s.cikti), ...Object.keys(o.cikti)]);
        return o.kosul.trim() !== s.kosul.trim() || [...anahtarlar].some((k) => (o.cikti[k] ?? "").trim() !== (s.cikti[k] ?? "").trim());
      })
      .map((s) => s.id),
  );
}

export function TabloGorunumu({ tablo }: { tablo: KararTablosu }) {
  const t = tablo.icerik;
  const ad = t.ad || "Karar tablosu";
  const degisenler = analistDegistirdi(tablo);
  const aiSatir = (id: string) => (degisenler.has(id) ? tablo.ai_icerik?.satirlar.find((x) => x.id === id) : undefined);
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
                    {degisenler.has(s.id) && (
                      <>
                        {" "}
                        <span data-testid="kt-analist-degistirdi">
                          <Cip ton="notr" title="Bu satır AI taslağındaki hâlinden farklı: analist düzenledi.">
                            analist değiştirdi
                          </Cip>
                        </span>
                      </>
                    )}
                  </td>
                  <td className="kt-ifade" data-etiket="Koşul">
                    {ifadeGosterimi(s.kosul)}
                    {aiSatir(s.id)?.kosul !== undefined && aiSatir(s.id)!.kosul.trim() !== s.kosul.trim() && (
                      <span className="kt-ai-ozgun" data-testid="kt-ai-ozgun">
                        AI taslağında: <span className="mono">{ifadeGosterimi(aiSatir(s.id)!.kosul)}</span>
                      </span>
                    )}
                  </td>
                  {t.ciktilar.map((c) => (
                    <td key={c.ad} className="kt-ifade" data-etiket={c.ad}>
                      {s.cikti[c.ad] !== undefined ? ifadeGosterimi(s.cikti[c.ad]) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {t.satirlar.length > 0 && (
        <div className="kt-anlam" data-testid="kt-anlam">
          <h3 className="kt-bolum">Satırların anlamı</h3>
          <p className="soluk kucuk">Koşulu ilk sağlayan satır geçerlidir. PO, ifadeyi değil bu iş kuralını onaylar.</p>
          <ol className="duz-liste kt-anlam-liste">
            {t.satirlar.map((s) => (
              <li key={s.id}>
                <span className="mono soluk">{s.id}</span>{" "}
                {satiriOku(s.kosul, s.cikti, t.ciktilar)}
              </li>
            ))}
          </ol>
        </div>
      )}
    </>
  );
}

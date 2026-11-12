// 012 review turu 1 (analist/PO 5, 17): sınır değerlerinden örnek ızgarası. PO, `<` mı `<=` mü sorusunu
// ifadeden değil örnekten görür: adet 6 / 7 / 12 / 13 / 14, tutar 749,99 / 750,00 / 750,01. Örnekler
// çekirdekte tabloyla değerlendirilir (`GET /decision-tables/{id}/ornekler`; kayıt yok).
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ApiError } from "../../api/http";
import type { KararTablosu, TabloOrnekleri } from "../../api/types";
import { Uyari } from "../ui";
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

export function OrnekIzgarasi({ tablo }: { tablo: KararTablosu }) {
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
  return (
    <details className="kt-ornek" data-testid="kt-ornek" open={acik || undefined} onToggle={(e) => setAcik((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>Sınır örnekleri</summary>
      <p className="soluk kucuk">
        Koşullardaki sınır değerleri ve çevresi tabloyla hesaplandı. Her satırı iş kuralına göre okuyun: beklediğiniz sonuç bu değilse tablo düzeltilmelidir.
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
                  </tr>
                </thead>
                <tbody>
                  {veri.ornekler.map((o, i) => (
                    <tr key={i} className={o.hata || !o.satir_id ? "oracle-farkli" : undefined}>
                      {t.girdiler.map((g) => (
                        <td key={g.ad} className="mono" data-etiket={g.ad}>
                          {degerMetni(o.girdiler[g.ad])}
                        </td>
                      ))}
                      <td className="mono" data-etiket="Satır">
                        {o.hata ? "hata" : (o.satir_id ?? "yok")}
                      </td>
                      {t.ciktilar.map((c) => (
                        <td key={c.ad} className="mono" data-etiket={c.ad}>
                          {degerMetni(o.ciktilar[c.ad])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {veri.uyarilar.length > 0 && (
            <ul className="duz-liste kt-ornek-uyari" data-testid="kt-ornek-uyari">
              {veri.uyarilar.map((u, i) => (
                <li key={i} className="kucuk">
                  <strong>{UYARI_TURU[u.tur] ?? u.tur}:</strong> {u.mesaj}
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

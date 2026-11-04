import { useMemo, useState } from "react";
import { api } from "../api/client";
import { BosDurum, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useKisiAdi } from "../auth";
import { useVeri } from "../hooks";
import { kisaHash, tarih } from "../lib/format";

export function Denetim() {
  const v = useVeri(() => api.denetim(true), []);
  const [ara, setAra] = useState("");
  const kisiAdi = useKisiAdi();
  const olaylar = useMemo(() => {
    const q = ara.trim().toLocaleLowerCase("tr-TR");
    const l = v.veri?.olaylar ?? [];
    return q
      ? l.filter((o) => `${o.aktor} ${kisiAdi(o.aktor)} ${o.eylem} ${o.nesne} ${o.ozet}`.toLocaleLowerCase("tr-TR").includes(q))
      : l;
  }, [v.veri, ara, kisiAdi]);
  const dg = v.veri?.dogrulama;

  return (
    <>
      <SayfaBasligi
        baslik="Denetim"
        aciklama="Her AI çağrısı, araç çağrısı, onay ve ret append-only kayıttadır; her olay bir öncekinin hash'ine zincirlenir."
        eylemler={
          <IslemDugmesi tur="ikincil" calisiyor={v.yukleniyor} onClick={() => void v.yenile()}>
            Zinciri yeniden doğrula
          </IslemDugmesi>
        }
      />
      {v.yukleniyor && !v.veri ? (
        <Yukleniyor />
      ) : v.hata && !v.veri ? (
        <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />
      ) : (
        <>
          {dg ? (
            dg.gecerli ? (
              <Uyari ton="basari" baslik="✓ Zincir doğrulandı" isaretli>
                {dg.kontrol_edilen} olay kontrol edildi · son hash <span className="mono">{kisaHash(dg.son_hash, 16)}</span> · {tarih(dg.zaman)}
              </Uyari>
            ) : (
              <Uyari ton="hata" baslik="✗ Zincir kırık" isaretli>
                {dg.kontrol_edilen} olay kontrol edildi · ilk kırık kayıt <span className="mono">{dg.ilk_kirik_id}</span>. Denetim kaydı değiştirilmiş olabilir.
              </Uyari>
            )
          ) : (
            <Uyari ton="bilgi">Zincir doğrulaması yapılmadı.</Uyari>
          )}
          <Kart
            baslik={`Olaylar (${olaylar.length})`}
            eylemler={
              <div className="alan alan-satir">
                <label htmlFor="denetim-ara" className="gorunmez">
                  Olay ara
                </label>
                <input id="denetim-ara" type="search" placeholder="Aktör, eylem, nesne ara" value={ara} onChange={(e) => setAra(e.target.value)} />
              </div>
            }
          >
            {olaylar.length === 0 ? (
              <BosDurum baslik="Olay yok." />
            ) : (
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Denetim olayları tablosu">
                <table className="tablo tablo-sik">
                  <thead>
                    <tr>
                      <th scope="col" className="sayi">
                        #
                      </th>
                      <th scope="col">Zaman</th>
                      <th scope="col">Aktör</th>
                      <th scope="col">Eylem</th>
                      <th scope="col">Nesne</th>
                      <th scope="col">Özet</th>
                      <th scope="col">Hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {olaylar.map((o) => (
                      <tr key={o.id} className={dg && !dg.gecerli && dg.ilk_kirik_id === o.id ? "satir-hata" : undefined}>
                        <td className="sayi mono">{o.sira}</td>
                        <td>{tarih(o.zaman)}</td>
                        <td title={kisiAdi(o.aktor) !== o.aktor ? o.aktor : undefined}>{kisiAdi(o.aktor)}</td>
                        <td className="mono">{o.eylem}</td>
                        <td className="mono">{o.nesne}</td>
                        <td>{o.ozet}</td>
                        <td className="mono kucuk" title={`prev ${o.prev_hash}\nhash ${o.hash}`}>
                          {kisaHash(o.hash)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Kart>
        </>
      )}
    </>
  );
}

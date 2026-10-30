import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { YayinOnizlemeKalemi, YayinSonucu } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useIslem, useVeri } from "../hooks";
import type { Ton } from "../lib/etiketler";

const ISLEM: Record<YayinOnizlemeKalemi["islem"], { etiket: string; ton: Ton }> = {
  create: { etiket: "Oluşturulacak", ton: "basari" },
  skip_existing: { etiket: "Zaten yayında", ton: "notr" },
  blocked_hash_mismatch: { etiket: "Engelli: onaydan sonra değişmiş", ton: "hata" },
  blocked_not_approved: { etiket: "Engelli: onaylı değil", ton: "uyari" },
};

const HEDEF = { jira: "Jira (Test issue)", xray: "Xray Cloud" } as const;

export function Yayin() {
  const { id = "" } = useParams();
  const onizleme = useVeri(() => api.yayinOnizleme(id), [id]);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [sonuc, setSonuc] = useState<YayinSonucu | null>(null);
  const islem = useIslem();
  const bildir = useBildirim();

  const kalemler = onizleme.veri?.kalemler ?? [];
  const olusturulabilir = kalemler.filter((k) => k.islem === "create");

  useEffect(() => {
    setSecili(new Set(olusturulabilir.map((k) => k.case_id)));
  }, [onizleme.veri]);

  const degistir = (cid: string) =>
    setSecili((s) => {
      const y = new Set(s);
      if (y.has(cid)) y.delete(cid);
      else y.add(cid);
      return y;
    });

  async function yayinla() {
    const s = await islem.calistir(() => api.yayinla([...secili]));
    if (s) {
      setSonuc(s);
      const n = s.sonuclar.filter((x) => x.durum === "created").length;
      bildir(`${n} test ${HEDEF[s.hedef]} hedefine yayınlandı.`);
      void onizleme.yenile(true);
    }
  }

  const o = onizleme.veri;

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}/caseler`}>← Case review</Link>}
        baslik="Yayın önizleme"
        aciklama="Dry-run: yalnızca onaylı ve onaydan sonra değişmemiş case'ler yayınlanır. Yayın idempotenttir (aynı içerik ikinci kez oluşturulmaz)."
      />
      {onizleme.yukleniyor && !o ? (
        <Yukleniyor />
      ) : onizleme.hata && !o ? (
        <HataKutusu hata={onizleme.hata} yenile={() => void onizleme.yenile()} />
      ) : o ? (
        <>
          <Kart
            baslik="Hedef"
            eylemler={
              <IslemDugmesi roller={["analyst"]} disabled={secili.size === 0} calisiyor={islem.calisiyor} onClick={yayinla}>
                Seçilenleri yayınla ({secili.size})
              </IslemDugmesi>
            }
          >
            <p>
              <strong>{HEDEF[o.hedef]}</strong> · proje <span className="mono">{o.proje}</span>
              <span className="soluk"> · hedef sunucu yapılandırmasından gelir (TP_TEST_MGMT)</span>
            </p>
            {o.uyarilar.map((u) => (
              <Uyari key={u}>{u}</Uyari>
            ))}
            {islem.hata && <HataKutusu hata={islem.hata} />}
          </Kart>

          {sonuc && (
            <Kart baslik="Yayın sonucu">
              <ul className="duz-liste">
                {sonuc.sonuclar.map((s) => (
                  <li key={s.case_id}>
                    <Cip ton={s.durum === "created" ? "basari" : s.durum === "exists" ? "notr" : "hata"}>
                      {s.durum === "created" ? "Oluşturuldu" : s.durum === "exists" ? "Zaten vardı" : "Başarısız"}
                    </Cip>{" "}
                    <span className="mono">{s.external_key ?? s.case_id}</span>
                    {s.hata && <span className="soluk"> · {s.hata}</span>}
                  </li>
                ))}
              </ul>
            </Kart>
          )}

          <Kart baslik="Oluşturulacak kayıtlar">
            {kalemler.length === 0 ? (
              <BosDurum baslik="Yayınlanacak case yok." />
            ) : (
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Oluşturulacak kayıtlar tablosu">
                <table className="tablo">
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="gorunmez">Seç</span>
                      </th>
                      <th scope="col">Özet</th>
                      <th scope="col">Tür</th>
                      <th scope="col">Bağlantı</th>
                      <th scope="col">Etiketler</th>
                      <th scope="col" className="sayi">
                        Adım
                      </th>
                      <th scope="col">İşlem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {kalemler.map((k) => {
                      const i = ISLEM[k.islem];
                      return (
                        <tr key={k.case_id}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`${k.title} yayınla`}
                              checked={secili.has(k.case_id)}
                              disabled={k.islem !== "create"}
                              onChange={() => degistir(k.case_id)}
                            />
                          </td>
                          <td>{k.summary}</td>
                          <td>{k.issue_type}</td>
                          <td className="kucuk">
                            {k.link.story_key ? (
                              <>
                                {k.link.type} <span className="mono">{k.link.story_key}</span>
                              </>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td className="kucuk mono">{k.labels.join(", ")}</td>
                          <td className="sayi">{k.adim_sayisi}</td>
                          <td>
                            <Cip ton={i.ton}>{i.etiket}</Cip>
                            {k.external_key && <span className="mono"> {k.external_key}</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Kart>
        </>
      ) : null}
    </>
  );
}

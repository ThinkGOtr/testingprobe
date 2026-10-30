import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { TestCase } from "../api/types";
import { CaseKarti } from "../components/CaseKarti";
import { BosDurum, HataKutusu, Kart, Metrik, SayfaBasligi, Yukleniyor } from "../components/ui";
import { HedefOlcer } from "../components/Grafikler";
import { useGeciktirilmis, useVeri } from "../hooks";
import { dolar, sure } from "../lib/format";

/** §12: kabul = onay + küçük düzeltmeyle onay (ölçü ≤ 0,15) / üretilen. */
export function caseOzeti(caseler: TestCase[]) {
  const onay = caseler.filter((c) => c.karar === "approve").length;
  const duzeltilmis = caseler.filter((c) => c.karar === "edit").length;
  const kucukDuzeltme = caseler.filter((c) => c.karar === "edit" && (c.duzeltme_olcusu ?? 1) <= 0.15).length;
  const ret = caseler.filter((c) => c.karar === "reject").length;
  const bekleyen = caseler.filter((c) => c.karar === null).length;
  return {
    uretilen: caseler.length,
    onay,
    duzeltilmis,
    ret,
    bekleyen,
    kabulOrani: caseler.length ? (onay + kucukDuzeltme) / caseler.length : 0,
    aiSure: caseler.reduce((a, c) => a + c.ai_sure_ms, 0),
    reviewSure: caseler.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0),
    maliyet: caseler.reduce((a, c) => a + c.maliyet_usd, 0),
  };
}

type Filtre = "hepsi" | "bekleyen" | "onayli" | "reddedilen";

export function CaseReview() {
  const { id = "" } = useParams();
  const gereksinim = useVeri(() => api.gereksinim(id), [id]);
  const caseler = useVeri(() => api.caseler(id), [id]);
  const [filtre, setFiltre] = useState<Filtre>("hepsi");
  const sessiz = useGeciktirilmis(() => void caseler.yenile(true));
  useOlay((o) => {
    if (o.type === "case.generated" && o.data.requirement_id !== id) return;
    sessiz();
  }, ["case.generated", "requirement.updated"]);

  const liste = caseler.veri ?? [];
  const ozet = useMemo(() => caseOzeti(liste), [liste]);
  const gorunen = liste.filter((c) =>
    filtre === "hepsi"
      ? true
      : filtre === "bekleyen"
        ? c.karar === null
        : filtre === "onayli"
          ? c.durum === "approved" || c.durum === "published"
          : c.durum === "rejected",
  );
  const g = gereksinim.veri;

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}`}>← {g?.jira_key ?? g?.baslik ?? "Gereksinim"}</Link>}
        baslik="Case review"
        aciklama={g ? `${g.jira_key ? `${g.jira_key} · ` : ""}${g.baslik}` : undefined}
        eylemler={
          <Link className="dugme dugme-birincil" to={`/gereksinimler/${encodeURIComponent(id)}/yayin`}>
            Yayın önizleme
          </Link>
        }
      />

      <Kart baslik="Özet">
        <div className="metrik-izgara">
          <Metrik etiket="Üretilen" deger={ozet.uretilen} />
          <Metrik etiket="Onaylı" deger={ozet.onay} />
          <Metrik etiket="Düzeltilerek onaylı" deger={ozet.duzeltilmis} />
          <Metrik etiket="Reddedilen" deger={ozet.ret} />
          <Metrik etiket="Karar bekleyen" deger={ozet.bekleyen} />
          <Metrik etiket="AI süresi" deger={sure(ozet.aiSure)} />
          <Metrik etiket="Review süresi" deger={sure(ozet.reviewSure)} />
          <Metrik etiket="AI maliyeti" deger={dolar(ozet.maliyet)} />
        </div>
        <HedefOlcer etiket="Kabul oranı (onay + küçük düzeltme / üretilen)" deger={ozet.kabulOrani} hedef={0.7} />
      </Kart>

      <div className="sekmeler" role="group" aria-label="Case filtresi">
        {(
          [
            ["hepsi", `Hepsi (${liste.length})`],
            ["bekleyen", `Karar bekleyen (${ozet.bekleyen})`],
            ["onayli", `Onaylı (${liste.filter((c) => c.durum === "approved" || c.durum === "published").length})`],
            ["reddedilen", `Reddedilen (${ozet.ret})`],
          ] as [Filtre, string][]
        ).map(([k, etiket]) => (
          <button key={k} type="button" className={`sekme${filtre === k ? " aktif" : ""}`} aria-pressed={filtre === k} onClick={() => setFiltre(k)}>
            {etiket}
          </button>
        ))}
      </div>

      {caseler.yukleniyor && !caseler.veri ? (
        <Yukleniyor />
      ) : caseler.hata && !caseler.veri ? (
        <HataKutusu hata={caseler.hata} yenile={() => void caseler.yenile()} />
      ) : gorunen.length === 0 ? (
        <Kart>
          <BosDurum baslik={liste.length ? "Bu filtrede case yok." : "Henüz case üretilmedi."}>
            {!liste.length && "PO teyidinden sonra gereksinim ekranından 'Case üret' ile başlatın."}
          </BosDurum>
        </Kart>
      ) : (
        <div className="case-liste">
          {gorunen.map((c) => (
            <CaseKarti
              key={c.id}
              tc={c}
              guncellendi={(t) => caseler.setVeri(liste.map((x) => (x.id === t.id ? t : x)))}
              yenile={() => void caseler.yenile(true)}
            />
          ))}
        </div>
      )}
    </>
  );
}

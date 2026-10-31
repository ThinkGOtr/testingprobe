import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { CaseMetrikleri, TestCase } from "../api/types";
import { useOturum } from "../auth";
import { CaseKarti } from "../components/CaseKarti";
import { BosDurum, HataKutusu, Kart, Metrik, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { HedefOlcer } from "../components/Grafikler";
import { useGeciktirilmis, useVeri } from "../hooks";
import { dolar, sure, yuzde } from "../lib/format";
import { YAYIN_ROLU_GEREKLI } from "./Yayin";

const ONAYLI = new Set(["approved", "published"]);

/** Düzeltme küçük mü: core bayrağı (`kucuk_duzeltme`) varsa o, yoksa §12 eşiği (ölçü ≤ 0,15). */
const kucukMu = (c: TestCase) => c.kucuk_duzeltme ?? (c.duzeltme_olcusu ?? 1) <= 0.15;

/**
 * Case sayaçları. Durum esastır: "Taslağa al" sonrası case `draft`'a döner ama core'un son karar
 * kaydı (`karar`) önceki kararı göstermeye devam eder — bu yüzden bekleyen = `draft`.
 * §12 kabul = onay + küçük düzeltmeyle onay / üretilen (yerel yaklaşık; çekirdek ölçümü varsa o).
 */
/**
 * Story başına manuel case hazırlama süresi (baz değer, TEKNIK-TASARIM §1.6/§12). Önce çekirdeğin
 * `manuel_baz_ms`'i; yoksa portal derleme ayarı `VITE_MANUEL_BAZ_DK` (dakika). İkisi de yoksa
 * null: baz değer uydurulmaz, "ölçülmedi" yazılır.
 */
export function manuelBazMs(m?: CaseMetrikleri | null, ortam: string | undefined = import.meta.env.VITE_MANUEL_BAZ_DK): number | null {
  if (m && typeof m.manuel_baz_ms === "number" && m.manuel_baz_ms > 0) return m.manuel_baz_ms;
  const dk = ortam ? Number(ortam.replace(",", ".")) : NaN;
  return Number.isFinite(dk) && dk > 0 ? Math.round(dk * 60_000) : null;
}

/**
 * AI çağrılarının modu: hepsi kayıttan (replay / replay_miss) ise süre ve maliyet ölçülmemiştir
 * (REPLAY 0 ms / 0 token kaydeder); "0 ms / $0,00" ölçüm gibi gösterilmez. Bilinmiyorsa null.
 */
export function aiModu(caseler: TestCase[], m?: CaseMetrikleri | null): "live" | "replay" | "replay_miss" | "karisik" | null {
  const modlar = new Set<string>();
  if (m && Object.keys(m.ai_cagri_modlari ?? {}).length) {
    for (const [k, n] of Object.entries(m.ai_cagri_modlari)) if (n > 0) modlar.add(k);
  } else {
    for (const c of caseler) if (c.ai_generated && c.mode) modlar.add(c.mode);
  }
  if (modlar.size === 0) return null;
  if (!modlar.has("live")) return modlar.has("replay_miss") ? "replay_miss" : "replay";
  return modlar.size === 1 ? "live" : "karisik";
}

export function caseOzeti(caseler: TestCase[], m?: CaseMetrikleri | null) {
  const onayli = caseler.filter((c) => ONAYLI.has(c.durum));
  const onay = onayli.filter((c) => c.karar === "approve").length;
  const duzeltilmis = onayli.filter((c) => c.karar === "edit").length;
  const kucukDuzeltme = onayli.filter((c) => c.karar === "edit" && kucukMu(c)).length;
  const ret = caseler.filter((c) => c.durum === "rejected").length;
  const bekleyen = caseler.filter((c) => c.durum === "draft").length;
  const olculen = caseler.filter((c) => c.review_sure_ms !== null);
  const yerel = {
    uretilen: caseler.length,
    onay,
    duzeltilmis,
    ret,
    bekleyen,
    /** Hiç karar yoksa null: "%0 hedefin altında" denmez. */
    kabulOrani: caseler.length && caseler.some((c) => c.durum !== "draft") ? (onay + kucukDuzeltme) / caseler.length : (null as number | null),
    /** Kabul oranının kaynağı: çekirdek ölçümü (ilk karara göre, §12) ya da ekrandaki son durum. */
    kabulKaynagi: "yerel" as "cekirdek" | "yerel",
    aiSure: caseler.reduce((a, c) => a + c.ai_sure_ms, 0),
    reviewSure: olculen.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0),
    /** Review süresi ölçülen (görüntüleme → karar) case sayısı ve ortalaması. */
    olculenReview: olculen.length,
    ortReviewSure: olculen.length ? olculen.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0) / olculen.length : 0,
    maliyet: caseler.reduce((a, c) => a + c.maliyet_usd, 0),
  };
  if (!m) return yerel;
  return {
    ...yerel,
    kabulOrani: m.karar_verilen > 0 ? m.kabul_orani : null,
    kabulKaynagi: "cekirdek" as const,
    aiSure: m.ai_sure_ms,
    reviewSure: m.review_sure_ms,
    ortReviewSure: m.ort_review_sure_ms ?? 0,
    maliyet: m.maliyet_usd,
  };
}

type Filtre = "hepsi" | "bekleyen" | "onayli" | "reddedilen";

export function CaseReview() {
  const { id = "" } = useParams();
  const gereksinim = useVeri(() => api.gereksinim(id), [id]);
  const caseler = useVeri(() => api.caseler(id), [id]);
  // Çekirdek ölçümü yoksa (uç henüz yok / hata) sayaçlar listeden hesaplanır.
  const metrik = useVeri(() => api.caseMetrikleri(id).catch(() => null), [id]);
  const [filtre, setFiltre] = useState<Filtre>("hepsi");
  const sessiz = useGeciktirilmis(() => {
    void caseler.yenile(true);
    void metrik.yenile(true);
  });
  useOlay((o) => {
    // Başka gereksinimin olayı bu listeyi yenilemez (gereksinim kimliği taşıyorsa).
    if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== id) return;
    sessiz();
  }, ["case.generated", "case.updated", "requirement.updated", "publish.updated"]);

  const liste = caseler.veri ?? [];
  const ozet = useMemo(() => caseOzeti(liste, metrik.veri), [liste, metrik.veri]);
  const gorunen = liste.filter((c) =>
    filtre === "hepsi"
      ? true
      : filtre === "bekleyen"
        ? c.durum === "draft"
        : filtre === "onayli"
          ? c.durum === "approved" || c.durum === "published"
          : c.durum === "rejected",
  );
  const g = gereksinim.veri;
  const { kullanici } = useOturum();
  const yayinYetkili = kullanici?.rol === "analyst";
  const mod = aiModu(liste, metrik.veri);
  const aiOlculmedi = mod === "replay" || mod === "replay_miss";
  const baz = manuelBazMs(metrik.veri);
  const hazirlik = aiOlculmedi ? ozet.reviewSure : ozet.aiSure + ozet.reviewSure;
  const kazanc = baz && ozet.olculenReview > 0 ? 1 - hazirlik / baz : null;

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}`}>← {g?.jira_key ?? g?.baslik ?? "Gereksinim"}</Link>}
        baslik="Case review"
        aciklama={g ? `${g.jira_key ? `${g.jira_key} · ` : ""}${g.baslik}` : undefined}
        eylemler={
          yayinYetkili ? (
            <Link className="dugme dugme-birincil" to={`/gereksinimler/${encodeURIComponent(id)}/yayin`}>
              Yayın önizleme
            </Link>
          ) : (
            <button type="button" className="dugme dugme-ikincil" disabled title={YAYIN_ROLU_GEREKLI}>
              Yayın önizleme
            </button>
          )
        }
      />

      <Kart baslik="Özet" eylemler={aiOlculmedi ? <ReplayRozeti mode={mod} /> : undefined}>
        <div className="metrik-izgara">
          <Metrik etiket="Üretilen" deger={ozet.uretilen} />
          <Metrik etiket="Onaylı" deger={ozet.onay} />
          <Metrik etiket="Düzeltilerek onaylı" deger={ozet.duzeltilmis} />
          <Metrik etiket="Reddedilen" deger={ozet.ret} />
          <Metrik etiket="Karar bekleyen" deger={ozet.bekleyen} />
          <Metrik
            etiket="AI süresi"
            deger={aiOlculmedi ? "—" : sure(ozet.aiSure)}
            alt={aiOlculmedi ? "REPLAY — ölçülmedi" : mod === "karisik" ? "kısmen REPLAY (yalnız canlı çağrılar)" : undefined}
          />
          <Metrik
            etiket="Review süresi"
            deger={sure(ozet.reviewSure)}
            alt={ozet.olculenReview ? `${ozet.olculenReview} case · ort. ${sure(ozet.ortReviewSure)}` : "henüz ölçülmedi"}
          />
          <Metrik
            etiket="AI + review"
            deger={sure(hazirlik)}
            alt={
              aiOlculmedi
                ? "yalnız review; AI süresi REPLAY'de ölçülmedi"
                : ozet.bekleyen > 0
                  ? `review sürüyor (${ozet.bekleyen} case bekliyor)`
                  : undefined
            }
          />
          <Metrik
            etiket="Manuel baz (story başına)"
            deger={baz ? sure(baz) : "—"}
            alt={baz ? "elle hazırlama, F0 ölçümü" : "ölçülmedi — baz değer girilmedi (F0 ölçümü)"}
          />
          <Metrik
            etiket="Kazanç"
            deger={kazanc === null ? "—" : yuzde(kazanc)}
            alt={
              kazanc === null
                ? baz
                  ? "henüz review süresi ölçülmedi"
                  : "baz değer olmadan hesaplanmaz"
                : `hedef %30–50${aiOlculmedi ? " · AI süresi hariç (REPLAY)" : ""}${ozet.bekleyen > 0 ? ` · ara değer, ${ozet.bekleyen} case bekliyor` : ""}`
            }
          />
          <Metrik etiket="AI maliyeti" deger={aiOlculmedi ? "—" : dolar(ozet.maliyet)} alt={aiOlculmedi ? "REPLAY — ölçülmedi" : undefined} />
        </div>
        <HedefOlcer
          etiket={
            ozet.kabulKaynagi === "cekirdek"
              ? "Kabul oranı (ilk karar: onay + küçük düzeltme / üretilen)"
              : "Kabul oranı (onay + küçük düzeltme / üretilen)"
          }
          deger={ozet.kabulOrani}
          hedef={metrik.veri?.kabul_hedefi ?? 0.7}
          bosMetin="henüz karar yok"
        />
        {(metrik.veri?.kapsanmayan_ac?.length ?? 0) > 0 && (
          <Uyari baslik="Kapsanmayan kabul kriteri">
            Hiçbir güncel case şu kabul kriterlerine atıf yapmıyor: {metrik.veri!.kapsanmayan_ac!.join(", ")}. Reddetmeden önce kapsamı
            kontrol edin.
          </Uyari>
        )}
        <p className="soluk kucuk">
          Review süresi, case kartı ekranınıza ilk girdiği andan kararınıza kadar sunucuda ölçülür. Yeniden açılan case'in süresi yeniden
          başlar.
        </p>
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

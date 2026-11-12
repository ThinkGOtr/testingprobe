// 012/Ş8 (ANALIZ §4.7): Kule KPI şeridinin iki kalite karosu. Değer yoksa "ölçülmedi" yazılır; core
// anahtarı sunmuyorsa (eski sürüm) ya da payda 0 ise sayı uydurulmaz.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { KontrolKulesi, KpiAnahtari } from "../../api/types";
import { tarih, yuzde } from "../../lib/format";
import { PLATFORM_ETIKETI, type Platform } from "../../lib/platform";
import { KaynakIpucu } from "../KaynakIpucu";
import { Cip, Kart, Metrik, Olculmedi } from "../ui";
import "./kule-hata.css";

/** Kule'deki `KpiBaslik` ile aynı biçim: ad + (i) kaynak ipucu (`k.kaynaklar[anahtar]`). */
function KpiBaslik({ ad, k, anahtar, ek }: { ad: string; k: KontrolKulesi; anahtar: KpiAnahtari; ek?: string }): ReactNode {
  const kaynak = k.kaynaklar[anahtar];
  return (
    <span className="kpi-baslik">
      {ad} <KaynakIpucu kaynak={kaynak && ek ? `${kaynak} ${ek}` : (kaynak ?? ek)} />
    </span>
  );
}

/** g2 O2: dürüst bağımsızlık notu (karar tabloları sayfası ve Kule ipucu). */
export const BAGIMSIZLIK_NOTU = "Bağımsızlık insan onayına dayanır: tablo AI taslağıdır, PO onayıyla bağımsızlaşır.";

/**
 * u2 N1: beklenti doğruluğunun özeti — "5/6 uyumlu" (payda = uyumlu + uyumsuz = n), kısmen / kontrol edilemedi /
 * tekrar ayrı. Kule karosu ve case review "Özet" kartı aynı metni kullanır.
 */
export function beklentiParcalari(b: { uyumlu: number; uyumsuz: number; kismen?: number; kontrol_edilemedi: number; tekrar?: number }): string[] {
  const payda = b.uyumlu + b.uyumsuz;
  const p = [payda > 0 ? `${b.uyumlu}/${payda} uyumlu${b.uyumsuz > 0 ? ` · ${b.uyumsuz} uyuşmayan` : ""}` : "tabloyla karşılaştırılan case yok"];
  if (b.kismen) p.push(`${b.kismen} kısmen (orana girmez)`);
  return p;
}

/** n satırı: n = oranın paydası (uyumlu + uyumsuz); tekrar ayrı yazılır ("n = 6 case · 1 tekrar"). */
export function beklentiNParcalari(b: { uyumlu: number; uyumsuz: number; tekrar?: number; n_story?: number; golden_kaynakli?: number }): string[] {
  const n = b.uyumlu + b.uyumsuz;
  return [
    `n = ${n} case`,
    ...(b.tekrar ? [`${b.tekrar} tekrar (aynı denetim, tek sayıldı)`] : []),
    ...(b.n_story !== undefined ? [`${b.n_story} story`] : []),
    ...(b.golden_kaynakli ? ["REPLAY / elle golden"] : []),
  ];
}

/** Çekirdeğin anahtarı hiç sunmadığı durum (eski sürüm): tek ifade, oracle metriğiyle aynı. */
export const CEKIRDEK_BILDIRMIYOR = "çekirdek bu ölçümü bildirmiyor";
/** n bu sayının altındaysa oran istatistiksel sonuç değil, göstergedir (§13.2). */
export const GOSTERGE_ESIGI = 20;

/** "Beklenti doğruluğu": AI'ın ürettiği beklenen değerlerin onaylı karar tablosuyla uyuşma oranı. */
export function BeklentiDogruluguKarosu({ k }: { k: KontrolKulesi }) {
  const b = k.beklenti_dogrulugu;
  const parcalar: string[] = [];
  if (b) {
    parcalar.push(...beklentiParcalari(b));
    // Payda yalnız tablosu olan story'ler: etiket bunu söyler (yanlış okunmasın).
    if (b.kapsam_orani !== null) parcalar.push(`tablosu olan story'lerde kapsam ${yuzde(b.kapsam_orani)}`);
    else if (b.kapsam_disi > 0) parcalar.push(`${b.kapsam_disi} kapsam dışı`);
    if (b.tablolu_story !== undefined && b.toplam_story !== undefined) parcalar.push(`tablosu olan story: ${b.tablolu_story} / ${b.toplam_story}`);
    if (b.kontrol_edilemedi > 0) parcalar.push(`${b.kontrol_edilemedi} kontrol edilemedi`);
    parcalar.push(`${b.istisna} istisnayla onaylanan`);
    if (b.kontrolsuz_onay !== undefined) parcalar.push(`${b.kontrolsuz_onay} kontrolsüz onay`);
  }
  const n = b ? b.uyumlu + b.uyumsuz : undefined;
  const nParcalari = b && b.n_case !== undefined ? beklentiNParcalari(b) : [];
  return (
    <Metrik
      etiket={<KpiBaslik ad="Beklenti doğruluğu" k={k} anahtar="beklenti_dogrulugu" ek={BAGIMSIZLIK_NOTU} />}
      deger={<span data-testid="beklenti-dogrulugu">{!b || b.oran === null ? <Olculmedi /> : yuzde(b.oran)}</span>}
      alt={
        <>
          <span data-testid="beklenti-ayrinti">{b ? parcalar.join(" · ") : CEKIRDEK_BILDIRMIYOR}</span>
          {nParcalari.length > 0 && (
            <span className="kule-n" data-testid="beklenti-n">
              {nParcalari.join(" · ")}
              {n !== undefined && n < GOSTERGE_ESIGI && (
                <>
                  {" "}
                  <Cip ton="uyari" title={`n < ${GOSTERGE_ESIGI}: oran istatistiksel sonuç değil, gösterge niteliğindedir.`}>
                    gösterge
                  </Cip>
                </>
              )}
            </span>
          )}
        </>
      }
    />
  );
}

/** Platform adları ("Web, Android"). */
const platformAdlari = (p: readonly Platform[]) => p.map((x) => PLATFORM_ETIKETI[x]).join(", ");

/**
 * "Hata yakalama oranı": son tam katalog ekilmiş hata koşusunda yakalanan / (yakalanan + kaçan). §13.2
 * biçiminde (`el_yazisi` var) değer yalnız AI (üretilmiş) testlerinin oranıdır; el yazısı suite ayrı yazılır.
 */
export function HataYakalamaKarosu({ k }: { k: KontrolKulesi }) {
  const h = k.hata_yakalama;
  let alt: string;
  if (h === undefined) alt = CEKIRDEK_BILDIRMIYOR;
  else if (h === null) alt = "henüz ekilmiş hata koşusu yok";
  else {
    const sayilan = h.yakalanan + h.kacan;
    const parcalar: string[] = [];
    if (h.el_yazisi) {
      parcalar.push(
        h.oran === null
          ? h.kapsam?.yeterli === false
            ? `AI testleri ${h.yakalanan}/${sayilan}`
            : "AI testleri: ölçülmedi (üretilmiş test yok)"
          : `AI testleri ${h.yakalanan}/${sayilan}`,
      );
      const e = h.el_yazisi;
      parcalar.push(`el yazısı suite ${e.oran === null ? (e.yakalanan + e.kacan > 0 ? `${e.yakalanan}/${e.yakalanan + e.kacan}` : "ölçülmedi") : `${yuzde(e.oran)} (${e.yakalanan}/${e.yakalanan + e.kacan})`}`);
    } else parcalar.push(sayilan > 0 ? `${h.yakalanan}/${sayilan} hata yakalandı` : "sayılan adım yok");
    if (h.kapsam) {
      const kp = h.kapsam;
      parcalar.push(
        `${kp.kosulan_hata < kp.katalog ? `${kp.kosulan_hata}/${kp.katalog} katalog hatası` : `${kp.kosulan_hata} ekilmiş hata üzerinde`}${kp.platformlar.length ? ` · ${platformAdlari(kp.platformlar)}` : ""}`,
      );
    }
    if (h.gecersiz > 0) parcalar.push(`${h.gecersiz} geçersiz (orana girmez)`);
    // Q2 (Y10): geçerli adım eşiğin altındaysa oranlar null; nedeni yazılır.
    if (h.kapsam?.yeterli === false) parcalar.unshift(`ölçülmedi — ${h.kapsam.not ?? "geçerli hata adımı yetersiz"}`);
    if (h.ai_kacanlar && h.ai_kacanlar.length > 0) parcalar.push(`AI testlerinin kaçırdığı ${new Set(h.ai_kacanlar.map((x) => x.hata_kodu)).size} hata`);
    parcalar.push(`son koşu ${tarih(h.son_kosu.bitis)}`);
    alt = parcalar.join(" · ");
  }
  return (
    <Metrik
      etiket={<KpiBaslik ad="Hata yakalama oranı" k={k} anahtar="hata_yakalama" />}
      deger={<span data-testid="hata-yakalama">{!h || h.oran === null ? <Olculmedi /> : yuzde(h.oran)}</span>}
      alt={<span data-testid="hata-yakalama-ayrinti">{alt}</span>}
    />
  );
}

/** §13.2 Kule `onayli_uyumsuz`: onaylandıktan sonra (tablo değişti ya da istisnayla onay) tabloyla uyuşmayan case'ler. */
export function OnayliUyumsuzKarti({ k }: { k: KontrolKulesi }) {
  const liste = k.onayli_uyumsuz;
  // Çekirdek anahtarı sunmuyorsa kart çizilmez (boş liste "yok" demektir, bilinmeyen değil).
  if (liste === undefined) return null;
  return (
    <Kart baslik="Onaylandıktan sonra tabloyla uyuşmayan case'ler" className="kule-onayli-uyumsuz">
      <div data-testid="onayli-uyumsuz">
        {liste.length === 0 ? (
          <p className="soluk kucuk">Onaylı case'lerin hepsi güncel onaylı tablolarla uyumlu ya da kapsam dışı.</p>
        ) : (
          <>
            <p className="kucuk">
              Bu case'ler onaylı, ama beklenen değerleri güncel onaylı karar tablosuyla uyuşmuyor (tablo sonradan değişti ya da case gerekçeli istisnayla
              onaylandı). Case'i düzeltin ya da tablonun doğru olduğunu PO ile teyit edin.
            </p>
            <ul className="duz-liste">
              {liste.map((c) => (
                <li key={c.case_id}>
                  {/* Ham case kimliği gösterilmez: "TPD-1 · C5 başlık" (core anahtarı vermezse yalnız başlık). */}
                  <Link to={`/gereksinimler/${encodeURIComponent(c.requirement_id)}/caseler#case-${encodeURIComponent(c.case_id)}`}>
                    {[c.jira_key, typeof c.sira_no === "number" ? `C${c.sira_no}` : null].filter(Boolean).join(" · ")}
                    {(c.jira_key || typeof c.sira_no === "number") && " "}
                    {c.baslik}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Kart>
  );
}

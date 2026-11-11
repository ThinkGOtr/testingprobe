// 012/Ş8 (ANALIZ §4.7): Kule KPI şeridinin iki kalite karosu. Değer yoksa "ölçülmedi" yazılır; core
// anahtarı sunmuyorsa (eski sürüm) ya da payda 0 ise sayı uydurulmaz.
import type { ReactNode } from "react";
import type { KontrolKulesi, KpiAnahtari } from "../../api/types";
import { tarih, yuzde } from "../../lib/format";
import { KaynakIpucu } from "../KaynakIpucu";
import { Metrik, Olculmedi } from "../ui";
import "./kule-hata.css";

/** Kule'deki `KpiBaslik` ile aynı biçim: ad + (i) kaynak ipucu (`k.kaynaklar[anahtar]`). */
function KpiBaslik({ ad, k, anahtar }: { ad: string; k: KontrolKulesi; anahtar: KpiAnahtari }): ReactNode {
  return (
    <span className="kpi-baslik">
      {ad} <KaynakIpucu kaynak={k.kaynaklar[anahtar]} />
    </span>
  );
}

/** "Beklenti doğruluğu": AI'ın ürettiği beklenen değerlerin onaylı karar tablosuyla uyuşma oranı. */
export function BeklentiDogruluguKarosu({ k }: { k: KontrolKulesi }) {
  const b = k.beklenti_dogrulugu;
  const parcalar: string[] = [];
  if (b) {
    if (b.uyumlu + b.uyumsuz > 0) parcalar.push(`${b.uyumlu} uyumlu · ${b.uyumsuz} uyuşmayan`);
    else parcalar.push("tabloyla karşılaştırılan case yok");
    if (b.kapsam_orani !== null) parcalar.push(`kapsam ${yuzde(b.kapsam_orani)}`);
    else if (b.kapsam_disi > 0) parcalar.push(`${b.kapsam_disi} kapsam dışı`);
    if (b.kontrol_edilemedi > 0) parcalar.push(`${b.kontrol_edilemedi} kontrol edilemedi`);
    parcalar.push(`${b.istisna} istisnayla onaylanan`);
  }
  return (
    <Metrik
      etiket={<KpiBaslik ad="Beklenti doğruluğu" k={k} anahtar="beklenti_dogrulugu" />}
      deger={<span data-testid="beklenti-dogrulugu">{!b || b.oran === null ? <Olculmedi /> : yuzde(b.oran)}</span>}
      alt={<span data-testid="beklenti-ayrinti">{b ? parcalar.join(" · ") : "çekirdek bu ölçüyü bildirmedi"}</span>}
    />
  );
}

/** "Hata yakalama oranı": son ekilmiş hata koşusunda yakalanan / (yakalanan + kaçan). */
export function HataYakalamaKarosu({ k }: { k: KontrolKulesi }) {
  const h = k.hata_yakalama;
  let alt: string;
  if (h === undefined) alt = "çekirdek bu ölçüyü bildirmedi";
  else if (h === null) alt = "henüz ekilmiş hata koşusu yok";
  else {
    const sayilan = h.yakalanan + h.kacan;
    const parcalar = [sayilan > 0 ? `${h.yakalanan}/${sayilan} hata yakalandı` : "sayılan adım yok"];
    if (h.gecersiz > 0) parcalar.push(`${h.gecersiz} geçersiz (orana girmez)`);
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

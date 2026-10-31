import { useId, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { buFazdaYok } from "../api/http";
import type { CiktiModu, Rol } from "../api/types";
import { useOturum } from "../auth";
import { ROL, type Ton } from "../lib/etiketler";
import { baglantiTuru } from "../lib/rotalar";

/** Kayıtlı (replay) çıktı rozeti. live için hiçbir şey göstermez (Constitution VIII). */
export function ReplayRozeti({ mode }: { mode: CiktiModu | null | undefined }) {
  if (mode === "replay") {
    return (
      <span className="rozet rozet-replay" title="REPLAY: hazırlanmış örnek çıktı; canlı model değil.">
        REPLAY
      </span>
    );
  }
  if (mode === "replay_miss") {
    return (
      <span
        className="rozet rozet-replay-miss"
        title="REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok; canlı model gerekir."
      >
        REPLAY-MISS
      </span>
    );
  }
  return null;
}

export function Cip({ ton = "notr", children, title }: { ton?: Ton; children: ReactNode; title?: string }) {
  return (
    <span className={`cip cip-${ton}`} title={title}>
      {children}
    </span>
  );
}

export function Yukleniyor({ metin = "Yükleniyor…" }: { metin?: string }) {
  return (
    <div className="yukleniyor" role="status" aria-live="polite">
      <span className="donen" aria-hidden="true" />
      {metin}
    </div>
  );
}

export function HataKutusu({ hata, yenile }: { hata: string; yenile?: () => void }) {
  // Canlı derlemede core'un henüz sunmadığı ekran: hata değil, planlı "bu fazda yok" boş durumu.
  if (buFazdaYok(hata)) {
    return (
      <div className="bos-durum" role="status" data-testid="bu-fazda-yok">
        <p className="bos-baslik">Bu ekran bu fazda yok.</p>
        <div className="soluk">Çekirdek bu veriyi henüz sunmuyor. Canlı portalda örnek veri gösterilmez.</div>
      </div>
    );
  }
  return (
    <div className="uyari-kutusu uyari-hata" role="alert">
      <span>{hata}</span>
      {yenile && (
        <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={yenile}>
          Tekrar dene
        </button>
      )}
    </div>
  );
}

export function Uyari({ ton = "uyari", children, baslik }: { ton?: "uyari" | "bilgi" | "hata" | "basari"; children: ReactNode; baslik?: string }) {
  return (
    <div className={`uyari-kutusu uyari-${ton}`} role={ton === "hata" ? "alert" : "note"}>
      {baslik && <strong>{baslik}</strong>}
      <div>{children}</div>
    </div>
  );
}

export function BosDurum({ baslik, children }: { baslik: string; children?: ReactNode }) {
  return (
    <div className="bos-durum">
      <p className="bos-baslik">{baslik}</p>
      {children && <div className="soluk">{children}</div>}
    </div>
  );
}

export function SayfaBasligi({ baslik, aciklama, eylemler, ust }: { baslik: ReactNode; aciklama?: ReactNode; eylemler?: ReactNode; ust?: ReactNode }) {
  return (
    <header className="sayfa-basligi">
      <div>
        {ust && <div className="ust-baglanti">{ust}</div>}
        <h1>{baslik}</h1>
        {aciklama && <p className="soluk">{aciklama}</p>}
      </div>
      {eylemler && <div className="eylemler">{eylemler}</div>}
    </header>
  );
}

export function Kart({ baslik, eylemler, children, className, id }: { baslik?: ReactNode; eylemler?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  const baslikId = useId();
  return (
    <section className={`kart ${className ?? ""}`} aria-labelledby={baslik ? baslikId : undefined} id={id}>
      {(baslik || eylemler) && (
        <div className="kart-baslik">
          {baslik && <h2 id={baslikId}>{baslik}</h2>}
          {eylemler && <div className="eylemler">{eylemler}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

type DugmeTuru = "birincil" | "ikincil" | "tehlike" | "hayalet";

interface IslemDugmesiOzellikleri extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Bu düğmeyi kullanabilecek roller; boşsa herkes. */
  roller?: Rol[];
  calisiyor?: boolean;
  tur?: DugmeTuru;
  kucuk?: boolean;
}

/**
 * Rol farkındalıklı eylem düğmesi: yetkisiz rolde pasif ve nedenini söyler
 * (sunucu yine de her uçta rolü kontrol eder).
 */
export function IslemDugmesi({ roller, calisiyor, tur = "birincil", kucuk, disabled, children, title, className, ...geri }: IslemDugmesiOzellikleri) {
  const { kullanici } = useOturum();
  const yetkili = !roller || roller.length === 0 || (!!kullanici && roller.includes(kullanici.rol));
  const neden = !yetkili ? `Bu işlem için gereken rol: ${roller?.map((r) => ROL[r]).join(" / ")}` : title;
  return (
    <button
      type="button"
      {...geri}
      className={`dugme dugme-${tur}${kucuk ? " dugme-kucuk" : ""} ${className ?? ""}`}
      disabled={disabled || !yetkili || calisiyor}
      title={neden}
      aria-busy={calisiyor || undefined}
      data-yetkisiz={!yetkili || undefined}
    >
      {calisiyor && <span className="donen donen-kucuk" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Ilerleme({ oran, etiket, hedef }: { oran: number; etiket: string; hedef?: number }) {
  const yuzde = Math.max(0, Math.min(1, oran)) * 100;
  return (
    <div className="ilerleme" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(yuzde)} aria-label={etiket}>
      <div className="ilerleme-dolgu" style={{ width: `${yuzde}%` }} />
      {hedef !== undefined && <div className="ilerleme-hedef" style={{ left: `${hedef * 100}%` }} title={`Hedef: %${Math.round(hedef * 100)}`} />}
    </div>
  );
}

export function Metrik({ etiket, deger, alt }: { etiket: ReactNode; deger: ReactNode; alt?: ReactNode }) {
  return (
    <div className="metrik">
      <div className="metrik-etiket">{etiket}</div>
      <div className="metrik-deger">{deger}</div>
      {alt && <div className="metrik-alt">{alt}</div>}
    </div>
  );
}

export function DisBaglanti({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="dis-baglanti">
      {children}
      <span className="gorunmez"> (yeni sekmede açılır)</span>
      <span aria-hidden="true"> ↗</span>
    </a>
  );
}

/**
 * Adresin türüne göre bağlantı: dış adres yeni sekmede, portal ekranı uygulama içinde açılır.
 * Adres yoksa ya da portalın sunmadığı bir yolsa (ör. artifact sunucusu, forge) tıklanamaz metin
 * olarak gösterilir ve nedeni yazılır — "Sayfa bulunamadı"ya giden ölü bağlantı üretilmez.
 */
export function Baglanti({ href, children, yokNedeni }: { href: string | null | undefined; children: ReactNode; yokNedeni?: string }) {
  const tur = baglantiTuru(href);
  if (tur === "dis" && href) return <DisBaglanti href={href}>{children}</DisBaglanti>;
  if (tur === "ic" && href) return <Link to={href}>{children}</Link>;
  return (
    <span className="baglanti-yok">
      {children}
      {yokNedeni && <span className="soluk kucuk"> ({yokNedeni})</span>}
    </span>
  );
}

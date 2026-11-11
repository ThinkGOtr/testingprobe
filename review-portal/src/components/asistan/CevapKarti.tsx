// Asistan cevap kartı (AI-ASISTAN-PLANI §11 "Cevap kartı", §7.3 güven tablosu). Bloklar düz
// metin olarak çizilir (HTML yok); kaynaklar dosya:satır / Jira / CI biçiminde, doğrulanmamış
// kaynak biçimle işaretli (kesik kenarlı amber "doğrulanmadı" rozeti, --muted yol metni; satır
// soldurulmaz); bağlantılar yalnız iç rota (Git) ve sunucunun kurduğu Jira adresidir.
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { kaynakDogrulandi, kipRozeti, type AsistanDurumu, type AsistanMesaji, type CevapBlogu, type CevapKaynagiOgesi, type GuvenGosterimi } from "../../api/asistan";
import { mockZorunlu } from "../../api/http";
import { dolar, goreliZaman, guvenliDisAdres } from "../../lib/format";
import type { Ton } from "../../lib/etiketler";
import { uygulamaRotasiMi } from "../../lib/rotalar";
import { Ikon } from "../Ikon";
import { Cip, DisBaglanti } from "../ui";
import { AiOneriKarti } from "./OneriKarti";

// Renk disiplini (TASARIM-YENILEME-PLANI §3.2, §4.6): kırmızı yalnız hata/engel, indigo yalnız etkileşim/süren.
// "Emin değil" bir hata değil, dikkat çağrısıdır (doğrulayın) → amber; "Genel bilgi" kategoriktir → nötr.
export const GUVEN_TONU: Record<GuvenGosterimi, Ton> = {
  "Kaynakla doğrulandı": "basari",
  Kısmen: "uyari",
  "Emin değil": "uyari",
  "Genel bilgi": "notr",
};

const GUVEN_ACIKLAMASI: Record<GuvenGosterimi, string> = {
  "Kaynakla doğrulandı": "En az bir kaynak deterministik olarak doğrulandı.",
  Kısmen: "Kaynak var ama model emin değil ya da yalnız genel bilgiye dayanıyor.",
  "Emin değil": "Ürüne özgü soruda doğrulanmış kaynak yok.",
  "Genel bilgi": "Ürüne özgü olmayan genel QA bilgisi.",
};

/**
 * Kip rozeti (013 §7, K12): `CANLI · Haiku 5.5` / `ŞABLON` / `MODEL KAPALI`. Eski "Hazır cevap · …"
 * etiketi rozetin açıklamasıdır (title + ekran okuyucu metni): kartta iki ayrı etiket olmaz. Anlam
 * metinde; renk ek ipucudur (canlı = AI moru, şablon/kapalı = nötr).
 */
export function KipRozeti({ mesaj, modeller }: { mesaj: Pick<AsistanMesaji, "kaynak" | "amac">; modeller?: Pick<AsistanDurumu, "varsayilan_model" | "derin_model"> | null }) {
  const r = kipRozeti(mesaj, modeller);
  if (!r) return null;
  // Açıklama rozetin dışında: .rozet büyük harfe çevirir, ekran okuyucu metni olduğu gibi okunsun.
  return (
    <>
      <span className={`rozet rozet-kip rozet-kip-${r.tur}`} title={r.aciklama} data-testid="kip-rozeti">
        {r.metin}
      </span>
      <span className="gorunmez">{r.aciklama}</span>
    </>
  );
}

/** Göreli zaman tek yerde (lib/format); eski içe aktarımlar için yeniden dışa aktarılır. */
export { goreliZaman };

/** Kaynak listesindeki görünen etiket. */
export function kaynakEtiketi(k: CevapKaynagiOgesi): string {
  switch (k.tur) {
    case "jira": {
      const anahtar = k.jira?.anahtar ?? k.ref;
      const zaman = goreliZaman(k.jira?.tarih);
      const tur = k.jira?.yorum === false ? "Jira kaydı" : "Jira yorumu";
      return `${tur} (${[anahtar, zaman].filter(Boolean).join(", ")})`;
    }
    case "ci_log": {
      const c = k.ci;
      const kosu = c?.kosu_no != null ? `koşu #${c.kosu_no}` : c?.run_id ? `koşu ${c.run_id}` : "koşu";
      const satir =
        c?.satir_bas != null ? `, satır ${c.satir_bas}${c.satir_bit != null && c.satir_bit !== c.satir_bas ? `–${c.satir_bit}` : ""}` : "";
      return `CI logu (${kosu}${satir})`;
    }
    case "genel_bilgi":
      return "Genel bilgi";
    case "probe_verisi":
      return "Testing Probe kaydı";
    case "uygulama_verisi":
      return "Test edilen uygulamanın verisi";
    case "urun_kodu":
    case "uygulama_kodu":
    case "dokuman":
      return k.ref || "dosya";
  }
}

const KAYNAK_TURU: Record<CevapKaynagiOgesi["tur"], string> = {
  urun_kodu: "Ürün kodu",
  uygulama_kodu: "Uygulama kodu",
  uygulama_verisi: "Uygulama verisi",
  probe_verisi: "Probe verisi",
  jira: "Jira",
  ci_log: "CI",
  dokuman: "Doküman",
  genel_bilgi: "Genel",
};

export function Bloklar({ bloklar }: { bloklar: CevapBlogu[] }) {
  return (
    <div className="asistan-bloklar">
      {bloklar.map((b, i) => {
        switch (b.tur) {
          case "baslik":
            return (
              <h3 key={i} className="asistan-blok-baslik">
                {b.metin}
              </h3>
            );
          case "liste":
            return (
              <div key={i}>
                {b.metin && <p>{b.metin}</p>}
                <ul>
                  {(b.maddeler ?? []).map((m, j) => (
                    <li key={j}>{m}</li>
                  ))}
                </ul>
              </div>
            );
          case "kod":
            return (
              <pre key={i} className="kod-blok">
                <code>{b.metin}</code>
              </pre>
            );
          default:
            return <p key={i}>{b.metin}</p>;
        }
      })}
    </div>
  );
}

const MODAL_ODAKLANABILIR = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Alıntı modalı (`aria-modal`): açılınca "Kapat"a odak, Tab/Shift+Tab modal içinde döner (panelin
 * kendi tuzağına geçmez), kapanınca odak açan düğmeye ("Alıntıyı göster") geri verilir.
 */
function AlintiModali({ kaynak, kapat }: { kaynak: CevapKaynagiOgesi; kapat: () => void }) {
  const baslikId = useId();
  const modalRef = useRef<HTMLDivElement>(null);
  const kapatRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const acan = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    kapatRef.current?.focus();
    return () => {
      if (acan?.isConnected) acan.focus();
    };
  }, []);
  return (
    <div className="asistan-modal-arka" onClick={kapat}>
      <div
        ref={modalRef}
        className="asistan-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={baslikId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            kapat();
            return;
          }
          if (e.key !== "Tab") return;
          // Panelin (dar ekran) belge düzeyindeki Tab tuzağına ulaşmasın: odak modalda kalır.
          e.stopPropagation();
          const ogeler = Array.from(modalRef.current?.querySelectorAll<HTMLElement>(MODAL_ODAKLANABILIR) ?? []);
          if (ogeler.length === 0) {
            e.preventDefault();
            return;
          }
          const ilk = ogeler[0];
          const son = ogeler[ogeler.length - 1];
          const aktif = document.activeElement;
          if (e.shiftKey && (aktif === ilk || !modalRef.current?.contains(aktif))) {
            e.preventDefault();
            son.focus();
          } else if (!e.shiftKey && (aktif === son || !modalRef.current?.contains(aktif))) {
            e.preventDefault();
            ilk.focus();
          }
        }}
      >
        <div className="asistan-modal-baslik">
          <h3 id={baslikId}>{kaynakEtiketi(kaynak)}</h3>
          <button ref={kapatRef} type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={kapat}>
            Kapat
          </button>
        </div>
        {kaynak.dogrulandi === false && <p className="asistan-dogrulanmadi">Bu alıntı kaynakta doğrulanamadı.</p>}
        <pre className="kod-blok">
          <code>{kaynak.alinti || "(alıntı yok)"}</code>
        </pre>
        {guvenliDisAdres(kaynak.jira?.url) && <DisBaglanti href={guvenliDisAdres(kaynak.jira?.url)!}>Jira'da aç</DisBaglanti>}
      </div>
    </div>
  );
}

function Kaynaklar({ kaynaklar }: { kaynaklar: CevapKaynagiOgesi[] }) {
  const [acik, setAcik] = useState<CevapKaynagiOgesi | null>(null);
  if (kaynaklar.length === 0) return null;
  return (
    <div className="asistan-kaynaklar">
      <div className="asistan-alt-baslik">Kaynaklar</div>
      <ul>
        {kaynaklar.map((k, i) => {
          const dogrulanmadi = k.dogrulandi === false && k.tur !== "genel_bilgi";
          return (
            <li key={i} className={dogrulanmadi ? "asistan-kaynak soluk-kaynak" : "asistan-kaynak"}>
              <span className="asistan-kaynak-tur">{KAYNAK_TURU[k.tur]}</span>
              <span className="mono asistan-kaynak-ref">{kaynakEtiketi(k)}</span>
              {dogrulanmadi && (
                <span className="asistan-dogrulanmadi" title="Alıntı kaynakta bulunamadı; bu kaynağa dayanmayın.">
                  doğrulanmadı
                </span>
              )}
              {k.alinti && (
                <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setAcik(k)}>
                  {k.tur === "urun_kodu" || k.tur === "uygulama_kodu" || k.tur === "dokuman" ? "Satırları göster" : "Alıntıyı göster"}
                </button>
              )}
              {k.tur === "jira" && guvenliDisAdres(k.jira?.url) && <DisBaglanti href={guvenliDisAdres(k.jira?.url)!}>Jira'da aç</DisBaglanti>}
            </li>
          );
        })}
      </ul>
      {acik && <AlintiModali kaynak={acik} kapat={() => setAcik(null)} />}
    </div>
  );
}

export interface CevapKartiOzellikleri {
  mesaj: AsistanMesaji;
  /** Kartın üst etiketi ("Ön cevap (kaynakla doğrulanamadı)", "Ayrıntılı inceleme"). */
  baslik?: ReactNode;
  /** "Daha ayrıntılı incele" gösterilsin mi (çağıran koşulları hesaplar). */
  derinIncelenebilir?: boolean;
  derinIncele?: () => void;
  derinCalisiyor?: boolean;
  geriBildir?: (deger: -1 | 1) => void;
  /** "Bu saat kalan soru hakkı ≈ N" (son kartta; core saatlik sınırdan türetir, günlük bütçe ayrı 402 ile keser). */
  kalanSoru?: number | null;
  /** Git bağlantısına basılınca (mobilde panel kapanır). */
  onGit?: () => void;
  /** `/assistant/status` model kimlikleri: kip rozetindeki kısa model adı. */
  modeller?: Pick<AsistanDurumu, "varsayilan_model" | "derin_model"> | null;
}

export function CevapKarti({ mesaj, baslik, derinIncelenebilir, derinIncele, derinCalisiyor, geriBildir, kalanSoru, onGit, modeller }: CevapKartiOzellikleri) {
  const derinNotId = useId();
  const c = mesaj.cevap;
  if (!c) return null;
  const guven = c.guven_gosterimi ?? null;
  const ornek = c.ornek_veri === true || mockZorunlu();
  const yonlendirmeler = (c.yonlendirmeler ?? []).filter((y) => uygulamaRotasiMi(y.rota));
  // Jira adresleri yalnız http(s) ise bağlantı olur (javascript:/data: vb. düşer; OneriKarti ile aynı süzgeç).
  const kaynakJiraAnahtarlari = new Set(
    (c.kaynaklar ?? []).filter((k) => k.tur === "jira" && guvenliDisAdres(k.jira?.url)).map((k) => k.jira!.anahtar),
  );
  const jiraBaglantilari = (c.jira_baglantilari ?? [])
    .flatMap((j) => {
      const url = guvenliDisAdres(j.url);
      return url ? [{ ...j, url }] : [];
    })
    .filter((j) => !kaynakJiraAnahtarlari.has(j.anahtar));
  const maliyet = mesaj.maliyet_usd != null ? Number(mesaj.maliyet_usd) : null;
  const olculmedi = mesaj.kaynak !== "model" || maliyet === null || !Number.isFinite(maliyet);
  return (
    <article className="asistan-cevap" aria-label={typeof baslik === "string" ? baslik : "Asistan cevabı"} data-mesaj-id={mesaj.id}>
      <div className="asistan-cevap-ust">
        {baslik && <strong className="asistan-cevap-etiket">{baslik}</strong>}
        {guven && (
          <Cip ton={GUVEN_TONU[guven]} title={GUVEN_ACIKLAMASI[guven]}>
            {guven}
          </Cip>
        )}
        <KipRozeti mesaj={mesaj} modeller={modeller} />
        {ornek && (
          <span className="rozet rozet-mock" title="Örnek veri: hazırlanmış cevap, gerçek asistan cevabı değil.">
            ÖRNEK VERİ
          </span>
        )}
      </div>
      <Bloklar bloklar={c.cevap_bloklari ?? []} />
      {c.eylem_reddi && <p className="asistan-not">Asistan işlem yapmaz; bu işlemi ilgili ekranda siz yaparsınız.</p>}
      {(c.notlar ?? []).map((n, i) => (
        <p key={i} className="asistan-not">
          {n}
        </p>
      ))}
      {(c.oneriler ?? []).length > 0 && (
        <div className="asistan-oneriler">
          <div className="asistan-alt-baslik">Ek öneriler</div>
          {/* Öneriler sekmesindeki kartın aynısı: taslak/Jira eylemleri (Taslağı göster/Kopyala) geçmişte de çizilir. */}
          <ul className="oneri-liste">
            {c.oneriler!.map((o, i) => (
              <li key={i}>
                <AiOneriKarti oneri={o} onGit={onGit} sohbetId={mesaj.sohbet_id} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <Kaynaklar kaynaklar={(c.kaynaklar ?? []).map((k) => ({ ...k, dogrulandi: kaynakDogrulandi(c, k) }))} />
      {(yonlendirmeler.length > 0 || jiraBaglantilari.length > 0) && (
        <div className="asistan-yonlendirmeler">
          {yonlendirmeler.map((y, i) => (
            <Link key={i} to={y.rota} className="dugme dugme-ikincil dugme-kucuk" onClick={onGit}>
              Git: {y.etiket}
            </Link>
          ))}
          {jiraBaglantilari.map((j) => (
            <DisBaglanti key={j.anahtar} href={j.url}>
              Jira'da aç: {j.anahtar}
            </DisBaglanti>
          ))}
        </div>
      )}
      {derinIncelenebilir && derinIncele && c.derin_onerilir && (
        <p id={derinNotId} className="asistan-not" data-testid="derin-onerilir">
          Bu cevap kaynakla doğrulanamadı; ayrıntılı inceleme önerilir.
        </p>
      )}
      <p className="asistan-bilgi-amacli soluk kucuk">Bilgi amaçlıdır; kararı ilgili ekranda verin.</p>
      <div className="asistan-cevap-alt">
        {derinIncelenebilir && derinIncele && (
          // `derin_onerilir`: cevap doğrulanamadı ama otomatik yükseltme ön koşulu tutmadı (bütçe %20
          // altı vb., §6.2); otomatik inceleme yerine düğme birincil tonda ve notla önerilir.
          <button
            type="button"
            className={c.derin_onerilir ? "dugme dugme-birincil dugme-kucuk" : "dugme dugme-ikincil dugme-kucuk"}
            onClick={derinIncele}
            disabled={derinCalisiyor}
            aria-describedby={c.derin_onerilir ? derinNotId : undefined}
          >
            Daha ayrıntılı incele
          </button>
        )}
        {geriBildir && (
          <span className="asistan-geri-bildirim">
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              aria-label="Faydalı"
              aria-pressed={mesaj.geri_bildirim === 1}
              onClick={() => geriBildir(1)}
            >
              <Ikon ad="begen" />
            </button>
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              aria-label="Faydasız"
              aria-pressed={mesaj.geri_bildirim === -1}
              onClick={() => geriBildir(-1)}
            >
              <Ikon ad="begenme" />
            </button>
          </span>
        )}
        <span className="soluk kucuk">Maliyet: {olculmedi ? "ölçülmedi" : `≈ ${dolar(maliyet!)}`}</span>
        {kalanSoru != null && <span className="soluk kucuk">Bu saat kalan soru hakkı ≈ {kalanSoru}</span>}
      </div>
    </article>
  );
}

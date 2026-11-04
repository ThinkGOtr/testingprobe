// Asistan cevap kartı (AI-ASISTAN-PLANI §11 "Cevap kartı", §7.3 güven tablosu). Bloklar düz
// metin olarak çizilir (HTML yok); kaynaklar dosya:satır / Jira / CI biçiminde, doğrulanmamış
// kaynak soluk ve uyarılı; bağlantılar yalnız iç rota (Git) ve sunucunun kurduğu Jira adresidir.
import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { kaynakDogrulandi, type AsistanMesaji, type CevapBlogu, type CevapKaynagiOgesi, type GuvenGosterimi } from "../../api/asistan";
import { mockZorunlu } from "../../api/http";
import { dolar } from "../../lib/format";
import type { Ton } from "../../lib/etiketler";
import { uygulamaRotasiMi } from "../../lib/rotalar";
import { Cip, DisBaglanti } from "../ui";
import { AiOneriKarti } from "./OneriKarti";

export const GUVEN_TONU: Record<GuvenGosterimi, Ton> = {
  "Kaynakla doğrulandı": "basari",
  Kısmen: "uyari",
  "Emin değil": "hata",
  "Genel bilgi": "bilgi",
};

const GUVEN_ACIKLAMASI: Record<GuvenGosterimi, string> = {
  "Kaynakla doğrulandı": "En az bir kaynak deterministik olarak doğrulandı.",
  Kısmen: "Kaynak var ama model emin değil ya da yalnız genel bilgiye dayanıyor.",
  "Emin değil": "Ürüne özgü soruda doğrulanmış kaynak yok.",
  "Genel bilgi": "Ürüne özgü olmayan genel QA bilgisi.",
};

const KAYNAK_NOTU: Record<string, string> = {
  sozluk: "Hazır cevap · hata sözlüğü",
  sablon: "Hazır cevap · kayıt durumu",
  kapali: "Hazır cevap",
};

/** "2 gün önce" biçiminde göreli zaman. */
export function goreliZaman(iso: string | null | undefined, simdi = Date.now()): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const sn = Math.max(0, Math.round((simdi - t) / 1000));
  if (sn < 60) return "az önce";
  const dk = Math.floor(sn / 60);
  if (dk < 60) return `${dk} dk önce`;
  const sa = Math.floor(dk / 60);
  if (sa < 24) return `${sa} sa önce`;
  return `${Math.floor(sa / 24)} gün önce`;
}

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

function AlintiModali({ kaynak, kapat }: { kaynak: CevapKaynagiOgesi; kapat: () => void }) {
  const baslikId = useId();
  return (
    <div className="asistan-modal-arka" onClick={kapat}>
      <div
        className="asistan-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={baslikId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            kapat();
          }
        }}
      >
        <div className="asistan-modal-baslik">
          <h3 id={baslikId}>{kaynakEtiketi(kaynak)}</h3>
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={kapat} autoFocus>
            Kapat
          </button>
        </div>
        {kaynak.dogrulandi === false && <p className="asistan-dogrulanmadi">Bu alıntı kaynakta doğrulanamadı.</p>}
        <pre className="kod-blok">
          <code>{kaynak.alinti || "(alıntı yok)"}</code>
        </pre>
        {kaynak.jira?.url && <DisBaglanti href={kaynak.jira.url}>Jira'da aç</DisBaglanti>}
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
              {k.tur === "jira" && k.jira?.url && <DisBaglanti href={k.jira.url}>Jira'da aç</DisBaglanti>}
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
  /** "Bugün kalan soru hakkı ≈ N" (son kartta). */
  kalanSoru?: number | null;
  /** Git bağlantısına basılınca (mobilde panel kapanır). */
  onGit?: () => void;
}

export function CevapKarti({ mesaj, baslik, derinIncelenebilir, derinIncele, derinCalisiyor, geriBildir, kalanSoru, onGit }: CevapKartiOzellikleri) {
  const c = mesaj.cevap;
  if (!c) return null;
  const guven = c.guven_gosterimi ?? null;
  const ornek = c.ornek_veri === true || mockZorunlu();
  const yonlendirmeler = (c.yonlendirmeler ?? []).filter((y) => uygulamaRotasiMi(y.rota));
  const kaynakJiraAnahtarlari = new Set((c.kaynaklar ?? []).filter((k) => k.tur === "jira" && k.jira?.url).map((k) => k.jira!.anahtar));
  const jiraBaglantilari = (c.jira_baglantilari ?? []).filter((j) => !kaynakJiraAnahtarlari.has(j.anahtar));
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
        {mesaj.kaynak && KAYNAK_NOTU[mesaj.kaynak] && <span className="soluk kucuk">{KAYNAK_NOTU[mesaj.kaynak]}</span>}
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
                <AiOneriKarti oneri={o} onGit={onGit} />
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
      <p className="asistan-bilgi-amacli soluk kucuk">Bilgi amaçlıdır; kararı ilgili ekranda verin.</p>
      <div className="asistan-cevap-alt">
        {derinIncelenebilir && derinIncele && (
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={derinIncele} disabled={derinCalisiyor}>
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
              👍
            </button>
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              aria-label="Faydasız"
              aria-pressed={mesaj.geri_bildirim === -1}
              onClick={() => geriBildir(-1)}
            >
              👎
            </button>
          </span>
        )}
        <span className="soluk kucuk">Maliyet: {olculmedi ? "ölçülmedi" : `≈ ${dolar(maliyet!)}`}</span>
        {kalanSoru != null && <span className="soluk kucuk">Bugün kalan soru hakkı ≈ {kalanSoru}</span>}
      </div>
    </article>
  );
}

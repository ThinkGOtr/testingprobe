// 012 Ş7 — karar tablosu ve ilişki kartlarının ortak parçaları: durum çipleri, sunucu doğrulama
// hatalarının alanlara dağıtımı, durum geçişi düğmeleri (ANALIZ §4.1 makinesi).
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../../api/http";
import type { KaliteGecisGirdisi, KaliteGecisi, KararTablosu, MetamorfikIliski } from "../../api/types";
import { useKisiAdi } from "../../auth";
import { useIslem } from "../../hooks";
import { KARAR_TABLOSU_DURUMU } from "../../lib/etiketler";
import { kisaHash, tarih } from "../../lib/format";
import { AlanHatasi, Cip, IslemDugmesi, ReplayRozeti, Uyari } from "../ui";
import "./kalite.css";

type Kayit = KararTablosu | MetamorfikIliski;

/** Durum çipi + AI taslağı işareti (mor = AI) + bayat uyarısı + kabul kriteri atıfları. */
export function KayitCipleri({ k }: { k: Kayit }) {
  const d = KARAR_TABLOSU_DURUMU[k.durum];
  return (
    <div className="kt-ust">
      <Cip ton={d.ton}>{d.etiket}</Cip>
      {k.ai_generated && (
        <Cip ton="vurgu" title="Model kabul kriterinden çıkardı; analist düzenler, PO onaylar.">
          AI taslağı
        </Cip>
      )}
      <ReplayRozeti mode={k.uretim_modu} />
      {k.bayat && (
        <Cip ton="uyari" title="Gereksinim onaydan sonra değişti; kontrolde kullanılmaz.">
          Bayat
        </Cip>
      )}
      {k.icerik.ac_refs.map((a) => (
        <span key={a} className="mono ac-ref">
          {a}
        </span>
      ))}
    </div>
  );
}

/** Onay bilgisi (yalnız PO onayından sonra), bayat ve "değişiklik istendi" notları. */
export function KayitNotlari({ k, ad }: { k: Kayit; ad: "Tablo" | "İlişki" }) {
  const kisiAdi = useKisiAdi();
  return (
    <>
      {k.durum === "approved" && (
        <p className="kucuk kt-onay" data-testid="kt-onay">
          <strong>PO onayı:</strong> {k.onaylayan ? kisiAdi(k.onaylayan) : "onaylayan bildirilmedi"}
          {k.onay_zamani && `, ${tarih(k.onay_zamani)}`}
          {k.onaylanan_hash && <span className="mono soluk"> · {kisaHash(k.onaylanan_hash)}</span>}
        </p>
      )}
      {k.bayat && (
        <Uyari baslik={`${ad} bayat`}>
          Gereksinim bu onaydan sonra değişti. {ad} beklenen sonuç kontrolünde kullanılmaz; yeniden açıp gözden geçirin ve PO onayına gönderin.
        </Uyari>
      )}
      {k.durum === "draft" && k.son_karar?.karar === "request_changes" && (
        <Uyari baslik="PO değişiklik istedi">
          {k.son_karar.gerekce ?? "Gerekçe bildirilmedi."}
          <span className="soluk kucuk">
            {k.son_karar.kullanici && ` · ${kisiAdi(k.son_karar.kullanici)}`}
            {k.son_karar.zaman && `, ${tarih(k.son_karar.zaman)}`}
          </span>
        </Uyari>
      )}
    </>
  );
}

export interface AlanHatalari {
  /** Alan yolu (`satirlar[0].kosul`) → mesajlar. */
  alan: Record<string, string[]>;
  /** Yolu olmayan ya da ekranda karşılığı bulunmayan mesajlar. */
  genel: string[];
}

const YOL = /^([A-Za-z_]+(?:\[\d+\])?(?:\.[^\s:.]+)*):\s*(.+)$/;

/**
 * 422 doğrulama hatasını alanlara dağıtır. Sunucu mesajları `"<alan yolu>: <mesaj>"` biçimindedir
 * (`ApiError.hatalar`; liste yoksa `detail` "; " ile bölünür). Yolu tanınmayan mesaj genel listeye düşer.
 */
export function alanHatalari(e: unknown): AlanHatalari | null {
  if (!(e instanceof ApiError) || e.status !== 422) return null;
  const mesajlar = e.hatalar?.length ? e.hatalar : e.detail.split(/;\s+|\n/).filter(Boolean);
  const s: AlanHatalari = { alan: {}, genel: [] };
  for (const m of mesajlar) {
    const p = YOL.exec(m);
    if (p) (s.alan[p[1]] ??= []).push(p[2]);
    else s.genel.push(m);
  }
  return s;
}

/** Alanın hata bağları (`aria-invalid`, `aria-describedby`) ve yanındaki mesaj. `onek`: formun `useId` değeri. */
export function alanBagi(hatalar: AlanHatalari | null, yol: string, onek: string) {
  const mesajlar = hatalar?.alan[yol];
  const id = `${onek}-hata-${yol.replace(/[^A-Za-z0-9]+/g, "-")}`;
  return {
    oz: mesajlar ? ({ "aria-invalid": true, "aria-describedby": id } as const) : {},
    mesaj: mesajlar ? (
      <span id={id} className="alan-hata" data-testid="alan-hatasi">
        {mesajlar.join(" · ")}
      </span>
    ) : null,
  };
}

/** Ekranda bir alana bağlanmamış sunucu mesajları (yolu `gorulen` içinde olmayanlar + genel). */
export function GenelHatalar({ hatalar, gorulen }: { hatalar: AlanHatalari | null; gorulen: ReadonlySet<string> }) {
  if (!hatalar) return null;
  const kalan = [...hatalar.genel, ...Object.entries(hatalar.alan).flatMap(([yol, m]) => (gorulen.has(yol) ? [] : m.map((x) => `${yol}: ${x}`)))];
  if (kalan.length === 0) return null;
  return (
    <div role="alert" className="alan-hata" data-testid="genel-hatalar">
      <ul className="duz-liste">
        {kalan.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Durum geçişleri: "PO onayına gönder", "Geri çek", "Yeniden aç" (analist); "PO olarak onayla",
 * "Değişiklik iste" + gerekçe (PO). Her istek ekranda görülen `icerik_hash`'i taşır; 409'da liste yenilenir.
 */
export function DurumEylemleri<T extends Kayit>({
  kayit,
  gecis,
  guncellendi,
  yenile,
  engel,
  ek,
}: {
  kayit: T;
  gecis: (g: KaliteGecisi, govde: KaliteGecisGirdisi) => Promise<T>;
  guncellendi: (k: T) => void;
  yenile: () => void;
  /** Geçişleri kapatan görünür neden (ör. kaydedilmemiş düzenleme açık). */
  engel?: string;
  ek?: ReactNode;
}) {
  const islem = useIslem();
  const [istekAcik, setIstekAcik] = useState(false);
  const [gerekce, setGerekce] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  const alan = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    if (istekAcik) alan.current?.focus();
  }, [istekAcik]);
  useEffect(() => setIstekAcik(false), [kayit.durum]);

  async function yap(g: KaliteGecisi, ekGovde: Partial<KaliteGecisGirdisi> = {}) {
    const yeni = await islem.calistir(() => gecis(g, { icerik_hash: kayit.icerik_hash, ...ekGovde }), { cakismada: yenile });
    if (yeni) {
      setGerekce("");
      guncellendi(yeni);
    }
    return yeni;
  }
  function istekGonder(e: FormEvent) {
    e.preventDefault();
    if (!gerekce.trim()) {
      setUyari("Değişiklik isteği için gerekçe yazın.");
      alan.current?.focus();
      return;
    }
    setUyari(null);
    void yap("request-changes", { gerekce: gerekce.trim() });
  }
  const hatalar = alanHatalari(islem.hataNesnesi);
  if (kayit.durum === "superseded") return null;
  const ortak = { kucuk: true, calisiyor: islem.calisiyor, disabled: !!engel, title: engel } as const;
  return (
    <div className="kt-eylemler" data-testid="kt-eylemler">
      <div className="eylemler">
        {kayit.durum === "draft" && (
          <IslemDugmesi roller={["analyst"]} {...ortak} onClick={() => void yap("submit")}>
            PO onayına gönder
          </IslemDugmesi>
        )}
        {kayit.durum === "pending_po" && (
          <>
            <IslemDugmesi roller={["po"]} {...ortak} onClick={() => void yap("approve")}>
              PO olarak onayla
            </IslemDugmesi>
            <IslemDugmesi roller={["po"]} {...ortak} tur="ikincil" aria-expanded={istekAcik} onClick={() => setIstekAcik((a) => !a)}>
              Değişiklik iste
            </IslemDugmesi>
            <IslemDugmesi roller={["analyst"]} {...ortak} tur="ikincil" onClick={() => void yap("withdraw")}>
              Geri çek
            </IslemDugmesi>
          </>
        )}
        {kayit.durum === "approved" && (
          <IslemDugmesi roller={["analyst"]} {...ortak} tur="ikincil" onClick={() => void yap("reopen")}>
            Yeniden aç
          </IslemDugmesi>
        )}
        {ek}
      </div>
      {kayit.durum === "approved" && <p className="soluk kucuk">Yeniden açılan kayıt taslağa döner; yeniden PO onayı gerekir ve o zamana dek kontrolde kullanılmaz.</p>}
      {istekAcik && kayit.durum === "pending_po" && (
        <form className="ret-formu" onSubmit={istekGonder} noValidate>
          <div className="alan kt-alan-genis">
            <label htmlFor={`${id}-gerekce`}>Değişiklik gerekçesi</label>
            <textarea ref={alan} id={`${id}-gerekce`} rows={2} value={gerekce} aria-required="true" onChange={(e) => setGerekce(e.target.value)} />
          </div>
          {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
          <div className="eylemler">
            <IslemDugmesi roller={["po"]} type="submit" kucuk tur="ikincil" calisiyor={islem.calisiyor}>
              Değişiklik isteğini gönder
            </IslemDugmesi>
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setIstekAcik(false)}>
              Vazgeç
            </button>
          </div>
        </form>
      )}
      {islem.hata &&
        (hatalar ? (
          <div role="alert" className="alan-hata" data-testid="gecis-hatalari">
            <p>Gönderilemedi: içerik geçerli değil.</p>
            <ul className="duz-liste">
              {[...hatalar.genel, ...Object.entries(hatalar.alan).flatMap(([yol, m]) => m.map((x) => `${yol}: ${x}`))].map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </div>
        ) : (
          <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>
        ))}
    </div>
  );
}

/**
 * Kabul kriteri atıfları: gereksinimin AC'leri onay kutusu; gereksinimde olmayan mevcut atıf da
 * listede kalır (sunucu 422 ile bildirir, sessizce silinmez).
 */
export function AcSecici({
  secili,
  degisti,
  kriterler,
  hata,
}: {
  secili: string[];
  degisti: (refs: string[]) => void;
  kriterler: { ref: string; metin: string }[];
  hata?: ReactNode;
}) {
  const id = useId();
  const tumu = [...kriterler.map((k) => k.ref), ...secili.filter((r) => !kriterler.some((k) => k.ref === r))];
  return (
    <fieldset className="kt-ac" aria-describedby={hata ? `${id}-hata` : undefined}>
      <legend>Kabul kriterleri</legend>
      {tumu.length === 0 && <p className="soluk kucuk">Gereksinimde kabul kriteri yok.</p>}
      <div className="kt-ac-liste">
        {tumu.map((ref) => {
          const k = kriterler.find((x) => x.ref === ref);
          return (
            <label key={ref} className="kt-ac-secenek" title={k?.metin}>
              <input
                type="checkbox"
                checked={secili.includes(ref)}
                onChange={(e) => degisti(e.target.checked ? [...secili, ref] : secili.filter((r) => r !== ref))}
              />
              <span className="mono">{ref}</span>
              {!k && <span className="soluk kucuk">(gereksinimde yok)</span>}
            </label>
          );
        })}
      </div>
      {hata && <div id={`${id}-hata`}>{hata}</div>}
    </fieldset>
  );
}

/** Liste düzenleme yardımcıları (sıra değiştirme / kaldırma); odak çağıranın işidir. */
export function tasi<T>(liste: T[], i: number, yon: -1 | 1): T[] {
  const j = i + yon;
  if (j < 0 || j >= liste.length) return liste;
  const yeni = [...liste];
  [yeni[i], yeni[j]] = [yeni[j], yeni[i]];
  return yeni;
}

/** Bir sonraki çizimde kimliği verilen öğeye odak (eklenen satırın ilk alanı, silinende "ekle" düğmesi). */
export function odakla(id: string) {
  requestAnimationFrame(() => document.getElementById(id)?.focus());
}

/** Sıra düğmeleri: yukarı / aşağı / kaldır (erişilebilir adlar konumla). */
export function SiraDugmeleri({
  ad,
  i,
  n,
  tasi: tasiFn,
  kaldir,
}: {
  ad: string;
  i: number;
  n: number;
  tasi: (yon: -1 | 1) => void;
  kaldir: () => void;
}) {
  return (
    <span className="kt-sira">
      {/* Uçtaki öğede ilgili yön düğmesi çizilmez (nedensiz pasif düğme bırakılmaz). */}
      {i > 0 && (
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-label={`${ad} yukarı taşı`} onClick={() => tasiFn(-1)}>
          ↑
        </button>
      )}
      {i < n - 1 && (
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-label={`${ad} aşağı taşı`} onClick={() => tasiFn(1)}>
          ↓
        </button>
      )}
      <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-label={`${ad} kaldır`} onClick={kaldir}>
        Kaldır
      </button>
    </span>
  );
}

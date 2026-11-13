// 012 Ş7 — karar tablosu ve ilişki kartlarının ortak parçaları: durum çipleri, sunucu doğrulama
// hatalarının alanlara dağıtımı, durum geçişi düğmeleri (ANALIZ §4.1 makinesi).
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../../api/http";
import { Link } from "react-router-dom";
import type { KaliteGecisGirdisi, KaliteGecisi, KaliteSonKarar, KararTablosu, MetamorfikIliski } from "../../api/types";
import { useKisiAdi } from "../../auth";
import { useIslem } from "../../hooks";
import { KARAR_TABLOSU_DURUMU } from "../../lib/etiketler";
import { kisaHash, tarih } from "../../lib/format";
import { AlanHatasi, Cip, IslemDugmesi, ReplayRozeti, Uyari } from "../ui";
import "./kalite.css";

type Kayit = KararTablosu | MetamorfikIliski;

/** Başarılı durum geçişinin ekran okuyucu duyurusu (ve görünür satırı). */
const GECIS_DUYURUSU: Record<KaliteGecisi, string> = {
  submit: "PO onayına gönderildi.",
  withdraw: "Geri çekildi; kayıt taslağa döndü.",
  reopen: "Yeniden açıldı; kayıt taslağa döndü ve yeniden PO onayı gerekir.",
  approve: "PO olarak onaylandı.",
  "request-changes": "Değişiklik istendi; kayıt analiste taslak olarak döndü.",
};

/** Durum çipi + AI taslağı işareti (mor = AI) + bayat uyarısı + kabul kriteri atıfları. */
export function KayitCipleri({ k }: { k: Kayit }) {
  const d = KARAR_TABLOSU_DURUMU[k.durum];
  return (
    <div className="kt-ust">
      <Cip ton={d.ton}>{d.etiket}</Cip>
      {/* Mor yalnız insan kapısından geçmemiş AI taslağında; PO'ya giden / onaylanan kayıtta köken nötr yazılır. */}
      {k.ai_generated &&
        (k.durum === "draft" ? (
          <Cip ton="vurgu" title="Model kabul kriterinden çıkardı; analist düzenler, PO onaylar.">
            AI taslağı
          </Cip>
        ) : (
          <Cip ton="notr" title="İlk taslağı model çıkardı; analist düzenledi ve PO onayına gönderdi.">
            AI kökenli
          </Cip>
        ))}
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

const GECMIS_EYLEMI: Record<string, string> = {
  submit: "PO onayına gönderdi",
  withdraw: "Geri çekti",
  reopen: "Yeniden açtı",
  approve: "PO olarak onayladı",
  request_changes: "Değişiklik istedi",
  duzenle: "İçeriği düzenledi",
};

/** u2 N5: kaydın geçiş geçmişi (gerekçeler ve "Tablo yanlış" bildirimleri dahil); çekirdek vermezse çizilmez. */
export function KayitGecmisi({ k }: { k: Kayit }) {
  const kisiAdi = useKisiAdi();
  if (!k.gecmis?.length) return null;
  return (
    <details className="kt-gecmis" data-testid="kt-gecmis">
      <summary className="kucuk">Geçmiş ({k.gecmis.length})</summary>
      <ol className="duz-liste kucuk">
        {[...k.gecmis].reverse().map((g, i) => (
          <li key={`${g.zaman ?? ""}-${i}`}>
            <span className="soluk">{g.zaman ? tarih(g.zaman) : "zaman bildirilmedi"}</span> · {g.kullanici ? kisiAdi(g.kullanici) : "kişi bildirilmedi"}:{" "}
            {GECMIS_EYLEMI[g.karar] ?? g.karar}
            {g.karar === "reopen" && g.case_id && " (Tablo yanlış bildirimi)"}
            {g.gerekce && <> — “{g.gerekce}”</>}
            {g.icerik_hash && <span className="mono soluk"> · {kisaHash(g.icerik_hash)}</span>}
          </li>
        ))}
      </ol>
    </details>
  );
}

/** u2 N5: "Tablo yanlış" yoluyla yeniden açılma notu — PO, tablo yeniden gelince nedenini görür. */
function TabloYanlisNotu({ k, karar }: { k: Kayit; karar: KaliteSonKarar }) {
  const kisiAdi = useKisiAdi();
  return (
    <div data-testid="kt-tablo-yanlis-notu">
      <Uyari baslik="Tablo yanlış bildirildi (case incelemesinden yeniden açıldı)">
        “{karar.gerekce}”
        <span className="soluk kucuk">
          {karar.kullanici && ` · ${kisiAdi(karar.kullanici)}`}
          {karar.zaman && `, ${tarih(karar.zaman)}`}
        </span>
        {karar.case_id && (
          <>
            {" "}
            <Link className="kucuk" to={`/gereksinimler/${encodeURIComponent(k.requirement_id)}/caseler#case-${encodeURIComponent(karar.case_id)}`}>
              Bildiren case'i aç
            </Link>
          </>
        )}
      </Uyari>
    </div>
  );
}

/** Onay bilgisi (yalnız PO onayından sonra), bayat ve "değişiklik istendi" notları. */
export function KayitNotlari({ k, ad }: { k: Kayit; ad: "Tablo" | "İlişki" }) {
  const kisiAdi = useKisiAdi();
  return (
    <>
      {k.son_duzenleyen && (
        <p className="soluk kucuk" data-testid="kt-son-duzenleyen">
          Son düzenleyen: {kisiAdi(k.son_duzenleyen)}
          {k.guncelleme && `, ${tarih(k.guncelleme)}`}
        </p>
      )}
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
      {(k.durum === "draft" || k.durum === "pending_po") && k.son_karar?.karar === "reopen" && k.son_karar.gerekce && <TabloYanlisNotu k={k} karar={k.son_karar} />}
      {k.durum === "draft" && k.son_karar?.karar === "request_changes" && (
        <Uyari baslik="PO değişiklik istedi">
          {k.son_karar.gerekce ?? "Gerekçe bildirilmedi."}
          <span className="soluk kucuk">
            {k.son_karar.kullanici && ` · ${kisiAdi(k.son_karar.kullanici)}`}
            {k.son_karar.zaman && `, ${tarih(k.son_karar.zaman)}`}
          </span>
        </Uyari>
      )}
      <KayitGecmisi k={k} />
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
  const [onayNotu, setOnayNotu] = useState("");
  const [duyuru, setDuyuru] = useState("");
  const id = useId();
  const alan = useRef<HTMLTextAreaElement | null>(null);
  const istekDugmesi = useRef<HTMLSpanElement | null>(null);
  const durumSatiri = useRef<HTMLParagraphElement | null>(null);
  // PO'nun gözden geçirdiği içerik: kart PO onayı beklerken ilk görülen hash sabitlenir. Sessiz yenileme
  // içeriği değiştirirse onay o anki hash'le gönderilmez; uyarı gösterilir ve yeniden gözden geçirme istenir.
  const [gorulenHash, setGorulenHash] = useState<string | null>(kayit.durum === "pending_po" ? kayit.icerik_hash : null);
  // u2 N9: sabitlenen hash'in içeriği — değişince PO neyin değiştiğini satır satır görür.
  const [gorulenIcerik, setGorulenIcerik] = useState<unknown>(kayit.durum === "pending_po" ? kayit.icerik : null);
  useEffect(() => {
    if (kayit.durum !== "pending_po") {
      setGorulenHash(null);
      setGorulenIcerik(null);
    } else {
      setGorulenHash((h) => h ?? kayit.icerik_hash);
      setGorulenIcerik((i: unknown) => i ?? kayit.icerik);
    }
  }, [kayit.durum, kayit.icerik_hash, kayit.icerik]);
  const icerikDegisti = kayit.durum === "pending_po" && gorulenHash !== null && gorulenHash !== kayit.icerik_hash;
  useEffect(() => {
    if (istekAcik) alan.current?.focus();
  }, [istekAcik]);
  useEffect(() => setIstekAcik(false), [kayit.durum]);

  async function yap(g: KaliteGecisi, ekGovde: Partial<KaliteGecisGirdisi> = {}) {
    const yeni = await islem.calistir(() => gecis(g, { icerik_hash: gorulenHash ?? kayit.icerik_hash, ...ekGovde }), { cakismada: yenile });
    if (yeni) {
      setGerekce("");
      setOnayNotu("");
      guncellendi(yeni);
      // Durum geçişinden sonra odak kaybolmasın: duyuru satırına odak + role="status".
      setDuyuru(GECIS_DUYURUSU[g]);
      requestAnimationFrame(() => durumSatiri.current?.focus());
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
  const kapanisOdagi = () => requestAnimationFrame(() => istekDugmesi.current?.querySelector("button")?.focus());
  return (
    <div className="kt-eylemler" data-testid="kt-eylemler">
      <p ref={durumSatiri} tabIndex={-1} role="status" className="kucuk kt-duyuru" data-testid="kt-duyuru">
        {duyuru}
      </p>
      {icerikDegisti && (
        <div data-testid="kt-icerik-degisti">
          <Uyari baslik="İçerik siz bakarken değişti — yeniden gözden geçirin">
            Analist bu kaydı siz incelerken değiştirdi. Onay, gördüğünüz eski içerik için gönderilmez.
            <IcerikFarki eski={gorulenIcerik} yeni={kayit.icerik} />
            <button
              type="button"
              className="dugme dugme-ikincil dugme-kucuk"
              onClick={() => {
                setGorulenHash(kayit.icerik_hash);
                setGorulenIcerik(kayit.icerik);
                setDuyuru("Güncel içerik gözden geçirildi olarak işaretlendi.");
              }}
            >
              Güncel içeriği gözden geçirdim
            </button>
          </Uyari>
        </div>
      )}
      {kayit.durum === "pending_po" && (
        <div className="alan kt-alan-genis kt-onay-notu">
          <label htmlFor={`${id}-onay-notu`}>PO onay notu (isteğe bağlı)</label>
          <input id={`${id}-onay-notu`} value={onayNotu} maxLength={500} onChange={(e) => setOnayNotu(e.target.value)} />
        </div>
      )}
      <div className="eylemler">
        {kayit.durum === "draft" && (
          <IslemDugmesi izin="decision_table.edit" {...ortak} onClick={() => void yap("submit")}>
            PO onayına gönder
          </IslemDugmesi>
        )}
        {kayit.durum === "pending_po" && (
          <>
            <IslemDugmesi
              izin="decision_table.approve"
              {...ortak}
              disabled={!!engel || icerikDegisti}
              title={engel ?? (icerikDegisti ? "İçerik siz bakarken değişti; önce güncel içeriği gözden geçirin." : undefined)}
              onClick={() => void yap("approve", onayNotu.trim() ? { gerekce: onayNotu.trim() } : {})}
            >
              PO olarak onayla
            </IslemDugmesi>
            <span ref={istekDugmesi} className="satir-ogeler">
              <IslemDugmesi izin="decision_table.approve" {...ortak} tur="ikincil" aria-expanded={istekAcik} onClick={() => setIstekAcik((a) => !a)}>
                Değişiklik iste
              </IslemDugmesi>
            </span>
            <IslemDugmesi izin="decision_table.edit" {...ortak} tur="ikincil" onClick={() => void yap("withdraw")}>
              Geri çek
            </IslemDugmesi>
          </>
        )}
        {kayit.durum === "approved" && (
          <IslemDugmesi izin="decision_table.edit" {...ortak} tur="ikincil" onClick={() => void yap("reopen")}>
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
            <IslemDugmesi izin="decision_table.approve" type="submit" kucuk tur="ikincil" calisiyor={islem.calisiyor}>
              Değişiklik isteğini gönder
            </IslemDugmesi>
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              onClick={() => {
                setIstekAcik(false);
                kapanisOdagi();
              }}
            >
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
  /** `null`: gereksinim okunamadı (kabul kriterleri bilinmiyor; düzenleme kapalı). */
  kriterler: { ref: string; metin: string }[] | null;
  hata?: ReactNode;
}) {
  const id = useId();
  const liste = kriterler ?? [];
  const tumu = [...liste.map((k) => k.ref), ...secili.filter((r) => !liste.some((k) => k.ref === r))];
  return (
    <fieldset className="kt-ac" aria-describedby={hata ? `${id}-hata` : undefined}>
      <legend>Kabul kriterleri</legend>
      {kriterler === null ? (
        <p className="soluk kucuk">Gereksinim okunamadı; kabul kriterleri bilinmiyor.</p>
      ) : (
        tumu.length === 0 && <p className="soluk kucuk">Gereksinimde kabul kriteri yok.</p>
      )}
      <div className="kt-ac-liste">
        {tumu.map((ref) => {
          const k = liste.find((x) => x.ref === ref);
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

// ------------------------------------------------------------------ içerik farkı (u2 N9)

type Duz = Record<string, string>;

/** İçeriği okunur yollara açar: dizi öğeleri `id`/`ad` ile anahtarlanır ("Satır R2 · koşul", "Çıktı indirim · tolerans"). */
export function icerigiDuzlestir(x: unknown, onek = "", cikti: Duz = {}): Duz {
  const ADLAR: Record<string, string> = {
    satirlar: "Satır",
    girdiler: "Girdi",
    ciktilar: "Çıktı",
    kosul: "koşul",
    cikti: "çıktı",
    ad: "ad",
    tur: "tür",
    birim: "birim",
    tolerans: "tolerans",
    aciklama: "açıklama",
    ac_refs: "kabul kriterleri",
    on_kosul: "ön koşul",
    donusum: "dönüşüm",
    iliski: "ilişki",
    degismez: "değişmez",
    tablo_ref: "tablo",
  };
  if (Array.isArray(x)) {
    if (x.every((o) => typeof o !== "object" || o === null)) {
      cikti[onek] = x.join(", ");
      return cikti;
    }
    x.forEach((o, i) => {
      const r = o as Record<string, unknown>;
      const anahtar = typeof r.id === "string" ? r.id : typeof r.ad === "string" ? r.ad : String(i + 1);
      const { id: _id, ...kalan } = r;
      void _id;
      icerigiDuzlestir(kalan, `${onek} ${anahtar}`, cikti);
    });
    return cikti;
  }
  if (x && typeof x === "object") {
    for (const [k, v] of Object.entries(x as Record<string, unknown>)) {
      const ad = ADLAR[k] ?? k;
      icerigiDuzlestir(v, onek ? (Array.isArray(v) && ad[0] === ad[0].toUpperCase() ? ad : `${onek} · ${ad}`) : ad, cikti);
    }
    return cikti;
  }
  cikti[onek] = x === null || x === undefined ? "" : String(x);
  return cikti;
}

/** Görülen ve güncel içerik arasındaki fark satırları. */
export function icerikFarklari(eski: unknown, yeni: unknown): { yol: string; once: string | null; sonra: string | null }[] {
  const a = icerigiDuzlestir(eski);
  const b = icerigiDuzlestir(yeni);
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .filter((k) => a[k] !== b[k])
    .map((k) => ({ yol: k, once: k in a ? a[k] : null, sonra: k in b ? b[k] : null }));
}

export function IcerikFarki({ eski, yeni }: { eski: unknown; yeni: unknown }) {
  if (!eski) return null;
  const f = icerikFarklari(eski, yeni);
  if (f.length === 0) return null;
  return (
    <ul className="duz-liste kt-fark" data-testid="kt-icerik-farki" aria-label="Gördüğünüz içerikten bu yana değişenler">
      {f.map((x) => (
        <li key={x.yol} className="kucuk">
          <strong>{x.yol}:</strong> {x.once !== null ? <del className="mono">{x.once || "(boş)"}</del> : <span className="soluk">(yoktu)</span>} →{" "}
          {x.sonra !== null ? <ins className="mono">{x.sonra || "(boş)"}</ins> : <span className="soluk">(kaldırıldı)</span>}
        </li>
      ))}
    </ul>
  );
}

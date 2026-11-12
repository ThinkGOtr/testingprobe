// 012 Ş7 — metamorfik ilişki kartı (ANALIZ §4.5): görünüm, düzenleyici (analist, yalnız taslak) ve
// tabloyla aynı durum geçişleri. `donusum` yeni girdileri, `iliski` yeni beklenen çıktıları kaynak
// case'in değerlerinden hesaplar.
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { kararCakismasi } from "../../api/http";
import type { KararTablosu, MetamorfikIliski, MetamorfikIliskiIcerik } from "../../api/types";
import { useIslem } from "../../hooks";
import { AlanHatasi, IslemDugmesi } from "../ui";
import { tabloCapasi } from "./KararTablosuKarti";
import { AcSecici, alanBagi, alanHatalari, DurumEylemleri, GenelHatalar, KayitCipleri, KayitNotlari, odakla } from "./ortak";

export const iliskiCapasi = (id: string) => `iliski-${id}`;

function iliskiSinifi(r: MetamorfikIliski): string {
  const s = ["iliski"];
  if (r.durum === "approved" && !r.bayat) s.push("iliski-onayli");
  else if (r.durum === "pending_po") s.push("iliski-bekliyor");
  else if (r.ai_generated) s.push("iliski-ai");
  return s.join(" ");
}

function IfadeListesi({ esleme, ok }: { esleme: Record<string, string>; ok: string }) {
  const girdiler = Object.entries(esleme);
  if (girdiler.length === 0) return <span className="soluk">—</span>;
  return (
    <ul className="duz-liste">
      {girdiler.map(([ad, ifade]) => (
        <li key={ad} className="kt-ifade">
          {ad} {ok} {ifade}
        </li>
      ))}
    </ul>
  );
}

export function IliskiKarti({
  iliski,
  tablolar,
  kriterler,
  guncellendi,
  yenile,
}: {
  iliski: MetamorfikIliski;
  tablolar: KararTablosu[];
  kriterler: { ref: string; metin: string }[];
  guncellendi: (r: MetamorfikIliski) => void;
  yenile: () => void;
}) {
  const [duzenle, setDuzenle] = useState(false);
  const r = iliski.icerik;
  const taslak = iliski.durum === "draft";
  const bagliTablo = tablolar.find((t) => t.id === iliski.karar_tablosu_id);
  const baslikId = useId();
  const duzenleId = `${iliskiCapasi(iliski.id)}-duzenle`;
  const kapat = () => {
    setDuzenle(false);
    requestAnimationFrame(() => document.getElementById(duzenleId)?.focus());
  };
  return (
    <article id={iliskiCapasi(iliski.id)} className={iliskiSinifi(iliski)} aria-labelledby={baslikId} data-testid="iliski-kart">
      <KayitCipleri k={iliski} />
      <h3 id={baslikId}>
        <span className="mono soluk">İ{iliski.sira_no}</span> · {r.ad || "Adsız ilişki"}
      </h3>
      <KayitNotlari k={iliski} ad="İlişki" />
      {duzenle && taslak ? (
        <IliskiDuzenleyici
          requirementId={iliski.requirement_id}
          iliski={iliski}
          tablolar={tablolar}
          kriterler={kriterler}
          yenile={yenile}
          vazgec={kapat}
          kaydedildi={(y) => {
            guncellendi(y);
            kapat();
          }}
        />
      ) : (
        <dl className="iliski-tanim">
          <dt>Tablo</dt>
          <dd>
            {bagliTablo ? (
              <a href={`#${tabloCapasi(bagliTablo.id)}`}>
                T{bagliTablo.sira_no} · {bagliTablo.icerik.ad}
              </a>
            ) : (
              (r.tablo_ref ?? <span className="soluk">bağlı tablo yok</span>)
            )}
          </dd>
          <dt>Ön koşul</dt>
          <dd className="kt-ifade">{r.on_kosul || "—"}</dd>
          <dt>Dönüşüm</dt>
          <dd>
            <IfadeListesi esleme={r.donusum} ok="←" />
          </dd>
          <dt>İlişki</dt>
          <dd>
            <IfadeListesi esleme={r.iliski} ok="←" />
          </dd>
          {r.aciklama && (
            <>
              <dt>Açıklama</dt>
              <dd>{r.aciklama}</dd>
            </>
          )}
        </dl>
      )}
      {iliski.durum !== "superseded" && (
        <DurumEylemleri
          kayit={iliski}
          gecis={(g, govde) => api.iliskiGecis(iliski.id, g, govde)}
          guncellendi={guncellendi}
          yenile={yenile}
          engel={duzenle && taslak ? "Önce düzenlemeyi kaydedin ya da vazgeçin." : undefined}
          ek={
            taslak && !duzenle ? (
              <IslemDugmesi id={duzenleId} roller={["analyst"]} kucuk tur="ikincil" onClick={() => setDuzenle(true)}>
                Düzenle
              </IslemDugmesi>
            ) : null
          }
        />
      )}
    </article>
  );
}

interface Cift {
  anahtar: number;
  ad: string;
  ifade: string;
}
let sayac = 0;
const ciftler = (e: Record<string, string>): Cift[] => Object.entries(e).map(([ad, ifade]) => ({ anahtar: ++sayac, ad, ifade }));
const eslemeYap = (c: Cift[]) => Object.fromEntries(c.filter((x) => x.ad.trim()).map((x) => [x.ad.trim(), x.ifade.trim()]));

const BOS_ILISKI: MetamorfikIliskiIcerik = { ad: "", ac_refs: [], tablo_ref: null, on_kosul: "dogru", donusum: {}, iliski: {} };

/** İlişki düzenleyici; `iliski` verilmezse yeni ilişki oluşturur (`POST /requirements/{id}/relations`). */
export function IliskiDuzenleyici({
  requirementId,
  iliski,
  tablolar,
  kriterler,
  kaydedildi,
  vazgec,
  yenile,
}: {
  requirementId: string;
  iliski?: MetamorfikIliski;
  tablolar: KararTablosu[];
  kriterler: { ref: string; metin: string }[];
  kaydedildi: (r: MetamorfikIliski) => void;
  vazgec: () => void;
  yenile: () => void;
}) {
  const ilk = iliski?.icerik ?? BOS_ILISKI;
  const [ad, setAd] = useState(ilk.ad);
  const [aciklama, setAciklama] = useState(ilk.aciklama ?? "");
  const [acRefs, setAcRefs] = useState(ilk.ac_refs);
  /** Yetkili bağ tablo kimliğidir (`karar_tablosu_id`); `tablo_ref` yalnız bilgi. */
  const [tabloId, setTabloId] = useState(iliski?.karar_tablosu_id ?? "");
  const [onKosul, setOnKosul] = useState(ilk.on_kosul);
  const [donusum, setDonusum] = useState(() => ciftler(ilk.donusum));
  const [iliskiler, setIliskiler] = useState(() => ciftler(ilk.iliski));
  const [taban, setTaban] = useState(iliski?.icerik_hash ?? "");
  const islem = useIslem();
  const id = useId();
  const ilkAlan = useRef<HTMLInputElement | null>(null);
  useEffect(() => ilkAlan.current?.focus(), []);
  const hatalar = alanHatalari(islem.hataNesnesi);
  const gorulen = new Set<string>();
  const bag = (yol: string) => {
    gorulen.add(yol);
    return alanBagi(hatalar, yol, id);
  };
  const etkin = tablolar.filter((t) => t.durum !== "superseded");
  const secilenTablo = etkin.find((t) => t.id === tabloId);

  async function kaydet(e: FormEvent) {
    e.preventDefault();
    const icerik: MetamorfikIliskiIcerik = {
      ad: ad.trim(),
      ac_refs: acRefs,
      tablo_ref: secilenTablo ? `T${secilenTablo.sira_no}` : null,
      on_kosul: onKosul.trim(),
      donusum: eslemeYap(donusum),
      iliski: eslemeYap(iliskiler),
      ...(aciklama.trim() ? { aciklama: aciklama.trim() } : {}),
    };
    const karar_tablosu_id = tabloId || null;
    const y = await islem.calistir(
      () => (iliski ? api.iliskiKaydet(iliski.id, { icerik, icerik_hash: taban, karar_tablosu_id }) : api.iliskiEkle(requirementId, { icerik, karar_tablosu_id })),
      { cakismada: yenile },
    );
    if (y) kaydedildi(y);
  }

  function ciftAlani(tur: "donusum" | "iliski", liste: Cift[], set: (c: Cift[]) => void) {
    const baslik = tur === "donusum" ? "Dönüşüm (yeni girdiler)" : "İlişki (yeni beklenen çıktılar)";
    const adEtiketi = tur === "donusum" ? "Girdi" : "Çıktı";
    const oneriler = secilenTablo ? (tur === "donusum" ? secilenTablo.icerik.girdiler : secilenTablo.icerik.ciktilar).map((k) => k.ad) : [];
    const listeId = `${id}-${tur}-oneriler`;
    const genel = bag(tur);
    return (
      <fieldset className="kt-grup">
        <legend>{baslik}</legend>
        {genel.mesaj}
        {oneriler.length > 0 && (
          <datalist id={listeId}>
            {oneriler.map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
        )}
        {liste.map((c, i) => {
          const b = c.ad.trim() ? bag(`${tur}.${c.ad.trim()}`) : { oz: {}, mesaj: null };
          const alanId = `${id}-${tur}-${c.anahtar}`;
          const guncelle = (ek: Partial<Cift>) => set(liste.map((x, j) => (j === i ? { ...x, ...ek } : x)));
          return (
            <div key={c.anahtar} className="kt-satir" role="group" aria-label={`${adEtiketi} ${i + 1}`}>
              <div className="alan">
                <label htmlFor={`${alanId}-ad`}>{adEtiketi}</label>
                <input id={`${alanId}-ad`} className="mono" list={oneriler.length ? listeId : undefined} value={c.ad} autoComplete="off" spellCheck={false} onChange={(e) => guncelle({ ad: e.target.value })} />
              </div>
              <div className="alan kt-alan-genis">
                <label htmlFor={`${alanId}-ifade`}>İfade</label>
                <input id={`${alanId}-ifade`} className="mono" value={c.ifade} maxLength={300} autoComplete="off" spellCheck={false} {...b.oz} onChange={(e) => guncelle({ ifade: e.target.value })} />
                {b.mesaj}
              </div>
              <div className="kt-satir-bas">
                <span />
                <button
                  type="button"
                  className="dugme dugme-hayalet dugme-kucuk"
                  aria-label={`${adEtiketi} ${i + 1} kaldır`}
                  onClick={() => {
                    set(liste.filter((_, j) => j !== i));
                    odakla(`${id}-${tur}-ekle`);
                  }}
                >
                  Kaldır
                </button>
              </div>
            </div>
          );
        })}
        <button
          type="button"
          id={`${id}-${tur}-ekle`}
          className="dugme dugme-ikincil dugme-kucuk"
          onClick={() => {
            const c = { anahtar: ++sayac, ad: "", ifade: "" };
            set([...liste, c]);
            odakla(`${id}-${tur}-${c.anahtar}-ad`);
          }}
        >
          {adEtiketi} ekle
        </button>
      </fieldset>
    );
  }

  const adBag = bag("ad");
  const acBag = bag("ac_refs");
  const tabloBag = bag("karar_tablosu_id");
  bag("tablo_ref");
  const onBag = bag("on_kosul");
  const aciklamaBag = bag("aciklama");
  const cakisma = kararCakismasi(islem.hataNesnesi);
  const donusumAlani = ciftAlani("donusum", donusum, setDonusum);
  const iliskiAlani = ciftAlani("iliski", iliskiler, setIliskiler);

  return (
    <form className="kt-duzenle" onSubmit={kaydet} noValidate aria-label={iliski ? `${ilk.ad || "İlişki"} düzenleme` : "Yeni ilişki"} data-testid="iliski-duzenleyici">
      <div className="kt-duzenle-ust">
        <div className="alan">
          <label htmlFor={`${id}-ad`}>İlişki adı</label>
          <input ref={ilkAlan} id={`${id}-ad`} value={ad} maxLength={200} {...adBag.oz} onChange={(e) => setAd(e.target.value)} />
          {adBag.mesaj}
        </div>
        <div className="alan">
          <label htmlFor={`${id}-tablo`}>Bağlı tablo</label>
          <select id={`${id}-tablo`} value={tabloId} {...tabloBag.oz} onChange={(e) => setTabloId(e.target.value)}>
            <option value="">Tablosuz</option>
            {etkin.map((t) => (
              <option key={t.id} value={t.id}>
                T{t.sira_no} · {t.icerik.ad}
              </option>
            ))}
            {tabloId && !secilenTablo && <option value={tabloId}>{ilk.tablo_ref ?? tabloId} (bulunamadı)</option>}
          </select>
          {tabloBag.mesaj}
        </div>
      </div>
      <AcSecici secili={acRefs} degisti={setAcRefs} kriterler={kriterler} hata={acBag.mesaj} />
      <div className="alan">
        <label htmlFor={`${id}-on`}>Ön koşul</label>
        <input id={`${id}-on`} className="mono" value={onKosul} maxLength={300} spellCheck={false} autoComplete="off" aria-describedby={`${id}-on-ipucu`} {...onBag.oz} onChange={(e) => setOnKosul(e.target.value)} />
        <span id={`${id}-on-ipucu`} className="soluk kucuk">
          Kaynak case'in girdileri üzerinde değerlendirilir; koşulsuz ilişki için <span className="mono">dogru</span> yazın.
        </span>
        {onBag.mesaj}
      </div>
      {donusumAlani}
      {iliskiAlani}
      <div className="alan">
        <label htmlFor={`${id}-aciklama`}>Açıklama</label>
        <textarea id={`${id}-aciklama`} rows={2} value={aciklama} {...aciklamaBag.oz} onChange={(e) => setAciklama(e.target.value)} />
        {aciklamaBag.mesaj}
      </div>
      <GenelHatalar hatalar={hatalar} gorulen={gorulen} />
      {hatalar && (
        <p role="alert" className="alan-hata" data-testid="kt-kayit-hatasi">
          Kaydedilemedi: {Object.values(hatalar.alan).flat().length + hatalar.genel.length} doğrulama hatası. Mesajlar ilgili alanların yanında.
        </p>
      )}
      {islem.hata && !hatalar && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
      {cakisma && (
        <p className="kucuk">
          Düzenlemeniz duruyor. Kaydetmek için önce güncel içeriği yükleyin (düzenlemeniz silinir) ya da vazgeçin.{" "}
          <button
            type="button"
            className="dugme dugme-ikincil dugme-kucuk"
            onClick={() => {
              if (!iliski) return;
              const g = iliski.icerik;
              setAd(g.ad);
              setAciklama(g.aciklama ?? "");
              setAcRefs(g.ac_refs);
              setTabloId(iliski.karar_tablosu_id ?? "");
              setOnKosul(g.on_kosul);
              setDonusum(ciftler(g.donusum));
              setIliskiler(ciftler(g.iliski));
              setTaban(iliski.icerik_hash);
              islem.temizle();
            }}
          >
            Güncel içeriği yükle
          </button>
        </p>
      )}
      <div className="eylemler">
        <IslemDugmesi roller={["analyst"]} type="submit" calisiyor={islem.calisiyor}>
          {iliski ? "Kaydet" : "İlişkiyi oluştur"}
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** Türetme sonucundaki case bağlantısı: case review sayfası. */
export function CaseBaglantisi({ requirementId, children }: { requirementId: string; children: ReactNode }) {
  return <Link to={`/gereksinimler/${encodeURIComponent(requirementId)}/caseler`}>{children}</Link>;
}

// 012 Ş7 — karar tablosu düzenleyici (analist, yalnız `draft`): ad, açıklama, AC atıfları, girdiler,
// çıktılar, satırlar (koşul + her çıktı için bir ifade); ekle / kaldır / sırala. Sunucunun 422
// `karar_tablosu_gecersiz` mesajları alan yoluyla ilgili alanın yanına yazılır; kayıt ekranda görülen
// `icerik_hash` ile gider (409'da güncel içerik yüklenebilir, düzenleme kendiliğinden ezilmez).
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { kararCakismasi } from "../../api/http";
import type { KararTablosu, KararTablosuIcerik, KolonTuru } from "../../api/types";
import { useIslem } from "../../hooks";
import { KOLON_TURU } from "../../lib/etiketler";
import { AlanHatasi, IslemDugmesi } from "../ui";
import { AcSecici, alanBagi, alanHatalari, GenelHatalar, odakla, SiraDugmeleri, tasi } from "./ortak";

interface Kolon {
  anahtar: number;
  ad: string;
  tur: KolonTuru;
  birim: string;
  aciklama: string;
  tolerans: string;
}

interface Satir {
  anahtar: number;
  id: string;
  kosul: string;
  /** Çıktı kolonlarıyla aynı sırada: `cikti[i]` → `ciktilar[i]`'nin ifadesi (çıktı adı değişse de bağ kalır). */
  cikti: Record<number, string>;
}

interface Taslak {
  ad: string;
  aciklama: string;
  ac_refs: string[];
  girdiler: Kolon[];
  ciktilar: Kolon[];
  satirlar: Satir[];
}

let sayac = 0;
const yeniAnahtar = () => ++sayac;

function taslakYap(i: KararTablosuIcerik): Taslak {
  const ciktilar = i.ciktilar.map((c) => ({ anahtar: yeniAnahtar(), ad: c.ad, tur: c.tur, birim: c.birim ?? "", aciklama: c.aciklama ?? "", tolerans: c.tolerans ?? "" }));
  return {
    ad: i.ad,
    aciklama: i.aciklama ?? "",
    ac_refs: [...i.ac_refs],
    girdiler: i.girdiler.map((g) => ({ anahtar: yeniAnahtar(), ad: g.ad, tur: g.tur, birim: g.birim ?? "", aciklama: g.aciklama ?? "", tolerans: "" })),
    ciktilar,
    satirlar: i.satirlar.map((s) => ({
      anahtar: yeniAnahtar(),
      id: s.id,
      kosul: s.kosul,
      cikti: Object.fromEntries(ciktilar.map((c) => [c.anahtar, s.cikti[c.ad] ?? ""])),
    })),
  };
}

/** Düzenleyicinin içeriği → sözleşme içeriği (`icerik`). Boş isteğe bağlı alanlar gönderilmez. */
export function icerikYap(t: Taslak): KararTablosuIcerik {
  const secmeli = (ad: string, v: string) => (v.trim() ? { [ad]: v.trim() } : {});
  return {
    ad: t.ad.trim(),
    ac_refs: t.ac_refs,
    ...secmeli("aciklama", t.aciklama),
    girdiler: t.girdiler.map((g) => ({ ad: g.ad.trim(), tur: g.tur, ...secmeli("birim", g.birim), ...secmeli("aciklama", g.aciklama) })),
    ciktilar: t.ciktilar.map((c) => ({
      ad: c.ad.trim(),
      tur: c.tur,
      ...secmeli("birim", c.birim),
      ...(c.tur === "sayi" ? secmeli("tolerans", c.tolerans) : {}),
      ...secmeli("aciklama", c.aciklama),
    })),
    satirlar: t.satirlar.map((s) => ({ id: s.id, kosul: s.kosul.trim(), cikti: Object.fromEntries(t.ciktilar.map((c) => [c.ad.trim(), (s.cikti[c.anahtar] ?? "").trim()])) })),
  };
}

/** Sıradaki boş satır kimliği (`R<n>`; şema `^R[0-9]{1,3}$`). */
function yeniSatirId(satirlar: Satir[]): string {
  const n = Math.max(0, ...satirlar.map((s) => Number(/^R(\d+)$/.exec(s.id)?.[1] ?? 0)));
  return `R${n + 1}`;
}

export function TabloDuzenleyici({
  tablo,
  kriterler,
  kaydedildi,
  vazgec,
  yenile,
  degisti,
}: {
  tablo: KararTablosu;
  /** Kaydedilmemiş içerik (ör. "Örnekle dene" onu değerlendirir). */
  degisti?: (icerik: KararTablosuIcerik) => void;
  /** `null`: gereksinim okunamadı (kabul kriterleri bilinmiyor; düzenleme kapalı). */
  kriterler: { ref: string; metin: string }[] | null;
  kaydedildi: (t: KararTablosu) => void;
  vazgec: () => void;
  /** 409: liste yeniden yüklenir (güncel hash ve içerik gelir). */
  yenile: () => void;
}) {
  const [taslak, setTaslak] = useState<Taslak>(() => taslakYap(tablo.icerik));
  /** Düzenleme açılırken görülen hash: kayıt bu hash'le gider; 409'dan sonra kullanıcı güncel içeriği yükler. */
  const [taban, setTaban] = useState(tablo.icerik_hash);
  const islem = useIslem();
  const id = useId();
  const ilkAlan = useRef<HTMLInputElement | null>(null);
  useEffect(() => ilkAlan.current?.focus(), []);
  const degistiRef = useRef(degisti);
  degistiRef.current = degisti;
  useEffect(() => degistiRef.current?.(icerikYap(taslak)), [taslak]);

  const hatalar = alanHatalari(islem.hataNesnesi);
  const cakisma = kararCakismasi(islem.hataNesnesi);
  const gorulen = new Set<string>();
  const bag = (yol: string) => {
    gorulen.add(yol);
    return alanBagi(hatalar, yol, id);
  };
  /** Yapı değişince (ekle/kaldır/sırala) yola bağlı eski mesajlar yanlış alana düşmesin. */
  const yapiDegisti = (t: Taslak) => {
    if (hatalar) islem.temizle();
    setTaslak(t);
  };

  async function kaydet(e: FormEvent) {
    e.preventDefault();
    const yeni = await islem.calistir(() => api.kararTablosuKaydet(tablo.id, { icerik: icerikYap(taslak), icerik_hash: taban }), { cakismada: yenile });
    if (yeni) kaydedildi(yeni);
  }

  function guncelIcerigiYukle() {
    setTaslak(taslakYap(tablo.icerik));
    setTaban(tablo.icerik_hash);
    islem.temizle();
  }

  const kolonGuncelle = (liste: "girdiler" | "ciktilar", i: number, ek: Partial<Kolon>) =>
    setTaslak((t) => ({ ...t, [liste]: t[liste].map((k, j) => (j === i ? { ...k, ...ek } : k)) }));

  function kolonEkle(liste: "girdiler" | "ciktilar") {
    const k: Kolon = { anahtar: yeniAnahtar(), ad: "", tur: "sayi", birim: "", aciklama: "", tolerans: "" };
    yapiDegisti({ ...taslak, [liste]: [...taslak[liste], k], ...(liste === "ciktilar" ? { satirlar: taslak.satirlar.map((s) => ({ ...s, cikti: { ...s.cikti, [k.anahtar]: "" } })) } : {}) });
    odakla(`${id}-${liste}-${k.anahtar}-ad`);
  }
  function kolonKaldir(liste: "girdiler" | "ciktilar", i: number) {
    yapiDegisti({ ...taslak, [liste]: taslak[liste].filter((_, j) => j !== i) });
    odakla(`${id}-${liste}-ekle`);
  }
  function satirEkle() {
    const s: Satir = { anahtar: yeniAnahtar(), id: yeniSatirId(taslak.satirlar), kosul: "", cikti: Object.fromEntries(taslak.ciktilar.map((c) => [c.anahtar, ""])) };
    yapiDegisti({ ...taslak, satirlar: [...taslak.satirlar, s] });
    odakla(`${id}-satir-${s.anahtar}-kosul`);
  }

  function kolonlar(liste: "girdiler" | "ciktilar") {
    const baslik = liste === "girdiler" ? "Girdiler" : "Çıktılar";
    const tekil = liste === "girdiler" ? "Girdi" : "Çıktı";
    const b = bag(liste);
    return (
      <fieldset className="kt-grup">
        <legend>{baslik}</legend>
        {b.mesaj}
        {taslak[liste].length === 0 && <p className="soluk kucuk">Henüz {tekil.toLocaleLowerCase("tr")} yok.</p>}
        {taslak[liste].map((k, i) => {
          const yol = `${liste}[${i}]`;
          const ad = bag(`${yol}.ad`);
          const tur = bag(`${yol}.tur`);
          const birim = bag(`${yol}.birim`);
          const ek = liste === "ciktilar" ? bag(`${yol}.tolerans`) : bag(`${yol}.aciklama`);
          const etiket = `${tekil} ${i + 1}${k.ad ? ` (${k.ad})` : ""}`;
          const alanId = `${id}-${liste}-${k.anahtar}`;
          return (
            <div key={k.anahtar} className="kt-satir" role="group" aria-label={etiket} data-testid={`kt-${liste}`}>
              <div className="kt-satir-bas">
                <strong className="kucuk">{etiket}</strong>
                <SiraDugmeleri
                  ad={etiket}
                  i={i}
                  n={taslak[liste].length}
                  tasi={(yon) => yapiDegisti({ ...taslak, [liste]: tasi(taslak[liste], i, yon) })}
                  kaldir={() => kolonKaldir(liste, i)}
                />
              </div>
              <div className="alan">
                <label htmlFor={`${alanId}-ad`}>Ad</label>
                <input id={`${alanId}-ad`} className="mono" value={k.ad} spellCheck={false} autoComplete="off" {...ad.oz} onChange={(e) => kolonGuncelle(liste, i, { ad: e.target.value })} />
                {ad.mesaj}
              </div>
              <div className="alan">
                <label htmlFor={`${alanId}-tur`}>Tür</label>
                <select id={`${alanId}-tur`} value={k.tur} {...tur.oz} onChange={(e) => kolonGuncelle(liste, i, { tur: e.target.value as KolonTuru })}>
                  {(Object.keys(KOLON_TURU) as KolonTuru[]).map((t) => (
                    <option key={t} value={t}>
                      {KOLON_TURU[t]}
                    </option>
                  ))}
                </select>
                {tur.mesaj}
              </div>
              <div className="alan">
                <label htmlFor={`${alanId}-birim`}>Birim</label>
                <input id={`${alanId}-birim`} value={k.birim} {...birim.oz} onChange={(e) => kolonGuncelle(liste, i, { birim: e.target.value })} />
                {birim.mesaj}
              </div>
              {liste === "ciktilar" ? (
                <div className="alan">
                  <label htmlFor={`${alanId}-tolerans`}>Tolerans</label>
                  <input
                    id={`${alanId}-tolerans`}
                    className="mono"
                    inputMode="decimal"
                    value={k.tur === "sayi" ? k.tolerans : ""}
                    placeholder={k.tur === "sayi" ? "0" : "yalnız sayı"}
                    readOnly={k.tur !== "sayi"}
                    aria-describedby={k.tur !== "sayi" ? `${alanId}-tolerans-ipucu` : undefined}
                    {...ek.oz}
                    onChange={(e) => kolonGuncelle(liste, i, { tolerans: e.target.value })}
                  />
                  {k.tur !== "sayi" && (
                    <span id={`${alanId}-tolerans-ipucu`} className="soluk kucuk">
                      Tolerans yalnız sayı çıktısında kullanılır.
                    </span>
                  )}
                  {ek.mesaj}
                </div>
              ) : (
                <div className="alan">
                  <label htmlFor={`${alanId}-aciklama`}>Açıklama</label>
                  <input id={`${alanId}-aciklama`} value={k.aciklama} {...ek.oz} onChange={(e) => kolonGuncelle(liste, i, { aciklama: e.target.value })} />
                  {ek.mesaj}
                </div>
              )}
            </div>
          );
        })}
        <button type="button" id={`${id}-${liste}-ekle`} className="dugme dugme-ikincil dugme-kucuk" onClick={() => kolonEkle(liste)}>
          {tekil} ekle
        </button>
      </fieldset>
    );
  }

  const adBag = bag("ad");
  const aciklamaBag = bag("aciklama");
  const acBag = bag("ac_refs");
  const satirlarBag = bag("satirlar");

  return (
    <form className="kt-duzenle" onSubmit={kaydet} noValidate aria-label={`${tablo.icerik.ad || "Karar tablosu"} düzenleme`} data-testid="kt-duzenleyici">
      <div className="kt-duzenle-ust">
        <div className="alan">
          <label htmlFor={`${id}-ad`}>Tablo adı</label>
          <input ref={ilkAlan} id={`${id}-ad`} value={taslak.ad} maxLength={200} {...adBag.oz} onChange={(e) => setTaslak({ ...taslak, ad: e.target.value })} />
          {adBag.mesaj}
        </div>
        <div className="alan">
          <label htmlFor={`${id}-aciklama`}>Açıklama</label>
          <textarea id={`${id}-aciklama`} rows={2} value={taslak.aciklama} {...aciklamaBag.oz} onChange={(e) => setTaslak({ ...taslak, aciklama: e.target.value })} />
          {aciklamaBag.mesaj}
        </div>
      </div>
      <AcSecici secili={taslak.ac_refs} degisti={(r) => setTaslak({ ...taslak, ac_refs: r })} kriterler={kriterler} hata={acBag.mesaj} />
      {kolonlar("girdiler")}
      {kolonlar("ciktilar")}

      <fieldset className="kt-grup">
        <legend>Satırlar</legend>
        <p className="soluk kucuk" id={`${id}-ifade-ozet`}>
          Koşulu ilk sağlayan satır geçerlidir. İfade dili: <span className="mono kt-ifade">+ - * / // % == != &lt; &lt;= &gt; &gt;= ve veya degil</span>,{" "}
          <span className="mono kt-ifade">min max yuvarla taban tavan eger</span>, <span className="mono kt-ifade">dogru</span> /{" "}
          <span className="mono kt-ifade">yanlis</span>.
        </p>
        <IfadeDiliYardimi id={`${id}-ifade-yardim`} girdiler={taslak.girdiler.map((g) => g.ad.trim()).filter(Boolean)} />
        <p className="soluk kucuk" id={`${id}-satir-kimligi`}>
          Satır kimliği (R1, R2 …) otomatik verilir, elle düzenlenmez; kimlik hatası görürseniz satırı kaldırıp yeniden ekleyin.
        </p>
        {satirlarBag.mesaj}
        {taslak.satirlar.length === 0 && <p className="soluk kucuk">Henüz satır yok.</p>}
        {taslak.satirlar.map((s, i) => {
          const kosul = bag(`satirlar[${i}].kosul`);
          bag(`satirlar[${i}].id`);
          const idHata = hatalar?.alan[`satirlar[${i}].id`];
          // onyüz 21: satır kimliği hatası satıra ve koşul alanına bağlı (aria-describedby + aria-invalid).
          const idHataId = `${id}-satir-${s.anahtar}-id-hata`;
          return (
            <div
              key={s.anahtar}
              className={`kt-satir${idHata ? " kt-satir-hatali" : ""}`}
              role="group"
              aria-label={`Satır ${s.id}`}
              aria-describedby={[idHata ? idHataId : null, `${id}-satir-kimligi`].filter(Boolean).join(" ")}
              data-testid="kt-satir"
            >
              <div className="kt-satir-bas">
                <strong className="mono kucuk">{s.id}</strong>
                <SiraDugmeleri
                  ad={`Satır ${s.id}`}
                  i={i}
                  n={taslak.satirlar.length}
                  tasi={(yon) => yapiDegisti({ ...taslak, satirlar: tasi(taslak.satirlar, i, yon) })}
                  kaldir={() => {
                    yapiDegisti({ ...taslak, satirlar: taslak.satirlar.filter((_, j) => j !== i) });
                    odakla(`${id}-satir-ekle`);
                  }}
                />
              </div>
              {idHata && (
                <span id={idHataId} className="alan-hata kt-satir-kosul" data-testid="kt-satir-id-hatasi">
                  Satır {s.id || "(kimliksiz)"}: {idHata.join(" · ")}
                </span>
              )}
              <div className="alan kt-satir-kosul">
                <label htmlFor={`${id}-satir-${s.anahtar}-kosul`}>Koşul</label>
                <input
                  id={`${id}-satir-${s.anahtar}-kosul`}
                  className="mono"
                  value={s.kosul}
                  maxLength={300}
                  spellCheck={false}
                  autoComplete="off"
                  aria-describedby={[kosul.oz["aria-describedby"], idHata ? idHataId : null, `${id}-ifade-ozet`].filter(Boolean).join(" ")}
                  {...("aria-invalid" in kosul.oz || idHata ? { "aria-invalid": true } : {})}
                  onChange={(e) => setTaslak({ ...taslak, satirlar: taslak.satirlar.map((x, j) => (j === i ? { ...x, kosul: e.target.value } : x)) })}
                />
                {kosul.mesaj}
              </div>
              {taslak.ciktilar.map((c, ci) => {
                const yol = `satirlar[${i}].cikti.${c.ad.trim()}`;
                const b = c.ad.trim() ? bag(yol) : { oz: {}, mesaj: null };
                const alanId = `${id}-satir-${s.anahtar}-cikti-${c.anahtar}`;
                return (
                  <div key={c.anahtar} className="alan">
                    <label htmlFor={alanId}>
                      <span className="mono">{c.ad || `çıktı ${ci + 1}`}</span> ifadesi
                    </label>
                    <input
                      id={alanId}
                      className="mono"
                      value={s.cikti[c.anahtar] ?? ""}
                      maxLength={300}
                      spellCheck={false}
                      autoComplete="off"
                      {...b.oz}
                      onChange={(e) =>
                        setTaslak({ ...taslak, satirlar: taslak.satirlar.map((x, j) => (j === i ? { ...x, cikti: { ...x.cikti, [c.anahtar]: e.target.value } } : x)) })
                      }
                    />
                    {b.mesaj}
                  </div>
                );
              })}
            </div>
          );
        })}
        <button type="button" id={`${id}-satir-ekle`} className="dugme dugme-ikincil dugme-kucuk" onClick={satirEkle}>
          Satır ekle
        </button>
      </fieldset>

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
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={guncelIcerigiYukle}>
            Güncel içeriği yükle
          </button>
        </p>
      )}
      <div className="eylemler">
        <IslemDugmesi izin="decision_table.edit" type="submit" calisiyor={islem.calisiyor}>
          Kaydet
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** Açılır "İfade dili" yardımı: örnekler (bu tablodan), girdi adları, sabitlerin yazımı (onyüz 4). */
function IfadeDiliYardimi({ id, girdiler }: { id: string; girdiler: string[] }) {
  return (
    <details className="kt-ifade-yardim" id={id} data-testid="ifade-yardim">
      <summary className="kucuk">İfade dili</summary>
      <ul className="duz-liste kucuk">
        <li>
          Karşılaştırma: <code className="kt-ifade">adet &gt;= 7</code> (7 dahil), <code className="kt-ifade">sepet_tutari &lt; 750</code> (750 hariç).
        </li>
        <li>
          Birleştirme: <code className="kt-ifade">kampanyali_sepet ve sepet_tutari &lt; 750</code>, <code className="kt-ifade">degil kampanyali_sepet</code>.
        </li>
        <li>
          Tam bölme: <code className="kt-ifade">adet // 7</code> (14 // 7 = 2, 13 // 7 = 1); kalan: <code className="kt-ifade">adet % 7</code>.
        </li>
        <li>
          Yuvarlama: <code className="kt-ifade">yuvarla(ara_toplam / adet, 2)</code> (2 haneye, yarım yukarı); <code className="kt-ifade">taban(x)</code> aşağı,{" "}
          <code className="kt-ifade">tavan(x)</code> yukarı.
        </li>
        <li>
          Koşullu değer: <code className="kt-ifade">eger(adet &gt;= 7, 1, 0)</code>.
        </li>
        <li>
          Sabitler: ondalık ayırıcı nokta (<code className="kt-ifade">25.50</code>, virgül değil), metin çift tırnakla (<code className="kt-ifade">&quot;P-001&quot;</code>),
          mantıksal <code className="kt-ifade">dogru</code> / <code className="kt-ifade">yanlis</code>. Son satırda <code className="kt-ifade">dogru</code> “diğer tüm
          durumlar” demektir.
        </li>
      </ul>
      {girdiler.length > 0 && (
        <p className="kucuk">
          Bu tablonun girdi adları:{" "}
          {girdiler.map((g) => (
            <code key={g} className="kt-ifade kt-ad-cip">
              {g}
            </code>
          ))}
        </p>
      )}
    </details>
  );
}

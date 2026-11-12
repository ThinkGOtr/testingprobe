// K20 (D5) "Seçilenleri onayla": case listesinde toplu onay. Yalnız taslak, hazır ve tutarlı (core
// `onay_engeli` null) case seçilebilir; her case kendi görülen içerik hash'iyle AYRI onaylanır
// (`POST /cases/bulk-decision`, kalem bazlı sonuç). Kısmi başarıda kalem hataları case başlığıyla listelenir.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { TestCase, TopluOnaySonucu } from "../api/types";
import { useIslem } from "../hooks";
import { hataListesi, sayiEki, topluOnayEngeli } from "../lib/caseV3";
import { useBildirim } from "./Bildirim";
import { AlanHatasi, IslemDugmesi, SayfaIciOnay, Uyari } from "./ui";

/** Seçim durumu: yalnız görünen ve seçilebilir case'ler seçili kalır (liste/süzgeç değişince ayıklanır). */
export function useTopluSecim(gorunen: TestCase[]) {
  const [secili, setSecili] = useState<Set<string>>(() => new Set());
  const secilebilir = useMemo(() => gorunen.filter((c) => topluOnayEngeli(c) === null), [gorunen]);
  const anahtar = secilebilir.map((c) => c.id).join("|");
  useEffect(() => {
    const gecerli = new Set(anahtar ? anahtar.split("|") : []);
    setSecili((s) => {
      const yeni = new Set([...s].filter((x) => gecerli.has(x)));
      return yeni.size === s.size ? s : yeni;
    });
  }, [anahtar]);
  const degistir = (id: string, acik: boolean) =>
    setSecili((s) => {
      const yeni = new Set(s);
      if (acik) yeni.add(id);
      else yeni.delete(id);
      return yeni;
    });
  return { secili, setSecili, secilebilir, degistir };
}

/**
 * Kartın başlık satırındaki seçim kutusu (gerçek checkbox, etiketli). Karar verilmiş case'te kutu
 * yok; seçilemeyen taslakta kutu pasif ve nedeni görünür.
 */
export function SecimKutusu({ tc, secili, degistir }: { tc: TestCase; secili: boolean; degistir: (id: string, acik: boolean) => void }) {
  const nedenId = useId();
  if (tc.durum !== "draft") return null;
  const engel = topluOnayEngeli(tc);
  const ad = `Case ${sayiEki(tc.sira_no, "belirtme")} seç: ${tc.icerik.title}`;
  return (
    <span className="toplu-secim" data-testid="toplu-secim">
      <input
        type="checkbox"
        className="toplu-secim-kutu"
        aria-label={ad}
        checked={engel === null && secili}
        disabled={engel !== null}
        aria-describedby={engel ? nedenId : undefined}
        onChange={(e) => degistir(tc.id, e.target.checked)}
      />
      {engel && (
        <span id={nedenId} className="soluk kucuk toplu-secim-neden">
          Toplu onaya seçilemez: {engel}
        </span>
      )}
    </span>
  );
}

/** Tek satırlık sonuç metni: "3 case onaylandı" ya da "2 onaylandı, 1 onaylanamadı". */
export function topluSonucMetni(s: Pick<TopluOnaySonucu, "onaylanan" | "basarisiz">): string {
  return s.basarisiz === 0 ? `${s.onaylanan} case onaylandı` : `${s.onaylanan} onaylandı, ${s.basarisiz} onaylanamadı`;
}

export function TopluOnayCubugu({
  gorunen,
  secim,
  tamamlandi,
}: {
  /** Listede görünen case'ler (başlık ve hash buradan). */
  gorunen: TestCase[];
  secim: ReturnType<typeof useTopluSecim>;
  /** Toplu onaydan sonra liste ve paneller yenilenir. */
  tamamlandi: () => void;
}) {
  const { secili, setSecili, secilebilir } = secim;
  const islem = useIslem();
  const bildir = useBildirim();
  const [onayAcik, setOnayAcik] = useState(false);
  const [sonuc, setSonuc] = useState<{ ozet: string; hatalar: { id: string; baslik: string; hata: string }[] } | null>(null);
  const tumuRef = useRef<HTMLInputElement>(null);
  const nedenId = useId();
  const n = secili.size;
  const tumu = secilebilir.length > 0 && secilebilir.every((c) => secili.has(c.id));
  const kismen = n > 0 && !tumu;
  useEffect(() => {
    if (tumuRef.current) tumuRef.current.indeterminate = kismen;
  }, [kismen]);
  useEffect(() => {
    if (n === 0) setOnayAcik(false);
  }, [n]);
  const taslakVar = gorunen.some((c) => c.durum === "draft");
  if (!taslakVar && !sonuc) return null;

  async function onayla() {
    // Görülen içerik: her kalem ekrandaki case'in hash'iyle gider (arada değiştiyse kalem 409 olur).
    const kalemler = gorunen.filter((c) => secili.has(c.id)).map((c) => ({ case_id: c.id, icerik_hash: c.icerik_hash }));
    if (kalemler.length === 0) return;
    const s = await islem.calistir(() => api.topluOnay(kalemler));
    if (!s) return;
    setOnayAcik(false);
    const ozet = topluSonucMetni(s);
    const baslik = (id: string) => {
      const c = gorunen.find((x) => x.id === id);
      return c ? `#${c.sira_no} ${c.icerik.title}` : id;
    };
    const hatalar = s.sonuclar
      .filter((k) => !k.basarili)
      // Sunucu metni "başlık — [ayrıntı]" biçimindeyse başlık yeterli (ayrıntı kartta görünür).
      .map((k) => ({ id: k.case_id, baslik: baslik(k.case_id), hata: hataListesi(k.hata).baslik || k.hata || "Onaylanamadı" }));
    setSonuc(hatalar.length ? { ozet, hatalar } : null);
    bildir(ozet, s.basarisiz ? "hata" : "basari");
    setSecili(new Set());
    tamamlandi();
  }

  return (
    <div className="toplu-onay" role="group" aria-label="Toplu onay" data-testid="toplu-onay">
      {taslakVar && (
        <div className="toplu-onay-satir">
          <label className="toplu-onay-tumu">
            <input
              ref={tumuRef}
              type="checkbox"
              className="toplu-secim-kutu"
              checked={tumu}
              disabled={secilebilir.length === 0}
              aria-describedby={secilebilir.length === 0 ? nedenId : undefined}
              onChange={(e) => setSecili(e.target.checked ? new Set(secilebilir.map((c) => c.id)) : new Set())}
            />{" "}
            Tümünü seç (seçilebilir {secilebilir.length})
          </label>
          {secilebilir.length === 0 && (
            <span id={nedenId} className="soluk kucuk">
              Toplu onaya uygun case yok: yalnız hazır ve tutarlı taslaklar seçilebilir.
            </span>
          )}
          <span className="toplu-onay-sayi" role="status" aria-live="polite">
            {n > 0 ? `${n} case seçildi` : ""}
          </span>
          {n > 0 && !onayAcik && (
            <IslemDugmesi roller={["analyst"]} kucuk calisiyor={islem.calisiyor} onClick={() => setOnayAcik(true)}>
              Seçilenleri onayla
            </IslemDugmesi>
          )}
        </div>
      )}
      {onayAcik && n > 0 && (
        <SayfaIciOnay
          baslik={`${n} case onaylansın mı?`}
          onayMetni={`Evet, ${n} case'i onayla`}
          calisiyor={islem.calisiyor}
          onayla={() => void onayla()}
          vazgec={() => setOnayAcik(false)}
          testId="toplu-onay-onayi"
        >
          <p className="kucuk">{n} case kendi görülen içerikleriyle ayrı ayrı onaylanacak. Arada değişen ya da hazır olmayan case onaylanmaz ve nedeni listelenir.</p>
        </SayfaIciOnay>
      )}
      {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
      {sonuc && sonuc.hatalar.length > 0 && (
        <div data-testid="toplu-onay-sonuc">
          <Uyari baslik={sonuc.ozet}>
            <ul className="toplu-onay-hatalar">
              {sonuc.hatalar.map((h) => (
                <li key={h.id}>
                  <strong>{h.baslik}</strong>: {h.hata}
                </li>
              ))}
            </ul>
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setSonuc(null)}>
              Kapat
            </button>
          </Uyari>
        </div>
      )}
    </div>
  );
}

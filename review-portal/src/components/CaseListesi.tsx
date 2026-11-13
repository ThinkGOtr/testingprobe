// Case review sayfasının case listesi bölgesi (A2): filtre sekmeleri (URL `?filtre=`), ek süzgeçler
// (`?uretim=<no>`, `?hazirlik=<durum>`, `?teknik=<kısaltma>`), toplu karar alanı (013/012: Case review
// `TopluOnayCubugu`; çağıran verir) ve case kartları. Durum şeridi (A1) ve derinleştirme "göster"
// bağlantısı bu parametrelerle buraya gelir.
import { useMemo, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import type { CaseUretimOzeti, TestCase } from "../api/types";
import { useIzin } from "../auth";
import { caseHazirlik, onayaHazirDegil, sayiEki } from "../lib/caseV3";
import { CASE_HAZIRLIK, CASE_TEKNIGI } from "../lib/etiketler";
import { PoyaGonderEylemi } from "./AcikSorular";
import { CaseKarti, type CaseSecimi } from "./CaseKarti";
import { BosDurum, HataKutusu, Kart, Yukleniyor } from "./ui";

/** 012: `bekleyen` Testçi kararı bekleyen taslak, `hazir` Analist son onayı bekleyen (onaya hazır). */
export type CaseFiltresi = "hepsi" | "bekleyen" | "hazir" | "onayli" | "reddedilen" | "hazir-degil";
const FILTRELER: CaseFiltresi[] = ["hepsi", "bekleyen", "hazir", "onayli", "reddedilen", "hazir-degil"];
/** Ek süzgeç parametreleri ("Tümünü göster" bunları temizler). */
export const EK_SUZGECLER = ["uretim", "hazirlik", "teknik"] as const;

const onayli = (c: TestCase) => c.durum === "approved" || c.durum === "published";

export function filtreUygula(c: TestCase, f: CaseFiltresi): boolean {
  if (f === "bekleyen") return c.durum === "draft";
  if (f === "hazir") return c.durum === "ready";
  if (f === "onayli") return onayli(c);
  if (f === "reddedilen") return c.durum === "rejected";
  if (f === "hazir-degil") return onayaHazirDegil(c);
  return true;
}

/** URL'deki süzgeçler: geçersiz değer yok sayılır. */
export function useCaseSuzgeci() {
  const [p, setP] = useSearchParams();
  const ham = p.get("filtre");
  const filtre: CaseFiltresi = FILTRELER.includes(ham as CaseFiltresi) ? (ham as CaseFiltresi) : "hepsi";
  const uretimHam = Number(p.get("uretim"));
  const uretim = p.get("uretim") && Number.isInteger(uretimHam) && uretimHam > 0 ? uretimHam : null;
  const hazirlik = p.get("hazirlik") || null;
  const teknik = p.get("teknik") || null;
  const guncelle = (fn: (q: URLSearchParams) => void) => {
    const q = new URLSearchParams(p);
    fn(q);
    setP(q, { replace: true });
  };
  return {
    filtre,
    uretim,
    hazirlik,
    teknik,
    filtreSec: (f: CaseFiltresi) => guncelle((q) => (f === "hepsi" ? q.delete("filtre") : q.set("filtre", f))),
    ekleriTemizle: () => guncelle((q) => EK_SUZGECLER.forEach((k) => q.delete(k))),
  };
}

/** Ek süzgeçlerin cümlesi: "Üretim 2'nin case'leri gösteriliyor". */
export function suzgecMetni(s: { uretim: number | null; hazirlik: string | null; teknik: string | null }): string | null {
  const parcalar: string[] = [];
  if (s.uretim !== null) parcalar.push(`Üretim ${sayiEki(s.uretim, "tamlayan")} case'leri`);
  if (s.hazirlik) parcalar.push(`hazır olma durumu "${CASE_HAZIRLIK[s.hazirlik]?.etiket ?? s.hazirlik}" olan case'ler`);
  if (s.teknik) parcalar.push(`${s.teknik}${CASE_TEKNIGI[s.teknik] ? ` (${CASE_TEKNIGI[s.teknik]})` : ""} tekniğini kullanan case'ler`);
  if (!parcalar.length) return null;
  const metin = parcalar.join(" ve ");
  return `${metin.charAt(0).toLocaleUpperCase("tr-TR")}${metin.slice(1)} gösteriliyor`;
}

export function CaseListesi({
  liste,
  yukleniyor,
  hata,
  hataNesnesi,
  yeniden,
  yenile,
  guncellendi,
  uretimler,
  varsayimDogrulandi,
  topluAlani,
  secim,
  goruntulendi,
  kisitli = false,
}: {
  liste: TestCase[];
  /** Toplu karar çubuğu ve sonucu (Case review, 013/012); filtre sekmelerinin altına yerleşir. */
  topluAlani?: ReactNode;
  /** Kartın toplu karar seçimi (yalnız kararı bekleyen evredeki case'te). */
  secim?: (c: TestCase) => CaseSecimi | undefined;
  /** Kart 3 sn kesintisiz görüldü (toplu karar uygunluğu yeniden hesaplanır). */
  goruntulendi?: (anahtar: string) => void;
  /** Developer kısıtlı görünümü: yalnız onaylı/yayınlanmış case, boş durum ipucu yok. */
  kisitli?: boolean;
  /** İlk yükleme sürüyor (henüz veri yok). */
  yukleniyor: boolean;
  /** Liste hiç yüklenemedi. */
  hata: string | null;
  hataNesnesi?: unknown;
  /** "Tekrar dene" (görünür yükleme). */
  yeniden: () => void;
  /** Sessiz yenileme (409 sonrası). */
  yenile: () => void;
  guncellendi: (t: TestCase) => void;
  /** case-summary üretimleri: derinleştirme rozeti için üretim türü (yoksa rozet yok). */
  uretimler?: CaseUretimOzeti[] | null;
  /** B2: "Varsayım doğrulandı" sonrası aynı varsayıma dayanan case'ler iyimser güncellenir. */
  varsayimDogrulandi?: (onceki: TestCase, yeni: TestCase, varsayimlar: string[]) => void;
}) {
  const s = useCaseSuzgeci();
  // D6 "Açık soruları PO'ya gönder" kart yuvası yalnız `case.ask_po` (Analist) için çizilir.
  const poyaSorabilir = useIzin("case.ask_po");
  const turler = useMemo(() => new Map((uretimler ?? []).map((u) => [u.uretim_no, u.tur])), [uretimler]);
  // Ek süzgeçler sayaçlara da uygulanır: sekme sayıları görünen kümeyi anlatır.
  const taban = useMemo(
    () =>
      liste.filter(
        (c) =>
          (s.uretim === null || (c.uretim_no ?? 1) === s.uretim) &&
          (!s.hazirlik || caseHazirlik(c) === s.hazirlik) &&
          (!s.teknik || (c.icerik.technique ?? []).includes(s.teknik as never)),
      ),
    [liste, s.uretim, s.hazirlik, s.teknik],
  );
  const gorunen = useMemo(() => taban.filter((c) => filtreUygula(c, s.filtre)), [taban, s.filtre]);
  const suzgec = suzgecMetni(s);
  const say = (f: CaseFiltresi) => taban.filter((c) => filtreUygula(c, f)).length;
  const sekmeler: [CaseFiltresi, string][] = [
    ["hepsi", `Hepsi (${taban.length})`],
    ["bekleyen", `Karar bekleyen (${say("bekleyen")})`],
    ["hazir", `Onaya hazır (${say("hazir")})`],
    ["hazir-degil", `Hazır değil (${say("hazir-degil")})`],
    ["onayli", `Onaylı (${say("onayli")})`],
    ["reddedilen", `Reddedilen (${say("reddedilen")})`],
  ];

  return (
    <div className="case-liste-alani">
      {/* Developer kısıtlı görünümü (012): yalnız onaylı/yayınlanmış case gelir; durum filtresi anlamsız. */}
      {!kisitli && (
        <div className="sekmeler sekmeler-yapiskan" role="group" aria-label="Case filtresi">
          {sekmeler.map(([k, etiket]) => (
            <button key={k} type="button" className={`sekme${s.filtre === k ? " aktif" : ""}`} aria-pressed={s.filtre === k} onClick={() => s.filtreSec(k)}>
              {etiket}
            </button>
          ))}
        </div>
      )}
      <div role="status" aria-live="polite" className="case-suzgec-kap">
        {suzgec && (
          <p className="case-suzgec" data-testid="case-suzgec">
            <span>{suzgec}</span>{" "}
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={s.ekleriTemizle}>
              Tümünü göster
            </button>
          </p>
        )}
      </div>

      {liste.length > 0 && topluAlani}

      {yukleniyor ? (
        <Yukleniyor />
      ) : hata ? (
        <HataKutusu hata={hata} kaynak={hataNesnesi} yenile={yeniden} />
      ) : gorunen.length === 0 ? (
        <Kart>
          <BosDurum baslik={liste.length ? "Bu filtrede case yok." : "Henüz case üretilmedi."}>
            {!liste.length && !kisitli && "PO teyidinden sonra gereksinim ekranından 'Tasarım modelini üret (iki tur)' ile başlatın (Testçi)."}
          </BosDurum>
        </Kart>
      ) : (
        <div className="case-liste">
          {gorunen.map((c) => (
            <CaseKarti
              key={c.id}
              tc={c}
              guncellendi={guncellendi}
              yenile={yenile}
              uretimTuru={c.uretim_no !== undefined ? turler.get(c.uretim_no) : undefined}
              secim={secim?.(c)}
              goruntulendi={goruntulendi}
              poyaGonder={poyaSorabilir ? <PoyaGonderEylemi tc={c} tamamlandi={yenile} /> : undefined}
              varsayimDogrulandi={varsayimDogrulandi}
            />
          ))}
        </div>
      )}
    </div>
  );
}

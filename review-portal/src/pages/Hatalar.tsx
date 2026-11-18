// TP UX denetimi IA-16: hata (triage) kuyruğu. Belirsiz kalan hata artık sessizce kaybolmaz:
// "Sınıflandırılmamış" sekmesi Test Uzmanı / Otomasyon Mühendisinin kuyruğudur; diğer sekmeler ürün
// hatası, test bakımı, test verisi, ortam ve kararsız testleri ayırır. Kaynak: `GET /failures`.
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { HataAnalizi, HataSinifi } from "../api/types";
import { BosDurum, Cip, HataKutusu, Kart, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useVeri } from "../hooks";
import { HATA_SINIFI, testAdiGoster } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { kisaKosuAdi } from "./Kosular";

const SEKMELER: { anahtar: HataSinifi | "hepsi"; etiket: string }[] = [
  { anahtar: "unknown", etiket: "Sınıflandırılmamış" },
  { anahtar: "product_defect", etiket: "Ürün hatası" },
  { anahtar: "test_maintenance", etiket: "Test bakımı" },
  { anahtar: "test_data", etiket: "Test verisi" },
  { anahtar: "environment", etiket: "Ortam" },
  { anahtar: "flaky", etiket: "Kararsız" },
  { anahtar: "hepsi", etiket: "Tümü" },
];

const KAYNAK_ETIKETI: Record<HataAnalizi["karar_kaynagi"], string> = { rule: "Kural", llm: "AI", human: "İnsan" };

/** Sekmedeki hatalar: kasıtlı kırma kırmızıları kuyruğa girmez (yalnız "Tümü"nde, işaretli). */
export function hataSuz(liste: readonly HataAnalizi[], sekme: HataSinifi | "hepsi"): HataAnalizi[] {
  if (sekme === "hepsi") return [...liste];
  return liste.filter((h) => h.sinif === sekme && !h.kirma);
}

export function Hatalar() {
  const [p, setP] = useSearchParams();
  const ham = p.get("sinif");
  const sekme = (SEKMELER.find((s) => s.anahtar === ham)?.anahtar ?? "unknown") as HataSinifi | "hepsi";
  const v = useVeri(() => api.hatalar({ limit: 200 }), []);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["failure.classified", "failure.updated"]);
  const liste = v.veri ?? [];
  const gorunen = hataSuz(liste, sekme);

  return (
    <>
      <SayfaBasligi
        baslik="Hatalar"
        aciklama="Koşulardaki kırmızı testlerin triage sonuçları. Sınıflandırılmamış hatayı Test Uzmanı ya da Otomasyon Mühendisi sınıflandırır; ürün hatası bug taslağına, test bakımı onarıma gider."
      />
      <div className="sekmeler" role="group" aria-label="Hata sınıfı">
        {SEKMELER.map((s) => (
          <button
            key={s.anahtar}
            type="button"
            className={`sekme${sekme === s.anahtar ? " aktif" : ""}`}
            aria-pressed={sekme === s.anahtar}
            onClick={() => setP(s.anahtar === "unknown" ? {} : { sinif: s.anahtar }, { replace: true })}
          >
            {s.etiket}
            {v.veri ? ` (${hataSuz(liste, s.anahtar).length})` : ""}
          </button>
        ))}
      </div>
      <Kart>
        {v.yukleniyor && !v.veri ? (
          <Yukleniyor />
        ) : v.hata && !v.veri ? (
          <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
        ) : gorunen.length === 0 ? (
          <BosDurum baslik={sekme === "unknown" ? "Sınıflandırma bekleyen hata yok." : "Bu sınıfta hata yok."}>
            Kırmızı testler koşu bitince otomatik sınıflandırılır; kural ya da AI karar veremezse burada görünür.{" "}
            <Link to="/kosular">Koşulara git</Link>
          </BosDurum>
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Hatalar tablosu">
            <table className="tablo tablo-yigin">
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  <th scope="col">Sınıf</th>
                  <th scope="col">Kim karar verdi</th>
                  <th scope="col">Koşu</th>
                  <th scope="col">Zaman</th>
                </tr>
              </thead>
              <tbody>
                {gorunen.map((h) => {
                  const s = HATA_SINIFI[h.sinif] ?? { etiket: h.sinif, ton: "notr" as const };
                  return (
                    <tr key={h.id}>
                      <td data-etiket="Test">
                        <Link to={`/hatalar/${encodeURIComponent(h.id)}`} className="satir-baglanti">
                          {testAdiGoster(h.test_adi)}
                        </Link>
                        {h.kirma && <span className="soluk kucuk"> · kasıtlı kırma</span>}
                      </td>
                      <td data-etiket="Sınıf">
                        <Cip ton={s.ton}>{s.etiket}</Cip>
                      </td>
                      <td data-etiket="Kim karar verdi">{h.sinif === "unknown" ? "—" : KAYNAK_ETIKETI[h.karar_kaynagi]}</td>
                      <td data-etiket="Koşu">
                        <Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>{kisaKosuAdi(h.run_id)}</Link>
                      </td>
                      <td data-etiket="Zaman" className="tek-satir">
                        {tarih(h.zaman)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Kart>
    </>
  );
}

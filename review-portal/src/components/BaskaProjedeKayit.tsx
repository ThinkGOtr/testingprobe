// TP UX IA-05: detay sayfası kaydı bulamadığında (404) kaydın başka bir projede olup olmadığını sorar
// (`GET /locate`; yalnız kişinin rolü olan projeler) ve "Bu kayıt X projesinde — X'e geç ve aç" der.
// Kayıt hiçbir erişilebilir projede yoksa "Kayıt bu projede yok; [listeye dön]" (tekrar eden ham
// "… bulunamadı" alt metni gösterilmez). 404 dışındaki hatalarda `yedek` (sayfanın mevcut hata görünümü)
// çizilir. Kullanım (detay sayfasının "bulunamadı" dalı, tek satır):
//   if (v.hata && !v.veri) return <BaskaProjedeKayit tur="script" id={id} hata={v.hataNesnesi} ad="Test kodu" liste={["/kod", "Kod üretimi"]} yedek={<KayitHatasi … />} />;
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { bulunamadi } from "../api/http";
import { islerimApi, type IsTuru, type KayitYeri } from "../api/islerim";
import { projeyeGecVeAc } from "../lib/proje";
import { BosDurum, Kart, SayfaBasligi, useHataKaydi, Yukleniyor } from "./ui";

export function BaskaProjedeKayit({
  tur,
  id,
  hata,
  ad,
  liste,
  yedek,
}: {
  tur: IsTuru;
  id: string;
  /** Sayfanın yükleme hatası (`hataNesnesi`); 404 değilse `yedek` gösterilir. */
  hata: unknown;
  /** Kaydın adı ("Gereksinim" → "Gereksinim bulunamadı"). */
  ad: string;
  /** Dönülecek liste: [yol, ad]. */
  liste: readonly [string, string];
  yedek: ReactNode;
}) {
  const yok = bulunamadi(hata);
  const konum = useLocation();
  const [yer, setYer] = useState<KayitYeri | null | undefined>(undefined);
  const [gecisHatasi, setGecisHatasi] = useState<string | null>(null);
  const [geciyor, setGeciyor] = useState(false);
  useEffect(() => {
    if (!yok) return;
    let iptal = false;
    setYer(undefined);
    islerimApi
      .kayitYeri(tur, id)
      .then((y) => !iptal && setYer(y))
      .catch(() => !iptal && setYer(null));
    return () => {
      iptal = true;
    };
  }, [yok, tur, id]);

  const baska = yer?.bulundu && !yer.ayni_proje && yer.proje ? yer.proje : null;
  // Kayıt hiçbir projede yoksa hata asistanın "son hata" kaydına yazılır (HataKutusu'nun yaptığı gibi).
  useHataKaydi(hata, yok && yer !== undefined && !baska ? (hata instanceof Error ? hata.message : `${ad} bulunamadı`) : null);
  if (!yok) return <>{yedek}</>;
  if (yer === undefined) return <Yukleniyor metin="Kayıt aranıyor…" />;
  return (
    <>
      <SayfaBasligi ust={<Link to={liste[0]}>← {liste[1]}</Link>} baslik={baska ? `${ad} başka projede` : `${ad} bulunamadı`} />
      <Kart>
        {baska ? (
          <BosDurum baslik={`Bu kayıt ${baska.ad} projesinde.`}>
            <p>Açmak için o projeye geçin; menü ve listeler o projeye göre değişir.</p>
            <button
              type="button"
              className="dugme dugme-birincil"
              disabled={geciyor}
              aria-busy={geciyor || undefined}
              onClick={() => {
                setGeciyor(true);
                setGecisHatasi(null);
                projeyeGecVeAc(baska.pid, konum.pathname + konum.search + konum.hash).catch((e: unknown) => {
                  setGeciyor(false);
                  setGecisHatasi(e instanceof Error ? e.message : String(e));
                });
              }}
            >
              {baska.ad} projesine geç ve aç
            </button>
            {gecisHatasi && (
              <p className="kucuk" role="alert">
                Projeye geçilemedi: {gecisHatasi}
              </p>
            )}
          </BosDurum>
        ) : (
          <BosDurum baslik="Kayıt bu projede yok.">
            <p>Silinmiş olabilir ya da erişiminiz olan başka bir projede değil.</p>
            <Link to={liste[0]}>{liste[1]} listesine dön</Link>
          </BosDurum>
        )}
      </Kart>
    </>
  );
}

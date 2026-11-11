// Agent Probe'da ön tanımları tamamlanmış AI ajan ürünleri (011 F6, K10). Bu sürümde Agent Probe
// simüle edilir; sayfa bunu rozet ve açıklamayla açıkça söyler.
import { api } from "../api/client";
import { BosDurum, Cip, HataKutusu, Kart, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useVeri } from "../hooks";
import { SIMULASYON_ACIKLAMASI } from "../lib/ajanProbe";

export function AjanUrunleri() {
  const v = useVeri(() => api.ajanUrunleri(), []);
  const urunler = v.veri?.urunler ?? [];
  return (
    <>
      <SayfaBasligi
        baslik="Ajan ürünleri"
        aciklama={
          <span className="satir-ogeler">
            {(v.veri?.simulasyon ?? true) && (
              <Cip ton="uyari" title={SIMULASYON_ACIKLAMASI}>
                Simülasyon
              </Cip>
            )}
            <span>
              Test edilen ürün bir AI ajanıysa test Agent Probe'da koşar; Testing Probe sonuçlara göre süreci sürdürür.
            </span>
          </span>
        }
      />
      <p className="soluk kucuk" data-testid="simulasyon-aciklamasi">
        {SIMULASYON_ACIKLAMASI}
      </p>
      {v.yukleniyor && !v.veri ? (
        <Yukleniyor />
      ) : v.hata && !v.veri ? (
        <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
      ) : (
        <Kart baslik={`Ürünler (${urunler.length})`}>
          {urunler.length === 0 ? (
            <BosDurum baslik="Agent Probe'da hazır ajan ürünü yok." />
          ) : (
            <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Ajan ürünleri tablosu">
              <table className="tablo">
                <thead>
                  <tr>
                    <th scope="col">Ürün</th>
                    <th scope="col">Kod</th>
                    <th scope="col">Açıklama</th>
                  </tr>
                </thead>
                <tbody>
                  {urunler.map((u) => (
                    <tr key={u.kod}>
                      <td>{u.ad}</td>
                      <td className="mono">{u.kod}</td>
                      <td>{u.aciklama}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="soluk kucuk">Bir gereksinimi ajan ürününe bağlamak için gereksinim detayındaki "Ürün AI ajanı" bölümünü kullanın.</p>
        </Kart>
      )}
    </>
  );
}

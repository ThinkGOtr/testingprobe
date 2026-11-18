// Agent Probe'da ön tanımları tamamlanmış AI ajan ürünleri (011 F6, K10). Bu sürümde Agent Probe
// simüle edilir; sayfa bunu rozet ve açıklamayla açıkça söyler.
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AjanUrunu } from "../api/types";
import { BosDurum, Cip, HataKutusu, Kart, SayfaBasligi, SonrakiAdim, Yukleniyor } from "../components/ui";
import { useVeri } from "../hooks";
import { TabloSarici } from "../components/tasarim";
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
            <span>
              Test edilen ürün bir AI ajanıysa test Agent Probe'da koşar; Testing Probe sonuçlara göre süreci sürdürür.
            </span>
            {/* Simülasyon açıklaması sayfada yalnız burada (rozetin yanında) yazılır. */}
            {(v.veri?.simulasyon ?? true) && (
              <span className="satir-ogeler">
                <Cip ton="uyari">Simülasyon</Cip>
                <span className="soluk kucuk" data-testid="simulasyon-aciklamasi">
                  {SIMULASYON_ACIKLAMASI}
                </span>
              </span>
            )}
          </span>
        }
      />
      {v.yukleniyor && !v.veri ? (
        <Yukleniyor />
      ) : v.hata && !v.veri ? (
        <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
      ) : (
        <Kart baslik={`Ürünler (${urunler.length})`}>
          {urunler.length === 0 ? (
            <BosDurum baslik="Agent Probe'da hazır ajan ürünü yok.">
              <SonrakiAdim metin="Ajan ürünü Agent Probe'da tanımlanınca burada listelenir; gereksinime bağlamayı Analist gereksinim ekranından yapar." />
            </BosDurum>
          ) : (
            <TabloSarici etiket="Ajan ürünleri tablosu">
                <thead>
                  <tr>
                    <th scope="col">Ürün</th>
                    <th scope="col">Kod</th>
                    <th scope="col">Açıklama</th>
                    <th scope="col">Bağlı gereksinim</th>
                  </tr>
                </thead>
                <tbody>
                  {urunler.map((u) => (
                    <tr key={u.kod}>
                      <td className="yigin-baslik" data-etiket="Ürün">
                        <strong>{u.ad}</strong>
                      </td>
                      <td className="sutun-kimlik" data-etiket="Kod">
                        {u.kod}
                      </td>
                      <td className="sutun-metin" data-etiket="Açıklama">
                        {u.aciklama}
                      </td>
                      <td data-etiket="Bağlı gereksinim">
                        <BagliGereksinimler u={u} />
                      </td>
                    </tr>
                  ))}
                </tbody>
            </TabloSarici>
          )}
          <p className="soluk kucuk">Bir gereksinimi ajan ürününe bağlamak için gereksinim detayındaki "Ürün AI ajanı" bölümünü kullanın.</p>
        </Kart>
      )}
    </>
  );
}

/** Ürüne bağlı gereksinimler (UX-11); core alanı sunmuyorsa ya da bağlı gereksinim yoksa "—". */
function BagliGereksinimler({ u }: { u: AjanUrunu }) {
  const liste = u.bagli_gereksinimler ?? [];
  if (liste.length === 0)
    return (
      <span data-testid="bagli-gereksinim-yok">
        <span aria-hidden="true">—</span>
        <span className="gorunmez">Bağlı gereksinim yok</span>
      </span>
    );
  return (
    <span className="satir-ogeler">
      {liste.map((r) => (
        <Link key={r.id} to={`/gereksinimler/${encodeURIComponent(r.id)}`} title={r.baslik ?? undefined}>
          {r.jira_key ?? r.baslik ?? r.id}
        </Link>
      ))}
    </span>
  );
}

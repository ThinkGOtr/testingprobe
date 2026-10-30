import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { Kosu } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, Metrik, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { KAYNAK, KOSU_DURUMU, TETIK } from "../lib/etiketler";
import { sure, tarih } from "../lib/format";

function DurumCipi({ d }: { d: string }) {
  const x = KOSU_DURUMU[d] ?? { etiket: d, ton: "notr" as const };
  return <Cip ton={x.ton}>{x.etiket}</Cip>;
}

export function KosuTablosu({ kosular, kompakt }: { kosular: Kosu[]; kompakt?: boolean }) {
  return (
    <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Koşular tablosu">
      <table className="tablo">
        <thead>
          <tr>
            <th scope="col">Koşu</th>
            <th scope="col">Tetik</th>
            {!kompakt && <th scope="col">Kaynak</th>}
            <th scope="col">Durum</th>
            <th scope="col" className="sayi">
              Geçen / toplam
            </th>
            {!kompakt && <th scope="col">Commit</th>}
            <th scope="col">Başlangıç</th>
            {!kompakt && <th scope="col">Süre</th>}
          </tr>
        </thead>
        <tbody>
          {kosular.map((k) => (
            <tr key={k.id}>
              <td>
                <Link to={`/kosular/${encodeURIComponent(k.id)}`} className="satir-baglanti mono">
                  {k.id}
                </Link>
                {k.break_campaign && (
                  <Cip ton="uyari" title="Uygulama BREAK_CAMPAIGN=1 ile koştu (kasıtlı kırma)">
                    kırma
                  </Cip>
                )}
              </td>
              <td>
                {TETIK[k.tetik]}
                {k.pr_no !== null && <span className="mono"> #{k.pr_no}</span>}
              </td>
              {!kompakt && <td>{KAYNAK[k.kaynak]}</td>}
              <td>
                <DurumCipi d={k.durum} />
                {k.flaky > 0 && (
                  <Cip ton="uyari" title="Yeniden denemeyle geçen test">
                    {k.flaky} flaky
                  </Cip>
                )}
              </td>
              <td className="sayi mono">
                {k.gecen}/{k.toplam}
              </td>
              {!kompakt && <td className="mono">{k.commit}</td>}
              <td>{tarih(k.baslangic)}</td>
              {!kompakt && <td>{sure(k.sure_ms)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Kosular() {
  const v = useVeri(() => api.kosular(), []);
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["ci.status", "failure.classified"]);

  const tetikle = async (tetik: "deploy" | "nightly") => {
    const s = await islem.calistir(() => api.ciTetikle(tetik));
    if (s) {
      bildir(s.mesaj ?? "Koşu tetiklendi.");
      void v.yenile(true);
    }
  };

  return (
    <>
      <SayfaBasligi
        baslik="Koşular"
        aciklama="CI yalnızca onaylı, deterministik test kodunu koşturur; CI'da AI yoktur. Sauce Labs ana gösterim, yerel Chromium yedektir."
        eylemler={
          <>
            <IslemDugmesi roller={["presenter"]} tur="ikincil" calisiyor={islem.calisiyor} onClick={() => tetikle("nightly")}>
              Gece koşusu
            </IslemDugmesi>
            <IslemDugmesi roller={["presenter"]} calisiyor={islem.calisiyor} onClick={() => tetikle("deploy")}>
              Deploy tetikle
            </IslemDugmesi>
          </>
        }
      />
      {islem.hata && <HataKutusu hata={islem.hata} />}
      <Kart>
        {v.yukleniyor && !v.veri ? (
          <Yukleniyor />
        ) : v.hata && !v.veri ? (
          <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />
        ) : (v.veri ?? []).length === 0 ? (
          <BosDurum baslik="Henüz koşu yok." />
        ) : (
          <KosuTablosu kosular={v.veri ?? []} />
        )}
      </Kart>
    </>
  );
}

export function KosuDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.kosu(id), [id]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["ci.status", "failure.classified"], id);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />;
  const k = v.veri;
  if (!k) return null;

  return (
    <>
      <SayfaBasligi
        ust={<Link to="/kosular">← Koşular</Link>}
        baslik={<span className="mono">{k.id}</span>}
        aciklama={
          <span className="satir-ogeler">
            <DurumCipi d={k.durum} />
            <span>
              {TETIK[k.tetik]}
              {k.pr_no !== null && ` #${k.pr_no}`} · {KAYNAK[k.kaynak]}
            </span>
            <span className="mono">{k.commit}</span>
            <span className="soluk">{tarih(k.baslangic)}</span>
          </span>
        }
        eylemler={
          <>
            {k.allure_url && (
              <Baglanti href={k.allure_url} yokNedeni="artifact sunucusu yok">
                Allure raporu
              </Baglanti>
            )}
            {k.sauce_url && (
              <Baglanti href={k.sauce_url} yokNedeni="bağlantı yok">
                Sauce Labs
              </Baglanti>
            )}
            {k.ci_url && (
              <Baglanti href={k.ci_url} yokNedeni="bağlantı yok">
                CI işi
              </Baglanti>
            )}
          </>
        }
      />
      {k.break_campaign && <Uyari>Bu koşuda uygulama BREAK_CAMPAIGN=1 ile açıldı (kasıtlı kırma); başarısızlık beklenir.</Uyari>}
      <Kart>
        <div className="metrik-izgara">
          <Metrik etiket="Toplam" deger={k.toplam} />
          <Metrik etiket="Geçen" deger={k.gecen} />
          <Metrik etiket="Başarısız" deger={k.basarisiz} />
          <Metrik etiket="Flaky" deger={k.flaky} />
          <Metrik etiket="Süre" deger={sure(k.sure_ms)} />
        </div>
      </Kart>
      <Kart baslik="Test sonuçları">
        {k.sonuclar.length === 0 ? (
          <BosDurum baslik={k.durum === "queued" || k.durum === "running" ? "Koşu sürüyor…" : "Sonuç yok."} />
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Test sonuçları tablosu">
            <table className="tablo">
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  <th scope="col">Durum</th>
                  <th scope="col" className="sayi">
                    Retry
                  </th>
                  <th scope="col">Süre</th>
                  <th scope="col">Triage</th>
                </tr>
              </thead>
              <tbody>
                {k.sonuclar.map((s) => (
                  <tr key={s.id}>
                    <td>
                      {s.test_adi}
                      {s.hata_mesaji && <pre className="hata-mesaji">{s.hata_mesaji}</pre>}
                    </td>
                    <td>
                      <DurumCipi d={s.durum} />
                    </td>
                    <td className="sayi">{s.retry}</td>
                    <td>{sure(s.sure_ms)}</td>
                    <td>{s.failure_id ? <Link to={`/hatalar/${encodeURIComponent(s.failure_id)}`}>Triage sonucu</Link> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Kart>
    </>
  );
}

import { api } from "../api/client";
import { useOlay } from "../api/events";
import { useBildirim } from "../components/Bildirim";
import { HedefOlcer, OranSutunlari } from "../components/Grafikler";
import { BosDurum, Cip, HataKutusu, Ilerleme, IslemDugmesi, Kart, Metrik, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useRol } from "../auth";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { dolar, sure, tarih, yuzde } from "../lib/format";
import { KosuTablosu } from "./Kosular";

export function KontrolKulesi() {
  const v = useVeri(() => api.kontrolKulesi(), []);
  const sunucu = useRol("presenter");
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => void v.yenile(true), 500);
  useOlay(sessiz, ["ci.status", "failure.classified", "case.generated", "bug.published"]);

  const demo = async (fn: () => Promise<{ mesaj?: string }>) => {
    const s = await islem.calistir(fn);
    if (s) {
      bildir(s.mesaj ?? "Tamam.");
      void v.yenile(true);
    }
  };

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />;
  const k = v.veri;
  if (!k) return null;
  const ai = k.ai_katkisi;
  const toplamSure = ai.ort_ai_sure_ms + ai.ort_review_sure_ms;

  return (
    <>
      <SayfaBasligi
        baslik="Kontrol Kulesi"
        aciklama="Kalite, flaky testler, karne ve AI katkısı tek ekranda. Kaynak: koşuların JUnit XML sonuçları."
        eylemler={
          sunucu && (
            <>
              <IslemDugmesi roller={["presenter"]} tur="ikincil" calisiyor={islem.calisiyor} onClick={() => demo(() => api.demoKir())}>
                Locator'ı kır
              </IslemDugmesi>
              <IslemDugmesi roller={["presenter"]} tur="hayalet" calisiyor={islem.calisiyor} onClick={() => demo(() => api.demoSifirla())}>
                Demoyu sıfırla
              </IslemDugmesi>
            </>
          )
        }
      />
      {islem.hata && <HataKutusu hata={islem.hata} />}

      <div className="kule-izgara">
        <Kart baslik="Geçme oranı" className="kule-oran">
          <div className="buyuk-sayi">{yuzde(k.gecme_orani.oran)}</div>
          <p className="soluk">
            Son {k.gecme_orani.donem_gun} gün · {k.gecme_orani.gecen}/{k.gecme_orani.toplam} test sonucu (kasıtlı kırma koşuları hariç)
          </p>
          <OranSutunlari
            baslik="Günlük geçme oranı"
            hedef={0.95}
            noktalar={k.gunluk_gecme.map((g) => ({
              etiket: new Date(g.tarih).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" }),
              oran: g.oran,
              ek: `${g.kosu} koşu`,
            }))}
          />
          <p className="kucuk soluk">Kesikli çizgi: %95 hedef.</p>
        </Kart>

        <Kart baslik="AI katkısı" className="kule-ai">
          <HedefOlcer etiket="Case kabul oranı" deger={ai.kabul_orani} hedef={ai.kabul_hedefi} />
          <HedefOlcer etiket="Script ilk review başarısı (pass@1)" deger={ai.script_ilk_review} hedef={ai.script_hedefi} />
          <div className="metrik-izgara">
            <Metrik etiket="Case başına AI + review" deger={sure(toplamSure)} alt={`AI ${sure(ai.ort_ai_sure_ms)} · review ${sure(ai.ort_review_sure_ms)}`} />
            <Metrik
              etiket="Manuel baz değer"
              deger={ai.manuel_baz_ms ? sure(ai.manuel_baz_ms) : "ölçülmedi"}
              alt={ai.manuel_baz_ms && toplamSure ? `Kazanç ${yuzde(1 - toplamSure / ai.manuel_baz_ms)}` : undefined}
            />
            <Metrik etiket="Maliyet (toplam)" deger={dolar(ai.maliyet_usd_toplam)} alt={`${ai.cagri_sayisi} model çağrısı`} />
            <Metrik etiket="Bugün" deger={dolar(ai.maliyet_usd_bugun)} alt={`Günlük tavan ${dolar(ai.gunluk_butce_usd)}`} />
          </div>
          <Ilerleme oran={ai.maliyet_usd_bugun / ai.gunluk_butce_usd} etiket="Günlük bütçe kullanımı" />
          {ai.replay_cagri > 0 && (
            <p className="kucuk">
              <span className="rozet rozet-replay">REPLAY</span> {ai.replay_cagri} çağrı kayıtlı çıktıdan karşılandı.
            </p>
          )}
        </Kart>

        <Kart baslik="Erişilebilirlik" className="kule-a11y">
          <div className="metrik-izgara">
            <Metrik etiket="İhlal" deger={k.a11y.ihlal} />
            <Metrik etiket="Kritik" deger={k.a11y.kritik > 0 ? <span className="hata-metin">{k.a11y.kritik}</span> : 0} />
          </div>
          <table className="tablo tablo-sik">
            <caption className="gorunmez">Sayfa bazında erişilebilirlik ihlalleri</caption>
            <thead>
              <tr>
                <th scope="col">Sayfa</th>
                <th scope="col" className="sayi">
                  İhlal
                </th>
                <th scope="col" className="sayi">
                  Kritik
                </th>
              </tr>
            </thead>
            <tbody>
              {k.a11y.sayfalar.map((s) => (
                <tr key={s.yol}>
                  <td className="mono">{s.yol}</td>
                  <td className="sayi">{s.ihlal}</td>
                  <td className="sayi">{s.kritik}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="kucuk soluk">axe-core · WCAG 2.2 AA · son tarama {tarih(k.a11y.son_tarama)}</p>
        </Kart>

        <Kart baslik="Flaky testler" className="kule-flaky">
          {k.flaky.length === 0 ? (
            <BosDurum baslik="Flaky test yok." />
          ) : (
            <ul className="duz-liste">
              {k.flaky.map((f) => (
                <li key={f.test_adi}>
                  <div>{f.test_adi}</div>
                  <div className="kucuk soluk">
                    {f.neden === "retry" ? "Yeniden denemeyle geçti" : "Aynı commit'te sonuç değişti"} · {f.sayi} kez · son {tarih(f.son_gorulme)}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Kart>
      </div>

      <Kart baslik="Karne (story ve uygulama alanı)">
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Karne tablosu">
          <table className="tablo">
            <thead>
              <tr>
                <th scope="col">Story</th>
                <th scope="col">Alan</th>
                <th scope="col" className="sayi">
                  Case
                </th>
                <th scope="col">Otomasyon kapsamı</th>
                <th scope="col">Son sonuç</th>
                <th scope="col" className="sayi">
                  Açık bug
                </th>
              </tr>
            </thead>
            <tbody>
              {k.karne.map((s) => (
                <tr key={s.story_key}>
                  <td>
                    <span className="mono">{s.story_key}</span> {s.baslik}
                  </td>
                  <td>{s.alan}</td>
                  <td className="sayi">{s.case_sayisi}</td>
                  <td>
                    <div className="kapsam">
                      <Ilerleme oran={s.otomasyon_kapsami} etiket={`${s.story_key} otomasyon kapsamı`} />
                      <span className="mono kucuk">{yuzde(s.otomasyon_kapsami)}</span>
                    </div>
                  </td>
                  <td>
                    {s.son_sonuc === "none" ? (
                      "—"
                    ) : (
                      <Cip ton={s.son_sonuc === "passed" ? "basari" : "hata"}>{s.son_sonuc === "passed" ? "Geçti" : "Başarısız"}</Cip>
                    )}
                  </td>
                  <td className="sayi">{s.acik_bug || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Kart>

      <Kart baslik="Son koşular">
        <KosuTablosu kosular={k.son_kosular} kompakt />
      </Kart>
    </>
  );
}

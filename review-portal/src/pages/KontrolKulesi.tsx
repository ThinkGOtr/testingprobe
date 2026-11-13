import { type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { KontrolKulesi as Kule, KpiAnahtari } from "../api/types";
import { HedefOlcer, OranSutunlari } from "../components/Grafikler";
import { BosDurum, Cip, HataKutusu, Ilerleme, Kart, Metrik, Olculmedi, SayfaBasligi, Uyari, Yukleniyor, IzinliLink } from "../components/ui";
import { useGeciktirilmis, useVeri } from "../hooks";
import { kazancOzeti, type KazancOzeti } from "../api/uyumFaz5";
import { BAZ_KAYNAGI } from "../components/BazDegerKarti";
import { dolar, sure, tarih, yuzde } from "../lib/format";
import { KosuTablosu } from "./Kosular";
import { OnerilerOlcumKarti } from "../components/asistan/OnerilerOlcumKarti";
import { tumuReplayMi } from "../lib/aiMaliyet";
import { KaynakIpucu } from "../components/KaynakIpucu";
import { CaseKalitesiBolumu } from "../components/CaseKalitesi";
import { PlatformSuzgeci } from "../components/Platform";
import type { Script } from "../api/types";
import { PLATFORMLAR, PLATFORM_ETIKETI, platformaGoreSuz, platformSecimiOku, type Platform, type PlatformSecimi } from "../lib/platform";
import { BeklentiDogruluguKarosu, HataYakalamaKarosu, OnayliUyumsuzKarti } from "../components/kule/KaliteKpilari";
import { HataKosusuKarti } from "../components/kule/HataKosusuKarti";

/** Platform başına üretilen test sayıları (Kule "Platform dağılımı"; kapatılan kayıtlar sayılmaz). */
export function platformDagilimi(scriptler: Script[]): { platform: Platform; toplam: number; pr_acik: number; birlesti: number; defect: number }[] {
  return PLATFORMLAR.map((platform) => {
    const ps = scriptler.filter((s) => (s.platform === undefined ? "web" : s.platform) === platform && s.durum !== "closed");
    return {
      platform,
      toplam: ps.length,
      pr_acik: ps.filter((s) => s.pr?.durum === "open").length,
      birlesti: ps.filter((s) => s.pr?.durum === "merged" || s.durum === "merged").length,
      defect: ps.filter((s) => s.yerel_sinif === "defect_adayi").length,
    };
  });
}

function PlatformDagilimiKarti({ scriptler, secim }: { scriptler: Script[] | null; secim: PlatformSecimi }) {
  if (!scriptler) return null;
  const satirlar = platformDagilimi(scriptler).filter((r) => secim === "tumu" || r.platform === secim);
  return (
    <Kart baslik="Üretilen testler (platform bazında)">
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Platform dağılımı tablosu">
        <table className="tablo tablo-sik">
          <thead>
            <tr>
              <th scope="col">Platform</th>
              <th scope="col" className="sayi">
                Üretilen test
              </th>
              <th scope="col" className="sayi">
                PR açık
              </th>
              <th scope="col" className="sayi">
                Birleşti
              </th>
              <th scope="col" className="sayi">
                Defect adayı
              </th>
            </tr>
          </thead>
          <tbody>
            {satirlar.map((r) => (
              <tr key={r.platform} data-testid={`platform-dagilimi-${r.platform}`}>
                <td>{PLATFORM_ETIKETI[r.platform]}</td>
                <td className="sayi">{r.toplam}</td>
                <td className="sayi">{r.pr_acik}</td>
                <td className="sayi">{r.birlesti}</td>
                <td className="sayi">{r.defect}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="kucuk soluk">Kaynak: üretilen testler (script tablosu, platform alanı); kapatılan kayıtlar sayılmaz.</p>
    </Kart>
  );
}

function KpiBaslik({ ad, k, anahtar }: { ad: string; k: Kule; anahtar: KpiAnahtari }): ReactNode {
  return (
    <span className="kpi-baslik">
      {ad} <KaynakIpucu kaynak={k.kaynaklar[anahtar]} />
    </span>
  );
}

export function KontrolKulesi() {
  const v = useVeri(() => api.kontrolKulesi(), []);
  // 009: platform süzgeci (adres çubuğunda ?platform=). Platform taşıyan veriler: son koşular ve üretilen testler.
  const scriptler = useVeri(() => api.scriptler().catch(() => null), []);
  const [sorgu, setSorgu] = useSearchParams();
  const secim = platformSecimiOku(sorgu.get("platform"));
  const secimDegistir = (p: PlatformSecimi) => {
    const y = new URLSearchParams(sorgu);
    if (p === "tumu") y.delete("platform");
    else y.set("platform", p);
    setSorgu(y, { replace: true });
  };
  const sessiz = useGeciktirilmis(() => {
    void v.yenile(true);
    void scriptler.yenile(true);
  }, 500);
  useOlay(sessiz, ["ci.status", "failure.classified", "case.generated", "bug.published", "script.updated"]);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />;
  const k = v.veri;
  if (!k) return null;
  const ai = k.ai_katkisi;
  // Tüm AI çağrıları REPLAY'den karşılandıysa ücret ölçülmez (§4.12, K5); "Öneriler ve asistan" kartı da aynı kuralı kullanır.
  const tumuReplay = tumuReplayMi(ai);
  const toplamSure = ai.ort_ai_sure_ms !== null && ai.ort_review_sure_ms !== null ? ai.ort_ai_sure_ms + ai.ort_review_sure_ms : null;
  // Kazanç yalnızca baz değeri story için ölçülmüş satırlardan (varsayılan baz değer kazanca girmez).
  const kazanc = kazancOzeti(k.hazirlik);
  const defectAdayi = k.karne.reduce((a, s) => a + s.acik_defect_adayi, 0);
  const sonKosular = platformaGoreSuz(k.son_kosular, secim, (x) => x.platform);
  const platformsuzKosu = secim === "tumu" ? 0 : k.son_kosular.filter((x) => !x.platform).length;

  return (
    <>
      <SayfaBasligi
        baslik="Kontrol Kulesi"
        aciklama="Kalite, flaky testler, karne ve AI katkısı tek ekranda. Her ölçünün kaynağı yanındaki (i) ipucunda; ölçülmemiş değer “ölçülmedi” yazılır."
      />
      {/*
        "Buton kimliğini değiştir" / "Demoyu sıfırla" (POST /demo/break-locator, /demo/reset) core'da henüz yok
        (Faz 4/5). Sahnede 404 göstermemek için düğmeler bu sayfada çizilmez; sıfırlama `make reset`.
      */}
      <div className="kule-platform" data-testid="kule-platform">
        <PlatformSuzgeci
          etiket="Platform"
          deger={secim}
          degistir={secimDegistir}
          ipucu={
            secim === "tumu"
              ? "Süzgeç son koşuları ve platform bazında üretilen test ölçülerini daraltır."
              : `${PLATFORM_ETIKETI[secim]}: son koşular ve üretilen testler süzüldü. Geçme oranı, karne, AI katkısı ve erişilebilirlik çekirdekte platform ayrımı taşımaz; tüm platformlar içindir.`
          }
        />
      </div>
      {k.uyarilar.length > 0 && (
        <Uyari ton="bilgi">
          <ul className="duz-liste kucuk">
            {k.uyarilar.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </Uyari>
      )}

      {/*
        KPI şeridi (§5 F4, §4.12 stat şeridi): öğeler kartlardan taşındı (kopya değil); testid ve (i) ipucu
        öğeyle birlikte. Maliyet şeride girmez (AI katkısı kartında kalır). "Geçme oranı" h2 kartta tek.
      */}
      <div className="metrik-izgara kule-kpi" data-testid="kule-kpi">
        <Metrik
          etiket={<KpiBaslik ad="Geçme oranı" k={k} anahtar="gecme_orani" />}
          deger={<span data-testid="gecme-orani">{k.gecme_orani.oran === null ? <Olculmedi metin="veri yok" /> : yuzde(k.gecme_orani.oran)}</span>}
        />
        {/* DOM sırası "⚠ n açık defect adayı" okunur; etiket görsel olarak üstte (CSS order). */}
        <div className="metrik kule-kpi-defect" data-testid="defect-adayi-ozet">
          <div className={`metrik-deger${defectAdayi > 0 ? " kule-kpi-uyari" : ""}`}>
            {k.karne.length === 0 ? "—" : defectAdayi > 0 ? `⚠ ${defectAdayi}` : defectAdayi}
          </div>{" "}
          <div className="metrik-etiket">açık defect adayı</div>
          {defectAdayi > 0 && (
            <div className="metrik-alt">
              Assertion kırmızı; PR açılmadı, main koşularına ve bu orana girmez. <IzinliLink to="/kod">Kod üretiminde incele</IzinliLink>
            </div>
          )}
        </div>
        <HedefOlcer
          etiket="Case kabul oranı"
          deger={ai.kabul_orani}
          hedef={ai.kabul_hedefi}
          bosMetin="henüz karar yok"
          ek={<KaynakIpucu kaynak={k.kaynaklar.kabul_orani} />}
        />
        <HedefOlcer
          etiket="Script ilk review başarısı"
          deger={ai.script_ilk_review}
          hedef={ai.script_hedefi}
          bosMetin="henüz merge/review yok"
          ek={<KaynakIpucu kaynak={k.kaynaklar.script_ilk_review} />}
        />
        <Metrik
          etiket={<KpiBaslik ad="Hazırlık kazancı" k={k} anahtar="kazanc_orani" />}
          deger={<span data-testid="hazirlik-kazanci">{kazanc.oran === null ? <Olculmedi metin={kazanc.replay_haric > 0 ? "REPLAY: hesaplanmaz" : "ölçülmüş baz yok"} /> : yuzde(kazanc.oran)}</span>}
          alt={<span data-testid="kazanc-kapsam">{kazanc.kapsam}</span>}
        />
        {/* 012 §4.7: kalite KPI'ları (components/kule). Değer yoksa "ölçülmedi"; sıfır uydurulmaz. */}
        <BeklentiDogruluguKarosu k={k} />
        <HataYakalamaKarosu k={k} />
      </div>

      <div className="kule-izgara">
        <Kart baslik="Geçme oranı" className="kule-oran">
          <p className="soluk">
            {k.gecme_orani.metin
              ? k.gecme_orani.metin
              : k.gecme_orani.toplam === 0
              ? `Henüz sayılan ${k.gecme_orani.birim === "kosu" ? "CI koşusu" : "test sonucu"} yok (kasıtlı kırma koşuları sayılmaz).`
              : k.gecme_orani.birim === "kosu"
                ? `Son ${k.gecme_orani.son_n ?? k.gecme_orani.toplam} CI koşusundan ${k.gecme_orani.gecen}/${k.gecme_orani.toplam} geçti (kasıtlı kırma koşuları hariç)`
                : `${k.gecme_orani.donem_gun ? `Son ${k.gecme_orani.donem_gun} gün · ` : ""}${k.gecme_orani.gecen}/${k.gecme_orani.toplam} test sonucu (kasıtlı kırma koşuları hariç)`}
          </p>
          {k.gecme_orani.test && k.gecme_orani.test.toplam > 0 && (
            <p className="kucuk">
              Test bazında: {k.gecme_orani.test.oran === null ? "—" : yuzde(k.gecme_orani.test.oran)} ({k.gecme_orani.test.gecen}/{k.gecme_orani.test.toplam})
            </p>
          )}
          {k.gunluk_gecme.length > 0 && (
            <OranSutunlari
              baslik="Günlük geçme oranı"
              hedef={k.gecme_hedefi ?? undefined}
              noktalar={k.gunluk_gecme.map((g) => ({
                etiket: new Date(g.tarih).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" }),
                oran: g.oran,
                ek: `${g.kosu} koşu`,
              }))}
            />
          )}
          {k.gecme_hedefi !== null && <p className="kucuk soluk">Kesikli çizgi: {yuzde(k.gecme_hedefi)} hedef.</p>}
        </Kart>

        <Kart baslik="AI katkısı" className="kule-ai">
          {(ai.pass_at_1 !== null || ai.duzeltme_sonrasi !== null) && (
            <p className="kucuk">
              pass@1 {ai.pass_at_1 === null ? "—" : yuzde(ai.pass_at_1)} · düzeltme sonrası {ai.duzeltme_sonrasi === null ? "—" : yuzde(ai.duzeltme_sonrasi)}
            </p>
          )}
          {/* 011 MİM-Y2: doğrulanmamış (C# / Python) script'ler review başarısına girmez; ayrı sayılır. Core vermezse yok. */}
          {typeof ai.script_dogrulanmamis === "number" && (
            <p className="kucuk" data-testid="script-dogrulanmamis">
              {ai.script_dogrulanmamis} doğrulanmamış script (C# / Python: derlenmedi, koşulmadı) ·{" "}
              <span className="soluk">review başarısına ve pass@1'e girmez</span>
            </p>
          )}
          <div className="metrik-izgara">
            <Metrik
              etiket={<KpiBaslik ad="Case başına AI + review" k={k} anahtar="hazirlik_suresi" />}
              deger={toplamSure === null ? <Olculmedi /> : sure(toplamSure)}
              alt={toplamSure === null ? undefined : `AI ${sure(ai.ort_ai_sure_ms)} · review ${sure(ai.ort_review_sure_ms)}`}
            />
            <Metrik
              etiket={<KpiBaslik ad="Maliyet (toplam)" k={k} anahtar="maliyet" />}
              deger={tumuReplay ? <Olculmedi metin="REPLAY — ölçülmedi" /> : ai.maliyet_usd_toplam === null ? <Olculmedi /> : dolar(ai.maliyet_usd_toplam)}
              alt={ai.cagri_sayisi === null ? undefined : `${ai.cagri_sayisi} model çağrısı`}
            />
            <Metrik
              etiket="Bugün"
              deger={tumuReplay ? <Olculmedi metin="REPLAY — ölçülmedi" /> : ai.maliyet_usd_bugun === null ? <Olculmedi /> : dolar(ai.maliyet_usd_bugun)}
              alt={
                ai.gunluk_butce_usd === null ? undefined : (
                  <>
                    Günlük tavan {dolar(ai.gunluk_butce_usd)}
                    {/* Bütçe çubuğu tavanın altında; maliyet ölçülmediyse (REPLAY) boş ray çizilmez. */}
                    {!tumuReplay && ai.maliyet_usd_bugun !== null && ai.gunluk_butce_usd ? (
                      <Ilerleme oran={ai.maliyet_usd_bugun / ai.gunluk_butce_usd} etiket="Günlük bütçe kullanımı" />
                    ) : null}
                  </>
                )
              }
            />
          </div>
          {ai.replay_cagri !== null && ai.replay_cagri > 0 && (
            <p className="kucuk">
              <span className="rozet rozet-replay">REPLAY</span> {ai.replay_cagri} çağrı girdisi doğrulanmış hazır (golden) çıktıdan karşılandı (süre ve maliyet ölçülmez).
            </p>
          )}
        </Kart>

        <Kart baslik="Erişilebilirlik" eylemler={<KaynakIpucu kaynak={k.kaynaklar.a11y} />} className="kule-a11y">
          {k.a11y === null ? (
            <BosDurum baslik="Erişilebilirlik taraması yapılmadı.">
              <span className="soluk kucuk">İhlal sayısı ölçülmedi; sayı gösterilmez.</span>
            </BosDurum>
          ) : (
            <>
              <div className="metrik-izgara">
                <Metrik etiket="İhlal" deger={<span data-testid="a11y-ihlal">{k.a11y.ihlal}</span>} />
                <Metrik etiket="Kritik" deger={k.a11y.kritik > 0 ? <span className="hata-metin">{k.a11y.kritik}</span> : 0} />
              </div>
              {k.a11y.sayfalar.length > 0 && (
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
              )}
              <p className="kucuk soluk">axe-core · WCAG 2.2 AA · son tarama {k.a11y.son_tarama ? tarih(k.a11y.son_tarama) : "—"}</p>
            </>
          )}
        </Kart>

        <Kart baslik="Flaky testler" eylemler={<KaynakIpucu kaynak={k.kaynaklar.flaky} />} className="kule-flaky">
          {k.flaky.length === 0 ? (
            <BosDurum baslik="Flaky test yok." />
          ) : (
            <ul className="duz-liste">
              {k.flaky.map((f) => (
                <li key={f.test_adi}>
                  <div>{f.test_adi}</div>
                  <div className="kucuk soluk">
                    {f.neden === "retry" ? "Yeniden denemeyle geçti" : "Aynı commit'te sonuç değişti"} · {f.sayi} kez
                    {f.son_gorulme && ` · son ${tarih(f.son_gorulme)}`}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Kart>

        {/* 012 §13.2: onaylı ama güncel tabloyla uyuşmayan case'ler (çekirdek anahtarı sunmuyorsa çizilmez). */}
        <OnayliUyumsuzKarti k={k} />

        {/* 012 §4.6: ekilmiş hata koşusu (başlat, ilerleme, hata × platform tablosu, kaçan hatalar). */}
        <HataKosusuKarti olcuDegisti={() => void v.yenile(true)} olculenKosuId={v.veri?.hata_yakalama?.son_kosu.id ?? null} />
      </div>

      {k.hazirlik.length > 0 && <HazirlikKarti k={k} kazanc={kazanc} />}

      {/* 011 K21: case kalitesi (uç yoksa bölüm çizilmez). */}
      <CaseKalitesiBolumu />

      <Kart baslik="Karne (story ve uygulama alanı)" eylemler={<KaynakIpucu kaynak={k.kaynaklar.karne} />}>
        {k.karne.length === 0 ? (
          <BosDurum baslik="Karne için story yok." />
        ) : (
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
                  <th scope="col">Son sonuç (main)</th>
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
                    <td>{s.alan ?? "—"}</td>
                    <td className="sayi">{s.case_sayisi}</td>
                    <td>
                      {s.otomasyon_kapsami === null ? (
                        <Olculmedi metin="case yok" />
                      ) : (
                        <div className="kapsam">
                          <Ilerleme oran={s.otomasyon_kapsami} etiket={`${s.story_key} otomasyon kapsamı`} />
                          <span className="mono kucuk">{yuzde(s.otomasyon_kapsami)}</span>
                        </div>
                      )}
                    </td>
                    <td>
                      {s.son_sonuc === "none" ? (
                        "—"
                      ) : (
                        <Cip ton={s.son_sonuc === "passed" ? "basari" : "hata"}>{s.son_sonuc === "passed" ? "Geçti" : "Başarısız"}</Cip>
                      )}
                      {s.acik_defect_adayi > 0 && (
                        <>
                          {" "}
                          <Cip ton="uyari" title="Yerel kontrolde assertion kırmızı: uygulama onaylı case'in beklenen değerini vermiyor. PR açılmadı; main sonucuna girmez.">
                            {s.acik_defect_adayi} defect adayı
                          </Cip>
                        </>
                      )}
                    </td>
                    <td className="sayi" data-testid={`karne-bug-${s.story_key}`}>
                      {s.acik_bug || "—"}
                      {s.bug_taslagi > 0 && (
                        <>
                          {" "}
                          <span className="kucuk" title="Henüz Jira'da açılmamış (taslak/onaylı) bug taslağı; kasıtlı kırma koşusu taslakları hariç.">
                            · taslak {s.bug_taslagi}
                          </span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Kart>

      <OnerilerOlcumKarti kule={k} />

      <PlatformDagilimiKarti scriptler={scriptler.veri ?? null} secim={secim} />

      <Kart baslik="Son koşular" eylemler={<KaynakIpucu kaynak={k.kaynaklar.son_kosular} />}>
        {k.son_kosular.length === 0 ? (
          <BosDurum baslik="Henüz koşu yok." />
        ) : sonKosular.length === 0 ? (
          <BosDurum baslik={`${secim === "tumu" ? "" : `${PLATFORM_ETIKETI[secim]} için `}koşu yok.`} />
        ) : (
          <KosuTablosu kosular={sonKosular} kompakt />
        )}
        {platformsuzKosu > 0 && (
          <p className="kucuk soluk" data-testid="platformsuz-kosu">
            {platformsuzKosu} koşunun platformu bilinmiyor (çekirdek bildirmedi); süzgeçte yalnız “Tümü”nde görünür.
          </p>
        )}
      </Kart>
    </>
  );
}

/** Story bazında hazırlık süresi ve baz değer; kazanç yalnızca ölçülmüş baz değerli satırlarda. */
function HazirlikKarti({ k, kazanc }: { k: Kule; kazanc: KazancOzeti }) {
  return (
    <Kart baslik="Hazırlık süresi (story bazında)" eylemler={<KaynakIpucu kaynak={k.kaynaklar.hazirlik_suresi} />}>
      <p className="soluk kucuk">
        AI + review süresi story'nin ölçülmüş manuel baz değeriyle karşılaştırılır. Baz değer story ekranından (Gereksinim detayı →
        Manuel baz değer) girilir; varsayılan ya da ölçülmemiş baz değerle kazanç hesaplanmaz.
      </p>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Story bazında hazırlık tablosu">
        <table className="tablo hazirlik-tablo">
          <thead>
            <tr>
              <th scope="col">Story</th>
              <th scope="col">AI + review</th>
              <th scope="col">
                Manuel baz <KaynakIpucu kaynak={k.kaynaklar.manuel_baz} />
              </th>
              <th scope="col" className="sayi">
                Kazanç
              </th>
            </tr>
          </thead>
          <tbody>
            {kazanc.storyler.map(({ satir: h, sure_ms, yalniz_review, kazanc: oran }) => {
              const bk = BAZ_KAYNAGI[h.baz_kaynagi];
              return (
                <tr key={h.requirement_id || h.story_key || ""} data-testid={`hazirlik-${h.story_key ?? h.requirement_id}`}>
                  <td>
                    {h.requirement_id ? (
                      <IzinliLink to={`/gereksinimler/${encodeURIComponent(h.requirement_id)}`} className="mono">
                        {h.story_key ?? "serbest metin"}
                      </IzinliLink>
                    ) : (
                      <span className="mono">{h.story_key ?? "—"}</span>
                    )}
                  </td>
                  <td>
                    {sure_ms === null ? <Olculmedi /> : sure(sure_ms)}
                    {yalniz_review && sure_ms !== null && (
                      <span className="kucuk soluk" title="REPLAY: AI süresi ölçülmez; süre yalnız insan review süresidir.">
                        {" "}
                        (REPLAY: yalnız review)
                      </span>
                    )}
                  </td>
                  <td>
                    {/* Ölçülmemiş baz yalnız "Ölçülmedi" çipiyle (aynı hücrede iki kez "ölçülmedi" yazılmaz). */}
                    {h.manuel_baz_ms !== null ? sure(h.manuel_baz_ms) : h.baz_kaynagi === "olculmedi" ? null : <Olculmedi />}
                    <Cip ton={bk.ton} title={bk.aciklama}>
                      {bk.etiket}
                    </Cip>
                  </td>
                  <td className="sayi">{oran === null ? "—" : yuzde(oran)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="kucuk">{kazanc.kapsam}</p>
    </Kart>
  );
}

import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { HataSinifi, Kosu, KosuDetay as KosuDetayTuru, KosuHatasi, KosuKaynagi, Tetik } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, Metrik, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { HATA_SINIFI, KAYNAK, KOSU_DURUMU, TETIK } from "../lib/etiketler";
import { sure, tarih } from "../lib/format";

const TETIK_TONU: Partial<Record<Tetik, "notr" | "bilgi" | "vurgu" | "uyari">> = {
  nightly: "bilgi",
  deploy: "vurgu",
  break_verify: "uyari",
  local_check: "notr",
};

/** İş kullanıcısına kısa koşu adı: UUID'nin ilk 8 hanesi (tamamı ipucunda). */
export function kisaKosuAdi(id: string): string {
  return /^[0-9a-f]{8}-/i.test(id) ? id.slice(0, 8) : id;
}

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
                <Link to={`/kosular/${encodeURIComponent(k.id)}`} className="satir-baglanti mono" title={`Koşu kimliği: ${k.id}`}>
                  {kisaKosuAdi(k.id)}
                </Link>
                {k.break_campaign && (
                  <Cip ton="uyari" title="Uygulama BREAK_CAMPAIGN=1 ile koştu (kasıtlı kırma)">
                    kırma
                  </Cip>
                )}
              </td>
              <td>
                <Cip ton={TETIK_TONU[k.tetik] ?? "notr"}>{TETIK[k.tetik] ?? k.tetik}</Cip>
                {k.pr_no !== null && <span className="mono"> #{k.pr_no}</span>}
              </td>
              {!kompakt && (
                <td>
                  <Cip ton={k.kaynak === "sauce" ? "vurgu" : k.kaynak === "github" ? "bilgi" : "notr"}>{KAYNAK[k.kaynak] ?? k.kaynak}</Cip>
                </td>
              )}
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

type Filtre = { tetik: Tetik | ""; kaynak: KosuKaynagi | ""; durum: Kosu["durum"] | ""; kirma: boolean };

/** Koşu listesinin süzgeci (adres çubuğunda: ?tetik=&kaynak=&durum=&kirma=1). */
export function kosulariSuz(kosular: Kosu[], f: Filtre): Kosu[] {
  return kosular.filter(
    (k) =>
      (!f.tetik || k.tetik === f.tetik) &&
      (!f.kaynak || k.kaynak === f.kaynak) &&
      (!f.durum || k.durum === f.durum) &&
      (f.kirma || !k.break_campaign || f.tetik === "break_verify"),
  );
}

export function Kosular() {
  const v = useVeri(() => api.kosular(), []);
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["ci.status", "failure.classified"]);
  const [sorgu, setSorgu] = useSearchParams();
  const [sonTetik, setSonTetik] = useState<string | null>(null);
  const filtre: Filtre = {
    tetik: (sorgu.get("tetik") ?? "") as Filtre["tetik"],
    kaynak: (sorgu.get("kaynak") ?? "") as Filtre["kaynak"],
    durum: (sorgu.get("durum") ?? "") as Filtre["durum"],
    kirma: sorgu.get("kirma") !== "0",
  };
  const ayarla = (anahtar: string, deger: string) => {
    const y = new URLSearchParams(sorgu);
    if (deger) y.set(anahtar, deger);
    else y.delete(anahtar);
    setSorgu(y, { replace: true });
  };
  const tum = v.veri ?? [];
  const suzulen = useMemo(() => kosulariSuz(tum, filtre), [tum, filtre.tetik, filtre.kaynak, filtre.durum, filtre.kirma]);
  const tetikler = [...new Set(tum.map((k) => k.tetik))];
  // Kırma koşusu yoksa süzgeç işe yaramaz: gösterilmez (yerel kontrol / kırarak doğrulama koşuları
  // koşu tablosuna alındığında görünür hale gelir).
  const kirmaVar = tum.some((k) => k.break_campaign);
  const kaynaklar = [...new Set(tum.map((k) => k.kaynak))];

  const tetikle = async (tetik: "deploy" | "nightly") => {
    const s = await islem.calistir(() => api.ciTetikle(tetik));
    if (s) {
      bildir(s.mesaj ?? "Koşu tetiklendi.");
      setSonTetik(s.mesaj ?? `${tetik === "deploy" ? "Deploy" : "Gece"} koşusu tetiklendi.`);
      void v.yenile(true);
    }
  };

  return (
    <>
      <SayfaBasligi
        baslik="Koşular"
        aciklama="CI yalnızca onaylı, deterministik test kodunu koşturur; CI'da AI yoktur. Yerel test-runner her zaman koşar; GitHub Actions ve Sauce Labs kimlik bilgileri varsa aynı testleri koşturur."
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
      {sonTetik && !islem.hata && <Uyari ton="bilgi">{sonTetik}</Uyari>}
      <Kart>
        {v.yukleniyor && !v.veri ? (
          <Yukleniyor />
        ) : v.hata && !v.veri ? (
          <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />
        ) : tum.length === 0 ? (
          <BosDurum baslik="Henüz koşu yok." />
        ) : (
          <>
            <div className="filtre-cubugu" role="group" aria-label="Koşu süzgeci">
              <label>
                Tetik
                <select value={filtre.tetik} onChange={(e) => ayarla("tetik", e.target.value)}>
                  <option value="">Tümü</option>
                  {tetikler.map((t) => (
                    <option key={t} value={t}>
                      {TETIK[t] ?? t}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Kaynak
                <select value={filtre.kaynak} onChange={(e) => ayarla("kaynak", e.target.value)}>
                  <option value="">Tümü</option>
                  {kaynaklar.map((k) => (
                    <option key={k} value={k}>
                      {KAYNAK[k] ?? k}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Durum
                <select value={filtre.durum} onChange={(e) => ayarla("durum", e.target.value)}>
                  <option value="">Tümü</option>
                  {(["queued", "running", "passed", "failed", "error"] as const).map((d) => (
                    <option key={d} value={d}>
                      {KOSU_DURUMU[d].etiket}
                    </option>
                  ))}
                </select>
              </label>
              {kirmaVar && (
                <label className="satir-ogeler">
                  <span>
                    <input type="checkbox" checked={filtre.kirma} onChange={(e) => ayarla("kirma", e.target.checked ? "" : "0")} /> Kasıtlı kırma koşuları
                  </span>
                </label>
              )}
              <span className="soluk kucuk" role="status">
                {suzulen.length}/{tum.length} koşu
              </span>
            </div>
            {suzulen.length ? <KosuTablosu kosular={suzulen} /> : <BosDurum baslik="Süzgece uyan koşu yok." />}
          </>
        )}
      </Kart>
    </>
  );
}

function SinifCipi({ sinif, alt }: { sinif: HataSinifi | null; alt: string | null }) {
  if (!sinif) return <Cip ton="notr">sınıflandırılıyor</Cip>;
  const x = HATA_SINIFI[sinif] ?? { etiket: sinif, ton: "notr" as const };
  return (
    <Cip ton={x.ton}>
      {x.etiket}
      {alt ? ` · ${alt}` : ""}
    </Cip>
  );
}

/**
 * Koşunun triage kayıtları: core `hatalar` listesi (test sonucuna bağlı olmayan ortam hatası dahil)
 * ya da sonuçlardaki `failure_id`'ler (aynı imzalı başarısızlıklar tek kayıtta toplanır).
 */
export function kosuHatalari(k: Pick<KosuDetayTuru, "hatalar" | "sonuclar">): KosuHatasi[] {
  if (k.hatalar) return k.hatalar;
  const gorulen = new Map<string, KosuHatasi>();
  for (const s of k.sonuclar) {
    if (!s.failure_id) continue;
    const var_ = gorulen.get(s.failure_id);
    if (var_) var_.test_adi = `${var_.test_adi} · ${s.test_adi}`;
    else gorulen.set(s.failure_id, { id: s.failure_id, test_adi: s.test_adi, sinif: s.triage_sinifi ?? null, alt_tur: s.triage_alt_tur ?? null, ozet: null });
  }
  return [...gorulen.values()];
}

function HataListesi({ k }: { k: KosuDetayTuru }) {
  const hatalar = kosuHatalari(k);
  if (hatalar.length === 0) return null;
  return (
    <Kart baslik="Başarısızlıklar ve triage">
      <ul className="duz-liste" aria-label="Triage kayıtları">
        {hatalar.map((h) => (
          <li key={h.id} className="satir-ogeler">
            <SinifCipi sinif={h.sinif} alt={h.alt_tur} />
            <span>{h.test_adi}</span>
            {h.ozet && <span className="kucuk soluk">{h.ozet}</span>}
            <Link to={`/hatalar/${encodeURIComponent(h.id)}`}>Triage sonucunu aç</Link>
          </li>
        ))}
      </ul>
    </Kart>
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
        baslik={
          <span title={`Koşu kimliği: ${k.id}`}>
            {TETIK[k.tetik] ?? k.tetik} koşusu <span className="mono">{kisaKosuAdi(k.id)}</span>
          </span>
        }
        aciklama={
          <span className="satir-ogeler">
            <DurumCipi d={k.durum} />
            <Cip ton={TETIK_TONU[k.tetik] ?? "notr"}>
              {TETIK[k.tetik] ?? k.tetik}
              {k.pr_no !== null && ` #${k.pr_no}`}
            </Cip>
            <Cip ton={k.kaynak === "sauce" ? "vurgu" : k.kaynak === "github" ? "bilgi" : "notr"}>{KAYNAK[k.kaynak] ?? k.kaynak}</Cip>
            <span className="mono">{k.commit}</span>
            <span className="soluk">{tarih(k.baslangic)}</span>
          </span>
        }
      />
      {k.break_campaign && <Uyari>Bu koşuda kampanya kuralı koşunun bayisi için BREAK_CAMPAIGN ile bozuldu (kasıtlı kırma); başarısızlık beklenir.</Uyari>}
      {k.saglik_hatasi && (
        <Uyari ton="hata" baslik="Ortam sorunu">
          Koşu öncesi sağlık yoklaması başarısız; Playwright başlatılmadı: {k.saglik_hatasi}
        </Uyari>
      )}
      <Kart baslik="Raporlar ve bağlantılar">
        <div className="artefakt-baglantilari">
          <Baglanti href={k.rapor_url} yokNedeni="koşu bu raporu üretmedi ya da core sunmuyor">
            Playwright HTML raporu
          </Baglanti>
          <Baglanti href={k.junit_url ?? null} yokNedeni="koşu JUnit XML üretmedi">
            JUnit XML
          </Baglanti>
          <Baglanti href={k.allure_url} yokNedeni="yok">
            {k.allure_url && /allure-results\/?$/.test(k.allure_url) ? "Allure ham sonuçları (JSON listesi)" : "Allure raporu"}
          </Baglanti>
          {k.allure_sonuclari_url && k.allure_sonuclari_url !== k.allure_url && (
            <Baglanti href={k.allure_sonuclari_url} yokNedeni="yok">
              Allure ham sonuçları (JSON listesi)
            </Baglanti>
          )}
          {(k.kaynak === "sauce" || k.sauce_url) && (
            <Baglanti href={k.sauce_url} yokNedeni="Sauce bağlantısı yok">
              Sauce Labs videosu
            </Baglanti>
          )}
          {(k.kaynak !== "local" || k.ci_url) && (
            <Baglanti href={k.ci_url} yokNedeni="yok">
              CI işi
            </Baglanti>
          )}
          <Baglanti href={k.log_url} yokNedeni="yok">
            Koşu günlüğü
          </Baglanti>
          {k.script_id && <Link to={`/kod/${encodeURIComponent(k.script_id)}`}>Üretilen test</Link>}
        </div>
        {k.hata && <p className="kucuk hata-metin">{k.hata}</p>}
        {k.uyarilar.length > 0 && (
          <ul className="kucuk duz-liste">
            {k.uyarilar.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        )}
      </Kart>
      <Kart>
        <div className="metrik-izgara">
          <Metrik etiket="Toplam" deger={k.toplam} />
          <Metrik etiket="Geçen" deger={k.gecen} />
          <Metrik etiket="Başarısız" deger={k.basarisiz} />
          <Metrik etiket="Flaky" deger={k.flaky} />
          <Metrik etiket="Süre" deger={sure(k.sure_ms)} />
        </div>
      </Kart>
      <HataListesi k={k} />
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
                      {s.ekler && s.ekler.length > 0 && (
                        <div className="satir-ogeler kucuk">
                          {s.ekler.map((e, i) => (
                            <Baglanti key={`${e.ad}-${i}`} href={e.url}>
                              {e.ad}
                            </Baglanti>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <DurumCipi d={s.durum} />
                    </td>
                    <td className="sayi">{s.retry}</td>
                    <td>{sure(s.sure_ms)}</td>
                    <td>
                      {s.failure_id ? (
                        <span className="satir-ogeler">
                          {s.triage_sinifi && <SinifCipi sinif={s.triage_sinifi} alt={s.triage_alt_tur ?? null} />}
                          <Link to={`/hatalar/${encodeURIComponent(s.failure_id)}`}>Triage sonucu</Link>
                        </span>
                      ) : s.durum === "failed" ? (
                        <span className="soluk kucuk">sınıflandırılıyor</span>
                      ) : (
                        "—"
                      )}
                    </td>
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

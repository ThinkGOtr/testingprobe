import { Fragment, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { KosuDetay, PwAdimi, TestDenemesi, TestSonucu } from "../api/types";
import { Baglanti, BosDurum, Cip, DisBaglanti, Kart, IzinliLink } from "../components/ui";
import { altTurEtiketi, HATA_SINIFI, KOSU_DURUMU } from "../lib/etiketler";
import { sure } from "../lib/format";

/**
 * Koşu detayındaki test sonuçları: süzgeç (durum, arama, dosya, sıralama — adres çubuğunda),
 * satır açılınca okunur ayrıntı (hata + stack, Playwright adımları, denemeler, ekler, çıktı) ve
 * CI adımlarının özeti. Ham JUnit/JSON/allure dosyalarını açmadan aynı bilgi okunur.
 */

export type SonucDurumu = TestSonucu["durum"];
export type Siralama = "durum" | "ad" | "sure";

export interface SonucFiltresi {
  durum: SonucDurumu | "";
  ara: string;
  dosya: string;
  sirala: Siralama;
  yalnizBasarisiz: boolean;
}

const DURUMLAR: SonucDurumu[] = ["passed", "failed", "flaky", "skipped"];
const DURUM_SIRASI: Record<SonucDurumu, number> = { failed: 0, flaky: 1, passed: 2, skipped: 3 };
const DURUM_ETIKETI: Record<SonucDurumu, string> = { passed: "Geçen", failed: "Başarısız", flaky: "Flaky", skipped: "Atlanan" };
const SIRALAMALAR: { deger: Siralama; etiket: string }[] = [
  { deger: "durum", etiket: "Duruma göre" },
  { deger: "sure", etiket: "Süreye göre (uzun önce)" },
  { deger: "ad", etiket: "Ada göre" },
];

/** Adres çubuğu: ?t_durum=&t_ara=&t_dosya=&t_sirala=&t_basarisiz=1 (Koşular süzgeciyle aynı desen). */
export function sonucFiltresiOku(sorgu: URLSearchParams): SonucFiltresi {
  const durum = sorgu.get("t_durum") ?? "";
  const sirala = sorgu.get("t_sirala") ?? "";
  return {
    durum: (DURUMLAR as string[]).includes(durum) ? (durum as SonucDurumu) : "",
    ara: sorgu.get("t_ara") ?? "",
    dosya: sorgu.get("t_dosya") ?? "",
    sirala: sirala === "ad" || sirala === "sure" ? sirala : "durum",
    yalnizBasarisiz: sorgu.get("t_basarisiz") === "1",
  };
}

const kucult = (x: string) => x.toLocaleLowerCase("tr");

/** Testin spec dosyası (core `dosya`; yoksa adın ilk " › " parçası .spec ise o). */
export function sonucDosyasi(s: TestSonucu): string {
  if (s.dosya) return s.dosya;
  const ilk = s.test_adi.split(" › ")[0];
  return /\.(spec|test)\.[cm]?[jt]sx?$/.test(ilk) ? ilk : "";
}

function aranacakMetin(s: TestSonucu): string {
  const denemeHatalari = (s.denemeler ?? []).map((d) => `${d.hata?.mesaj ?? ""} ${d.hata?.konum ?? ""}`).join(" ");
  return kucult(`${s.test_adi} ${sonucDosyasi(s)} ${s.hata_mesaji ?? ""} ${denemeHatalari}`);
}

/** Saf süzgeç + sıralama (test edilebilir). */
export function sonuclariSuz(sonuclar: TestSonucu[], f: SonucFiltresi): TestSonucu[] {
  const ara = kucult(f.ara.trim());
  const suzulen = sonuclar.filter(
    (s) =>
      (!f.durum || s.durum === f.durum) &&
      (!f.yalnizBasarisiz || s.durum === "failed") &&
      (!f.dosya || sonucDosyasi(s) === f.dosya) &&
      (!ara || aranacakMetin(s).includes(ara)),
  );
  const adla = (a: TestSonucu, b: TestSonucu) => a.test_adi.localeCompare(b.test_adi, "tr");
  const sirali = [...suzulen];
  if (f.sirala === "ad") sirali.sort(adla);
  else if (f.sirala === "sure") sirali.sort((a, b) => b.sure_ms - a.sure_ms || adla(a, b));
  else sirali.sort((a, b) => DURUM_SIRASI[a.durum] - DURUM_SIRASI[b.durum] || adla(a, b));
  return sirali;
}

export function sonucSayaclari(sonuclar: TestSonucu[]): Record<SonucDurumu | "tumu", number> {
  const s = { tumu: sonuclar.length, passed: 0, failed: 0, flaky: 0, skipped: 0 };
  for (const x of sonuclar) s[x.durum] += 1;
  return s;
}

function DurumCipi({ d }: { d: string }) {
  const x = KOSU_DURUMU[d] ?? { etiket: d, ton: "notr" as const };
  return <Cip ton={x.ton}>{x.etiket}</Cip>;
}

// ------------------------------------------------------------------ ayrıntı paneli

/** Adım ağacında hatalı adım var mı (hatalı yol vurgulanır). */
export function adimHatali(a: PwAdimi): boolean {
  return Boolean(a.hata) || (a.adimlar ?? []).some(adimHatali);
}

function Adimlar({ adimlar }: { adimlar: PwAdimi[] }) {
  return (
    <ol className="pw-adimlar">
      {adimlar.map((a, i) => {
        const hatali = adimHatali(a);
        return (
          <li key={i} className={hatali ? "pw-adim pw-adim-hata" : "pw-adim"} data-hatali={hatali ? "1" : undefined}>
            <span className="satir-ogeler">
              <span aria-hidden="true">{hatali ? "✗" : "✓"}</span>
              <span>{a.baslik || "(adsız adım)"}</span>
              <span className="soluk kucuk">{sure(a.sure_ms)}</span>
              {hatali && <span className="gorunmez"> (başarısız adım)</span>}
            </span>
            {a.hata && <pre className="hata-mesaji">{a.hata}</pre>}
            {a.adimlar && a.adimlar.length > 0 && <Adimlar adimlar={a.adimlar} />}
          </li>
        );
      })}
    </ol>
  );
}

type Ek = NonNullable<TestSonucu["ekler"]>[number];

export function ekTuru(e: Ek): "resim" | "video" | "iz" | "diger" {
  const tur = e.tur ?? "";
  const url = e.url ?? "";
  if (tur.startsWith("image/") || /\.(png|jpe?g|gif|webp)$/i.test(url)) return "resim";
  if (tur.startsWith("video/") || /\.webm$/i.test(url)) return "video";
  if (e.ad === "trace" || /trace\.zip$/i.test(url)) return "iz";
  return "diger";
}

function Ekler({ ekler }: { ekler: Ek[] }) {
  if (ekler.length === 0) return null;
  return (
    <div className="test-ekleri">
      {ekler.map((e, i) => {
        const tur = ekTuru(e);
        const anahtar = `${e.ad}-${i}`;
        if (!e.url) {
          return (
            <span key={anahtar} className="soluk kucuk">
              {e.ad} (dosya sunulmuyor)
            </span>
          );
        }
        if (tur === "resim") {
          return (
            <figure key={anahtar} className="test-ek-resim">
              <a href={e.url} target="_blank" rel="noreferrer noopener">
                <img src={e.url} alt={`Ekran görüntüsü: ${e.ad}`} loading="lazy" />
              </a>
              <figcaption className="kucuk soluk">{e.ad}</figcaption>
            </figure>
          );
        }
        if (tur === "video") {
          return (
            <figure key={anahtar} className="test-ek-video">
              <video controls preload="metadata" src={e.url} aria-label={`Video: ${e.ad}`} />
              <figcaption className="kucuk soluk">{e.ad}</figcaption>
            </figure>
          );
        }
        if (tur === "iz") {
          return (
            <div key={anahtar} className="kucuk">
              <a href={e.url} download>
                Playwright trace'i indir ({e.ad})
              </a>
              <p className="soluk">
                Açmak için: <span className="mono">npx playwright show-trace trace.zip</span> ya da dosyayı{" "}
                <DisBaglanti href="https://trace.playwright.dev">trace.playwright.dev</DisBaglanti>'e sürükleyin (dosya tarayıcıda açılır,
                yüklenmez).
              </p>
            </div>
          );
        }
        return (
          <Baglanti key={anahtar} href={e.url}>
            {e.ad}
          </Baglanti>
        );
      })}
    </div>
  );
}

function Deneme({ d, ekler, tekDeneme }: { d: TestDenemesi; ekler: Ek[]; tekDeneme: boolean }) {
  const basarisiz = d.sonuc !== "passed" && d.sonuc !== "skipped";
  const icerik = (
    <>
      {d.hata?.mesaj && <pre className="hata-mesaji">{d.hata.mesaj}</pre>}
      {d.hata?.konum && <p className="kucuk mono">{d.hata.konum}</p>}
      {d.hata?.snippet && <pre className="kod-blok">{d.hata.snippet}</pre>}
      {d.hata?.stack && (
        <details className="test-blok">
          <summary>Stack</summary>
          <pre className="kod-blok">{d.hata.stack}</pre>
        </details>
      )}
      {d.adimlar && d.adimlar.length > 0 && (
        <section aria-label={`Adımlar (deneme ${d.deneme + 1})`}>
          <h4 className="kucuk">Adımlar</h4>
          <Adimlar adimlar={d.adimlar} />
        </section>
      )}
      <Ekler ekler={ekler} />
      {d.stdout && (
        <details className="test-blok">
          <summary>stdout</summary>
          <pre className="kod-blok">{d.stdout}</pre>
        </details>
      )}
      {d.stderr && (
        <details className="test-blok">
          <summary>stderr</summary>
          <pre className="kod-blok">{d.stderr}</pre>
        </details>
      )}
    </>
  );
  if (tekDeneme) return icerik;
  return (
    <details className="test-deneme" open={basarisiz}>
      <summary>
        <span className="satir-ogeler">
          <span>Deneme {d.deneme + 1}</span>
          <DurumCipi d={d.sonuc === "timedOut" ? "failed" : d.sonuc} />
          <span className="soluk kucuk">{sure(d.sure_ms)}</span>
        </span>
      </summary>
      {icerik}
    </details>
  );
}

export function TestAyrintisi({ s }: { s: TestSonucu }) {
  const denemeler = s.denemeler ?? [];
  const ekler = s.ekler ?? [];
  const dosya = sonucDosyasi(s);
  // Ekler denemeye göre dağıtılır; deneme bilgisi olmayanlar sona.
  const denemeEki = (n: number) => ekler.filter((e) => e.deneme === n);
  const sahipsiz = ekler.filter((e) => e.deneme === null || e.deneme === undefined || !denemeler.some((d) => d.deneme === e.deneme));
  return (
    <div className="test-ayrinti" role="region" aria-label={`Test ayrıntısı: ${s.test_adi}`}>
      {dosya && <p className="kucuk mono">{dosya}</p>}
      {denemeler.length === 0 && s.hata_mesaji && <pre className="hata-mesaji">{s.hata_mesaji}</pre>}
      {denemeler.map((d) => (
        <Deneme key={d.deneme} d={d} ekler={denemeEki(d.deneme)} tekDeneme={denemeler.length === 1} />
      ))}
      <Ekler ekler={sahipsiz} />
      {denemeler.length === 0 && ekler.length === 0 && !s.hata_mesaji && <p className="soluk kucuk">Bu test için ayrıntı (adım, ek, çıktı) yok.</p>}
    </div>
  );
}

// ------------------------------------------------------------------ tablo + süzgeç

function SinifCipi({ s }: { s: TestSonucu }) {
  if (!s.triage_sinifi) return null;
  const x = HATA_SINIFI[s.triage_sinifi] ?? { etiket: s.triage_sinifi, ton: "notr" as const };
  return (
    <Cip ton={x.ton}>
      {x.etiket}
      {s.triage_alt_tur ? ` · ${altTurEtiketi(s.triage_alt_tur)}` : ""}
    </Cip>
  );
}

export function TestSonuclari({ k }: { k: KosuDetay }) {
  const [sorgu, setSorgu] = useSearchParams();
  const f = sonucFiltresiOku(sorgu);
  const [acik, setAcik] = useState<Set<string>>(() => new Set());
  const ayarla = (anahtar: string, deger: string) => {
    const y = new URLSearchParams(sorgu);
    if (deger) y.set(anahtar, deger);
    else y.delete(anahtar);
    setSorgu(y, { replace: true });
  };
  const sayac = useMemo(() => sonucSayaclari(k.sonuclar), [k.sonuclar]);
  const dosyalar = useMemo(() => [...new Set(k.sonuclar.map(sonucDosyasi).filter(Boolean))].sort(), [k.sonuclar]);
  const suzulen = useMemo(() => sonuclariSuz(k.sonuclar, f), [k.sonuclar, f.durum, f.ara, f.dosya, f.sirala, f.yalnizBasarisiz]);
  const degistir = (id: string) =>
    setAcik((eski) => {
      const y = new Set(eski);
      if (y.has(id)) y.delete(id);
      else y.add(id);
      return y;
    });

  if (k.sonuclar.length === 0) {
    return (
      <Kart baslik="Test sonuçları">
        <BosDurum baslik={k.durum === "queued" || k.durum === "running" ? "Koşu sürüyor…" : "Sonuç yok."} />
      </Kart>
    );
  }
  return (
    <Kart baslik="Test sonuçları">
      <div className="filtre-cubugu" role="group" aria-label="Test sonucu süzgeci">
        <div className="satir-ogeler" role="group" aria-label="Duruma göre">
          {(["", ...DURUMLAR] as const).map((d) => {
            const secili = f.durum === d;
            const n = d ? sayac[d] : sayac.tumu;
            return (
              <button
                key={d || "tumu"}
                type="button"
                className={secili ? "dugme dugme-kucuk dugme-birincil" : "dugme dugme-kucuk dugme-ikincil"}
                aria-pressed={secili}
                onClick={() => ayarla("t_durum", d)}
                disabled={d !== "" && n === 0}
              >
                {d ? DURUM_ETIKETI[d] : "Tümü"} ({n})
              </button>
            );
          })}
        </div>
        <label>
          Ara
          <input type="search" value={f.ara} placeholder="Test adı, dosya ya da hata" onChange={(e) => ayarla("t_ara", e.target.value)} />
        </label>
        {dosyalar.length > 1 && (
          <label>
            Dosya
            <select value={f.dosya} onChange={(e) => ayarla("t_dosya", e.target.value)}>
              <option value="">Tümü</option>
              {dosyalar.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          Sırala
          <select value={f.sirala} onChange={(e) => ayarla("t_sirala", e.target.value === "durum" ? "" : e.target.value)}>
            {SIRALAMALAR.map((s) => (
              <option key={s.deger} value={s.deger}>
                {s.etiket}
              </option>
            ))}
          </select>
        </label>
        <label className="satir-ogeler">
          <span>
            <input type="checkbox" checked={f.yalnizBasarisiz} onChange={(e) => ayarla("t_basarisiz", e.target.checked ? "1" : "")} /> Yalnız
            başarısızlar
          </span>
        </label>
        <span className="soluk kucuk" role="status">
          {suzulen.length}/{k.sonuclar.length} test
        </span>
      </div>
      {suzulen.length === 0 ? (
        <BosDurum baslik="Süzgece uyan test yok." />
      ) : (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Test sonuçları tablosu">
          <table className="tablo test-sonuclari">
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
              {suzulen.map((s) => {
                const ac = acik.has(s.id);
                const panel = `test-ayrinti-${s.id}`;
                return (
                  <Fragment key={s.id}>
                    <tr>
                      <td>
                        <button type="button" className="dugme-metin" aria-expanded={ac} aria-controls={ac ? panel : undefined} onClick={() => degistir(s.id)}>
                          <span aria-hidden="true">{ac ? "▾" : "▸"} </span>
                          {s.test_adi}
                        </button>
                        {!ac && s.hata_mesaji && <pre className="hata-mesaji hata-mesaji-kisa">{s.hata_mesaji}</pre>}
                        {!ac && s.ekler && s.ekler.length > 0 && (
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
                      <td className="tek-satir">{sure(s.sure_ms)}</td>
                      <td>
                        {s.failure_id ? (
                          <span className="satir-ogeler">
                            <SinifCipi s={s} />
                            <IzinliLink to={`/hatalar/${encodeURIComponent(s.failure_id)}`}>Triage sonucu</IzinliLink>
                          </span>
                        ) : s.durum === "failed" ? (
                          <span className="soluk kucuk">sınıflandırılıyor</span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                    {ac && (
                      <tr id={panel} className="test-ayrinti-satiri">
                        <td colSpan={5}>
                          <TestAyrintisi s={s} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Kart>
  );
}

// ------------------------------------------------------------------ CI adımları özeti

const ADIM_ADI: Record<string, string> = {
  deps: "Bağımlılıklar",
  tsc: "TypeScript (tsc)",
  eslint: "ESLint",
  ast_guard: "AST koruması",
  run: "Testler (Playwright)",
};

const GH_SONUC_TONU: Record<string, "basari" | "hata" | "uyari" | "notr"> = {
  success: "basari",
  failure: "hata",
  cancelled: "uyari",
  timed_out: "hata",
  skipped: "notr",
  neutral: "notr",
};

/** GitHub job sonucu (`conclusion`) için Türkçe etiket; bilinmeyen değer olduğu gibi gösterilir. */
const GH_SONUC_ETIKETI: Record<string, string> = {
  success: "geçti",
  failure: "kaldı",
  skipped: "atlandı",
  cancelled: "iptal",
  timed_out: "zaman aşımı",
  neutral: "nötr",
};

const META_ETIKETI: Record<string, string> = {
  durum: "Koşu durumu",
  exit_code: "Çıkış kodu",
  playwright: "Playwright",
  tetik: "Tetik",
  event: "GitHub olayı",
  ref: "Ref",
  job: "İş",
  hata: "Hata",
};

/** Yerel CI adımları (toolchain) ya da GitHub işleri + ci-meta.json — ham dosyayı açmadan. */
export function CiAdimlari({ k }: { k: KosuDetay }) {
  const adimlar = k.adimlar ? Object.entries(k.adimlar) : [];
  const gh = k.github;
  const meta = gh ? Object.entries(gh.meta).filter(([a]) => a in META_ETIKETI) : [];
  if (adimlar.length === 0 && !gh && !k.log_url) return null;
  return (
    <Kart baslik="CI adımları">
      {adimlar.length > 0 && (
        <ul className="duz-liste" aria-label="Yerel CI adımları">
          {adimlar.map(([ad, a]) => (
            <li key={ad} className="satir-ogeler">
              <Cip ton={a.atlandi ? "notr" : a.ok ? "basari" : "hata"}>{a.atlandi ? "atlandı" : a.ok ? "geçti" : "kaldı"}</Cip>
              <span>{ADIM_ADI[ad] ?? ad}</span>
              {a.mode && <span className="soluk kucuk">mod: {a.mode}</span>}
              {(a.error || a.reason) && <span className={a.atlandi ? "kucuk soluk" : "kucuk hata-metin"}>{a.error ?? a.reason}</span>}
            </li>
          ))}
        </ul>
      )}
      {gh && gh.isler.length > 0 && (
        <ul className="duz-liste" aria-label="GitHub işleri">
          {gh.isler.map((j, i) => (
            <li key={`${j.ad}-${i}`} className="satir-ogeler">
              <Cip ton={GH_SONUC_TONU[j.sonuc ?? ""] ?? "notr"}>{j.sonuc ? (GH_SONUC_ETIKETI[j.sonuc] ?? j.sonuc) : "—"}</Cip>
              {j.url ? <DisBaglanti href={j.url}>{j.ad}</DisBaglanti> : <span>{j.ad}</span>}
            </li>
          ))}
        </ul>
      )}
      {meta.length > 0 && (
        <dl className="ci-meta kucuk" aria-label="ci-meta.json özeti">
          {meta.map(([a, v]) => (
            <Fragment key={a}>
              <dt>{META_ETIKETI[a]}</dt>
              <dd className={a === "hata" ? "hata-metin" : "mono"}>{v}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {k.log_url && k.log_url.startsWith("/api/") && <GunlukGorunumu url={k.log_url} />}
    </Kart>
  );
}

const GUNLUK_SINIRI = 64 * 1024;

/** Koşu günlüğünün son kısmı (açılınca bir kez yüklenir; oturumlu, aynı köken). */
function GunlukGorunumu({ url }: { url: string }) {
  const [durum, setDurum] = useState<{ metin?: string; hata?: string; yukleniyor?: boolean }>({});
  const yukle = async () => {
    if (durum.metin !== undefined || durum.yukleniyor) return;
    setDurum({ yukleniyor: true });
    try {
      const r = await fetch(url, { credentials: "same-origin" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const t = await r.text();
      setDurum({ metin: t.length > GUNLUK_SINIRI ? `… (ilk ${t.length - GUNLUK_SINIRI} karakter gösterilmiyor)\n${t.slice(-GUNLUK_SINIRI)}` : t });
    } catch (e) {
      setDurum({ hata: e instanceof Error ? e.message : String(e) });
    }
  };
  return (
    <details className="test-blok" onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && void yukle()}>
      <summary>Koşu günlüğünü burada göster</summary>
      {durum.yukleniyor && <p className="soluk kucuk">Yükleniyor…</p>}
      {durum.hata && <p className="kucuk hata-metin">Günlük okunamadı: {durum.hata}</p>}
      {durum.metin !== undefined && <pre className="kod-blok gunluk">{durum.metin || "(boş)"}</pre>}
    </details>
  );
}

// ------------------------------------------------------------------ GitHub yerel kopya notu

/** GitHub koşusunda raporların yerel kopyası yoksa kısa not (bağlantılar GitHub'a düşer); yoksa null. */
export function githubYedekNotu(k: Pick<KosuDetay, "kaynak" | "github_artefakt">): string | null {
  const g = k.github_artefakt;
  if (k.kaynak !== "github" || !g || g.durum === "indirildi" || g.durum === "mevcut") return null;
  if (g.durum === "budandi") return "Raporların yerel kopyası saklama süresi dolduğu için silindi; bağlantılar GitHub'daki artefakta gider.";
  return `Raporlar portala alınamadı${g.hata ? ` (${g.hata})` : ""}; bağlantılar GitHub'daki artefakta gider.`;
}

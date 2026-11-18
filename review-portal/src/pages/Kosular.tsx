import { teknikMetniCevir } from "../lib/kullaniciMetni";
import { BaskaProjedeKayit } from "../components/BaskaProjedeKayit";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { BasarisizOzeti, HataSinifi, Kosu, KosuDetay as KosuDetayTuru, KosuHatasi, KosuKaynagi, Tetik } from "../api/types";
import { useIzin, useOturum, usePlatformlar } from "../auth";
import { normalizeRol } from "../lib/yetki";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, Baglanti, HataKutusu, KayitHatasi, IslemDugmesi, Kart, Metrik, SayfaBasligi, Uyari, Yukleniyor, IzinliLink } from "../components/ui";
import { Kimlik, KisaDeger, MetaSatiri, TabloSarici } from "../components/tasarim";
import { DetaySayfasi, OzetKarti, type DetaySekmesi } from "../components/DetaySayfasi";
import "../stiller/detay-kosu-hata.css";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { altTurEtiketi, HATA_SINIFI, KAYNAK, KOSU_DURUMU, TETIK } from "../lib/etiketler";
import { sure, tarih } from "../lib/format";
import { CiAdimlari, githubYedekNotu, TestSonuclari } from "./KosuSonuclari";
import { PlatformRozeti } from "../components/Platform";
import { DepoCipi, depoGosterimi } from "../components/Depo";
import { DilRozeti } from "../components/Dil";
import { checkEtiketi, PLATFORMLAR, PLATFORM_ETIKETI, platformaGoreSuz, platformSecimiOku, type Platform } from "../lib/platform";
import { EkilmisHataCipi } from "../components/kule/EkilmisHataCipi";
import { SuzgecSecimi, suzgecSecenekleri } from "../components/Suzgec";
import { DIL_ETIKETI, DILLER, type Dil } from "../lib/dil";
import { OrtamRozeti, OrtamSecici, OrtamSuzgeci, suzgecOrtamlari, useOrtamlar } from "../components/Ortam";
import { ortamMetni } from "../lib/ortam";

const TETIK_TONU: Partial<Record<Tetik, "notr" | "bilgi" | "vurgu" | "uyari">> = {
  nightly: "notr",
  deploy: "notr",
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

/**
 * Takılmış koşu uyarısı eşikleri: bu süreden uzun "Sırada" / "Koşuyor" kalan koşu uyarı alır.
 * GitHub gece koşusu da artık core'dan `workflow_dispatch` ile hemen başlatılır (GitHub cron'u
 * beklenmez): 1 saatte başlamayan gece koşusu da uyarı alır; core 1 saatte GitHub'da bulamazsa
 * koşuyu `error` ile kapatır (`TP_CI_GITHUB_BULMA_S`).
 */
export const TAKILMA_ESIGI_MS = { queued: 60 * 60 * 1000, running: 6 * 60 * 60 * 1000 } as const;

/** "3 saattir sırada — takılmış olabilir"; eşik altında ya da bitmiş koşuda null. */
export function takilmaUyarisi(k: Pick<Kosu, "durum" | "baslangic"> & Partial<Pick<Kosu, "tetik" | "kaynak">>, simdi = Date.now()): string | null {
  if (k.durum !== "queued" && k.durum !== "running") return null;
  const t = Date.parse(k.baslangic);
  if (Number.isNaN(t)) return null;
  const gecen = simdi - t;
  const esik = TAKILMA_ESIGI_MS[k.durum];
  if (gecen < esik) return null;
  const saat = Math.floor(gecen / 3_600_000);
  const sure = saat >= 48 ? `${Math.floor(saat / 24)} gündür` : `${saat} saattir`;
  return `${sure} ${k.durum === "queued" ? "sırada" : "çalışıyor"} — takılmış olabilir`;
}

function TakilmaCipi({ k }: { k: Pick<Kosu, "durum" | "baslangic"> }) {
  const u = takilmaUyarisi(k);
  if (!u) return null;
  return (
    <Cip ton="uyari" title="Koşu beklenenden uzun süredir bitmedi; CI kuyruğunu ya da çalıştırıcıyı kontrol edin.">
      {u}
    </Cip>
  );
}

export function KosuTablosu({ kosular, kompakt }: { kosular: Kosu[]; kompakt?: boolean }) {
  return (
    // ET-03: satırın (390'da kartın) tamamı koşuyu açar; satır başına tek Tab durağı (ET-08).
    <TabloSarici etiket="Koşular tablosu" uzun={kosular.length > 15} satirBaglanti>
        <thead>
          <tr>
            <th scope="col">Koşu</th>
            <th scope="col">Tetik</th>
            {!kompakt && <th scope="col" className="sutun-ikincil">Kaynak</th>}
            <th scope="col">Durum</th>
            <th scope="col" className="sayi">
              Geçen / toplam
            </th>
            {!kompakt && <th scope="col" className="sutun-ikincil">Commit</th>}
            <th scope="col">Başlangıç</th>
            {!kompakt && <th scope="col">Süre</th>}
          </tr>
        </thead>
        <tbody>
          {kosular.map((k) => (
            <tr key={k.id}>
              <td className="yigin-baslik" data-etiket="Koşu">
                <Link
                  to={`/kosular/${encodeURIComponent(k.id)}`}
                  className="satir-baglanti mono"
                  title={`Koşu kimliği: ${k.id}`}
                >
                  {kisaKosuAdi(k.id)}
                </Link>
                {k.break_campaign && (
                  <Cip ton="uyari" title="Uygulama BREAK_CAMPAIGN=1 ile koştu (kasıtlı kırma)">
                    kırma
                  </Cip>
                )}
                {/* 012/Ş8: ekilmiş hata koşusunun adımı ("Ekilmiş hata: <ad>"); diğer koşularda çizilmez. */}
                <EkilmisHataCipi kosu={k} />
              </td>
              <td data-etiket="Tetik">
                <Cip ton={TETIK_TONU[k.tetik] ?? "notr"}>{TETIK[k.tetik] ?? k.tetik}</Cip>
                {k.pr_no !== null && <span className="mono"> #{k.pr_no}</span>}
                {/* Platform deposu: koşu varsayılan dışı depoda koştuysa sahip/ad. */}
                <DepoCipi kaynak={k} />
                {/* Test ortamı (core `test_ortami`); ortamsız koşuda çizilmez. Canlı ortam uyarı tonunda. */}
                <OrtamRozeti ortam={k.test_ortami} />
                {k.platform && (
                  <>
                    {" "}
                    <PlatformRozeti platform={k.platform} />
                    {/* 011 §2.8: koşunun dili (core `dil` / `ortam.dil`); bilinmiyorsa çizilmez. */}
                    <DilRozeti dil={k.dil} platform={k.platform} />
                  </>
                )}
              </td>
              {!kompakt && (
                <td className="sutun-ikincil" data-etiket="Kaynak">
                  <Cip ton="notr">{KAYNAK[k.kaynak] ?? k.kaynak}</Cip>
                </td>
              )}
              <td className="sutun-durum" data-etiket="Durum">
                <DurumCipi d={k.durum} />
                <TakilmaCipi k={k} />
                {k.flaky > 0 && (
                  <Cip ton="uyari" title="Yeniden denemeyle geçen test">
                    {k.flaky} flaky
                  </Cip>
                )}
                <BasarisizOzetSatiri k={k} />
              </td>
              <td className="sayi mono" data-etiket="Geçen / toplam">
                {k.gecen}/{k.toplam}
              </td>
              {!kompakt && <td className="sutun-kimlik sutun-ikincil" data-etiket="Commit">{k.commit}</td>}
              <td className="sutun-tarih" data-etiket="Başlangıç">{tarih(k.baslangic)}</td>
              {!kompakt && <td className="sutun-tarih" data-etiket="Süre">{sure(k.sure_ms)}</td>}
            </tr>
          ))}
        </tbody>
    </TabloSarici>
  );
}

/** Başarısız testin kısa adı: case kısaltması varsa o ("TPD-1·C10"), yoksa test adının son parçası. */
export function basarisizAdi(o: BasarisizOzeti): string {
  if (o.case_ref) return o.case_ref;
  const parca = o.test_adi.split(" › ").pop() ?? o.test_adi;
  return parca.length > 60 ? `${parca.slice(0, 59)}…` : parca;
}

/**
 * UX IA-15: listede "ne kırıldı" — "1 başarısız: TPD-1·C10 (Belirsiz) [Triage]". Hata/zaman aşımında
 * testler koşmadıysa nedeni (CI başlamadı / sağlık yoklaması) tek satır. Core alanı yoksa sayıyla yetinilir.
 */
export function BasarisizOzetSatiri({ k }: { k: Pick<Kosu, "durum" | "basarisiz" | "basarisiz_ozet" | "saglik_hatasi" | "toplam"> & { hata?: string | null } }) {
  if ((k.durum === "error" || k.durum === "zaman_asimi") && k.toplam === 0) {
    const neden = k.saglik_hatasi ?? (k.durum === "zaman_asimi" ? "koşu beklenen sürede bitmedi" : null);
    return (
      <div className="kucuk kosu-basarisiz-ozet" data-testid="kosu-basarisiz-ozet">
        Testler koşmadı{neden ? `: ${neden}` : "; ayrıntı koşu sayfasında"}
      </div>
    );
  }
  const ozet = k.basarisiz_ozet ?? [];
  if (k.basarisiz === 0 || ozet.length === 0) return null;
  const kalan = k.basarisiz - ozet.length;
  return (
    <div className="kucuk kosu-basarisiz-ozet" data-testid="kosu-basarisiz-ozet">
      {k.basarisiz} başarısız:{" "}
      {ozet.map((o, i) => (
        <span key={`${o.test_adi}-${i}`} title={o.test_adi}>
          {i > 0 && ", "}
          {basarisizAdi(o)}
          {o.sinif && ` (${HATA_SINIFI[o.sinif]?.etiket ?? o.sinif})`}
          {o.failure_id && (
            <>
              {" "}
              <IzinliLink to={`/hatalar/${encodeURIComponent(o.failure_id)}`} aria-label={`${basarisizAdi(o)} triage sonucu`}>
                Triage
              </IzinliLink>
            </>
          )}
        </span>
      ))}
      {kalan > 0 && ` ve ${kalan} test daha`}
    </div>
  );
}

/** Koşu listesinin sayfa boyu (core `GET /runs?offset=&limit=`). */
export const KOSU_SAYFA = 50;

/** Platform bazlı gece koşusu özeti satırı: platformun en son gece koşusu ve deposu. */
export type GeceSatiri = { platform: Platform; kosu: Kosu };

/**
 * Gece koşusu her platform deposunda ayrı tetiklenir (kullanıcı kararı 2): son gece koşusu platform
 * başına. Platformu bilinmeyen koşu atlanır (uydurulmaz). Özet yalnız anlamlıysa döner: en az iki
 * platformda gece koşusu var ya da biri varsayılan dışı depoda koştu; yoksa null (tek depolu, tek
 * platformlu projede ekran bugünküyle aynı).
 */
export function geceOzeti(kosular: readonly Kosu[]): GeceSatiri[] | null {
  const son = new Map<Platform, Kosu>();
  for (const k of kosular) {
    if (k.tetik !== "nightly" || !k.platform) continue;
    const onceki = son.get(k.platform);
    if (!onceki || Date.parse(k.baslangic) > Date.parse(onceki.baslangic)) son.set(k.platform, k);
  }
  const satirlar = PLATFORMLAR.filter((p) => son.has(p)).map((p) => ({ platform: p, kosu: son.get(p)! }));
  if (satirlar.length >= 2 || satirlar.some((x) => (x.kosu.depo ?? "").trim())) return satirlar;
  return null;
}

export function GeceOzeti({ kosular }: { kosular: readonly Kosu[] }) {
  const satirlar = geceOzeti(kosular);
  if (!satirlar) return null;
  return (
    <Kart baslik="Gece koşuları: platform bazlı son sonuç">
      <p className="kucuk soluk">Gece koşusu her platformun deposunda ayrı tetiklenir; her platformun en son gece koşusu.</p>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Platform bazlı gece koşuları">
        <table className="tablo tablo-yigin" data-testid="gece-ozeti">
          <thead>
            <tr>
              <th scope="col">Platform</th>
              <th scope="col">Depo</th>
              <th scope="col">Durum</th>
              <th scope="col" className="sayi">
                Geçen / toplam
              </th>
              <th scope="col">Koşu</th>
              <th scope="col">Başlangıç</th>
            </tr>
          </thead>
          <tbody>
            {satirlar.map(({ platform, kosu: k }) => (
              <tr key={platform} data-platform={platform}>
                <td data-etiket="Platform">
                  <PlatformRozeti platform={platform} />
                </td>
                <td data-etiket="Depo">{depoGosterimi(k) ? <span className="mono">{depoGosterimi(k)}</span> : <span className="soluk">Varsayılan depo</span>}</td>
                <td data-etiket="Durum">
                  <DurumCipi d={k.durum} />
                  <TakilmaCipi k={k} />
                  {k.flaky > 0 && (
                    <Cip ton="uyari" title="Yeniden denemeyle geçen test">
                      {k.flaky} flaky
                    </Cip>
                  )}
                </td>
                <td className="sayi mono" data-etiket="Geçen / toplam">
                  {k.gecen}/{k.toplam}
                </td>
                <td data-etiket="Koşu">
                  <Link to={`/kosular/${encodeURIComponent(k.id)}`} className="mono" title={`Koşu kimliği: ${k.id}`}>
                    {kisaKosuAdi(k.id)}
                  </Link>
                </td>
                <td className="tek-satir" data-etiket="Başlangıç">{tarih(k.baslangic)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Kart>
  );
}

const GECE_ACIKLAMASI =
  "Her gece 02:00'de (UTC) zamanlanmış koşuyu şimdi başlatır: aynı onaylı test paketi; kod değişmese de veri/ortam kaymasını ve kararsız (flaky) testleri yakalar. Platformların ayrı depoları varsa her depoda ayrı koşu başlar.";
export const MANUEL_ACIKLAMASI =
  "Main'deki onaylı testleri şimdi koşturur (manuel tetik). Geliştirici rolü yalnız prod dışı ortamda başlatabilir.";
/** Maskeli koşu (core `maskeli: true`): ham artefaktlar rolde gizli; "yok" denmez. */
export const ARTEFAKT_MASKELI = "Ham artefaktlar bu rolde görünmez";
/** Geliştirici + `TP_ORTAM=prod`: manuel koşu düğmesi pasif (core 403). */
export const MANUEL_PROD_ENGELI = "Geliştirici prod ortamında manuel koşu başlatamaz (üretim ortamı).";
const DEPLOY_ACIKLAMASI =
  "Müşterinin deploy hattının yükleme bitince göndereceği sinyali taklit eder ve testleri koşturur; uygulamayı hiçbir yere yüklemez.";

/**
 * Koşunun Sauce Labs durumu (GitHub kipinde Sauce, koşunun içindeki bir job'dur: `sauce_durum`).
 * Sauce bilgisi olmayan yerel koşuda hiçbir şey gösterilmez.
 */
export function SauceCipi({ k }: { k: Pick<Kosu, "kaynak" | "durum" | "sauce_durum" | "sauce_neden"> }): ReactNode {
  switch (k.sauce_durum) {
    case "passed":
      return <Cip ton="basari">Sauce: geçti</Cip>;
    case "failed":
      return <Cip ton="hata">Sauce: kırmızı</Cip>;
    case "error":
      return <Cip ton="uyari" className="cip-uzun">Sauce koşmadı: {k.sauce_neden ?? "altyapı hatası"}</Cip>;
    case "atlandi":
      // IA-12: iç ayar adı (SAUCE_TETIKLER=…) kullanıcı cümlesine çevrilir; ham neden title'da.
      return (
        <Cip ton="notr" className="cip-uzun" title={k.sauce_neden ?? undefined}>
          Sauce atlandı: {teknikMetniCevir(k.sauce_neden) ?? k.sauce_neden ?? "neden bildirilmedi"}
        </Cip>
      );
  }
  if (k.kaynak === "github" && (k.durum === "queued" || k.durum === "running")) return <Cip ton="bilgi">Sauce: sırada/sürüyor</Cip>;
  return null;
}

type Filtre = { tetik: Tetik | ""; kaynak: KosuKaynagi | ""; durum: Kosu["durum"] | ""; kirma: boolean; platform?: Platform | ""; dil?: Dil | "" };

/** Adresteki `?dil=` değeri (bilinmeyen değer süzgeç uygulamaz). */
export function dilSecimiOku(d: string | null): Dil | "" {
  return d && (DILLER as readonly string[]).includes(d) ? (d as Dil) : "";
}

/** Koşu listesinin süzgeci (adres çubuğunda: ?tetik=&kaynak=&durum=&kirma=1&platform=&dil=). */
export function kosulariSuz(kosular: Kosu[], f: Filtre): Kosu[] {
  // Platformu bilinmeyen koşu hiçbir platform seçimine girmez (uydurulmaz).
  return platformaGoreSuz(kosular, f.platform || "tumu", (k) => k.platform).filter(
    (k) =>
      (!f.tetik || k.tetik === f.tetik) &&
      (!f.kaynak || k.kaynak === f.kaynak) &&
      (!f.durum || k.durum === f.durum) &&
      // Dili bilinmeyen koşu hiçbir dil seçimine girmez (ts sayılmaz; ekran testi 2 TP-7).
      (!f.dil || k.dil === f.dil) &&
      (f.kirma || !k.break_campaign || f.tetik === "break_verify"),
  );
}

export function Kosular() {
  const [sorgu, setSorgu] = useSearchParams();
  // Ortam süzgeci sunucudadır (`GET /runs?ortam=<eid>|-`).
  const ortamSecimi = sorgu.get("ortam") ?? "";
  // UX IA-15: sayfalama — ilk sayfa canlı yenilenir, "Daha eski koşular" sonraki sayfaları ekler.
  const v = useVeri(() => api.kosuSayfasi({ ortam: ortamSecimi || undefined, offset: 0, limit: KOSU_SAYFA }), [ortamSecimi]);
  const [ekSayfalar, setEkSayfalar] = useState<Kosu[][]>([]);
  const [sayfaYukleniyor, setSayfaYukleniyor] = useState(false);
  const [sayfaHatasi, setSayfaHatasi] = useState<string | null>(null);
  useEffect(() => {
    setEkSayfalar([]);
    setSayfaHatasi(null);
  }, [ortamSecimi]);
  const sonSayfa = ekSayfalar.length ? ekSayfalar[ekSayfalar.length - 1] : (v.veri ?? []);
  // Sabitlenen kanıt (`sabit`) ilk sayfayı sayfa boyunun üstüne çıkarabilir: tam sayfa geldiyse devamı olabilir.
  const dahaVar = !!v.veri && sonSayfa.length >= KOSU_SAYFA;
  const dahaEskiYukle = async () => {
    setSayfaYukleniyor(true);
    setSayfaHatasi(null);
    try {
      const yeni = await api.kosuSayfasi({ ortam: ortamSecimi || undefined, offset: (ekSayfalar.length + 1) * KOSU_SAYFA, limit: KOSU_SAYFA });
      setEkSayfalar((s) => [...s, yeni]);
    } catch (e) {
      setSayfaHatasi(e instanceof Error ? e.message : String(e));
    } finally {
      setSayfaYukleniyor(false);
    }
  };
  const ortam = useOrtamlar();
  // Tetik ortamı: kullanıcı seçmediyse projenin varsayılanı (listede yoksa ilk ortam).
  const [tetikOrtami, setTetikOrtami] = useState<string | null>(null);
  const seciliTetikOrtami =
    tetikOrtami && ortam.ortamlar.some((o) => o.eid === tetikOrtami) ? tetikOrtami : (ortam.varsayilan?.eid ?? ortam.ortamlar[0]?.eid ?? "");
  // Her düğmenin kendi meşgul durumu: biri koşarken diğeri "dönüyor" görünmez.
  const geceIslem = useIslem();
  const deployIslem = useIslem();
  const manuelIslem = useIslem();
  // core: deploy/nightly `run.trigger_scheduled` (Otomasyon Mühendisi); manual `run.trigger_manual`
  // (Otomasyon Mühendisi, Geliştirici; developer prod'da 403 → core'un mesajı gösterilir).
  const zamanliTetik = useIzin("run.trigger_scheduled");
  const manuelTetik = useIzin("run.trigger_manual");
  // Geliştirici prod ortamında manuel koşu başlatamaz (core 403): `/demo/status` → `ortam`.
  const { kullanici } = useOturum();
  const gelistirici = normalizeRol(kullanici?.rol) === "developer";
  const [kurulumOrtami, setKurulumOrtami] = useState<string | null>(null);
  useEffect(() => {
    if (!gelistirici || !manuelTetik) return;
    let iptal = false;
    api
      .demoDurumu()
      .then((d) => !iptal && setKurulumOrtami(d.ortam ?? null))
      .catch(() => undefined);
    return () => {
      iptal = true;
    };
  }, [gelistirici, manuelTetik]);
  const manuelProdEngeli = gelistirici && kurulumOrtami === "prod";
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["ci.status", "failure.classified"]);
  const acikPlatformlar = usePlatformlar();
  const [sonTetik, setSonTetik] = useState<string | null>(null);
  const filtre: Filtre = {
    tetik: (sorgu.get("tetik") ?? "") as Filtre["tetik"],
    kaynak: (sorgu.get("kaynak") ?? "") as Filtre["kaynak"],
    durum: (sorgu.get("durum") ?? "") as Filtre["durum"],
    // IA-15: kasıtlı kırma koşuları varsayılan gizli (normal sonuçlarla karışmasın); `?kirma=1` gösterir.
    kirma: sorgu.get("kirma") === "1",
    platform: (() => {
      const p = platformSecimiOku(sorgu.get("platform"));
      return p === "tumu" ? "" : p;
    })(),
    dil: dilSecimiOku(sorgu.get("dil")),
  };
  const ayarla = (anahtar: string, deger: string) => {
    const y = new URLSearchParams(sorgu);
    if (deger) y.set(anahtar, deger);
    else y.delete(anahtar);
    setSorgu(y, { replace: true });
  };
  const tum = useMemo(() => {
    const gorulen = new Set<string>();
    return [...(v.veri ?? []), ...ekSayfalar.flat()].filter((k) => (gorulen.has(k.id) ? false : (gorulen.add(k.id), true)));
  }, [v.veri, ekSayfalar]);
  const suzgecVar = ["tetik", "kaynak", "durum", "dil", "platform", "ortam", "kirma"].some((a) => sorgu.has(a));
  const suzgecleriTemizle = () => {
    const y = new URLSearchParams(sorgu);
    for (const a of ["tetik", "kaynak", "durum", "dil", "platform", "ortam", "kirma"]) y.delete(a);
    setSorgu(y, { replace: true });
  };
  const suzulen = useMemo(
    () => kosulariSuz(tum, filtre),
    [tum, filtre.tetik, filtre.kaynak, filtre.durum, filtre.kirma, filtre.platform, filtre.dil],
  );
  // 009: platform süzgeci yalnız platformu bilinen koşu varsa (liste ucu taşımıyorsa gösterilmez).
  const platformVar = tum.some((k) => k.platform) || !!filtre.platform;
  const tetikler = [...new Set(tum.map((k) => k.tetik))];
  // Kırma koşusu yoksa süzgeç işe yaramaz: gösterilmez (yerel kontrol / kırarak doğrulama koşuları
  // koşu tablosuna alındığında görünür hale gelir).
  const kirmaVar = tum.some((k) => k.break_campaign);
  const kaynaklar = [...new Set(tum.map((k) => k.kaynak))];
  // TP-7: dil süzgeci yalnız dili bilinen koşu varsa (ya da adreste seçim varsa); seçenekler koşulardaki diller.
  const dilSecenekleri = suzgecSecenekleri(tum, (k) => k.dil, (d) => DIL_ETIKETI[d], { secili: filtre.dil, sira: DILLER });
  // Ortam süzgeci: projede ortam varsa, koşulardan biri ortam taşıyorsa ya da adreste seçim varsa.
  const ortamSuzgecVar = ortam.ortamlar.length > 0 || tum.some((k) => k.test_ortami) || !!ortamSecimi;

  const tetikle = async (tetik: "deploy" | "nightly" | "manual") => {
    const islemler = { deploy: deployIslem, nightly: geceIslem, manual: manuelIslem };
    for (const [t, i] of Object.entries(islemler)) if (t !== tetik) i.temizle();
    // Ortam yalnız projede ortam varsa gönderilir. Gece koşusu her zaman varsayılan ortamda koşar
    // (zamanlanmış koşuyla aynı): `ortam` yazılmaz, core varsayılanı kullanır.
    const ortamEid = ortam.ortamlar.length > 0 && tetik !== "nightly" && seciliTetikOrtami ? seciliTetikOrtami : undefined;
    const s = await islemler[tetik].calistir(() => (ortamEid === undefined ? api.ciTetikle(tetik) : api.ciTetikle(tetik, ortamEid)));
    if (s) {
      const ortamEki = s.test_ortami ? ` (${ortamMetni("ortam")}: ${s.test_ortami.ad})` : "";
      bildir(s.mesaj ?? "Koşu tetiklendi.");
      setSonTetik(`${s.mesaj ?? `${tetik === "deploy" ? "Deploy" : tetik === "manual" ? "Manuel" : "Gece"} koşusu tetiklendi.`}${ortamEki}`);
      void v.yenile(true);
    }
  };
  const tetikHatasi = [geceIslem, deployIslem, manuelIslem].find((i) => i.hata);

  return (
    <>
      <SayfaBasligi
        baslik="Koşular"
        aciklama="CI yalnızca onaylı, deterministik test kodunu koşturur; CI'da AI yoktur. Yerel test-runner her zaman koşar; GitHub Actions ve Sauce Labs kimlik bilgileri varsa aynı testleri koşturur."
        eylemler={
          (zamanliTetik || manuelTetik) && (
            <>
              {zamanliTetik && (
                <IslemDugmesi
                  izin="run.trigger_scheduled"
                  tur="ikincil"
                  calisiyor={geceIslem.calisiyor}
                  title={GECE_ACIKLAMASI}
                  aria-describedby="kosular-gece-aciklama"
                  nedenGizli
                  onClick={() => tetikle("nightly")}
                >
                  Gece koşusunu şimdi başlat
                </IslemDugmesi>
              )}
              {manuelTetik && (
                <IslemDugmesi
                  izin="run.trigger_manual"
                  tur={zamanliTetik ? "ikincil" : "birincil"}
                  calisiyor={manuelIslem.calisiyor}
                  disabled={manuelProdEngeli}
                  title={manuelProdEngeli ? MANUEL_PROD_ENGELI : MANUEL_ACIKLAMASI}
                  aria-describedby="kosular-manuel-aciklama"
                  nedenGizli={!manuelProdEngeli}
                  onClick={() => tetikle("manual")}
                >
                  Manuel koşu başlat
                </IslemDugmesi>
              )}
              {zamanliTetik && (
                <IslemDugmesi
                  izin="run.trigger_scheduled"
                  calisiyor={deployIslem.calisiyor}
                  title={DEPLOY_ACIKLAMASI}
                  aria-describedby="kosular-deploy-aciklama"
                  nedenGizli
                  onClick={() => tetikle("deploy")}
                >
                  Deploy sonrası testleri koş
                </IslemDugmesi>
              )}
            </>
          )
        }
      />
      {(zamanliTetik || manuelTetik) && (
        <ul className="tetik-aciklamalari kucuk soluk" aria-label="Tetik düğmeleri">
          {zamanliTetik && (
            <li id="kosular-gece-aciklama">
              <strong>Gece koşusunu şimdi başlat:</strong> {GECE_ACIKLAMASI}
            </li>
          )}
          {manuelTetik && (
            <li id="kosular-manuel-aciklama">
              <strong>Manuel koşu başlat:</strong> {MANUEL_ACIKLAMASI}
            </li>
          )}
          {zamanliTetik && (
            <li id="kosular-deploy-aciklama">
              <strong>Deploy sonrası testleri koş:</strong> {DEPLOY_ACIKLAMASI}
            </li>
          )}
        </ul>
      )}
      {(zamanliTetik || manuelTetik) && (
        <OrtamSecici ortamlar={ortam.ortamlar} deger={seciliTetikOrtami} degistir={setTetikOrtami} geceNotu={zamanliTetik} />
      )}
      {tetikHatasi && <HataKutusu hata={tetikHatasi.hata!} kaynak={tetikHatasi.hataNesnesi} />}
      {sonTetik && !tetikHatasi && <Uyari ton="bilgi">{sonTetik}</Uyari>}
      {v.veri && <GeceOzeti kosular={v.veri} />}
      <Kart>
        {v.yukleniyor && !v.veri ? (
          <Yukleniyor />
        ) : v.hata && !v.veri ? (
          <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
        ) : tum.length === 0 && !ortamSecimi ? (
          <BosDurum baslik="Henüz koşu yok.">
            İlk koşu, üretilen bir test main'e birleşince CI'da başlar (Otomasyon Mühendisi). <IzinliLink to="/kod">Kod üretimine git</IzinliLink>
          </BosDurum>
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
                  {(["queued", "running", "passed", "failed", "error", "zaman_asimi"] as const).map((d) => (
                    <option key={d} value={d}>
                      {KOSU_DURUMU[d].etiket}
                    </option>
                  ))}
                </select>
              </label>
              {dilSecenekleri.length > 0 && (
                <SuzgecSecimi etiket="Dil" testId="kosu-dil-suzgeci" deger={filtre.dil ?? ""} secenekler={dilSecenekleri} degistir={(d) => ayarla("dil", d)} />
              )}
              {platformVar && (
                <label>
                  Platform
                  <select value={filtre.platform} onChange={(e) => ayarla("platform", e.target.value)}>
                    <option value="">Tümü</option>
                    {/* Projede açık platformlar; adresteki seçim kapalı bir platformsa o da listede kalır (seçim görünür). */}
                    {PLATFORMLAR.filter((p) => acikPlatformlar.includes(p) || p === filtre.platform).map((p) => (
                      <option key={p} value={p}>
                        {PLATFORM_ETIKETI[p]}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {ortamSuzgecVar && (
                <OrtamSuzgeci ortamlar={suzgecOrtamlari(ortam.ortamlar, tum)} deger={ortamSecimi} degistir={(d) => ayarla("ortam", d)} />
              )}
              {kirmaVar && (
                <label className="satir-ogeler">
                  <span>
                    <input type="checkbox" checked={filtre.kirma} onChange={(e) => ayarla("kirma", e.target.checked ? "1" : "")} /> Kasıtlı kırma koşularını göster
                  </span>
                </label>
              )}
              {suzgecVar && (
                <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={suzgecleriTemizle}>
                  Süzgeçleri temizle
                </button>
              )}
              <span className="soluk kucuk" role="status">
                {suzulen.length}/{tum.length} koşu{dahaVar ? " (daha eskileri var)" : ""}
              </span>
            </div>
            {suzulen.length ? (
              <KosuTablosu kosular={suzulen} />
            ) : (
              <BosDurum baslik="Süzgece uyan koşu yok.">
                {suzgecVar && (
                  <button type="button" className="dugme-metin" onClick={suzgecleriTemizle}>
                    Süzgeçleri temizle
                  </button>
                )}
              </BosDurum>
            )}
            {(dahaVar || sayfaHatasi) && (
              <div className="sayfalama" data-testid="kosu-sayfalama">
                {sayfaHatasi && <span className="hata-metin kucuk">{sayfaHatasi}</span>}
                <button type="button" className="dugme dugme-ikincil dugme-kucuk" disabled={sayfaYukleniyor} aria-busy={sayfaYukleniyor} onClick={() => void dahaEskiYukle()}>
                  {sayfaYukleniyor ? "Yükleniyor…" : `Daha eski ${KOSU_SAYFA} koşu`}
                </button>
              </div>
            )}
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
      {alt ? ` · ${altTurEtiketi(alt)}` : ""}
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
            {/* Koşunun platformu triage kayıtlarının platformudur (aynı koşu, aynı cihaz). */}
            <PlatformRozeti platform={k.platform} />
            {/* 011 §2.8: koşunun dili (core `dil` / `ortam.dil`); bilinmiyorsa çizilmez. */}
            <DilRozeti dil={k.dil} platform={k.platform} />
            <span>{h.test_adi}</span>
            {h.ozet && <span className="kucuk soluk">{h.ozet}</span>}
            <IzinliLink to={`/hatalar/${encodeURIComponent(h.id)}`}>Triage sonucunu aç</IzinliLink>
          </li>
        ))}
      </ul>
    </Kart>
  );
}

const PK_DURUMU: Record<string, { etiket: string; ton: "basari" | "hata" | "bilgi" | "notr" }> = {
  passed: { etiket: "geçti", ton: "basari" },
  failed: { etiket: "kırmızı", ton: "hata" },
  error: { etiket: "hata", ton: "hata" },
  pending: { etiket: "bekliyor", ton: "bilgi" },
  skipped: { etiket: "atlandı", ton: "notr" },
};

/** 009: aynı commit'in platform başına yerel CI kontrolleri (`local-ci-<platform>`; core `checks.platformlar`). */
function PlatformKontrolleri({ k }: { k: KosuDetayTuru }) {
  const pk = k.platform_kontrolleri ?? [];
  if (pk.length === 0) return null;
  return (
    <Kart baslik="Platform kontrolleri">
      <p className="kucuk soluk">Bu koşunun commit'i için uygulama platformlarının yerel CI kontrolleri (her biri ayrı kayıt; Java PR'larında zorunlu check). Web kontrolü (local-ci) PR check'lerinde görünür.</p>
      <ul className="duz-liste" aria-label="Platform kontrolleri">
        {pk.map((c) => {
          const d = PK_DURUMU[c.durum] ?? { etiket: c.durum, ton: "notr" as const };
          return (
            <li key={c.ad} className="satir-ogeler">
              <span>{checkEtiketi(c.ad) ?? c.ad}</span>
              <span className="mono kucuk soluk">{c.ad}</span>
              <Cip ton={d.ton}>{d.etiket}</Cip>
            </li>
          );
        })}
      </ul>
    </Kart>
  );
}

const githubaGider = (u: string | null | undefined) => Boolean(u && /^https:\/\/github\.com\//.test(u));

/**
 * Rapor bağlantısı. Yerel kopya yoksa (GitHub yedeği) ve dosya bağlantısı da yoksa, "GitHub
 * artefaktında" nedeni GitHub'daki koşuya (ci_url) bağlanır: artefakt oradan indirilir.
 */
function ArtefaktBaglantisi({
  href,
  ghYedek,
  ciUrl,
  yokNedeni,
  children,
}: {
  href: string | null | undefined;
  ghYedek: string | null;
  ciUrl: string | null;
  yokNedeni: string;
  children: ReactNode;
}) {
  if (!href && ghYedek && githubaGider(ciUrl)) {
    return (
      <Baglanti href={ciUrl}>
        {children} (GitHub artefaktında)
      </Baglanti>
    );
  }
  return (
    <Baglanti href={href} yokNedeni={ghYedek && !href ? "GitHub artefaktında" : yokNedeni}>
      {children}
    </Baglanti>
  );
}

export function KosuDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.kosu(id), [id]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["ci.status", "failure.classified"], id);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <BaskaProjedeKayit tur="run" id={id} hata={v.hataNesnesi} ad="Koşu" liste={["/kosular", "Koşular"]} yedek={<KayitHatasi ad="Koşu" ust={<Link to="/kosular">← Koşular</Link>} hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />} />;
  const k = v.veri;
  if (!k) return null;
  const ghYedek = githubYedekNotu(k);
  const hatalar = kosuHatalari(k);
  const takilma = takilmaUyarisi(k);
  const sauceUzun = k.sauce_durum === "error" || k.sauce_durum === "atlandi";
  const kisa = kisaKosuAdi(k.id);
  const ciVar = Boolean((k.adimlar && Object.keys(k.adimlar).length > 0) || k.github || k.log_url || (k.platform_kontrolleri ?? []).length > 0);

  const raporlar = (
      <Kart baslik="Raporlar ve bağlantılar">
        {k.maskeli ? (
          <p className="soluk" data-testid="artefakt-maskeli">
            {ARTEFAKT_MASKELI}
            {k.ci_url && (
              <>
                {" · "}
                <Baglanti href={k.ci_url}>CI işi</Baglanti>
              </>
            )}
            {k.script_id && (
              <>
                {" · "}
                <IzinliLink to={`/kod/${encodeURIComponent(k.script_id)}`}>Üretilen test</IzinliLink>
              </>
            )}
          </p>
        ) : (
        <div className="artefakt-baglantilari">
          <Baglanti href={k.rapor_url} yokNedeni="koşu bu raporu üretmedi ya da core sunmuyor">
            Playwright HTML raporu{githubaGider(k.rapor_url) ? " (GitHub)" : ""}
          </Baglanti>
          <ArtefaktBaglantisi href={k.junit_url ?? null} ghYedek={ghYedek} ciUrl={k.ci_url} yokNedeni="koşu JUnit XML üretmedi">
            JUnit XML
          </ArtefaktBaglantisi>
          <ArtefaktBaglantisi href={k.allure_url} ghYedek={ghYedek} ciUrl={k.ci_url} yokNedeni="bu koşuda üretilmedi">
            {k.allure_url && /allure-results\/?$/.test(k.allure_url)
              ? "Allure ham sonuçları (JSON listesi)"
              : `Allure raporu${githubaGider(k.allure_url) ? " (GitHub artefaktı)" : ""}`}
          </ArtefaktBaglantisi>
          {k.allure_sonuclari_url && k.allure_sonuclari_url !== k.allure_url && (
            <Baglanti href={k.allure_sonuclari_url} yokNedeni="yok">
              Allure ham sonuçları (JSON listesi)
            </Baglanti>
          )}
          {/* Extent raporunu Java koşuları üretir (uygulama: Appium + TestNG; web: Playwright for Java + TestNG); yoksa satır hiç görünmez. */}
          {k.extent_url && <Baglanti href={k.extent_url}>Extent raporu</Baglanti>}
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
          <ArtefaktBaglantisi href={k.log_url} ghYedek={ghYedek} ciUrl={k.ci_url} yokNedeni="yok">
            Koşu günlüğü
          </ArtefaktBaglantisi>
          {k.script_id && <IzinliLink to={`/kod/${encodeURIComponent(k.script_id)}`}>Üretilen test</IzinliLink>}
        </div>
        )}
        {ghYedek && !k.maskeli && <p className="kucuk soluk">{ghYedek}</p>}
        {k.hata && <p className="kucuk hata-metin">{k.hata}</p>}
      </Kart>
  );

  const sekmeler: DetaySekmesi[] = [
    {
      id: "sonuclar",
      ad: "Test sonuçları",
      sayi: k.toplam,
      dikkat: k.basarisiz > 0,
      icerik: () => (
        <>
          <HataListesi k={k} />
          <TestSonuclari k={k} />
        </>
      ),
    },
    {
      id: "ci",
      ad: "CI ve platform",
      icerik: () =>
        ciVar ? (
          <>
            <PlatformKontrolleri k={k} />
            <CiAdimlari k={k} />
          </>
        ) : (
          <BosDurum kip="sekme" baslik="Bu koşuda CI adımı kaydı yok.">
            Yerel ya da harici koşularda CI adımları raporlanmaz; ayrıntı için Raporlar sekmesindeki bağlantılara bakın.
          </BosDurum>
        ),
    },
    { id: "raporlar", ad: "Raporlar ve bağlantılar", icerik: raporlar },
  ];

  return (
    <DetaySayfasi
      key={k.id}
      sekmeEtiketi="Koşu bölümleri"
      ozet={
        <OzetKarti
          testId="kosu-ozet"
          kirinti={[{ ad: "Koşular", yol: "/kosular" }, { ad: `Koşu ${kisa}` }]}
          kimlik={<Kimlik deger={k.id} tur="kosu" kisaltUzunluk={8} kirp="bas" />}
          baslik={`${TETIK[k.tetik] ?? k.tetik} koşusu`}
          rozetler={
            <>
              <DurumCipi d={k.durum} />
              <Cip ton={TETIK_TONU[k.tetik] ?? "notr"}>
                {TETIK[k.tetik] ?? k.tetik}
                {k.pr_no !== null && ` #${k.pr_no}`}
              </Cip>
              <Cip ton="notr">{KAYNAK[k.kaynak] ?? k.kaynak}</Cip>
              <PlatformRozeti platform={k.platform} />
              <DepoCipi kaynak={k} />
              <OrtamRozeti ortam={k.test_ortami} />
              <EkilmisHataCipi kosu={k} />
              {/* 011 §2.8: koşunun dili (core `dil` / `ortam.dil`); bilinmiyorsa çizilmez. */}
              <DilRozeti dil={k.dil} platform={k.platform} />
              {/* DZ-08: uzun Sauce nedeni çip değil, özetin altında uyarı kutusu. */}
              {!sauceUzun && <SauceCipi k={k} />}
            </>
          }
          meta={
            <MetaSatiri
              ogeler={[
                { etiket: "Commit", deger: k.commit ? <KisaDeger deger={k.commit} /> : null },
                { etiket: "Süre", deger: k.sure_ms ? sure(k.sure_ms) : null },
                { etiket: "Başlangıç", deger: tarih(k.baslangic) },
              ]}
            />
          }
          siradaki={<KosuSiradaki k={k} hatalar={hatalar} takilma={takilma} />}
          eylemler={
            k.script_id ? (
              <IzinliLink className="dugme dugme-ikincil" to={`/kod/${encodeURIComponent(k.script_id)}`}>
                Üretilen test
              </IzinliLink>
            ) : undefined
          }
        />
      }
      serit={
        <div className="metrik-izgara kosu-metrikleri" aria-label="Koşu özeti">
          <Metrik etiket="Toplam" deger={k.toplam} />
          <Metrik etiket="Geçen" deger={k.gecen} ton={k.toplam > 0 && k.gecen === k.toplam ? "basari" : undefined} />
          <Metrik etiket="Başarısız" deger={k.basarisiz} ton={k.basarisiz > 0 ? "hata" : undefined} />
          <Metrik etiket="Flaky" deger={k.flaky} ton={k.flaky > 0 ? "uyari" : undefined} />
          <Metrik etiket="Süre" deger={sure(k.sure_ms)} />
        </div>
      }
      ust={
        (takilma || k.break_campaign || k.saglik_hatasi || sauceUzun || k.uyarilar.length > 0) && (
          <>
            {/* Koşu uyarıları (ör. ekilmiş hata koşusu: kırmızı beklenir) sekmelerin üstünde, gizli sekmede değil. */}
            {k.uyarilar.length > 0 && (
              <Uyari ton="bilgi">
                <ul className="duz-liste" data-testid="kosu-uyarilari">
                  {k.uyarilar.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
              </Uyari>
            )}
            {takilma && (
              <Uyari baslik="Koşu takılmış olabilir">
                <span data-testid="takilma-uyarisi">{takilma}</span>. CI kuyruğunu ya da çalıştırıcıyı kontrol edin; core süre aşımında
                koşuyu "Zaman aşımı" olarak kapatır.
              </Uyari>
            )}
            {k.break_campaign && <Uyari>Bu koşuda kampanya kuralı koşunun bayisi için BREAK_CAMPAIGN ile bozuldu (kasıtlı kırma); başarısızlık beklenir.</Uyari>}
            {k.saglik_hatasi && (
              <Uyari ton="hata" baslik="Ortam sorunu">
                Koşu öncesi sağlık yoklaması başarısız; Playwright başlatılmadı: {k.saglik_hatasi}
              </Uyari>
            )}
            {sauceUzun && (
              <div data-testid="sauce-uyarisi">
                <Uyari ton={k.sauce_durum === "error" ? "uyari" : "bilgi"} baslik={k.sauce_durum === "error" ? "Sauce koşmadı" : "Sauce atlandı"}>
                  {k.sauce_neden ?? (k.sauce_durum === "error" ? "altyapı hatası" : "neden bildirilmedi")}
                  {k.sauce_durum === "error" && ". CI işi bilerek yeşil biter; Sauce sonucu bu koşuda yok."}
                </Uyari>
              </div>
            )}
          </>
        )
      }
      sekmeler={sekmeler}
    />
  );
}

/** Koşunun tek "Sıradaki adım"ı: başarısızlıkta triage, sürüyorsa bekleme, yeşilse eylem yok. */
function KosuSiradaki({ k, hatalar, takilma }: { k: KosuDetayTuru; hatalar: KosuHatasi[]; takilma: string | null }) {
  if (takilma) return <>Koşu beklenenden uzun sürüyor; CI kuyruğunu ya da çalıştırıcıyı kontrol edin.</>;
  if (k.durum === "queued" || k.durum === "running") return <>Koşu sürüyor; sonuçlar geldikçe bu sayfa kendiliğinden güncellenir.</>;
  if (hatalar.length > 0) {
    const ilk = hatalar[0];
    return (
      <>
        {hatalar.length === 1 ? `Başarısız test triage'a düştü: ${ilk.test_adi}.` : `${hatalar.length} başarısızlık triage'a düştü.`}{" "}
        <IzinliLink className="ds-siradaki-git" to={`/hatalar/${encodeURIComponent(ilk.id)}`}>
          Triage sonucunu aç →
        </IzinliLink>
      </>
    );
  }
  if (k.basarisiz > 0) return <>Başarısız testler sınıflandırılıyor; triage sonucu gelince burada bağlantısı görünür.</>;
  if (k.durum === "error" || k.durum === "zaman_asimi") return <>Koşu tamamlanmadı{k.hata ? `: ${k.hata}` : ""}. CI işini ve günlüğü Raporlar sekmesinde inceleyin.</>;
  if (k.durum === "passed") return <>Tüm testler geçti; bu koşu için eylem gerekmiyor.</>;
  return <>Sonuçları Test sonuçları sekmesinde inceleyin.</>;
}

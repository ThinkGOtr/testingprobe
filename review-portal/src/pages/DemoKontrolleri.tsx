// Sunucu (presenter) için demo kontrolleri: locator kırılması (TEKNIK-TASARIM §2 ikinci kırılma
// senaryosu, `make break` eşi) ve demo sıfırlama. Her ikisi de onay ister; ilerleme core olaylarından
// (`demo.progress`) ve koşu listesinden izlenir — olay gelmese de koşu ve triage görünür.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { hataMesaji } from "../api/http";
import type { DemoDurumu, HataAnalizi, HataSinifi, IsYaniti, Kosu, KosuHatasi, PortalOlayi } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { Cip, IslemDugmesi, Kart, SayfaBasligi, Uyari } from "../components/ui";
import { HATA_SINIFI, KOSU_DURUMU, TETIK } from "../lib/etiketler";
import { saat } from "../lib/format";
import { kisaKosuAdi, kosuHatalari } from "./Kosular";

const YOKLAMA_MS = 2000;
const YOKLAMA_UST_SINIR_MS = 10 * 60 * 1000;

type Gunluk = { zaman: string; mesaj: string };

interface KirmaDurumu {
  basladi: number;
  yanit: IsYaniti;
  kosu: Kosu | null;
  hatalar: KosuHatasi[] | null;
  bitti: boolean;
  /** Sayfaya dönüldüğünde `/demo/status` yenileme isteğinden kuruldu (bu oturumda basılmadı). */
  geriYuklendi?: boolean;
}

/** Web yenilemesi bu kadar sürerse sunucuya host komutu hatırlatılır (CI uygulama yenilenmeden başlamaz). */
export const WEB_BEKLEME_UYARI_MS = 20_000;

/** main'e ait CI koşusu tetikleri (PR, yerel kontrol ve kırarak doğrulama hariç). */
const MAIN_TETIKLERI = ["push", "deploy", "nightly", "manual"];
const YENI_TESTID = "cart-add";

/** Kısaltılmış ya da tam iki sha aynı commit'i mi gösterir (en az 7 karakter ortak önek)? */
export function shaEsit(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const n = Math.min(a.length, b.length);
  return n >= 7 && a.slice(0, n).toLowerCase() === b.slice(0, n).toLowerCase();
}

/** Forge main'in şu anki commit'inde koşan en son main CI koşusu (yoksa null). */
export function mainKosusu(kosular: Kosu[], main: string | null | undefined): Kosu | null {
  const k = kosular.filter((x) => MAIN_TETIKLERI.includes(x.tetik) && shaEsit(x.commit, main));
  return k.sort((a, b) => Date.parse(b.baslangic) - Date.parse(a.baslangic))[0] ?? null;
}

/**
 * Onarım PR'ı: yeşil main koşusunun PR'ı; yoksa ondan önceki son kırmızı main koşusundan (kırılma)
 * sonra yeşil biten son PR koşusu. Bulunamazsa null (numara uydurulmaz).
 */
export function onarimPrNo(kosular: Kosu[], mk: Kosu | null): number | null {
  if (!mk || mk.durum !== "passed") return null;
  if (mk.pr_no) return mk.pr_no;
  const t = Date.parse(mk.baslangic);
  const kirmizi = kosular
    .filter((x) => MAIN_TETIKLERI.includes(x.tetik) && (x.durum === "failed" || x.durum === "error") && Date.parse(x.baslangic) < t)
    .sort((a, b) => Date.parse(b.baslangic) - Date.parse(a.baslangic))[0];
  const alt = kirmizi ? Date.parse(kirmizi.baslangic) : -Infinity;
  const pr = kosular
    .filter((x) => x.tetik === "pr" && x.pr_no && x.durum === "passed" && Date.parse(x.baslangic) < t && Date.parse(x.baslangic) > alt)
    .sort((a, b) => Date.parse(b.baslangic) - Date.parse(a.baslangic))[0];
  return pr?.pr_no ?? null;
}

/**
 * Locator senaryosunun durumu:
 * - `baseline`: main kırılmamış (baseline ya da uygulama testId'si eski `add-to-cart`) → kırılabilir.
 * - `kirik`: uygulama `cart-add`, test tarafı onarılmamış (e2e testId farklı ya da main koşusu kırmızı/yok).
 * - `dogrulaniyor`: main'in son commit'inde CI sürüyor; sonuç bekleniyor.
 * - `onarildi`: uygulama ve test aynı testId'de (`cart-add`) ve main koşusu yeşil → yeniden prova için sıfırlama gerekir.
 * Core `locator_durumu` ya da `forge.e2e_testid` verirse o esas alınır; yoksa main'deki son CI koşusuna bakılır.
 */
export type LocatorHali = "baseline" | "kirik" | "dogrulaniyor" | "onarildi";
export interface LocatorDurumOzeti {
  hal: LocatorHali;
  mainKosusu: Kosu | null;
  onarimPr: number | null;
}

export function locatorDurumu(d: DemoDurumu | null, kosular: Kosu[] | null): LocatorDurumOzeti {
  const f = d?.forge ?? {};
  const mk = mainKosusu(kosular ?? [], f.main);
  // "Onarıldı" metni main'deki son YEŞİL koşuyu gösterir: sonrasında ortam hatasıyla düşen bir
  // deploy/nightly koşusu (ör. demo-app-web durdurulmuş, 0/0) "CI yeşil (0/0)" diye okunmasın.
  const yesil = mainKosusu((kosular ?? []).filter((k) => k.durum === "passed"), f.main);
  const ozet = (hal: LocatorHali): LocatorDurumOzeti => {
    const k = hal === "onarildi" ? (yesil ?? mk) : mk;
    return { hal, mainKosusu: k, onarimPr: hal === "onarildi" ? onarimPrNo(kosular ?? [], k) : null };
  };
  const kosuHali = (): LocatorHali =>
    mk?.durum === "passed" ? "onarildi" : mk && (mk.durum === "queued" || mk.durum === "running") ? "dogrulaniyor" : "kirik";
  if (!d) return ozet("baseline");
  if (d.locator_durumu === "baseline" || d.locator_durumu === "kirik" || d.locator_durumu === "onarildi") return ozet(d.locator_durumu);
  if (f.main_baseline_mi !== false) return ozet("baseline");
  const web = typeof f.testid === "string" ? f.testid : null;
  if (web !== YENI_TESTID) return ozet("baseline");
  const e2e = typeof f.e2e_testid === "string" ? f.e2e_testid : null;
  if (e2e && e2e !== web) return ozet("kirik");
  // e2e de `cart-add` (onarım merge edildi) ya da bilinmiyor: main'deki son CI koşusu karar verir.
  if (e2e === web) {
    const h = kosuHali();
    return ozet(mk ? h : "onarildi");
  }
  return ozet(kosuHali());
}

/** Main zaten kırık mı (uygulama `cart-add`, test tarafı onarılmamış)? */
export function zatenKirik(d: DemoDurumu | null, kosular: Kosu[] | null = null): boolean {
  return locatorDurumu(d, kosular).hal === "kirik";
}

/**
 * `/demo/status`'taki son yenileme isteği bir kırılmaya aitse ilerleme yeniden kurulur (sayfadan
 * ayrılıp dönünce kart boş kalmaz); koşu ve triage yoklamayla bulunur.
 */
export function kirmaGeriYukle(d: DemoDurumu | null): KirmaDurumu | null {
  const i = d?.web_yenileme_istegi;
  if (!i || typeof i !== "object") return null;
  const x = i as Record<string, unknown>;
  if (x.eylem !== "break" || typeof x.zaman !== "string") return null;
  const basladi = Date.parse(x.zaman);
  if (Number.isNaN(basladi)) return null;
  // Main artık kırık değilse (sıfırlandı/onarıldı) eski kırılma ilerlemesi gösterilmez.
  if (d?.forge?.main_baseline_mi === true) return null;
  if (d?.locator_durumu === "baseline") return null;
  return {
    basladi,
    yanit: { job_id: null, durum: "done", mesaj: "Kırılma daha önce başlatıldı." },
    kosu: null,
    hatalar: null,
    bitti: false,
    geriYuklendi: true,
  };
}

/**
 * Onarım PR numarası triage kaydından (`oneri.pr`, core `/failures/{id}/fix` birleşik): en son merge
 * edilen locator onarımı. Yoksa null (koşulardan çıkarıma düşülür; numara uydurulmaz).
 */
export function onarimPrHatalardan(hatalar: HataAnalizi[]): number | null {
  const mergeli = hatalar
    .filter((h) => h.oneri?.tur === "locator_fix" && h.oneri.durum === "merged" && h.oneri.pr?.number)
    .sort((a, b) => b.zaman.localeCompare(a.zaman))[0];
  return mergeli?.oneri?.tur === "locator_fix" ? (mergeli.oneri.pr?.number ?? null) : null;
}

/** Kırmadan sonra başlayan ilk CI koşusu (yerel kontrol ve kırarak doğrulama hariç). */
export function kirmaKosusu(kosular: Kosu[], basladi: number, runId?: string | null): Kosu | null {
  if (runId) {
    const k = kosular.find((x) => x.id === runId);
    if (k) return k;
  }
  const adaylar = kosular.filter(
    (k) => !["local_check", "break_verify"].includes(k.tetik) && Date.parse(k.baslangic) >= basladi - 5000,
  );
  return adaylar.sort((a, b) => Date.parse(a.baslangic) - Date.parse(b.baslangic))[0] ?? null;
}

function SinifEtiketi({ sinif }: { sinif: HataSinifi | null }) {
  if (!sinif) return <Cip ton="notr">sınıflandırılıyor</Cip>;
  const x = HATA_SINIFI[sinif];
  return <Cip ton={x.ton}>{x.etiket}</Cip>;
}

/**
 * core demo olayı → günlük satırı (core olayları `mesaj` taşımaz; varsa o kullanılır). `islem`:
 * olay hangi işleme ait (break | reset); bilinmiyorsa null.
 */
export function demoOlayMetni(o: PortalOlayi): { islem: "break" | "reset" | null; mesaj: string } | null {
  const d = o.data;
  const m = typeof d.mesaj === "string" ? d.mesaj : null;
  const eylem = d.eylem === "reset" || d.islem === "reset" ? "reset" : d.eylem === "break" || d.islem === "break" ? "break" : null;
  const kisa = (x: unknown) => (typeof x === "string" ? x.slice(0, 10) : "");
  switch (o.type) {
    case "demo.break":
      return { islem: "break", mesaj: m ?? `Kırılma main'e merge edildi (demo-admin bypass, denetim: demo kırılması)${d.merge_sha ? ` · ${kisa(d.merge_sha)}` : ""}.` };
    case "demo.break_failed":
      return { islem: "break", mesaj: m ?? `Kırılma başarısız: ${typeof d.hata === "string" ? d.hata : "bilinmeyen hata"}` };
    case "demo.web_waiting":
      return {
        islem: eylem,
        mesaj: m ?? `Demo uygulamasının main'den yeniden kurulması bekleniyor… ${typeof d.yonerge === "string" ? d.yonerge : ""}`.trim(),
      };
    case "demo.web_ready":
      return { islem: eylem, mesaj: m ?? `Demo uygulaması main'i yansıtıyor${d.uygulama_sha ? ` (${kisa(d.uygulama_sha)})` : ""}.` };
    case "demo.web_timeout":
      return { islem: eylem, mesaj: m ?? `Demo uygulaması zamanında yenilenmedi. ${typeof d.yonerge === "string" ? d.yonerge : ""}`.trim() };
    case "demo.ci_enqueued":
      return { islem: eylem, mesaj: m ?? "CI koşusu kuyruğa alındı." };
    case "demo.ci_skipped":
      return { islem: eylem, mesaj: m ?? "CI koşusu başlatılmadı." };
    case "demo.reset":
      return { islem: "reset", mesaj: m ?? "Demo başlangıç durumuna döndü (main → demo-baseline)." };
    case "demo.progress":
      return m ? { islem: eylem ?? "break", mesaj: m } : null;
    default:
      return m ? { islem: eylem, mesaj: m } : null;
  }
}

/**
 * Sıfırlama işinin özeti (core `run_reset` dönüşü; 200 `sonuc` ya da `demo.reset` olayı) → Türkçe
 * satırlar. Yapılmayan adımlar (jira-sim atlandı, veritabanı dokunulmadı) açıkça yazılır.
 */
export function sifirlamaOzeti(o: Record<string, unknown> | null | undefined): { ton: "basari" | "uyari" | "hata"; metin: string }[] {
  if (!o || typeof o !== "object") return [];
  const n = (x: unknown) => (x && typeof x === "object" ? (x as Record<string, unknown>) : {});
  const sat: { ton: "basari" | "uyari" | "hata"; metin: string }[] = [];
  const f = n(o.forge);
  if (Object.keys(f).length) {
    const sha = typeof f.main_sonra === "string" ? ` (${f.main_sonra.slice(0, 10)})` : "";
    sat.push({ ton: "basari", metin: f.degisti === false ? `Forge main zaten demo-baseline'daydı${sha}.` : `Forge main demo-baseline'a döndü${sha}.` });
  }
  if (Array.isArray(o.kapanan_prlar)) {
    const k = o.kapanan_prlar.map(n);
    const hatali = k.filter((x) => x.hata);
    sat.push({ ton: hatali.length ? "uyari" : "basari", metin: `Açık demo PR'ları kapatıldı: ${k.length - hatali.length}${hatali.length ? ` (${hatali.length} kapatılamadı)` : ""}.` });
  }
  const w = n(o.web);
  if (w.durum) {
    const wd = String(w.durum);
    sat.push(
      wd === "atlandi"
        ? { ton: "uyari", metin: "Demo uygulaması yeniden kurulmadı (yenileme kapalı)." }
        : wd === "hata"
          ? { ton: "hata", metin: `Demo uygulaması yenileme isteği yazılamadı: ${String(w.hata ?? "bilinmeyen hata")}` }
          : { ton: "basari", metin: "Demo uygulamasının main'den yeniden kurulması istendi; CI uygulama yenilenince başlar." },
    );
  }
  const j = n(o.jira);
  if (j.durum === "tamam") sat.push({ ton: "basari", metin: "jira-sim seed durumuna döndü." });
  else if (j.durum) sat.push({ ton: "uyari", metin: `Jira sıfırlanmadı${j.neden ? ` (${String(j.neden)})` : ""}: host'ta \`make demo-reset\` çalıştırın.` });
  const v = n(o.veritabani);
  if (v.durum === "dokunulmadi") sat.push({ ton: "uyari", metin: "Kararlar, taslaklar ve koşu geçmişi korunur: tam sıfırlama için host'ta `make reset`." });
  return sat;
}

function useGunluk(): [Gunluk[], (m: string) => void, () => void] {
  const [g, setG] = useState<Gunluk[]>([]);
  const ekle = useCallback((mesaj: string) => setG((x) => [...x, { zaman: new Date().toISOString(), mesaj }]), []);
  const temizle = useCallback(() => setG([]), []);
  return [g, ekle, temizle];
}

function LocatorKirmaKarti({ durum }: { durum: DemoDurumu | null }) {
  const bildir = useBildirim();
  const [onay, setOnay] = useState(false);
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const [d, setD] = useState<KirmaDurumu | null>(null);
  const [gunluk, ekle, temizle] = useGunluk();
  const runIdRef = useRef<string | null>(null);
  const [webBekliyor, setWebBekliyor] = useState<{ basladi: number; yonerge: string | null } | null>(null);
  const [simdi, setSimdi] = useState(() => Date.now());
  const [kosular, setKosular] = useState<Kosu[] | null>(null);

  // main'deki son CI koşusu (kırık mı, onarıldı mı?): açılışta, demo durumu değişince ve CI/PR olaylarında.
  const kosulariYukle = useCallback(async () => {
    try {
      setKosular(await api.kosular());
    } catch {
      /* koşu listesi yoksa durum yalnızca forge'dan türetilir */
    }
  }, []);
  useEffect(() => {
    void kosulariYukle();
  }, [durum, kosulariYukle]);
  useOlay(() => void kosulariYukle(), ["ci.status", "pr.merged"]);

  // Sayfaya dönüşte ilerlemeyi `/demo/status`'tan kur (bu oturumda başlatılmış bir kırılma yoksa).
  // Koşular (ve kırmızı koşunun triage'ı) okunmadan kurulmaz: yoksa onarılmış senaryoda yeşil
  // "onarıldı" ile birlikte "CI bekleniyor / uygulama kurulmadı / triage bekleniyor" bir an görünür.
  const geriYukleniyor = useRef(false);
  useEffect(() => {
    if (d || kosular === null || geriYukleniyor.current) return;
    const g = kirmaGeriYukle(durum);
    if (!g) return;
    geriYukleniyor.current = true;
    let iptal = false;
    void (async () => {
      const k = kirmaKosusu(kosular, g.basladi);
      let hatalar: KosuHatasi[] | null = null;
      if (k && (k.durum === "failed" || k.durum === "error")) {
        try {
          hatalar = kosuHatalari(await api.kosu(k.id));
        } catch {
          /* yoklama yeniden dener */
        }
      }
      const bitti = (k?.durum === "passed") || (!!hatalar && hatalar.length > 0 && hatalar.every((h) => h.sinif !== null));
      if (!iptal) setD((x) => x ?? { ...g, kosu: k, hatalar, bitti });
      geriYukleniyor.current = false;
    })();
    return () => {
      iptal = true;
      geriYukleniyor.current = false;
    };
  }, [durum, d, kosular]);

  // Onarım PR numarası triage kaydından (koşulardan çıkarım yalnızca yedek).
  const [onarimPrKaydi, setOnarimPrKaydi] = useState<number | null>(null);
  const onarildi = locatorDurumu(durum, kosular).hal === "onarildi";
  useEffect(() => {
    if (!onarildi) return;
    let iptal = false;
    void (async () => {
      try {
        const hatalar = await api.hatalar({ sinif: "test_maintenance" });
        let no = onarimPrHatalardan(hatalar);
        if (no === null) {
          const aday = hatalar
            .filter((h) => h.oneri?.tur === "locator_fix" && h.oneri.durum === "merged")
            .sort((a, b) => b.zaman.localeCompare(a.zaman))[0];
          if (aday) no = onarimPrHatalardan([await api.hata(aday.id)]);
        }
        if (!iptal) setOnarimPrKaydi(no);
      } catch {
        /* triage okunamadı: koşulardan çıkarım kalır */
      }
    })();
    return () => {
      iptal = true;
    };
  }, [onarildi]);


  // core'un ilerleme olayları (varsa): günlüğe yazılır, koşu kimliği yakalanır.
  useOlay(
    (o: PortalOlayi) => {
      if (!d || d.bitti) return;
      const x = demoOlayMetni(o);
      if (!x || x.islem === "reset") return;
      ekle(x.mesaj);
      if (typeof o.data.run_id === "string") runIdRef.current = o.data.run_id;
      if (o.type === "demo.web_waiting") setWebBekliyor({ basladi: Date.now(), yonerge: typeof o.data.yonerge === "string" ? o.data.yonerge : null });
      if (o.type === "demo.web_ready" || o.type === "demo.web_timeout" || o.type === "demo.ci_enqueued") setWebBekliyor(null);
    },
    ["demo.updated"],
  );

  // Koşu ve triage yoklaması (olay gelmese de ilerleme görünür).
  useEffect(() => {
    if (!d || d.bitti) return;
    let iptal = false;
    const zamanlayici = setTimeout(async () => {
      try {
        const kosular = await api.kosular();
        const k = kirmaKosusu(kosular, d.basladi, runIdRef.current);
        let hatalar: KosuHatasi[] | null = d.hatalar;
        let bitti = Date.now() - d.basladi > YOKLAMA_UST_SINIR_MS;
        if (k && (k.durum === "failed" || k.durum === "error")) {
          const detay = await api.kosu(k.id);
          hatalar = kosuHatalari(detay);
          bitti = bitti || (hatalar.length > 0 && hatalar.every((h) => h.sinif !== null));
        } else if (k?.durum === "passed") {
          bitti = true;
        }
        if (!iptal) {
          setD((x) => (x ? { ...x, kosu: k, hatalar, bitti } : x));
          if (k) setWebBekliyor(null);
        }
      } catch (e) {
        if (!iptal) setHata(hataMesaji(e));
      }
    }, YOKLAMA_MS);
    return () => {
      iptal = true;
      clearTimeout(zamanlayici);
    };
  }, [d]);

  async function kir() {
    setCalisiyor(true);
    setHata(null);
    temizle();
    runIdRef.current = null;
    setWebBekliyor(null);
    const basladi = Date.now();
    try {
      const y = await api.demoKir();
      ekle(y.mesaj ?? "Buton kimliği değiştirme isteği alındı.");
      // core işi ≤20 sn bekler: bittiyse sonuç CI koşusunun kimliğini taşıyabilir.
      const sonuc = (y as IsYaniti & { sonuc?: Record<string, unknown> }).sonuc;
      const runId = sonuc && (typeof sonuc.ci_run_id === "string" ? sonuc.ci_run_id : typeof sonuc.run_id === "string" ? sonuc.run_id : null);
      if (runId) runIdRef.current = runId;
      setD({ basladi, yanit: y, kosu: null, hatalar: null, bitti: false });
      bildir(y.mesaj ?? "Buton kimliği değiştiriliyor…");
      setOnay(false);
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setCalisiyor(false);
    }
  }

  const k = d?.kosu ?? null;
  const kd = k ? (KOSU_DURUMU[k.durum] ?? { etiket: k.durum, ton: "notr" as const }) : null;
  const locator = d?.hatalar?.find((h) => h.sinif === "test_maintenance") ?? null;
  const ldHam = locatorDurumu(durum, kosular);
  const ld = ldHam.hal === "onarildi" && onarimPrKaydi ? { ...ldHam, onarimPr: onarimPrKaydi } : ldHam;
  const kirik = ld.hal === "kirik";
  const desteksiz = durum?.locator_demo?.destekleniyor === false;
  const onKosul = durum?.onarim_on_kosulu ?? null;
  // Yeşil temel koşu yoksa core kırılmayı 409 ile reddeder (onarım "son yeşil yok" der): düğme pasif, yönerge görünür.
  const onKosulYok = onKosul?.hazir === false && ld.hal === "baseline";
  const kirmaPasif = ld.hal !== "baseline" || desteksiz || onKosulYok;
  const mk = ld.mainKosusu;
  // Kırılmanın kendi koşusu main'in son koşusuysa (henüz onarım yok) ayrıca "son adım" olarak gösterilmez.
  const onarimAdimlari = ld.hal === "onarildi" && mk && (!k || mk.id !== k.id);
  // CI koşusu henüz yokken web yenilemesi beklenir: ~20 sn sonra host komutu hatırlatılır.
  const beklemeBasi = webBekliyor?.basladi ?? (d && !d.bitti && !k ? d.basladi : null);
  const uzunBekleme = beklemeBasi !== null && !k && ld.hal !== "onarildi" && simdi - beklemeBasi >= WEB_BEKLEME_UYARI_MS;
  const yonerge = webBekliyor?.yonerge ?? durum?.uygulama?.yonerge ?? null;

  // Bekleme başlayınca sayaç da çalışsın (olay gelmese de).
  useEffect(() => {
    if (beklemeBasi === null || k) return;
    const t = setInterval(() => setSimdi(Date.now()), 1000);
    return () => clearInterval(t);
  }, [beklemeBasi, k]);

  return (
    <Kart
      baslik="Test bakımı demosu"
      eylemler={
        !onay && (
          <IslemDugmesi
            roller={["presenter"]}
            tur="tehlike"
            calisiyor={calisiyor}
            disabled={(!!d && !d.bitti) || kirmaPasif}
            // Her pasif hâlin (kipte yok, ön koşul yok, zaten kırık, CI sürüyor, onarıldı) kartta kendi
            // görünür notu var; düğme etiketi de hâli söyler. Neden tekrarlanmaz.
            nedenGizli
            title={
              desteksiz
                ? (durum?.locator_demo?.neden ?? "Test bakımı demosu bu kipte desteklenmiyor.")
                : onKosulYok
                  ? (onKosul?.yonerge ?? "Önce main için yeşil bir temel koşu gerekir.")
                  : ld.hal === "kirik"
                ? "Main zaten kırık (testId cart-add): önce onarımı merge edin ya da demoyu sıfırlayın."
                : ld.hal === "onarildi"
                  ? "Kırıldı ve onarıldı: yeniden kırmak için önce demoyu sıfırlayın (kırılma baseline'dan yapılır)."
                  : ld.hal === "dogrulaniyor"
                    ? "Main'deki CI koşusu sürüyor; sonuç bekleniyor."
                    : undefined
            }
            onClick={() => setOnay(true)}
          >
            {desteksiz
              ? "Bu kipte yok"
              : onKosulYok
                ? "Önce yeşil temel koşu"
                : ld.hal === "kirik"
                  ? "Buton kimliği zaten değişti"
                  : ld.hal === "onarildi"
                    ? "Önce demoyu sıfırlayın"
                    : ld.hal === "dogrulaniyor"
                      ? "CI sürüyor"
                      : "Buton kimliğini değiştir"}
          </IslemDugmesi>
        )
      }
    >
      <Uyari ton="bilgi" baslik="Bu demo ne gösteriyor? Test bakımı">
        <div data-testid="locator-aciklama">
          <p>
            Otomasyonun asıl maliyeti yazmak değil <strong>bakımı</strong>. Bir geliştirici "Sepete ekle" butonunun teknik kimliğini
            değiştirir; işlev aynı, uygulama sağlam — ama o butona tıklayan bütün testler kırmızı olur. Klasik otomasyonda bu, sabah
            onlarca kırmızı test ve tek tek "uygulama mı bozuk, test mi?" incelemesi demektir.
          </p>
          <ol>
            <li>
              <strong>Ayırt eder</strong> (kural, AI yok): butonun rolü ve adı sayfada duruyor, yalnız kimliği değişmiş → ürün hatası
              değil, <em>test bakımı</em>. Kırmızılar için tek tek bug açılmaz.
            </li>
            <li>
              <strong>Tek satırlık onarım önerir</strong>: yalnız kimlik değeri değişir; AST koruması testin neyi kontrol ettiğine
              (assertion) dokunulamayacağını garanti eder — gerçek bir hata testi değiştirerek gizlenemez.
            </li>
            <li>
              <strong>İnsan onaylar</strong>: mühendis bir satırlık farkı görüp merge eder; testler yeşile döner.
            </li>
          </ol>
          <p className="kucuk">Bu düğme o geliştiriciyi taklit eder: kimliği değiştiren commit'i ana dala alır, uygulamayı yeniden kurar, CI'ı başlatır.</p>
        </div>
      </Uyari>
      <details className="soluk kucuk">
        <summary>Teknik ayrıntı</summary>
        <span className="mono">demo/break-locator</span> dalı (Sepete ekle butonunun <span className="mono">data-testid</span>'i{" "}
        <span className="mono">add-to-cart</span> → <span className="mono">cart-add</span>) demo-admin yetkisiyle korumalı ana dala
        merge edilir; işlem denetime "demo kırılması" olarak yazılır. Çalışan demo uygulaması main'den yeniden kurulur, CI kırmızıya
        döner, triage "test bakımı / locator" der ve onarım önerir. Onarım PR'ını mühendis açar ve onaylar.
      </details>
      {desteksiz && (
        <Uyari ton="hata" baslik="Test bakımı demosu bu kipte yok">
          <span data-testid="locator-desteksiz">{durum?.locator_demo?.neden ?? "Yalnızca yerel forge'da (TP_FORGE=local) desteklenir."}</span>
        </Uyari>
      )}
      {!desteksiz && onKosulYok && (
        <Uyari ton="uyari" baslik="Önce yeşil temel koşu">
          <span data-testid="on-kosul-yok">
            {onKosul?.yonerge ?? "Main için yeşil bir koşu olmadan kırılırsa onarım 'son yeşil yok' diye engellenir."}{" "}
            <Link to="/kosular">Koşular</Link>
          </span>
        </Uyari>
      )}
      {!desteksiz && onKosul?.hazir === true && ld.hal === "baseline" && (
        <p className="kucuk" data-testid="on-kosul-hazir">
          <Cip ton="basari">ön koşul ✓</Cip> Son yeşil koşu{" "}
          {onKosul.son_yesil_kosu?.run_id ? (
            <Link to={`/kosular/${encodeURIComponent(onKosul.son_yesil_kosu.run_id)}`} className="mono">
              {kisaKosuAdi(onKosul.son_yesil_kosu.run_id)}
            </Link>
          ) : (
            "var"
          )}
          {onKosul.son_yesil_kosu?.tetik && <span className="soluk"> ({TETIK[onKosul.son_yesil_kosu.tetik as keyof typeof TETIK] ?? onKosul.son_yesil_kosu.tetik})</span>}: onarımın rol + ad
          doğrulaması bu koşunun aria kanıtıyla yapılır.
        </p>
      )}
      {onay && (
        <div className="onay-kutusu" role="group" aria-label="Buton kimliği değiştirme onayı">
          <p>
            <strong>Emin misiniz?</strong> Korumalı ana dala demo kırılması merge edilecek ve demo uygulaması yeniden kurulacak. Onarım
            merge edilene kadar katalog testleri kırmızı kalır.
          </p>
          <div className="satir-ogeler">
            <IslemDugmesi roller={["presenter"]} tur="tehlike" calisiyor={calisiyor} onClick={() => void kir()}>
              Evet, buton kimliğini değiştir
            </IslemDugmesi>
            <button type="button" className="dugme dugme-ikincil" onClick={() => setOnay(false)} disabled={calisiyor}>
              Vazgeç
            </button>
          </div>
        </div>
      )}
      {hata && (
        <Uyari ton="hata" baslik="Değişiklik başlatılamadı">
          {hata}
        </Uyari>
      )}
      {kirik && (
        <p className="kucuk" data-testid="zaten-kirik">
          Main zaten kırık: Sepete ekle <span className="mono">data-testid</span>'i <span className="mono">cart-add</span>. Yeniden kırmak
          gerekmez; onarım PR'ını merge edin ya da demoyu sıfırlayın.
        </p>
      )}
      {ld.hal === "dogrulaniyor" && (
        <p className="kucuk" data-testid="main-ci-suruyor">
          Main'in son commit'inde CI koşuyor{mk && <> (<Link to={`/kosular/${encodeURIComponent(mk.id)}`} className="mono">{kisaKosuAdi(mk.id)}</Link>)</>};
          sonuç gelince kırık ya da onarıldı olarak gösterilir.
        </p>
      )}
      {ld.hal === "onarildi" && (
        <Uyari ton="basari" baslik="Kırıldı ve onarıldı">
          <span data-testid="onarildi">
            {ld.onarimPr ? `Onarım PR #${ld.onarimPr} merge edildi` : "Onarım main'de"}
            {mk ? `, CI yeşil (${mk.gecen}/${mk.toplam})` : ""}. Uygulama ve testler aynı testId'yi (<span className="mono">cart-add</span>)
            kullanıyor. Tekrar prova için demoyu sıfırlayın.
          </span>
        </Uyari>
      )}
      {uzunBekleme && (
        <Uyari ton="uyari" baslik="Demo uygulaması hâlâ yeniden kurulmadı">
          CI, çalışan uygulama main'i yansıtınca başlar. {yonerge ?? "Host'ta `make demo-web-sync A=--watch` çalıştırın."}
        </Uyari>
      )}
      {d && (
        <ol className="demo-adimlari" aria-label="Locator kırılması ilerlemesi">
          <li>
            <Cip ton="basari">tamam</Cip>
            <span>
              {d.geriYuklendi ? `Kırılma istendi (${saat(new Date(d.basladi).toISOString())})` : "İstek alındı"}
              {d.yanit.job_id && <span className="mono kucuk soluk"> · iş {d.yanit.job_id}</span>}
            </span>
          </li>
          <li>
            <Cip ton={k ? (kd?.ton ?? "notr") : "bilgi"}>{k ? kd?.etiket : "bekleniyor"}</Cip>
            <span>
              CI koşusu{" "}
              {k ? (
                <>
                  <Link to={`/kosular/${encodeURIComponent(k.id)}`} className="mono">
                    {kisaKosuAdi(k.id)}
                  </Link>{" "}
                  <span className="soluk kucuk">({TETIK[k.tetik] ?? k.tetik})</span>
                </>
              ) : (
                <span className="soluk kucuk">merge ve yeniden kurulum sonrası başlar…</span>
              )}
            </span>
          </li>
          <li>
            {d.hatalar && d.hatalar.length > 0 ? <SinifEtiketi sinif={locator?.sinif ?? d.hatalar[0].sinif} /> : <Cip ton="notr">bekleniyor</Cip>}
            <span>
              Triage{" "}
              {d.hatalar && d.hatalar.length > 0 ? (
                <Link to={`/hatalar/${encodeURIComponent((locator ?? d.hatalar[0]).id)}`}>
                  {ld.hal === "onarildi" ? "triage kaydını aç" : "onarım önerisini aç"}
                </Link>
              ) : k?.durum === "passed" ? (
                <span className="soluk kucuk">koşu yeşil bitti; kırılma etkisini göstermedi</span>
              ) : (
                <span className="soluk kucuk">kırmızı koşu sınıflandırılınca görünür</span>
              )}
            </span>
          </li>
          {onarimAdimlari && (
            <>
              <li>
                <Cip ton="basari">merge edildi</Cip>
                <span>
                  Onarım PR'ı{" "}
                  {ld.onarimPr ? <span className="mono">#{ld.onarimPr}</span> : <span className="soluk kucuk">(numara bulunamadı)</span>}{" "}
                  <span className="soluk kucuk">· main {mk.commit.slice(0, 10)}</span>
                </span>
              </li>
              <li>
                <Cip ton="basari">{KOSU_DURUMU.passed?.etiket ?? "Geçti"}</Cip>
                <span>
                  Main CI koşusu{" "}
                  <Link to={`/kosular/${encodeURIComponent(mk.id)}`} className="mono">
                    {kisaKosuAdi(mk.id)}
                  </Link>{" "}
                  <span className="soluk kucuk">
                    ({TETIK[mk.tetik] ?? mk.tetik}, {mk.gecen}/{mk.toplam} geçti)
                  </span>
                </span>
              </li>
            </>
          )}
        </ol>
      )}
      {gunluk.length > 0 && (
        <details className="kucuk" open>
          <summary>Olay günlüğü</summary>
          <ul className="duz-liste" aria-label="Demo olay günlüğü">
            {gunluk.map((g, i) => (
              <li key={`${g.zaman}-${i}`}>
                <span className="mono soluk">{saat(g.zaman)}</span> {g.mesaj}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Kart>
  );
}

function SifirlamaKarti() {
  const bildir = useBildirim();
  const [onay, setOnay] = useState(false);
  const [anladim, setAnladim] = useState(false);
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const [sonuc, setSonuc] = useState<IsYaniti | null>(null);
  const [sifirlandi, setSifirlandi] = useState(false);
  const [ozet, setOzet] = useState<Record<string, unknown> | null>(null);
  const [gunluk, ekle, temizle] = useGunluk();

  useOlay(
    (o: PortalOlayi) => {
      if (!sonuc) return;
      const x = demoOlayMetni(o);
      if (x && x.islem !== "break") ekle(x.mesaj);
      if (o.type === "demo.reset") {
        setSifirlandi(true);
        setOzet(o.data);
      }
    },
    ["demo.updated"],
  );

  async function sifirla() {
    setCalisiyor(true);
    setHata(null);
    setSifirlandi(false);
    setOzet(null);
    temizle();
    try {
      const y = await api.demoSifirla();
      setSonuc(y);
      const s = (y as IsYaniti & { sonuc?: unknown }).sonuc;
      if (s && typeof s === "object") setOzet(s as Record<string, unknown>);
      ekle(y.mesaj ?? "Sıfırlama isteği alındı.");
      bildir(y.mesaj ?? "Demo sıfırlanıyor.");
      setOnay(false);
      setAnladim(false);
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setCalisiyor(false);
    }
  }

  const bitti = sifirlandi || (sonuc && ["done", "completed", "tamam"].includes(sonuc.durum));
  const ozetSatirlari = sifirlamaOzeti(ozet);
  return (
    <Kart
      baslik="Demo'yu sıfırla"
      eylemler={
        !onay && (
          <IslemDugmesi roller={["presenter"]} tur="ikincil" calisiyor={calisiyor} onClick={() => setOnay(true)}>
            Demo'yu sıfırla
          </IslemDugmesi>
        )
      }
    >
      <p className="soluk kucuk">
        Forge ana dalı <span className="mono">demo-baseline</span>'a döner, açık demo PR'ları kapatılır, demo uygulaması main'den yeniden
        kurulur ve CI koşar. Kararlar, bug taslakları ve koşu geçmişi korunur (tam sıfırlama: host'ta <span className="mono">make reset</span>);
        jira-sim sıfırlanmaz: yalnızca bu sistemin açtığı AI Bug'ları (<span className="mono">AI-generated</span> +{" "}
        <span className="mono">tp-&lt;uuid&gt;</span>) silinir; TPD-5, story ve Test issue'ları kalır.
        Denetim kaydı silinmez (append-only); sıfırlama da denetime yazılır.
      </p>
      {onay && (
        <div className="onay-kutusu" role="group" aria-label="Sıfırlama onayı">
          <label className="satir-ogeler">
            <input type="checkbox" checked={anladim} onChange={(e) => setAnladim(e.target.checked)} />
            <span>Forge main baseline'a dönecek ve açık demo PR'ları kapatılacak (kararlar ve Jira kayıtları bu düğmeyle sıfırlanmaz).</span>
          </label>
          <div className="satir-ogeler">
            <IslemDugmesi roller={["presenter"]} tur="tehlike" calisiyor={calisiyor} disabled={!anladim} onClick={() => void sifirla()}>
              Sıfırla
            </IslemDugmesi>
            <button type="button" className="dugme dugme-ikincil" onClick={() => setOnay(false)} disabled={calisiyor}>
              Vazgeç
            </button>
          </div>
        </div>
      )}
      {hata && (
        <Uyari ton="hata" baslik="Sıfırlanamadı">
          {hata}
        </Uyari>
      )}
      {sonuc && (
        <ol className="demo-adimlari" aria-label="Sıfırlama ilerlemesi">
          <li>
            <Cip ton="basari">tamam</Cip>
            <span>
              İstek alındı{sonuc.job_id && <span className="mono kucuk soluk"> · iş {sonuc.job_id}</span>}
            </span>
          </li>
          <li>
            <Cip ton={bitti ? "basari" : "bilgi"}>{bitti ? "tamam" : "sürüyor"}</Cip>
            <span>{bitti ? "Forge ve demo uygulaması sıfırlandı; ayrıntı aşağıda." : "Sıfırlama sürüyor; bitince olay günlüğüne yazılır."}</span>
          </li>
        </ol>
      )}
      {ozetSatirlari.length > 0 && (
        <ul className="duz-liste kucuk" aria-label="Sıfırlama özeti" data-testid="sifirlama-ozeti">
          {ozetSatirlari.map((x) => (
            <li key={x.metin} className="satir-ogeler">
              <Cip ton={x.ton}>{x.ton === "basari" ? "yapıldı" : x.ton === "hata" ? "hata" : "yapılmadı"}</Cip>
              <span>{x.metin}</span>
            </li>
          ))}
        </ul>
      )}
      {gunluk.length > 0 && (
        <ul className="duz-liste kucuk" aria-label="Sıfırlama günlüğü">
          {gunluk.map((g, i) => (
            <li key={`${g.zaman}-${i}`}>
              <span className="mono soluk">{saat(g.zaman)}</span> {g.mesaj}
            </li>
          ))}
        </ul>
      )}
    </Kart>
  );
}

/** `/demo/status` (salt okuma): sayfa açılışında ve her demo olayında yenilenir. */
function useDemoDurumu(): DemoDurumu | null {
  const [d, setD] = useState<DemoDurumu | null>(null);
  const yukle = useCallback(async () => {
    try {
      setD(await api.demoDurumu());
    } catch {
      /* durum ucu yoksa kartlar durumsuz çalışır */
    }
  }, []);
  useEffect(() => {
    void yukle();
  }, [yukle]);
  useOlay(() => void yukle(), ["demo.updated"]);
  return d;
}

function DurumKarti({ d }: { d: DemoDurumu | null }) {
  if (!d) return null;
  const u = d.uygulama ?? {};
  const f = d.forge ?? {};
  const testid = typeof f.testid === "string" ? f.testid : f.testid && typeof f.testid === "object" ? JSON.stringify(f.testid) : null;
  return (
    <Kart baslik="Demo durumu">
      <dl className="tanim-izgara">
        <dt>Forge main</dt>
        <dd className="mono">
          {f.hata ? <span className="hata-metin">{f.hata}</span> : (f.main ?? "—").slice(0, 12)}
          {f.main_baseline_mi === true && <Cip ton="basari">baseline</Cip>}
          {f.main_baseline_mi === false && <Cip ton="uyari">baseline'dan farklı</Cip>}
        </dd>
        {testid && (
          <>
            <dt>Sepete ekle testId</dt>
            <dd className="mono">{testid}</dd>
          </>
        )}
        {d.locator_durumu && (
          <>
            <dt>Locator durumu</dt>
            <dd>
              <Cip ton={d.locator_durumu === "baseline" ? "basari" : d.locator_durumu === "kirik" ? "hata" : "notr"}>
                {d.locator_durumu === "baseline" ? "başlangıç" : d.locator_durumu === "kirik" ? "kırık" : "onarıldı"}
              </Cip>
            </dd>
          </>
        )}
        {d.onarim_on_kosulu && (
          <>
            <dt>Kırma ön koşulu</dt>
            <dd>
              {d.onarim_on_kosulu.hazir === true ? (
                <Cip ton="basari">yeşil temel koşu var</Cip>
              ) : d.onarim_on_kosulu.hazir === false ? (
                <Cip ton="uyari">yeşil temel koşu yok</Cip>
              ) : (
                <Cip ton="notr">bilinmiyor</Cip>
              )}
            </dd>
          </>
        )}
        <dt>Çalışan uygulama</dt>
        <dd className="mono">
          {(u.sha ?? "—").slice(0, 12)}{" "}
          {u.main_ile_eslesiyor === true && <Cip ton="basari">main ile eşleşiyor</Cip>}
          {u.main_ile_eslesiyor === false && <Cip ton="hata">main ile eşleşmiyor</Cip>}
        </dd>
      </dl>
      {u.neden && u.main_ile_eslesiyor === false && <p className="kucuk">{u.neden}</p>}
      {u.yonerge && <Uyari ton="uyari">{u.yonerge}</Uyari>}
    </Kart>
  );
}

export function DemoKontrolleri() {
  const durum = useDemoDurumu();
  return (
    <>
      <SayfaBasligi
        baslik="Demo kontrolleri"
        aciklama={
          <>
            Sunum için kırılma senaryoları. Hata yakalama (BREAK_CAMPAIGN) kod üretiminde 'Kırarak doğrula' ile, locator kırılması buradan
            başlatılır. Adım adım ilerleme: <Link to="/yol-haritasi">Demo yol haritası</Link>.
          </>
        }
      />
      <div className="iki-sutun">
        <LocatorKirmaKarti durum={durum} />
        <SifirlamaKarti />
      </div>
      <DurumKarti d={durum} />
    </>
  );
}

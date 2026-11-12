import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { BazKaynagi, CaseMetrikleri, KodUretimIsi, ManuelBaz, OtomatikKodSonucu, TestCase, TopluKararYaniti, TopluOtomatikKod } from "../api/types";
import { hataMesaji } from "../api/http";
import { bazKaynagiUyarla, manuelBazUyarla } from "../api/uyumFaz5";
import { useKisiAdi, useOturum } from "../auth";
import { BAZ_KAYNAGI } from "../components/BazDegerKarti";
import { CaseKarti, GORULDU_KURALI, goruntulemeAnahtari, goruntulenenKumesi, goruntulemeyiUnut, otomatikKodMetni } from "../components/CaseKarti";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, Metrik, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { HedefOlcer } from "../components/Grafikler";
import { useGeciktirilmis, useVeri } from "../hooks";
import { dolar, sure, yuzde } from "../lib/format";
import { YAYIN_ROLU_GEREKLI } from "./Yayin";

const ONAYLI = new Set(["approved", "published"]);

/** Düzeltme küçük mü: core bayrağı (`kucuk_duzeltme`) varsa o, yoksa §12 eşiği (ölçü ≤ 0,15). */
const kucukMu = (c: TestCase) => c.kucuk_duzeltme ?? (c.duzeltme_olcusu ?? 1) <= 0.15;

/**
 * Case sayaçları. Durum esastır: "Taslağa al" sonrası case `draft`'a döner ama core'un son karar
 * kaydı (`karar`) önceki kararı göstermeye devam eder — bu yüzden bekleyen = `draft`.
 * §12 kabul = onay + küçük düzeltmeyle onay / üretilen (yerel yaklaşık; çekirdek ölçümü varsa o).
 */
/** Core `TP_CT_REVIEW_MIN_S` varsayılanı (5 sn): bunun altındaki review süresi betik/API onayıdır, insan review'u sayılmaz. */
export const REVIEW_TABANI_MS = 5000;

export interface CaseBazi extends ManuelBaz {
  /** Baz değer (ms); ölçülmediyse null. Varsayılan (ortam) değer de burada durur ama kazanca girmez. */
  ms: number | null;
}

/**
 * Story başına manuel case hazırlama süresi (baz değer, TEKNIK-TASARIM §1.6/§12) ve KAYNAĞI.
 * Çekirdek `case-metrics` → `manuel_baz {deger_s, kaynak, giren, zaman, not}` (yoksa
 * `manuel_baz_ms` + `manuel_baz_kaynagi`). Kaynak bildirmeyen değer ölçüm sayılmaz (varsayılan).
 * Portal kendi baz değerini üretmez (derleme ayarı yok): değer yoksa "ölçülmedi".
 */
export function caseBazi(m?: CaseMetrikleri | null): CaseBazi {
  const yok: CaseBazi = { ms: null, deger_s: null, kaynak: "olculmedi", giren: null, zaman: null, not: null };
  if (!m) return yok;
  const ic = m.manuel_baz !== undefined && m.manuel_baz !== null ? manuelBazUyarla(m.manuel_baz) : undefined;
  if (ic) return { ...ic, ms: ic.deger_s === null ? null : Math.round(ic.deger_s * 1000) };
  const ms = typeof m.manuel_baz_ms === "number" && m.manuel_baz_ms > 0 ? m.manuel_baz_ms : null;
  if (ms === null) return yok;
  const ham = m.manuel_baz_kaynagi;
  const kaynak: BazKaynagi = ham === undefined || ham === null ? "varsayilan" : bazKaynagiUyarla(ham);
  if (kaynak === "olculmedi") return yok;
  return { ms, deger_s: ms / 1000, kaynak, giren: null, zaman: null, not: null };
}

export const KAZANC_REPLAY_NEDENI = "REPLAY: AI süresi ölçülmedi — kazanç hesaplanmaz (verimlilik iddiası değil)";

/**
 * Story kazancı (Kontrol Kulesi / core `kazanc_orani` ile aynı kural): yalnızca story'ye özel
 * ÖLÇÜLMÜŞ baz değerle (`olcum`) ve insan review süresi ölçülmüşse (≥ taban) hesaplanır.
 * Varsayılan baz değer kazanca girmez; 5 sn altı (betik/API) review ölçüm sayılmaz; AI süresi
 * ölçülmemişse (REPLAY) oran hesaplanmaz.
 */
export function caseKazanci(
  baz: CaseBazi,
  ozet: { aiSure: number; reviewSure: number; olculenReview: number },
  aiOlculmedi: boolean,
  taban = REVIEW_TABANI_MS,
): { oran: number | null; reviewOlculdu: boolean; hazirlikMs: number | null; neden: string | null } {
  const reviewOlculdu = ozet.olculenReview > 0 && ozet.reviewSure >= taban;
  const hazirlikMs = reviewOlculdu ? (aiOlculmedi ? ozet.reviewSure : ozet.aiSure + ozet.reviewSure) : null;
  let neden: string | null = null;
  if (baz.kaynak === "olculmedi" || baz.ms === null) neden = "baz değer ölçülmedi — kazanç hesaplanmaz";
  else if (baz.kaynak !== "olcum") neden = "ölçülmedi — varsayılan baz değer kazanca girmez";
  else if (!reviewOlculdu)
    neden =
      ozet.olculenReview > 0
        ? `review ${taban / 1000} sn altı (betik/API onayı) — kazanç hesaplanmaz`
        : "henüz review süresi ölçülmedi";
  // REPLAY: AI süresi ölçülmedi → yalnız review süresiyle oran, verimlilik iddiası değildir
  // (core `kazanca_girer`, Kontrol Kulesi `kazancOzeti` ile aynı kural; hedef %30–50'ye karşı gösterilmez).
  else if (aiOlculmedi) neden = KAZANC_REPLAY_NEDENI;
  const oran = neden === null && baz.ms && hazirlikMs ? 1 - hazirlikMs / baz.ms : null;
  return { oran, reviewOlculdu, hazirlikMs, neden: oran === null && neden === null ? "hazırlık süresi ölçülmedi" : neden };
}

/**
 * AI çağrılarının modu: hepsi kayıttan (replay / replay_miss) ise süre ve maliyet ölçülmemiştir
 * (REPLAY 0 ms / 0 token kaydeder); "0 ms / $0,00" ölçüm gibi gösterilmez. Bilinmiyorsa null.
 */
export function aiModu(caseler: TestCase[], m?: CaseMetrikleri | null): "live" | "replay" | "replay_miss" | "karisik" | null {
  const modlar = new Set<string>();
  if (m && Object.keys(m.ai_cagri_modlari ?? {}).length) {
    for (const [k, n] of Object.entries(m.ai_cagri_modlari)) if (n > 0) modlar.add(k);
  } else {
    for (const c of caseler) if (c.ai_generated && c.mode) modlar.add(c.mode);
  }
  if (modlar.size === 0) return null;
  if (!modlar.has("live")) return modlar.has("replay_miss") ? "replay_miss" : "replay";
  return modlar.size === 1 ? "live" : "karisik";
}

export function caseOzeti(caseler: TestCase[], m?: CaseMetrikleri | null) {
  const onayli = caseler.filter((c) => ONAYLI.has(c.durum));
  const onay = onayli.filter((c) => c.karar === "approve").length;
  const duzeltilmis = onayli.filter((c) => c.karar === "edit").length;
  const kucukDuzeltme = onayli.filter((c) => c.karar === "edit" && kucukMu(c)).length;
  const ret = caseler.filter((c) => c.durum === "rejected").length;
  const bekleyen = caseler.filter((c) => c.durum === "draft").length;
  const olculen = caseler.filter((c) => c.review_sure_ms !== null);
  const yerel = {
    uretilen: caseler.length,
    onay,
    duzeltilmis,
    ret,
    bekleyen,
    /** Hiç karar yoksa null: "%0 hedefin altında" denmez. */
    kabulOrani: caseler.length && caseler.some((c) => c.durum !== "draft") ? (onay + kucukDuzeltme) / caseler.length : (null as number | null),
    /** Kabul oranının kaynağı: çekirdek ölçümü (ilk karara göre, §12) ya da ekrandaki son durum. */
    kabulKaynagi: "yerel" as "cekirdek" | "yerel",
    aiSure: caseler.reduce((a, c) => a + c.ai_sure_ms, 0),
    reviewSure: olculen.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0),
    /** Review süresi ölçülen (görüntüleme → karar) case sayısı ve ortalaması. */
    olculenReview: olculen.length,
    ortReviewSure: olculen.length ? olculen.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0) / olculen.length : 0,
    maliyet: caseler.reduce((a, c) => a + c.maliyet_usd, 0),
  };
  if (!m) return yerel;
  return {
    ...yerel,
    kabulOrani: m.karar_verilen > 0 ? m.kabul_orani : null,
    kabulKaynagi: "cekirdek" as const,
    aiSure: m.ai_sure_ms,
    reviewSure: m.review_sure_ms,
    ortReviewSure: m.ort_review_sure_ms ?? 0,
    maliyet: m.maliyet_usd,
  };
}

type Filtre = "hepsi" | "bekleyen" | "onayli" | "reddedilen";

/** Toplu onay isteğinin üst sınırı (core 1..200 öğe); fazlası sırayla parçalanır. */
export const TOPLU_UST_SINIR = 200;

/**
 * 013 §3.2/K3/K13' toplu onay adayları: yalnız karar bekleyen (`draft`), bu oturumda kartı en az 3 sn
 * kesintisiz görünür kalan (yerel küme; anahtar `goruntulemeAnahtari`) ve onaya engeli olmayan case'ler.
 * Sunucunun `goruldu` bayrağı tek başına uygun saymaz (tur 3 QA #3): kart bir an görünse de sunucuda
 * kayıt açılır. Sunucu yine kendi ≥ 3 sn şartını uygular.
 */
export function topluOnayAdaylari(caseler: TestCase[], gorulenler: ReadonlySet<string> = new Set()) {
  const taslaklar = caseler.filter((c) => c.durum === "draft");
  const goruldu = (c: TestCase) => gorulenler.has(goruntulemeAnahtari(c));
  return {
    taslaklar,
    uygun: taslaklar.filter((c) => goruldu(c) && !c.onay_engeli),
    gorulmeyen: taslaklar.filter((c) => !goruldu(c)).length,
    engelli: taslaklar.filter((c) => goruldu(c) && !!c.onay_engeli).length,
    goruldu,
  };
}

/** Teyit anındaki hedef: id + ekranda görülen hash (liste değişirse teyit sıfırlanır). */
type HedefOge = Pick<TestCase, "id" | "icerik_hash">;
const hedefImzasi = (l: HedefOge[]) => l.map((c) => `${c.id}:${c.icerik_hash}`).join("|");

export interface TopluOnayCiktisi {
  yanit: TopluKararYaniti;
  /** Bir parça başarısız olduysa hatası (önceki parçaların sonucu `yanit`ta kalır). */
  hata: unknown;
  /** Hata yüzünden gönderilemeyen öğe sayısı. */
  gonderilmeyen: number;
  /** Parça başına açılan `codegen.otomatik` işleri (200'ü aşan onayda birden çok; sırayla). */
  kodIsleri?: string[];
}

/** Parçaların üst düzey otomatik kod sonuçlarını birleştirir (K16: parça başına tek iş). */
function otokodBirlestir(a: TopluOtomatikKod | null, b: TopluOtomatikKod | null): TopluOtomatikKod | null {
  if (!a) return b;
  if (!b) return a;
  const durum = a.durum === "kuyrukta" || b.durum === "kuyrukta" ? "kuyrukta" : a.durum === "kapali" || b.durum === "kapali" ? "kapali" : "yok";
  const atlanan = a.atlanan || b.atlanan ? [...(a.atlanan ?? []), ...(b.atlanan ?? [])] : undefined;
  return { durum, job_id: b.job_id ?? a.job_id, case_sayisi: a.case_sayisi + b.case_sayisi, ...(atlanan ? { atlanan } : {}) };
}

/**
 * İstekleri 200'lük parçalar halinde sırayla gönderir, sonuçları birleştirir. Bir parça hata verirse
 * durur; o ana kadarki sonuç kaybolmaz (kısmi sonuç + hata döner, fırlatmaz).
 */
export async function topluOnayla(
  ogeler: HedefOge[],
  gonder: (p: HedefOge[]) => Promise<TopluKararYaniti> = (p) => api.topluOnay(p),
): Promise<TopluOnayCiktisi> {
  const yanit: TopluKararYaniti = { sonuclar: [], ozet: { onaylandi: 0, atlandi: 0, hata: 0 }, otomatik_kod: null };
  const kodIsleri: string[] = [];
  for (let i = 0; i < ogeler.length; i += TOPLU_UST_SINIR) {
    try {
      const y = await gonder(ogeler.slice(i, i + TOPLU_UST_SINIR));
      yanit.sonuclar.push(...y.sonuclar);
      yanit.ozet.onaylandi += y.ozet.onaylandi;
      yanit.ozet.atlandi += y.ozet.atlandi;
      yanit.ozet.hata += y.ozet.hata;
      yanit.otomatik_kod = otokodBirlestir(yanit.otomatik_kod, y.otomatik_kod);
      const is_ = y.otomatik_kod?.durum === "kuyrukta" ? y.otomatik_kod.job_id : null;
      if (is_ && !kodIsleri.includes(is_)) kodIsleri.push(is_);
    } catch (e) {
      return { yanit, hata: e, gonderilmeyen: ogeler.length - i, kodIsleri };
    }
  }
  return { yanit, hata: null, gonderilmeyen: 0, kodIsleri };
}

const OTOKOD_ETIKET = { kuyrukta: "kuyrukta", kapali: "kapalı", atlandi: "atlandı", reddedildi: "başlatılamadı", hata: "hata" } as const;

/** Toplu onayın kod üretimi notu (K16: tek arka plan işi; eski core öğe başına gönderir). */
export function topluOtokodMetni(y: TopluKararYaniti, isSayisi = 1): string | null {
  const o = y.otomatik_kod;
  if (o) {
    const m = o.atlanan?.length ?? 0;
    const atlananNotu = m > 0 ? ` ${m} case kod üretimine alınmadı (aşağıda nedeni).` : "";
    if (o.durum === "kuyrukta")
      return `Otomatik kod üretimi: ${o.case_sayisi} case için web kodu üretimi kuyruğa alındı (${isSayisi > 1 ? `${isSayisi} arka plan işi; her 200 case'lik parça için bir iş` : "tek arka plan işi"}).${atlananNotu}`;
    if (o.durum === "kapali") return "Otomatik kod üretimi kapalı (Otomasyon ayarı); kodu Kod üretimi ekranından başlatın.";
    if (m > 0) return `Otomatik kod üretimi başlatılmadı: onaylanan ${m} case'in hiçbiri kod üretimine alınmadı (aşağıda nedeni).`;
    return y.ozet.onaylandi > 0 ? "Otomatik kod üretimi başlatılmadı: üretilecek case yok." : null;
  }
  const eski = y.sonuclar.filter((s) => s.durum === "onaylandi" && s.otomatik_kod);
  if (eski.length === 0) return null;
  const sayac = new Map<string, number>();
  for (const s of eski) sayac.set(s.otomatik_kod!.durum, (sayac.get(s.otomatik_kod!.durum) ?? 0) + 1);
  return `Otomatik kod üretimi: ${[...sayac.entries()].map(([d, n]) => `${n} ${OTOKOD_ETIKET[d as keyof typeof OTOKOD_ETIKET] ?? d}`).join(" · ")}${
    sayac.has("kapali") ? " (Otomasyon ayarından kapalı; kodu Kod üretimi ekranından başlatın)" : ""
  }`;
}

export interface TopluSonucDurumu {
  cikti: TopluOnayCiktisi;
  /** Gönderilen case'ler (ad gösterimi; liste yenilenince de ad kaybolmasın). */
  caseler: TestCase[];
}

export const TOPLU_SONUC_BASLIK_ID = "toplu-onay-sonucu-baslik";

/** §10 (K13'): sunucu, görüntüleme kaydından hemen sonra gelen kararı bu nedenle atlar (case görülmüş sayılır). */
export const YENI_GORUNTULEME_NEDENI = "Görüntüleme yeni kaydedildi";
export const yeniGoruntulemeMi = (neden: string | null) => !!neden && neden.startsWith(YENI_GORUNTULEME_NEDENI);

const IS_DURUMU_ETIKETI: Record<KodUretimIsi["durum"], string> = {
  kuyrukta: "kuyrukta (henüz başlamadı)",
  calisiyor: "sürüyor",
  tamam: "bitti",
  hata: "hata verdi",
};
const OTOKOD_SONUC_ETIKETI: Record<OtomatikKodSonucu["durum"], { etiket: string; ton: "basari" | "uyari" | "hata" | "notr" }> = {
  kuyrukta: { etiket: "üretim başladı", ton: "basari" },
  atlandi: { etiket: "atlandı", ton: "uyari" },
  reddedildi: { etiket: "başlatılamadı", ton: "hata" },
  kapali: { etiket: "ayar kapalı", ton: "notr" },
  hata: { etiket: "hata", ton: "hata" },
};

/** Toplu onayın kod üretimi işinin case başına sonucu (`GET /automation/codegen-jobs/{job_id}`). */
function KodUretimIsiOzeti({ jobId, ad }: { jobId: string; ad: (id: string) => string }) {
  const is_ = useVeri(() => api.kodUretimIsi(jobId), [jobId]);
  const v = is_.veri;
  return (
    <div className="toplu-kod-isi" data-testid="kod-uretim-isi">
      {is_.yukleniyor && !v ? (
        <p className="soluk kucuk">Kod üretimi sonucu okunuyor…</p>
      ) : is_.hata && !v ? (
        <HataKutusu hata={is_.hata} kaynak={is_.hataNesnesi} yenile={() => void is_.yenile()} />
      ) : v ? (
        <>
          <p className="kucuk">
            Kod üretimi işi {IS_DURUMU_ETIKETI[v.durum]} · {v.case_sayisi} case
            {Object.entries(v.ozet).length > 0 &&
              ` · ${Object.entries(v.ozet)
                .map(([d, n]) => `${n} ${OTOKOD_SONUC_ETIKETI[d as OtomatikKodSonucu["durum"]]?.etiket ?? d}`)
                .join(" · ")}`}
          </p>
          {v.hata && <p className="kucuk hata-metin">{v.hata}</p>}
          {v.sonuclar.length > 0 && (
            <ul className="duz-liste kucuk" aria-label="Case başına kod üretimi sonucu">
              {v.sonuclar.map((o) => {
                const e = OTOKOD_SONUC_ETIKETI[o.durum];
                return (
                  <li key={o.case_id}>
                    <Cip ton={e.ton}>{e.etiket}</Cip> {ad(o.case_id)}
                    {o.neden && <> — {o.neden}</>}
                    {o.script_id && (
                      <>
                        {" "}
                        · <Link to={`/kod/${encodeURIComponent(o.script_id)}`}>Teste git</Link>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {(v.durum === "kuyrukta" || v.durum === "calisiyor") && (
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void is_.yenile()}>
              Sonucu yenile
            </button>
          )}
        </>
      ) : null}
    </div>
  );
}

/** Bir kod üretimi işinin açılır özeti (200'ü aşan toplu onayda iş başına bir tane). */
function KodIsiCekmecesi({ jobId, sira, toplam, ad }: { jobId: string; sira: number; toplam: number; ad: (id: string) => string }) {
  const [acik, setAcik] = useState(false);
  const ayrintiId = `toplu-kod-isi-ayrinti-${sira}`;
  const ek = toplam > 1 ? ` (iş ${sira}/${toplam})` : "";
  return (
    <>
      <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-expanded={acik} aria-controls={ayrintiId} onClick={() => setAcik((a) => !a)}>
        {acik ? `Kod üretimi sonucunu gizle${ek}` : `Kod üretimi sonucunu göster${ek}`}
      </button>
      <div id={ayrintiId}>{acik && <KodUretimIsiOzeti jobId={jobId} ad={ad} />}</div>
    </>
  );
}

export function TopluOnaySonucu({ sonuc, kapat }: { sonuc: TopluSonucDurumu; kapat: () => void }) {
  const { yanit, hata, gonderilmeyen } = sonuc.cikti;
  const ad = (id: string) => {
    const c = sonuc.caseler.find((x) => x.id === id);
    return c ? `#${c.sira_no} ${c.icerik.title}` : id;
  };
  const sorunlu = yanit.sonuclar.filter((s) => s.durum !== "onaylandi");
  // Eski core: öğe başına otomatik kod notu (yeni core'da öğe `otomatik_kod` null).
  const otokodSorunlu = yanit.otomatik_kod
    ? []
    : yanit.sonuclar.filter((s) => s.durum === "onaylandi" && s.otomatik_kod && s.otomatik_kod.durum !== "kuyrukta" && s.otomatik_kod.durum !== "kapali");
  // Eski çağıranlar `kodIsleri` vermeyebilir: birleşik sonuçtaki tek iş kullanılır.
  const kodIsleri =
    sonuc.cikti.kodIsleri ?? (yanit.otomatik_kod?.durum === "kuyrukta" && yanit.otomatik_kod.job_id ? [yanit.otomatik_kod.job_id] : []);
  const otokod = topluOtokodMetni(yanit, kodIsleri.length);
  const otokodAtlanan = yanit.otomatik_kod?.atlanan ?? [];
  const yeniGoruntuleme = sorunlu.filter((s) => s.durum === "atlandi" && yeniGoruntulemeMi(s.neden)).length;
  const ton = hata || yanit.ozet.hata > 0 ? "hata" : yanit.ozet.atlandi > 0 ? "uyari" : "basari";
  return (
    <div className={`kart toplu-sonuc toplu-sonuc-${ton}`} data-ton={ton} role="status" data-testid="toplu-onay-sonucu">
      <h3 tabIndex={-1} className="toplu-sonuc-baslik" id={TOPLU_SONUC_BASLIK_ID}>
        Toplu onay: {yanit.ozet.onaylandi} onaylandı · {yanit.ozet.atlandi} atlandı{yanit.ozet.hata > 0 && ` · ${yanit.ozet.hata} hata`}
        {gonderilmeyen > 0 && ` · ${gonderilmeyen} gönderilemedi`}
      </h3>
      {hata != null && (
        <HataKutusu
          hata={`${yanit.sonuclar.length > 0 ? `İlk ${yanit.sonuclar.length} case işlendi; kalan ${gonderilmeyen} case gönderilemedi. ` : ""}${hataMesaji(hata)}`}
          kaynak={hata}
        />
      )}
      {sorunlu.length > 0 && (
        <ul className="duz-liste kucuk" aria-label="Onaylanmayan case'ler">
          {sorunlu.map((s) => (
            <li key={s.case_id}>
              <Cip ton={s.durum === "hata" ? "hata" : "uyari"}>{s.durum === "hata" ? "hata" : "atlandı"}</Cip> {ad(s.case_id)}
              {s.neden && <> — {s.neden}</>}
            </li>
          ))}
        </ul>
      )}
      {yeniGoruntuleme > 0 && (
        <p className="kucuk" data-testid="toplu-yeni-goruntuleme">
          {yeniGoruntuleme} case az önce ekranınıza geldiği için atlandı: görüntüleme kaydı en az 3 saniyelik olmalı. Birkaç saniye sonra
          "Tümünü onayla" ile yeniden deneyin; bu case'ler görülmüş sayılır.
        </p>
      )}
      {otokod && (
        <p className="kucuk" data-testid="toplu-otokod">
          {otokod}
        </p>
      )}
      {otokodAtlanan.length > 0 && (
        <ul className="duz-liste kucuk" aria-label="Kod üretimine alınmayan case'ler">
          {otokodAtlanan.map((a) => (
            <li key={a.case_id}>
              {ad(a.case_id)} — {a.neden ?? "Süren ya da açık PR'lı bir üretim var; yeniden üretim mühendis kararıyla."}
            </li>
          ))}
        </ul>
      )}
      {kodIsleri.map((j, i) => (
        <KodIsiCekmecesi key={j} jobId={j} sira={i + 1} toplam={kodIsleri.length} ad={ad} />
      ))}
      {otokodSorunlu.length > 0 && (
        <ul className="duz-liste kucuk" aria-label="Otomatik kod üretimi notları">
          {otokodSorunlu.map((s) => (
            <li key={s.case_id}>
              {ad(s.case_id)}: {otomatikKodMetni(s.otomatik_kod!)}
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={kapat}>
        Özeti kapat
      </button>
    </div>
  );
}

/**
 * Toplu onay çubuğu (013 §3.5): "Seçili onayla (n)" ve "Tümünü onayla (n)". Tarayıcı diyaloğu yok;
 * onay portalın kendi onay kutusuyla verilir. Teyit açılınca hedef (id + hash) sabitlenir; liste
 * değişirse teyit sıfırlanır. Her case ekranda görülen hash'iyle gönderilir.
 */
function TopluOnayCubugu({
  caseler,
  gorulenler,
  secili,
  setSecili,
  bitti,
}: {
  caseler: TestCase[];
  gorulenler: ReadonlySet<string>;
  secili: ReadonlySet<string>;
  setSecili: Dispatch<SetStateAction<Set<string>>>;
  /** İşlem bitti (başarılı, kısmi ya da hatalı): sonuç gösterilir, liste her durumda yenilenir. */
  bitti: (s: TopluSonucDurumu) => void;
}) {
  const [calisiyor, setCalisiyor] = useState(false);
  const [onay, setOnay] = useState<"secili" | "tumu" | null>(null);
  const [anladim, setAnladim] = useState(false);
  const [anlik, setAnlik] = useState<HedefOge[]>([]);
  const [listeDegisti, setListeDegisti] = useState(false);
  const teyitRef = useRef<HTMLInputElement>(null);
  const tetikleyen = useRef<"secili" | "tumu" | null>(null);
  // Onay sonrası otomatik kod ayarı teyit açılırken taze okunur (K16; başka kullanıcı değiştirmiş olabilir).
  const [otokod, setOtokod] = useState<"okunuyor" | "acik" | "kapali" | "bilinmiyor">("okunuyor");
  const ayarIstegi = useRef(0);
  const { uygun, gorulmeyen, engelli } = topluOnayAdaylari(caseler, gorulenler);
  const seciliUygun = uygun.filter((c) => secili.has(c.id));
  const hedef = onay === "tumu" ? uygun : seciliUygun;
  const imza = hedefImzasi(hedef);
  const notId = "toplu-onay-notu";

  // Teyit açıkken hedef liste değişirse (sessiz yenileme, yeni görüntüleme) teyit sıfırlanır.
  useEffect(() => {
    if (!onay || calisiyor) return;
    if (imza !== hedefImzasi(anlik)) {
      setAnlik(hedef.map((c) => ({ id: c.id, icerik_hash: c.icerik_hash })));
      setAnladim(false);
      setListeDegisti(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imza, onay, calisiyor]);

  function ac(tur: "secili" | "tumu") {
    const no = ++ayarIstegi.current;
    setOtokod("okunuyor");
    api
      .otomasyonAyarlari()
      .then((a) => no === ayarIstegi.current && setOtokod(a.otomatik_kod_uretimi.acik ? "acik" : "kapali"))
      .catch(() => no === ayarIstegi.current && setOtokod("bilinmiyor"));
    tetikleyen.current = tur;
    setOnay(tur);
    setAnladim(false);
    setListeDegisti(false);
    setAnlik((tur === "tumu" ? uygun : seciliUygun).map((c) => ({ id: c.id, icerik_hash: c.icerik_hash })));
    requestAnimationFrame(() => teyitRef.current?.focus());
  }

  function vazgec() {
    setOnay(null);
    setAnladim(false);
    const t = tetikleyen.current;
    tetikleyen.current = null;
    requestAnimationFrame(() => (document.querySelector(`[data-toplu="${t}"]`) as HTMLElement | null)?.focus());
  }

  async function onayla() {
    const gonderilen = anlik;
    const adlar = caseler.filter((c) => gonderilen.some((g) => g.id === c.id));
    setCalisiyor(true);
    try {
      const cikti = await topluOnayla(gonderilen);
      setOnay(null);
      setAnladim(false);
      tetikleyen.current = null;
      const onaylanan = new Set(cikti.yanit.sonuclar.filter((s) => s.durum === "onaylandi").map((s) => s.case_id));
      // İstek sürerken yapılan seçimler korunur (fonksiyonel güncelleme).
      setSecili((s) => new Set([...s].filter((x) => !onaylanan.has(x))));
      bitti({ cikti, caseler: adlar });
    } finally {
      setCalisiyor(false);
    }
  }

  const n = anlik.length;
  return (
    <section className="kart toplu-onay" aria-label="Toplu onay">
      <div className="satir-ogeler toplu-onay-cubuk">
        <IslemDugmesi
          roller={["analyst"]}
          kucuk
          data-toplu="secili"
          disabled={seciliUygun.length === 0 || onay !== null}
          title={seciliUygun.length === 0 ? "Onaylanacak case'leri kartlardaki kutularla seçin." : undefined}
          aria-describedby={notId}
          onClick={() => ac("secili")}
        >
          Seçili onayla ({seciliUygun.length})
        </IslemDugmesi>
        <IslemDugmesi
          roller={["analyst"]}
          kucuk
          tur="ikincil"
          data-toplu="tumu"
          disabled={uygun.length === 0 || onay !== null}
          title={uygun.length === 0 ? `Toplu onaya girecek taslak yok (yalnız ${GORULDU_KURALI}, onaya engeli olmayanlar).` : undefined}
          aria-describedby={notId}
          onClick={() => ac("tumu")}
        >
          Tümünü onayla ({uygun.length})
        </IslemDugmesi>
        {secili.size > 0 && (
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setSecili(new Set())}>
            Seçimi temizle
          </button>
        )}
      </div>
      <p id={notId} className="soluk kucuk" data-testid="toplu-onay-notu">
        Toplu onaya yalnız {GORULDU_KURALI} ve onaya engeli olmayan taslaklar girer; her case ekranda gördüğünüz içerikle onaylanır.
        {gorulmeyen > 0 && ` ${gorulmeyen} case en az 3 saniye ekranda kalmadığı için dışarıda.`}
        {" Sayım bu sayfaya özeldir: sayfa yenilenince case'lerin yeniden en az 3 saniye ekranda kalması gerekir."}
        {engelli > 0 && ` ${engelli} case onay engeli nedeniyle dışarıda.`}
      </p>
      {onay && (
        <div className="onay-kutusu" role="group" aria-label="Toplu onay teyidi">
          {listeDegisti && (
            <p className="kucuk hata-metin" role="alert">
              Liste değişti; hedef güncellendi. Teyidi yeniden verin.
            </p>
          )}
          <label className="satir-ogeler">
            <input ref={teyitRef} type="checkbox" checked={anladim} onChange={(e) => setAnladim(e.target.checked)} />
            <span>
              {n} taslak case onaylanacak ({onay === "tumu" ? `${GORULDU_KURALI}in tümü` : "seçilenler"}). Her case kendi görüntülenen
              içeriğiyle onaylanır; içeriği sonradan değişen case atlanır.
              {otokod === "acik" &&
                ` Onaylanan ${n} case için web kodu üretilecek (Otomasyon ayarı açık); açık PR'ı ya da süren üretimi olan case'lere dokunulmaz.`}
              {otokod === "bilinmiyor" && " Otomatik kod üretimi ayarı okunamadı; açıksa onaylananların web kodu üretilir."}
            </span>
          </label>
          <div className="satir-ogeler">
            <IslemDugmesi roller={["analyst"]} calisiyor={calisiyor} disabled={!anladim || n === 0} onClick={() => void onayla()}>
              Onayla ({n})
            </IslemDugmesi>
            <button type="button" className="dugme dugme-ikincil" disabled={calisiyor} onClick={vazgec}>
              Vazgeç
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export function CaseReview() {
  const { id = "" } = useParams();
  const gereksinim = useVeri(() => api.gereksinim(id), [id]);
  const caseler = useVeri(() => api.caseler(id), [id]);
  // Çekirdek ölçümü yoksa (uç henüz yok / hata) sayaçlar listeden hesaplanır.
  const metrik = useVeri(() => api.caseMetrikleri(id).catch(() => null), [id]);
  const [filtre, setFiltre] = useState<Filtre>("hepsi");
  // 013 toplu onay: seçim. "Görüldü" kümesi CaseKarti'nin oturum kaydından okunur (kişiye göre; K13');
  // küme değişince sayaç yeniden çizimi tetikler.
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [, setGorulmeSurumu] = useState(0);
  const gorulmeDegisti = () => setGorulmeSurumu((n) => n + 1);
  // Toplu onay sonucu çubuktan bağımsız tutulur: tüm taslaklar onaylanınca da görünür kalır.
  const [topluSonuc, setTopluSonuc] = useState<TopluSonucDurumu | null>(null);
  const kisiAdi = useKisiAdi();
  const sessiz = useGeciktirilmis(() => {
    void caseler.yenile(true);
    void metrik.yenile(true);
  });
  useOlay((o) => {
    // Başka gereksinimin olayı bu listeyi yenilemez (gereksinim kimliği taşıyorsa).
    if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== id) return;
    sessiz();
  }, ["case.generated", "case.updated", "requirement.updated", "publish.updated"]);

  const liste = caseler.veri ?? [];
  const ozet = useMemo(() => caseOzeti(liste, metrik.veri), [liste, metrik.veri]);
  const gorunen = liste.filter((c) =>
    filtre === "hepsi"
      ? true
      : filtre === "bekleyen"
        ? c.durum === "draft"
        : filtre === "onayli"
          ? c.durum === "approved" || c.durum === "published"
          : c.durum === "rejected",
  );
  const g = gereksinim.veri;
  const { kullanici } = useOturum();
  const kullaniciAnahtari = kullanici ? kullanici.id || kullanici.kullanici_adi : null;
  // Oturum (kişi/rol) değişince seçim başkasına geçmez (görüntüleme kaydı zaten kişiye göre).
  useEffect(() => {
    setSecili(new Set());
  }, [kullaniciAnahtari]);
  const gorulenler = goruntulenenKumesi(kullaniciAnahtari);
  const yayinYetkili = kullanici?.rol === "analyst";
  const karar = kullanici?.rol === "analyst";
  const toplu = topluOnayAdaylari(liste, gorulenler);
  const secimEngeli = (c: TestCase) =>
    !toplu.goruldu(c)
      ? `Toplu onaya yalnız ${GORULDU_KURALI} girer; kart ekranınızda kaldıkça kaydedilir.`
      : c.onay_engeli
        ? `Onaya engel: ${c.onay_engeli}`
        : null;
  const mod = aiModu(liste, metrik.veri);
  const aiOlculmedi = mod === "replay" || mod === "replay_miss";
  const baz = caseBazi(metrik.veri);
  const bazEtiket = BAZ_KAYNAGI[baz.kaynak];
  const taban = metrik.veri?.review_tabani_ms ?? REVIEW_TABANI_MS;
  const kz = caseKazanci(baz, ozet, aiOlculmedi, taban);
  const kazanc = kz.oran;
  const hazirlik = aiOlculmedi ? ozet.reviewSure : ozet.aiSure + ozet.reviewSure;
  const reviewBetik = ozet.olculenReview > 0 && !kz.reviewOlculdu;

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}`}>← {g?.jira_key ?? g?.baslik ?? "Gereksinim"}</Link>}
        baslik="Case review"
        aciklama={g ? `${g.jira_key ? `${g.jira_key} · ` : ""}${g.baslik}` : undefined}
        eylemler={
          yayinYetkili ? (
            <Link className="dugme dugme-birincil" to={`/gereksinimler/${encodeURIComponent(id)}/yayin`}>
              Yayın önizleme
            </Link>
          ) : (
            <IslemDugmesi tur="ikincil" disabled title={YAYIN_ROLU_GEREKLI}>
              Yayın önizleme
            </IslemDugmesi>
          )
        }
      />

      <Kart baslik="Özet" eylemler={aiOlculmedi ? <ReplayRozeti mode={mod} /> : undefined}>
        <div className="metrik-izgara">
          <Metrik etiket="Üretilen" deger={ozet.uretilen} />
          <Metrik etiket="Onaylı" deger={ozet.onay} />
          <Metrik etiket="Düzeltilerek onaylı" deger={ozet.duzeltilmis} />
          <Metrik etiket="Reddedilen" deger={ozet.ret} />
          <Metrik etiket="Karar bekleyen" deger={ozet.bekleyen} />
        </div>
        {/* İkinci şerit: süre ve maliyet (kararlar şeridiyle eşit sütun ritmi; 11 öğe tek şeritte 7+4 sarıyordu). */}
        <div className="metrik-izgara">
          <Metrik
            etiket="AI süresi"
            deger={aiOlculmedi ? "—" : sure(ozet.aiSure)}
            alt={aiOlculmedi ? "REPLAY — ölçülmedi" : mod === "karisik" ? "kısmen REPLAY (yalnız canlı çağrılar)" : undefined}
          />
          <Metrik
            etiket="Review süresi"
            deger={kz.reviewOlculdu ? sure(ozet.reviewSure) : "—"}
            alt={
              kz.reviewOlculdu
                ? `${ozet.olculenReview} case · ort. ${sure(ozet.ortReviewSure)}`
                : reviewBetik
                  ? `ölçülmedi — ${taban / 1000} sn altı (${sure(ozet.reviewSure)}): betik/API onayı, insan review'u sayılmaz`
                  : "henüz ölçülmedi"
            }
          />
          <Metrik
            etiket="AI + review"
            deger={aiOlculmedi && !kz.reviewOlculdu ? "—" : sure(kz.hazirlikMs ?? hazirlik)}
            alt={
              aiOlculmedi
                ? "yalnız review; AI süresi REPLAY'de ölçülmedi"
                : ozet.bekleyen > 0
                  ? `review sürüyor (${ozet.bekleyen} case bekliyor)`
                  : undefined
            }
          />
          <Metrik
            etiket="Manuel baz (story başına)"
            deger={
              <span data-testid="case-baz">
                {/* Ölçülmemiş baz: yalnız "Ölçülmedi" çipi (tire + çip + açıklamada üçüncü kez "ölçülmedi" yazılmaz). */}
                {baz.ms !== null ? `${sure(baz.ms)} ` : baz.kaynak === "olculmedi" ? null : "— "}
                <Cip ton={bazEtiket.ton} title={bazEtiket.aciklama}>
                  {bazEtiket.etiket}
                </Cip>
              </span>
            }
            alt={
              <span data-testid="case-baz-aciklama">
                {baz.kaynak === "olcum"
                  ? `ölçüm${baz.giren ? ` · ${kisiAdi(baz.giren)}` : ""}${baz.not ? ` · ${baz.not}` : ""}`
                  : baz.kaynak === "varsayilan"
                    ? "varsayılan (TP_MANUAL_BASELINE_S) — bu story için ölçülmedi, kazanca girmez"
                    : "bu story için baz değer girilmedi"}
              </span>
            }
          />
          <Metrik
            etiket="Kazanç"
            deger={<span data-testid="case-kazanc">{kazanc === null ? "—" : yuzde(kazanc)}</span>}
            alt={
              kazanc === null
                ? kz.neden
                : `hedef %30–50 · ölçülmüş baz${ozet.bekleyen > 0 ? ` · ara değer, ${ozet.bekleyen} case bekliyor` : ""}`
            }
          />
          <Metrik etiket="AI maliyeti" deger={aiOlculmedi ? "—" : dolar(ozet.maliyet)} alt={aiOlculmedi ? "REPLAY — ölçülmedi" : undefined} />
        </div>
        <HedefOlcer
          etiket={
            ozet.kabulKaynagi === "cekirdek"
              ? "Kabul oranı (ilk karar: onay + küçük düzeltme / üretilen)"
              : "Kabul oranı (onay + küçük düzeltme / üretilen)"
          }
          deger={ozet.kabulOrani}
          hedef={metrik.veri?.kabul_hedefi ?? 0.7}
          bosMetin="henüz karar yok"
        />
        {(metrik.veri?.kapsanmayan_ac?.length ?? 0) > 0 && (
          <Uyari baslik="Kapsanmayan kabul kriteri">
            Hiçbir güncel case şu kabul kriterlerine atıf yapmıyor: {metrik.veri!.kapsanmayan_ac!.join(", ")}. Reddetmeden önce kapsamı
            kontrol edin.
          </Uyari>
        )}
        {(metrik.veri?.uyarilar?.length ?? 0) > 0 && (
          <ul className="soluk kucuk" data-testid="metrik-uyarilari">
            {metrik.veri!.uyarilar!.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        )}
        <p className="soluk kucuk">
          Review süresi, case kartı ekranınızda en az 3 saniye kesintisiz kaldığında başlar ve kararınıza kadar sunucuda ölçülür.
          Yeniden açılan case'in süresi yeniden başlar.
        </p>
      </Kart>

      <div className="sekmeler sekmeler-yapiskan" role="group" aria-label="Case filtresi">
        {(
          [
            ["hepsi", `Hepsi (${liste.length})`],
            ["bekleyen", `Karar bekleyen (${ozet.bekleyen})`],
            ["onayli", `Onaylı (${liste.filter((c) => c.durum === "approved" || c.durum === "published").length})`],
            ["reddedilen", `Reddedilen (${ozet.ret})`],
          ] as [Filtre, string][]
        ).map(([k, etiket]) => (
          <button key={k} type="button" className={`sekme${filtre === k ? " aktif" : ""}`} aria-pressed={filtre === k} onClick={() => setFiltre(k)}>
            {etiket}
          </button>
        ))}
      </div>

      {karar && toplu.taslaklar.length > 0 && (
        <TopluOnayCubugu
          caseler={liste}
          gorulenler={gorulenler}
          secili={secili}
          setSecili={setSecili}
          bitti={(sonuc) => {
            setTopluSonuc(sonuc);
            // Onaylanan case'ler artık taslak değil: görüntüleme kaydı yeni karardan önce kaldı.
            const onaylanan = sonuc.cikti.yanit.sonuclar.filter((x) => x.durum === "onaylandi").map((x) => x.case_id);
            for (const cid of onaylanan) goruntulemeyiUnut(cid);
            gorulmeDegisti();
            // Başarılı, kısmi ya da hatalı: liste her durumda yenilenir.
            void caseler.yenile(true);
            void metrik.yenile(true);
            requestAnimationFrame(() => document.getElementById(TOPLU_SONUC_BASLIK_ID)?.focus());
          }}
        />
      )}
      {karar && topluSonuc && (
        <TopluOnaySonucu
          sonuc={topluSonuc}
          kapat={() => {
            setTopluSonuc(null);
            // Odak body'ye düşmesin: varsa "Tümünü onayla", yoksa filtre sekmesi.
            requestAnimationFrame(() => {
              const hedef =
                (document.querySelector('[data-toplu="tumu"]:not(:disabled)') as HTMLElement | null) ??
                (document.querySelector(".sekmeler .sekme.aktif") as HTMLElement | null);
              hedef?.focus();
            });
          }}
        />
      )}

      {caseler.yukleniyor && !caseler.veri ? (
        <Yukleniyor />
      ) : caseler.hata && !caseler.veri ? (
        <HataKutusu hata={caseler.hata} kaynak={caseler.hataNesnesi} yenile={() => void caseler.yenile()} />
      ) : gorunen.length === 0 ? (
        <Kart>
          <BosDurum baslik={liste.length ? "Bu filtrede case yok." : "Henüz case üretilmedi."}>
            {!liste.length && "PO teyidinden sonra gereksinim ekranından 'Case üret' ile başlatın."}
          </BosDurum>
        </Kart>
      ) : (
        <div className="case-liste">
          {gorunen.map((c) => (
            <CaseKarti
              key={c.id}
              tc={c}
              guncellendi={(t) => {
                caseler.setVeri(liste.map((x) => (x.id === t.id ? t : x)));
                // Karar ya da yeniden açma: "görüldü" kaydı CaseKarti'de silindi (sunucuda yeni eşik).
                gorulmeDegisti();
              }}
              yenile={() => void caseler.yenile(true)}
              secim={
                karar
                  ? {
                      secili: secili.has(c.id),
                      engel: secimEngeli(c),
                      degistir: (v) =>
                        setSecili((s) => {
                          const y = new Set(s);
                          if (v) y.add(c.id);
                          else y.delete(c.id);
                          return y;
                        }),
                    }
                  : undefined
              }
              goruntulendi={gorulmeDegisti}
            />
          ))}
        </div>
      )}
    </>
  );
}

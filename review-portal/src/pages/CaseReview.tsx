import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { ApiError } from "../api/http";
import type { AcikSorularYaniti } from "../api/acikSoruTipleri";
import type { BazKaynagi, CaseMetrikleri, ManuelBaz, TestCase } from "../api/types";
import { bazKaynagiUyarla, manuelBazUyarla } from "../api/uyumFaz5";
import { useKisiAdi, useOturum } from "../auth";
import { BAZ_KAYNAGI } from "../components/BazDegerKarti";
import { AcikSorularPaneli } from "../components/AcikSorular";
import { CaseListesi } from "../components/CaseListesi";
import { GherkinIndir } from "../components/GherkinIndir";
import { CASE_KARARLARI_ID, CaseDurumSeridi, useCaseListesineGit, yayinAcikMi } from "../components/CaseDurumSeridi";
import { DenetimPaneli, gonderBirincilMi, ReviewPaneli } from "../components/KalitePanelleri";
import { DerinlestirmePaneli } from "../components/DerinlestirmePaneli";
import { KapsamPaneli } from "../components/KapsamPaneli";
import { Cip, IslemDugmesi, Kart, Metrik, ReplayRozeti, SayfaBasligi, Uyari } from "../components/ui";
import { HedefOlcer } from "../components/Grafikler";
import { useGeciktirilmis, useVeri } from "../hooks";
import { caseEski, dogrulamayiYay, gonderilmemisSoruSayisi } from "../lib/caseV3";
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

/**
 * Review süresi kartının alt metni, süre ölçüm sayılmadığında. Toplu onay (K20) ayrı kategoridir:
 * kısa süre "betik/API onayı" diye yazılmaz (insan kararıdır ama kart başına süre vermez).
 */
export function reviewSuresiAlti(
  ozet: { reviewSure: number; topluOnay?: number },
  taban: number,
  tabanAlti: boolean,
): string {
  if (!tabanAlti) return "henüz ölçülmedi";
  if ((ozet.topluOnay ?? 0) > 0)
    return `ölçülmedi — toplu onay (${ozet.topluOnay} case): kart başına review süresi ölçülmez`;
  return `ölçülmedi — ${taban / 1000} sn altı (${sure(ozet.reviewSure)}): betik/API onayı, insan review'u sayılmaz`;
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
  ozet: { aiSure: number; reviewSure: number; olculenReview: number; topluOnay?: number },
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
        ? (ozet.topluOnay ?? 0) > 0
          ? "toplu onay: kart başına review süresi ölçülmedi — kazanç hesaplanmaz"
          : `review ${taban / 1000} sn altı (betik/API onayı) — kazanç hesaplanmaz`
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
    /** K20 toplu onayla verilen karar sayısı (yalnız çekirdek ölçümünden; yerelde bilinmez). */
    topluOnay: 0,
  };
  if (!m) return yerel;
  return {
    ...yerel,
    kabulOrani: m.karar_verilen > 0 ? m.kabul_orani : null,
    kabulKaynagi: "cekirdek" as const,
    aiSure: m.ai_sure_ms,
    reviewSure: m.review_sure_ms,
    ortReviewSure: m.ort_review_sure_ms ?? 0,
    topluOnay: m.toplu_onay_sayisi ?? 0,
    maliyet: m.maliyet_usd,
  };
}

export function CaseReview() {
  const { id = "" } = useParams();
  const gereksinim = useVeri(() => api.gereksinim(id), [id]);
  const caseler = useVeri(() => api.caseler(id), [id]);
  // Çekirdek ölçümü yoksa (uç henüz yok / hata) sayaçlar listeden hesaplanır.
  const metrik = useVeri(() => api.caseMetrikleri(id).catch(() => null), [id]);
  // Kapsam ve açık noktalar (011 §4.4). Uç yoksa (eski core: 404/501) özet yok sayılır; diğer hatalar gösterilir.
  const kapsam = useVeri(
    () =>
      api.caseSummary(id).catch((e: unknown) => {
        if (e instanceof ApiError && (e.status === 404 || e.status === 501)) return null;
        throw e;
      }),
    [id],
  );
  // P8 review ve P9 denetim (011 D). Uç yoksa (eski core) panel gösterilmez.
  const yoksaNull = (e: unknown) => {
    if (e instanceof ApiError && (e.status === 404 || e.status === 501)) return null;
    throw e;
  };
  const review = useVeri(() => api.caseReview(id).catch(yoksaNull), [id]);
  const denetim = useVeri(() => api.caseDenetim(id).catch(yoksaNull), [id]);
  const [kaliteIslem, setKaliteIslem] = useState<"review" | "denetim" | null>(null);
  // İşlem hatası ilgili panelin içinde gösterilir (UX-7: hata tek yerde).
  const [kaliteHata, setKaliteHata] = useState<{ tur: "review" | "denetim"; mesaj: string } | null>(null);
  const kaliteCalistir = async (tur: "review" | "denetim") => {
    setKaliteIslem(tur);
    setKaliteHata(null);
    try {
      if (tur === "review") review.setVeri(await api.caseReviewCalistir(id));
      else denetim.setVeri(await api.caseDenetimGonder(id));
    } catch (e) {
      setKaliteHata({ tur, mesaj: e instanceof Error ? e.message : String(e) });
    } finally {
      setKaliteIslem(null);
    }
  };
  const kisiAdi = useKisiAdi();
  const sessiz = useGeciktirilmis(() => {
    void caseler.yenile(true);
    void metrik.yenile(true);
    void kapsam.yenile(true);
    void review.yenile(true);
    void denetim.yenile(true);
  });
  useOlay((o) => {
    // Başka gereksinimin olayı bu listeyi yenilemez (gereksinim kimliği taşıyorsa).
    if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== id) return;
    sessiz();
  }, ["case.generated", "case.updated", "requirement.updated", "publish.updated", "case.review", "case.audit"]);

  const liste = caseler.veri ?? [];
  const ozet = useMemo(() => caseOzeti(liste, metrik.veri), [liste, metrik.veri]);
  const g = gereksinim.veri;
  const { kullanici } = useOturum();
  const yayinYetkili = kullanici?.rol === "analyst";
  const mod = aiModu(liste, metrik.veri);
  const aiOlculmedi = mod === "replay" || mod === "replay_miss";
  const baz = caseBazi(metrik.veri);
  const bazEtiket = BAZ_KAYNAGI[baz.kaynak];
  const taban = metrik.veri?.review_tabani_ms ?? REVIEW_TABANI_MS;
  const kz = caseKazanci(baz, ozet, aiOlculmedi, taban);
  const kazanc = kz.oran;
  const hazirlik = aiOlculmedi ? ozet.reviewSure : ozet.aiSure + ozet.reviewSure;
  const reviewBetik = ozet.olculenReview > 0 && !kz.reviewOlculdu;
  const yayinYolu = `/gereksinimler/${encodeURIComponent(id)}/yayin`;
  // Sayfada tek birincil eylem (UX-7): "Agent Probe'a gönder" birincilse yayın düğmesi ikincildir;
  // yayın düğmesi yalnız yayın kapısı açıkken birincil olur.
  const gonderBirincil = gonderBirincilMi(denetim.veri, ozet.bekleyen);
  const yayinBirincil = !gonderBirincil && yayinAcikMi(denetim.veri) && ozet.bekleyen === 0;
  const listeyeGit = useCaseListesineGit();
  // Açık soru paneli core listesini buraya bildirir (şerit + toplu onay uyarısı; UX4 Bulgu 2).
  const [acikSorular, setAcikSorular] = useState<AcikSorularYaniti | null>(null);

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}`}>← {g?.jira_key ?? g?.baslik ?? "Gereksinim"}</Link>}
        baslik="Case review"
        aciklama={g ? `${g.jira_key ? `${g.jira_key} · ` : ""}${g.baslik}` : undefined}
        eylemler={
          <>
            <GherkinIndir requirementId={id} anahtar={g?.jira_key ?? id} caseler={liste} />
            {yayinYetkili ? (
              <Link className={`dugme ${yayinBirincil ? "dugme-birincil" : "dugme-ikincil"}`} to={yayinYolu}>
                Yayın önizleme
              </Link>
            ) : (
              <IslemDugmesi tur="ikincil" disabled title={YAYIN_ROLU_GEREKLI}>
                Yayın önizleme
              </IslemDugmesi>
            )}
          </>
        }
      />

      {caseler.veri && liste.length > 0 && (
        <CaseDurumSeridi caseler={liste} denetim={denetim.veri} yayinYolu={yayinYolu} acikSorular={acikSorular?.sorular} />
      )}

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
                ? `${ozet.olculenReview} case · ort. ${sure(ozet.ortReviewSure)}${ozet.topluOnay ? ` · ${ozet.topluOnay} toplu onay` : ""}`
                : reviewSuresiAlti(ozet, taban, reviewBetik)
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
                    ? "varsayılan değer (yönetici ayarı) — bu story için ölçülmedi, kazanca girmez"
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
          Review süresi, case kartı ekranınıza ilk girdiği andan kararınıza kadar sunucuda ölçülür. Yeniden açılan case'in süresi yeniden
          başlar.
        </p>
      </Kart>

      {/* 011 P5/P6: derinleştirme bitince case listesi, kapsam özeti, ölçümler, review ve denetim tazelenir;
          "göster" listeyi o üretimin case'lerine süzer (`?uretim=`, A2 süzgeci) ve listeye kaydırır. */}
      {caseler.veri && liste.length > 0 && (
        <DerinlestirmePaneli
          gereksinim={g}
          tazele={() => {
            void gereksinim.yenile(true);
            void caseler.yenile(true);
            void metrik.yenile(true);
            void kapsam.yenile(true);
            void review.yenile(true);
            void denetim.yenile(true);
          }}
          goster={(no) => listeyeGit({ uretim: String(no) })}
        />
      )}

      {caseler.veri && (
        <KapsamPaneli
          ozet={kapsam.veri}
          yukleniyor={kapsam.yukleniyor}
          hata={kapsam.hata}
          hataKaynagi={kapsam.hataNesnesi}
          yenile={() => void kapsam.yenile()}
          caseSayisi={liste.length}
          eskiSema={liste.length > 0 && liste.every(caseEski)}
          baslangictaAcik={false}
          filtreSec={(f) => listeyeGit(f)}
        />
      )}

      {/* 011 K16: açık soruların PO'ya gönderimi ve yanıtları; gönderim/yanıt case listesini tazeler. */}
      {caseler.veri && liste.length > 0 && <AcikSorularPaneli requirementId={id} tazele={() => void caseler.yenile(true)} caseler={liste} veriDegisti={setAcikSorular} />}

      {review.veri !== null && caseler.veri && liste.length > 0 && (
        <ReviewPaneli
          gorunum={review.veri}
          yukleniyor={review.yukleniyor}
          hata={review.hata}
          hataKaynagi={review.hataNesnesi}
          yenile={() => void review.yenile()}
          calistir={() => void kaliteCalistir("review")}
          calisiyor={kaliteIslem === "review"}
          islemHata={kaliteHata?.tur === "review" ? kaliteHata.mesaj : null}
        />
      )}
      {denetim.veri !== null && caseler.veri && liste.length > 0 && (
        <DenetimPaneli
          gorunum={denetim.veri}
          yukleniyor={denetim.yukleniyor}
          hata={denetim.hata}
          hataKaynagi={denetim.hataNesnesi}
          yenile={() => void denetim.yenile()}
          gonder={() => void kaliteCalistir("denetim")}
          gonderiliyor={kaliteIslem === "denetim"}
          islemHata={kaliteHata?.tur === "denetim" ? kaliteHata.mesaj : null}
          bekleyen={ozet.bekleyen}
          toplam={liste.filter((c) => c.durum !== "rejected" && c.durum !== "superseded").length}
          yayinYolu={yayinYolu}
        />
      )}

      {/* Durum şeridi ve derinleştirme "göster" bağlantılarının hedefi (A1). */}
      <h2 id={CASE_KARARLARI_ID} className="bolum-basligi-case">
        Case kararları
      </h2>

      {/* A2: filtre sekmeleri (URL ?filtre= / ?uretim= / ?hazirlik= / ?teknik=), toplu onay ve case kartları. */}
      <CaseListesi
        liste={liste}
        gonderilmemisSoru={gonderilmemisSoruSayisi(acikSorular?.sorular)}
        yukleniyor={caseler.yukleniyor && !caseler.veri}
        hata={caseler.veri ? null : caseler.hata}
        hataNesnesi={caseler.hataNesnesi}
        yeniden={() => void caseler.yenile()}
        yenile={() => void caseler.yenile(true)}
        guncellendi={(t) => {
          caseler.setVeri(liste.map((x) => (x.id === t.id ? t : x)));
          // Karar/düzeltme kapsamı, hazır olma dağılımını ve setin kimliğini değiştirir.
          void kapsam.yenile(true);
          void review.yenile(true);
          void denetim.yenile(true);
        }}
        topluSonrasi={() => {
          void caseler.yenile(true);
          void metrik.yenile(true);
          void kapsam.yenile(true);
          void review.yenile(true);
          void denetim.yenile(true);
        }}
        uretimler={kapsam.veri?.uretimler}
        varsayimDogrulandi={(onceki, yeni, varsayimlar) => {
          // B2: aynı varsayıma dayanan diğer case'ler ve panel hemen "doğrulandı (#n)" der; ardından
          // liste sunucudan sessizce yenilenir (HazirlikYonlendirme `yenile`).
          caseler.setVeri(dogrulamayiYay(liste, onceki, yeni, varsayimlar));
          void kapsam.yenile(true);
          void review.yenile(true);
          void denetim.yenile(true);
        }}
      />
    </>
  );
}

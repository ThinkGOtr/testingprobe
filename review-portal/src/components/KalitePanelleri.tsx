import { useId, useState, type MouseEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { CaseDenetimGorunumu, CaseHaritasi, CaseReviewGorunumu, DenetimKarari, ReviewKarari } from "../api/types";
import type { Ton } from "../lib/etiketler";
import { denetimYonlendirmesi, hataMetniniAyikla, KAPI_KAPALI_METNI, yayinlanamaz } from "../lib/kalite";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaIciOnay, Uyari, Yukleniyor } from "./ui";

/** P8 madde kararı → etiket + ton. */
export const REVIEW_KARARI: Record<ReviewKarari, { etiket: string; ton: Ton }> = {
  UYGUN: { etiket: "Uygun", ton: "basari" },
  UYGUN_DEGIL: { etiket: "Uygun değil", ton: "hata" },
  ACIK_BILGI_GEREKLI: { etiket: "Açık bilgi gerekli", ton: "uyari" },
};

/** P9 karar → etiket + ton (yalnız KABUL yayına açar). */
export const DENETIM_KARARI: Record<DenetimKarari, { etiket: string; ton: Ton }> = {
  KABUL: { etiket: "KABUL", ton: "basari" },
  "DÜZELTME_GEREKLİ": { etiket: "DÜZELTME GEREKLİ", ton: "uyari" },
  ENGELLE: { etiket: "ENGELLE", ton: "hata" },
};

const RISK_TONU: Record<string, Ton> = { Yüksek: "hata", Orta: "uyari", Düşük: "notr" };

const KONTROL: Record<number, string> = {
  1: "Gereksinime bağlılık",
  2: "Veri gizliliği",
  3: "Yan etki",
  4: "Ortam",
  5: "Ölçülebilirlik",
  6: "Kapsam",
  7: "Otomasyon dürüstlüğü",
  8: "Gizli talimat",
  9: "Hazır olma",
};

/** Set numarası (C<n>) → case kartı bağlantısı (kart sayfadaysa oraya kaydırır). */
export function CaseRef({ no, harita }: { no: number | null; harita?: CaseHaritasi }) {
  if (no === null) return <span className="soluk">set düzeyi</span>;
  const c = harita?.[String(no)];
  if (!c) return <span>C{no}</span>;
  const git = (e: MouseEvent<HTMLAnchorElement>) => {
    const el = document.getElementById(`case-${c.id}`);
    if (!el) return;
    e.preventDefault();
    el.scrollIntoView?.({ block: "start" });
    el.focus({ preventScroll: true });
  };
  return (
    <a href={`#case-${c.id}`} onClick={git} title={c.title ?? undefined} data-testid="case-ref">
      C{no}
    </a>
  );
}

const kisaHash = (h: string | null | undefined) => (h ? h.slice(0, 12) : "—");

function Bolum({ baslik, children }: { baslik: string; children: ReactNode }) {
  return (
    <div className="kalite-bolum">
      <h4>{baslik}</h4>
      {children}
    </div>
  );
}

/**
 * Panelin ayrıntı bölümü (UX-3): panel özet satırına daralmış başlar; ayrıntı `aria-expanded`
 * düğmeyle açılır. İçerik DOM'da kalır (`hidden`): `aria-controls` hedefi her zaman vardır.
 */
function Ayrinti({ baslangictaAcik = false, testId, children }: { baslangictaAcik?: boolean; testId: string; children: ReactNode }) {
  const [acik, setAcik] = useState(baslangictaAcik);
  const id = useId();
  return (
    <>
      <button
        type="button"
        className="dugme dugme-hayalet dugme-kucuk kalite-ayrinti-dugmesi"
        aria-expanded={acik}
        aria-controls={id}
        onClick={() => setAcik((x) => !x)}
      >
        {acik ? "Ayrıntıları gizle" : "Ayrıntıları göster"}
      </button>
      <div id={id} hidden={!acik} data-testid={testId} className="kalite-ayrinti">
        {children}
      </div>
    </>
  );
}

/**
 * "Review bulguları" paneli (011 F2, P8): skor x/12, 12 madde (karar + bulgu + eksik case / soru),
 * eksik case önerileri, birleştir/kaldır önerileri, bayat uyarısı ve "Yeniden çalıştır".
 * Review tavsiye niteliğindedir: onayı ve yayını engellemez. Panel özet satırına (skor + tek satır)
 * daralmış başlar; maddeler "Ayrıntıları göster" ile açılır (UX-3). İşlem hatası panel içinde.
 */
export function ReviewPaneli({
  gorunum,
  yukleniyor,
  hata,
  hataKaynagi,
  yenile,
  calistir,
  calisiyor,
  islemHata,
  baslangictaAcik,
}: {
  gorunum: CaseReviewGorunumu | null | undefined;
  yukleniyor?: boolean;
  hata?: string | null;
  hataKaynagi?: unknown;
  yenile?: () => void;
  calistir: () => void;
  calisiyor?: boolean;
  /** "Yeniden çalıştır" isteğinin hatası (panel içinde gösterilir). */
  islemHata?: string | null;
  baslangictaAcik?: boolean;
}) {
  const baslik = "Review bulguları";
  if (yukleniyor && gorunum === undefined)
    return (
      <Kart baslik={baslik}>
        <Yukleniyor />
      </Kart>
    );
  if (hata && !gorunum)
    return (
      <Kart baslik={baslik}>
        <HataKutusu hata={hata} kaynak={hataKaynagi} yenile={yenile} />
      </Kart>
    );
  if (!gorunum) return null;
  const r = gorunum.review;
  const ic = r?.icerik ?? {};
  const harita = ic.case_haritasi;
  const dugme = (
    <IslemDugmesi
      izin="case.generate"
      tur="ikincil"
      kucuk
      calisiyor={calisiyor || gorunum.calisiyor}
      disabled={!gorunum.yeniden_calistirilabilir}
      title={gorunum.yeniden_calistirilabilir ? undefined : "Review yalnız \"Case review aşamasında\" olan, v3 case'i bulunan gereksinimde çalışır"}
      onClick={calistir}
    >
      {r ? "Yeniden çalıştır" : "Review çalıştır"}
    </IslemDugmesi>
  );
  return (
    <Kart
      baslik={baslik}
      eylemler={
        <>
          {r?.mode && r.mode !== "live" && <ReplayRozeti mode={r.mode} />}
          {dugme}
        </>
      }
      id="review-bulgulari"
    >
      {islemHata && <HataKutusu hata={hataMetniniAyikla(islemHata)} kayitDisi />}
      {!r ? (
        <BosDurum baslik="Henüz review yok.">Review case üretiminden sonra otomatik çalışır (tavsiye niteliğinde).</BosDurum>
      ) : r.durum === "bekliyor" ? (
        <p data-testid="review-durum">
          <span className="donen donen-kucuk" aria-hidden="true" /> Review çalışıyor…
        </p>
      ) : r.durum === "hata" ? (
        <Uyari ton="hata" baslik="Review çalışmadı, yeniden deneyin">
          <span data-testid="review-hata">{hataMetniniAyikla(r.hata)}</span> Review tavsiye niteliğindedir; case kararlarını ve yayını etkilemez.
        </Uyari>
      ) : (
        <>
          <p className="kalite-skor kalite-ozet-satiri" data-testid="review-skor">
            <strong>{r.skor ?? "—"}/12</strong> madde uygun
            {gorunum.bayat && (
              <>
                {" "}
                <Cip ton="uyari">bayat — set değişti</Cip>
              </>
            )}
            {ic.summary && <span className="soluk"> · {ic.summary}</span>}
          </p>
          <Ayrinti baslangictaAcik={baslangictaAcik} testId="review-ayrinti">
            {gorunum.bayat && (
              <Uyari baslik="Review bayat">Set bu review'dan sonra değişti (case eklendi, düzeltildi ya da reddedildi). Güncel set için yeniden çalıştırın.</Uyari>
            )}
            <ol className="kalite-maddeler" data-testid="review-maddeleri">
              {(ic.items ?? []).map((m) => (
                <li key={m.no}>
                  <Cip ton={REVIEW_KARARI[m.verdict]?.ton ?? "notr"}>{REVIEW_KARARI[m.verdict]?.etiket ?? m.verdict}</Cip> <strong>{m.title}</strong>
                  <div className="soluk kucuk">{m.finding}</div>
                  {m.missing_case && <div className="kucuk">Eksik / düzeltme: {m.missing_case}</div>}
                  {m.question && (
                    <div className="kucuk">
                      Soru{m.owner ? ` (${m.owner})` : ""}: {m.question}
                    </div>
                  )}
                </li>
              ))}
            </ol>
            {(ic.missing_cases?.length ?? 0) > 0 && (
              <Bolum baslik="Eksik case önerileri">
                <ul data-testid="review-eksik">
                  {ic.missing_cases!.map((m, i) => (
                    <li key={i}>
                      <Cip ton="bilgi">{m.technique}</Cip> {m.ac_ref && <Cip>{m.ac_ref}</Cip>} {m.description}
                    </li>
                  ))}
                </ul>
              </Bolum>
            )}
            {(ic.remove_or_merge?.length ?? 0) > 0 && (
              <Bolum baslik="Birleştir / kaldır önerileri">
                <ul data-testid="review-birlestir">
                  {ic.remove_or_merge!.map((m, i) => (
                    <li key={i}>
                      <Cip ton="uyari">{m.action === "merge" ? "Birleştir" : "Kaldır"}</Cip>{" "}
                      {m.case_refs.map((n, j) => (
                        <span key={n}>
                          {j > 0 && ", "}
                          <CaseRef no={n} harita={harita} />
                        </span>
                      ))}{" "}
                      — {m.reason}
                    </li>
                  ))}
                </ul>
              </Bolum>
            )}
            <p className="soluk kucuk">
              Review tavsiye niteliğindedir (onayı ve yayını engellemez) ve Agent Probe denetimine girdi olur. Set: <code>{kisaHash(r.set_hash)}</code>
            </p>
          </Ayrinti>
        </>
      )}
    </Kart>
  );
}

/** Karar rozeti (yayın sayfası da kullanır). */
export function DenetimRozeti({ karar }: { karar: DenetimKarari | null | undefined }) {
  if (!karar) return <Cip>karar yok</Cip>;
  const k = DENETIM_KARARI[karar];
  return (
    <span data-testid="denetim-karari">
      <Cip ton={k?.ton ?? "notr"}>{k?.etiket ?? karar}</Cip>
    </span>
  );
}

/**
 * "Agent Probe'a gönder" birincil mi (UX-7, sayfada tek birincil eylem): karar bekleyen case yok,
 * gönderilebilir, kapı açık ve setin güncel hâli için KABUL yok. Case review başlığındaki yayın
 * düğmesi bu false iken birincil olur.
 */
export function gonderBirincilMi(gorunum: CaseDenetimGorunumu | null | undefined, bekleyen: number): boolean {
  if (!gorunum || bekleyen > 0 || gorunum.gonder_engeli || gorunum.calisiyor || !gorunum.kapi_acik || !gorunum.set_hash) return false;
  return gorunum.guncel_karar?.karar !== "KABUL";
}

/**
 * "Agent Probe denetimi" paneli (011 F5, P9): karar rozeti, karar sonrası yönlendirme, gerekçe,
 * case'e bağlı bulgular, eksik senaryolar, kodun deterministik sertleştirmesi, bayat/güncel ve
 * "Agent Probe'a gönder" (kapalıysa nedeni). Karar bekleyen case varken düğme ikincildir ve sayfa
 * içi onay ister (UX-7). Denetim hatası tek yerde, ham sınıf adı ayıklanmış ve hata tonunda.
 * Yayın için setin güncel hâline ait KABUL gerekir (K3).
 */
export function DenetimPaneli({
  gorunum,
  yukleniyor,
  hata,
  hataKaynagi,
  yenile,
  gonder,
  gonderiliyor,
  islemHata,
  bekleyen = 0,
  toplam,
  yayinYolu,
  baslangictaAcik,
}: {
  gorunum: CaseDenetimGorunumu | null | undefined;
  yukleniyor?: boolean;
  hata?: string | null;
  hataKaynagi?: unknown;
  yenile?: () => void;
  gonder: () => void;
  gonderiliyor?: boolean;
  /** "Agent Probe'a gönder" isteğinin hatası (panel içinde gösterilir). */
  islemHata?: string | null;
  /** Karar bekleyen (taslak) case sayısı: > 0 ise düğme ikincil + sayfa içi onay. */
  bekleyen?: number;
  /** Setteki case sayısı (onay metni için). */
  toplam?: number;
  /** KABUL sonrası "Yayın sayfasına geç" bağlantısı. */
  yayinYolu?: string;
  baslangictaAcik?: boolean;
}) {
  const baslik = "Agent Probe denetimi";
  const [onaySoruluyor, setOnaySoruluyor] = useState(false);
  const dugmeId = useId();
  if (yukleniyor && gorunum === undefined)
    return (
      <Kart baslik={baslik}>
        <Yukleniyor />
      </Kart>
    );
  if (hata && !gorunum)
    return (
      <Kart baslik={baslik}>
        <HataKutusu hata={hata} kaynak={hataKaynagi} yenile={yenile} />
      </Kart>
    );
  if (!gorunum) return null;
  const d = gorunum.guncel_karar ?? gorunum.denetim;
  const ic = d?.icerik ?? {};
  const harita = ic.case_haritasi;
  const birincil = gonderBirincilMi(gorunum, bekleyen);
  const odagiGeriVer = () => requestAnimationFrame(() => document.getElementById(dugmeId)?.focus());
  const dugme = (
    <IslemDugmesi
      id={dugmeId}
      izin="case.approve"
      tur={birincil ? "birincil" : "ikincil"}
      kucuk
      calisiyor={gonderiliyor || gorunum.calisiyor}
      disabled={!!gorunum.gonder_engeli || onaySoruluyor}
      title={gorunum.gonder_engeli ?? undefined}
      aria-expanded={bekleyen > 0 ? onaySoruluyor : undefined}
      onClick={() => (bekleyen > 0 ? setOnaySoruluyor(true) : gonder())}
    >
      Agent Probe'a gönder
    </IslemDugmesi>
  );
  const yon = d && d.durum !== "hata" ? denetimYonlendirmesi(d) : null;
  return (
    <Kart baslik={baslik} eylemler={dugme} id="denetim">
      {!gorunum.kapi_acik && (
        <Uyari ton="bilgi" baslik="Denetim kapısı kapalı">
          <span data-testid="denetim-kapi-kapali">{KAPI_KAPALI_METNI}</span>
        </Uyari>
      )}
      {onaySoruluyor && (
        <SayfaIciOnay
          baslik="Karar bekleyen case'ler var"
          onayMetni="Yine de gönder"
          testId="denetim-gonder-onayi"
          onayla={() => {
            setOnaySoruluyor(false);
            gonder();
            odagiGeriVer();
          }}
          vazgec={() => {
            setOnaySoruluyor(false);
            odagiGeriVer();
          }}
        >
          <p>
            {toplam !== undefined ? `${toplam} case'ten ${bekleyen} tanesi` : `${bekleyen} case`} hâlâ karar bekliyor. Denetim yalnız bugünkü
            seti değerlendirir; case'ler değişirse karar bayatlar.
          </p>
        </SayfaIciOnay>
      )}
      {islemHata && <HataKutusu hata={hataMetniniAyikla(islemHata)} kayitDisi />}
      {gorunum.calisiyor ? (
        <p data-testid="denetim-durum">
          <span className="donen donen-kucuk" aria-hidden="true" /> Agent Probe denetliyor…
        </p>
      ) : !d ? (
        <BosDurum baslik="Henüz denetim yok.">
          Kararlarınızı verdikten sonra seti Agent Probe'a gönderin. Yayın için setin güncel hâline ait KABUL gerekir.
        </BosDurum>
      ) : d.durum === "hata" ? (
        <Uyari ton="hata" baslik="Agent Probe denetimi yapılamadı">
          <span data-testid="denetim-hata">{hataMetniniAyikla(d.hata)}</span> Karar yok; yayın kapısı kapalı kalır. Seti yeniden Agent Probe'a
          gönderin.
        </Uyari>
      ) : (
        <>
          <p className="kalite-skor kalite-ozet-satiri">
            <DenetimRozeti karar={d.karar} />{" "}
            {d.guncel ? (
              <Cip ton="basari">güncel set</Cip>
            ) : (
              <span data-testid="denetim-bayat">
                <Cip ton="uyari">bayat — set değişti</Cip>
              </span>
            )}{" "}
            {d.talep_no && <span className="soluk kucuk">Talep {d.talep_no}</span>}
            {ic.mode && ic.mode !== "live" && (
              <>
                {" "}
                <ReplayRozeti mode={ic.mode as "replay"} />
              </>
            )}
          </p>
          {yon && (
            <p className={`kalite-yonlendirme kalite-yonlendirme-${yon.tur}`} data-testid="denetim-yonlendirme">
              <strong>Sonraki adım:</strong> {yon.metin}
              {yon.tur === "yayin" && (
                <>
                  {" "}
                  {yayinYolu ? <Link to={yayinYolu}>Yayın sayfasına geç</Link> : "Yayın sayfasına geçin."}
                </>
              )}
            </p>
          )}
          <Ayrinti baslangictaAcik={baslangictaAcik} testId="denetim-ayrinti">
            {ic.decision_rationale && <p data-testid="denetim-gerekce">{ic.decision_rationale}</p>}
            {ic.sertlestirildi && (
              <Uyari baslik="Karar kodda sertleştirildi">
                Model kararı {d.model_karari}; deterministik kurallar kararı {d.karar} yaptı (model kararını sertleştirebilir, yumuşatamaz).
              </Uyari>
            )}
            {(ic.deterministik_bulgular?.length ?? 0) > 0 && (
              <Bolum baslik="Deterministik kontroller">
                <ul data-testid="denetim-deterministik">
                  {ic.deterministik_bulgular!.map((b, i) => (
                    <li key={i}>
                      <Cip ton={DENETIM_KARARI[b.alt_sinir]?.ton ?? "uyari"}>en az {DENETIM_KARARI[b.alt_sinir]?.etiket ?? b.alt_sinir}</Cip>{" "}
                      <CaseRef no={b.case_ref} harita={harita} /> — {b.aciklama}
                    </li>
                  ))}
                </ul>
              </Bolum>
            )}
            {(ic.findings?.length ?? 0) > 0 && (
              <Bolum baslik="Bulgular">
                <ul className="kalite-maddeler" data-testid="denetim-bulgulari">
                  {ic.findings!.map((f) => (
                    <li key={f.finding_id}>
                      <Cip ton={RISK_TONU[f.risk] ?? "notr"}>{f.risk}</Cip> <strong>{f.finding_id}</strong> · <CaseRef no={f.case_ref} harita={harita} /> ·{" "}
                      <span className="soluk">
                        {f.control_no}. {KONTROL[f.control_no] ?? "kontrol"}
                      </span>
                      <div>{f.issue}</div>
                      <div className="soluk kucuk">{f.rationale}</div>
                      <div className="kucuk">Öneri: {f.suggested_fix}</div>
                    </li>
                  ))}
                </ul>
              </Bolum>
            )}
            {(ic.missing_scenarios?.length ?? 0) > 0 && (
              <Bolum baslik="Eksik senaryolar">
                <ul>
                  {ic.missing_scenarios!.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </Bolum>
            )}
            {gorunum.yayin_engeli && gorunum.kapi_acik && (
              <Uyari baslik="Yayın kapalı">
                <span data-testid="denetim-yayin-engeli">{hataMetniniAyikla(yayinlanamaz(gorunum.yayin_engeli))}</span>
              </Uyari>
            )}
          </Ayrinti>
        </>
      )}
    </Kart>
  );
}

/** Yayın sayfası özeti: kararın kısa hâli + engel + case review'a bağlantı. */
export function DenetimOzeti({ gorunum, reviewYolu }: { gorunum: CaseDenetimGorunumu | null | undefined; reviewYolu: string }) {
  if (!gorunum || !gorunum.set_hash) return null;
  const d = gorunum.guncel_karar;
  return (
    <Kart baslik="Agent Probe denetimi" id="yayin-denetim">
      <p data-testid="yayin-denetim-ozeti">
        {gorunum.calisiyor ? (
          "Agent Probe denetliyor…"
        ) : d ? (
          <>
            <DenetimRozeti karar={d.karar} /> {d.talep_no && <span className="soluk kucuk">Talep {d.talep_no}</span>}
          </>
        ) : (
          <Cip ton="uyari">güncel set için karar yok</Cip>
        )}{" "}
        {!gorunum.kapi_acik && <Cip title={KAPI_KAPALI_METNI}>denetim kapısı kapalı</Cip>}
      </p>
      {!gorunum.kapi_acik && <p className="soluk kucuk">{KAPI_KAPALI_METNI}</p>}
      {gorunum.yayin_engeli && gorunum.kapi_acik && (
        <p className="kucuk" data-testid="yayin-denetim-engeli">
          {hataMetniniAyikla(yayinlanamaz(gorunum.yayin_engeli))}
        </p>
      )}
      <p className="kucuk">
        <Link to={`${reviewYolu}#denetim`}>Denetim ayrıntısı ve "Agent Probe'a gönder" → Case review</Link>
      </p>
    </Kart>
  );
}

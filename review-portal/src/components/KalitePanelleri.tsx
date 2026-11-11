import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router-dom";
import type { CaseDenetimGorunumu, CaseHaritasi, CaseReviewGorunumu, DenetimKarari, ReviewKarari } from "../api/types";
import type { Ton } from "../lib/etiketler";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, Uyari, Yukleniyor } from "./ui";

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
 * "Review bulguları" paneli (011 F2, P8): skor x/12, 12 madde (karar + bulgu + eksik case / soru),
 * eksik case önerileri, birleştir/kaldır önerileri, bayat uyarısı ve "Yeniden çalıştır".
 * Review tavsiye niteliğindedir: onayı ve yayını engellemez.
 */
export function ReviewPaneli({
  gorunum,
  yukleniyor,
  hata,
  hataKaynagi,
  yenile,
  calistir,
  calisiyor,
}: {
  gorunum: CaseReviewGorunumu | null | undefined;
  yukleniyor?: boolean;
  hata?: string | null;
  hataKaynagi?: unknown;
  yenile?: () => void;
  calistir: () => void;
  calisiyor?: boolean;
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
      roller={["analyst"]}
      tur="ikincil"
      kucuk
      calisiyor={calisiyor || gorunum.calisiyor}
      disabled={!gorunum.yeniden_calistirilabilir}
      title={gorunum.yeniden_calistirilabilir ? undefined : "Review yalnız case'leri hazır, v3 case'i olan gereksinimde çalışır"}
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
      {!r ? (
        <BosDurum baslik="Henüz review yok.">Review case üretiminden sonra otomatik çalışır (tavsiye niteliğinde).</BosDurum>
      ) : r.durum === "bekliyor" ? (
        <p data-testid="review-durum">
          <span className="donen donen-kucuk" aria-hidden="true" /> Review çalışıyor…
        </p>
      ) : r.durum === "hata" ? (
        <Uyari baslik="Review çalışmadı, yeniden deneyin">
          <span data-testid="review-hata">{r.hata}</span> Review tavsiye niteliğindedir; case kararlarını ve yayını etkilemez.
        </Uyari>
      ) : (
        <>
          {gorunum.bayat && (
            <Uyari baslik="Review bayat">Set bu review'dan sonra değişti (case eklendi, düzeltildi ya da reddedildi). Güncel set için yeniden çalıştırın.</Uyari>
          )}
          <p className="kalite-skor" data-testid="review-skor">
            <strong>{r.skor ?? "—"}/12</strong> madde uygun
            {ic.summary && <span className="soluk"> · {ic.summary}</span>}
          </p>
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
            Review tavsiye niteliğindedir (onayı ve yayını engellemez) ve denetime girdi olur. Set: <code>{kisaHash(r.set_hash)}</code>
          </p>
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
 * "Denetim" paneli (011 F5, P9; Agent Probe): karar rozeti, gerekçe, case'e bağlı bulgular, eksik
 * senaryolar, kodun deterministik sertleştirmesi, bayat/güncel ve "Denetime gönder" (kapalıysa
 * nedeni). Yayın için setin güncel hâline ait KABUL gerekir (K3).
 */
export function DenetimPaneli({
  gorunum,
  yukleniyor,
  hata,
  hataKaynagi,
  yenile,
  gonder,
  gonderiliyor,
}: {
  gorunum: CaseDenetimGorunumu | null | undefined;
  yukleniyor?: boolean;
  hata?: string | null;
  hataKaynagi?: unknown;
  yenile?: () => void;
  gonder: () => void;
  gonderiliyor?: boolean;
}) {
  const baslik = "Denetim (Agent Probe)";
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
  const dugme = (
    <IslemDugmesi
      roller={["analyst"]}
      kucuk
      calisiyor={gonderiliyor || gorunum.calisiyor}
      disabled={!!gorunum.gonder_engeli}
      title={gorunum.gonder_engeli ?? undefined}
      onClick={gonder}
    >
      Denetime gönder
    </IslemDugmesi>
  );
  return (
    <Kart baslik={baslik} eylemler={dugme} id="denetim">
      {!gorunum.kapi_acik && (
        <Uyari baslik="Denetim kapısı kapalı">TP_DENETIM_KAPISI=off: yayın denetim kararı aranmadan yapılır.</Uyari>
      )}
      {gorunum.calisiyor ? (
        <p data-testid="denetim-durum">
          <span className="donen donen-kucuk" aria-hidden="true" /> Agent Probe denetliyor…
        </p>
      ) : !d ? (
        <BosDurum baslik="Henüz denetim yok.">
          Kararlarınızı verdikten sonra seti denetime gönderin. Yayın için setin güncel hâline ait KABUL gerekir.
        </BosDurum>
      ) : d.durum === "hata" ? (
        <Uyari baslik="Denetim yapılamadı">
          <span data-testid="denetim-hata">{d.hata}</span> Karar yok; yayın kapısı kapalı kalır. Yeniden denetime gönderin.
        </Uyari>
      ) : (
        <>
          <p className="kalite-skor">
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
        </>
      )}
      {gorunum.yayin_engeli && (
        <p className="soluk kucuk" data-testid="denetim-yayin-engeli">
          Yayın: {gorunum.yayin_engeli}
        </p>
      )}
    </Kart>
  );
}

/** Yayın sayfası özeti: kararın kısa hâli + engel + case review'a bağlantı. */
export function DenetimOzeti({ gorunum, reviewYolu }: { gorunum: CaseDenetimGorunumu | null | undefined; reviewYolu: string }) {
  if (!gorunum || !gorunum.set_hash) return null;
  const d = gorunum.guncel_karar;
  return (
    <Kart baslik="Denetim durumu" id="yayin-denetim">
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
        {!gorunum.kapi_acik && <Cip>kapı kapalı (TP_DENETIM_KAPISI=off)</Cip>}
      </p>
      {gorunum.yayin_engeli && gorunum.kapi_acik && <p className="kucuk">{gorunum.yayin_engeli}</p>}
      <p className="kucuk">
        <Link to={`${reviewYolu}#denetim`}>Denetim ayrıntısı ve "Denetime gönder" → Case review</Link>
      </p>
    </Kart>
  );
}

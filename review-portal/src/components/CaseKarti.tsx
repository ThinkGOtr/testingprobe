import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { caseKarariVerilebilir, GECIS_YOK, gecisVar, type CaseKarari } from "../api/sozlesme/durumMakinesi";
import { useOturum } from "../auth";
import type { RetNedeni, TestCase, TestCaseIcerik } from "../api/types";
import { useIslem } from "../hooks";
import { CASE_DURUMU, CASE_TURU, RET_NEDENI, RISK } from "../lib/etiketler";
import { sure, tarih } from "../lib/format";
import { Cip, IslemDugmesi, ReplayRozeti } from "./ui";

type Mod = "goster" | "duzenle" | "reddet";

const KARAR_ADI = { approve: "onay", edit: "düzeltme", reject: "ret" } as const;

// Bu oturumda "görüntülendi" bildirilen case'ler (her case için tek istek).
const goruntulenenler = new Set<string>();

/** Testler için: görüntüleme kayıtlarını sıfırlar. */
export function goruntulenenleriSifirla(): void {
  goruntulenenler.clear();
}

/**
 * Karar bekleyen case analistin ekranına ilk girdiğinde (kartın yarısı görünür olunca) core'a
 * bildirilir; review süresi (`review_sure_ms`) sunucuda bu andan karara kadar ölçülür. Hata
 * sessizce yutulur: ölçüm kararın önüne geçmez (uç yoksa süre ölçülmez, karar yine verilir).
 */
function useGoruntulemeBildir(tc: TestCase, etkin: boolean) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!etkin || tc.goruntulenme || goruntulenenler.has(tc.id)) return;
    const bildir = () => {
      if (goruntulenenler.has(tc.id)) return;
      goruntulenenler.add(tc.id);
      api.caseGoruntulendi(tc.id).catch(() => undefined);
    };
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      bildir();
      return;
    }
    const g = new IntersectionObserver(
      (kayitlar) => {
        if (kayitlar.some((k) => k.isIntersecting)) {
          bildir();
          g.disconnect();
        }
      },
      { threshold: 0.5 },
    );
    g.observe(el);
    return () => g.disconnect();
  }, [tc.id, tc.goruntulenme, etkin]);
  return ref;
}
export function CaseKarti({
  tc,
  guncellendi,
  yenile,
}: {
  tc: TestCase;
  guncellendi: (t: TestCase) => void;
  /** 409 (içerik siz görüntüledikten sonra değişti): case listesini yeniden yükler. */
  yenile?: () => void;
}) {
  const [mod, setMod] = useState<Mod>("goster");
  const islem = useIslem();
  const id = useId();
  const { kullanici } = useOturum();
  // Yalnızca karar verecek rol (analist) ve karar bekleyen case için görüntüleme ölçülür.
  const kartRef = useGoruntulemeBildir(tc, kullanici?.rol === "analyst" && tc.durum === "draft");
  // core test_case: approved | rejected → draft (yeniden aç). Yayınlanmış case son durumdur.
  const yenidenAcilabilir = gecisVar("test_case", tc.durum, "draft");
  const d = CASE_DURUMU[tc.durum];
  const r = RISK[tc.icerik.risk];
  // Son durumlar (core): yayınlanan ve yerini yenisi alan case'e karar verilmez.
  const kilitli = tc.durum === "published" || tc.durum === "superseded";
  // core test_case makinesi: kararlar yalnızca izinli geçişlerde (draft → approved | rejected).
  const verilebilir = (k: CaseKarari) => caseKarariVerilebilir(tc.durum, k);
  const gecisYokNedeni = (k: CaseKarari) => (verilebilir(k) ? undefined : `${GECIS_YOK} (${CASE_DURUMU[tc.durum].etiket})`);
  const kararVerildi = !kilitli && !(["approve", "edit", "reject"] as const).some(verilebilir);
  // Kararlar ekranda görülen içeriğin hash'iyle gönderilir (düzeltmede düzeltme öncesi içerik).
  const bag = { icerik_hash: tc.icerik_hash };

  async function karar(fn: () => Promise<TestCase>) {
    const yeni = await islem.calistir(fn, {
      cakismada: () => {
        setMod("goster");
        yenile?.();
      },
    });
    if (yeni) {
      setMod("goster");
      guncellendi(yeni);
    }
  }

  return (
    <article ref={kartRef} className={`case case-${tc.durum}`} aria-labelledby={`${id}-baslik`}>
      <header className="case-baslik">
        <div className="satir-ogeler">
          <span className="mono soluk">#{tc.sira_no}</span>
          <Cip ton={d.ton}>{d.etiket}</Cip>
          <Cip ton="notr">{CASE_TURU[tc.icerik.type] ?? tc.icerik.type}</Cip>
          {r && <Cip ton={r.ton}>{r.etiket}</Cip>}
          {tc.icerik.acceptance_criteria_refs.map((a) => (
            <span key={a} className="mono ac-ref">
              {a}
            </span>
          ))}
          {tc.kanal === "ide" && <Cip ton="vurgu" title="Claude Code (MCP submit_draft_cases) kanalından geldi">Claude Code</Cip>}
          <ReplayRozeti mode={tc.mode} />
        </div>
        {tc.jira_test_key && <span className="mono">{tc.jira_test_key}</span>}
      </header>

      {mod === "duzenle" ? (
        <CaseDuzenleyici
          ilk={tc.icerik}
          calisiyor={islem.calisiyor}
          hata={islem.hata}
          vazgec={() => setMod("goster")}
          kaydet={(icerik) => karar(() => api.caseKarari(tc.id, { ...bag, karar: "edit", icerik }))}
        />
      ) : (
        <>
          <h3 id={`${id}-baslik`} className="case-ad">
            {tc.icerik.title}
          </h3>
          {tc.icerik.preconditions.length > 0 && (
            <p className="kucuk">
              <strong>Ön koşul:</strong> {tc.icerik.preconditions.join(" · ")}
            </p>
          )}
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`Adımlar: ${tc.icerik.title}`}>
            <table className="tablo tablo-sik tablo-yigin">
              <caption className="gorunmez">Adımlar</caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Adım</th>
                  <th scope="col">Veri</th>
                  <th scope="col">Beklenen</th>
                </tr>
              </thead>
              <tbody>
                {tc.icerik.steps.map((s) => (
                  <tr key={s.id}>
                    <td className="mono adim-no" data-etiket="#">
                      {s.id}
                    </td>
                    <td data-etiket="Adım">{s.action}</td>
                    <td className={`mono${s.data ? "" : " bos-hucre"}`} data-etiket="Veri">
                      {s.data ?? "—"}
                    </td>
                    <td data-etiket="Beklenen">{s.expected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <strong>Beklenen sonuç:</strong> {tc.icerik.expected_result}
          </p>
        </>
      )}

      {mod === "reddet" && (
        <RetFormu
          calisiyor={islem.calisiyor}
          hata={islem.hata}
          vazgec={() => setMod("goster")}
          reddet={(neden) => karar(() => api.caseKarari(tc.id, { ...bag, karar: "reject", ret_nedeni: neden }))}
        />
      )}

      <footer className="case-alt">
        <span className="soluk kucuk">
          {tc.mode === "replay" || tc.mode === "replay_miss" ? "AI: REPLAY — ölçülmedi" : `AI ${sure(tc.ai_sure_ms)}`}
          {tc.review_sure_ms !== null && ` · review ${sure(tc.review_sure_ms)}`}
          {tc.karar_veren && ` · ${tc.karar_veren}, ${tarih(tc.karar_zamani)}`}
          {tc.durum === "draft" && tc.karar && ` · taslağa alındı (önceki karar: ${KARAR_ADI[tc.karar]})`}
          {tc.ret_nedeni && tc.durum === "rejected" && ` · ret: ${RET_NEDENI[tc.ret_nedeni]}`}
          {tc.duzeltme_olcusu !== null && tc.karar === "edit" && ` · düzeltme ölçüsü ${tc.duzeltme_olcusu.toLocaleString("tr-TR")}`}
          {tc.durum === "draft" && tc.goruntulenme && ` · review ${tarih(tc.goruntulenme)} itibarıyla sürüyor`}
        </span>
        {mod === "goster" && !kilitli && (
          <div className="eylemler">
            <IslemDugmesi
              roller={["analyst"]}
              kucuk
              disabled={!verilebilir("approve")}
              title={gecisYokNedeni("approve")}
              calisiyor={islem.calisiyor}
              onClick={() => karar(() => api.caseKarari(tc.id, { ...bag, karar: "approve" }))}
            >
              Onayla
            </IslemDugmesi>
            <IslemDugmesi
              roller={["analyst"]}
              kucuk
              tur="ikincil"
              disabled={!verilebilir("edit")}
              title={gecisYokNedeni("edit")}
              onClick={() => setMod("duzenle")}
            >
              Düzelt
            </IslemDugmesi>
            <IslemDugmesi
              roller={["analyst"]}
              kucuk
              tur="tehlike"
              disabled={!verilebilir("reject")}
              title={gecisYokNedeni("reject")}
              onClick={() => setMod("reddet")}
            >
              Reddet
            </IslemDugmesi>
          </div>
        )}
      </footer>
      {mod === "goster" && kararVerildi && (
        <div className="satir-ogeler">
          <p className="soluk kucuk" data-testid="case-karar-kilit">
            Karar verildi. Karar yalnızca taslaktaki case için verilir; değiştirmek için case'i yeniden açın (yeniden review gerekir).
          </p>
          {yenidenAcilabilir && (
            <IslemDugmesi
              roller={["analyst"]}
              kucuk
              tur="ikincil"
              calisiyor={islem.calisiyor}
              onClick={() => karar(() => api.caseYenidenAc(tc))}
            >
              Yeniden aç
            </IslemDugmesi>
          )}
        </div>
      )}
      {tc.uyarilar && tc.uyarilar.length > 0 && (
        <ul className="duz-liste kucuk hata-metin">
          {tc.uyarilar.map((u) => (
            <li key={u}>{u}</li>
          ))}
        </ul>
      )}
      {mod === "goster" && islem.hata && (
        <p className="alan-hata" role="alert">
          {islem.hata}
        </p>
      )}
    </article>
  );
}

function RetFormu({ reddet, vazgec, calisiyor, hata }: { reddet: (n: RetNedeni) => void; vazgec: () => void; calisiyor: boolean; hata: string | null }) {
  const [neden, setNeden] = useState<RetNedeni | "">("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  return (
    <form
      className="ret-formu"
      onSubmit={(e) => {
        e.preventDefault();
        if (!neden) return setUyari("Ret nedeni seçilmelidir.");
        reddet(neden);
      }}
      noValidate
    >
      <div className="alan">
        <label htmlFor={`${id}-neden`}>Ret nedeni</label>
        <select id={`${id}-neden`} value={neden} onChange={(e) => setNeden(e.target.value as RetNedeni)} aria-required="true">
          <option value="">Seçin…</option>
          {(Object.keys(RET_NEDENI) as RetNedeni[]).map((k) => (
            <option key={k} value={k}>
              {RET_NEDENI[k]}
            </option>
          ))}
        </select>
      </div>
      {(uyari || hata) && (
        <p className="alan-hata" role="alert">
          {uyari ?? hata}
        </p>
      )}
      <div className="eylemler">
        <IslemDugmesi roller={["analyst"]} type="submit" tur="tehlike" kucuk calisiyor={calisiyor}>
          Reddi kaydet
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

function CaseDuzenleyici({
  ilk,
  kaydet,
  vazgec,
  calisiyor,
  hata,
}: {
  ilk: TestCaseIcerik;
  kaydet: (i: TestCaseIcerik) => void;
  vazgec: () => void;
  calisiyor: boolean;
  hata: string | null;
}) {
  const [icerik, setIcerik] = useState<TestCaseIcerik>(() => JSON.parse(JSON.stringify(ilk)) as TestCaseIcerik);
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();

  const adimGuncelle = (i: number, alan: "action" | "data" | "expected", deger: string) =>
    setIcerik((c) => ({
      ...c,
      steps: c.steps.map((s, j) => (j === i ? { ...s, [alan]: alan === "data" && deger === "" ? null : deger } : s)),
    }));

  function gonder(e: FormEvent) {
    e.preventDefault();
    if (!icerik.title.trim()) return setUyari("Başlık boş olamaz.");
    if (icerik.title.length > 120) return setUyari("Başlık en fazla 120 karakter.");
    if (icerik.steps.length === 0 || icerik.steps.some((s) => !s.action.trim() || !s.expected.trim())) {
      return setUyari("Her adımın eylemi ve beklenen sonucu dolu olmalı.");
    }
    if (!icerik.expected_result.trim()) return setUyari("Beklenen sonuç boş olamaz.");
    setUyari(null);
    kaydet({ ...icerik, steps: icerik.steps.map((s, i) => ({ ...s, id: `S${i + 1}` })) });
  }

  return (
    <form className="case-duzenle" onSubmit={gonder} noValidate>
      <div className="alan">
        <label htmlFor={`${id}-baslik`}>Başlık</label>
        <input id={`${id}-baslik`} value={icerik.title} maxLength={120} onChange={(e) => setIcerik({ ...icerik, title: e.target.value })} />
      </div>
      <fieldset className="alan">
        <legend>Adımlar</legend>
        {icerik.steps.map((s, i) => (
          <div key={i} className="adim-duzenle">
            <span className="mono">S{i + 1}</span>
            <label className="gorunmez" htmlFor={`${id}-a${i}`}>{`S${i + 1} eylem`}</label>
            <input id={`${id}-a${i}`} placeholder="Eylem" value={s.action} onChange={(e) => adimGuncelle(i, "action", e.target.value)} />
            <label className="gorunmez" htmlFor={`${id}-d${i}`}>{`S${i + 1} veri`}</label>
            <input id={`${id}-d${i}`} placeholder="Veri" value={s.data ?? ""} onChange={(e) => adimGuncelle(i, "data", e.target.value)} />
            <label className="gorunmez" htmlFor={`${id}-e${i}`}>{`S${i + 1} beklenen`}</label>
            <input id={`${id}-e${i}`} placeholder="Beklenen" value={s.expected} onChange={(e) => adimGuncelle(i, "expected", e.target.value)} />
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              aria-label={`S${i + 1} adımını sil`}
              onClick={() => setIcerik((c) => ({ ...c, steps: c.steps.filter((_, j) => j !== i) }))}
            >
              Sil
            </button>
          </div>
        ))}
        <button
          type="button"
          className="dugme dugme-ikincil dugme-kucuk"
          onClick={() => setIcerik((c) => ({ ...c, steps: [...c.steps, { id: `S${c.steps.length + 1}`, action: "", data: null, expected: "" }] }))}
        >
          Adım ekle
        </button>
      </fieldset>
      <div className="alan">
        <label htmlFor={`${id}-beklenen`}>Beklenen sonuç</label>
        <textarea id={`${id}-beklenen`} rows={2} value={icerik.expected_result} onChange={(e) => setIcerik({ ...icerik, expected_result: e.target.value })} />
      </div>
      {(uyari || hata) && (
        <p className="alan-hata" role="alert">
          {uyari ?? hata}
        </p>
      )}
      <div className="eylemler">
        <IslemDugmesi roller={["analyst"]} type="submit" kucuk calisiyor={calisiyor}>
          Düzeltip onayla
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

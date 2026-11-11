import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type TextareaHTMLAttributes } from "react";
import { api } from "../api/client";
import { caseKarariVerilebilir, GECIS_YOK, type CaseKarari } from "../api/sozlesme/durumMakinesi";
import { useCaseKisitli, useIzin, useKisiAdi } from "../auth";
import type { RetNedeni, TestCase, TestCaseIcerik } from "../api/types";
import { useIslem } from "../hooks";
import { CASE_DURUMU, CASE_TURU, RET_NEDENI, RISK } from "../lib/etiketler";
import { sure, tarih } from "../lib/format";
import { FarkGorunumu } from "./FarkGorunumu";
import { AlanHatasi, Cip, IslemDugmesi, ReplayRozeti } from "./ui";

type Mod = "goster" | "duzenle" | "reddet" | "geriGonder";

const KARAR_ADI: Record<string, string> = {
  accept: "kabul",
  edit: "düzelterek kabul",
  reject: "ret",
  approve: "onay",
  send_back: "geri gönderme",
  reopen: "taslağa alma",
};

/** Karar sonrası durum notu (ANALIZ 012 §5). */
const DURUM_NOTU: Partial<Record<TestCase["durum"], string>> = {
  ready: "Testçi kabul etti; Analist son onayı bekleniyor. Değiştirmek için taslağa alın.",
  approved: "Analist onayladı. Değiştirmek için taslağa alın; onay düşer ve yeniden karar gerekir.",
  rejected: "Reddedildi. Yeniden değerlendirmek için taslağa alın.",
};

// Bu oturumda "görüntülendi" bildirilen case'ler (her case için tek istek).
const goruntulenenler = new Set<string>();

/** Testler için: görüntüleme kayıtlarını sıfırlar. */
export function goruntulenenleriSifirla(): void {
  goruntulenenler.clear();
}

/**
 * Karar bekleyen case Testçinin ekranına ilk girdiğinde (kartın yarısı görünür olunca) core'a
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
  const testci = useIzin("case.decide");
  // Developer: yalnız onaylı/yayınlanmış case, karar geçmişi ve eylem yok (core süzgeciyle aynı).
  const kisitli = useCaseKisitli();
  const kisiAdi = useKisiAdi();
  // Yalnızca karar verecek rol (Testçi) ve karar bekleyen case için görüntüleme ölçülür.
  const kartRef = useGoruntulemeBildir(tc, testci && tc.durum === "draft");
  // core test_case: ready | approved | rejected → draft ("Taslağa al"). Yayınlanmış case son durumdur.
  const yenidenAcilabilir = caseKarariVerilebilir(tc.durum, "reopen");
  const d = CASE_DURUMU[tc.durum];
  const r = RISK[tc.icerik.risk];
  // Son durumlar (core): yayınlanan ve yerini yenisi alan case'e karar verilmez.
  const kilitli = tc.durum === "published" || tc.durum === "superseded";
  // core test_case makinesi: Testçi kararı draft'tan (→ ready | rejected), Analist kararı ready'den.
  const verilebilir = (k: CaseKarari) => caseKarariVerilebilir(tc.durum, k);
  const gecisYokNedeni = (k: CaseKarari) => (verilebilir(k) ? undefined : `${GECIS_YOK} (${CASE_DURUMU[tc.durum].etiket})`);
  const testciKarari = !kilitli && tc.durum === "draft";
  const analistKarari = !kilitli && tc.durum === "ready";
  const kararVerildi = !kilitli && !testciKarari;
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
          {tc.kanal === "ide" && <Cip ton="notr" title="Claude Code (MCP submit_draft_cases) kanalından geldi">Claude Code</Cip>}
          <ReplayRozeti mode={tc.mode} />
        </div>
        {tc.jira_test_key && <span className="mono">{tc.jira_test_key}</span>}
      </header>

      {mod === "duzenle" ? (
        <CaseDuzenleyici
          ilk={tc.icerik}
          calisiyor={islem.calisiyor}
          hata={islem.hata}
          hataKaynagi={islem.hataNesnesi}
          vazgec={() => setMod("goster")}
          kaydet={(icerik, beklenenAnlamDegisti) =>
            karar(() =>
              api.caseKarari(tc.id, {
                ...bag,
                karar: "edit",
                icerik,
                ...(beklenenAnlamDegisti !== undefined ? { beklenen_anlam_degisti: beklenenAnlamDegisti } : {}),
              }),
            )
          }
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

      {mod === "geriGonder" && (
        <GeriGonderFormu
          calisiyor={islem.calisiyor}
          hata={islem.hata}
          hataKaynagi={islem.hataNesnesi}
          vazgec={() => setMod("goster")}
          gonder={(gerekce) => karar(() => api.caseKarari(tc.id, { ...bag, karar: "send_back", gerekce }))}
        />
      )}

      {mod === "reddet" && (
        <RetFormu
          calisiyor={islem.calisiyor}
          hata={islem.hata}
          hataKaynagi={islem.hataNesnesi}
          vazgec={() => setMod("goster")}
          reddet={(neden) => karar(() => api.caseKarari(tc.id, { ...bag, karar: "reject", ret_nedeni: neden }))}
        />
      )}

      <footer className="case-alt">
        <span className="soluk kucuk">
          {tc.mode === "replay" || tc.mode === "replay_miss" ? "AI: REPLAY — ölçülmedi" : `AI ${sure(tc.ai_sure_ms)}`}
          {!kisitli && (
            <>
              {tc.review_sure_ms !== null && ` · review ${sure(tc.review_sure_ms)}`}
              {tc.karar_veren && ` · ${kisiAdi(tc.karar_veren)}, ${tarih(tc.karar_zamani)}`}
              {tc.onaylayan && ` · onay: ${kisiAdi(tc.onaylayan)}${tc.onay_zamani ? `, ${tarih(tc.onay_zamani)}` : ""}`}
              {tc.durum === "draft" && tc.karar && tc.karar !== "send_back" && ` · taslağa alındı (önceki karar: ${KARAR_ADI[tc.karar] ?? tc.karar})`}
              {tc.durum === "draft" && tc.karar === "send_back" && (
                <span data-testid="case-geri-gonderildi">{` · Analist geri gönderdi${tc.gerekce ? `: ${tc.gerekce}` : ""}`}</span>
              )}
              {tc.ret_nedeni && tc.durum === "rejected" && ` · ret: ${RET_NEDENI[tc.ret_nedeni]}`}
              {tc.duzeltme_olcusu !== null && (tc.testci_karari ?? tc.karar) === "edit" && ` · düzeltme ölçüsü ${tc.duzeltme_olcusu.toLocaleString("tr-TR")}`}
              {(tc.testci_karari ?? tc.karar) === "edit" && <KucukDuzeltme tc={tc} />}
              {tc.durum === "draft" && tc.goruntulenme && ` · review ${tarih(tc.goruntulenme)} itibarıyla sürüyor`}
            </>
          )}
        </span>
        {/* Testçi kararı yalnız taslakta; Analist son onayı yalnız onaya hazır case'te (ANALIZ 012 §5). */}
        {mod === "goster" && !kisitli && testciKarari && (
          <div className="eylemler">
            <IslemDugmesi
              izin="case.decide"
              kucuk
              disabled={!verilebilir("accept")}
              title={gecisYokNedeni("accept")}
              calisiyor={islem.calisiyor}
              onClick={() => karar(() => api.caseKarari(tc.id, { ...bag, karar: "accept" }))}
            >
              Kabul et
            </IslemDugmesi>
            <IslemDugmesi
              izin="case.decide"
              kucuk
              tur="ikincil"
              disabled={!verilebilir("edit")}
              title={gecisYokNedeni("edit")}
              onClick={() => setMod("duzenle")}
            >
              Düzelterek kabul
            </IslemDugmesi>
            <IslemDugmesi
              izin="case.decide"
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
        {mod === "goster" && !kisitli && analistKarari && (
          <div className="eylemler">
            <IslemDugmesi
              izin="case.approve"
              kucuk
              disabled={!verilebilir("approve")}
              title={gecisYokNedeni("approve")}
              calisiyor={islem.calisiyor}
              onClick={() => karar(() => api.caseKarari(tc.id, { ...bag, karar: "approve" }))}
            >
              Onayla
            </IslemDugmesi>
            <IslemDugmesi
              izin="case.approve"
              kucuk
              tur="ikincil"
              disabled={!verilebilir("send_back")}
              title={gecisYokNedeni("send_back")}
              onClick={() => setMod("geriGonder")}
            >
              Geri gönder
            </IslemDugmesi>
          </div>
        )}
      </footer>
      {mod === "goster" && !kisitli && kararVerildi && (
        <div className="satir-ogeler">
          <p className="soluk kucuk" data-testid="case-karar-kilit">
            {DURUM_NOTU[tc.durum] ?? "Karar verildi."}
          </p>
          {yenidenAcilabilir && (
            <IslemDugmesi izin="case.decide" kucuk tur="ikincil" calisiyor={islem.calisiyor} onClick={() => karar(() => api.caseYenidenAc(tc))}>
              Taslağa al
            </IslemDugmesi>
          )}
        </div>
      )}
      {!kisitli && tc.fark && tc.fark.length > 0 && (
        <details className="case-fark" data-testid="case-fark">
          <summary className="kucuk">AI özgünü → insan düzeltmesi ({tc.fark.length} alan)</summary>
          {tc.duzeltme_nedeni && <p className="soluk kucuk">{tc.duzeltme_nedeni}</p>}
          {tc.fark.map((f, i) => (
            <div key={`${f.alan}-${i}`} className="case-fark-alan">
              <strong className="kucuk">{f.etiket}</strong>
              <FarkGorunumu eski={f.once} yeni={f.sonra} />
            </div>
          ))}
        </details>
      )}
      {tc.uyarilar && tc.uyarilar.length > 0 && (
        <ul className="duz-liste kucuk hata-metin">
          {tc.uyarilar.map((u) => (
            <li key={u}>{u}</li>
          ))}
        </ul>
      )}
      {mod === "goster" && islem.hata && (
        <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>
      )}
    </article>
  );
}

/** §12 eşiği: düzeltme ölçüsü bu değerin altındaysa (ve beklenen sonuç anlamca değişmediyse) küçük düzeltme. */
export const KUCUK_DUZELTME_ESIGI = 0.15;

/**
 * Düzeltmenin "küçük düzeltme" (kabul oranına girer) sayılıp sayılmadığı ve nedeni. Core bayrağı
 * (`kucuk_duzeltme`) ve gerekçesi (`duzeltme_nedeni`) varsa onlar; yoksa ölçüden türetilir.
 */
export function kucukDuzeltmeDurumu(tc: Pick<TestCase, "kucuk_duzeltme" | "duzeltme_olcusu" | "duzeltme_nedeni">): {
  kucuk: boolean;
  neden: string;
} {
  const olcu = tc.duzeltme_olcusu;
  const olcuAsti = olcu !== null && olcu > KUCUK_DUZELTME_ESIGI;
  const kucuk = tc.kucuk_duzeltme ?? (olcu !== null && !olcuAsti);
  const esik = KUCUK_DUZELTME_ESIGI.toLocaleString("tr-TR");
  let neden: string;
  if (kucuk) neden = `ölçü ≤ ${esik} ve beklenen sonuç anlamca değişmedi`;
  else if (olcuAsti) neden = `ölçü > ${esik}`;
  else if (olcu === null) neden = "düzeltme ölçüsü yok";
  else neden = "beklenen sonuç anlamca değişti";
  return { kucuk, neden };
}

function KucukDuzeltme({ tc }: { tc: TestCase }) {
  const { kucuk, neden } = kucukDuzeltmeDurumu(tc);
  return (
    <span data-testid="kucuk-duzeltme" title={tc.duzeltme_nedeni ?? undefined}>
      {` · küçük düzeltme ${kucuk ? "✓" : "✗"} (${kucuk ? "kabul oranına girer" : `neden: ${neden}`})`}
    </span>
  );
}

function RetFormu({
  reddet,
  vazgec,
  calisiyor,
  hata,
  hataKaynagi,
}: {
  reddet: (n: RetNedeni) => void;
  vazgec: () => void;
  calisiyor: boolean;
  hata: string | null;
  /** useIslem `hataNesnesi`: 409 / karar hatasının yanında "Asistana sor". */
  hataKaynagi?: unknown;
}) {
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
        <AlanHatasi asistan={uyari ? null : { hata, kaynak: hataKaynagi }}>{uyari ?? hata}</AlanHatasi>
      )}
      <div className="eylemler">
        <IslemDugmesi izin="case.decide" type="submit" tur="tehlike" kucuk calisiyor={calisiyor}>
          Reddi kaydet
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** Analist "Geri gönder": gerekçe zorunlu (ready → draft; ANALIZ 012 §5). */
function GeriGonderFormu({
  gonder,
  vazgec,
  calisiyor,
  hata,
  hataKaynagi,
}: {
  gonder: (gerekce: string) => void;
  vazgec: () => void;
  calisiyor: boolean;
  hata: string | null;
  hataKaynagi?: unknown;
}) {
  const [gerekce, setGerekce] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  return (
    <form
      className="ret-formu"
      data-testid="geri-gonder-formu"
      onSubmit={(e) => {
        e.preventDefault();
        if (!gerekce.trim()) return setUyari("Geri gönderme gerekçesi zorunludur.");
        setUyari(null);
        gonder(gerekce.trim());
      }}
      noValidate
    >
      <div className="alan">
        <label htmlFor={`${id}-gerekce`}>Geri gönderme gerekçesi</label>
        <OtoMetin
          id={`${id}-gerekce`}
          value={gerekce}
          aria-required="true"
          placeholder="Testçinin neyi düzeltmesi gerekiyor?"
          onChange={(e) => setGerekce(e.target.value)}
        />
      </div>
      {(uyari || hata) && <AlanHatasi asistan={uyari ? null : { hata, kaynak: hataKaynagi }}>{uyari ?? hata}</AlanHatasi>}
      <div className="eylemler">
        <IslemDugmesi izin="case.approve" type="submit" kucuk calisiyor={calisiyor}>
          Geri gönder
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
  hataKaynagi,
}: {
  ilk: TestCaseIcerik;
  kaydet: (i: TestCaseIcerik, beklenenAnlamDegisti?: boolean) => void;
  vazgec: () => void;
  calisiyor: boolean;
  hata: string | null;
  hataKaynagi?: unknown;
}) {
  const [icerik, setIcerik] = useState<TestCaseIcerik>(() => JSON.parse(JSON.stringify(ilk)) as TestCaseIcerik);
  const [uyari, setUyari] = useState<string | null>(null);
  // §12: beklenen sonuç metni değiştiyse "anlamca değişti mi?" kararını insan verir (zorunlu).
  const [anlamDegisti, setAnlamDegisti] = useState<"evet" | "hayir" | "">("");
  const id = useId();
  const beklenenDegisti = icerik.expected_result.trim() !== ilk.expected_result.trim();

  const listeMetni = (l: string[]) => l.join("\n");
  const listeyeCevir = (m: string) =>
    m
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  const [onKosulMetni, setOnKosulMetni] = useState(() => listeMetni(ilk.preconditions));
  const [acMetni, setAcMetni] = useState(() => ilk.acceptance_criteria_refs.join(", "));

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
    const acRefleri = acMetni
      .split(/[,\s]+/)
      .map((x) => x.trim().toUpperCase())
      .filter(Boolean);
    if (acRefleri.length === 0) return setUyari("En az bir kabul kriteri atfı gerekir (ör. AC1).");
    if (beklenenDegisti && !anlamDegisti) return setUyari("Beklenen sonuç anlamca değişti mi? Evet ya da Hayır seçin.");
    setUyari(null);
    kaydet(
      {
        ...icerik,
        preconditions: listeyeCevir(onKosulMetni),
        acceptance_criteria_refs: [...new Set(acRefleri)],
        steps: icerik.steps.map((s, i) => ({ ...s, id: `S${i + 1}` })),
      },
      // Metin değişmediyse anlam da değişmemiştir; değiştiyse insanın beyanı gönderilir.
      beklenenDegisti ? anlamDegisti === "evet" : false,
    );
  }

  return (
    <form className="case-duzenle" onSubmit={gonder} noValidate>
      <div className="alan">
        <label htmlFor={`${id}-baslik`}>Başlık</label>
        <input id={`${id}-baslik`} value={icerik.title} maxLength={120} onChange={(e) => setIcerik({ ...icerik, title: e.target.value })} />
      </div>
      <div className="case-duzenle-ozellik">
        <div className="alan">
          <label htmlFor={`${id}-tur`}>Tür</label>
          <select
            id={`${id}-tur`}
            value={icerik.type}
            onChange={(e) => setIcerik({ ...icerik, type: e.target.value as TestCaseIcerik["type"] })}
          >
            {(["positive", "negative", "boundary"] as const).map((k) => (
              <option key={k} value={k}>
                {CASE_TURU[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="alan">
          <label htmlFor={`${id}-risk`}>Risk</label>
          <select
            id={`${id}-risk`}
            value={icerik.risk}
            onChange={(e) => setIcerik({ ...icerik, risk: e.target.value as TestCaseIcerik["risk"] })}
          >
            {(["high", "medium", "low"] as const).map((k) => (
              <option key={k} value={k}>
                {RISK[k].etiket}
              </option>
            ))}
          </select>
        </div>
        <div className="alan">
          <label htmlFor={`${id}-ac`}>Kabul kriteri atıfları</label>
          <input
            id={`${id}-ac`}
            value={acMetni}
            placeholder="AC1, AC2"
            aria-describedby={`${id}-ac-ipucu`}
            onChange={(e) => setAcMetni(e.target.value)}
          />
          <span id={`${id}-ac-ipucu`} className="soluk kucuk">
            Virgülle ayırın; gereksinimde olmayan atıf sunucuda reddedilir.
          </span>
        </div>
      </div>
      <div className="alan">
        <label htmlFor={`${id}-onkosul`}>Ön koşullar (her satır bir ön koşul)</label>
        <OtoMetin id={`${id}-onkosul`} value={onKosulMetni} onChange={(e) => setOnKosulMetni(e.target.value)} />
      </div>
      <fieldset className="alan">
        <legend>Adımlar</legend>
        {icerik.steps.map((s, i) => (
          <div key={i} className="adim-duzenle">
            <span className="mono">S{i + 1}</span>
            <label className="gorunmez" htmlFor={`${id}-a${i}`}>{`S${i + 1} eylem`}</label>
            <OtoMetin id={`${id}-a${i}`} placeholder="Eylem" value={s.action} onChange={(e) => adimGuncelle(i, "action", e.target.value)} />
            <label className="gorunmez" htmlFor={`${id}-d${i}`}>{`S${i + 1} veri`}</label>
            <OtoMetin id={`${id}-d${i}`} placeholder="Veri" value={s.data ?? ""} onChange={(e) => adimGuncelle(i, "data", e.target.value)} />
            <label className="gorunmez" htmlFor={`${id}-e${i}`}>{`S${i + 1} beklenen`}</label>
            <OtoMetin
              id={`${id}-e${i}`}
              placeholder="Beklenen"
              value={s.expected}
              onChange={(e) => adimGuncelle(i, "expected", e.target.value)}
            />
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
        <OtoMetin id={`${id}-beklenen`} value={icerik.expected_result} onChange={(e) => setIcerik({ ...icerik, expected_result: e.target.value })} />
      </div>
      {beklenenDegisti && (
        <fieldset className="alan" data-testid="beklenen-anlam">
          <legend>
            Beklenen sonuç anlamca değişti mi? <span className="hata-metin">*</span>
          </legend>
          <p className="soluk kucuk" id={`${id}-anlam-ipucu`}>
            Yazım/noktalama düzeltmesi ya da açıklama eklemek anlamı değiştirmez. Anlam değiştiyse düzeltme ölçüsü küçük olsa da "küçük
            düzeltme" sayılmaz (§12) ve kabul oranına girmez.
          </p>
          <div className="satir-ogeler" role="radiogroup" aria-required="true" aria-describedby={`${id}-anlam-ipucu`}>
            <label>
              <input
                type="radio"
                name={`${id}-anlam`}
                value="evet"
                checked={anlamDegisti === "evet"}
                onChange={() => setAnlamDegisti("evet")}
              />{" "}
              Evet, anlam değişti
            </label>
            <label>
              <input
                type="radio"
                name={`${id}-anlam`}
                value="hayir"
                checked={anlamDegisti === "hayir"}
                onChange={() => setAnlamDegisti("hayir")}
              />{" "}
              Hayır, yalnızca ifade düzeltildi
            </label>
          </div>
        </fieldset>
      )}
      {(uyari || hata) && (
        <AlanHatasi asistan={uyari ? null : { hata, kaynak: hataKaynagi }}>{uyari ?? hata}</AlanHatasi>
      )}
      <div className="eylemler">
        <IslemDugmesi izin="case.decide" type="submit" kucuk calisiyor={calisiyor}>
          Düzeltip kabul et
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** İçeriğe göre uzayan çok satırlı alan: uzun Türkçe adım metni kırpılmadan görünür. */
function OtoMetin(props: TextareaHTMLAttributes<HTMLTextAreaElement> & { value: string }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight + 2}px`;
  }, [props.value]);
  return <textarea ref={ref} rows={1} className="oto-metin" {...props} />;
}

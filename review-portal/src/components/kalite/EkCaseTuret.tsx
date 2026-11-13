// 012 Ş7 — "Ek case türet" (ANALIZ §4.5): onaylı ilişki + isteğe bağlı kaynak case'ler →
// `POST /requirements/{id}/metamorphic-cases` → türetilen (bağlantılı) ve atlanan (nedenli) liste.
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { MetamorfikIliski, MetamorfikTuretme, TestCase, TuretmeAtlamaSonucu, TuretmeYaniti } from "../../api/types";
import { tarih } from "../../lib/format";
import { useIslem } from "../../hooks";
import { TURETME_ATLAMA } from "../../lib/etiketler";
import { AlanHatasi, Cip, IslemDugmesi } from "../ui";
import { CaseBaglantisi } from "./IliskiKarti";

const ONAYLI_CASE = new Set(["approved", "published"]);

export function EkCaseTuret({
  requirementId,
  iliskiler,
  caseler,
  turetildi,
}: {
  requirementId: string;
  iliskiler: MetamorfikIliski[];
  /** Gereksinimin case'leri (kaynak seçimi ve başlıklar); yüklenemediyse boş. */
  caseler: TestCase[];
  turetildi: () => void;
}) {
  const uygun = iliskiler.filter((r) => r.durum === "approved" && !r.bayat);
  // u2 N7: Kule'deki kaçan hatadan gelen bağlantı ilişkiyi, kaynak case'i ve türetilecek girdiyi taşır.
  const [parametreler] = useSearchParams();
  const pIliski = parametreler.get("iliski") ?? "";
  const pKaynak = parametreler.get("kaynak");
  const pGirdi = parametreler.get("girdi");
  const [iliskiId, setIliskiId] = useState(pIliski);
  const [secili, setSecili] = useState<string[]>(pKaynak ? [pKaynak] : []);
  const [sonuc, setSonuc] = useState<TuretmeYaniti | null>(null);
  const islem = useIslem();
  const id = useId();
  const sonucRef = useRef<HTMLDivElement | null>(null);
  const secilen = uygun.find((r) => r.id === iliskiId) ?? uygun[0];
  // u2 N12: kaynak listesi seçili ilişkinin kabul kriterine atıf yapan onaylı case'lerle süzülür.
  const iliskiRefleri = new Set((secilen?.icerik.ac_refs ?? []).map((r) => r.replace(/\s/g, "").toUpperCase()));
  const kaynaklar = caseler.filter(
    (c) => ONAYLI_CASE.has(c.durum) && (!secilen || c.icerik.acceptance_criteria_refs.some((r) => iliskiRefleri.has(r.replace(/\s/g, "").toUpperCase()))),
  );
  const kaynakCase = pKaynak ? caseler.find((c) => c.id === pKaynak) : undefined;
  const baslik = (cid: string) => caseler.find((c) => c.id === cid)?.icerik.title ?? cid;

  async function turet(e: FormEvent) {
    e.preventDefault();
    if (!secilen) return;
    const y = await islem.calistir(() => api.ekCaseTuret(requirementId, { iliski_id: secilen.id, ...(secili.length ? { case_ids: secili } : {}) }));
    if (y) {
      setSonuc(y);
      turetildi();
      requestAnimationFrame(() => sonucRef.current?.focus());
    }
  }

  return (
    <section className="turet" id="ek-case-turet" tabIndex={-1} aria-labelledby={`${id}-baslik`} data-testid="ek-case-turet">
      <h3 id={`${id}-baslik`}>Ek case türet</h3>
      <p className="soluk kucuk">
        Onaylı ilişki, kaynak case'in doğrulanmış değerlerinden yeni girdi ve beklenen değer hesaplar. Türetilen case taslak olarak yazılır; insan onayından ve
        beklenen sonuç kontrolünden geçer. Aynı kaynak ve ilişki ikinci kez türetilmez.
      </p>
      {pKaynak && secilen?.id === pIliski && (
        <p className="kucuk turet-onizleme" data-testid="turet-onizleme">
          Kaçan hata için hazırlandı: <strong>İ{secilen.sira_no}</strong> ilişkisi, kaynak{" "}
          <strong>{kaynakCase ? `C${kaynakCase.sira_no}` : pKaynak}</strong>
          {pGirdi && (
            <>
              {" "}
              · türetilecek girdi: <strong className="mono">{pGirdi}</strong>
            </>
          )}
          . Kontrol edip “Ek case türet”e basın.
        </p>
      )}
      <form onSubmit={turet} noValidate>
        <div className="alan">
          <label htmlFor={`${id}-iliski`}>İlişki</label>
          <select
            id={`${id}-iliski`}
            value={secilen?.id ?? ""}
            disabled={uygun.length === 0}
            onChange={(e) => {
              setIliskiId(e.target.value);
              setSecili([]);
            }}
          >
            {uygun.length === 0 && <option value="">Onaylı ilişki yok</option>}
            {uygun.map((r) => (
              <option key={r.id} value={r.id}>
                İ{r.sira_no} · {r.icerik.ad}
              </option>
            ))}
          </select>
        </div>
        <fieldset>
          <legend>Kaynak case'ler (isteğe bağlı)</legend>
          <p id={`${id}-kaynak-ipucu`} className="soluk kucuk">
            Seçilmezse ilişkinin kabul kriterine ({[...iliskiRefleri].join(", ") || "—"}) atıf yapan onaylı case'ler kullanılır; liste yalnız onları gösterir.
          </p>
          {kaynaklar.length === 0 ? (
            <p className="soluk kucuk">Bu ilişkinin kabul kriterine atıf yapan onaylı case yok.</p>
          ) : (
            <div className="turet-kaynaklar">
              {kaynaklar.map((c) => (
                <label key={c.id}>
                  <input
                    type="checkbox"
                    checked={secili.includes(c.id)}
                    aria-describedby={`${id}-kaynak-ipucu`}
                    onChange={(e) => setSecili(e.target.checked ? [...secili, c.id] : secili.filter((x) => x !== c.id))}
                  />{" "}
                  <span className="mono soluk">C{c.sira_no}</span> {c.icerik.title}
                </label>
              ))}
            </div>
          )}
        </fieldset>
        <div className="eylemler">
          <IslemDugmesi izin="case.generate" type="submit" calisiyor={islem.calisiyor} disabled={!secilen} title={!secilen ? "Önce bir ilişkiyi PO onayına gönderip onaylatın." : undefined}>
            Ek case türet
          </IslemDugmesi>
        </div>
      </form>
      {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
      {sonuc && (
        <div ref={sonucRef} tabIndex={-1} className="turet-sonuc-kutu" data-testid="turet-sonuc" aria-live="polite">
          <h4 className="kt-bolum">Türetilen ({sonuc.turetilen.length})</h4>
          {sonuc.turetilen.length === 0 ? (
            <p className="soluk kucuk">Yeni case türetilmedi.</p>
          ) : (
            <ul className="duz-liste turet-sonuc">
              {sonuc.turetilen.map((t) => (
                <li key={t.case_id}>
                  <Cip ton="bilgi">Taslak</Cip>
                  <CaseBaglantisi requirementId={requirementId} caseId={t.case_id}>
                    {t.baslik || t.case_id}
                  </CaseBaglantisi>
                  <span className="soluk kucuk">kaynak: {baslik(t.kaynak_case_id)}</span>
                </li>
              ))}
            </ul>
          )}
          <h4 className="kt-bolum">Atlanan ({sonuc.atlanan.length})</h4>
          {sonuc.atlanan.length === 0 ? (
            <p className="soluk kucuk">Atlanan kaynak yok.</p>
          ) : (
            <ul className="duz-liste turet-sonuc">
              {sonuc.atlanan.map((a) => (
                <li key={a.kaynak_case_id}>
                  <Cip ton={a.sonuc === "zaten_turetildi" ? "notr" : "uyari"}>Atlandı: {TURETME_ATLAMA[a.sonuc as TuretmeAtlamaSonucu] ?? a.sonuc}</Cip>
                  <span>{baslik(a.kaynak_case_id)}</span>
                  {a.neden && <span className="soluk kucuk">— {a.neden}</span>}
                  {a.case_id && (
                    <CaseBaglantisi requirementId={requirementId} caseId={a.case_id}>
                      Türetilen case'i aç
                    </CaseBaglantisi>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <TuretmeGecmisi requirementId={requirementId} baslik={baslik} yenileme={sonuc} />
    </section>
  );
}

/** "Türetme geçmişi": açılınca yüklenir (`GET /requirements/{id}/metamorphic-derivations`). */
function TuretmeGecmisi({ requirementId, baslik, yenileme }: { requirementId: string; baslik: (cid: string) => string; yenileme: unknown }) {
  const [acik, setAcik] = useState(false);
  const [liste, setListe] = useState<MetamorfikTuretme[] | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  useEffect(() => {
    if (!acik) return;
    let iptal = false;
    setHata(null);
    api.metamorfikTuretmeler(requirementId).then(
      (l) => !iptal && setListe(l),
      (e: unknown) => !iptal && setHata(e instanceof Error ? e.message : "Türetme geçmişi yüklenemedi."),
    );
    return () => {
      iptal = true;
    };
  }, [acik, requirementId, yenileme]);
  return (
    <details className="turet-gecmis" data-testid="turetme-gecmisi" onToggle={(e) => setAcik((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="kucuk">Türetme geçmişi</summary>
      {hata ? (
        <AlanHatasi>{hata}</AlanHatasi>
      ) : !liste ? (
        acik && <p className="soluk kucuk">Yükleniyor…</p>
      ) : liste.length === 0 ? (
        <p className="soluk kucuk">Bu gereksinimde henüz türetme yapılmadı.</p>
      ) : (
        <ul className="duz-liste turet-sonuc">
          {liste.map((t) => (
            <li key={t.id}>
              {t.sonuc === "turetildi" ? <Cip ton="bilgi">Türetildi</Cip> : <Cip ton="uyari">Atlandı: {TURETME_ATLAMA[t.sonuc as TuretmeAtlamaSonucu] ?? t.sonuc}</Cip>}
              <span>{baslik(t.kaynak_case_id)}</span>
              {t.turetilen_case_id && (
                <CaseBaglantisi requirementId={requirementId} caseId={t.turetilen_case_id}>
                  Türetilen case
                </CaseBaglantisi>
              )}
              {t.neden && <span className="soluk kucuk">— {t.neden}</span>}
              {t.olusturma && <span className="soluk kucuk">{tarih(t.olusturma)}</span>}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

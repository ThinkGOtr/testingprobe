// 012 Ş7 — "Ek case türet" (ANALIZ §4.5): onaylı ilişki + isteğe bağlı kaynak case'ler →
// `POST /requirements/{id}/metamorphic-cases` → türetilen (bağlantılı) ve atlanan (nedenli) liste.
import { useId, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { MetamorfikIliski, TestCase, TuretmeAtlamaSonucu, TuretmeYaniti } from "../../api/types";
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
  const [iliskiId, setIliskiId] = useState("");
  const [secili, setSecili] = useState<string[]>([]);
  const [sonuc, setSonuc] = useState<TuretmeYaniti | null>(null);
  const islem = useIslem();
  const id = useId();
  const sonucRef = useRef<HTMLDivElement | null>(null);
  const secilen = uygun.find((r) => r.id === iliskiId) ?? uygun[0];
  const kaynaklar = caseler.filter((c) => ONAYLI_CASE.has(c.durum));
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
    <section className="turet" aria-labelledby={`${id}-baslik`} data-testid="ek-case-turet">
      <h3 id={`${id}-baslik`}>Ek case türet</h3>
      <p className="soluk kucuk">
        Onaylı ilişki, kaynak case'in doğrulanmış değerlerinden yeni girdi ve beklenen değer hesaplar. Türetilen case taslak olarak yazılır; insan onayından ve
        beklenen sonuç kontrolünden geçer. Aynı kaynak ve ilişki ikinci kez türetilmez.
      </p>
      <form onSubmit={turet} noValidate>
        <div className="alan">
          <label htmlFor={`${id}-iliski`}>İlişki</label>
          <select id={`${id}-iliski`} value={secilen?.id ?? ""} disabled={uygun.length === 0} onChange={(e) => setIliskiId(e.target.value)}>
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
            Seçilmezse ilişkinin kabul kriterine atıf yapan onaylı case'ler kullanılır.
          </p>
          {kaynaklar.length === 0 ? (
            <p className="soluk kucuk">Onaylı case yok.</p>
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
          <IslemDugmesi roller={["analyst"]} type="submit" calisiyor={islem.calisiyor} disabled={!secilen} title={!secilen ? "Önce bir ilişkiyi PO onayına gönderip onaylatın." : undefined}>
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
                  <CaseBaglantisi requirementId={requirementId}>{t.baslik || t.case_id}</CaseBaglantisi>
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
                  {a.case_id && <CaseBaglantisi requirementId={requirementId}>Türetilen case'i aç</CaseBaglantisi>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

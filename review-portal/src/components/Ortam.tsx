// Test ortamı rozeti, tetik seçicisi ve süzgeci. Projede ortam yoksa (boş liste, eski core, izin yok)
// hiçbiri çizilmez ve istekler eskisiyle birebir kalır.
import { useId } from "react";
import { api } from "../api/client";
import type { Ortam, Ortamlar, TestOrtami } from "../api/types";
import { varsayilanOrtam } from "../api/uyumOrtam";
import { useIzin } from "../auth";
import { useVeri } from "../hooks";
import { ortamMetni, ortamSecenekMetni, ortamTuruEtiketi } from "../lib/ortam";
import { Cip, Uyari } from "./ui";

const BOS: Ortamlar = { ortamlar: [], varsayilan_eid: null };

/** Projenin ortamları; okunamazsa (uç yok, izin yok) boş liste. `yuklendi`: istek bitti. */
export function useOrtamlar(): { ortamlar: Ortam[]; varsayilan: Ortam | null; varsayilanEid: string | null; yuklendi: boolean } {
  const okur = useIzin("run.read");
  const v = useVeri(() => (okur ? api.ortamlar().catch(() => BOS) : Promise.resolve(BOS)), [okur]);
  const o = v.veri ?? BOS;
  return { ortamlar: o.ortamlar, varsayilan: varsayilanOrtam(o), varsayilanEid: o.varsayilan_eid, yuklendi: v.veri !== undefined };
}

export function OrtamRozeti({ ortam }: { ortam: TestOrtami | null | undefined }) {
  if (!ortam) return null;
  return (
    <Cip ton={ortam.canli ? "uyari" : "notr"} className="ortam-rozeti" title={`${ortamMetni("rozetOnEki")}${ortam.ad} (${ortamTuruEtiketi(ortam.tur)})`}>
      <span className="gorunmez">{ortamMetni("rozetOnEki")}</span>
      <span data-testid="ortam-rozeti" data-eid={ortam.eid} data-canli={ortam.canli || undefined}>
        {ortam.ad}
      </span>
    </Cip>
  );
}

export function CanliOrtamUyarisi({ id }: { id?: string }) {
  return (
    <Uyari ton="uyari" id={id}>
      <span data-testid="canli-ortam-uyarisi">{ortamMetni("canliUyari")}</span>
    </Uyari>
  );
}

/** Koşu tetiklerinin ortam seçicisi (seçili ortam canlıysa satır içi uyarı). */
export function OrtamSecici({ ortamlar, deger, degistir, geceNotu }: { ortamlar: Ortam[]; deger: string; degistir: (eid: string) => void; geceNotu?: boolean }) {
  const id = useId();
  if (ortamlar.length === 0) return null;
  const secili = ortamlar.find((o) => o.eid === deger) ?? null;
  return (
    <div className="ortam-secici" data-testid="ortam-secici">
      <div className="filtre-cubugu" role="group" aria-label={ortamMetni("tetikOrtami")}>
        <label htmlFor={id}>{ortamMetni("tetikOrtami")}</label>
        <select id={id} value={deger} onChange={(e) => degistir(e.target.value)}>
          {ortamlar.map((o) => (
            <option key={o.eid} value={o.eid}>
              {ortamSecenekMetni(o)}
            </option>
          ))}
        </select>
        {geceNotu && <span className="kucuk soluk">{ortamMetni("geceNotu")}</span>}
      </div>
      {secili?.canli && <CanliOrtamUyarisi />}
    </div>
  );
}

/** Liste süzgeci: "" = tümü, eid, `-` = ortamsız (`ortamsiz` verilirse). */
export function OrtamSuzgeci({ ortamlar, deger, degistir, ortamsiz = true }: { ortamlar: TestOrtami[]; deger: string; degistir: (d: string) => void; ortamsiz?: boolean }) {
  return (
    <label>
      {ortamMetni("ortam")}
      <select value={deger} onChange={(e) => degistir(e.target.value)} data-testid="ortam-suzgeci">
        <option value="">{ortamMetni("tumu")}</option>
        {ortamlar.map((o) => (
          <option key={o.eid} value={o.eid}>
            {o.ad} ({ortamTuruEtiketi(o.tur)})
          </option>
        ))}
        {ortamsiz && <option value="-">{ortamMetni("ortamsiz")}</option>}
      </select>
    </label>
  );
}

/** Süzgeç seçenekleri: projenin ortamları + koşularda görülüp listede olmayanlar (silinmiş ortam). */
export function suzgecOrtamlari(ortamlar: readonly TestOrtami[], kosular: readonly { test_ortami?: TestOrtami | null }[]): TestOrtami[] {
  const m = new Map<string, TestOrtami>();
  for (const o of ortamlar) m.set(o.eid, o);
  for (const k of kosular) if (k.test_ortami && !m.has(k.test_ortami.eid)) m.set(k.test_ortami.eid, k.test_ortami);
  return [...m.values()];
}

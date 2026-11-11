// Tasarım modeli "Düzelt" formu: JSON değil, alan bazlı düzenleme. Kapsam öğesi ekle/sil/tanım
// düzelt/geçerlilik değiştir; bölüm tanımı/temsilci değeri; sınır değeri ve beklenen sonucu;
// koşul iddiası; açık soru ve varsayım ekle/sil/düzelt. Kaydet → karar "edit" (core şema + model
// kontrollerinden geçirir; düzeltme ölçüsü sunucuda kaydedilir). Model kontrolü önizlemesi anında
// gösterilir (lib/tasarimModeli.modelSorunlari); yetkili kontrol core'dadır.
import { useMemo, useState } from "react";
import type { DesignModel, SinirBeklenen, SoruSahibi } from "../api/tasarimModeliTipleri";
import { modelSorunlari, OGE_KIMLIGI, SAHIP, SINIR_BEKLENEN } from "../lib/tasarimModeli";
import { Uyari } from "./ui";

const kopya = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const SAHIPLER: SoruSahibi[] = ["PO", "analyst", "developer", ""];

/** Silinen kapsam öğesine bağlı ayrıntılı model satırları da çıkarılır (sahipsiz satır kalmaz). */
export function ogeSil(m: DesignModel, id: string): DesignModel {
  return {
    ...m,
    coverage_items: m.coverage_items.filter((o) => o.id !== id),
    partitions: m.partitions.filter((p) => p.item_id !== id),
    boundaries: m.boundaries.filter((b) => b.item_id !== id),
    decision_tables: m.decision_tables.map((d) => ({ ...d, rules: d.rules.filter((r) => r.item_id !== id) })),
    state_models: m.state_models.map((s) => ({
      ...s,
      valid_transitions: s.valid_transitions.filter((t) => t.item_id !== id),
      invalid_transitions: s.invalid_transitions.filter((t) => t.item_id !== id),
    })),
    flows: m.flows.filter((f) => f.item_id !== id),
  };
}

/** Kapsam öğesinin geçerliliği değişince ona bağlı bölüm de aynı sınıfa geçer. */
export function gecerlilikDegistir(m: DesignModel, id: string, valid: boolean): DesignModel {
  return {
    ...m,
    coverage_items: m.coverage_items.map((o) => (o.id === id ? { ...o, valid } : o)),
    partitions: m.partitions.map((p) => (p.item_id === id ? { ...p, valid } : p)),
  };
}

function sonrakiKimlik(onek: "Q" | "A", liste: { id: string }[]): string {
  const n = Math.max(0, ...liste.map((x) => Number(x.id.slice(1)) || 0)) + 1;
  return `${onek}${n}`;
}

export function TasarimModeliDuzenleyici({
  ilk,
  kaydet,
  vazgec,
  calisiyor,
}: {
  ilk: DesignModel;
  kaydet: (m: DesignModel) => void;
  vazgec: () => void;
  calisiyor?: boolean;
}) {
  const [m, setM] = useState<DesignModel>(() => kopya(ilk));
  const [yeniOge, setYeniOge] = useState({ id: "", ac_ref: "", definition: "", valid: true });
  const sorunlar = useMemo(() => modelSorunlari(m), [m]);
  const degisti = JSON.stringify(m) !== JSON.stringify(ilk);
  const yeniOgeHatasi = !yeniOge.id
    ? null
    : !OGE_KIMLIGI.test(yeniOge.id)
      ? "Kimlik deseni: EP-V1, EP-I1, BV-1, DT-R1, ST-S1>S2, PW-1, UC-MF/AF1/EF1, EG-1"
      : m.coverage_items.some((o) => o.id === yeniOge.id)
        ? "Bu kimlik zaten var"
        : null;

  const guncelle = (f: (x: DesignModel) => DesignModel) => setM((x) => f(kopya(x)));

  return (
    <form
      className="model-duzenleyici"
      data-testid="model-duzenleyici"
      aria-label="Tasarım modelini düzelt"
      onSubmit={(e) => {
        e.preventDefault();
        kaydet(m);
      }}
    >
      <fieldset>
        <legend>Test koşulları</legend>
        {m.conditions.map((c, i) => (
          <label key={c.id} className="duzen-satir">
            <span className="mono">{c.id}</span>
            <input
              aria-label={`${c.id} iddiası`}
              value={c.statement}
              onChange={(e) => guncelle((x) => ((x.conditions[i].statement = e.target.value), x))}
            />
          </label>
        ))}
      </fieldset>

      <fieldset>
        <legend>Kapsam öğeleri</legend>
        {m.coverage_items.map((o, i) => (
          <div key={o.id} className="duzen-satir" data-testid={`duzen-oge-${o.id}`}>
            <span className="mono">{o.id}</span>
            <input
              aria-label={`${o.id} tanımı`}
              value={o.definition}
              onChange={(e) => guncelle((x) => ((x.coverage_items[i].definition = e.target.value), x))}
            />
            <label className="secenek-satir">
              <input type="checkbox" checked={o.valid} onChange={(e) => guncelle((x) => gecerlilikDegistir(x, o.id, e.target.checked))} aria-label={`${o.id} geçerli`} />
              geçerli
            </label>
            <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => guncelle((x) => ogeSil(x, o.id))} aria-label={`${o.id} öğesini sil`}>
              Sil
            </button>
          </div>
        ))}
        <div className="duzen-satir" data-testid="duzen-yeni-oge">
          <input aria-label="Yeni öğe kimliği" placeholder="EP-I3" value={yeniOge.id} onChange={(e) => setYeniOge({ ...yeniOge, id: e.target.value.trim() })} />
          <input aria-label="Yeni öğe AC" placeholder="AC1" value={yeniOge.ac_ref} onChange={(e) => setYeniOge({ ...yeniOge, ac_ref: e.target.value.trim() })} />
          <input aria-label="Yeni öğe tanımı" placeholder="Tanım" value={yeniOge.definition} onChange={(e) => setYeniOge({ ...yeniOge, definition: e.target.value })} />
          <label className="secenek-satir">
            <input type="checkbox" checked={yeniOge.valid} onChange={(e) => setYeniOge({ ...yeniOge, valid: e.target.checked })} aria-label="Yeni öğe geçerli" />
            geçerli
          </label>
          <button
            type="button"
            className="dugme dugme-ikincil dugme-kucuk"
            disabled={!yeniOge.id || !yeniOge.definition.trim() || !!yeniOgeHatasi}
            onClick={() => {
              guncelle((x) => {
                x.coverage_items.push({ id: yeniOge.id, ac_ref: /^AC\d+$/.test(yeniOge.ac_ref) ? yeniOge.ac_ref : null, definition: yeniOge.definition.trim(), valid: yeniOge.valid });
                return x;
              });
              setYeniOge({ id: "", ac_ref: "", definition: "", valid: true });
            }}
          >
            Öğe ekle
          </button>
          {yeniOgeHatasi && <span className="kucuk hata-metin">{yeniOgeHatasi}</span>}
        </div>
      </fieldset>

      {m.partitions.length > 0 && (
        <fieldset>
          <legend>Eşdeğerlik bölümleri</legend>
          {m.partitions.map((p, i) => (
            <div key={p.item_id} className="duzen-satir">
              <span className="mono">{p.item_id}</span>
              <input aria-label={`${p.item_id} bölüm tanımı`} value={p.definition} onChange={(e) => guncelle((x) => ((x.partitions[i].definition = e.target.value), x))} />
              <input
                aria-label={`${p.item_id} temsilci değer`}
                value={p.representative}
                onChange={(e) => guncelle((x) => ((x.partitions[i].representative = e.target.value), x))}
              />
            </div>
          ))}
        </fieldset>
      )}

      {m.boundaries.length > 0 && (
        <fieldset>
          <legend>Sınır değerler</legend>
          {m.boundaries.map((b, i) => (
            <div key={b.item_id} className="duzen-satir">
              <span className="mono">{b.item_id}</span>
              <input aria-label={`${b.item_id} değer`} value={b.value} onChange={(e) => guncelle((x) => ((x.boundaries[i].value = e.target.value), x))} />
              <select
                aria-label={`${b.item_id} beklenen`}
                value={b.expected}
                onChange={(e) =>
                  guncelle((x) => {
                    const beklenen = e.target.value as SinirBeklenen;
                    x.boundaries[i].expected = beklenen;
                    // Ret beklenen sınır geçersiz, kabul beklenen geçerli öğedir (model kontrolü).
                    if (beklenen !== "open_question") return gecerlilikDegistir(x, b.item_id, beklenen === "accept");
                    return x;
                  })
                }
              >
                {(Object.keys(SINIR_BEKLENEN) as SinirBeklenen[]).map((k) => (
                  <option key={k} value={k}>
                    {SINIR_BEKLENEN[k].etiket}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </fieldset>
      )}

      <fieldset>
        <legend>Açık sorular</legend>
        {m.open_questions.map((q, i) => (
          <div key={q.id} className="duzen-satir">
            <span className="mono">{q.id}</span>
            <input aria-label={`${q.id} soru`} value={q.question} onChange={(e) => guncelle((x) => ((x.open_questions[i].question = e.target.value), x))} />
            <select aria-label={`${q.id} sahibi`} value={q.owner} onChange={(e) => guncelle((x) => ((x.open_questions[i].owner = e.target.value as SoruSahibi), x))}>
              {SAHIPLER.map((s) => (
                <option key={s} value={s}>
                  {SAHIP[s]}
                </option>
              ))}
            </select>
            <button type="button" className="dugme dugme-ikincil dugme-kucuk" aria-label={`${q.id} sorusunu sil`} onClick={() => guncelle((x) => ({ ...x, open_questions: x.open_questions.filter((y) => y.id !== q.id) }))}>
              Sil
            </button>
          </div>
        ))}
        <button
          type="button"
          className="dugme dugme-ikincil dugme-kucuk"
          onClick={() => guncelle((x) => ({ ...x, open_questions: [...x.open_questions, { id: sonrakiKimlik("Q", x.open_questions), question: "", owner: "PO" }] }))}
        >
          Soru ekle
        </button>
      </fieldset>

      <fieldset>
        <legend>Varsayımlar</legend>
        {m.assumptions.map((a, i) => (
          <div key={a.id} className="duzen-satir">
            <span className="mono">{a.id}</span>
            <input aria-label={`${a.id} varsayım`} value={a.statement} onChange={(e) => guncelle((x) => ((x.assumptions[i].statement = e.target.value), x))} />
            <select aria-label={`${a.id} doğrulayacak`} value={a.owner} onChange={(e) => guncelle((x) => ((x.assumptions[i].owner = e.target.value as SoruSahibi), x))}>
              {SAHIPLER.map((s) => (
                <option key={s} value={s}>
                  {SAHIP[s]}
                </option>
              ))}
            </select>
            <button type="button" className="dugme dugme-ikincil dugme-kucuk" aria-label={`${a.id} varsayımını sil`} onClick={() => guncelle((x) => ({ ...x, assumptions: x.assumptions.filter((y) => y.id !== a.id) }))}>
              Sil
            </button>
          </div>
        ))}
        <button
          type="button"
          className="dugme dugme-ikincil dugme-kucuk"
          onClick={() => guncelle((x) => ({ ...x, assumptions: [...x.assumptions, { id: sonrakiKimlik("A", x.assumptions), statement: "", owner: "PO" }] }))}
        >
          Varsayım ekle
        </button>
      </fieldset>

      {sorunlar.length > 0 && (
        <div data-testid="duzen-sorunlar">
          <Uyari baslik="Model kontrolleri (kaydetmeden önce düzeltin)">
            <ul>
              {sorunlar.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </Uyari>
        </div>
      )}
      {(m.open_questions.some((q) => !q.question.trim()) || m.assumptions.some((a) => !a.statement.trim())) && (
        <p className="kucuk hata-metin">Boş soru/varsayım metni kaydedilemez.</p>
      )}
      <div className="satir-ogeler">
        <button
          type="submit"
          className="dugme dugme-birincil"
          disabled={
            calisiyor ||
            !degisti ||
            sorunlar.length > 0 ||
            m.open_questions.some((q) => !q.question.trim()) ||
            m.assumptions.some((a) => !a.statement.trim())
          }
          title={!degisti ? "Değişiklik yok; değiştirmeden onaylamak için 'Onayla'yı kullanın" : undefined}
        >
          Düzeltmeyi kaydet ve onayla
        </button>
        <button type="button" className="dugme dugme-ikincil" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

// Tasarım modelinin salt okunur tabloları (koşullar, teknikler, kapsam öğeleri, bölümler, sınırlar,
// karar tabloları, durum modelleri, akışlar, pairwise, model sorunları, açık sorular, varsayımlar).
// Boş bölüm gösterilmez. Model içeriği AI çıktısıdır: düz metin olarak gösterilir.
import type { ReactNode } from "react";
import type { DesignModel } from "../api/tasarimModeliTipleri";
import { MODEL_SORUNU, RISK_ETIKETI, SAHIP, SINIR_BEKLENEN, SINIR_TARAFI, TEKNIK_ADI } from "../lib/tasarimModeli";
import { TeknikRozeti } from "./CaseKarti";
import { Cip } from "./ui";

function Tablo({ ad, testId, basliklar, children }: { ad: string; testId: string; basliklar: string[]; children: ReactNode }) {
  return (
    <section aria-label={ad} data-testid={testId} className="model-bolum">
      <h3>{ad}</h3>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`${ad} tablosu`}>
        <table className="tablo tablo-sik tablo-yigin">
          <thead>
            <tr>
              {basliklar.map((b) => (
                <th key={b} scope="col">
                  {b}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </section>
  );
}

const Gecerlilik = ({ valid }: { valid: boolean }) => <Cip ton={valid ? "basari" : "uyari"}>{valid ? "geçerli" : "geçersiz"}</Cip>;

export function TasarimModeliTablolari({ m }: { m: DesignModel }) {
  const kosulAc = new Map(m.conditions.map((c) => [c.id, c.ac_refs.join(", ")]));
  return (
    <div className="model-tablolari">
      {m.conditions.length > 0 && (
        <Tablo ad="Test koşulları" testId="model-kosullar" basliklar={["Kimlik", "AC", "İddia", "Risk", "Gerekçe"]}>
          {m.conditions.map((c) => (
            <tr key={c.id}>
              <td className="mono" data-etiket="Kimlik">{c.id}</td>
              <td className="mono" data-etiket="AC">{c.ac_refs.join(", ") || "—"}</td>
              <td data-etiket="İddia">{c.statement}</td>
              <td data-etiket="Risk">
                <Cip ton={RISK_ETIKETI[c.risk]?.ton ?? "notr"}>{RISK_ETIKETI[c.risk]?.etiket ?? c.risk}</Cip>
              </td>
              <td data-etiket="Gerekçe">{c.rationale}</td>
            </tr>
          ))}
        </Tablo>
      )}
      {m.techniques.length > 0 && (
        <Tablo ad="Seçilen teknikler" testId="model-teknikler" basliklar={["Koşul", "Teknik", "Gerekçe"]}>
          {m.techniques.map((t, i) => (
            <tr key={`${t.condition_id}-${t.technique}-${i}`}>
              <td className="mono" data-etiket="Koşul">
                {t.condition_id}
                {kosulAc.get(t.condition_id) && <span className="soluk kucuk"> ({kosulAc.get(t.condition_id)})</span>}
              </td>
              <td data-etiket="Teknik">
                <TeknikRozeti teknik={t.technique} /> <span className="kucuk">{TEKNIK_ADI[t.technique] ?? ""}</span>
              </td>
              <td data-etiket="Gerekçe">{t.rationale}</td>
            </tr>
          ))}
        </Tablo>
      )}
      {m.coverage_items.length > 0 && (
        <Tablo ad="Kapsam öğeleri" testId="model-ogeler" basliklar={["Öğe", "AC", "Tanım", "Sınıf"]}>
          {m.coverage_items.map((o) => (
            <tr key={o.id}>
              <td className="mono" data-etiket="Öğe">{o.id}</td>
              <td className="mono" data-etiket="AC">{o.ac_ref ?? "—"}</td>
              <td data-etiket="Tanım">{o.definition}</td>
              <td data-etiket="Sınıf"><Gecerlilik valid={o.valid} /></td>
            </tr>
          ))}
        </Tablo>
      )}
      {m.partitions.length > 0 && (
        <Tablo ad="Eşdeğerlik bölümleri" testId="model-bolumler" basliklar={["Alan", "Öğe", "Bölüm", "Temsilci değer", "Sınıf"]}>
          {m.partitions.map((p) => (
            <tr key={p.item_id}>
              <td data-etiket="Alan">{p.field}</td>
              <td className="mono" data-etiket="Öğe">{p.item_id}</td>
              <td data-etiket="Bölüm">{p.definition}</td>
              <td className="mono" data-etiket="Temsilci değer">{p.representative || "—"}</td>
              <td data-etiket="Sınıf"><Gecerlilik valid={p.valid} /></td>
            </tr>
          ))}
        </Tablo>
      )}
      {m.boundaries.length > 0 && (
        <Tablo ad="Sınır değerler" testId="model-sinirlar" basliklar={["Alan", "Öğe", "Değer", "Konum", "Beklenen", "Dahil/hariç kaynağı"]}>
          {m.boundaries.map((b) => (
            <tr key={b.item_id}>
              <td data-etiket="Alan">{b.field}</td>
              <td className="mono" data-etiket="Öğe">{b.item_id}</td>
              <td className="mono" data-etiket="Değer">{b.value}</td>
              <td data-etiket="Konum">{SINIR_TARAFI[b.side] ?? b.side}</td>
              <td data-etiket="Beklenen">
                <Cip ton={SINIR_BEKLENEN[b.expected]?.ton ?? "notr"}>{SINIR_BEKLENEN[b.expected]?.etiket ?? b.expected}</Cip>
              </td>
              <td data-etiket="Dahil/hariç kaynağı">
                {b.inclusive_source ?? <span className="soluk">kaynak sessiz{b.question_ref ? ` (${b.question_ref})` : ""}</span>}
              </td>
            </tr>
          ))}
        </Tablo>
      )}
      {m.decision_tables.map((d) => (
        <section key={d.id} aria-label={`Karar tablosu ${d.id}`} data-testid="model-karar-tablosu" className="model-bolum">
          <h3>Karar tablosu {d.id}</h3>
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`Karar tablosu ${d.id} tablosu`}>
            <table className="tablo tablo-sik">
              <thead>
                <tr>
                  <th scope="col">Kural</th>
                  {d.conditions.map((c) => (
                    <th key={c} scope="col">
                      {c}
                    </th>
                  ))}
                  <th scope="col">Eylemler</th>
                </tr>
              </thead>
              <tbody>
                {d.rules.map((r) => (
                  <tr key={r.item_id}>
                    <td className="mono">{r.item_id}</td>
                    {d.conditions.map((c) => (
                      <td key={c}>{r.condition_values.find((v) => v.condition === c)?.value ?? "—"}</td>
                    ))}
                    <td>{r.actions.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.actions.length > 0 && <p className="kucuk soluk">Eylemler: {d.actions.join("; ")}</p>}
          {d.undefined_combinations.length > 0 && (
            <div className="kucuk" data-testid="model-tanimsiz-kombinasyon">
              <strong>Tanımsız kombinasyonlar (açık soru):</strong>
              <ul>
                {d.undefined_combinations.map((u) => (
                  <li key={`${u.question_ref}-${u.description}`}>
                    {u.description} <span className="mono">({u.question_ref})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      ))}
      {m.state_models.map((s) => (
        <section key={s.id} aria-label={`Durum modeli ${s.id}`} data-testid="model-durum-modeli" className="model-bolum">
          <h3>Durum modeli {s.id}</h3>
          <p className="kucuk">Durumlar: {s.states.map((d) => `${d.id} ${d.name}`).join(", ")}</p>
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`Durum modeli ${s.id} geçişleri`}>
            <table className="tablo tablo-sik tablo-yigin">
              <thead>
                <tr>
                  <th scope="col">Öğe</th>
                  <th scope="col">Kaynak</th>
                  <th scope="col">Olay</th>
                  <th scope="col">Hedef</th>
                </tr>
              </thead>
              <tbody>
                {s.valid_transitions.map((t) => (
                  <tr key={t.item_id}>
                    <td className="mono" data-etiket="Öğe">{t.item_id}</td>
                    <td data-etiket="Kaynak">{t.from}</td>
                    <td data-etiket="Olay">{t.event}</td>
                    <td data-etiket="Hedef">{t.to}</td>
                  </tr>
                ))}
                {s.invalid_transitions.map((t) => (
                  <tr key={t.item_id}>
                    <td className="mono" data-etiket="Öğe">{t.item_id}</td>
                    <td data-etiket="Kaynak">{t.from}</td>
                    <td data-etiket="Olay">{t.event}</td>
                    <td data-etiket="Hedef">
                      <Cip ton="hata">geçersiz geçiş</Cip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {s.undefined_transitions.length > 0 && (
            <div className="kucuk">
              <strong>Tanımsız geçişler (açık soru):</strong>
              <ul>
                {s.undefined_transitions.map((u) => (
                  <li key={`${u.question_ref}-${u.description}`}>
                    {u.description} <span className="mono">({u.question_ref})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      ))}
      {m.flows.length > 0 && (
        <Tablo ad="Akışlar" testId="model-akislar" basliklar={["Öğe", "Tür", "Adımlar", "Koşul"]}>
          {m.flows.map((f) => (
            <tr key={f.item_id}>
              <td className="mono" data-etiket="Öğe">{f.item_id}</td>
              <td data-etiket="Tür">{f.kind === "MF" ? "Ana akış" : f.kind === "AF" ? "Alternatif" : "İstisna"}</td>
              <td data-etiket="Adımlar">
                <ol>
                  {f.steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </td>
              <td data-etiket="Koşul">{f.condition || "—"}</td>
            </tr>
          ))}
        </Tablo>
      )}
      {(m.pairwise.parameters.length > 0 || m.pairwise.constraints.length > 0) && (
        <section aria-label="Pairwise modeli" data-testid="model-pairwise" className="model-bolum">
          <h3>Pairwise modeli</h3>
          <p className="kucuk soluk">Yalnız parametreler ve kısıtlar; satırlar modelce üretilmez.</p>
          <ul>
            {m.pairwise.parameters.map((p) => (
              <li key={p.name}>
                <strong>{p.name}</strong>: {p.values.join(", ")}
              </li>
            ))}
          </ul>
          {m.pairwise.constraints.length > 0 && (
            <ul className="kucuk">
              {m.pairwise.constraints.map((c) => (
                <li key={c}>Kısıt: {c}</li>
              ))}
            </ul>
          )}
        </section>
      )}
      {m.model_issues.length > 0 && (
        <section aria-label="Model sorunları" data-testid="model-sorunlari" className="model-bolum">
          <h3>Modelin kendi bulduğu sorunlar ({m.model_issues.length})</h3>
          <ul>
            {m.model_issues.map((s, i) => (
              <li key={i}>
                <Cip ton="uyari">{MODEL_SORUNU[s.kind] ?? s.kind}</Cip> {s.detail}
              </li>
            ))}
          </ul>
        </section>
      )}
      {m.open_questions.length > 0 && (
        <section aria-label="Açık sorular" data-testid="model-acik-sorular" className="model-bolum">
          <h3>Açık sorular ({m.open_questions.length})</h3>
          <ul className="case-atif-listesi">
            {m.open_questions.map((q) => (
              <li key={q.id}>
                <span className="mono ac-ref">{q.id}</span> {q.question} <span className="soluk kucuk">· Sahibi: {SAHIP[q.owner] ?? q.owner}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {m.assumptions.length > 0 && (
        <section aria-label="Varsayımlar" data-testid="model-varsayimlar" className="model-bolum">
          <h3>Varsayımlar ({m.assumptions.length})</h3>
          <ul className="case-atif-listesi">
            {m.assumptions.map((a) => (
              <li key={a.id}>
                <span className="mono ac-ref">{a.id}</span> {a.statement} <span className="soluk kucuk">· Doğrulayacak: {SAHIP[a.owner] ?? a.owner}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

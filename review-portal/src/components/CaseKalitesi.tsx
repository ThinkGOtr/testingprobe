// Kontrol Kulesi "Case kalitesi" bölümü (011 K21): kapsam, P8 case seti review dağılımı, P9 Agent Probe
// denetimi (kod kararı ve model kararı ayrı), tekrar oranı, hazır olma, teknik, asistan içerik kontrolü
// ve prompt sürümüne göre kırılım. AI yok; her sayı core'dan (GET /control-tower/case-quality).
//
// Grafik dili (§4.13, Grafikler.tsx ile aynı): tek seri, --chart-bar ince yatay çubuk, değer her satırda
// metin olarak yazılı (renk ya da çubuk boyu tek başına anlam taşımaz); kararlar renkle değil etiketle
// ayrılır. Hedefler ekip hedefidir, eşik/kapı gibi davranılmaz (kırmızı/yeşil yok).
import { useId, type ReactNode } from "react";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { ApiError } from "../api/http";
import type { CaseKalitesi as Veri, CaseKalitesiKarar } from "../api/types";
import { useGeciktirilmis, useVeri } from "../hooks";
import { yuzde } from "../lib/format";
import { CASE_HAZIRLIK } from "../lib/etiketler";
import { TEKNIK_ADI } from "../lib/tasarimModeli";
import { KaynakIpucu } from "./KaynakIpucu";
import { HataKutusu, Metrik, Olculmedi, Uyari } from "./ui";

/** Bu sayının altında oranlar yön göstermez; panelde n ile birlikte not düşülür (B11). */
export const KUCUK_ORNEKLEM = 20;

/** K22 / B13: karar terimleri tek sözlükte — "Kabul", "Düzeltme gerekli", "Engelle" (kod ENGELLE). */
export const KARAR_ETIKETI: Record<CaseKalitesiKarar, string> = {
  KABUL: "Kabul",
  DUZELTME_GEREKLI: "Düzeltme gerekli",
  ENGELLE: "Engelle",
};
const KARAR_SIRASI: CaseKalitesiKarar[] = ["KABUL", "DUZELTME_GEREKLI", "ENGELLE"];

/** K22 sözlüğü: hazır olma etiketleri; eski (v2) case readiness taşımaz. */
const HAZIRLIK_SIRASI: { anahtar: keyof Veri["readiness"]; etiket: string }[] = [
  { anahtar: "ready", etiket: CASE_HAZIRLIK.ready?.etiket ?? "Hazır" },
  { anahtar: "assumption_dependent", etiket: CASE_HAZIRLIK.assumption_dependent?.etiket ?? "Varsayıma bağlı" },
  { anahtar: "blocked", etiket: CASE_HAZIRLIK.blocked?.etiket ?? "Soru bekliyor" },
  { anahtar: "legacy", etiket: "Eski biçim" },
];

/** UX4 Bulgu 9: öncelik dağılımı satırları (P1 en yüksek). */
const ONCELIK_SIRASI: { anahtar: "P1" | "P2" | "P3" | "yok"; etiket: string }[] = [
  { anahtar: "P1", etiket: "P1 (en yüksek)" },
  { anahtar: "P2", etiket: "P2" },
  { anahtar: "P3", etiket: "P3" },
  { anahtar: "yok", etiket: "Öncelik yok" },
];

/** B5: teknik adları tek kaynaktan (tasarım modeli sözlüğü; CL dahil). */
const teknikAdi = (t: string): string | undefined => (TEKNIK_ADI as Record<string, string>)[t];

/** 404/405/501: eski core'da uç yok; bölüm sessizce gizlenir. */
function ucYok(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 404 || e.status === 405 || e.status === 501);
}

const oranMetni = (o: number | null) => (o === null ? null : yuzde(o));

interface Cubuk {
  etiket: string;
  n: number;
  ek?: string;
}

/**
 * Yatay dağılım çubukları: etiket | çubuk | "n (%pay)". Çubuk süs (aria-hidden), değer metin olarak okunur;
 * liste ekran okuyucuda satır satır gezilir. Çubuk boyu panel içindeki en büyük değere göre; yan yana
 * karşılaştırılan dağılımlar (P9 kod/model) ortak ölçek için `enBuyuk` verir (B9). Ek ad (ör. tekniğin
 * tam adı) etiketin altına sarılır: dar ekranda değer kesilmez (B10).
 */
export function DagilimCubuklari({ satirlar, etiket, testId, enBuyuk: ortak }: { satirlar: Cubuk[]; etiket: string; testId?: string; enBuyuk?: number }) {
  const toplam = satirlar.reduce((a, s) => a + s.n, 0);
  const enBuyuk = Math.max(1, ortak ?? 0, ...satirlar.map((s) => s.n));
  return (
    <ul className="ck-dagilim" aria-label={etiket} data-testid={testId}>
      {satirlar.map((s) => (
        <li key={s.etiket} className="ck-dagilim-satir">
          <span className="ck-dagilim-etiket">
            {s.etiket}
            {s.ek && <span className="ck-dagilim-ek soluk"> · {s.ek}</span>}
          </span>
          <span className="ck-dagilim-iz" aria-hidden="true">
            {s.n > 0 && <span className="ck-dagilim-cubuk" style={{ width: `${(s.n / enBuyuk) * 100}%` }} />}
          </span>
          <span className="ck-dagilim-deger">
            <strong>{s.n}</strong>
            {toplam > 0 && <span className="soluk"> ({yuzde(s.n / toplam)})</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function KucukOrneklem({ n, birim }: { n: number; birim: string }) {
  if (n === 0 || n >= KUCUK_ORNEKLEM) return null;
  return (
    <p className="kucuk soluk ck-orneklem" data-testid="kucuk-orneklem">
      n={n} {birim} · küçük örneklem: dağılım yön göstermez, karşılaştırma için erken.
    </p>
  );
}

/** B12: ekip hedefinin metriğinin güncel değeri (renksiz metin); bilinmeyen/ölçülmemiş metrik "ölçülmedi". */
export function hedefGuncelDegeri(k: Veri, metrik: string | undefined): string | null {
  if (!metrik) return null;
  let d: unknown = k;
  for (const p of metrik.split(".")) d = d && typeof d === "object" ? (d as Record<string, unknown>)[p] : undefined;
  if (d === undefined) return null;
  if (d === null || typeof d !== "number") return "ölçülmedi";
  // review.ortalama yüzde (0–100); diğer oranlar 0–1.
  if (metrik === "review.ortalama") return `%${d.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}`;
  // UX4 Bulgu 9: aynı metrik KPI kartında nasıl yuvarlanıyorsa hedef satırında da öyle (kart %92,
  // hedef satırı %91,7 diyordu). Kapsam oranları kartta tam sayı, tekrar oranı bir ondalık.
  return metrik.startsWith("kapsam.") ? yuzde(d) : yuzde(d, 1);
}

function Panel({ baslik, kaynak, children, testId }: { baslik: string; kaynak?: string; children: ReactNode; testId?: string }) {
  const id = useId();
  return (
    <section className="ck-panel" aria-labelledby={id} data-testid={testId}>
      <h3 id={id} className="ck-panel-baslik">
        {baslik} {kaynak !== undefined && <KaynakIpucu kaynak={kaynak} />}
      </h3>
      {children}
    </section>
  );
}

function Oran({ deger, bos = "ölçülmedi" }: { deger: number | null; bos?: string }) {
  return deger === null ? <Olculmedi metin={bos} /> : <>{yuzde(deger)}</>;
}

/** Kontrol Kulesi "Case kalitesi" bölümü; uç yoksa (eski core) hiç çizilmez. */
export function CaseKalitesiBolumu({ requirementId }: { requirementId?: string }) {
  const v = useVeri(() => api.caseKalitesi(requirementId), [requirementId]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true), 800);
  useOlay(sessiz, ["case.generated", "case.review", "case.audit", "case.decision", "case.updated", "case.reopen"]);
  const baslikId = useId();

  if (v.hata && !v.veri) {
    if (ucYok(v.hataNesnesi)) return null;
    return (
      <section className="kart" aria-labelledby={baslikId}>
        <div className="kart-baslik">
          <h2 id={baslikId}>Case kalitesi</h2>
        </div>
        <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
      </section>
    );
  }
  const k = v.veri;
  if (!k) return null;
  return <CaseKalitesiIcerik k={k} baslikId={baslikId} />;
}

/** Canlı: "Proje geneli · 0 gereksinim" (4 gereksinimde case var) — ölçüler yalnız v3 case'i olanı sayar. */
export function projeGeneliMetni(kapsam: Pick<Veri["kapsam"], "n_gereksinim" | "n_gereksinim_case" | "n_gereksinim_eski">): string {
  const n = kapsam.n_gereksinim;
  const eski = kapsam.n_gereksinim_eski ?? 0;
  const tum = kapsam.n_gereksinim_case ?? n;
  if (n > 0 && eski === 0) return `Proje geneli · ${n} gereksinim`;
  if (eski > 0) {
    const bas = n > 0 ? `Proje geneli · ${n} / ${tum} gereksinim ölçüldü` : `Proje geneli · case'i olan ${tum} gereksinim var ama ölçülemedi`;
    return `${bas} (${eski} gereksinimde yalnız eski biçimli case var; kapsam ölçüsüne girmez)`;
  }
  return "Proje geneli · henüz güncel case'i olan gereksinim yok (veri boş; yetki kısıtı değil)";
}

export function CaseKalitesiIcerik({ k, baslikId }: { k: Veri; baslikId: string }) {
  const ky = k.kaynaklar;
  const hazirVar = k.kapsam.hazir_gereksinim !== null || k.kapsam.hazir_oge !== null;
  const teknikler = Object.entries(k.teknik).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const ic = k.icerik_kontrolu;
  const caseToplam = HAZIRLIK_SIRASI.reduce((a, h) => a + k.readiness[h.anahtar], 0);
  // B9: kod ve model kararı yan yana; iki dağılım ortak ölçekle çizilir.
  const denetimOlcegi = Math.max(1, ...KARAR_SIRASI.flatMap((x) => [k.denetim.kod[x], k.denetim.model[x]]));
  return (
    <section className="kart case-kalitesi" aria-labelledby={baslikId} data-testid="case-kalitesi">
      <div className="kart-baslik">
        <h2 id={baslikId}>Case kalitesi</h2>
      </div>
      <p className="soluk kucuk">
        {k.requirement_id ? "Seçili gereksinim" : projeGeneliMetni(k.kapsam)}
        . Sayılar kayıtlardan hesaplanır; ölçülmemiş değer
        “ölçülmedi” yazılır.
      </p>

      {k.uyarilar.length > 0 && (
        <Uyari ton="bilgi">
          <ul className="duz-liste kucuk" data-testid="case-kalitesi-uyarilar">
            {k.uyarilar.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </Uyari>
      )}

      <div className="metrik-izgara ck-kpi" data-testid="case-kalitesi-kpi">
        <Metrik
          etiket={
            <span className="kpi-baslik">
              Gereksinim kapsamı <KaynakIpucu kaynak={ky.kapsam} />
            </span>
          }
          deger={<Oran deger={k.kapsam.gereksinim} />}
          alt={k.kapsam.kapsam_yontemi === "gereksinim_ortalamasi" ? "gereksinim ortalaması" : undefined}
        />
        <Metrik etiket="Öğe kapsamı" deger={<Oran deger={k.kapsam.oge} />} />
        <Metrik etiket="Negatif karar kapsamı" deger={<Oran deger={k.kapsam.negatif_karar} />} />
        <Metrik
          etiket={
            <span className="kpi-baslik">
              Hazır case kapsamı <KaynakIpucu kaynak={ky.hazir_kapsam} />
            </span>
          }
          deger={
            hazirVar ? (
              <span data-testid="hazir-kapsam">
                <Oran deger={k.kapsam.hazir_gereksinim} />
              </span>
            ) : (
              <span data-testid="hazir-kapsam">
                <Olculmedi />
              </span>
            )
          }
          alt={hazirVar ? <>öğe {k.kapsam.hazir_oge === null ? "ölçülmedi" : yuzde(k.kapsam.hazir_oge)}</> : undefined}
        />
        <Metrik
          etiket={
            <span className="kpi-baslik">
              Tekrar oranı <KaynakIpucu kaynak={ky.tekrar} />
            </span>
          }
          deger={<span data-testid="tekrar-orani">{k.tekrar.oran === null ? <Olculmedi /> : yuzde(k.tekrar.oran, 1)}</span>}
          alt={k.tekrar.case > 0 ? `${k.tekrar.oneri} birleştir/çıkar önerisi · ${k.tekrar.etkilenen_case}/${k.tekrar.case} case` : undefined}
        />
        {k.yetim_soru && (
          <Metrik
            etiket={
              <span className="kpi-baslik">
                Yetim açık soru <KaynakIpucu kaynak={ky.yetim_soru} />
              </span>
            }
            deger={<span data-testid="yetim-soru">{k.yetim_soru.toplam === 0 ? <Olculmedi /> : `${k.yetim_soru.yetim}/${k.yetim_soru.toplam}`}</span>}
            alt={k.yetim_soru.yetim > 0 ? `${k.yetim_soru.yetim_gereksinim} gereksinimde; PO yanıtı case'e dönmez` : undefined}
          />
        )}
      </div>

      <div className="ck-izgara">
        <Panel baslik="Case seti review (P8)" kaynak={ky.review} testId="ck-review">
          <p className="ck-ozet">
            Ortalama{" "}
            <strong data-testid="review-ortalama">
              {k.review.ortalama === null ? <Olculmedi /> : `%${k.review.ortalama.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}`}
            </strong>
            {k.review.ortalama_skor !== null && (
              <span className="soluk"> · {k.review.ortalama_skor.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}/12 madde uygun</span>
            )}
            <span className="soluk"> · {k.review.n} review</span>
          </p>
          {k.review.n > 0 && <DagilimCubuklari etiket="Review skor dağılımı (yüzde aralıkları)" satirlar={k.review.dagilim.map((d) => ({ etiket: d.aralik, n: d.n }))} />}
          <KucukOrneklem n={k.review.n} birim="review" />
          <p className="kucuk soluk">
            Ölçek: {k.review.olcek}.{k.review.bayat > 0 && ` ${k.review.bayat} review case seti değiştikten sonra kaldı (güncel değil).`}
          </p>
        </Panel>

        <Panel baslik="Agent Probe denetimi (P9)" kaynak={ky.denetim} testId="ck-denetim">
          <p className="ck-ozet">
            <strong>{k.denetim.n}</strong> denetim
            <span className="soluk">
              {" "}
              · {k.denetim.bekliyor} bekliyor · {k.denetim.hata} hata
            </span>
          </p>
          {k.denetim.n > 0 && (
            <div className="ck-yan-yana">
              <div>
                <h4 className="ck-alt-baslik">Kod kararı</h4>
                <DagilimCubuklari
                  etiket="Kod kararı dağılımı"
                  testId="denetim-kod"
                  enBuyuk={denetimOlcegi}
                  satirlar={KARAR_SIRASI.map((x) => ({ etiket: KARAR_ETIKETI[x], n: k.denetim.kod[x] }))}
                />
              </div>
              <div>
                <h4 className="ck-alt-baslik">Model kararı</h4>
                <DagilimCubuklari
                  etiket="Model kararı dağılımı"
                  testId="denetim-model"
                  enBuyuk={denetimOlcegi}
                  satirlar={KARAR_SIRASI.map((x) => ({ etiket: KARAR_ETIKETI[x], n: k.denetim.model[x] }))}
                />
              </div>
            </div>
          )}
          <KucukOrneklem n={k.denetim.n} birim="denetim" />
          <p className="kucuk soluk">Kod kararı, model kararının deterministik kurallarla sertleştirilmiş hâlidir; yayına esas olan odur.</p>
        </Panel>

        <Panel baslik="Hazır olma" kaynak={ky.readiness} testId="ck-hazirlik">
          {caseToplam === 0 ? (
            <p className="soluk kucuk">Güncel case yok.</p>
          ) : (
            <DagilimCubuklari etiket="Case hazır olma dağılımı" satirlar={HAZIRLIK_SIRASI.map((h) => ({ etiket: h.etiket, n: k.readiness[h.anahtar] }))} />
          )}
        </Panel>

        {k.oncelik && (
          <Panel baslik="Öncelik dağılımı" kaynak={ky.oncelik} testId="ck-oncelik">
            {ONCELIK_SIRASI.reduce((a, o) => a + k.oncelik![o.anahtar], 0) === 0 ? (
              <p className="soluk kucuk">Öncelik bilgisi olan case yok.</p>
            ) : (
              <DagilimCubuklari
                etiket="Case öncelik dağılımı"
                satirlar={ONCELIK_SIRASI.filter((o) => o.anahtar !== "yok" || k.oncelik!.yok > 0).map((o) => ({ etiket: o.etiket, n: k.oncelik![o.anahtar] }))}
              />
            )}
          </Panel>
        )}

        <Panel baslik="Teknik dağılımı" kaynak={ky.teknik} testId="ck-teknik">
          {teknikler.length === 0 ? (
            <p className="soluk kucuk">Teknik bilgisi olan case yok.</p>
          ) : (
            <>
              <DagilimCubuklari etiket="Test tasarım tekniği dağılımı" satirlar={teknikler.map(([t, n]) => ({ etiket: t, n, ek: teknikAdi(t) }))} />
              <p className="kucuk soluk">Bir case birden çok tekniğe sayılabilir.</p>
            </>
          )}
        </Panel>

        <Panel baslik="İçerik kontrolü (asistan)" kaynak={ky.icerik_kontrolu} testId="ck-icerik">
          {ic.n === 0 ? (
            <p className="soluk kucuk">Henüz içerik kontrolü kaydı yok.</p>
          ) : (
            <>
              <p className="ck-ozet">
                Engelleme oranı <strong data-testid="icerik-engel-orani">{oranMetni(ic.engel_orani) ?? <Olculmedi />}</strong>
                <span className="soluk"> · </span>
                uyarı oranı <strong data-testid="icerik-uyari-orani">{oranMetni(ic.uyari_orani) ?? <Olculmedi />}</strong>
              </p>
              <DagilimCubuklari
                etiket="İçerik kontrolü karar dağılımı"
                satirlar={[
                  { etiket: "Geçti", n: ic.gec },
                  { etiket: "Uyarı", n: ic.uyar },
                  { etiket: "Engelle", n: ic.engelle },
                ]}
              />
              <p className="kucuk soluk">
                {ic.n} kontrol
                {Object.keys(ic.yon).length > 0 &&
                  ` (${Object.entries(ic.yon)
                    .map(([y, n]) => `${y === "soru" ? "soru" : y === "cevap" ? "cevap" : y} ${n}`)
                    .join(", ")})`}
                ; proje geneli.
              </p>
            </>
          )}
          <KucukOrneklem n={ic.n} birim="kontrol" />
        </Panel>
      </div>

      <SurumTablosu k={k} />

      {k.hedefler.length > 0 && (
        <div className="ck-hedefler" data-testid="case-kalitesi-hedefler">
          <h3 className="ck-panel-baslik">
            Ekip hedefleri <KaynakIpucu kaynak={ky.hedefler} />
          </h3>
          <p className="kucuk soluk">Ekip hedefi, standart değil: eşik ya da kapı olarak uygulanmaz, değerler hedefe göre renklendirilmez.</p>
          <ul className="duz-liste kucuk">
            {k.hedefler.map((h) => {
              const guncel = hedefGuncelDegeri(k, h.metrik);
              // B12: "ekip hedefi, standart değil" başlık notunda; maddede tekrarlanmaz.
              const not = h.not && !/standart değil/i.test(h.not) ? h.not : null;
              return (
                <li key={`${h.ad}-${h.metrik ?? ""}`} data-testid="hedef-maddesi">
                  {h.ad}: hedef <strong>{h.hedef}</strong>
                  {guncel !== null && <span> · şu an {guncel}</span>}
                  {not && <span className="soluk"> ({not})</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function SurumTablosu({ k }: { k: Veri }) {
  if (k.surumler.length === 0) return null;
  return (
    <div className="ck-surumler">
      <h3 className="ck-panel-baslik">
        Prompt sürümüne göre <KaynakIpucu kaynak={k.kaynaklar.surumler} />
      </h3>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Prompt sürümüne göre case kalitesi tablosu">
        <table className="tablo tablo-sik" data-testid="case-kalitesi-surumler">
          <caption className="gorunmez">Prompt sürümüne göre case kalitesi</caption>
          <thead>
            <tr>
              <th scope="col">Sürüm</th>
              <th scope="col" className="sayi">
                Üretim
              </th>
              <th scope="col" className="sayi">
                Case
              </th>
              <th scope="col" className="sayi">
                Review ort.
              </th>
              <th scope="col" className="sayi">
                Kabul
              </th>
              <th scope="col" className="sayi">
                Düzeltme
              </th>
              <th scope="col" className="sayi">
                Engelle
              </th>
              <th scope="col" className="sayi">
                Tekrar
              </th>
            </tr>
          </thead>
          <tbody>
            {k.surumler.map((s) => (
              <tr key={s.surum}>
                <th scope="row" className="mono">
                  {s.surum}
                </th>
                <td className="sayi">{s.uretim}</td>
                <td className="sayi">{s.case}</td>
                <td className="sayi">
                  {s.review_ortalama === null ? (
                    "—"
                  ) : (
                    <>
                      %{s.review_ortalama.toLocaleString("tr-TR", { maximumFractionDigits: 1 })} <span className="soluk kucuk">(n={s.review_n})</span>
                    </>
                  )}
                </td>
                <td className="sayi">{s.kabul}</td>
                <td className="sayi">{s.duzeltme}</td>
                <td className="sayi">{s.engel}</td>
                <td className="sayi">{s.tekrar_orani === null ? "—" : yuzde(s.tekrar_orani, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="kucuk soluk">Kabul / Düzeltme / Engelle: Agent Probe denetiminin kod kararı. “—”: ölçülmedi.</p>
    </div>
  );
}

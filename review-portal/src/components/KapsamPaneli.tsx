import type { MouseEvent, ReactNode } from "react";
import type { CaseKapsamOzeti, CaseUretimOzeti, KapsamOrani } from "../api/types";
import { CASE_HAZIRLIK, CASE_TEKNIGI, NEGATIF_KARAR, SORU_SAHIBI, URETIM_TURU } from "../lib/etiketler";
import { yuzde } from "../lib/format";
import { HazirlikRozeti, TeknikRozeti } from "./CaseKarti";
import { BosDurum, Cip, HataKutusu, Kart, Metrik, Olculmedi, Uyari, Yukleniyor } from "./ui";

const TEKNIK_SIRASI = ["EP", "BVA", "DT", "ST", "PW", "UC", "EG"];
const HAZIRLIK_SIRASI = ["ready", "assumption_dependent", "blocked"];

/** Bilinen anahtarlar sabit sırada, bilinmeyenler sonda (core yeni değer eklerse kaybolmaz). */
const sirali = (dagilim: Record<string, number>, sira: string[]) => [
  ...sira.filter((k) => (dagilim[k] ?? 0) > 0),
  ...Object.keys(dagilim).filter((k) => !sira.includes(k) && dagilim[k] > 0),
];

/** Birden çok üretim varsa kimlikler çakışabilir (her üretim Q1'den başlar): satır üretimiyle etiketlenir. */
function uretimEtiketi(u: CaseUretimOzeti, cok: boolean): string {
  return cok ? ` · üretim ${u.uretim_no} (${URETIM_TURU[u.tur] ?? u.tur})` : "";
}

/** Derinleştirme üretimlerinin rozeti (011 P5/P6); ilk üretimde (tur "uretim") rozet yok. */
export function UretimTuruRozeti({ tur }: { tur: string }) {
  if (tur === "uretim") return null;
  return (
    <Cip ton="bilgi" title={tur === "negatif" || tur === "teknik" ? "Mevcut sete derinleştirmeyle eklenen taslaklar" : undefined}>
      {URETIM_TURU[tur] ?? tur}
    </Cip>
  );
}

/**
 * UX-13: matristeki karar etiketleri (negatif kararlar tablosu da aynı dili kullanır). Bilinçli
 * kapsam dışı nötrdür; yalnız gerekçesiz kapsanmayan öğe uyarıdır.
 */
export const MATRIS_KARARI: Record<string, string> = {
  tested: "Negatif case ile test edilir",
  covered_by: "Başka case kapsıyor",
  out_of_scope: "Kapsam dışı (gerekçeli)",
};

/** D3 hazır kapsam oranlarının etiketleri; bilinmeyen `hazir_*` anahtarı okunur biçime çevrilir. */
const HAZIR_ORAN_ETIKETI: Record<string, [string, string]> = {
  hazir_gereksinim_kapsami: ["Hazır case'lerle gereksinim kapsamı", "en az bir hazır case'in atıf yaptığı kabul kriterleri"],
  hazir_oge_kapsami: ["Hazır case'lerle öğe kapsamı", "en az bir hazır case'in çalıştırdığı kapsam öğeleri"],
};
const hazirOranEtiketi = (k: string): [string, string] => HAZIR_ORAN_ETIKETI[k] ?? [k.replace(/_/g, " ").replace(/^./, (c) => c.toLocaleUpperCase("tr-TR")), "hazır case'lerle"];

/** Dağılım rozetinden case listesi süzgecine (URL parametresi: `hazirlik` ya da `teknik`). */
export type DagilimFiltresi = Record<"hazirlik", string> | Record<"teknik", string>;

/** Dağılım öğesi: süzgeç bağlıysa düğme (tıklayınca liste o değere süzülür), değilse düz içerik. */
function DagilimOgesi({ children, etiket, sec }: { children: ReactNode; etiket: string; sec?: () => void }) {
  if (!sec) return <>{children}</>;
  return (
    <button type="button" className="dagilim-dugme" aria-label={etiket} title={etiket} onClick={sec}>
      {children}
    </button>
  );
}

const oranMetni = (x: KapsamOrani) => (x.oran === null ? <Olculmedi metin="hesaplanamadı" /> : yuzde(x.oran));
/** "kapsanan/toplam · açıklama" (core sayıları gelmediyse yalnız açıklama). */
const oranAlt = (x: KapsamOrani, aciklama: string) => (x.kapsanan !== null && x.toplam !== null ? `${x.kapsanan}/${x.toplam} · ${aciklama}` : aciklama);

/** Kapsayan case'e git: kart görünürse oraya kaydırır ve odaklar (filtrede gizliyse bağlantı yalnız adres gösterir). */
function caseyeGit(e: MouseEvent<HTMLAnchorElement>, id: string) {
  const el = document.getElementById(`case-${id}`);
  if (!el) return;
  e.preventDefault();
  el.scrollIntoView?.({ block: "start" });
  el.focus({ preventScroll: true });
}

/**
 * "Kapsam ve açık noktalar" paneli (011 §4.8): açık sorular, varsayımlar, kapsam matrisi (öğe →
 * kapsayan case'ler), kapsanmayanlar + gerekçe, negatif kapsam kararları, teknik ve hazır olma
 * dağılımı, oranlar. Veri `GET /requirements/{id}/case-summary`. Özet yoksa (eski şemalı case'ler,
 * eski core) anlamlı boş durum gösterir.
 */
export function KapsamPaneli({
  ozet,
  yukleniyor,
  hata,
  hataKaynagi,
  yenile,
  caseSayisi,
  eskiSema,
  baslangictaAcik = true,
  filtreSec,
}: {
  ozet: CaseKapsamOzeti | null | undefined;
  yukleniyor?: boolean;
  hata?: string | null;
  hataKaynagi?: unknown;
  yenile?: () => void;
  /** Gereksinimin case sayısı: boş durum metni buna göre seçilir. */
  caseSayisi: number;
  /** Gereksinimin tüm case'leri eski (v2) şemalı mı. */
  eskiSema?: boolean;
  /**
   * Ayrıntılar (açık sorular, varsayımlar, kapsanmayanlar, matris, kararlar) başta açık mı.
   * Varsayılan true (her şey açık); false: oranlar, dağılımlar ve uyarılar görünür, ayrıntılar kapalı.
   */
  baslangictaAcik?: boolean;
  /** Dağılım rozetleri case listesini süzer (verilmezse rozetler düz gösterilir). */
  filtreSec?: (f: DagilimFiltresi) => void;
}) {
  const baslik = "Kapsam ve açık noktalar";
  if (yukleniyor && ozet === undefined) {
    return (
      <Kart baslik={baslik}>
        <Yukleniyor />
      </Kart>
    );
  }
  if (hata && !ozet) {
    return (
      <Kart baslik={baslik}>
        <HataKutusu hata={hata} kaynak={hataKaynagi} yenile={yenile} />
      </Kart>
    );
  }
  // Özet (üst listeler) kayıtlı üretim var mı: eski şemalı case'lerde ve eski üretimlerde yoktur.
  const ozetVar = !!ozet && ozet.uretimler.some((u) => u.ozet_var !== false);
  const ozetYokMetni =
    caseSayisi === 0
      ? { baslik: "Henüz kapsam özeti yok.", metin: "Kapsam matrisi, açık sorular ve varsayımlar case üretiminden sonra burada görünür." }
      : eskiSema
        ? {
            baslik: "Bu gereksinimin case'leri eski şemayla üretildi; kapsam özeti yok.",
            metin:
              "Eski şemalı case'ler hazır sayılır ve olduğu gibi kalır. Açık sorular, varsayımlar ve kapsam öğeleri yeni şemayla yapılan üretimlerde oluşur.",
          }
        : {
            baslik: "Bu üretimin kapsam özeti kayıtlı değil.",
            metin: "Açık sorular, varsayımlar ve kapsam öğeleri bu üretim için saklanmamış; yalnızca kabul kriteri kapsamı hesaplanabilir.",
          };
  if (!ozet || (!ozetVar && ozet.kapsam_matrisi.length === 0)) {
    return (
      <Kart baslik={baslik}>
        <div data-testid="kapsam-bos">
          <BosDurum baslik={ozetYokMetni.baslik}>{ozetYokMetni.metin}</BosDurum>
        </div>
      </Kart>
    );
  }

  const cok = ozet.uretimler.length > 1;
  const sorular = ozet.uretimler.flatMap((u) => u.open_questions.map((q) => ({ ...q, u })));
  const varsayimlar = ozet.uretimler.flatMap((u) => u.assumptions.map((a) => ({ ...a, u })));
  const kararlar = ozet.uretimler.flatMap((u) => u.negative_coverage.map((k) => ({ ...k, u })));
  const gozlemler = ozet.uretimler.flatMap((u) => u.observations);
  const otomasyon = ozet.uretimler.flatMap((u) => u.automation_open_points);
  const bosluklar = ozet.uretimler.flatMap((u) => u.testability_gaps);
  const parametreler = ozet.uretimler.flatMap((u) => u.config_matrix.parameters);
  const kisitlar = ozet.uretimler.flatMap((u) => u.config_matrix.constraints);
  const teknikler = sirali(ozet.teknik_dagilimi, TEKNIK_SIRASI);
  const hazirliklar = sirali(ozet.readiness_dagilimi, HAZIRLIK_SIRASI);
  const hazirOranlar = Object.entries(ozet.oranlar).filter((e): e is [string, KapsamOrani] => e[0].includes("hazir") && !!e[1]);
  const hazirVar = ozet.kapsam_matrisi.some((s) => s.covered_by_ready !== undefined);
  const digerVar = gozlemler.length + otomasyon.length + bosluklar.length + parametreler.length + kisitlar.length > 0;

  return (
    <Kart baslik={baslik} className="kapsam-paneli">
      {!ozetVar && (
        <div data-testid="kapsam-bos">
          <Uyari ton="bilgi" baslik={ozetYokMetni.baslik}>
            {ozetYokMetni.metin}
          </Uyari>
        </div>
      )}
      {(cok || ozet.uretimler.some((u) => u.tur !== "uretim")) && (
        <section aria-label="Üretimler" data-testid="kapsam-uretimler">
          <h3>Üretimler ({ozet.uretimler.length})</h3>
          <ul className="satir-ogeler kapsam-cipler">
            {ozet.uretimler.map((u) => (
              <li key={u.uretim_no}>
                <span className="mono">Üretim {u.uretim_no}</span> <UretimTuruRozeti tur={u.tur} />
                {typeof u.case_sayisi === "number" && <span className="soluk kucuk"> · {u.case_sayisi} case</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="metrik-izgara" data-testid="kapsam-oranlar">
        <Metrik
          etiket="Gereksinim kapsamı"
          deger={oranMetni(ozet.oranlar.gereksinim_kapsami)}
          alt={oranAlt(ozet.oranlar.gereksinim_kapsami, "en az bir case'in atıf yaptığı kabul kriterleri")}
        />
        <Metrik etiket="Öğe kapsamı" deger={oranMetni(ozet.oranlar.oge_kapsami)} alt={oranAlt(ozet.oranlar.oge_kapsami, "en az bir case'in çalıştırdığı kapsam öğeleri")} />
        <Metrik
          etiket="Negatif karar kapsamı"
          deger={oranMetni(ozet.oranlar.negatif_karar_kapsami)}
          alt={oranAlt(ozet.oranlar.negatif_karar_kapsami, "kararı yazılmış geçersiz öğeler")}
        />
        {/* D3: hazır case'lerle kapsam (alan yoksa — eski core — gösterilmez). */}
        {hazirOranlar.map(([k, x]) => {
          const [etiket, aciklama] = hazirOranEtiketi(k);
          return <Metrik key={k} etiket={etiket} deger={oranMetni(x)} alt={oranAlt(x, aciklama)} />;
        })}
      </div>

      <div className="kapsam-dagilim">
        <div data-testid="kapsam-teknik-dagilimi">
          <h3>Teknik dağılımı</h3>
          {teknikler.length === 0 ? (
            <p className="soluk kucuk">Teknik bilgisi olan case yok.</p>
          ) : (
            <ul className="satir-ogeler kapsam-cipler">
              {teknikler.map((t) => (
                <li key={t}>
                  <DagilimOgesi
                    etiket={`${t}${CASE_TEKNIGI[t] ? ` (${CASE_TEKNIGI[t]})` : ""}: ${ozet.teknik_dagilimi[t]} case — listeyi bu tekniğe süz`}
                    sec={filtreSec && (() => filtreSec({ teknik: t }))}
                  >
                    <TeknikRozeti teknik={t} /> <span className="mono">{ozet.teknik_dagilimi[t]}</span>
                    <span className="gorunmez"> case</span>
                  </DagilimOgesi>
                  {!CASE_TEKNIGI[t] && <span className="soluk kucuk"> (bilinmeyen teknik)</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div data-testid="kapsam-hazirlik-dagilimi">
          <h3>Hazır olma dağılımı</h3>
          {hazirliklar.length === 0 ? (
            <p className="soluk kucuk">Hazır olma bilgisi olan case yok.</p>
          ) : (
            <ul className="satir-ogeler kapsam-cipler">
              {hazirliklar.map((h) => (
                <li key={h}>
                  <DagilimOgesi
                    etiket={`${CASE_HAZIRLIK[h]?.etiket ?? h}: ${ozet.readiness_dagilimi[h]} case — listeyi bu duruma süz`}
                    sec={filtreSec && (() => filtreSec({ hazirlik: h }))}
                  >
                    {CASE_HAZIRLIK[h] ? <HazirlikRozeti durum={h as never} /> : <Cip>{h}</Cip>} <span className="mono">{ozet.readiness_dagilimi[h]}</span>
                    <span className="gorunmez"> case</span>
                  </DagilimOgesi>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {ozet.uyarilar.length > 0 && (
        <div data-testid="kapsam-uyarilari">
          <Uyari baslik="Kapsam uyarıları">
            <ul>
              {ozet.uyarilar.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          </Uyari>
        </div>
      )}

      <AyrintiSarici acik={baslangictaAcik} ozet={`Ayrıntılar: açık sorular (${sorular.length}), varsayımlar (${varsayimlar.length}), kapsanmayanlar (${ozet.kapsanmayan.length}), kapsam matrisi`}>
      {ozetVar && (
        <>
      <section aria-label="Açık sorular" data-testid="kapsam-acik-sorular">
        <h3>Açık sorular ({sorular.length})</h3>
        {sorular.length === 0 ? (
          <p className="soluk kucuk">Açık soru yok.</p>
        ) : (
          <ul className="case-atif-listesi">
            {sorular.map((q) => (
              <li key={`${q.u.uretim_no}-${q.id}`}>
                <span className="mono ac-ref">{q.id}</span> {q.question}{" "}
                <span className="soluk kucuk">
                  · Sahibi: {SORU_SAHIBI[q.owner] ?? q.owner}
                  {uretimEtiketi(q.u, cok)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Varsayımlar" data-testid="kapsam-varsayimlar">
        <h3>Varsayımlar ({varsayimlar.length})</h3>
        {varsayimlar.length === 0 ? (
          <p className="soluk kucuk">Varsayım yok.</p>
        ) : (
          <ul className="case-atif-listesi">
            {varsayimlar.map((a) => (
              <li key={`${a.u.uretim_no}-${a.id}`}>
                <span className="mono ac-ref">{a.id}</span> {a.statement}{" "}
                <span className="soluk kucuk">
                  · Sahibi: {SORU_SAHIBI[a.owner] ?? a.owner}
                  {uretimEtiketi(a.u, cok)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

        </>
      )}

      <section aria-label="Kapsanmayanlar" data-testid="kapsam-kapsanmayanlar">
        <h3>Kapsanmayanlar ({ozet.kapsanmayan.length})</h3>
        {ozet.kapsanmayan.length === 0 ? (
          <p className="soluk kucuk">Her kabul kriteri ve kapsam öğesi en az bir case tarafından kapsanıyor.</p>
        ) : (
          <ul className="case-atif-listesi">
            {ozet.kapsanmayan.map((k) => (
              <li key={k.item}>
                <span className="mono ac-ref">{k.item}</span> {k.gerekce || <span className="hata-metin">Gerekçe yazılmamış.</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <details className="kapsam-ayrinti" open data-testid="kapsam-matrisi">
        <summary>Kapsam matrisi ({ozet.kapsam_matrisi.length} satır)</summary>
        {ozet.kapsam_matrisi.length === 0 ? (
          <p className="soluk kucuk">Kapsam matrisi boş.</p>
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Kapsam matrisi tablosu">
            <table className="tablo tablo-sik tablo-yigin">
              <caption className="gorunmez">Kapsam matrisi: kabul kriterleri ve kapsam öğeleri ile onları kapsayan case'ler</caption>
              <thead>
                <tr>
                  <th scope="col">Öğe</th>
                  <th scope="col">Tür</th>
                  <th scope="col">Tanım</th>
                  <th scope="col">Sınıf</th>
                  <th scope="col">Kapsayan case'ler</th>
                  <th scope="col">Gerekçe</th>
                </tr>
              </thead>
              <tbody>
                {ozet.kapsam_matrisi.map((s) => (
                  <tr key={`${s.tur}-${s.item}`}>
                    <td className="mono" data-etiket="Öğe">
                      {s.item}
                    </td>
                    <td data-etiket="Tür">{s.tur === "ac" ? "Kabul kriteri" : "Kapsam öğesi"}</td>
                    <td data-etiket="Tanım">{s.tanim}</td>
                    <td className={s.valid === null ? "bos-hucre" : undefined} data-etiket="Sınıf">
                      {s.valid === null ? "—" : s.valid ? "Geçerli" : "Geçersiz"}
                      {s.karar && (MATRIS_KARARI[s.karar] || NEGATIF_KARAR[s.karar]) && (
                        <span className="soluk kucuk"> · {MATRIS_KARARI[s.karar] ?? NEGATIF_KARAR[s.karar].etiket}</span>
                      )}
                    </td>
                    <td data-etiket="Kapsayan case'ler">
                      {s.kapsayanlar && s.kapsayanlar.length > 0 ? (
                        <ul className="satir-ogeler kapsam-cipler">
                          {s.kapsayanlar.map((c) => (
                            <li key={c.id}>
                              <a
                                className="mono"
                                href={`#case-${c.id}`}
                                title={c.title}
                                aria-label={`#${c.sira_no}${cok && c.uretim_no !== null ? ` (üretim ${c.uretim_no})` : ""}: ${c.title}`}
                                onClick={(e) => caseyeGit(e, c.id)}
                              >
                                #{c.sira_no}
                                {cok && c.uretim_no !== null && <span className="soluk kucuk">/{c.uretim_no}</span>}
                              </a>
                            </li>
                          ))}
                        </ul>
                      ) : s.covered_by.length > 0 ? (
                        <ul className="satir-ogeler kapsam-cipler">
                          {s.covered_by.map((n, i) => (
                            <li key={`${i}-${n}`} className="mono">
                              #{n}
                            </li>
                          ))}
                        </ul>
                      ) : s.karar === "out_of_scope" ? (
                        <Cip ton="notr">Kapsam dışı (gerekçeli)</Cip>
                      ) : s.gerekce ? (
                        <Cip ton="notr">Kapsanmıyor (gerekçeli)</Cip>
                      ) : (
                        <Cip ton="uyari">⚠ Kapsanmıyor</Cip>
                      )}
                      {hazirVar && s.covered_by.length > 0 && <HazirKapsayanlar siralar={s.covered_by_ready} />}
                    </td>
                    <td className={s.gerekce ? "kucuk" : "bos-hucre"} data-etiket="Gerekçe">
                      {s.gerekce ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>

      {ozetVar && (
      <details className="kapsam-ayrinti" data-testid="kapsam-negatif-kararlar">
        <summary>Negatif kapsam kararları ({kararlar.length})</summary>
        {kararlar.length === 0 ? (
          <p className="soluk kucuk">Negatif kapsam kararı yok.</p>
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Negatif kapsam kararları tablosu">
            <table className="tablo tablo-sik tablo-yigin">
              <caption className="gorunmez">Geçersiz kapsam öğeleri için verilen kararlar</caption>
              <thead>
                <tr>
                  <th scope="col">Öğe</th>
                  <th scope="col">Karar</th>
                  <th scope="col">Gerekçe</th>
                </tr>
              </thead>
              <tbody>
                {kararlar.map((k) => {
                  const n = NEGATIF_KARAR[k.decision] ?? { etiket: k.decision, ton: "notr" as const };
                  const e = { ...n, etiket: MATRIS_KARARI[k.decision] ?? n.etiket };
                  return (
                    <tr key={`${k.u.uretim_no}-${k.item}`}>
                      <td className="mono" data-etiket="Öğe">
                        {k.item}
                        {cok && <span className="soluk kucuk">{uretimEtiketi(k.u, cok)}</span>}
                      </td>
                      <td data-etiket="Karar">
                        <Cip ton={e.ton}>{e.etiket}</Cip>
                      </td>
                      <td data-etiket="Gerekçe">{k.rationale}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </details>
      )}

      {digerVar && (
        <details className="kapsam-ayrinti" data-testid="kapsam-diger">
          <summary>Gözlemler ve otomasyon notları ({gozlemler.length + otomasyon.length + bosluklar.length + parametreler.length + kisitlar.length})</summary>
          {gozlemler.length > 0 && (
            <section aria-label="Gözlemler" data-testid="kapsam-gozlemler">
              <h4>Gözlemler ({gozlemler.length})</h4>
              <p className="soluk kucuk">
                Gözlem — beklenen sonuç değildir. Benimsenmemiş standartların eşikleri ve platform notları burada yazılır; case'lerde
                doğrulanmaz.
              </p>
              <ul className="case-atif-listesi">
                {gozlemler.map((g, i) => (
                  <li key={`${i}-${g.note}`}>
                    {g.standard_ref ? <span className="mono ac-ref">{g.standard_ref}</span> : <span className="soluk kucuk">Standart atfı yok</span>} {g.note}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {(parametreler.length > 0 || kisitlar.length > 0) && (
            <section aria-label="Yapılandırma matrisi" data-testid="kapsam-yapilandirma">
              <h4>Yapılandırma matrisi</h4>
              <p className="soluk kucuk">Burada yalnız parametreler, değerleri ve kısıtlar yer alır; kombinasyon satırları PICT ile üretilir.</p>
              {parametreler.length > 0 && (
                <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Yapılandırma parametreleri tablosu">
                  <table className="tablo tablo-sik tablo-yigin">
                    <caption className="gorunmez">Yapılandırma parametreleri ve değerleri</caption>
                    <thead>
                      <tr>
                        <th scope="col">Parametre</th>
                        <th scope="col">Değerler</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parametreler.map((p, i) => (
                        <tr key={`p-${i}-${p.name}`}>
                          <td className="mono" data-etiket="Parametre">
                            {p.name}
                          </td>
                          <td data-etiket="Değerler">{p.values.join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {kisitlar.length > 0 && (
                <>
                  <h5 className="kucuk">Kısıtlar</h5>
                  <ul className="case-atif-listesi">
                    {kisitlar.map((k, i) => (
                      <li key={`k-${i}-${k}`} className="mono">
                        {k}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )}
          {bosluklar.length > 0 && (
            <section aria-label="Test edilebilirlik boşlukları" data-testid="kapsam-bosluklar">
              <h4>Test edilebilirlik boşlukları ({bosluklar.length})</h4>
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Test edilebilirlik boşlukları tablosu">
                <table className="tablo tablo-sik tablo-yigin">
                  <caption className="gorunmez">Test edilebilirlik boşlukları: kontrol ve eksik olan</caption>
                  <thead>
                    <tr>
                      <th scope="col">Kontrol</th>
                      <th scope="col">Eksik</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bosluklar.map((b, i) => (
                      <tr key={`${i}-${b.control}`}>
                        <td data-etiket="Kontrol">{b.control}</td>
                        <td className="mono" data-etiket="Eksik">
                          {b.missing}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {otomasyon.length > 0 && (
            <section aria-label="Otomasyon açık noktaları" data-testid="kapsam-otomasyon">
              <h4>Otomasyon açık noktaları ({otomasyon.length})</h4>
              <ul className="case-atif-listesi">
                {otomasyon.map((o, i) => (
                  <li key={`${i}-${o}`}>{o}</li>
                ))}
              </ul>
            </section>
          )}
        </details>
      )}
      </AyrintiSarici>
    </Kart>
  );
}

/** `baslangictaAcik` false ise ayrıntılar kapalı bir açılır bölümde; true ise olduğu gibi çizilir. */
function AyrintiSarici({ acik, ozet, children }: { acik: boolean; ozet: string; children: ReactNode }) {
  if (acik) return <>{children}</>;
  return (
    <details className="kapsam-ayrinti kapsam-ayrintilar" data-testid="kapsam-ayrintilar">
      <summary>{ozet}</summary>
      {children}
    </details>
  );
}

/** D3: satırı kapsayan hazır case'ler ("hazır case: 2, 5") ya da "hazır case yok" uyarısı. */
function HazirKapsayanlar({ siralar }: { siralar: number[] | undefined }) {
  if (siralar === undefined) return null;
  return siralar.length > 0 ? (
    <span className="soluk kucuk kapsam-hazir" data-testid="kapsam-hazir-case">
      hazır case: {siralar.join(", ")}
    </span>
  ) : (
    <span className="kapsam-hazir" data-testid="kapsam-hazir-case">
      <Cip ton="uyari" title="Bu öğeyi kapsayan case'lerin hiçbiri hazır değil: onaylanmadan kapsam sayılmaz.">
        ⚠ hazır case yok
      </Cip>
    </span>
  );
}

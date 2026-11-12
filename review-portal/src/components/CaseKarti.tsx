import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type TextareaHTMLAttributes } from "react";
import { api } from "../api/client";
import { caseKarariVerilebilir, GECIS_YOK, gecisVar, type CaseKarari } from "../api/sozlesme/durumMakinesi";
import { useKisiAdi, useOturum } from "../auth";
import {
  CASE_HAZIRLIKLARI,
  CASE_ONCELIKLERI,
  CASE_TEKNIKLERI,
  DOGRULAMA_NOKTALARI,
  TEST_SEVIYELERI,
  type AcikSoru,
  type CaseHazirlik,
  type CaseTeknigi,
  type RetNedeni,
  type TestCase,
  type TestCaseIcerik,
  type TestVerisi,
  type Varsayim,
} from "../api/types";
import { useIslem } from "../hooks";
import { atiflariCoz, caseEski, caseHazirlik, eskiIcerik, hataListesi, hazirlikSorunlari, kimlikListesi } from "../lib/caseV3";
import {
  CASE_DURUMU,
  CASE_HAZIRLIK,
  CASE_ONCELIGI,
  CASE_TEKNIGI,
  CASE_TURU,
  DOGRULAMA_NOKTASI,
  RET_NEDENI,
  RISK,
  SORU_SAHIBI,
  TEST_SEVIYESI,
} from "../lib/etiketler";
import { sure, tarih } from "../lib/format";
import { AtifPoDurumu, DuzeltmeKaynaklari, PoYanitOnerisi } from "./AcikSorular";
import { FarkGorunumu } from "./FarkGorunumu";
import { AlanHatasi, Cip, IslemDugmesi, ReplayRozeti, Uyari } from "./ui";

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
  const kisiAdi = useKisiAdi();
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
  // Şema v3 (011): eski case'te v3 blokları hiç çizilmez; hazır sayılır (K9).
  const eski = caseEski(tc);
  const hazirlik = caseHazirlik(tc);
  // K6: hazır olmayan ya da tutarlılık ihlali olan case onaylanamaz. Core `onay_engeli` approve'un
  // vereceği 422 metninin aynısıdır: varsa o gösterilir. Alan yoksa (eski core) içerikten türetilir.
  const onayEngeli = !verilebilir("approve")
    ? gecisYokNedeni("approve")
    : tc.onay_engeli
      ? `${tc.onay_engeli}. "Düzelt" ile giderin ya da reddedin.`
      : tc.onay_engeli === undefined && hazirlik !== "ready"
        ? `Hazır değil (${CASE_HAZIRLIK[hazirlik].etiket}): "Düzelt" ile hazır yapın ya da reddedin.`
        : tc.onay_engeli === undefined && !eski && tc.uyarilar && tc.uyarilar.length > 0
          ? 'İçerik uyarısı var: "Düzelt" ile giderin ya da reddedin.'
          : undefined;
  const hataAyrik = hataListesi(islem.hata);

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
    <article ref={kartRef} id={`case-${tc.id}`} tabIndex={-1} className={`case case-${tc.durum}`} aria-labelledby={`${id}-baslik`}>
      <header className="case-baslik">
        <div className="satir-ogeler">
          <span className="mono soluk">#{tc.sira_no}</span>
          <Cip ton={d.ton}>{d.etiket}</Cip>
          {!eski && <HazirlikRozeti durum={hazirlik} />}
          <Cip ton="notr">{CASE_TURU[tc.icerik.type] ?? tc.icerik.type}</Cip>
          {r && <Cip ton={r.ton}>{r.etiket}</Cip>}
          {tc.icerik.acceptance_criteria_refs.map((a) => (
            <span key={a} className="mono ac-ref">
              {a}
            </span>
          ))}
          {tc.kanal === "ide" && <Cip ton="notr" title="Claude Code (MCP submit_draft_cases) kanalından geldi">Claude Code</Cip>}
          <ReplayRozeti mode={tc.mode} />
          {eski && (
            <span className="soluk kucuk" data-testid="case-eski-sema" title="Bu case önceki şemayla üretildi: teknik, öncelik ve hazır olma bilgisi yok; hazır sayılır.">
              eski şema
            </span>
          )}
        </div>
        {tc.jira_test_key && <span className="mono">{tc.jira_test_key}</span>}
      </header>

      {mod === "duzenle" ? (
        <>
          {/* 011 K16: yanıtlanan sorunun PO yanıtı düzeltmede beklenen sonucun kaynağıdır. */}
          <DuzeltmeKaynaklari sorular={tc.acik_sorular} varsayimlar={tc.varsayimlar} />
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
        </>
      ) : (
        <>
          <h3 id={`${id}-baslik`} className="case-ad">
            {tc.icerik.title}
          </h3>
          {!eski && <CaseV3Ozeti tc={tc} hazirlik={hazirlik} />}
          {tc.icerik.preconditions.length > 0 && (
            <p className="kucuk">
              <strong>Ön koşul:</strong> {tc.icerik.preconditions.join(" · ")}
            </p>
          )}
          {!eski && <TestVerisiTablosu veriler={tc.icerik.test_data ?? []} baslik={tc.icerik.title} />}
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
                    <td className={s.expected ? undefined : "bos-hucre"} data-etiket="Beklenen">
                      {s.expected || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <strong>Beklenen sonuç:</strong>{" "}
            {tc.icerik.expected_result || <span className="soluk">— (henüz yazılamıyor: açık soru yanıtlanmalı)</span>}
          </p>
          {!eski && (tc.icerik.teardown?.length ?? 0) > 0 && (
            <div className="kucuk" data-testid="case-temizlik">
              <strong>Temizlik:</strong>
              <ol className="case-temizlik">
                {tc.icerik.teardown!.map((a, i) => (
                  <li key={`${i}-${a}`}>{a}</li>
                ))}
              </ol>
            </div>
          )}
        </>
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
          {tc.review_sure_ms !== null && ` · review ${sure(tc.review_sure_ms)}`}
          {tc.karar_veren && ` · ${kisiAdi(tc.karar_veren)}, ${tarih(tc.karar_zamani)}`}
          {tc.durum === "draft" && tc.karar && ` · taslağa alındı (önceki karar: ${KARAR_ADI[tc.karar]})`}
          {tc.ret_nedeni && tc.durum === "rejected" && ` · ret: ${RET_NEDENI[tc.ret_nedeni]}`}
          {tc.duzeltme_olcusu !== null && tc.karar === "edit" && ` · düzeltme ölçüsü ${tc.duzeltme_olcusu.toLocaleString("tr-TR")}`}
          {tc.karar === "edit" && <KucukDuzeltme tc={tc} />}
          {tc.durum === "draft" && tc.goruntulenme && ` · review ${tarih(tc.goruntulenme)} itibarıyla sürüyor`}
        </span>
        {/* Karar verilmiş case'te karar düğmeleri gösterilmez; yalnızca "Yeniden aç" (aşağıda). */}
        {mod === "goster" && !kilitli && !kararVerildi && (
          <div className="eylemler">
            <IslemDugmesi
              roller={["analyst"]}
              kucuk
              disabled={onayEngeli !== undefined}
              title={onayEngeli}
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
      {tc.fark && tc.fark.length > 0 && (
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
        <>
          <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{hataAyrik.baslik || "İşlem reddedildi:"}</AlanHatasi>
          <HataMaddeleri maddeler={hataAyrik.maddeler} />
        </>
      )}
    </article>
  );
}

/** Sunucunun (422) hata listesi: her sorun ayrı madde. Boşsa hiçbir şey çizmez. */
function HataMaddeleri({ maddeler }: { maddeler: string[] }) {
  if (maddeler.length === 0) return null;
  return (
    <ul className="kucuk hata-metin case-hata-listesi" data-testid="case-hata-listesi">
      {maddeler.map((m, i) => (
        <li key={`${i}-${m}`}>{m}</li>
      ))}
    </ul>
  );
}

/** Hazır olma rozeti: renk + işaret + metin (yalnız renge dayanmaz); ekran okuyucu için ön ek. */
export function HazirlikRozeti({ durum }: { durum: CaseHazirlik }) {
  const h = CASE_HAZIRLIK[durum] ?? CASE_HAZIRLIK.ready;
  return (
    <span className={`cip cip-${h.ton}`} title={h.aciklama} data-testid="case-hazirlik" data-durum={durum}>
      <span className="gorunmez">Hazır olma durumu: </span>
      {/* İşaret ayrı öğe değil, etiket metninin parçası (tek karakterlik öğe axe kontrastında ölçülemiyor). */}
      {`${h.isaret} ${h.etiket}`}
    </span>
  );
}

/** Teknik rozeti: kısaltma görünür; tam Türkçe ad `title`'da ve erişilebilir adda. */
export function TeknikRozeti({ teknik }: { teknik: string }) {
  const ad = CASE_TEKNIGI[teknik];
  return (
    <span className="cip cip-bilgi" title={ad}>
      {teknik}
      {ad && <span className="gorunmez"> ({ad})</span>}
    </span>
  );
}

function AtifListesi({ kayitlar, metin }: { kayitlar: (AcikSoru | Varsayim | { id: string })[]; metin: (k: AcikSoru | Varsayim) => string }) {
  return (
    <ul className="case-atif-listesi">
      {kayitlar.map((k) => (
        <li key={k.id}>
          <span className="mono ac-ref">{k.id}</span>{" "}
          {"owner" in k ? (
            <>
              {metin(k)} <span className="soluk kucuk">· Sahibi: {SORU_SAHIBI[k.owner] ?? k.owner}</span>
              <AtifPoDurumu kayit={k} />
            </>
          ) : (
            <span className="soluk">metni bu yanıtta yok (Kapsam ve açık noktalar paneline bakın)</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** v3 blokları: öncelik + teknik rozetleri, özellikler ve atıf yapılan açık sorular / varsayımlar. */
function CaseV3Ozeti({ tc, hazirlik }: { tc: TestCase; hazirlik: CaseHazirlik }) {
  const i = tc.icerik;
  const oncelik = i.priority ? CASE_ONCELIGI[i.priority] : undefined;
  const sorular = atiflariCoz(i.open_question_refs, tc.acik_sorular);
  const varsayimlar = atiflariCoz(i.assumption_refs, tc.varsayimlar);
  return (
    <div className="case-v3" data-testid="case-v3">
      <div className="satir-ogeler">
        {oncelik && (
          <span className={`cip cip-${oncelik.ton}`} title={oncelik.aciklama} data-testid="case-oncelik">
            {oncelik.etiket}
            <span className="gorunmez"> ({oncelik.aciklama})</span>
          </span>
        )}
        {(i.technique?.length ?? 0) > 0 && (
          <span className="satir-ogeler" role="group" aria-label="Test tasarım teknikleri">
            {i.technique!.map((t) => (
              <TeknikRozeti key={t} teknik={t} />
            ))}
          </span>
        )}
      </div>
      <dl className="case-ozellik kucuk">
        {i.priority_rationale && (
          <div>
            <dt>Öncelik gerekçesi</dt>
            <dd>{i.priority_rationale}</dd>
          </div>
        )}
        {(i.covers?.length ?? 0) > 0 && (
          <div>
            <dt>Kapsadığı öğeler</dt>
            <dd className="satir-ogeler">
              {i.covers!.map((c) => (
                <span key={c} className="mono ac-ref">
                  {c}
                </span>
              ))}
            </dd>
          </div>
        )}
        {i.verification_point && (
          <div>
            <dt>Doğrulama noktası</dt>
            <dd>{DOGRULAMA_NOKTASI[i.verification_point] ?? i.verification_point}</dd>
          </div>
        )}
        {i.test_level && (
          <div>
            <dt>Test seviyesi</dt>
            <dd>{TEST_SEVIYESI[i.test_level] ?? i.test_level}</dd>
          </div>
        )}
        {(i.platform || i.requires_real_device) && (
          <div>
            <dt>Platform</dt>
            <dd>
              {i.platform}
              {i.platform && i.requires_real_device && " · "}
              {i.requires_real_device && (
                <Cip ton="uyari" title="Bu case emülatör/simülatörde değil, gerçek cihazda koşulmalı">
                  Gerçek cihaz gerekir
                </Cip>
              )}
            </dd>
          </div>
        )}
        {(i.standard_refs?.length ?? 0) > 0 && (
          <div>
            <dt>Standart atıfları</dt>
            <dd>{i.standard_refs!.join(" · ")}</dd>
          </div>
        )}
      </dl>
      <PoYanitOnerisi tc={tc} />
      {sorular.length > 0 && (
        <div data-testid="case-acik-sorular">
          <Uyari baslik={hazirlik === "blocked" ? "Açık sorular (yanıtlanmadan bu case hazır olamaz)" : "Açık sorular"}>
            <AtifListesi kayitlar={sorular} metin={(k) => (k as AcikSoru).question} />
          </Uyari>
        </div>
      )}
      {varsayimlar.length > 0 && (
        <div data-testid="case-varsayimlar">
          <Uyari ton="bilgi" baslik="Dayandığı varsayımlar (doğrulanmadan onaylanamaz)">
            <AtifListesi kayitlar={varsayimlar} metin={(k) => (k as Varsayim).statement} />
          </Uyari>
        </div>
      )}
    </div>
  );
}

/**
 * Test verisi tablosu. Değer güvenilmeyen metindir: yalnız metin düğümü olarak (`<code>`) yazılır,
 * HTML olarak işlenmez. Saldırı verisi "güvenlik testi girdisi" olarak işaretlenir.
 */
function TestVerisiTablosu({ veriler, baslik }: { veriler: TestVerisi[]; baslik: string }) {
  if (veriler.length === 0) return null;
  return (
    <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`Test verisi: ${baslik}`} data-testid="case-test-verisi">
      <table className="tablo tablo-sik tablo-yigin">
        <caption className="gorunmez">Test verisi</caption>
        <thead>
          <tr>
            <th scope="col">Veri</th>
            <th scope="col">Değer</th>
            <th scope="col">Kapsam öğesi</th>
            <th scope="col">İşaret</th>
          </tr>
        </thead>
        <tbody>
          {veriler.map((v, i) => (
            <tr key={`${i}-${v.name}`}>
              <td className="mono" data-etiket="Veri">
                {v.name}
              </td>
              <td data-etiket="Değer">
                <code className="veri-deger">{v.value}</code>
              </td>
              <td className={`mono${v.class ? "" : " bos-hucre"}`} data-etiket="Kapsam öğesi">
                {v.class ?? "—"}
              </td>
              <td data-etiket="İşaret">
                {v.is_attack_payload && (
                  <Cip ton="uyari" title="Saldırı verisi: yalnız test girdisi olarak kullanılır; düz metin olarak gösterilir, çalıştırılmaz.">
                    ⚠ Güvenlik testi girdisi
                  </Cip>
                )}
                {!v.synthetic && <Cip ton="hata">Sentetik değil</Cip>}
                {!v.is_attack_payload && v.synthetic && <span className="soluk kucuk">sentetik</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
  const [uyarilar, setUyarilar] = useState<string[]>([]);
  // §12: beklenen sonuç metni değiştiyse "anlamca değişti mi?" kararını insan verir (zorunlu).
  const [anlamDegisti, setAnlamDegisti] = useState<"evet" | "hayir" | "">("");
  const id = useId();
  const beklenenDegisti = icerik.expected_result.trim() !== ilk.expected_result.trim();
  // Şema v3 (011): eski case yalnız eski alan kümesiyle düzenlenir (K9); v3 alanları hiç çizilmez/gönderilmez.
  const v3 = !eskiIcerik(ilk);

  const listeMetni = (l: string[]) => l.join("\n");
  const listeyeCevir = (m: string) =>
    m
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  const [onKosulMetni, setOnKosulMetni] = useState(() => listeMetni(ilk.preconditions));
  const [acMetni, setAcMetni] = useState(() => ilk.acceptance_criteria_refs.join(", "));
  const [kapsamMetni, setKapsamMetni] = useState(() => (ilk.covers ?? []).join(", "));
  const [varsayimMetni, setVarsayimMetni] = useState(() => (ilk.assumption_refs ?? []).join(", "));
  const [soruMetni, setSoruMetni] = useState(() => (ilk.open_question_refs ?? []).join(", "));
  const [temizlikMetni, setTemizlikMetni] = useState(() => listeMetni(ilk.teardown ?? []));

  const adimGuncelle = (i: number, alan: "action" | "data" | "expected", deger: string) =>
    setIcerik((c) => ({
      ...c,
      steps: c.steps.map((s, j) => (j === i ? { ...s, [alan]: alan === "data" && deger === "" ? null : deger } : s)),
    }));
  const veriGuncelle = (i: number, ek: Partial<TestVerisi>) =>
    setIcerik((c) => ({ ...c, test_data: (c.test_data ?? []).map((v, j) => (j === i ? { ...v, ...ek } : v)) }));
  const teknikDegistir = (t: CaseTeknigi) =>
    setIcerik((c) => {
      const mevcut = c.technique ?? [];
      return { ...c, technique: mevcut.includes(t) ? mevcut.filter((x) => x !== t) : CASE_TEKNIKLERI.filter((x) => x === t || mevcut.includes(x)) };
    });

  /** Formdaki güncel değerlerden gönderilecek içerik (v3 alanları yalnız v3 case'te). */
  const sonIcerik = (): TestCaseIcerik => ({
    ...icerik,
    preconditions: listeyeCevir(onKosulMetni),
    steps: icerik.steps.map((s, i) => ({ ...s, id: `S${i + 1}` })),
    ...(v3
      ? {
          covers: kimlikListesi(kapsamMetni),
          assumption_refs: kimlikListesi(varsayimMetni).map((x) => x.toUpperCase()),
          open_question_refs: kimlikListesi(soruMetni).map((x) => x.toUpperCase()),
          teardown: listeyeCevir(temizlikMetni),
          test_data: (icerik.test_data ?? []).map((v) => ({ ...v, name: v.name.trim(), class: v.class?.trim() || null })),
        }
      : {}),
  });
  // Hazır olma kuralı (§4.2 kural 4–5): seçilen duruma göre eksikler anında gösterilir.
  const hazirlikEksikleri = v3 ? hazirlikSorunlari(sonIcerik()) : [];
  const atifVar = v3 && (kimlikListesi(varsayimMetni).length > 0 || kimlikListesi(soruMetni).length > 0);

  function gonder(e: FormEvent) {
    e.preventDefault();
    const son = sonIcerik();
    if (!son.title.trim()) return setUyarilar(["Başlık boş olamaz."]);
    if (son.title.length > 120) return setUyarilar(["Başlık en fazla 120 karakter."]);
    if (!v3) {
      if (son.steps.length === 0 || son.steps.some((s) => !s.action.trim() || !s.expected.trim())) {
        return setUyarilar(["Her adımın eylemi ve beklenen sonucu dolu olmalı."]);
      }
      if (!son.expected_result.trim()) return setUyarilar(["Beklenen sonuç boş olamaz."]);
    } else {
      if (son.steps.length === 0 || son.steps.some((s) => !s.action.trim())) return setUyarilar(["Her adımın eylemi dolu olmalı."]);
      if ((son.technique ?? []).length === 0) return setUyarilar(["En az bir test tasarım tekniği seçilmeli."]);
      if ((son.covers ?? []).length === 0) return setUyarilar(["En az bir kapsam öğesi gerekir (ör. EP-V1)."]);
      if ((son.test_data ?? []).some((v) => !v.name)) return setUyarilar(["Her test verisinin adı dolu olmalı."]);
      // Düzeltme case'i onaylar (core: draft → approved); hazır olmayan içerik kaydedilemez (K6).
      if (son.readiness !== "ready") {
        return setUyarilar([
          `Düzeltme case'i onaylar; durum "${CASE_HAZIRLIK[son.readiness ?? "ready"].etiket}" iken kaydedilemez. Soru yanıtlandıysa ya da varsayım doğrulandıysa durumu "Hazır" yapın; değilse case'i reddedin ya da taslakta bırakın.`,
        ]);
      }
      const eksikler = hazirlikSorunlari(son);
      if (eksikler.length) return setUyarilar(eksikler);
    }
    const acRefleri = acMetni
      .split(/[,\s]+/)
      .map((x) => x.trim().toUpperCase())
      .filter(Boolean);
    if (acRefleri.length === 0) return setUyarilar(["En az bir kabul kriteri atfı gerekir (ör. AC1)."]);
    if (beklenenDegisti && !anlamDegisti) return setUyarilar(["Beklenen sonuç anlamca değişti mi? Evet ya da Hayır seçin."]);
    setUyarilar([]);
    kaydet(
      { ...son, acceptance_criteria_refs: [...new Set(acRefleri)] },
      // Metin değişmediyse anlam da değişmemiştir; değiştiyse insanın beyanı gönderilir.
      beklenenDegisti ? anlamDegisti === "evet" : false,
    );
  }

  const sunucuHatasi = hataListesi(hata);

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
            {(v3 ? (["positive", "negative", "boundary", "authorization", "integration"] as const) : (["positive", "negative", "boundary"] as const)).map((k) => (
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
      {v3 && (
        <>
          <div className="case-duzenle-ozellik">
            <div className="alan">
              <label htmlFor={`${id}-oncelik`}>Öncelik</label>
              <select
                id={`${id}-oncelik`}
                value={icerik.priority ?? "P2"}
                onChange={(e) => setIcerik({ ...icerik, priority: e.target.value as TestCaseIcerik["priority"] })}
              >
                {CASE_ONCELIKLERI.map((k) => (
                  <option key={k} value={k}>
                    {CASE_ONCELIGI[k].aciklama}
                  </option>
                ))}
              </select>
            </div>
            <div className="alan">
              <label htmlFor={`${id}-dogrulama`}>Doğrulama noktası</label>
              <select
                id={`${id}-dogrulama`}
                value={icerik.verification_point ?? "other"}
                onChange={(e) => setIcerik({ ...icerik, verification_point: e.target.value as TestCaseIcerik["verification_point"] })}
              >
                {DOGRULAMA_NOKTALARI.map((k) => (
                  <option key={k} value={k}>
                    {DOGRULAMA_NOKTASI[k]}
                  </option>
                ))}
              </select>
            </div>
            <div className="alan">
              <label htmlFor={`${id}-seviye`}>Test seviyesi</label>
              <select
                id={`${id}-seviye`}
                value={icerik.test_level ?? ""}
                onChange={(e) => setIcerik({ ...icerik, test_level: e.target.value || null })}
              >
                <option value="">Belirtilmedi</option>
                {TEST_SEVIYELERI.map((k) => (
                  <option key={k} value={k}>
                    {TEST_SEVIYESI[k]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="alan">
            <label htmlFor={`${id}-oncelik-gerekce`}>Öncelik gerekçesi</label>
            <OtoMetin
              id={`${id}-oncelik-gerekce`}
              maxLength={300}
              value={icerik.priority_rationale ?? ""}
              onChange={(e) => setIcerik({ ...icerik, priority_rationale: e.target.value })}
            />
          </div>
          <fieldset className="alan">
            <legend>Test tasarım teknikleri</legend>
            <div className="satir-ogeler">
              {CASE_TEKNIKLERI.map((t) => (
                <label key={t}>
                  <input type="checkbox" checked={(icerik.technique ?? []).includes(t)} onChange={() => teknikDegistir(t)} /> {t}{" "}
                  <span className="soluk kucuk">({CASE_TEKNIGI[t]})</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="alan">
            <label htmlFor={`${id}-kapsam`}>Kapsadığı öğeler</label>
            <input
              id={`${id}-kapsam`}
              className="mono"
              value={kapsamMetni}
              placeholder="EP-V1, BV-2"
              aria-describedby={`${id}-kapsam-ipucu`}
              onChange={(e) => setKapsamMetni(e.target.value)}
            />
            <span id={`${id}-kapsam-ipucu`} className="soluk kucuk">
              Virgülle ayırın. Kimlik öneki seçili teknikle uyumlu olmalı (EP → EP-, BVA → BV-, DT → DT-, ST → ST-, PW → PW-, UC → UC-, EG → EG-);
              tanımsız öğe sunucuda reddedilir.
            </span>
          </div>
          <fieldset className="alan" data-testid="hazirlik-alani">
            <legend>Hazır olma durumu</legend>
            <div className="case-duzenle-ozellik">
              <div className="alan">
                <label htmlFor={`${id}-hazirlik`}>Durum</label>
                <select
                  id={`${id}-hazirlik`}
                  value={icerik.readiness ?? "ready"}
                  aria-describedby={`${id}-hazirlik-ipucu`}
                  onChange={(e) => setIcerik({ ...icerik, readiness: e.target.value as CaseHazirlik })}
                >
                  {CASE_HAZIRLIKLARI.map((k) => (
                    <option key={k} value={k}>
                      {CASE_HAZIRLIK[k].etiket}
                    </option>
                  ))}
                </select>
              </div>
              <div className="alan">
                <label htmlFor={`${id}-varsayim`}>Varsayım atıfları</label>
                <input id={`${id}-varsayim`} className="mono" value={varsayimMetni} placeholder="A1" onChange={(e) => setVarsayimMetni(e.target.value)} />
              </div>
              <div className="alan">
                <label htmlFor={`${id}-soru`}>Açık soru atıfları</label>
                <input id={`${id}-soru`} className="mono" value={soruMetni} placeholder="Q1" onChange={(e) => setSoruMetni(e.target.value)} />
              </div>
            </div>
            <p id={`${id}-hazirlik-ipucu`} className="soluk kucuk">
              Düzeltme case'i onaylar; yalnız "Hazır" case kaydedilebilir. Hazır: açık soru ve varsayım atfı yok, beklenen sonuç ve tüm adım
              beklenenleri dolu. Soru yanıtlanmadıysa ya da varsayım doğrulanmadıysa case'i reddedin ya da taslakta bırakın.
            </p>
            {(icerik.readiness !== "ready" || atifVar) && (
              <button
                type="button"
                className="dugme dugme-ikincil dugme-kucuk"
                onClick={() => {
                  setIcerik((c) => ({ ...c, readiness: "ready" }));
                  setVarsayimMetni("");
                  setSoruMetni("");
                }}
              >
                Hazır yap: atıfları boşalt
              </button>
            )}
            <div role="status" data-testid="hazirlik-eksikleri">
              {icerik.readiness !== "ready" ? (
                <Uyari baslik={`Durum "${CASE_HAZIRLIK[icerik.readiness ?? "ready"].etiket}": bu hâliyle kaydedilemez`}>
                  Case'i hazır yapmak için: durumu "Hazır" seçin, açık soru ve varsayım atıflarını boşaltın, beklenen sonucu ve tüm adım
                  beklenenlerini yazın. ("Hazır yap" düğmesi durumu ve atıfları ayarlar; beklenenleri siz yazarsınız.)
                </Uyari>
              ) : hazirlikEksikleri.length > 0 ? (
                <Uyari baslik={'"Hazır" olarak kaydetmek için'}>
                  <ul>
                    {hazirlikEksikleri.map((m) => (
                      <li key={m}>{m}</li>
                    ))}
                  </ul>
                </Uyari>
              ) : null}
            </div>
          </fieldset>
        </>
      )}
      <div className="alan">
        <label htmlFor={`${id}-onkosul`}>Ön koşullar (her satır bir ön koşul)</label>
        <OtoMetin id={`${id}-onkosul`} value={onKosulMetni} onChange={(e) => setOnKosulMetni(e.target.value)} />
      </div>
      {v3 && (
        <fieldset className="alan">
          <legend>Test verisi</legend>
          <p className="soluk kucuk">
            Yalnız sentetik veri. Güvenlik testi girdisi (saldırı verisi) yalnız burada yazılır; adımlarda verinin adıyla anılır.
          </p>
          {(icerik.test_data ?? []).map((v, i) => (
            <div key={i} className="veri-duzenle">
              <label className="gorunmez" htmlFor={`${id}-v${i}-ad`}>{`Veri ${i + 1} adı`}</label>
              <input id={`${id}-v${i}-ad`} className="mono" placeholder="Ad" maxLength={60} value={v.name} onChange={(e) => veriGuncelle(i, { name: e.target.value })} />
              <label className="gorunmez" htmlFor={`${id}-v${i}-deger`}>{`Veri ${i + 1} değeri`}</label>
              <OtoMetin
                id={`${id}-v${i}-deger`}
                className="oto-metin mono"
                placeholder="Değer"
                maxLength={2000}
                spellCheck={false}
                value={v.value}
                onChange={(e) => veriGuncelle(i, { value: e.target.value })}
              />
              <label className="gorunmez" htmlFor={`${id}-v${i}-sinif`}>{`Veri ${i + 1} kapsam öğesi`}</label>
              <input
                id={`${id}-v${i}-sinif`}
                className="mono"
                placeholder="Kapsam öğesi"
                value={v.class ?? ""}
                onChange={(e) => veriGuncelle(i, { class: e.target.value === "" ? null : e.target.value })}
              />
              <span className="veri-duzenle-isaret">
                <label>
                  <input type="checkbox" checked={v.synthetic} onChange={(e) => veriGuncelle(i, { synthetic: e.target.checked })} /> Sentetik
                </label>
                <label>
                  <input type="checkbox" checked={v.is_attack_payload} onChange={(e) => veriGuncelle(i, { is_attack_payload: e.target.checked })} /> Güvenlik
                  testi girdisi
                </label>
              </span>
              <button
                type="button"
                className="dugme dugme-hayalet dugme-kucuk"
                aria-label={`Veri ${i + 1} sil${v.name ? ` (${v.name})` : ""}`}
                onClick={() => setIcerik((c) => ({ ...c, test_data: (c.test_data ?? []).filter((_, j) => j !== i) }))}
              >
                Sil
              </button>
            </div>
          ))}
          <button
            type="button"
            className="dugme dugme-ikincil dugme-kucuk"
            onClick={() =>
              setIcerik((c) => ({ ...c, test_data: [...(c.test_data ?? []), { name: "", value: "", class: null, synthetic: true, is_attack_payload: false }] }))
            }
          >
            Veri ekle
          </button>
        </fieldset>
      )}
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
      {v3 && (
        <div className="alan">
          <label htmlFor={`${id}-temizlik`}>Temizlik adımları (her satır bir adım)</label>
          <OtoMetin id={`${id}-temizlik`} value={temizlikMetni} onChange={(e) => setTemizlikMetni(e.target.value)} />
        </div>
      )}
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
      {uyarilar.length > 0 ? (
        <>
          <AlanHatasi>{uyarilar.length === 1 ? uyarilar[0] : "Kaydetmeden önce düzeltin:"}</AlanHatasi>
          <HataMaddeleri maddeler={uyarilar.length === 1 ? [] : uyarilar} />
        </>
      ) : hata ? (
        <>
          <AlanHatasi asistan={{ hata, kaynak: hataKaynagi }}>{sunucuHatasi.baslik || "Sunucu düzeltmeyi reddetti:"}</AlanHatasi>
          <HataMaddeleri maddeler={sunucuHatasi.maddeler} />
        </>
      ) : null}
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

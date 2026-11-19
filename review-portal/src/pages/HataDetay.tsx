import { BaskaProjedeKayit } from "../components/BaskaProjedeKayit";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ARIA_KAYNAKLARI } from "../api/uyumTriage";
import { useOlay } from "../api/events";
import { useBugKisitli, useIzin } from "../auth";
import { BUG_KISITLI_METNI } from "../lib/yetki";
import type { BugTaslagi, HataAnalizi, LocatorOnarimi, LocatorProbeSonucu, SaglikSonucu, SaglikUcu, TriageKaniti } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { Baglanti, BosDurum, Cip, HataKutusu, KayitHatasi, IslemDugmesi, Kart, ReplayRozeti, Uyari, Yukleniyor } from "../components/ui";
import { DurumCipi, EylemCubugu, Kimlik, MetaIzgara, MetaSatiri } from "../components/tasarim";
import { DetaySayfasi, OzetKarti, type DetaySekmesi } from "../components/DetaySayfasi";
import "../stiller/detay-kosu-hata.css";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { INSAN_SINIFLARI, islerimApi } from "../api/islerim";
import { altTurEtiketi, HATA_SINIFI, sinyalBasligi, testAdiGoster, TRIAGE_ALT_TUR, type Ton } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { kisaKosuAdi } from "./Kosular";
import { PlatformRozeti } from "../components/Platform";
import { DepoCipi } from "../components/Depo";
import { EkranGoruntusuKaniti, SayfaKaynagiGoruntuleyici } from "../components/SayfaKaynagi";
import { PLATFORM_ETIKETI, uygulamaPlatformuMu } from "../lib/platform";

/** 009: uygulama testinin kimlik onarımı (hata anı sayfa kaynağı); rol/ad/url_path boştur. */
export function sayfaKaynagiOnerisiMi(o: Pick<LocatorOnarimi, "kaynak">): boolean {
  return o.kaynak === "sayfa_kaynagi";
}

const ONARIM_DURUMU: Record<LocatorOnarimi["durum"], { etiket: string; ton: Ton }> = {
  proposed: { etiket: "Önerildi", ton: "notr" },
  checking: { etiket: "Kontrol ediliyor", ton: "bilgi" },
  pr_open: { etiket: "PR açık", ton: "bilgi" },
  merged: { etiket: "Birleşti", ton: "basari" },
  rejected: { etiket: "Reddedildi", ton: "notr" },
  failed: { etiket: "Başarısız", ton: "hata" },
};

const SHA_ESLESMESI: Record<NonNullable<LocatorProbeSonucu["sha_eslesmesi"]>, { etiket: string; ton: Ton }> = {
  eslesiyor: { etiket: "commit eşleşiyor", ton: "basari" },
  farkli: { etiket: "commit farklı", ton: "hata" },
  dogrulanamadi: { etiket: "commit doğrulanamadı", ton: "uyari" },
};

/** Test adının kısa hâli: "@etiket"ler atılır, " · " öncesi (ör. "TPD-1 C10"); ayraç yoksa ilk 48 karakter. */
export function testKisaAdi(ad: string | null | undefined): string {
  const temiz = (ad ?? "").replace(/\s*@\S+/g, "").trim();
  const bas = temiz.split(" · ")[0].trim();
  if (!bas) return "Hata";
  return bas.length > 48 ? `${bas.slice(0, 47)}…` : bas;
}

/** Karar kaynağı: deterministik kural (adıyla), AI yorumu (yalnızca kural eşleşmediyse) ya da insan (IA-16). */
export function kararKaynagiMetni(h: Pick<HataAnalizi, "karar_kaynagi" | "kural">, { teknik = false }: { teknik?: boolean } = {}): string {
  if (h.karar_kaynagi === "human") return "Karar kaynağı: insan sınıflandırması";
  if (h.karar_kaynagi === "llm") return "Karar kaynağı: AI (kural eşleşmedi)";
  // YD-07: iç kural kodu (`product_defect`, `test_maintenance/locator`) kullanıcıya sınıf adıyla; ham kod yalnız
  // Teknik ayrıntı sekmesinde (`teknik`).
  const ad = kuralAdi(h.kural);
  return `Karar kaynağı: otomatik kural${ad ? ` (${ad})` : ""}${teknik && h.kural ? ` · ${h.kural}` : ""}`;
}

const KURAL_ALT_ADI: Record<string, string> = { locator: "locator değişikliği", timing: "zamanlama", data: "test verisi" };

function kuralAdi(kural: string | null | undefined): string | null {
  if (!kural) return null;
  const [sinif, alt] = kural.split("/");
  const etiket = HATA_SINIFI[sinif as keyof typeof HATA_SINIFI]?.etiket;
  if (!etiket) return null;
  return alt ? `${etiket} · ${KURAL_ALT_ADI[alt] ?? alt.replace(/_/g, " ")}` : etiket;
}

type Asama = { ad: string; durum: "tamam" | "hata" | "bekliyor" | "suruyor"; ayrinti?: string | null };

const ASAMA_ISARETI: Record<Asama["durum"], { isaret: string; ton: Ton; metin: string }> = {
  tamam: { isaret: "✓", ton: "basari", metin: "tamam" },
  hata: { isaret: "✗", ton: "hata", metin: "başarısız" },
  bekliyor: { isaret: "○", ton: "notr", metin: "bekliyor" },
  suruyor: { isaret: "…", ton: "bilgi", metin: "sürüyor" },
};

/** Aria doğrulama aşamasının etiketi: kanıtın gerçek kaynağı (aria dosyası yoksa "aria" denmez). */
export function ariaAsamaAdi(o: Pick<LocatorOnarimi, "aria_dogrulama">): string {
  const k = o.aria_dogrulama?.kaynak;
  return (k && ARIA_KAYNAKLARI[k]) || "Son yeşil kanıtla rol + ad doğrulaması";
}

/**
 * Onarım hattı (§8.7): öneri → aria doğrulaması → AST koruması → etkilenen tüm testlerde yerel
 * kontrol → bot PR → insan merge'ü → CI. Durum bilinmiyorsa "bekliyor" (uydurma yeşil yok).
 */
export function onarimAsamalari(o: LocatorOnarimi): Asama[] {
  const yk = o.yerel_kontrol;
  const etk = o.etkilenen_testler ?? [];
  const ast = o.ast_guard;
  const ileri = o.durum === "pr_open" || o.durum === "merged";
  const oneriVar = Boolean(o.eski_test_id && o.yeni_test_id);
  // 009: uygulama testinde aria snapshot yok; onarım işi hata anı sayfa kaynağını yeniden okur.
  const app = sayfaKaynagiOnerisiMi(o);
  const ariaDurumu: Asama["durum"] =
    o.aria_dogrulama?.eslesti === true ? "tamam" : o.aria_dogrulama?.eslesti === false ? "hata" : "bekliyor";
  return [
    {
      ad: app ? "Öneri (AI'sız: hata anı sayfa kaynağından okunan kimlik)" : "Öneri (AI'sız: DOM'dan okunan testId)",
      durum: oneriVar ? "tamam" : o.durum === "failed" ? "hata" : "bekliyor",
      ayrinti: oneriVar ? `${o.eski_test_id} → ${o.yeni_test_id}` : "öneri üretilmedi",
    },
    {
      // Yalnızca onarım işinin kaydettiği sonuçtan: triage gözlemleri bu aşamayı tamamlamaz.
      ad: app ? "Sayfa kaynağında tek aday kimlik (sembol tablosunda tanımsız)" : ariaAsamaAdi(o),
      durum: ariaDurumu,
      ayrinti: o.aria_dogrulama?.aciklama ?? null,
    },
    {
      ad: app ? "AST koruması (onarım modu: yalnızca kimlik değeri)" : "AST koruması (onarım modu: yalnızca testId değeri)",
      durum: ast?.ok === true ? "tamam" : ast?.ok === false ? "hata" : ileri ? "tamam" : o.durum === "checking" ? "suruyor" : "bekliyor",
      ayrinti: ast?.ihlaller.length ? ast.ihlaller.join(" · ") : null,
    },
    {
      ad: `Yerel kontrol${app && o.platform ? ` (${PLATFORM_ETIKETI[o.platform]} cihazında)` : ""}: etkilenen tüm testler${etk.length ? ` (${etk.length})` : ""}`,
      durum:
        yk?.sonuc === "passed" ? "tamam" : yk?.sonuc === "failed" || yk?.sonuc === "error" ? "hata" : yk?.sonuc === "pending" || o.durum === "checking" ? "suruyor" : ileri ? "tamam" : "bekliyor",
      ayrinti: yk && yk.gecen !== null && yk.toplam !== null ? `${yk.gecen}/${yk.toplam} geçti` : null,
    },
    { ad: "Bot PR (tp-repair etiketi)", durum: o.pr ? "tamam" : o.durum === "failed" ? "hata" : "bekliyor", ayrinti: o.pr ? `#${o.pr.number} · ${o.pr.branch}` : null },
    { ad: "İnsan onayı (merge)", durum: o.durum === "merged" ? "tamam" : o.durum === "rejected" ? "hata" : "bekliyor" },
  ];
}

/**
 * Onarım işinin kontrol satırı → işaret. Engel, sha "farkli", AST ihlali, kırmızı kontrol başarı
 * yeşiliyle gösterilmez; "dogrulanamadi" uyarıdır.
 */
export function dogrulamaIsareti(x: string): { isaret: string; ton: Ton; metin: string } {
  if (/^Engellendi|ihlal|kırmızı|:\s*farkli\b|başarısız/i.test(x)) return { isaret: "✗", ton: "hata", metin: "olumsuz" };
  if (/dogrulanamadi|doğrulanamadı|bilinmiyor/i.test(x)) return { isaret: "!", ton: "uyari", metin: "doğrulanamadı" };
  return { isaret: "✓", ton: "basari", metin: "geçti" };
}

function OnarimKarti({ o, hataId, yenile }: { o: LocatorOnarimi; hataId: string; yenile: () => void }) {
  const islem = useIslem();
  const bildir = useBildirim();
  const d = ONARIM_DURUMU[o.durum];
  const asamalar = onarimAsamalari(o);
  const astHata = o.ast_guard?.ok === false;
  const kontrolKirmizi = o.yerel_kontrol?.sonuc === "failed" || o.yerel_kontrol?.sonuc === "error";
  const pr = o.pr;
  const oneriVar = Boolean(o.eski_test_id && o.yeni_test_id);
  const app = sayfaKaynagiOnerisiMi(o);
  // Rol/ad/kapsam satırı yalnız değer varsa: uygulama önerisinde (sayfa kaynağı) boş gelir, boş satır çizilmez.
  const niyetVar = Boolean(o.rol || o.ad || o.within);
  // Kardeş hata: onarım aynı koşudaki başka bir hata üzerinden yürüyor (bu hatanın onarım kaydı yok).
  const kardes = o.dogrulama_kaynagi !== "onarim" && (o.durum === "pr_open" || o.durum === "merged") && !pr;
  const mergeEngeli = !pr
    ? null
    : astHata
      ? "AST koruması başarısız: merge edilemez"
      : kontrolKirmizi
        ? "Etkilenen testlerde yerel kontrol kırmızı"
        : pr.ci === "failed"
          ? "CI kırmızı: merge edilemez"
          : pr.ci === "pending"
            ? "CI sürüyor; yeşil olunca merge edilebilir"
            : null; // CI özeti yoksa kapıyı core uygular (409 gerekçesi gösterilir)
  return (
    <Kart
      baslik={
        o.platform ? (
          <span className="satir-ogeler">
            Locator onarım önerisi <PlatformRozeti platform={o.platform} />
          </span>
        ) : (
          "Locator onarım önerisi"
        )
      }
      eylemler={
        o.durum === "proposed" && oneriVar ? (
          <IslemDugmesi
            izin="code.repair"
            calisiyor={islem.calisiyor}
            onClick={async () => {
              const s = await islem.calistir(() => api.onarimPrAc(hataId));
              if (s) {
                bildir(s.mesaj ?? "Onarım işi başladı: AST koruması ve yerel kontrol sonrası bot PR açar.");
                yenile();
              }
            }}
          >
            Onarım PR'ı aç
          </IslemDugmesi>
        ) : o.durum === "failed" ? (
          <IslemDugmesi
            izin="code.repair"
            tur="ikincil"
            calisiyor={islem.calisiyor}
            title="Core sağlık ve commit eşleşmesini yeniden denetler; ortam hâlâ sağlıksızsa reddeder."
            onClick={async () => {
              const s = await islem.calistir(() => api.onarimPrAc(hataId));
              if (s) {
                bildir(s.mesaj ?? "Onarım yeniden denendi: yoklama, AST koruması ve yerel kontrol baştan çalışır.");
                yenile();
              }
            }}
          >
            Yeniden dene
          </IslemDugmesi>
        ) : null
      }
    >
      {app ? (
        <p className="soluk kucuk" data-testid="onarim-sayfa-kaynagi">
          Uygulama testi: yeni kimlik hata anındaki sayfa kaynağından (Appium XML) bulundu. Onarım yalnızca{" "}
          <span className="mono yol-kirilir">{o.dosya || "(dosya bilinmiyor)"}</span> içindeki ilgili kimlik değerini değiştirir; ekran nesnesi metotları ve test
          adımları değişmez (AST koruması). Merge insan onayı ister.
        </p>
      ) : (
        <p className="soluk kucuk">
          Onarım yalnızca <span className="mono">{o.dosya}</span> içindeki ilgili <span className="mono">testId</span> değerini değiştirir;
          anahtar, rol, ad, niyet{o.within ? " ve kapsam (within)" : ""} değişmez (AST koruması). Merge insan onayı ister.
        </p>
      )}
      {oneriVar ? (
        <div className="locator-fark" aria-label="Locator değişikliği">
          <span className="mono">{app ? `${o.anahtar || "kimlik"} (kimlik)` : `${o.anahtar}.testId`}</span>
          <del className="mono">"{o.eski_test_id}"</del>
          <span aria-hidden="true">→</span>
          <span className="gorunmez">yeni değer</span>
          <ins className="mono">"{o.yeni_test_id}"</ins>
        </div>
      ) : (
        <p className="kucuk" data-testid="oneri-yok">
          <span className="mono">{app ? `${o.anahtar || "kimlik"} (kimlik)` : `${o.anahtar || "locator"}.testId`}</span> için değişiklik önerisi
          üretilmedi; yama yok.
        </p>
      )}
      {niyetVar && (
        <p className="kucuk" data-testid="onarim-niyet">
          Rol <span className="mono">{o.rol}</span> · ad <span className="mono">"{o.ad}"</span>
          {o.within && (
            <>
              {" "}
              · kapsam <span className="mono">{o.within}</span>
              {o.scope_test_id && (
                <>
                  {" "}
                  (<span className="mono">{o.scope_test_id}</span>)
                </>
              )}
            </>
          )}{" "}
          (değişmez)
        </p>
      )}
      {o.yama && (
        <pre className="kod-blok" aria-label="Onarım yaması" tabIndex={0}>
          {o.yama}
        </pre>
      )}
      {o.dogrulama.length > 0 &&
        (o.dogrulama_kaynagi === "onarim" ? (
          <ul className="kontrol-liste" aria-label="Onarım kontrolleri">
            {o.dogrulama.map((x) => {
              const i = dogrulamaIsareti(x);
              return (
                <li key={x} className={i.ton === "basari" ? undefined : `${i.ton}-metin`}>
                  <span className={`cip-${i.ton}`} aria-hidden="true">
                    {i.isaret}
                  </span>{" "}
                  {x} <span className="gorunmez">({i.metin})</span>
                </li>
              );
            })}
          </ul>
        ) : (
          // Triage gözlemleri: onarım henüz bir şey denetlemedi; onay işareti taşımaz.
          <>
            <p className="kucuk soluk">Triage gözlemleri (onarım kontrolü değil):</p>
            <ul className="duz-liste kucuk" aria-label="Triage gözlemleri">
              {o.dogrulama.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </>
        ))}
      {kardes && (
        <Uyari ton="bilgi" baslik="Onarım kardeş hata üzerinden yürüyor">
          Aynı koşuda aynı locator değişikliğini isteyen başka bir hata için onarım başlatıldı; PR ve kontroller o hatanın
          triage ekranında görünür. Bu hata için ayrı PR açılmaz.
        </Uyari>
      )}

      <ol className="onarim-asamalari" aria-label="Onarım hattı">
        {asamalar.map((a) => {
          const i = ASAMA_ISARETI[a.durum];
          return (
            <li key={a.ad} className={`asama-${a.durum}`}>
              <span className={`asama-isaret cip-${i.ton}`} aria-hidden="true">
                {i.isaret}
              </span>
              <div>
                <div>
                  {a.ad} <span className="gorunmez">({i.metin})</span>
                </div>
                {a.ayrinti && <div className="kucuk soluk mono">{a.ayrinti}</div>}
              </div>
            </li>
          );
        })}
      </ol>

      {(o.etkilenen_testler ?? []).length > 0 && (
        <details className="etkilenen-testler">
          <summary>Etkilenen testler ({o.etkilenen_testler!.length})</summary>
          <ul className="duz-liste kucuk">
            {o.etkilenen_testler!.map((t) => (
              <li key={t.test_adi} className="satir-ogeler">
                <Cip ton={t.durum === "passed" ? "basari" : t.durum === "failed" ? "hata" : "notr"}>
                  {t.durum === "passed" ? "geçti" : t.durum === "failed" ? "kırmızı" : "bekliyor"}
                </Cip>
                <span title={t.test_adi}>{testAdiGoster(t.test_adi)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {o.yerel_kontrol?.run_id && (
        <p className="kucuk">
          Yerel kontrol koşusu: <Link to={`/kosular/${encodeURIComponent(o.yerel_kontrol.run_id)}`}>{kisaKosuAdi(o.yerel_kontrol.run_id)}</Link>
        </p>
      )}
      {o.neden && (
        <Uyari ton={o.durum === "failed" ? "hata" : "uyari"} baslik={o.durum === "failed" ? "Onarım PR'ı açılamadı" : undefined}>
          {o.neden}
        </Uyari>
      )}

      <div className="satir-ogeler">
        <Cip ton={d.ton}>{d.etiket}</Cip>
        {pr && (
          <>
            <span className="mono">#{pr.number}</span>
            <DepoCipi kaynak={pr} />
            {pr.ci && (
              <Cip ton={pr.ci === "passed" ? "basari" : pr.ci === "failed" ? "hata" : "bilgi"}>
                CI: {pr.ci === "passed" ? "yeşil" : pr.ci === "failed" ? "kırmızı" : "bekliyor"}
              </Cip>
            )}
            {o.ast_guard && (
              <Cip ton={o.ast_guard.ok ? "basari" : o.ast_guard.ok === false ? "hata" : "notr"}>
                AST koruması: {o.ast_guard.ok ? "geçti" : o.ast_guard.ok === false ? "ihlal" : "bilinmiyor"}
              </Cip>
            )}
            <Baglanti href={pr.url} yokNedeni="LocalForge'un web arayüzü yok">
              {pr.url ? "PR'ı aç" : `PR #${pr.number} · ${pr.branch}`}
            </Baglanti>
          </>
        )}
      </div>

      {pr?.durum === "open" && (
        <div className="onarim-merge" data-testid="onarim-merge">
          <p className="kucuk soluk">
            Bot PR'ı yalnızca locator dosyasındaki testId değerini değiştirir. Merge insan kararıdır ve denetim kaydına yazılır.
          </p>
          <IslemDugmesi
            izin="code.merge"
            disabled={mergeEngeli !== null}
            title={mergeEngeli ?? undefined}
            // Engel düğmenin altında zaten görünür yazılı (aşağıdaki p); düğmeye bağlanır.
            nedenGizli={mergeEngeli !== null}
            aria-describedby={mergeEngeli !== null ? "onarim-merge-engeli" : undefined}
            calisiyor={islem.calisiyor}
            onClick={async () => {
              const s = await islem.calistir(() => api.prBirlestir(pr), { cakismada: yenile });
              if (s) {
                bildir(s.mesaj);
                yenile();
              }
            }}
          >
            Onarımı onayla ve merge et
          </IslemDugmesi>
          {mergeEngeli && (
            <p className="kucuk soluk" id="onarim-merge-engeli">
              {mergeEngeli}.
            </p>
          )}
        </div>
      )}
      {o.durum === "merged" && <Uyari ton="basari">Onarım birleşti; main üzerindeki CI koşusu testin yeniden yeşile döndüğünü gösterir.</Uyari>}
      {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
    </Kart>
  );
}

function SaglikUcuSatiri({ ad, u }: { ad: string; u: SaglikUcu | null }) {
  if (!u) return null;
  return (
    <li className="satir-ogeler">
      <span className="mono">{ad}</span>
      <Cip ton={u.hata ? "hata" : u.status !== null && u.status < 400 ? "basari" : "notr"}>{u.status ?? "yanıt yok"}</Cip>
      {u.ms !== null && <span className="kucuk soluk">{u.ms} ms</span>}
      {u.url && <span className="kucuk mono soluk">{u.url}</span>}
      {u.hata && <span className="kucuk hata-metin">{u.hata}</span>}
    </li>
  );
}

function SaglikBolumu({ s }: { s: SaglikSonucu }) {
  return (
    <section aria-labelledby="kanit-saglik">
      <h3 id="kanit-saglik" className="kanit-baslik">
        Sağlık yoklaması{" "}
        <Cip ton={s.ok === true ? "basari" : s.ok === false ? "hata" : "notr"}>{s.ok === true ? "başarılı" : s.ok === false ? "başarısız" : "bilinmiyor"}</Cip>
      </h3>
      <ul className="duz-liste">
        <SaglikUcuSatiri ad="web" u={s.web} />
        <SaglikUcuSatiri ad="api" u={s.api} />
      </ul>
      {s.hata && <p className="kucuk hata-metin">{s.hata}</p>}
      {s.zaman && <p className="kucuk soluk">{tarih(s.zaman)}</p>}
    </section>
  );
}

function ProbeBolumu({ p }: { p: LocatorProbeSonucu }) {
  const sha = p.sha_eslesmesi ? SHA_ESLESMESI[p.sha_eslesmesi] : null;
  return (
    <section aria-labelledby="kanit-probe">
      <h3 id="kanit-probe" className="kanit-baslik">
        Locator yoklaması (locator-probe)
      </h3>
      <dl className="tanim-izgara">
        <dt>Niyet (rol + ad)</dt>
        <dd className="mono">
          {p.rol ?? "—"} "{p.ad ?? "—"}"
        </dd>
        {p.scope_test_id && (
          <>
            <dt>Kapsam</dt>
            <dd className="mono">{p.scope_test_id}</dd>
          </>
        )}
        <dt>Eşleşen eleman</dt>
        <dd>{p.matches ?? "ölçülmedi"}</dd>
        <dt>DOM'daki data-testid</dt>
        <dd className="mono">{p.test_id ?? "—"}</dd>
        <dt>Ölçüm</dt>
        <dd>
          {p.olculen === "calisan_uygulama" ? "çalışan demo uygulaması" : (p.olculen ?? "—")}
          {p.uygulama_sha && <span className="mono"> · {p.uygulama_sha.slice(0, 12)}</span>} {sha && <Cip ton={sha.ton}>{sha.etiket}</Cip>}
        </dd>
      </dl>
      {p.uyari && <Uyari ton="uyari">{p.uyari}</Uyari>}
      {p.oneri_uretilebilir === false && <p className="kucuk soluk">Bu ölçümden onarım önerisi üretilmez; karar insana düşer.</p>}
    </section>
  );
}

/** Aynı adrese giden kanıt bağlantıları bir kez (en açıklayıcı etiketle) gösterilir. */
export function tekilLinkler(linkler: HataAnalizi["kanit_linkleri"]): HataAnalizi["kanit_linkleri"] {
  const sira: string[] = [];
  const secilen = new Map<string, HataAnalizi["kanit_linkleri"][number]>();
  for (const l of linkler) {
    const anahtar = l.url ? `u:${l.url}` : `e:${l.etiket}`;
    const var_ = secilen.get(anahtar);
    if (!var_) {
      sira.push(anahtar);
      secilen.set(anahtar, l);
    } else if (l.etiket.length > var_.etiket.length) {
      secilen.set(anahtar, l);
    }
  }
  return sira.map((k) => secilen.get(k)!);
}

type KanitLinki = HataAnalizi["kanit_linkleri"][number];

const KANIT_TURU_ETIKETI: Record<string, string> = {
  page_source: "Hata anı sayfa kaynağı (Appium)",
  trace: "Playwright trace",
  screenshot: "Ekran görüntüsü",
  error_context: "Hata anı sayfa snapshot'ı (error-context)",
  video: "Video",
};

/** Kanıt türü: core `tur` (trace|screenshot|error_context|video ya da Playwright ek adı) ya da etiketten. */
export function kanitTuru(l: KanitLinki): string {
  const ham = `${l.tur ?? ""} ${l.etiket}`.toLowerCase();
  // 009: Appium sayfa kaynağı — "hata anı" etiketi error_context'ten ÖNCE ayrılır.
  if (/page[-_ ]?source|sayfa kaynağı|sayfa-kaynagi\.xml/.test(ham)) return "page_source";
  if (/trace/.test(ham)) return "trace";
  if (/error[-_ ]?context|hata anı/.test(ham)) return "error_context";
  if (/screenshot|ekran görüntüsü|image\//.test(ham)) return "screenshot";
  if (/video/.test(ham)) return "video";
  return `etiket:${l.etiket}`;
}

/** Playwright yeniden deneme dizini (`…-retry1/…`) → "2. deneme"; bilinmiyorsa null. */
export function denemeEtiketi(url: string | null): string | null {
  const m = url?.match(/-retry(\d+)(?:\/|$)/);
  return m ? `${Number(m[1]) + 1}. deneme` : url ? "1. deneme" : null;
}

export interface KanitGrubu {
  etiket: string;
  linkler: { etiket: string; url: string | null }[];
}

/**
 * Kanıt bağlantıları türe göre tek satırda: aynı dosya (aynı adres) bir kez; aynı türün farklı
 * denemelerden gelen kopyaları ("Playwright trace" + ek adı "trace") ayrı satır olarak tekrar
 * edilmez, deneme numarasıyla aynı satırda gösterilir.
 */
export function kanitGruplari(linkler: KanitLinki[]): KanitGrubu[] {
  const sira: string[] = [];
  const gruplar = new Map<string, KanitLinki[]>();
  for (const l of tekilLinkler(linkler)) {
    const t = kanitTuru(l);
    if (!gruplar.has(t)) {
      sira.push(t);
      gruplar.set(t, []);
    }
    gruplar.get(t)!.push(l);
  }
  return sira.map((t) => {
    const ls = gruplar.get(t)!;
    const etiket = KANIT_TURU_ETIKETI[t] ?? ls.reduce((a, l) => (l.etiket.length > a.length ? l.etiket : a), ls[0].etiket);
    if (ls.length === 1) return { etiket, linkler: [{ etiket, url: ls[0].url }] };
    const adresli = ls.filter((l) => l.url);
    // Adresi olmayan kopya, adresli bir kopya varken tekrar gösterilmez.
    const gosterilen = adresli.length ? adresli : ls.slice(0, 1);
    const etiketler = gosterilen.map((l) => denemeEtiketi(l.url));
    const benzersiz = new Set(etiketler).size === etiketler.length && etiketler.every(Boolean);
    return {
      etiket,
      linkler: gosterilen
        .map((l, i) => ({ etiket: gosterilen.length === 1 ? etiket : benzersiz ? etiketler[i]! : `${i + 1}. kopya`, url: l.url }))
        .sort((a, b) => a.etiket.localeCompare(b.etiket, "tr")),
    };
  });
}

/** Ürün hatası: bug taslağındaki en olası mükerrer adayı (§2 adım 12: "olası mükerrer: XYZ-12"). */
function MukerrerSatiri({ id, kisitli = false }: { id: string; kisitli?: boolean }) {
  const v = useVeri(() => api.bugTaslagi(id), [id]);
  // Kısıtlı rol (developer) yalnız yayınlanmış taslağı açabilir: core diğerlerinde 404 döner.
  if (kisitli && !v.veri) {
    return v.hata ? (
      <p className="soluk kucuk" data-testid="bug-taslagi-kisitli">
        {BUG_KISITLI_METNI}
      </p>
    ) : null;
  }
  if (!v.veri) return null;
  const b = v.veri;
  const karara = b.durum === "published" || b.durum === "dismissed" || b.durum === "approved";
  return (
    <>
      {karara && b.sonuc_metni && (
        <p data-testid="bug-taslagi-sonucu">
          <strong>{b.sonuc_metni}</strong>
          {b.durum === "published" && b.jira_url && (
            <>
              {" "}
              <a href={b.jira_url} target="_blank" rel="noreferrer">
                Jira'da aç
              </a>
            </>
          )}
        </p>
      )}
      <p className="kucuk" data-testid="olasi-mukerrer">
        {olasiMukerrerMetni(b)}
      </p>
      {kisitli && (
        <p>
          <Link className="dugme dugme-birincil dugme-kucuk" to={`/bug-taslaklari/${encodeURIComponent(b.id)}`}>
            Bug taslağına git
          </Link>
        </p>
      )}
    </>
  );
}

const OLASILIK_METNI = { high: "yüksek olasılık", medium: "orta olasılık", low: "düşük olasılık" } as const;

export function olasiMukerrerMetni(b: Pick<BugTaslagi, "mukerrer_adaylari" | "mukerrer_arama">): string {
  const a = b.mukerrer_arama;
  if (a?.durum === "suruyor") return "Olası mükerrer: Jira'da aranıyor…";
  if (a?.durum === "basarisiz") return "Olası mükerrer: arama başarısız (Jira'yı elle kontrol edin).";
  if (a?.durum === "yapilmadi") return "Olası mükerrer: arama yapılmadı.";
  const ilk = b.mukerrer_adaylari[0];
  if (!ilk) return "Olası mükerrer: Jira'da benzer açık bug bulunamadı.";
  const ai = ilk.olasilik || ilk.gerekce;
  const ek = ai
    ? `${ilk.olasilik ? OLASILIK_METNI[ilk.olasilik] : "olasılık yok"}, AI sıralaması${a?.mode === "replay" ? " (REPLAY)" : ""}`
    : `AI sıralaması yok${a?.mode === "replay_miss" ? " (REPLAY-MISS)" : ""}; Jira arama sırası`;
  return `Olası mükerrer: ${ilk.key}${ilk.summary ? ` — ${ilk.summary}` : ""} (${ek})`;
}

/**
 * 009: uygulama testinin hata anı kanıtları (core `kanit_linkleri` `tur`: page_source, screenshot).
 * Ekran görüntüsü yalnız uygulama testinde satır içi gösterilir (web kanıtı bağlantı olarak kalır).
 */
export function uygulamaKanitlari(
  linkler: HataAnalizi["kanit_linkleri"],
  platform: HataAnalizi["platform"],
): { sayfaKaynagi: KanitLinki | null; ekran: KanitLinki | null } {
  const tekil = tekilLinkler(linkler);
  const sayfaKaynagi = tekil.find((l) => kanitTuru(l) === "page_source") ?? null;
  const app = sayfaKaynagi !== null || uygulamaPlatformuMu(platform ?? null);
  const ekran = app ? (tekil.find((l) => kanitTuru(l) === "screenshot" && l.url) ?? null) : null;
  return { sayfaKaynagi, ekran };
}

function KanitKarti({
  k,
  linkler,
  platform,
}: {
  k: TriageKaniti | null | undefined;
  linkler: HataAnalizi["kanit_linkleri"];
  platform?: HataAnalizi["platform"];
}) {
  const [sar, setSar] = useState(false);
  if (!k && linkler.length === 0) return null;
  const app = uygulamaKanitlari(linkler, platform);
  // Sayfa kaynağı görüntüleyicide (kendi bağlantısıyla) gösterilir; listede tekrarlanmaz.
  const listedeki = app.sayfaKaynagi ? linkler.filter((l) => kanitTuru(l) !== "page_source") : linkler;
  return (
    <Kart baslik="Kanıt">
      {/* DZ-10: hata mesajı tam genişlikte (yığın izi girintisi korunur, yatay kayar; "Satırları sar" ile sarılır);
          aria snapshot, locator yoklaması ve sağlık yoklaması altında iki sütun. */}
      {k?.hata_mesaji && (
        <section aria-labelledby="kanit-hata" className="kanit-hata">
          <div className="kanit-hata-ust">
            <h3 id="kanit-hata" className="kanit-baslik">
              Hata mesajı
            </h3>
            <label className="kanit-sar">
              <input type="checkbox" checked={sar} onChange={(e) => setSar(e.target.checked)} /> Satırları sar
            </label>
          </div>
          <pre className={`hata-mesaji kanit-hata-metni${sar ? " kanit-sar-acik" : ""}`} tabIndex={0}>
            {k.hata_mesaji}
          </pre>
          {(k.beklenen || k.gerceklesen) && (
            <p className="kucuk">
              Beklenen <span className="mono">{k.beklenen ?? "—"}</span> · Gerçekleşen <span className="mono">{k.gerceklesen ?? "—"}</span>
            </p>
          )}
          {k.konum && <p className="kucuk mono soluk">{k.konum}</p>}
          {k.tekrarlar && k.tekrarlar.length > 0 && <p className="kucuk">Tekrarlar: {k.tekrarlar.join(" · ")}</p>}
        </section>
      )}
      <div className="kanit-izgara">
        {k?.aria_snippet && (
          <section aria-labelledby="kanit-aria">
            <h3 id="kanit-aria" className="kanit-baslik">
              Aria snapshot (hata anı, yalnızca rol + ad)
            </h3>
            <pre className="kod-blok" tabIndex={0}>
              {k.aria_snippet}
            </pre>
          </section>
        )}
        {k?.locator_probe && <ProbeBolumu p={k.locator_probe} />}
        {k?.saglik && <SaglikBolumu s={k.saglik} />}
      </div>
      {(app.sayfaKaynagi || app.ekran) && (
        <div className="uygulama-kanit">
          {app.ekran && <EkranGoruntusuKaniti url={app.ekran.url} etiket={`Hata anı ekran görüntüsü${platform ? ` (${PLATFORM_ETIKETI[platform]})` : ""}`} />}
          {app.sayfaKaynagi && <SayfaKaynagiGoruntuleyici key={app.sayfaKaynagi.url ?? "yok"} url={app.sayfaKaynagi.url} />}
        </div>
      )}
      {k?.uyarilar && k.uyarilar.length > 0 && (
        <ul className="kucuk duz-liste" aria-label="Kanıt uyarıları">
          {k.uyarilar.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      )}
      {listedeki.length > 0 && (
        <ul className="duz-liste kanit-gruplari" aria-label="Kanıt bağlantıları">
          {kanitGruplari(listedeki).map((g) => (
            <li key={g.etiket} className="kanit-grubu">
              {g.linkler.length === 1 ? (
                <Baglanti href={g.linkler[0].url} yokNedeni="dosya sunucusu yok">
                  {g.etiket}
                </Baglanti>
              ) : (
                <>
                  <span>{g.etiket}:</span>
                  {g.linkler.map((l) => (
                    <Baglanti key={`${l.etiket}-${l.url ?? ""}`} href={l.url} yokNedeni="dosya sunucusu yok">
                      <span className="gorunmez">{g.etiket}, </span>
                      {l.etiket}
                    </Baglanti>
                  ))}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Kart>
  );
}

const SINIF_ACIKLAMASI: Record<(typeof INSAN_SINIFLARI)[number], string> = {
  product_defect: "Uygulama yanlış davranıyor: bug taslağı açılır, Test Uzmanı karar verir.",
  test_maintenance: "Test güncel değil (locator, adım): Otomasyon Mühendisinin onarım kuyruğuna gider.",
  test_data: "Test verisi yanlış ya da eksik: test verisi kataloğu düzeltilir.",
  flaky: "Kararsız test: aynı kodda bazen geçiyor; Otomasyon Mühendisi takip eder.",
  environment: "Ortam sorunu (ağ, servis, cihaz): onarım ya da bug açılmaz.",
};

/**
 * IA-16 karar kartı: kural ya da AI sınıflandıramadıysa ("Belirsiz", REPLAY-MISS) yetkili rol (Test Uzmanı,
 * Otomasyon Mühendisi) sınıfı gerekçeyle belirler; yetkisiz rolde tek satır "kimi bekliyoruz". Sınıflandırılmış
 * hatada yetkili rol sınıfı "Sınıfı düzelt" açılırından değiştirebilir (onarım PR'ı / bug taslağı yoksa).
 */
export function SiniflandirmaKarti({ h, guncellendi }: { h: HataAnalizi; guncellendi: (h: HataAnalizi) => void }) {
  const yetkili = useIzin("failure.classify");
  const bildir = useBildirim();
  const islem = useIslem();
  const [sinif, setSinif] = useState<(typeof INSAN_SINIFLARI)[number] | "">("");
  const [gerekce, setGerekce] = useState("");
  const [acilan, setAcilan] = useState<string | null>(null);
  const [duzeltAcik, setDuzeltAcik] = useState(false);
  const belirsiz = h.sinif === "unknown";
  const kilitli = h.oneri?.tur === "bug_draft" || (h.oneri?.tur === "locator_fix" && (h.oneri.durum === "pr_open" || h.oneri.durum === "merged"));
  if (!belirsiz && (!yetkili || kilitli)) {
    return h.karar_kaynagi === "human" && h.gerekce ? (
      <p className="kucuk" data-testid="insan-karari">
        <strong>İnsan sınıflandırması:</strong> {h.gerekce}
      </p>
    ) : null;
  }
  if (belirsiz && !yetkili) {
    return (
      <p className="sonraki-adim-satiri" role="note" data-testid="siniflandirma-bekleniyor">
        Bu adım Test Uzmanı'nda: sınıflandırma bekleniyor (Otomasyon Mühendisi de sınıflandırabilir).
      </p>
    );
  }
  const form = (
    <form
      className="form siniflandirma-formu"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!sinif || !gerekce.trim()) return;
        const s = await islem.calistir(() => islerimApi.hataSiniflandir(h.id, { sinif, gerekce: gerekce.trim() }));
        if (!s) return;
        setAcilan(s.bugTaslagiId);
        setGerekce("");
        setSinif("");
        guncellendi(s.hata);
        bildir(s.bugTaslagiId ? "Ürün hatası olarak sınıflandırıldı; bug taslağı açıldı." : `Sınıf kaydedildi: ${HATA_SINIFI[s.hata.sinif]?.etiket ?? s.hata.sinif}.`);
      }}
    >
      <fieldset className="alan">
        <legend>Bu hata ne?</legend>
        {INSAN_SINIFLARI.map((k) => (
          <label key={k} className="secenek-satiri">
            <input type="radio" name={`sinif-${h.id}`} value={k} checked={sinif === k} onChange={() => setSinif(k)} />
            <span>
              <strong>{HATA_SINIFI[k].etiket}</strong> <span className="soluk kucuk">— {SINIF_ACIKLAMASI[k]}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="alan">
        <label htmlFor={`sinif-gerekce-${h.id}`}>Gerekçe (denetim kaydına yazılır)</label>
        <textarea id={`sinif-gerekce-${h.id}`} rows={2} value={gerekce} maxLength={2000} onChange={(e) => setGerekce(e.target.value)} required />
      </div>
      {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
      <div className="eylemler">
        <IslemDugmesi izin="failure.classify" type="submit" calisiyor={islem.calisiyor} disabled={!sinif || !gerekce.trim()}>
          Sınıfı kaydet
        </IslemDugmesi>
      </div>
    </form>
  );
  return (
    <div data-testid="siniflandirma-karti">
      {acilan && (
        <Uyari ton="bilgi" baslik="Bug taslağı açıldı">
          <Link to={`/bug-taslaklari/${encodeURIComponent(acilan)}`}>Bug taslağına git</Link>
        </Uyari>
      )}
      {belirsiz ? (
        <Kart baslik="Karar: bu hatayı sınıflandırın">
          <p className="soluk kucuk">
            Kural eşleşmedi ve AI sınıflandıramadı{h.mode === "replay_miss" ? " (REPLAY-MISS: kayıtlı AI yanıtı yok)" : ""}. Sınıfı siz belirleyin;
            hata ilgili kuyruğa düşer.
          </p>
          {form}
        </Kart>
      ) : (
        <details className="siniflandirma-duzelt" onToggle={(e) => setDuzeltAcik((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>Sınıfı düzelt</summary>
          {duzeltAcik && form}
        </details>
      )}
    </div>
  );
}

export function HataDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.hata(id), [id]);
  const bugKisitli = useBugKisitli();
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["failure.classified", "failure.updated", "ci.status", "pr.opened", "pr.merged"], id);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <BaskaProjedeKayit tur="failure" id={id} hata={v.hataNesnesi} ad="Hata kaydı" liste={["/hatalar", "Hatalar"]} yedek={<KayitHatasi ad="Hata kaydı" hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />} />;
  const h = v.veri;
  if (!h) return null;
  const ortam = h.sinif === "environment";
  const kisaKosu = kisaKosuAdi(h.run_id);
  const bugTaslagi = !ortam && h.oneri?.tur === "bug_draft" ? h.oneri.bug_draft_id : null;
  const locatorOnarimi = !ortam && h.oneri?.tur === "locator_fix" ? h.oneri : null;
  const beklenti = !ortam && h.alt_tur === "beklenti";
  const oneriYok = !h.oneri && h.oneri_yok_nedeni && h.alt_tur !== "beklenti";
  const onarimVar = Boolean(locatorOnarimi || bugTaslagi || beklenti || oneriYok);
  const kanitVar = Boolean(h.kanit || h.kanit_linkleri.length > 0);

  // Öneri kartındaki "Git" çapası (#onarim): onarım/öneri bölümü her durumda bu kapta (Onarım sekmesi).
  const onarim = (
    <div id="onarim" className="triage-oneri">
      {locatorOnarimi && <OnarimKarti o={locatorOnarimi} hataId={h.id} yenile={() => void v.yenile(true)} />}
      {bugTaslagi && (
        <Kart baslik="Öneri">
          <p>Ürün hatası adayı: bug taslağı hazırlandı ve Jira'da mükerrer araması yapıldı. Kayıt yalnızca Test Uzmanı onayıyla açılır.</p>
          <MukerrerSatiri id={bugTaslagi} kisitli={bugKisitli} />
          {/* DZ-10: eylem paragrafın içinde değil, kartın alt eylem satırında. */}
          {!bugKisitli && (
            <EylemCubugu etiket="Öneri eylemleri">
              <Link className="dugme dugme-birincil" to={`/bug-taslaklari/${encodeURIComponent(bugTaslagi)}`}>
                Bug taslağına git
              </Link>
            </EylemCubugu>
          )}
        </Kart>
      )}
      {/* 012 Ş3: test beklentisi onaylı karar tablosuyla uyuşmuyor → bug/onarım değil, case düzeltilir. */}
      {beklenti && (
        <div data-testid="case-duzeltilmeli">
          <Uyari ton="uyari" baslik="Case düzeltilmeli">
            Case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor; uygulama tabloya uygun. Bug taslağı ve locator onarımı açılmaz.{" "}
            {/* Çekirdek `GET /failures/{id}` case/gereksinim kimliği vermez (yalnız `script_id`, `run_id`,
                `test_adi`); gelirse doğrudan case listesine, yoksa script'e, o da yoksa koşuya bağlanır. */}
            {h.requirement_id ? (
              <Link to={`/gereksinimler/${encodeURIComponent(h.requirement_id)}/caseler`}>Case'i aç{h.case_id ? ` (${h.case_id})` : ""}</Link>
            ) : h.script_id ? (
              <Link to={`/kod/${encodeURIComponent(h.script_id)}`}>Script ve bağlı case'i aç</Link>
            ) : h.run_id ? (
              <Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>Koşuyu aç ({testAdiGoster(h.test_adi)})</Link>
            ) : null}
          </Uyari>
        </div>
      )}
      {oneriYok && (
        <Uyari ton="uyari" baslik="Öneri üretilmedi">
          {h.oneri_yok_nedeni}
        </Uyari>
      )}
      {!onarimVar && (
        <BosDurum kip="sekme" baslik={ortam ? "Ortam sorunu için onarım ya da bug taslağı üretilmez." : "Bu hata için öneri yok."}>
          {ortam ? "Ortam düzelince koşuyu yeniden çalıştırın." : "Sınıflandırma ve kanıtı inceleyip kararı verin."}
        </BosDurum>
      )}
    </div>
  );

  const sekmeler: DetaySekmesi[] = [
    {
      id: "kanit",
      ad: "Kanıt",
      icerik: () =>
        kanitVar ? (
          <KanitKarti k={h.kanit} linkler={h.kanit_linkleri} platform={h.platform} />
        ) : (
          <BosDurum kip="sekme" baslik="Bu hata için kanıt kaydı yok.">
            {h.hata_mesaji ? <pre className="hata-mesaji">{h.hata_mesaji}</pre> : "Koşunun raporlarına koşu sayfasından ulaşabilirsiniz."}
          </BosDurum>
        ),
    },
    {
      id: "sinyaller",
      ad: "Sinyaller",
      sayi: h.eslesen_sinyaller.length,
      icerik: () => (
        <Kart baslik="Eşleşen sinyaller">
          {h.eslesen_sinyaller.length === 0 ? (
            <BosDurum baslik="Sinyal kaydı yok." />
          ) : (
            <ul className="sinyal-liste" aria-label="Eşleşen sinyaller">
              {h.eslesen_sinyaller.map((sg) => {
                const { baslik, ayrinti } = sinyalBasligi(sg);
                const tabloSinyali = sg.kod.startsWith("karar_tablosu");
                return (
                  <li key={sg.kod} data-testid={`sinyal-${sg.kod}`}>
                    <span aria-hidden="true">✓</span>
                    <div>
                      <div className="sinyal-baslik">
                        {tabloSinyali ? <strong>{baslik}</strong> : baslik}
                        {tabloSinyali && h.requirement_id && (
                          <>
                            {" "}
                            <Link className="kucuk" to={`/gereksinimler/${encodeURIComponent(h.requirement_id)}/karar-tablolari`}>
                              Karar tablosunu aç
                            </Link>
                          </>
                        )}
                      </div>
                      {ayrinti && <div className="kucuk">{ayrinti}</div>}
                      {sg.kanit && (
                        <pre className="kod-blok sinyal-kanit" tabIndex={0}>
                          {sg.kanit}
                        </pre>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {h.llm_yorumu && (
            <Uyari ton="bilgi" baslik="AI yorumu">
              {h.llm_yorumu}
            </Uyari>
          )}
        </Kart>
      ),
    },
    { id: "onarim", ad: "Onarım", capalar: ["onarim"], icerik: onarim },
    {
      id: "teknik",
      ad: "Teknik ayrıntı",
      icerik: () => (
        <Kart baslik="Teknik ayrıntı">
          <MetaIzgara
            etiket="Triage teknik ayrıntısı"
            ogeler={[
              { etiket: "Hata kaydı", deger: <Kimlik deger={h.id} tur="uuid" kopyala /> },
              { etiket: "Koşu", deger: <Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>Koşu {kisaKosu}</Link> },
              { etiket: "Karar kaynağı", deger: kararKaynagiMetni(h, { teknik: true }) },
              { etiket: "Kural", deger: h.kural ? <span className="kucuk mono">{h.kural}</span> : null },
              // IA-12: imza ve sinyal kodları geliştirici/destek içindir; kullanıcı metninde değil, burada.
              { etiket: "Hata imzası", deger: h.hata_imzasi ? <span className="kucuk mono">{h.hata_imzasi}</span> : null, genis: true },
              {
                etiket: "Sinyal kodları",
                deger: h.eslesen_sinyaller.length ? (
                  <span className="kucuk mono">{h.eslesen_sinyaller.map((sg) => `${sg.kod}${sg.kaynak ? ` · ${sg.kaynak}` : ""}`).join(", ")}</span>
                ) : null,
                genis: true,
              },
              { etiket: "Zaman", deger: tarih(h.zaman) },
            ]}
          />
          <p className="soluk kucuk">
            Önce kural seti uygulanır; AI yalnızca hiçbir kural eşleşmezse devreye girer ve ortam kararını ezemez. Sayısal güven yerine
            eşleşen sinyaller gösterilir.
          </p>
          {/* Kanıt sekmesi tam hata metnini gösteriyorsa burada tekrar edilmez. */}
          {h.hata_mesaji && !h.kanit?.hata_mesaji && <pre className="hata-mesaji">{h.hata_mesaji}</pre>}
        </Kart>
      ),
    },
  ];

  return (
    <DetaySayfasi
      key={h.id}
      sekmeEtiketi="Triage bölümleri"
      varsayilanSekme={locatorOnarimi || bugTaslagi || beklenti ? "onarim" : "kanit"}
      ozet={
        <OzetKarti
          testId="triage-ozet"
          // YD-10: menüde "Hatalar" seçili; kırıntı da Hatalar kuyruğundan gelir (koşu bağlantısı meta satırında).
          kirinti={[{ ad: "Hatalar", yol: "/hatalar" }, { ad: testKisaAdi(h.test_adi) }]}
          // YD-12: sekme başlığı kısa test adı ("TPD-1 C10 · Triage"); uzun ad ve @etiketler sekmede okunmaz.
          sekme={`${testKisaAdi(h.test_adi)} · Triage`}
          baslik={testAdiGoster(h.test_adi)}
          rozetler={
            <span className="satir-ogeler" data-testid="triage-sinif">
              <DurumCipi harita={HATA_SINIFI} deger={h.sinif} />
              {h.alt_tur && (TRIAGE_ALT_TUR[h.alt_tur] ? <span data-testid="triage-alt-tur">{altTurEtiketi(h.alt_tur)}</span> : <span className="mono">{h.alt_tur}</span>)}
              <Cip ton={h.karar_kaynagi === "rule" ? "notr" : "vurgu"}>{kararKaynagiMetni(h)}</Cip>
              <ReplayRozeti mode={h.mode} degerlendirme={h.degerlendirme} />
              <PlatformRozeti platform={h.platform} />
            </span>
          }
          meta={
            <MetaSatiri
              ogeler={[
                { deger: tarih(h.zaman) },
                { etiket: "Koşu", deger: <Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>{kisaKosu}</Link> },
                { etiket: "Gereksinim", deger: h.requirement_id ? <Link to={`/gereksinimler/${encodeURIComponent(h.requirement_id)}`}>Gereksinimi aç</Link> : null },
                { etiket: "Case", deger: h.case_id ? <span className="mono">{h.case_id}</span> : null },
                { deger: h.script_id ? <Link to={`/kod/${encodeURIComponent(h.script_id)}`}>Üretilen test</Link> : null },
              ]}
            />
          }
          siradaki={<TriageSiradaki ortam={ortam} locator={Boolean(locatorOnarimi)} bug={bugTaslagi} bugKisitli={bugKisitli} beklenti={beklenti} />}
        />
      }
      ust={
        // Karar alanı (IA-16): sınıfın gerekçesi, ortam notu ve sınıflandırma kartı (Belirsiz → karar formu, yetkili
        // rolde "Sınıfı düzelt", yetkisizde kimi beklediğimiz). İçerik yoksa kap gizlenir (.karar-yuvasi:empty).
        <section className="kart karar-yuvasi" aria-label="Triage kararı" data-testid="karar-yuvasi">
          {/* Belirsiz (unknown) hatada gerekçe gösterilmez (YD-09): "neden sınıflandırılamadı" zaten sıradaki
              adımda ve sınıflandırma kartının açıklamasında yazıyor; üçüncü kez tekrarlanmaz. */}
          {h.gerekce && h.karar_kaynagi !== "human" && h.sinif !== "unknown" && <p className="karar-yuvasi-gerekce">{h.gerekce}</p>}
          {ortam && (
            <Uyari ton="bilgi" baslik="Ortam sorunu">
              Test koşmadan önce ortam sağlıksızdı ya da ağ hatası oluştu. Bu başarısızlık için onarım PR'ı ya da bug taslağı üretilmez.
            </Uyari>
          )}
          <SiniflandirmaKarti h={h} guncellendi={(y) => v.setVeri(y)} />
        </section>
      }
      sekmeler={sekmeler}
    />
  );
}

/** Triage'ın tek "Sıradaki adım"ı (öneriye göre). */
function TriageSiradaki({ ortam, locator, bug, bugKisitli, beklenti }: { ortam: boolean; locator: boolean; bug: string | null; bugKisitli: boolean; beklenti: boolean }) {
  const onarimaGit = (
    <Link to="?sekme=onarim" className="ds-siradaki-git">
      Onarım →
    </Link>
  );
  if (ortam) return <>Ortam sorunu: ortamı düzeltip koşuyu yeniden çalıştırın; onarım ya da bug taslağı üretilmez.</>;
  if (locator) return <>Önerilen locator onarımını inceleyin (Otomasyon Mühendisi). {onarimaGit}</>;
  if (bug)
    return bugKisitli ? (
      <>Ürün hatası adayı; bug kararını Test Uzmanı verir.</>
    ) : (
      <>
        Bug taslağını inceleyip kararı verin (Test Uzmanı).{" "}
        <Link to={`/bug-taslaklari/${encodeURIComponent(bug)}`} className="ds-siradaki-git">
          Bug taslağı →
        </Link>
      </>
    );
  if (beklenti) return <>Case'in beklenen değeri düzeltilmeli (Analist). {onarimaGit}</>;
  // `failure.classify`: Test Uzmanı ve Otomasyon Mühendisi (YD-06).
  return <>Öneri üretilmedi; hatayı Test Uzmanı ya da Otomasyon Mühendisi kanıta bakarak sınıflandırmalı.</>;
}

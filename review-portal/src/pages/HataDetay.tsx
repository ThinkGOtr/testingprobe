import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ARIA_KAYNAKLARI } from "../api/uyumTriage";
import { useOlay } from "../api/events";
import type { BugTaslagi, HataAnalizi, LocatorOnarimi, LocatorProbeSonucu, SaglikSonucu, SaglikUcu, TriageKaniti } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { Baglanti, BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { altTurEtiketi, HATA_SINIFI, sinyalBasligi, TRIAGE_ALT_TUR, type Ton } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { kisaKosuAdi } from "./Kosular";
import { PlatformRozeti } from "../components/Platform";
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

/** Karar kaynağı: deterministik kural (adıyla) ya da LLM yorumu (yalnızca kural eşleşmediyse). */
export function kararKaynagiMetni(h: Pick<HataAnalizi, "karar_kaynagi" | "kural">): string {
  if (h.karar_kaynagi === "llm") return "Karar kaynağı: LLM (kural eşleşmedi)";
  return h.kural ? `Karar kaynağı: kural · ${h.kural}` : "Karar kaynağı: deterministik kural";
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
      ad: app ? "Öneri (LLM'siz: hata anı sayfa kaynağından okunan kimlik)" : "Öneri (LLM'siz: DOM'dan okunan testId)",
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
                <span>{t.test_adi}</span>
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
function MukerrerSatiri({ id }: { id: string }) {
  const v = useVeri(() => api.bugTaslagi(id), [id]);
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
  if (!k && linkler.length === 0) return null;
  const app = uygulamaKanitlari(linkler, platform);
  // Sayfa kaynağı görüntüleyicide (kendi bağlantısıyla) gösterilir; listede tekrarlanmaz.
  const listedeki = app.sayfaKaynagi ? linkler.filter((l) => kanitTuru(l) !== "page_source") : linkler;
  return (
    <Kart baslik="Kanıt">
      <div className="kanit-izgara">
        {k?.hata_mesaji && (
          <section aria-labelledby="kanit-hata">
            <h3 id="kanit-hata" className="kanit-baslik">
              Hata mesajı
            </h3>
            <pre className="hata-mesaji" tabIndex={0}>
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

export function HataDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.hata(id), [id]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["failure.classified", "failure.updated", "ci.status", "pr.opened", "pr.merged"], id);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />;
  const h = v.veri;
  if (!h) return null;
  const s = HATA_SINIFI[h.sinif] ?? { etiket: h.sinif, ton: "notr" as const };
  const ortam = h.sinif === "environment";

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>← Koşu {kisaKosuAdi(h.run_id)}</Link>}
        baslik="Triage sonucu"
        aciklama={h.test_adi}
      />
      {/* Triage ızgarası (§5 görsel kapı, 1152 px): solda Sınıf + öneri, sağda iki satıra yayılan sinyaller.
          DOM sırası Sınıf → Sinyaller → Öneri olarak kalır; yerleşim yalnız CSS ızgarasıyla. */}
      <div className="iki-sutun triage-izgara">
        <Kart baslik="Sınıf">
          <p className="satir-ogeler" data-testid="triage-sinif">
            <Cip ton={s.ton}>{s.etiket}</Cip>
            {h.alt_tur && (TRIAGE_ALT_TUR[h.alt_tur] ? <span data-testid="triage-alt-tur">{altTurEtiketi(h.alt_tur)}</span> : <span className="mono">{h.alt_tur}</span>)}
            <Cip ton={h.karar_kaynagi === "rule" ? "notr" : "vurgu"}>{kararKaynagiMetni(h)}</Cip>
            <ReplayRozeti mode={h.mode} degerlendirme={h.degerlendirme} />
            <PlatformRozeti platform={h.platform} />
          </p>
          <p className="soluk kucuk">
            Önce kural seti uygulanır; LLM yalnızca hiçbir kural eşleşmezse devreye girer ve ortam kararını ezemez. Sayısal güven yerine
            eşleşen sinyaller gösterilir.
          </p>
          {ortam && (
            <Uyari ton="bilgi" baslik="Ortam sorunu">
              Test koşmadan önce ortam sağlıksızdı ya da ağ hatası oluştu. Bu başarısızlık için onarım PR'ı ya da bug taslağı üretilmez.
            </Uyari>
          )}
          {h.gerekce && <p className="kucuk">{h.gerekce}</p>}
          {/* Kanıt kartı tam hata metnini gösteriyorsa burada tekrar edilmez. */}
          {h.hata_mesaji && !h.kanit?.hata_mesaji && <pre className="hata-mesaji">{h.hata_mesaji}</pre>}
          {h.hata_imzasi && <p className="kucuk mono soluk">imza: {h.hata_imzasi}</p>}
          <p className="kucuk soluk">
            {tarih(h.zaman)}
            {h.script_id && (
              <>
                {" · "}
                <Link to={`/kod/${encodeURIComponent(h.script_id)}`}>Üretilen test</Link>
              </>
            )}
          </p>
        </Kart>
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
                      <div className="kucuk soluk mono">
                        {sg.kod}
                        {sg.kaynak && ` · ${sg.kaynak}`}
                      </div>
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
            <Uyari ton="bilgi" baslik="LLM yorumu">
              {h.llm_yorumu}
            </Uyari>
          )}
        </Kart>

        {/* Öneri kartındaki "Git" çapası (#onarim): onarım/öneri bölümü her durumda bu kapta. Izgaranın üçüncü
            öğesi; öneri yokken kap boştur ve ızgarada yer tutmaz (styles.css .triage-oneri:empty). */}
        <div id="onarim" className="triage-oneri">
          {!ortam && h.oneri?.tur === "locator_fix" && <OnarimKarti o={h.oneri} hataId={h.id} yenile={() => void v.yenile(true)} />}
          {!ortam && h.oneri?.tur === "bug_draft" && (
            <Kart baslik="Öneri">
              <p>
                Ürün hatası adayı: bug taslağı hazırlandı ve Jira'da mükerrer araması yapıldı. Kayıt yalnızca testçi onayıyla açılır.{" "}
                <Link className="dugme dugme-birincil dugme-kucuk" to={`/bug-taslaklari/${encodeURIComponent(h.oneri.bug_draft_id)}`}>
                  Bug taslağına git
                </Link>
              </p>
              <MukerrerSatiri id={h.oneri.bug_draft_id} />
            </Kart>
          )}
          {/* 012 Ş3: test beklentisi onaylı karar tablosuyla uyuşmuyor → bug/onarım değil, case düzeltilir. */}
          {!ortam && h.alt_tur === "beklenti" && (
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
                  <Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>Koşuyu aç ({h.test_adi})</Link>
                ) : null}
              </Uyari>
            </div>
          )}
          {!h.oneri && h.oneri_yok_nedeni && h.alt_tur !== "beklenti" && (
            <Uyari ton="uyari" baslik="Öneri üretilmedi">
              {h.oneri_yok_nedeni}
            </Uyari>
          )}
        </div>
      </div>

      <KanitKarti k={h.kanit} linkler={h.kanit_linkleri} platform={h.platform} />
    </>
  );
}

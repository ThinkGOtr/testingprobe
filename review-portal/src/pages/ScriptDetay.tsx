import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { AdimEslemesi, AjanAdimi, BreakVerify, PrCheck, PullRequest, RetNedeni, ScriptDetay as Detay, YerelKontrol, YerelKontrolHatasi, YerelKontrolSinifi } from "../api/types";
import { ajanAdimiUyarla } from "../api/uyumDemoB";
import { useBildirim } from "../components/Bildirim";
import { KodGorunumu } from "../components/KodGorunumu";
import { BosDurum, Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { SCRIPT_DURUMU, scriptIsareti, scriptUretiliyor } from "../lib/etiketler";
import { ENGEL_TURU, kosuKimligiMi, mergeEngelleri, mergeOnayNotu, mergeUyarilari, RET_NEDENI, YEREL_SINIF } from "../lib/kapi";
import { saat, tarih } from "../lib/format";

const ASAMA_ADI = { baseline: "Bayraksız (yeşil olmalı)", broken: "BREAK_CAMPAIGN=1 (kırmızı olmalı)", restored: "Bayrak kaldırıldı (yeşil olmalı)" } as const;
const SONUC = {
  pending: { etiket: "Bekliyor", ikon: "○" },
  running: { etiket: "Koşuyor", ikon: "◌" },
  passed: { etiket: "Yeşil", ikon: "✓" },
  failed: { etiket: "Kırmızı", ikon: "✗" },
} as const;

/**
 * Koşu bağlantısı. Yalnızca koşu tablosundaki (UUID) koşular `/kosular/:id` sayfasına bağlanır;
 * yerel kontrol ve kırarak doğrulama koşuları toolchain etiketiyle (cg-…) kalır ve koşu kaydı/artefakt
 * ucu yoktur: etiket düz metin gösterilir (422 veren bağlantı üretilmez).
 */
export function KosuBaglantisi({ id, etiket }: { id: string; etiket?: string }) {
  if (kosuKimligiMi(id)) {
    return (
      <Link to={`/kosular/${encodeURIComponent(id)}`} title={`Koşu kimliği: ${id}`}>
        {etiket ?? (/^[0-9a-f]{8}-/i.test(id) ? `koşu ${id.slice(0, 8)}` : id)}
      </Link>
    );
  }
  return (
    <span className="mono" title="Toolchain koşu etiketi: bu koşu koşu listesine alınmadı, raporu portaldan açılamaz.">
      {id}
    </span>
  );
}

/** Kırık koşunun sınıfı: aşamada yoksa core'un "assertion dışında bir nedenle kırmızı (sınıf)" gerekçesinden. */
function kirikSinifi(a: BreakVerify["asamalar"][number], bv: BreakVerify): YerelKontrolSinifi | "bilinmiyor" | null {
  if (a.sinif) return a.sinif;
  if (bv.durum === "failed" && bv.neden && /assertion dışında/i.test(bv.neden)) {
    const m = /\(([a-z_]+)\)/.exec(bv.neden);
    const s = m?.[1];
    return s === "locator" || s === "ortam" || s === "derleme" ? s : "bilinmiyor";
  }
  return null;
}

export function KirmaZaman({ bv, uygulanmaz = false }: { bv: BreakVerify; uygulanmaz?: boolean }) {
  return (
    <ol className="kirma-zaman" aria-label="Kırarak doğrulama zaman çizelgesi">
      {bv.asamalar.map((a) => {
        // Defect adayında kırarak doğrulama koşmaz: başlamamış aşama "Bekliyor" (koşacak) değil "Uygulanmaz".
        if (uygulanmaz && a.sonuc === "pending") {
          return (
            <li key={a.ad} className="kirma-asama kirma-uygulanmaz" data-testid="kirma-uygulanmaz">
              <span className="kirma-ikon" aria-hidden="true">
                –
              </span>
              <div>
                <div className="kirma-ad">{ASAMA_ADI[a.ad]}</div>
                <div className="kucuk soluk">Uygulanmaz (defect adayı)</div>
              </div>
            </li>
          );
        }
        const beklenen = a.ad === "broken" ? "failed" : "passed";
        const uyumlu = a.sonuc === beklenen;
        const sinif = a.ad === "broken" && a.sonuc === "failed" ? kirikSinifi(a, bv) : null;
        // Kırık koşu kırmızı ama assertion dışı (locator/ortam…): hata yakalama kanıtı değildir.
        const sonucsuz = sinif !== null && sinif !== "defect_adayi";
        return (
          <li key={a.ad} className={`kirma-asama kirma-${a.sonuc}${sonucsuz ? " kirma-sonucsuz" : ""}`}>
            <span className="kirma-ikon" aria-hidden="true">
              {sonucsuz ? "⚠" : SONUC[a.sonuc].ikon}
            </span>
            <div>
              <div className="kirma-ad">{ASAMA_ADI[a.ad]}</div>
              <div className="kucuk">
                {sonucsuz ? (
                  <span className="uyari-metin">
                    Kırmızı ama assertion dışı ({sinif === "bilinmiyor" ? "sınıflandırılamadı" : YEREL_SINIF[sinif as YerelKontrolSinifi].etiket.toLowerCase()}) — kanıt
                    sayılmaz
                  </span>
                ) : (
                  <>
                    {SONUC[a.sonuc].etiket}
                    {(a.sonuc === "passed" || a.sonuc === "failed") && (uyumlu ? " · beklendiği gibi" : " · beklenmeyen sonuç")}
                  </>
                )}
                {a.run_id && (
                  <>
                    {" · "}
                    <KosuBaglantisi id={a.run_id} />
                  </>
                )}
                {a.zaman && <span className="soluk"> · {saat(a.zaman)}</span>}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function AjanAdimlari({ adimlar, canli }: { adimlar: AjanAdimi[]; canli: boolean }) {
  const [secili, setSecili] = useState<number | null>(null);
  const aktif = adimlar.find((a) => a.sira === secili) ?? adimlar[adimlar.length - 1];
  if (adimlar.length === 0) {
    return <BosDurum baslik={canli ? "Ajan başlıyor…" : "Ajan adımı yok."} />;
  }
  return (
    <div className="ajan">
      <ol className="ajan-adimlar" aria-label="Ajan adımları">
        {adimlar.map((a) => (
          <li key={a.sira}>
            <button
              type="button"
              className={`ajan-adim${aktif?.sira === a.sira ? " aktif" : ""}`}
              aria-pressed={aktif?.sira === a.sira}
              onClick={() => setSecili(a.sira)}
            >
              <span className="mono soluk">
                Adım {a.sira}
                {a.step_id && <span title="Case adımı referansı"> · case {a.step_id}</span>}
              </span>
              <span>{a.aciklama}</span>
              <span className="kucuk mono">
                {a.po && a.method ? `${a.po}.${a.method}(${a.args.map((x) => JSON.stringify(x)).join(", ")})` : a.arac}
              </span>
              {a.verified !== null && (
                <span className={`kucuk ${a.verified ? "ok-metin" : "hata-metin"}`}>{a.verified ? "✓ snapshot'ta doğrulandı" : "✗ doğrulanamadı"}</span>
              )}
            </button>
          </li>
        ))}
        {canli && (
          <li className="soluk kucuk" role="status">
            <span className="donen donen-kucuk" aria-hidden="true" /> Ajan çalışıyor…
          </li>
        )}
      </ol>
      <figure className="ajan-ekran">
        {aktif?.ekran_goruntusu_url ? (
          <img src={aktif.ekran_goruntusu_url} alt={`Adım ${aktif.sira} ekran görüntüsü: ${aktif.aciklama}`} />
        ) : (
          <div className="ekran-yok">Ekran görüntüsü yok</div>
        )}
        <figcaption className="kucuk soluk">
          Adım {aktif?.sira}
          {aktif?.step_id && ` (case ${aktif.step_id})`} · {aktif?.arac} · {saat(aktif?.zaman)}. Görüntü yalnızca izleme içindir; modele gönderilmez.
        </figcaption>
        {aktif?.ham_cikti && (
          <details className="ham-cikti">
            <summary className="kucuk">Ham çıktı</summary>
            <pre className="kucuk mono">{aktif.ham_cikti}</pre>
          </details>
        )}
      </figure>
    </div>
  );
}

const DEGER = (x: unknown) => JSON.stringify(x);

const normal = (x: string) => x.toLocaleLowerCase("tr").replace(/\s+/g, " ");

/** `d`'nin `metin`de sayı/kelime sınırında geçtiği ilk konum ("0,00 TL" "150,00 TL"nin içinde sayılmaz). */
export function sinirliKonum(metin: string, d: string): number {
  const icinde = (c: string | undefined) => !!c && /[\p{L}\p{N}.,]/u.test(c);
  for (let i = metin.indexOf(d); i >= 0; i = metin.indexOf(d, i + 1)) {
    const once = metin[i - 1];
    const sonra = metin[i + d.length];
    const onceSinir = !icinde(once) || !/[\p{L}\p{N}]/u.test(d[0] ?? "");
    const sonraSinir = !(sonra && /[\p{L}\p{N}]/u.test(sonra)) || !/[\p{L}\p{N}]/u.test(d[d.length - 1] ?? "");
    if (onceSinir && sonraSinir) return i;
  }
  return metin.indexOf(d);
}

/** Onaylı case cümlesinde, assertion argümanının geçtiği yeri vurgular (§8.4 adım 3: değer metinde geçer). */
export function KaynakMetni({ metin, args }: { metin: string; args: unknown[] }) {
  const tek = metin.replace(/\s+/g, " ");
  for (const a of args) {
    if (typeof a !== "string" && typeof a !== "number") continue;
    const d = String(a).replace(/\s+/g, " ").trim();
    if (!d) continue;
    const i = sinirliKonum(normal(tek), normal(d));
    if (i < 0) continue;
    return (
      <q className="kucuk">
        {tek.slice(0, i)}
        <mark className="kaynak-deger">{tek.slice(i, i + d.length)}</mark>
        {tek.slice(i + d.length)}
      </q>
    );
  }
  return <q className="kucuk">{tek}</q>;
}

function EslemeTablosu({ eslemeler }: { eslemeler: AdimEslemesi[] }) {
  return (
    <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Eşlenen adımlar tablosu">
      <table className="tablo tablo-sik">
        <thead>
          <tr>
            <th scope="col" className="sayi">
              #
            </th>
            <th scope="col">Case adımı</th>
            <th scope="col">Page object metodu</th>
            <th scope="col">Tür</th>
            <th scope="col">Uygulamada</th>
            <th scope="col">Değerin kaynağı (onaylı case)</th>
          </tr>
        </thead>
        <tbody>
          {eslemeler.map((e) => (
            <tr key={`${e.adim_no}-${e.method}`}>
              <td className="sayi mono" data-etiket="#">
                {e.adim_no}
              </td>
              <td className="mono" data-etiket="Case adımı">
                {e.step_id ?? "—"}
              </td>
              <td className="mono" data-etiket="Metot">
                {e.po}.{e.method}({e.args.map(DEGER).join(", ")})
              </td>
              <td data-etiket="Tür">{e.beklenen ? <Cip ton="vurgu">Doğrulama</Cip> : <Cip>Eylem</Cip>}</td>
              <td data-etiket="Uygulamada">
                {e.beklenen ? (
                  // Doğrulamanın `verified`'ı değerin onaylı case metninde bulunmasıdır (kaynak
                  // denetimi), uygulamada gözlem değil: sonucu yerel kontrol belirler.
                  <span className="soluk kucuk">yerel kontrolde koşulur</span>
                ) : e.verified ? (
                  <span className="ok-metin">✓ {e.dogrulama_notu ?? "doğrulandı"}</span>
                ) : (
                  <span className="hata-metin">✗ doğrulanmadı</span>
                )}
              </td>
              <td data-etiket="Kaynak">
                {e.beklenen ? (
                  e.args.length === 0 ? (
                    <span className="soluk kucuk">Değer yok (parametresiz doğrulama)</span>
                  ) : e.kaynak_metin ? (
                    <KaynakMetni metin={e.kaynak_metin} args={e.args} />
                  ) : (
                    <span className="soluk kucuk">Kaynak cümlesi kaydedilmedi</span>
                  )
                ) : (
                  <span className="soluk">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const ISARET = (b: boolean | null) => (b === null ? "—" : b ? "✓" : "✗");

export interface HataGrubu {
  hata: YerelKontrolHatasi;
  adet: number;
}

/** repeat-each tekrarlarındaki aynı hatayı tek satırda toplar ("3/3 tekrarda aynı hata"). */
export function hatalariGrupla(hatalar: YerelKontrolHatasi[]): HataGrubu[] {
  const gruplar = new Map<string, HataGrubu>();
  for (const h of hatalar) {
    const anahtar = JSON.stringify([h.test_adi, h.adim, h.beklenen, h.gerceklesen, h.hata_mesaji?.split("\n")[0] ?? null]);
    const g = gruplar.get(anahtar);
    const n = h.tekrar && h.tekrar > 0 ? h.tekrar : 1; // core zaten topladıysa satır `tekrar` taşır
    if (g) g.adet += n;
    else gruplar.set(anahtar, { hata: h, adet: n });
  }
  return [...gruplar.values()];
}

/** Defect adayı için kısa, iş diliyle özet: "Yerel kontrol: beklenen 0, gerçekleşen 1 (3/3 tekrar)". */
export function defectOzeti(yk: YerelKontrol | null): string | null {
  if (!yk || yk.basarisiz.length === 0) return null;
  const [g] = hatalariGrupla(yk.basarisiz);
  const h = g.hata;
  if (!h.beklenen && !h.gerceklesen) return null;
  const tekrar = yk.tekrar > 0 ? ` (${g.adet}/${Math.max(yk.tekrar, g.adet)} tekrar)` : g.adet > 1 ? ` (${g.adet} tekrar)` : "";
  return `Yerel kontrol: beklenen ${h.beklenen ?? "—"}, gerçekleşen ${h.gerceklesen ?? "—"}${tekrar}.`;
}

export function YerelKontrolKarti({ yk, uretiliyor }: { yk: YerelKontrol | null; uretiliyor: boolean }) {
  if (!yk) return <BosDurum baslik={uretiliyor ? "Yerel kontrol, eşleme bitince başlar." : "Yerel kontrol yapılmadı."} />;
  const sinif = yk.sinif ? YEREL_SINIF[yk.sinif] : null;
  return (
    <div className="yerel-kontrol">
      <ul className="kontrol-liste" aria-label="Yerel kontrol adımları">
        <li>
          <span aria-hidden="true">{ISARET(yk.tsc)}</span> tsc --strict
        </li>
        <li>
          <span aria-hidden="true">{ISARET(yk.eslint)}</span> eslint --no-inline-config
        </li>
        <li>
          <span aria-hidden="true">{ISARET(yk.ast_guard)}</span> AST koruması
        </li>
        <li>
          <span aria-hidden="true">{yk.sonuc === null ? "◌" : yk.sonuc === "passed" ? "✓" : "✗"}</span> Playwright
          {yk.tekrar > 0 && ` --repeat-each=${yk.tekrar}`}
          {yk.toplam !== null && yk.toplam > 0 && <span className="soluk"> · {yk.gecen ?? 0}/{yk.toplam} geçti</span>}
          {yk.sonuc === null && <span className="soluk"> (sürüyor)</span>}
          {yk.run_id && (
            <>
              {" · "}
              <KosuBaglantisi id={yk.run_id} etiket="koşu" />
            </>
          )}
        </li>
      </ul>
      {sinif && (
        <div className={`uyari-kutusu uyari-${sinif.ton === "hata" ? "hata" : sinif.ton === "basari" ? "basari" : "bilgi"}`} role="note" data-testid="yerel-sinif">
          <strong>{sinif.etiket}</strong>
          <div>{yk.aciklama ?? sinif.aciklama}</div>
        </div>
      )}
      {yk.hata && <p className="kucuk">{yk.hata}</p>}
      {yk.duzeltme_turu > 0 && <p className="kucuk soluk">{yk.duzeltme_turu} yeniden eşleme turu yapıldı (beklenen değerler değişmedi).</p>}
      {yk.basarisiz.length > 0 && (
        <ul className="duz-liste" aria-label="Başarısız testler">
          {hatalariGrupla(yk.basarisiz).map(({ hata: h, adet }, i) => (
            <li key={i}>
              <div>
                {h.test_adi}
                {adet > 1 && (
                  <span className="soluk kucuk">
                    {" "}
                    · {adet}/{Math.max(yk.tekrar, adet)} tekrarda aynı hata
                  </span>
                )}
              </div>
              {h.adim && <div className="kucuk soluk">Adım: {h.adim}</div>}
              {(h.beklenen || h.gerceklesen) && (
                <div className="kucuk">
                  Beklenen: <span className="mono">{h.beklenen ?? "—"}</span> · Gerçekleşen: <span className="mono">{h.gerceklesen ?? "—"}</span>
                </div>
              )}
              {h.hata_mesaji && <pre className="hata-mesaji">{h.hata_mesaji}</pre>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const CHECK_IKON: Record<PrCheck["durum"], { ikon: string; etiket: string; ton: "basari" | "hata" | "bilgi" | "notr" }> = {
  passed: { ikon: "✓", etiket: "geçti", ton: "basari" },
  failed: { ikon: "✗", etiket: "kırmızı", ton: "hata" },
  error: { ikon: "✗", etiket: "hata", ton: "hata" },
  pending: { ikon: "◌", etiket: "bekliyor", ton: "bilgi" },
  skipped: { ikon: "–", etiket: "atlandı", ton: "notr" },
};

function CheckListesi({ checks }: { checks: PrCheck[] }) {
  return (
    <ul className="kontrol-liste" aria-label="PR check'leri">
      {checks.map((c) => (
        <li key={c.ad}>
          <span aria-hidden="true" className={c.durum === "passed" ? "ok-metin" : c.durum === "failed" || c.durum === "error" ? "hata-metin" : undefined}>
            {CHECK_IKON[c.durum].ikon}
          </span>{" "}
          <Baglanti href={c.url}>
            <span className="mono">{c.ad}</span>
          </Baglanti>{" "}
          <span className="soluk kucuk">
            {CHECK_IKON[c.durum].etiket}
            {c.zorunlu && " · zorunlu"}
            {c.aciklama && ` · ${c.aciklama}`}
          </span>
        </li>
      ))}
    </ul>
  );
}

const PUSH_CI_METNI: Record<NonNullable<PullRequest["ci"]> | "yok", { metin: string; ton: "basari" | "hata" | "bilgi" | "notr" }> = {
  pending: { metin: "koşuyor", ton: "bilgi" },
  passed: { metin: "yeşil", ton: "basari" },
  failed: { metin: "kırmızı", ton: "hata" },
  yok: { metin: "henüz başlamadı", ton: "notr" },
};

/**
 * Birleşmiş PR'ın CI gösterimi. PR'ın zorunlu check'leri merge anında yeşildi (forge kuralı); merge
 * sonrası main'deki push CI ayrı bir koşudur ve PR check'i gibi gösterilmez ("bekliyor · zorunlu"
 * birleşmiş bir PR'ın yanında kapı hâlâ açıkmış gibi okunur). Hızlı ileri merge'de (LocalForge
 * varsayılanı) merge commit'i PR head'iyle aynıdır: core'un o commit için verdiği check'ler push
 * CI'ındır. Merge commit'i farklıysa check'ler PR head'inindir (merge öncesi sonuç).
 */
export function BirlesmisPrCi({ pr }: { pr: PullRequest }) {
  const checks = pr.checks ?? [];
  const ayriMergeCommit = !!pr.merge_sha && !!pr.head_sha && pr.merge_sha !== pr.head_sha;
  const sha = (pr.merge_sha || pr.head_sha || "").slice(0, 7);
  const durum = PUSH_CI_METNI[pr.ci ?? "yok"];
  return (
    <div className="kucuk" data-testid="push-ci">
      {ayriMergeCommit ? (
        <>
          {checks.length > 0 && (
            <>
              <div className="soluk">PR check'leri (merge öncesi, head {pr.head_sha.slice(0, 7)}):</div>
              <CheckListesi checks={checks.map((c) => ({ ...c, zorunlu: null }))} />
            </>
          )}
          <p>
            <strong>main üzerinde push CI</strong> (merge commit <span className="mono">{sha}</span>):{" "}
            <Link to="/kosular?tetik=push">Koşular'da izle</Link>
          </p>
        </>
      ) : (
        <>
          <p>
            <strong>main üzerinde push CI</strong>
            {sha && (
              <>
                {" "}
                (commit <span className="mono">{sha}</span>)
              </>
            )}
            : <Cip ton={durum.ton}>{durum.metin}</Cip> · <Link to="/kosular?tetik=push">Koşular'da izle</Link>
          </p>
          {checks.length > 0 && <CheckListesi checks={checks.map((c) => ({ ...c, zorunlu: null }))} />}
        </>
      )}
    </div>
  );
}

/** Core gerekçesindeki teknik önekleri ve sondaki noktayı temizler ("Yerel CI başarısız: run — X." → "X"). */
export function nedenTemizle(n: string | null | undefined): string | null {
  if (!n) return null;
  return n
    .replace(/^Yerel CI başarısız:\s*run\s*—\s*/i, "Yerel kontrol: ")
    .replace(/^Yerel CI/i, "Yerel kontrol")
    .replace(/[.\s]+$/, "");
}

function kirmaNedeni(n: string | null | undefined): string {
  const t = nedenTemizle(n);
  if (!t) return "Doğrulama tamamlanamadı: bayraksız koşu yeşil değildi ya da ortam hatası oldu";
  return /tamamlanamadı/i.test(t) ? t : `Doğrulama tamamlanamadı: ${t}`;
}

/** Defect adayında ajanın sepette gördüğü an: sepete ilişkin son ekran görüntülü adım (yoksa son görüntülü adım). */
export function ajaninSepeti(adimlar: AjanAdimi[]): AjanAdimi | null {
  const goruntulu = adimlar.filter((a) => a.ekran_goruntusu_url);
  return [...goruntulu].reverse().find((a) => /sepet|cart/i.test(`${a.aciklama} ${a.po ?? ""}`)) ?? goruntulu[goruntulu.length - 1] ?? null;
}

/** Satır içi `kod` parçalarını mono gösterir (HTML yorumlanmaz; metin React ile kaçışlanır). */
function SatirIci({ metin }: { metin: string }) {
  const parcalar = metin.split(/(`[^`]+`)/g);
  return (
    <>
      {parcalar.map((p, i) =>
        p.startsWith("`") && p.endsWith("`") && p.length > 1 ? (
          <code key={i}>{p.slice(1, -1)}</code>
        ) : (
          <span key={i}>{p.replace(/\*\*/g, "")}</span>
        ),
      )}
    </>
  );
}

/**
 * PR açıklamasının (core `pull_request.govde`, Markdown) güvenli, küçük bir alt kümesi: başlık, madde,
 * tablo satırı (mono), satır içi kod. Ham HTML hiçbir zaman yorumlanmaz.
 */
export function PrAciklamasi({ govde }: { govde: string }) {
  const bloklar: JSX.Element[] = [];
  let maddeler: string[] = [];
  let tablo: string[] = [];
  const bosalt = () => {
    if (maddeler.length) {
      const m = maddeler;
      bloklar.push(
        <ul key={`m${bloklar.length}`} className="duz-liste">
          {m.map((x, i) => (
            <li key={i}>
              <SatirIci metin={x} />
            </li>
          ))}
        </ul>,
      );
      maddeler = [];
    }
    if (tablo.length) {
      bloklar.push(
        <pre key={`t${bloklar.length}`} className="pr-govde-tablo mono">
          {tablo.join("\n")}
        </pre>,
      );
      tablo = [];
    }
  };
  for (const ham of govde.split("\n")) {
    const satir = ham.trimEnd();
    if (/^\s*[-*] /.test(satir)) {
      if (tablo.length) bosalt();
      maddeler.push(satir.replace(/^\s*[-*] /, ""));
      continue;
    }
    if (satir.trimStart().startsWith("|")) {
      if (maddeler.length) bosalt();
      tablo.push(satir);
      continue;
    }
    bosalt();
    if (!satir.trim()) continue;
    const baslik = /^(#{1,6})\s+(.*)$/.exec(satir);
    if (baslik) {
      bloklar.push(
        <p key={`b${bloklar.length}`}>
          <strong>
            <SatirIci metin={baslik[2]} />
          </strong>
        </p>,
      );
    } else {
      bloklar.push(
        <p key={`p${bloklar.length}`}>
          <SatirIci metin={satir} />
        </p>,
      );
    }
  }
  bosalt();
  return <div className="pr-govde kucuk">{bloklar}</div>;
}

const RET_SECENEKLERI = Object.entries(RET_NEDENI) as [RetNedeni, string][];

export function ScriptDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.script(id), [id]);
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => void v.yenile(true), 300);
  // Uyarıların (zayıf test, kırma yapılmadı) açık kabulü: hangi head için verildiyse yalnız ona geçerli.
  const [kabulHead, setKabulHead] = useState<string | null>(null);
  // Hata hangi eylemden geldi: PR eylemlerinin hatası PR kartında, düğmenin yanında gösterilir.
  const [hataYeri, setHataYeri] = useState<"pr" | "genel">("genel");
  const [retNedeni, setRetNedeni] = useState<RetNedeni | "">("");
  const [retNotu, setRetNotu] = useState("");

  useOlay(
    (o) => {
      if (o.type === "agent.step" && v.veri) {
        // Mock ve core olayı aynı uyarlayıcıdan geçer; sırası yoksa sona eklenir.
        const adim = ajanAdimiUyarla(o.data, v.veri.adimlar.length + 1);
        if (!v.veri.adimlar.some((a) => a.sira === adim.sira)) {
          v.setVeri({ ...v.veri, adimlar: [...v.veri.adimlar, adim] });
        }
        return;
      }
      sessiz();
    },
    ["agent.step", "pr.opened", "pr.merged", "ci.status", "script.updated"],
    id,
  );

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />;
  const s: Detay | undefined = v.veri;
  if (!s) return null;
  const d = SCRIPT_DURUMU[s.durum] ?? { etiket: s.durum, ton: "notr" as const };
  const prAcik = s.pr?.durum === "open";
  const prBirlesti = s.pr?.durum === "merged";
  /** Kod üretiminin defect adayı (tutarlı assertion farkı): kırarak doğrulama kapalıdır (§2 adım 6, 12). */
  const defectAdayi = s.yerel_sinif === "defect_adayi";
  const engeller = mergeEngelleri(s);
  const uyarilar = mergeUyarilari(s);
  const kabul = !!s.pr && kabulHead === s.pr.head_sha;
  const kapiAcik = prAcik && engeller.length === 0;
  const mergeHazir = kapiAcik && (uyarilar.length === 0 || kabul);
  const onayNotu = uyarilar.length ? mergeOnayNotu(s) : null;
  const defectMetni = s.engel?.tur === "defect_candidate" ? defectOzeti(s.yerel_kontrol) : null;
  const sepetAdimi = s.engel?.tur === "defect_candidate" ? ajaninSepeti(s.adimlar) : null;
  const isaret = scriptIsareti(s);
  const uretiliyor = scriptUretiliyor(s.durum);
  const sinif = s.yerel_sinif && s.yerel_sinif !== "gecti" ? YEREL_SINIF[s.yerel_sinif] : null;

  async function eylem(fn: () => Promise<unknown>, mesaj: string | ((r: unknown) => string), yer: "pr" | "genel" = "genel") {
    setHataYeri(yer);
    // 409 (PR içeriği/head değişti): ekran yeniden yüklenir, kullanıcı yeniden inceler.
    const r = await islem.calistir(fn, { cakismada: () => void v.yenile(true) });
    if (r !== undefined) {
      bildir(typeof mesaj === "string" ? mesaj : mesaj(r));
      void v.yenile(true);
    }
  }

  return (
    <>
      <SayfaBasligi
        ust={<Link to="/kod">← Kod üretimi</Link>}
        baslik={s.baslik}
        aciklama={
          <span className="satir-ogeler">
            <Cip ton={d.ton}>{d.etiket}</Cip>
            {isaret && <Cip ton={isaret.ton}>{isaret.etiket}</Cip>}
            {sinif && <Cip ton={sinif.ton}>{sinif.etiket}</Cip>}
            <ReplayRozeti mode={s.mode} />
            {s.requirement_key && <span className="mono">{s.requirement_key}</span>}
            <span className="soluk">{tarih(s.olusturma)}</span>
          </span>
        }
      />
      {s.engel ? (
        <Uyari ton={s.engel.tur === "defect_candidate" ? "hata" : "uyari"} baslik={`İnsana düştü: ${ENGEL_TURU[s.engel.tur] ?? s.engel.tur}`}>
          {defectMetni ?? nedenTemizle(s.engel.neden ?? s.hata) ?? "Ayrıntı yerel kontrol ve eşleme kartlarında."}
          {sepetAdimi?.ekran_goruntusu_url && (
            <>
              {" "}
              <a href={sepetAdimi.ekran_goruntusu_url} target="_blank" rel="noopener noreferrer">
                Ajanın gördüğü sepet (adım {sepetAdimi.sira})
              </a>
            </>
          )}
        </Uyari>
      ) : (
        s.hata && <HataKutusu hata={s.hata} />
      )}
      {s.uyarilar.length > 0 && (
        <Uyari ton="bilgi">
          <ul className="duz-liste kucuk">
            {s.uyarilar.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </Uyari>
      )}
      {islem.hata && hataYeri === "genel" && <HataKutusu hata={islem.hata} />}

      <Kart baslik="Ajan adımları (Playwright MCP)" eylemler={uretiliyor && <Cip ton="bilgi">Adımlar geliyor</Cip>}>
        {s.mode === "replay" && (
          <p className="kucuk soluk" data-testid="replay-bandi">
            <span className="rozet rozet-replay">REPLAY</span> Model kararları kayıtlı golden çıktıdan; tarayıcı adımları çalışan uygulamada yeniden
            {uretiliyor ? " koşturuluyor (canlı model değil)." : " koşturuldu."}
          </p>
        )}
        <AjanAdimlari adimlar={s.adimlar} canli={uretiliyor} />
      </Kart>

      <Kart baslik="Eşlenen adımlar (adım → page object)">
        <p className="soluk kucuk">
          Her adım sembol tablosundaki bir metoda eşlendi; doğrulama değerleri onaylı case metninde geçmek zorundadır. Kod bu tablodan şablonla üretilir.
        </p>
        {s.eslemeler.length ? (
          <EslemeTablosu eslemeler={s.eslemeler} />
        ) : (
          <BosDurum baslik={uretiliyor ? "Eşleme ajan bitince yazılır." : "Eşleme kaydı yok."} />
        )}
      </Kart>

      <Kart baslik="Yerel kontrol">
        <YerelKontrolKarti yk={s.yerel_kontrol} uretiliyor={uretiliyor} />
      </Kart>

      <div className="iki-sutun">
        <Kart baslik="Pull request">
          {s.pr ? (
            <>
              <p>
                <span className="mono">#{s.pr.number}</span> {s.pr.baslik}
              </p>
              <p className="satir-ogeler">
                <Cip ton={s.pr.durum === "merged" ? "basari" : s.pr.durum === "open" ? "vurgu" : "notr"}>
                  {s.pr.durum === "merged" ? "Birleşti" : s.pr.durum === "open" ? "Açık" : "Kapalı"}
                </Cip>
                {prBirlesti ? (
                  <Cip ton="basari" title="Forge, zorunlu check'ler yeşil değilken merge etmez; PR'ın CI sonucu merge anında dondurulur.">
                    PR CI: merge öncesi yeşil
                  </Cip>
                ) : (
                  <Cip ton={s.pr.ci === "passed" ? "basari" : s.pr.ci === "failed" ? "hata" : "bilgi"}>
                    CI: {s.pr.ci === "passed" ? "yeşil" : s.pr.ci === "failed" ? "kırmızı" : s.pr.ci === "pending" ? "bekliyor" : "—"}
                  </Cip>
                )}
                <span className="mono kucuk">{s.pr.branch}</span>
                {s.pr.forge && <span className="kucuk soluk">{s.pr.forge === "local" ? "LocalForge" : "GitHub"}</span>}
              </p>
              {prBirlesti ? (
                <BirlesmisPrCi pr={s.pr} />
              ) : (
                s.pr.checks && s.pr.checks.length > 0 && <CheckListesi checks={s.pr.checks} />
              )}
              {s.pr.url && (
                <p>
                  <Baglanti href={s.pr.url}>PR'ı aç</Baglanti>
                </p>
              )}
              {s.pr.govde && (
                <details className="pr-aciklamasi" data-testid="pr-aciklamasi">
                  <summary>PR açıklaması</summary>
                  <PrAciklamasi govde={s.pr.govde} />
                </details>
              )}
              {prAcik && s.pr.dal?.geride && (
                <Uyari ton="uyari" baslik="Dal main'in gerisinde">
                  {s.pr.dal.guncelleme
                    ? `Dal güncelleniyor (${s.pr.dal.guncelleme}).`
                    : (s.pr.dal.neden ?? "Başka bir PR merge edildi; önce dalı güncelleyin. Güncelleme yeni head ve yeni CI üretir, yeniden incelemeniz gerekir.")}
                  <div className="eylemler">
                    <IslemDugmesi
                      roller={["engineer"]}
                      tur="ikincil"
                      calisiyor={islem.calisiyor}
                      disabled={!!s.pr.dal.guncelleme}
                      onClick={() => s.pr && eylem(() => api.prDaliGuncelle(s.pr!.number), "Dal güncellemesi kuyruğa alındı.", "pr")}
                    >
                      Dalı güncelle
                    </IslemDugmesi>
                  </div>
                </Uyari>
              )}
              {s.pass_at_1 !== null && <p className="kucuk">pass@1 (düzeltme turu öncesi): {s.pass_at_1 ? "✓" : "✗"}</p>}
            </>
          ) : (
            <BosDurum baslik={s.yerel_sinif === "defect_adayi" ? "PR açılmadı: defect adayı insana düştü." : "PR henüz açılmadı."}>
              {s.yerel_sinif === "defect_adayi" && s.failure_id && (
                <Link to={`/hatalar/${encodeURIComponent(s.failure_id)}`}>Triage sonucu ve bug taslağı</Link>
              )}
            </BosDurum>
          )}
          {prBirlesti && s.pr ? (
            <div className="merge-kapisi" data-testid="merge-kapisi">
              <div className="kucuk ok-metin">
                <strong>✓ Birleştirildi</strong>
                {s.pr.merge_eden && ` — ${s.pr.merge_eden}`}
                {s.pr.merge_zamani && `, ${tarih(s.pr.merge_zamani)}`}
                {s.pr.merge_sha && (
                  <>
                    {" · merge commit "}
                    <span className="mono">{s.pr.merge_sha.slice(0, 7)}</span>
                  </>
                )}
              </div>
            </div>
          ) : prAcik && (
            <div className="merge-kapisi" data-testid="merge-kapisi">
              <div className="kucuk">
                <strong>Merge kapısı</strong> {kapiAcik ? <span className="ok-metin">açık ✓</span> : <span className="soluk">kapalı</span>}
              </div>
              {engeller.length > 0 && (
                <ul className="kucuk kapi-nedenleri">
                  {engeller.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              {kapiAcik && uyarilar.length > 0 && (
                <div className="kucuk kapi-uyarilari" data-testid="merge-uyarilari">
                  <ul>
                    {uyarilar.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                  <label className="kapi-kabul">
                    <input type="checkbox" checked={kabul} onChange={(e) => setKabulHead(e.target.checked && s.pr ? s.pr.head_sha : null)} />
                    <span>Uyarıyı gördüm; {onayNotu?.startsWith("Zayıf") ? "zayıf test olarak" : "kırarak doğrulama kanıtı olmadan"} merge et (not denetime yazılır).</span>
                  </label>
                </div>
              )}
            </div>
          )}
          {s.pr && prAcik && (
            <div className="eylemler">
              <IslemDugmesi
                roller={["engineer"]}
                disabled={!mergeHazir}
                calisiyor={islem.calisiyor}
                title={
                  mergeHazir
                    ? "İnsan onaylı merge: incelediğiniz içerik ve head commit'e bağlanır"
                    : engeller.length
                      ? engeller.join(" ")
                      : "Önce uyarıyı kabul edin"
                }
                onClick={() =>
                  s.pr &&
                  eylem(
                    () => api.prBirlestir({ ...s.pr!, onay_notu: kabul ? onayNotu : null }),
                    (r) => (r as { mesaj: string }).mesaj,
                    "pr",
                  )
                }
              >
                Merge et
              </IslemDugmesi>
            </div>
          )}
          {islem.hata && hataYeri === "pr" && <HataKutusu hata={islem.hata} />}
          {s.pr && prAcik && (
            <details className="pr-ret" data-testid="pr-ret">
              <summary>Değişiklik iste / reddet</summary>
              <div className="form-alan kucuk">
                <label>
                  Ret nedeni{" "}
                  <select value={retNedeni} onChange={(e) => setRetNedeni(e.target.value as RetNedeni | "")} aria-label="Ret nedeni">
                    <option value="">Seçin…</option>
                    {RET_SECENEKLERI.map(([k, etiket]) => (
                      <option key={k} value={k}>
                        {etiket}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Not (isteğe bağlı)
                  <textarea value={retNotu} maxLength={500} rows={2} onChange={(e) => setRetNotu(e.target.value)} aria-label="Ret notu" />
                </label>
                <p className="soluk">PR kapatılır, case yeniden üretilebilir; karar ve neden denetime ve Kontrol Kulesi'ne yazılır.</p>
              </div>
              <div className="eylemler">
                {(["degisiklik_iste", "reddet"] as const).map((karar) => (
                  <IslemDugmesi
                    key={karar}
                    roller={["engineer"]}
                    tur="ikincil"
                    disabled={!retNedeni}
                    calisiyor={islem.calisiyor}
                    title={retNedeni ? undefined : "Önce ret nedeni seçin"}
                    onClick={() =>
                      s.pr &&
                      retNedeni &&
                      eylem(
                        () =>
                          api.prReview(s.pr!.number, {
                            karar,
                            ret_nedeni: retNedeni,
                            icerik_hash: s.pr!.icerik_hash,
                            head_sha: s.pr!.head_sha,
                            not: retNotu.trim() || null,
                          }),
                        karar === "reddet" ? "PR reddedildi." : "Değişiklik istendi.",
                        "pr",
                      )
                    }
                  >
                    {karar === "reddet" ? "Reddet" : "Değişiklik iste"}
                  </IslemDugmesi>
                ))}
              </div>
            </details>
          )}
        </Kart>

        <Kart
          baslik="Kırarak doğrula"
          eylemler={
            !prBirlesti && (
            <IslemDugmesi
              roller={["engineer"]}
              tur="ikincil"
              disabled={!prAcik || defectAdayi || s.break_verify.durum === "running"}
              calisiyor={s.break_verify.durum === "running"}
              title={
                defectAdayi
                  ? "Defect adayı: test zaten kırmızı (ürün hatası şüphesi). Kırarak doğrulama anlamsız; karar triage/bug taslağında."
                  : prAcik
                    ? undefined
                    : "Kırarak doğrulama için açık PR gerekir"
              }
              onClick={() => eylem(() => api.kirarakDogrula(s.id), (r) => (r as { mesaj?: string }).mesaj ?? "Kırarak doğrulama başladı.")}
            >
              {s.break_verify.durum === "not_started" ? "Kırarak doğrula" : "Yeniden doğrula"}
            </IslemDugmesi>
            )
          }
        >
          <p className="soluk kucuk">
            Koşunun bayisi için kampanya kuralı BREAK_CAMPAIGN ile bozulur (diğer bayiler ve ajan etkilenmez); test kırmızıya dönmezse "zayıf test" sayılır.
          </p>
          {defectAdayi && (
            <Uyari ton="bilgi" baslik="Kırarak doğrulama kapalı">
              Yerel kontrol bu testi assertion farkıyla kırmızı buldu (defect adayı). Uygulama zaten beklenenden farklı davranıyor; kırma
              kanıt üretmez. Hata triage'a gitti; bug taslağı ve testçi kararı triage sayfasında.
            </Uyari>
          )}
          <KirmaZaman bv={s.break_verify} uygulanmaz={defectAdayi} />
          {s.break_verify.durum === "passed" && <Uyari ton="basari">Test hata yakalıyor ✓</Uyari>}
          {(s.zayif_test || s.break_verify.durum === "weak") && (
            <Uyari ton="uyari">
              Zayıf test: kırılmış uygulamada da yeşil kaldı. BREAK_CAMPAIGN yalnızca kampanya kuralını bozar; kampanya dışı davranışı doğrulayan testte
              bu beklenir. Merge engellenmez, kabul notu denetime yazılır.
            </Uyari>
          )}
          {s.break_verify.durum === "failed" && (
            <Uyari ton="uyari">
              {kirmaNedeni(s.break_verify.neden)}. Koşu etiketleriyle
              inceleyip yeniden deneyin.
            </Uyari>
          )}
        </Kart>
      </div>

      <Kart baslik="Üretilen test dosyası">
        {s.kod ? <KodGorunumu kod={s.kod} dosya={s.dosya_yolu} /> : <BosDurum baslik="Kod henüz üretilmedi." />}
      </Kart>
    </>
  );
}

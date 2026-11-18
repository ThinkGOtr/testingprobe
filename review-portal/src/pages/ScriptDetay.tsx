import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { AdimEslemesi, AjanAdimi, BreakVerify, MusteriCi, PrCheck, PullRequest, RetNedeni, ScriptDetay as Detay, YerelKontrol, YerelKontrolHatasi, YerelKontrolSinifi } from "../api/types";
import { ajanAdimiUyarla, kontrolAdimiGecti } from "../api/uyumDemoB";
import { useBildirim } from "../components/Bildirim";
import { KodGorunumu } from "../components/KodGorunumu";
import { DilCakismasiKutusu, dilCakismasiMi, uretimBildirimi } from "../components/UretimSonuclari";
import { BosDurum, Cip, Baglanti, HataKutusu, KayitHatasi, IslemDugmesi, Kart, ReplayRozeti, Uyari, Yukleniyor } from "../components/ui";
import { DurumCipi, EylemCubugu, Kimlik, KisaDeger, TabloSarici } from "../components/tasarim";
import { DetaySayfasi, OzetKarti, type DetaySekmesi, type KirintiHalkasi } from "../components/DetaySayfasi";
import { caseCapasi } from "../components/CaseKarti";
import "../stiller/detay-script.css";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { useIzin } from "../auth";
import { SCRIPT_DURUMU, scriptIsareti, scriptUretiliyor, type Ton } from "../lib/etiketler";
import { ENGEL_TURU, kosuKimligiMi, mergeEngelleri, mergeOnayNotu, mergeUyarilari, RET_NEDENI, YEREL_SINIF } from "../lib/kapi";
import { saat, tarih } from "../lib/format";
import { PlatformRozeti } from "../components/Platform";
import { OTOMATIK_TETIK_ACIKLAMA, OTOMATIK_TETIK_ROZETI, VERI_DEGISTI_METNI, veriDegistiGecerli } from "./Kod";
import { DepoCipi } from "../components/Depo";
import { aracEtiketi, checkEtiketi, dikeyEkranMi, uygulamaPlatformuMu, type Platform } from "../lib/platform";
import { DilRozeti, KurulumBilgisi } from "../components/Dil";
import { KurulumPrEylemi } from "../components/KurulumPrEylemi";
import { DIL_CATISI, DIL_ETIKETI, gecerliDiller, KIRARAK_DOGRULANMADI, KIRARAK_DOGRULANMADI_ACIKLAMA, kontrolAdimiEtiketi, kontrolAdimlari, kontrolZinciri, kosuAraci, type Dil, type DilDurumu } from "../lib/dil";
import { vurguDili } from "../lib/vurgula";
import { useCapayaKaydir } from "../lib/capa";
import { useOrtamlar } from "../components/Ortam";
import { ortamMetni } from "../lib/ortam";

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

export function KirmaZaman({ bv, uygulanmaz = false, yapilmadi = false }: { bv: BreakVerify; uygulanmaz?: boolean; yapilmadi?: boolean }) {
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
        // Merge edilmiş PR'da hiç koşmamış aşama "Bekliyor" değil "Yapılmadı" (IA-14): artık koşmayacak.
        if (yapilmadi && a.sonuc === "pending") {
          return (
            <li key={a.ad} className="kirma-asama kirma-uygulanmaz" data-testid="kirma-yapilmadi">
              <span className="kirma-ikon" aria-hidden="true">
                –
              </span>
              <div>
                <div className="kirma-ad">{ASAMA_ADI[a.ad]}</div>
                <div className="kucuk soluk">Yapılmadı</div>
              </div>
            </li>
          );
        }
        const beklenen = a.ad === "broken" ? "failed" : "passed";
        const uyumlu = a.sonuc === beklenen;
        const sinif = a.ad === "broken" && a.sonuc === "failed" ? kirikSinifi(a, bv) : null;
        // Kırık koşu kırmızı ama assertion dışı (locator/ortam…): hata yakalama kanıtı değildir.
        const sonucsuz = sinif !== null && sinif !== "defect_adayi";
        // Beklenenin tersi (ör. kırık uygulamada yeşil): yeşil tik "sorun yok" diye okunmasın.
        const beklenmedik = (a.sonuc === "passed" || a.sonuc === "failed") && !uyumlu;
        const uyari = sonucsuz || beklenmedik;
        return (
          <li key={a.ad} className={`kirma-asama kirma-${a.sonuc}${uyari ? " kirma-sonucsuz" : ""}`} data-beklenmedik={beklenmedik || undefined}>
            <span className="kirma-ikon" aria-hidden="true">
              {uyari ? "⚠" : SONUC[a.sonuc].ikon}
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

export function AjanAdimlari({ adimlar, canli, platform = null }: { adimlar: AjanAdimi[]; canli: boolean; platform?: Platform | null }) {
  const [secili, setSecili] = useState<number | null>(null);
  const aktif = adimlar.find((a) => a.sira === secili) ?? adimlar[adimlar.length - 1];
  const listeRef = useRef<HTMLOListElement>(null);
  // ET-09: liste iç kaydırmasız (sayfayla kayar); seçim değişince seçili adım görünür alanda kalır.
  useEffect(() => {
    if (secili === null) return;
    const el = listeRef.current?.querySelector<HTMLElement>('[aria-current="step"]');
    el?.scrollIntoView?.({ block: "nearest" });
  }, [secili]);
  if (adimlar.length === 0) {
    return <BosDurum baslik={canli ? "Ajan başlıyor…" : "Ajan adımı yok."} />;
  }
  return (
    <div className="ajan">
      <ol ref={listeRef} className="ajan-adimlar" aria-label="Ajan adımları">
        {adimlar.map((a) => (
          <li key={a.sira}>
            <button
              type="button"
              className={`ajan-adim${aktif?.sira === a.sira ? " aktif" : ""}`}
              aria-pressed={aktif?.sira === a.sira}
              aria-current={aktif?.sira === a.sira ? "step" : undefined}
              onClick={() => setSecili(a.sira)}
            >
              <span className="mono soluk">
                Adım {a.sira}
                {a.step_id && <span title="Case adımı referansı"> · case {a.step_id}</span>}
              </span>
              <span>{a.aciklama}</span>
              <span className="kucuk mono">
                {a.po && a.method ? `${a.po}.${a.method}(${a.args.map((x) => JSON.stringify(x)).join(", ")})` : aracEtiketi(a.arac)}
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
      {/* Telefon görüntüsü dikeydir: çerçeve en çok yüksekliğe sığdırır, oranı korur (009). */}
      <figure className={`ajan-ekran${dikeyEkranMi(platform) ? " ajan-ekran-dikey" : ""}`}>
        {aktif?.ekran_goruntusu_url ? (
          <img src={aktif.ekran_goruntusu_url} alt={`Adım ${aktif.sira} ekran görüntüsü: ${aktif.aciklama}`} />
        ) : (
          <div className="ekran-yok">Ekran görüntüsü yok</div>
        )}
        <figcaption className="kucuk soluk">
          Adım {aktif?.sira}
          {aktif?.step_id && ` (case ${aktif.step_id})`} · {aktif ? <AracAdi arac={aktif.arac} /> : null} · {saat(aktif?.zaman)}. Görüntü yalnızca izleme içindir; modele gönderilmez.
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

/** Aracın Türkçe adı; ham araç adı (app_click …) yanında eş genişlikli yazıyla. */
function AracAdi({ arac }: { arac: string }) {
  const ad = aracEtiketi(arac);
  if (ad === arac) return <>{arac}</>;
  return (
    <>
      {ad} <span className="mono">({arac})</span>
    </>
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

function EslemeTablosu({ eslemeler, kosulmaz = false }: { eslemeler: AdimEslemesi[]; kosulmaz?: boolean }) {
  return (
    <TabloSarici etiket="Eşlenen adımlar tablosu" yogunluk="sik">
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
              <td className="sutun-kimlik" data-etiket="Case adımı">
                {e.step_id ?? "—"}
              </td>
              <td className="mono sutun-metin" data-etiket="Metot">
                {e.po}.{e.method}({e.args.map(DEGER).join(", ")})
              </td>
              <td data-etiket="Tür">{e.beklenen ? <Cip ton="notr">Doğrulama</Cip> : <Cip>Eylem</Cip>}</td>
              <td data-etiket="Uygulamada">
                {e.beklenen ? (
                  // Doğrulamanın `verified`'ı değerin onaylı case metninde bulunmasıdır (kaynak
                  // denetimi), uygulamada gözlem değil: sonucu yerel kontrol belirler.
                  <span className="soluk kucuk">{kosulmaz ? "koşulmadı (doğrulanmamış dil)" : "yerel kontrolde koşulur"}</span>
                ) : e.verified ? (
                  <span className="ok-metin">✓ {e.dogrulama_notu ?? "doğrulandı"}</span>
                ) : (
                  <span className="hata-metin">✗ doğrulanmadı</span>
                )}
              </td>
              <td className="sutun-zengin" data-etiket="Kaynak">
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
    </TabloSarici>
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

/**
 * Yerel kontrolün statik adımları: core `adimlar: [{ad, durum}]` (011, dile göre) varsa o liste; yoksa
 * eski alanlar (`tsc` / `eslint` / `ast_guard`). Eski alanlar boşken Java dilinde adım adları dilden.
 */
export function kontrolSatirlari(yk: YerelKontrol, dil: Dil | null = null): { ad: string; etiket: string; durum: boolean | null }[] {
  if (yk.adimlar && yk.adimlar.length) return yk.adimlar.map((a) => ({ ad: a.ad, etiket: kontrolAdimiEtiketi(a.ad, dil), durum: kontrolAdimiGecti(a.durum) }));
  const eski: Record<string, boolean | null> = { tsc: yk.tsc, eslint: yk.eslint, ast_guard: yk.ast_guard };
  const tsDisi = !!dil && dil !== "ts" && yk.tsc === null && yk.eslint === null && yk.ast_guard === null;
  const adlar = tsDisi ? kontrolAdimlari(dil) : ["tsc", "eslint", "ast_guard"];
  return adlar.map((ad) => ({ ad, etiket: kontrolAdimiEtiketi(ad, tsDisi ? dil : null), durum: eski[ad] ?? null }));
}

export function YerelKontrolKarti({
  yk,
  uretiliyor,
  platform = null,
  dil = null,
}: {
  yk: YerelKontrol | null;
  uretiliyor: boolean;
  platform?: Platform | null;
  dil?: Dil | null;
}) {
  if (!yk) return <BosDurum baslik={uretiliyor ? "Yerel kontrol, eşleme bitince başlar." : "Yerel kontrol yapılmadı."} />;
  const sinif = yk.sinif ? YEREL_SINIF[yk.sinif] : null;
  return (
    <div className="yerel-kontrol">
      <ul className="kontrol-liste" aria-label="Yerel kontrol adımları">
        {kontrolSatirlari(yk, dil).map((a) => (
          <li key={a.ad}>
            <span aria-hidden="true">{ISARET(a.durum)}</span> {a.etiket}
            <span className="gorunmez">: {a.durum === null ? "sonuç yok" : a.durum ? "geçti" : "kaldı"}</span>
          </li>
        ))}
        <li>
          <span aria-hidden="true">{yk.sonuc === null ? "◌" : yk.sonuc === "passed" ? "✓" : "✗"}</span> {kosuAraci(platform, dil)}
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
          <div>
            {yk.aciklama ??
              // Genel "geçti" metni TypeScript adımlarını sayar; Java web'de zincir dilin adımlarıyla yazılır.
              (yk.sinif === "gecti" && dil === "java" && platform === "web" ? `${kontrolZinciri(platform, dil)} (repeat-each) geçti.` : sinif.aciklama)}
          </div>
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

const MUSTERI_CI_DURUMU: Record<MusteriCi["durum"], { ikon: string; etiket: string; ton: Ton }> = {
  bekliyor: { ikon: "○", etiket: "bekliyor", ton: "bilgi" },
  kosuyor: { ikon: "◌", etiket: "koşuyor", ton: "bilgi" },
  gecti: { ikon: "✓", etiket: "geçti", ton: "basari" },
  kaldi: { ikon: "✗", etiket: "kaldı", ton: "hata" },
  derleme_hatasi: { ikon: "✗", etiket: "derleme hatası", ton: "hata" },
  bilinmiyor: { ikon: "?", etiket: "bilinmiyor", ton: "notr" },
};

/**
 * 014 müşteri CI check kartı: TP'nin statik koruması (yerel kontrolün `guard` adımı) + müşterinin GitHub
 * Actions iş akışındaki check (`tp-results` JUnit özeti). Kırarak doğrulama bu hatta yoktur.
 */
export function MusteriCiKarti({
  mc,
  yk,
  dil,
  uretiliyor,
}: {
  mc: MusteriCi | null | undefined;
  yk: YerelKontrol | null;
  dil: Dil | null;
  uretiliyor: boolean;
}) {
  const statik = yk ? kontrolSatirlari(yk, dil) : [];
  const d = mc ? MUSTERI_CI_DURUMU[mc.durum] : null;
  return (
    <div className="musteri-ci" data-testid="musteri-ci-karti">
      <p className="soluk kucuk">
        Test TP'de derlenmez ve koşulmaz: TP statik korumayı yapar, derleme ve koşu müşterinin GitHub Actions iş akışındadır. Sonuç check'ten ve
        tp-results artefaktından okunur.
      </p>
      <ul className="kontrol-liste" aria-label="Müşteri CI adımları">
        {statik.map((a) => (
          <li key={a.ad}>
            <span aria-hidden="true">{ISARET(a.durum)}</span> {a.etiket} (TP)
            <span className="gorunmez">: {a.durum === null ? "sonuç yok" : a.durum ? "geçti" : "kaldı"}</span>
          </li>
        ))}
        {mc && d ? (
          <li data-testid="musteri-ci-check" data-durum={mc.durum}>
            <span aria-hidden="true">{d.ikon}</span> GitHub Actions · <span className="mono">{mc.check_adi}</span>
            <span className="gorunmez">:</span> <Cip ton={d.ton}>{d.etiket}</Cip>
            {mc.sonuc && mc.sonuc.toplam > 0 && (
              <span className="soluk">
                {" "}
                · {mc.sonuc.gecen}/{mc.sonuc.toplam} geçti
                {mc.sonuc.atlanan > 0 && `, ${mc.sonuc.atlanan} atlandı`}
              </span>
            )}
            {mc.head_sha && (
              <span className="soluk">
                {" "}
                · head <span className="mono">{mc.head_sha.slice(0, 7)}</span>
              </span>
            )}
            {mc.run_url && (
              <>
                {" · "}
                <Baglanti href={mc.run_url}>koşu</Baglanti>
              </>
            )}
          </li>
        ) : (
          <li data-testid="musteri-ci-check" data-durum="yok">
            <span aria-hidden="true">○</span> GitHub Actions
            <span className="soluk"> · {uretiliyor ? "PR açılınca check başlar" : "check sonucu yok"}</span>
          </li>
        )}
      </ul>
      {mc?.artefakt === "yok" && (
        <Uyari ton="uyari" baslik="tp-results artefaktı yok">
          İş akışı bitti ama sonuç artefaktı yüklenmedi; test sonuçları okunamadı. İş akışının tp-results adımını denetleyin.
        </Uyari>
      )}
      {mc?.durum === "derleme_hatasi" && (
        <Uyari ton="hata" baslik="Müşteri CI'da derleme hatası">
          {mc.neden ?? "Test müşterinin iş akışında derlenemedi (JUnit sonucu yok)."} Ayrıntı GitHub Actions günlüğünde.
        </Uyari>
      )}
      {mc?.durum === "kaldi" && mc.neden && <p className="kucuk">{mc.neden}</p>}
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
            {checkEtiketi(c.ad) ? (
              <>
                {checkEtiketi(c.ad)} <span className="mono kucuk">({c.ad})</span>
              </>
            ) : (
              <span className="mono">{c.ad}</span>
            )}
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

/** Check'lerin özet metni: "9/9 check geçti" (hepsi yeşil değilse kaçının geçtiği). */
export function checkOzetMetni(checks: PrCheck[]): string {
  const gecen = checks.filter((c) => c.durum === "passed").length;
  return `${gecen}/${checks.length} check geçti`;
}

/** Check listesi (IA-14): hepsi yeşilse tek satır özet, liste açılır ayrıntıda; değilse liste açık. */
function CheckOzeti({ checks }: { checks: PrCheck[] }) {
  const hepsiYesil = checks.length > 0 && checks.every((c) => c.durum === "passed");
  if (!hepsiYesil) return <CheckListesi checks={checks} />;
  return (
    <details className="check-ozeti" data-testid="check-ozeti">
      <summary>
        <span className="ok-metin" aria-hidden="true">
          ✓
        </span>{" "}
        {checkOzetMetni(checks)}
      </summary>
      <CheckListesi checks={checks} />
    </details>
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
              <div className="soluk">
                PR check'leri (merge öncesi, head <KisaDeger deger={pr.head_sha} kopyala={false} kirp="bas" />
                ):
              </div>
              <CheckOzeti checks={checks.map((c) => ({ ...c, zorunlu: null }))} />
            </>
          )}
          <p>
            <strong>main üzerinde push CI</strong> (merge commit <KisaDeger deger={pr.merge_sha ?? sha} kopyala={false} kirp="bas" />):{" "}
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
                (commit <KisaDeger deger={pr.merge_sha || pr.head_sha || sha} kopyala={false} kirp="bas" />)
              </>
            )}
            : <Cip ton={durum.ton}>{durum.metin}</Cip> · <Link to="/kosular?tetik=push">Koşular'da izle</Link>
          </p>
          {checks.length > 0 && <CheckOzeti checks={checks.map((c) => ({ ...c, zorunlu: null }))} />}
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
          // Uzun özet (sha256, commit) kısaltılır; tam değer ipucunda ve kopyalanır (DZ-03, TS-09).
          /^[0-9a-f]{16,}$/i.test(p.slice(1, -1)) ? (
            <KisaDeger key={i} deger={p.slice(1, -1)} uzunluk={12} />
          ) : (
            <code key={i}>{p.slice(1, -1)}</code>
          )
        ) : (
          <span key={i}>{p.replace(/\*\*/g, "")}</span>
        ),
      )}
    </>
  );
}

const hucreler = (satir: string) =>
  satir
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((h) => h.trim());

/**
 * Markdown tablosu (`| a | b |` + `|---|---|`) gerçek tablo olarak (DZ-03): ≤640 px'te "etiket: değer" yığını,
 * hücreler sarar. Ayraç satırı yoksa ilk satır yine başlık sayılır.
 */
function PrTablosu({ satirlar }: { satirlar: string[] }) {
  const [bas, ...kalan] = satirlar;
  const basliklar = hucreler(bas);
  const govde = kalan.filter((x) => !/^\s*\|?\s*:?-{2,}/.test(x)).map(hucreler);
  return (
    <TabloSarici etiket="PR açıklaması tablosu" yogunluk="sik" className="pr-govde-tablo">
      <thead>
        <tr>
          {basliklar.map((b, i) => (
            <th key={i} scope="col">
              <SatirIci metin={b} />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {govde.map((r, i) => (
          <tr key={i}>
            {basliklar.map((b, j) => (
              <td key={j} className="sutun-metin" data-etiket={b.replace(/[`*]/g, "")}>
                <SatirIci metin={r[j] ?? ""} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </TabloSarici>
  );
}

/**
 * PR açıklamasının (core `pull_request.govde`, Markdown) güvenli, küçük bir alt kümesi: başlık, madde,
 * tablo (gerçek tablo), satır içi kod (uzun özetler kısaltılır). Ham HTML hiçbir zaman yorumlanmaz.
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
      bloklar.push(<PrTablosu key={`t${bloklar.length}`} satirlar={tablo} />);
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

/** İndirilen dosyanın adı: `dosya_yolu`'nun son parçası (yol yoksa dile göre genel ad). */
export function indirmeAdi(dosyaYolu: string, dil: Dil | null | undefined): string {
  const son = dosyaYolu.split(/[\\/]/).filter(Boolean).pop();
  if (son) return son;
  const uzanti: Record<Dil, string> = { ts: "ts", java: "java", csharp: "cs", python: "py", kotlin: "kt", swift: "swift" };
  return `uretilen-test.${uzanti[dil ?? "ts"]}`;
}

/** İstemci tarafı indirme (Blob): kod sunucuya yeniden istenmez; ekrandaki içeriğin aynısı kaydedilir. */
export function koduIndir(kod: string, dosyaAdi: string): void {
  const blob = new Blob([kod], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = dosyaAdi;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Tıklama işlendikten sonra adres bırakılır (bazı tarayıcılar eşzamanlı bırakmada indirmeyi iptal eder).
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/**
 * Doğrulanmamış (C#, Python) script'in kalıcı bandı: ne yapılmadığını açıkça söyler, kodu indirir ve
 * başka dilde yeniden üretimi başlatır. Dil seçenekleri core'dan (`GET /code/languages`); uç yoksa
 * platformun geçerli dilleri.
 */
function DogrulanmamisBandi({ s, calisiyor, uret }: { s: Detay; calisiyor: boolean; uret: (dil: Dil) => void }) {
  const platform: Platform = s.platform ?? "web";
  // `code.generate` yoksa uç çağrılmaz (403); platformun geçerli dilleri gösterilir.
  const uretebilir = useIzin("code.generate");
  const diller = useVeri(() => (uretebilir ? api.kodDilleri(platform) : Promise.resolve(null)), [platform, uretebilir]);
  const secenekler = (diller.veri?.secenekler ?? gecerliDiller(platform).map((dil) => ({ dil, etiket: DIL_ETIKETI[dil], kullanilabilir: true, neden: null, hat: "tam" as const, durum: "acik" as DilDurumu })))
    .filter((x) => x.dil !== s.dil);
  const ilkTam = secenekler.find((x) => x.kullanilabilir && x.hat === "tam") ?? secenekler.find((x) => x.kullanilabilir);
  const [hedef, setHedef] = useState<Dil | "">("");
  const secili = hedef || ilkTam?.dil || "";
  const dilAdi = s.dil ? DIL_ETIKETI[s.dil] : "Bu dil";
  const cati = s.dil ? DIL_CATISI(platform, s.dil) : null;
  return (
    <div className="dogrulanmamis-bandi" data-testid="dogrulanmamis-bandi">
      <Uyari ton="uyari" baslik={`Doğrulanmamış kod: ${dilAdi}${cati ? ` (${cati})` : ""}`}>
        <p>
          Bu kod derlenmedi ve koşulmadı; PR açılmadı ve merge edilemez. Ajan adımları tarayıcıda doğrulandı, değerler onaylı case metninden şablonla
          basıldı. Kendi projenizde derleyip koşturmadan önce gözden geçirin.
        </p>
        <div className="eylemler dogrulanmamis-eylemler">
          <button type="button" className="dugme dugme-ikincil" disabled={!s.kod} onClick={() => s.kod && koduIndir(s.kod, indirmeAdi(s.dosya_yolu, s.dil))}>
            Kodu indir
          </button>
          <span className="dil-yeniden">
            <label className="kucuk">
              Başka dil{" "}
              <select value={secili} onChange={(e) => setHedef(e.target.value as Dil)} disabled={calisiyor || secenekler.length === 0}>
                {secenekler.map((x) => (
                  <option key={x.dil} value={x.dil} disabled={!x.kullanilabilir}>
                    {x.etiket}
                    {x.hat === "dogrulanmamis" ? " (doğrulanmamış)" : ""}
                    {x.hat === "musteri_ci" ? " (müşteri CI)" : ""}
                    {!x.kullanilabilir ? ` — ${x.durum === "yakinda" ? "yakında" : "kullanılamıyor"}: ${x.neden ?? "bu depoda yok"}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <IslemDugmesi
              izin="code.generate"
              tur="ikincil"
              calisiyor={calisiyor}
              disabled={!secili || s.case_ids.length === 0}
              title={!secili ? "Bu platformda başka dil yok" : undefined}
              onClick={() => secili && uret(secili)}
            >
              Başka dilde yeniden üret
            </IslemDugmesi>
          </span>
        </div>
      </Uyari>
    </div>
  );
}

export function ScriptDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.script(id), [id]);
  const git = useNavigate();
  // "Test verisi değişti" uyarısı Kod listesindeki kuralla aynı (veriDegistiGecerli): daha yeni script
  // olup olmadığı için liste yalnız uyarı adayı varsa okunur; okunamazsa yalnız durum kuralı uygulanır.
  const veriAdayi = !!v.veri?.veri_degisti;
  // Kaynak case'in sıra numarası ve gereksinimi (kırıntı, "Kaynak" bağlantısı); okunamazsa yalnız Jira anahtarı.
  const caseler = useVeri(() => api.caseler().catch(() => null), [id]);
  const tumScriptler = useVeri(() => (veriAdayi ? api.scriptler().catch(() => null) : Promise.resolve(null)), [id, veriAdayi]);
  const islem = useIslem();
  const bildir = useBildirim();
  // Varsayılan test ortamı canlıysa kırarak doğrulama kapalıdır (core 409 `canli_ortam`; burada önceden pasif).
  const canliOrtam = useOrtamlar().varsayilan?.canli === true;
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
  // D-2 (tur 3): `/kod/:id#pr` (Test case'leri PR bağlantısı) — PR kartı (`id="pr"`) veri gelince çizilir.
  useCapayaKaydir(Boolean(v.veri));

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <KayitHatasi ad="Test kodu" ust={<Link to="/kod">← Kod üretimi</Link>} hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />;
  const s: Detay | undefined = v.veri;
  if (!s) return null;
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
  // 011: doğrulanmamış dil (C#, Python) — PR, kırarak doğrulama ve merge bu dilde yoktur.
  const dogrulanmamis = s.durum === "unverified" || s.dogrulanmamis === true;
  // 014: müşteri CI hattı (Kotlin/Espresso, Swift/XCUITest) — koşu müşterinin GitHub Actions'ında, kırarak doğrulama yok.
  const musteriCi = !dogrulanmamis && s.hat === "musteri_ci";
  const dilAdi = s.dil ? DIL_ETIKETI[s.dil] : null;

  // Kaynak case (IA-14): kırıntı ve özet kartı case review'daki kartına bağlanır.
  const kaynakCase = (caseler.veri ?? []).find((c) => c.id === s.case_ids[0]) ?? null;
  const caseAdi = kaynakCase ? `Case #${kaynakCase.sira_no}` : s.case_ids.length ? "Kaynak case" : null;
  const gereksinimYolu = kaynakCase ? `/gereksinimler/${encodeURIComponent(kaynakCase.requirement_id)}` : null;
  const caseYolu = kaynakCase && gereksinimYolu ? `${gereksinimYolu}/caseler#${encodeURIComponent(caseCapasi(kaynakCase.id))}` : null;
  const checks = s.pr?.checks ?? [];
  // Kırarak doğrulamanın durumu açık metinle (IA-14): yapılmadı mı, bekliyor mu, kimi bekliyor.
  const kirmaDurumu: string = musteriCi
    ? "Bu hatta yok (koşu müşterinin CI'ında)."
    : defectAdayi
      ? "Uygulanmaz: defect adayı (test zaten kırmızı)."
      : s.break_verify.durum === "running"
        ? "Sürüyor."
        : s.break_verify.durum === "passed"
          ? "Geçti: test hata yakalıyor."
          : s.break_verify.durum === "weak" || s.zayif_test
            ? "Zayıf test: kırılmış uygulamada yeşil kaldı."
            : s.break_verify.durum === "failed"
              ? "Tamamlanamadı; yeniden deneyin."
              : prBirlesti
                ? "Yapılmadı (merge öncesi zorunlu değildi; kabul notu denetimde)."
                : prAcik
                  ? canliOrtam
                    ? "Yapılamaz: varsayılan test ortamı canlı."
                    : "Bekliyor — Otomasyon Mühendisi başlatacak."
                  : "PR açılınca yapılır.";
  const kirmaBekliyor = prAcik && !musteriCi && !defectAdayi && !canliOrtam && s.break_verify.durum === "not_started" && !s.zayif_test;
  // Tek "Sıradaki adım" (kimi bekliyoruz) ve onun sekmesi (varsayılan sekme).
  const siradaki: { metin: ReactNode; sekme: string } = uretiliyor
    ? { metin: "Ajan test kodunu üretiyor; bitince yerel kontrol koşar. Sizden bir şey beklenmiyor.", sekme: "ajan" }
    : dogrulanmamis
      ? { metin: "Kodu indirip kendi projenizde derleyin ya da tam hatlı bir dilde yeniden üretin — Otomasyon Mühendisi.", sekme: "kod" }
      : s.engel?.tur === "defect_candidate"
        ? {
            metin: (
              <>
                Defect adayı: triage sonucuna ve bug taslağına karar verilecek — Test Uzmanı.{" "}
                {s.failure_id && (
                  <Link className="ds-siradaki-git" to={`/hatalar/${encodeURIComponent(s.failure_id)}`}>
                    Triage →
                  </Link>
                )}
              </>
            ),
            sekme: "kontrol",
          }
        : s.engel
          ? { metin: `İnsana düştü (${ENGEL_TURU[s.engel.tur] ?? s.engel.tur}): Otomasyon Mühendisi düzeltip yeniden üretecek.`, sekme: "kontrol" }
          : prAcik && s.pr?.dal?.geride
            ? { metin: "Dal main'in gerisinde: önce dalı güncelleyin — Otomasyon Mühendisi.", sekme: "pr" }
            : s.break_verify.durum === "running"
              ? { metin: "Kırarak doğrulama sürüyor; bitince merge kapısı güncellenir.", sekme: "kirarak-dogrula" }
              : kirmaBekliyor
                ? { metin: "Kırarak doğrulayın, ardından PR'ı merge edin — Otomasyon Mühendisi.", sekme: "kirarak-dogrula" }
                : prAcik
                  ? {
                      metin: mergeHazir
                        ? "PR'ı inceleyip merge edin — Otomasyon Mühendisi."
                        : engeller.length
                          ? `Merge kapısı kapalı: ${engeller[0]}`
                          : "Uyarıyı kabul edip merge edin — Otomasyon Mühendisi.",
                      sekme: "pr",
                    }
                  : prBirlesti
                    ? {
                        metin: (
                          <>
                            Yapılacak iş yok: kod main'e birleşti.{" "}
                            <Link className="ds-siradaki-git" to="/kosular?tetik=push">
                              Koşuları izle →
                            </Link>
                          </>
                        ),
                        sekme: "pr",
                      }
                    : s.durum === "closed"
                      ? { metin: "PR kapatıldı; case Kod üretimi ekranından yeniden üretilebilir — Otomasyon Mühendisi.", sekme: "pr" }
                      : s.durum === "failed"
                        ? { metin: "Üretim başarısız; Kod üretimi ekranından yeniden deneyin — Otomasyon Mühendisi.", sekme: "kontrol" }
                        : { metin: "PR'ın açılması bekleniyor (yerel kontrol geçince otomatik açılır).", sekme: "kontrol" };

  async function baskaDildeUret(dil: Dil) {
    setHataYeri("genel");
    const r = await islem.calistir(() => api.kodUret(s!.case_ids, s!.platform ?? "web", dil));
    if (r) {
      bildir(uretimBildirimi(r, `${DIL_ETIKETI[dil]} ile yeniden üretim başladı; bu kayıt kapatılır.`));
      git("/kod");
    }
  }

  async function eylem(fn: () => Promise<unknown>, mesaj: string | ((r: unknown) => string), yer: "pr" | "genel" = "genel") {
    setHataYeri(yer);
    // 409 (PR içeriği/head değişti): ekran yeniden yüklenir, kullanıcı yeniden inceler.
    const r = await islem.calistir(fn, { cakismada: () => void v.yenile(true) });
    if (r !== undefined) {
      bildir(typeof mesaj === "string" ? mesaj : mesaj(r));
      void v.yenile(true);
    }
  }

  const ajanKartlari = (
    <>
      <Kart
        baslik={uygulamaPlatformuMu(s.platform) ? "Ajan adımları (Appium · app-mcp)" : "Ajan adımları (Playwright MCP)"}
        eylemler={uretiliyor && <Cip ton="bilgi">Adımlar geliyor</Cip>}
      >
        {s.mode === "replay" && (
          <p className="kucuk soluk" data-testid="replay-bandi">
            <span className="rozet rozet-replay">REPLAY</span> Model kararları kayıtlı golden çıktıdan; {uygulamaPlatformuMu(s.platform) ? "cihaz" : "tarayıcı"} adımları çalışan uygulamada yeniden
            {uretiliyor ? " koşturuluyor (canlı model değil)." : " koşturuldu."}
          </p>
        )}
        <AjanAdimlari adimlar={s.adimlar} canli={uretiliyor} platform={s.platform} />
      </Kart>

      <Kart baslik="Eşlenen adımlar (adım → page object)">
        <p className="soluk kucuk">
          Her adım sembol tablosundaki bir metoda eşlendi; doğrulama değerleri onaylı case metninde geçmek zorundadır. Kod bu tablodan şablonla üretilir.
        </p>
        {s.eslemeler.length ? (
          <EslemeTablosu eslemeler={s.eslemeler} kosulmaz={dogrulanmamis} />
        ) : (
          <BosDurum baslik={uretiliyor ? "Eşleme ajan bitince yazılır." : "Eşleme kaydı yok."} />
        )}
      </Kart>

    </>
  );
  const kontrolKarti = (
    <>
      {musteriCi ? (
        <Kart baslik="Müşteri CI" id="musteri-ci">
          <MusteriCiKarti mc={s.musteri_ci} yk={s.yerel_kontrol} dil={s.dil ?? null} uretiliyor={uretiliyor} />
          <KurulumBilgisi kurulum={s.kurulum} dilEtiketi={dilAdi ?? "Bu dil"} />
          {(s.platform === "android" || s.platform === "ios") && (
            <KurulumPrEylemi platform={s.platform} kurulum={s.kurulum} degisti={() => void v.yenile()} />
          )}
        </Kart>
      ) : (
      <Kart baslik="Yerel kontrol">
        {dogrulanmamis ? (
          <BosDurum baslik={`${dilAdi ?? "Bu dil"} için yerel kontrol yok.`}>Doğrulanmamış dilde kod derlenmez, korunmaz ve koşulmaz.</BosDurum>
        ) : (
          <YerelKontrolKarti yk={s.yerel_kontrol} uretiliyor={uretiliyor} platform={s.platform} dil={s.dil} />
        )}
      </Kart>
      )}
    </>
  );

  const prKarti = (
      <Kart baslik="Pull request" id="pr">
        {s.pr ? (
          <>
            <p>
              <Kimlik deger={`#${s.pr.number}`} /> {s.pr.baslik}
            </p>
            <p className="satir-ogeler">
              <Cip ton={s.pr.durum === "merged" ? "basari" : s.pr.durum === "open" ? "bilgi" : "notr"}>
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
              <Kimlik deger={s.pr.branch} tur="yol" />
              {s.pr.forge && <span className="kucuk soluk">{s.pr.forge === "local" ? "LocalForge" : "GitHub"}</span>}
              {/* Platform deposu: PR varsayılan dışı depodaysa sahip/ad (tek depolu projede çizilmez). */}
              <DepoCipi kaynak={s.pr} />
            </p>
            {prBirlesti ? (
              <BirlesmisPrCi pr={s.pr} />
            ) : (
              s.pr.checks && s.pr.checks.length > 0 && <CheckOzeti checks={s.pr.checks} />
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
                <EylemCubugu>
                  <IslemDugmesi
                    izin="code.review"
                    tur="ikincil"
                    calisiyor={islem.calisiyor}
                    disabled={!!s.pr.dal.guncelleme}
                    onClick={() => s.pr && eylem(() => api.prDaliGuncelle(s.pr!.number, s.pr!.depo), "Dal güncellemesi kuyruğa alındı.", "pr")}
                  >
                    Dalı güncelle
                  </IslemDugmesi>
                </EylemCubugu>
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
          <div className="merge-kapisi kapi-gecti" data-testid="merge-kapisi">
            <div className="kucuk ok-metin">
              <strong>✓ Birleştirildi</strong>
              {s.pr.merge_eden && ` — ${s.pr.merge_eden}`}
              {s.pr.merge_zamani && `, ${tarih(s.pr.merge_zamani)}`}
              {s.pr.merge_sha && (
                <>
                  {" · merge commit "}
                  <KisaDeger deger={s.pr.merge_sha} kirp="bas" />
                </>
              )}
            </div>
          </div>
        ) : prAcik && (
          <div className="merge-kapisi kapi-bekliyor" data-testid="merge-kapisi">
            <div className="kucuk">
              <strong>Merge kapısı</strong> {kapiAcik ? <span className="ok-metin">açık ✓</span> : <span className="soluk">kapalı</span>}
            </div>
            {engeller.length > 0 && (
              <ul className="kucuk kapi-nedenleri" id="merge-kapi-nedenleri">
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
          <EylemCubugu>
            <IslemDugmesi
              izin="code.merge"
              disabled={!mergeHazir}
              calisiyor={islem.calisiyor}
              // Merge engelleri hemen üstte (kapi-nedenleri) görünür yazılı; tekrarlanmaz, düğmeye bağlanır.
              nedenGizli={!mergeHazir && engeller.length > 0}
              aria-describedby={!mergeHazir && engeller.length > 0 ? "merge-kapi-nedenleri" : undefined}
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
          </EylemCubugu>
        )}
        {islem.hata && hataYeri === "pr" && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
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
                  izin="code.review"
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
                        }, s.pr!.depo),
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
  );
  const kirmaKarti = (
    <>
      {musteriCi ? (
        <Kart id="kirarak-dogrula" baslik="Kırarak doğrula">
          <div data-testid="kirarak-dogrulanmadi">
            <Uyari ton="bilgi" baslik={KIRARAK_DOGRULANMADI}>
              {KIRARAK_DOGRULANMADI_ACIKLAMA}
            </Uyari>
          </div>
        </Kart>
      ) : (
      <Kart
        id="kirarak-dogrula"
        baslik="Kırarak doğrula"
        eylemler={
          !prBirlesti && (
          <IslemDugmesi
            izin="code.break_verify"
            tur={kirmaBekliyor ? "birincil" : "ikincil"}
            odaklanabilir
            disabled={!prAcik || defectAdayi || canliOrtam || s.break_verify.durum === "running"}
            calisiyor={s.break_verify.durum === "running"}
            // Defect adayında / canlı ortamda kutu nedeni zaten görünür yazar; düğmeye bağlanır.
            nedenGizli={defectAdayi || canliOrtam}
            aria-describedby={canliOrtam ? "kirma-canli-neden" : defectAdayi ? "kirma-kapali-neden" : undefined}
            title={
              canliOrtam
                ? ortamMetni("canliKapali")
                : defectAdayi
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
        <p className="kirma-durum" data-testid="kirma-durum">
          <strong>Durum:</strong> {kirmaDurumu}
        </p>
        <p className="soluk kucuk">
          Koşunun bayisi için kampanya kuralı BREAK_CAMPAIGN ile bozulur (diğer bayiler ve ajan etkilenmez); test kırmızıya dönmezse "zayıf test" sayılır.
        </p>
        {canliOrtam && !prBirlesti && (
          <Uyari ton="uyari" baslik={ortamMetni("canliKapaliBaslik")} id="kirma-canli-neden">
            <span data-testid="kirma-canli-ortam">{ortamMetni("canliKapali")}</span>
          </Uyari>
        )}
        {defectAdayi && (
          <Uyari ton="bilgi" baslik="Kırarak doğrulama kapalı" id="kirma-kapali-neden">
            Yerel kontrol bu testi assertion farkıyla kırmızı buldu (defect adayı). Uygulama zaten beklenenden farklı davranıyor; kırma
            kanıt üretmez. Hata triage'a gitti; bug taslağı ve testçi kararı triage sayfasında.
          </Uyari>
        )}
        <KirmaZaman bv={s.break_verify} uygulanmaz={defectAdayi} yapilmadi={prBirlesti} />
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
      )}
    </>
  );
  // Doğrulanmamış script'te karar kartları (PR, kırarak doğrula, merge) çizilmez: kısa açıklama yerlerini alır.
  const dogrulanmamisPr = (
    <Kart baslik="Pull request ve kırarak doğrulama" id="pr">
      <BosDurum kip="sekme" baslik={`${dilAdi ?? "Bu dil"} için PR, kırarak doğrulama ve merge yok.`}>
        Doğrulanmamış dilde üretilen kod depoya yazılmaz; PR'a ve merge'e giremez. Tam hat için TypeScript ya da Java ile yeniden üretin.
      </BosDurum>
    </Kart>
  );

  const sekmeler: DetaySekmesi[] = [
    { id: "pr", ad: "Pull request", capalar: ["pr"], icerik: dogrulanmamis ? dogrulanmamisPr : prKarti },
    {
      id: "kirarak-dogrula",
      ad: "Kırarak doğrula",
      capalar: ["kirarak-dogrula"],
      dikkat: kirmaBekliyor,
      icerik: dogrulanmamis ? (
        <Kart baslik="Kırarak doğrula">
          <BosDurum kip="sekme" baslik="Doğrulanmamış dilde kırarak doğrulama yok." />
        </Kart>
      ) : (
        kirmaKarti
      ),
    },
    { id: "ajan", ad: "Ajan adımları", sayi: s.adimlar.length, icerik: ajanKartlari },
    { id: "kontrol", ad: musteriCi ? "Müşteri CI" : "Yerel kontrol", capalar: ["musteri-ci"], icerik: kontrolKarti },
    {
      id: "kod",
      ad: "Kod",
      icerik: (
        <Kart baslik={dogrulanmamis ? "Üretilen test dosyası (doğrulanmamış)" : "Üretilen test dosyası"}>
          {s.kod ? (
            <KodGorunumu kod={s.kod} dosya={s.dosya_yolu} dil={vurguDili(s.dil) ?? undefined} />
          ) : (
            <BosDurum kip="sekme" baslik="Kod henüz üretilmedi." />
          )}
        </Kart>
      ),
    },
  ];

  const kirinti: KirintiHalkasi[] = [
    { ad: "Kod üretimi", yol: "/kod" },
    ...(s.requirement_key ? [{ ad: s.requirement_key, yol: gereksinimYolu }] : []),
    { ad: caseAdi ?? "Test kodu" },
  ];

  const ust = (
    <>
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
        // Script kaydının saklı hatası API hatası değildir: asistanın "son hata" bağlamına gitmez (§5.5).
        s.hata && <HataKutusu hata={s.hata} kayitDisi />
      )}
      {veriDegistiGecerli(s, tumScriptler.veri ?? [s]) && (
        <Uyari ton="uyari" baslik={VERI_DEGISTI_METNI}>
          Bu test üretildikten sonra kullandığı test verisinin değeri katalogda değişti
          {s.veri_degisen && s.veri_degisen.length > 0 && (
            <>
              {" "}
              (değişen:{" "}
              {s.veri_degisen.map((k, i) => (
                <span key={k}>
                  {i > 0 && ", "}
                  <span className="mono">{k}</span>
                </span>
              ))}
              )
            </>
          )}
          . Kod eski değerle duruyor; <Link to="/kod">Kod üretimi</Link> ekranından yeniden üretin (değerler: <Link to="/test-verisi">Test verisi</Link>).
        </Uyari>
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
      {dogrulanmamis && <DogrulanmamisBandi s={s} calisiyor={islem.calisiyor} uret={(dil) => void baskaDildeUret(dil)} />}
      {islem.hata &&
        hataYeri === "genel" &&
        (dilCakismasiMi(islem.hataNesnesi) ? <DilCakismasiKutusu hata={islem.hataNesnesi} /> : <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />)}
    </>
  );
  const ustVar = !!(s.engel || s.hata || veriDegistiGecerli(s, tumScriptler.veri ?? [s]) || s.uyarilar.length || dogrulanmamis || (islem.hata && hataYeri === "genel"));

  return (
    <DetaySayfasi
      key={s.id}
      sekmeEtiketi="Test kodu bölümleri"
      varsayilanSekme={siradaki.sekme}
      ozet={
        <OzetKarti
          kirinti={kirinti}
          baslik={s.baslik}
          rozetler={
            <>
              <DurumCipi harita={SCRIPT_DURUMU} deger={s.durum} />
              {isaret && <Cip ton={isaret.ton}>{isaret.etiket}</Cip>}
              {sinif && <Cip ton={sinif.ton}>{sinif.etiket}</Cip>}
              <ReplayRozeti mode={s.mode} />
              {s.tetik === "otomatik" && <Cip ton="bilgi" aciklama={OTOMATIK_TETIK_ACIKLAMA}>{OTOMATIK_TETIK_ROZETI}</Cip>}
              {musteriCi && (
                <>
                  <Cip ton="notr" aciklama="Derleme ve koşu müşterinin GitHub Actions iş akışında">
                    Müşteri CI
                  </Cip>
                  <span data-testid="kirarak-dogrulanmadi-rozeti">
                    <Cip ton="uyari" aciklama={KIRARAK_DOGRULANMADI_ACIKLAMA}>
                      {KIRARAK_DOGRULANMADI}
                    </Cip>
                  </span>
                </>
              )}
            </>
          }
          meta={
            <>
              {caseAdi && (
                <span data-testid="kaynak-case">
                  Kaynak: {s.requirement_key && <>{s.requirement_key} · </>}
                  {caseYolu ? <Link to={caseYolu}>{caseAdi}</Link> : caseAdi}
                  {s.case_ids.length > 1 && ` (+${s.case_ids.length - 1})`}
                </span>
              )}
              <PlatformRozeti platform={s.platform} />
              <DilRozeti dil={s.dil} platform={s.platform} />
              <DepoCipi kaynak={s} />
              {s.pr && (
                <span>
                  PR <Kimlik deger={`#${s.pr.number}`} />
                </span>
              )}
              {checks.length > 0 && !prBirlesti && <span data-testid="check-ozet-metni">{checkOzetMetni(checks)}</span>}
              <span>{tarih(s.olusturma)}</span>
            </>
          }
          siradaki={
            <>
              {siradaki.metin}{" "}
              {typeof siradaki.metin === "string" && (
                <Link to={`?sekme=${siradaki.sekme}`} className="ds-siradaki-git">
                  {sekmeler.find((x) => x.id === siradaki.sekme)?.ad} →
                </Link>
              )}
            </>
          }
          eylemler={
            (caseYolu || s.pr?.url) && (
              <>
                {s.pr?.url && (
                  <a className="dugme dugme-ikincil" href={s.pr.url} target="_blank" rel="noopener noreferrer">
                    PR'ı GitHub'da aç
                  </a>
                )}
                {caseYolu && (
                  <Link className="dugme dugme-ikincil" to={caseYolu}>
                    Case'i aç
                  </Link>
                )}
              </>
            )
          }
        />
      }
      ust={ustVar ? ust : undefined}
      sekmeler={sekmeler}
    />
  );

}

import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type TextareaHTMLAttributes } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { caseKarariVerilebilir, GECIS_YOK, gecisVar, type CaseKarari } from "../api/sozlesme/durumMakinesi";
import { useKisiAdi, useOturum } from "../auth";
import type { OtomatikKodSonucu, RetNedeni, TestCase, TestCaseIcerik, TestVerisi } from "../api/types";
import { atifMetni } from "../api/uyumOtomasyon";
import { useIslem, useVeri } from "../hooks";
import { useBildirim } from "./Bildirim";
import { AtifliMetin, GIZLI_DEGER } from "./VeriAtfi";
import { CASE_DURUMU, CASE_TURU, RET_NEDENI, RISK } from "../lib/etiketler";
import { sure, tarih } from "../lib/format";
import { FarkGorunumu } from "./FarkGorunumu";
import { AlanHatasi, Cip, IslemDugmesi, ReplayRozeti } from "./ui";

type Mod = "goster" | "duzenle" | "reddet";

const KARAR_ADI = { approve: "onay", edit: "düzeltme", reject: "ret" } as const;

/** K13': kart bu kadar süre kesintisiz görünür kalınca yerelde "görüldü" sayılır (kayıt görünürlüğün başında gider). */
export const GORULDU_SURE_MS = 3000;

/** §10 (K10): onaylı case'te katalog değeri değişti uyarısı. */
export const VERI_ONAYDAN_SONRA_DEGISTI = "Test verisi onaydan sonra değişti";

/** Toplu onay notu ve seçim engelinde tek dil (K13). */
export const GORULDU_KURALI = "en az 3 saniye ekranda kalan case'ler";

/**
 * Yerel "görüldü" kaydının anahtarı: case + son karar (durum, karar, karar zamanı). Case başka sekmede
 * ya da başka kullanıcı tarafından karara bağlanıp yeniden açılınca anahtar değişir; eski kayıt geçersiz
 * kalır ve kart yeniden en az 3 sn görülüp görüntüleme yeniden gönderilir (tur 3 frontend #4).
 */
export function goruntulemeAnahtari(tc: Pick<TestCase, "id" | "durum" | "karar" | "karar_zamani">): string {
  return `${tc.id}|${tc.durum}|${tc.karar ?? ""}|${tc.karar_zamani ?? ""}`;
}

// Bu oturumda 3 sn kesintisiz görülen (ve görüntülemesi sunucuya kaydedilen) case'ler, kullanıcıya göre
// (rol/kişi değişimi başka kullanıcının kaydını kullanmaz). Anahtar: `goruntulemeAnahtari`.
const goruntulenenler = new Map<string, Set<string>>();
const kullaniciKumesi = (k: string) => {
  let s = goruntulenenler.get(k);
  if (!s) goruntulenenler.set(k, (s = new Set()));
  return s;
};

/** Bu kullanıcının bu oturumda 3 sn kesintisiz gördüğü case anahtarları (toplu onay uygunluğu; K13'). */
export function goruntulenenKumesi(kullaniciAnahtari: string | null): ReadonlySet<string> {
  return (kullaniciAnahtari && goruntulenenler.get(kullaniciAnahtari)) || new Set<string>();
}

/** Testler için: görüntüleme kayıtlarını sıfırlar. */
export function goruntulenenleriSifirla(): void {
  goruntulenenler.clear();
}

/** Testler için: case bu kullanıcı için bu oturumda 3 sn görülmüş sayılır (kart açılınca listeye bildirilir). */
export function goruntulemeyiKaydetTest(kullaniciAnahtari: string, tc: Pick<TestCase, "id" | "durum" | "karar" | "karar_zamani">): void {
  kullaniciKumesi(kullaniciAnahtari).add(goruntulemeAnahtari(tc));
}

/** Karar ya da yeniden açma sonrası: sunucuda eşik yeni karar anı olur, case yeniden görülmelidir. */
export function goruntulemeyiUnut(caseId: string): void {
  for (const s of goruntulenenler.values()) for (const k of [...s]) if (k.startsWith(`${caseId}|`)) s.delete(k);
}

type GorunurlukKaydi = Pick<IntersectionObserverEntry, "isIntersecting" | "intersectionRect" | "boundingClientRect" | "rootBounds">;

/**
 * K13 görünürlük eşiği: kartın görünen yüksekliği `min(%50 kart, %50 viewport)` ve üstü. Viewport'tan
 * uzun kart da (çok adımlı case, dar ekran) yarım ekranı doldurunca görünür sayılır.
 */
export function yeterinceGorunur(k: GorunurlukKaydi): boolean {
  if (!k.isIntersecting) return false;
  const kart = k.boundingClientRect.height;
  if (!(kart > 0)) return false;
  const ekran = k.rootBounds?.height ?? (typeof window !== "undefined" ? window.innerHeight : kart);
  const esik = Math.min(kart / 2, ekran / 2);
  return k.intersectionRect.height + 0.5 >= esik;
}

/** Gözlemci eşikleri: %5 adımlar + bu kartın gereken oranı (uzun kartta %50'nin altında). */
function gozlemEsikleri(el: HTMLElement): number[] {
  const esikler = Array.from({ length: 21 }, (_, i) => i / 20);
  const kart = el.getBoundingClientRect().height;
  const ekran = typeof window !== "undefined" ? window.innerHeight : 0;
  if (kart > 0 && ekran > 0) esikler.push(Math.min(0.5, ekran / 2 / kart));
  return [...new Set(esikler)].sort((a, b) => a - b);
}

/** Görüntüleme kaydı hata verirse kart görünür kaldıkça bu aralıkla yeniden denenir. */
export const YENIDEN_DENEME_MS = 2000;
/** Bir görünürlük döneminde en çok bu kadar yeniden deneme. */
export const YENIDEN_DENEME_SAYISI = 3;

/** Sekme görünür mü (`document.visibilityState`); ortam bilmiyorsa görünür sayılır. */
const sekmeGorunur = () => typeof document === "undefined" || document.visibilityState !== "hidden";

/**
 * K13' (§10): karar bekleyen case kartı analistin ekranında görünür olunca core'a HEMEN bildirilir
 * (`POST /cases/{id}/viewed`; review süresi sunucuda bu andan karara kadar ölçülür). Case yerelde ancak
 * kart 3 sn kesintisiz görünür kalınca (ve sekme görünürken) "görüldü" sayılır ve toplu onaya girer;
 * kayıt başarısızsa görüldü sayılmaz. Kayıt sonradan (yeniden denemeyle) yapıldıysa 3 sn o andan
 * sayılır: sunucu da görüntüleme kaydı ile karar arasında ≥ 3 sn arar (çift bekleme yok).
 *
 * Sunucunun `goruldu` bayrağı burada kullanılmaz (tur 3 QA #3): bir an görünen kart da sunucuda kayıt
 * açar; toplu onay uygunluğu yalnız bu yerel 3 sn kümesine dayanır. Sayfa yenilenince küme boştur ve
 * kart yeniden 3 sn görülmelidir (görüntüleme isteği idempotenttir; sunucudaki ilk kayıt korunur).
 *
 * Görünürlük kesilirse ya da sekme gizlenirse sayaç sıfırlanır. POST hata verirse kart görünür kaldıkça
 * zamanlayıcıyla sınırlı sayıda yeniden denenir. IntersectionObserver yoksa görünürlük doğrulanamaz:
 * güvenli taraf seçilir, bildirilmez (case toplu onaya girmez; tekli onay etkilenmez).
 */
function useGoruntulemeBildir(tc: TestCase, etkin: boolean, kullaniciAnahtari: string | null, goruntulendi?: (anahtar: string) => void) {
  const ref = useRef<HTMLElement | null>(null);
  const geriCagri = useRef(goruntulendi);
  geriCagri.current = goruntulendi;
  const anahtar = goruntulemeAnahtari(tc);
  useEffect(() => {
    if (!etkin || !kullaniciAnahtari) return;
    const gorulen = kullaniciKumesi(kullaniciAnahtari);
    if (gorulen.has(anahtar)) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    let bitti = false;
    /** Gözlemcinin son görünürlük bilgisi (sekme durumundan bağımsız). */
    let kesisiyor = false;
    /** Şu anki kesintisiz görünürlük döneminin başı (ms); dönem yoksa null. */
    let donemBasi: number | null = null;
    /** Bu efektte sunucuya yapılan başarılı kaydın zamanı (ms). */
    let kayitZamani: number | null = null;
    let gonderiliyor = false;
    let deneme = 0;
    let sayac: ReturnType<typeof setTimeout> | null = null;
    let tekrar: ReturnType<typeof setTimeout> | null = null;
    const temizle = () => {
      if (sayac !== null) clearTimeout(sayac);
      if (tekrar !== null) clearTimeout(tekrar);
      sayac = tekrar = null;
    };
    const gorunurMu = () => kesisiyor && sekmeGorunur();
    const bitir = () => {
      bitti = true;
      temizle();
      g.disconnect();
      document.removeEventListener("visibilitychange", sekmeDegisti);
    };
    /** Dönem 3 sn'yi doldurdu ve kayıt 3 sn önce yapıldıysa: yerelde "görüldü". */
    const denetle = () => {
      sayac = null;
      if (bitti || donemBasi === null || kayitZamani === null) return;
      const hedef = Math.max(donemBasi, kayitZamani) + GORULDU_SURE_MS;
      const kalan = hedef - Date.now();
      if (kalan > 0) {
        sayac = setTimeout(denetle, kalan);
        return;
      }
      gorulen.add(anahtar);
      bitir();
      geriCagri.current?.(anahtar);
    };
    const gonder = () => {
      tekrar = null;
      if (bitti || gonderiliyor || kayitZamani !== null || !gorunurMu()) return;
      gonderiliyor = true;
      api
        .caseGoruntulendi(tc.id)
        .then(() => {
          // Karar/yeniden açma ya da sayfa değişimi sonrası gelen yanıt kaydı geri getirmez.
          if (bitti) return;
          kayitZamani = Date.now();
          if (donemBasi !== null) denetle();
        })
        .catch(() => {
          if (bitti) return;
          // Kart görünür kaldıkça sınırlı sayıda yeniden denenir; dönem değişince sayaç sıfırlanır.
          if (gorunurMu() && deneme < YENIDEN_DENEME_SAYISI) {
            deneme += 1;
            tekrar = setTimeout(gonder, YENIDEN_DENEME_MS);
          }
        })
        .finally(() => {
          gonderiliyor = false;
        });
    };
    /** Görünürlük (gözlemci + sekme) değişti: dönemi başlat ya da sıfırla. */
    const guncelle = () => {
      if (bitti) return;
      if (gorunurMu()) {
        if (donemBasi !== null) return;
        donemBasi = Date.now();
        deneme = 0;
        if (kayitZamani === null) gonder();
        else denetle();
      } else {
        donemBasi = null;
        temizle();
      }
    };
    function sekmeDegisti() {
      guncelle();
    }
    const g = new IntersectionObserver(
      (kayitlar) => {
        const k = kayitlar[kayitlar.length - 1];
        if (!k) return;
        kesisiyor = yeterinceGorunur(k);
        guncelle();
      },
      { threshold: gozlemEsikleri(el) },
    );
    g.observe(el);
    document.addEventListener("visibilitychange", sekmeDegisti);
    return () => {
      bitti = true;
      temizle();
      g.disconnect();
      document.removeEventListener("visibilitychange", sekmeDegisti);
    };
  }, [tc.id, anahtar, etkin, kullaniciAnahtari]);
  return ref;
}
/** K23: otomatik kod kapalıyken tekli onay notu (demoda her onayda çıkar; sade tek satır). */
export const OTOKOD_KAPALI_NOTU = "Otomatik kod kapalı; kodu Kod üretimi ekranından başlatın.";

/** Onay sonrası otomatik kod üretimi sonucunun kısa Türkçe metni (013 §3.2). */
export function otomatikKodMetni(o: OtomatikKodSonucu): string {
  switch (o.durum) {
    case "kuyrukta":
      return "Otomatik kod üretimi kuyruğa alındı.";
    case "kapali":
      // K23: demoda her tekli onayda çıkar; sade tek satır.
      return OTOKOD_KAPALI_NOTU;
    case "atlandi":
      return `Otomatik kod üretimi atlandı${o.neden ? `: ${o.neden}` : " (süren ya da açık bir üretim var)"}.`;
    case "reddedildi":
      return `Otomatik kod üretimi başlatılamadı${o.neden ? `: ${o.neden}` : ""}.`;
    case "hata":
      return `Otomatik kod üretimi hata verdi${o.neden ? `: ${o.neden}` : "; onay geçerli, kodu Kod üretimi ekranından elle başlatın"}.`;
  }
}

/** Toplu onay seçimi (Case review): onay kutusu yalnız karar bekleyen satırlarda. */
export interface CaseSecimi {
  secili: boolean;
  degistir: (secili: boolean) => void;
  /** Seçilemezse nedeni (ör. henüz görüntülenmedi, onaya engel var). */
  engel?: string | null;
}

export function CaseKarti({
  tc,
  guncellendi,
  yenile,
  secim,
  goruntulendi,
}: {
  tc: TestCase;
  guncellendi: (t: TestCase) => void;
  /** 409 (içerik siz görüntüledikten sonra değişti): case listesini yeniden yükler. */
  yenile?: () => void;
  secim?: CaseSecimi;
  /** Kart 3 sn kesintisiz görüldü ve görüntüleme kaydedildi (toplu onayda "görüldü" sayılır); `goruntulemeAnahtari`. */
  goruntulendi?: (anahtar: string) => void;
}) {
  const [mod, setMod] = useState<Mod>("goster");
  const islem = useIslem();
  const id = useId();
  const { kullanici } = useOturum();
  const kisiAdi = useKisiAdi();
  const bildir = useBildirim();
  // Yalnızca karar verecek rol (analist) ve karar bekleyen case için görüntüleme ölçülür.
  const kullaniciAnahtari = kullanici ? kullanici.id || kullanici.kullanici_adi : null;
  const kartRef = useGoruntulemeBildir(tc, kullanici?.rol === "analyst" && tc.durum === "draft", kullaniciAnahtari, goruntulendi);
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

  async function karar(fn: () => Promise<TestCase>) {
    const yeni = await islem.calistir(fn, {
      cakismada: () => {
        setMod("goster");
        yenile?.();
      },
    });
    if (yeni) {
      setMod("goster");
      // Karar/yeniden açma yeni eşik: bu case yeniden en az 3 sn görülmeden toplu onaya girmez.
      goruntulemeyiUnut(tc.id);
      guncellendi(yeni);
      if (yeni.otomatik_kod) bildir(otomatikKodMetni(yeni.otomatik_kod), yeni.otomatik_kod.durum === "reddedildi" || yeni.otomatik_kod.durum === "hata" ? "hata" : "bilgi");
    }
  }

  return (
    <article ref={kartRef} className={`case case-${tc.durum}`} aria-labelledby={`${id}-baslik`}>
      <header className="case-baslik">
        <div className="satir-ogeler">
          {secim && tc.durum === "draft" && (
            <label className="case-sec" title={secim.engel ?? undefined}>
              <input
                type="checkbox"
                checked={secim.secili}
                disabled={!!secim.engel}
                aria-describedby={secim.engel ? `${id}-sec-neden` : undefined}
                onChange={(e) => secim.degistir(e.target.checked)}
              />
              <span className="gorunmez">{`#${tc.sira_no} toplu onay için seç: ${tc.icerik.title}`}</span>
            </label>
          )}
          {secim && tc.durum === "draft" && secim.engel && (
            // Neden görünür (klavye ve dokunmatik kullanıcı da görür); pasif kutunun açıklaması.
            <span id={`${id}-sec-neden`} className="soluk kucuk case-sec-neden" data-testid="case-sec-neden">
              {secim.engel}
            </span>
          )}
          <span className="mono soluk">#{tc.sira_no}</span>
          <Cip ton={d.ton}>{d.etiket}</Cip>
          <Cip ton="notr">{CASE_TURU[tc.icerik.type] ?? tc.icerik.type}</Cip>
          {r && <Cip ton={r.ton}>{r.etiket}</Cip>}
          {tc.icerik.acceptance_criteria_refs.map((a) => (
            <span key={a} className="mono ac-ref">
              {a}
            </span>
          ))}
          {tc.kanal === "ide" && <Cip ton="notr" title="Claude Code (MCP submit_draft_cases) kanalından geldi">Claude Code</Cip>}
          <ReplayRozeti mode={tc.mode} />
        </div>
        {tc.jira_test_key && <span className="mono">{tc.jira_test_key}</span>}
      </header>

      {mod === "duzenle" ? (
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
      ) : (
        <>
          <h3 id={`${id}-baslik`} className="case-ad">
            {/* K22: başlıktaki gizli değer de `{veri:anahtar}` atfı olarak gelir; çip olarak gösterilir. */}
            <AtifliMetin metin={tc.icerik.title} veri={tc.veri} />
          </h3>
          {tc.icerik.preconditions.length > 0 && (
            <p className="kucuk">
              <strong>Ön koşul:</strong>{" "}
              {tc.icerik.preconditions.map((p, i) => (
                <span key={i}>
                  {i > 0 && " · "}
                  <AtifliMetin metin={p} veri={tc.veri} />
                </span>
              ))}
            </p>
          )}
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
                    <td data-etiket="Adım">
                      <AtifliMetin metin={s.action} veri={tc.veri} />
                    </td>
                    <td className={`mono${s.data ? "" : " bos-hucre"}`} data-etiket="Veri">
                      {s.data ? <AtifliMetin metin={s.data} veri={tc.veri} /> : "—"}
                    </td>
                    <td data-etiket="Beklenen">
                      <AtifliMetin metin={s.expected} veri={tc.veri} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <strong>Beklenen sonuç:</strong> <AtifliMetin metin={tc.icerik.expected_result} veri={tc.veri} />
          </p>
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
              disabled={!verilebilir("approve")}
              title={gecisYokNedeni("approve")}
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
      {tc.veri_onaydan_sonra_degisen && tc.veri_onaydan_sonra_degisen.length > 0 && (
        // §10 (K10): onaydan sonra katalogda değeri değişen test verisi; yalnız anahtarlar (değer/özet yok).
        <p className="kucuk uyari-metin" role="note" data-testid="case-veri-degisti">
          <strong>{VERI_ONAYDAN_SONRA_DEGISTI}:</strong>{" "}
          {tc.veri_onaydan_sonra_degisen.map((k, i) => (
            <span key={k}>
              {i > 0 && ", "}
              <span className="mono">{k}</span>
            </span>
          ))}
          . Ekrandaki değer güncel katalog değeridir; onaylanan değer farklıydı. Gerekirse case'i yeniden açıp gözden geçirin.
        </p>
      )}
      {tc.uyarilar && tc.uyarilar.length > 0 && (
        <ul className="duz-liste kucuk hata-metin">
          {tc.uyarilar.map((u) => (
            <li key={u}>{u}</li>
          ))}
        </ul>
      )}
      {mod === "goster" && islem.hata && (
        <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>
      )}
    </article>
  );
}

/** K22: case dışı metinlerdeki maske. Case alanlarında gizli değer `{veri:anahtar}` atfı olarak gelir. */
export const MASKE = "•••";

/** K22: düzeltme formunda maske kalmışsa kaydetmeden önce gösterilen uyarı (sunucu da 422 ile reddeder). */
export const MASKE_UYARISI =
  "Formda maskeli gizli değer (•••) var; böyle kaydedilirse gerçek değer kaybolur ve sunucu reddeder. •••'yi silip gizli değeri \"Test verisi ekle\" ile {veri:anahtar} atfı olarak yazın.";

/** K22: sunucunun düzeltme 422'si ("Gizli değer maskeli görünüyor; {veri:…} atfını kullanın") için ek açıklama. */
export const MASKE_HATASI_IPUCU =
  "Gizli değerler case'te {veri:anahtar} atfı olarak durur; formdaki ••• yerine \"Test verisi ekle\" ile atfı seçin. Atıf çipleri olduğu gibi kalırsa değer korunur.";

export const maskeHatasiMi = (hata: string | null | undefined) => !!hata && /maskeli/i.test(hata) && /veri:/.test(hata);

/** Düzeltme içeriğinde maske (`•••`) geçen alanların etiketleri. */
export function maskeliAlanlar(i: TestCaseIcerik): string[] {
  const l: string[] = [];
  const var_ = (m: string | null | undefined) => !!m && m.includes(MASKE);
  if (var_(i.title)) l.push("Başlık");
  if (i.preconditions.some(var_)) l.push("Ön koşullar");
  i.steps.forEach((s, j) => {
    if (var_(s.action) || var_(s.data) || var_(s.expected)) l.push(`S${j + 1}`);
  });
  if (var_(i.expected_result)) l.push("Beklenen sonuç");
  if ((i.tags ?? []).some(var_)) l.push("Etiketler");
  return l;
}

/** Review tur 4: düzeltme 429'u (aktör başına gizli değer denemesi freni; core `COK_DENEME_METNI`). */
export const cokDenemeHatasiMi = (hata: string | null | undefined, kaynak?: unknown) =>
  (kaynak instanceof ApiError && kaynak.status === 429) || (!!hata && /çok sayıda test verisi/i.test(hata));

export const COK_DENEME_IPUCU =
  "Kısa sürede gizli değer (parola vb.) içeren çok sayıda düzeltme gönderildi; güvenlik için düzeltme bir süre (en çok 15 dakika) durduruldu. Sonra yeniden deneyin; gizli değeri düz yazmak yerine \"Test verisi ekle\" ile {veri:anahtar} atfı olarak ekleyin.";

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
  const [uyari, setUyari] = useState<string | null>(null);
  // §12: beklenen sonuç metni değiştiyse "anlamca değişti mi?" kararını insan verir (zorunlu).
  const [anlamDegisti, setAnlamDegisti] = useState<"evet" | "hayir" | "">("");
  const id = useId();
  const beklenenDegisti = icerik.expected_result.trim() !== ilk.expected_result.trim();

  const listeMetni = (l: string[]) => l.join("\n");
  const listeyeCevir = (m: string) =>
    m
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  const [onKosulMetni, setOnKosulMetni] = useState(() => listeMetni(ilk.preconditions));
  const [acMetni, setAcMetni] = useState(() => ilk.acceptance_criteria_refs.join(", "));

  // 013 §3.5 "Test verisi ekle": atıf, en son odaklanılan atıf alanında imlecin olduğu yere eklenir.
  const imlec = useRef<{ alan: string; bas: number; son: number } | null>(null);
  const [sonAlan, setSonAlan] = useState<string | null>(null);
  const [eklendi, setEklendi] = useState("");
  const alanEtiketi = (alan: string) =>
    alan === "onkosul" ? "Ön koşullar" : alan === "beklenen" ? "Beklenen sonuç" : `S${Number(alan.slice(1)) + 1} ${{ a: "eylem", d: "veri", e: "beklenen" }[alan[0] as "a" | "d" | "e"]}`;
  const alanDegeri = (alan: string): string => {
    if (alan === "onkosul") return onKosulMetni;
    if (alan === "beklenen") return icerik.expected_result;
    const s = icerik.steps[Number(alan.slice(1))];
    if (!s) return "";
    return alan[0] === "a" ? s.action : alan[0] === "d" ? (s.data ?? "") : s.expected;
  };
  const alanYaz = (alan: string, deger: string) => {
    if (alan === "onkosul") setOnKosulMetni(deger);
    else if (alan === "beklenen") setIcerik((c) => ({ ...c, expected_result: deger }));
    else adimGuncelle(Number(alan.slice(1)), alan[0] === "a" ? "action" : alan[0] === "d" ? "data" : "expected", deger);
  };
  /**
   * Atıf alanlarının odak/imleç izleyicisi (atıf ekleme başlık ve AC alanına yapılmaz; başlıkta gelen
   * `{veri:…}` atfı (K22) metinde olduğu gibi korunur).
   */
  const izle = (alan: string) => ({
    onFocus: () => setSonAlan(alan),
    onBlur: (e: { currentTarget: HTMLTextAreaElement }) => {
      imlec.current = { alan, bas: e.currentTarget.selectionStart ?? 0, son: e.currentTarget.selectionEnd ?? 0 };
    },
  });
  /** Alan hâlâ formda mı (silinen adımın alanına yazılmaz). */
  const alanVar = (alan: string) => alan === "onkosul" || alan === "beklenen" || Number(alan.slice(1)) < icerik.steps.length;
  function atifEkle(anahtar: string) {
    const alan = sonAlan;
    if (!alan) return;
    if (!alanVar(alan)) {
      setSonAlan(null);
      imlec.current = null;
      return;
    }
    const deger = alanDegeri(alan);
    const h = imlec.current && imlec.current.alan === alan ? imlec.current : { alan, bas: deger.length, son: deger.length };
    const bas = Math.min(h.bas, deger.length);
    const son = Math.min(Math.max(h.son, bas), deger.length);
    const atif = atifMetni(anahtar);
    alanYaz(alan, deger.slice(0, bas) + atif + deger.slice(son));
    const konum = bas + atif.length;
    imlec.current = { alan, bas: konum, son: konum };
    setEklendi(`${atif} → ${alanEtiketi(alan)}`);
    // Odak alana döner, imleç atfın sonuna (klavye kullanıcısı yazmaya devam eder).
    requestAnimationFrame(() => {
      const el = document.getElementById(`${id}-${alan}`) as HTMLTextAreaElement | null;
      el?.focus();
      el?.setSelectionRange(konum, konum);
    });
  }

  const adimGuncelle = (i: number, alan: "action" | "data" | "expected", deger: string) =>
    setIcerik((c) => ({
      ...c,
      steps: c.steps.map((s, j) => (j === i ? { ...s, [alan]: alan === "data" && deger === "" ? null : deger } : s)),
    }));

  function gonder(e: FormEvent) {
    e.preventDefault();
    if (!icerik.title.trim()) return setUyari("Başlık boş olamaz.");
    if (icerik.title.length > 120) return setUyari("Başlık en fazla 120 karakter.");
    if (icerik.steps.length === 0 || icerik.steps.some((s) => !s.action.trim() || !s.expected.trim())) {
      return setUyari("Her adımın eylemi ve beklenen sonucu dolu olmalı.");
    }
    if (!icerik.expected_result.trim()) return setUyari("Beklenen sonuç boş olamaz.");
    const acRefleri = acMetni
      .split(/[,\s]+/)
      .map((x) => x.trim().toUpperCase())
      .filter(Boolean);
    if (acRefleri.length === 0) return setUyari("En az bir kabul kriteri atfı gerekir (ör. AC1).");
    if (beklenenDegisti && !anlamDegisti) return setUyari("Beklenen sonuç anlamca değişti mi? Evet ya da Hayır seçin.");
    const gonderilecek: TestCaseIcerik = {
      ...icerik,
      preconditions: listeyeCevir(onKosulMetni),
      acceptance_criteria_refs: [...new Set(acRefleri)],
      steps: icerik.steps.map((s, i) => ({ ...s, id: `S${i + 1}` })),
    };
    // K22: maske kaydedilmez (gerçek değer kaybolur; sunucu da 422 ile reddeder).
    const maskeli = maskeliAlanlar(gonderilecek);
    if (maskeli.length > 0) return setUyari(`${MASKE_UYARISI} (${maskeli.join(", ")})`);
    setUyari(null);
    kaydet(
      gonderilecek,
      // Metin değişmediyse anlam da değişmemiştir; değiştiyse insanın beyanı gönderilir.
      beklenenDegisti ? anlamDegisti === "evet" : false,
    );
  }

  // K22: formda maske görünürse kaydetmeden önce (yazarken) uyarılır.
  const gorunenMaske = maskeliAlanlar({ ...icerik, preconditions: listeyeCevir(onKosulMetni) });

  return (
    <form className="case-duzenle" onSubmit={gonder} noValidate>
      {gorunenMaske.length > 0 && (
        <p className="kucuk uyari-metin" role="note" data-testid="maske-uyarisi">
          {MASKE_UYARISI} ({gorunenMaske.join(", ")})
        </p>
      )}
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
            {(["positive", "negative", "boundary"] as const).map((k) => (
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
      <div className="alan">
        <label htmlFor={`${id}-onkosul`}>Ön koşullar (her satır bir ön koşul)</label>
        <OtoMetin id={`${id}-onkosul`} value={onKosulMetni} onChange={(e) => setOnKosulMetni(e.target.value)} {...izle("onkosul")} />
      </div>
      <fieldset className="alan">
        <legend>Adımlar</legend>
        {icerik.steps.map((s, i) => (
          <div key={i} className="adim-duzenle">
            <span className="mono">S{i + 1}</span>
            <label className="gorunmez" htmlFor={`${id}-a${i}`}>{`S${i + 1} eylem`}</label>
            <OtoMetin
              id={`${id}-a${i}`}
              placeholder="Eylem"
              value={s.action}
              onChange={(e) => adimGuncelle(i, "action", e.target.value)}
              {...izle(`a${i}`)}
            />
            <label className="gorunmez" htmlFor={`${id}-d${i}`}>{`S${i + 1} veri`}</label>
            <OtoMetin
              id={`${id}-d${i}`}
              placeholder="Veri"
              value={s.data ?? ""}
              onChange={(e) => adimGuncelle(i, "data", e.target.value)}
              {...izle(`d${i}`)}
            />
            <label className="gorunmez" htmlFor={`${id}-e${i}`}>{`S${i + 1} beklenen`}</label>
            <OtoMetin
              id={`${id}-e${i}`}
              placeholder="Beklenen"
              value={s.expected}
              onChange={(e) => adimGuncelle(i, "expected", e.target.value)}
              {...izle(`e${i}`)}
            />
            <button
              type="button"
              className="dugme dugme-hayalet dugme-kucuk"
              aria-label={`S${i + 1} adımını sil`}
              onClick={() => {
                setIcerik((c) => ({ ...c, steps: c.steps.filter((_, j) => j !== i) }));
                // Adım numaraları kayar: son alan/imleç başka adımı gösterebilir, sıfırlanır.
                setSonAlan(null);
                imlec.current = null;
              }}
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
        <OtoMetin
          id={`${id}-beklenen`}
          value={icerik.expected_result}
          onChange={(e) => setIcerik({ ...icerik, expected_result: e.target.value })}
          {...izle("beklenen")}
        />
      </div>
      <VeriSecici alan={sonAlan ? alanEtiketi(sonAlan) : null} ekle={atifEkle} eklendi={eklendi} />
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
      {(uyari || hata) && (
        <AlanHatasi asistan={uyari ? null : { hata, kaynak: hataKaynagi }}>{uyari ?? hata}</AlanHatasi>
      )}
      {!uyari && maskeHatasiMi(hata) && (
        <p className="kucuk" data-testid="maske-hatasi-ipucu">
          {MASKE_HATASI_IPUCU}
        </p>
      )}
      {!uyari && cokDenemeHatasiMi(hata, hataKaynagi) && (
        <p className="kucuk" data-testid="cok-deneme-ipucu">
          {COK_DENEME_IPUCU}
        </p>
      )}
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

/**
 * "Test verisi ekle" (013 §3.5): katalogdan anahtar seçip son odaklanılan atıf alanına `{veri:anahtar}`
 * ekler. Gizli kaydın değeri listede de gösterilmez. Katalog okunamazsa seçici yerine not çıkar.
 */
function VeriSecici({ alan, ekle, eklendi }: { alan: string | null; ekle: (anahtar: string) => void; eklendi: string }) {
  const katalog = useVeri(() => api.testVerileri(), []);
  const [anahtar, setAnahtar] = useState("");
  const id = useId();
  const gruplar = new Map<string, TestVerisi[]>();
  for (const k of katalog.veri ?? []) {
    const g = k.grup ?? "diğer";
    gruplar.set(g, [...(gruplar.get(g) ?? []), k]);
  }
  const neden = !alan ? "Önce atfın ekleneceği ön koşul, adım ya da beklenen sonuç alanına tıklayın." : !anahtar ? "Bir test verisi seçin." : undefined;
  return (
    <div className="veri-secici" role="group" aria-labelledby={`${id}-baslik`}>
      <span id={`${id}-baslik`} className="veri-secici-baslik">
        Test verisi ekle
      </span>
      {katalog.yukleniyor && !katalog.veri ? (
        <span className="soluk kucuk">Katalog yükleniyor…</span>
      ) : katalog.hata && !katalog.veri ? (
        <span className="soluk kucuk">Test verisi kataloğu okunamadı: {katalog.hata}</span>
      ) : (katalog.veri ?? []).length === 0 ? (
        <span className="soluk kucuk">Katalogda kayıt yok (Test verisi ekranından eklenir).</span>
      ) : (
        <div className="satir-ogeler">
          <label className="gorunmez" htmlFor={`${id}-anahtar`}>
            Eklenecek test verisi
          </label>
          <select id={`${id}-anahtar`} value={anahtar} onChange={(e) => setAnahtar(e.target.value)} aria-describedby={`${id}-ipucu`}>
            <option value="">Test verisi seçin…</option>
            {[...gruplar.entries()].map(([g, kayitlar]) => (
              <optgroup key={g} label={g}>
                {kayitlar.map((k) => (
                  <option key={k.id} value={k.anahtar}>
                    {`${k.anahtar} — ${k.gizli ? GIZLI_DEGER : (k.deger ?? "")}`}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <IslemDugmesi roller={["analyst"]} kucuk tur="ikincil" disabled={!!neden} title={neden} onClick={() => ekle(anahtar)}>
            {alan ? `İmlece ekle (${alan})` : "İmlece ekle"}
          </IslemDugmesi>
        </div>
      )}
      <span id={`${id}-ipucu`} className="soluk kucuk">
        Atıf <span className="mono">{"{veri:anahtar}"}</span> biçiminde eklenir; değer kod üretiminde katalogdan okunur, Jira'ya
        gizli olmayan değerler yazılır.
      </span>
      <span className="gorunmez" role="status" aria-live="polite">
        {eklendi && `Eklendi: ${eklendi}`}
      </span>
    </div>
  );
}

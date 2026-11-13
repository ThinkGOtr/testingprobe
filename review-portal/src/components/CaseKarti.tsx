import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode, type TextareaHTMLAttributes } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { caseKarariVerilebilir, GECIS_YOK, type CaseKarari } from "../api/sozlesme/durumMakinesi";
import { useCaseKisitli, useIzin, useKisiAdi, useOturum } from "../auth";
import {
  CASE_HAZIRLIKLARI,
  CASE_ONCELIKLERI,
  CASE_TEKNIKLERI,
  DOGRULAMA_NOKTALARI,
  TEST_SEVIYELERI,
  type AcikSoru,
  type CaseHazirlik,
  type CaseTeknigi,
  type CaseTestVerisi,
  type OtomatikKodSonucu,
  type RetNedeni,
  type TestCase,
  type TestCaseIcerik,
  type TestVerisi,
  type Varsayim,
} from "../api/types";
import { atifMetni } from "../api/uyumOtomasyon";
import { useIslem, useVeri } from "../hooks";
import {
  atiflariCoz,
  caseEski,
  caseHazirlik,
  eskiIcerik,
  hataListesi,
  hazirlikSorunlari,
  hazirlikYonlendirmesi,
  kimlikListesi,
  soruKimligi,
  sorularYanitlandi,
  TEKNIK_ONEK_IPUCU,
} from "../lib/caseV3";
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
  URETIM_TURU,
} from "../lib/etiketler";
import { sure, tarih } from "../lib/format";
import { AtifPoDurumu, DuzeltmeKaynaklari, PoYanitOnerisi } from "./AcikSorular";
import { useBildirim } from "./Bildirim";
import { FarkGorunumu } from "./FarkGorunumu";
import { HazirlikYonlendirme } from "./HazirlikYonlendirme";
import { AlanHatasi, Cip, IslemDugmesi, ReplayRozeti, Uyari } from "./ui";
import { damgaAlani, DuzeltmeOnKontrolPaneli, OracleAyrinti, OracleCipi, OracleKapisi, oracleHatasindaYenile, TuretmeCipi, useDuzeltmeOnKontrolu, useOracleKapisi } from "./kalite/oracle";
import { AtifliMetin, GIZLI_DEGER } from "./VeriAtfi";

type Mod = "goster" | "duzenle" | "reddet" | "geriGonder";

const KARAR_ADI: Record<string, string> = {
  accept: "kabul",
  edit: "düzelterek kabul",
  reject: "ret",
  approve: "onay",
  send_back: "geri gönderme",
  reopen: "taslağa alma",
};

/**
 * Karar sonrası durum notu (ANALIZ 012 §5). "Taslağa al" Testçinin işlemidir: yönerge yalnız ona;
 * Analist onaya hazır case'te değişiklik için gerekçeyle geri gönderir.
 */
export function durumNotu(durum: TestCase["durum"], testci: boolean, onaylayici: boolean): string {
  if (durum === "ready") {
    if (testci) return "Testçi kabul etti; Analist son onayı bekleniyor. Değiştirmek için taslağa alın.";
    if (onaylayici) return "Testçi kabul etti; son onayınızı bekliyor. Değişiklik gerekiyorsa gerekçeyle Geri gönderin.";
    return "Testçi kabul etti; Analist son onayı bekleniyor.";
  }
  if (durum === "approved") {
    return testci ? "Analist onayladı. Değiştirmek için taslağa alın; onay düşer ve yeniden karar gerekir." : "Analist onayladı.";
  }
  if (durum === "rejected") return testci ? "Reddedildi. Yeniden değerlendirmek için taslağa alın." : "Reddedildi.";
  return "Karar verildi.";
}

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
 * K13' (§10): karar bekleyen case kartı karar verecek rolün (Testçi taslakta, Analist onaya hazır
 * case'te) ekranında görünür olunca core'a HEMEN bildirilir
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

/** Case kartının kalıcı DOM kimliği (rota çapası `#case-<id>`). */
export function caseCapasi(caseId: string): string {
  return `case-${caseId}`;
}

export function CaseKarti({
  tc,
  guncellendi,
  yenile,
  secim,
  goruntulendi,
  uretimTuru,
  poyaGonder,
  varsayimDogrulandi,
}: {
  tc: TestCase;
  guncellendi: (t: TestCase) => void;
  /** 409 (içerik siz görüntüledikten sonra değişti): case listesini yeniden yükler. */
  yenile?: () => void;
  secim?: CaseSecimi;
  /** Kart 3 sn kesintisiz görüldü ve görüntüleme kaydedildi (toplu onayda "görüldü" sayılır); `goruntulemeAnahtari`. */
  goruntulendi?: (anahtar: string) => void;
  /** Case'i üreten üretimin türü (case-summary `uretimler[].tur`: uretim | negatif | teknik). */
  uretimTuru?: string;
  /** D6: açık soruyu PO'ya gönderme eylemi; "Neden kabul edilemiyor" kutusuna yerleşir. */
  poyaGonder?: ReactNode;
  /** B2: "Varsayım doğrulandı" başarılı; liste aynı varsayıma dayanan case'leri iyimser günceller. */
  varsayimDogrulandi?: (onceki: TestCase, yeni: TestCase, varsayimlar: string[]) => void;
}) {
  const [mod, setMod] = useState<Mod>("goster");
  const islem = useIslem();
  const id = useId();
  const testci = useIzin("case.decide");
  const onaylayici = useIzin("case.approve");
  // Developer: yalnız onaylı/yayınlanmış case, karar geçmişi ve eylem yok (core süzgeciyle aynı).
  const kisitli = useCaseKisitli();
  const { kullanici } = useOturum();
  const bildir = useBildirim();
  // Yalnızca karar verecek rol ve onun karar evresi için görüntüleme ölçülür: Testçi taslakta,
  // Analist (case.approve) onaya hazır case'te (anahtar durumu içerir; iki evre ayrı sayılır).
  const kullaniciAnahtari = kullanici ? kullanici.id || kullanici.kullanici_adi : null;
  const kartRef = useGoruntulemeBildir(
    tc,
    (testci && tc.durum === "draft") || (onaylayici && tc.durum === "ready"),
    kullaniciAnahtari,
    goruntulendi,
  );
  // core test_case: ready | approved | rejected → draft ("Taslağa al"). Yayınlanmış case son durumdur.
  const yenidenAcilabilir = caseKarariVerilebilir(tc.durum, "reopen");
  const d = CASE_DURUMU[tc.durum];
  // Son durumlar (core): yayınlanan ve yerini yenisi alan case'e karar verilmez.
  const kilitli = tc.durum === "published" || tc.durum === "superseded";
  // core test_case makinesi: Testçi kararı draft'tan (→ ready | rejected), Analist kararı ready'den.
  const verilebilir = (k: CaseKarari) => caseKarariVerilebilir(tc.durum, k);
  const gecisYokNedeni = (k: CaseKarari) => (verilebilir(k) ? undefined : `${GECIS_YOK} (${CASE_DURUMU[tc.durum].etiket})`);
  const testciKarari = !kilitli && tc.durum === "draft";
  const analistKarari = !kilitli && tc.durum === "ready";
  const kararVerildi = !kilitli && !testciKarari;
  // Kararlar ekranda görülen içeriğin hash'iyle gönderilir (düzeltmede düzeltme öncesi içerik).
  const bag = { icerik_hash: tc.icerik_hash };
  // Şema v3 (011): eski case'te v3 blokları hiç çizilmez; hazır sayılır (K9).
  const eski = caseEski(tc);
  const hazirlik = caseHazirlik(tc);
  // K6: hazır olmayan ya da tutarlılık ihlali olan case kabul edilemez. Core `onay_engeli` accept'in
  // vereceği 422 metninin aynısıdır: varsa o gösterilir. Alan yoksa (eski core) içerikten türetilir.
  // B3: PO yanıtı geldiyse ipucu "açık soru bekliyor" demez; sıradaki eylemi söyler.
  const poYanitladi = !eski && tc.durum === "draft" && sorularYanitlandi(tc);
  const kabulEngeli = !verilebilir("accept")
    ? gecisYokNedeni("accept")
    : poYanitladi
      ? "PO yanıtladı: önce 'Düzelterek kabul' ile beklenen sonucu yanıta göre yazın."
      : tc.onay_engeli
        ? `${tc.onay_engeli}. "Düzelterek kabul" ile giderin ya da reddedin.`
        : tc.onay_engeli === undefined && hazirlik !== "ready"
          ? `Hazır değil (${CASE_HAZIRLIK[hazirlik].etiket}): "Düzelterek kabul" ile hazır yapın ya da reddedin.`
          : tc.onay_engeli === undefined && !eski && tc.uyarilar && tc.uyarilar.length > 0
            ? 'İçerik uyarısı var: "Düzelterek kabul" ile giderin ya da reddedin.'
            : undefined;
  // K6 (012 iki adım): onaya hazır v3 case'te core `onay_engeli` doluysa Analist son onayı da verilemez
  // (ör. kabulden sonra içerik/özet tutarsızlaştı); "Geri gönder" ile Testçiye döner.
  const sonOnayEngeli = !verilebilir("approve")
    ? gecisYokNedeni("approve")
    : tc.onay_engeli
      ? `${tc.onay_engeli}. "Geri gönder" ile Testçiye döndürün.`
      : undefined;
  const hataAyrik = hataListesi(islem.hata);

  async function karar(fn: () => Promise<TestCase>) {
    // 012: sunucu kapı hatası (422 oracle_uyumsuz) verirse liste yenilenir; 409 aşağıdaki çakışma yoluna girer.
    const yeni = await islem.calistir(oracleHatasindaYenile(fn, yenile), {
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

  // 012 (ANALIZ §4.3): beklenen sonuç kontrolü kapısı ve düzeltme ön kontrolü.
  const kapi = useOracleKapisi(tc);
  const onKontrol = useDuzeltmeOnKontrolu(tc, (icerik, beklenenAnlamDegisti, istisnaGerekce, istisnaTuru, damga) =>
    karar(() =>
      api.caseKarari(tc.id, {
        ...bag,
        karar: "edit",
        icerik,
        ...(beklenenAnlamDegisti !== undefined ? { beklenen_anlam_degisti: beklenenAnlamDegisti } : {}),
        // Tur 2 (Y9): gerekçe verilince tür her zaman gönderilir; karar görülen kontrol kaydının damgasını taşır.
        ...(istisnaGerekce && istisnaTuru ? { oracle_istisna_gerekce: istisnaGerekce, oracle_istisna_turu: istisnaTuru } : {}),
        ...(damga ? { oracle_kayit_damgasi: damga } : {}),
      }),
    ),
  );

  return (
    // Kalıcı çapa (`#case-<id>`): Test case'leri satırı doğrudan bu karta götürür (lib/capa.ts kaydırır, odaklar).
    <article ref={kartRef} id={caseCapasi(tc.id)} tabIndex={-1} className={`case case-${tc.durum}`} aria-labelledby={`${id}-baslik`}>
      {/* UX-12: başlıkta yalnız durum, hazır olma ve öncelik rozetleri; diğer özellikler aşağıdaki listede. */}
      <header className="case-baslik">
        <div className="satir-ogeler">
          {secim && (tc.durum === "draft" || tc.durum === "ready") && (
            <label className="case-sec" title={secim.engel ?? undefined}>
              <input
                type="checkbox"
                checked={secim.secili}
                disabled={!!secim.engel}
                aria-describedby={secim.engel ? `${id}-sec-neden` : undefined}
                onChange={(e) => secim.degistir(e.target.checked)}
              />
              <span className="gorunmez">{`#${tc.sira_no} toplu ${tc.durum === "ready" ? "onay" : "kabul"} için seç: ${tc.icerik.title}`}</span>
            </label>
          )}
          {secim && (tc.durum === "draft" || tc.durum === "ready") && secim.engel && (
            // Neden görünür (klavye ve dokunmatik kullanıcı da görür); pasif kutunun açıklaması.
            <span id={`${id}-sec-neden`} className="soluk kucuk case-sec-neden" data-testid="case-sec-neden">
              {secim.engel}
            </span>
          )}
          <span className="mono soluk">#{tc.sira_no}</span>
          <Cip ton={d.ton}>{d.etiket}</Cip>
          {!eski && <HazirlikRozeti durum={hazirlik} />}
          {!eski && <OncelikRozeti tc={tc} />}
          {eski && (
            <span className="soluk kucuk" data-testid="case-eski-sema" title="Bu case önceki şemayla üretildi: teknik, öncelik ve hazır olma bilgisi yok; hazır sayılır.">
              eski şema
            </span>
          )}
          <OracleCipi tc={tc} />
          <TuretmeCipi tc={tc} />
        </div>
        {tc.jira_test_key && <span className="mono">{tc.jira_test_key}</span>}
      </header>
      {mod === "goster" && !kilitli && !kisitli && (
        <HazirlikYonlendirme
          tc={tc}
          guncellendi={guncellendi}
          yenile={yenile}
          poyaGonder={poyaGonder}
          duzelt={verilebilir("edit") ? () => setMod("duzenle") : undefined}
          varsayimDogrulandi={varsayimDogrulandi}
        />
      )}

      {mod === "duzenle" ? (
        <>
          {/* 011 K16: yanıtlanan sorunun PO yanıtı düzeltmede beklenen sonucun kaynağıdır. */}
          <DuzeltmeKaynaklari sorular={tc.acik_sorular} varsayimlar={tc.varsayimlar} />
          <CaseDuzenleyici
            ilk={tc.icerik}
            soruEtiketleri={(tc.icerik.open_question_refs ?? []).filter((q) => soruKimligi(tc, q) !== q).map((q) => `${q} = ${soruKimligi(tc, q)}`)}
            calisiyor={islem.calisiyor || onKontrol.bekliyor}
            hata={islem.hata}
            hataKaynagi={islem.hataNesnesi}
            vazgec={() => {
              onKontrol.sifirla();
              setMod("goster");
            }}
            kaydet={onKontrol.gonder}
            degisti={onKontrol.icerikDegisti}
          />
          <DuzeltmeOnKontrolPaneli kontrol={onKontrol} calisiyor={islem.calisiyor} />
        </>
      ) : (
        <>
          <h3 id={`${id}-baslik`} className="case-ad">
            {/* K22: başlıktaki gizli değer de `{veri:anahtar}` atfı olarak gelir; çip olarak gösterilir. */}
            <AtifliMetin metin={tc.icerik.title} veri={tc.veri} />
          </h3>
          {eski ? (
            <CaseOzellikleri tc={tc} uretimTuru={uretimTuru} />
          ) : (
            <CaseV3Ozeti tc={tc} hazirlik={hazirlik} uretimTuru={uretimTuru} yonlendirmeVar={!kilitli && !kisitli && hazirlikYonlendirmesi(tc) !== null} />
          )}
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
                    <td data-etiket="Adım">
                      <AtifliMetin metin={s.action} veri={tc.veri} />
                    </td>
                    <td className={`mono${s.data ? "" : " bos-hucre"}`} data-etiket="Veri">
                      {s.data ? <AtifliMetin metin={s.data} veri={tc.veri} /> : "—"}
                    </td>
                    <td className={s.expected ? undefined : "bos-hucre"} data-etiket="Beklenen">
                      {s.expected ? <AtifliMetin metin={s.expected} veri={tc.veri} /> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <strong>Beklenen sonuç:</strong>{" "}
            {tc.icerik.expected_result ? (
              <AtifliMetin metin={tc.icerik.expected_result} veri={tc.veri} />
            ) : (
              <span className="soluk">
                {poYanitladi
                  ? "— (PO yanıtına göre yazılacak)"
                  : (tc.icerik.open_question_refs?.length ?? 0) > 0
                    ? "— (henüz yazılamıyor: açık soru yanıtlanmalı)"
                    : "—"}
              </span>
            )}
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
          <OracleAyrinti tc={tc} />
        </>
      )}

      {mod === "geriGonder" && (
        <GeriGonderFormu
          calisiyor={islem.calisiyor}
          hata={islem.hata}
          hataKaynagi={islem.hataNesnesi}
          vazgec={() => setMod("goster")}
          gonder={(gerekce) => karar(() => api.caseKarari(tc.id, { ...bag, karar: "send_back", gerekce }))}
        />
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
          {/* u2 N11: AI çıktısı olmayan case'te (ilişkiden türetilen, elle) "AI 0 ms" yazılmaz. */}
          {!tc.ai_generated
            ? tc.icerik.tags?.includes("metamorfik")
              ? "İlişkiden türetildi (model çağrısı yok)"
              : "Elle yazıldı (model çağrısı yok)"
            : tc.mode === "replay" || tc.mode === "replay_miss"
              ? "AI: REPLAY — ölçülmedi"
              : `AI ${sure(tc.ai_sure_ms)}`}
          {!kisitli && (
            <>
              {tc.review_sure_ms !== null && ` · review ${sure(tc.review_sure_ms)}`}
              {tc.durum === "draft" && tc.karar && tc.karar !== "send_back" && ` · taslağa alındı (önceki karar: ${KARAR_ADI[tc.karar] ?? tc.karar})`}
              {tc.durum === "draft" && tc.karar === "send_back" && (
                <span data-testid="case-geri-gonderildi">{` · Analist geri gönderdi${tc.gerekce ? `: ${tc.gerekce}` : ""}`}</span>
              )}
              {tc.ret_nedeni && tc.durum === "rejected" && ` · ret: ${RET_NEDENI[tc.ret_nedeni]}`}
              {tc.duzeltme_olcusu !== null && (tc.testci_karari ?? tc.karar) === "edit" && ` · düzeltme ölçüsü ${tc.duzeltme_olcusu.toLocaleString("tr-TR")}`}
              {(tc.testci_karari ?? tc.karar) === "edit" && <KucukDuzeltme tc={tc} />}
              {tc.durum === "draft" && tc.goruntulenme && ` · review ${tarih(tc.goruntulenme)} itibarıyla sürüyor`}
            </>
          )}
        </span>
        {/* Testçi kararı yalnız taslakta; Analist son onayı yalnız onaya hazır case'te (ANALIZ 012 §5). */}
        {mod === "goster" && !kisitli && testciKarari && (
          <div className="eylemler">
            <IslemDugmesi
              izin="case.decide"
              kucuk
              disabled={kabulEngeli !== undefined || !!kapi.engel}
              title={kabulEngeli ?? kapi.engel ?? undefined}
              calisiyor={islem.calisiyor}
              onClick={() => karar(() => api.caseKarari(tc.id, { ...bag, karar: "accept", ...damgaAlani(tc.oracle) }))}
            >
              Kabul et
            </IslemDugmesi>
            <IslemDugmesi
              izin="case.decide"
              kucuk
              tur="ikincil"
              disabled={!verilebilir("edit")}
              title={gecisYokNedeni("edit")}
              onClick={() => setMod("duzenle")}
            >
              Düzelterek kabul
            </IslemDugmesi>
            <IslemDugmesi
              izin="case.decide"
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
        {mod === "goster" && !kisitli && analistKarari && (
          <div className="eylemler">
            <IslemDugmesi
              izin="case.approve"
              kucuk
              disabled={sonOnayEngeli !== undefined || !!kapi.engel}
              title={sonOnayEngeli ?? kapi.engel ?? undefined}
              calisiyor={islem.calisiyor}
              onClick={() => karar(() => api.caseKarari(tc.id, { ...bag, karar: "approve", ...damgaAlani(tc.oracle) }))}
            >
              Onayla
            </IslemDugmesi>
            <IslemDugmesi
              izin="case.approve"
              kucuk
              tur="ikincil"
              disabled={!verilebilir("send_back")}
              title={gecisYokNedeni("send_back")}
              onClick={() => setMod("geriGonder")}
            >
              Geri gönder
            </IslemDugmesi>
          </div>
        )}
      </footer>
      {/* 012 (ANALIZ §13.2): karar tablosu kapısı Testçi kabulünde ve Analist son onayında aynıdır;
          istisna formu bu evrenin kararını (taslakta accept, ready'de approve) gerekçeyle gönderir. Kart
          her role çizilir: yetkisiz düğmeler nedenini gösterir ("Tablo yanlış" Analistin işidir). */}
      {mod === "goster" && !kisitli && (testciKarari || analistKarari) && (
        <OracleKapisi
          kapi={kapi}
          tc={tc}
          izin={testciKarari ? "case.decide" : "case.approve"}
          calisiyor={islem.calisiyor}
          onayla={(gerekce, tur) =>
            karar(() =>
              api.caseKarari(tc.id, {
                ...bag,
                karar: testciKarari ? "accept" : "approve",
                oracle_istisna_gerekce: gerekce,
                oracle_istisna_turu: tur,
                ...damgaAlani(tc.oracle),
              }),
            )
          }
        />
      )}
      {!kisitli && <KararIzi tc={tc} />}
      {mod === "goster" && !kisitli && kararVerildi && (
        <div className="satir-ogeler">
          <p className="soluk kucuk" data-testid="case-karar-kilit">
            {durumNotu(tc.durum, testci, onaylayici)}
          </p>
          {yenidenAcilabilir && (
            <IslemDugmesi izin="case.decide" kucuk tur="ikincil" calisiyor={islem.calisiyor} onClick={() => karar(() => api.caseYenidenAc(tc))}>
              Taslağa al
            </IslemDugmesi>
          )}
        </div>
      )}
      {!kisitli && tc.fark && tc.fark.length > 0 && (
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
        <>
          <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{hataAyrik.baslik || "İşlem reddedildi:"}</AlanHatasi>
          <HataMaddeleri maddeler={hataAyrik.maddeler} />
        </>
      )}
    </article>
  );
}

/**
 * Kimin ne karar verdiği, ayrı etiketli satırlarda (ANALIZ 012 §5): Testçi kararı (`testci`,
 * `testci_karari`) ve Analist son onayı (`son_onay`). `karar_veren` son karardır (Analist olabilir);
 * yalnız core Testçi/son onay alanlarını vermezse "Son karar" etiketiyle gösterilir.
 */
function KararIzi({ tc }: { tc: TestCase }) {
  const kisiAdi = useKisiAdi();
  const so = tc.son_onay ?? (tc.onaylayan ? { karar: "approve" as const, veren: tc.onaylayan, zaman: tc.onay_zamani ?? null, gerekce: null } : null);
  // Testçi kararının zamanı: son karar Testçininse `karar_zamani` (core ayrı zaman alanı vermez).
  const testciZamani =
    tc.testci && tc.karar_veren === tc.testci && (!so || so.zaman !== tc.karar_zamani) ? tc.karar_zamani : null;
  const satirlar: { id: string; etiket: string; metin: string }[] = [];
  if (tc.testci || tc.testci_karari) {
    const k = tc.testci_karari ? (KARAR_ADI[tc.testci_karari] ?? tc.testci_karari) : null;
    satirlar.push({
      id: "case-testci-karari",
      etiket: "Testçi kararı",
      metin: [k, tc.testci ? kisiAdi(tc.testci) : null, testciZamani ? tarih(testciZamani) : null].filter(Boolean).join(" · "),
    });
  }
  if (so) {
    satirlar.push({
      id: "case-son-onay",
      etiket: "Analist son onayı",
      metin: [so.karar === "approve" ? "onaylandı" : "geri gönderildi", so.veren ? kisiAdi(so.veren) : null, so.zaman ? tarih(so.zaman) : null]
        .filter(Boolean)
        .join(" · "),
    });
  }
  if (satirlar.length === 0 && tc.karar_veren) {
    satirlar.push({ id: "case-son-karar", etiket: "Son karar", metin: `${kisiAdi(tc.karar_veren)}${tc.karar_zamani ? ` · ${tarih(tc.karar_zamani)}` : ""}` });
  }
  if (satirlar.length === 0) return null;
  return (
    <ul className="duz-liste soluk kucuk" aria-label="Karar izi">
      {satirlar.map((s) => (
        <li key={s.id} data-testid={s.id}>
          <strong>{s.etiket}:</strong> {s.metin}
        </li>
      ))}
    </ul>
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
export function TeknikRozeti({
  teknik,
  sade,
  adGorunur,
}: {
  teknik: string;
  /** Kart özellik listesinde renksiz (UX-12). */
  sade?: boolean;
  /** Teknik adı rozetin yanında görünür yazılıyorsa gizli ad eklenmez (ad iki kez okunmasın; UX4 Bulgu 9). */
  adGorunur?: boolean;
}) {
  const ad = CASE_TEKNIGI[teknik];
  return (
    <span className={sade ? "mono teknik-sade" : "cip cip-bilgi"} title={ad}>
      {teknik}
      {ad && !adGorunur && <span className="gorunmez"> ({ad})</span>}
    </span>
  );
}

function AtifListesi({
  kayitlar,
  metin,
  varsayim,
}: {
  kayitlar: (AcikSoru | Varsayim | { id: string })[];
  metin: (k: AcikSoru | Varsayim) => string;
  varsayim?: boolean;
}) {
  return (
    <ul className="case-atif-listesi">
      {kayitlar.map((k) => (
        <li key={k.id}>
          {/* B7: PO'ya gönderilen soru PO'nun gördüğü kimlikle (CQ1); üretimdeki kimlik ipucunda. */}
          {"po_etiketi" in k && k.po_etiketi && !varsayim ? (
            <span className="mono ac-ref" title={`Üretimdeki kimlik: ${k.id}`} data-testid="atif-kimlik">
              {k.po_etiketi}
              <span className="gorunmez"> (üretimdeki kimlik: {k.id})</span>
            </span>
          ) : (
            <span className="mono ac-ref" data-testid="atif-kimlik">
              {k.id}
            </span>
          )}{" "}
          {"owner" in k ? (
            <>
              {metin(k)} <span className="soluk kucuk">· Sahibi: {SORU_SAHIBI[k.owner] ?? k.owner}</span>
              <AtifPoDurumu kayit={k} varsayim={varsayim} />
            </>
          ) : (
            <span className="soluk">metni bu yanıtta yok (Kapsam ve açık noktalar paneline bakın)</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Öncelik rozeti (başlık satırında): v3 case'te `priority` varsa. */
function OncelikRozeti({ tc }: { tc: TestCase }) {
  const oncelik = tc.icerik.priority ? CASE_ONCELIGI[tc.icerik.priority] : undefined;
  if (!oncelik) return null;
  return (
    <span className={`cip cip-${oncelik.ton}`} title={oncelik.aciklama} data-testid="case-oncelik">
      {oncelik.etiket}
      <span className="gorunmez"> ({oncelik.aciklama})</span>
    </span>
  );
}

/**
 * UX-5: derinleştirmenin eklediği case'in rozeti ("Negatif genişletme · üretim 2"). İlk üretimde
 * (tur "uretim") ya da tür bilinmiyorsa çizilmez.
 */
export function DerinlestirmeRozeti({ tur, uretimNo }: { tur?: string; uretimNo?: number }) {
  if (!tur || tur === "uretim") return null;
  return (
    <Cip ton="bilgi" title="Mevcut sete derinleştirmeyle eklenen taslak">
      <span data-testid="case-uretim-rozeti">
        {URETIM_TURU[tur] ?? tur}
        {uretimNo !== undefined && ` · üretim ${uretimNo}`}
      </span>
    </Cip>
  );
}

/**
 * Case özellikleri listesi (UX-12): tür, risk (yalnız eski case; v3'te risk yok), kabul kriterleri,
 * kaynak; v3 case'te teknik, kapsam, doğrulama noktası, test seviyesi, platform, standartlar.
 */
function CaseOzellikleri({ tc, uretimTuru, children }: { tc: TestCase; uretimTuru?: string; children?: ReactNode }) {
  const i = tc.icerik;
  const eski = caseEski(tc);
  const r = eski && i.risk ? RISK[i.risk] : undefined;
  const kaynakVar = tc.kanal === "ide" || tc.mode === "replay" || tc.mode === "replay_miss" || (!!uretimTuru && uretimTuru !== "uretim");
  return (
    <dl className="case-ozellik kucuk" data-testid="case-ozellikler">
      <div>
        <dt>Tür</dt>
        <dd>{CASE_TURU[i.type] ?? i.type}</dd>
      </div>
      {r && (
        <div>
          <dt>Risk</dt>
          <dd>{r.etiket}</dd>
        </div>
      )}
      {i.acceptance_criteria_refs.length > 0 && (
        <div>
          <dt>Kabul kriterleri</dt>
          <dd className="satir-ogeler">
            {i.acceptance_criteria_refs.map((a) => (
              <span key={a} className="mono ac-ref">
                {a}
              </span>
            ))}
          </dd>
        </div>
      )}
      {kaynakVar && (
        <div>
          <dt>Kaynak</dt>
          <dd className="satir-ogeler">
            <DerinlestirmeRozeti tur={uretimTuru} uretimNo={tc.uretim_no} />
            {tc.kanal === "ide" && <span title="Claude Code (MCP submit_draft_cases) kanalından geldi">Claude Code</span>}
            <ReplayRozeti mode={tc.mode} />
          </dd>
        </div>
      )}
      {children}
    </dl>
  );
}

/** v3 blokları: özellikler (teknik, kapsam, doğrulama noktası …) ve atıf yapılan açık sorular / varsayımlar. */
function CaseV3Ozeti({
  tc,
  hazirlik,
  uretimTuru,
  yonlendirmeVar,
}: {
  tc: TestCase;
  hazirlik: CaseHazirlik;
  uretimTuru?: string;
  /** "Neden kabul edilemiyor" kutusu çiziliyor: PO yanıtı önerisi onun metninde (B3: tek mesaj). */
  yonlendirmeVar?: boolean;
}) {
  const i = tc.icerik;
  const sorular = atiflariCoz(i.open_question_refs, tc.acik_sorular);
  const varsayimlar = atiflariCoz(i.assumption_refs, tc.varsayimlar);
  // K6: onaylı case hazırdır; eski kayıtta varsayım kaldıysa başlık yalnız bilgi verir.
  const taslak = tc.durum === "draft";
  const yanitli = sorularYanitlandi(tc);
  return (
    <div className="case-v3" data-testid="case-v3">
      <CaseOzellikleri tc={tc} uretimTuru={uretimTuru}>
        {(i.technique?.length ?? 0) > 0 && (
          <div>
            <dt>Teknikler</dt>
            {/* B4: dd'de role/aria-label yok (definition-list kuralı); etiket işini dt görür. */}
            <dd className="satir-ogeler">
              {i.technique!.map((t) => (
                <TeknikRozeti key={t} teknik={t} sade />
              ))}
            </dd>
          </div>
        )}
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
              {i.requires_real_device && <span title="Bu case emülatör/simülatörde değil, gerçek cihazda koşulmalı">Gerçek cihaz gerekir</span>}
            </dd>
          </div>
        )}
        {(i.standard_refs?.length ?? 0) > 0 && (
          <div>
            <dt>Standart atıfları</dt>
            <dd>{i.standard_refs!.join(" · ")}</dd>
          </div>
        )}
      </CaseOzellikleri>
      {!yonlendirmeVar && <PoYanitOnerisi tc={tc} />}
      {sorular.length > 0 && (
        <div data-testid="case-acik-sorular">
          <Uyari
            ton={yanitli ? "bilgi" : undefined}
            baslik={yanitli ? "Açık sorular ve PO yanıtı" : hazirlik === "blocked" ? "Açık sorular (yanıtlanmadan bu case hazır olamaz)" : "Açık sorular"}
          >
            <AtifListesi kayitlar={sorular} metin={(k) => (k as AcikSoru).question} />
          </Uyari>
        </div>
      )}
      {varsayimlar.length > 0 && (
        <div data-testid="case-varsayimlar">
          <Uyari ton="bilgi" baslik={taslak ? "Dayandığı varsayımlar (doğrulanmadan kabul edilemez)" : "Dayandığı varsayımlar"}>
            <AtifListesi kayitlar={varsayimlar} metin={(k) => (k as Varsayim).statement} varsayim />
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
function TestVerisiTablosu({ veriler, baslik }: { veriler: CaseTestVerisi[]; baslik: string }) {
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
        <IslemDugmesi izin="case.decide" type="submit" tur="tehlike" kucuk calisiyor={calisiyor}>
          Reddi kaydet
        </IslemDugmesi>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={vazgec}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/** Gerekçe alanlarının üst sınırı (core `gerekce` ≤ 2000). */
export const GEREKCE_EN_COK = 2000;

/** Analist "Geri gönder": gerekçe zorunlu (ready → draft; ANALIZ 012 §5). */
function GeriGonderFormu({
  gonder,
  vazgec,
  calisiyor,
  hata,
  hataKaynagi,
}: {
  gonder: (gerekce: string) => void;
  vazgec: () => void;
  calisiyor: boolean;
  hata: string | null;
  hataKaynagi?: unknown;
}) {
  const [gerekce, setGerekce] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const id = useId();
  const hataVar = !!(uyari || hata);
  return (
    <form
      className="ret-formu"
      data-testid="geri-gonder-formu"
      onSubmit={(e) => {
        e.preventDefault();
        if (!gerekce.trim()) return setUyari("Geri gönderme gerekçesi zorunludur.");
        setUyari(null);
        gonder(gerekce.trim());
      }}
      noValidate
    >
      <div className="alan">
        <label htmlFor={`${id}-gerekce`}>Geri gönderme gerekçesi</label>
        <OtoMetin
          id={`${id}-gerekce`}
          value={gerekce}
          maxLength={GEREKCE_EN_COK}
          aria-required="true"
          aria-invalid={hataVar || undefined}
          aria-describedby={hataVar ? `${id}-gerekce-hata` : undefined}
          placeholder="Testçinin neyi düzeltmesi gerekiyor?"
          onChange={(e) => setGerekce(e.target.value)}
        />
      </div>
      {hataVar && (
        <div id={`${id}-gerekce-hata`}>
          <AlanHatasi asistan={uyari ? null : { hata, kaynak: hataKaynagi }}>{uyari ?? hata}</AlanHatasi>
        </div>
      )}
      <div className="eylemler">
        <IslemDugmesi izin="case.approve" type="submit" kucuk calisiyor={calisiyor}>
          Geri gönder
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
  soruEtiketleri = [],
  degisti,
}: {
  ilk: TestCaseIcerik;
  /** B7: PO'ya gönderilen soruların üretim kimliği ↔ PO kimliği eşlemesi ("Q1 = CQ1"). */
  soruEtiketleri?: string[];
  /** Formdaki herhangi bir değişiklik (ön kontrol engelini düşürür: eski içerik istisnayla gönderilmez). */
  degisti?: () => void;
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
  // Her düzenleme (adım ekleme/kaldırma dahil) çağırana bildirilir; ilk çizim sayılmaz.
  const degistiRef = useRef(degisti);
  degistiRef.current = degisti;
  const ilkCizim = useRef(true);
  useEffect(() => {
    if (ilkCizim.current) {
      ilkCizim.current = false;
      return;
    }
    degistiRef.current?.();
  }, [icerik, onKosulMetni, acMetni, kapsamMetni, varsayimMetni, soruMetni, temizlikMetni, anlamDegisti]);

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
  const veriGuncelle = (i: number, ek: Partial<CaseTestVerisi>) =>
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
      // Düzeltme case'i kabul eder (core: draft → ready, Analist son onayına gider); hazır olmayan içerik kaydedilemez (K6).
      if (son.readiness !== "ready") {
        return setUyarilar([
          `Düzeltme case'i kabul eder; durum "${CASE_HAZIRLIK[son.readiness ?? "ready"].etiket}" iken kaydedilemez. Soru yanıtlandıysa ya da varsayım doğrulandıysa durumu "Hazır" yapın; değilse case'i reddedin ya da taslakta bırakın.`,
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
    const gonderilecek: TestCaseIcerik = { ...son, acceptance_criteria_refs: [...new Set(acRefleri)] };
    // K22: maske kaydedilmez (gerçek değer kaybolur; sunucu da 422 ile reddeder).
    const maskeli = maskeliAlanlar(gonderilecek);
    if (maskeli.length > 0) return setUyarilar([`${MASKE_UYARISI} (${maskeli.join(", ")})`]);
    setUyarilar([]);
    kaydet(
      gonderilecek,
      // Metin değişmediyse anlam da değişmemiştir; değiştiyse insanın beyanı gönderilir.
      beklenenDegisti ? anlamDegisti === "evet" : false,
    );
  }

  const sunucuHatasi = hataListesi(hata);
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
            {(v3 ? (["positive", "negative", "boundary", "authorization", "integration"] as const) : (["positive", "negative", "boundary"] as const)).map((k) => (
              <option key={k} value={k}>
                {CASE_TURU[k]}
              </option>
            ))}
          </select>
        </div>
        {/* K18: v3 case'te risk alanı yok (risk değerlendirmesi öncelik gerekçesinde); yalnız eski case düzeltilir. */}
        {!v3 && (
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
        )}
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
              Virgülle ayırın. Kimlik öneki seçili teknikle uyumlu olmalı ({TEKNIK_ONEK_IPUCU}); tanımsız öğe sunucuda reddedilir.
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
                <input
                  id={`${id}-soru`}
                  className="mono"
                  value={soruMetni}
                  placeholder="Q1"
                  aria-describedby={soruEtiketleri.length ? `${id}-soru-ipucu` : undefined}
                  onChange={(e) => setSoruMetni(e.target.value)}
                />
                {soruEtiketleri.length > 0 && (
                  <span id={`${id}-soru-ipucu`} className="soluk kucuk" data-testid="soru-kimlik-ipucu">
                    Atıf üretimdeki kimlikle yazılır; PO'nun gördüğü kimlik: {soruEtiketleri.join(", ")}.
                  </span>
                )}
              </div>
            </div>
            <p id={`${id}-hazirlik-ipucu`} className="soluk kucuk">
              Düzeltme case'i kabul eder (Analist son onayına gider); yalnız "Hazır" case kaydedilebilir. Hazır: açık soru ve varsayım atfı yok, beklenen sonuç ve tüm adım
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
        <OtoMetin id={`${id}-onkosul`} value={onKosulMetni} onChange={(e) => setOnKosulMetni(e.target.value)} {...izle("onkosul")} />
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
      {uyarilar.length === 0 && maskeHatasiMi(hata) && (
        <p className="kucuk" data-testid="maske-hatasi-ipucu">
          {MASKE_HATASI_IPUCU}
        </p>
      )}
      {uyarilar.length === 0 && cokDenemeHatasiMi(hata, hataKaynagi) && (
        <p className="kucuk" data-testid="cok-deneme-ipucu">
          {COK_DENEME_IPUCU}
        </p>
      )}
      <div className="eylemler">
        <IslemDugmesi izin="case.decide" type="submit" kucuk calisiyor={calisiyor}>
          Düzelterek kabul et
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
          <IslemDugmesi izin="case.decide" kucuk tur="ikincil" disabled={!!neden} title={neden} onClick={() => ekle(anahtar)}>
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

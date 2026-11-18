import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode, type RefObject } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { buFazdaYok, bulunamadi } from "../api/http";
import type { CiktiModu, Degerlendirme } from "../api/types";
import { useIzin, useRotaIzni } from "../auth";
import { type Ton } from "../lib/etiketler";
import { izinNedeni, type Izin } from "../lib/yetki";
import { baglantiTuru } from "../lib/rotalar";
import { hataGosterildi, hataTazele } from "../lib/sonHata";
import { asistanaSor, useAsistanHazir } from "./asistan/kontrol";
import { Ikon } from "./Ikon";
import { Ipucu } from "./Ipucu";

/** Kayıtlı (replay) çıktı rozeti. live için hiçbir şey göstermez (Constitution VIII). */
export function ReplayRozeti({ mode, degerlendirme }: { mode: CiktiModu | null | undefined; degerlendirme?: Degerlendirme | null }) {
  const rozet =
    mode === "replay" ? (
      <Ipucu metin="REPLAY: hazırlanmış örnek çıktı; canlı model değil.">
        <span className="rozet rozet-replay">REPLAY</span>
      </Ipucu>
    ) : mode === "replay_miss" ? (
      <Ipucu metin="REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok; canlı model gerekir.">
        <span className="rozet rozet-replay-miss">REPLAY-MISS</span>
      </Ipucu>
    ) : null;
  if (!rozet) return null;
  return (
    <>
      {rozet}
      {/* Rozetler satır içinde de ayrık dursun (flex/gap kabında boşluk düğümü yok sayılır). */}
      {degerlendirme && degerlendirme.durum !== "evaluated" && " "}
      <DegerlendirmeNotu d={degerlendirme} />
    </>
  );
}

/**
 * Prompt paketinin canlı değerlendirme durumu (Anayasa X). Yalnızca core gönderdiyse gösterilir;
 * değerlendirilmiş paket için not yoktur.
 */
export function DegerlendirmeNotu({ d }: { d: Degerlendirme | null | undefined }) {
  const n = degerlendirmeNotuMetni(d);
  if (!n) return null;
  return (
    <span className="rozet rozet-degerlendirme" title={n.aciklama}>
      {n.metin}
    </span>
  );
}

/**
 * Değerlendirme notunun son kullanıcı metni. Core etiketi teknik olabilir (ör. "değerlendirme
 * sonrası içerik değişti (içerik hash'i uyuşmuyor)", "prompt sürümü değişti"): bayat/eksik kayıt
 * sade bir ifadeyle söylenir; hash, dosya yolu ya da sürüm ayrıntısı gösterilmez (UX4 Bulgu 6).
 */
export function degerlendirmeNotuMetni(d: Degerlendirme | null | undefined): { metin: string; aciklama: string } | null {
  if (!d || d.durum === "evaluated") return null;
  if (d.durum === "waived") return { metin: "onaylı istisna (canlı değerlendirme yok)", aciklama: "Bu özellik canlı değerlendirme yerine onaylı bir istisnayla kullanılıyor." };
  if (d.durum === "pending") return { metin: "canlı değerlendirme bekliyor", aciklama: "Bu özelliğin yapay zekâ ayarları henüz canlı modelle değerlendirilmedi." };
  return {
    metin: "değerlendirme güncel değil",
    aciklama: "Yapay zekâ ayarları son canlı değerlendirmeden sonra değişti ya da değerlendirme kaydı yok; yeniden değerlendirme bekleniyor.",
  };
}

/**
 * Çip / hap (§4.6, TS-07). `bicim`: `hap` (durum; varsayılan), `etiket` (kimlik/atıf/tür; köşe 6 px),
 * `duz` (yığındaki ikincil bilgi; zeminsiz, solunda ince ayraç). `boyut="kucuk"`: yoğun satır. `sar`: uzun metin
 * (cümle, neden) kabın içinde sarılır, kesilmez. `aciklama`: erişilebilir ipucu (klavye/dokunma; yalnız `title`
 * yerine, ET-06). `title` geriye uyum için kalır; yeni kodda `aciklama` kullanılır.
 */
export function Cip({
  ton = "notr",
  children,
  title,
  className,
  bicim = "hap",
  boyut = "normal",
  sar,
  aciklama,
  testId,
}: {
  ton?: Ton;
  children: ReactNode;
  title?: string;
  className?: string;
  bicim?: "hap" | "etiket" | "duz";
  boyut?: "normal" | "kucuk";
  sar?: boolean;
  aciklama?: string;
  testId?: string;
}) {
  const sinif = ["cip", `cip-${ton}`, bicim !== "hap" && `cip-${bicim}`, boyut === "kucuk" && "cip-kucuk", sar && "cip-uzun", className].filter(Boolean).join(" ");
  const cip = (
    <span className={sinif} title={title} data-testid={testId}>
      {children}
    </span>
  );
  return aciklama ? <Ipucu metin={aciklama}>{cip}</Ipucu> : cip;
}

export function Yukleniyor({ metin = "Yükleniyor…" }: { metin?: string }) {
  return (
    <div className="yukleniyor" role="status" aria-live="polite">
      <span className="donen" aria-hidden="true" />
      {metin}
    </div>
  );
}

/**
 * Gösterilen hatanın "son hata" kaydı (AI-ASISTAN-PLANI §5.5): `kaynak` (useVeri/useIslem
 * `hataNesnesi`) verilirse o kayıt, verilmezse metinle eşleşen ya da yeni açılan kayıt.
 * Kayıt dışı hatada (asistan/giriş uçları, 501) null.
 */
function useHataKaydi(kaynak: unknown, hata: string | null, kapali = false): string | null {
  const [kayitId, setKayitId] = useState<string | null>(null);
  useEffect(() => {
    setKayitId(kapali || !hata ? null : hataGosterildi(kaynak, hata));
  }, [kaynak, hata, kapali]);
  return kayitId;
}

/**
 * Gösterilen bir hatanın yanındaki "Asistana sor" (§11): paneli o kaydın bağlamıyla açar.
 * Yalnız asistan kullanılabilirken görünür. Karar ekranlarının satır içi hata/409 uyarıları
 * (`alan-hata`) bunu doğrudan kullanır; HataKutusu `kaynak` verildiğinde kullanır.
 */
export function AsistanaSorDugmesi({ hata, kaynak }: { hata: string | null; kaynak: unknown }) {
  const asistanHazir = useAsistanHazir();
  const kayitId = useHataKaydi(kaynak, hata);
  if (!asistanHazir || !kayitId) return null;
  return (
    <button
      type="button"
      className="dugme dugme-hayalet dugme-kucuk asistana-sor"
      onClick={() => {
        // Düğme 5 dk'dan uzun ekranda kalmış olabilir: kayıt yeniden yazılır (düştüyse yeniden açılır)
        // ve süresi tıklama anından başlar. Aksi halde panel başka bir hatanın bağlamına düşerdi.
        const id = hataGosterildi(kaynak, hata) ?? kayitId;
        hataTazele(id);
        asistanaSor(id);
      }}
    >
      <Ikon ad="aiSor" className="ikon-ai" />
      Asistana sor
    </button>
  );
}

/**
 * Karar ekranlarının satır içi hata/409 uyarısı (`alan-hata`). "Asistana sor" canlı bölgenin
 * (`role="alert"`) dışında, kardeş öğedir: ekran okuyucu duyuruya düğme metnini eklemez; düğme
 * kayıt yazıldıktan sonra belirdiğinde canlı bölgede ikinci bir değişiklik olmaz.
 */
export function AlanHatasi({ children, asistan }: { children: ReactNode; asistan?: { hata: string | null; kaynak: unknown } | null }) {
  return (
    <div className="alan-hata-satir">
      <p className="alan-hata" role="alert">
        {children}
      </p>
      {asistan && <AsistanaSorDugmesi hata={asistan.hata} kaynak={asistan.kaynak} />}
    </div>
  );
}

/**
 * Hata kutusu. Gösterilen hata "son hata" deposuna yazılır (asistan bağlamı, AI-ASISTAN-PLANI §5.5).
 * `kaynak` (useVeri/useIslem `hataNesnesi`) verildiğinde ve asistan kullanılabilirken
 * "Asistana sor" görünür. `kayitDisi`: gösterilen metin kullanıcının karşılaştığı bir API hatası
 * değil (ör. script kaydının saklı `hata` alanı); son hata deposuna yazılmaz.
 */
export function HataKutusu({
  hata,
  yenile,
  kaynak,
  kayitDisi = false,
}: {
  hata: string;
  yenile?: () => void;
  kaynak?: unknown;
  kayitDisi?: boolean;
}) {
  const planli = buFazdaYok(hata) || buFazdaYok(kaynak);
  // Kaynaksız kutu da kayda yazılır (metinle); düğme yalnız kaynakla çizilir.
  useHataKaydi(kaynak, hata, planli || kayitDisi || kaynak !== undefined);
  // Canlı derlemede core'un henüz sunmadığı ekran: hata değil, planlı "bu fazda yok" boş durumu.
  if (planli) {
    return (
      <div className="bos-durum" role="status" data-testid="bu-fazda-yok">
        <p className="bos-baslik">Bu ekran bu fazda yok.</p>
        <div className="soluk">Çekirdek bu veriyi henüz sunmuyor. Canlı portalda örnek veri gösterilmez.</div>
      </div>
    );
  }
  // Yalnız metin canlı bölgededir (AlanHatasi ile aynı desen): düğmeler kardeş öğedir; kayıt
  // yazıldıktan sonra beliren "Asistana sor" duyuruya eklenmez, ikinci değişiklik yaratmaz.
  return (
    <div className="uyari-kutusu uyari-hata">
      <span role="alert">{hata}</span>
      {yenile && !bulunamadi(kaynak) && (
        <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={yenile}>
          Tekrar dene
        </button>
      )}
      {kaynak !== undefined && <AsistanaSorDugmesi hata={hata} kaynak={kaynak} />}
    </div>
  );
}

/**
 * Detay ekranı yüklenemedi (bulunamadı ya da hata): sayfanın kendi başlığı veri olmadan çizilmez,
 * h1 burada çizilir ("Erişim yok" kalıbı, erişilebilirlik). `ad`: kayıt adı ("Koşu" → "Koşu bulunamadı").
 */
export function KayitHatasi({
  ad,
  ust,
  hata,
  kaynak,
  yenile,
  children,
}: {
  ad: string;
  ust?: ReactNode;
  hata: string;
  kaynak?: unknown;
  yenile?: () => void;
  children?: ReactNode;
}) {
  return (
    <>
      <SayfaBasligi ust={ust} baslik={bulunamadi(kaynak) ? `${ad} bulunamadı` : `${ad} yüklenemedi`} />
      <HataKutusu hata={hata} kaynak={kaynak} yenile={yenile} />
      {children}
    </>
  );
}

/** `isaretli`: başlık kendi işaretiyle başlıyor (ör. "✓ Zincir doğrulandı"); maske ikonu çizilmez, işaret iki kez görünmez. */
/**
 * ET-16: sayfa açılışında var olan kalıcı durum kutuları (`Uyari ton="hata"`) `role=alert` değil `note`
 * olur; açılışta ekran okuyucu üst üste kesintili uyarı okumaz. `alert` yalnız kullanıcı eyleminden
 * (tıklama/tuş) sonra beliren kutuda. Kabuk her rota değişiminde `sayfaAcildi()` çağırır; Kabuk dışında
 * (bileşen testleri, giriş ekranı) davranış eskisi gibidir (her zaman `alert`).
 */
let sayfaAcilisi: number | null = null;
let sonEtkilesim = 0;
if (typeof document !== "undefined") {
  const kaydet = () => {
    sonEtkilesim = Date.now();
  };
  document.addEventListener("pointerdown", kaydet, true);
  document.addEventListener("keydown", kaydet, true);
}
export function sayfaAcildi(): void {
  sayfaAcilisi = Date.now();
}
/** Şu an belirecek hata kutusu duyurulmalı mı (açılıştan sonra kullanıcı etkileşimi oldu mu)? */
export function eylemSonrasiMi(): boolean {
  return sayfaAcilisi === null || sonEtkilesim > sayfaAcilisi;
}

export function Uyari({
  ton = "uyari",
  children,
  baslik,
  isaretli,
  id,
}: {
  ton?: "uyari" | "bilgi" | "hata" | "basari";
  children: ReactNode;
  baslik?: string;
  isaretli?: boolean;
  /** Kutu bir düğmenin görünür pasiflik nedeniyse (`aria-describedby` hedefi). */
  id?: string;
}) {
  const [rol] = useState<"alert" | "note">(() => (ton === "hata" && eylemSonrasiMi() ? "alert" : "note"));
  return (
    <div id={id} className={`uyari-kutusu uyari-${ton}${isaretli ? " uyari-isaretli" : ""}`} role={ton === "hata" ? rol : "note"}>
      {baslik && <strong>{baslik}</strong>}
      <div>{children}</div>
    </div>
  );
}

/**
 * Boş durum (tek biçim, TS-13). `kip`: `bolum` (varsayılan; liste/kart gövdesi, ortalı), `sekme` (detay sayfası
 * sekmesinin tek içeriği, DS-1 — kart yüzeyinde, sola hizalı; sekme gizlenmez), `satir` (kart içinde küçük alan:
 * "Varsayım yok." gibi; sola hizalı, dolgusuz). `eylem`: sonraki adım yuvası (bağlantı ya da düğme) — kullanıcı
 * ne yapacağını bilsin ("Henüz koşu yok." → "Koşu başlat").
 */
export function BosDurum({ baslik, children, kip = "bolum", eylem }: { baslik: string; children?: ReactNode; kip?: "bolum" | "sekme" | "satir"; eylem?: ReactNode }) {
  const sinif = kip === "sekme" ? "bos-durum bos-durum-sekme kart" : kip === "satir" ? "bos-durum bos-durum-satir" : "bos-durum";
  return (
    <div className={sinif}>
      <p className="bos-baslik">{baslik}</p>
      {children && <div className="soluk">{children}</div>}
      {eylem && <div className="bos-durum-eylem">{eylem}</div>}
    </div>
  );
}

export function SayfaBasligi({ baslik, aciklama, eylemler, ust }: { baslik: ReactNode; aciklama?: ReactNode; eylemler?: ReactNode; ust?: ReactNode }) {
  return (
    <header className="sayfa-basligi">
      <div>
        {ust && <div className="ust-baglanti">{ust}</div>}
        <h1>{baslik}</h1>
        {aciklama && <p className="soluk">{aciklama}</p>}
      </div>
      {eylemler && <div className="eylemler">{eylemler}</div>}
    </header>
  );
}

export function Kart({ baslik, eylemler, children, className, id }: { baslik?: ReactNode; eylemler?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  const baslikId = useId();
  return (
    <section className={`kart ${className ?? ""}`} aria-labelledby={baslik ? baslikId : undefined} id={id}>
      {(baslik || eylemler) && (
        <div className="kart-baslik">
          {baslik && <h2 id={baslikId}>{baslik}</h2>}
          {eylemler && <div className="eylemler">{eylemler}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

type DugmeTuru = "birincil" | "ikincil" | "tehlike" | "hayalet";

interface IslemDugmesiOzellikleri extends ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * Düğmenin gerektirdiği izin (birden çoksa herhangi biri; `/auth/me` → `izinler`). Yoksa herkes.
   * Yetkisiz rolde düğme pasiftir ve gereken rolü söyler.
   */
  izin?: Izin | readonly Izin[];
  calisiyor?: boolean;
  tur?: DugmeTuru;
  kucuk?: boolean;
  /**
   * Durum nedenini düğmenin altına görünür yazmaz (`title` kalır). Neden zaten ekranda görünür
   * biçimde yazılıysa (ör. Koşular tetik açıklamaları, merge kapı nedenleri) kullanılır; çağıran o
   * görünür metnin kimliğini `aria-describedby` ile geçirir (korunur). Rol nedeni ("gereken rol")
   * başka yerde yazılmadığı için bastırılmaz: yetkisiz rolde neden yine görünür yazılır.
   */
  nedenGizli?: boolean;
  /** Kilitliyken `aria-disabled` (Tab sırasında kalır; ET-07). `EylemCubugu` içinde varsayılan açık. */
  odaklanabilir?: boolean;
}

/**
 * Ortak neden: aynı düğme grubunda (en yakın `.eylemler` / `.satir-ogeler`, yoksa ebeveyn) aynı metinli
 * görünür nedenler bir kez yazılır. DOM sırasındaki ilk düğme nedeni çizer, diğerleri `aria-describedby`
 * ile onun kimliğine bağlanır (aynı rol nedeni grupta tekrar etmez; kapsamsız `getByText` tekil kalır).
 * Sahip kaybolur ya da nedeni değişirse sıradaki düğme nedeni kendisi çizer.
 */
interface NedenKaydi {
  sarici: HTMLElement;
  neden: string;
  id: string;
  ata: (sahipId: string) => void;
}
const nedenGruplari = new WeakMap<Element, Set<NedenKaydi>>();

function nedenGrubunuYenile(kume: Set<NedenKaydi>) {
  const sirali = [...kume].sort((a, b) => (a.sarici.compareDocumentPosition(b.sarici) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
  for (const k of sirali) k.ata(sirali.find((x) => x.neden === k.neden)!.id);
}

/** Bu düğmenin görünür nedeninin çizildiği öğenin kimliği (kendisi ya da gruptaki ilk eş neden). */
function useOrtakNeden(sarici: RefObject<HTMLElement>, neden: string | undefined, id: string): string {
  const [sahip, setSahip] = useState(id);
  useLayoutEffect(() => {
    const el = sarici.current;
    const grup = el?.parentElement?.closest(".eylemler, .satir-ogeler") ?? el?.parentElement;
    if (!el || !grup || !neden) {
      setSahip(id);
      return;
    }
    let kume = nedenGruplari.get(grup);
    if (!kume) nedenGruplari.set(grup, (kume = new Set()));
    const kayit: NedenKaydi = { sarici: el, neden, id, ata: setSahip };
    kume.add(kayit);
    nedenGrubunuYenile(kume);
    return () => {
      kume.delete(kayit);
      nedenGrubunuYenile(kume);
    };
  }, [sarici, neden, id]);
  return sahip;
}

/**
 * Rol farkındalıklı eylem düğmesi: yetkisiz rolde pasif ve nedenini söyler
 * (sunucu yine de her uçta rolü kontrol eder).
 *
 * Pasifken (`disabled` ya da yetkisiz rol) bir neden varsa, native `disabled` düğme odak almadığı ve
 * `title` klavyede okunmadığı için neden düğmenin dışında görünür yazılır (`.dugme-neden`) ve
 * `aria-describedby` ile düğmeye bağlanır. Çalışırken (`calisiyor`) yazılmaz. Aynı gruptaki eş metinli
 * nedenler bir kez yazılır (`useOrtakNeden`).
 */
/**
 * `EylemCubugu` içinde (ya da `odaklanabilir` ile) kilitli `IslemDugmesi` yerel `disabled` yerine `aria-disabled`
 * kullanır: düğme Tab sırasında kalır, nedeni (`aria-describedby`) klavyeyle okunur, tıklama engellenir (ET-07).
 */
export const OdaklanabilirKilitBaglami = createContext(false);

export function IslemDugmesi({ izin, calisiyor, tur = "birincil", kucuk, disabled, children, title, className, nedenGizli, odaklanabilir, onClick, ...geri }: IslemDugmesiOzellikleri) {
  const baglamOdak = useContext(OdaklanabilirKilitBaglami);
  const istenen: Izin[] = izin === undefined ? [] : typeof izin === "string" ? [izin] : [...izin];
  const izinli = useIzin(...istenen);
  const nedenId = useId();
  const yetkili = istenen.length === 0 || izinli;
  const neden = !yetkili ? izinNedeni(...istenen) : title;
  const nedenGorunur = (!nedenGizli || !yetkili) && !calisiyor && (!!disabled || !yetkili) && !!neden?.trim();
  const sariciRef = useRef<HTMLSpanElement>(null);
  const nedenSahibi = useOrtakNeden(sariciRef, nedenGorunur ? neden : undefined, nedenId);
  const nedenCiz = nedenGorunur && nedenSahibi === nedenId;
  const tanim = [geri["aria-describedby"], nedenGorunur ? nedenSahibi : undefined].filter(Boolean).join(" ") || undefined;
  const kilitli = !!(disabled || !yetkili || calisiyor);
  const odakli = odaklanabilir ?? baglamOdak;
  const dugme = (
    <button
      type="button"
      {...geri}
      className={`dugme dugme-${tur}${kucuk ? " dugme-kucuk" : ""} ${className ?? ""}`}
      disabled={odakli ? undefined : kilitli}
      aria-disabled={odakli && kilitli ? true : undefined}
      onClick={
        odakli && kilitli
          ? (e) => {
              e.preventDefault();
            }
          : onClick
      }
      title={neden}
      aria-describedby={tanim}
      aria-busy={calisiyor || undefined}
      data-yetkisiz={!yetkili || undefined}
    >
      {calisiyor && <span className="donen donen-kucuk" aria-hidden="true" />}
      {children}
    </button>
  );
  // Sarıcı her zaman çizilir (neden yokken `display: contents`): neden belirip kaybolurken düğme
  // yeniden bağlanmaz (odak ve öğe kimliği korunur).
  return (
    <span ref={sariciRef} className={`dugme-neden-sarici${nedenCiz ? " neden-var" : ""}`}>
      {dugme}
      {nedenCiz && (
        <span id={nedenId} className="dugme-neden">
          {neden}
        </span>
      )}
    </span>
  );
}

export function Ilerleme({ oran, etiket, hedef }: { oran: number; etiket: string; hedef?: number }) {
  const yuzde = Math.max(0, Math.min(1, oran)) * 100;
  return (
    <div className="ilerleme" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(yuzde)} aria-label={etiket}>
      <div className="ilerleme-dolgu" style={{ width: `${yuzde}%` }} />
      {hedef !== undefined && <div className="ilerleme-hedef" style={{ left: `${hedef * 100}%` }} title={`Hedef: %${Math.round(hedef * 100)}`} />}
    </div>
  );
}

/** Ölçülmemiş değer: sayı uydurulmaz, açıkça "ölçülmedi" yazılır. */
export function Olculmedi({ metin = "ölçülmedi" }: { metin?: string }) {
  return <span className="olculmedi">{metin}</span>;
}

/** `ton`: değerin durum anlamı (§3.4 KPI: başarısız → --err, tamamı geçti → --ok, flaky → --warn); etiket anlamı taşır, renk ek işarettir. */
export function Metrik({ etiket, deger, alt, ton }: { etiket: ReactNode; deger: ReactNode; alt?: ReactNode; ton?: "basari" | "uyari" | "hata" }) {
  return (
    <div className={ton ? `metrik metrik-${ton}` : "metrik"}>
      <div className="metrik-etiket">{etiket}</div>
      <div className="metrik-deger">{deger}</div>
      {alt && <div className="metrik-alt">{alt}</div>}
    </div>
  );
}

export function DisBaglanti({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="dis-baglanti">
      {children}
      <span className="gorunmez"> (yeni sekmede açılır)</span>
      <Ikon ad="dis" className="ikon-dis" />
    </a>
  );
}

/**
 * Korumalı rotaya bağlantı: oturum adresin rotasının iznine (`ROTA_IZINLERI`) sahipse `Link`,
 * değilse düz metin (izinsiz rol "yetkiniz yok" kartına götürülmez). Korumasız adres hep bağlantıdır.
 */
export function IzinliLink({ to, children, ...geri }: { to: string; children: ReactNode } & Omit<LinkProps, "to">) {
  if (!useRotaIzni(to)) return <span className={geri.className}>{children}</span>;
  return (
    <Link to={to} {...geri}>
      {children}
    </Link>
  );
}

/**
 * Adresin türüne göre bağlantı: dış adres yeni sekmede, portal ekranı uygulama içinde açılır.
 * Adres yoksa ya da portalın sunmadığı bir yolsa (ör. artifact sunucusu, forge) tıklanamaz metin
 * olarak gösterilir ve nedeni yazılır — "Sayfa bulunamadı"ya giden ölü bağlantı üretilmez.
 */
export function Baglanti({ href, children, yokNedeni }: { href: string | null | undefined; children: ReactNode; yokNedeni?: string }) {
  const tur = baglantiTuru(href);
  if (tur === "dis" && href) return <DisBaglanti href={href}>{children}</DisBaglanti>;
  if (tur === "ic" && href) return <IzinliLink to={href}>{children}</IzinliLink>;
  return (
    <span className="baglanti-yok">
      {children}
      {yokNedeni && <span className="soluk kucuk"> ({yokNedeni})</span>}
    </span>
  );
}

/**
 * Sayfa içi onay (tarayıcı `confirm` yerine): geri alınması zor eylemden önce sonucu söyleyen kutu.
 * Açılınca "Vazgeç" odak alır (yanlışlıkla Enter'la onaylanmasın); Esc vazgeçer. Kutu `role="group"`
 * ve başlığıyla adlanır; eylem düğmesi metni sonucu söyler (ör. "Evet, yeniden üret").
 */
export function SayfaIciOnay({
  baslik,
  children,
  onayMetni,
  onayla,
  vazgec,
  calisiyor,
  tehlikeli,
  testId,
  vazgecMetni = "Vazgeç",
}: {
  baslik: string;
  children?: ReactNode;
  onayMetni: string;
  /** Vazgeç düğmesinin metni (ör. "İptal"). */
  vazgecMetni?: string;
  onayla: () => void;
  vazgec: () => void;
  calisiyor?: boolean;
  /** Yıkıcı eylem (mevcut veriyi değiştirir): onay düğmesi tehlike tonunda. */
  tehlikeli?: boolean;
  testId?: string;
}) {
  const baslikId = useId();
  const vazgecRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    vazgecRef.current?.focus();
  }, []);
  return (
    <div
      role="group"
      aria-labelledby={baslikId}
      className="uyari-kutusu uyari-uyari sayfa-ici-onay"
      data-testid={testId}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          vazgec();
        }
      }}
    >
      <strong id={baslikId}>{baslik}</strong>
      <div>
        {children}
        <div className="eylemler sayfa-ici-onay-eylemler">
          <button
            type="button"
            className={`dugme ${tehlikeli ? "dugme-tehlike" : "dugme-birincil"} dugme-kucuk`}
            onClick={onayla}
            disabled={calisiyor}
            aria-busy={calisiyor || undefined}
          >
            {calisiyor && <span className="donen donen-kucuk" aria-hidden="true" />}
            {onayMetni}
          </button>
          <button ref={vazgecRef} type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={vazgec} disabled={calisiyor}>
            {vazgecMetni}
          </button>
        </div>
      </div>
    </div>
  );
}

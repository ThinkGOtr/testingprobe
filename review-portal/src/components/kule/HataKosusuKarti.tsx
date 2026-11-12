// 012/Ş8 (ANALIZ §4.6, §7): Kontrol Kulesi "Ekilmiş hata koşusu" kartı.
// Demo uygulama her seferinde tek bir hatayla bilerek bozulur, onaylı test paketi koşar; en az bir test
// kırmızıya dönerse hata "yakalandı", hepsi yeşil kalırsa "kaçtı". Kart: başlatma formu (engineer,
// presenter), süren koşunun ilerlemesi, hata × platform sonuç tablosu, kaçan hatalar ve son koşular.
// Renk tek başına anlam taşımaz: sonuçlar ✓ ✗ ⚠ işaretli metindir; `gecersiz` adımın nedeni görünür yazılır.
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Link } from "react-router-dom";
import { api, HATA_KOSUSU_SURUYOR, hataKosusuApi } from "../../api/client";
import { useOlay } from "../../api/events";
import { ApiError, hataMesaji } from "../../api/http";
import type { HataKatalogOgesi, HataKosusu, HataKosusuAdimi, HataKosusuDetay, HataKosusuKapsami, HataTuru, KiranTest, Rol } from "../../api/types";
import { hataKosusuSuruyorMu, kaynakBilgisiVar, kaynakOrani, yakalamaOrani } from "../../api/uyumKule";
import { useOturum } from "../../auth";
import { useGeciktirilmis, useVeri } from "../../hooks";
import { ekilmisHataAdi, HATA_ADIM_SONUCU, HATA_KOSUSU_DURUMU, HATA_TURU } from "../../lib/etiketler";
import { sure, tarih, yuzde } from "../../lib/format";
import { PLATFORMLAR, PLATFORM_ETIKETI, uygulamaPlatformuMu, type Platform } from "../../lib/platform";
import { KisiAdi } from "../KisiAdi";
import { useBildirim } from "../Bildirim";
import { BosDurum, Cip, HataKutusu, Ilerleme, IslemDugmesi, Kart, Olculmedi, Uyari, Yukleniyor } from "../ui";
import "./kule-hata.css";

/** V4: koşuyu başlatabilen ve iptal edebilen roller. */
export const HATA_KOSUSU_ROLLERI: Rol[] = ["engineer", "presenter"];
const TURLER: HataTuru[] = ["kod", "veri"];
const SURUYOR_MESAJI = "Süren bir ekilmiş hata koşusu var. Bitmesini bekleyin ya da koşuyu iptal edin.";
/** ANALIZ §10: uygulama platformlarında koşu hata başına 3–5 dakika sürer. */
const UYGULAMA_DK = [3, 5] as const;
/** Web suite'in bir koşusu (demo uygulama, ~40–60 sn): yaklaşık 1 dakika. */
const WEB_DK = 1;
/** Tahmini üst süre bunu aşarsa başlatmadan önce onay istenir (dakika). */
export const ONAY_ESIGI_DK = 15;
/** Temel ve kapanış: her platformda hata koşularına ek iki çerçeve koşusu. */
const CERCEVE_KOSUSU = 2;
const YOKLAMA_MS = 5000;
/** Geçen süre göstergesinin yenilenme aralığı. */
const SAAT_MS = 10_000;

/** Seçimin koşu sayısı ve süre tahmini (dakika aralığı); platform yoksa süre null. */
export function kosuTahmini(platformlar: readonly Platform[], hataSayisi: number): { kosuBasina: number; toplam: number; dk: [number, number] | null } {
  const kosuBasina = hataSayisi + CERCEVE_KOSUSU;
  const uygulama = platformlar.filter(uygulamaPlatformuMu).length;
  const web = platformlar.includes("web") ? kosuBasina * WEB_DK : 0;
  return {
    kosuBasina,
    toplam: platformlar.length * kosuBasina,
    dk: platformlar.length === 0 ? null : [web + uygulama * kosuBasina * UYGULAMA_DK[0], web + uygulama * kosuBasina * UYGULAMA_DK[1]],
  };
}

const dkAraligi = ([a, b]: [number, number]) => (a === b ? `${a}` : `${a}–${b}`);

const ASAMA_ADI: Record<HataKosusuAdimi["asama"], string> = {
  temel: "Temel koşu (hatasız)",
  hata: "Hata koşusu",
  kapanis: "Kapanış koşusu (hatasız)",
};

function adimAdi(a: HataKosusuAdimi, katalog: Map<string, HataKatalogOgesi>): string {
  return a.asama === "hata" && a.hata_kodu ? ekilmisHataAdi(a.hata_kodu, katalog.get(a.hata_kodu)?.ad ?? a.hata_adi) : ASAMA_ADI[a.asama];
}

/** Oran metni: "%78 (7/9)"; payda 0 ise null (çağıran "ölçülmedi" yazar). */
function oranMetni(o: { oran: number | null; yakalanan: number; kacan: number }): string | null {
  return o.oran === null ? null : `${yuzde(o.oran)} (${o.yakalanan}/${o.yakalanan + o.kacan})`;
}

export function HataKosusuKarti({ olcuDegisti }: { olcuDegisti?: () => void }) {
  const { kullanici } = useOturum();
  const yetkili = !!kullanici && HATA_KOSUSU_ROLLERI.includes(kullanici.rol);
  const katalog = useVeri(() => hataKosusuApi.katalog(), []);
  const liste = useVeri(() => hataKosusuApi.liste(5), []);
  const [secili, setSecili] = useState<string | null>(null);

  const suren = liste.veri?.find(hataKosusuSuruyorMu) ?? null;
  const gosterilenId = secili ?? suren?.id ?? liste.veri?.[0]?.id ?? null;
  const detay = useVeri(() => (gosterilenId ? hataKosusuApi.detay(gosterilenId) : Promise.resolve(null)), [gosterilenId]);
  // Süren koşunun adımları (ilerleme): gösterilen koşu o değilse ayrıca okunur.
  const surenDetay = useVeri(() => (suren && suren.id !== gosterilenId ? hataKosusuApi.detay(suren.id) : Promise.resolve(null)), [suren?.id, gosterilenId]);

  // Koşu bitince Kule ölçüleri yenilenir — koşu başına bir kez: bitiş olayı (SSE) ya da olay akışı yokken
  // yoklamada süren koşunun listeden kalkması (hangisi önce gelirse).
  const olcuRef = useRef(olcuDegisti);
  olcuRef.current = olcuDegisti;
  const bildirilen = useRef<string | null>(null);
  const bitisiBildir = useCallback((id: string) => {
    if (bildirilen.current === id) return;
    bildirilen.current = id;
    olcuRef.current?.();
  }, []);
  const biten = useRef<string | null>(null);
  // Olay patlamaları (adım başına bir olay) tek yenilemede birleşir.
  const sessiz = useGeciktirilmis(() => {
    void liste.yenile(true);
    void detay.yenile(true);
    void surenDetay.yenile(true);
    if (biten.current) {
      bitisiBildir(biten.current);
      biten.current = null;
    }
  }, 300);
  useOlay(
    (o) => {
      const d = o.data.durum;
      if ((d === "done" || d === "failed" || d === "cancelled") && typeof o.data.id === "string") biten.current = o.data.id;
      sessiz();
    },
    ["hata_kosusu.ilerleme"],
  );

  // Olay akışı kopuk ya da yokken de ilerleme görünür: koşu sürerken seyrek yoklama (olaylar gelirse zararsız).
  const surenId = suren?.id ?? null;
  useEffect(() => {
    if (!surenId) return;
    const t = setInterval(sessiz, YOKLAMA_MS);
    return () => clearInterval(t);
  }, [surenId, sessiz]);
  // Süren koşu listeden kalktı (bitti ya da iptal edildi): olay gelmemiş olsa da Kule ölçüleri yenilenir.
  const oncekiSuren = useRef<string | null>(null);
  useEffect(() => {
    const onceki = oncekiSuren.current;
    oncekiSuren.current = surenId;
    if (onceki && !surenId && liste.veri) bitisiBildir(onceki);
  }, [surenId, liste.veri, bitisiBildir]);

  // Odak yönetimi (durum geçişlerinde odak kaybolmaz): başlatınca ilerlemeye, iptal ve "Aç" sonrası sonuç başlığına.
  const [odak, setOdak] = useState<"ilerleme" | "sonuc" | "baslat" | null>(null);
  const ilerlemeRef = useRef<HTMLDivElement | null>(null);
  const sonucRef = useRef<HTMLHeadingElement | null>(null);
  const baslatRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!odak) return;
    const hedef =
      odak === "ilerleme"
        ? ilerlemeRef.current
        : odak === "baslat"
          ? (baslatRef.current?.querySelector("button") ?? null)
          : detay.veri && detay.veri.id === gosterilenId && !detay.yukleniyor
            ? sonucRef.current
            : null;
    if (hedef) {
      hedef.focus();
      setOdak(null);
    }
  });

  const katalogHaritasi = useMemo(() => new Map((katalog.veri ?? []).map((h) => [h.kod, h])), [katalog.veri]);

  // ---- form
  const [platformlar, setPlatformlar] = useState<Platform[]>(["web"]); // V5: yalnız web işaretli
  // null: kullanıcı seçime dokunmadı → kataloğun tamamı (varsayılan hepsi seçili).
  const [hataSecimi, setHataSecimi] = useState<string[] | null>(null);
  const tumHatalar = (katalog.veri ?? []).map((h) => h.kod);
  const secilenHatalar = hataSecimi === null ? tumHatalar : tumHatalar.filter((h) => hataSecimi.includes(h));
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  /** Uzun koşu (> ONAY_ESIGI_DK) için başlatmadan önce açılan onay adımı. */
  const [onaySoruluyor, setOnaySoruluyor] = useState(false);
  const onayRef = useRef<HTMLDivElement | null>(null);

  const degistir = <T,>(dizi: T[], x: T, sec: boolean): T[] => (sec ? [...dizi.filter((y) => y !== x), x] : dizi.filter((y) => y !== x));

  const tahmin = kosuTahmini(platformlar, secilenHatalar.length);
  const uzun = !!tahmin.dk && tahmin.dk[1] > ONAY_ESIGI_DK;

  const baslat = async (onayli = false) => {
    if (uzun && !onayli) {
      setOnaySoruluyor(true);
      requestAnimationFrame(() => onayRef.current?.focus());
      return;
    }
    setOnaySoruluyor(false);
    setCalisiyor(true);
    setHata(null);
    try {
      await hataKosusuApi.baslat({
        platformlar: PLATFORMLAR.filter((p) => platformlar.includes(p)),
        // Tüm katalog seçiliyse `hatalar` gönderilmez (sözleşme: verilmezse tamamı).
        ...(secilenHatalar.length === tumHatalar.length ? {} : { hatalar: secilenHatalar }),
      });
      setSecili(null);
      setOdak("ilerleme");
    } catch (e) {
      setHata(e instanceof ApiError && (e.kod === HATA_KOSUSU_SURUYOR || e.status === 409) ? SURUYOR_MESAJI : hataMesaji(e));
    } finally {
      setCalisiyor(false);
      void liste.yenile(true);
    }
  };

  const iptal = async (id: string) => {
    setCalisiyor(true);
    setHata(null);
    try {
      await hataKosusuApi.iptal(id);
      setSecili(id);
      setOdak("sonuc");
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setCalisiyor(false);
      void liste.yenile(true);
      void detay.yenile(true);
    }
  };

  const baslatmaNedeni = suren
    ? "Süren koşu bitmeden yenisi başlatılamaz."
    : katalog.hata
      ? "Hata kataloğu okunamadı."
      : platformlar.length === 0
        ? "En az bir platform seçin."
        : secilenHatalar.length === 0
          ? "En az bir hata seçin."
          : undefined;

  const uygulamaSayisi = platformlar.filter(uygulamaPlatformuMu).length;
  const formKapali = !yetkili || !!suren || calisiyor;

  return (
    <Kart baslik="Ekilmiş hata koşusu" className="hk-kart">
      <p className="hk-aciklama" data-testid="hk-aciklama">
        Demo uygulama her seferinde <strong>tek bir hatayla bilerek bozulur</strong> ve onaylı testler koşturulur. Testlerin kırmızıya dönmesi
        beklenir: en az bir test kırmızıysa hata <strong>yakalandı</strong>, hepsi yeşil kaldıysa hata <strong>kaçtı</strong>. Kaçan hata, o
        kuralı sınayan bir testin eksik olduğunu gösterir. Bu koşular kasıtlı kırmadır: geçme oranına girmez, bug taslağı açmaz.
      </p>

      {/* ------------------------------------------------ başlatma formu */}
      <form
        className="hk-form"
        aria-label="Ekilmiş hata koşusu başlat"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <fieldset className="hk-grup" disabled={formKapali}>
          <legend>Platformlar</legend>
          <div className="hk-secenekler">
            {PLATFORMLAR.map((p) => (
              <label key={p} className="hk-secenek">
                <input
                  type="checkbox"
                  checked={platformlar.includes(p)}
                  onChange={(e) => setPlatformlar((o) => degistir(o, p, e.target.checked))}
                  data-testid={`hk-platform-${p}`}
                />
                <span>{PLATFORM_ETIKETI[p]}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {katalog.yukleniyor && !katalog.veri ? (
          <Yukleniyor metin="Hata kataloğu yükleniyor…" />
        ) : katalog.hata && !katalog.veri ? (
          <HataKutusu hata={katalog.hata} kaynak={katalog.hataNesnesi} yenile={() => void katalog.yenile()} />
        ) : (
          <div className="hk-turler">
            {TURLER.map((tur) => {
              const ogeler = (katalog.veri ?? []).filter((h) => h.tur === tur);
              if (ogeler.length === 0) return null;
              return (
                <fieldset key={tur} className="hk-grup" disabled={formKapali} data-testid={`hk-tur-${tur}`}>
                  <legend>
                    {HATA_TURU[tur]} ({ogeler.length})
                  </legend>
                  <ul className="hk-hatalar">
                    {ogeler.map((h) => (
                      <li key={h.kod}>
                        <label className="hk-secenek">
                          <input
                            type="checkbox"
                            checked={secilenHatalar.includes(h.kod)}
                            onChange={(e) => setHataSecimi(degistir(secilenHatalar, h.kod, e.target.checked))}
                            aria-describedby={`hk-hata-${h.kod}`}
                          />
                          <span>{h.ad}</span>
                        </label>
                        <div className="hk-secenek-alt kucuk" id={`hk-hata-${h.kod}`}>
                          {h.aciklama}
                          {h.yakalayan_kural ? ` Yakalaması beklenen kural: ${h.yakalayan_kural}.` : ""} <span className="mono">{h.kod}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              );
            })}
          </div>
        )}

        <p className="kucuk hk-tahmin" data-testid="hk-tahmin">
          Seçim: {secilenHatalar.length} hata + {CERCEVE_KOSUSU} çerçeve koşusu (temel, kapanış) = {tahmin.kosuBasina} koşu / platform;{" "}
          {platformlar.length} platform × {tahmin.kosuBasina} = toplam {tahmin.toplam} koşu. Platformlar sırayla koşar.{" "}
          {tahmin.dk && <span data-testid="hk-sure-tahmini">Tahmini süre: yaklaşık {dkAraligi(tahmin.dk)} dakika (web'de koşu başına ~{WEB_DK} dk). </span>}
          {uygulamaSayisi > 0 ? (
            <strong>
              Android, iOS ve Windows'ta her koşu {UYGULAMA_DK[0]}–{UYGULAMA_DK[1]} dakika sürer. Cihaz ya da emülatör açık olmalı; ulaşılamayan
              platformun adımları geçersiz sayılır.
            </strong>
          ) : (
            <>
              Android, iOS ve Windows'ta her koşu {UYGULAMA_DK[0]}–{UYGULAMA_DK[1]} dakika sürer; cihaz ya da emülatör açık olmalı.
            </>
          )}
        </p>

        {onaySoruluyor && tahmin.dk && !baslatmaNedeni ? (
          <div className="hk-onay" ref={onayRef} tabIndex={-1} data-testid="hk-onay" role="group" aria-label="Uzun koşu onayı">
            <Uyari baslik="Uzun koşu">
              Bu seçim yaklaşık {dkAraligi(tahmin.dk)} dakika sürer ({tahmin.toplam} koşu). Bu sürede başka ekilmiş hata koşusu başlatılamaz. Başlatılsın mı?
            </Uyari>
            <div className="satir-ogeler">
              <IslemDugmesi roller={HATA_KOSUSU_ROLLERI} calisiyor={calisiyor} onClick={() => void baslat(true)}>
                Evet, başlat
              </IslemDugmesi>
              <button
                type="button"
                className="dugme dugme-hayalet"
                onClick={() => {
                  setOnaySoruluyor(false);
                  setOdak("baslat");
                }}
              >
                Vazgeç
              </button>
            </div>
          </div>
        ) : (
          <div className="satir-ogeler" ref={baslatRef}>
            <IslemDugmesi
              roller={HATA_KOSUSU_ROLLERI}
              calisiyor={calisiyor && !suren}
              disabled={!!baslatmaNedeni}
              title={baslatmaNedeni}
              onClick={() => void baslat()}
            >
              Koşuyu başlat
            </IslemDugmesi>
          </div>
        )}
        {hata && (
          <Uyari ton="hata">
            <span data-testid="hk-hata">{hata}</span>
          </Uyari>
        )}
      </form>

      {/* ------------------------------------------------ süren koşu */}
      {suren && (
        <Ilerlemesi
          kok={ilerlemeRef}
          kosu={suren}
          detay={detay.veri?.id === suren.id ? detay.veri : (surenDetay.veri ?? null)}
          katalog={katalogHaritasi}
          calisiyor={calisiyor}
          iptal={() => void iptal(suren.id)}
        />
      )}

      {/* ------------------------------------------------ sonuç tablosu */}
      {liste.yukleniyor && !liste.veri ? (
        <Yukleniyor metin="Koşular yükleniyor…" />
      ) : liste.hata && !liste.veri ? (
        <HataKutusu hata={liste.hata} kaynak={liste.hataNesnesi} yenile={() => void liste.yenile()} />
      ) : !gosterilenId ? (
        <BosDurum baslik="Henüz ekilmiş hata koşusu yok.">Hata yakalama oranı ölçülmedi; ilk koşudan sonra burada görünür.</BosDurum>
      ) : detay.hata && !detay.veri ? (
        <HataKutusu hata={detay.hata} kaynak={detay.hataNesnesi} yenile={() => void detay.yenile()} />
      ) : !detay.veri ? (
        <Yukleniyor metin="Koşu sonucu yükleniyor…" />
      ) : (
        <Sonuc kosu={detay.veri} katalog={katalogHaritasi} baslikRef={sonucRef} />
      )}

      {/* ------------------------------------------------ geçmiş */}
      {liste.veri && liste.veri.length > 0 && <Gecmis
          kosular={liste.veri}
          gosterilenId={gosterilenId}
          ac={(id) => {
            setSecili(id);
            setOdak("sonuc");
          }}
        />
      }
    </Kart>
  );
}

/** "12:04" (saat:dakika, yerel saat). */
const saatDakika = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "—");

/** "6 dk", 1 dakikadan kısa ise "<1 dk". */
const dakika = (ms: number) => (ms < 60_000 ? "<1 dk" : `${Math.round(ms / 60_000)} dk`);

/** Kalan adımların tahmini (biten adım yoksa platform başına sabit tahmin; varsa ortalama adım süresi). */
function kalanTahmini(adimlar: readonly HataKosusuAdimi[], gecenMs: number | null): number | null {
  const kalan = adimlar.filter((a) => a.sonuc === "bekliyor");
  if (adimlar.length === 0) return null;
  const biten = adimlar.length - kalan.length;
  if (biten > 0 && gecenMs !== null && gecenMs > 0) return (gecenMs / biten) * kalan.length;
  return kalan.reduce((t, a) => t + (a.platform === "web" ? WEB_DK : (UYGULAMA_DK[0] + UYGULAMA_DK[1]) / 2) * 60_000, 0);
}

function Ilerlemesi({
  kok,
  kosu,
  detay,
  katalog,
  calisiyor,
  iptal,
}: {
  kok: MutableRefObject<HTMLDivElement | null>;
  kosu: HataKosusu;
  detay: HataKosusuDetay | null;
  katalog: Map<string, HataKatalogOgesi>;
  calisiyor: boolean;
  iptal: () => void;
}) {
  const adimlar = detay?.adimlar ?? [];
  const biten = adimlar.filter((a) => a.sonuc !== "bekliyor").length;
  const simdiki = adimlar.find((a) => a.sonuc === "bekliyor") ?? null;
  // Geçen süre için seyrek saat (ekran okuyucuya duyurulmaz; canlı bölge yalnız adım değişiminde).
  const [simdi, setSimdi] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setSimdi(Date.now()), SAAT_MS);
    return () => clearInterval(t);
  }, []);
  const basladi = kosu.baslama ? new Date(kosu.baslama).getTime() : NaN;
  const gecenMs = Number.isFinite(basladi) ? Math.max(0, simdi - basladi) : null;
  const kalanMs = kosu.durum === "running" ? kalanTahmini(adimlar, gecenMs) : null;
  const iptalIstendi = kosu.iptal_istendi === true;
  const durumAdi = iptalIstendi ? "İptal istendi, adım bitince durur" : kosu.durum === "queued" ? "Koşu sırada" : "Koşu sürüyor";
  const adimMetni = simdiki ? `${PLATFORM_ETIKETI[simdiki.platform]} · ${adimAdi(simdiki, katalog)}` : null;
  const sayacMetni = adimlar.length > 0 ? `adım ${Math.min(biten + 1, adimlar.length)} / ${adimlar.length}` : null;
  return (
    <div className="hk-ilerleme" data-testid="hk-ilerleme" role="group" aria-label="Süren ekilmiş hata koşusu" ref={kok} tabIndex={-1}>
      {/* Tek canlı bölge: yalnız durum ya da adım değişince metni değişir (süre sayacı burada değil). */}
      <span className="gorunmez" role="status" aria-live="polite" data-testid="hk-duyuru">
        {[durumAdi, adimMetni, sayacMetni].filter(Boolean).join(" · ")}
      </span>
      <div className="hk-ilerleme-ust">
        <div>
          <strong>{durumAdi}</strong>
          {adimMetni ? <span data-testid="hk-simdiki"> · {adimMetni}</span> : null}
          {sayacMetni && (
            <span className="hk-sayac mono" data-testid="hk-sayac">
              {" "}
              · {sayacMetni}
            </span>
          )}
        </div>
        <div className="satir-ogeler">
          <IslemDugmesi
            roller={HATA_KOSUSU_ROLLERI}
            tur="ikincil"
            kucuk
            calisiyor={calisiyor}
            disabled={iptalIstendi}
            title={iptalIstendi ? "İptal istendi; süren adım bitince koşu durur." : undefined}
            onClick={iptal}
          >
            İptal et
          </IslemDugmesi>
        </div>
      </div>
      {adimlar.length > 0 && <Ilerleme oran={biten / adimlar.length} etiket="Ekilmiş hata koşusu ilerlemesi" />}
      <p className="kucuk hk-sure" data-testid="hk-sure">
        {gecenMs === null ? (
          "Henüz başlamadı (sırada)."
        ) : (
          <>
            başladı {saatDakika(kosu.baslama)} · geçen {dakika(gecenMs)}
            {kalanMs !== null && ` · tahmini kalan ~${dakika(kalanMs)}`}
          </>
        )}
      </p>
      <p className="kucuk hk-ilerleme-not">
        {kosu.platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")} · {kosu.hatalar.length} hata. Sonuçlar aşağıdaki tabloya adım adım
        yazılır.
      </p>
    </div>
  );
}

const KAYNAK_ADI: Record<"ai" | "el", string> = { ai: "AI testi", el: "el yazısı" };

/** "(1 AI testi, 2 el yazısı)"; kaynak bilinmiyorsa boş. */
function kaynakOzeti(testler: readonly KiranTest[]): string {
  const ai = testler.filter((t) => t.kaynak === "ai").length;
  const el = testler.filter((t) => t.kaynak === "el").length;
  const parca = [ai ? `${ai} ${KAYNAK_ADI.ai}` : "", el ? `${el} ${KAYNAK_ADI.el}` : ""].filter(Boolean);
  return parca.length ? ` (${parca.join(", ")})` : "";
}

function Hucre({ a, ad, platform }: { a: HataKosusuAdimi | undefined; ad: string; platform: Platform }) {
  if (!a) return <span className="hk-bos">—</span>;
  const s = HATA_ADIM_SONUCU[a.sonuc];
  return (
    <div className="hk-hucre" data-sonuc={a.sonuc}>
      <div className="hk-hucre-ust">
        <Cip ton={s.ton}>{s.etiket}</Cip>
        {a.run_id && (
          <Link to={`/kosular/${encodeURIComponent(a.run_id)}`} className="kucuk" title={a.sure_ms !== null ? `Süre: ${sure(a.sure_ms)}` : undefined}>
            koşuyu aç
            <span className="gorunmez">
              : {ad} · {PLATFORM_ETIKETI[platform]}
            </span>
          </Link>
        )}
      </div>
      {/* Neden yalnız ipucunda değil, görünür metin (dokunmatik ve klavye kullanıcıları için). */}
      {a.neden && (a.sonuc === "gecersiz" || a.sonuc === "kirmizi") && <div className="hk-neden kucuk">Neden: {a.neden}</div>}
      {/* R4: yakalanan adımda core'un notu (ör. assertion dışı nedenle düşen, sayılmayan testler). */}
      {a.neden && a.sonuc === "yakalandi" && (
        <div className="hk-neden kucuk" data-testid="hk-not">
          Not: {a.neden}
        </div>
      )}
      {a.sonuc === "yakalandi" &&
        (a.kiran_testler.length > 0 ? (
          <details className="hk-testler">
            <summary>
              {a.kiran_testler.length} test yakaladı{kaynakOzeti(a.kiran_testler)}
              <span className="gorunmez">
                : {ad} · {PLATFORM_ETIKETI[platform]}
              </span>
            </summary>
            <ul>
              {a.kiran_testler.map((t) => (
                <li key={t.test}>
                  {t.test}
                  {t.kaynak && (
                    <>
                      {" "}
                      {/* Mor yalnız AI çıktısı: üretilmiş test AI çıktısıdır; el yazısı nötr. */}
                      <Cip ton={t.kaynak === "ai" ? "vurgu" : "notr"}>{KAYNAK_ADI[t.kaynak]}</Cip>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </details>
        ) : (
          <div className="kucuk hk-neden">Kıran test adı bildirilmedi.</div>
        ))}
    </div>
  );
}

/** Kuralın görünen adı: "T1 · AC2"; tablosuz "AC1 (tablo yok)"; K9 alanları yoksa katalogdaki yakalayan kural. */
export function kuralEtiketi(oge: HataKatalogOgesi | undefined): string {
  if (!oge) return "Kural bilinmiyor";
  const ac = oge.ac_refs?.join(", ") ?? "";
  if (oge.tablo) return ac ? `${oge.tablo} · ${ac}` : oge.tablo;
  if (ac) return `${ac} (tablo yok)`;
  return oge.yakalayan_kural ?? "Kural bilinmiyor";
}

/** Kaçan hata için analiste iletilecek case isteği (düz metin; panoya kopyalanır). */
export function caseIstegiMetni(kod: string, oge: HataKatalogOgesi | undefined, platformlar: readonly Platform[]): string {
  const ad = ekilmisHataAdi(kod, oge?.ad);
  const parcalar = [
    `Case isteği: ekilmiş hata "${ad}" (${kod}) ${platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")} koşusunda hiçbir onaylı testle yakalanmadı.`,
    `Kural: ${kuralEtiketi(oge)}.`,
  ];
  const a = oge?.ayirt_edici;
  if (a) parcalar.push(`Ayırt edici örnek: ${a.girdi} → doğru: ${a.dogru}; hatalı uygulama: ${a.hatali}.`);
  parcalar.push("Bu girdiyle beklenen değeri onaylı karar tablosuna göre yazan bir case ekleyin.");
  return parcalar.join(" ");
}

/** "T1 · AC2" → karar tablosuna bağlantı (gereksinim biliniyorsa; tablo kimliği `T<sira_no>`'dan çözülür). */
function KuralBaglantisi({ oge }: { oge: HataKatalogOgesi | undefined }) {
  const req = oge?.requirement_id ?? null;
  const tabloEtiketi = oge?.tablo ?? null;
  const tablolar = useVeri(() => (req && tabloEtiketi ? api.kararTablolari(req).then((y) => y.tablolar, () => null) : Promise.resolve(null)), [req, tabloEtiketi]);
  const etiket = kuralEtiketi(oge);
  if (!req) return <>{etiket}</>;
  const tablo = (tablolar.veri ?? []).find((t) => `T${t.sira_no}` === tabloEtiketi && t.durum !== "superseded");
  return (
    <Link to={`/gereksinimler/${encodeURIComponent(req)}/karar-tablolari${tablo ? `#tablo-${tablo.id}` : ""}`}>
      {etiket}
      <span className="gorunmez"> karar tablosunu aç</span>
    </Link>
  );
}

function KacanHata({ kod, oge, platformlar }: { kod: string; oge: HataKatalogOgesi | undefined; platformlar: Platform[] }) {
  const bildir = useBildirim();
  const istek = caseIstegiMetni(kod, oge, platformlar);
  const a = oge?.ayirt_edici ?? null;
  const req = oge?.requirement_id ?? null;
  async function kopyala() {
    try {
      await navigator.clipboard.writeText(istek);
      bildir("Case isteği panoya kopyalandı.");
    } catch {
      bildir("Kopyalanamadı; metni elle seçin.", "hata");
    }
  }
  return (
    <li data-testid={`hk-kacan-${kod}`}>
      {/* ✗ adla aynı metinde: tek karakterlik ayrı öğe axe kontrastını "incomplete"e düşürür. */}
      <div>
        <strong>✗ {ekilmisHataAdi(kod, oge?.ad)}</strong> <span className="kucuk">· {platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")}</span>
        {oge?.aciklama && <div className="kucuk hk-neden">{oge.aciklama}</div>}
      </div>
      <dl className="hk-kacan-ayrinti kucuk" data-testid={`hk-kacan-ayrinti-${kod}`}>
        <dt>Kural</dt>
        <dd>
          <KuralBaglantisi oge={oge} />
        </dd>
        {a ? (
          <>
            <dt>Ayırt edici girdi</dt>
            <dd>
              <span className="mono">{a.girdi}</span> → doğru <span className="mono">{a.dogru}</span>, hatalı uygulama{" "}
              <span className="mono">{a.hatali}</span>
            </dd>
            <dt>Olası neden</dt>
            <dd>Bu girdiyi deneyen onaylı test yok; mevcut testlerin girdilerinde doğru ve hatalı uygulama aynı sonucu veriyor.</dd>
          </>
        ) : (
          <>
            <dt>Ayırt edici girdi</dt>
            <dd className="soluk">Katalog bu hata için ayırt edici örnek vermiyor.</dd>
          </>
        )}
      </dl>
      <div className="hk-istek">
        <p className="kucuk" data-testid={`hk-istek-${kod}`}>
          {istek}
        </p>
        <div className="satir-ogeler">
          {req && a && (
            <Link className="dugme dugme-ikincil dugme-kucuk" to={`/gereksinimler/${encodeURIComponent(req)}/karar-tablolari#ek-case-turet`}>
              Bu girdiyle ek case türet
            </Link>
          )}
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void kopyala()}>
            Case isteğini kopyala
          </button>
        </div>
      </div>
    </li>
  );
}

/** Platform başına "x / y" ya da ölçülmedi. */
function OranHucresi({ o, olculmediMetni = "ölçülmedi" }: { o: { oran: number | null; yakalanan: number; kacan: number } | null; olculmediMetni?: string }) {
  const m = o ? oranMetni(o) : null;
  return m ? <strong>{m}</strong> : <Olculmedi metin={olculmediMetni} />;
}

function Sonuc({
  kosu,
  katalog,
  baslikRef,
}: {
  kosu: HataKosusuDetay;
  katalog: Map<string, HataKatalogOgesi>;
  baslikRef?: MutableRefObject<HTMLHeadingElement | null>;
}) {
  const adim = (platform: Platform, asama: HataKosusuAdimi["asama"], kod: string | null) =>
    kosu.adimlar.find((a) => a.platform === platform && a.asama === asama && a.hata_kodu === kod);
  const suruyor = hataKosusuSuruyorMu(kosu);
  const d = HATA_KOSUSU_DURUMU[kosu.durum];
  const genel = yakalamaOrani(kosu.adimlar);
  // Kaçan hatalar: hata bazında, kaçtığı platformlarla.
  const kacanlar = kosu.hatalar
    .map((kod) => ({ kod, platformlar: kosu.platformlar.filter((p) => adim(p, "hata", kod)?.sonuc === "kacti") }))
    .filter((x) => x.platformlar.length > 0);

  // K12 (§13.2): AI (üretilmiş) testleri ve el yazısı suite ayrı. Kaynak bilgisi yoksa (eski çekirdek) ayrım çizilmez.
  const ayrik = kaynakBilgisiVar(kosu.adimlar) || !!kosu.ozet?.el_yazisi;
  const aiVar = kaynakOrani(kosu.adimlar, "ai").olculdu || (!!kosu.ozet?.el_yazisi && kosu.ozet.oran !== null);
  const kaynakIcin = (pa: HataKosusuAdimi[], k: "ai" | "el") => {
    const o = kaynakOrani(pa, k);
    return { oran: o.yakalanan + o.kacan > 0 ? o.yakalanan / (o.yakalanan + o.kacan) : null, yakalanan: o.yakalanan, kacan: o.kacan };
  };
  const pAdim = (p: Platform) => kosu.adimlar.filter((a) => a.platform === p);
  const aiGenel = aiVar ? kaynakIcin(kosu.adimlar, "ai") : null;
  const elGenel = kaynakIcin(kosu.adimlar, "el");

  // Kapsam satırı: çekirdeğin `kapsam`'ı; yoksa koşunun hata listesi ve okunabildiyse katalog boyu.
  const kapsam: HataKosusuKapsami = kosu.ozet?.kapsam ?? { kosulan_hata: kosu.hatalar.length, katalog: katalog.size, platformlar: kosu.platformlar };
  // R4: platform başına suite'teki üretilmiş / el yazısı test sayıları (core verirse).
  const testSayilari = (kosu.ozet?.platformlar ?? [])
    .filter((p) => p.uretilen_test !== undefined || p.el_test !== undefined)
    .map((p) => `${PLATFORM_ETIKETI[p.platform]} ${p.uretilen_test ?? "?"} üretilmiş (AI) + ${p.el_test ?? "?"} el yazısı test`);
  // K12: temelde kırmızı olduğu için sayılmayan testler (platform başına). Alan hiç yoksa satır çizilmez.
  const temeldeBilgi = kosu.adimlar.some((a) => a.temelde_kirmizi !== undefined);
  const temeldeKirmizi = kosu.platformlar
    .map((p) => ({ p, testler: [...new Set(pAdim(p).flatMap((a) => a.temelde_kirmizi ?? []))] }))
    .filter((x) => x.testler.length > 0);

  // Kural × hata dağılımı (analist: oran mutation score gibi okunmasın).
  const kurallar = new Map<string, string[]>();
  for (const kod of kosu.hatalar) {
    const e = kuralEtiketi(katalog.get(kod));
    kurallar.set(e, [...(kurallar.get(e) ?? []), kod]);
  }

  return (
    <div className="hk-sonuc" data-testid="hk-sonuc" data-kosu={kosu.id}>
      <div className="hk-sonuc-ust">
        <h3 ref={baslikRef} tabIndex={-1}>
          Sonuç tablosu
        </h3>
        <span className="kucuk hk-sonuc-kunye">
          <Cip ton={d.ton}>{d.etiket}</Cip> {tarih(kosu.bitis ?? kosu.baslama ?? kosu.olusturma)}
          {kosu.baslatan ? (
            <>
              {" "}
              · başlatan <KisiAdi ad={kosu.baslatan} />
            </>
          ) : null}
          {kosu.commit ? (
            <>
              {" "}
              · commit <span className="mono">{kosu.commit.slice(0, 7)}</span>
            </>
          ) : null}
        </span>
      </div>
      <p className="kucuk hk-kapsam" data-testid="hk-kapsam">
        Kapsam: {kapsam.katalog > 0 ? `${kapsam.kosulan_hata}/${kapsam.katalog} katalog hatası` : `${kapsam.kosulan_hata} hata`} ·{" "}
        {kapsam.platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")}
        {(kapsam.tam_katalog === false || (kapsam.tam_katalog === undefined && kapsam.katalog > 0 && kapsam.kosulan_hata < kapsam.katalog)) &&
          " · kısmi seçim: Kontrol Kulesi oranına girmez"}
      </p>
      {(kapsam.gecerli_adim !== undefined || testSayilari.length > 0) && (
        <p className="kucuk hk-kapsam" data-testid="hk-suite-sayilari">
          {[kapsam.gecerli_adim !== undefined ? `${kapsam.gecerli_adim} geçerli adım (yakalandı + kaçtı)` : "", testSayilari.length ? `Suite: ${testSayilari.join("; ")}` : ""]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {kosu.uyarilar.length > 0 && (
        <Uyari ton="uyari">
          <ul className="duz-liste kucuk">
            {kosu.uyarilar.map((u) => (
              <li key={u}>⚠ {u}</li>
            ))}
          </ul>
        </Uyari>
      )}
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Ekilmiş hata sonuç tablosu">
        <table className="tablo hk-tablo">
          <thead>
            <tr>
              <th scope="col">Hata</th>
              {kosu.platformlar.map((p) => (
                <th scope="col" key={p}>
                  {PLATFORM_ETIKETI[p]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="hk-cerceve-satiri">
              <th scope="row">{ASAMA_ADI.temel}</th>
              {kosu.platformlar.map((p) => (
                <td key={p} data-testid={`hk-temel-${p}`}>
                  <Hucre a={adim(p, "temel", null)} ad={ASAMA_ADI.temel} platform={p} />
                </td>
              ))}
            </tr>
            {kosu.hatalar.map((kod) => {
              const oge = katalog.get(kod);
              const ad = ekilmisHataAdi(kod, oge?.ad);
              return (
                <tr key={kod} data-testid={`hk-satir-${kod}`}>
                  <th scope="row">
                    <span className="hk-hata-adi">{ad}</span>
                    <span className="hk-hata-kunye kucuk">
                      {oge ? `${HATA_TURU[oge.tur]} · ` : ""}
                      <span className="mono">{kod}</span>
                    </span>
                  </th>
                  {kosu.platformlar.map((p) => (
                    <td key={p} data-testid={`hk-hucre-${p}-${kod}`}>
                      <Hucre a={adim(p, "hata", kod)} ad={ad} platform={p} />
                    </td>
                  ))}
                </tr>
              );
            })}
            <tr className="hk-cerceve-satiri">
              <th scope="row">{ASAMA_ADI.kapanis}</th>
              {kosu.platformlar.map((p) => (
                <td key={p} data-testid={`hk-kapanis-${p}`}>
                  <Hucre a={adim(p, "kapanis", null)} ad={ASAMA_ADI.kapanis} platform={p} />
                </td>
              ))}
            </tr>
          </tbody>
          <tfoot>
            {ayrik && (
              <>
                <tr className="hk-oran-ai">
                  <th scope="row">AI testleri (ana oran)</th>
                  {kosu.platformlar.map((p) => (
                    <td key={p} data-testid={`hk-oran-ai-${p}`}>
                      <OranHucresi o={aiVar ? kaynakIcin(pAdim(p), "ai") : null} olculmediMetni={aiVar ? "ölçülmedi" : "ölçülmedi — üretilmiş test yok"} />
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">El yazısı testler</th>
                  {kosu.platformlar.map((p) => (
                    <td key={p} data-testid={`hk-oran-el-${p}`}>
                      <OranHucresi o={kaynakIcin(pAdim(p), "el")} />
                    </td>
                  ))}
                </tr>
              </>
            )}
            <tr>
              <th scope="row">{ayrik ? "Tüm testler" : "Yakalama oranı"}</th>
              {kosu.platformlar.map((p) => {
                const hesap = yakalamaOrani(pAdim(p));
                // R4: core'un `tum_testler`'ı varsa o (aynı formül; adımlar okunamadıysa da doğru), yoksa adımlardan.
                const t = kosu.ozet?.platformlar.find((x) => x.platform === p)?.tum_testler;
                const o = t && !suruyor ? { ...hesap, ...t } : hesap;
                const m = oranMetni(o);
                return (
                  <td key={p} data-testid={`hk-oran-${p}`}>
                    {m ? <strong>{m}</strong> : <Olculmedi metin={o.bekleyen > 0 ? "sürüyor" : "ölçülmedi"} />}
                    {o.gecersiz > 0 && <div className="kucuk hk-neden">⚠ {o.gecersiz} geçersiz (orana girmez)</div>}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="kucuk hk-not" data-testid="hk-oran-notu">
        Oran = yakalanan / (yakalanan + kaçan). <strong>⚠ Geçersiz</strong> adımlar (ortam ya da altyapı hatası, yeşil olmayan temel koşu)
        tabloda gösterilir ama orana girmez.{" "}
        {ayrik && (
          <>
            Ana oran yalnız onaylı case'lerden üretilen (AI) testlerle sayılır; el yazısı suite ayrı satırdır. Bir test, hatasız temel koşuda
            yeşilse ve hatalı koşuda assertion ile kırmızıya dönerse hatayı yakalamış sayılır.{" "}
            <span data-testid="hk-oran-ayrik">
              AI testleri: {aiGenel && oranMetni(aiGenel) ? <strong>{oranMetni(aiGenel)}</strong> : "ölçülmedi (üretilmiş test yok)"} · El yazısı:{" "}
              {oranMetni(elGenel) ? <strong>{oranMetni(elGenel)}</strong> : "ölçülmedi"}
            </span>
            .{" "}
          </>
        )}
        {oranMetni(genel) ? (
          <>
            Tüm platformlar{ayrik ? ", tüm testler" : ""}: <strong data-testid="hk-oran-genel">{oranMetni(genel)}</strong>
            {genel.gecersiz > 0 ? ` · ${genel.gecersiz} geçersiz` : ""}.
          </>
        ) : (
          <>Tüm platformlar: {suruyor ? "sürüyor" : "ölçülmedi (sayılan adım yok)"}.</>
        )}
      </p>
      {temeldeBilgi && (
        <p className="kucuk hk-suite" data-testid="hk-suite">
          {temeldeKirmizi.length === 0 ? (
            "Suite: temel koşuda kırmızı test yok; bütün testler sayıldı."
          ) : (
            <>
              Suite: temel koşuda zaten kırmızı olan testler sayılmadı (açık defect adayı olabilir) —{" "}
              {temeldeKirmizi.map((x, i) => (
                <span key={x.p}>
                  {i > 0 && "; "}
                  {PLATFORM_ETIKETI[x.p]}: {x.testler.length} test ({x.testler.join(", ")})
                </span>
              ))}
              .
            </>
          )}
        </p>
      )}

      {kurallar.size > 0 && (
        <div className="hk-kural-dagilim" data-testid="hk-kural-dagilim">
          <h3>Kural başına dağılım</h3>
          <p className="kucuk">
            {kosu.hatalar.length} ekilmiş hata üzerinde (mutation score değildir: yalnız katalogdaki bu hatalar için). Hücre: yakalanan / sayılan,
            tüm testler.
          </p>
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Kural başına ekilmiş hata dağılımı">
            <table className="tablo tablo-sik">
              <thead>
                <tr>
                  <th scope="col">Kural</th>
                  <th scope="col" className="sayi">
                    Hata
                  </th>
                  {kosu.platformlar.map((p) => (
                    <th scope="col" key={p}>
                      {PLATFORM_ETIKETI[p]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...kurallar].map(([kural, kodlar]) => (
                  <tr key={kural}>
                    <th scope="row">{kural}</th>
                    <td className="sayi">{kodlar.length}</td>
                    {kosu.platformlar.map((p) => {
                      const o = yakalamaOrani(kosu.adimlar.filter((a) => a.platform === p && a.hata_kodu && kodlar.includes(a.hata_kodu)));
                      const sayilan = o.yakalanan + o.kacan;
                      return (
                        <td key={p}>
                          {sayilan > 0 ? `${o.yakalanan} / ${sayilan}` : <Olculmedi metin={o.bekleyen > 0 ? "sürüyor" : "ölçülmedi"} />}
                          {o.kacan > 0 && <span className="hata-metin"> · ✗ {o.kacan} kaçtı</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="hk-kacanlar" data-testid="hk-kacanlar">
        <h3>Kaçan hatalar</h3>
        {kacanlar.length > 0 ? (
          <>
            <p className="kucuk">
              Bu hatalarla uygulama bozukken bütün onaylı testler yeşil kaldı. İlgili kural için case eksik ya da beklenen değer hatayı ayırt
              etmiyor; yapılacak iş burada.
            </p>
            <ul className="hk-kacan-liste">
              {kacanlar.map(({ kod, platformlar }) => (
                <KacanHata key={kod} kod={kod} oge={katalog.get(kod)} platformlar={platformlar} />
              ))}
            </ul>
          </>
        ) : (
          <p className="kucuk" data-testid="hk-kacan-yok">
            {suruyor
              ? "Koşu sürüyor; kaçan hata olursa burada listelenir."
              : genel.yakalanan > 0
                ? "Kaçan hata yok: sayılan her hatayı en az bir test yakaladı."
                : "Sayılan adım yok; kaçan hata ölçülmedi."}
          </p>
        )}
      </div>
    </div>
  );
}

function Gecmis({ kosular, gosterilenId, ac }: { kosular: HataKosusu[]; gosterilenId: string | null; ac: (id: string) => void }) {
  return (
    <div className="hk-gecmis" data-testid="hk-gecmis">
      <h3>Son koşular</h3>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Son ekilmiş hata koşuları tablosu">
        <table className="tablo tablo-sik">
          <thead>
            <tr>
              <th scope="col">Tarih</th>
              <th scope="col">Başlatan</th>
              <th scope="col">Platformlar</th>
              <th scope="col">Oran</th>
              <th scope="col">Durum</th>
              <th scope="col">
                <span className="gorunmez">İşlem</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {kosular.map((k) => {
              const d = HATA_KOSUSU_DURUMU[k.durum];
              const zaman = tarih(k.bitis ?? k.baslama ?? k.olusturma);
              // §13.2: `ozet.oran` yalnız AI testleri; el yazısı suite ayrı yazılır (eski özet: tek oran).
              const el = k.ozet?.el_yazisi;
              const m = k.ozet ? oranMetni(k.ozet) : null;
              const elMetni = el ? oranMetni(el) : null;
              return (
                <tr key={k.id} data-testid={`hk-gecmis-${k.id}`} data-gosterilen={k.id === gosterilenId || undefined}>
                  <td className="tek-satir">{zaman}</td>
                  <td>{k.baslatan ? <KisiAdi ad={k.baslatan} /> : "—"}</td>
                  <td>{k.platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")}</td>
                  <td>
                    {el ? (
                      <>
                        AI {m ?? <Olculmedi metin="ölçülmedi" />} · el yazısı {elMetni ?? <Olculmedi metin="ölçülmedi" />}
                      </>
                    ) : (
                      (m ?? <Olculmedi metin={hataKosusuSuruyorMu(k) ? "sürüyor" : "ölçülmedi"} />)
                    )}
                    {k.ozet && k.ozet.gecersiz > 0 ? <span className="kucuk"> · {k.ozet.gecersiz} geçersiz</span> : null}
                  </td>
                  <td>
                    <Cip ton={d.ton}>{d.etiket}</Cip>
                  </td>
                  <td>
                    {k.id === gosterilenId ? (
                      <span className="kucuk">gösteriliyor</span>
                    ) : (
                      <button type="button" className="dugme dugme-ikincil dugme-kucuk" aria-label={`Aç: ${zaman} koşusu`} onClick={() => ac(k.id)}>
                        Aç
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Asistan panelinin "Sohbet" sekmesi (AI-ASISTAN-PLANI §11): bağlam çipleri, soru gönderme,
// bekleme (adım + süre, 25 sn'de "Uzun sürüyor", "Beklemeyi bırak"), SSE kopukken 3 sn yoklama,
// sayfa yenilenince bekleyen mesaja yeniden bağlanma, cevap kartları, otomatik yükseltme kartı,
// sohbet geçmişi ve silme onayı.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  adimMetni,
  asistanApi,
  baglamiSigdir,
  BEKLEYEN_VAR_METNI,
  bekliyor,
  gonderimHataMetni,
  mesajHataMetni,
  SORU_AZAMI,
  type AsistanDurumu,
  type AsistanMesaji,
  type Sohbet,
} from "../../api/asistan";
import { useBaglantiDurumu, useOlay } from "../../api/events";
import { ApiError, hataMesaji } from "../../api/http";
import { useOturum } from "../../auth";
import type { EkranBaglami } from "../../lib/ekranBaglami";
import { tarih } from "../../lib/format";
import { oturumDegisinceTemizle } from "../../lib/oturumTemizligi";
import { hataKaydi, SON_HATA_GECERLILIK_MS, sonHata, sonHataAbone, sonHataBaglami, sonHataSurumu, type SonHataKaydi } from "../../lib/sonHata";
import { BosDurum, Yukleniyor } from "../ui";
import type { SeciliEleman } from "./buNe";
import { CevapKarti } from "./CevapKarti";
import type { AcmaIstegi } from "./kontrol";
import { ekOneriDurdur, ekOneriKontrol, useBekleyenEkOneri } from "./OneriEkOneriler";
import { soruOnerileri } from "./sorular";

/** Zamanlamalar (testler kısaltabilir). */
export const sohbetAyar = { yoklamaMs: 3000, uzunSurerMs: 25_000, saatMs: 1000 };

const SOHBET_ANAHTARI = "tp-asistan-sohbet";

function kayitliSohbet(): string | null {
  try {
    return sessionStorage.getItem(SOHBET_ANAHTARI);
  } catch {
    return null;
  }
}

function sohbetiHatirla(id: string | null): void {
  try {
    if (id) sessionStorage.setItem(SOHBET_ANAHTARI, id);
    else sessionStorage.removeItem(SOHBET_ANAHTARI);
  } catch {
    /* yoksay */
  }
}

// Kayıtlı sohbet kullanıcıya aittir: çıkışta / kullanıcı değişince unutulur.
oturumDegisinceTemizle(() => sohbetiHatirla(null));

// Bekleme süresi istemci saatiyle ölçülür: başlangıç mesajın bu sekmede ilk görüldüğü an.
// Sunucunun `olusturma` zamanı istemci saatine karşı kullanılmaz (saat kayması sayacı 0'da
// tutar ya da "Uzun sürüyor"u hemen gösterirdi). Sayfa yenilenince sayaç yeniden başlar.
function gecenSure(baslangic: number, simdi: number): string {
  const sn = Math.max(0, Math.floor((simdi - baslangic) / 1000));
  return sn < 60 ? `${sn} sn` : `${Math.floor(sn / 60)} dk ${String(sn % 60).padStart(2, "0")} sn`;
}

function uzunSurdu(baslangic: number, simdi: number): boolean {
  return Math.max(0, simdi - baslangic) >= sohbetAyar.uzunSurerMs;
}

/** Gönderilecek sorunun seçenekleri (öneri kuralı, yeni sohbet, hedef sohbet). */
interface GonderSecenegi {
  yeniSohbet?: boolean;
  oneriKuralId?: string | null;
  sohbetId?: string | null;
}

/** Bekleyen soru varken dışarıdan gelen ("Neden? Sor", "Bunu sor") ve girdiye bırakılan soru. */
interface BekletilenSoru {
  metin: string;
  secenek: GonderSecenegi;
}

/** Gönderim, asistanın kapandığını söyledi (ör. 503 `worker_yok`): durum yeniden okunmalı. */
function asistanKapandi(e: unknown): boolean {
  return e instanceof ApiError && (e.kod === "asistan_kapali" || e.status === 503);
}

export interface SohbetSekmesiOzellikleri {
  ekran: EkranBaglami;
  asistan: AsistanDurumu;
  /** status'u yeniden oku (kalan soru hakkı). */
  durumYenile: () => void;
  /** "? Bu ne?" kipini başlatır (panel bindirmeyi açar). */
  buNeBaslat: () => void;
  buNeAcik: boolean;
  secili: SeciliEleman | null;
  seciliTemizle: () => void;
  /** Dışarıdan gelen açma isteği ("Asistana sor", "Neden? Sor"). */
  istek: AcmaIstegi | null;
  istegiTuket: (sira: number) => void;
  onGit?: () => void;
}

export function SohbetSekmesi({
  ekran,
  asistan,
  durumYenile,
  buNeBaslat,
  buNeAcik,
  secili,
  seciliTemizle,
  istek,
  istegiTuket,
  onGit,
}: SohbetSekmesiOzellikleri) {
  const { kullanici } = useOturum();
  const baglanti = useBaglantiDurumu();
  const [sohbetId, setSohbetId] = useState<string | null>(kayitliSohbet);
  const [mesajlar, setMesajlar] = useState<AsistanMesaji[]>([]);
  const [yukleniyor, setYukleniyor] = useState(false);
  const [yuklemeHatasi, setYuklemeHatasi] = useState<string | null>(null);
  const [girdi, setGirdi] = useState("");
  const [gonderiyor, setGonderiyor] = useState(false);
  const [gonderimHatasi, setGonderimHatasi] = useState<string | null>(null);
  const [adimlar, setAdimlar] = useState<Record<string, string>>({});
  const [notlar, setNotlar] = useState<Record<string, string>>({});
  const [derinCalisan, setDerinCalisan] = useState<string | null>(null);
  const [simdi, setSimdi] = useState(() => Date.now());
  const [gecmisAcik, setGecmisAcik] = useState(false);
  const [sohbetler, setSohbetler] = useState<Sohbet[] | null>(null);
  const [gecmisHatasi, setGecmisHatasi] = useState<string | null>(null);
  const [silinecek, setSilinecek] = useState<Sohbet | null>(null);
  const [ekranDahil, setEkranDahil] = useState(true);
  const [hataDahil, setHataDahil] = useState(true);
  const [secilenHataId, setSecilenHataId] = useState<string | null>(null);
  /** "Asistana sor" ile seçilen kaydın süresi dolmuşsa gösterilen not. */
  const [hataNotu, setHataNotu] = useState<string | null>(null);
  /** Bekleme sürerken girdiye bırakılan dış soru: girdiden gönderilince seçenekleriyle gider. */
  const [bekletilen, setBekletilen] = useState<BekletilenSoru | null>(null);
  /** Ekran okuyucuya yalnız sonuç duyurulur (liste kabı canlı bölge değildir). */
  const [duyuru, setDuyuru] = useState("");
  const ilkGorulme = useRef(new Map<string, number>());
  const girdiRef = useRef<HTMLTextAreaElement>(null);
  const sohbetRef = useRef(sohbetId);
  sohbetRef.current = sohbetId;
  /** İşlenen son dış istek: StrictMode'da effect iki kez koşsa da soru bir kez gönderilir. */
  const islenenSira = useRef<number | null>(null);

  // Rota değişince ekran çipi yeniden eklenir (kaldırma yalnız o ekran için).
  useEffect(() => setEkranDahil(true), [ekran.rota_kalibi, ekran.varlik?.id]);

  // Son hata: "Asistana sor" ile seçilen kayıt, yoksa 5 dk içindeki son kayıt. Seçilen kaydın
  // süresi dolduysa başka (ilgisiz) bir hataya düşülmez: o hata sorusu bağlamsız kalır, not gösterilir.
  useSyncExternalStore(sonHataAbone, sonHataSurumu);
  const gecerliHata = useCallback(
    (): SonHataKaydi | null => (secilenHataId ? hataKaydi(secilenHataId) : sonHata()),
    [secilenHataId],
  );
  const hata = gecerliHata();
  useEffect(() => setHataDahil(true), [hata?.kayitId]);
  // 5 dk dolunca çip kendiliğinden kalksın (panel açık beklerken de): kalan süre kadar sonra yeniden çiz.
  const [, setHataSaati] = useState(0);
  useEffect(() => {
    if (!hata) return;
    const kalan = hata.zaman + SON_HATA_GECERLILIK_MS - Date.now() + 50;
    const z = setTimeout(() => setHataSaati((n) => n + 1), Math.max(0, kalan));
    return () => clearTimeout(z);
  }, [hata?.kayitId, hata?.zaman]);

  const yukle = useCallback(async (id: string, sessiz = false) => {
    if (!sessiz) setYukleniyor(true);
    try {
      const liste = await asistanApi.mesajlar(id);
      if (sohbetRef.current !== id) return;
      setMesajlar(liste);
      setYuklemeHatasi(null);
    } catch (e) {
      if (sohbetRef.current !== id) return;
      if (e instanceof ApiError && e.status === 404) {
        // Silinmiş/süresi dolmuş sohbet: yeni sohbetle devam.
        setSohbetId(null);
        sohbetiHatirla(null);
        setMesajlar([]);
      } else {
        setYuklemeHatasi(hataMesaji(e));
      }
    } finally {
      if (!sessiz) setYukleniyor(false);
    }
  }, []);

  // Panel açılınca kayıtlı sohbet yüklenir; bekleyen mesaj varsa bekleme yeniden kurulur.
  useEffect(() => {
    if (sohbetId) void yukle(sohbetId);
    else setMesajlar([]);
  }, [sohbetId, yukle]);

  const bekleyenler = useMemo(() => mesajlar.filter((m) => m.rol === "assistant" && bekliyor(m)), [mesajlar]);
  // Öneriler sekmesindeki "Başka ne yapabilirim?" de kullanıcının bekleyen sorusudur (sunucu 409 bekleyen_var).
  const ekBekleyen = useBekleyenEkOneri();
  const kullaniciBekliyor = bekleyenler.some((m) => m.tetik === "kullanici") || !!ekBekleyen;
  const bekleyenAnahtar = bekleyenler.map((m) => m.id).join("|");

  // Olaylar: core yalnız bu kullanıcının asistan olaylarını teslim eder.
  useOlay(
    (o) => {
      const id = typeof o.data.mesaj_id === "string" ? o.data.mesaj_id : o.id;
      if (!id) return;
      if (o.type === "assistant.answered" && ekBekleyen && id === ekBekleyen) {
        void ekOneriKontrol(ekBekleyen);
        return;
      }
      if (o.type === "assistant.step" && typeof o.data.adim_kodu === "string") {
        setAdimlar((a) => ({ ...a, [id]: o.data.adim_kodu as string }));
      } else if (o.type === "assistant.answered" && sohbetRef.current) {
        void yukle(sohbetRef.current, true);
        durumYenile();
      }
    },
    ["assistant.step", "assistant.answered"],
  );

  // SSE kopukken (yeniden bağlanıyor / kapalı) 3 sn'de bir yoklama.
  const sseVar = baglanti === "bagli" || baglanti === "mock";
  useEffect(() => {
    if (!bekleyenAnahtar || sseVar) return;
    const ids = bekleyenAnahtar.split("|");
    const z = setInterval(() => {
      void (async () => {
        let bitti = false;
        for (const id of ids) {
          try {
            const m = await asistanApi.mesaj(id);
            if (!bekliyor(m)) bitti = true;
            else if (m.adim_kodu) setAdimlar((a) => ({ ...a, [id]: m.adim_kodu! }));
          } catch {
            /* bir sonraki turda yeniden denenir */
          }
        }
        if (bitti && sohbetRef.current) {
          await yukle(sohbetRef.current, true);
          durumYenile();
        }
      })();
    }, sohbetAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [bekleyenAnahtar, sseVar, yukle, durumYenile]);

  // Ek öneri beklerken SSE kopuksa onu da yokla (Öneriler sekmesi kapalıyken bekleme takılı kalmasın).
  useEffect(() => {
    if (!ekBekleyen || sseVar) return;
    const z = setInterval(() => void ekOneriKontrol(ekBekleyen), sohbetAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [ekBekleyen, sseVar]);

  // Bekleyen mesaj bitince yalnız sonuç duyurulur (geçmişten açılan sohbetin tamamı okunmaz).
  const oncekiBekleyenler = useRef<string[]>([]);
  useEffect(() => {
    const onceki = oncekiBekleyenler.current;
    oncekiBekleyenler.current = bekleyenAnahtar ? bekleyenAnahtar.split("|") : [];
    const biten = mesajlar.filter((m) => onceki.includes(m.id) && !bekliyor(m));
    if (biten.length === 0) return;
    const son = biten[biten.length - 1];
    setDuyuru(son.durum === "done" ? "Asistanın cevabı geldi." : son.durum === "iptal" ? "Soru iptal edildi." : "Soru tamamlanamadı.");
  }, [bekleyenAnahtar, mesajlar]);

  /** Bekleme başlangıcı: mesajın bu sekmede ilk görüldüğü an (istemci saati). */
  const baslangic = (m: AsistanMesaji): number => {
    let t = ilkGorulme.current.get(m.id);
    if (t === undefined) {
      t = Date.now();
      ilkGorulme.current.set(m.id, t);
    }
    return t;
  };

  // Geçen süre sayacı.
  useEffect(() => {
    if (!bekleyenAnahtar) return;
    setSimdi(Date.now());
    const z = setInterval(() => setSimdi(Date.now()), sohbetAyar.saatMs);
    return () => clearInterval(z);
  }, [bekleyenAnahtar]);

  /** `ekranZorunlu`: öneri sorusu ("Neden? Sor") kuralın ekranına bağlıdır; çip kaldırılmış olsa da ekran gider. */
  const baglamUret = useCallback((ekranZorunlu = false): Record<string, unknown> => {
    const b: Record<string, unknown> = {};
    if (ekranDahil || ekranZorunlu) {
      b.rota_kalibi = ekran.rota_kalibi;
      b.ekran = ekran.ekran;
      if (ekran.varlik) b.varlik = { tur: ekran.varlik.tur, id: ekran.varlik.id, anahtar: ekran.varlik.anahtar ?? null };
    }
    // Gönderim anında yeniden doğrulanır: süresi dolmuş kayıt (yas_s > 300) bağlama girmez.
    const guncelHata = gecerliHata();
    if (guncelHata && hataDahil) b.son_hata = sonHataBaglami(guncelHata);
    if (secili) b.secili_eleman = secili;
    return baglamiSigdir(b);
  }, [ekranDahil, ekran, gecerliHata, hataDahil, secili]);

  const gonder = useCallback(
    async (soru: string, secenek: GonderSecenegi = {}) => {
      const metin = soru.trim();
      if (!metin) return;
      // Yanıt bekleyen soru varken (bu sekmede) ya da önceki gönderim sürerken yeni soru
      // gönderilmez: sunucu 409 bekleyen_var döndürür. Yeni sohbete de geçilmez; soru girdide
      // kalır, cevap gelince gönderilir. Öneri kuralı / hedef sohbet de saklanır (§17.6): girdiden
      // gönderilen aynı soru onlarla gider, girdi değişirse düşer.
      if (kullaniciBekliyor || gonderiyor) {
        setGirdi(metin);
        setBekletilen(secenek.oneriKuralId || secenek.yeniSohbet || secenek.sohbetId ? { metin, secenek } : null);
        setGonderimHatasi(
          kullaniciBekliyor ? BEKLEYEN_VAR_METNI : "Önceki soru gönderiliyor; bu soru girdide bekliyor, sonra yeniden gönderin.",
        );
        return;
      }
      setBekletilen(null);
      setGonderiyor(true);
      setGonderimHatasi(null);
      let yeniId: string | null = null;
      try {
        let id = secenek.sohbetId ?? (secenek.yeniSohbet ? null : sohbetRef.current);
        // Öneri kuralı yalnız sohbeti açan ilk soruda gider; sunucu sohbete yazar
        // (`asistan_sohbet.oneri_kural_id`) ve takip sorularında bağlamı oradan taşır (§17.6).
        // Takipte yeniden göndermek, ekran değişince ya da Geçmiş'ten açılınca 409 `oneri_gecersiz` verirdi.
        const kural = id ? null : (secenek.oneriKuralId ?? null);
        if (!id) {
          yeniId = (await asistanApi.sohbetOlustur(null)).id;
          id = yeniId;
        }
        await asistanApi.soruGonder(id, {
          soru: metin,
          baglam: baglamUret(!!kural),
          kip: "soru",
          ...(kural ? { oneri_kural_id: kural } : {}),
        });
        // Yeni sohbete ancak soru kabul edildikten sonra geçilir (409'da mevcut sohbet kalır).
        if (yeniId) {
          sohbetRef.current = yeniId;
          sohbetiHatirla(yeniId);
          setSohbetId(yeniId);
          setMesajlar([]);
        } else if (id !== sohbetRef.current) {
          // Başka sohbette soruldu ("Bunu sor": ek öneri sohbeti): o sohbete geçilir.
          sohbetRef.current = id;
          sohbetiHatirla(id);
          setSohbetId(id);
          setMesajlar([]);
        }
        setGirdi("");
        seciliTemizle();
        // Seçilen hata kaydı bu soruyla gitti; sonraki sorular güncel son hatayı kullanır.
        setSecilenHataId(null);
        setHataNotu(null);
        await yukle(id, true);
        durumYenile();
      } catch (e) {
        if (yeniId && sohbetRef.current !== yeniId) {
          // Soru kabul edilmedi: az önce açılan boş sohbet sahipsiz kalmasın.
          void asistanApi.sohbetSil(yeniId).catch(() => undefined);
          setGirdi((g) => g || metin);
        }
        setGonderimHatasi(gonderimHataMetni(e));
        // Asistan bu arada kapandıysa (worker gitti) panel nedenini gösteren pasif uyarıya geçsin.
        if (asistanKapandi(e)) durumYenile();
      } finally {
        setGonderiyor(false);
      }
    },
    [gonderiyor, kullaniciBekliyor, baglamUret, seciliTemizle, yukle, durumYenile],
  );

  // Dış istek: "Asistana sor" (hata kaydı) ya da "Neden? Sor" (öneri kuralı + soru).
  useEffect(() => {
    if (!istek || istek.sekme !== "sohbet") return;
    // StrictMode effect'i iki kez çalıştırır ve ikinci çağrı aynı `istek` prop'unu görür.
    if (islenenSira.current === istek.sira) return;
    islenenSira.current = istek.sira;
    istegiTuket(istek.sira);
    if (istek.kayitId) {
      setSecilenHataId(istek.kayitId);
      setHataDahil(true);
      if (hataKaydi(istek.kayitId)) {
        setHataNotu(null);
        if (!istek.soru) setGirdi((g) => g || "Bu hata ne demek, ne yapmalıyım?");
      } else {
        // Kayıt süresi doldu / silindi: başka bir hatanın bağlamı yerine gitmesin, girdi doldurulmaz.
        setHataNotu("Bu hatanın kaydı artık yok (5 dk geçti). Hata yeniden görünürse oradan tekrar sorun.");
      }
    }
    if (istek.soru) {
      void gonder(istek.soru, { yeniSohbet: !!istek.oneriKuralId, oneriKuralId: istek.oneriKuralId ?? null, sohbetId: istek.sohbetId ?? null });
    } else {
      girdiRef.current?.focus();
    }
    // gonder kasıtlı olarak bağımlılık değil: istek bir kez işlenir (sira ile tüketilir).
  }, [istek]);

  const sohbetiBirak = () => {
    sohbetRef.current = null;
    setSohbetId(null);
    sohbetiHatirla(null);
    setMesajlar([]);
    setGonderimHatasi(null);
    setSecilenHataId(null);
    setHataNotu(null);
  };

  const yeniSohbet = () => {
    sohbetiBirak();
    setGecmisAcik(false);
    girdiRef.current?.focus();
  };

  const gecmisiAc = async () => {
    setGecmisAcik(true);
    setSohbetler(null);
    setGecmisHatasi(null);
    try {
      setSohbetler(await asistanApi.sohbetler());
    } catch (e) {
      // Liste okunamadı: "Henüz sohbet yok" denmez; hata ve "Yeniden dene" gösterilir.
      setGecmisHatasi(hataMesaji(e));
    }
  };

  const sil = async (s: Sohbet) => {
    setGecmisHatasi(null);
    try {
      await asistanApi.sohbetSil(s.id);
      setSohbetler((l) => (l ?? []).filter((x) => x.id !== s.id));
      if (s.id === sohbetId) sohbetiBirak();
    } catch (e) {
      setGecmisHatasi(`Sohbet silinemedi: ${hataMesaji(e)}`);
    } finally {
      setSilinecek(null);
    }
  };

  const iptalEt = async (m: AsistanMesaji) => {
    try {
      // Ücret notu sunucunun gördüğü duruma göre: iptal yanıtı (yoksa mesajın kendisi) başladı mı?
      const yanit = await asistanApi.iptal(m.id);
      const son = yanit && typeof yanit === "object" && "durum" in yanit ? yanit : await asistanApi.mesaj(m.id).catch(() => null);
      const basladi =
        m.durum === "running" ||
        m.basladi === true ||
        (!!adimlar[m.id] && adimlar[m.id] !== "sirada") ||
        son?.basladi === true ||
        Number(son?.maliyet_usd ?? 0) > 0;
      setNotlar((n) => ({
        ...n,
        [m.id]:
          m.tetik === "otomatik"
            ? "Ayrıntılı inceleme durduruldu; bu soru için yeniden başlatılamaz."
            : basladi
              ? "Bekleme bırakıldı. İşlenen kısım ücretlendi."
              : "Bekleme bırakıldı. İşlenmeye başlamadığı için ücret yok.",
      }));
    } catch (e) {
      setGonderimHatasi(hataMesaji(e));
    }
    if (sohbetRef.current) await yukle(sohbetRef.current, true);
  };

  const derinIncele = async (m: AsistanMesaji) => {
    if (!sohbetRef.current) return;
    setDerinCalisan(m.id);
    setGonderimHatasi(null);
    try {
      await asistanApi.derinIncele(sohbetRef.current, m.id);
      await yukle(sohbetRef.current, true);
      durumYenile();
    } catch (e) {
      setGonderimHatasi(gonderimHataMetni(e));
    } finally {
      setDerinCalisan(null);
    }
  };

  const geriBildir = async (m: AsistanMesaji, deger: -1 | 1) => {
    try {
      await asistanApi.geriBildirim(m.id, deger);
      setMesajlar((l) => l.map((x) => (x.id === m.id ? { ...x, geri_bildirim: deger } : x)));
    } catch (e) {
      setGonderimHatasi(hataMesaji(e));
    }
  };

  const modelAcik = asistan.model_hazir ?? asistan.mod === "live";
  const sonCevapId = [...mesajlar].reverse().find((m) => m.rol === "assistant" && m.durum === "done")?.id;
  const oneriler = soruOnerileri(kullanici?.rol, ekran, { modelAcik, sonHataVar: !!hata });

  const bekleme = (m: AsistanMesaji, etiket?: string) => (
    <div className="asistan-bekleme" role="status" data-testid="asistan-bekleme">
      <span className="donen donen-kucuk" aria-hidden="true" />
      <span>
        {etiket ?? adimMetni(adimlar[m.id] ?? m.adim_kodu)}
        {/* Sayaç her saniye değişir: canlı bölgede duyurulmaz (yalnız adım ve "Uzun sürüyor"). */}
        <span aria-hidden="true"> · {gecenSure(baslangic(m), simdi)}</span>
      </span>
      {uzunSurdu(baslangic(m), simdi) && <span className="asistan-uzun">Uzun sürüyor</span>}
      <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void iptalEt(m)}>
        {m.tetik === "otomatik" ? "Durdur" : "Beklemeyi bırak"}
      </button>
    </div>
  );

  const kartOzellikleri = (m: AsistanMesaji, cocukVar: boolean) => ({
    derinIncelenebilir:
      modelAcik && m.kip === "soru" && m.amac !== "assistant_deep" && m.kaynak !== "kapali" && !cocukVar && !kullaniciBekliyor,
    derinIncele: () => void derinIncele(m),
    derinCalisiyor: derinCalisan === m.id,
    geriBildir: (d: -1 | 1) => void geriBildir(m, d),
    kalanSoru: m.id === sonCevapId ? (asistan.kalan_soru ?? null) : null,
    onGit,
  });

  const cevapGrubu = (m: AsistanMesaji) => {
    const not = notlar[m.id];
    if (bekliyor(m)) return bekleme(m);
    if (m.durum === "error") {
      return (
        <div className="uyari-kutusu uyari-hata" role="alert">
          {mesajHataMetni(m.hata_kodu)}
        </div>
      );
    }
    if (m.durum === "iptal") return <p className="asistan-not">{not ?? "Soru iptal edildi."}</p>;
    const cocuk = mesajlar.find((x) => x.ust_mesaj_id === m.id);
    if (!cocuk) return <CevapKarti mesaj={m} {...kartOzellikleri(m, false)} />;
    const otomatik = cocuk.tetik === "otomatik";
    const onCevap = otomatik ? "Ön cevap (kaynakla doğrulanamadı)" : undefined;
    if (bekliyor(cocuk)) {
      return (
        <>
          <CevapKarti mesaj={m} baslik={onCevap} {...kartOzellikleri(m, true)} />
          {bekleme(cocuk, otomatik ? "Ayrıntılı inceleme sürüyor…" : undefined)}
        </>
      );
    }
    if (cocuk.durum === "done") {
      return (
        <>
          <details className="asistan-on-cevap">
            <summary>{onCevap ?? "İlk cevap"}</summary>
            <CevapKarti mesaj={m} {...kartOzellikleri(m, true)} />
          </details>
          <CevapKarti mesaj={cocuk} baslik="Ayrıntılı inceleme" {...kartOzellikleri(cocuk, false)} />
        </>
      );
    }
    const neden =
      cocuk.durum === "iptal"
        ? "Ayrıntılı inceleme durduruldu; bu soru için yeniden başlatılamaz."
        : `Ayrıntılı inceleme tamamlanamadı (${mesajHataMetni(cocuk.hata_kodu)}); bu soru için yeniden başlatılamaz.`;
    return (
      <>
        <CevapKarti mesaj={m} baslik={onCevap} {...kartOzellikleri(m, true)} />
        <p className="asistan-not">{neden}</p>
      </>
    );
  };

  if (gecmisAcik) {
    return (
      <div className="asistan-gecmis">
        <div className="asistan-gecmis-ust">
          <strong>Sohbet geçmişi</strong>
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setGecmisAcik(false)}>
            Geri
          </button>
        </div>
        {gecmisHatasi && (
          <div className="uyari-kutusu uyari-hata" role="alert">
            {gecmisHatasi}{" "}
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void gecmisiAc()}>
              Yeniden dene
            </button>
          </div>
        )}
        {sohbetler === null ? (
          !gecmisHatasi && <Yukleniyor />
        ) : sohbetler.length === 0 ? (
          <BosDurum baslik="Henüz sohbet yok." />
        ) : (
          <ul className="asistan-sohbet-listesi">
            {sohbetler.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="asistan-sohbet-sec"
                  onClick={() => {
                    sohbetRef.current = s.id;
                    sohbetiHatirla(s.id);
                    setSohbetId(s.id);
                    setGecmisAcik(false);
                  }}
                >
                  <span>{s.baslik || "Başlıksız sohbet"}</span>
                  <span className="soluk kucuk">{tarih(s.guncelleme)}</span>
                </button>
                {silinecek?.id === s.id ? (
                  <span className="asistan-sil-onay" role="group" aria-label="Silme onayı">
                    <span className="kucuk">Silinsin mi?</span>
                    <button type="button" className="dugme dugme-tehlike dugme-kucuk" onClick={() => void sil(s)}>
                      Sil
                    </button>
                    <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setSilinecek(null)}>
                      Vazgeç
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="dugme dugme-hayalet dugme-kucuk"
                    aria-label={`${s.baslik || "Başlıksız sohbet"} sohbetini sil`}
                    onClick={() => setSilinecek(s)}
                  >
                    Sil
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="soluk kucuk">
          Silinen sohbet listeden kalkar; sorular denetim kaydında (maskeli) kalır. Sohbetler 90 gün sonra temizlenir.
        </p>
      </div>
    );
  }

  /** Girdideki soru bekletilen dış soruysa onun seçenekleri (öneri kuralı, sohbet); elle değiştiyse yok. */
  const bekletilenSecenek = (): GonderSecenegi => (bekletilen && bekletilen.metin === girdi.trim() ? bekletilen.secenek : {});
  const sayac = girdi.length;
  const gonderilemez = !girdi.trim() || sayac > SORU_AZAMI || gonderiyor || kullaniciBekliyor;
  const kokler = mesajlar.filter((m) => !m.ust_mesaj_id);

  return (
    <div className="asistan-sohbet">
      <div className="asistan-sohbet-eylem">
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={yeniSohbet}>
          Yeni sohbet
        </button>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void gecmisiAc()}>
          Geçmiş
        </button>
      </div>
      {/* Liste kabı canlı bölge değildir: geçmişten açılan sohbet baştan okunmaz. Bekleme adımları
          kendi role="status" bölgelerinde, sonuç bu küçük bölgede duyurulur. */}
      <p className="gorunmez" role="status" data-testid="asistan-duyuru">
        {duyuru}
      </p>
      <div className="asistan-mesajlar">
        {yukleniyor && <Yukleniyor metin="Sohbet yükleniyor…" />}
        {yuklemeHatasi && (
          <div className="uyari-kutusu uyari-hata" role="alert">
            {yuklemeHatasi}
          </div>
        )}
        {!yukleniyor && kokler.length === 0 && (
          <div className="asistan-bos">
            <p className="soluk">
              Portal, kayıtlarınız ya da test edilen uygulama hakkında sorun. Asistan yalnızca okur; işlem yapmaz.
            </p>
            {oneriler.length > 0 && (
              <ul className="asistan-soru-onerileri" aria-label="Soru önerileri">
                {oneriler.map((s) => (
                  <li key={s.metin}>
                    <button type="button" className="cip cip-notr asistan-oneri-cipi" onClick={() => void gonder(s.metin)} disabled={kullaniciBekliyor}>
                      {s.metin}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {kokler.map((m) =>
          m.rol === "user" ? (
            <div key={m.id} className="asistan-soru">
              {m.icerik}
            </div>
          ) : (
            <div key={m.id} className="asistan-grup">
              {cevapGrubu(m)}
            </div>
          ),
        )}
      </div>
      <form
        className="asistan-girdi"
        onSubmit={(e) => {
          e.preventDefault();
          if (!gonderilemez) void gonder(girdi, bekletilenSecenek());
        }}
      >
        <div className="asistan-cipler" aria-label="Soruya eklenecek bağlam">
          {ekranDahil && ekran.rota_kalibi && (
            <span className="cip cip-bilgi asistan-baglam-cipi">
              Bu ekran: {ekran.ekran}
              {ekran.varlik?.anahtar ? ` · ${ekran.varlik.anahtar}` : ""}
              <button type="button" className="asistan-cip-kaldir" aria-label="Ekran bağlamını kaldır" onClick={() => setEkranDahil(false)}>
                ×
              </button>
            </span>
          )}
          {hata && hataDahil && (
            <span className="cip cip-uyari asistan-baglam-cipi" title={hata.detail}>
              Son hata: {(hata.gorunen_metin ?? hata.detail).slice(0, 60)}
              <button type="button" className="asistan-cip-kaldir" aria-label="Son hata bağlamını kaldır" onClick={() => setHataDahil(false)}>
                ×
              </button>
            </span>
          )}
          {secili && (
            <span className="cip cip-vurgu asistan-baglam-cipi">
              Seçili: {secili.ad || secili.ipucu || secili.test_id}
              <button type="button" className="asistan-cip-kaldir" aria-label="Seçili öğeyi kaldır" onClick={seciliTemizle}>
                ×
              </button>
            </span>
          )}
          {/* Model kapalıyken seçili öğe sorusu cevaplanamaz (yalnız "kapalı" metni döner): düğme gizli. */}
          {modelAcik && (
            <button type="button" className="cip cip-notr asistan-bune-dugmesi" aria-pressed={buNeAcik} onClick={buNeBaslat}>
              ? Bu ne?
            </button>
          )}
        </div>
        <label className="gorunmez" htmlFor="asistan-soru">
          Sorunuz
        </label>
        <textarea
          id="asistan-soru"
          ref={girdiRef}
          value={girdi}
          rows={3}
          placeholder="Sorunuzu yazın…"
          onChange={(e) => {
            setGirdi(e.target.value);
            // Bekletilen dış soru elle değiştirildiyse kuralı/sohbeti artık onun değildir.
            if (bekletilen && e.target.value.trim() !== bekletilen.metin) setBekletilen(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (!gonderilemez) void gonder(girdi, bekletilenSecenek());
            }
          }}
          aria-describedby="asistan-sayac"
        />
        <div className="asistan-girdi-alt">
          <span id="asistan-sayac" className={sayac > SORU_AZAMI ? "asistan-sayac asistan-sayac-asim" : "asistan-sayac soluk kucuk"}>
            {sayac} / {SORU_AZAMI}
          </span>
          <button type="submit" className="dugme dugme-birincil dugme-kucuk" disabled={gonderilemez} aria-busy={gonderiyor || undefined}>
            Asistana sor
          </button>
        </div>
        {ekBekleyen ? (
          <p className="soluk kucuk" role="status" data-testid="ek-oneri-bekliyor">
            Ek öneriler hazırlanıyor (Öneriler sekmesi); bitince yeni soru sorabilirsiniz.{" "}
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void ekOneriDurdur(ekBekleyen)}>
              Durdur
            </button>
          </p>
        ) : (
          kullaniciBekliyor && <p className="soluk kucuk">Cevap gelince yeni soru sorabilirsiniz.</p>
        )}
        {hataNotu && (
          <p className="soluk kucuk" role="status">
            {hataNotu}
          </p>
        )}
        {gonderimHatasi && (
          <div className="uyari-kutusu uyari-hata" role="alert">
            {gonderimHatasi}
          </div>
        )}
      </form>
    </div>
  );
}

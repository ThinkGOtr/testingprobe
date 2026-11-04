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
import { Ikon } from "../Ikon";
import { BosDurum, Yukleniyor } from "../ui";
import type { SeciliEleman } from "./buNe";
import { CevapKarti } from "./CevapKarti";
import { ekranAnahtariUret, ilkGorulmeler, istekGecerli, oneriSohbetiUnut, oneriSohbetiYaz, sohbetTaslagi, type AcmaIstegi, type SohbetTaslagi } from "./kontrol";
import { ekOneriDurdur, ekOneriKontrol, sohbetBekleyeniYaz, useBekleyenEkOneri } from "./OneriEkOneriler";
import { oneriAnahtari, oneriGetir, oneriSorgusu } from "./OneriVerisi";
import { soruOnerileri } from "./sorular";

/** Zamanlamalar (testler kısaltabilir). `duyuruAraMs`: aynı duyuru metni yeniden yazılmadan önce
 * canlı bölgenin boş kaldığı süre. */
export const sohbetAyar = { yoklamaMs: 3000, uzunSurerMs: 25_000, saatMs: 1000, duyuruAraMs: 100 };

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

// Bekleme süresi istemci saatiyle ölçülür: başlangıç mesajın bu sekmede ilk görüldüğü an
// (`ilkGorulmeler`, modül düzeyinde: Sohbet/Öneriler geçişinde ya da panel kapanıp açılınca
// korunur). Sunucunun `olusturma` zamanı istemci saatine karşı kullanılmaz (saat kayması sayacı
// 0'da tutar ya da "Uzun sürüyor"u hemen gösterirdi). Sayfa yenilenince sayaç yeniden başlar.
function gecenSure(baslangic: number, simdi: number): string {
  const sn = Math.max(0, Math.floor((simdi - baslangic) / 1000));
  return sn < 60 ? `${sn} sn` : `${Math.floor(sn / 60)} dk ${String(sn % 60).padStart(2, "0")} sn`;
}

function uzunSurdu(baslangic: number, simdi: number): boolean {
  return Math.max(0, simdi - baslangic) >= sohbetAyar.uzunSurerMs;
}

/** Bekleyen soru varken dışarıdan gelen ("Neden? Sor", "Bunu sor") ve girdiye bırakılan soru. */
type BekletilenSoru = NonNullable<SohbetTaslagi["bekletilen"]>;

/** Gönderilecek sorunun seçenekleri (öneri kuralı, yeni sohbet, hedef sohbet). */
type GonderSecenegi = BekletilenSoru["secenek"];

/** `useState` gibi; değer `sohbetTaslagi`nda da tutulur (sekme geçişi / "Bu ne?" sonrası yeniden
 * çizimde korunur). Tek panel örneği olduğundan bileşen state'i ile depo ayrışmaz. */
function useTaslak<K extends keyof SohbetTaslagi>(
  alan: K,
): [SohbetTaslagi[K], (d: SohbetTaslagi[K] | ((o: SohbetTaslagi[K]) => SohbetTaslagi[K])) => void] {
  const [deger, setDeger] = useState<SohbetTaslagi[K]>(() => sohbetTaslagi[alan]);
  const ayarla = useCallback(
    (d: SohbetTaslagi[K] | ((o: SohbetTaslagi[K]) => SohbetTaslagi[K])) => {
      const yeni = typeof d === "function" ? (d as (o: SohbetTaslagi[K]) => SohbetTaslagi[K])(sohbetTaslagi[alan]) : d;
      sohbetTaslagi[alan] = yeni;
      setDeger(yeni);
    },
    [alan],
  );
  return [deger, ayarla];
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
  const [girdi, setGirdi] = useTaslak("girdi");
  const [gonderiyor, setGonderiyor] = useState(false);
  const [gonderimHatasi, setGonderimHatasi] = useState<string | null>(null);
  const [adimlar, setAdimlar] = useTaslak("adimlar");
  const [notlar, setNotlar] = useTaslak("notlar");
  const [derinCalisan, setDerinCalisan] = useState<string | null>(null);
  const [simdi, setSimdi] = useState(() => Date.now());
  const [gecmisAcik, setGecmisAcik] = useState(false);
  const [sohbetler, setSohbetler] = useState<Sohbet[] | null>(null);
  const [gecmisHatasi, setGecmisHatasi] = useState<string | null>(null);
  const [silinecek, setSilinecek] = useState<Sohbet | null>(null);
  /** Dış istekten sonra girdiye odak (Geçmiş'ten dönülürken girdi bir sonraki çizimde gelir). */
  const [odakIste, setOdakIste] = useState(0);
  // Çip tercihleri kaldırıldıkları ekran / hata kaydıyla saklanır: rota ya da kayıt değişince
  // çip yeniden eklenir (kaldırma yalnız o ekran / o hata için).
  const [ekranKaldirilan, setEkranKaldirilan] = useTaslak("ekranKaldirilan");
  const [hataKaldirilan, setHataKaldirilan] = useTaslak("hataKaldirilan");
  const [secilenHataId, setSecilenHataId] = useTaslak("secilenHataId");
  /** "Asistana sor" ile seçilen kaydın süresi dolmuşsa gösterilen not. */
  const [hataNotu, setHataNotu] = useTaslak("hataNotu");
  /** Bekleme sürerken girdiye bırakılan dış soru: girdiden gönderilince seçenekleriyle gider. */
  const [bekletilen, setBekletilen] = useTaslak("bekletilen");
  /** Ekran okuyucuya yalnız sonuç duyurulur (liste kabı canlı bölge değildir). */
  const [duyuru, setDuyuru] = useState("");
  const duyuruZamanlayici = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (duyuruZamanlayici.current) clearTimeout(duyuruZamanlayici.current);
    },
    [],
  );
  /** Aynı metin ardışık duyurulsa da canlı bölgede DOM değişsin: önce boşaltılır, metin kısa bir
   * aradan sonra yazılır (aynı değerle `setDuyuru` yeniden çizmez, ikinci cevap duyurulmazdı). */
  const duyur = useCallback((metin: string) => {
    if (duyuruZamanlayici.current) clearTimeout(duyuruZamanlayici.current);
    setDuyuru("");
    duyuruZamanlayici.current = setTimeout(() => {
      duyuruZamanlayici.current = null;
      setDuyuru(metin);
    }, sohbetAyar.duyuruAraMs);
  }, []);
  const girdiRef = useRef<HTMLTextAreaElement>(null);
  const sohbetRef = useRef(sohbetId);
  sohbetRef.current = sohbetId;
  /** İşlenen son dış istek: StrictMode'da effect iki kez koşsa da soru bir kez gönderilir. */
  const islenenSira = useRef<number | null>(null);
  /** Gönderimden sonra yeni sohbete geçerken etki yüklemeyi atlar: `gonder` zaten sessiz yükler
   * (aynı liste iki kez çekilmez, "Sohbet yükleniyor…" yanıp sönmez). */
  const yuklemeyiAtla = useRef<string | null>(null);

  // Rota değişince ekran çipi yeniden eklenir (kaldırma yalnız o ekran için). Sekme çizili değilken
  // gezinmeyi `AsistanPaneli` (ekranDegisti) yakalar; bu effect sekme açıkken bileşen state'ini düşürür.
  const ekranAnahtari = ekranAnahtariUret(ekran);
  const ekranDahil = ekranKaldirilan !== ekranAnahtari;
  useEffect(() => {
    if (ekranKaldirilan !== null && ekranKaldirilan !== ekranAnahtari) setEkranKaldirilan(null);
  }, [ekranAnahtari]);

  // Son hata: "Asistana sor" ile seçilen kayıt, yoksa 5 dk içindeki son kayıt. Seçilen kaydın
  // süresi dolduysa başka (ilgisiz) bir hataya düşülmez: o hata sorusu bağlamsız kalır, not gösterilir.
  useSyncExternalStore(sonHataAbone, sonHataSurumu);
  const gecerliHata = useCallback(
    (): SonHataKaydi | null => (secilenHataId ? hataKaydi(secilenHataId) : sonHata()),
    [secilenHataId],
  );
  const hata = gecerliHata();
  const hataDahil = !hata || hataKaldirilan !== hata.kayitId;
  useEffect(() => {
    if (hataKaldirilan !== null && hataKaldirilan !== hata?.kayitId) setHataKaldirilan(null);
  }, [hata?.kayitId]);
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
    if (sohbetId && yuklemeyiAtla.current === sohbetId) {
      yuklemeyiAtla.current = null;
      return;
    }
    yuklemeyiAtla.current = null;
    if (sohbetId) void yukle(sohbetId);
    else setMesajlar([]);
  }, [sohbetId, yukle]);

  const bekleyenler = useMemo(() => mesajlar.filter((m) => m.rol === "assistant" && bekliyor(m)), [mesajlar]);
  // Öneriler sekmesindeki "Başka ne yapabilirim?" de kullanıcının bekleyen sorusudur (sunucu 409 bekleyen_var).
  const ekBekleyen = useBekleyenEkOneri();
  /** Bu sohbette yanıt bekleyen kullanıcı sorusu: sohbetten çıkılırsa bekleme ve "Beklemeyi bırak"
   * görünmez olur, sunucu ise cevap gelene dek her yeni soruya 409 verir. Bu yüzden o sürede
   * "Yeni sohbet" ve "Geçmiş" pasiftir (ek öneri bekleyeni kendi deposunda tutulur, sayılmaz). */
  const sohbetteBekleyenId = bekleyenler.find((m) => m.tetik === "kullanici")?.id ?? null;
  const sohbetteBekleyen = !!sohbetteBekleyenId;
  // Öneriler sekmesindeki "Başka ne yapabilirim?" de bu süre pasif olsun (ters yön kilidi). Sekme
  // kalkınca kayıt silinmez: Öneriler açıkken cevap gelince orada düşer.
  useEffect(() => sohbetBekleyeniYaz(sohbetteBekleyenId), [sohbetteBekleyenId]);
  const kullaniciBekliyor = sohbetteBekleyen || !!ekBekleyen;
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

  /** Bekleyen mesajları tek tek okur; biten varsa sohbet ve durum yenilenir. */
  const bekleyenleriOku = useCallback(
    async (ids: string[]) => {
      let bitti = false;
      for (const id of ids) {
        try {
          const m = await asistanApi.mesaj(id);
          if (!bekliyor(m)) bitti = true;
          // Core mesaj yanıtı adım kodu taşımaz; `running` görüldüyse listeye yazılır
          // (iptal notu "işlenen kısım ücretlendi" buna dayanır).
          else if (m.durum === "running") setMesajlar((l) => l.map((x) => (x.id === id && x.durum !== "running" ? { ...x, durum: "running" } : x)));
        } catch {
          /* bir sonraki turda / olayda yeniden denenir */
        }
      }
      if (bitti && sohbetRef.current) {
        await yukle(sohbetRef.current, true);
        durumYenile();
      }
    },
    [yukle, durumYenile],
  );

  // SSE kopukken (yeniden bağlanıyor / kapalı) 3 sn'de bir yoklama.
  const sseVar = baglanti === "bagli" || baglanti === "mock";
  useEffect(() => {
    if (!bekleyenAnahtar || sseVar) return;
    const ids = bekleyenAnahtar.split("|");
    const z = setInterval(() => void bekleyenleriOku(ids), sohbetAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [bekleyenAnahtar, sseVar, bekleyenleriOku]);

  // SSE yeniden bağlanınca (kopuk → bağlı) bekleyenler bir kez okunur: kopukluk yoklama aralığından
  // kısa sürdüyse arada yayınlanan `assistant.answered` kaçmış olabilir (Last-Event-ID ile tekrar
  // oynatma yok); okunmazsa bekleme takılı kalır ve yeni soru engellenirdi.
  const oncekiSse = useRef(sseVar);
  useEffect(() => {
    const onceki = oncekiSse.current;
    oncekiSse.current = sseVar;
    if (onceki || !sseVar) return;
    if (bekleyenAnahtar) void bekleyenleriOku(bekleyenAnahtar.split("|"));
    if (ekBekleyen) void ekOneriKontrol(ekBekleyen);
    // Yalnız bağlantı geçişinde: bekleyen listesi değişince yeniden okunmaz.
  }, [sseVar]);

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
    duyur(son.durum === "done" ? "Asistanın cevabı geldi." : son.durum === "iptal" ? "Soru iptal edildi." : "Soru tamamlanamadı.");
  }, [bekleyenAnahtar, mesajlar, duyur]);

  /** Bekleme başlangıcı: mesajın bu sekmede ilk görüldüğü an (istemci saati). */
  const baslangic = (m: AsistanMesaji): number => {
    let t = ilkGorulmeler.get(m.id);
    if (t === undefined) {
      t = Date.now();
      ilkGorulmeler.set(m.id, t);
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
        setBekletilen(secenek.oneriKuralId || secenek.yeniSohbet || secenek.sohbetId ? { metin, ekran: ekranAnahtari, secenek } : null);
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
        // Öneri sohbeti hatırlanır: kartın sonraki hazır soruları bu sohbete gider.
        if (kural) oneriSohbetiYaz(kural, ekran.varlik?.id, id);
        // Yeni sohbete ancak soru kabul edildikten sonra geçilir (409'da mevcut sohbet kalır).
        if (yeniId) {
          sohbetRef.current = yeniId;
          sohbetiHatirla(yeniId);
          yuklemeyiAtla.current = yeniId;
          setSohbetId(yeniId);
          setMesajlar([]);
        } else if (id !== sohbetRef.current) {
          // Başka sohbette soruldu ("Bunu sor": ek öneri sohbeti): o sohbete geçilir.
          sohbetRef.current = id;
          sohbetiHatirla(id);
          yuklemeyiAtla.current = id;
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
        // Hedef öneri sohbeti silinmiş: eşleme düşer, sonraki çip yeni sohbet açar.
        if (secenek.sohbetId && e instanceof ApiError && e.status === 404) oneriSohbetiUnut(secenek.sohbetId);
        setGonderimHatasi(gonderimHataMetni(e));
        // Öneri geçersizleşti: Öneriler sekmesi/rozet eski kartı göstermesin, bu ekranın önerileri yenilenir.
        if (e instanceof ApiError && e.kod === "oneri_gecersiz") {
          const sorgu = oneriSorgusu(ekran);
          if (kullanici && sorgu) void oneriGetir(oneriAnahtari(kullanici.id, sorgu), sorgu, { zorla: true });
        }
        // Asistan bu arada kapandıysa (worker gitti) panel nedenini gösteren pasif uyarıya geçsin.
        if (asistanKapandi(e)) durumYenile();
      } finally {
        setGonderiyor(false);
      }
    },
    [gonderiyor, kullaniciBekliyor, baglamUret, seciliTemizle, yukle, durumYenile, ekran, ekranAnahtari, kullanici],
  );

  // Dış istek: "Asistana sor" (hata kaydı) ya da "Neden? Sor" (öneri kuralı + soru).
  useEffect(() => {
    if (!istek || istek.sekme !== "sohbet") return;
    // StrictMode effect'i iki kez çalıştırır ve ikinci çağrı aynı `istek` prop'unu görür.
    if (islenenSira.current === istek.sira) return;
    islenenSira.current = istek.sira;
    istegiTuket(istek.sira);
    // Bayat istek (Sohbet o sırada çizilemedi): kullanıcı bir şey yapmadan eski soru gönderilmez.
    if (!istekGecerli(istek)) return;
    // Panel Geçmiş görünümündeyse sohbete dönülür: hata çipi ve doldurulan soru görünsün.
    setGecmisAcik(false);
    setSilinecek(null);
    if (istek.kayitId) {
      setSecilenHataId(istek.kayitId);
      setHataKaldirilan(null);
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
      // Geçmiş açıktıysa girdi bu çizimde yok: odak, girdi çizildikten sonra verilir.
      setOdakIste((n) => n + 1);
    }
    // gonder kasıtlı olarak bağımlılık değil: istek bir kez işlenir (sira ile tüketilir).
  }, [istek]);

  useEffect(() => {
    if (odakIste) girdiRef.current?.focus();
  }, [odakIste]);

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
      oneriSohbetiUnut(s.id);
      if (s.id === sohbetId) sohbetiBirak();
    } catch (e) {
      setGecmisHatasi(`Sohbet silinemedi: ${hataMesaji(e)}`);
    } finally {
      setSilinecek(null);
    }
  };

  const iptalEt = async (m: AsistanMesaji) => {
    try {
      // Ücret notu sunucunun gördüğü duruma göre: core mesaj yanıtı "başladı" bilgisi taşımaz,
      // iptal yanıtında durum artık `iptal`dir. Bu yüzden iptalden hemen önce güncel durum okunur
      // (SSE kopukken listedeki `m.durum` eski `pending` olabilir).
      const once = await asistanApi.mesaj(m.id).catch(() => null);
      const yanit = await asistanApi.iptal(m.id);
      const son = yanit && typeof yanit === "object" && "durum" in yanit ? yanit : null;
      const basladi =
        m.durum === "running" ||
        once?.durum === "running" ||
        (!!adimlar[m.id] && adimlar[m.id] !== "sirada") ||
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
  const oneriler = soruOnerileri(kullanici?.rol, ekran, { modelAcik, sonHataVar: !!hata && hataDahil });

  const bekleme = (m: AsistanMesaji, etiket?: string) => (
    <div className="asistan-bekleme" role="status" data-testid="asistan-bekleme">
      <span className="donen donen-kucuk" aria-hidden="true" />
      <span>
        {etiket ?? adimMetni(adimlar[m.id] ?? (m.durum === "pending" ? "sirada" : null))}
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
            <Ikon ad="geri" /> Geri
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

  /** Girdideki soru bekletilen dış soruysa onun seçenekleri (öneri kuralı, sohbet); elle değiştiyse yok.
   * Öneri kuralı bırakıldığı ekrana bağlıdır: başka ekranda gönderilirse kural düşer (sunucu 409
   * `oneri_gecersiz` verirdi); soru yine yeni sohbette, o anki ekran bağlamıyla gider. */
  const bekletilenSecenek = (): GonderSecenegi => {
    if (!bekletilen || bekletilen.metin !== girdi.trim()) return {};
    if (bekletilen.ekran === ekranAnahtari) return bekletilen.secenek;
    return { ...bekletilen.secenek, oneriKuralId: null };
  };
  const sayac = girdi.length;
  const gonderilemez = !girdi.trim() || sayac > SORU_AZAMI || gonderiyor || kullaniciBekliyor;
  const kokler = mesajlar.filter((m) => !m.ust_mesaj_id);

  return (
    <div className="asistan-sohbet">
      <div className="asistan-sohbet-eylem">
        <button
          type="button"
          className="dugme dugme-hayalet dugme-kucuk"
          onClick={yeniSohbet}
          disabled={sohbetteBekleyen}
          aria-describedby={sohbetteBekleyen ? "asistan-sohbet-kilit" : undefined}
        >
          <Ikon ad="arti" /> Yeni sohbet
        </button>
        <button
          type="button"
          className="dugme dugme-hayalet dugme-kucuk"
          onClick={() => void gecmisiAc()}
          disabled={sohbetteBekleyen}
          aria-describedby={sohbetteBekleyen ? "asistan-sohbet-kilit" : undefined}
        >
          <Ikon ad="gecmis" /> Geçmiş
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
        <div className="asistan-cipler" role="group" aria-label="Soruya eklenecek bağlam">
          {ekranDahil && ekran.rota_kalibi && (
            <span className="cip cip-bilgi asistan-baglam-cipi">
              Bu ekran: {ekran.ekran}
              {ekran.varlik?.anahtar ? ` · ${ekran.varlik.anahtar}` : ""}
              <button type="button" className="asistan-cip-kaldir" aria-label="Ekran bağlamını kaldır" onClick={() => setEkranKaldirilan(ekranAnahtari)}>
                <Ikon ad="kapat" />
              </button>
            </span>
          )}
          {hata && hataDahil && (
            <span className="cip cip-uyari asistan-baglam-cipi" title={hata.detail}>
              Son hata: {(hata.gorunen_metin ?? hata.detail).slice(0, 60)}
              <button type="button" className="asistan-cip-kaldir" aria-label="Son hata bağlamını kaldır" onClick={() => setHataKaldirilan(hata.kayitId)}>
                <Ikon ad="kapat" />
              </button>
            </span>
          )}
          {secili && (
            <span className="cip cip-bilgi asistan-baglam-cipi">
              Seçili: {secili.ad || secili.ipucu || secili.test_id}
              <button type="button" className="asistan-cip-kaldir" aria-label="Seçili öğeyi kaldır" onClick={seciliTemizle}>
                <Ikon ad="kapat" />
              </button>
            </span>
          )}
          {/* Model kapalıyken seçili öğe sorusu cevaplanamaz (yalnız "kapalı" metni döner): düğme gizli. */}
          {modelAcik && (
            // Erişilebilir ad "? Bu ne?" korunur (testler ve plan bu adla arar); "?" glifi yerine SVG ikon.
            <button type="button" className="cip cip-notr asistan-bune-dugmesi" aria-label="? Bu ne?" aria-pressed={buNeAcik} onClick={buNeBaslat}>
              <Ikon ad="soru" /> Bu ne?
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
          <button
            type="submit"
            className="dugme dugme-birincil dugme-kucuk"
            disabled={gonderilemez}
            aria-busy={gonderiyor || undefined}
            aria-describedby={sohbetteBekleyen ? "asistan-sohbet-kilit" : undefined}
          >
            Asistana sor <Ikon ad="gonder" />
          </button>
        </div>
        {ekBekleyen ? (
          <p className="soluk kucuk" role="status" data-testid="ek-oneri-bekliyor">
            Ek öneriler hazırlanıyor (Öneriler sekmesi); bitince yeni soru sorabilirsiniz.{" "}
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void ekOneriDurdur(ekBekleyen)}>
              Durdur
            </button>
          </p>
        ) : null}
        {/* "Yeni sohbet" / "Geçmiş" aria-describedby buna işaret eder: ek öneri de beklerken çizilir;
            pasifleşme ekran okuyucuya duyurulsun diye canlı bölgedir. */}
        {sohbetteBekleyen && (
          <p className="soluk kucuk" id="asistan-sohbet-kilit" role="status">
            Cevap gelince yeni soru sorabilir, yeni sohbet açabilirsiniz.
          </p>
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

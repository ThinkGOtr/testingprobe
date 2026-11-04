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
import { hataKaydi, sonHata, sonHataAbone, sonHataBaglami, sonHataSurumu, type SonHataKaydi } from "../../lib/sonHata";
import { BosDurum, Yukleniyor } from "../ui";
import type { SeciliEleman } from "./buNe";
import { CevapKarti } from "./CevapKarti";
import type { AcmaIstegi } from "./kontrol";
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

function gecenSure(iso: string, simdi: number): string {
  const sn = Math.max(0, Math.floor((simdi - new Date(iso).getTime()) / 1000));
  return sn < 60 ? `${sn} sn` : `${Math.floor(sn / 60)} dk ${String(sn % 60).padStart(2, "0")} sn`;
}

function uzunSurdu(iso: string, simdi: number): boolean {
  return simdi - new Date(iso).getTime() >= sohbetAyar.uzunSurerMs;
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
  const [silinecek, setSilinecek] = useState<Sohbet | null>(null);
  const [ekranDahil, setEkranDahil] = useState(true);
  const [hataDahil, setHataDahil] = useState(true);
  const [secilenHataId, setSecilenHataId] = useState<string | null>(null);
  const [oneriKuralId, setOneriKuralId] = useState<string | null>(null);
  const girdiRef = useRef<HTMLTextAreaElement>(null);
  const sohbetRef = useRef(sohbetId);
  sohbetRef.current = sohbetId;

  // Rota değişince ekran çipi yeniden eklenir (kaldırma yalnız o ekran için).
  useEffect(() => setEkranDahil(true), [ekran.rota_kalibi, ekran.varlik?.id]);

  // Son hata: "Asistana sor" ile seçilen kayıt, yoksa 5 dk içindeki son kayıt.
  useSyncExternalStore(sonHataAbone, sonHataSurumu);
  const hata: SonHataKaydi | null = (secilenHataId ? hataKaydi(secilenHataId) : null) ?? sonHata();
  useEffect(() => setHataDahil(true), [hata?.kayitId]);

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
  const kullaniciBekliyor = bekleyenler.some((m) => m.tetik === "kullanici");
  const bekleyenAnahtar = bekleyenler.map((m) => m.id).join("|");

  // Olaylar: core yalnız bu kullanıcının asistan olaylarını teslim eder.
  useOlay(
    (o) => {
      const id = typeof o.data.mesaj_id === "string" ? o.data.mesaj_id : o.id;
      if (!id) return;
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

  // Geçen süre sayacı.
  useEffect(() => {
    if (!bekleyenAnahtar) return;
    setSimdi(Date.now());
    const z = setInterval(() => setSimdi(Date.now()), sohbetAyar.saatMs);
    return () => clearInterval(z);
  }, [bekleyenAnahtar]);

  const baglamUret = useCallback((): Record<string, unknown> => {
    const b: Record<string, unknown> = {};
    if (ekranDahil) {
      b.rota_kalibi = ekran.rota_kalibi;
      b.ekran = ekran.ekran;
      if (ekran.varlik) b.varlik = { tur: ekran.varlik.tur, id: ekran.varlik.id, anahtar: ekran.varlik.anahtar ?? null };
    }
    if (hata && hataDahil) b.son_hata = sonHataBaglami(hata);
    if (secili) b.secili_eleman = secili;
    return baglamiSigdir(b);
  }, [ekranDahil, ekran, hata, hataDahil, secili]);

  const gonder = useCallback(
    async (soru: string, secenek: { yeniSohbet?: boolean; oneriKuralId?: string | null } = {}) => {
      const metin = soru.trim();
      if (!metin || gonderiyor) return;
      // Yanıt bekleyen soru varken (bu sekmede) yeni soru gönderilmez: sunucu 409 bekleyen_var
      // döndürür. Yeni sohbete de geçilmez; soru girdide kalır, cevap gelince gönderilir.
      if (kullaniciBekliyor) {
        setGirdi(metin);
        setGonderimHatasi(BEKLEYEN_VAR_METNI);
        return;
      }
      setGonderiyor(true);
      setGonderimHatasi(null);
      let yeniId: string | null = null;
      try {
        let id = secenek.yeniSohbet ? null : sohbetRef.current;
        const kural = secenek.oneriKuralId ?? (secenek.yeniSohbet ? null : oneriKuralId);
        if (!id) {
          yeniId = (await asistanApi.sohbetOlustur(null)).id;
          id = yeniId;
        }
        await asistanApi.soruGonder(id, {
          soru: metin,
          baglam: baglamUret(),
          kip: "soru",
          ...(kural ? { oneri_kural_id: kural } : {}),
        });
        // Yeni sohbete ancak soru kabul edildikten sonra geçilir (409'da mevcut sohbet kalır).
        if (yeniId) {
          sohbetRef.current = yeniId;
          sohbetiHatirla(yeniId);
          setSohbetId(yeniId);
          setMesajlar([]);
          setOneriKuralId(kural ?? null);
        }
        setGirdi("");
        seciliTemizle();
        await yukle(id, true);
        durumYenile();
      } catch (e) {
        if (yeniId && sohbetRef.current !== yeniId) {
          // Soru kabul edilmedi: az önce açılan boş sohbet sahipsiz kalmasın.
          void asistanApi.sohbetSil(yeniId).catch(() => undefined);
          setGirdi((g) => g || metin);
        }
        setGonderimHatasi(gonderimHataMetni(e));
      } finally {
        setGonderiyor(false);
      }
    },
    [gonderiyor, kullaniciBekliyor, oneriKuralId, baglamUret, seciliTemizle, yukle, durumYenile],
  );

  // Dış istek: "Asistana sor" (hata kaydı) ya da "Neden? Sor" (öneri kuralı + soru).
  useEffect(() => {
    if (!istek || istek.sekme !== "sohbet") return;
    istegiTuket(istek.sira);
    if (istek.kayitId) {
      setSecilenHataId(istek.kayitId);
      setHataDahil(true);
      if (!istek.soru) setGirdi((g) => g || "Bu hata ne demek, ne yapmalıyım?");
    }
    if (istek.soru) {
      void gonder(istek.soru, { yeniSohbet: !!istek.oneriKuralId, oneriKuralId: istek.oneriKuralId ?? null });
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
    setOneriKuralId(null);
    setGonderimHatasi(null);
  };

  const yeniSohbet = () => {
    sohbetiBirak();
    setGecmisAcik(false);
    girdiRef.current?.focus();
  };

  const gecmisiAc = async () => {
    setGecmisAcik(true);
    setSohbetler(null);
    try {
      setSohbetler(await asistanApi.sohbetler());
    } catch (e) {
      setSohbetler([]);
      setYuklemeHatasi(hataMesaji(e));
    }
  };

  const sil = async (s: Sohbet) => {
    try {
      await asistanApi.sohbetSil(s.id);
      setSohbetler((l) => (l ?? []).filter((x) => x.id !== s.id));
      if (s.id === sohbetId) sohbetiBirak();
    } catch (e) {
      setYuklemeHatasi(hataMesaji(e));
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
        <span aria-hidden="true"> · {gecenSure(m.olusturma, simdi)}</span>
      </span>
      {uzunSurdu(m.olusturma, simdi) && <span className="asistan-uzun">Uzun sürüyor</span>}
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
        {sohbetler === null ? (
          <Yukleniyor />
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
                    setOneriKuralId(s.oneri_kural_id ?? null);
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
      <div className="asistan-mesajlar" aria-live="polite">
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
          if (!gonderilemez) void gonder(girdi);
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
          <button type="button" className="cip cip-notr asistan-bune-dugmesi" aria-pressed={buNeAcik} onClick={buNeBaslat}>
            ? Bu ne?
          </button>
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
          onChange={(e) => setGirdi(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (!gonderilemez) void gonder(girdi);
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
        {kullaniciBekliyor && <p className="soluk kucuk">Cevap gelince yeni soru sorabilirsiniz.</p>}
        {gonderimHatasi && (
          <div className="uyari-kutusu uyari-hata" role="alert">
            {gonderimHatasi}
          </div>
        )}
      </form>
    </div>
  );
}

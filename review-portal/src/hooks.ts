import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, cakismaMesaji, hataMesaji, kararCakismasi } from "./api/http";

export interface VeriDurumu<T> {
  veri: T | undefined;
  hata: string | null;
  /** Son hatanın HTTP durum kodu (ApiError değilse null); ör. 403'te "Tekrar dene" anlamsızdır. */
  hataKodu: number | null;
  /** Son hatanın kendisi (ApiError ise `kayitId` taşır); `HataKutusu kaynak` prop'una verilir. */
  hataNesnesi: unknown;
  yukleniyor: boolean;
  /** sessiz=true: mevcut veriyi koruyarak arka planda yenile (SSE olaylarında). */
  yenile: (sessiz?: boolean) => Promise<void>;
  setVeri: (v: T) => void;
}

/** Basit veri yükleyici: yarış durumlarını (eski isteğin geç dönmesi) yok sayar. */
export function useVeri<T>(yukle: () => Promise<T>, bagimliliklar: readonly unknown[]): VeriDurumu<T> {
  const [veri, setVeri] = useState<T | undefined>(undefined);
  const [hata, setHata] = useState<string | null>(null);
  const [hataKodu, setHataKodu] = useState<number | null>(null);
  const [hataNesnesi, setHataNesnesi] = useState<unknown>(null);
  const [yukleniyor, setYukleniyor] = useState(true);
  const sayac = useRef(0);
  const yukleRef = useRef(yukle);
  yukleRef.current = yukle;

  const yenile = useCallback(async (sessiz = false) => {
    const benim = ++sayac.current;
    if (!sessiz) setYukleniyor(true);
    try {
      const v = await yukleRef.current();
      if (benim === sayac.current) {
        setVeri(v);
        setHata(null);
        setHataKodu(null);
        setHataNesnesi(null);
      }
    } catch (e) {
      if (benim === sayac.current) {
        setHata(hataMesaji(e));
        setHataKodu(e instanceof ApiError ? e.status : null);
        setHataNesnesi(e);
      }
    } finally {
      if (benim === sayac.current) setYukleniyor(false);
    }
  }, []);

  useEffect(() => {
    setVeri(undefined);
    void yenile();
    return () => {
      sayac.current++;
    };
  }, bagimliliklar);

  return { veri, hata, hataKodu, hataNesnesi, yukleniyor, yenile, setVeri };
}

export interface IslemSecenegi {
  /**
   * İnsan kararı uçları için: 409 (içerik siz görüntüledikten sonra değişti / durum değişti)
   * gelince çağrılır — ekran güncel içeriği yeniden yükler, kullanıcı yeniden inceler.
   */
  cakismada?: () => void;
}

export interface IslemDurumu {
  calisiyor: boolean;
  hata: string | null;
  /** Son hatanın kendisi (`HataKutusu kaynak`). */
  hataNesnesi: unknown;
  calistir: <T>(fn: () => Promise<T>, secenek?: IslemSecenegi) => Promise<T | undefined>;
  temizle: () => void;
}

/** Tek bir eylemin (POST) bekleme ve hata durumu. */
export function useIslem(): IslemDurumu {
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const [hataNesnesi, setHataNesnesi] = useState<unknown>(null);
  const bagli = useRef(true);
  // Yeniden giriş kilidi: state güncellemesi bir sonraki çizime kadar görünmez; aynı olay
  // döngüsündeki ikinci tıklama (çift tıklama) ikinci isteği göndermesin diye ref ile kilitlenir.
  const kilit = useRef(false);
  useEffect(() => {
    bagli.current = true;
    return () => {
      bagli.current = false;
    };
  }, []);
  const calistir = useCallback(async <T,>(fn: () => Promise<T>, secenek?: IslemSecenegi) => {
    if (kilit.current) return undefined;
    kilit.current = true;
    setCalisiyor(true);
    setHata(null);
    setHataNesnesi(null);
    try {
      return await fn();
    } catch (e) {
      if (secenek?.cakismada && kararCakismasi(e)) {
        if (bagli.current) {
          setHata(cakismaMesaji(e));
          setHataNesnesi(e);
        }
        secenek.cakismada();
      } else if (bagli.current) {
        setHata(hataMesaji(e));
        setHataNesnesi(e);
      }
      return undefined;
    } finally {
      kilit.current = false;
      if (bagli.current) setCalisiyor(false);
    }
  }, []);
  const temizle = useCallback(() => {
    setHata(null);
    setHataNesnesi(null);
  }, []);
  return { calisiyor, hata, hataNesnesi, calistir, temizle };
}

/** Değer değişmeden belirli süre geçince çağrılan zamanlayıcı (SSE patlamalarını birleştirir). */
export function useGeciktirilmis(fn: () => void, ms = 250): () => void {
  const zaman = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(
    () => () => {
      if (zaman.current) clearTimeout(zaman.current);
    },
    [],
  );
  return useCallback(() => {
    if (zaman.current) clearTimeout(zaman.current);
    zaman.current = setTimeout(() => fnRef.current(), ms);
  }, [ms]);
}

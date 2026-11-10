import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api/client";
import { ApiError, mockOturumuAyarla, yetkisizOlunca } from "./api/http";
import type { Kullanici, Rol } from "./api/types";
import { oturumVerileriniTemizle } from "./lib/oturumTemizligi";
import { formlariSakla } from "./lib/formYedegi";
import { aiprobeCikisAdresi, aiprobeKipinde, cikisYonlendirmesi, kimlikKipi, yonlendirmeSayaciniSifirla } from "./lib/kimlikKipi";

interface OturumBaglami {
  kullanici: Kullanici | null;
  yukleniyor: boolean;
  girisYap: (kullaniciAdi: string, parola: string) => Promise<Kullanici>;
  /**
   * Çıkış. Dönen adres boş değilse çağıran oraya tam sayfa gider (AI Probe oturumu: tüm ürünlerden
   * çıkış sayfası); `local` kipte her zaman null (bugünkü gibi `/giris`).
   */
  cikisYap: () => Promise<string | null>;
  /** Sunucunun açtığı oturumu (AI Probe rol seçici / "Rol değiştir") istemciye işler. */
  oturumKur: (k: Kullanici) => void;
}

const Baglam = createContext<OturumBaglami | null>(null);

export function OturumProvider({ children }: { children: ReactNode }) {
  const [kullanici, setKullanici] = useState<Kullanici | null>(null);
  const [yukleniyor, setYukleniyor] = useState(true);
  /** Son bilinen kullanıcı: çıkışta ya da başka kullanıcıya geçişte istemci depoları temizlenir. */
  const oncekiId = useRef<string | null>(null);

  const ayarla = useCallback((k: Kullanici | null) => {
    // Sayfa açılışındaki `me()` (null → kullanıcı) temizlemez: yenilemeden sonra bekleyen
    // asistan mesajına yeniden bağlanılabilsin. Bilinen kullanıcı gidince ya da değişince temizler.
    const yeniId = k?.id ?? null;
    if (oncekiId.current !== null && oncekiId.current !== yeniId) oturumVerileriniTemizle();
    oncekiId.current = yeniId;
    mockOturumuAyarla(k);
    setKullanici(k);
  }, []);

  useEffect(() => {
    let iptal = false;
    api
      .me()
      .then((k) => {
        if (iptal) return;
        yonlendirmeSayaciniSifirla();
        ayarla(k);
      })
      .catch(() => !iptal && ayarla(null))
      .finally(() => !iptal && setYukleniyor(false));
    yetkisizOlunca(() => {
      // AI Probe kipinde 401 yeniden giriş demektir (tam sayfa yönlendirme): ekrandaki form verisi
      // önce yedeklenir, dönüşte geri konur (lib/formYedegi.ts). `local` kipte davranış aynı.
      if (aiprobeKipinde()) formlariSakla(window.location.pathname + window.location.search, oncekiId.current);
      ayarla(null);
    });
    return () => {
      iptal = true;
      yetkisizOlunca(null);
    };
  }, [ayarla]);

  const girisYap = useCallback(
    async (kullaniciAdi: string, parola: string) => {
      const k = await api.login(kullaniciAdi, parola);
      // Açık giriş yeni oturumdur: önceki kullanıcıdan (ör. süresi dolup yeniden yüklenen sekme)
      // kalan sohbet/hata kayıtları taşınmaz.
      oturumVerileriniTemizle();
      ayarla(k);
      return k;
    },
    [ayarla],
  );

  const cikisYap = useCallback(async (): Promise<string | null> => {
    let hedef: string | null = null;
    try {
      const yanit = await api.logout();
      hedef = cikisYonlendirmesi(yanit?.redirect);
    } catch (e) {
      // Oturum zaten düşmüşse (401) yine de yerelde çıkış yapılır.
      if (!(e instanceof ApiError)) throw e;
    } finally {
      ayarla(null);
    }
    // Yalnız AI Probe kipinde yerel giriş yoktur: `/giris` yeniden AI Probe girişine götüreceği için
    // çıkış (yanıt yönlendirme taşımasa da) AI Probe çıkış sayfasında biter.
    if (!hedef && kimlikKipi().kip === "aiprobe") hedef = aiprobeCikisAdresi();
    return hedef;
  }, [ayarla]);

  const oturumKur = useCallback(
    (k: Kullanici) => {
      yonlendirmeSayaciniSifirla();
      ayarla(k);
    },
    [ayarla],
  );

  const deger = useMemo(
    () => ({ kullanici, yukleniyor, girisYap, cikisYap, oturumKur }),
    [kullanici, yukleniyor, girisYap, cikisYap, oturumKur],
  );
  return <Baglam.Provider value={deger}>{children}</Baglam.Provider>;
}

export function useOturum(): OturumBaglami {
  const b = useContext(Baglam);
  if (!b) throw new Error("useOturum OturumProvider içinde kullanılmalı");
  return b;
}

/**
 * Kullanıcı adını (denetim aktörü, onaylayan, karar veren …) görünen ada çevirir:
 * "analist" → "Cengizhan Gunaydin · Analist". Eşlemede olmayan değer ("system", Jira hesabı) aynen
 * döner. Yalnızca gösterim içindir; yetki kararları `rol` ile verilir.
 */
export function kisiAdiCevir(kisiler: Record<string, string> | undefined, ad: string | null | undefined): string {
  if (!ad) return "";
  return kisiler?.[ad] ?? kisiler?.[ad.trim().toLowerCase()] ?? ad;
}

export function useKisiAdi(): (ad: string | null | undefined) => string {
  // Sağlayıcı dışında (bileşen testleri) eşleme yok: ad aynen gösterilir.
  const kisiler = useContext(Baglam)?.kullanici?.kisiler;
  return useCallback((ad: string | null | undefined) => kisiAdiCevir(kisiler, ad), [kisiler]);
}

/** Kullanıcı verilen rollerden birine sahip mi? */
export function useRol(...roller: Rol[]): boolean {
  const { kullanici } = useOturum();
  return !!kullanici && roller.includes(kullanici.rol);
}

/** Ekranın core'daki veri ucu (canlı derlemede ekran ancak uç varsa açılış sayfası olur). */
const EKRAN_UCU: Record<string, readonly [string, string]> = {
  "/kod": ["GET", "/scripts"],
  "/kosular": ["GET", "/runs"],
  "/kontrol-kulesi": ["GET", "/control-tower"],
  "/bug-taslaklari": ["GET", "/bug-drafts"],
  "/gereksinimler": ["GET", "/requirements"],
  "/yol-haritasi": ["GET", "/requirements"],
};

const ROL_SAYFALARI: Record<Rol, string[]> = {
  engineer: ["/kod", "/kosular", "/gereksinimler"],
  presenter: ["/yol-haritasi", "/kontrol-kulesi", "/kosular", "/gereksinimler"],
  tester: ["/bug-taslaklari", "/kosular", "/gereksinimler"],
  analyst: ["/gereksinimler"],
  po: ["/gereksinimler"],
};

/**
 * Rol bazlı varsayılan açılış ekranı: sunucu → Demo yol haritası, mühendis → Kod üretimi, testçi →
 * Bug taslakları. `ucVar` verilirse (canlı derleme, core'un uç listesi) core'un henüz sunmadığı
 * ekran atlanır — kullanıcı "bu fazda yok" ekranına düşmez, sıradaki ekrana gider.
 */
export function varsayilanSayfa(rol: Rol, ucVar?: (method: string, yol: string) => boolean): string {
  const adaylar = ROL_SAYFALARI[rol] ?? ["/gereksinimler"];
  if (!ucVar) return adaylar[0];
  return adaylar.find((y) => !EKRAN_UCU[y] || ucVar(...EKRAN_UCU[y])) ?? "/gereksinimler";
}

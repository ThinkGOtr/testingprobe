import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api/client";
import { ApiError, mockOturumuAyarla, yetkisizOlunca } from "./api/http";
import type { Kullanici, Rol } from "./api/types";
import { oturumVerileriniTemizle } from "./lib/oturumTemizligi";
import { formlariSakla } from "./lib/formYedegi";
import { izinVar, KISITLI_BUG_ROLLERI, KISITLI_CASE_ROLLERI, normalizeRol, oturumIzinleri, rotaIzinleri, ROTA_IZINLERI, type Izin } from "./lib/yetki";
import { aiprobeCikisAdresi, aiprobeKipinde, cikisSurecinde, cikisSureciniAyarla, cikisYonlendirmesi, kimlikKipi, yonlendirmeSayaciniSifirla } from "./lib/kimlikKipi";

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
      if (aiprobeKipinde() && !cikisSurecinde()) formlariSakla(window.location.pathname + window.location.search, oncekiId.current);
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
    // Çıkış süreci: yanıt beklenirken ya da tam sayfa çıkış gezintisi başlarken oturumsuz kalan
    // korumalı rota AI Probe girişini (SSO) yeniden tetiklemez (bkz. lib/kimlikKipi.ts).
    cikisSureciniAyarla(true);
    let hedef: string | null = null;
    try {
      const yanit = await api.logout();
      hedef = cikisYonlendirmesi(yanit?.redirect);
    } catch (e) {
      // Oturum zaten düşmüşse (401) yine de yerelde çıkış yapılır.
      if (!(e instanceof ApiError)) {
        cikisSureciniAyarla(false);
        ayarla(null);
        throw e;
      }
    }
    // Yalnız AI Probe kipinde yerel giriş yoktur: `/giris` yeniden AI Probe girişine götüreceği için
    // çıkış (yanıt yönlendirme taşımasa da) AI Probe çıkış sayfasında biter.
    if (!hedef && kimlikKipi().kip === "aiprobe") hedef = aiprobeCikisAdresi();
    if (hedef) {
      // Tam sayfa çıkış: kullanıcı boşaltılmaz (boşalırsa korumalı rota SSO girişini başlatıp çıkış
      // gezintisini ezerdi); istemci depoları yine de şimdi temizlenir. Gezintiyi çağıran yapar.
      oturumVerileriniTemizle();
      mockOturumuAyarla(null);
      return hedef;
    }
    cikisSureciniAyarla(false);
    ayarla(null);
    return null;
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

/** Oturumun etkin izinleri (`/auth/me` → `izinler`; yoksa katalogdan rolün izinleri). */
export function useIzinler(): ReadonlySet<string> {
  // Sağlayıcı dışında (bileşen testleri) oturum yok: izin yok.
  const kullanici = useContext(Baglam)?.kullanici ?? null;
  return useMemo(() => oturumIzinleri(kullanici), [kullanici]);
}

/**
 * Adrese gidilebilir mi (`ROTA_IZINLERI`): korumasız adres ya da oturum yokken (sayfa koruması
 * zaten girişe yönlendirir) true; oturumlu ve izinsizse false.
 */
export function useRotaIzni(yol: string): boolean {
  const kullanici = useContext(Baglam)?.kullanici ?? null;
  const izinler = useIzinler();
  const istenen = rotaIzinleri(yol);
  return !kullanici || istenen.length === 0 || izinVar(izinler, ...istenen);
}

/** Oturum verilen izinlerden en az birine sahip mi? (`useIzin("case.approve")`) */
export function useIzin(...izinler: Izin[]): boolean {
  return izinVar(useIzinler(), ...izinler);
}

/**
 * Case'i kısıtlı görüyor mu (developer): yalnız onaylı/yayınlanmış case, karar geçmişi ve sohbet
 * yok. Core süzgeci aynı kuralı uygular; portal yalnızca bu panelleri çizmez.
 */
export function useCaseKisitli(): boolean {
  const rol = normalizeRol(useContext(Baglam)?.kullanici?.rol);
  return !!rol && KISITLI_CASE_ROLLERI.includes(rol);
}

/** Bug taslağını kısıtlı görüyor mu (developer): yalnız yayınlanmış taslak (core süzgeciyle aynı). */
export function useBugKisitli(): boolean {
  const rol = normalizeRol(useContext(Baglam)?.kullanici?.rol);
  return !!rol && KISITLI_BUG_ROLLERI.includes(rol);
}

/** Demo menü öğeleri ve demo açılış ekranı yalnız demo kipinde (`/demo/status` → `demo_modu`). */
export const DEMO_ROTALARI: readonly string[] = ["/yol-haritasi", "/demo"];

/**
 * Demo kipi açık mı (`GET /demo/status` → `demo_modu`). `etkin` false ise istek atılmaz (null).
 * undefined: okunuyor; null: bilinmiyor (uç yok/hata); boolean: core'un bildirdiği.
 */
export function useDemoModu(etkin = true): boolean | null | undefined {
  const [deger, setDeger] = useState<boolean | null | undefined>(etkin ? undefined : null);
  useEffect(() => {
    if (!etkin) {
      setDeger(null);
      return;
    }
    let iptal = false;
    setDeger(undefined);
    api
      .demoDurumu()
      .then((d) => !iptal && setDeger(typeof d.demo_modu === "boolean" ? d.demo_modu : null))
      .catch(() => !iptal && setDeger(null));
    return () => {
      iptal = true;
    };
  }, [etkin]);
  return deger;
}

/** Ekranın core'daki veri ucu (canlı derlemede ekran ancak uç varsa açılış sayfası olur). */
const EKRAN_UCU: Record<string, readonly [string, string]> = {
  "/kod": ["GET", "/scripts"],
  "/kosular": ["GET", "/runs"],
  "/kontrol-kulesi": ["GET", "/control-tower"],
  "/bug-taslaklari": ["GET", "/bug-drafts"],
  "/caseler": ["GET", "/cases"],
  "/gereksinimler": ["GET", "/requirements"],
  "/yol-haritasi": ["GET", "/requirements"],
  "/denetim": ["GET", "/audit"],
};

/** Rolün asıl çalışma alanı sırasıyla; izni olmayan ekran atlanır. */
const ROL_SAYFALARI: Record<Rol, string[]> = {
  admin: ["/yol-haritasi", "/kontrol-kulesi", "/kosular"],
  auditor: ["/denetim", "/kontrol-kulesi"],
  analyst: ["/gereksinimler", "/caseler"],
  po: ["/gereksinimler"],
  tester: ["/gereksinimler", "/caseler", "/bug-taslaklari", "/kosular"],
  engineer: ["/kod", "/kosular", "/gereksinimler"],
  developer: ["/kosular", "/gereksinimler"],
  viewer: ["/kontrol-kulesi", "/kosular"],
};

/**
 * Rol bazlı varsayılan açılış ekranı (izni olan ilk ekran): sistem yöneticisi → Demo yol haritası,
 * Automation Engineer → Kod üretimi, denetçi → Denetim, görüntüleyici → Kontrol Kulesi. `ucVar`
 * verilirse (canlı derleme, core'un uç listesi) core'un henüz sunmadığı ekran atlanır.
 */
export function varsayilanSayfa(
  rol: Rol,
  ucVar?: (method: string, yol: string) => boolean,
  izinler: ReadonlySet<string> = oturumIzinleri({ rol }),
  /** Demo kipi açık mı; açık değilse (false/bilinmiyor) demo ekranları açılış olmaz. Verilmezse süzülmez. */
  demoAcik?: boolean | null,
): string {
  const adaylar = (ROL_SAYFALARI[normalizeRol(rol) ?? rol] ?? ["/kontrol-kulesi"])
    .filter((y) => izinVar(izinler, ...(ROTA_IZINLERI[y] ?? [])))
    .filter((y) => demoAcik === undefined || demoAcik === true || !DEMO_ROTALARI.includes(y));
  const son = "/kontrol-kulesi";
  if (!ucVar) return adaylar[0] ?? son;
  return adaylar.find((y) => !EKRAN_UCU[y] || ucVar(...EKRAN_UCU[y])) ?? son;
}

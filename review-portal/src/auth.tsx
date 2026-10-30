import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api/client";
import { ApiError, mockOturumuAyarla, yetkisizOlunca } from "./api/http";
import type { Kullanici, Rol } from "./api/types";

interface OturumBaglami {
  kullanici: Kullanici | null;
  yukleniyor: boolean;
  girisYap: (kullaniciAdi: string, parola: string) => Promise<Kullanici>;
  cikisYap: () => Promise<void>;
}

const Baglam = createContext<OturumBaglami | null>(null);

export function OturumProvider({ children }: { children: ReactNode }) {
  const [kullanici, setKullanici] = useState<Kullanici | null>(null);
  const [yukleniyor, setYukleniyor] = useState(true);

  const ayarla = useCallback((k: Kullanici | null) => {
    mockOturumuAyarla(k);
    setKullanici(k);
  }, []);

  useEffect(() => {
    let iptal = false;
    api
      .me()
      .then((k) => !iptal && ayarla(k))
      .catch(() => !iptal && ayarla(null))
      .finally(() => !iptal && setYukleniyor(false));
    yetkisizOlunca(() => ayarla(null));
    return () => {
      iptal = true;
      yetkisizOlunca(null);
    };
  }, [ayarla]);

  const girisYap = useCallback(
    async (kullaniciAdi: string, parola: string) => {
      const k = await api.login(kullaniciAdi, parola);
      ayarla(k);
      return k;
    },
    [ayarla],
  );

  const cikisYap = useCallback(async () => {
    try {
      await api.logout();
    } catch (e) {
      // Oturum zaten düşmüşse (401) yine de yerelde çıkış yapılır.
      if (!(e instanceof ApiError)) throw e;
    } finally {
      ayarla(null);
    }
  }, [ayarla]);

  const deger = useMemo(() => ({ kullanici, yukleniyor, girisYap, cikisYap }), [kullanici, yukleniyor, girisYap, cikisYap]);
  return <Baglam.Provider value={deger}>{children}</Baglam.Provider>;
}

export function useOturum(): OturumBaglami {
  const b = useContext(Baglam);
  if (!b) throw new Error("useOturum OturumProvider içinde kullanılmalı");
  return b;
}

/** Kullanıcı verilen rollerden birine sahip mi? */
export function useRol(...roller: Rol[]): boolean {
  const { kullanici } = useOturum();
  return !!kullanici && roller.includes(kullanici.rol);
}

/** Rol bazlı varsayılan açılış ekranı. */
export function varsayilanSayfa(rol: Rol): string {
  switch (rol) {
    case "engineer":
      return "/kod";
    case "presenter":
      return "/kontrol-kulesi";
    case "tester":
      return "/bug-taslaklari";
    default:
      return "/gereksinimler";
  }
}

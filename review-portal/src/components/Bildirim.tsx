import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type Tur = "basari" | "hata" | "bilgi";
interface Bildirim {
  id: number;
  tur: Tur;
  metin: string;
}

const Baglam = createContext<(metin: string, tur?: Tur) => void>(() => {});

export function BildirimProvider({ children }: { children: ReactNode }) {
  const [liste, setListe] = useState<Bildirim[]>([]);
  const sayac = useRef(0);
  const kapat = useCallback((id: number) => setListe((l) => l.filter((b) => b.id !== id)), []);
  const bildir = useCallback(
    (metin: string, tur: Tur = "basari") => {
      const id = ++sayac.current;
      setListe((l) => [...l.slice(-3), { id, tur, metin }]);
      setTimeout(() => kapat(id), tur === "hata" ? 8000 : 4500);
    },
    [kapat],
  );
  return (
    <Baglam.Provider value={bildir}>
      {children}
      <div className="bildirimler" aria-live="polite" aria-atomic="false">
        {liste.map((b) => (
          <div key={b.id} className={`bildirim bildirim-${b.tur}`} role={b.tur === "hata" ? "alert" : "status"}>
            <span>{b.metin}</span>
            <button type="button" className="kapat" aria-label="Bildirimi kapat" onClick={() => kapat(b.id)}>
              ×
            </button>
          </div>
        ))}
      </div>
    </Baglam.Provider>
  );
}

export function useBildirim() {
  return useContext(Baglam);
}

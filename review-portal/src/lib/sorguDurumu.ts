// Liste ekranlarının süzgeç / arama / sıralama / sayfa durumu adres çubuğunda (`?ara=…&durum=…&sayfa=2`):
// bağlantı paylaşılınca, geri dönülünce ve sayfa yenilenince aynı görünüm açılır. Değişiklikler geçmişe yeni
// kayıt eklemez (`replace`), Geri düğmesi önceki ekrana döner. Varsayılan değer adreste yazılmaz.
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** Süzgeç değişince sayfa başa döner: `sayfa` bu adla tutulur ve her süzgeç yazımında silinir. */
export const SAYFA_PARAMETRESI = "sayfa";

/**
 * Birden çok süzgeç alanını adreste tutar. `varsayilan` alanların adlarını ve adreste yazılmayan
 * değerlerini verir. `ayarla(alan, deger)` tek alanı, `temizle()` hepsini varsayılana döndürür; ikisi de
 * sayfa numarasını sıfırlar. `suzuldu`: en az bir alan varsayılandan farklı.
 */
export function useSorguSuzgeci<T extends Record<string, string>>(varsayilan: T) {
  const [sorgu, setSorgu] = useSearchParams();
  const anahtar = Object.keys(varsayilan).join("|");
  const deger = useMemo(() => {
    const d = { ...varsayilan };
    for (const k of Object.keys(varsayilan) as (keyof T & string)[]) {
      const v = sorgu.get(k);
      if (v !== null) (d as Record<string, string>)[k] = v;
    }
    return d;
    // varsayilan nesnesi her çizimde yeniden yaratılabilir; alan adları değişmedikçe aynı kabul edilir.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sorgu, anahtar]);
  const ayarla = useCallback(
    (alan: keyof T & string, yeni: string) => {
      setSorgu(
        (onceki) => {
          const y = new URLSearchParams(onceki);
          if (yeni === varsayilan[alan]) y.delete(alan);
          else y.set(alan, yeni);
          y.delete(SAYFA_PARAMETRESI);
          return y;
        },
        { replace: true },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setSorgu, anahtar],
  );
  const temizle = useCallback(() => {
    setSorgu(
      (onceki) => {
        const y = new URLSearchParams(onceki);
        for (const k of Object.keys(varsayilan)) y.delete(k);
        y.delete(SAYFA_PARAMETRESI);
        return y;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setSorgu, anahtar]);
  const suzuldu = (Object.keys(varsayilan) as (keyof T)[]).some((k) => deger[k] !== varsayilan[k]);
  return { deger, ayarla, temizle, suzuldu };
}

/**
 * İstemci tarafı sayfalama: `?sayfa=` (1'den başlar; 1 adreste yazılmaz). Aralık dışı sayfa son sayfaya
 * kırpılır (süzgeç değişip liste kısalınca boş sayfa görünmez).
 */
export function useSayfalama<T>(liste: readonly T[], boyut: number) {
  const [sorgu, setSorgu] = useSearchParams();
  const sayfaSayisi = Math.max(1, Math.ceil(liste.length / boyut));
  const istenen = Number.parseInt(sorgu.get(SAYFA_PARAMETRESI) ?? "1", 10);
  const sayfa = Math.min(Math.max(1, Number.isFinite(istenen) ? istenen : 1), sayfaSayisi);
  const git = useCallback(
    (n: number) => {
      setSorgu(
        (onceki) => {
          const y = new URLSearchParams(onceki);
          if (n <= 1) y.delete(SAYFA_PARAMETRESI);
          else y.set(SAYFA_PARAMETRESI, String(n));
          return y;
        },
        { replace: true },
      );
    },
    [setSorgu],
  );
  const bas = (sayfa - 1) * boyut;
  const gorunen = useMemo(() => liste.slice(bas, bas + boyut), [liste, bas, boyut]);
  return { sayfa, sayfaSayisi, gorunen, git, bas, toplam: liste.length, boyut };
}

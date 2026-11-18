// Liste süzgeçleri için genel seçim bileşeni (ekran testi 2 TP-7). Etiket + "Tümü" + seçenekler; değer adres
// çubuğunda tutulur (çağıran yazar). Yeni süzgeç (dil, ortam …) aynı bileşenle eklenir: seçenek listesini
// veriden türetmek için `suzgecSecenekleri` kullanılır.
import type { ReactNode } from "react";

export interface SuzgecSecenegi<T extends string = string> {
  deger: T;
  ad: ReactNode;
}

export function SuzgecSecimi<T extends string>({
  etiket,
  deger,
  secenekler,
  degistir,
  tumuAdi = "Tümü",
  testId,
}: {
  etiket: string;
  deger: T | "";
  secenekler: readonly SuzgecSecenegi<T>[];
  degistir: (d: T | "") => void;
  tumuAdi?: string;
  testId?: string;
}) {
  return (
    <label data-testid={testId}>
      {etiket}
      <select value={deger} onChange={(e) => degistir(e.target.value as T | "")}>
        <option value="">{tumuAdi}</option>
        {secenekler.map((s) => (
          <option key={s.deger} value={s.deger}>
            {s.ad}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * Kayıtlardaki değerlerden süzgeç seçenekleri (`sira`daki sırayla; sırada olmayanlar sonda). Seçili değer
 * kayıtlarda olmasa da listede kalır (adresteki seçim görünür). Değeri bilinmeyen (null) kayıt seçenek üretmez.
 */
export function suzgecSecenekleri<K, T extends string>(
  kayitlar: readonly K[],
  al: (k: K) => T | null | undefined,
  ad: (d: T) => ReactNode,
  { secili, sira = [] }: { secili?: T | ""; sira?: readonly T[] } = {},
): SuzgecSecenegi<T>[] {
  const set = new Set<T>();
  for (const k of kayitlar) {
    const d = al(k);
    if (d) set.add(d);
  }
  if (secili) set.add(secili);
  const sirali = [...sira.filter((d) => set.has(d)), ...[...set].filter((d) => !sira.includes(d))];
  return sirali.map((d) => ({ deger: d, ad: ad(d) }));
}

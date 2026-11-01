import { useKisiAdi } from "../auth";

/** Kullanıcı adını görünen adla gösterir ("analist" → "Cengizhan Gunaydin · Analist"); yalnızca gösterim. */
export function KisiAdi({ ad }: { ad: string | null | undefined }) {
  const cevir = useKisiAdi();
  const metin = cevir(ad);
  return ad && metin !== ad ? <span title={ad}>{metin}</span> : <>{metin}</>;
}

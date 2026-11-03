// Öneri düğmesi ve Öneriler sekmesinin ortak verisi (AI-ASISTAN-PLANI §17.6). Düğme ve sekme aynı
// (kullanıcı, rota, varlık) için tek isteği paylaşır: sonuç modül düzeyindeki depoda tutulur,
// bileşenler `useSyncExternalStore` ile okur. Kurallar:
// - rota/varlık değişince bir istek (aynı anahtarda uçuştaki istek yeniden kullanılır);
// - 429 gelirse son değer sessizce korunur;
// - 404 (`TP_ASISTAN_ONERI=0`, varlık yok/rolüne kapalı) ve "bu fazda yok" → düğme gizli;
// - yetenek kapısı: uç listesi okunurken gizli, liste yoksa (`null`, örnek veri derlemesi) görünür,
//   listede `GET /assistant/suggestions` yoksa gizli (istek hiç atılmaz).
import { useEffect, useState, useSyncExternalStore } from "react";
import { oneriApi, type OneriListesi, type OneriSorgusu } from "../../api/asistan";
import { ApiError, buFazdaYok, cekirdekYetenekleri, hataMesaji, ucVar } from "../../api/http";
import type { EkranBaglami } from "../../lib/ekranBaglami";

/** Zamanlamalar (testler kısaltabilir). */
export const oneriAyar = { olayGecikmeMs: 5000, yoklamaMs: 3000 };

export interface OneriDurumu {
  sonuc: OneriListesi | null;
  yukleniyor: boolean;
  /** Gösterilecek hata (429'da önceki sonuç varsa yazılmaz). */
  hata: string | null;
  /** Uç kapalı/yok ya da ekran rolüne kapalı: düğme gizli. */
  gizli: boolean;
}

const BOS: OneriDurumu = { sonuc: null, yukleniyor: false, hata: null, gizli: false };

const kayitlar = new Map<string, OneriDurumu>();
const ucuslar = new Map<string, Promise<void>>();
const dinleyiciler = new Set<() => void>();

function yaz(anahtar: string, d: Partial<OneriDurumu>): void {
  kayitlar.set(anahtar, { ...(kayitlar.get(anahtar) ?? BOS), ...d });
  dinleyiciler.forEach((fn) => fn());
}

function abone(fn: () => void): () => void {
  dinleyiciler.add(fn);
  return () => {
    dinleyiciler.delete(fn);
  };
}

/** Ekranın öneri sorgusu; portal dışı yol ve giriş ekranında null. */
export function oneriSorgusu(ekran: EkranBaglami): OneriSorgusu | null {
  if (!ekran.rota_kalibi || ekran.rota_kalibi === "/giris") return null;
  const v = ekran.varlik;
  if (!v) return { rota: ekran.rota_kalibi };
  return { rota: ekran.rota_kalibi.replace(":id", encodeURIComponent(v.id)), varlik_tur: v.tur, varlik_id: v.id };
}

/** Depo anahtarı: (kullanıcı, rota, varlık) — sunucu önbelleğiyle aynı ayrım. */
export function oneriAnahtari(kullaniciId: string, s: OneriSorgusu): string {
  return `${kullaniciId}|${s.rota}|${s.varlik_tur ?? ""}|${s.varlik_id ?? ""}`;
}

/** Önerileri okur. `zorla` değilse ve sonuç varsa istek atılmaz; uçuştaki istek paylaşılır. */
export function oneriGetir(anahtar: string, sorgu: OneriSorgusu, { zorla = false }: { zorla?: boolean } = {}): Promise<void> {
  const ucus = ucuslar.get(anahtar);
  if (ucus) return ucus;
  const onceki = kayitlar.get(anahtar);
  if (!zorla && onceki?.sonuc) return Promise.resolve();
  yaz(anahtar, { yukleniyor: true });
  const p = (async () => {
    try {
      const sonuc = await oneriApi.liste(sorgu);
      yaz(anahtar, { sonuc, yukleniyor: false, hata: null, gizli: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        // Son değer sessizce korunur; hiç değer yoksa kısa not.
        const var_ = !!kayitlar.get(anahtar)?.sonuc;
        yaz(anahtar, { yukleniyor: false, hata: var_ ? null : "Çok sık istek gönderildi; öneriler biraz sonra yenilenecek." });
      } else if (buFazdaYok(e) || (e instanceof ApiError && (e.status === 404 || e.status === 501 || e.status === 403))) {
        yaz(anahtar, { yukleniyor: false, gizli: true, sonuc: null, hata: null });
      } else {
        yaz(anahtar, { yukleniyor: false, hata: `Öneriler okunamadı: ${hataMesaji(e)}` });
      }
    } finally {
      ucuslar.delete(anahtar);
    }
  })();
  ucuslar.set(anahtar, p);
  return p;
}

export function useOneriDurumu(anahtar: string | null): OneriDurumu {
  return useSyncExternalStore(abone, () => (anahtar ? (kayitlar.get(anahtar) ?? BOS) : BOS));
}

/** Testler için. */
export function oneriDeposunuSifirla(): void {
  kayitlar.clear();
  ucuslar.clear();
  dinleyiciler.forEach((fn) => fn());
}

/**
 * Öneri ucunun yetenek kapısı: `undefined` uç listesi okunuyor (gizli), `true` görünür
 * (liste yok = örnek veri derlemesi ya da uç var), `false` uç yok (gizli, istek atılmaz).
 */
export function useOneriYetenegi(): boolean | undefined {
  const [y, setY] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    let iptal = false;
    void cekirdekYetenekleri().then((v) => {
      if (!iptal) setY(v ? ucVar(v, "GET", "/assistant/suggestions") : true);
    });
    return () => {
      iptal = true;
    };
  }, []);
  return y;
}

/**
 * Açık varlığın olay konuları (rozet yenileme): yalnız bu konular ve — varlıklı ekranda — yalnız
 * bu varlığın kimliği. Liste ekranında yalnız ilgili konu listesi; kuralı olmayan ekranda boş.
 */
export function oneriOlayKonulari(ekran: EkranBaglami): string[] {
  switch (ekran.varlik?.tur) {
    case "requirement":
      return ["requirement.updated", "finding.updated", "case.updated"];
    case "script":
      return ["script.updated", "ci.status"];
    case "run":
      return ["ci.status", "failure.updated"];
    case "failure":
      return ["failure.updated", "bug.updated"];
    case "bug_draft":
      return ["bug.updated"];
    default:
      break;
  }
  if (ekran.rota_kalibi === "/kosular" || ekran.rota_kalibi === "/kontrol-kulesi") return ["ci.status"];
  return [];
}

// "Başka ne yapabilirim?" (AI-ASISTAN-PLANI §17.5): model destekli ≤ 3 ek öneri. Yeni bir sohbette
// `kip: "oneri"` mesajı gönderilir (soru boş; sunucu sabit metni yazar), cevap SSE'den (kopukken 3 sn
// yoklamayla) gelir ve `cevap.oneriler` "AI önerisi · doğrulanmadı" kartları olarak çizilir.
// Model kapalıyken bu bileşen hiç çizilmez (çağıran gizler). Otomatik yükseltme yok (sunucu kuralı).
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { asistanApi, baglamiSigdir, bekliyor, gonderimHataMetni, mesajHataMetni, type AsistanMesaji } from "../../api/asistan";
import { useBaglantiDurumu, useOlay } from "../../api/events";
import { ApiError } from "../../api/http";
import type { EkranBaglami } from "../../lib/ekranBaglami";
import { AiOneriKarti } from "./OneriKarti";
import { oneriAyar } from "./OneriVerisi";

/**
 * "Ek öneri" sohbeti ekran/varlık başına bir kez açılır ve oturum boyunca yeniden kullanılır
 * (her tıklamada yeni sohbet geçmiş listesini doldurmasın).
 */
const ekSohbetler = new Map<string, string>();

type Durum =
  | { tur: "bos" }
  | { tur: "gonderiliyor" }
  | { tur: "bekliyor"; mesajId: string }
  | { tur: "hazir"; mesaj: AsistanMesaji }
  | { tur: "hata"; metin: string };

type KaliciDurum = Extract<Durum, { tur: "bekliyor" } | { tur: "hazir" }>;

/**
 * Bekleyen / gelen ek öneri ekran başına modül düzeyinde tutulur: sekme değişince bileşen
 * kaldırılır, geri gelince bekleme ("hazırlanıyor · Durdur") ya da sonuç buradan kurulur.
 * Bekleyen mesaj sunucuda kullanıcının tek bekleyen sorusudur (Sohbet'te yeni soru 409 alır);
 * Sohbet sekmesi `useBekleyenEkOneri` ile bunu gösterir ve durdurabilir.
 */
const ekDurumlar = new Map<string, KaliciDurum>();
const ekDinleyiciler = new Set<() => void>();
let ekSurum = 0;

function ekBildir(): void {
  ekSurum += 1;
  ekDinleyiciler.forEach((fn) => fn());
}

function ekDurumYaz(anahtar: string, d: Durum): void {
  const onceki = ekDurumlar.get(anahtar);
  if (d.tur === "bekliyor" || d.tur === "hazir") {
    if (onceki === d) return;
    ekDurumlar.set(anahtar, d);
  } else {
    if (!onceki) return;
    ekDurumlar.delete(anahtar);
  }
  ekBildir();
}

function ekAbone(fn: () => void): () => void {
  ekDinleyiciler.add(fn);
  return () => {
    ekDinleyiciler.delete(fn);
  };
}

function bekleyenEkOneri(): string | null {
  for (const d of ekDurumlar.values()) if (d.tur === "bekliyor") return d.mesajId;
  return null;
}

/** Yanıt bekleyen ek öneri mesajının kimliği (yoksa null). */
export function useBekleyenEkOneri(): string | null {
  useSyncExternalStore(ekAbone, () => ekSurum);
  return bekleyenEkOneri();
}

/** Bekleyen ek öneriyi durdurur (Sohbet sekmesinden de). */
export async function ekOneriDurdur(mesajId: string): Promise<void> {
  try {
    await asistanApi.iptal(mesajId);
  } catch {
    /* zaten bitti */
  }
  let degisti = false;
  for (const [k, d] of ekDurumlar) {
    if (d.tur === "bekliyor" && d.mesajId === mesajId) {
      ekDurumlar.delete(k);
      degisti = true;
    }
  }
  if (degisti) ekBildir();
}

/** Bekleyen ek öneri bitti (cevap ya da iptal): kayıt sonuca çevrilir / silinir. */
function ekBitti(mesaj: AsistanMesaji): void {
  for (const [k, d] of ekDurumlar) {
    if (d.tur === "bekliyor" && d.mesajId === mesaj.id) {
      if (mesaj.durum === "done") ekDurumlar.set(k, { tur: "hazir", mesaj });
      else ekDurumlar.delete(k);
      ekBildir();
    }
  }
}

/** Bileşen yokken (Sohbet sekmesi açık) bekleyen ek önerinin bitip bitmediğini okur. */
export async function ekOneriKontrol(mesajId: string): Promise<void> {
  try {
    const m = await asistanApi.mesaj(mesajId);
    if (!bekliyor(m)) ekBitti(m);
  } catch {
    /* bir sonraki olayda/turda yeniden denenir */
  }
}

/** Testler için. */
export function ekOneriSohbetleriniSifirla(): void {
  ekSohbetler.clear();
  ekDurumlar.clear();
  ekBildir();
}

export function OneriEkOneriler({ ekran, onGit }: { ekran: EkranBaglami; onGit?: () => void }) {
  const anahtar = `${ekran.rota_kalibi}|${ekran.varlik?.id ?? ""}`;
  const [durum, setDurum] = useState<Durum>(() => ekDurumlar.get(anahtar) ?? { tur: "bos" });
  const baglanti = useBaglantiDurumu();
  const bagli = useRef(true);
  useEffect(() => {
    // StrictMode effect'i kaldırıp yeniden kurar: yeniden bağlanınca bayrak geri açılır.
    bagli.current = true;
    return () => {
      bagli.current = false;
    };
  }, []);

  // Ekran değişince eski ek öneriler gösterilmez; o ekranın kayıtlı bekleme/sonucu varsa o kurulur.
  useEffect(() => setDurum(ekDurumlar.get(anahtar) ?? { tur: "bos" }), [anahtar]);
  // Kalıcı durum depoya yazılır (sekme değişip bileşen kalkınca kaybolmasın).
  const anahtarRef = useRef(anahtar);
  anahtarRef.current = anahtar;
  useEffect(() => ekDurumYaz(anahtarRef.current, durum), [durum]);
  // Başka sekmeden durdurulunca (Sohbet'teki "Durdur") bekleme kalkar.
  useSyncExternalStore(ekAbone, () => ekSurum);
  const kayitli = ekDurumlar.get(anahtar);
  useEffect(() => {
    if (durum.tur === "bekliyor" && !kayitli) setDurum({ tur: "bos" });
    // Yalnız depo değişince: yerel "bekliyor" kaydı depoya yazılmadan önceki çizimde de bos olurdu.
  }, [kayitli]);

  const bekleyenId = durum.tur === "bekliyor" ? durum.mesajId : null;

  const oku = useCallback(async (id: string) => {
    try {
      const m = await asistanApi.mesaj(id);
      if (bekliyor(m)) return;
      // Bileşen kalkmış olsa da (sekme değişti) sonuç depoya yazılır.
      ekBitti(m);
      if (!bagli.current) return;
      if (m.durum === "done") setDurum((d) => (d.tur === "bekliyor" && d.mesajId === id ? { tur: "hazir", mesaj: m } : d));
      else if (m.durum === "iptal") setDurum((d) => (d.tur === "bekliyor" && d.mesajId === id ? { tur: "bos" } : d));
      else setDurum((d) => (d.tur === "bekliyor" && d.mesajId === id ? { tur: "hata", metin: mesajHataMetni(m.hata_kodu) } : d));
    } catch {
      /* bir sonraki olayda/turda yeniden denenir */
    }
  }, []);

  useOlay(
    (o) => {
      const id = typeof o.data.mesaj_id === "string" ? o.data.mesaj_id : o.id;
      if (bekleyenId && id === bekleyenId) void oku(bekleyenId);
    },
    ["assistant.answered"],
  );

  // Yeniden bağlanınca (sekmeye dönüş) bekleyen mesaj bir kez okunur: arada gelen cevap kaçmasın.
  useEffect(() => {
    if (bekleyenId) void oku(bekleyenId);
  }, [bekleyenId, oku]);

  // SSE kopukken yoklama.
  const sseVar = baglanti === "bagli" || baglanti === "mock";
  useEffect(() => {
    if (!bekleyenId || sseVar) return;
    const z = setInterval(() => void oku(bekleyenId), oneriAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [bekleyenId, sseVar, oku]);

  const baslat = async () => {
    setDurum({ tur: "gonderiliyor" });
    const baglam: Record<string, unknown> = { rota_kalibi: ekran.rota_kalibi, ekran: ekran.ekran };
    if (ekran.varlik) baglam.varlik = { tur: ekran.varlik.tur, id: ekran.varlik.id, anahtar: ekran.varlik.anahtar ?? null };
    const gonder = (sohbetId: string) => asistanApi.soruGonder(sohbetId, { soru: "", kip: "oneri", baglam: baglamiSigdir(baglam) });
    try {
      let mesaj_id: string | null = null;
      const mevcut = ekSohbetler.get(anahtar);
      if (mevcut) {
        try {
          mesaj_id = (await gonder(mevcut)).mesaj_id;
        } catch (e) {
          // Sohbet silinmiş (geçmişten): yenisi açılır; başka hata olduğu gibi gösterilir.
          if (!(e instanceof ApiError && e.status === 404)) throw e;
          ekSohbetler.delete(anahtar);
        }
      }
      if (!mesaj_id) {
        const s = await asistanApi.sohbetOlustur("Ek öneri");
        try {
          mesaj_id = (await gonder(s.id)).mesaj_id;
        } catch (e) {
          // Soru kabul edilmedi (ör. 409 bekleyen_var): boş sohbet sahipsiz kalmasın.
          void asistanApi.sohbetSil(s.id).catch(() => undefined);
          throw e;
        }
        ekSohbetler.set(anahtar, s.id);
      }
      const bekleme: Durum = { tur: "bekliyor", mesajId: mesaj_id };
      // Gönderim sürerken sekme değiştiyse de bekleme depoya yazılır (Sohbet gösterir, durdurabilir).
      ekDurumYaz(anahtar, bekleme);
      if (!bagli.current) return;
      setDurum(bekleme);
      // Olay gönderimden önce geldiyse kaçmasın.
      void oku(mesaj_id);
    } catch (e) {
      if (bagli.current) setDurum({ tur: "hata", metin: gonderimHataMetni(e) });
    }
  };

  const durdur = async (id: string) => {
    await ekOneriDurdur(id);
    setDurum({ tur: "bos" });
  };

  if (durum.tur === "bos" || durum.tur === "gonderiliyor") {
    return (
      <div className="oneri-ek">
        <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => void baslat()} disabled={durum.tur === "gonderiliyor"}>
          Başka ne yapabilirim?
        </button>
      </div>
    );
  }
  if (durum.tur === "bekliyor") {
    return (
      <div className="oneri-ek" role="status">
        <span className="soluk kucuk">Ek öneriler hazırlanıyor…</span>{" "}
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void durdur(durum.mesajId)}>
          Durdur
        </button>
      </div>
    );
  }
  if (durum.tur === "hata") {
    return (
      <div className="oneri-ek">
        <p className="oneri-hata" role="alert">
          {durum.metin}
        </p>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setDurum({ tur: "bos" })}>
          Tamam
        </button>
      </div>
    );
  }
  const c = durum.mesaj.cevap;
  const oneriler = (c?.oneriler ?? []).slice(0, 3);
  const ilkParagraf = c?.cevap_bloklari.find((b) => b.tur === "paragraf")?.metin;
  return (
    <section className="oneri-ek" aria-label="Ek öneriler">
      {c?.ornek_veri && <span className="rozet rozet-mock">ÖRNEK VERİ</span>}
      {oneriler.length === 0 ? (
        <p className="soluk kucuk">{ilkParagraf ?? "Bu ekranda kural önerilerine ek bir iş bulunamadı."}</p>
      ) : (
        <ul className="oneri-liste">
          {oneriler.map((o, i) => (
            <li key={i}>
              <AiOneriKarti oneri={o} onGit={onGit} sohbetId={durum.mesaj.sohbet_id} />
            </li>
          ))}
        </ul>
      )}
      {/* Sonuç ekran başına saklanır (sekme değişse de kalır); yenisi yalnız istenince. */}
      <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void baslat()}>
        Başka ne yapabilirim?
      </button>
    </section>
  );
}

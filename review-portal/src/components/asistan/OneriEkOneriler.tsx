// "Başka ne yapabilirim?" (AI-ASISTAN-PLANI §17.5): model destekli ≤ 3 ek öneri. Yeni bir sohbette
// `kip: "oneri"` mesajı gönderilir (soru boş; sunucu sabit metni yazar), cevap SSE'den (kopukken 3 sn
// yoklamayla) gelir ve `cevap.oneriler` "AI önerisi · doğrulanmadı" kartları olarak çizilir.
// Model kapalıyken bu bileşen hiç çizilmez (çağıran gizler). Otomatik yükseltme yok (sunucu kuralı).
import { useCallback, useEffect, useRef, useState } from "react";
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

/** Testler için. */
export function ekOneriSohbetleriniSifirla(): void {
  ekSohbetler.clear();
}

type Durum =
  | { tur: "bos" }
  | { tur: "gonderiliyor" }
  | { tur: "bekliyor"; mesajId: string }
  | { tur: "hazir"; mesaj: AsistanMesaji }
  | { tur: "hata"; metin: string };

export function OneriEkOneriler({ ekran, onGit }: { ekran: EkranBaglami; onGit?: () => void }) {
  const [durum, setDurum] = useState<Durum>({ tur: "bos" });
  const baglanti = useBaglantiDurumu();
  const bagli = useRef(true);
  useEffect(
    () => () => {
      bagli.current = false;
    },
    [],
  );

  // Ekran değişince eski ek öneriler gösterilmez.
  useEffect(() => setDurum({ tur: "bos" }), [ekran.rota_kalibi, ekran.varlik?.id]);

  const bekleyenId = durum.tur === "bekliyor" ? durum.mesajId : null;

  const oku = useCallback(async (id: string) => {
    try {
      const m = await asistanApi.mesaj(id);
      if (!bagli.current || bekliyor(m)) return;
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

  // SSE kopukken yoklama.
  const sseVar = baglanti === "bagli" || baglanti === "mock";
  useEffect(() => {
    if (!bekleyenId || sseVar) return;
    const z = setInterval(() => void oku(bekleyenId), oneriAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [bekleyenId, sseVar, oku]);

  const baslat = async () => {
    setDurum({ tur: "gonderiliyor" });
    const anahtar = `${ekran.rota_kalibi}|${ekran.varlik?.id ?? ""}`;
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
      if (!bagli.current) return;
      setDurum({ tur: "bekliyor", mesajId: mesaj_id });
      // Olay gönderimden önce geldiyse kaçmasın.
      void oku(mesaj_id);
    } catch (e) {
      if (bagli.current) setDurum({ tur: "hata", metin: gonderimHataMetni(e) });
    }
  };

  const durdur = async (id: string) => {
    try {
      await asistanApi.iptal(id);
    } catch {
      /* zaten bitti */
    }
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
              <AiOneriKarti oneri={o} onGit={onGit} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

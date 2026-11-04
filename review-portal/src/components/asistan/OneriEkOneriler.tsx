// "Başka ne yapabilirim?" (AI-ASISTAN-PLANI §17.5): model destekli ≤ 3 ek öneri. Yeni bir sohbette
// `kip: "oneri"` mesajı gönderilir (soru boş; sunucu sabit metni yazar), cevap SSE'den (kopukken 3 sn
// yoklamayla) gelir ve `cevap.oneriler` "AI önerisi · doğrulanmadı" kartları olarak çizilir.
// Model kapalıyken bu bileşen hiç çizilmez (çağıran gizler). Otomatik yükseltme yok (sunucu kuralı).
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { asistanApi, baglamiSigdir, bekliyor, gonderimHataMetni, mesajHataMetni, type AsistanMesaji } from "../../api/asistan";
import { useBaglantiDurumu, useOlay } from "../../api/events";
import { ApiError } from "../../api/http";
import type { EkranBaglami } from "../../lib/ekranBaglami";
import { oturumDegisinceTemizle } from "../../lib/oturumTemizligi";
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

/**
 * Bekleyen ek öneri sayfa yenilemesinden sağ çıksın: sunucu onu kullanıcının bekleyen sorusu
 * sayar (Sohbet'te 409 bekleyen_var); bellekte kalsaydı kullanıcı bekleyeni göremez, durduramazdı.
 * Yalnız `bekliyor` kayıtları (anahtar → mesaj kimliği) oturum deposuna yazılır.
 */
const EK_BEKLEYEN_ANAHTARI = "tp-asistan-ek-bekleyen";
/** Depodan geri yüklenen, bu sayfa ömründe henüz durumu okunmamış bekleyenler. */
const geriYuklenenler = new Set<string>();

function ekKaydet(): void {
  try {
    const kayit: Record<string, string> = {};
    for (const [k, d] of ekDurumlar) if (d.tur === "bekliyor") kayit[k] = d.mesajId;
    if (Object.keys(kayit).length) sessionStorage.setItem(EK_BEKLEYEN_ANAHTARI, JSON.stringify(kayit));
    else sessionStorage.removeItem(EK_BEKLEYEN_ANAHTARI);
  } catch {
    /* depo kapalı: yalnız bellek */
  }
}

/** Sayfa açılışında (ve testlerde) oturum deposundaki bekleyen ek önerileri belleğe alır. */
export function ekBekleyenleriGeriYukle(): void {
  try {
    const ham = sessionStorage.getItem(EK_BEKLEYEN_ANAHTARI);
    if (!ham) return;
    const kayit = JSON.parse(ham) as unknown;
    if (!kayit || typeof kayit !== "object") return;
    for (const [k, id] of Object.entries(kayit as Record<string, unknown>)) {
      if (typeof id !== "string" || ekDurumlar.has(k)) continue;
      ekDurumlar.set(k, { tur: "bekliyor", mesajId: id });
      geriYuklenenler.add(id);
    }
  } catch {
    /* bozuk kayıt / depo kapalı */
  }
}

ekBekleyenleriGeriYukle();

function ekBildir(): void {
  ekSurum += 1;
  ekKaydet();
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
  const id = bekleyenEkOneri();
  // Yenilemeden geri yüklenen bekleyen, bu arada bitmiş olabilir (olayı kaçırıldı): bir kez okunur.
  useEffect(() => {
    if (!id || !geriYuklenenler.has(id)) return;
    geriYuklenenler.delete(id);
    void ekOneriKontrol(id);
  }, [id]);
  return id;
}

/**
 * Bekleyen ek öneriyi durdurur (Sohbet sekmesinden de). Cevap sunucuda bu arada bittiyse
 * (iptal 409 "zaten tamamlandı") mesaj okunur ve sonuç kaydedilir: gelen öneriler kaybolmasın.
 */
export async function ekOneriDurdur(mesajId: string): Promise<void> {
  try {
    await asistanApi.iptal(mesajId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      try {
        const m = await asistanApi.mesaj(mesajId);
        if (!bekliyor(m)) {
          ekBitti(m);
          return;
        }
      } catch {
        /* okunamadı: bekleme aşağıda düşer */
      }
    }
    /* diğerleri: zaten bitti / iptal edildi */
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

/** Mesaj artık okunamıyor (404: silinmiş ya da bu kullanıcının değil): bekleme kaydı düşer. */
function ekBeklemeyiDusur(mesajId: string): void {
  let degisti = false;
  for (const [k, d] of ekDurumlar) {
    if (d.tur === "bekliyor" && d.mesajId === mesajId) {
      ekDurumlar.delete(k);
      degisti = true;
    }
  }
  if (degisti) ekBildir();
}

/** Bileşen yokken (Sohbet sekmesi açık) bekleyen ek önerinin bitip bitmediğini okur. */
export async function ekOneriKontrol(mesajId: string): Promise<void> {
  try {
    const m = await asistanApi.mesaj(mesajId);
    if (!bekliyor(m)) ekBitti(m);
  } catch (e) {
    // 404 kalıcıdır: kayıt kalırsa Sohbet "Ek öneriler hazırlanıyor" diye kilitli kalır.
    if (e instanceof ApiError && e.status === 404) ekBeklemeyiDusur(mesajId);
    /* diğerleri: bir sonraki olayda/turda yeniden denenir */
  }
}

/**
 * Ters yön kilidi: Sohbet sekmesinde yanıt bekleyen kullanıcı sorusu (sunucu ek öneriye de 409
 * bekleyen_var verir). Sohbet sekmesi kimliği yazar; sekmeler arasında yalnız seçili olan çizildiği
 * için Öneriler açıkken kaydı bu bileşen cevap olayı / okuma ile kendisi düşürür.
 */
let sohbetBekleyen: string | null = null;

/** Sohbet sekmesi: bu sohbette yanıt bekleyen kullanıcı sorusunun kimliği (yoksa null). */
export function sohbetBekleyeniYaz(id: string | null): void {
  if (sohbetBekleyen === id) return;
  sohbetBekleyen = id;
  ekBildir();
}

function useSohbetBekleyen(): string | null {
  useSyncExternalStore(ekAbone, () => ekSurum);
  return sohbetBekleyen;
}

/** Sohbet'teki bekleyen soru bitti mi: bittiyse (ya da artık okunamıyorsa) kilit kalkar. */
async function sohbetBekleyeniKontrol(id: string): Promise<void> {
  try {
    const m = await asistanApi.mesaj(id);
    if (bekliyor(m)) return;
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 404)) return;
  }
  if (sohbetBekleyen === id) sohbetBekleyeniYaz(null);
}

/**
 * Çıkışta / kullanıcı değişince ve testlerde. Ek öneri sohbetleri ve sonuçları kullanıcıya
 * aittir (anahtar yalnız ekran/varlık): önceki kullanıcının bekleyen ek önerisi sonrakinin
 * Sohbet'ini kilitlemesin, sonuçları ona gösterilmesin (§16 madde 1).
 */
export function ekOneriSohbetleriniSifirla(): void {
  ekSohbetler.clear();
  ekDurumlar.clear();
  geriYuklenenler.clear();
  sohbetBekleyen = null;
  ekBildir();
}

oturumDegisinceTemizle(ekOneriSohbetleriniSifirla);

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
    } catch (e) {
      // 404 kalıcıdır (mesaj silinmiş / bu kullanıcının değil): bekleme bırakılır.
      if (e instanceof ApiError && e.status === 404) {
        ekBeklemeyiDusur(id);
        if (bagli.current) setDurum((d) => (d.tur === "bekliyor" && d.mesajId === id ? { tur: "bos" } : d));
      }
      /* diğerleri: bir sonraki olayda/turda yeniden denenir */
    }
  }, []);

  const sohbetteBekleyen = useSohbetBekleyen();

  useOlay(
    (o) => {
      const id = typeof o.data.mesaj_id === "string" ? o.data.mesaj_id : o.id;
      if (bekleyenId && id === bekleyenId) void oku(bekleyenId);
      if (sohbetteBekleyen && id === sohbetteBekleyen) void sohbetBekleyeniKontrol(sohbetteBekleyen);
    },
    ["assistant.answered"],
  );

  // Sekmeye dönüşte ve SSE yeniden bağlanınca (kopuk → bağlı) bekleyen mesaj bir kez okunur:
  // kopukluk yoklama aralığından kısa sürdüyse arada gelen cevap olayı kaçmış olabilir (tekrar
  // oynatma yok). Bağlantı koptuğunda da bir okuma olur; zararsızdır.
  const sseVar = baglanti === "bagli" || baglanti === "mock";
  useEffect(() => {
    if (bekleyenId) void oku(bekleyenId);
  }, [bekleyenId, sseVar, oku]);

  // SSE kopukken yoklama.
  useEffect(() => {
    if (!bekleyenId || sseVar) return;
    const z = setInterval(() => void oku(bekleyenId), oneriAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [bekleyenId, sseVar, oku]);

  // Sohbet'teki bekleyen soru: sekme değişirken olay kaçmış olabilir; bir kez ve kopukken yoklamayla okunur.
  useEffect(() => {
    if (!sohbetteBekleyen) return;
    void sohbetBekleyeniKontrol(sohbetteBekleyen);
    if (sseVar) return;
    const z = setInterval(() => void sohbetBekleyeniKontrol(sohbetteBekleyen), oneriAyar.yoklamaMs);
    return () => clearInterval(z);
  }, [sohbetteBekleyen, sseVar]);

  /** Sohbet'te soru beklerken yeni ek öneri sunucuda 409 alır: düğme pasif, neden yanında yazılı. */
  const baslatDugmesi = (gonderiliyor: boolean, sinif = "dugme-ikincil") => (
    <>
      <button
        type="button"
        className={`dugme ${sinif} dugme-kucuk`}
        onClick={() => void baslat()}
        disabled={gonderiliyor || !!sohbetteBekleyen}
        aria-describedby={sohbetteBekleyen ? "oneri-ek-kilit" : undefined}
      >
        Başka ne yapabilirim?
      </button>
      {sohbetteBekleyen && (
        <p className="soluk kucuk" id="oneri-ek-kilit" role="status">
          Sohbet'teki soru yanıt bekliyor; cevap gelince kullanılabilir.
        </p>
      )}
    </>
  );

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
    // İptal yetişmediyse (cevap bitmişti) kayıt "hazir"a çevrilmiştir: sonuç gösterilir.
    if (!bagli.current) return;
    const k = ekDurumlar.get(anahtarRef.current);
    setDurum((d) => (d.tur === "bekliyor" && d.mesajId === id ? (k?.tur === "hazir" && k.mesaj.id === id ? k : { tur: "bos" }) : d));
  };

  if (durum.tur === "bos" || durum.tur === "gonderiliyor") {
    return (
      <div className="oneri-ek">{baslatDugmesi(durum.tur === "gonderiliyor")}</div>
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
      {baslatDugmesi(false, "dugme-hayalet")}
    </section>
  );
}

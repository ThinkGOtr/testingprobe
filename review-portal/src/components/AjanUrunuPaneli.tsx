// "Ürün AI ajanı" (011 F6, K10): gereksinimi Agent Probe'daki bir ajan ürününe bağlama ve ajan
// testi talebinin durumu/sonucu. Bağlı gereksinimde case üretim akışı çalışmaz; test Agent
// Probe'da koşar ve Testing Probe sonuca göre süreci sürdürür. Agent Probe bu sürümde simüle
// edilir: her yerde "Simülasyon" açıkça yazılır.
import { useEffect, useId, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { AjanTestiGorunumu, AjanTestiTalebi } from "../api/types";
import { useVeri, type VeriDurumu } from "../hooks";
import { AJAN_TESTI_BITMEDI, AJAN_TESTI_DURUMU, SIMULASYON_ACIKLAMASI } from "../lib/ajanProbe";
import { tarih } from "../lib/format";
import { useIzin } from "../auth";
import { useBildirim } from "./Bildirim";
import { Cip, DisBaglanti, HataKutusu, IslemDugmesi, Kart, Uyari } from "./ui";

/** Talep bitmemişken yeniden sorgulama aralığı (GET sunucuda durumu yeniler). */
export const AJAN_SORGU_MS = 3000;

/**
 * Gereksinimin ajan ürünü görünümü. Core bu ucu sunmuyorsa (eski sürüm: 404/501) `null` döner ve
 * panel hiç çizilmez; diğer hatalar panelde gösterilir. Talep sürerken sonuç D4'ün
 * `POST …/agent-test/refresh` ucuyla işletilip okunur (uç yoksa istemci eski GET'e düşer).
 */
export function useAjanTesti(id: string): VeriDurumu<AjanTestiGorunumu | null> {
  const v = useVeri(
    () =>
      api.ajanTesti(id).catch((e: unknown) => {
        if (e instanceof ApiError && (e.status === 404 || e.status === 501)) return null;
        throw e;
      }),
    [id],
  );
  // 012: ajan testini başlatan/işleten Testçi (`agent_test.run`).
  const isletir = useIzin("agent_test.run");
  // D4: GET yalnız okur; `yenilenebilir` true iken `agent_test.run` sahibi refresh POST'u ile sonucu
  // işletir. Alan yoksa (eski core) talep bitmeyene kadar yoklanır. Diğer roller yalnız GET ile okur.
  const veri = v.veri;
  const aktif = !!veri && (typeof veri.yenilenebilir === "boolean" ? veri.yenilenebilir : !!veri.talep && AJAN_TESTI_BITMEDI.has(veri.talep.durum));
  const { setVeri } = v;
  useEffect(() => {
    if (!aktif) return;
    let iptal = false;
    const t = window.setTimeout(() => {
      (isletir ? api.ajanTestiYenile(id) : api.ajanTesti(id))
        .then((g) => {
          if (!iptal) setVeri(g);
        })
        .catch(() => undefined); // geçici hata: bir sonraki çizimde yeniden denenmez; sayfa yenilemesi okur
    }, AJAN_SORGU_MS);
    return () => {
      iptal = true;
      window.clearTimeout(t);
    };
  }, [aktif, isletir, id, setVeri, v.veri]);
  return v;
}

function SimulasyonRozeti() {
  return (
    <Cip ton="uyari" title={SIMULASYON_ACIKLAMASI}>
      Simülasyon
    </Cip>
  );
}

function TalepSonucu({ t }: { t: AjanTestiTalebi }) {
  const d = AJAN_TESTI_DURUMU[t.durum] ?? { etiket: t.durum, ton: "notr" as const };
  const ayrintilar = t.sonuc.ayrintilar ?? [];
  const kalanlar = ayrintilar.filter((a) => a.sonuc === "failed");
  return (
    <div data-testid="ajan-talep">
      <p className="satir-ogeler">
        <span className="mono">{t.talep_no}</span>
        <Cip ton={d.ton}>{d.etiket}</Cip>
        {t.simulasyon && <SimulasyonRozeti />}
        <span className="soluk kucuk">Güncelleme: {tarih(t.guncelleme)}</span>
        {t.url && <DisBaglanti href={t.url}>Agent Probe'da aç{t.simulasyon ? " (temsili)" : ""}</DisBaglanti>}
      </p>
      {t.ozet && <p>{t.ozet}</p>}
      {t.sonuc.toplam !== undefined && (
        <p className="kucuk" data-testid="ajan-sayilar">
          Toplam {t.sonuc.toplam} senaryo · geçen {t.sonuc.gecen ?? 0} · kalan {t.sonuc.kalan ?? 0}
        </p>
      )}
      {t.surec === "simule" ? (
        <Uyari ton="bilgi" baslik="Simülasyon sonucu — gereksinim tamamlanmadı">
          {t.surec_notu ?? "Sonuç simülatörden geldi; gerçek Agent Probe koşusu olmadığı için gereksinim tamamlandı olarak işaretlenmez."}
        </Uyari>
      ) : (
        t.surec_notu && (
          <Uyari ton={t.surec === "tamamlandi" ? "basari" : t.surec === "bulgu" ? "uyari" : t.surec ? "hata" : "bilgi"} baslik="Testing Probe süreci">
            {t.surec_notu}
          </Uyari>
        )
      )}
      {t.durum === "failed" && kalanlar.length > 0 && (
        <div data-testid="ajan-bulgular">
          <strong>Bulgular (kalan senaryolar)</strong>
          <ul>
            {kalanlar.map((a) => (
              <li key={a.senaryo}>
                <strong>{a.senaryo}</strong> <Cip ton="hata">{a.kategori}</Cip> — {a.aciklama}
              </li>
            ))}
          </ul>
        </div>
      )}
      {ayrintilar.length > 0 && (
        <details>
          <summary>Tüm senaryolar ({ayrintilar.length})</summary>
          <ul>
            {ayrintilar.map((a) => (
              <li key={a.senaryo}>
                <Cip ton={a.sonuc === "passed" ? "basari" : "hata"}>{a.sonuc === "passed" ? "Geçti" : "Kaldı"}</Cip> {a.senaryo}{" "}
                <span className="soluk">({a.kategori})</span> — {a.aciklama}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function AjanUrunuPaneli({
  id,
  bolumId,
  ajan,
  caseVar,
  degisti,
}: {
  id: string;
  /** Bölüm gezgininin çapası (kart kimliği). */
  bolumId?: string;
  ajan: VeriDurumu<AjanTestiGorunumu | null>;
  /** Gereksinimin case'i var: bağlama sunucuda reddedilir, düğme açıklamalı pasif. */
  caseVar: boolean;
  degisti?: () => void;
}) {
  const bildir = useBildirim();
  const [secim, setSecim] = useState("");
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<unknown>(null);
  // Bağlı değilken bölüm tek satırlık özet (UX-11): bağlama formu yalnız "Bağla" ile açılır.
  const [acik, setAcik] = useState(false);
  const govdeId = useId();
  const g = ajan.veri;
  const bagli = !!g?.urun_kodu;
  // Ürün listesi yalnız bağlama formu açıkken okunur.
  const urunler = useVeri(() => (g && !bagli && acik ? api.ajanUrunleri() : Promise.resolve(null)), [!!g, bagli, acik]);

  if (ajan.veri === null) return null; // core ucu yok (eski sürüm)
  if (ajan.hata && !g) return <HataKutusu hata={ajan.hata} kaynak={ajan.hataNesnesi} yenile={() => void ajan.yenile()} />;
  if (!g) return null;

  async function calistir(fn: () => Promise<AjanTestiGorunumu>, basari: string) {
    setCalisiyor(true);
    setHata(null);
    try {
      ajan.setVeri(await fn());
      bildir(basari);
      degisti?.();
    } catch (e) {
      setHata(e);
    } finally {
      setCalisiyor(false);
    }
  }

  const liste = urunler.veri?.urunler ?? [];
  const aktif = !!g.talep && AJAN_TESTI_BITMEDI.has(g.talep.durum);
  if (!bagli) {
    return (
      <Kart
        id={bolumId}
        className="ajan-daraltilmis"
        baslik="Ürün AI ajanı"
        eylemler={
          <span className="satir-ogeler">
            <span data-testid="ajan-ozet">bağlı değil —</span>
            {g.simulasyon && <SimulasyonRozeti />}
            <button
              type="button"
              className="dugme dugme-ikincil dugme-kucuk"
              aria-expanded={acik}
              aria-controls={acik ? govdeId : undefined}
              onClick={() => setAcik((x) => !x)}
            >
              Bağla
            </button>
          </span>
        }
      >
        {hata !== null && <HataKutusu hata={hata instanceof Error ? hata.message : String(hata)} kaynak={hata} />}
        {acik && (
          <div id={govdeId}>
            <p className="soluk kucuk">
              Test edilen ürün bir AI ajanıysa gereksinimi Agent Probe'daki ürünüyle bağlayın: test Agent Probe'da koşar, case üretilmez.
            </p>
            <div className="alan alan-satir">
              <label htmlFor={`${govdeId}-urun`}>Ajan ürünü</label>
              <select id={`${govdeId}-urun`} value={secim} onChange={(e) => setSecim(e.target.value)}>
                <option value="">Ürün seçin…</option>
                {liste.map((u) => (
                  <option key={u.kod} value={u.kod}>
                    {u.ad}
                  </option>
                ))}
              </select>
              <IslemDugmesi
                izin="requirement.review"
                tur="ikincil"
                disabled={!secim || caseVar}
                title={caseVar ? "Bu gereksinim için case'ler üretilmiş; ajan ürününe bağlanamaz." : !secim ? "Önce bir ürün seçin" : undefined}
                calisiyor={calisiyor}
                onClick={() => void calistir(() => api.ajanUrunuBagla(id, secim), "Gereksinim ajan ürününe bağlandı.")}
              >
                Ürün AI ajanı olarak bağla
              </IslemDugmesi>
            </div>
          </div>
        )}
      </Kart>
    );
  }
  return (
    <Kart
      id={bolumId}
      baslik="Ürün AI ajanı"
      eylemler={
        <span className="satir-ogeler">
          {g.simulasyon && <SimulasyonRozeti />}
          {bagli && (
            <IslemDugmesi
              izin="agent_test.run"
              disabled={!g.baslatilabilir}
              title={g.baslatilabilir ? "Test Agent Probe'da koşar; sonuç geldiğinde Testing Probe süreci sürdürür." : g.engel ?? undefined}
              calisiyor={calisiyor}
              onClick={() => void calistir(() => api.ajanTestiBaslat(id), "Agent Probe'da test talebi açıldı.")}
            >
              Agent Probe'da test başlat
            </IslemDugmesi>
          )}
        </span>
      }
    >
      {hata !== null && <HataKutusu hata={hata instanceof Error ? hata.message : String(hata)} kaynak={hata} />}
      {bagli ? (
        <>
          <p className="satir-ogeler">
            <span>
              Bağlı ürün: <strong>{g.urun?.ad ?? g.urun_kodu}</strong> <span className="mono soluk">{g.urun_kodu}</span>
            </span>
            {g.baglayan && (
              <span className="soluk kucuk">
                {g.baglayan} · {tarih(g.baglanma)}
              </span>
            )}
            <IslemDugmesi
              izin="requirement.review"
              tur="ikincil"
              kucuk
              disabled={aktif || calisiyor}
              title={aktif ? "Süren ajan testi varken bağlantı kaldırılamaz." : undefined}
              onClick={() => void calistir(() => api.ajanUrunuBagla(id, null), "Ajan ürünü bağlantısı kaldırıldı.")}
            >
              Bağlantıyı kaldır
            </IslemDugmesi>
          </p>
          <p className="soluk kucuk">
            Bu gereksinimde case üretimi, case review ve yayın yapılmaz; test Agent Probe'da koşar ve Testing Probe sonuca göre ilerler.
          </p>
          {g.talep ? <TalepSonucu t={g.talep} /> : <p className="soluk">Henüz ajan testi talebi yok.</p>}
          {g.gecmis.length > 0 && (
            <details>
              <summary>Önceki talepler ({g.gecmis.length})</summary>
              <ul>
                {g.gecmis.map((t) => (
                  <li key={t.talep_no}>
                    <span className="mono">{t.talep_no}</span> {AJAN_TESTI_DURUMU[t.durum]?.etiket ?? t.durum} · {tarih(t.olusturma)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      ) : null}
    </Kart>
  );
}

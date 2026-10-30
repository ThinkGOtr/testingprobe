import { useCallback, useEffect, useState } from "react";

type Durum = "yukleniyor" | "ok" | "degraded" | "unreachable";

interface HealthBody {
  service?: string;
  status?: string;
  version?: string;
  checks?: Record<string, string>;
}

interface Sonuc {
  durum: Durum;
  body?: HealthBody;
  httpStatus?: number;
  zaman?: Date;
}

const ETIKET: Record<Durum, string> = {
  yukleniyor: "Kontrol ediliyor…",
  ok: "Çalışıyor",
  degraded: "Kısmi arıza",
  unreachable: "Erişilemiyor",
};

async function saglikSorgula(): Promise<Sonuc> {
  const zaman = new Date();
  try {
    const res = await fetch("/api/health", {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    let body: HealthBody | undefined;
    try {
      body = (await res.json()) as HealthBody;
    } catch {
      body = undefined;
    }
    if (res.ok && body?.status === "ok") {
      return { durum: "ok", body, httpStatus: res.status, zaman };
    }
    // core-api cevap verdi ama sağlıksız (contract: 503 + status "degraded")
    if (body?.status) {
      return { durum: "degraded", body, httpStatus: res.status, zaman };
    }
    // 502/504 vb. — proxy core-api'ye ulaşamadı
    return { durum: "unreachable", httpStatus: res.status, zaman };
  } catch {
    return { durum: "unreachable", zaman };
  }
}

export default function App() {
  const [sonuc, setSonuc] = useState<Sonuc>({ durum: "yukleniyor" });

  const yenile = useCallback(async () => {
    setSonuc((s) => ({ ...s, durum: "yukleniyor" }));
    setSonuc(await saglikSorgula());
  }, []);

  useEffect(() => {
    void yenile();
    const id = window.setInterval(() => void yenile(), 15000);
    return () => window.clearInterval(id);
  }, [yenile]);

  const checks = sonuc.body?.checks ?? {};

  return (
    <div className="sayfa">
      <header className="ust">
        <h1>AI Testing Probe</h1>
        <p className="alt-baslik">Kontrol Kulesi</p>
      </header>

      <main>
        <section className="kart" aria-labelledby="servis-durumu">
          <div className="kart-baslik">
            <h2 id="servis-durumu">Servis durumu</h2>
            <button type="button" onClick={() => void yenile()} disabled={sonuc.durum === "yukleniyor"}>
              Yenile
            </button>
          </div>

          <div className="satir">
            <span className="servis-adi">core-api</span>
            <span className={`rozet rozet-${sonuc.durum}`} role="status">
              {ETIKET[sonuc.durum]}
            </span>
          </div>

          <dl className="detay">
            {sonuc.body?.version && (
              <>
                <dt>Sürüm</dt>
                <dd>{sonuc.body.version}</dd>
              </>
            )}
            {Object.entries(checks).map(([ad, deger]) => (
              <div key={ad} className="detay-satir">
                <dt>Kontrol: {ad}</dt>
                <dd>{deger}</dd>
              </div>
            ))}
            {sonuc.httpStatus !== undefined && sonuc.durum !== "ok" && (
              <>
                <dt>HTTP</dt>
                <dd>{sonuc.httpStatus}</dd>
              </>
            )}
            {sonuc.zaman && (
              <>
                <dt>Son kontrol</dt>
                <dd>{sonuc.zaman.toLocaleTimeString("tr-TR")}</dd>
              </>
            )}
          </dl>
        </section>
      </main>
    </div>
  );
}

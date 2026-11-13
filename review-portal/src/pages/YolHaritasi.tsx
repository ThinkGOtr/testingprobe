// Demo yol haritası (sunucunun açılış ekranı): TEKNIK-TASARIM §2'nin 14 adımı + locator yolu,
// demo story'si (TPD-1) için gerçek API durumundan türetilmiş canlı kontrol listesi. Her adım
// ilgili ekrana bağlanır; model kipi (REPLAY/strict) ve prompt değerlendirme durumu üstte yazılır.
// Okunamayan kaynak "tamam" sayılmaz: adım "bekliyor" kalır ve okunamayan uç açıkça listelenir.
import { useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { buFazdaYok, hataMesaji, ortamAdlariniGizle } from "../api/http";
import type { BugTaslagi, DemoDurumu, GereksinimDetay, HataAnalizi, KontrolKulesi, Kosu, Script, TestCase } from "../api/types";
import { Cip, HataKutusu, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useVeri } from "../hooks";
import type { Ton } from "../lib/etiketler";
import { saat } from "../lib/format";
import {
  DEMO_STORY,
  degerlendirmeOzeti,
  demoAdimlari,
  ilerleme,
  locatorAdimlari,
  modOzeti,
  type AdimHali,
  type YolAdimi,
  type YolGirdisi,
} from "../lib/yolHaritasi";

const YENILEME_MS = 20_000;

const HAL: Record<AdimHali, { etiket: string; ton: Ton; isaret: string }> = {
  tamam: { etiket: "tamam", ton: "notr", isaret: "✓" },
  suruyor: { etiket: "sürüyor", ton: "bilgi", isaret: "…" },
  bekliyor: { etiket: "bekliyor", ton: "notr", isaret: "○" },
  engel: { etiket: "engel", ton: "hata", isaret: "!" },
  yedek: { etiket: "yerel yedek", ton: "uyari", isaret: "≈" },
};

const TUR: Record<YolAdimi["tur"], string> = { sistem: "Sistem", ai: "AI", insan: "İnsan kapısı", ai_insan: "AI + insan" };

interface Yuklenen extends YolGirdisi {
  okunamayan: string[];
  zaman: string;
}

async function yukle(): Promise<Yuklenen> {
  const okunamayan: string[] = [];
  async function oku<T>(ad: string, fn: () => Promise<T>, bos: T): Promise<T> {
    try {
      return await fn();
    } catch (e) {
      okunamayan.push(buFazdaYok(e) ? `${ad} (bu fazda yok)` : `${ad}: ${hataMesaji(e)}`);
      return bos;
    }
  }
  const gereksinimler = await oku("Gereksinimler", () => api.gereksinimler(), []);
  const ozet = gereksinimler.find((g) => g.jira_key === DEMO_STORY) ?? null;
  const [gereksinim, caseler, scriptler, kosular, hatalar, bugTaslaklari, kule, demo] = await Promise.all([
    ozet ? oku<GereksinimDetay | null>(DEMO_STORY, () => api.gereksinim(ozet.id), null) : Promise.resolve(null),
    ozet ? oku<TestCase[]>("Case'ler", () => api.caseler(ozet.id), []) : Promise.resolve([] as TestCase[]),
    oku<Script[]>("Kod üretimi", () => api.scriptler(), []),
    oku<Kosu[]>("Koşular", () => api.kosular(), []),
    oku<HataAnalizi[]>("Triage", () => api.hatalar(), []),
    oku<BugTaslagi[]>("Bug taslakları", () => api.bugTaslaklari(), []),
    oku<KontrolKulesi | null>("Kontrol Kulesi", () => api.kontrolKulesi(), null),
    oku<DemoDurumu | null>("Demo durumu", () => api.demoDurumu(), null),
  ]);
  return { gereksinim, caseler, scriptler, kosular, hatalar, bugTaslaklari, kule, demo, okunamayan, zaman: new Date().toISOString() };
}

function AdimSatiri({ a }: { a: YolAdimi }) {
  const h = HAL[a.hal];
  return (
    <li className={`yh-adim yh-${a.hal}`} data-testid={`yh-adim-${a.no}`} data-hal={a.hal} data-tur={a.tur}>
      <span className="yh-no" aria-hidden="true">
        {a.hal === "tamam" ? h.isaret : a.no}
      </span>
      <div>
        <div className="yh-baslik">
          <span>
            <span className="gorunmez">Adım {a.no}: </span>
            {a.ad}
          </span>
          <span className="yh-tur">{TUR[a.tur]}</span>
          <Cip ton={h.ton}>{h.etiket}</Cip>
          <ReplayRozeti mode={a.mode} />
        </div>
        <p className="yh-kanit">{ortamAdlariniGizle(a.kanit)}</p>
        {a.simulator && (
          <p className="yh-simulator kucuk" data-testid={`yh-simulator-${a.no}`}>
            <Cip ton="notr">Simülatör</Cip> {a.simulator.replace(/^simülatör: /, "")}
          </p>
        )}
        {a.ipucu && <p className="yh-ipucu">↳ {ortamAdlariniGizle(a.ipucu)}</p>}
      </div>
      {a.baglanti ? (
        <Link className="yh-baglanti" to={a.baglanti.yol}>
          {a.baglanti.etiket} →
        </Link>
      ) : (
        <span />
      )}
    </li>
  );
}

function DurumSeridi({ v }: { v: Yuklenen }) {
  const m = modOzeti(v);
  const d = degerlendirmeOzeti(v);
  const modTon: Ton = m.mod === "replay" ? "vurgu" : m.mod === "live" ? "basari" : m.mod === "karisik" ? "uyari" : "notr";
  return (
    <div className="yh-durum-izgara">
      <Kart baslik="Model kipi">
        <p className="satir-ogeler" data-testid="yh-mod">
          {m.mod === "replay" ? <span className="rozet rozet-replay">REPLAY</span> : <Cip ton={modTon}>{m.mod === "live" ? "canlı" : m.mod === "karisik" ? "karışık" : "bilinmiyor"}</Cip>}
          <span>{m.metin}</span>
        </p>
        <p className="soluk kucuk">
          {m.kaynak === "cekirdek" ? "Çekirdek bildirdi (/demo/status)." : m.kaynak === "gozlem" ? "Çekirdek kipi bildirmiyor; ekrandaki çıktılardan gözlendi." : "Henüz gözlenecek çıktı yok."}
        </p>
        {m.replay_miss > 0 && (
          <p className="kucuk">
            <span className="rozet rozet-replay-miss">REPLAY-MISS</span> {m.replay_miss} çıktı kayıtta yok; canlı model gerekir.
          </p>
        )}
      </Kart>
      <Kart baslik="REPLAY strict (prova)">
        <p className="satir-ogeler" data-testid="yh-strict">
          {m.strict === true ? (
            <Cip ton="basari">açık</Cip>
          ) : m.strict === false ? (
            <Cip ton="uyari">kapalı</Cip>
          ) : (
            <Cip ton="notr">bilinmiyor</Cip>
          )}
          <span className="kucuk">
            {m.strict === true
              ? "Girdisi beyanla eşleşmeyen golden'a düşülmez; sapma REPLAY-MISS olur."
              : m.strict === false
                ? "Prova için REPLAY strict kipinin açılması önerilir (yönetici ayarı)."
                : "Çekirdek bildirmiyor. Provada REPLAY strict kipi açık olmalı (yönetici ayarı); sunum öncesi demo kontrolü koşulur."}
          </span>
        </p>
      </Kart>
      <Kart baslik="Prompt değerlendirmesi">
        <p className="satir-ogeler" data-testid="yh-degerlendirme">
          <Cip ton={d.kaynak === "yok" ? "notr" : d.bekleyen > 0 ? "uyari" : "basari"}>{d.kaynak === "yok" ? "bilinmiyor" : d.bekleyen > 0 ? "bekliyor" : "tamam"}</Cip>
          <span className="kucuk">{d.metin}</span>
        </p>
        {d.paketler.length > 0 && (
          <details className="kucuk">
            <summary>Paketler</summary>
            <ul className="duz-liste">
              {d.paketler.map((p) => (
                <li key={p.paket}>
                  <span className="mono">{p.paket}</span>
                  {p.surum !== null && <span className="soluk"> v{p.surum}</span>} — {p.etiket ?? p.durum}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Kart>
    </div>
  );
}

export function YolHaritasi() {
  const v = useVeri(yukle, []);
  const sessiz = useGeciktirilmis(() => void v.yenile(true), 600);
  useOlay(sessiz, [
    "requirement.updated",
    "finding.updated",
    "case.generated",
    "case.updated",
    "publish.completed",
    "script.updated",
    "ci.status",
    "failure.classified",
    "bug.updated",
    "bug.published",
    "demo.updated",
  ]);
  const yenile = useCallback(() => void v.yenile(true), [v]);
  useEffect(() => {
    const t = setInterval(yenile, YENILEME_MS);
    return () => clearInterval(t);
  }, [yenile]);

  if (v.yukleniyor && !v.veri) return <Yukleniyor metin="Demo durumu okunuyor…" />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />;
  const y = v.veri;
  if (!y) return null;
  const adimlar = demoAdimlari(y);
  const loc = locatorAdimlari(y);
  const il = ilerleme(adimlar);
  const li = ilerleme(loc);

  return (
    <>
      <SayfaBasligi
        baslik="Demo yol haritası"
        aciklama={
          <>
            Ana senaryo <span className="mono">f2-kod-hatasi</span>: {DEMO_STORY} story'si 14 adımda ve locator kırılma yolu. Her adım gerçek
            durumdan okunur; kanıt yoksa “bekliyor” yazar.
          </>
        }
        eylemler={
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={yenile} disabled={v.yukleniyor}>
            Yenile
          </button>
        }
      />
      {y.okunamayan.length > 0 && (
        <Uyari ton="uyari" baslik="Bazı kaynaklar okunamadı (ilgili adımlar 'bekliyor' gösterilir)">
          <ul className="duz-liste kucuk">
            {y.okunamayan.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </Uyari>
      )}
      {!y.gereksinim && (
        <Uyari ton="bilgi" baslik={`${DEMO_STORY} henüz yok`}>
          Analist Gereksinimler ekranında “Jira'dan çek” ile story'leri çeker. Sunum öncesi: <span className="mono">make reset</span> → Demo-A →{" "}
          <span className="mono">make demo-check</span> (çıkış 0).
        </Uyari>
      )}

      <DurumSeridi v={y} />

      <Kart
        baslik={`14 adım · ${DEMO_STORY}`}
        eylemler={
          <span className="yh-ozet kucuk" data-testid="yh-ilerleme">
            <strong>
              {il.tamam}/{il.toplam}
            </strong>{" "}
            tamam{il.yedek ? ` (${il.yedek} yerel yedek)` : ""} · güncellendi {saat(y.zaman)}
          </span>
        }
      >
        {il.sonraki && (
          <p className="kucuk yh-sonraki" data-testid="yh-sonraki">
            <strong>Sıradaki:</strong> {il.sonraki.no}. {il.sonraki.ad}
            {il.sonraki.ipucu ? ` — ${il.sonraki.ipucu}` : ""}
          </p>
        )}
        <ol className="yh-adimlar" aria-label="14 adımlı demo akışı">
          {adimlar.map((a) => (
            <AdimSatiri key={a.no} a={a} />
          ))}
        </ol>
      </Kart>

      <Kart
        baslik="Test bakımı yolu"
        eylemler={
          <span className="kucuk" data-testid="yh-locator-ilerleme">
            <strong>
              {li.tamam}/{li.toplam}
            </strong>{" "}
            tamam
          </span>
        }
      >
        <p className="soluk kucuk">
          “Sepete ekle” <span className="mono">data-testid</span> <span className="mono">add-to-cart → cart-add</span>: triage “test bakımı /
          locator” der, onarım PR'ı yalnızca testId değerini değiştirir, mühendis onaylar, CI yeşile döner.
        </p>
        <ol className="yh-adimlar" aria-label="Test bakımı yolu">
          {loc.map((a) => (
            <AdimSatiri key={a.no} a={a} />
          ))}
        </ol>
      </Kart>
    </>
  );
}

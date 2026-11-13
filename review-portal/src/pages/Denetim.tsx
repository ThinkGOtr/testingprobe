import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { hataMesaji, ortamAdlariniGizle } from "../api/http";
import type { DenetimOlayi } from "../api/types";
import { BosDurum, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useIzin, useKisiAdi } from "../auth";
import { useVeri } from "../hooks";
import { kisaHash, tarih } from "../lib/format";

/** Özet sütununda gösterilen en çok karakter (tamamı ipucunda ve satır ayrıntısında). */
export const OZET_KISA_SINIR = 140;

function degerMetni(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.length <= 3 && v.every((x) => typeof x !== "object") ? v.join(", ") : `${v.length} öğe`;
  return `{${Object.keys(v as object).length} alan}`;
}

/**
 * Denetim özeti (core'da JSON nesne) okunur metne: `{"sonuc":{"TPD-1":"yeni"},"baz":2}` →
 * "sonuc: {1 alan} · baz: 2". `tam`: biçimli tam metin (ipucu ve ayrıntı). JSON değilse metin aynen.
 */
export function okunurOzet(ozet: string): { kisa: string; tam: string } {
  const temiz = ortamAdlariniGizle(ozet);
  let nesne: unknown = null;
  if (/^\s*[{[]/.test(ozet)) {
    try {
      nesne = JSON.parse(ozet);
    } catch {
      nesne = null;
    }
  }
  if (nesne && typeof nesne === "object" && !Array.isArray(nesne)) {
    const kisa = Object.entries(nesne as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${degerMetni(v)}`)
      .join(" · ");
    const tam = ortamAdlariniGizle(JSON.stringify(nesne, null, 2));
    return { kisa: kisalt(ortamAdlariniGizle(kisa)), tam };
  }
  return { kisa: kisalt(temiz), tam: temiz };
}

function kisalt(m: string): string {
  return m.length > OZET_KISA_SINIR ? `${m.slice(0, OZET_KISA_SINIR - 1)}…` : m;
}

function OzetHucresi({ ozet }: { ozet: string }) {
  const o = okunurOzet(ozet);
  if (!o.kisa) return null;
  if (o.kisa === o.tam) return <>{o.kisa}</>;
  return (
    <details className="denetim-ozet">
      <summary title={o.tam}>{o.kisa}</summary>
      <pre className="kucuk mono">{o.tam}</pre>
    </details>
  );
}

export function Denetim() {
  // Tüm kayıt + zincir doğrulaması: Sistem Yöneticisi ve Denetçi (`audit.read_all`, `audit.verify`).
  // Diğer roller yalnız kendi olaylarını görür (`audit.read_own`; core süzer).
  const tumu = useIzin("audit.read_all");
  const dogrulayabilir = useIzin("audit.verify");
  const v = useVeri(() => api.denetim(dogrulayabilir), [dogrulayabilir]);
  // "Daha fazla yükle": core sayfası 100 olay; eski olaylar `before_id` imleciyle eklenir.
  const [ekOlaylar, setEkOlaylar] = useState<DenetimOlayi[]>([]);
  const [sonraki, setSonraki] = useState<string | null>(null);
  const [ekYukleniyor, setEkYukleniyor] = useState(false);
  const [ekHata, setEkHata] = useState<string | null>(null);
  useEffect(() => {
    setEkOlaylar([]);
    setEkHata(null);
    setSonraki(v.veri?.sonraki ?? null);
  }, [v.veri]);
  async function dahaFazla() {
    if (!sonraki) return;
    setEkYukleniyor(true);
    setEkHata(null);
    try {
      const y = await api.denetim(false, sonraki);
      setEkOlaylar((l) => {
        const gorulen = new Set([...(v.veri?.olaylar ?? []), ...l].map((o) => o.id));
        return [...l, ...y.olaylar.filter((o) => !gorulen.has(o.id))];
      });
      setSonraki(y.sonraki ?? null);
    } catch (e) {
      setEkHata(hataMesaji(e));
    } finally {
      setEkYukleniyor(false);
    }
  }
  const [ara, setAra] = useState("");
  const kisiAdi = useKisiAdi();
  const olaylar = useMemo(() => {
    const q = ara.trim().toLocaleLowerCase("tr-TR");
    const l = [...(v.veri?.olaylar ?? []), ...ekOlaylar];
    return q
      ? l.filter((o) => `${o.aktor} ${kisiAdi(o.aktor)} ${o.eylem} ${o.nesne} ${o.ozet}`.toLocaleLowerCase("tr-TR").includes(q))
      : l;
  }, [v.veri, ekOlaylar, ara, kisiAdi]);
  const yuklenen = (v.veri?.olaylar.length ?? 0) + ekOlaylar.length;
  const sayac = ara.trim() ? `${olaylar.length}/${yuklenen}` : `${yuklenen}${sonraki ? "+" : ""}`;
  const dg = v.veri?.dogrulama;

  return (
    <>
      <SayfaBasligi
        baslik="Denetim kaydı"
        aciklama={
          tumu
            ? "Her AI çağrısı, araç çağrısı, onay ve ret append-only kayıttadır; her olay bir öncekinin hash'ine zincirlenir."
            : "Yalnız sizin olaylarınız gösterilir. Tüm kayıt ve zincir doğrulaması Sistem Yöneticisi ve Denetçi rolündedir."
        }
        eylemler={
          dogrulayabilir && (
            <IslemDugmesi izin="audit.verify" tur="ikincil" calisiyor={v.yukleniyor} onClick={() => void v.yenile()}>
              Zinciri yeniden doğrula
            </IslemDugmesi>
          )
        }
      />
      {v.yukleniyor && !v.veri ? (
        <Yukleniyor />
      ) : v.hata && !v.veri ? (
        <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
      ) : (
        <>
          {dg ? (
            dg.gecerli ? (
              <Uyari ton="basari" baslik="✓ Zincir doğrulandı" isaretli>
                {dg.kontrol_edilen} olay kontrol edildi · son hash <span className="mono">{kisaHash(dg.son_hash, 16)}</span> · {tarih(dg.zaman)}
              </Uyari>
            ) : (
              <Uyari ton="hata" baslik="✗ Zincir kırık" isaretli>
                {dg.kontrol_edilen} olay kontrol edildi · ilk kırık kayıt <span className="mono">{dg.ilk_kirik_id}</span>. Denetim kaydı değiştirilmiş olabilir.
              </Uyari>
            )
          ) : dogrulayabilir ? (
            <Uyari ton="bilgi">Zincir doğrulaması yapılmadı.</Uyari>
          ) : null}
          <Kart
            baslik={tumu ? `Olaylar (${sayac})` : `Olaylarınız (${sayac})`}
            eylemler={
              <div className="alan alan-satir">
                <label htmlFor="denetim-ara" className="gorunmez">
                  Olay ara
                </label>
                <input id="denetim-ara" type="search" placeholder="Aktör, eylem, nesne ara" value={ara} onChange={(e) => setAra(e.target.value)} />
              </div>
            }
          >
            {olaylar.length === 0 ? (
              <BosDurum baslik="Olay yok." />
            ) : (
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Denetim olayları tablosu">
                <table className="tablo tablo-sik">
                  <thead>
                    <tr>
                      <th scope="col" className="sayi">
                        #
                      </th>
                      <th scope="col">Zaman</th>
                      <th scope="col">Aktör</th>
                      <th scope="col">Eylem</th>
                      <th scope="col">Nesne</th>
                      <th scope="col">Özet</th>
                      <th scope="col">Hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {olaylar.map((o) => (
                      <tr key={o.id} className={dg && !dg.gecerli && dg.ilk_kirik_id === o.id ? "satir-hata" : undefined}>
                        <td className="sayi mono">{o.sira}</td>
                        <td className="tek-satir">{tarih(o.zaman)}</td>
                        <td className="tek-satir" title={kisiAdi(o.aktor) !== o.aktor ? o.aktor : undefined}>{kisiAdi(o.aktor)}</td>
                        <td className="mono">{o.eylem}</td>
                        <td className="mono">{o.nesne}</td>
                        <td className="denetim-ozet-hucre">
                          <OzetHucresi ozet={o.ozet} />
                        </td>
                        <td className="mono kucuk" title={`prev ${o.prev_hash}\nhash ${o.hash}`}>
                          {kisaHash(o.hash)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {sonraki && (
              <div className="eylemler" data-testid="denetim-daha-fazla">
                <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => void dahaFazla()} disabled={ekYukleniyor} aria-busy={ekYukleniyor || undefined}>
                  {ekYukleniyor && <span className="donen donen-kucuk" aria-hidden="true" />}
                  Daha eski olayları yükle
                </button>
                <span className="soluk kucuk">{yuklenen} olay yüklendi; arama yalnız yüklenen olaylarda yapılır.</span>
              </div>
            )}
            {ekHata && <HataKutusu hata={ekHata} yenile={() => void dahaFazla()} />}
          </Kart>
        </>
      )}
    </>
  );
}

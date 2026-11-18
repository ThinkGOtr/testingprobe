import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { hataMesaji, ortamAdlariniGizle } from "../api/http";
import type { DenetimOlayi } from "../api/types";
import { BosDurum, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { EylemCubugu, Kimlik, Sayfalama, SuzgecCubugu, TabloSarici } from "../components/tasarim";
import { useSayfalama, useSorguSuzgeci } from "../lib/sorguDurumu";
import { useIzin, useKisiAdi } from "../auth";
import { useVeri } from "../hooks";
import { kisaHash, tarih } from "../lib/format";

/** Özet sütununda gösterilen en çok karakter (tamamı ipucunda ve satır ayrıntısında). */
export const OZET_KISA_SINIR = 140;

/** Bir sayfada gösterilen olay (DZ-20: 100 olay 390 px'te 55k px, ET-08: 126 Tab durağı). */
export const DENETIM_SAYFA = 25;

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
  // Arama ve sayfa adreste (`?ara=…&sayfa=2`): paylaşılan bağlantı aynı görünümü açar.
  const suzgec = useSorguSuzgeci({ ara: "" });
  const ara = suzgec.deger.ara;
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
  const sayfalama = useSayfalama(olaylar, DENETIM_SAYFA);

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
            // ET-07: doğrulama sürerken düğme odakta kalır (aria-disabled + aria-busy), odak body'ye düşmez.
            <EylemCubugu hiza="son">
              <IslemDugmesi izin="audit.verify" tur="ikincil" calisiyor={v.yukleniyor} onClick={() => void v.yenile()}>
                Zinciri yeniden doğrula
              </IslemDugmesi>
            </EylemCubugu>
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
          <Kart baslik={tumu ? `Olaylar (${sayac})` : `Olaylarınız (${sayac})`}>
            <SuzgecCubugu etiket="Olay süzgeci" sonuc={ara.trim() ? `${olaylar.length}/${yuklenen} olay` : `${yuklenen}${sonraki ? "+" : ""} olay`}>
              <label htmlFor="denetim-ara">
                Ara
                <input id="denetim-ara" type="search" placeholder="Aktör, eylem, nesne ara" value={ara} onChange={(e) => suzgec.ayarla("ara", e.target.value)} />
              </label>
            </SuzgecCubugu>
            {olaylar.length === 0 ? (
              <BosDurum baslik="Olay yok.">
                {ara ? "Aramayla eşleşen olay yok; aramayı temizleyin." : "Portalda bir işlem yapıldıkça (çekim, üretim, onay) olaylar burada zincire eklenir."}
              </BosDurum>
            ) : (
              <div id="denetim-olaylari">
                <TabloSarici etiket="Denetim olayları tablosu" yogunluk="sik" uzun={sayfalama.gorunen.length > 15}>
                  <thead>
                    <tr>
                      <th scope="col">
                        # <span className="soluk">· hash</span>
                      </th>
                      <th scope="col">Zaman</th>
                      <th scope="col">Aktör</th>
                      <th scope="col">Eylem</th>
                      <th scope="col">Nesne</th>
                      <th scope="col">Özet</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sayfalama.gorunen.map((o) => (
                      <tr key={o.id} className={dg && !dg.gecerli && dg.ilk_kirik_id === o.id ? "satir-hata" : undefined}>
                        {/* Sıra ve zincir hash'i tek sütunda: 1024 px'te Hash sütunu yatay kaydırmada kalıyordu (DZ-02). */}
                        <td className="sutun-kimlik" data-etiket="# · hash" title={`prev ${o.prev_hash}\nhash ${o.hash}`}>
                          <span className="denetim-sira">
                            <span className="denetim-sira-no mono">{o.sira}</span>
                            {o.hash ? <Kimlik deger={o.hash.replace(/^sha256:/, "")} tur="sha" kisaltUzunluk={10} kirp="bas" kopyala /> : <span className="bos-hucre">—</span>}
                          </span>
                        </td>
                        <td className="sutun-tarih" data-etiket="Zaman">{tarih(o.zaman)}</td>
                        <td className="denetim-aktor" data-etiket="Aktör" title={kisiAdi(o.aktor) !== o.aktor ? o.aktor : undefined}>{kisiAdi(o.aktor)}</td>
                        <td className="sutun-kimlik" data-etiket="Eylem">{o.eylem}</td>
                        <td className="mono" data-etiket="Nesne">{o.nesne}</td>
                        <td className="denetim-ozet-hucre sutun-metin" data-etiket="Özet">
                          <OzetHucresi ozet={o.ozet} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </TabloSarici>
              </div>
            )}
            <Sayfalama {...sayfalama} birim="olay" hedefId="denetim-olaylari">
              {sonraki && sayfalama.sayfa === sayfalama.sayfaSayisi && (
                <span className="satir-ogeler" data-testid="denetim-daha-fazla">
                  <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => void dahaFazla()} disabled={ekYukleniyor} aria-busy={ekYukleniyor || undefined}>
                    {ekYukleniyor && <span className="donen donen-kucuk" aria-hidden="true" />}
                    Daha eski olayları yükle
                  </button>
                  <span className="soluk kucuk">{yuklenen} olay yüklendi; arama yalnız yüklenen olaylarda yapılır.</span>
                </span>
              )}
            </Sayfalama>
            {ekHata && <HataKutusu hata={ekHata} yenile={() => void dahaFazla()} />}
          </Kart>
        </>
      )}
    </>
  );
}

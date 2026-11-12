// 012/Ş8 (ANALIZ §4.6, §7): Kontrol Kulesi "Ekilmiş hata koşusu" kartı.
// Demo uygulama her seferinde tek bir hatayla bilerek bozulur, onaylı test paketi koşar; en az bir test
// kırmızıya dönerse hata "yakalandı", hepsi yeşil kalırsa "kaçtı". Kart: başlatma formu (engineer,
// presenter), süren koşunun ilerlemesi, hata × platform sonuç tablosu, kaçan hatalar ve son koşular.
// Renk tek başına anlam taşımaz: sonuçlar ✓ ✗ ⚠ işaretli metindir; `gecersiz` adımın nedeni görünür yazılır.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { HATA_KOSUSU_SURUYOR, hataKosusuApi } from "../../api/client";
import { useOlay } from "../../api/events";
import { ApiError, hataMesaji } from "../../api/http";
import type { HataKatalogOgesi, HataKosusu, HataKosusuAdimi, HataKosusuDetay, HataTuru, Rol } from "../../api/types";
import { hataKosusuSuruyorMu, yakalamaOrani } from "../../api/uyumKule";
import { useOturum } from "../../auth";
import { useGeciktirilmis, useVeri } from "../../hooks";
import { ekilmisHataAdi, HATA_ADIM_SONUCU, HATA_KOSUSU_DURUMU, HATA_TURU } from "../../lib/etiketler";
import { sure, tarih, yuzde } from "../../lib/format";
import { PLATFORMLAR, PLATFORM_ETIKETI, uygulamaPlatformuMu, type Platform } from "../../lib/platform";
import { KisiAdi } from "../KisiAdi";
import { BosDurum, Cip, HataKutusu, Ilerleme, IslemDugmesi, Kart, Olculmedi, Uyari, Yukleniyor } from "../ui";
import "./kule-hata.css";

/** V4: koşuyu başlatabilen ve iptal edebilen roller. */
export const HATA_KOSUSU_ROLLERI: Rol[] = ["engineer", "presenter"];
const TURLER: HataTuru[] = ["kod", "veri"];
const SURUYOR_MESAJI = "Süren bir ekilmiş hata koşusu var. Bitmesini bekleyin ya da koşuyu iptal edin.";
/** ANALIZ §10: uygulama platformlarında koşu hata başına 3–5 dakika sürer. */
const UYGULAMA_DK = [3, 5] as const;
const YOKLAMA_MS = 5000;

const ASAMA_ADI: Record<HataKosusuAdimi["asama"], string> = {
  temel: "Temel koşu (hatasız)",
  hata: "Hata koşusu",
  kapanis: "Kapanış koşusu (hatasız)",
};

function adimAdi(a: HataKosusuAdimi, katalog: Map<string, HataKatalogOgesi>): string {
  return a.asama === "hata" && a.hata_kodu ? ekilmisHataAdi(a.hata_kodu, katalog.get(a.hata_kodu)?.ad ?? a.hata_adi) : ASAMA_ADI[a.asama];
}

/** Oran metni: "%78 (7/9)"; payda 0 ise null (çağıran "ölçülmedi" yazar). */
function oranMetni(o: { oran: number | null; yakalanan: number; kacan: number }): string | null {
  return o.oran === null ? null : `${yuzde(o.oran)} (${o.yakalanan}/${o.yakalanan + o.kacan})`;
}

export function HataKosusuKarti({ olcuDegisti }: { olcuDegisti?: () => void }) {
  const { kullanici } = useOturum();
  const yetkili = !!kullanici && HATA_KOSUSU_ROLLERI.includes(kullanici.rol);
  const katalog = useVeri(() => hataKosusuApi.katalog(), []);
  const liste = useVeri(() => hataKosusuApi.liste(5), []);
  const [secili, setSecili] = useState<string | null>(null);

  const suren = liste.veri?.find(hataKosusuSuruyorMu) ?? null;
  const gosterilenId = secili ?? suren?.id ?? liste.veri?.[0]?.id ?? null;
  const detay = useVeri(() => (gosterilenId ? hataKosusuApi.detay(gosterilenId) : Promise.resolve(null)), [gosterilenId]);
  // Süren koşunun adımları (ilerleme): gösterilen koşu o değilse ayrıca okunur.
  const surenDetay = useVeri(() => (suren && suren.id !== gosterilenId ? hataKosusuApi.detay(suren.id) : Promise.resolve(null)), [suren?.id, gosterilenId]);

  // Olay patlamaları (adım başına bir olay) tek yenilemede birleşir; koşu bitince Kule ölçüleri de yenilenir.
  const bitti = useRef(false);
  const sessiz = useGeciktirilmis(() => {
    void liste.yenile(true);
    void detay.yenile(true);
    void surenDetay.yenile(true);
    if (bitti.current) {
      bitti.current = false;
      olcuDegisti?.();
    }
  }, 300);
  useOlay(
    (o) => {
      const d = o.data.durum;
      if (d === "done" || d === "failed" || d === "cancelled") bitti.current = true;
      sessiz();
    },
    ["hata_kosusu.ilerleme"],
  );

  // Olay akışı kopuk ya da yokken de ilerleme görünür: koşu sürerken seyrek yoklama (olaylar gelirse zararsız).
  const surenId = suren?.id ?? null;
  useEffect(() => {
    if (!surenId) return;
    const t = setInterval(sessiz, YOKLAMA_MS);
    return () => clearInterval(t);
  }, [surenId, sessiz]);

  const katalogHaritasi = useMemo(() => new Map((katalog.veri ?? []).map((h) => [h.kod, h])), [katalog.veri]);

  // ---- form
  const [platformlar, setPlatformlar] = useState<Platform[]>(["web"]); // V5: yalnız web işaretli
  // null: kullanıcı seçime dokunmadı → kataloğun tamamı (varsayılan hepsi seçili).
  const [hataSecimi, setHataSecimi] = useState<string[] | null>(null);
  const tumHatalar = (katalog.veri ?? []).map((h) => h.kod);
  const secilenHatalar = hataSecimi === null ? tumHatalar : tumHatalar.filter((h) => hataSecimi.includes(h));
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);

  const degistir = <T,>(dizi: T[], x: T, sec: boolean): T[] => (sec ? [...dizi.filter((y) => y !== x), x] : dizi.filter((y) => y !== x));

  const baslat = async () => {
    setCalisiyor(true);
    setHata(null);
    try {
      await hataKosusuApi.baslat({
        platformlar: PLATFORMLAR.filter((p) => platformlar.includes(p)),
        // Tüm katalog seçiliyse `hatalar` gönderilmez (sözleşme: verilmezse tamamı).
        ...(secilenHatalar.length === tumHatalar.length ? {} : { hatalar: secilenHatalar }),
      });
      setSecili(null);
    } catch (e) {
      setHata(e instanceof ApiError && (e.kod === HATA_KOSUSU_SURUYOR || e.status === 409) ? SURUYOR_MESAJI : hataMesaji(e));
    } finally {
      setCalisiyor(false);
      void liste.yenile(true);
    }
  };

  const iptal = async (id: string) => {
    setCalisiyor(true);
    setHata(null);
    try {
      await hataKosusuApi.iptal(id);
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setCalisiyor(false);
      void liste.yenile(true);
      void detay.yenile(true);
    }
  };

  const baslatmaNedeni = suren
    ? "Süren koşu bitmeden yenisi başlatılamaz."
    : katalog.hata
      ? "Hata kataloğu okunamadı."
      : platformlar.length === 0
        ? "En az bir platform seçin."
        : secilenHatalar.length === 0
          ? "En az bir hata seçin."
          : undefined;

  const uygulamaSayisi = platformlar.filter(uygulamaPlatformuMu).length;
  const kosuSayisi = platformlar.length * (secilenHatalar.length + 2);
  const formKapali = !yetkili || !!suren || calisiyor;

  return (
    <Kart baslik="Ekilmiş hata koşusu" className="hk-kart">
      <p className="hk-aciklama" data-testid="hk-aciklama">
        Demo uygulama her seferinde <strong>tek bir hatayla bilerek bozulur</strong> ve onaylı testler koşturulur. Testlerin kırmızıya dönmesi
        beklenir: en az bir test kırmızıysa hata <strong>yakalandı</strong>, hepsi yeşil kaldıysa hata <strong>kaçtı</strong>. Kaçan hata, o
        kuralı sınayan bir testin eksik olduğunu gösterir. Bu koşular kasıtlı kırmadır: geçme oranına girmez, bug taslağı açmaz.
      </p>

      {/* ------------------------------------------------ başlatma formu */}
      <form
        className="hk-form"
        aria-label="Ekilmiş hata koşusu başlat"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <fieldset className="hk-grup" disabled={formKapali}>
          <legend>Platformlar</legend>
          <div className="hk-secenekler">
            {PLATFORMLAR.map((p) => (
              <label key={p} className="hk-secenek">
                <input
                  type="checkbox"
                  checked={platformlar.includes(p)}
                  onChange={(e) => setPlatformlar((o) => degistir(o, p, e.target.checked))}
                  data-testid={`hk-platform-${p}`}
                />
                <span>{PLATFORM_ETIKETI[p]}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {katalog.yukleniyor && !katalog.veri ? (
          <Yukleniyor metin="Hata kataloğu yükleniyor…" />
        ) : katalog.hata && !katalog.veri ? (
          <HataKutusu hata={katalog.hata} kaynak={katalog.hataNesnesi} yenile={() => void katalog.yenile()} />
        ) : (
          <div className="hk-turler">
            {TURLER.map((tur) => {
              const ogeler = (katalog.veri ?? []).filter((h) => h.tur === tur);
              if (ogeler.length === 0) return null;
              return (
                <fieldset key={tur} className="hk-grup" disabled={formKapali} data-testid={`hk-tur-${tur}`}>
                  <legend>
                    {HATA_TURU[tur]} ({ogeler.length})
                  </legend>
                  <ul className="hk-hatalar">
                    {ogeler.map((h) => (
                      <li key={h.kod}>
                        <label className="hk-secenek">
                          <input
                            type="checkbox"
                            checked={secilenHatalar.includes(h.kod)}
                            onChange={(e) => setHataSecimi(degistir(secilenHatalar, h.kod, e.target.checked))}
                            aria-describedby={`hk-hata-${h.kod}`}
                          />
                          <span>{h.ad}</span>
                        </label>
                        <div className="hk-secenek-alt kucuk" id={`hk-hata-${h.kod}`}>
                          {h.aciklama}
                          {h.yakalayan_kural ? ` Yakalaması beklenen kural: ${h.yakalayan_kural}.` : ""} <span className="mono">{h.kod}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              );
            })}
          </div>
        )}

        <p className="kucuk hk-tahmin" data-testid="hk-tahmin">
          Seçim: {secilenHatalar.length} hata × {platformlar.length} platform = {kosuSayisi} koşu (platform başına ayrıca hatasız temel ve kapanış
          koşusu dahil). Platformlar sırayla koşar.{" "}
          {uygulamaSayisi > 0 ? (
            <strong>
              Android, iOS ve Windows'ta her hata {UYGULAMA_DK[0]}–{UYGULAMA_DK[1]} dakika sürer: seçilen uygulama platformları için yaklaşık{" "}
              {uygulamaSayisi * secilenHatalar.length * UYGULAMA_DK[0]}–{uygulamaSayisi * secilenHatalar.length * UYGULAMA_DK[1]} dakika. Cihaz ya
              da emülatör açık olmalı; ulaşılamayan platformun adımları geçersiz sayılır.
            </strong>
          ) : (
            <>
              Android, iOS ve Windows'ta her hata {UYGULAMA_DK[0]}–{UYGULAMA_DK[1]} dakika sürer; cihaz ya da emülatör açık olmalı.
            </>
          )}
        </p>

        <div className="satir-ogeler">
          <IslemDugmesi
            roller={HATA_KOSUSU_ROLLERI}
            calisiyor={calisiyor && !suren}
            disabled={!!baslatmaNedeni}
            title={baslatmaNedeni}
            onClick={() => void baslat()}
          >
            Koşuyu başlat
          </IslemDugmesi>
        </div>
        {hata && (
          <Uyari ton="hata">
            <span data-testid="hk-hata">{hata}</span>
          </Uyari>
        )}
      </form>

      {/* ------------------------------------------------ süren koşu */}
      {suren && (
        <Ilerlemesi
          kosu={suren}
          detay={detay.veri?.id === suren.id ? detay.veri : (surenDetay.veri ?? null)}
          katalog={katalogHaritasi}
          calisiyor={calisiyor}
          iptal={() => void iptal(suren.id)}
        />
      )}

      {/* ------------------------------------------------ sonuç tablosu */}
      {liste.yukleniyor && !liste.veri ? (
        <Yukleniyor metin="Koşular yükleniyor…" />
      ) : liste.hata && !liste.veri ? (
        <HataKutusu hata={liste.hata} kaynak={liste.hataNesnesi} yenile={() => void liste.yenile()} />
      ) : !gosterilenId ? (
        <BosDurum baslik="Henüz ekilmiş hata koşusu yok.">Hata yakalama oranı ölçülmedi; ilk koşudan sonra burada görünür.</BosDurum>
      ) : detay.hata && !detay.veri ? (
        <HataKutusu hata={detay.hata} kaynak={detay.hataNesnesi} yenile={() => void detay.yenile()} />
      ) : !detay.veri ? (
        <Yukleniyor metin="Koşu sonucu yükleniyor…" />
      ) : (
        <Sonuc kosu={detay.veri} katalog={katalogHaritasi} />
      )}

      {/* ------------------------------------------------ geçmiş */}
      {liste.veri && liste.veri.length > 0 && <Gecmis kosular={liste.veri} gosterilenId={gosterilenId} ac={setSecili} />}
    </Kart>
  );
}

function Ilerlemesi({
  kosu,
  detay,
  katalog,
  calisiyor,
  iptal,
}: {
  kosu: HataKosusu;
  detay: HataKosusuDetay | null;
  katalog: Map<string, HataKatalogOgesi>;
  calisiyor: boolean;
  iptal: () => void;
}) {
  const adimlar = detay?.adimlar ?? [];
  const biten = adimlar.filter((a) => a.sonuc !== "bekliyor").length;
  const simdiki = adimlar.find((a) => a.sonuc === "bekliyor") ?? null;
  return (
    <div className="hk-ilerleme" data-testid="hk-ilerleme" role="group" aria-label="Süren ekilmiş hata koşusu">
      <div className="hk-ilerleme-ust">
        <div role="status" aria-live="polite">
          <strong>{kosu.durum === "queued" ? "Koşu sırada" : "Koşu sürüyor"}</strong>
          {simdiki ? (
            <span data-testid="hk-simdiki">
              {" "}
              · {PLATFORM_ETIKETI[simdiki.platform]} · {adimAdi(simdiki, katalog)}
            </span>
          ) : null}
          {adimlar.length > 0 && (
            <span className="hk-sayac mono" data-testid="hk-sayac">
              {" "}
              · adım {Math.min(biten + 1, adimlar.length)} / {adimlar.length}
            </span>
          )}
        </div>
        <div className="satir-ogeler">
          <IslemDugmesi roller={HATA_KOSUSU_ROLLERI} tur="ikincil" kucuk calisiyor={calisiyor} onClick={iptal}>
            İptal et
          </IslemDugmesi>
        </div>
      </div>
      {adimlar.length > 0 && <Ilerleme oran={biten / adimlar.length} etiket="Ekilmiş hata koşusu ilerlemesi" />}
      <p className="kucuk hk-ilerleme-not">
        {kosu.platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")} · {kosu.hatalar.length} hata. Sonuçlar aşağıdaki tabloya adım adım
        yazılır.
      </p>
    </div>
  );
}

function Hucre({ a, ad, platform }: { a: HataKosusuAdimi | undefined; ad: string; platform: Platform }) {
  if (!a) return <span className="hk-bos">—</span>;
  const s = HATA_ADIM_SONUCU[a.sonuc];
  return (
    <div className="hk-hucre" data-sonuc={a.sonuc}>
      <div className="hk-hucre-ust">
        <Cip ton={s.ton}>{s.etiket}</Cip>
        {a.run_id && (
          <Link to={`/kosular/${encodeURIComponent(a.run_id)}`} className="kucuk" title={a.sure_ms !== null ? `Süre: ${sure(a.sure_ms)}` : undefined}>
            koşuyu aç
            <span className="gorunmez">
              : {ad} · {PLATFORM_ETIKETI[platform]}
            </span>
          </Link>
        )}
      </div>
      {/* Neden yalnız ipucunda değil, görünür metin (dokunmatik ve klavye kullanıcıları için). */}
      {a.neden && (a.sonuc === "gecersiz" || a.sonuc === "kirmizi") && <div className="hk-neden kucuk">Neden: {a.neden}</div>}
      {a.sonuc === "yakalandi" &&
        (a.kiran_testler.length > 0 ? (
          <details className="hk-testler">
            <summary>
              {a.kiran_testler.length} test yakaladı
              <span className="gorunmez">
                : {ad} · {PLATFORM_ETIKETI[platform]}
              </span>
            </summary>
            <ul>
              {a.kiran_testler.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </details>
        ) : (
          <div className="kucuk hk-neden">Kıran test adı bildirilmedi.</div>
        ))}
    </div>
  );
}

function Sonuc({ kosu, katalog }: { kosu: HataKosusuDetay; katalog: Map<string, HataKatalogOgesi> }) {
  const adim = (platform: Platform, asama: HataKosusuAdimi["asama"], kod: string | null) =>
    kosu.adimlar.find((a) => a.platform === platform && a.asama === asama && a.hata_kodu === kod);
  const suruyor = hataKosusuSuruyorMu(kosu);
  const d = HATA_KOSUSU_DURUMU[kosu.durum];
  const genel = yakalamaOrani(kosu.adimlar);
  // Kaçan hatalar: hata bazında, kaçtığı platformlarla.
  const kacanlar = kosu.hatalar
    .map((kod) => ({ kod, platformlar: kosu.platformlar.filter((p) => adim(p, "hata", kod)?.sonuc === "kacti") }))
    .filter((x) => x.platformlar.length > 0);

  return (
    <div className="hk-sonuc" data-testid="hk-sonuc" data-kosu={kosu.id}>
      <div className="hk-sonuc-ust">
        <h3>Sonuç tablosu</h3>
        <span className="kucuk hk-sonuc-kunye">
          <Cip ton={d.ton}>{d.etiket}</Cip> {tarih(kosu.bitis ?? kosu.baslama ?? kosu.olusturma)}
          {kosu.baslatan ? (
            <>
              {" "}
              · başlatan <KisiAdi ad={kosu.baslatan} />
            </>
          ) : null}
          {kosu.commit ? (
            <>
              {" "}
              · commit <span className="mono">{kosu.commit.slice(0, 7)}</span>
            </>
          ) : null}
        </span>
      </div>
      {kosu.uyarilar.length > 0 && (
        <Uyari ton="uyari">
          <ul className="duz-liste kucuk">
            {kosu.uyarilar.map((u) => (
              <li key={u}>⚠ {u}</li>
            ))}
          </ul>
        </Uyari>
      )}
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Ekilmiş hata sonuç tablosu">
        <table className="tablo hk-tablo">
          <thead>
            <tr>
              <th scope="col">Hata</th>
              {kosu.platformlar.map((p) => (
                <th scope="col" key={p}>
                  {PLATFORM_ETIKETI[p]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="hk-cerceve-satiri">
              <th scope="row">{ASAMA_ADI.temel}</th>
              {kosu.platformlar.map((p) => (
                <td key={p} data-testid={`hk-temel-${p}`}>
                  <Hucre a={adim(p, "temel", null)} ad={ASAMA_ADI.temel} platform={p} />
                </td>
              ))}
            </tr>
            {kosu.hatalar.map((kod) => {
              const oge = katalog.get(kod);
              const ad = ekilmisHataAdi(kod, oge?.ad);
              return (
                <tr key={kod} data-testid={`hk-satir-${kod}`}>
                  <th scope="row">
                    <span className="hk-hata-adi">{ad}</span>
                    <span className="hk-hata-kunye kucuk">
                      {oge ? `${HATA_TURU[oge.tur]} · ` : ""}
                      <span className="mono">{kod}</span>
                    </span>
                  </th>
                  {kosu.platformlar.map((p) => (
                    <td key={p} data-testid={`hk-hucre-${p}-${kod}`}>
                      <Hucre a={adim(p, "hata", kod)} ad={ad} platform={p} />
                    </td>
                  ))}
                </tr>
              );
            })}
            <tr className="hk-cerceve-satiri">
              <th scope="row">{ASAMA_ADI.kapanis}</th>
              {kosu.platformlar.map((p) => (
                <td key={p} data-testid={`hk-kapanis-${p}`}>
                  <Hucre a={adim(p, "kapanis", null)} ad={ASAMA_ADI.kapanis} platform={p} />
                </td>
              ))}
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Yakalama oranı</th>
              {kosu.platformlar.map((p) => {
                const o = yakalamaOrani(kosu.adimlar.filter((a) => a.platform === p));
                const m = oranMetni(o);
                return (
                  <td key={p} data-testid={`hk-oran-${p}`}>
                    {m ? <strong>{m}</strong> : <Olculmedi metin={o.bekleyen > 0 ? "sürüyor" : "ölçülmedi"} />}
                    {o.gecersiz > 0 && <div className="kucuk hk-neden">⚠ {o.gecersiz} geçersiz (orana girmez)</div>}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="kucuk hk-not" data-testid="hk-oran-notu">
        Oran = yakalanan / (yakalanan + kaçan). <strong>⚠ Geçersiz</strong> adımlar (ortam ya da altyapı hatası, yeşil olmayan temel koşu)
        tabloda gösterilir ama orana girmez.{" "}
        {oranMetni(genel) ? (
          <>
            Tüm platformlar: <strong data-testid="hk-oran-genel">{oranMetni(genel)}</strong>
            {genel.gecersiz > 0 ? ` · ${genel.gecersiz} geçersiz` : ""}.
          </>
        ) : (
          <>Tüm platformlar: {suruyor ? "sürüyor" : "ölçülmedi (sayılan adım yok)"}.</>
        )}
      </p>

      <div className="hk-kacanlar" data-testid="hk-kacanlar">
        <h3>Kaçan hatalar</h3>
        {kacanlar.length > 0 ? (
          <>
            <p className="kucuk">
              Bu hatalarla uygulama bozukken bütün onaylı testler yeşil kaldı. İlgili kural için case eksik ya da beklenen değer hatayı ayırt
              etmiyor; yapılacak iş burada.
            </p>
            <ul className="hk-kacan-liste">
              {kacanlar.map(({ kod, platformlar }) => {
                const oge = katalog.get(kod);
                return (
                  <li key={kod} data-testid={`hk-kacan-${kod}`}>
                    {/* ✗ adla aynı metinde: tek karakterlik ayrı öğe axe kontrastını "incomplete"e düşürür. */}
                    <div>
                      <strong>✗ {ekilmisHataAdi(kod, oge?.ad)}</strong> <span className="kucuk">· {platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")}</span>
                      {oge?.aciklama && <div className="kucuk hk-neden">{oge.aciklama}</div>}
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        ) : (
          <p className="kucuk" data-testid="hk-kacan-yok">
            {suruyor
              ? "Koşu sürüyor; kaçan hata olursa burada listelenir."
              : genel.yakalanan > 0
                ? "Kaçan hata yok: sayılan her hatayı en az bir test yakaladı."
                : "Sayılan adım yok; kaçan hata ölçülmedi."}
          </p>
        )}
      </div>
    </div>
  );
}

function Gecmis({ kosular, gosterilenId, ac }: { kosular: HataKosusu[]; gosterilenId: string | null; ac: (id: string) => void }) {
  return (
    <div className="hk-gecmis" data-testid="hk-gecmis">
      <h3>Son koşular</h3>
      <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Son ekilmiş hata koşuları tablosu">
        <table className="tablo tablo-sik">
          <thead>
            <tr>
              <th scope="col">Tarih</th>
              <th scope="col">Başlatan</th>
              <th scope="col">Platformlar</th>
              <th scope="col">Oran</th>
              <th scope="col">Durum</th>
              <th scope="col">
                <span className="gorunmez">İşlem</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {kosular.map((k) => {
              const d = HATA_KOSUSU_DURUMU[k.durum];
              const zaman = tarih(k.bitis ?? k.baslama ?? k.olusturma);
              const m = k.ozet ? oranMetni(k.ozet) : null;
              return (
                <tr key={k.id} data-testid={`hk-gecmis-${k.id}`} data-gosterilen={k.id === gosterilenId || undefined}>
                  <td className="tek-satir">{zaman}</td>
                  <td>{k.baslatan ? <KisiAdi ad={k.baslatan} /> : "—"}</td>
                  <td>{k.platformlar.map((p) => PLATFORM_ETIKETI[p]).join(", ")}</td>
                  <td>
                    {m ?? <Olculmedi metin={hataKosusuSuruyorMu(k) ? "sürüyor" : "ölçülmedi"} />}
                    {k.ozet && k.ozet.gecersiz > 0 ? <span className="kucuk"> · {k.ozet.gecersiz} geçersiz</span> : null}
                  </td>
                  <td>
                    <Cip ton={d.ton}>{d.etiket}</Cip>
                  </td>
                  <td>
                    {k.id === gosterilenId ? (
                      <span className="kucuk">gösteriliyor</span>
                    ) : (
                      <button type="button" className="dugme dugme-ikincil dugme-kucuk" aria-label={`Aç: ${zaman} koşusu`} onClick={() => ac(k.id)}>
                        Aç
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// 012 Ş7 — "Karar tabloları" sayfası (/gereksinimler/:id/karar-tablolari; specs/012 ANALIZ §7):
// gereksinimin karar tabloları ve metamorfik ilişkileri, AI taslağı üretimi, elle boş tablo, düzenleme,
// "örnekle dene", PO onay akışı ve "Ek case türet".
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useOlay } from "../../api/events";
import type { KararTablolariYaniti, KararTablosu, MetamorfikIliski } from "../../api/types";
import { EkCaseTuret } from "../../components/kalite/EkCaseTuret";
import { IliskiDuzenleyici, IliskiKarti } from "../../components/kalite/IliskiKarti";
import { KararTablosuKarti } from "../../components/kalite/KararTablosuKarti";
import "../../components/kalite/kalite.css";
import { BosDurum, HataKutusu, IslemDugmesi, SayfaBasligi, Uyari, Yukleniyor } from "../../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../../hooks";

/** AI taslağı yalnız PO onaylı (ya da sonrasındaki) gereksinimden üretilir (ANALIZ §4.1). */
const TASLAK_DURUMLARI = new Set(["po_approved", "generating", "cases_ready", "done"]);
export const TASLAK_NEDENI = "Karar tablosu için gereksinim PO onaylı olmalı.";
/** Taslak işi bu süre içinde sonuç olayı vermezse bekleme göstergesi uyarıya döner. */
export const TASLAK_BEKLEME_MS = 60000;
const TASLAK_SUREN = new Set(["started", "running", "queued"]);

export function KararTablolari() {
  const { id = "" } = useParams();
  const gereksinim = useVeri(() => api.gereksinim(id), [id]);
  // Yerini yenisi alanlar da istenir (ayrı, kapalı bölümde gösterilir).
  const veri = useVeri(() => api.kararTablolari(id, true), [id]);
  // Kaynak seçimi ve türetme sonucundaki başlıklar için; yüklenemezse bölüm yine çalışır.
  const caseler = useVeri(() => api.caseler(id).catch(() => []), [id]);
  const [uretiliyor, setUretiliyor] = useState<"yok" | "suruyor" | "gecikti">("yok");
  const [onay, setOnay] = useState(false);
  const [yeniTabloId, setYeniTabloId] = useState<string | null>(null);
  const [yeniIliski, setYeniIliski] = useState(false);
  const uretIslem = useIslem();
  const ekleIslem = useIslem();
  const durumRef = useRef<HTMLDivElement | null>(null);

  const sessiz = useGeciktirilmis(() => void veri.yenile(true));
  useOlay(
    (o) => {
      if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== id) return;
      // Taslak işinin sonucu (yeni taslaklar) liste yenilenince görünür.
      if (o.type === "karar_tablosu.updated" && o.data.eylem === "ai_taslak") setUretiliyor("yok");
      sessiz();
    },
    ["karar_tablosu.updated", "requirement.updated"],
  );
  const sessizCase = useGeciktirilmis(() => void caseler.yenile(true));
  useOlay(
    (o) => {
      if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== id) return;
      sessizCase();
    },
    ["case.generated", "case.updated"],
  );
  useEffect(() => {
    if (uretiliyor !== "suruyor") return;
    const z = setTimeout(() => setUretiliyor("gecikti"), TASLAK_BEKLEME_MS);
    return () => clearTimeout(z);
  }, [uretiliyor]);

  const g = gereksinim.veri;
  const y = veri.veri;
  const sonTaslak = y?.son_taslak ?? null;
  const taslakSuruyor = sonTaslak ? TASLAK_SUREN.has(sonTaslak.durum) : false;
  // Sayfa açıldığında süren iş varsa (başka sekmeden başlatılmış) gösterge açılır; liste işin bittiğini söylerse kapanır.
  useEffect(() => {
    if (taslakSuruyor) setUretiliyor((u) => (u === "yok" ? "suruyor" : u));
    else if (sonTaslak) setUretiliyor("yok");
  }, [taslakSuruyor, sonTaslak]);
  const kriterler = g?.kabul_kriterleri ?? [];
  const etkinTablolar = y?.tablolar.filter((t) => t.durum !== "superseded") ?? [];
  const eskiTablolar = y?.tablolar.filter((t) => t.durum === "superseded") ?? [];
  const etkinIliskiler = y?.iliskiler.filter((r) => r.durum !== "superseded") ?? [];
  const eskiIliskiler = y?.iliskiler.filter((r) => r.durum === "superseded") ?? [];
  const taslakNedeni = g && !TASLAK_DURUMLARI.has(g.durum) ? TASLAK_NEDENI : undefined;

  const listeGuncelle = (f: (y: KararTablolariYaniti) => KararTablolariYaniti) => {
    if (veri.veri) veri.setVeri(f(veri.veri));
  };
  const tabloGuncellendi = (t: KararTablosu) => listeGuncelle((y) => ({ ...y, tablolar: y.tablolar.map((x) => (x.id === t.id ? t : x)) }));
  const iliskiGuncellendi = (r: MetamorfikIliski) => listeGuncelle((y) => ({ ...y, iliskiler: y.iliskiler.map((x) => (x.id === r.id ? r : x)) }));
  const yenile = () => void veri.yenile(true);

  async function taslakUret() {
    setOnay(false);
    const is = await uretIslem.calistir(() => api.kararTablosuTaslagiUret(id));
    if (is) {
      setUretiliyor("suruyor");
      requestAnimationFrame(() => durumRef.current?.focus());
    }
  }
  async function bosTabloEkle() {
    const t = await ekleIslem.calistir(() => api.kararTablosuEkle(id));
    if (t) {
      setYeniTabloId(t.id);
      listeGuncelle((y) => ({ ...y, tablolar: y.tablolar.some((x) => x.id === t.id) ? y.tablolar : [...y.tablolar, t] }));
    }
  }

  const eylemler = (
    <>
      <Link className="dugme dugme-ikincil" to={`/gereksinimler/${encodeURIComponent(id)}/caseler`}>
        Case review
      </Link>
      <IslemDugmesi roller={["analyst"]} tur="ikincil" calisiyor={ekleIslem.calisiyor} disabled={!!taslakNedeni} title={taslakNedeni} onClick={() => void bosTabloEkle()}>
        Boş tablo ekle
      </IslemDugmesi>
      <IslemDugmesi
        roller={["analyst"]}
        calisiyor={uretIslem.calisiyor || uretiliyor === "suruyor"}
        disabled={!!taslakNedeni}
        title={taslakNedeni}
        aria-expanded={etkinTablolar.length + etkinIliskiler.length > 0 ? onay : undefined}
        onClick={() => (etkinTablolar.length + etkinIliskiler.length > 0 ? setOnay((a) => !a) : void taslakUret())}
      >
        AI taslağı üret
      </IslemDugmesi>
    </>
  );

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}`}>← {g?.jira_key ?? g?.baslik ?? "Gereksinim"}</Link>}
        baslik="Karar tabloları"
        aciklama={g ? `${g.jira_key ? `${g.jira_key} · ` : ""}${g.baslik}` : undefined}
        eylemler={eylemler}
      />
      <p className="soluk kt-giris">
        Karar tablosu, bir hesaplama kuralının PO onaylı girdi → çıktı tanımıdır. AI taslağı yalnız onaylı gereksinim metninden çıkarılır; analist düzenler, PO
        onaylar. Onaylı ve güncel tablo, case'lerin beklenen değerlerini onaydan önce bağımsız olarak kontrol eder.
      </p>

      {onay && (
        <div className="kt-onay-kutu" data-testid="taslak-onay">
          <Uyari baslik="Yeni AI taslağı mevcut kayıtların yerini alır">
            Bu gereksinimdeki {etkinTablolar.length} tablo ve {etkinIliskiler.length} ilişki "Yerini yenisi aldı" durumuna geçer; onaylı tablolar kontrolde
            kullanılmaz hâle gelir. Yeni taslaklar yeniden düzenlenip PO onayından geçmelidir.
          </Uyari>
          <div className="eylemler">
            <IslemDugmesi roller={["analyst"]} kucuk calisiyor={uretIslem.calisiyor} onClick={() => void taslakUret()}>
              Evet, yeni taslak üret
            </IslemDugmesi>
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setOnay(false)}>
              Vazgeç
            </button>
          </div>
        </div>
      )}
      {uretIslem.hata && <HataKutusu hata={uretIslem.hata} kaynak={uretIslem.hataNesnesi} />}
      {ekleIslem.hata && <HataKutusu hata={ekleIslem.hata} kaynak={ekleIslem.hataNesnesi} />}
      <div ref={durumRef} tabIndex={-1} className="kt-durum" aria-live="polite">
        {uretiliyor === "suruyor" && (
          <div className="yukleniyor" role="status" data-testid="taslak-suruyor">
            <span className="donen" aria-hidden="true" />
            AI taslağı üretiliyor… Tablolar ve ilişkiler hazır olunca liste yenilenir.
          </div>
        )}
        {uretiliyor === "gecikti" && (
          <Uyari baslik="Taslak henüz gelmedi">
            Taslak işi {Math.round(TASLAK_BEKLEME_MS / 1000)} saniyede sonuç bildirmedi. İş arka planda sürüyor olabilir; liste olay gelince yenilenir.{" "}
            <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => void veri.yenile()}>
              Listeyi yenile
            </button>
          </Uyari>
        )}
        {uretiliyor === "yok" && sonTaslak?.hata && (
          <Uyari ton="hata" baslik="Son AI taslağı üretilemedi">
            {sonTaslak.hata}
          </Uyari>
        )}
        {uretiliyor === "yok" && !!sonTaslak?.sonuc?.atilan.length && (
          <div data-testid="taslak-atilan">
            <Uyari baslik={`Son AI taslağında ${sonTaslak.sonuc.atilan.length} öğe yazılmadı`}>
              Doğrulamadan geçmeyen öğeler kayda alınmadı; gerekirse elle ekleyin.
              <ul className="duz-liste">
                {sonTaslak.sonuc.atilan.map((a, i) => (
                  <li key={`${a.tur}-${a.ref ?? i}`}>
                    <strong>{a.tur === "metamorfik_iliski" ? "İlişki" : "Tablo"}</strong> {a.ref && <span className="mono">{a.ref}</span>} {a.ad}
                    {a.hatalar.length > 0 && <span className="soluk kucuk"> — {a.hatalar.join("; ")}</span>}
                  </li>
                ))}
              </ul>
            </Uyari>
          </div>
        )}
      </div>

      {veri.hata && !y ? (
        <HataKutusu hata={veri.hata} yenile={() => void veri.yenile()} kaynak={veri.hataNesnesi} />
      ) : !y ? (
        <Yukleniyor />
      ) : (
        <>
          <section aria-labelledby="kt-tablolar" className="kt-bolum-kap">
            <h2 id="kt-tablolar" className="kt-bolum-baslik">
              Tablolar
            </h2>
            {etkinTablolar.length === 0 ? (
              <BosDurum baslik="Bu gereksinim için karar tablosu yok.">
                {taslakNedeni ?? "“AI taslağı üret” ile kabul kriterlerinden taslak çıkarın ya da “Boş tablo ekle” ile elle başlayın."}
              </BosDurum>
            ) : (
              etkinTablolar.map((t) => (
                <KararTablosuKarti key={t.id} tablo={t} kriterler={kriterler} guncellendi={tabloGuncellendi} yenile={yenile} duzenleAcik={t.id === yeniTabloId} />
              ))
            )}
            {eskiTablolar.length > 0 && (
              <details className="kt-eskiler">
                <summary>Yerini yenisi alan tablolar ({eskiTablolar.length})</summary>
                {eskiTablolar.map((t) => (
                  <KararTablosuKarti key={t.id} tablo={t} kriterler={kriterler} guncellendi={tabloGuncellendi} yenile={yenile} />
                ))}
              </details>
            )}
          </section>

          <section aria-labelledby="kt-iliskiler" className="kart kt-bolum-kap" data-testid="iliskiler">
            <h2 id="kt-iliskiler" className="kt-bolum-baslik">
              İlişkiler
            </h2>
            <p className="soluk kucuk">
              Metamorfik ilişki, girdi değişince beklenen çıktının nasıl değişeceğini söyler. Onaylı ilişkiden, onaylı case'lerden deterministik ek case türetilir.
            </p>
            <div className="eylemler kt-iliski-eylem">
              {!yeniIliski && (
                <IslemDugmesi id="kt-yeni-iliski" roller={["analyst"]} tur="ikincil" kucuk disabled={!!taslakNedeni} title={taslakNedeni} onClick={() => setYeniIliski(true)}>
                  Yeni ilişki
                </IslemDugmesi>
              )}
            </div>
            {yeniIliski && (
              <div className="iliski">
                <IliskiDuzenleyici
                  requirementId={id}
                  tablolar={y.tablolar}
                  kriterler={kriterler}
                  yenile={yenile}
                  vazgec={() => {
                    setYeniIliski(false);
                    requestAnimationFrame(() => document.getElementById("kt-yeni-iliski")?.focus());
                  }}
                  kaydedildi={(r) => {
                    setYeniIliski(false);
                    listeGuncelle((y) => ({ ...y, iliskiler: y.iliskiler.some((x) => x.id === r.id) ? y.iliskiler : [...y.iliskiler, r] }));
                  }}
                />
              </div>
            )}
            {etkinIliskiler.length === 0 ? (
              <BosDurum baslik="Bu gereksinim için ilişki yok.">İlişkiler AI taslağıyla gelir ya da “Yeni ilişki” ile elle eklenir.</BosDurum>
            ) : (
              etkinIliskiler.map((r) => <IliskiKarti key={r.id} iliski={r} tablolar={y.tablolar} kriterler={kriterler} guncellendi={iliskiGuncellendi} yenile={yenile} />)
            )}
            {eskiIliskiler.length > 0 && (
              <details className="kt-eskiler">
                <summary>Yerini yenisi alan ilişkiler ({eskiIliskiler.length})</summary>
                {eskiIliskiler.map((r) => (
                  <IliskiKarti key={r.id} iliski={r} tablolar={y.tablolar} kriterler={kriterler} guncellendi={iliskiGuncellendi} yenile={yenile} />
                ))}
              </details>
            )}
            <EkCaseTuret requirementId={id} iliskiler={y.iliskiler} caseler={caseler.veri ?? []} turetildi={() => void caseler.yenile(true)} />
          </section>
        </>
      )}
    </>
  );
}

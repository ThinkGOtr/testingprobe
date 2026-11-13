// "Tasarım modeli" paneli (011 F3, iki tur): gereksinim detayında, model üretimi/onayı aşamasında
// ve sonrasında. Veri `GET /requirements/{id}/design-model`. Kararlar `POST /design-models/{id}/decision`
// (görülen içerik hash'i zorunlu; Constitution I). K20/D1: onay yanıtı `tur2` taşıyorsa case üretimi
// (tur 2) otomatik başlamıştır; alan yoksa (eski core) onaylı modelden case üretimi elle:
// `POST /requirements/{id}/generate-cases {kip:"iki_tur"}` ("Case'leri üret").
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { GereksinimDetay } from "../api/types";
import type { ModelRetNedeni } from "../api/tasarimModeliTipleri";
import type { DesignModel, TasarimModeliKaydi } from "../api/tasarimModeliTipleri";
import { useIslem, useVeri } from "../hooks";
import { MODEL_RET_NEDENI, RET_NEDENI } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { MODEL_DURUMU, tur2Bildirimi, YER_TUTUCU_NEDENI, yerTutucuModelMi, type Tur2Bilgisi } from "../lib/tasarimModeli";
import { useBildirim } from "./Bildirim";
import { TasarimModeliDuzenleyici } from "./TasarimModeliDuzenleyici";
import { TasarimModeliTablolari } from "./TasarimModeliTablolari";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaIciOnay, Uyari, Yukleniyor } from "./ui";

export const TASARIM_MODELI_BOLUMU = "tasarim-modeli";
/** Panelin her zaman göründüğü gereksinim durumları (diğerlerinde yalnız model varsa). */
export const MODEL_ASAMASI = new Set(["modeling", "model_ready"]);

export function TasarimModeliPaneli({
  g,
  yenile,
  gorunurDegisti,
}: {
  g: GereksinimDetay;
  yenile: () => void;
  /** Panel çizildi mi (bölüm gezgini yalnız görünen bölümü listeler). */
  gorunurDegisti?: (gorunur: boolean) => void;
}) {
  const asamada = MODEL_ASAMASI.has(g.durum);
  // Durum değişince (model üretildi, onaylandı, case üretimi başladı) yeniden okunur.
  const veri = useVeri(() => api.tasarimModeli(g.id), [g.id, g.durum]);
  const islem = useIslem();
  const bildir = useBildirim();
  const [kip, setKip] = useState<"goster" | "duzelt" | "reddet">("goster");
  const [retNedeni, setRetNedeni] = useState<ModelRetNedeni>("missing_ac");
  const [gerekce, setGerekce] = useState("");
  const [yenidenOnay, setYenidenOnay] = useState(false);
  // Son onay yanıtının tur 2 bilgisi (D1); null: alan yok (eski core) ya da henüz onay verilmedi.
  const [tur2, setTur2] = useState<Tur2Bilgisi | null>(null);

  const y = veri.veri;
  const gorunur = asamada || !!y?.model;
  useEffect(() => {
    gorunurDegisti?.(gorunur);
  }, [gorunur, gorunurDegisti]);
  // Model aşaması dışında ve kayıt yoksa (tek turla üretilmiş gereksinim, eski core) panel çizilmez.
  if (!gorunur) return null;
  const baslik = "Tasarım modeli (iki tur)";
  if (veri.yukleniyor && !y) {
    return (
      <Kart baslik={baslik} id={TASARIM_MODELI_BOLUMU}>
        <Yukleniyor />
      </Kart>
    );
  }
  if (veri.hata && !y) {
    return (
      <Kart baslik={baslik} id={TASARIM_MODELI_BOLUMU}>
        <HataKutusu hata={veri.hata} kaynak={veri.hataNesnesi} yenile={() => void veri.yenile()} />
      </Kart>
    );
  }
  const m: TasarimModeliKaydi | null = y?.model ?? null;

  async function eylem<T>(fn: () => Promise<T>, basari: string | ((s: T) => string)) {
    const s = await islem.calistir(fn, { cakismada: () => void veri.yenile(true) });
    if (s !== undefined) {
      bildir(typeof basari === "function" ? basari(s) : basari);
      setKip("goster");
      setYenidenOnay(false);
      void veri.yenile(true);
      yenile();
    }
  }

  const karar = (k: "approve" | "edit" | "reject", ek: { icerik?: DesignModel; ret_nedeni?: ModelRetNedeni; gerekce?: string } = {}) =>
    m &&
    eylem(
      () => api.tasarimModeliKarari(m.id, { karar: k, icerik_hash: m.icerik_hash, ...ek }),
      (s) => {
        setTur2(s.tur2);
        // "Düzelt" düzenlenmiş içeriği kaydeder VE modeli onaylar (core edit kararı = düzeltilerek onay).
        const temel =
          k === "reject" ? "Tasarım modeli reddedildi." : k === "edit" ? "Düzeltme kaydedildi ve model onaylandı." : "Tasarım modeli onaylandı.";
        if (k === "reject" || !s.tur2) return temel;
        if (s.tur2.basladi) return `${temel} ${tur2Bildirimi(s.tur2)}`;
        return `${temel} Case üretimi otomatik başlatılamadı${s.tur2.mesaj ? `: ${s.tur2.mesaj}` : ""}; "Case'leri üret" ile başlatın.`;
      },
    );

  const taslak = m?.durum === "draft";
  // REPLAY-MISS: kayıtlı çıktı yokken kurulan yer tutucu iskelet; onaylanamaz (düzeltme de onaydır).
  const yerTutucu = yerTutucuModelMi(m);
  const onayEngeli = yerTutucu
    ? YER_TUTUCU_NEDENI
    : m?.onay_engeli ?? (m && m.sorunlar.length > 0 ? "Model kontrolleri ihlal ediliyor; 'Düzelt' ile düzeltin ya da reddedin." : null);
  const yenidenUretilebilir = g.durum === "model_ready" && (!m || m.durum === "rejected" || m.durum === "draft");
  // Tur 2 otomatik başladıysa eski "Case'leri üret" düğmesi gizlenir (alan yoksa ya da başlamadıysa kalır).
  const tur2Basladi = !!tur2?.basladi;
  const caseUretilebilir = !!y?.case_uretimi_hazir && !tur2Basladi;
  const tur2Suruyor = m?.durum === "approved" && (g.durum === "generating" || (tur2Basladi && g.durum === "model_ready"));
  const siradaki = siradakiAdim(g.durum, m, { yerTutucu, caseUretilebilir, tur2Suruyor });

  return (
    <Kart
      baslik={baslik}
      id={TASARIM_MODELI_BOLUMU}
      className={`insan-kapisi ${m?.durum === "approved" ? "kapi-gecti" : "kapi-bekliyor"}`}
      eylemler={
        <>
          {m && <ReplayRozeti mode={m.uretim_modu} />}
          {m && <Cip ton={MODEL_DURUMU[m.durum]?.ton ?? "notr"}>{MODEL_DURUMU[m.durum]?.etiket ?? m.durum}</Cip>}
        </>
      }
    >
      <div data-testid="tasarim-modeli-paneli">
        <p className="soluk kucuk">
          İki tur: model case yazmaz; test koşullarını, seçilen teknikleri ve kapsam öğelerini çıkarır. Onayladığınız model case üretiminin
          tek girdisidir; modelde olmayan davranış için case yazılmaz.
        </p>
        {siradaki && (
          <p className="model-siradaki-adim" data-testid="model-siradaki-adim">
            <strong>Sıradaki adım:</strong> {siradaki}
          </p>
        )}
        {tur2Suruyor && (
          <p className="kucuk" role="status" data-testid="model-tur2-durumu">
            <Cip ton="bilgi">Tur 2</Cip>{" "}
            {tur2Basladi && tur2 ? tur2Bildirimi(tur2) : "Case üretimi sürüyor."} Bitince case'ler Case review'da kararınızı bekler.
          </p>
        )}
        {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
        {g.durum === "modeling" && <Yukleniyor metin="Tasarım modeli üretiliyor… Bitince burada onayınızı bekler." />}
        {!m && g.durum !== "modeling" && <BosDurum baslik={y?.engel ?? "Henüz tasarım modeli yok."} />}
        {m && !m.guncel && (
          <Uyari ton="hata" baslik="Model eski içeriğe ait">
            Gereksinim içeriği bu model üretildikten sonra değişti. Model kullanılamaz; PO teyidinden sonra yeniden üretin.
          </Uyari>
        )}
        {m && yerTutucu && m.durum === "draft" && (
          <div data-testid="model-yer-tutucu">
            <Uyari baslik="Yer tutucu model — onaylanamaz">{YER_TUTUCU_NEDENI}</Uyari>
          </div>
        )}
        {m && (
          <>
            <p className="satir-ogeler kucuk" data-testid="model-ozet">
              <span>Sürüm {m.surum}</span>
              <span>{m.ozet.kosul} koşul</span>
              <span>
                {m.ozet.oge} kapsam öğesi ({m.ozet.gecersiz_oge} geçersiz)
              </span>
              <span>{m.ozet.acik_soru} açık soru</span>
              <span>{m.ozet.varsayim} varsayım</span>
              {m.ozet.model_sorunu > 0 && <span>{m.ozet.model_sorunu} model sorunu</span>}
              <span className="soluk">{tarih(m.olusturma)}</span>
            </p>
            {m.sorunlar.length > 0 && (
              <div data-testid="model-kontrol-sorunlari">
                <Uyari baslik="Model kontrolleri ihlal ediliyor (onaylanamaz)">
                  <ul>
                    {m.sorunlar.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </Uyari>
              </div>
            )}
            {kip === "duzelt" && taslak ? (
              <TasarimModeliDuzenleyici
                ilk={m.icerik}
                calisiyor={islem.calisiyor}
                vazgec={() => setKip("goster")}
                kaydet={(icerik) => void karar("edit", { icerik })}
              />
            ) : (
              <TasarimModeliTablolari m={m.icerik} />
            )}
            {kip === "reddet" && taslak && (
              <form
                className="model-ret"
                data-testid="model-ret-formu"
                onSubmit={(e) => {
                  e.preventDefault();
                  void karar("reject", { ret_nedeni: retNedeni, ...(gerekce.trim() ? { gerekce: gerekce.trim() } : {}) });
                }}
              >
                <label>
                  Ret nedeni{" "}
                  <select value={retNedeni} onChange={(e) => setRetNedeni(e.target.value as ModelRetNedeni)}>
                    {(Object.keys(MODEL_RET_NEDENI) as ModelRetNedeni[]).map((r) => (
                      <option key={r} value={r}>
                        {MODEL_RET_NEDENI[r]}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Gerekçe <input value={gerekce} onChange={(e) => setGerekce(e.target.value)} maxLength={2000} />
                </label>
                <div className="satir-ogeler">
                  <button type="submit" className="dugme dugme-birincil" disabled={islem.calisiyor}>
                    Reddi kaydet
                  </button>
                  <button type="button" className="dugme dugme-ikincil" onClick={() => setKip("goster")}>
                    Vazgeç
                  </button>
                </div>
              </form>
            )}
            {m.kararlar.length > 0 && (
              <p className="kucuk soluk" data-testid="model-kararlar">
                {m.kararlar.map((k, i) => (
                  <span key={i}>
                    {i > 0 && " · "}
                    {k.karar === "approve" ? "Onay" : k.karar === "edit" ? "Düzeltilerek onay" : "Ret"} — {k.kullanici ?? "—"} ({tarih(k.zaman)})
                    {k.ret_nedeni && `: ${(MODEL_RET_NEDENI as Record<string, string>)[k.ret_nedeni] ?? (RET_NEDENI as Record<string, string>)[k.ret_nedeni] ?? k.ret_nedeni}`}
                    {k.gerekce && ` — ${k.gerekce}`}
                  </span>
                ))}
              </p>
            )}
          </>
        )}
        {/* Uzun tablolarda eylemler görünür kalsın: panelin altında yapışkan çubuk (UX-8). */}
        <div className="satir-ogeler model-eylemler model-eylemler-yapiskan">
          {m && taslak && kip === "goster" && (
            <>
              <IslemDugmesi
                izin="design_model.decide"
                disabled={!!onayEngeli || !m.guncel}
                title={onayEngeli ?? (!m.guncel ? "Model eski içeriğe ait" : "Model onaylanır; ardından case'ler yalnız bu modelden otomatik üretilir")}
                calisiyor={islem.calisiyor}
                onClick={() => void karar("approve")}
              >
                Modeli onayla
              </IslemDugmesi>
              <IslemDugmesi
                izin="design_model.decide"
                tur="ikincil"
                disabled={!m.guncel || yerTutucu}
                title={yerTutucu ? YER_TUTUCU_NEDENI : !m.guncel ? "Model eski içeriğe ait" : "Alanları düzeltip kaydettiğinizde model onaylanır"}
                onClick={() => setKip("duzelt")}
              >
                Düzelt
              </IslemDugmesi>
              <IslemDugmesi izin="design_model.decide" tur="ikincil" disabled={!m.guncel} onClick={() => setKip("reddet")}>
                Reddet
              </IslemDugmesi>
            </>
          )}
          {caseUretilebilir && (
            <IslemDugmesi
              id="model-case-uret"
              izin="case.generate"
              calisiyor={islem.calisiyor}
              title="Onaylı tasarım modelinden case üretilir (tur 2)"
              onClick={() => void eylem(() => api.caseUret(g.id, "iki_tur"), "Onaylı modelden case üretimi başlatıldı.")}
            >
              Case'leri üret
            </IslemDugmesi>
          )}
          {yenidenUretilebilir && !(m && taslak && kip !== "goster") && (
            <IslemDugmesi
              id="model-yeniden-uret"
              izin="case.generate"
              tur={m?.durum === "rejected" || yerTutucu ? "birincil" : "ikincil"}
              disabled={yenidenOnay}
              nedenGizli
              aria-expanded={yenidenOnay}
              title={m?.durum === "rejected" ? "Reddedilen modelin yerine yeni model üretilir" : "Mevcut taslak geçersiz olur, yeni model üretilir"}
              onClick={() => setYenidenOnay(true)}
            >
              Modeli yeniden üret…
            </IslemDugmesi>
          )}
        </div>
        {yenidenOnay && yenidenUretilebilir && (
          <SayfaIciOnay
            testId="model-yeniden-uret-onayi"
            baslik="Model yeniden üretilsin mi?"
            onayMetni="Evet, yeniden üret"
            calisiyor={islem.calisiyor}
            onayla={() => void eylem(() => api.tasarimModeliUret(g.id), "Tasarım modeli yeniden üretiliyor.")}
            vazgec={() => {
              setYenidenOnay(false);
              requestAnimationFrame(() => document.getElementById("model-yeniden-uret")?.focus());
            }}
          >
            <p>
              {m?.durum === "rejected"
                ? "Reddedilen modelin yerine yeni bir model üretilir ve onayınızı bekler."
                : m
                  ? `Mevcut taslak (sürüm ${m.surum}) geçersiz olur; yeni model üretilir ve yeniden onayınızı bekler.`
                  : "Yeni bir tasarım modeli üretilir ve onayınızı bekler."}
            </p>
          </SayfaIciOnay>
        )}
        {y && y.gecmis.length > 1 && (
          <details className="kucuk" data-testid="model-gecmis">
            <summary>Önceki sürümler ({y.gecmis.length - 1})</summary>
            <ul>
              {y.gecmis
                .filter((h) => h.id !== m?.id)
                .map((h) => (
                  <li key={h.id}>
                    Sürüm {h.surum} · {MODEL_DURUMU[h.durum]?.etiket ?? h.durum} · {tarih(h.olusturma)}
                  </li>
                ))}
            </ul>
          </details>
        )}
      </div>
    </Kart>
  );
}

/** Paneldeki "Sıradaki adım" satırı (UX-8): Testçinin şimdi ne yapacağı; adım yoksa null. */
export function siradakiAdim(
  durum: string,
  m: Pick<TasarimModeliKaydi, "durum" | "guncel" | "sorunlar"> | null,
  d: { yerTutucu: boolean; caseUretilebilir: boolean; tur2Suruyor: boolean },
): string | null {
  if (durum === "modeling") return "model üretiliyor; bitince burada inceleyip onaylayın.";
  if (!m) return null;
  if (!m.guncel) return "PO teyidinden sonra modeli yeniden üretin (bu model eski içeriğe ait).";
  if (m.durum === "draft") {
    if (d.yerTutucu) return "modeli yeniden üretin — yer tutucu model onaylanamaz.";
    if (m.sorunlar.length > 0) return "'Düzelt' ile model kontrollerini giderin ya da modeli reddedin.";
    return "modeli inceleyip onaylayın — onaydan sonra case'ler otomatik üretilir.";
  }
  if (m.durum === "rejected") return "modeli yeniden üretin.";
  if (m.durum === "approved") {
    if (d.tur2Suruyor) return "case'ler üretiliyor (tur 2); bitince Case review'da inceleyin.";
    if (d.caseUretilebilir) return "'Case'leri üret' ile onaylı modelden case üretin.";
    if (durum === "cases_ready") return "case'leri Case review'da inceleyin.";
  }
  return null;
}

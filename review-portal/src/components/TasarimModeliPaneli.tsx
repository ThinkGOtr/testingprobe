// "Tasarım modeli" paneli (011 F3, iki tur): gereksinim detayında, model üretimi/onayı aşamasında
// ve sonrasında. Veri `GET /requirements/{id}/design-model`. Kararlar `POST /design-models/{id}/decision`
// (görülen içerik hash'i zorunlu; Constitution I). Onaylı modelden case üretimi
// `POST /requirements/{id}/generate-cases {kip:"iki_tur"}`.
import { useState } from "react";
import { api } from "../api/client";
import type { GereksinimDetay, RetNedeni } from "../api/types";
import type { DesignModel, TasarimModeliKaydi } from "../api/tasarimModeliTipleri";
import { useIslem, useVeri } from "../hooks";
import { RET_NEDENI } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { MODEL_DURUMU } from "../lib/tasarimModeli";
import { useBildirim } from "./Bildirim";
import { TasarimModeliDuzenleyici } from "./TasarimModeliDuzenleyici";
import { TasarimModeliTablolari } from "./TasarimModeliTablolari";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, Uyari, Yukleniyor } from "./ui";

export const TASARIM_MODELI_BOLUMU = "tasarim-modeli";
/** Panelin her zaman göründüğü gereksinim durumları (diğerlerinde yalnız model varsa). */
export const MODEL_ASAMASI = new Set(["modeling", "model_ready"]);

export function TasarimModeliPaneli({ g, yenile }: { g: GereksinimDetay; yenile: () => void }) {
  const asamada = MODEL_ASAMASI.has(g.durum);
  // Durum değişince (model üretildi, onaylandı, case üretimi başladı) yeniden okunur.
  const veri = useVeri(() => api.tasarimModeli(g.id), [g.id, g.durum]);
  const islem = useIslem();
  const bildir = useBildirim();
  const [kip, setKip] = useState<"goster" | "duzelt" | "reddet">("goster");
  const [retNedeni, setRetNedeni] = useState<RetNedeni>("missing_ac");
  const [gerekce, setGerekce] = useState("");

  const y = veri.veri;
  // Model aşaması dışında ve kayıt yoksa (tek turla üretilmiş gereksinim, eski core) panel çizilmez.
  if (!asamada && (!y || !y.model)) return null;
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

  async function eylem<T>(fn: () => Promise<T>, basari: string) {
    const s = await islem.calistir(fn, { cakismada: () => void veri.yenile(true) });
    if (s !== undefined) {
      bildir(basari);
      setKip("goster");
      void veri.yenile(true);
      yenile();
    }
  }

  const karar = (k: "approve" | "edit" | "reject", ek: { icerik?: DesignModel; ret_nedeni?: RetNedeni; gerekce?: string } = {}) =>
    m &&
    eylem(
      () => api.tasarimModeliKarari(m.id, { karar: k, icerik_hash: m.icerik_hash, ...ek }),
      k === "reject" ? "Tasarım modeli reddedildi." : "Tasarım modeli onaylandı.",
    );

  const taslak = m?.durum === "draft";
  const onayEngeli = m?.onay_engeli ?? (m && m.sorunlar.length > 0 ? "Model kontrolleri ihlal ediliyor; 'Düzelt' ile düzeltin ya da reddedin." : null);
  const yenidenUretilebilir = g.durum === "model_ready" && (!m || m.durum === "rejected" || m.durum === "draft");
  const caseUretilebilir = !!y?.case_uretimi_hazir;

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
        {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
        {g.durum === "modeling" && <Yukleniyor metin="Tasarım modeli üretiliyor… Bitince burada onayınızı bekler." />}
        {!m && g.durum !== "modeling" && <BosDurum baslik={y?.engel ?? "Henüz tasarım modeli yok."} />}
        {m && !m.guncel && (
          <Uyari ton="hata" baslik="Model eski içeriğe ait">
            Gereksinim içeriği bu model üretildikten sonra değişti. Model kullanılamaz; PO teyidinden sonra yeniden üretin.
          </Uyari>
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
                  <select value={retNedeni} onChange={(e) => setRetNedeni(e.target.value as RetNedeni)}>
                    {(Object.keys(RET_NEDENI) as RetNedeni[]).map((r) => (
                      <option key={r} value={r}>
                        {RET_NEDENI[r]}
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
                    {k.ret_nedeni && `: ${RET_NEDENI[k.ret_nedeni] ?? k.ret_nedeni}`}
                    {k.gerekce && ` — ${k.gerekce}`}
                  </span>
                ))}
              </p>
            )}
          </>
        )}
        <div className="satir-ogeler model-eylemler">
          {m && taslak && kip === "goster" && (
            <>
              <IslemDugmesi
                roller={["analyst"]}
                disabled={!!onayEngeli || !m.guncel}
                title={onayEngeli ?? (!m.guncel ? "Model eski içeriğe ait" : "Model onaylanır; ardından yalnız bu modelden case üretilir")}
                calisiyor={islem.calisiyor}
                onClick={() => void karar("approve")}
              >
                Modeli onayla
              </IslemDugmesi>
              <IslemDugmesi roller={["analyst"]} tur="ikincil" disabled={!m.guncel} onClick={() => setKip("duzelt")}>
                Düzelt
              </IslemDugmesi>
              <IslemDugmesi roller={["analyst"]} tur="ikincil" disabled={!m.guncel} onClick={() => setKip("reddet")}>
                Reddet
              </IslemDugmesi>
            </>
          )}
          {caseUretilebilir && (
            <IslemDugmesi
              id="model-case-uret"
              roller={["analyst"]}
              calisiyor={islem.calisiyor}
              title="Onaylı tasarım modelinden case üretilir (tur 2)"
              onClick={() => void eylem(() => api.caseUret(g.id, "iki_tur"), "Onaylı modelden case üretimi başlatıldı.")}
            >
              Case'leri üret
            </IslemDugmesi>
          )}
          {yenidenUretilebilir && !(m && taslak && kip !== "goster") && (
            <IslemDugmesi
              roller={["analyst"]}
              tur={m?.durum === "rejected" ? "birincil" : "ikincil"}
              title={m?.durum === "rejected" ? "Reddedilen modelin yerine yeni model üretilir" : "Mevcut taslak geçersiz olur, yeni model üretilir"}
              onClick={() => void eylem(() => api.tasarimModeliUret(g.id), "Tasarım modeli yeniden üretiliyor.")}
            >
              Modeli yeniden üret
            </IslemDugmesi>
          )}
        </div>
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

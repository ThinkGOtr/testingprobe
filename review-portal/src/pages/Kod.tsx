import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { SCRIPT_DURUMU, scriptIsareti } from "../lib/etiketler";
import { YEREL_SINIF } from "../lib/kapi";
import { tarih } from "../lib/format";
import { PlatformRozeti, PlatformSecici } from "../components/Platform";
import { PLATFORM_ETIKETI, type Platform } from "../lib/platform";
import type { Script } from "../api/types";

export const OTOMATIK_TETIK_ACIKLAMA = "Bu test, case onaylanınca otomatik kod üretimiyle başlatıldı (Otomasyon ayarı).";
export const OTOMATIK_TETIK_ROZETI = "Onay sonrası otomatik";
export const VERI_DEGISTI_METNI = "Test verisi değişti; yeniden üretin";

const SUREN_DURUMLAR = new Set(["pending", "verifying", "checking"]);
const scriptPlatformu = (s: Pick<Script, "platform">) => (s.platform === undefined ? "web" : s.platform);

/** Aynı case + platform için bu script'ten sonra üretilmiş başka script var mı (eski kayıt). */
export function dahaYeniScriptVar(s: Script, tum: readonly Script[]): boolean {
  const p = scriptPlatformu(s);
  return tum.some(
    (o) => o.id !== s.id && scriptPlatformu(o) === p && Date.parse(o.olusturma) > Date.parse(s.olusturma) && o.case_ids.some((c) => s.case_ids.includes(c)),
  );
}

/**
 * "Test verisi değişti" uyarısı ve yeniden üretim yalnız güncel kayıtta anlamlı: süren üretim
 * (pending/verifying/checking) bitmeden, kapatılmış ya da yerine yenisi üretilmiş eski kayıtta gösterilmez.
 */
export function veriDegistiGecerli(s: Script, tum: readonly Script[]): boolean {
  return !!s.veri_degisti && s.durum !== "closed" && !SUREN_DURUMLAR.has(s.durum) && !dahaYeniScriptVar(s, tum);
}

/** Değeri değişen anahtarların kısa metni (değer/özet gösterilmez). */
export const veriDegisenMetni = (s: Pick<Script, "veri_degisen">) =>
  s.veri_degisen && s.veri_degisen.length > 0 ? `Değeri değişen test verisi: ${s.veri_degisen.join(", ")}` : "Üretimde kullanılan test verisinin değeri katalogda değişti.";

/** 013 §3.5: otomatik tetik rozeti ve "test verisi değişti" işareti (core göndermediyse hiçbiri). */
export function OtomasyonIsaretleri({ s, veriUyarisi = !!s.veri_degisti }: { s: Pick<Script, "tetik" | "veri_degisti" | "veri_degisen">; veriUyarisi?: boolean }) {
  return (
    <>
      {s.tetik === "otomatik" && (
        <Cip ton="bilgi" title={OTOMATIK_TETIK_ACIKLAMA}>
          {OTOMATIK_TETIK_ROZETI}
        </Cip>
      )}
      {veriUyarisi && (
        <Cip ton="uyari" title={veriDegisenMetni(s)}>
          {VERI_DEGISTI_METNI}
        </Cip>
      )}
    </>
  );
}

export function Kod() {
  const scriptler = useVeri(() => api.scriptler(), []);
  const caseler = useVeri(() => api.caseler(), []);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [kapatilanlar, setKapatilanlar] = useState(false);
  // 009: üretimin hedef platformu (varsayılan Web). Aynı case her platformda ayrı script/PR alır.
  const [platform, setPlatform] = useState<Platform>("web");
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => {
    void scriptler.yenile(true);
  });
  useOlay(sessiz, ["agent.step", "pr.opened", "ci.status", "script.updated", "case.updated"]);

  // Kapatılmış (değişiklik istendi / reddedildi / yerine geçildi) test case'i yeniden üretime açar:
  // çekirdek kapalı script'ten sonra yeni üretimi kabul eder.
  // Aday: seçili platformda açık script'i olmayan onaylı case (başka platformdaki script'i engel değil).
  const scriptliCaseler = new Set(
    (scriptler.veri ?? []).filter((s) => s.durum !== "closed" && (s.platform === undefined ? "web" : s.platform) === platform).flatMap((s) => s.case_ids),
  );
  const adaylar = (caseler.veri ?? []).filter((c) => (c.durum === "approved" || c.durum === "published") && !scriptliCaseler.has(c.id));
  // Platform değişince başka platformda artık aday olmayan seçimler sayılmaz/gönderilmez.
  const seciliAdaylar = adaylar.filter((c) => secili.has(c.id)).map((c) => c.id);
  const tumScriptler = scriptler.veri ?? [];
  const kapaliSayisi = tumScriptler.filter((s) => s.durum === "closed").length;
  // Yeniden üretimle kapatılan eski kayıtlar varsayılan olarak gizlenir (aynı test iki kez görünmesin).
  const gorunen = kapatilanlar ? tumScriptler : tumScriptler.filter((s) => s.durum !== "closed");

  const yenidenUret = async (caseIds: string[], p: Platform) => {
    const s = await islem.calistir(() => api.kodUret(caseIds, p));
    if (s) {
      bildir(s.mesaj ?? "Yeniden üretim başladı; eski kayıt kapatılır.");
      void scriptler.yenile(true);
    }
  };

  return (
    <>
      <SayfaBasligi
        baslik="Kod üretimi"
        aciklama="Onaylı case'ler seçilen platformda adım adım doğrulanır (Web: Playwright MCP; Android, iOS, Windows: Appium), page object'lere eşlenir ve şablondan teste dönüşür (Web: TypeScript, uygulamalar: Java). Model kod yazmaz; yerel kontrol yeşilse bot ayrı dalda PR açar."
      />

      <Kart
        baslik="Kodu üretilecek onaylı case'ler"
        eylemler={
          <IslemDugmesi
            roller={["engineer"]}
            disabled={seciliAdaylar.length === 0}
            calisiyor={islem.calisiyor}
            onClick={async () => {
              const s = await islem.calistir(() => api.kodUret(seciliAdaylar, platform));
              if (s) {
                bildir(s.mesaj ?? "Kod üretimi başladı.");
                setSecili(new Set());
                void scriptler.yenile(true);
                void caseler.yenile(true);
              }
            }}
          >
            Seçilenler için kod üret ({seciliAdaylar.length}){platform !== "web" && ` · ${PLATFORM_ETIKETI[platform]}`}
          </IslemDugmesi>
        }
      >
        <PlatformSecici
          etiket="Hedef platform"
          deger={platform}
          degistir={(p) => {
            // Bir platform için seçilen case başka platforma taşınmaz: seçim temizlenir.
            setPlatform(p);
            setSecili(new Set());
          }}
          disabled={islem.calisiyor}
          aciklamali
          ipucu="Aynı onaylı case her platform için ayrı test ve ayrı PR olur; listede yalnızca bu platformda kodu üretilmemiş case'ler görünür."
        />
        {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
        {caseler.yukleniyor && !caseler.veri ? (
          <Yukleniyor />
        ) : caseler.hata && !caseler.veri ? (
          <HataKutusu hata={caseler.hata} kaynak={caseler.hataNesnesi} yenile={() => void caseler.yenile()} />
        ) : adaylar.length === 0 ? (
          <BosDurum baslik={platform === "web" ? "Kodu üretilmemiş onaylı case yok." : `${PLATFORM_ETIKETI[platform]} için kodu üretilmemiş onaylı case yok.`} />
        ) : (
          <ul className="secim-liste">
            {adaylar.map((c) => (
              <li key={c.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={secili.has(c.id)}
                    onChange={() =>
                      setSecili((s) => {
                        const y = new Set(s);
                        if (y.has(c.id)) y.delete(c.id);
                        else y.add(c.id);
                        return y;
                      })
                    }
                  />
                  <span className="mono">{c.jira_test_key ?? `${c.jira_key ?? "FT"} #${c.sira_no}`}</span> {c.icerik.title}
                </label>
                <div className="kucuk soluk secim-alt">Beklenen: {c.icerik.expected_result}</div>
              </li>
            ))}
          </ul>
        )}
      </Kart>

      <Kart
        baslik="Üretilen testler"
        eylemler={
          kapaliSayisi > 0 && (
            <label className="kucuk">
              <input type="checkbox" checked={kapatilanlar} onChange={(e) => setKapatilanlar(e.target.checked)} /> Kapatılanları göster ({kapaliSayisi})
            </label>
          )
        }
      >
        {scriptler.yukleniyor && !scriptler.veri ? (
          <Yukleniyor />
        ) : scriptler.hata && !scriptler.veri ? (
          <HataKutusu hata={scriptler.hata} kaynak={scriptler.hataNesnesi} yenile={() => void scriptler.yenile()} />
        ) : tumScriptler.length === 0 ? (
          <BosDurum baslik="Henüz üretilen test yok." />
        ) : gorunen.length === 0 ? (
          <BosDurum baslik="Açık üretilen test yok; kapatılanlar gizli." />
        ) : (
          <div className="tablo-sarici kod-tablosu" tabIndex={0} role="region" aria-label="Üretilen testler tablosu">
            <table className="tablo">
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  <th scope="col">Durum</th>
                  <th scope="col">PR</th>
                  <th scope="col">Kırarak doğrula</th>
                  <th scope="col">Oluşturma</th>
                  <th scope="col">
                    <span className="gorunmez">Eylem</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {gorunen.map((s) => {
                  const d = SCRIPT_DURUMU[s.durum] ?? { etiket: s.durum, ton: "notr" as const };
                  const isaret = scriptIsareti(s);
                  const sinif = s.yerel_sinif && s.yerel_sinif !== "gecti" ? YEREL_SINIF[s.yerel_sinif] : null;
                  return (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/kod/${encodeURIComponent(s.id)}`} className="satir-baglanti">
                          {s.baslik}
                        </Link>
                        <div className="satir-ogeler kucuk">
                          <PlatformRozeti platform={s.platform} />
                          <span className="mono soluk">{s.dosya_yolu}</span>
                        </div>
                      </td>
                      <td>
                        <span className="satir-ogeler">
                          <Cip ton={d.ton}>{d.etiket}</Cip>
                          {isaret && (
                            <Cip ton={isaret.ton} title={isaret.aciklama}>
                              {isaret.etiket}
                            </Cip>
                          )}
                          {sinif && (
                            <Cip ton={sinif.ton} title={sinif.aciklama}>
                              {sinif.etiket}
                            </Cip>
                          )}
                          <ReplayRozeti mode={s.mode} />
                          <OtomasyonIsaretleri s={s} veriUyarisi={veriDegistiGecerli(s, tumScriptler)} />
                        </span>
                      </td>
                      <td>{s.pr ? <span className="mono">#{s.pr.number} · {s.pr.durum === "merged" ? "birleşti" : s.pr.durum === "open" ? "açık" : "kapalı"}</span> : "—"}</td>
                      <td>
                        {s.break_verify.durum === "passed"
                          ? "✓ hata yakalıyor"
                          : s.break_verify.durum === "weak"
                            ? s.pr?.durum === "merged"
                              ? "Kırma etkilemedi · kabulle birleşti"
                              : "Kırma etkilemedi · kabul gerekli"
                            : s.break_verify.durum === "running"
                              ? "Sürüyor…"
                              : s.break_verify.durum === "failed"
                                ? "Tamamlanamadı"
                                : "—"}
                      </td>
                      <td className="tek-satir">{tarih(s.olusturma)}</td>
                      <td>
                        {/* Defect adayının testi doğru (uygulama farklı davranıyor): yeniden üretim önerilmez, karar triage'da. */}
                        {/* 013: test verisi değişen güncel script de yeniden üretilebilir (süren / eski kayıtta değil). */}
                        {(s.durum === "blocked" || s.durum === "failed" || veriDegistiGecerli(s, tumScriptler)) &&
                          s.case_ids.length > 0 &&
                          s.platform !== null &&
                          !(s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate") && (
                          <IslemDugmesi
                            roller={["engineer"]}
                            tur="ikincil"
                            calisiyor={islem.calisiyor}
                            title={
                              s.durum === "blocked" || s.durum === "failed"
                                ? "Aynı onaylı case için kodu yeniden üretir; bu kayıt kapatılır."
                                : s.durum === "merged"
                                  ? "Kodu güncel test verisiyle yeniden üretir; birleşmiş kayıt değişmez, yeni PR açılır."
                                  : "Kodu güncel test verisiyle yeniden üretir; bu kayıt ve açık PR'ı kapatılır, yenisi açılır."
                            }
                            onClick={() => yenidenUret(s.case_ids, s.platform === undefined ? "web" : (s.platform as Platform))}
                          >
                            Yeniden üret
                          </IslemDugmesi>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Kart>
    </>
  );
}

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

export function Kod() {
  const scriptler = useVeri(() => api.scriptler(), []);
  const caseler = useVeri(() => api.caseler(), []);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [kapatilanlar, setKapatilanlar] = useState(false);
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => {
    void scriptler.yenile(true);
  });
  useOlay(sessiz, ["agent.step", "pr.opened", "ci.status", "script.updated", "case.updated"]);

  // Kapatılmış (değişiklik istendi / reddedildi / yerine geçildi) test case'i yeniden üretime açar:
  // çekirdek kapalı script'ten sonra yeni üretimi kabul eder.
  const scriptliCaseler = new Set((scriptler.veri ?? []).filter((s) => s.durum !== "closed").flatMap((s) => s.case_ids));
  const adaylar = (caseler.veri ?? []).filter((c) => (c.durum === "approved" || c.durum === "published") && !scriptliCaseler.has(c.id));
  const tumScriptler = scriptler.veri ?? [];
  const kapaliSayisi = tumScriptler.filter((s) => s.durum === "closed").length;
  // Yeniden üretimle kapatılan eski kayıtlar varsayılan olarak gizlenir (aynı test iki kez görünmesin).
  const gorunen = kapatilanlar ? tumScriptler : tumScriptler.filter((s) => s.durum !== "closed");

  const yenidenUret = async (caseIds: string[]) => {
    const s = await islem.calistir(() => api.kodUret(caseIds));
    if (s) {
      bildir(s.mesaj ?? "Yeniden üretim başladı; eski kayıt kapatılır.");
      void scriptler.yenile(true);
    }
  };

  return (
    <>
      <SayfaBasligi
        baslik="Kod üretimi"
        aciklama="Onaylı case'ler uygulamada adım adım doğrulanır (Playwright MCP), page object'lere eşlenir ve şablondan TypeScript teste dönüşür. Model kod yazmaz; yerel kontrol yeşilse bot ayrı dalda PR açar."
      />

      <Kart
        baslik="Kodu üretilecek onaylı case'ler"
        eylemler={
          <IslemDugmesi
            roller={["engineer"]}
            disabled={secili.size === 0}
            calisiyor={islem.calisiyor}
            onClick={async () => {
              const s = await islem.calistir(() => api.kodUret([...secili]));
              if (s) {
                bildir(s.mesaj ?? "Kod üretimi başladı.");
                setSecili(new Set());
                void scriptler.yenile(true);
                void caseler.yenile(true);
              }
            }}
          >
            Seçilenler için kod üret ({secili.size})
          </IslemDugmesi>
        }
      >
        {islem.hata && <HataKutusu hata={islem.hata} />}
        {caseler.yukleniyor && !caseler.veri ? (
          <Yukleniyor />
        ) : caseler.hata && !caseler.veri ? (
          <HataKutusu hata={caseler.hata} yenile={() => void caseler.yenile()} />
        ) : adaylar.length === 0 ? (
          <BosDurum baslik="Kodu üretilmemiş onaylı case yok." />
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
          <HataKutusu hata={scriptler.hata} yenile={() => void scriptler.yenile()} />
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
                        <div className="mono kucuk soluk">{s.dosya_yolu}</div>
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
                      <td>{tarih(s.olusturma)}</td>
                      <td>
                        {/* Defect adayının testi doğru (uygulama farklı davranıyor): yeniden üretim önerilmez, karar triage'da. */}
                        {(s.durum === "blocked" || s.durum === "failed") &&
                          s.case_ids.length > 0 &&
                          !(s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate") && (
                          <IslemDugmesi
                            roller={["engineer"]}
                            tur="ikincil"
                            calisiyor={islem.calisiyor}
                            title="Aynı onaylı case için kodu yeniden üretir; bu kayıt kapatılır."
                            onClick={() => yenidenUret(s.case_ids)}
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

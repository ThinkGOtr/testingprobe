import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { SCRIPT_DURUMU, scriptIsareti } from "../lib/etiketler";
import { tarih } from "../lib/format";

export function Kod() {
  const scriptler = useVeri(() => api.scriptler(), []);
  const caseler = useVeri(() => api.caseler(), []);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => {
    void scriptler.yenile(true);
  });
  useOlay(sessiz, ["agent.step", "pr.opened", "ci.status"]);

  const scriptliCaseler = new Set((scriptler.veri ?? []).flatMap((s) => s.case_ids));
  const adaylar = (caseler.veri ?? []).filter((c) => (c.durum === "approved" || c.durum === "published") && !scriptliCaseler.has(c.id));

  return (
    <>
      <SayfaBasligi
        baslik="Kod üretimi"
        aciklama="Onaylı case'ler uygulamada adım adım doğrulanır, page object'lere eşlenir ve şablondan TypeScript teste dönüşür. Model kod yazmaz."
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
              </li>
            ))}
          </ul>
        )}
      </Kart>

      <Kart baslik="Üretilen testler">
        {scriptler.yukleniyor && !scriptler.veri ? (
          <Yukleniyor />
        ) : scriptler.hata && !scriptler.veri ? (
          <HataKutusu hata={scriptler.hata} yenile={() => void scriptler.yenile()} />
        ) : (scriptler.veri ?? []).length === 0 ? (
          <BosDurum baslik="Henüz üretilen test yok." />
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Üretilen testler tablosu">
            <table className="tablo">
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  <th scope="col">Durum</th>
                  <th scope="col">PR</th>
                  <th scope="col">Kırarak doğrula</th>
                  <th scope="col">Oluşturma</th>
                </tr>
              </thead>
              <tbody>
                {(scriptler.veri ?? []).map((s) => {
                  const d = SCRIPT_DURUMU[s.durum] ?? { etiket: s.durum, ton: "notr" as const };
                  const isaret = scriptIsareti(s);
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
                          {isaret && <Cip ton={isaret.ton}>{isaret.etiket}</Cip>}
                          <ReplayRozeti mode={s.mode} />
                        </span>
                      </td>
                      <td>{s.pr ? <span className="mono">#{s.pr.number} · {s.pr.durum === "merged" ? "birleşti" : s.pr.durum === "open" ? "açık" : "kapalı"}</span> : "—"}</td>
                      <td>
                        {s.break_verify.durum === "passed"
                          ? "✓ hata yakalıyor"
                          : s.break_verify.durum === "weak"
                            ? "✗ zayıf test"
                            : s.break_verify.durum === "running"
                              ? "Sürüyor…"
                              : "—"}
                      </td>
                      <td>{tarih(s.olusturma)}</td>
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

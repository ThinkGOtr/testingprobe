import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { AjanAdimi, BreakVerify, ScriptDetay as Detay } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { KodGorunumu } from "../components/KodGorunumu";
import { BosDurum, Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { SCRIPT_DURUMU, scriptIsareti, scriptUretiliyor } from "../lib/etiketler";
import { saat, tarih } from "../lib/format";

const ASAMA_ADI = { baseline: "Bayraksız (yeşil olmalı)", broken: "BREAK_CAMPAIGN=1 (kırmızı olmalı)", restored: "Bayrak kaldırıldı (yeşil olmalı)" } as const;
const SONUC = {
  pending: { etiket: "Bekliyor", ikon: "○" },
  running: { etiket: "Koşuyor", ikon: "◌" },
  passed: { etiket: "Yeşil", ikon: "✓" },
  failed: { etiket: "Kırmızı", ikon: "✗" },
} as const;

export function KirmaZaman({ bv }: { bv: BreakVerify }) {
  return (
    <ol className="kirma-zaman" aria-label="Kırarak doğrulama zaman çizelgesi">
      {bv.asamalar.map((a) => {
        const beklenen = a.ad === "broken" ? "failed" : "passed";
        const uyumlu = a.sonuc === beklenen;
        return (
          <li key={a.ad} className={`kirma-asama kirma-${a.sonuc}`}>
            <span className="kirma-ikon" aria-hidden="true">
              {SONUC[a.sonuc].ikon}
            </span>
            <div>
              <div className="kirma-ad">{ASAMA_ADI[a.ad]}</div>
              <div className="kucuk">
                {SONUC[a.sonuc].etiket}
                {(a.sonuc === "passed" || a.sonuc === "failed") && (uyumlu ? " · beklendiği gibi" : " · beklenmeyen sonuç")}
                {a.run_id && (
                  <>
                    {" · "}
                    <Link to={`/kosular/${encodeURIComponent(a.run_id)}`}>{a.run_id}</Link>
                  </>
                )}
                {a.zaman && <span className="soluk"> · {saat(a.zaman)}</span>}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function AjanAdimlari({ adimlar, canli }: { adimlar: AjanAdimi[]; canli: boolean }) {
  const [secili, setSecili] = useState<number | null>(null);
  const aktif = adimlar.find((a) => a.sira === secili) ?? adimlar[adimlar.length - 1];
  if (adimlar.length === 0) {
    return <BosDurum baslik={canli ? "Ajan başlıyor…" : "Ajan adımı yok."} />;
  }
  return (
    <div className="ajan">
      <ol className="ajan-adimlar" aria-label="Ajan adımları">
        {adimlar.map((a) => (
          <li key={a.sira}>
            <button
              type="button"
              className={`ajan-adim${aktif?.sira === a.sira ? " aktif" : ""}`}
              aria-pressed={aktif?.sira === a.sira}
              onClick={() => setSecili(a.sira)}
            >
              <span className="mono soluk">
                Adım {a.sira}
                {a.step_id && <span title="Case adımı referansı"> · case {a.step_id}</span>}
              </span>
              <span>{a.aciklama}</span>
              <span className="kucuk mono">
                {a.po && a.method ? `${a.po}.${a.method}(${a.args.map((x) => JSON.stringify(x)).join(", ")})` : a.arac}
              </span>
              <span className={`kucuk ${a.verified ? "ok-metin" : "hata-metin"}`}>{a.verified ? "✓ snapshot'ta doğrulandı" : "✗ doğrulanamadı"}</span>
            </button>
          </li>
        ))}
        {canli && (
          <li className="soluk kucuk" role="status">
            <span className="donen donen-kucuk" aria-hidden="true" /> Ajan çalışıyor…
          </li>
        )}
      </ol>
      <figure className="ajan-ekran">
        {aktif?.ekran_goruntusu_url ? (
          <img src={aktif.ekran_goruntusu_url} alt={`Adım ${aktif.sira} ekran görüntüsü: ${aktif.aciklama}`} />
        ) : (
          <div className="ekran-yok">Ekran görüntüsü yok</div>
        )}
        <figcaption className="kucuk soluk">
          Adım {aktif?.sira}
          {aktif?.step_id && ` (case ${aktif.step_id})`} · {aktif?.arac} · {saat(aktif?.zaman)}. Görüntü yalnızca izleme içindir; modele gönderilmez.
        </figcaption>
      </figure>
    </div>
  );
}

export function ScriptDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.script(id), [id]);
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => void v.yenile(true), 300);

  useOlay(
    (o) => {
      if (o.type === "agent.step" && v.veri) {
        const adim = o.data as unknown as AjanAdimi;
        if (typeof adim.sira === "number" && !v.veri.adimlar.some((a) => a.sira === adim.sira)) {
          v.setVeri({ ...v.veri, adimlar: [...v.veri.adimlar, adim] });
        }
        return;
      }
      sessiz();
    },
    ["agent.step", "pr.opened", "ci.status"],
    id,
  );

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />;
  const s: Detay | undefined = v.veri;
  if (!s) return null;
  const d = SCRIPT_DURUMU[s.durum] ?? { etiket: s.durum, ton: "notr" as const };
  const prAcik = s.pr?.durum === "open";
  const mergeHazir = prAcik && !s.zayif_test && s.break_verify.durum === "passed" && s.pr?.ci === "passed";
  const isaret = scriptIsareti(s);
  const uretiliyor = scriptUretiliyor(s.durum);

  async function eylem(fn: () => Promise<unknown>, mesaj: string) {
    // 409 (PR içeriği/head değişti): ekran yeniden yüklenir, kullanıcı yeniden inceler.
    const r = await islem.calistir(fn, { cakismada: () => void v.yenile(true) });
    if (r !== undefined) {
      bildir(mesaj);
      void v.yenile(true);
    }
  }

  return (
    <>
      <SayfaBasligi
        ust={<Link to="/kod">← Kod üretimi</Link>}
        baslik={s.baslik}
        aciklama={
          <span className="satir-ogeler">
            <Cip ton={d.ton}>{d.etiket}</Cip>
            {isaret && <Cip ton={isaret.ton}>{isaret.etiket}</Cip>}
            <ReplayRozeti mode={s.mode} />
            {s.requirement_key && <span className="mono">{s.requirement_key}</span>}
            <span className="soluk">{tarih(s.olusturma)}</span>
          </span>
        }
      />
      {s.hata && <HataKutusu hata={s.hata} />}
      {islem.hata && <HataKutusu hata={islem.hata} />}

      <Kart baslik="Ajan adımları (Playwright MCP)" eylemler={uretiliyor && <Cip ton="bilgi">Canlı</Cip>}>
        <AjanAdimlari adimlar={s.adimlar} canli={uretiliyor} />
      </Kart>

      <div className="iki-sutun">
        <Kart baslik="Pull request">
          {s.pr ? (
            <>
              <p>
                <span className="mono">#{s.pr.number}</span> {s.pr.baslik}
              </p>
              <p className="satir-ogeler">
                <Cip ton={s.pr.durum === "merged" ? "basari" : s.pr.durum === "open" ? "vurgu" : "notr"}>
                  {s.pr.durum === "merged" ? "Birleşti" : s.pr.durum === "open" ? "Açık" : "Kapalı"}
                </Cip>
                <Cip ton={s.pr.ci === "passed" ? "basari" : s.pr.ci === "failed" ? "hata" : "bilgi"}>
                  CI: {s.pr.ci === "passed" ? "yeşil" : s.pr.ci === "failed" ? "kırmızı" : s.pr.ci === "pending" ? "bekliyor" : "—"}
                </Cip>
                <span className="mono kucuk">{s.pr.branch}</span>
              </p>
              <p>
                <Baglanti href={s.pr.url} yokNedeni="forge adresi yok; LocalForge PR kaydı core'da">
                  {s.pr.url ? "PR'ı aç" : `PR #${s.pr.number}`}
                </Baglanti>
              </p>
              {s.yerel_kontrol && (
                <p className="kucuk">
                  Yerel kontrol: tsc {s.yerel_kontrol.tsc ? "✓" : "✗"} · eslint {s.yerel_kontrol.eslint ? "✓" : "✗"} · AST koruması{" "}
                  {s.yerel_kontrol.ast_guard ? "✓" : "✗"} · repeat-each {s.yerel_kontrol.tekrar}
                  {s.pass_at_1 !== null && ` · pass@1 ${s.pass_at_1 ? "✓" : "✗"}`}
                </p>
              )}
              <div className="eylemler">
                <IslemDugmesi
                  roller={["engineer"]}
                  disabled={!mergeHazir}
                  title={mergeHazir ? undefined : "Merge için CI yeşil ve kırarak doğrulama tamamlanmış olmalı"}
                  onClick={() => s.pr && eylem(() => api.prBirlestir(s.pr!), `PR #${s.pr.number} birleştirildi.`)}
                >
                  Merge et
                </IslemDugmesi>
              </div>
            </>
          ) : (
            <BosDurum baslik="PR henüz açılmadı." />
          )}
        </Kart>

        <Kart
          baslik="Kırarak doğrula"
          eylemler={
            <IslemDugmesi
              roller={["engineer"]}
              tur="ikincil"
              disabled={!prAcik || s.break_verify.durum === "running"}
              calisiyor={s.break_verify.durum === "running"}
              onClick={() => eylem(() => api.kirarakDogrula(s.id), "Kırarak doğrulama başladı.")}
            >
              {s.break_verify.durum === "not_started" ? "Kırarak doğrula" : "Yeniden doğrula"}
            </IslemDugmesi>
          }
        >
          <p className="soluk kucuk">Uygulama BREAK_CAMPAIGN bayrağıyla açılır; test kırmızıya dönmezse "zayıf test" sayılır.</p>
          <KirmaZaman bv={s.break_verify} />
          {s.break_verify.durum === "passed" && <Uyari ton="basari">Test hata yakalıyor ✓</Uyari>}
          {(s.zayif_test || s.break_verify.durum === "weak") && <Uyari ton="hata">Zayıf test: kırılmış uygulamada da yeşil kaldı.</Uyari>}
        </Kart>
      </div>

      <Kart baslik="Üretilen test dosyası">
        {s.kod ? <KodGorunumu kod={s.kod} dosya={s.dosya_yolu} /> : <BosDurum baslik="Kod henüz üretilmedi." />}
      </Kart>
    </>
  );
}

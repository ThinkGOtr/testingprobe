import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { LocatorOnarimi } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { HATA_SINIFI } from "../lib/etiketler";
import { tarih } from "../lib/format";

const ONARIM_DURUMU = { proposed: "Önerildi", pr_open: "PR açık", merged: "Birleşti", rejected: "Reddedildi" } as const;

function OnarimKarti({ o, hataId, yenile }: { o: LocatorOnarimi; hataId: string; yenile: () => void }) {
  const islem = useIslem();
  const bildir = useBildirim();
  return (
    <Kart
      baslik="Locator onarım önerisi"
      eylemler={
        o.durum === "proposed" ? (
          <IslemDugmesi
            roller={["engineer"]}
            calisiyor={islem.calisiyor}
            onClick={async () => {
              const s = await islem.calistir(() => api.onarimPrAc(hataId));
              if (s) {
                bildir(s.mesaj ?? "Onarım PR'ı açıldı.");
                yenile();
              }
            }}
          >
            Onarım PR'ı aç
          </IslemDugmesi>
        ) : o.pr?.durum === "open" ? (
          <IslemDugmesi
            roller={["engineer"]}
            disabled={o.pr.ci !== "passed"}
            title={o.pr.ci !== "passed" ? "CI yeşil olmadan merge edilemez" : undefined}
            calisiyor={islem.calisiyor}
            onClick={async () => {
              const s = await islem.calistir(() => api.prBirlestir(o.pr!), { cakismada: yenile });
              if (s) {
                bildir(`PR #${s.number} birleştirildi.`);
                yenile();
              }
            }}
          >
            Merge et
          </IslemDugmesi>
        ) : null
      }
    >
      <p className="soluk kucuk">
        Onarım yalnızca <span className="mono">{o.dosya}</span> içindeki ilgili <span className="mono">testId</span> değerini değiştirir;
        anahtar, rol, ad ve niyet değişmez (AST koruması).
      </p>
      <div className="locator-fark" aria-label="Locator değişikliği">
        <span className="mono">{o.anahtar}.testId</span>
        <del className="mono">"{o.eski_test_id}"</del>
        <span aria-hidden="true">→</span>
        <span className="gorunmez">yeni değer</span>
        <ins className="mono">"{o.yeni_test_id}"</ins>
      </div>
      <p className="kucuk">
        Rol <span className="mono">{o.rol}</span> · ad <span className="mono">"{o.ad}"</span> (değişmez)
      </p>
      <ul className="kontrol-liste">
        {o.dogrulama.map((d) => (
          <li key={d}>✓ {d}</li>
        ))}
      </ul>
      <p className="satir-ogeler">
        <Cip ton={o.durum === "merged" ? "basari" : o.durum === "pr_open" ? "vurgu" : "notr"}>{ONARIM_DURUMU[o.durum]}</Cip>
        {o.pr && (
          <>
            <span className="mono">#{o.pr.number}</span>
            <Cip ton={o.pr.ci === "passed" ? "basari" : o.pr.ci === "failed" ? "hata" : "bilgi"}>
              CI: {o.pr.ci === "passed" ? "yeşil" : o.pr.ci === "failed" ? "kırmızı" : "bekliyor"}
            </Cip>
            <Baglanti href={o.pr.url} yokNedeni="forge adresi yok">
              {o.pr.url ? "PR'ı aç" : `PR #${o.pr.number} · ${o.pr.branch}`}
            </Baglanti>
          </>
        )}
      </p>
      {islem.hata && <HataKutusu hata={islem.hata} />}
    </Kart>
  );
}

export function HataDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.hata(id), [id]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["failure.classified", "ci.status", "pr.opened"], id);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />;
  const h = v.veri;
  if (!h) return null;
  const s = HATA_SINIFI[h.sinif] ?? { etiket: h.sinif, ton: "notr" as const };

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/kosular/${encodeURIComponent(h.run_id)}`}>← {h.run_id}</Link>}
        baslik="Triage sonucu"
        aciklama={h.test_adi}
      />
      <div className="iki-sutun">
        <Kart baslik="Sınıf">
          <p className="satir-ogeler">
            <Cip ton={s.ton}>{s.etiket}</Cip>
            {h.alt_tur && <span className="mono">{h.alt_tur}</span>}
            <Cip ton="notr">{h.karar_kaynagi === "rule" ? "Deterministik kural" : "LLM yorumu"}</Cip>
            <ReplayRozeti mode={h.mode} />
          </p>
          <p className="soluk kucuk">
            Önce kural seti uygulanır; LLM yalnızca hiçbir kural eşleşmezse devreye girer ve ortam kararını ezemez. Sayısal güven yerine
            eşleşen sinyaller gösterilir.
          </p>
          <pre className="hata-mesaji">{h.hata_mesaji}</pre>
          <p className="kucuk mono soluk">imza: {h.hata_imzasi}</p>
          <p className="kucuk soluk">{tarih(h.zaman)}</p>
        </Kart>
        <Kart baslik="Eşleşen sinyaller">
          <ul className="sinyal-liste">
            {h.eslesen_sinyaller.map((sg) => (
              <li key={sg.kod}>
                <span aria-hidden="true">✓</span>
                <div>
                  <div>{sg.aciklama}</div>
                  <div className="kucuk soluk mono">
                    {sg.kod} · {sg.kaynak}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {h.llm_yorumu && (
            <Uyari ton="bilgi" baslik="LLM yorumu">
              {h.llm_yorumu}
            </Uyari>
          )}
        </Kart>
      </div>

      {h.oneri?.tur === "locator_fix" && <OnarimKarti o={h.oneri} hataId={h.id} yenile={() => void v.yenile(true)} />}
      {h.oneri?.tur === "bug_draft" && (
        <Kart baslik="Öneri">
          <p>
            Ürün hatası adayı: bug taslağı hazırlandı.{" "}
            <Link className="dugme dugme-birincil dugme-kucuk" to={`/bug-taslaklari/${encodeURIComponent(h.oneri.bug_draft_id)}`}>
              Bug taslağına git
            </Link>
          </p>
        </Kart>
      )}

      {h.kanit_linkleri.length > 0 && (
        <Kart baslik="Kanıt">
          <ul className="duz-liste">
            {h.kanit_linkleri.map((k) => (
              <li key={`${k.etiket}-${k.url ?? ""}`}>
                <Baglanti href={k.url} yokNedeni="dosya sunucusu yok">
                  {k.etiket}
                </Baglanti>
              </li>
            ))}
          </ul>
        </Kart>
      )}
    </>
  );
}

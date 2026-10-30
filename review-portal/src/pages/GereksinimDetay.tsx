import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { Bulgu, GereksinimDetay as Detay } from "../api/types";
import { AkisAdimlari } from "../components/AkisAdimlari";
import { useBildirim } from "../components/Bildirim";
import { BulguKarti } from "../components/BulguKarti";
import { BosDurum, Cip, DisBaglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { akisAdimi } from "../lib/akis";
import { AC_EKSIK, gereksinimDurumu, SORU_TURU } from "../lib/etiketler";
import { tarih } from "../lib/format";

export function GereksinimDetay() {
  const { id = "" } = useParams();
  const detay = useVeri(() => api.gereksinim(id), [id]);
  const bulgular = useVeri(() => api.bulgular(id), [id]);
  const islem = useIslem();
  const bildir = useBildirim();

  const tumunuYenile = useCallback(() => {
    void detay.yenile(true);
    void bulgular.yenile(true);
  }, [detay, bulgular]);
  const sessiz = useGeciktirilmis(tumunuYenile);
  useOlay(sessiz, ["requirement.updated", "finding.updated", "case.generated"], id);

  if (detay.yukleniyor && !detay.veri) return <Yukleniyor />;
  if (detay.hata && !detay.veri) return <HataKutusu hata={detay.hata} yenile={() => void detay.yenile()} />;
  const g = detay.veri;
  if (!g) return null;
  const d = g.ac_missing && g.durum === "new" ? AC_EKSIK : gereksinimDurumu(g.durum);
  const liste = bulgular.veri ?? [];
  const yazilacak = liste.filter((b) => b.karar === "fix_doc" && b.durum === "decided").length;
  const acikEngelleyici = liste.filter((b) => b.severity === "blocking" && b.durum === "open").length;
  // core: `discarded` (kanıtı doğrulanamadı) kullanıcıya gösterilmez.
  const turdakiBulgular = liste.filter((b) => b.kontrol_turu >= 1 && b.durum !== "discarded");

  async function eylem(fn: () => Promise<unknown>, basari: string) {
    const s = await islem.calistir(fn);
    if (s !== undefined) {
      bildir(basari);
      tumunuYenile();
    }
  }

  const bulguGuncelle = (b: Bulgu) => {
    bulgular.setVeri(liste.map((x) => (x.id === b.id ? b : x)));
    void detay.yenile(true);
  };

  const incelemeBaslatilabilir = ["new", "findings_open", "failed"].includes(g.durum) && !g.ac_missing;
  const caseUretilebilir = g.po.durum === "approved" && ["po_approved", "cases_ready"].includes(g.durum);
  const caseVar = g.sayaclar.case_toplam > 0;

  return (
    <>
      <SayfaBasligi
        ust={<Link to="/gereksinimler">← Gereksinimler</Link>}
        baslik={
          <>
            {g.jira_key && <span className="mono baslik-anahtar">{g.jira_key}</span>} {g.baslik}
          </>
        }
        aciklama={
          <span className="satir-ogeler">
            <Cip ton={d.ton}>{d.etiket}</Cip>
            <span>{g.kaynak === "jira" ? "Jira story'si" : "Serbest metin gereksinim"}</span>
            {g.jira_url && <DisBaglanti href={g.jira_url}>Jira'da aç</DisBaglanti>}
            <span className="soluk">Çekim: {tarih(g.cekim_zamani)}</span>
          </span>
        }
        eylemler={
          <>
            <IslemDugmesi
              roller={["analyst"]}
              tur={incelemeBaslatilabilir ? "birincil" : "ikincil"}
              disabled={!incelemeBaslatilabilir}
              calisiyor={islem.calisiyor && g.durum === "in_review"}
              title={incelemeBaslatilabilir ? undefined : "Bu durumda ön inceleme başlatılamaz"}
              onClick={() => eylem(() => api.incelemeBaslat(g.id), "Ön inceleme başlatıldı.")}
            >
              {g.kontrol_turu > 0 ? "Yeniden denetle" : "Ön incelemeyi başlat"}
            </IslemDugmesi>
            <IslemDugmesi
              roller={["analyst"]}
              disabled={!caseUretilebilir}
              title={caseUretilebilir ? undefined : "Case üretimi için PO teyidi gerekir"}
              onClick={() => eylem(() => api.caseUret(g.id), "Case üretimi başlatıldı.")}
            >
              Case üret
            </IslemDugmesi>
            {caseVar && (
              <Link className="dugme dugme-ikincil" to={`/gereksinimler/${encodeURIComponent(g.id)}/caseler`}>
                Case review
              </Link>
            )}
          </>
        }
      />
      {islem.hata && <HataKutusu hata={islem.hata} />}

      <Kart>
        <AkisAdimlari adim={akisAdimi(g.durum, g.adim)} />
      </Kart>

      {g.uyarilar.map((u) => (
        <Uyari key={u} baslik="Dikkat">
          {u}
        </Uyari>
      ))}

      <div className="iki-sutun">
        <Kart baslik="Doküman">
          <p>{g.aciklama}</p>
          {g.kabul_kriterleri.length === 0 ? (
            <Uyari>Kabul kriteri yok. Story case üretimine gönderilmez.</Uyari>
          ) : (
            <ol className="ac-liste">
              {g.kabul_kriterleri.map((ac) => (
                <li key={ac.ref}>
                  <span className="mono ac-ref">{ac.ref}</span> {ac.metin}
                </li>
              ))}
            </ol>
          )}
        </Kart>

        <PoKarti g={g} yenile={tumunuYenile} />
      </div>

      <Kart
        baslik="Ön inceleme soruları"
        eylemler={g.on_inceleme && <ReplayRozeti mode={g.on_inceleme.mode} />}
      >
        {!g.on_inceleme ? (
          <BosDurum baslik="Ön inceleme henüz yapılmadı." />
        ) : (
          <>
            <p className="soluk">
              Karar: {g.on_inceleme.verdict === "ready" ? "Hazır (yine de PO teyidi istenir)" : "PO'ya sorular var"} ·{" "}
              {tarih(g.on_inceleme.zaman)}
              {g.on_inceleme.jira_comment_id && ` · Jira yorumu #${g.on_inceleme.jira_comment_id}`}
            </p>
            <ol className="soru-liste">
              {g.on_inceleme.questions.map((s) => (
                <li key={s.id}>
                  <div className="satir-ogeler">
                    <Cip ton="bilgi">{SORU_TURU[s.type] ?? s.type}</Cip>
                    {s.ac_ref && <span className="mono">{s.ac_ref}</span>}
                  </div>
                  <p>{s.text}</p>
                  {s.cevap ? <p className="cevap">↳ {s.cevap}</p> : <p className="soluk kucuk">Cevap bekleniyor</p>}
                </li>
              ))}
            </ol>
          </>
        )}
      </Kart>

      <Kart
        baslik={`Tutarlılık bulguları${g.kontrol_turu ? ` · kontrol turu ${g.kontrol_turu}/${g.kontrol_turu_ust_sinir}` : ""}`}
        eylemler={
          <IslemDugmesi
            roller={["analyst"]}
            disabled={yazilacak === 0}
            calisiyor={islem.calisiyor && g.durum === "in_review"}
            title={yazilacak === 0 ? "Yazılmayı bekleyen 'dokümanı düzelt' kararı yok" : undefined}
            onClick={() =>
              eylem(
                () => api.duzeltmeleriUygula(g.id),
                g.kaynak === "jira" ? "Düzeltmeler Jira'ya yazılıyor; ardından yeniden kontrol." : "Düzeltmeler uygulanıyor; ardından yeniden kontrol.",
              )
            }
          >
            {g.kaynak === "jira" ? "Düzeltmeleri Jira'ya yaz" : "Düzeltmeleri uygula"}
            {yazilacak > 0 && ` (${yazilacak})`}
          </IslemDugmesi>
        }
      >
        <p className="soluk">
          Doküman kodla (salt okuma repo) ve veriyle (salt okuma sorgu) karşılaştırılır. Yalnızca kanıtı deterministik olarak yeniden
          doğrulanan bulgular gösterilir.
        </p>
        {acikEngelleyici > 0 && (
          <Uyari>
            {acikEngelleyici} engelleyici bulgu karar bekliyor. Engelleyici bulgu kalmadan doküman "son hal" olmaz ve PO teyidine geçilmez.
          </Uyari>
        )}
        {bulgular.yukleniyor && !bulgular.veri ? (
          <Yukleniyor />
        ) : bulgular.hata && !bulgular.veri ? (
          <HataKutusu hata={bulgular.hata} yenile={() => void bulgular.yenile()} />
        ) : turdakiBulgular.length === 0 ? (
          <BosDurum baslik={g.kontrol_turu ? "Bulgu yok: doküman kod ve veriyle tutarlı." : "Denetim henüz çalıştırılmadı."} />
        ) : (
          <div className="bulgu-liste">
            {turdakiBulgular.map((b) => (
              <BulguKarti key={`${b.id}-${b.durum}`} bulgu={b} guncellendi={bulguGuncelle} yenile={tumunuYenile} />
            ))}
          </div>
        )}
      </Kart>
    </>
  );
}

function PoKarti({ g, yenile }: { g: Detay; yenile: () => void }) {
  const islem = useIslem();
  const bildir = useBildirim();
  const po = g.po;
  return (
    <Kart baslik="PO teyidi">
      {po.durum === "approved" ? (
        <p>
          <Cip ton="basari">Onaylı</Cip> <strong>{po.onaylayan}</strong> · {tarih(po.zaman)}
          <span className="soluk"> · {po.kanal === "jira" ? "Jira etiketi (tp-po-approved)" : "Portal"}</span>
        </p>
      ) : po.durum === "pending" ? (
        <>
          <p>
            <Cip ton="uyari">Bekliyor</Cip>{" "}
            {po.kanal === "jira"
              ? "PO soruları Jira'da cevaplayıp tp-po-approved etiketini koyduğunda akış devam eder (15 sn'de bir kontrol edilir)."
              : "Serbest metin gereksinim: PO teyidi portalda verilir."}
          </p>
          {po.kanal === "portal" && (
            <IslemDugmesi
              roller={["po"]}
              calisiyor={islem.calisiyor}
              onClick={async () => {
                // Gösterilen içeriğin hash'i gönderilir; arada değiştiyse 409 → ekran yenilenir.
                const s = await islem.calistir(() => api.poOnayla(g), { cakismada: yenile });
                if (s) {
                  bildir("PO teyidi verildi.");
                  yenile();
                }
              }}
            >
              PO olarak onayla
            </IslemDugmesi>
          )}
          {islem.hata && <HataKutusu hata={islem.hata} />}
        </>
      ) : (
        <p className="soluk">Henüz istenmedi. Doküman "son hal" olunca PO teyidi istenir.</p>
      )}
      <p className="soluk kucuk">İnsan kapısı: PO teyidi olmadan case üretimine geçilmez.</p>
    </Kart>
  );
}

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

/** "sha256:abcdef…" → kısa gösterim (ilk 12 hane). */
function kisaHash(h: string): string {
  const [on, govde] = h.includes(":") ? h.split(":", 2) : ["", h];
  return `${on ? `${on}:` : ""}${govde.slice(0, 12)}${govde.length > 12 ? "…" : ""}`;
}

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
  // Constitution XI: kanıtı deterministik olarak doğrulanmamış bulgu gösterilmez. `unverified`
  // (doğrulama sürüyor) ve `discarded` (doğrulanamadı, elendi) yalnızca sayı olarak görünür.
  const turdakiBulgular = liste.filter((b) => b.kontrol_turu >= 1 && b.durum !== "discarded" && b.durum !== "unverified");
  const dogrulaniyor = liste.filter((b) => b.durum === "unverified").length;
  const elenen = Math.max(g.elenen_bulgu ?? 0, liste.filter((b) => b.durum === "discarded").length);
  const turSiniri = g.kontrol_turu >= g.kontrol_turu_ust_sinir;
  // Yazılacak düzeltme ve açık engelleyici yokken analist belgeyi açıkça son hal yapar (ör.
  // güvenilmez denetim sonrası otomatik son hal olmaz; core apply-doc-fixes'i düzeltmesiz kabul eder).
  const sonHalAcik = g.durum === "findings_open" && yazilacak === 0 && acikEngelleyici === 0;
  const bosBulgu = bosBulguMetni(g, elenen, dogrulaniyor);
  const poCevaplari = g.po_cevaplari ?? [];

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
        <AkisAdimlari adim={akisAdimi(g.durum, g.adim)} kaynak={g.kaynak} />
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
            {g.on_inceleme.ozet && (
              <p className="kucuk" data-testid="on-inceleme-ozet">
                {/* Model çıktısı (güvenilmeyen içerikten türedi): düz metin, karar dayanağı değil. */}
                <strong>AI özeti</strong> <span className="soluk">(model çıktısı, karar dayanağı değildir)</span>: {g.on_inceleme.ozet}
              </p>
            )}
            <ol className="soru-liste">
              {g.on_inceleme.questions.map((s) => (
                <li key={s.id}>
                  <div className="satir-ogeler">
                    <strong className="mono" title="PO cevabında kullanılan kimlik (ör. 'Q3: …')">{s.id}</strong>
                    <Cip ton="bilgi">{SORU_TURU[s.type] ?? s.type}</Cip>
                    {s.ac_ref && <span className="mono">{s.ac_ref}</span>}
                    {s.duzeltmeyle_degisti && (
                      <Cip ton="uyari" title="Sorunun ilgilendiği madde doküman düzeltmesiyle değişti; PO güncel metne göre cevaplar.">
                        Düzeltmeyle metni değişti
                      </Cip>
                    )}
                  </div>
                  <p>{s.text}</p>
                  {s.cevap ? (
                    <p className="cevap">↳ {s.cevap}</p>
                  ) : (
                    <p className="soluk kucuk">
                      {g.po.durum !== "approved"
                        ? "Cevap bekleniyor"
                        : poCevaplari.length > 0
                          ? "PO Jira'da yanıtladı (aşağıda)"
                          : "Ayrı cevap yazılmadı; PO içeriği onayladı."}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
        {poCevaplari.length > 0 && (
          <section className="po-cevaplari" aria-labelledby="po-cevaplari-baslik" data-testid="po-cevaplari">
            <h3 id="po-cevaplari-baslik" className="alt-baslik">
              PO cevapları {g.kaynak === "jira" && "(Jira yorumu)"}
            </h3>
            <ul className="po-cevap-liste">
              {poCevaplari.map((c, i) => (
                <li key={c.id || i} className="po-cevap">
                  <div className="satir-ogeler soluk kucuk">
                    <strong>{c.yazar ?? "PO"}</strong>
                    {c.zaman && <span>{tarih(c.zaman)}</span>}
                    {c.url && <DisBaglanti href={c.url}>{c.id ? `Jira yorumu #${c.id}` : "Jira'da aç"}</DisBaglanti>}
                  </div>
                  {/* Güvenilmeyen içerik (§5): düz metin olarak gösterilir. */}
                  <p className="po-cevap-metin">{c.metin}</p>
                </li>
              ))}
            </ul>
          </section>
        )}
      </Kart>

      <Kart
        baslik={`Tutarlılık bulguları${g.kontrol_turu ? ` · kontrol turu ${g.kontrol_turu}/${g.kontrol_turu_ust_sinir}` : ""}`}
        eylemler={
          <>
          {g.son_kontrol && <ReplayRozeti mode={g.son_kontrol.mode} />}
          <IslemDugmesi
            roller={["analyst"]}
            disabled={sonHalAcik ? false : yazilacak === 0 || turSiniri}
            calisiyor={islem.calisiyor && g.durum === "in_review"}
            title={
              sonHalAcik
                ? g.denetim_guvenilmez
                  ? `Denetim güvenilmez (${g.denetim_guvenilmez}); belge yalnızca açık kararınızla son hal olur ve PO'ya gider`
                  : "Yazılacak düzeltme yok; belge son hal olur ve PO'ya gider"
                : turSiniri
                ? `Kontrol turu sınırına ulaşıldı (${g.kontrol_turu_ust_sinir}); insan kararı gerekiyor`
                : yazilacak === 0
                  ? "Yazılmayı bekleyen 'dokümanı düzelt' kararı yok"
                  : `Yazılır ve yeniden kontrol turu ${g.kontrol_turu + 1}/${g.kontrol_turu_ust_sinir} başlar`
            }
            onClick={() =>
              eylem(
                () => api.duzeltmeleriUygula(g.id),
                sonHalAcik
                  ? "Belge son hal yapıldı; PO teyidi bekleniyor."
                  : g.kaynak === "jira"
                    ? "Düzeltmeler Jira'ya yazılıyor; ardından yeniden kontrol."
                    : "Düzeltmeler uygulanıyor; ardından yeniden kontrol.",
              )
            }
          >
            {sonHalAcik ? "Son hal olarak onayla" : g.kaynak === "jira" ? "Düzeltmeleri Jira'ya yaz" : "Düzeltmeleri uygula"}
            {yazilacak > 0 && ` (${yazilacak})`}
            {g.kontrol_turu > 0 && " · "}
            {g.kontrol_turu > 0 && (
              <span className="dugme-ek">
                tur {g.kontrol_turu}/{g.kontrol_turu_ust_sinir}
              </span>
            )}
          </IslemDugmesi>
          </>
        }
      >
        <p className="soluk">
          Doküman kodla (salt okuma repo) ve veriyle (salt okuma sorgu) karşılaştırılır. Yalnızca kanıtı deterministik olarak yeniden
          doğrulanan bulgular gösterilir.
        </p>
        {g.kontrol_turu > 0 && (
          <p className="satir-ogeler kucuk" data-testid="bulgu-sayaclari">
            <span>
              Kontrol turu{" "}
              <strong className="mono">
                {g.kontrol_turu}/{g.kontrol_turu_ust_sinir}
              </strong>
            </span>
            <span>
              Gösterilen <strong>{turdakiBulgular.length}</strong>
            </span>
            {dogrulaniyor > 0 && (
              <span>
                Kanıt doğrulanıyor <strong>{dogrulaniyor}</strong>
              </span>
            )}
            <span title="Kanıtı (kod satırı veya sorgu sonucu) yeniden çekilip eşleşmediği için gösterilmeyen bulgular">
              Kanıtı doğrulanamadığı için elenen <strong>{elenen}</strong>
            </span>
          </p>
        )}
        {turSiniri && yazilacak > 0 && (
          <Uyari>
            Kontrol turu sınırına ulaşıldı ({g.kontrol_turu_ust_sinir}). Kalan düzeltmeler otomatik yazılmaz; insan kararı gerekiyor.
          </Uyari>
        )}
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
          <div data-testid="bulgu-bos">
            <BosDurum baslik={bosBulgu} />
          </div>
        ) : (
          <div className="bulgu-liste">
            {turdakiBulgular.map((b) => (
              <BulguKarti
                key={`${b.id}-${b.durum}`}
                bulgu={b}
                gereksinimDurumu={g.durum}
                kaynak={g.kaynak}
                guncellendi={bulguGuncelle}
                yenile={tumunuYenile}
              />
            ))}
          </div>
        )}
      </Kart>
    </>
  );
}

/**
 * Gösterilecek bulgu yokken ne denir. "Tutarlı" yalnızca son kontrol gerçekten bulgusuz
 * çıktıysa söylenir: REPLAY-MISS ya da kanıtı doğrulanamadığı için elenen bulgu varsa tutarlılık
 * kurulmamıştır (Constitution VIII, XI) ve bu açıkça yazılır.
 */
export function bosBulguMetni(g: Detay, elenenToplam: number, dogrulaniyor: number): string {
  if (!g.kontrol_turu && !g.son_kontrol) return "Denetim henüz çalıştırılmadı.";
  if (dogrulaniyor > 0) return "Bulguların kanıtı doğrulanıyor; doğrulanan bulgular burada görünecek.";
  const miss = g.son_kontrol?.mode === "replay_miss";
  const elenen = g.son_kontrol ? g.son_kontrol.elenen : elenenToplam;
  if (miss || elenen > 0) {
    const nedenler = [
      miss ? "REPLAY-MISS" : null,
      elenen > 0 ? `${elenen} bulgu kanıtı doğrulanamadığı için elendi` : null,
    ].filter(Boolean);
    return `Gösterilecek doğrulanmış bulgu yok (${nedenler.join("; ")}) — tutarlılık doğrulanmadı.`;
  }
  return "Bulgu yok: doküman kod ve veriyle tutarlı.";
}

function PoKarti({ g, yenile }: { g: Detay; yenile: () => void }) {
  const islem = useIslem();
  const bildir = useBildirim();
  const po = g.po;
  return (
    <Kart baslik="PO teyidi">
      {po.durum === "approved" ? (
        <>
          <p>
            <Cip ton="basari">Onaylı</Cip> <strong>{po.onaylayan ?? "—"}</strong> · {tarih(po.zaman)}
            <span className="soluk"> · {po.kanal === "jira" ? "Jira etiketi (tp-po-approved)" : "Portal"}</span>
          </p>
          {po.onaylanan_hash && (
            <p className="soluk kucuk">
              Onaylanan içerik <span className="mono">{kisaHash(po.onaylanan_hash)}</span>
              {g.icerik_hash && po.onaylanan_hash !== g.icerik_hash && (
                <>
                  {" "}
                  · <strong className="hata-metin">içerik onaydan sonra değişti; yeniden PO teyidi gerekir</strong>
                </>
              )}
            </p>
          )}
        </>
      ) : po.durum === "pending" ? (
        <>
          <p>
            <Cip ton="uyari">Bekliyor</Cip>{" "}
            {po.kanal === "jira"
              ? "PO soruları Jira'da cevaplayıp tp-po-approved etiketini koyduğunda akış devam eder (15 sn'de bir kontrol edilir)."
              : "Serbest metin gereksinim: PO teyidi portalda verilir."}
          </p>
          {po.kanal === "portal" && g.icerik_hash && (
            <p className="soluk kucuk">
              Onay, ekranda gördüğünüz içeriğe bağlanır (<span className="mono">{kisaHash(g.icerik_hash)}</span>); arada değişirse reddedilir.
            </p>
          )}
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

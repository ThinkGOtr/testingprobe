import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { useOlay } from "../api/events";
import type { Bulgu, GereksinimDetay as Detay } from "../api/types";
import { AkisAdimlari } from "../components/AkisAdimlari";
import { BazDegerKarti } from "../components/BazDegerKarti";
import { useBildirim } from "../components/Bildirim";
import { BulguKarti, SON_HAL_SONRASI } from "../components/BulguKarti";
import { BosDurum, Cip, DisBaglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { akisAdimi, DENETIM_ISLERI, hataAdimi, URETIM_ISI } from "../lib/akis";
import { akisKanitlari, guncelAdim } from "../lib/yolHaritasi";
import { AC_EKSIK, gereksinimDurumu, SORU_TURU } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { dokumanBloklari } from "../lib/dokuman";
import type { UretimKipi } from "../api/tasarimModeliTipleri";
import { MODEL_ASAMASI, TasarimModeliPaneli } from "../components/TasarimModeliPaneli";
import { UretimKipiSecici, VARSAYILAN_KIP } from "../components/UretimKipiSecici";

/**
 * Onaylı düzeltmeleri uygular. Düzeltme aynı döngüdeki 'bilinçli fark' kararıyla çelişirse core 409
 * döner; analist çelişkiyi görüp onaylarsa `cakismayi_onayla` ile yeniden gönderilir (denetlenir).
 */
async function duzeltmeleriUygula(id: string) {
  try {
    return await api.duzeltmeleriUygula(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && e.detail.includes("bilinçli fark")) {
      if (window.confirm(`${e.detail}\n\nDüzeltme yine de uygulansın mı? (Karar denetim kaydına yazılır.)`)) {
        return api.duzeltmeleriUygula(id, true);
      }
    }
    throw e;
  }
}

/** "sha256:abcdef…" → kısa gösterim (ilk 12 hane). */
function kisaHash(h: string): string {
  const [on, govde] = h.includes(":") ? h.split(":", 2) : ["", h];
  return `${on ? `${on}:` : ""}${govde.slice(0, 12)}${govde.length > 12 ? "…" : ""}`;
}

export function GereksinimDetay() {
  const { id = "" } = useParams();
  const detay = useVeri(() => api.gereksinim(id), [id]);
  const bulgular = useVeri(() => api.bulgular(id), [id]);
  // Gereksinim makinesi `done` ile biter; kod → bug adımları (5–14) yol haritasıyla aynı kanıtlardan.
  const tamamMi = detay.veri?.durum === "done";
  const kanit = useVeri(() => (tamamMi ? akisKanitlari(id) : Promise.resolve(null)), [id, tamamMi]);
  const islem = useIslem();
  const bildir = useBildirim();
  // 011 K1: üretim kipi (iki tur varsayılan); "Case üret" seçili kipi açıkça gönderir.
  const [kip, setKip] = useState<UretimKipi>(VARSAYILAN_KIP);

  const tumunuYenile = useCallback(() => {
    void detay.yenile(true);
    void bulgular.yenile(true);
  }, [detay, bulgular]);
  const sessiz = useGeciktirilmis(tumunuYenile);
  useOlay(sessiz, ["requirement.updated", "finding.updated", "case.generated"], id);

  if (detay.yukleniyor && !detay.veri) return <Yukleniyor />;
  if (detay.hata && !detay.veri) return <HataKutusu hata={detay.hata} kaynak={detay.hataNesnesi} yenile={() => void detay.yenile()} />;
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
  // Yazılacak düzeltme ve açık engelleyici yokken analist belgeyi açıkça son hâl yapar (ör.
  // güvenilmez denetim sonrası otomatik son hâl olmaz; core apply-doc-fixes'i düzeltmesiz kabul eder).
  const sonHalAcik = g.durum === "findings_open" && yazilacak === 0 && acikEngelleyici === 0;
  // Belge son hâle geçtiyse düzeltme düğmesi artık işlevsiz: soluk düğme "takıldı" sanılmasın,
  // yerine gereksinimin güncel durumu yazılır.
  const sonHalSonrasi = SON_HAL_SONRASI.has(g.durum);
  const bosBulgu = bosBulguMetni(g, elenen, dogrulaniyor);
  const poCevaplari = g.po_cevaplari ?? [];

  async function eylem<T>(fn: () => Promise<T>, basari: string | ((sonuc: T) => string)) {
    const s = await islem.calistir(fn);
    if (s !== undefined) {
      bildir(typeof basari === "function" ? basari(s as T) : basari);
      tumunuYenile();
    }
  }

  const bulguGuncelle = (b: Bulgu) => {
    bulgular.setVeri(liste.map((x) => (x.id === b.id ? b : x)));
    void detay.yenile(true);
  };

  // Kabul kriteri eksik story de ön incelemeye girer (TPD-2): ön inceleme eksik kriterleri PO'ya
  // soru olarak sorar (TEKNIK-TASARIM §8.2). Yalnızca case üretimi kapalıdır (core 422).
  const incelemeBaslatilabilir = ["new", "findings_open", "failed"].includes(g.durum);
  // Case üretimi hata ile bittiyse (REPLAY-MISS, model zaman aşımı, düşen worker) core yeniden
  // denemeye izin verir (failed → generating; PO onayının güncelliği sunucuda yeniden doğrulanır).
  // Ön incelemeyi baştan başlatmak gerekmez — o yol Jira story'sinde yeni PO teyidi ister.
  const uretimHatasi = uretimHatasiMi(g);
  const poGuncel = poOnayiGuncel(g);
  const caseUretilebilir =
    !g.ac_missing &&
    ((poGuncel && ["po_approved", "cases_ready"].includes(g.durum)) || (uretimHatasi && poYenidenDenemedeGecerli(g)));
  const modelAsamasi = MODEL_ASAMASI.has(g.durum);
  const caseUretNedeni = modelAsamasi
    ? "İki tur sürüyor: tasarım modeli panelinden ilerleyin (onay → Case'leri üret)"
    : caseUretilebilir
    ? uretimHatasi
      ? "Case üretimi hata ile bitti; yeniden dener. PO onayının güncelliği sunucuda yeniden doğrulanır."
      : undefined
    : g.ac_missing
      ? AC_YOK_CASE_URETILEMEZ
      : uretimHatasi
        ? "İçerik PO onayından sonra değişti; yeniden PO teyidi gerekir"
        : "Case üretimi için PO teyidi gerekir";
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
              tur={incelemeBaslatilabilir && !(uretimHatasi && caseUretilebilir) ? "birincil" : "ikincil"}
              disabled={!incelemeBaslatilabilir}
              calisiyor={islem.calisiyor && g.durum === "in_review"}
              title={
                incelemeBaslatilabilir
                  ? uretimHatasi
                    ? "Denetimi baştan başlatır; Jira story'sinde yeni PO teyidi gerekir. Yalnızca case üretimini yeniden denemek için 'Case üret'i kullanın."
                    : g.ac_missing
                    ? "Kabul kriteri yok: ön inceleme eksik kriterleri PO'ya sorar"
                    : undefined
                  : "Bu durumda ön inceleme başlatılamaz"
              }
              onClick={() => eylem(() => api.incelemeBaslat(g.id), "Ön inceleme başlatıldı.")}
            >
              {g.kontrol_turu > 0 ? "Yeniden denetle" : "Ön incelemeyi başlat"}
            </IslemDugmesi>
            <IslemDugmesi
              id="case-uret"
              roller={["analyst"]}
              tur={uretimHatasi && caseUretilebilir ? "birincil" : undefined}
              disabled={!caseUretilebilir}
              title={caseUretNedeni}
              onClick={() =>
                eylem(
                  () => api.caseUret(g.id, kip).catch(caseUretHatasi),
                  kip === "iki_tur" ? "Tasarım modeli üretimi başlatıldı (iki tur)." : "Case üretimi başlatıldı.",
                )
              }
            >
              {uretimHatasi ? "Case üretimini yeniden dene" : "Case üret"}
            </IslemDugmesi>
            {caseVar && (
              <Link className="dugme dugme-ikincil" to={`/gereksinimler/${encodeURIComponent(g.id)}/caseler`}>
                Case review
              </Link>
            )}
          </>
        }
      />
      {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}

      {caseUretilebilir && (
        <Kart>
          <UretimKipiSecici kip={kip} degistir={setKip} />
        </Kart>
      )}
      <TasarimModeliPaneli g={g} yenile={tumunuYenile} />

      <Kart>
        <AkisAdimlari adim={guncelAdim(g, kanit.veri ?? null, akisAdimi(g.durum, g.adim ?? hataAdimi(g.son_hata?.job_tur)))} kaynak={g.kaynak} />
      </Kart>

      {g.son_hata && (
        <div data-testid="son-hata">
          <Uyari ton="hata" baslik="Son işlem başarısız">
            {g.son_hata.neden && <p>{g.son_hata.neden}</p>}
            {g.son_hata.is_hatasi && g.son_hata.is_hatasi !== g.son_hata.neden && <p className="kucuk mono">{g.son_hata.is_hatasi}</p>}
            {g.son_hata.oneri && <p className="kucuk">{g.son_hata.oneri}</p>}
            <p className="soluk kucuk">
              {g.son_hata.job_tur && <span className="mono">{g.son_hata.job_tur}</span>}
              {g.son_hata.zaman && <> · {tarih(g.son_hata.zaman)}</>}
            </p>
          </Uyari>
        </div>
      )}
      {/* son_hata ayrıntılı kutuda gösterilir; core'un aynı içerikli özet uyarısı tekrarlanmaz. */}
      {g.uyarilar.filter((u) => !(g.son_hata && u.startsWith("Son işlem başarısız:"))).map((u) => (
        <Uyari key={u} baslik="Dikkat">
          {u}
        </Uyari>
      ))}

      <div className="bolum-duzen">
        <BolumGezgini />
        <div className="bolum-govde">
          <div className="iki-sutun">
            <Kart baslik="Doküman" id={BOLUM_ID.dokuman}>
              <Dokuman g={g} />
            </Kart>

            <PoKarti g={g} yenile={tumunuYenile} />
          </div>

          <BazDegerKarti
            id={BOLUM_ID.baz}
            g={g}
            guncellendi={(b) => {
              if (b !== undefined) detay.setVeri({ ...g, manuel_baz: b });
              void detay.yenile(true);
            }}
          />

          <Kart
            id={BOLUM_ID.sorular}
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
                      {s.kararla_cozuldu && !s.cevap ? (
                        <p className="kucuk" data-testid={`soru-cozuldu-${s.id}`}>
                          <Cip ton="basari" title="Bu soru analistin bulgu kararıyla kapandı; PO'ya sorulmaz (bilgi için).">
                            Çözüldü
                          </Cip>{" "}
                          {s.kararla_cozuldu}
                        </p>
                      ) : s.cevap ? (
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
            id={BOLUM_ID.bulgular}
            baslik={`Tutarlılık bulguları${g.kontrol_turu ? ` · kontrol turu ${g.kontrol_turu}/${g.kontrol_turu_ust_sinir}` : ""}`}
            eylemler={
              <>
                {g.son_kontrol && <ReplayRozeti mode={g.son_kontrol.mode} />}
                {sonHalSonrasi ? (
                  <span data-testid="son-hal-durumu">
                    {/* Bu çip dokümanın durumunu söyler: son hâl tamam (✓). PO teyidi beklemesi bir uyarı
                        değil, sıradaki adımdır; bu yüzden uyarı tonu yerine bilgi tonu. */}
                    <Cip ton={g.durum === "pending_po" ? "bilgi" : d.ton}>{g.durum === "doc_final" ? "✓ Doküman son hâl" : `✓ Doküman son hâl · ${d.etiket}`}</Cip>
                  </span>
                ) : (
                  <IslemDugmesi
                    roller={["analyst"]}
                    disabled={sonHalAcik ? false : yazilacak === 0 || turSiniri}
                    calisiyor={islem.calisiyor && g.durum === "in_review"}
                    // Tur sınırı nedeni aşağıdaki uyarı kutusunda (yalnız yazılacak düzeltme varken) görünür
                    // yazılı; düğmeye bağlanır. Kutu yoksa neden düğmenin altında yazılır.
                    nedenGizli={turSiniri && yazilacak > 0}
                    aria-describedby={turSiniri && yazilacak > 0 ? "tur-siniri-neden" : undefined}
                    title={
                      sonHalAcik
                        ? g.denetim_guvenilmez
                          ? `Denetim güvenilmez (${g.denetim_guvenilmez}); belge yalnızca açık kararınızla son hâl olur ve PO'ya gider`
                          : "Yazılacak düzeltme yok; belge son hâl olur ve PO'ya gider"
                        : turSiniri
                        ? `Kontrol turu sınırına ulaşıldı (${g.kontrol_turu_ust_sinir}); insan kararı gerekiyor`
                        : yazilacak === 0
                          ? "Yazılmayı bekleyen 'dokümanı düzelt' kararı yok"
                          : `Yazılır ve yeniden kontrol turu ${g.kontrol_turu + 1}/${g.kontrol_turu_ust_sinir} başlar`
                    }
                    onClick={() =>
                      eylem(
                        () => duzeltmeleriUygula(g.id),
                        sonHalAcik
                          ? (r) =>
                              r?.kabul_edilen_uyarilar && r.kabul_edilen_uyarilar.length > 0
                                ? `Belge son hâl yapıldı; kararsız uyarılar bilinçli fark olarak kaydedildi (${r.kabul_edilen_uyarilar.join(", ")}). PO teyidi bekleniyor.`
                                : "Belge son hâl yapıldı; PO teyidi bekleniyor."
                          : g.kaynak === "jira"
                            ? "Düzeltmeler Jira'ya yazılıyor; ardından yeniden kontrol."
                            : "Düzeltmeler uygulanıyor; ardından yeniden kontrol.",
                      )
                    }
                  >
                    {sonHalAcik ? "Son hâl olarak onayla" : g.kaynak === "jira" ? "Düzeltmeleri Jira'ya yaz" : "Düzeltmeleri uygula"}
                    {yazilacak > 0 && ` (${yazilacak})`}
                    {g.kontrol_turu > 0 && " · "}
                    {g.kontrol_turu > 0 && (
                      <span className="dugme-ek">
                        tur {g.kontrol_turu}/{g.kontrol_turu_ust_sinir}
                      </span>
                    )}
                  </IslemDugmesi>
                )}
              </>
            }
          >
            <p className="soluk">
              Doküman kodla (salt okuma repo) ve veriyle (salt okuma sorgu) karşılaştırılır. Yalnızca kanıtı deterministik olarak yeniden
              doğrulanan bulgular gösterilir.
            </p>
            {sonHalSonrasi && (
              <p className="kucuk" data-testid="son-hal-notu">
                Düzeltmeler Jira'ya yazıldı ve son kontrol turunda engelleyici bulgu kalmadı. Aşağıdaki kartlar bu turun kaydıdır;
                karar gerekmez.
              </p>
            )}
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
              <Uyari id="tur-siniri-neden">
                Kontrol turu sınırına ulaşıldı ({g.kontrol_turu_ust_sinir}). Kalan düzeltmeler otomatik yazılmaz; insan kararı gerekiyor.
              </Uyari>
            )}
            {acikEngelleyici > 0 && (
              <Uyari>
                {acikEngelleyici} engelleyici bulgu karar bekliyor. Engelleyici bulgu kalmadan doküman "son hâl" olmaz ve PO teyidine geçilmez.
              </Uyari>
            )}
            {bulgular.yukleniyor && !bulgular.veri ? (
              <Yukleniyor />
            ) : bulgular.hata && !bulgular.veri ? (
              <HataKutusu hata={bulgular.hata} kaynak={bulgular.hataNesnesi} yenile={() => void bulgular.yenile()} />
            ) : turdakiBulgular.length === 0 ? (
              <div data-testid="bulgu-bos">
                {g.durum === "in_review" ? <Yukleniyor metin={bosBulgu} /> : <BosDurum baslik={bosBulgu} />}
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
        </div>
      </div>
    </>
  );
}

/**
 * Bölüm kimlikleri: bölüm gezgini (F4) ile asistan öneri çapalarının (`rules/assistant/oneriler.yaml`
 * `capa:`, AI-ASISTAN-PLANI §17.4) ortak sözleşmesi. `bulgular` ve `po-onay` kural dosyasında geçer;
 * değiştirilirse kurallar da değişir (capa.test.tsx denetler). Diğerleri aynı adlandırmayı izler.
 */
export const BOLUM_ID = {
  dokuman: "dokuman",
  po: "po-onay",
  baz: "baz-deger",
  sorular: "on-inceleme",
  bulgular: "bulgular",
} as const;

const BOLUMLER: { id: string; ad: string }[] = [
  { id: BOLUM_ID.dokuman, ad: "Doküman" },
  { id: BOLUM_ID.po, ad: "PO teyidi" },
  { id: BOLUM_ID.baz, ad: "Manuel baz değer" },
  { id: BOLUM_ID.sorular, ad: "Ön inceleme soruları" },
  { id: BOLUM_ID.bulgular, ad: "Tutarlılık bulguları" },
];

/**
 * Uzun sayfada yön bulma (G8), üç aralık (CSS): ≤860 px gizli (display: none → erişilebilirlik ağacında da
 * yok); 861–1279 px üst çubuğun altında yapışkan tek satır yatay şerit; ≥1280 px sağda yapışkan sütun. Liste
 * rolü bilinçli olarak kullanılmaz (§9 rol sayımları); düz bağlantılar. DOM'da içerikten önce: klavyede
 * bölümlere atlama yolu. Bağlantı metinleri kart başlıklarıyla aynı: ≥861 px'te testte
 * getByText(kart başlığı).first() bu bağlantıyı bulur → kartlar getByRole("region", { name }) ile aranır (§9).
 */
function BolumGezgini() {
  return (
    <nav className="bolum-gezgini" aria-label="Sayfa bölümleri">
      {BOLUMLER.map((b) => (
        <a key={b.id} href={`#${b.id}`}>
          {b.ad}
        </a>
      ))}
    </nav>
  );
}

/**
 * Gösterilecek bulgu yokken ne denir. "Tutarlı" yalnızca son kontrol gerçekten bulgusuz
 * çıktıysa söylenir: REPLAY-MISS ya da kanıtı doğrulanamadığı için elenen bulgu varsa tutarlılık
 * kurulmamıştır (Constitution VIII, XI) ve bu açıkça yazılır.
 */
export function bosBulguMetni(g: Detay, elenenToplam: number, dogrulaniyor: number): string {
  // Denetim sürerken ya da hata ile bittiyse "tutarlı" denmez: tamamlanmamış denetim temiz sonuç değildir.
  if (g.durum === "in_review") return DENETIM_SURUYOR;
  // Yalnızca denetim işi (ön inceleme/tutarlılık) düştüyse "denetim tamamlanmadı" denir. Sonraki bir
  // adım (ör. case üretimi) düştüyse denetim sonucu geçerlidir ve aşağıdaki kurallarla anlatılır.
  // Hangi işin düştüğü bilinmiyorsa temkinli davranılır (tutarlı denmez).
  if (g.durum === "failed") {
    const tur = g.son_hata?.job_tur ?? null;
    if (!tur || DENETIM_ISLERI.has(tur) || hataAdimi(tur) === null) return DENETIM_HATALI;
  }
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
  // Tamamlanmış bir kontrol koşusu kaydı yoksa (son_kontrol yok) tutarlılık kurulmamıştır.
  if (!g.son_kontrol) return DENETIM_TAMAMLANMADI;
  return "Bulgu yok: doküman kod ve veriyle tutarlı.";
}

export const DENETIM_SURUYOR = "Denetim sürüyor… Sonuç gelince bulgular burada görünecek.";
export const DENETIM_TAMAMLANMADI = "Denetim tamamlanmadı — tutarlılık doğrulanmadı.";
export const DENETIM_HATALI =
  "Denetim tamamlanmadı (iş hata ile bitti) — tutarlılık doğrulanmadı. 'Yeniden denetle' ile tekrar başlatın.";

export const AC_YOK_CASE_URETILEMEZ = "Kabul kriteri yok; case üretilemez";

/** Gereksinim, case üretimi işi hata ile bittiği için mi `failed`? */
export function uretimHatasiMi(g: Pick<Detay, "durum" | "son_hata">): boolean {
  // İki turda model üretimi (`model.generate`) de üretim işidir: yeniden denenir (011 F3).
  return g.durum === "failed" && (g.son_hata?.job_tur === URETIM_ISI || g.son_hata?.job_tur === "model.generate");
}

/** PO onayı var ve onaylanan içerik hâlâ ekrandaki içerik mi (hash'ler biliniyorsa)? */
export function poOnayiGuncel(g: Pick<Detay, "po" | "icerik_hash">): boolean {
  if (g.po.durum !== "approved") return false;
  return !g.po.onaylanan_hash || !g.icerik_hash || g.po.onaylanan_hash === g.icerik_hash;
}

/**
 * Case üretimi düşmüş gereksinimde PO onayı yeniden deneme için geçerli sayılır mı. Core onayı
 * `approved` + hash ile bildiriyorsa güncellik burada da kontrol edilir; core `failed` durumunda
 * onayı göstermiyorsa (eski sürüm: `not_requested`) karar sunucuya bırakılır — üretime yalnızca PO
 * onayından sonra girilebildiği için düşen üretimin onayı vardı ve core yeniden denemede PO
 * güncelliğini yeniden doğrular (Constitution I, sunucu tarafı). Bekleyen PO teyidi geçersizdir.
 */
export function poYenidenDenemedeGecerli(g: Pick<Detay, "po" | "icerik_hash">): boolean {
  if (g.po.durum === "approved") return poOnayiGuncel(g);
  return g.po.durum !== "pending";
}

/**
 * core `generate-cases` kabul kriteri eksik story'ye 422 döner; ham mesaj ("requirement: …
 * (ac_missing) …") alan öneki ve iç kod taşır. Kullanıcıya temiz Türkçe metin gösterilir.
 */
export function caseUretHatasi(e: unknown): never {
  if (e instanceof ApiError && e.status === 422 && /ac_missing|kabul kriter/i.test(e.detail)) {
    throw new ApiError(422, "Kabul kriteri olmayan gereksinimden case üretilemez. Önce PO'dan kabul kriterlerini alın.");
  }
  throw e;
}

function PoKarti({ g, yenile }: { g: Detay; yenile: () => void }) {
  const islem = useIslem();
  const bildir = useBildirim();
  const po = g.po;
  // Onay var ve içerik onaydan sonra değişmediyse kapı geçilmiştir; sabit kural metni "henüz
  // geçilmedi" gibi okunmasın.
  const kapiGecildi =
    po.durum === "approved" && !(po.onaylanan_hash && g.icerik_hash && po.onaylanan_hash !== g.icerik_hash);
  return (
    <Kart baslik="PO teyidi" id={BOLUM_ID.po} className={`insan-kapisi ${kapiGecildi ? "kapi-gecti" : "kapi-bekliyor"}`}>
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
          {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
        </>
      ) : uretimHatasiMi(g) ? (
        <p className="soluk" data-testid="po-uretim-hatasi">
          PO teyidi verilmişti; case üretimi hata ile bitti. Yeniden denemede onayın güncelliği sunucuda yeniden doğrulanır.
        </p>
      ) : (
        <p className="soluk">Henüz istenmedi. Doküman "son hâl" olunca PO teyidi istenir.</p>
      )}
      {kapiGecildi ? (
        <p className="kucuk" data-testid="po-kapisi">
          ✓ İnsan kapısı geçildi: PO onayı alındı, case üretimine geçilebilir.
        </p>
      ) : (
        <p className="soluk kucuk" data-testid="po-kapisi">
          İnsan kapısı: PO teyidi olmadan case üretimine geçilmez.
        </p>
      )}
    </Kart>
  );
}


const AC_BASLIGI = "🔑 Acceptance Criteria (Kabul Kriterleri)";

/** Story açıklaması Jira'daki gibi: şablon başlıkları, maddeler, numaralı akış; AC'ler şablondaki
 *  yerinde (QA Checklist'ten önce). Şablonsuz açıklamada AC listesi açıklamanın altındadır. */
function Dokuman({ g }: { g: Detay }) {
  const { bloklar, sablon } = dokumanBloklari(g.aciklama);
  const acler =
    g.kabul_kriterleri.length === 0 ? (
      <Uyari>
        Kabul kriteri yok. Story case üretimine gönderilmez; ön inceleme eksik kabul kriterlerini PO'ya soru olarak iletir.
      </Uyari>
    ) : (
      <ol className="ac-liste">
        {g.kabul_kriterleri.map((ac) => (
          <li key={ac.ref}>
            <span className="mono ac-ref">{ac.ref}</span> {ac.metin}
          </li>
        ))}
      </ol>
    );
  return (
    <div className="dokuman">
      {bloklar.map((b, i) => {
        switch (b.tur) {
          case "baslik":
            return <h4 key={i}>{b.metin}</h4>;
          case "liste": {
            const Liste = b.numarali ? "ol" : "ul";
            return (
              <Liste key={i}>
                {b.maddeler.map((m, j) => (
                  <li key={j}>{m}</li>
                ))}
              </Liste>
            );
          }
          case "paragraf":
            return (
              <p key={i}>
                {b.satirlar.map((s, j) => (
                  <span key={j}>
                    {j > 0 && <br />}
                    {s}
                  </span>
                ))}
              </p>
            );
          case "ac":
            return (
              <section key={i}>
                <h4>{AC_BASLIGI}</h4>
                {acler}
              </section>
            );
        }
      })}
      {!sablon && acler}
    </div>
  );
}

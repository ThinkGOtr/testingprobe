import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Bulgu, BulguKarari, Gereksinim, GereksinimDurumu, Kanit } from "../api/types";
import { useIslem } from "../hooks";
import { BULGU_DURUMU, BULGU_KARARI, BULGU_TURU, gereksinimDurumu as durumEtiketi } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { FarkGorunumu } from "./FarkGorunumu";
import { KisiAdi } from "./KisiAdi";
import { KodGorunumu } from "./KodGorunumu";
import { Cip, IslemDugmesi, ReplayRozeti } from "./ui";

function KanitGorunumu({ k }: { k: Kanit }) {
  if (k.kind === "code") {
    return (
      <div className="kanit">
        <div className="kanit-baslik">
          <span className="cip cip-notr">Kod</span>
          <span className="mono">
            {k.path}:{k.line}
          </span>
          <span className="soluk kucuk">{k.repo}</span>
        </div>
        <KodGorunumu kod={k.snippet} kaynakYolu={k.path} baslangicSatiri={k.line} vurguSatiri={k.line} />
      </div>
    );
  }
  return (
    <div className="kanit">
      <div className="kanit-baslik">
        <span className="cip cip-notr">Veri</span>
        <span className="soluk kucuk">Salt okuma sorgu · özet {k.result_digest}</span>
      </div>
      <pre className="sql" tabIndex={0} aria-label="SQL sorgusu">
        <code>{k.query}</code>
      </pre>
      {k.result_preview && (
        <pre className="sonuc" aria-label="Sorgu sonucu">
          {k.result_preview}
        </pre>
      )}
    </div>
  );
}

/** Doküman "son hâl"e ulaştıktan sonraki gereksinim durumları (uyarılar artık karar beklemez). */
export const SON_HAL_SONRASI = new Set<GereksinimDurumu>(["doc_final", "pending_po", "po_approved", "generating", "cases_ready", "done"]);

export function BulguKarti({
  bulgu,
  gereksinimDurumu,
  kaynak = "jira",
  guncellendi,
  yenile,
}: {
  bulgu: Bulgu;
  /**
   * Gereksinimin durumu: core bulgu kararını yalnızca `findings_open` iken kabul eder. Başka
   * durumda (ör. son hâl, PO teyidi, yayınlandı) karar formu gösterilmez. Verilmezse kısıtlanmaz.
   */
  gereksinimDurumu?: GereksinimDurumu;
  /** Düzeltmenin nereye yazıldığı: Jira story'si ya da serbest metin doküman. */
  kaynak?: Gereksinim["kaynak"];
  guncellendi: (b: Bulgu) => void;
  /** 409 (içerik siz görüntüledikten sonra değişti): bulguları yeniden yükler. */
  yenile?: () => void;
}) {
  const [duzenle, setDuzenle] = useState(bulgu.karar === null);
  const [karar, setKarar] = useState<BulguKarari | null>(bulgu.karar);
  const [metin, setMetin] = useState(bulgu.karar_metni ?? bulgu.suggested_doc_text ?? "");
  const [gerekce, setGerekce] = useState(bulgu.gerekce ?? "");
  const [dogrulama, setDogrulama] = useState<string | null>(null);
  const islem = useIslem();
  const id = useId();
  // core: kapı yalnızca open → decided; decided iken karar değiştirilebilir. Diğer durumlar kilitli.
  const bulguKarariAcik = bulgu.durum === "open" || bulgu.durum === "decided";
  const gereksinimKararBekliyor = gereksinimDurumu === undefined || gereksinimDurumu === "findings_open";
  const kararVerilebilir = bulguKarariAcik && gereksinimKararBekliyor;
  // `unverified` kanıt doğrulanmış gibi gösterilmez (bayrak ne derse desin).
  const kanitDogrulandi = bulgu.kanit_dogrulandi && bulgu.durum !== "unverified";
  const dd = BULGU_DURUMU[bulgu.durum] ?? { etiket: bulgu.durum, ton: "notr" as const };

  async function gonder(e: FormEvent) {
    e.preventDefault();
    if (!karar) return setDogrulama("Bir karar seçin.");
    if (karar === "accept_difference" && !gerekce.trim()) return setDogrulama("Bilinçli fark için gerekçe zorunludur.");
    if (karar === "fix_doc" && !metin.trim()) return setDogrulama("Düzeltilmiş metin boş olamaz.");
    setDogrulama(null);
    const yeni = await islem.calistir(() =>
      api.bulguKarari(bulgu.id, {
        icerik_hash: bulgu.icerik_hash,
        karar,
        ...(karar === "fix_doc" ? { metin: metin.trim() } : {}),
        ...(gerekce.trim() ? { gerekce: gerekce.trim() } : {}),
      }),
      { cakismada: yenile },
    );
    if (yeni) {
      setDuzenle(false);
      guncellendi(yeni);
    }
  }

  return (
    <article className={`bulgu bulgu-${bulgu.severity}`} data-durum={bulgu.durum} aria-labelledby={`${id}-baslik`}>
      <header className="bulgu-baslik">
        <div className="satir-ogeler">
          <Cip ton={bulgu.severity === "blocking" ? "hata" : "uyari"}>{bulgu.severity === "blocking" ? "Engelleyici" : "Uyarı"}</Cip>
          {bulgu.bulgu_etiketi && (
            <span className="mono" data-testid="bulgu-etiketi" title="Jira düzeltme yorumundaki bulgu etiketi">
              {bulgu.bulgu_etiketi}
            </span>
          )}
          <Cip ton="vurgu">{BULGU_TURU[bulgu.type] ?? bulgu.type}</Cip>
          <span className="mono">{bulgu.doc_ref}</span>
          <ReplayRozeti mode={bulgu.mode} />
          {bulgu.durum !== "open" && <Cip ton={dd.ton}>{dd.etiket}</Cip>}
        </div>
        {kanitDogrulandi ? (
          <span className="rozet rozet-dogrulandi" title="Kanıt deterministik olarak yeniden çekildi ve eşleşti.">
            ✓ kanıt doğrulandı
          </span>
        ) : (
          <span className="rozet rozet-dogrulanamadi">kanıt doğrulanamadı</span>
        )}
      </header>
      <h3 id={`${id}-baslik`} className="bulgu-ozet">
        {bulgu.ozet}
      </h3>

      {bulgu.evidence.length > 0 ? (
        <div className="kanitlar">
          {bulgu.evidence.map((k, i) => (
            <KanitGorunumu key={i} k={k} />
          ))}
        </div>
      ) : (
        <p className="soluk kucuk">Kanıt dokümanın kendisi (iç tutarlılık).</p>
      )}

      {!duzenle && bulgu.karar ? (
        <div className="karar-ozet">
          <div>
            <strong>Karar:</strong> {BULGU_KARARI[bulgu.karar]}
            {bulgu.durum === "resolved" && bulgu.karar === "fix_doc" && (
              <Cip ton="basari">{kaynak === "jira" ? "Jira'ya yazıldı" : "Dokümana uygulandı"}</Cip>
            )}
            {bulgu.durum === "decided" && bulgu.karar === "fix_doc" && (
              <Cip ton="uyari">{kaynak === "jira" ? "Yazılmayı bekliyor" : "Uygulanmayı bekliyor"}</Cip>
            )}
          </div>
          {bulgu.karar === "fix_doc" && bulgu.mevcut_doc_text && bulgu.karar_metni && (
            <FarkGorunumu eski={bulgu.mevcut_doc_text} yeni={bulgu.karar_metni} />
          )}
          {bulgu.gerekce && (
            <p>
              <strong>Gerekçe:</strong> {bulgu.gerekce}
            </p>
          )}
          {bulgu.bug_draft_id && (
            <p>
              <Link to={`/bug-taslaklari/${encodeURIComponent(bulgu.bug_draft_id)}`}>Bug taslağına git</Link>
            </p>
          )}
          <p className="soluk kucuk">
            <KisiAdi ad={bulgu.karar_veren} /> · {tarih(bulgu.karar_zamani)} · kontrol turu {bulgu.onceki_karar?.kontrol_turu ?? bulgu.kontrol_turu}
          </p>
          {bulgu.onceki_karar && (
            <p className="soluk kucuk" data-testid="onceki-karar">
              Bu fark tur {bulgu.kontrol_turu}'de yeniden raporlandı; tur {bulgu.onceki_karar.kontrol_turu}'deki insan kararı devralındı
              (yeniden karar gerekmiyor).
            </p>
          )}
          {kararVerilebilir && (
            <IslemDugmesi roller={["analyst"]} tur="ikincil" kucuk onClick={() => setDuzenle(true)}>
              Kararı değiştir
            </IslemDugmesi>
          )}
        </div>
      ) : bulguKarariAcik && gereksinimDurumu && !gereksinimKararBekliyor ? (
        <p className="soluk" role="status" data-testid="bulgu-salt-okunur">
          {bulgu.severity === "warning" && SON_HAL_SONRASI.has(gereksinimDurumu)
            ? `Uyarı — karar gerekmiyor; doküman son hâl (${durumEtiketi(gereksinimDurumu).etiket}).`
            : `Gereksinim şu an bulgu kararı beklemiyor (${durumEtiketi(gereksinimDurumu).etiket}).`}
        </p>
      ) : !kararVerilebilir ? (
        <p className="soluk" role="status">
          {bulgu.durum === "unverified"
            ? "Kanıt henüz deterministik olarak doğrulanmadı; doğrulanana kadar karar verilemez."
            : bulgu.durum === "stale"
              ? "Doküman değiştiği için bu bulgu güncelliğini yitirdi; yeni kontrol turunun bulgularına bakın."
              : `Bu bulgu için karar verilemez (${dd.etiket}).`}
        </p>
      ) : (
        <form className="karar-formu" onSubmit={gonder} noValidate>
          <fieldset>
            <legend>Analist kararı</legend>
            <div className="secenekler">
              {(["fix_doc", "code_defect", "accept_difference"] as const).map((k) => (
                <label key={k} className={`secenek${karar === k ? " secili" : ""}`}>
                  <input
                    type="radio"
                    name={`${id}-karar`}
                    value={k}
                    checked={karar === k}
                    onChange={() => {
                      // Önceki karara ait doğrulama mesajı (ör. gerekçe zorunlu) yeni seçimde kalmaz.
                      setKarar(k);
                      setDogrulama(null);
                      islem.temizle();
                    }}
                  />
                  {BULGU_KARARI[k]}
                </label>
              ))}
            </div>
          </fieldset>

          {karar === "fix_doc" && (
            <div className="alan">
              <label htmlFor={`${id}-metin`}>Önerilen doküman metni (düzenlenebilir)</label>
              <textarea id={`${id}-metin`} rows={3} value={metin} onChange={(e) => setMetin(e.target.value)} />
              {bulgu.mevcut_doc_text && (
                <>
                  <div className="soluk kucuk">Mevcut metne göre fark:</div>
                  <FarkGorunumu eski={bulgu.mevcut_doc_text} yeni={metin} />
                </>
              )}
            </div>
          )}
          {karar === "code_defect" && (
            <p className="soluk">Doküman doğru, uygulama hatalı: bu bulgu için bug taslağı oluşturulur ve testçinin onayına düşer.</p>
          )}
          {karar === "accept_difference" && (
            <div className="alan">
              <label htmlFor={`${id}-gerekce`}>
                Gerekçe <span aria-hidden="true">*</span>
                <span className="gorunmez">(zorunlu)</span>
              </label>
              <textarea
                id={`${id}-gerekce`}
                rows={2}
                value={gerekce}
                onChange={(e) => setGerekce(e.target.value)}
                aria-required="true"
              />
            </div>
          )}
          {(dogrulama || islem.hata) && (
            <p className="alan-hata" role="alert">
              {dogrulama ?? islem.hata}
            </p>
          )}
          <div className="eylemler">
            <IslemDugmesi roller={["analyst"]} type="submit" calisiyor={islem.calisiyor}>
              Kararı kaydet
            </IslemDugmesi>
            {bulgu.karar && (
              <button type="button" className="dugme dugme-hayalet" onClick={() => setDuzenle(false)}>
                Vazgeç
              </button>
            )}
          </div>
        </form>
      )}
    </article>
  );
}

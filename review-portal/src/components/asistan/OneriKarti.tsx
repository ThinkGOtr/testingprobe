// Öneri kartı (AI-ASISTAN-PLANI §17.4–17.6): başlık, neden, eylem ("Git" / "Taslağı göster" /
// "Jira'yı aç"), "Neden? Sor" (model kapalıyken "Açıklamayı göster"), hazır soru çipleri, "Yaptım"
// (isteğe bağlı Jira anahtarı) ve "Gizle". Model destekli ek öneri kartı aynı görünür, "AI önerisi ·
// doğrulanmadı" etiketi taşır; onda Yaptım/Gizle yoktur (kural kimliği yok), "Neden? Sor" yerine
// "Bunu sor" öneriyi üreten sohbette sorar. İlke I: hiçbir eylem
// kendiliğinden uygulanmaz; Jira'ya yazılmaz, taslağı kullanıcı kopyalar ve kaydı kendisi açar.
import { useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { JIRA_ANAHTARI, oneriApi, oneriHataMetni, type AsistanOnerisi, type KuralOnerisi, type OneriEylemi, type OneriGeriBildirimDegeri } from "../../api/asistan";
import { goreliZaman, guvenliDisAdres } from "../../lib/format";
import { uygulamaRotasiMi } from "../../lib/rotalar";
import { useBildirim } from "../Bildirim";
import { acSekme, oneriSohbeti } from "./kontrol";

export const NEDEN_SORUSU = "Bu öneriyi neden yapmalıyım, yapmazsam ne olur?";

/** "Neden? Sor" altındaki hazır soru çipleri (Jira çipi yalnız Jira eylemli kartta). */
export const HAZIR_SORULAR: { metin: string; yalnizJira?: boolean }[] = [
  { metin: "Yapmazsam ne olur?" },
  { metin: "Kim onaylıyor?" },
  { metin: "Jira'da nasıl açarım?", yalnizJira: true },
];

const JIRA_EYLEMLERI = new Set(["jira_taslak", "jira_yorum", "jira_kaydi"]);

/** Göreli zaman tek yerde (lib/format, NaN korumalı); eski içe aktarımlar için yeniden dışa aktarılır. */
export { goreliZaman };

/** Panoya giden düz metin: proje, tür, etiketler, özet ve açıklama (yalnız `text/plain`). */
export function taslakMetni(e: Pick<OneriEylemi, "taslak" | "anahtar">): string {
  const t = e.taslak;
  if (!t) return "";
  const satirlar: string[] = [];
  if (t.proje) satirlar.push(`Proje: ${t.proje}`);
  if (e.anahtar) satirlar.push(`Kayıt: ${e.anahtar}`);
  satirlar.push(`Tür: ${t.tur}`);
  if (t.etiketler && t.etiketler.length > 0) satirlar.push(`Etiketler: ${t.etiketler.join(", ")}`);
  if (t.ozet) satirlar.push(`Özet: ${t.ozet}`);
  satirlar.push("", "Açıklama:", t.aciklama);
  return satirlar.join("\n");
}

const KALDIRILDI = "[bağlantı kaldırıldı]";

/**
 * Model taslağı temizliği (§17.5; sunucudaki §7.3 son işleminin istemci tarafı yedeği): URL'ler
 * silinir, Jira wiki bağlantısı (`[metin|adres]`) metne indirgenir, mention (`[~accountid:..]`,
 * `@ad`) sözdizimi temizlenir.
 */
export function aiMetniTemizle(metin: string): string {
  return metin
    .replace(/\[([^\]|]*)\|[^\]]*\]/g, "$1")
    .replace(/\[~[^\]]*\]/g, "")
    .replace(/\b(?:https?:\/\/|ftp:\/\/|www\.)[^\s<>"')\]]+/gi, KALDIRILDI)
    .replace(/(^|[\s(])@([\p{L}\p{N}._-]+)/gu, "$1$2");
}

/** Model önerisini kart biçimine çevirir: metinler temizlenir, iç rota yalnız portal kalıbına uyuyorsa. */
export function aiOnerisiKarta(o: AsistanOnerisi): { baslik: string; neden: string; eylem: OneriEylemi } {
  const e = o.eylem;
  const rota = e.rota && e.rota.startsWith("/") && !e.rota.startsWith("//") && uygulamaRotasiMi(e.rota) ? e.rota : null;
  const baglanti = guvenliDisAdres(e.baglanti);
  const eylem: OneriEylemi =
    e.tur === "rota"
      ? rota
        ? { tur: "rota", rota }
        : { tur: "bilgi" }
      : e.tur === "bilgi"
        ? { tur: "bilgi" }
        : {
            tur: e.tur,
            anahtar: e.anahtar && JIRA_ANAHTARI.test(e.anahtar) ? e.anahtar : null,
            taslak: e.taslak ? { tur: e.taslak.tur, ozet: aiMetniTemizle(e.taslak.ozet), aciklama: aiMetniTemizle(e.taslak.aciklama) } : null,
            baglanti,
          };
  return { baslik: aiMetniTemizle(o.baslik), neden: aiMetniTemizle(o.neden), eylem };
}

/** Eylem alanı: Git / Taslağı göster (+ Kopyala) / Jira'yı aç. */
export function OneriEylemAlani({ eylem, ai, onGit }: { eylem: OneriEylemi; ai?: boolean; onGit?: () => void }) {
  const git = useNavigate();
  const bildir = useBildirim();
  const [taslakAcik, setTaslakAcik] = useState(false);
  const [yedek, setYedek] = useState<string | null>(null);
  const taslakId = useId();

  const kopyala = async () => {
    const metin = taslakMetni(eylem);
    if (!navigator.clipboard?.writeText) {
      setYedek(metin);
      bildir("Pano bu bağlantıda kullanılamıyor (HTTPS değil); metni aşağıdan seçip kopyalayın.", "hata");
      return;
    }
    try {
      await navigator.clipboard.writeText(metin);
      setYedek(null);
      bildir("Taslak panoya kopyalandı.");
    } catch {
      setYedek(metin);
      bildir("Kopyalanamadı; metni aşağıdan seçip kopyalayın.", "hata");
    }
  };

  // Kural önerisinin adresi de yalnız http(s) ise bağlantı olur (AI önerisi `aiOnerisiKarta`da süzülür).
  const jiraAdresi = guvenliDisAdres(eylem.baglanti);
  const jiraAc = jiraAdresi ? (
    <a className="dugme dugme-ikincil dugme-kucuk" href={jiraAdresi} target="_blank" rel="noopener noreferrer">
      Jira'yı aç<span className="gorunmez"> (yeni sekmede açılır)</span>
      <span aria-hidden="true"> ↗</span>
    </a>
  ) : null;

  if (eylem.tur === "bilgi") return null;
  if (eylem.tur === "rota" && eylem.rota) {
    const hedef = eylem.capa ? `${eylem.rota}#${eylem.capa}` : eylem.rota;
    return (
      <div className="oneri-eylemler">
        <button
          type="button"
          className="dugme dugme-birincil dugme-kucuk"
          onClick={() => {
            git(hedef);
            onGit?.();
          }}
        >
          Git
        </button>
      </div>
    );
  }
  if (eylem.tur === "jira_kaydi") {
    return (
      <div className="oneri-eylemler">
        {jiraAc ?? <span className="soluk kucuk">Jira kaydı: {eylem.anahtar ?? "—"}</span>}
        {eylem.not && <p className="oneri-not soluk kucuk">{eylem.not}</p>}
      </div>
    );
  }
  // jira_taslak / jira_yorum
  return (
    <div className="oneri-eylemler">
      <div className="oneri-eylem-satiri">
        {eylem.taslak && (
          <button
            type="button"
            className="dugme dugme-ikincil dugme-kucuk"
            aria-expanded={taslakAcik}
            aria-controls={taslakId}
            onClick={() => setTaslakAcik((a) => !a)}
          >
            {taslakAcik ? "Taslağı gizle" : "Taslağı göster"}
          </button>
        )}
        {jiraAc}
      </div>
      {!eylem.baglanti && eylem.baglanti_yok_nedeni && <p className="soluk kucuk">{eylem.baglanti_yok_nedeni}; taslağı kopyalayıp kaydı elle açın.</p>}
      {taslakAcik && eylem.taslak && (
        <div className="oneri-taslak" id={taslakId}>
          {ai && <p className="oneri-ai-uyari">AI taslağı — göndermeden önce okuyun.</p>}
          <dl className="oneri-taslak-alanlar">
            {eylem.taslak.proje && (
              <>
                <dt>Proje</dt>
                <dd>{eylem.taslak.proje}</dd>
              </>
            )}
            {eylem.anahtar && (
              <>
                <dt>Kayıt</dt>
                <dd className="mono">{eylem.anahtar}</dd>
              </>
            )}
            <dt>Tür</dt>
            <dd>{eylem.taslak.tur}</dd>
            {eylem.taslak.etiketler && eylem.taslak.etiketler.length > 0 && (
              <>
                <dt>Etiketler</dt>
                <dd>{eylem.taslak.etiketler.join(", ")}</dd>
              </>
            )}
            {eylem.taslak.ozet && (
              <>
                <dt>Özet</dt>
                <dd>{eylem.taslak.ozet}</dd>
              </>
            )}
          </dl>
          <div className="oneri-taslak-metin">{eylem.taslak.aciklama}</div>
          {eylem.adim_notu && <p className="soluk kucuk">{eylem.adim_notu}</p>}
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => void kopyala()}>
            Kopyala
          </button>
          {yedek !== null && (
            <textarea
              className="oneri-kopya-yedek"
              aria-label="Kopyalanacak taslak metni"
              readOnly
              value={yedek}
              rows={6}
              onFocus={(e) => e.currentTarget.select()}
            />
          )}
        </div>
      )}
      <p className="oneri-not soluk kucuk">{eylem.not ?? "Bu bir öneridir; kaydı siz açarsınız."}</p>
    </div>
  );
}

export interface OneriKartiOzellikleri {
  oneri: KuralOnerisi;
  /** Model hazır: "Neden? Sor" + çipler; değilse "Açıklamayı göster". */
  modelAcik: boolean;
  /** Ekrandaki varlığın kimliği (geri bildirim için). */
  varlikId: string | null;
  vurgulu?: boolean;
  onGit?: () => void;
  /** Geri bildirim kaydedilince (liste yeniden okunur; "Gizle" kartı hemen kaldırır). */
  onGeriBildirim: (kuralId: string, deger: OneriGeriBildirimDegeri) => void;
}

export function OneriKarti({ oneri, modelAcik, varlikId, vurgulu, onGit, onGeriBildirim }: OneriKartiOzellikleri) {
  const bildir = useBildirim();
  const [aciklamaAcik, setAciklamaAcik] = useState(false);
  const [yaptimAcik, setYaptimAcik] = useState(false);
  const [anahtar, setAnahtar] = useState("");
  const [hata, setHata] = useState<string | null>(null);
  const [gonderiyor, setGonderiyor] = useState(false);
  const [faydali, setFaydali] = useState(false);
  const baslikId = useId();
  const alanId = useId();
  const jiraEylemi = JIRA_EYLEMLERI.has(oneri.eylem.tur);

  // Aynı kural için "Neden? Sor" sohbeti açıldıysa çip sorusu oraya (takip) gider; yoksa yeni sohbet.
  const sor = (soru: string) => {
    const sohbetId = oneriSohbeti(oneri.kural_id, varlikId);
    acSekme("sohbet", sohbetId ? { soru, sohbetId } : { oneriKuralId: oneri.kural_id, soru });
  };

  const geriBildir = async (deger: OneriGeriBildirimDegeri) => {
    const jira = anahtar.trim().toUpperCase();
    if (deger === 2 && jira && !JIRA_ANAHTARI.test(jira)) {
      setHata("Jira anahtarı biçimi geçersiz (ör. TPD-12).");
      return;
    }
    setGonderiyor(true);
    setHata(null);
    try {
      await oneriApi.geriBildirim(oneri.kural_id, {
        deger,
        ...(varlikId ? { varlik_id: varlikId } : {}),
        ...(deger === 2 && jira ? { jira_anahtari: jira } : {}),
      });
      bildir(
        deger === 2 ? "Kaydedildi: bu öneri bu durumda herkes için kapandı." : deger === 1 ? "Teşekkürler: faydalı olarak işaretlendi." : "Öneri sizin için gizlendi.",
      );
      if (deger === 1) setFaydali(true);
      setYaptimAcik(false);
      onGeriBildirim(oneri.kural_id, deger);
    } catch (e) {
      setHata(oneriHataMetni(e));
    } finally {
      setGonderiyor(false);
    }
  };

  return (
    <article
      className={`oneri-karti${vurgulu ? " oneri-karti-vurgulu" : ""}`}
      aria-labelledby={baslikId}
      data-kural-id={oneri.kural_id}
    >
      <h3 id={baslikId} className="oneri-baslik">
        {oneri.baslik}
      </h3>
      <p className="oneri-neden">{oneri.neden}</p>
      <OneriEylemAlani eylem={oneri.eylem} onGit={onGit} />

      <div className="oneri-alt">
        {modelAcik ? (
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => sor(NEDEN_SORUSU)}>
            Neden? Sor
          </button>
        ) : (
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-expanded={aciklamaAcik} onClick={() => setAciklamaAcik((a) => !a)}>
            {aciklamaAcik ? "Açıklamayı gizle" : "Açıklamayı göster"}
          </button>
        )}
        <button
          type="button"
          className="dugme dugme-hayalet dugme-kucuk"
          aria-pressed={faydali}
          onClick={() => void geriBildir(1)}
          disabled={gonderiyor || faydali}
          title="Bu öneri işe yaradı (kart kalır; Kontrol Kulesi ölçümüne girer)"
        >
          Faydalı
        </button>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-expanded={yaptimAcik} onClick={() => setYaptimAcik((a) => !a)} disabled={gonderiyor}>
          Yaptım
        </button>
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void geriBildir(-1)} disabled={gonderiyor} title="Bu öneriyi yalnız sizin için gizler (faydasız)">
          Gizle
        </button>
      </div>

      {modelAcik && (
        <ul className="oneri-cipler" aria-label="Hazır sorular">
          {HAZIR_SORULAR.filter((s) => !s.yalnizJira || jiraEylemi).map((s) => (
            <li key={s.metin}>
              <button type="button" className="cip cip-notr oneri-cipi" onClick={() => sor(s.metin)}>
                {s.metin}
              </button>
            </li>
          ))}
        </ul>
      )}

      {!modelAcik && aciklamaAcik && <p className="oneri-aciklama">{oneri.aciklama || oneri.neden}</p>}

      {yaptimAcik && (
        <form
          className="oneri-yaptim"
          onSubmit={(e) => {
            e.preventDefault();
            void geriBildir(2);
          }}
        >
          <label htmlFor={alanId} className="kucuk">
            Jira anahtarı (isteğe bağlı)
          </label>
          <input
            id={alanId}
            value={anahtar}
            onChange={(e) => setAnahtar(e.target.value)}
            placeholder="TPD-12"
            maxLength={64}
            autoComplete="off"
            spellCheck={false}
          />
          <div className="oneri-eylem-satiri">
            <button type="submit" className="dugme dugme-birincil dugme-kucuk" disabled={gonderiyor}>
              Kaydet
            </button>
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setYaptimAcik(false)}>
              Vazgeç
            </button>
          </div>
        </form>
      )}
      {hata && (
        <p className="oneri-hata" role="alert">
          {hata}
        </p>
      )}
    </article>
  );
}

/** AI öneri kartının "Bunu sor" sorusu: başlık ve gerekçe soruya taşınır (soru sınırı içinde). */
export function aiOneriSorusu(baslik: string, neden: string): string {
  const b = baslik.slice(0, 200);
  const n = neden.slice(0, 600);
  return `"${b}" önerisini neden yapmalıyım, yapmazsam ne olur?${n ? ` Önerinin gerekçesi: ${n}` : ""}`;
}

/**
 * Model destekli ek öneri kartı ("AI önerisi · doğrulanmadı"). Kural kimliği olmadığından
 * "Neden? Sor" yerine "Bunu sor": başlık ve gerekçe, öneriyi üreten sohbette (verildiyse) soru
 * olarak sorulur; hazır soru çipleri aynı sohbete gider.
 */
export function AiOneriKarti({ oneri, onGit, sohbetId }: { oneri: AsistanOnerisi; onGit?: () => void; sohbetId?: string }) {
  const k = aiOnerisiKarta(oneri);
  const baslikId = useId();
  const jiraEylemi = JIRA_EYLEMLERI.has(k.eylem.tur);
  const sor = (soru: string) => acSekme("sohbet", { soru, ...(sohbetId ? { sohbetId } : {}) });
  return (
    <article className="oneri-karti oneri-karti-ai" aria-labelledby={baslikId}>
      <span className="oneri-ai-etiket">AI önerisi · doğrulanmadı</span>
      <h3 id={baslikId} className="oneri-baslik">
        {k.baslik}
      </h3>
      <p className="oneri-neden">{k.neden}</p>
      <OneriEylemAlani eylem={k.eylem} ai onGit={onGit} />
      <div className="oneri-alt">
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => sor(aiOneriSorusu(k.baslik, k.neden))}>
          Bunu sor
        </button>
      </div>
      <ul className="oneri-cipler" aria-label="Hazır sorular">
        {HAZIR_SORULAR.filter((s) => !s.yalnizJira || jiraEylemi).map((s) => (
          <li key={s.metin}>
            <button type="button" className="cip cip-notr oneri-cipi" onClick={() => sor(`${s.metin} (Öneri: ${k.baslik.slice(0, 200)})`)}>
              {s.metin}
            </button>
          </li>
        ))}
      </ul>
    </article>
  );
}

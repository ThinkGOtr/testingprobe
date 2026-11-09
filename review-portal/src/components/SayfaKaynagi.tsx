// 009: uygulama testinin hata anı kanıtları — Appium sayfa kaynağı (XML) ve ekran görüntüsü.
//
// Sayfa kaynağı güvenilmeyen veridir (uygulamanın ekranındaki metinler dahil): yalnızca düz metin
// olarak gösterilir (React kaçışı; HTML/XML yorumlanmaz), boyutu sınırlıdır ve kullanıcı açınca okunur.
import { useId, useRef, useState } from "react";
import { artefaktMetniOku, okunabilirArtefakt, SAYFA_KAYNAGI_SINIRI, type ArtefaktMetni } from "../api/artefakt";
import { Baglanti, Yukleniyor } from "./ui";

const kb = (bayt: number) => `${Math.round(bayt / 1024).toLocaleString("tr-TR")} KB`;

export function SayfaKaynagiGoruntuleyici({ url, etiket = "Hata anı sayfa kaynağı (Appium)" }: { url: string | null; etiket?: string }) {
  const [veri, setVeri] = useState<ArtefaktMetni | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [yukleniyor, setYukleniyor] = useState(false);
  const istendi = useRef(false);
  const okunur = okunabilirArtefakt(url);
  const baslikId = useId();

  const yukle = async () => {
    if (!url || istendi.current) return;
    istendi.current = true;
    setYukleniyor(true);
    setHata(null);
    try {
      setVeri(await artefaktMetniOku(url));
    } catch (e) {
      istendi.current = false; // kapatıp açınca yeniden denenir
      setHata(e instanceof Error ? e.message : "Sayfa kaynağı okunamadı.");
    } finally {
      setYukleniyor(false);
    }
  };

  return (
    <section className="sayfa-kaynagi" aria-labelledby={baslikId} data-testid="sayfa-kaynagi">
      <h3 id={baslikId} className="kanit-baslik">
        {etiket}
      </h3>
      <p className="kucuk soluk">
        Testin başarısız olduğu andaki ekran ağacı (erişilebilirlik kimlikleri ve metinler). Onarım önerisi yeni kimliği bu dosyadan
        bulur.{" "}
        {url && !url.startsWith("data:") && (
          <Baglanti href={url} yokNedeni="dosya sunucusu yok">
            Ham dosyayı aç
          </Baglanti>
        )}
      </p>
      {okunur ? (
        <details
          className="sayfa-kaynagi-ac"
          onToggle={(e) => {
            if ((e.currentTarget as HTMLDetailsElement).open) void yukle();
          }}
        >
          <summary>Sayfa kaynağını göster (XML)</summary>
          {yukleniyor && <Yukleniyor metin="Sayfa kaynağı okunuyor…" />}
          {hata && (
            <p className="kucuk hata-metin" role="alert">
              {hata}
            </p>
          )}
          {veri && (
            <>
              {veri.kesildi && (
                <p className="kucuk uyari-metin" data-testid="sayfa-kaynagi-kesildi">
                  Dosya büyük: ilk {kb(SAYFA_KAYNAGI_SINIRI)} gösteriliyor. Tamamı için ham dosyayı açın.
                </p>
              )}
              <pre className="kod-blok sayfa-kaynagi-xml" tabIndex={0} aria-label={`${etiket} (XML, ${kb(veri.bayt)})`}>
                {veri.metin}
              </pre>
            </>
          )}
        </details>
      ) : (
        <p className="kucuk soluk">Sayfa kaynağı portaldan açılamıyor ({url ? "core artefakt ucu değil" : "dosya sunucusu yok"}).</p>
      )}
    </section>
  );
}

/** Hata anı ekran görüntüsü: dikey (telefon) görüntü de sığar (en çok yükseklik, oran korunur). */
export function EkranGoruntusuKaniti({ url, etiket = "Hata anı ekran görüntüsü" }: { url: string | null; etiket?: string }) {
  if (!url || !okunabilirArtefakt(url)) return null;
  return (
    <figure className="kanit-ekran" data-testid="kanit-ekran">
      <img src={url} alt={etiket} loading="lazy" />
      <figcaption className="kucuk soluk">{etiket}</figcaption>
    </figure>
  );
}

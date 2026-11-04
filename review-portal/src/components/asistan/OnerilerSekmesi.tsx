// Asistan panelinin "Öneriler" sekmesi (AI-ASISTAN-PLANI §17.4–17.6): kural önerileri öncelik
// sırasıyla, "Yaptım" ile bastırılanlar ("{kişi} yaptım dedi · TPD-12 · 2 sa önce"), "Diğer
// ekranlarda N iş → Git" (rozete sayılmaz), boş durum ve "Başka ne yapabilirim?" (model açıksa).
// Veri Öneri düğmesiyle ortak depodan (`OneriVerisi`) gelir; panel bu bileşeni sekme kabında çizer,
// imza sözleşmedir.
import "./oneri.css";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { AsistanDurumu } from "../../api/asistan";
import { useOturum } from "../../auth";
import type { EkranBaglami } from "../../lib/ekranBaglami";
import { BosDurum, Uyari, Yukleniyor } from "../ui";
import { OneriEkOneriler } from "./OneriEkOneriler";
import { goreliZaman, OneriKarti } from "./OneriKarti";
import { oneriAnahtari, oneriGetir, oneriSorgusu, useOneriDurumu } from "./OneriVerisi";

export interface OnerilerSekmesiOzellikleri {
  ekran: EkranBaglami;
  /** Asistan durumu (model kapalıyken "Başka ne yapabilirim?" gizlenir); asistan kapalıyken null. */
  asistan: AsistanDurumu | null;
  /** Öneri düğmesi/bağlantısıyla açıldıysa vurgulanacak kural. */
  oneriKuralId?: string | null;
  /** "Git" sonrası (mobilde panel kapanır). */
  onGit?: () => void;
}

/** Model hazır mı: "Neden? Sor" ve "Başka ne yapabilirim?" yalnız o zaman. */
export function modelHazir(asistan: AsistanDurumu | null): boolean {
  if (!asistan || !asistan.etkin) return false;
  return asistan.model_hazir ?? asistan.mod === "live";
}

export function OnerilerSekmesi({ ekran, asistan, oneriKuralId, onGit }: OnerilerSekmesiOzellikleri) {
  const { kullanici } = useOturum();
  const sorgu = oneriSorgusu(ekran);
  const anahtar = kullanici && sorgu ? oneriAnahtari(kullanici.id, sorgu) : null;
  const durum = useOneriDurumu(anahtar);
  const [gizlenen, setGizlenen] = useState<Set<string>>(() => new Set());
  const modelAcik = modelHazir(asistan);

  // Sekme açıldığında veri yoksa okunur (düğmenin isteği uçuştaysa paylaşılır).
  useEffect(() => {
    if (anahtar && sorgu) void oneriGetir(anahtar, sorgu);
    setGizlenen(new Set());
    // `sorgu` anahtardan türer; yalnız anahtar değişince.
  }, [anahtar]);

  // Vurgulanan kart görünür alana.
  useEffect(() => {
    if (!oneriKuralId || !durum.sonuc) return;
    const el = Array.from(document.querySelectorAll<HTMLElement>("[data-kural-id]")).find((e) => e.dataset.kuralId === oneriKuralId);
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest" });
  }, [oneriKuralId, durum.sonuc]);

  const yenile = () => {
    if (anahtar && sorgu) void oneriGetir(anahtar, sorgu, { zorla: true });
  };

  if (!sorgu) {
    return (
      <div className="asistan-oneriler-sekmesi" data-testid="oneriler-sekmesi">
        <BosDurum baslik="Bu ekranda öneri yok.">Öneriler portal ekranlarında listelenir.</BosDurum>
      </div>
    );
  }
  if (durum.gizli) {
    return (
      <div className="asistan-oneriler-sekmesi" data-testid="oneriler-sekmesi">
        <BosDurum baslik="Öneriler bu ekranda kullanılamıyor.">Bu kurulumda öneriler kapalı ya da bu kayıt rolünüze açık değil.</BosDurum>
      </div>
    );
  }
  const sonuc = durum.sonuc;
  if (!sonuc) {
    return (
      <div className="asistan-oneriler-sekmesi" data-testid="oneriler-sekmesi">
        {durum.hata ? (
          <Uyari ton="hata" baslik="Öneriler okunamadı">
            {durum.hata}{" "}
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={yenile}>
              Yeniden dene
            </button>
          </Uyari>
        ) : (
          <Yukleniyor metin="Öneriler okunuyor…" />
        )}
      </div>
    );
  }

  const oneriler = [...sonuc.oneriler].filter((o) => !gizlenen.has(o.kural_id)).sort((a, b) => b.oncelik - a.oncelik);
  const diger = sonuc.diger_ekranlar && sonuc.diger_ekranlar.sayi > 0 ? sonuc.diger_ekranlar : null;
  const varlikId = ekran.varlik?.id ?? null;

  const digerSatiri = diger && (
    <p className="oneri-diger">
      Diğer ekranlarda sizi bekleyen {diger.sayi} iş{" "}
      <Link to={diger.rota || "/"} onClick={onGit}>
        Git
      </Link>
    </p>
  );

  return (
    <div className="asistan-oneriler-sekmesi" data-testid="oneriler-sekmesi">
      <div className="oneri-ust">
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={yenile} disabled={durum.yukleniyor} aria-label="Önerileri yenile">
          {durum.yukleniyor ? "Yenileniyor…" : "Yenile"}
        </button>
      </div>
      {durum.hata && <p className="oneri-hata kucuk">{durum.hata}</p>}
      {oneriler.length === 0 ? (
        <BosDurum baslik="Bu ekranda sizin için bekleyen bir iş yok.">
          {!diger && (
            <Link to="/" onClick={onGit}>
              İş kuyruğunuza gidin
            </Link>
          )}
        </BosDurum>
      ) : (
        <ul className="oneri-liste" aria-label="Öneriler">
          {oneriler.map((o) => (
            <li key={o.kural_id}>
              <OneriKarti
                oneri={o}
                modelAcik={modelAcik}
                varlikId={varlikId}
                vurgulu={o.kural_id === oneriKuralId}
                onGit={onGit}
                onGeriBildirim={(kuralId, deger) => {
                  if (deger === -1) setGizlenen((g) => new Set(g).add(kuralId));
                  yenile();
                }}
              />
            </li>
          ))}
        </ul>
      )}

      {sonuc.bastirilan.length > 0 && (
        <ul className="oneri-bastirilanlar" aria-label="Yapıldı olarak işaretlenenler">
          {sonuc.bastirilan.map((b) => (
            <li key={b.kural_id} className="oneri-bastirilan">
              <span className="oneri-bastirilan-baslik">{b.baslik}</span>
              <span className="soluk kucuk">
                {b.kisi} yaptım dedi
                {b.jira_anahtari ? ` · ${b.jira_anahtari}` : ""} · {goreliZaman(b.zaman)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {digerSatiri}
      {modelAcik && <OneriEkOneriler ekran={ekran} onGit={onGit} />}
    </div>
  );
}

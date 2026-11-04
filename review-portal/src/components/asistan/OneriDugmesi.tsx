// Kabuk üst çubuğundaki tek "Öneri" düğmesi (AI-ASISTAN-PLANI §17.6): sayı rozeti yalnız > 0 ise;
// paneli "Öneriler" sekmesinde açar. Gizleme: (rota × rol) için kural yoksa (`ekranda_kural_var=false`),
// yetenek kapısı yüklenirken ya da uç yoksa, uç 404/"bu fazda yok" ise. Rozet yenileme: rota/varlık
// değişince bir istek; açık varlığın olaylarında 5 sn içinde tek yenileme; 429'da son değer korunur.
// Rozet değişimi `aria-live` ile duyurulmaz (gürültü).
import "./oneri.css";
import { useEffect, useRef } from "react";
import { useOlay } from "../../api/events";
import { useOturum } from "../../auth";
import { useEkranBaglami } from "../../lib/ekranBaglami";
import { Ikon } from "../Ikon";
import { acSekme } from "./kontrol";
import { oneriAnahtari, oneriAyar, oneriGetir, oneriOlayiIlgili, oneriOlayKonulari, oneriSorgusu, useOneriDurumu, useOneriYetenegi } from "./OneriVerisi";

export function OneriDugmesi() {
  const { kullanici } = useOturum();
  const ekran = useEkranBaglami();
  const yetenek = useOneriYetenegi();
  const sorgu = oneriSorgusu(ekran);
  const anahtar = kullanici && yetenek && sorgu ? oneriAnahtari(kullanici.id, sorgu) : null;
  const durum = useOneriDurumu(anahtar);
  const sorguRef = useRef(sorgu);
  sorguRef.current = sorgu;
  const zamanlayici = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Rota/varlık (ya da kullanıcı) değişince bir istek.
  useEffect(() => {
    if (anahtar && sorguRef.current) void oneriGetir(anahtar, sorguRef.current, { zorla: true });
  }, [anahtar]);

  // Ekran değişince bekleyen olay yenilemesi iptal.
  useEffect(
    () => () => {
      if (zamanlayici.current) clearTimeout(zamanlayici.current);
      zamanlayici.current = null;
    },
    [anahtar],
  );

  const konular = oneriOlayKonulari(ekran);
  const varlikRef = useRef(ekran.varlik);
  varlikRef.current = ekran.varlik;
  useOlay(
    (o) => {
      if (!anahtar || konular.length === 0 || zamanlayici.current) return;
      // Kimlik süzgeci burada: core'un bulgu/case olayları gereksinim kimliği taşımaz (bkz. oneriOlayiIlgili).
      if (!oneriOlayiIlgili(o, varlikRef.current)) return;
      // İlk olay 5 sn'lik pencereyi açar; penceredeki diğer olaylar aynı yenilemeye katılır.
      zamanlayici.current = setTimeout(() => {
        zamanlayici.current = null;
        if (sorguRef.current) void oneriGetir(anahtar, sorguRef.current, { zorla: true });
      }, oneriAyar.olayGecikmeMs);
    },
    konular.length > 0 ? konular : ["oneri.olay-yok"],
  );

  const sonuc = durum.sonuc;
  if (!anahtar || durum.gizli || !sonuc || !sonuc.ekranda_kural_var) return null;
  const n = sonuc.oneriler.length;
  return (
    <button
      type="button"
      // Üst çubuktaki "Çıkış" ile aynı dil: ikincil küçük düğme (oneri.css yalnız rozet ve vurgu ekler).
      className={`dugme dugme-ikincil dugme-kucuk oneri-dugmesi${n > 0 ? " oneri-dugmesi-var" : ""}`}
      data-testid="oneri-dugmesi"
      aria-label={`Öneriler: ${n}`}
      title={n > 0 ? `Bu ekranda sizi bekleyen ${n} iş` : "Bu ekranda sizi bekleyen iş yok"}
      onClick={() => acSekme("oneriler")}
    >
      <Ikon ad="oneri" />
      {/* Görünür etiket erişilebilir adın içinde kalır ("Öneriler 1" ⊂ "Öneriler (1)", WCAG 2.5.3). */}
      <span className="oneri-etiket" aria-hidden="true">
        Öneriler
      </span>{" "}
      {n > 0 && (
        <span className="oneri-rozet" aria-hidden="true">
          {n}
        </span>
      )}
    </button>
  );
}

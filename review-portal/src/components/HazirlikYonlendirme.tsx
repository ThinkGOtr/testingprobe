// UX-2 (D5): hazır olmayan taslak case'te kartın üstünde "Neden onaylanamıyor / ne yapmalı" kutusu ve
// K20 "Varsayım doğrulandı" eylemi. Açık soru varsa önce o söylenir ve doğrulama düğmesi sunulmaz;
// D6'nın "PO'ya gönder" eylemi `poyaGonder` yuvasına bağlanır.
import { useId, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { TestCase } from "../api/types";
import { useIslem } from "../hooks";
import { hazirlikYonlendirmesi } from "../lib/caseV3";
import { useBildirim } from "./Bildirim";
import { AlanHatasi, IslemDugmesi, SayfaIciOnay } from "./ui";

export function HazirlikYonlendirme({
  tc,
  guncellendi,
  yenile,
  poyaGonder,
}: {
  tc: TestCase;
  /** Başarılı doğrulamadan dönen (onaylı) case. */
  guncellendi: (t: TestCase) => void;
  /** 409 (içerik siz görüntüledikten sonra değişti): case listesini yeniden yükler. */
  yenile?: () => void;
  /** D6: açık soruyu PO'ya gönderme eylemi (ve yanıt gösterimi) bu yuvaya verilir. */
  poyaGonder?: ReactNode;
}) {
  const y = hazirlikYonlendirmesi(tc);
  const islem = useIslem();
  const bildir = useBildirim();
  const [onayAcik, setOnayAcik] = useState(false);
  const [gerekce, setGerekce] = useState("");
  const id = useId();
  if (!y) return null;
  const cok = y.dogrulanacak.length > 1;
  const dugmeMetni = cok ? `Varsayımlar doğrulandı (${y.dogrulanacak.join(", ")})` : "Varsayım doğrulandı";

  async function dogrula() {
    const varsayimlar = y!.dogrulanacak;
    const yeni = await islem.calistir(
      () =>
        api.varsayimDogrulandi(tc.id, {
          // Görülen içeriğin hash'i: arada içerik değiştiyse core 409 döner.
          icerik_hash: tc.icerik_hash,
          varsayim_id: varsayimlar.length === 1 ? varsayimlar[0] : varsayimlar,
          ...(gerekce.trim() ? { gerekce: gerekce.trim() } : {}),
        }),
      {
        cakismada: () => {
          setOnayAcik(false);
          yenile?.();
        },
      },
    );
    if (yeni) {
      setOnayAcik(false);
      bildir(`Case #${tc.sira_no} onaylandı: ${varsayimlar.join(", ")} ${cok ? "varsayımları" : "varsayımı"} doğrulandı.`);
      guncellendi(yeni);
    }
  }

  return (
    <div className="uyari-kutusu uyari-uyari hazirlik-yonlendirme" role="note" aria-labelledby={`${id}-baslik`} data-testid="hazirlik-yonlendirme" data-tur={y.tur}>
      <strong id={`${id}-baslik`}>Neden onaylanamıyor, ne yapmalı?</strong>
      <div>
        <p className="hazirlik-yonlendirme-metin" data-testid="hazirlik-yonlendirme-metin">
          {y.metin}
        </p>
        {y.tur === "soru" && poyaGonder}
        {/* D6: "Açık soruları PO'ya gönder" (PoyaGonderEylemi, CaseListesi bağlar). */}
        {y.dogrulanacak.length > 0 && !onayAcik && (
          <div className="eylemler">
            <IslemDugmesi roller={["analyst"]} kucuk tur="ikincil" calisiyor={islem.calisiyor} onClick={() => setOnayAcik(true)}>
              {dugmeMetni}
            </IslemDugmesi>
          </div>
        )}
        {onayAcik && (
          <SayfaIciOnay
            baslik={`${y.dogrulanacak.join(", ")} doğrulandı mı?`}
            onayMetni="Evet, doğrulandı — onayla"
            calisiyor={islem.calisiyor}
            onayla={() => void dogrula()}
            vazgec={() => setOnayAcik(false)}
            testId="varsayim-dogrulama-onayi"
          >
            <p className="kucuk">
              Case ekranda gördüğünüz içerikle "Hazır" yapılıp onaylanır; beklenen sonuç değişmez. Varsayım yanlışsa vazgeçip "Düzelt" ile
              beklenen sonucu güncelleyin.
            </p>
            <div className="alan">
              <label htmlFor={`${id}-gerekce`}>Doğrulama notu (isteğe bağlı)</label>
              <input id={`${id}-gerekce`} value={gerekce} maxLength={300} placeholder="Ör. PO ile teyit edildi" onChange={(e) => setGerekce(e.target.value)} />
            </div>
          </SayfaIciOnay>
        )}
        {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
      </div>
    </div>
  );
}

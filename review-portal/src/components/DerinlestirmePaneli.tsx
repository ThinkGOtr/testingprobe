import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { DerinlestirmeDurumu, DerinlestirmeGirdisi, DerinlestirmeTeknigi, GereksinimDetay } from "../api/types";
import { useIslem } from "../hooks";
import { DERINLESTIRME_YOK, derinlestirmeAdi, derinlestirmeEngeli, derinlestirmeSonucu } from "../lib/derinlestirme";
import { DERINLESTIRME_TEKNIKLERI } from "../lib/uretimSecenekleri";
import { useBildirim } from "./Bildirim";
import { Cip, HataKutusu, IslemDugmesi, Kart, Uyari, Yukleniyor } from "./ui";

/** Yoklama aralığı (ms); testler küçültür. */
export const derinlestirmeAyari = { aralikMs: 2000 };

/**
 * Derinleştirme paneli (011 §4.8; P5 negatif genişletme, P6 teknikle derinleştirme; K7): mevcut
 * sete ek taslaklar üretir, mevcut taslak ve onaylar korunur. Yalnız analist ve gereksinim
 * `cases_ready` iken etkin (core aksi hâlde 409). Başlatınca `GET deepen` aralıkla yoklanır; bitince
 * `tazele` çağrılır (case listesi ve kapsam özeti yenilenir). Uç yoksa (eski core) panel görünmez.
 */
export function DerinlestirmePaneli({ gereksinim, tazele }: { gereksinim: Pick<GereksinimDetay, "id" | "durum"> | undefined; tazele: () => void }) {
  const id = gereksinim?.id;
  const [durum, setDurum] = useState<DerinlestirmeDurumu | null>(null);
  const [ucYok, setUcYok] = useState(false);
  const [okumaHatasi, setOkumaHatasi] = useState<unknown>(null);
  const [teknik, setTeknik] = useState<DerinlestirmeTeknigi>("EP");
  const islem = useIslem();
  const bildir = useBildirim();
  const kimlik = useId();
  // Bu oturumda "çalışıyor" görüldü mü: yalnız gerçek bir bitişte liste tazelenir ve bildirilir.
  const izleniyor = useRef(false);
  const tazeleRef = useRef(tazele);
  tazeleRef.current = tazele;

  // İlk okuma: son derinleştirmenin durumu (sürüyorsa yoklama başlar).
  useEffect(() => {
    if (!id) return;
    let iptal = false;
    setDurum(null);
    setUcYok(false);
    api
      .derinlestirmeDurumu(id)
      .then((d) => {
        if (iptal) return;
        setDurum(d);
        if (d.durum === "calisiyor") izleniyor.current = true;
      })
      .catch((e: unknown) => {
        if (iptal) return;
        if (e instanceof ApiError && (e.status === 404 || e.status === 501)) setUcYok(true);
        else setOkumaHatasi(e);
      });
    return () => {
      iptal = true;
    };
  }, [id]);

  // Yoklama: durum "calisiyor" iken aralıkla; bitince bir kez tazele.
  const calisiyor = durum?.durum === "calisiyor";
  useEffect(() => {
    if (!id || !calisiyor) return;
    let iptal = false;
    const zaman = setTimeout(() => {
      api
        .derinlestirmeDurumu(id)
        .then((d) => {
          if (iptal) return;
          setDurum(d);
          if (d.durum !== "calisiyor" && izleniyor.current) {
            izleniyor.current = false;
            tazeleRef.current();
            if (d.durum === "tamam") bildir(derinlestirmeSonucu(d) ?? "Derinleştirme tamamlandı.");
          }
        })
        .catch(() => {
          // Geçici okuma hatası: bir sonraki turda yeniden denenir (durum değişmedi → yeniden kur).
          if (!iptal) setDurum((x) => (x ? { ...x } : x));
        });
    }, derinlestirmeAyari.aralikMs);
    return () => {
      iptal = true;
      clearTimeout(zaman);
    };
  }, [id, calisiyor, durum, bildir]);

  if (!gereksinim || ucYok) return null;

  const engel = derinlestirmeEngeli(gereksinim.durum, durum);

  async function baslat(g: DerinlestirmeGirdisi) {
    const y = await islem.calistir(() => api.derinlestir(gereksinim!.id, g));
    if (y === undefined) return;
    izleniyor.current = true;
    bildir(y.mesaj ?? "Derinleştirme başlatıldı.");
    setDurum({ ...DERINLESTIRME_YOK, durum: "calisiyor", tur: g.tur, teknik: g.teknik ?? null, uretim_no: y.uretim_no ?? null });
  }

  const sonuc = durum ? derinlestirmeSonucu(durum) : null;
  const d = durum ?? DERINLESTIRME_YOK;

  return (
    <Kart baslik="Derinleştirme" className="derinlestirme-paneli">
      <p className="soluk kucuk">
        Mevcut case setine ek taslaklar üretir; mevcut taslaklar ve onaylar korunur. Yeni taslaklar ayrı bir üretim numarasıyla listeye
        eklenir ve review'dan geçer.
      </p>
      <div className="eylemler derinlestirme-dugmeleri" data-testid="derinlestirme-dugmeleri">
        <IslemDugmesi
          roller={["analyst"]}
          tur="ikincil"
          disabled={!!engel}
          title={engel ?? "Geçersiz bölümler, hata koşulları ve yetki ihlalleri için ek negatif case'ler üretir"}
          calisiyor={islem.calisiyor}
          onClick={() => void baslat({ tur: "negatif" })}
        >
          Negatif kapsamı genişlet
        </IslemDugmesi>
        <span className="derinlestirme-teknik">
          <label htmlFor={`${kimlik}-teknik`} className="gorunmez">
            Teknik
          </label>
          <select
            id={`${kimlik}-teknik`}
            value={teknik}
            onChange={(e) => setTeknik(e.target.value as DerinlestirmeTeknigi)}
            disabled={!!engel}
            style={{ width: "auto" }}
          >
            {DERINLESTIRME_TEKNIKLERI.map((t) => (
              <option key={t.kod} value={t.kod}>
                {t.kod} — {t.ad}
              </option>
            ))}
          </select>
          <IslemDugmesi
            roller={["analyst"]}
            tur="ikincil"
            disabled={!!engel}
            title={engel ?? "Seçilen test tasarım tekniğiyle ek case'ler üretir"}
            calisiyor={islem.calisiyor}
            onClick={() => void baslat({ tur: "teknik", teknik })}
          >
            Teknikle derinleştir
          </IslemDugmesi>
        </span>
      </div>
      {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
      {okumaHatasi !== null && durum === null && <p className="soluk kucuk">Son derinleştirmenin durumu okunamadı.</p>}

      <div aria-live="polite" data-testid="derinlestirme-durumu">
        {d.durum === "calisiyor" && <Yukleniyor metin={`${derinlestirmeAdi(d.tur, d.teknik)} çalışıyor…`} />}
        {d.durum === "tamam" && (
          <div className="satir-ogeler">
            <Cip ton={(d.yeni_case_sayisi ?? 0) > 0 ? "basari" : "notr"}>{derinlestirmeAdi(d.tur, d.teknik)}</Cip>
            <span>{sonuc}</span>
          </div>
        )}
        {d.durum === "tamam" && d.uyarilar.length > 0 && (
          <Uyari baslik="Uyarılar">
            <ul>
              {d.uyarilar.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          </Uyari>
        )}
        {d.durum === "hata" && (
          <Uyari ton="hata" baslik={`${derinlestirmeAdi(d.tur, d.teknik)} başarısız`}>
            {d.hata && <p>{d.hata}</p>}
            {d.uyarilar.filter((u) => u !== d.hata).length > 0 && (
              <ul>
                {d.uyarilar
                  .filter((u) => u !== d.hata)
                  .map((u) => (
                    <li key={u}>{u}</li>
                  ))}
              </ul>
            )}
            <p className="kucuk">Gereksinim "Case'ler hazır" durumunda kaldı; mevcut case'ler etkilenmedi.</p>
          </Uyari>
        )}
      </div>
    </Kart>
  );
}

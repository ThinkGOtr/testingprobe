import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { DerinlestirmeDurumu, DerinlestirmeGirdisi, DerinlestirmeTeknigi, DerinlestirmeTuru, GereksinimDetay } from "../api/types";
import { useIslem } from "../hooks";
import {
  DERINLESTIRME_SURUYOR,
  DERINLESTIRME_YOK,
  DIGER_DERINLESTIRME_SURUYOR,
  derinlestirmeAdi,
  derinlestirmeEngeli,
  derinlestirmeSonucu,
  YOKLAMA_HATA_SINIRI,
} from "../lib/derinlestirme";
import { DERINLESTIRME_TEKNIKLERI } from "../lib/uretimSecenekleri";
import { useBildirim } from "./Bildirim";
import { Cip, HataKutusu, IslemDugmesi, Kart, Uyari, Yukleniyor } from "./ui";

/** Yoklama aralığı (ms); testler küçültür. */
export const derinlestirmeAyari = { aralikMs: 2000 };

/**
 * Derinleştirme paneli (011 §4.8; P5 negatif genişletme, P6 teknikle derinleştirme; K7): mevcut
 * sete ek taslaklar üretir, mevcut taslak ve onaylar korunur. Yalnız Testçi (`case.generate`) ve gereksinim
 * `cases_ready` ("Case review aşamasında") iken etkin (core aksi hâlde 409). Core tek iş tutar: biri
 * sürerken diğer düğme "Diğer derinleştirme sürüyor" nedeniyle pasiftir. Başlatınca `GET deepen`
 * aralıkla yoklanır; ardışık 3 okuma hatasında yoklama durur ve "Tekrar dene" sunulur. Bitince
 * `tazele` çağrılır (case listesi, kapsam, review ve denetim yenilenir); sonuç satırındaki "göster"
 * `goster(uretim_no)` ile listeyi o üretimin case'lerine süzer (UX-5). Uç yoksa (eski core) panel görünmez.
 */
export function DerinlestirmePaneli({
  gereksinim,
  tazele,
  goster,
}: {
  gereksinim: Pick<GereksinimDetay, "id" | "durum"> | undefined;
  tazele: () => void;
  /** "N yeni taslak eklendi — göster": listeyi bu üretimin case'lerine süzer ve listeye kaydırır. */
  goster?: (uretimNo: number) => void;
}) {
  const id = gereksinim?.id;
  const [durum, setDurum] = useState<DerinlestirmeDurumu | null>(null);
  const [ucYok, setUcYok] = useState(false);
  const [okumaHatasi, setOkumaHatasi] = useState<unknown>(null);
  const [teknik, setTeknik] = useState<DerinlestirmeTeknigi>("EP");
  // POST sürerken hangi düğmenin başlattığı (diğeri pasif, bu düğme "çalışıyor").
  const [baslatilan, setBaslatilan] = useState<DerinlestirmeTuru | null>(null);
  // Yoklamanın ardışık okuma hatası; sınıra ulaşınca yoklama durur.
  const hataSayisi = useRef(0);
  const [yoklamaDurdu, setYoklamaDurdu] = useState(false);
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
    hataSayisi.current = 0;
    setYoklamaDurdu(false);
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

  // Yoklama: durum "calisiyor" iken aralıkla; bitince bir kez tazele. Ardışık hata sınırında durur.
  const calisiyor = durum?.durum === "calisiyor";
  useEffect(() => {
    if (!id || !calisiyor || yoklamaDurdu) return;
    let iptal = false;
    const zaman = setTimeout(() => {
      api
        .derinlestirmeDurumu(id)
        .then((d) => {
          if (iptal) return;
          hataSayisi.current = 0;
          setDurum(d);
          if (d.durum !== "calisiyor" && izleniyor.current) {
            izleniyor.current = false;
            tazeleRef.current();
            if (d.durum === "tamam") bildir(derinlestirmeSonucu(d) ?? "Derinleştirme tamamlandı.");
          }
        })
        .catch(() => {
          if (iptal) return;
          // Geçici okuma hatası: sınırın altındaysa bir sonraki turda yeniden denenir (durum kopyası
          // efekti yeniden kurar); ardışık sınıra ulaşınca durur, kullanıcı "Tekrar dene" ile sürdürür.
          hataSayisi.current += 1;
          if (hataSayisi.current >= YOKLAMA_HATA_SINIRI) setYoklamaDurdu(true);
          else setDurum((x) => (x ? { ...x } : x));
        });
    }, derinlestirmeAyari.aralikMs);
    return () => {
      iptal = true;
      clearTimeout(zaman);
    };
  }, [id, calisiyor, durum, bildir, yoklamaDurdu]);

  function yoklamayiSurdur() {
    hataSayisi.current = 0;
    setYoklamaDurdu(false);
  }

  if (!gereksinim || ucYok) return null;

  // Gereksinim durumundan gelen ortak engel (süren iş ayrıca, düğme başına ele alınır).
  const engel = derinlestirmeEngeli(gereksinim.durum, null);
  const d0 = durum ?? DERINLESTIRME_YOK;
  // Süren işin türü: POST sürerken başlatan düğme, sonra core durumu. Tür bilinmiyorsa ikisi de pasif.
  const suren: DerinlestirmeTuru | "bilinmiyor" | null = islem.calisiyor
    ? (baslatilan ?? "bilinmiyor")
    : d0.durum === "calisiyor"
      ? (d0.tur ?? "bilinmiyor")
      : null;
  const dugmeDurumu = (tur: DerinlestirmeTuru, varsayilanNeden: string) => {
    if (engel) return { disabled: true, title: engel, calisiyor: false };
    if (suren === tur) return { disabled: false, title: varsayilanNeden, calisiyor: true };
    if (suren === "bilinmiyor") return { disabled: true, title: DERINLESTIRME_SURUYOR, calisiyor: false };
    if (suren) return { disabled: true, title: DIGER_DERINLESTIRME_SURUYOR, calisiyor: false };
    return { disabled: false, title: varsayilanNeden, calisiyor: false };
  };
  const negatifDugme = dugmeDurumu("negatif", "Geçersiz bölümler, hata koşulları ve yetki ihlalleri için ek negatif case'ler üretir");
  const teknikDugme = dugmeDurumu("teknik", "Seçilen test tasarım tekniğiyle ek case'ler üretir");

  async function baslat(g: DerinlestirmeGirdisi) {
    setBaslatilan(g.tur);
    const y = await islem.calistir(() => api.derinlestir(gereksinim!.id, g));
    setBaslatilan(null);
    if (y === undefined) return;
    izleniyor.current = true;
    hataSayisi.current = 0;
    setYoklamaDurdu(false);
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
          izin="case.generate"
          tur="ikincil"
          disabled={negatifDugme.disabled}
          title={negatifDugme.title}
          calisiyor={negatifDugme.calisiyor}
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
            disabled={teknikDugme.disabled || teknikDugme.calisiyor}
            style={{ width: "auto" }}
          >
            {DERINLESTIRME_TEKNIKLERI.map((t) => (
              <option key={t.kod} value={t.kod}>
                {t.kod} — {t.ad}
              </option>
            ))}
          </select>
          <IslemDugmesi
            izin="case.generate"
            tur="ikincil"
            disabled={teknikDugme.disabled}
            title={teknikDugme.title}
            calisiyor={teknikDugme.calisiyor}
            onClick={() => void baslat({ tur: "teknik", teknik })}
          >
            Teknikle derinleştir
          </IslemDugmesi>
        </span>
      </div>
      {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
      {okumaHatasi !== null && durum === null && <p className="soluk kucuk">Son derinleştirmenin durumu okunamadı.</p>}
      {yoklamaDurdu && calisiyor && (
        <div data-testid="derinlestirme-yoklama-hatasi">
          <HataKutusu hata="Durum alınamadı — derinleştirmenin son durumu okunamadı." yenile={yoklamayiSurdur} kayitDisi />
        </div>
      )}

      <div aria-live="polite" data-testid="derinlestirme-durumu">
        {d.durum === "calisiyor" && !yoklamaDurdu && <Yukleniyor metin={`${derinlestirmeAdi(d.tur, d.teknik)} çalışıyor…`} />}
        {d.durum === "tamam" && (
          <div className="satir-ogeler">
            <Cip ton={(d.yeni_case_sayisi ?? 0) > 0 ? "basari" : "notr"}>{derinlestirmeAdi(d.tur, d.teknik)}</Cip>
            {(d.yeni_case_sayisi ?? 0) > 0 && d.uretim_no !== null && goster ? (
              <span data-testid="derinlestirme-sonucu">
                {d.yeni_case_sayisi} yeni taslak eklendi —{" "}
                <button
                  type="button"
                  className="baglanti-dugme"
                  aria-label={`Üretim ${d.uretim_no} ile eklenen ${d.yeni_case_sayisi} taslağı listede göster`}
                  onClick={() => goster(d.uretim_no!)}
                >
                  göster
                </button>
              </span>
            ) : (
              <span data-testid="derinlestirme-sonucu">{sonuc}</span>
            )}
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
            <p className="kucuk">Gereksinim "Case review aşamasında" durumunda kaldı; mevcut case'ler etkilenmedi.</p>
          </Uyari>
        )}
      </div>
    </Kart>
  );
}

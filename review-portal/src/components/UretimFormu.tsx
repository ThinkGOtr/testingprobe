import { useEffect, useId, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { EkBilgiAlani, IsYaniti, UretimGovdesi, UretimSecenekleri } from "../api/types";
import type { UretimKipi } from "../api/tasarimModeliTipleri";
import { useIslem, useVeri } from "../hooks";
import { TEST_SEVIYESI } from "../lib/etiketler";
import {
  baslangicSecenekleri,
  EK_BILGI_ALANLARI,
  gorunurAlanlar,
  platformDegistir,
  SECENEK_SINIRI,
  secenekHatalari,
  standartEkle,
  standartSil,
  uretimGovdesi,
  URETIM_PLATFORMLARI,
  URETIM_TEST_SEVIYELERI,
  varsayilanSecenekler,
} from "../lib/uretimSecenekleri";
import { Cip, HataKutusu, IslemDugmesi, Kart, Uyari, Yukleniyor } from "./ui";
import { UretimKipiSecici } from "./UretimKipiSecici";

/** Uç yok (eski core: 404/501): form yerel katalogla açılır, kayıtlı seçenek yoktur. */
const ucYok = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 501);

/**
 * "Üretimi başlat" formu (011 §4.8, K5): platform(lar), test seviyesi, benimsenen standartlar,
 * kapsam dışı, roller ve seçili platforma ait ek bilgiler. Açılışta gereksinimde kayıtlı son
 * seçeneklerle (yoksa varsayılanla) dolar; gönderilen seçenekler gereksinimde saklanır.
 * Form durumu ve kuralları `lib/uretimSecenekleri.ts`'tedir (saf, birim testli).
 * Kip verilirse (gereksinim ekranı) formun ilk alanı kip seçimidir (UX-4); `uyari` gönderimden önce
 * bilinmesi gereken sonucu (ör. mevcut case'lerin yerini yenilerinin alması) formun başında söyler.
 */
export function UretimFormu({
  gereksinimId,
  gonder,
  basladi,
  kapat,
  kip,
  kipDegistir,
  uyari,
}: {
  gereksinimId: string;
  /** Seçili üretim kipi (sayfayla ortak); verilmezse kip alanı çizilmez. */
  kip?: UretimKipi;
  kipDegistir?: (k: UretimKipi) => void;
  uyari?: ReactNode;
  /** Gövdeli `generate-cases` çağrısı (hata dönüşümü çağıranda). */
  gonder: (govde: UretimGovdesi) => Promise<IsYaniti>;
  basladi: (y: IsYaniti) => void;
  kapat: () => void;
}) {
  const yanit = useVeri(
    () =>
      api.uretimSecenekleri(gereksinimId).catch((e: unknown) => {
        if (ucYok(e)) return null;
        throw e;
      }),
    [gereksinimId],
  );
  const [s, setS] = useState<UretimSecenekleri | null>(null);
  const [standartGirdi, setStandartGirdi] = useState("");
  const [standartHata, setStandartHata] = useState<string | null>(null);
  const [hatalar, setHatalar] = useState<string[]>([]);
  const islem = useIslem();
  const kimlik = useId();

  const y = yanit.veri;
  // Yanıt gelince bir kez ön doldurulur (sonraki sessiz yenilemeler girilen değeri ezmez).
  useEffect(() => {
    if (s === null && y !== undefined) setS(y ? baslangicSecenekleri(y) : varsayilanSecenekler());
  }, [y, s]);

  if (yanit.yukleniyor && y === undefined) {
    return (
      <Kart baslik="Üretimi başlat">
        <Yukleniyor metin="Üretim seçenekleri yükleniyor…" />
      </Kart>
    );
  }
  if (yanit.hata && y === undefined) {
    return (
      <Kart baslik="Üretimi başlat">
        <HataKutusu hata={yanit.hata} kaynak={yanit.hataNesnesi} yenile={() => void yanit.yenile()} />
      </Kart>
    );
  }
  if (!s) return null;

  const alanlar = y?.ek_bilgi_alanlari ?? EK_BILGI_ALANLARI;
  const platformlar = y?.platformlar ?? [...URETIM_PLATFORMLARI];
  const seviyeler = y?.test_seviyeleri ?? [...URETIM_TEST_SEVIYELERI];
  const gorunen = gorunurAlanlar(alanlar, s);
  const guncelle = (p: Partial<UretimSecenekleri>) => setS({ ...s, ...p });
  const ekGuncelle = (ad: string, v: string | boolean) => setS({ ...s, ek_bilgi: { ...s.ek_bilgi, [ad]: v } });

  function standartlariEkle() {
    const r = standartEkle(s!.benimsenen_standartlar, standartGirdi);
    setStandartHata(r.hata);
    if (!r.hata) {
      guncelle({ benimsenen_standartlar: r.liste });
      setStandartGirdi("");
    }
  }

  function standartTusu(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      standartlariEkle();
    } else if (e.key === "Backspace" && !standartGirdi && s!.benimsenen_standartlar.length > 0) {
      guncelle({ benimsenen_standartlar: s!.benimsenen_standartlar.slice(0, -1) });
    }
  }

  async function gonderForm(e: FormEvent) {
    e.preventDefault();
    // Yazılıp eklenmemiş standart kodu da gönderime katılır (Enter'a basılmadan "Başlat").
    let guncel = s!;
    if (standartGirdi.trim()) {
      const r = standartEkle(guncel.benimsenen_standartlar, standartGirdi);
      setStandartHata(r.hata);
      if (r.hata) return;
      guncel = { ...guncel, benimsenen_standartlar: r.liste };
      setS(guncel);
      setStandartGirdi("");
    }
    const govde = uretimGovdesi(guncel, alanlar);
    const h = secenekHatalari(govde, alanlar, platformlar, seviyeler);
    setHatalar(h);
    if (h.length) return;
    const sonuc = await islem.calistir(() => gonder(govde));
    if (sonuc !== undefined) basladi(sonuc);
  }

  return (
    <Kart
      baslik="Üretimi başlat"
      className="uretim-formu"
    >
      <form className="form" aria-label="Üretim seçenekleri" onSubmit={(e) => void gonderForm(e)} noValidate data-testid="uretim-formu">
        {kip && kipDegistir && <UretimKipiSecici kip={kip} degistir={kipDegistir} />}
        {uyari}
        {y === null && (
          <Uyari ton="bilgi" baslik="Kayıtlı seçenek alınamadı">
            Çekirdek üretim seçeneklerini henüz sunmuyor; form varsayılanlarla açıldı.
          </Uyari>
        )}
        {y?.secenekler && <p className="soluk kucuk">Bu gereksinimin son üretiminde kullanılan seçeneklerle dolduruldu.</p>}

        <fieldset>
          <legend>Platformlar</legend>
          <ul className="satir-ogeler kapsam-cipler" role="list">
            {platformlar.map((p) => (
              <li key={p}>
                <label className="satir-ogeler">
                  <input
                    type="checkbox"
                    name="platform"
                    value={p}
                    checked={s.platformlar.includes(p)}
                    onChange={(e) => setS(platformDegistir(s, p, e.target.checked, platformlar))}
                  />{" "}
                  {p}
                </label>
              </li>
            ))}
          </ul>
          {s.platformlar.length === 0 && <p className="soluk kucuk">Platform seçilmezse üretim platformdan bağımsız yapılır.</p>}
        </fieldset>

        <div className="alan">
          <label htmlFor={`${kimlik}-seviye`}>Test seviyesi</label>
          <select id={`${kimlik}-seviye`} value={s.test_seviyesi} onChange={(e) => guncelle({ test_seviyesi: e.target.value })}>
            {seviyeler.map((v) => (
              <option key={v} value={v}>
                {TEST_SEVIYESI[v] ? `${TEST_SEVIYESI[v]} (${v})` : v}
              </option>
            ))}
          </select>
        </div>

        <div className="alan">
          <label htmlFor={`${kimlik}-standart`}>Benimsenen standartlar</label>
          {s.benimsenen_standartlar.length > 0 && (
            <ul className="satir-ogeler kapsam-cipler" aria-label="Eklenen standartlar" data-testid="standart-etiketleri">
              {s.benimsenen_standartlar.map((k) => (
                <li key={k}>
                  <Cip ton="bilgi">
                    <span className="mono">{k}</span>{" "}
                    <button
                      type="button"
                      className="dugme-metin"
                      aria-label={`${k} standardını kaldır`}
                      onClick={() => guncelle({ benimsenen_standartlar: standartSil(s.benimsenen_standartlar, k) })}
                    >
                      ×
                    </button>
                  </Cip>
                </li>
              ))}
            </ul>
          )}
          <input
            id={`${kimlik}-standart`}
            value={standartGirdi}
            placeholder="ör. WCAG 2.2 AA, OWASP MASVS L1 — Enter ya da virgülle ekleyin"
            maxLength={SECENEK_SINIRI.standartUzunluk * 4}
            aria-describedby={`${kimlik}-standart-aciklama`}
            aria-invalid={standartHata ? true : undefined}
            onChange={(e) => {
              setStandartGirdi(e.target.value);
              setStandartHata(null);
            }}
            onKeyDown={standartTusu}
            onBlur={() => standartGirdi.trim() && standartlariEkle()}
          />
          <p id={`${kimlik}-standart-aciklama`} className="soluk kucuk">
            En fazla {SECENEK_SINIRI.standartSayisi} kod, her biri {SECENEK_SINIRI.standartUzunluk} karaktere kadar. Platform rehberi
            eşikleri yalnız burada benimsenen standartlarda beklenen sonuç olur; diğerleri gözlem olarak yazılır.
          </p>
          {standartHata && (
            <p className="alan-hata" role="alert">
              {standartHata}
            </p>
          )}
        </div>

        <div className="alan">
          <label htmlFor={`${kimlik}-kapsam-disi`}>Kapsam dışı</label>
          <textarea
            id={`${kimlik}-kapsam-disi`}
            rows={2}
            maxLength={SECENEK_SINIRI.kapsamDisi}
            value={s.kapsam_disi}
            onChange={(e) => guncelle({ kapsam_disi: e.target.value })}
          />
        </div>

        <div className="alan">
          <label htmlFor={`${kimlik}-roller`}>Roller</label>
          <input
            id={`${kimlik}-roller`}
            maxLength={SECENEK_SINIRI.roller}
            placeholder="ör. bayi, depo görevlisi, yönetici"
            value={s.roller}
            onChange={(e) => guncelle({ roller: e.target.value })}
          />
        </div>

        {gorunen.length > 0 && (
          <fieldset data-testid="ek-bilgi-alanlari">
            <legend>Ek bilgi (isteğe bağlı)</legend>
            {gorunen.map(([ad, a]) => (
              <EkBilgi key={ad} id={`${kimlik}-ek-${ad}`} ad={ad} alan={a} deger={s.ek_bilgi[ad]} degisti={(v) => ekGuncelle(ad, v)} />
            ))}
          </fieldset>
        )}

        {hatalar.length > 0 && (
          <div role="alert" data-testid="uretim-formu-hatalari">
            <Uyari ton="hata" baslik="Seçenekler gönderilemedi">
              <ul>
                {hatalar.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            </Uyari>
          </div>
        )}
        {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}

        <div className="satir-ogeler">
          <IslemDugmesi izin="case.generate" type="submit" calisiyor={islem.calisiyor}>
            Üretimi başlat
          </IslemDugmesi>
          <button type="button" className="dugme dugme-ikincil" onClick={kapat}>
            Vazgeç
          </button>
        </div>
      </form>
    </Kart>
  );
}

function EkBilgi({
  id,
  ad,
  alan,
  deger,
  degisti,
}: {
  id: string;
  ad: string;
  alan: EkBilgiAlani;
  deger: string | boolean | undefined;
  degisti: (v: string | boolean) => void;
}) {
  const metin = typeof deger === "string" ? deger : "";
  if (alan.tur === "evet_hayir") {
    return (
      <div className="alan">
        <label className="satir-ogeler">
          <input type="checkbox" name={ad} checked={deger === true} onChange={(e) => degisti(e.target.checked)} /> {alan.etiket}
        </label>
      </div>
    );
  }
  return (
    <div className="alan">
      <label htmlFor={id}>{alan.etiket}</label>
      {alan.tur === "secim" ? (
        <select id={id} name={ad} value={metin} onChange={(e) => degisti(e.target.value)}>
          <option value="">Belirtilmedi</option>
          {(alan.secenekler ?? []).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      ) : alan.tur === "uzun_metin" ? (
        <textarea id={id} name={ad} rows={4} maxLength={SECENEK_SINIRI.uzunMetin} value={metin} onChange={(e) => degisti(e.target.value)} />
      ) : (
        <input id={id} name={ad} maxLength={SECENEK_SINIRI.metin} value={metin} onChange={(e) => degisti(e.target.value)} />
      )}
    </div>
  );
}

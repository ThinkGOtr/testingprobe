/**
 * 014 müşteri CI "Kurulum PR'ı aç" eylemi (`POST /code/ci-setup`, `code.ci_setup`). Kurulum gerekli ya da
 * önceki PR kapatılmışken görünür; parametre formu (Android: test paketi; iOS: Xcode projesi, şema, UI test
 * hedefi; isteğe bağlı hazırlık betiği / Node / izlenen kök), önizleme ve açma. Kurulum dalında açık PR varsa
 * core yenisini açmaz, var olanı döner (`mevcut`); bağlantı her iki durumda da gösterilir.
 */
import { useId, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { DilSecenegi, KurulumPr, KurulumPrSonucu } from "../api/types";
import type { Platform } from "../lib/platform";
import { useIslem } from "../hooks";
import {
  eksikZorunlular,
  formParametreleri,
  KURULUM_ALANLARI,
  kurulumDili,
  kurulumMetni,
  sonucIletisi,
  type KurulumFormu,
  type KurulumPlatformu,
} from "../lib/kurulumPr";
import { AlanHatasi, Baglanti, IslemDugmesi, Uyari } from "./ui";

const DIL: Record<KurulumPlatformu, "kotlin" | "swift"> = { android: "kotlin", ios: "swift" };

/** Eylem bu kurulum durumunda gösterilir mi (açık / birleşmiş PR'da gösterilmez). */
export function kurulumEylemiGerekli(k: KurulumPr | null | undefined): boolean {
  return !!k && (k.durum === "gerekli" || k.durum === "kapali");
}

export function KurulumPrEylemi({
  platform,
  kurulum,
  degisti,
}: {
  platform: KurulumPlatformu;
  kurulum: KurulumPr | null | undefined;
  /** PR açıldı / mevcut döndü: üst bileşen kurulum özetini yeniler. */
  degisti?: (s: KurulumPrSonucu) => void;
}) {
  const dil = kurulumDili();
  const m = (a: Parameters<typeof kurulumMetni>[0]) => kurulumMetni(a, dil);
  const kimlik = useId();
  const islem = useIslem();
  const [acik, setAcik] = useState(false);
  const [form, setForm] = useState<KurulumFormu>({});
  const [sonuc, setSonuc] = useState<KurulumPrSonucu | null>(null);
  const [yerelHata, setYerelHata] = useState<string | null>(null);

  if (!kurulumEylemiGerekli(kurulum) && !(sonuc && sonuc.durum !== "onizleme")) return null;

  const alanlar = KURULUM_ALANLARI[platform];
  const sunucuHatalari = islem.hataNesnesi instanceof ApiError && islem.hataNesnesi.kod === "kurulum_parametre" ? (islem.hataNesnesi.hatalar ?? []) : [];

  const gonder = async (onizle: boolean) => {
    const eksik = eksikZorunlular(platform, form, dil);
    if (eksik.length) {
      setYerelHata(`${m("zorunluEksik")}: ${eksik.join(", ")}`);
      return;
    }
    setYerelHata(null);
    const s = await islem.calistir(() => api.kurulumPrAc(platform, DIL[platform], formParametreleri(platform, form), onizle));
    if (!s) return;
    setSonuc(s);
    if (s.durum !== "onizleme") {
      setAcik(false);
      degisti?.(s);
    }
  };

  // Sonuç (açıldı / mevcut / gereksiz / sürüyor): bağlantı ve elle adımlar.
  if (sonuc && sonuc.durum !== "onizleme") {
    const ton = sonuc.durum === "acildi" ? "basari" : "bilgi";
    return (
      <div className="kurulum-pr-sonuc" data-testid="kurulum-pr-sonuc" data-durum={sonuc.durum}>
        <Uyari ton={ton} baslik={sonucIletisi(sonuc, dil)}>
          {sonuc.pr_no !== null && (
            <p className="kucuk">
              <Baglanti href={sonuc.url}>{`#${sonuc.pr_no}${sonuc.kurulum?.baslik ? ` ${sonuc.kurulum.baslik}` : ""}`}</Baglanti>
              {sonuc.taban && (
                <>
                  {" "}
                  · {m("taban")}: <span className="mono">{sonuc.taban}</span>
                </>
              )}
            </p>
          )}
          {sonuc.elle_adimlar.length > 0 && (
            <>
              <p className="kucuk">
                <strong>{m("elle")}:</strong>
              </p>
              <ul className="kucuk" aria-label={m("elle")}>
                {sonuc.elle_adimlar.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          )}
        </Uyari>
      </div>
    );
  }

  if (!acik) {
    return (
      <div className="eylemler kurulum-pr-eylem">
        <IslemDugmesi izin="code.ci_setup" tur="ikincil" kucuk onClick={() => setAcik(true)} data-testid="kurulum-pr-ac">
          {kurulum?.durum === "kapali" ? m("yeniden") : m("ac")}
        </IslemDugmesi>
      </div>
    );
  }

  const zorunlular = alanlar.filter((a) => !a.hazirlik);
  const hazirlik = alanlar.filter((a) => a.hazirlik);
  const alan = (a: (typeof alanlar)[number]) => {
    const id = `${kimlik}-${a.ad}`;
    return (
      <div className="alan" key={a.ad}>
        <label htmlFor={id}>
          {a.etiket[dil]}
          {a.zorunlu && <span className="soluk"> ({m("zorunlu")})</span>}
        </label>
        <input
          id={id}
          name={a.ad}
          value={form[a.ad] ?? ""}
          placeholder={a.ornek}
          inputMode={a.sayi ? "numeric" : undefined}
          maxLength={200}
          aria-required={a.zorunlu || undefined}
          disabled={islem.calisiyor}
          onChange={(e) => setForm((f) => ({ ...f, [a.ad]: e.target.value }))}
        />
      </div>
    );
  };

  return (
    <form
      className="kurulum-pr-form"
      data-testid="kurulum-pr-form"
      aria-labelledby={`${kimlik}-baslik`}
      onSubmit={(e) => {
        e.preventDefault();
        void gonder(false);
      }}
    >
      <p id={`${kimlik}-baslik`}>
        <strong>{m("formBaslik")}</strong>
      </p>
      <p className="kucuk soluk">{m("formAciklama")}</p>
      {zorunlular.map(alan)}
      <fieldset>
        <legend className="kucuk">{m("istegeBagli")}</legend>
        {hazirlik.map(alan)}
      </fieldset>
      {yerelHata && <p className="alan-hata" role="alert">{yerelHata}</p>}
      {islem.hata && (
        <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>
          {sunucuHatalari.length > 0 ? (
            <>
              {m("parametreHatasi")}:
              <ul className="kucuk">
                {sunucuHatalari.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            </>
          ) : (
            `${m("acilamadi")}: ${islem.hata}`
          )}
        </AlanHatasi>
      )}
      {sonuc?.durum === "onizleme" && (
        <div className="kurulum-pr-onizleme" data-testid="kurulum-pr-onizleme">
          <Uyari ton={sonuc.hazir ? "bilgi" : "uyari"} baslik={sonuc.hazir ? m("onizlemeBaslik") : m("hazirDegil")}>
            {sonuc.dosyalar.length > 0 ? (
              <ul className="kucuk mono" aria-label={m("onizlemeBaslik")}>
                {sonuc.dosyalar.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            ) : (
              <p className="kucuk">{m("dosyaYok")}</p>
            )}
            {sonuc.elle_adimlar.length > 0 && (
              <>
                <p className="kucuk">
                  <strong>{m("elle")}:</strong>
                </p>
                <ul className="kucuk" aria-label={m("elle")}>
                  {sonuc.elle_adimlar.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </>
            )}
            {sonuc.pr_no !== null && (
              <p className="kucuk">
                {m("mevcut")}: <Baglanti href={sonuc.url}>{`#${sonuc.pr_no}`}</Baglanti>
              </p>
            )}
          </Uyari>
        </div>
      )}
      <div className="eylemler">
        <IslemDugmesi izin="code.ci_setup" tur="ikincil" kucuk calisiyor={islem.calisiyor} onClick={() => void gonder(true)} data-testid="kurulum-pr-onizle">
          {m("onizle")}
        </IslemDugmesi>
        <IslemDugmesi izin="code.ci_setup" kucuk calisiyor={islem.calisiyor} type="submit" data-testid="kurulum-pr-gonder">
          {m("gonder")}
        </IslemDugmesi>
        <button
          type="button"
          className="dugme dugme-metin dugme-kucuk"
          disabled={islem.calisiyor}
          onClick={() => {
            setAcik(false);
            setYerelHata(null);
            islem.temizle();
          }}
        >
          {m("vazgec")}
        </button>
      </div>
    </form>
  );
}

/**
 * Ekran testi 2 TP-1: müşteri CI dili (Android Kotlin, iOS Swift) projenin test dillerinde seçili değilken ya da
 * depoda test projesi yokken de kurulum yolu görünür (kapı açıksa). Sıra: önce kurulum PR'ı (iş akışı + iskelet),
 * birleşince dil Platform ayarları'nda seçilir. Dil seçiliyken iş akışı PR'larda zorunlu check olarak beklendiği
 * için kurulum dil seçiminden önce yapılabilir ve yapılmalıdır.
 */
export function musteriCiKurulumAdimi(
  s: Pick<DilSecenegi, "etiket" | "engel" | "acma_yolu" | "kurulum" | "neden">,
  platform: KurulumPlatformu,
): string {
  const yol = s.acma_yolu ?? `AI Probe › Proje › Platform ayarları › ${platform === "ios" ? "iOS" : "Android"} › Test dilleri`;
  const birlesti = s.kurulum?.durum === "birlesti";
  const liste = s.engel === "liste" || /seçili değil|hattı etkin değil/i.test(s.neden ?? "");
  if (liste && birlesti) return `Kurulum tamam. ${s.etiket} ile üretmek için ${yol} bölümünde ${s.etiket} seçeneğini işaretleyin.`;
  if (liste)
    return `${s.etiket} bu projede henüz seçili değil; kurulum dil seçilmeden önce yapılabilir. 1) Kurulum PR'ını açın ve GitHub'da birleştirin (CI iş akışı ve test iskeleti eklenir). 2) Sonra ${yol} bölümünde ${s.etiket} seçeneğini işaretleyin. Sıra önemlidir: dil seçilince bu dilin CI kontrolü PR'larda beklenir.`;
  return `${s.etiket} depoda henüz kurulu değil. Kurulum PR'ı birleşince ${s.etiket} bu ekranda seçilebilir olur.`;
}

export function MusteriCiKurulumYolu({
  platform,
  secenekler,
  seciliDil,
  degisti,
}: {
  platform: Platform;
  secenekler: readonly DilSecenegi[];
  /** Seçili ve kullanılabilir dil kendi akışıyla (seçicinin altında) çizilir; burada tekrarlanmaz. */
  seciliDil: string | null;
  degisti?: () => void;
}) {
  if (platform !== "android" && platform !== "ios") return null;
  const adaylar = secenekler.filter((s) => s.hat === "musteri_ci" && s.durum !== "yakinda" && !s.kullanilabilir && s.dil !== seciliDil && s.engel !== "yapilandirma");
  if (adaylar.length === 0) return null;
  return (
    <>
      {adaylar.map((s) => (
        <div className="kurulum-pr-yolu" data-testid="kurulum-pr-yolu" data-dil={s.dil} key={s.dil}>
          <Uyari ton="bilgi" baslik={`Müşteri CI kurulumu: ${s.etiket}`}>
            <p className="kucuk">{musteriCiKurulumAdimi(s, platform)}</p>
            <KurulumPrEylemi key={`${platform}/${s.dil}`} platform={platform} kurulum={s.kurulum} degisti={degisti ? () => degisti() : undefined} />
          </Uyari>
        </div>
      ))}
    </>
  );
}

// Otomasyon ayarları (specs/013-sprint-otomasyonu §3.1, §3.4, §3.5; K4, K5, Y3): onay sonrası otomatik
// kod üretimi ve Jira durum tetiği. Herkes görür; Analist ve Mühendis değiştirir. Her kaydetme yalnız
// değişen ayar anahtarını kısmi nesneyle yazar (`PUT /automation-settings/{anahtar}`); sunucu denetler.
import { useEffect, useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { JiraTetikDurumu, OtomasyonAyarlari } from "../api/types";
import { useKisiAdi, useOturum } from "../auth";
import { useBildirim } from "../components/Bildirim";
import { AlanHatasi, BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useIslem, useVeri } from "../hooks";
import { tarih } from "../lib/format";
import { TESTVERI_ROLLERI } from "./TestVerisi";

/** Ayarları değiştirebilen roller (Y3: katalogla aynı). */
export const OTOMASYON_ROLLERI = TESTVERI_ROLLERI;
export const ARALIK_EN_AZ = 30;
export const ARALIK_EN_COK = 3600;

function SonGuncelleme({ kim, ne }: { kim: string | null; ne: string | null }) {
  const kisiAdi = useKisiAdi();
  if (!kim && !ne) return <p className="soluk kucuk">Varsayılan değer (henüz değiştirilmedi).</p>;
  return (
    <p className="soluk kucuk">
      Son değişiklik: {kim ? kisiAdi(kim) : "—"}
      {ne && `, ${tarih(ne)}`}
    </p>
  );
}

function OtomatikKodKarti({ ayar, yetkili, guncellendi }: { ayar: OtomasyonAyarlari["otomatik_kod_uretimi"]; yetkili: boolean; guncellendi: (a: OtomasyonAyarlari) => void }) {
  const id = useId();
  const islem = useIslem();
  const bildir = useBildirim();
  const [acik, setAcik] = useState(ayar.acik);
  useEffect(() => setAcik(ayar.acik), [ayar.acik]);
  const degisti = acik !== ayar.acik;

  async function kaydet(e: FormEvent) {
    e.preventDefault();
    const y = await islem.calistir(() => api.otomasyonAyariKaydet("otomatik_kod_uretimi", { acik }));
    if (y) {
      guncellendi(y);
      bildir(y.otomatik_kod_uretimi.acik ? "Otomatik kod üretimi açıldı." : "Otomatik kod üretimi kapatıldı.");
    }
  }

  return (
    <Kart
      baslik="Onay sonrası otomatik kod üretimi"
      eylemler={<Cip ton={ayar.acik ? "basari" : "notr"}>{ayar.acik ? "açık" : "kapalı"}</Cip>}
    >
      <p className="soluk kucuk">
        Case onaylanınca (tek tek ya da toplu) Web testi için kod üretimi hemen kuyruğa alınır; başlatan "otomasyon", tetikleyen onaylayan
        analisttir. Android, iOS ve Windows cihaz gerektirdiği için kendiliğinden başlamaz. <Link to="/kod">Kod üretimi</Link> ekranındaki
        düğme her durumda kalır.
      </p>
      <form onSubmit={(e) => void kaydet(e)} noValidate>
        <fieldset disabled={!yetkili} className="otomasyon-alanlar">
          <legend className="gorunmez">Otomatik kod üretimi ayarı</legend>
          <div className="alan alan-satir">
            <input id={`${id}-acik`} type="checkbox" role="switch" checked={acik} onChange={(e) => setAcik(e.target.checked)} />
            <label htmlFor={`${id}-acik`}>Onaylanan case için kodu otomatik üret</label>
          </div>
        </fieldset>
        {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
        <div className="eylemler">
          <IslemDugmesi roller={OTOMASYON_ROLLERI} type="submit" kucuk calisiyor={islem.calisiyor} disabled={!degisti} title={!degisti ? "Değişiklik yok." : undefined}>
            Kaydet
          </IslemDugmesi>
        </div>
      </form>
      <SonGuncelleme kim={ayar.guncelleyen} ne={ayar.guncelleme} />
    </Kart>
  );
}

type JiraForm = { acik: boolean; durum: string; aralik: string; otomatik_case: boolean };

/** Jira tetiği formundaki değişen alanlar (kısmi gövde); doğrulama hatası varsa metni. */
export function jiraTetikDegisiklikleri(
  ayar: OtomasyonAyarlari["jira_tetik"],
  f: JiraForm,
): { govde: Partial<Omit<OtomasyonAyarlari["jira_tetik"], "guncelleyen" | "guncelleme">>; hata: string | null } {
  const durum = f.durum.trim();
  if (!durum) return { govde: {}, hata: "Durum adı boş olamaz." };
  if (durum.length > 100) return { govde: {}, hata: "Durum adı en çok 100 karakter." };
  const aralik = Number(f.aralik);
  if (!/^\d+$/.test(f.aralik.trim()) || aralik < ARALIK_EN_AZ || aralik > ARALIK_EN_COK) {
    return { govde: {}, hata: `Sorgu aralığı ${ARALIK_EN_AZ}–${ARALIK_EN_COK} saniye arasında tam sayı olmalı.` };
  }
  const govde: ReturnType<typeof jiraTetikDegisiklikleri>["govde"] = {};
  if (f.acik !== ayar.acik) govde.acik = f.acik;
  if (durum !== ayar.durum) govde.durum = durum;
  if (aralik !== ayar.aralik_s) govde.aralik_s = aralik;
  if (f.otomatik_case !== ayar.otomatik_case) govde.otomatik_case = f.otomatik_case;
  return { govde, hata: null };
}

function JiraTetikKarti({ ayar, yetkili, guncellendi }: { ayar: OtomasyonAyarlari["jira_tetik"]; yetkili: boolean; guncellendi: (a: OtomasyonAyarlari) => void }) {
  const id = useId();
  const islem = useIslem();
  const bildir = useBildirim();
  const ilk = (): JiraForm => ({ acik: ayar.acik, durum: ayar.durum, aralik: String(ayar.aralik_s), otomatik_case: ayar.otomatik_case });
  const [f, setF] = useState<JiraForm>(ilk);
  const [uyari, setUyari] = useState<string | null>(null);
  useEffect(() => setF(ilk()), [ayar.acik, ayar.durum, ayar.aralik_s, ayar.otomatik_case]);
  const { govde } = jiraTetikDegisiklikleri(ayar, f);
  const degisti = Object.keys(govde).length > 0 || f.durum.trim() !== ayar.durum || f.aralik.trim() !== String(ayar.aralik_s);

  async function kaydet(e: FormEvent) {
    e.preventDefault();
    const d = jiraTetikDegisiklikleri(ayar, f);
    if (d.hata) return setUyari(d.hata);
    setUyari(null);
    if (Object.keys(d.govde).length === 0) return;
    const y = await islem.calistir(() => api.otomasyonAyariKaydet("jira_tetik", d.govde));
    if (y) {
      guncellendi(y);
      bildir("Jira tetiği ayarı kaydedildi.");
    }
  }

  return (
    <Kart baslik="Jira durum tetiği" eylemler={<Cip ton={ayar.acik ? "basari" : "notr"}>{ayar.acik ? "açık" : "kapalı"}</Cip>}>
      <p className="soluk kucuk">
        Worker Jira'yı aralıklarla sorgular; bu duruma gelen yeni story çekilir ve ön incelemeye girer. PO kapısı korunur: PO onayı gelince
        (otomatik case açıksa) case üretimi kendiliğinden başlar. Jira'ya yazmaz, yalnız okur.
      </p>
      <form onSubmit={(e) => void kaydet(e)} noValidate>
        <fieldset disabled={!yetkili} className="otomasyon-alanlar">
          <legend className="gorunmez">Jira durum tetiği ayarı</legend>
          <div className="alan alan-satir">
            <input id={`${id}-acik`} type="checkbox" role="switch" checked={f.acik} onChange={(e) => setF({ ...f, acik: e.target.checked })} />
            <label htmlFor={`${id}-acik`}>Tetik açık</label>
          </div>
          <div className="otomasyon-izgara">
            <div className="alan">
              <label htmlFor={`${id}-durum`}>Tetikleyen Jira durumu</label>
              <input id={`${id}-durum`} value={f.durum} maxLength={100} aria-required="true" onChange={(e) => setF({ ...f, durum: e.target.value })} />
            </div>
            <div className="alan">
              <label htmlFor={`${id}-aralik`}>Sorgu aralığı (saniye)</label>
              <input
                id={`${id}-aralik`}
                type="number"
                inputMode="numeric"
                min={ARALIK_EN_AZ}
                max={ARALIK_EN_COK}
                step={1}
                value={f.aralik}
                aria-describedby={`${id}-aralik-ipucu`}
                onChange={(e) => setF({ ...f, aralik: e.target.value })}
              />
              <span id={`${id}-aralik-ipucu`} className="soluk kucuk">
                {ARALIK_EN_AZ}–{ARALIK_EN_COK} sn
              </span>
            </div>
          </div>
          <div className="alan alan-satir">
            <input
              id={`${id}-case`}
              type="checkbox"
              role="switch"
              checked={f.otomatik_case}
              aria-describedby={`${id}-case-ipucu`}
              onChange={(e) => setF({ ...f, otomatik_case: e.target.checked })}
            />
            <label htmlFor={`${id}-case`}>PO onayından sonra case'leri otomatik üret</label>
          </div>
          <p id={`${id}-case-ipucu`} className="soluk kucuk">
            Yalnız bu tetikle akışa alınmış story'lerde çalışır; elle çekilen gereksinimin akışı değişmez.
          </p>
        </fieldset>
        {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
        {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
        <div className="eylemler">
          <IslemDugmesi roller={OTOMASYON_ROLLERI} type="submit" kucuk calisiyor={islem.calisiyor} disabled={!degisti} title={!degisti ? "Değişiklik yok." : undefined}>
            Kaydet
          </IslemDugmesi>
        </div>
      </form>
      <SonGuncelleme kim={ayar.guncelleyen} ne={ayar.guncelleme} />
    </Kart>
  );
}

function JiraTetikDurumKarti({ d, yenile, yukleniyor }: { d: JiraTetikDurumu | undefined; yenile: () => void; yukleniyor: boolean }) {
  return (
    <Kart
      baslik="Jira tetiği: son tur"
      eylemler={
        <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={yenile} disabled={yukleniyor} aria-busy={yukleniyor || undefined}>
          Yenile
        </button>
      }
    >
      {!d ? (
        <Yukleniyor />
      ) : (
        <>
          <dl className="tanim-izgara" data-testid="jira-tetik-son-tur">
            <dt>Durum</dt>
            <dd>
              <Cip ton={d.acik ? "basari" : "notr"}>{d.acik ? "açık" : "kapalı"}</Cip> <span className="mono">"{d.durum}"</span> · her {d.aralik_s} sn
            </dd>
            <dt>Son tur</dt>
            <dd>{d.son_tur ? tarih(d.son_tur.zaman) : "Henüz tur yok."}</dd>
            {d.son_tur && (
              <>
                <dt>Bulunan / tetiklenen</dt>
                <dd>
                  {d.son_tur.bulunan} / {d.son_tur.tetiklenen}
                </dd>
              </>
            )}
          </dl>
          {d.son_tur?.hata && (
            <Uyari ton="hata" baslik="Son turda hata">
              {d.son_tur.hata}
            </Uyari>
          )}
          <h3 className="kucuk">Son tetiklenen story'ler</h3>
          {d.son_tetiklenenler.length === 0 ? (
            <BosDurum baslik="Henüz tetiklenen story yok." />
          ) : (
            <ul className="duz-liste" aria-label="Son tetiklenen story'ler">
              {d.son_tetiklenenler.map((s, i) => (
                <li key={`${s.jira_key}-${i}`} className="satir-ogeler">
                  <span className="mono">{s.jira_key}</span>
                  <span className="soluk kucuk">{tarih(s.zaman)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Kart>
  );
}

export function Otomasyon() {
  const ayarlar = useVeri(() => api.otomasyonAyarlari(), []);
  const tetik = useVeri(() => api.jiraTetikDurumu(), []);
  const { kullanici } = useOturum();
  const yetkili = !!kullanici && OTOMASYON_ROLLERI.includes(kullanici.rol);
  const guncellendi = (a: OtomasyonAyarlari) => {
    ayarlar.setVeri(a);
    void tetik.yenile(true);
  };
  return (
    <>
      <SayfaBasligi
        baslik="Otomasyon"
        aciklama="Sprint içi akış: Jira'da QA durumuna gelen story ön incelemeye girer, PO onayından sonra case'ler üretilir, onaylanan case'in kodu kendiliğinden üretilir. İnsan kapıları (PO onayı, case onayı, merge) atlanmaz."
      />
      {!yetkili && <Uyari ton="bilgi">Bu ayarları Analist ve Mühendis değiştirir; siz görüntüleyebilirsiniz.</Uyari>}
      {ayarlar.yukleniyor && !ayarlar.veri ? (
        <Yukleniyor />
      ) : ayarlar.hata && !ayarlar.veri ? (
        <HataKutusu hata={ayarlar.hata} kaynak={ayarlar.hataNesnesi} yenile={() => void ayarlar.yenile()} />
      ) : (
        ayarlar.veri && (
          <div className="iki-sutun">
            <OtomatikKodKarti ayar={ayarlar.veri.otomatik_kod_uretimi} yetkili={yetkili} guncellendi={guncellendi} />
            <JiraTetikKarti ayar={ayarlar.veri.jira_tetik} yetkili={yetkili} guncellendi={guncellendi} />
          </div>
        )
      )}
      {tetik.hata && !tetik.veri ? (
        <Kart baslik="Jira tetiği: son tur">
          <HataKutusu hata={tetik.hata} kaynak={tetik.hataNesnesi} yenile={() => void tetik.yenile()} />
        </Kart>
      ) : (
        <JiraTetikDurumKarti d={tetik.veri} yenile={() => void tetik.yenile(true)} yukleniyor={tetik.yukleniyor} />
      )}
    </>
  );
}

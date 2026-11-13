// Otomasyon ayarları (specs/013-sprint-otomasyonu §3.1, §3.4, §3.5; K4, K5, Y3): onay sonrası otomatik
// kod üretimi ve Jira durum tetiği. Herkes görür; Analist ve Mühendis değiştirir (`automation.manage`;
// tetikleyen Jira durumu yalnız Mühendis, `automation.jira_status`). Her kaydetme yalnız
// değişen ayar anahtarını kısmi nesneyle yazar (`PUT /automation-settings/{anahtar}`); sunucu denetler.
import { useEffect, useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Gereksinim, JiraTetikDurumu, JiraTetikTurSonucu, OtomasyonAyarlari } from "../api/types";
import type { Ton } from "../lib/etiketler";
import { useIzin, useKisiAdi } from "../auth";
import { izinRolleriMetni, type Izin } from "../lib/yetki";
import { useBildirim } from "../components/Bildirim";
import { AlanHatasi, BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useIslem, useVeri } from "../hooks";
import { tarih } from "../lib/format";

/** Ayarları değiştirme izni (Y3; 012 kataloğu). */
export const OTOMASYON_IZNI = "automation.manage" satisfies Izin;
/** Jira tetiğinin durum adını değiştirme izni (K14). */
export const JIRA_DURUM_IZNI = "automation.jira_status" satisfies Izin;
export const ARALIK_EN_AZ = 30;
export const ARALIK_EN_COK = 3600;
/** K14: tur başına en çok tetiklenen story. */
export const TUR_BASINA_EN_COK = 10;
export const DURUM_YALNIZ_MUHENDIS = `Tetikleyen Jira durumunu yalnız ${izinRolleriMetni("automation.jira_status")} değiştirir.`;
/** K21: elle çekilmiş gereksinim de akışa alınır (otomatik case ayarına göre iki metin). */
export const AKIS_METNI_OTOMATIK =
  "Story bu duruma girerse elle çekilmiş gereksinim de akışa alınır; PO onayından sonra case'ler otomatik üretilir.";
export const AKIS_METNI_ELLE =
  "Story bu duruma girerse elle çekilmiş gereksinim de akışa alınır; otomatik case kapalıyken PO onayından sonra case üretimini elle başlatın.";
/** K23: REPLAY kipinde otomatik kod kartındaki uyarı. */
export const REPLAY_OTOKOD_UYARISI = "Demo kayıtları bu ayara göre değil; açarsanız kod üretimi kayıt bulamaz.";
export const JIRA_YAZIM_METNI =
  "Tetik Jira'yı okur; başlattığı ön inceleme bulgusuz biterse PO'ya Jira yorumu ve etiketi yazılır.";

/** Tetik turu story sonucunun Türkçe etiketi (`dokunulmadi:<ayrıntı>` gibi ekli değerler önekten okunur). */
const TUR_SONUCU: Record<string, { etiket: string; ton: Ton }> = {
  tetiklendi: { etiket: "Tetiklendi (ön incelemeye girdi)", ton: "basari" },
  yeniden_tetiklendi: { etiket: "Yeniden tetiklendi (içerik değişti)", ton: "basari" },
  case_uretimi: { etiket: "Case üretimi başladı", ton: "basari" },
  // Ayrıntı (aşama, otomatik case ayarı) neden sütununda.
  akisa_alindi: { etiket: "Akışa alındı", ton: "bilgi" },
  isaretlendi: { etiket: "İşaretlendi (zaten durumdaydı, tetiklenmedi)", ton: "notr" },
  ertelendi: { etiket: `Sonraki tura kaldı (tur sınırı ${TUR_BASINA_EN_COK})`, ton: "uyari" },
  dokunulmadi: { etiket: "Dokunulmadı", ton: "notr" },
  durumda: { etiket: "Durumda (değişiklik yok)", ton: "notr" },
  guncellendi: { etiket: "Jira içeriği çekildi", ton: "bilgi" },
  hata: { etiket: "Hata", ton: "hata" },
};
/** Eylemsiz, kalabalık sonuç: tabloda varsayılan olarak gizlenir. */
export const SESSIZ_SONUC = "durumda";
export function turSonucuEtiketi(sonuc: string): { etiket: string; ton: Ton } {
  const onek = sonuc.split(":")[0];
  return TUR_SONUCU[onek] ?? { etiket: sonuc.replace(/_/g, " "), ton: "notr" };
}

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

/**
 * K23: model geçidi REPLAY kipinde mi. Ayar ucu bildirirse o (`replay`/`model_kipi`); yoksa
 * `/demo/status` → `model.mod`. Bilinmiyorsa null (uyarı gösterilmez).
 */
function useReplayKipi(ayarlar: OtomasyonAyarlari | undefined): boolean | null {
  const ayardan = ayarlar?.replay;
  const [demodan, setDemodan] = useState<boolean | null>(null);
  const bekle = !ayarlar || ayardan !== undefined;
  useEffect(() => {
    if (bekle) return;
    let iptal = false;
    api
      .demoDurumu()
      .then((d) => !iptal && setDemodan(d.model?.mod ? d.model.mod.toLowerCase() === "replay" : null))
      .catch(() => undefined);
    return () => {
      iptal = true;
    };
  }, [bekle]);
  return ayardan !== undefined ? ayardan : demodan;
}

function OtomatikKodKarti({
  ayar,
  yetkili,
  guncellendi,
  replay,
}: {
  ayar: OtomasyonAyarlari["otomatik_kod_uretimi"];
  yetkili: boolean;
  guncellendi: (a: OtomasyonAyarlari) => void;
  /** K23: REPLAY kipi (bilinmiyorsa null). */
  replay: boolean | null;
}) {
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
      {replay && (
        <Uyari ton="uyari" baslik="REPLAY kipi">
          <span data-testid="replay-otokod-uyarisi">{REPLAY_OTOKOD_UYARISI}</span>
        </Uyari>
      )}
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
          <IslemDugmesi izin={OTOMASYON_IZNI} type="submit" kucuk calisiyor={islem.calisiyor} disabled={!degisti} title={!degisti ? "Değişiklik yok." : undefined}>
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

function JiraTetikKarti({
  ayar,
  yetkili,
  durumYetkili,
  guncellendi,
}: {
  ayar: OtomasyonAyarlari["jira_tetik"];
  yetkili: boolean;
  /** K14: `durum` alanını yalnız engineer değiştirir (sunucu da 403 döner). */
  durumYetkili: boolean;
  guncellendi: (a: OtomasyonAyarlari) => void;
}) {
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
        Worker Jira'yı aralıklarla sorgular; bu duruma giren story çekilir ve ön incelemeye girer. PO kapısı korunur: PO onayı gelince
        (otomatik case açıksa) case üretimi kendiliğinden başlar.
      </p>
      <p className="kucuk" data-testid="jira-yazim-notu">
        <strong>Jira'ya yazım:</strong> {JIRA_YAZIM_METNI}
      </p>
      <p className="soluk kucuk" data-testid="tetik-kapsam-notu">
        Tetik açılınca (ve ilk turda) o anda bu durumda bekleyen story'ler yalnız işaretlenir, tetiklenmez; yalnız sonradan bu duruma giren
        story'ler tetiklenir. Tur başına en çok {TUR_BASINA_EN_COK} story tetiklenir, kalanlar sonraki tura kalır.
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
              <input
                id={`${id}-durum`}
                value={f.durum}
                maxLength={100}
                aria-required="true"
                disabled={!durumYetkili}
                aria-describedby={!durumYetkili ? `${id}-durum-neden` : undefined}
                onChange={(e) => setF({ ...f, durum: e.target.value })}
              />
              {yetkili && !durumYetkili && (
                <span id={`${id}-durum-neden`} className="soluk kucuk">
                  {DURUM_YALNIZ_MUHENDIS}
                </span>
              )}
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
          <p id={`${id}-case-ipucu`} className="soluk kucuk" data-testid="akis-notu">
            {f.otomatik_case ? AKIS_METNI_OTOMATIK : AKIS_METNI_ELLE}
          </p>
        </fieldset>
        {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
        {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
        <div className="eylemler">
          <IslemDugmesi izin={OTOMASYON_IZNI} type="submit" kucuk calisiyor={islem.calisiyor} disabled={!degisti} title={!degisti ? "Değişiklik yok." : undefined}>
            Kaydet
          </IslemDugmesi>
        </div>
      </form>
      <SonGuncelleme kim={ayar.guncelleyen} ne={ayar.guncelleme} />
    </Kart>
  );
}

function StoryBaglantisi({ jiraKey, gereksinimler }: { jiraKey: string; gereksinimler: Map<string, string> }) {
  const rid = gereksinimler.get(jiraKey);
  return rid ? (
    <Link className="mono" to={`/gereksinimler/${encodeURIComponent(rid)}`}>
      {jiraKey}
    </Link>
  ) : (
    <span className="mono">{jiraKey}</span>
  );
}

/** Son tur story sonuçları; eylemsiz `durumda` satırları varsayılan gizli (kalabalık). */
function TurSonuclari({ sonuclar, gereksinimler }: { sonuclar: JiraTetikTurSonucu[]; gereksinimler: Map<string, string> }) {
  const [hepsi, setHepsi] = useState(false);
  const sessiz = sonuclar.filter((r) => r.sonuc.split(":")[0] === SESSIZ_SONUC).length;
  const gorunen = hepsi ? sonuclar : sonuclar.filter((r) => r.sonuc.split(":")[0] !== SESSIZ_SONUC);
  return (
    <>
      {sessiz > 0 && (
        <div className="satir-ogeler kucuk">
          <span className="soluk">
            {hepsi ? `${sessiz} değişmeyen story dahil.` : `${sessiz} story durumda (değişiklik yok); gizli.`}
          </span>
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-pressed={hepsi} onClick={() => setHepsi((x) => !x)}>
            {hepsi ? "Yalnız eylemli olanlar" : "Tümünü göster"}
          </button>
        </div>
      )}
      {gorunen.length > 0 && (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Son tur story sonuçları">
          <table className="tablo tablo-sik" data-testid="jira-tetik-sonuclar">
            <caption className="gorunmez">Son tur story sonuçları</caption>
            <thead>
              <tr>
                <th scope="col">Story</th>
                <th scope="col">Sonuç</th>
                <th scope="col">Neden</th>
              </tr>
            </thead>
            <tbody>
              {gorunen.map((r, i) => {
                const e = turSonucuEtiketi(r.sonuc);
                return (
                  <tr key={`${r.jira_key}-${i}`}>
                    <td>
                      <StoryBaglantisi jiraKey={r.jira_key} gereksinimler={gereksinimler} />
                    </td>
                    <td>
                      <Cip ton={e.ton}>{e.etiket}</Cip>
                    </td>
                    <td className="kucuk">{r.neden ?? <span className="soluk">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function JiraTetikDurumKarti({
  d,
  yenile,
  yukleniyor,
  gereksinimler,
}: {
  d: JiraTetikDurumu | undefined;
  yenile: () => void;
  yukleniyor: boolean;
  /** jira_key → gereksinim kimliği (bağlantı; TP'ye henüz çekilmemişse yok). */
  gereksinimler: Map<string, string>;
}) {
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
          {d.son_tur?.taban && (
            <Uyari ton="bilgi" baslik="İlk tur">
              İlk tur: mevcut story'ler işaretlendi, tetiklenmedi. Yalnız bundan sonra duruma giren story'ler tetiklenir.
            </Uyari>
          )}
          {d.son_tur && d.son_tur.ertelenen > 0 && (
            <p className="kucuk" data-testid="jira-tetik-ertelenen">
              {d.son_tur.ertelenen} story tur sınırı ({TUR_BASINA_EN_COK}) nedeniyle sonraki tura kaldı.
            </p>
          )}
          {d.son_tur && d.son_tur.sonuclar.length > 0 && (
            <TurSonuclari sonuclar={d.son_tur.sonuclar} gereksinimler={gereksinimler} />
          )}
          <h3 className="kucuk">Story başına son tetik sonucu</h3>
          {d.son_tetiklenenler.length === 0 ? (
            <BosDurum baslik="Henüz tetik sonucu yok." />
          ) : (
            <ul className="duz-liste" aria-label="Story başına son tetik sonucu" data-testid="son-tetik-sonuclari">
              {d.son_tetiklenenler.map((s, i) => (
                <li key={`${s.jira_key}-${i}`} className="satir-ogeler">
                  <StoryBaglantisi jiraKey={s.jira_key} gereksinimler={gereksinimler} />
                  {s.sonuc && <Cip ton={turSonucuEtiketi(s.sonuc).ton}>{turSonucuEtiketi(s.sonuc).etiket}</Cip>}
                  {s.neden && <span className="kucuk">{s.neden}</span>}
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
  const gereksinimler = useVeri(() => api.gereksinimler().catch(() => [] as Gereksinim[]), []);
  const anahtarlar = new Map((gereksinimler.veri ?? []).filter((g) => g.jira_key).map((g) => [g.jira_key!, g.id] as const));
  const yetkili = useIzin(OTOMASYON_IZNI);
  const durumYetkili = useIzin(JIRA_DURUM_IZNI);
  const replay = useReplayKipi(ayarlar.veri);
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
      {!yetkili && <Uyari ton="bilgi">Bu ayarları {izinRolleriMetni("automation.manage")} değiştirir; siz görüntüleyebilirsiniz.</Uyari>}
      {ayarlar.yukleniyor && !ayarlar.veri ? (
        <Yukleniyor />
      ) : ayarlar.hata && !ayarlar.veri ? (
        <HataKutusu hata={ayarlar.hata} kaynak={ayarlar.hataNesnesi} yenile={() => void ayarlar.yenile()} />
      ) : (
        ayarlar.veri && (
          <div className="iki-sutun">
            <OtomatikKodKarti ayar={ayarlar.veri.otomatik_kod_uretimi} yetkili={yetkili} guncellendi={guncellendi} replay={replay} />
            <JiraTetikKarti ayar={ayarlar.veri.jira_tetik} yetkili={yetkili} durumYetkili={durumYetkili} guncellendi={guncellendi} />
          </div>
        )
      )}
      {tetik.hata && !tetik.veri ? (
        <Kart baslik="Jira tetiği: son tur">
          <HataKutusu hata={tetik.hata} kaynak={tetik.hataNesnesi} yenile={() => void tetik.yenile()} />
        </Kart>
      ) : (
        <JiraTetikDurumKarti d={tetik.veri} yenile={() => void tetik.yenile(true)} yukleniyor={tetik.yukleniyor} gereksinimler={anahtarlar} />
      )}
    </>
  );
}

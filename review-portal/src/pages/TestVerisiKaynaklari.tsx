// Test verisi kataloğunun veritabanı kaynakları (`/test-data-sources`): katalog, projenin salt okunur
// veritabanına tanımlı SELECT sorgularından doldurulur. Her değer kolonu `<grup>.<slug(anahtar)>.<alan>`
// kaydı üretir. Liste `case.read`; tanım, önizleme ve yenileme `testdata.manage` (kataloğu düzenleyenler).
// Sorgular worker'da koşar: önizleme ve yenileme iş kimliği döner, sonuç yoklanır.
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { ApiError, hataMesaji } from "../api/http";
import type {
  KaynakIsi,
  KaynakOnizleme,
  KaynakOnizlemeDurumu,
  KaynakYenilemeSonucu,
  TestVerisiKaynagi,
  TestVerisiKaynakGirdisi,
  TestVerisiYenilemeSayaclari,
} from "../api/types";
import { useKisiAdi } from "../auth";
import { useBildirim } from "../components/Bildirim";
import { AlanHatasi, BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, Uyari, Yukleniyor } from "../components/ui";
import type { VeriDurumu } from "../hooks";
import type { Ton } from "../lib/etiketler";
import { tarih } from "../lib/format";

const IZIN = "testdata.manage" as const;

/** Yoklama ayarı (testler kısaltır). Sorgular worker'da koşar; ~2 dk sonra vazgeçilir. */
export const kaynakIsAyari = { aralikMs: 1500, sinirMs: 120_000 };

export const IS_ZAMAN_ASIMI = "İş 2 dakikada tamamlanmadı; worker meşgul olabilir. Biraz sonra listeyi yenileyin.";
export const KAYNAK_SURUM_CAKISMASI =
  "Bu kaynak siz düzenlerken değişti (başka biri güncelledi). Değişikliğiniz kaydedilmedi; listeyi yenileyip yeniden deneyin.";

/** İşi bitene (tamam | hata) kadar yoklar. `iptal()` true dönerse (sayfa kapandı) sessizce bırakır. */
export async function kaynakIsiniBekle(jobId: string, iptal: () => boolean): Promise<KaynakIsi | null> {
  const bas = Date.now();
  for (;;) {
    if (iptal()) return null;
    const is = await api.testVerisiKaynakIsi(jobId);
    if (is.durum === "tamam" || is.durum === "hata") return is;
    if (Date.now() - bas > kaynakIsAyari.sinirMs) throw new Error(IS_ZAMAN_ASIMI);
    await new Promise((r) => setTimeout(r, kaynakIsAyari.aralikMs));
  }
}

/** "3 yeni · 1 güncellendi · 0 kaynakta yok" (+ geri gelen / atlanan varsa). */
export function yenilemeOzeti(o: TestVerisiYenilemeSayaclari): string {
  const parcalar = [`${o.eklenen} yeni`, `${o.guncellenen} güncellendi`, `${o.kaynakta_yok} kaynakta yok`];
  if (o.geri_gelen) parcalar.push(`${o.geri_gelen} geri geldi`);
  if (o.atlanan) parcalar.push(`${o.atlanan} atlandı`);
  return parcalar.join(" · ") + (o.kesildi ? " (satır sınırında kesildi)" : "");
}

const ONIZLEME_DURUMU: Record<KaynakOnizlemeDurumu, { etiket: string; ton: Ton; aciklama: string }> = {
  yeni: { etiket: "yeni", ton: "basari", aciklama: "Katalogda yok; eklenecek." },
  ayni: { etiket: "aynı", ton: "notr", aciklama: "Katalogdaki değerle aynı." },
  degisecek: { etiket: "değişecek", ton: "uyari", aciklama: "Katalogdaki değer güncellenecek." },
  silinmis: { etiket: "silinmiş · atlanacak", ton: "hata", aciklama: "Katalogda silinmiş; kaynaktan geri açılmaz." },
  gizli_kayit: { etiket: "gizli kayıt · atlanacak", ton: "hata", aciklama: "Bu anahtar gizli (ortam sırrı) kayıt; üzerine yazılmaz." },
  gizli_cakisma: { etiket: "gizli değer · atlanacak", ton: "hata", aciklama: "Değer bir gizli kaydın değeriyle aynı; gösterilmez, yazılmaz." },
};

interface KolonFormu {
  kolon: string;
  alan: string;
  bicim: "metin" | "tutar";
  aciklama: string;
}

interface KaynakFormDegerleri {
  grup: string;
  aciklama: string;
  sorgu: string;
  anahtar_kolonu: string;
  kolonlar: KolonFormu[];
}

const bosKolon = (): KolonFormu => ({ kolon: "", alan: "", bicim: "metin", aciklama: "" });
const bosKaynakFormu = (): KaynakFormDegerleri => ({ grup: "", aciklama: "", sorgu: "", anahtar_kolonu: "", kolonlar: [bosKolon()] });
const kaynaktanForm = (k: TestVerisiKaynagi): KaynakFormDegerleri => ({
  grup: k.grup,
  aciklama: k.aciklama,
  sorgu: k.sorgu,
  anahtar_kolonu: k.anahtar_kolonu,
  kolonlar: k.deger_kolonlari.length ? k.deger_kolonlari.map((d) => ({ ...d })) : [bosKolon()],
});

/**
 * Formdan sunucu gövdesi. Boş alan: tek değer kolonunda "" gider (anahtar `<grup>.<anahtar>`), birden
 * çok kolonda null (core alanı kolon adından türetir).
 */
function tanimGovdesi(f: KaynakFormDegerleri): TestVerisiKaynakGirdisi {
  const tek = f.kolonlar.length === 1;
  return {
    grup: f.grup.trim(),
    sorgu: f.sorgu.trim(),
    anahtar_kolonu: f.anahtar_kolonu.trim(),
    deger_kolonlari: f.kolonlar.map((d) => ({
      kolon: d.kolon.trim(),
      alan: d.alan.trim() || (tek ? "" : null),
      bicim: d.bicim,
      aciklama: d.aciklama.trim() || null,
    })),
    aciklama: f.aciklama.trim() || null,
  };
}

type KaynakFormDurumu = { tur: "ekle" } | { tur: "duzenle"; kaynak: TestVerisiKaynagi };

function OnizlemeSonucu({ o }: { o: KaynakOnizleme }) {
  if (o.hata !== null) {
    return (
      <Uyari ton="hata" baslik="Sorgu çalıştırılamadı">
        {o.hata}
      </Uyari>
    );
  }
  return (
    <div className="testveri-onizleme" data-testid="kaynak-onizleme">
      <p className="kucuk">
        Sorgu <strong>{o.toplam_satir}</strong> satır döndü{o.kesildi && " (satır sınırında kesildi; fazlası alınmaz)"}; kaynak{" "}
        <strong>{o.kayit_sayisi}</strong> katalog kaydı üretir.{o.satirlar.length < o.toplam_satir && ` İlk ${o.satirlar.length} satır gösteriliyor.`}
      </p>
      {o.kolonlar.length > 0 && (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Sorgu sonucunun ilk satırları">
          <table className="tablo tablo-sik">
            <thead>
              <tr>
                {o.kolonlar.map((k) => (
                  <th scope="col" key={k} className="mono">
                    {k}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {o.satirlar.map((r, i) => (
                <tr key={i}>
                  {r.map((h, j) => (
                    <td key={j} className="mono">
                      {h ?? <span className="soluk">NULL</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {o.kayitlar.length > 0 && (
        <>
          <h4 className="testveri-onizleme-baslik">Bu satırlardan çıkan anahtarlar</h4>
          <ul className="duz-liste kucuk" aria-label="Önizlenen katalog anahtarları">
            {o.kayitlar.map((k) => {
              const d = ONIZLEME_DURUMU[k.durum];
              return (
                <li key={k.anahtar} className="satir-ogeler" data-anahtar={k.anahtar}>
                  <span className="mono">{k.anahtar}</span>
                  {k.deger !== null && <span className="soluk mono">= {k.deger}</span>}
                  <Cip ton={d.ton} title={d.aciklama}>
                    {d.etiket}
                  </Cip>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {o.uyarilar.length > 0 && (
        <Uyari ton="uyari" baslik="Uyarılar">
          <ul className="duz-liste kucuk">
            {o.uyarilar.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </Uyari>
      )}
    </div>
  );
}

function KaynakFormu({ durum, kapat, kaydedildi, yenile }: { durum: KaynakFormDurumu; kapat: () => void; kaydedildi: (k: TestVerisiKaynagi, mesaj: string) => void; yenile: () => void }) {
  const id = useId();
  const duzenle = durum.tur === "duzenle";
  const [f, setF] = useState<KaynakFormDegerleri>(() => (duzenle ? kaynaktanForm(durum.kaynak) : bosKaynakFormu()));
  const [uyari, setUyari] = useState<string | null>(null);
  const [hata, setHata] = useState<{ metin: string; nesne: unknown } | null>(null);
  const [calisiyor, setCalisiyor] = useState(false);
  const [onizleniyor, setOnizleniyor] = useState(false);
  const [onizleme, setOnizleme] = useState<{ sonuc: KaynakOnizleme; tanim: string } | null>(null);
  const [onizlemeHatasi, setOnizlemeHatasi] = useState<{ metin: string; nesne: unknown } | null>(null);
  const baslikRef = useRef<HTMLHeadingElement>(null);
  const kapali = useRef(false);
  useEffect(() => {
    baslikRef.current?.focus();
    kapali.current = false;
    return () => {
      kapali.current = true;
    };
  }, []);

  const kolonAyarla = (i: number, d: Partial<KolonFormu>) => setF({ ...f, kolonlar: f.kolonlar.map((k, j) => (j === i ? { ...k, ...d } : k)) });

  function dogrula(): string | null {
    if (!duzenle && !/^[a-z0-9_]{1,40}$/.test(f.grup.trim())) return "Grup küçük harf, rakam ve alt çizgiyle yazılır (ör. bayi).";
    if (!f.sorgu.trim()) return "SQL sorgusu zorunlu.";
    if (!f.anahtar_kolonu.trim()) return "Anahtar kolonu zorunlu.";
    if (f.kolonlar.some((k) => !k.kolon.trim())) return "Her değer satırında kolon adı zorunlu.";
    return null;
  }

  async function onizle() {
    const u = dogrula();
    if (u) return setUyari(u);
    setUyari(null);
    setOnizlemeHatasi(null);
    setOnizleniyor(true);
    const govde = tanimGovdesi(f);
    try {
      const jobId = await api.testVerisiKaynagiOnizle(govde);
      const is = await kaynakIsiniBekle(jobId, () => kapali.current);
      if (!is) return;
      if (is.durum === "hata" || is.tur !== "onizle" || !is.sonuc) {
        setOnizleme(null);
        setOnizlemeHatasi({ metin: is.hata ?? "Önizleme tamamlanamadı.", nesne: null });
      } else {
        setOnizleme({ sonuc: is.sonuc, tanim: JSON.stringify(govde) });
      }
    } catch (e) {
      setOnizleme(null);
      setOnizlemeHatasi({ metin: e instanceof ApiError ? e.detail || hataMesaji(e) : hataMesaji(e), nesne: e });
    } finally {
      if (!kapali.current) setOnizleniyor(false);
    }
  }

  async function gonder(e: FormEvent) {
    e.preventDefault();
    const u = dogrula();
    if (u) return setUyari(u);
    setUyari(null);
    setHata(null);
    setCalisiyor(true);
    const { grup, ...geri } = tanimGovdesi(f);
    try {
      const k = duzenle
        ? await api.testVerisiKaynagiGuncelle(durum.kaynak.id, { ...geri, aciklama: geri.aciklama ?? "", beklenen_surum: durum.kaynak.surum })
        : await api.testVerisiKaynagiEkle({ grup, ...geri });
      kaydedildi(k, duzenle ? `${k.grup} kaynağı güncellendi (sürüm ${k.surum}). Kataloğa yansıması için yenileyin.` : `${k.grup} kaynağı eklendi. Kataloğu doldurmak için "Yenile"yi kullanın.`);
    } catch (e2) {
      if (e2 instanceof ApiError && e2.status === 409) {
        setHata({ metin: duzenle ? KAYNAK_SURUM_CAKISMASI : e2.detail || `Bu grup için zaten bir kaynak var: ${grup}`, nesne: e2 });
        if (duzenle) yenile();
      } else {
        setHata({ metin: e2 instanceof ApiError && e2.detail ? e2.detail : hataMesaji(e2), nesne: e2 });
      }
    } finally {
      setCalisiyor(false);
    }
  }

  const grupOrnek = f.grup.trim() || "<grup>";
  const eskiOnizleme = onizleme !== null && onizleme.tanim !== JSON.stringify(tanimGovdesi(f));

  return (
    <Kart className="testveri-form">
      <div className="kart-baslik">
        <h3 ref={baslikRef} tabIndex={-1} id={`${id}-baslik`}>
          {duzenle ? `Kaynağı düzenle: ${durum.kaynak.grup}` : "Yeni veritabanı kaynağı"}
        </h3>
      </div>
      <form onSubmit={(e) => void gonder(e)} noValidate aria-labelledby={`${id}-baslik`}>
        <div className="testveri-form-izgara">
          <div className="alan">
            <label htmlFor={`${id}-grup`}>Kaynak grubu</label>
            <input
              id={`${id}-grup`}
              className="mono"
              value={f.grup}
              readOnly={duzenle}
              aria-readonly={duzenle || undefined}
              aria-required="true"
              aria-describedby={`${id}-grup-ipucu`}
              placeholder="bayi"
              onChange={(e) => setF({ ...f, grup: e.target.value })}
            />
            <span id={`${id}-grup-ipucu`} className="soluk kucuk">
              {duzenle ? "Grup değişmez (anahtarların ilk parçası)." : "Anahtarların ilk parçası; küçük harf, rakam, alt çizgi."}
            </span>
          </div>
          <div className="alan">
            <label htmlFor={`${id}-anahtar`}>Anahtar kolonu</label>
            <input
              id={`${id}-anahtar`}
              className="mono"
              value={f.anahtar_kolonu}
              aria-required="true"
              aria-describedby={`${id}-anahtar-ipucu`}
              placeholder="kullanici_adi"
              onChange={(e) => setF({ ...f, anahtar_kolonu: e.target.value })}
            />
            <span id={`${id}-anahtar-ipucu`} className="soluk kucuk">
              Satırı tanımlayan kolon; değeri anahtara küçük harf/alt çizgi olarak girer (P-001 → p_001).
            </span>
          </div>
          <div className="alan testveri-form-genis">
            <label htmlFor={`${id}-aciklama`}>Kaynak açıklaması</label>
            <input id={`${id}-aciklama`} value={f.aciklama} onChange={(e) => setF({ ...f, aciklama: e.target.value })} />
          </div>
          <div className="alan testveri-form-genis">
            <label htmlFor={`${id}-sorgu`}>SQL sorgusu</label>
            <textarea
              id={`${id}-sorgu`}
              className="mono"
              rows={4}
              value={f.sorgu}
              aria-required="true"
              aria-describedby={`${id}-sorgu-ipucu`}
              spellCheck={false}
              placeholder="SELECT kullanici_adi, ad, kredi_limiti FROM bayi ORDER BY kullanici_adi"
              onChange={(e) => setF({ ...f, sorgu: e.target.value })}
            />
            <span id={`${id}-sorgu-ipucu`} className="soluk kucuk">
              Tek SELECT; projenin salt okunur veritabanında çalışır. Hassas kolonlar (parola, hash, token…) reddedilir — sırlar elle girilen
              gizli kayıtlarda kalır.
            </span>
          </div>
        </div>

        <fieldset className="testveri-kolonlar">
          <legend>Değer kolonları</legend>
          <p className="soluk kucuk" id={`${id}-kolon-ipucu`}>
            Her kolon <span className="mono">{`${grupOrnek}.<anahtar>.<alan>`}</span> kaydı üretir; birden çok kolonda boş alan kolon adını alır.
            Tek değer kolonunda alan boş bırakılırsa anahtar <span className="mono">{`${grupOrnek}.<anahtar>`}</span> olur. "Tutar" biçimi parayı{" "}
            <span className="mono">1.250,00 TL</span> yazar. Açıklamada <span className="mono">{"{kolon}"}</span> satırdaki değerle dolar.
          </p>
          <div className="tablo-sarici">
            <table className="tablo tablo-sik">
              <thead>
                <tr>
                  <th scope="col">Kolon</th>
                  <th scope="col">Alan</th>
                  <th scope="col">Biçim</th>
                  <th scope="col">Açıklama</th>
                  <th scope="col">
                    <span className="gorunmez">Eylemler</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {f.kolonlar.map((k, i) => (
                  <tr key={i}>
                    <td>
                      <input
                        className="mono"
                        aria-label={`Değer kolonu ${i + 1}`}
                        aria-describedby={`${id}-kolon-ipucu`}
                        value={k.kolon}
                        onChange={(e) => kolonAyarla(i, { kolon: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="mono"
                        aria-label={`Alan ${i + 1}`}
                        value={k.alan}
                        placeholder={f.kolonlar.length === 1 ? "(boş: alan yok)" : k.kolon.trim().toLowerCase() || undefined}
                        onChange={(e) => kolonAyarla(i, { alan: e.target.value })}
                      />
                    </td>
                    <td>
                      <select aria-label={`Biçim ${i + 1}`} value={k.bicim} onChange={(e) => kolonAyarla(i, { bicim: e.target.value === "tutar" ? "tutar" : "metin" })}>
                        <option value="metin">metin</option>
                        <option value="tutar">tutar</option>
                      </select>
                    </td>
                    <td>
                      <input aria-label={`Kolon açıklaması ${i + 1}`} value={k.aciklama} onChange={(e) => kolonAyarla(i, { aciklama: e.target.value })} />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="dugme dugme-hayalet dugme-kucuk"
                        aria-label={`${i + 1}. değer kolonunu kaldır`}
                        disabled={f.kolonlar.length === 1}
                        onClick={() => setF({ ...f, kolonlar: f.kolonlar.filter((_, j) => j !== i) })}
                      >
                        Kaldır
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" disabled={f.kolonlar.length >= 20} onClick={() => setF({ ...f, kolonlar: [...f.kolonlar, bosKolon()] })}>
            Kolon ekle
          </button>
        </fieldset>

        {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
        {hata && <AlanHatasi asistan={{ hata: hata.metin, kaynak: hata.nesne }}>{hata.metin}</AlanHatasi>}
        <div className="eylemler">
          <IslemDugmesi izin={IZIN} type="submit" calisiyor={calisiyor} disabled={onizleniyor}>
            {duzenle ? "Kaynağı kaydet" : "Kaynağı ekle"}
          </IslemDugmesi>
          <IslemDugmesi izin={IZIN} tur="ikincil" calisiyor={onizleniyor} disabled={calisiyor} onClick={() => void onizle()}>
            Önizle
          </IslemDugmesi>
          <button type="button" className="dugme dugme-hayalet" onClick={kapat} disabled={calisiyor}>
            Vazgeç
          </button>
        </div>
      </form>
      <div aria-live="polite">
        {onizleniyor && <Yukleniyor metin="Sorgu worker'da çalışıyor…" />}
        {onizlemeHatasi && <AlanHatasi asistan={{ hata: onizlemeHatasi.metin, kaynak: onizlemeHatasi.nesne }}>{onizlemeHatasi.metin}</AlanHatasi>}
        {onizleme && !onizleniyor && (
          <>
            {eskiOnizleme && <Uyari ton="bilgi">Tanım önizlemeden sonra değişti; güncel sonuç için yeniden önizleyin.</Uyari>}
            <OnizlemeSonucu o={onizleme.sonuc} />
          </>
        )}
      </div>
    </Kart>
  );
}

function KaynakSilmeOnayi({ kaynak, vazgec, silindi, yenile }: { kaynak: TestVerisiKaynagi; vazgec: () => void; silindi: () => void; yenile: () => void }) {
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<{ metin: string; nesne: unknown } | null>(null);
  const vazgecRef = useRef<HTMLButtonElement>(null);
  useEffect(() => vazgecRef.current?.focus(), []);

  async function sil() {
    setCalisiyor(true);
    setHata(null);
    try {
      await api.testVerisiKaynagiSil(kaynak.id, kaynak.surum);
      silindi();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setHata({ metin: KAYNAK_SURUM_CAKISMASI, nesne: e });
        yenile();
      } else {
        setHata({ metin: hataMesaji(e), nesne: e });
      }
    } finally {
      setCalisiyor(false);
    }
  }

  return (
    <div className="onay-kutusu" role="group" aria-label={`${kaynak.grup} kaynağı silme onayı`}>
      <p>
        <span className="mono">{kaynak.grup}</span> kaynağı silinsin mi? Bu kaynaktan gelen {kaynak.kayit_sayisi} katalog kaydı silinmez; elle girilmiş
        kayıt olarak kalır ve artık yenilenmez.
      </p>
      <div className="satir-ogeler">
        <button type="button" className="dugme dugme-tehlike dugme-kucuk" disabled={calisiyor} aria-busy={calisiyor || undefined} onClick={() => void sil()}>
          Evet, kaynağı sil
        </button>
        <button ref={vazgecRef} type="button" className="dugme dugme-ikincil dugme-kucuk" disabled={calisiyor} onClick={vazgec}>
          Vazgeç
        </button>
      </div>
      {hata && <AlanHatasi asistan={{ hata: hata.metin, kaynak: hata.nesne }}>{hata.metin}</AlanHatasi>}
    </div>
  );
}

function SonYenileme({ k }: { k: TestVerisiKaynagi }) {
  if (!k.son_yenileme) return <span className="soluk">Henüz yenilenmedi</span>;
  const d = k.son_durum;
  return (
    <>
      {tarih(k.son_yenileme)}
      {d && (d.hata ? <div className="alan-hata">{d.hata}</div> : <div className="soluk">{yenilemeOzeti(d)}</div>)}
    </>
  );
}

/** Yenileme işinin durumu: hangi kaynak (null = tümü) yenileniyor ya da son sonuç. */
type Yenileme = { tur: "calisiyor"; kaynakId: string | null } | { tur: "bitti"; sonuc: KaynakYenilemeSonucu | null; hata: string | null; nesne?: unknown };

export function VeritabaniKaynaklari({
  kaynaklar,
  duzenleyebilir,
  katalogYenile,
}: {
  kaynaklar: VeriDurumu<TestVerisiKaynagi[]>;
  duzenleyebilir: boolean;
  /** Yenileme bitince katalog listesi de yeniden yüklenir. */
  katalogYenile: () => void;
}) {
  const bildir = useBildirim();
  const kisiAdi = useKisiAdi();
  const [form, setForm] = useState<KaynakFormDurumu | null>(null);
  const [silinecek, setSilinecek] = useState<string | null>(null);
  const [yenileme, setYenileme] = useState<Yenileme | null>(null);
  const kapali = useRef(false);
  useEffect(() => {
    kapali.current = false;
    return () => {
      kapali.current = true;
    };
  }, []);
  const yenileniyor = yenileme?.tur === "calisiyor";
  const liste = kaynaklar.veri ?? [];

  async function yenile(kaynak: TestVerisiKaynagi | null) {
    setYenileme({ tur: "calisiyor", kaynakId: kaynak?.id ?? null });
    try {
      const jobId = await api.testVerisiKaynaklariniYenile(kaynak?.id);
      const is = await kaynakIsiniBekle(jobId, () => kapali.current);
      if (!is) return;
      if (is.durum === "hata" || is.tur !== "yenile") {
        setYenileme({ tur: "bitti", sonuc: null, hata: is.hata ?? "Yenileme tamamlanamadı." });
      } else {
        setYenileme({ tur: "bitti", sonuc: is.sonuc, hata: null });
        const t = is.sonuc?.toplam;
        bildir(t ? `${kaynak ? `${kaynak.grup} kaynağı` : "Kaynaklar"} yenilendi: ${yenilemeOzeti(t)}.` : "Kaynaklar yenilendi.");
      }
    } catch (e) {
      if (kapali.current) return;
      setYenileme({ tur: "bitti", sonuc: null, hata: e instanceof ApiError && e.detail ? e.detail : hataMesaji(e), nesne: e });
    }
    void kaynaklar.yenile(true);
    katalogYenile();
  }

  if (kaynaklar.hataKodu === 501 && !kaynaklar.veri) return null; // çekirdek bu ucu henüz sunmuyor

  return (
    <Kart
      baslik="Veritabanı kaynakları"
      className="testveri-kaynaklar"
      eylemler={
        duzenleyebilir && (
          <>
            <button
              type="button"
              className="dugme dugme-ikincil dugme-kucuk"
              onClick={() => setForm({ tur: "ekle" })}
              disabled={form?.tur === "ekle" || yenileniyor}
            >
              Kaynak ekle
            </button>
            <IslemDugmesi
              izin={IZIN}
              kucuk
              calisiyor={yenileniyor && yenileme.kaynakId === null}
              disabled={yenileniyor || liste.length === 0}
              onClick={() => void yenile(null)}
            >
              Tümünü yenile
            </IslemDugmesi>
          </>
        )
      }
    >
      <p className="soluk kucuk">
        Katalog, projenin salt okunur veritabanındaki SELECT sorgularından doldurulabilir. Yenileme yeni anahtarları ekler, değişen değerleri günceller;
        kaynakta artık dönmeyen kayıtlar silinmez, "Kaynakta yok" olarak işaretlenir.
      </p>

      <div aria-live="polite" data-testid="kaynak-yenileme-durumu">
        {yenileme?.tur === "calisiyor" && (
          <Yukleniyor
            metin={`${yenileme.kaynakId ? `${liste.find((k) => k.id === yenileme.kaynakId)?.grup ?? ""} kaynağı` : "Tüm kaynaklar"} yenileniyor (sorgular worker'da çalışıyor)…`}
          />
        )}
        {yenileme?.tur === "bitti" &&
          (yenileme.hata ? (
            <AlanHatasi asistan={{ hata: yenileme.hata, kaynak: yenileme.nesne }}>{yenileme.hata}</AlanHatasi>
          ) : (
            yenileme.sonuc && (
              <Uyari ton={yenileme.sonuc.toplam.hata ? "uyari" : "basari"} baslik={`Yenileme tamamlandı: ${yenilemeOzeti(yenileme.sonuc.toplam)}`}>
                <ul className="duz-liste kucuk">
                  {yenileme.sonuc.kaynaklar.map((s) => (
                    <li key={s.id}>
                      <span className="mono">{s.grup}</span>: {s.hata ? <span className="alan-hata">{s.hata}</span> : `${s.satir} satır · ${yenilemeOzeti(s)}`}
                      {s.uyarilar.length > 0 && <span className="soluk"> · {s.uyarilar.length} uyarı</span>}
                    </li>
                  ))}
                </ul>
              </Uyari>
            )
          ))}
      </div>

      {form && (
        <KaynakFormu
          key={form.tur === "duzenle" ? form.kaynak.id : "ekle"}
          durum={form}
          kapat={() => setForm(null)}
          yenile={() => void kaynaklar.yenile(true)}
          kaydedildi={(k, mesaj) => {
            bildir(mesaj);
            setForm(null);
            kaynaklar.setVeri(liste.some((x) => x.id === k.id) ? liste.map((x) => (x.id === k.id ? k : x)) : [...liste, k]);
            void kaynaklar.yenile(true);
          }}
        />
      )}

      {kaynaklar.yukleniyor && !kaynaklar.veri ? (
        <Yukleniyor />
      ) : kaynaklar.hata && !kaynaklar.veri ? (
        <HataKutusu hata={kaynaklar.hata} kaynak={kaynaklar.hataNesnesi} yenile={() => void kaynaklar.yenile()} />
      ) : liste.length === 0 ? (
        <BosDurum baslik="Tanımlı veritabanı kaynağı yok.">{duzenleyebilir && "'Kaynak ekle' ile bir SELECT sorgusu tanımlayın."}</BosDurum>
      ) : (
        <ul className="duz-liste testveri-kaynak-listesi" aria-label="Veritabanı kaynakları">
          {liste.map((k) => (
            <li key={k.id} data-kaynak={k.grup} className="testveri-kaynak">
              <div className="testveri-kaynak-ust">
                <span className="satir-ogeler">
                  <strong className="mono">{k.grup}</strong>
                  {k.on_tanimli && (
                    <Cip ton="bilgi" title="Bayi Portalı tohumundan gelen kaynak">
                      Ön tanımlı
                    </Cip>
                  )}
                  {k.aciklama && <span>{k.aciklama}</span>}
                </span>
                {duzenleyebilir && (
                  <span className="satir-ogeler testveri-eylemler">
                    <IslemDugmesi
                      izin={IZIN}
                      tur="ikincil"
                      kucuk
                      aria-label={`${k.grup} kaynağını yenile`}
                      calisiyor={yenileniyor && yenileme.kaynakId === k.id}
                      disabled={yenileniyor}
                      onClick={() => void yenile(k)}
                    >
                      Yenile
                    </IslemDugmesi>
                    <button
                      type="button"
                      className="dugme dugme-ikincil dugme-kucuk"
                      aria-label={`${k.grup} kaynağını düzenle`}
                      disabled={yenileniyor}
                      onClick={() => setForm({ tur: "duzenle", kaynak: k })}
                    >
                      Düzenle
                    </button>
                    <button
                      type="button"
                      className="dugme dugme-hayalet dugme-kucuk"
                      aria-label={`${k.grup} kaynağını sil`}
                      aria-expanded={silinecek === k.id}
                      disabled={yenileniyor}
                      onClick={() => setSilinecek(k.id)}
                    >
                      Sil
                    </button>
                  </span>
                )}
              </div>
              <dl className="testveri-kaynak-ayrinti kucuk">
                <div>
                  <dt>Anahtar kolonu</dt>
                  <dd className="mono">{k.anahtar_kolonu}</dd>
                </div>
                <div>
                  <dt>Değer kolonları</dt>
                  <dd className="mono">
                    {k.deger_kolonlari.map((d) => `${d.kolon}${d.alan && d.alan !== d.kolon ? `→${d.alan}` : !d.alan ? "→(anahtar)" : ""}${d.bicim === "tutar" ? " (tutar)" : ""}`).join(", ")}
                  </dd>
                </div>
                <div>
                  <dt>Kayıt</dt>
                  <dd>
                    {k.kayit_sayisi}
                    {k.kaynakta_yok_sayisi > 0 && (
                      <>
                        {" "}
                        <Cip ton="uyari">{k.kaynakta_yok_sayisi} kaynakta yok</Cip>
                      </>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Son yenileme</dt>
                  <dd>
                    <SonYenileme k={k} />
                  </dd>
                </div>
              </dl>
              <details className="kucuk">
                <summary>SQL</summary>
                <pre className="mono testveri-sorgu">{k.sorgu}</pre>
                <span className="soluk">
                  Sürüm {k.surum} · {k.guncelleyen ? kisiAdi(k.guncelleyen) : "—"} · {tarih(k.guncelleme)}
                </span>
              </details>
              {silinecek === k.id && (
                <KaynakSilmeOnayi
                  kaynak={k}
                  vazgec={() => setSilinecek(null)}
                  yenile={() => void kaynaklar.yenile(true)}
                  silindi={() => {
                    bildir(`${k.grup} kaynağı silindi; kayıtları katalogda kaldı.`);
                    setSilinecek(null);
                    kaynaklar.setVeri(liste.filter((x) => x.id !== k.id));
                    void kaynaklar.yenile(true);
                    katalogYenile();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </Kart>
  );
}

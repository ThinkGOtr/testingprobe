// Test verisi kataloğu (specs/013-sprint-otomasyonu §3.3, §3.5; K6, K10, K11). Case metni değeri değil
// `{veri:anahtar}` atfını taşır; kod üretimi değeri buradan okur. Analist, Testçi ve Mühendis düzenler
// (`testdata.manage`, 012), case okuyan roller görür (`case.read`). Her değişiklik sürüm + denetim kaydıdır; düzenleme iyimser kilitle (`beklenen_surum`) gönderilir.
// Gizli kayıtların değeri kataloğa yazılmaz (ortam sırrı); ekranda yalnız "sır tanımlı / tanımsız".
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, hataMesaji } from "../api/http";
import type { AtifYapanCase, CaseDurumu, TestVerisi, TestVerisiSurumu } from "../api/types";
import { ANAHTAR_RE, SIR_ADI_RE, atifYapanlarUyarla } from "../api/uyumOtomasyon";
import { useIzin, useKisiAdi } from "../auth";
import type { Izin } from "../lib/yetki";
import { useBildirim } from "../components/Bildirim";
import { AlanHatasi, BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { GIZLI_DEGER } from "../components/VeriAtfi";
import { useVeri } from "../hooks";
import { CASE_DURUMU } from "../lib/etiketler";
import { tarih } from "../lib/format";

/** Kataloğu düzenleme izni (K11; 012: `testdata.manage`). */
export const TESTVERI_IZNI = "testdata.manage" satisfies Izin;

export const SURUM_CAKISMASI =
  "Bu kayıt siz düzenlerken değişti (başka biri güncelledi). Değişikliğiniz kaydedilmedi; güncel değeri yükleyip yeniden deneyin.";

const ISLEM_ADI: Record<TestVerisiSurumu["islem"], string> = { olustur: "oluşturuldu", guncelle: "güncellendi", sil: "silindi" };

/** Arama: anahtar, değer, açıklama, grup ve sır adında (büyük/küçük harf duyarsız, Türkçe). */
export function testVerisiAra(liste: TestVerisi[], sorgu: string): TestVerisi[] {
  const q = sorgu.trim().toLocaleLowerCase("tr-TR");
  if (!q) return liste;
  return liste.filter((k) =>
    [k.anahtar, k.deger, k.aciklama, k.grup, k.sir_adi].some((x) => (x ?? "").toLocaleLowerCase("tr-TR").includes(q)),
  );
}

export const GRUP_IPUCU = "Boş bırakılırsa grup anahtarın ilk parçası olur.";

/** Grup → kayıtlar (grup adına, sonra anahtara göre sıralı). */
export function gruplara(liste: TestVerisi[]): [string, TestVerisi[]][] {
  const m = new Map<string, TestVerisi[]>();
  for (const k of liste) {
    const g = k.grup ?? "diğer";
    m.set(g, [...(m.get(g) ?? []), k]);
  }
  return [...m.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "tr"))
    .map(([g, l]) => [g, [...l].sort((a, b) => a.anahtar.localeCompare(b.anahtar, "tr"))]);
}

type FormDurumu = { tur: "ekle" } | { tur: "duzenle"; kayit: TestVerisi };

interface FormDegerleri {
  anahtar: string;
  grup: string;
  aciklama: string;
  deger: string;
  gizli: boolean;
  sir_adi: string;
}

const bosForm = (): FormDegerleri => ({ anahtar: "", grup: "", aciklama: "", deger: "", gizli: false, sir_adi: "" });
const kayittanForm = (k: TestVerisi): FormDegerleri => ({
  anahtar: k.anahtar,
  grup: k.grup ?? "",
  aciklama: k.aciklama ?? "",
  deger: k.deger ?? "",
  gizli: k.gizli,
  sir_adi: k.sir_adi ?? "",
});

function KayitFormu({
  durum,
  guncelKayit,
  kapat,
  kaydedildi,
  yenile,
}: {
  durum: FormDurumu;
  /** 409 (sürüm uyuşmazlığı): liste sessizce yenilenir, "güncel değeri yükle" yeni sürümü gösterir. */
  yenile: () => void;
  /** Listede şu an duran kayıt (409 sonrası "güncel değeri yükle" için). */
  guncelKayit: TestVerisi | undefined;
  kapat: () => void;
  kaydedildi: (k: TestVerisi, mesaj: string) => void;
}) {
  const id = useId();
  const duzenle = durum.tur === "duzenle";
  const [f, setF] = useState<FormDegerleri>(() => (duzenle ? kayittanForm(durum.kayit) : bosForm()));
  const [surum, setSurum] = useState(duzenle ? durum.kayit.surum : 0);
  const [uyari, setUyari] = useState<string | null>(null);
  const [hata, setHata] = useState<{ metin: string; nesne: unknown } | null>(null);
  const [cakisma, setCakisma] = useState(false);
  const [calisiyor, setCalisiyor] = useState(false);
  const baslikRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => baslikRef.current?.focus(), []);

  async function gonder(e: FormEvent) {
    e.preventDefault();
    const anahtar = f.anahtar.trim();
    if (!duzenle && !ANAHTAR_RE.test(anahtar)) {
      return setUyari("Anahtar küçük harf, rakam, alt çizgi ve nokta ile yazılır; en çok 6 parça (ör. bayi.bayi1.kullanici_adi).");
    }
    if (f.gizli && !f.sir_adi.trim()) return setUyari("Gizli kayıt için ortam sırrının adı zorunlu (değer kataloğa yazılmaz).");
    if (f.gizli && !SIR_ADI_RE.test(f.sir_adi.trim())) return setUyari("Ortam sırrı adı TP_TESTVERI_ ile başlar; büyük harf, rakam ve alt çizgi (ör. TP_TESTVERI_DEMO_PAROLA).");
    if (duzenle) {
      const once = kayittanForm(durum.kayit);
      // Boş grup sunucuda anahtarın ilk parçası olur: karşılaştırma o değerle yapılır.
      const ilkParca = durum.kayit.anahtar.split(".")[0];
      const grupDegisti = (f.grup.trim() || ilkParca) !== (once.grup.trim() || ilkParca);
      if (!grupDegisti && (["aciklama", "deger", "sir_adi"] as const).every((k) => f[k].trim() === once[k].trim() && (k !== "deger" || f.deger === once.deger))) {
        return setUyari("Değişiklik yok.");
      }
    }
    if (!f.gizli && !f.deger) return setUyari("Değer boş olamaz.");
    setUyari(null);
    setHata(null);
    setCalisiyor(true);
    try {
      const ortak = {
        // Düzenlemede boş grup "" gider: core grubu anahtarın ilk parçasına döndürür (null "değiştirme" demektir).
        grup: duzenle ? f.grup.trim() : f.grup.trim() || null,
        // Düzenlemede boş açıklama "" gider (null core'da "değiştirme" demektir; açıklama silinemezdi).
        aciklama: duzenle ? f.aciklama.trim() : f.aciklama.trim() || null,
        ...(f.gizli ? { sir_adi: f.sir_adi.trim() } : { deger: f.deger }),
      };
      const k = duzenle
        ? await api.testVerisiGuncelle(durum.kayit.id, { ...ortak, beklenen_surum: surum })
        : await api.testVerisiEkle({ anahtar, gizli: f.gizli, ...ortak });
      kaydedildi(k, duzenle ? `${k.anahtar} güncellendi (sürüm ${k.surum}).` : `${k.anahtar} eklendi.`);
    } catch (e2) {
      if (e2 instanceof ApiError && e2.status === 409) {
        if (duzenle) {
          setCakisma(true);
          setHata({ metin: SURUM_CAKISMASI, nesne: e2 });
          yenile();
        } else {
          setHata({ metin: e2.detail || `Bu anahtar zaten var: ${anahtar}`, nesne: e2 });
        }
      } else {
        setHata({ metin: hataMesaji(e2), nesne: e2 });
      }
    } finally {
      setCalisiyor(false);
    }
  }

  return (
    <Kart className="testveri-form">
      <div className="kart-baslik">
        <h2 ref={baslikRef} tabIndex={-1} id={`${id}-baslik`}>
          {duzenle ? `Düzenle: ${durum.kayit.anahtar}` : "Yeni test verisi"}
        </h2>
      </div>
      <form onSubmit={(e) => void gonder(e)} noValidate aria-labelledby={`${id}-baslik`}>
        <div className="testveri-form-izgara">
          <div className="alan">
            <label htmlFor={`${id}-anahtar`}>Anahtar</label>
            <input
              id={`${id}-anahtar`}
              className="mono"
              value={f.anahtar}
              readOnly={duzenle}
              aria-readonly={duzenle || undefined}
              aria-describedby={`${id}-anahtar-ipucu`}
              aria-required="true"
              placeholder="bayi.bayi1.kullanici_adi"
              onChange={(e) => setF({ ...f, anahtar: e.target.value })}
            />
            <span id={`${id}-anahtar-ipucu`} className="soluk kucuk">
              {duzenle
                ? "Anahtar değişmez (case'ler bu anahtara atıf yapar)."
                : <>Case metninde <span className="mono">{"{veri:anahtar}"}</span> olarak geçer.</>}
            </span>
          </div>
          <div className="alan">
            <label htmlFor={`${id}-grup`}>Grup</label>
            <input
              id={`${id}-grup`}
              value={f.grup}
              placeholder="bayi"
              aria-describedby={`${id}-grup-ipucu`}
              onChange={(e) => setF({ ...f, grup: e.target.value })}
            />
            <span id={`${id}-grup-ipucu`} className="soluk kucuk">
              {GRUP_IPUCU}
            </span>
          </div>
          <div className="alan testveri-form-genis">
            <label htmlFor={`${id}-aciklama`}>Açıklama</label>
            <input id={`${id}-aciklama`} value={f.aciklama} onChange={(e) => setF({ ...f, aciklama: e.target.value })} />
          </div>
          <div className="alan alan-satir testveri-form-genis">
            <input
              id={`${id}-gizli`}
              type="checkbox"
              checked={f.gizli}
              disabled={duzenle}
              aria-describedby={`${id}-gizli-ipucu`}
              onChange={(e) => setF({ ...f, gizli: e.target.checked })}
            />
            <label htmlFor={`${id}-gizli`}>Gizli (parola vb.)</label>
            <span id={`${id}-gizli-ipucu`} className="soluk kucuk">
              Gizli değer kataloğa ve Jira'ya yazılmaz; kod üretimi ortam sırrından okur.{duzenle && " Gizlilik sonradan değiştirilemez."}
            </span>
          </div>
          {f.gizli ? (
            <div className="alan testveri-form-genis">
              <label htmlFor={`${id}-sir`}>Ortam sırrının adı</label>
              <input
                id={`${id}-sir`}
                className="mono"
                value={f.sir_adi}
                placeholder="TP_TESTVERI_DEMO_PAROLA"
                aria-required="true"
                onChange={(e) => setF({ ...f, sir_adi: e.target.value })}
              />
            </div>
          ) : (
            <div className="alan testveri-form-genis">
              <label htmlFor={`${id}-deger`}>Değer</label>
              <input id={`${id}-deger`} value={f.deger} aria-required="true" onChange={(e) => setF({ ...f, deger: e.target.value })} />
              {duzenle && (
                <span className="soluk kucuk">
                  Değişiklik onaylı case'lerin onayını düşürmez; bu veriyle üretilmiş testlerde "test verisi değişti" uyarısı çıkar.
                </span>
              )}
            </div>
          )}
        </div>
        {uyari && <AlanHatasi>{uyari}</AlanHatasi>}
        {hata && <AlanHatasi asistan={{ hata: hata.metin, kaynak: hata.nesne }}>{hata.metin}</AlanHatasi>}
        <div className="eylemler">
          <IslemDugmesi izin={TESTVERI_IZNI} type="submit" calisiyor={calisiyor} disabled={cakisma}>
            {duzenle ? "Kaydet" : "Ekle"}
          </IslemDugmesi>
          {cakisma && guncelKayit && guncelKayit.surum !== surum && (
            <button
              type="button"
              className="dugme dugme-ikincil"
              onClick={() => {
                setF(kayittanForm(guncelKayit));
                setSurum(guncelKayit.surum);
                setCakisma(false);
                setHata(null);
              }}
            >
              Güncel değeri yükle (sürüm {guncelKayit.surum})
            </button>
          )}
          <button type="button" className="dugme dugme-hayalet" onClick={kapat} disabled={calisiyor}>
            Vazgeç
          </button>
        </div>
      </form>
    </Kart>
  );
}

/** Sürüm geçmişi çekmecesi: açılınca başlığa odak, Esc ya da "Kapat" ile kapanır ve odak tetikleyene döner. */
function GecmisCekmecesi({ kayit, kapat }: { kayit: TestVerisi; kapat: () => void }) {
  const gecmis = useVeri(() => api.testVerisiGecmisi(kayit.id), [kayit.id]);
  const kisiAdi = useKisiAdi();
  const baslikRef = useRef<HTMLHeadingElement>(null);
  const id = useId();
  useEffect(() => baslikRef.current?.focus(), [kayit.id]);
  return (
    <aside
      className="kart cekmece"
      aria-labelledby={`${id}-baslik`}
      data-testid="surum-gecmisi"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          kapat();
        }
      }}
    >
      <div className="kart-baslik">
        <h2 id={`${id}-baslik`} ref={baslikRef} tabIndex={-1}>
          Sürüm geçmişi: <span className="mono">{kayit.anahtar}</span>
        </h2>
        <div className="eylemler">
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={kapat}>
            Kapat
          </button>
        </div>
      </div>
      {gecmis.yukleniyor && !gecmis.veri ? (
        <Yukleniyor />
      ) : gecmis.hata && !gecmis.veri ? (
        <HataKutusu hata={gecmis.hata} kaynak={gecmis.hataNesnesi} yenile={() => void gecmis.yenile()} />
      ) : (gecmis.veri ?? []).length === 0 ? (
        <BosDurum baslik="Sürüm kaydı yok." />
      ) : (
        <ol className="duz-liste surum-listesi" aria-label={`${kayit.anahtar} sürümleri`}>
          {gecmis.veri!.map((s) => (
            <li key={s.surum}>
              <span className="satir-ogeler">
                <span className="mono">s{s.surum}</span>
                <Cip ton={s.islem === "sil" ? "hata" : s.islem === "olustur" ? "basari" : "notr"}>{ISLEM_ADI[s.islem]}</Cip>
                <span className="soluk kucuk">
                  {s.degistiren ? kisiAdi(s.degistiren) : "—"} · {tarih(s.zaman)}
                </span>
              </span>
              <div className="kucuk">
                {s.gizli ? (
                  <>
                    {GIZLI_DEGER}
                    {s.sir_adi && (
                      <>
                        {" "}
                        · sır <span className="mono">{s.sir_adi}</span>
                      </>
                    )}
                  </>
                ) : s.islem === "sil" ? (
                  "—"
                ) : (
                  <span className="mono">{s.deger ?? "—"}</span>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}

function SilmeOnayi({
  kayit,
  vazgec,
  silindi,
  yenile,
}: {
  kayit: TestVerisi;
  vazgec: () => void;
  silindi: (anahtar: string) => void;
  yenile: () => void;
}) {
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<{ metin: string; nesne: unknown } | null>(null);
  const [atif, setAtif] = useState<AtifYapanCase[]>([]);
  // İlk odak geri dönülebilir eylemde: çift Enter yanlışlıkla silmesin.
  const vazgecRef = useRef<HTMLButtonElement>(null);
  useEffect(() => vazgecRef.current?.focus(), []);

  async function sil() {
    setCalisiyor(true);
    setHata(null);
    setAtif([]);
    try {
      await api.testVerisiSil(kayit.id, kayit.surum);
      silindi(kayit.anahtar);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const liste = atifYapanlarUyarla(e.govde);
        setAtif(liste);
        setHata({
          metin: liste.length
            ? `Silinemedi: ${liste.length} etkin case bu test verisine atıf yapıyor. Önce case'lerden atfı kaldırın.`
            : /sürüm|surum|değişti/i.test(e.detail)
              ? SURUM_CAKISMASI
              : e.detail,
          nesne: e,
        });
        if (!liste.length) yenile();
      } else {
        setHata({ metin: hataMesaji(e), nesne: e });
      }
    } finally {
      setCalisiyor(false);
    }
  }

  return (
    <div className="onay-kutusu" role="group" aria-label={`${kayit.anahtar} silme onayı`}>
      <p>
        <span className="mono">{kayit.anahtar}</span> silinsin mi? Kayıt geçmişte kalır (sürüm + denetim); atıf yapan case varsa silinmez.
      </p>
      <div className="satir-ogeler">
        <button type="button" className="dugme dugme-tehlike dugme-kucuk" disabled={calisiyor} aria-busy={calisiyor || undefined} onClick={() => void sil()}>
          Evet, sil
        </button>
        <button ref={vazgecRef} type="button" className="dugme dugme-ikincil dugme-kucuk" disabled={calisiyor} onClick={vazgec}>
          Vazgeç
        </button>
      </div>
      {hata && <AlanHatasi asistan={{ hata: hata.metin, kaynak: hata.nesne }}>{hata.metin}</AlanHatasi>}
      {atif.length > 0 && (
        <ul className="duz-liste kucuk" aria-label="Atıf yapan case'ler" data-testid="atif-yapan-caseler">
          {atif.map((c) => {
            const durum = c.durum ? (CASE_DURUMU[c.durum as CaseDurumu]?.etiket ?? c.durum) : null;
            const ad = `${c.case_ref ?? `${c.jira_key ?? "Case"}${c.sira_no !== null ? ` #${c.sira_no}` : ""}`}${c.baslik ? ` · ${c.baslik}` : ""}${durum ? ` (${durum})` : ""}`;
            return (
              <li key={c.id}>{c.requirement_id ? <Link to={`/gereksinimler/${encodeURIComponent(c.requirement_id)}/caseler`}>{ad}</Link> : ad}</li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Model kipi etiketi (K17 notu). */
const KIP_ADI: Record<string, string> = { live: "canlı", record: "kayıt", replay: "REPLAY", auto: "otomatik" };

/**
 * K17/K18: katalog case üretimine ne zaman girer ve neyi atfa çevirir. Model kipi `/demo/status`
 * (herkes okur) `model.mod`'dan; okunamazsa genel ifade.
 */
function KatalogKapsamNotu() {
  const durum = useVeri(() => api.demoDurumu().catch(() => null), []);
  const mod = durum.veri?.model?.mod ?? null;
  const kip = mod ? (KIP_ADI[mod] ?? mod) : null;
  return (
    <Uyari ton="bilgi" baslik="Katalog case üretimine nasıl girer">
      <ul className="duz-liste kucuk" data-testid="katalog-kapsam-notu">
        <li>
          Model kipi canlı ya da kayıt (live/record) iken case üretimine giden test verisi bu katalogdan kurulur. REPLAY (demo provası)
          kipinde kayıtlı veri kullanılır; katalog değişikliği o case'lere yansımaz.
          {kip && (
            <>
              {" "}
              Şu anki kip: <strong>{kip}</strong>
              {mod === "replay" ? " — katalog değişikliği yeni üretilen case'lere yansımaz." : "."}
            </>
          )}
        </li>
        <li>
          Yalnız bayi, ürün, kampanya ve ortak (parola) grupları case metninde otomatik olarak atfa çevrilir; tutar biçimli değerler yalnız
          adım verisinde ve ön koşullarda. Etiket ve ayar grupları case'e otomatik atfedilmez (gerekirse düzeltirken elle eklenir).
        </li>
        <li data-testid="katalog-ide-notu">
          IDE/MCP kanalı (Claude Code, Copilot) her zaman bu kataloğu kullanır; REPLAY kipinde de katalog değişikliği bu kanalda yazılan
          case'lere yansır. Gizli değerler bu kanala atıf olarak gider.
        </li>
        <li>Gizli kayıtların değeri hiçbir ekranda gösterilmez; kod üretimi ortam sırrından okur.</li>
      </ul>
    </Uyari>
  );
}

export function TestVerisiSayfasi() {
  const liste = useVeri(() => api.testVerileri(), []);
  const kisiAdi = useKisiAdi();
  const bildir = useBildirim();
  const duzenleyebilir = useIzin(TESTVERI_IZNI);
  const [sorgu, setSorgu] = useState("");
  const [form, setForm] = useState<FormDurumu | null>(null);
  const [gecmis, setGecmis] = useState<TestVerisi | null>(null);
  const [silinecek, setSilinecek] = useState<string | null>(null);
  const tetikleyen = useRef<HTMLElement | null>(null);
  const aramaId = useId();

  const kayitlar = liste.veri ?? [];
  const gruplar = useMemo(() => gruplara(testVerisiAra(kayitlar, sorgu)), [kayitlar, sorgu]);
  const bulunan = gruplar.reduce((a, [, l]) => a + l.length, 0);

  const odagiGeriVer = () => {
    const el = tetikleyen.current;
    tetikleyen.current = null;
    if (el && document.contains(el)) requestAnimationFrame(() => el.focus());
  };
  const ac = (fn: () => void) => {
    tetikleyen.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    fn();
  };

  return (
    <>
      <SayfaBasligi
        baslik="Test verisi"
        aciklama="Case'ler değeri değil anahtarı taşır ({veri:anahtar}); kod üretimi değeri buradan okur. Değer değişince onay düşmez, o veriyle üretilmiş testlerde uyarı çıkar."
        eylemler={
          duzenleyebilir && (
            <button type="button" className="dugme dugme-birincil" onClick={() => ac(() => setForm({ tur: "ekle" }))} disabled={form?.tur === "ekle"}>
              Yeni kayıt
            </button>
          )
        }
      />
      {!duzenleyebilir && (
        <Uyari ton="bilgi">Kataloğu Analist, Testçi ve Mühendis düzenler; siz değerleri ve sürüm geçmişini görüntüleyebilirsiniz.</Uyari>
      )}
      <KatalogKapsamNotu />

      {form && (
        <KayitFormu
          key={form.tur === "duzenle" ? form.kayit.id : "ekle"}
          durum={form}
          guncelKayit={form.tur === "duzenle" ? kayitlar.find((k) => k.id === form.kayit.id) : undefined}
          kapat={() => {
            setForm(null);
            odagiGeriVer();
          }}
          yenile={() => void liste.yenile(true)}
          kaydedildi={(k, mesaj) => {
            bildir(mesaj);
            setForm(null);
            const varMi = kayitlar.some((x) => x.id === k.id);
            liste.setVeri(varMi ? kayitlar.map((x) => (x.id === k.id ? k : x)) : [...kayitlar, k]);
            void liste.yenile(true);
            odagiGeriVer();
          }}
        />
      )}

      {gecmis && (
        <GecmisCekmecesi
          kayit={gecmis}
          kapat={() => {
            setGecmis(null);
            odagiGeriVer();
          }}
        />
      )}

      <Kart>
        <div className="alan testveri-arama">
          <label htmlFor={aramaId}>Ara</label>
          <input
            id={aramaId}
            type="search"
            value={sorgu}
            placeholder="Anahtar, değer, açıklama…"
            aria-describedby={`${aramaId}-sonuc`}
            onChange={(e) => setSorgu(e.target.value)}
          />
          <span id={`${aramaId}-sonuc`} className="soluk kucuk" aria-live="polite">
            {liste.veri ? (sorgu.trim() ? `${bulunan} / ${kayitlar.length} kayıt` : `${kayitlar.length} kayıt`) : ""}
          </span>
        </div>
        {liste.yukleniyor && !liste.veri ? (
          <Yukleniyor />
        ) : liste.hata && !liste.veri ? (
          <HataKutusu hata={liste.hata} kaynak={liste.hataNesnesi} yenile={() => void liste.yenile()} />
        ) : kayitlar.length === 0 ? (
          <BosDurum baslik="Katalogda henüz test verisi yok.">{duzenleyebilir && "'Yeni kayıt' ile ekleyin."}</BosDurum>
        ) : gruplar.length === 0 ? (
          <BosDurum baslik="Aramayla eşleşen kayıt yok." />
        ) : (
          gruplar.map(([grup, l], gi) => (
            // Başlık kimliği indeksle: grup adındaki boşluk aria-labelledby IDREF listesini bölmesin.
            <section key={grup} className="testveri-grup" aria-labelledby={`${aramaId}-g-${gi}`}>
              <h2 id={`${aramaId}-g-${gi}`} className="testveri-grup-baslik">
                {grup} <span className="soluk kucuk">({l.length})</span>
              </h2>
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label={`${grup} grubu test verileri`}>
                <table className="tablo tablo-sik">
                  <thead>
                    <tr>
                      <th scope="col">Anahtar</th>
                      <th scope="col">Değer</th>
                      <th scope="col">Açıklama</th>
                      <th scope="col">Sürüm</th>
                      <th scope="col">Kullanım</th>
                      <th scope="col">Güncelleme</th>
                      <th scope="col">
                        <span className="gorunmez">Eylemler</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {l.map((k) => (
                      <tr key={k.id} data-anahtar={k.anahtar}>
                        <td className="mono">{k.anahtar}</td>
                        <td>
                          {k.gizli ? (
                            <span className="satir-ogeler">
                              <span>{GIZLI_DEGER}</span>
                              <Cip ton={k.sir_tanimli ? "basari" : "hata"} title={k.sir_adi ? `Ortam sırrı: ${k.sir_adi}` : undefined}>
                                {k.sir_tanimli ? "sır tanımlı" : "sır tanımsız"}
                              </Cip>
                              {k.sir_adi && <span className="mono soluk kucuk">{k.sir_adi}</span>}
                            </span>
                          ) : (
                            <span className="mono">{k.deger ?? "—"}</span>
                          )}
                        </td>
                        <td>{k.aciklama ?? <span className="soluk">—</span>}</td>
                        <td className="mono">s{k.surum}</td>
                        <td>
                          <span aria-label={`${k.kullanim} case atıf yapıyor`}>{k.kullanim}</span>
                        </td>
                        <td className="kucuk">
                          {k.guncelleyen ? kisiAdi(k.guncelleyen) : "—"}
                          <div className="soluk">{tarih(k.guncelleme)}</div>
                        </td>
                        <td>
                          <div className="satir-ogeler testveri-eylemler">
                            <button
                              type="button"
                              className="dugme dugme-hayalet dugme-kucuk"
                              aria-label={`${k.anahtar} sürüm geçmişi`}
                              aria-expanded={gecmis?.id === k.id}
                              onClick={() => ac(() => setGecmis(k))}
                            >
                              Geçmiş
                            </button>
                            {duzenleyebilir && (
                              <>
                                <button
                                  type="button"
                                  className="dugme dugme-ikincil dugme-kucuk"
                                  aria-label={`${k.anahtar} düzenle`}
                                  onClick={() => ac(() => setForm({ tur: "duzenle", kayit: k }))}
                                >
                                  Düzenle
                                </button>
                                <button
                                  type="button"
                                  className="dugme dugme-hayalet dugme-kucuk"
                                  aria-label={`${k.anahtar} sil`}
                                  aria-expanded={silinecek === k.id}
                                  onClick={() => ac(() => setSilinecek(k.id))}
                                >
                                  Sil
                                </button>
                              </>
                            )}
                          </div>
                          {silinecek === k.id && (
                            <SilmeOnayi
                              kayit={k}
                              vazgec={() => {
                                setSilinecek(null);
                                odagiGeriVer();
                              }}
                              silindi={(anahtar) => {
                                bildir(`${anahtar} silindi.`);
                                setSilinecek(null);
                                tetikleyen.current = null;
                                liste.setVeri(kayitlar.filter((x) => x.id !== k.id));
                                void liste.yenile(true);
                              }}
                              yenile={() => void liste.yenile(true)}
                            />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))
        )}
      </Kart>
    </>
  );
}

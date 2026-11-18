// 013 sprint otomasyonu örnek arka ucu: test verisi kataloğu, otomasyon ayarları, Jira tetiği durumu ve
// jira-sim durum değişikliği (specs/013-sprint-otomasyonu §3.1, §3.3, §3.4). Core sözleşmesindeki
// kurallar taklit edilir: rol kapısı (analyst | engineer düzenler), iyimser kilit (beklenen_surum → 409),
// atıf yapan case varken silme 409 + liste, gizli kayıtta değer yok.
import { ApiError } from "../http";
import type { Kullanici, TestCase, TestCaseIcerik } from "../types";
import type { Izin } from "../../lib/yetki";
import { atifDeseni, ANAHTAR_RE, SIR_ADI_RE } from "../uyumOtomasyon";

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

interface KatalogKaydi {
  id: string;
  anahtar: string;
  grup: string | null;
  aciklama: string | null;
  deger: string | null;
  gizli: boolean;
  sir_adi: string | null;
  surum: number;
  silindi: boolean;
  guncelleyen: string | null;
  guncelleme: string | null;
  kaynak_id: string | null;
  kaynakta_yok: boolean;
}

interface SurumKaydi {
  test_verisi_id: string;
  surum: number;
  islem: "olustur" | "guncelle" | "sil";
  deger: string | null;
  gizli: boolean;
  sir_adi: string | null;
  degistiren: string;
  zaman: string;
}

const T0 = "2026-11-10T09:00:00+03:00";
/** Örnek veride tanımlı ortam sırları (gerçek değer tutulmaz; yalnız "tanımlı mı"). */
const TANIMLI_SIRLAR = new Set(["TP_TESTVERI_DEMO_PAROLA"]);

function ilkKatalog(): KatalogKaydi[] {
  const k = (id: number, anahtar: string, grup: string, deger: string | null, aciklama: string, sir_adi: string | null = null): KatalogKaydi => ({
    id: `tv-${id}`,
    anahtar,
    grup,
    aciklama,
    deger,
    gizli: sir_adi !== null,
    sir_adi,
    surum: 1,
    silindi: false,
    guncelleyen: "tohum",
    guncelleme: T0,
    // Tohum kayıtları ön tanımlı kaynaklardan gelir (ortak grubu: elle girilmiş gizli kayıt).
    kaynak_id: ON_TANIMLI_GRUPLAR.includes(grup) ? `kyn-${grup}` : null,
    kaynakta_yok: false,
  });
  return [
    k(1, "bayi.bayi1.kullanici_adi", "bayi", "bayi1", "Kampanyalı bayi kullanıcı adı"),
    k(2, "bayi.bayi1.ad", "bayi", "Anadolu Bayi", "Bayi görünen adı"),
    k(3, "bayi.bayi2.kullanici_adi", "bayi", "bayi2", "Düşük kredi limitli bayi"),
    k(4, "bayi.bayi2.kredi_limiti", "bayi", "500,00 TL", "Kredi limiti"),
    k(5, "urun.p_001.ad", "urun", "Portakal Gazozu 1L", "Kampanyalı ürün"),
    k(6, "urun.p_001.fiyat", "urun", "30,00 TL", "Birim fiyat"),
    k(7, "kampanya.k6_1.ad", "kampanya", "6 al 1 bedava", "Kampanya adı"),
    k(8, "ayar.min_siparis_tutari", "ayar", "250,00 TL", "Minimum sipariş tutarı"),
    k(9, "ortak.demo_parola", "ortak", null, "Demo kullanıcılarının parolası (ortam sırrı)", "TP_TESTVERI_DEMO_PAROLA"),
  ];
}

// ------------------------------------------------------------ veritabanı kaynakları (örnek)

interface KaynakKolonu {
  kolon: string;
  alan: string;
  bicim: "metin" | "tutar";
  aciklama: string;
}

interface KaynakKaydi {
  id: string;
  grup: string;
  aciklama: string;
  sorgu: string;
  anahtar_kolonu: string;
  deger_kolonlari: KaynakKolonu[];
  sira: number;
  on_tanimli: boolean;
  surum: number;
  silindi: boolean;
  guncelleyen: string | null;
  guncelleme: string | null;
  son_yenileme: string | null;
  son_durum: Record<string, unknown> | null;
}

interface KaynakIsKaydi {
  id: string;
  tur: "yenile" | "onizle";
  /** Örnek veride iş ilk sorgulamada "çalışıyor", ikincide tamam görünür (yoklama sınansın). */
  sorgulama: number;
  sonuc: Record<string, unknown>;
}

const ON_TANIMLI_GRUPLAR = ["bayi", "urun", "kampanya", "ayar"];

/** Salt okunur proje veritabanının örnek tabloları (Bayi Portalı tohumu). */
const ORNEK_DB: Record<string, { kolonlar: string[]; satirlar: (string | null)[][] }> = {
  bayi: {
    kolonlar: ["kullanici_adi", "ad", "kredi_limiti", "parola_hash"],
    satirlar: [
      ["bayi1", "Anadolu Bayi", "10000.00", "x"],
      ["bayi2", "Ege Bayi", "500.00", "x"],
    ],
  },
  urun: {
    kolonlar: ["kod", "ad", "fiyat", "aktif"],
    satirlar: [
      ["P-001", "Portakal Gazozu 1L", "30.00", "true"],
      ["P-002", "Limonata 1L", "25.50", "true"],
    ],
  },
  kampanya: { kolonlar: ["kod", "ad", "urun_kodu"], satirlar: [["K6-1", "6 al 1 bedava", "P-001"]] },
  ayar: { kolonlar: ["anahtar", "deger"], satirlar: [["min_siparis_tutari", "250,00 TL"]] },
};

const ON_TANIMLI_SORGULAR: Record<string, string> = {
  bayi: "SELECT kullanici_adi, ad, kredi_limiti FROM bayi WHERE kullanici_adi <> 'bayi3' ORDER BY kullanici_adi",
  urun: "SELECT kod, ad, fiyat FROM urun WHERE aktif ORDER BY sira, kod",
  kampanya: "SELECT kampanya.kod, kampanya.ad, urun.kod AS urun_kodu FROM kampanya JOIN urun ON urun.id = kampanya.urun_id WHERE kampanya.aktif ORDER BY kampanya.kod",
  ayar: "SELECT anahtar, deger FROM ayar ORDER BY anahtar",
};

function ilkKaynaklar(): KaynakKaydi[] {
  const kol = (kolon: string, alan: string, bicim: "metin" | "tutar", aciklama: string): KaynakKolonu => ({ kolon, alan, bicim, aciklama });
  const k = (sira: number, grup: string, aciklama: string, anahtar_kolonu: string, deger_kolonlari: KaynakKolonu[]): KaynakKaydi => ({
    id: `kyn-${grup}`,
    grup,
    aciklama,
    sorgu: ON_TANIMLI_SORGULAR[grup],
    anahtar_kolonu,
    deger_kolonlari,
    sira,
    on_tanimli: true,
    surum: 1,
    silindi: false,
    guncelleyen: "tohum",
    guncelleme: T0,
    son_yenileme: null,
    son_durum: null,
  });
  return [
    k(0, "bayi", "Test kullanıcıları (bayiler)", "kullanici_adi", [
      kol("kullanici_adi", "kullanici_adi", "metin", "Test kullanıcısının kullanıcı adı"),
      kol("ad", "ad", "metin", "Bayi adı"),
      kol("kredi_limiti", "kredi_limiti", "tutar", "Kredi limiti"),
    ]),
    k(1, "urun", "Aktif ürünler", "kod", [kol("kod", "kod", "metin", "Ürün kodu"), kol("ad", "ad", "metin", "Ürün adı"), kol("fiyat", "fiyat", "tutar", "Birim fiyat")]),
    k(2, "kampanya", "Aktif kampanyalar", "kod", [kol("kod", "kod", "metin", "Kampanya kodu; ürün: {urun_kodu}"), kol("ad", "ad", "metin", "Kampanya adı")]),
    k(3, "ayar", "Uygulama ayarları", "anahtar", [kol("deger", "", "metin", "Uygulama ayarı ({anahtar})")]),
  ];
}

const durum = {
  katalog: ilkKatalog(),
  kaynaklar: ilkKaynaklar(),
  kaynakIsleri: [] as KaynakIsKaydi[],
  surumler: [] as SurumKaydi[],
  sayac: 100,
  ayarlar: {
    otomatik_kod_uretimi: { acik: true, guncelleyen: null as string | null, guncelleme: null as string | null },
    jira_tetik: { acik: true, durum: "QA To Do", aralik_s: 60, otomatik_case: true, guncelleyen: null as string | null, guncelleme: null as string | null },
  },
  sonTetiklenenler: [] as { jira_key: string; zaman: string; sonuc: string; neden?: string | null }[],
  sonTur: null as {
    zaman: string;
    bulunan: number;
    tetiklenen: number;
    ertelenen: number;
    taban: boolean;
    hata: string | null;
    sonuclar: { jira_key: string; sonuc: string; neden: string | null }[];
  } | null,
};

/** Sim'de tetik açık başlar ve worker taban turunu çoktan koşmuştur (tohum): yeni giriş tetiklenir. */
function tabanTuru(): NonNullable<typeof durum.sonTur> {
  return { zaman: T0, bulunan: 0, tetiklenen: 0, ertelenen: 0, taban: true, hata: null, sonuclar: [] };
}
durum.sonTur = tabanTuru();

function tohumSurumleri(): SurumKaydi[] {
  return durum.katalog.map((k) => ({
    test_verisi_id: k.id,
    surum: 1,
    islem: "olustur",
    deger: k.deger,
    gizli: k.gizli,
    sir_adi: k.sir_adi,
    degistiren: "tohum",
    zaman: T0,
  }));
}
durum.surumler = tohumSurumleri();

export function otomasyonMockSifirla(): void {
  durum.katalog = ilkKatalog();
  durum.kaynaklar = ilkKaynaklar();
  durum.kaynakIsleri = [];
  durum.surumler = tohumSurumleri();
  durum.sayac = 100;
  durum.ayarlar.otomatik_kod_uretimi = { acik: true, guncelleyen: null, guncelleme: null };
  durum.ayarlar.jira_tetik = { acik: true, durum: "QA To Do", aralik_s: 60, otomatik_case: true, guncelleyen: null, guncelleme: null };
  durum.sonTetiklenenler = [];
  durum.sonTur = tabanTuru();
}

export function otomatikKodAcik(): boolean {
  return durum.ayarlar.otomatik_kod_uretimi.acik;
}

const simdi = () => new Date().toISOString();
const etkin = () => durum.katalog.filter((k) => !k.silindi);

/** Case içeriğinin atıf yapılabilen alanları (core atif.py: başlık hariç). */
/** Atıf taşıyan case alanları (K22: başlık dahil). */
function alanMetinleri(i: TestCaseIcerik): string[] {
  return [i.title, ...i.preconditions, ...i.steps.flatMap((s) => [s.action, s.data ?? "", s.expected]), i.expected_result];
}

export function icerikAtiflari(i: TestCaseIcerik): string[] {
  return [...new Set(alanMetinleri(i).flatMap((m) => [...m.matchAll(atifDeseni())].map((e) => e[1])))];
}

/** Düzelt kararında katalogda olmayan anahtarlar (core: 422). */
export function bilinmeyenAtiflar(i: TestCaseIcerik): string[] {
  const var_ = new Set(etkin().map((k) => k.anahtar));
  return icerikAtiflari(i).filter((a) => !var_.has(a));
}

/** `serialize_cases` `veri` alanı. */
export function caseVerisi(i: TestCaseIcerik): Record<string, { deger: string | null; gizli: boolean; surum: number | null; var: boolean }> {
  const out: Record<string, { deger: string | null; gizli: boolean; surum: number | null; var: boolean }> = {};
  for (const a of icerikAtiflari(i)) {
    const k = etkin().find((x) => x.anahtar === a);
    out[a] = k ? { deger: k.gizli ? null : k.deger, gizli: k.gizli, surum: k.surum, var: true } : { deger: null, gizli: false, surum: null, var: false };
  }
  return out;
}

function gorunum(k: KatalogKaydi, caseler: TestCase[]) {
  const { silindi: _s, ...geri } = k;
  return {
    ...geri,
    deger: k.gizli ? null : k.deger,
    sir_tanimli: k.gizli ? TANIMLI_SIRLAR.has(k.sir_adi ?? "") : false,
    kullanim: atifYapanlar(k.anahtar, caseler).length,
  };
}

function atifYapanlar(anahtar: string, caseler: TestCase[]): TestCase[] {
  return caseler.filter((c) => c.durum !== "superseded" && c.durum !== "rejected" && icerikAtiflari(c.icerik).includes(anahtar));
}

function surumYaz(k: KatalogKaydi, islem: SurumKaydi["islem"], aktor: string): void {
  durum.surumler.push({ test_verisi_id: k.id, surum: k.surum, islem, deger: k.gizli ? null : k.deger, gizli: k.gizli, sir_adi: k.sir_adi, degistiren: aktor, zaman: simdi() });
}

const metinMi = (x: unknown): x is string => typeof x === "string";
const istegeBagli = (x: unknown): string | null => (metinMi(x) && x.trim() ? x.trim() : null);

function bulKayit(id: string): KatalogKaydi {
  const k = durum.katalog.find((x) => x.id === id && !x.silindi);
  if (!k) throw new ApiError(404, `Test verisi bulunamadı: ${id}`);
  return k;
}

// ------------------------------------------------------------ kaynak taklidi (core testveri/kaynak.py)

const GRUP_RE = /^[a-z0-9_]{1,40}$/;
const ALAN_RE = /^[a-z0-9_]{0,40}$/;
const KOLON_RE = /^[A-Za-z_][A-Za-z0-9_$#]{0,63}$/;
/** Sorgu muhafızı: hassas kolonlar reddedilir (sırlar elle girilen gizli kayıtlarda kalır). */
const HASSAS_RE = /(parola|sifre|password|passwd|hash|token|secret|gizli)/i;
const TR: Record<string, string> = { ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u", Ç: "c", Ğ: "g", İ: "i", Ö: "o", Ş: "s", Ü: "u" };

export function slug(m: string): string {
  const s = [...m].map((c) => TR[c] ?? c).join("").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return s || "x";
}

/** core testdata.tl: `1250` → `1.250,00 TL` (sayı değilse olduğu gibi). */
export function tl(deger: string): string {
  const n = Number(deger);
  if (!deger.trim() || !Number.isFinite(n)) return deger;
  const [tam, kusur] = Math.abs(n).toFixed(2).split(".");
  return `${n < 0 ? "-" : ""}${tam.replace(/\B(?=(\d{3})+(?!\d))/g, ".")},${kusur} TL`;
}

type Tanim = Pick<KaynakKaydi, "grup" | "sorgu" | "anahtar_kolonu" | "deger_kolonlari" | "aciklama">;

function tanimDogrula(b: Record<string, unknown>, grupZorunlu = true): Tanim {
  const grup = metinMi(b.grup) ? b.grup.trim() : "";
  if (grupZorunlu && !GRUP_RE.test(grup)) throw new ApiError(422, "Grup küçük harf, rakam ve alt çizgiyle yazılır (en çok 40 karakter).");
  const sorgu = metinMi(b.sorgu) ? b.sorgu.trim() : "";
  if (!sorgu) throw new ApiError(422, "Sorgu zorunlu.");
  if (!/^select\s/i.test(sorgu) || /;\s*\S/.test(sorgu)) throw new ApiError(422, "Yalnızca SELECT sorgusu tanımlanabilir");
  const anahtar_kolonu = metinMi(b.anahtar_kolonu) ? b.anahtar_kolonu.trim() : "";
  if (!KOLON_RE.test(anahtar_kolonu)) throw new ApiError(422, "Anahtar kolonu geçerli bir kolon adı olmalı.");
  const ham = Array.isArray(b.deger_kolonlari) ? (b.deger_kolonlari as Record<string, unknown>[]) : [];
  if (!ham.length) throw new ApiError(422, "En az bir değer kolonu tanımlayın.");
  const deger_kolonlari = ham.map((d) => {
    const kolon = metinMi(d?.kolon) ? d.kolon.trim() : "";
    if (!KOLON_RE.test(kolon)) throw new ApiError(422, `Geçersiz değer kolonu: ${kolon || "(boş)"}`);
    // core: alan null → slug(kolon); "" → alansız anahtar (yalnız tek değer kolonunda).
    const alan = metinMi(d.alan) ? d.alan.trim() : slug(kolon);
    if (!ALAN_RE.test(alan)) throw new ApiError(422, `Geçersiz alan adı: ${alan}`);
    const bicim = d.bicim === "tutar" ? "tutar" : "metin";
    return { kolon, alan, bicim, aciklama: metinMi(d.aciklama) ? d.aciklama.trim() : "" } satisfies KaynakKolonu;
  });
  if (deger_kolonlari.length > 1 && deger_kolonlari.some((d) => !d.alan)) {
    throw new ApiError(422, "Alan adı yalnız tek değer kolonlu kaynakta boş bırakılabilir");
  }
  const alanlar = deger_kolonlari.map((d) => d.alan);
  if (new Set(alanlar).size !== alanlar.length) throw new ApiError(422, "Alan adları tekil olmalı.");
  return { grup, sorgu, anahtar_kolonu, deger_kolonlari, aciklama: metinMi(b.aciklama) ? b.aciklama.trim() : "" };
}

/** Örnek "çalıştırıcı": FROM tablosu ve projeksiyon adları (takma ad ya da son parça) okunur. */
function sorguCalistir(sorgu: string): { kolonlar: string[]; satirlar: (string | null)[][] } {
  const m = sorgu.match(/^select\s+([\s\S]+?)\s+from\s+([a-z_][a-z0-9_]*)/i);
  if (!m) throw new Error("Sorgu çalıştırılamadı: FROM bulunamadı.");
  const tablo = ORNEK_DB[m[2].toLowerCase()];
  if (!tablo) throw new Error(`Sorgu çalıştırılamadı: "${m[2]}" tablosu yok.`);
  const projeksiyon = m[1].split(",").map((p) => p.trim());
  const adlar = projeksiyon.map((p) => {
    const ad = (p.match(/\s+as\s+([a-z_][a-z0-9_]*)$/i)?.[1] ?? p.split(".").pop() ?? p).toLowerCase();
    if (HASSAS_RE.test(ad)) throw new Error(`Sorgu muhafızı: hassas kolon okunamaz (${ad}). Sırları elle gizli kayıt olarak girin.`);
    return ad;
  });
  const kolonlar = projeksiyon[0] === "*" ? tablo.kolonlar.filter((k) => !HASSAS_RE.test(k)) : adlar;
  const yok = kolonlar.find((k) => !tablo.kolonlar.includes(k));
  if (yok) throw new Error(`Sorgu çalıştırılamadı: "${yok}" kolonu yok.`);
  const idx = kolonlar.map((k) => tablo.kolonlar.indexOf(k));
  return { kolonlar, satirlar: tablo.satirlar.map((r) => idx.map((i) => r[i])) };
}

interface UretilenKayit {
  anahtar: string;
  deger: string;
  aciklama: string;
}

function kayitlariUret(t: Tanim, kolonlar: string[], satirlar: (string | null)[][]): { kayitlar: UretilenKayit[]; uyarilar: string[] } {
  const uyarilar: string[] = [];
  const ai = kolonlar.indexOf(t.anahtar_kolonu.toLowerCase());
  if (ai < 0) throw new Error(`Anahtar kolonu sonuçta yok: ${t.anahtar_kolonu}`);
  const eksik = t.deger_kolonlari.find((d) => !kolonlar.includes(d.kolon.toLowerCase()));
  if (eksik) throw new Error(`Değer kolonu sonuçta yok: ${eksik.kolon}`);
  const kayitlar: UretilenKayit[] = [];
  const gorulen = new Set<string>();
  for (const r of satirlar) {
    const ham = r[ai];
    if (ham === null || ham === "") {
      uyarilar.push("Anahtar kolonu boş olan satır atlandı.");
      continue;
    }
    const s = slug(ham);
    const satir = Object.fromEntries(kolonlar.map((k, i) => [k, r[i]]));
    for (const d of t.deger_kolonlari) {
      const anahtar = d.alan ? `${t.grup}.${s}.${d.alan}` : `${t.grup}.${s}`;
      const v = satir[d.kolon.toLowerCase()];
      if (gorulen.has(anahtar)) {
        uyarilar.push(`Yinelenen anahtar atlandı: ${anahtar}`);
        continue;
      }
      if (v === null || v === undefined || v === "") {
        uyarilar.push(`Boş değer atlandı: ${anahtar}`);
        continue;
      }
      gorulen.add(anahtar);
      const aciklama = d.aciklama.replace(/\{([A-Za-z_][A-Za-z0-9_$#]{0,63})\}/g, (tam, ad: string) =>
        ad.toLowerCase() in satir ? (satir[ad.toLowerCase()] ?? "") : tam,
      );
      kayitlar.push({ anahtar, deger: d.bicim === "tutar" ? tl(v) : v, aciklama });
    }
  }
  return { kayitlar, uyarilar };
}

function kaynakGorunum(k: KaynakKaydi) {
  const { silindi: _s, ...geri } = k;
  const kayitlar = etkin().filter((x) => x.kaynak_id === k.id);
  return { ...geri, kayit_sayisi: kayitlar.length, kaynakta_yok_sayisi: kayitlar.filter((x) => x.kaynakta_yok).length };
}

function bulKaynak(id: string): KaynakKaydi {
  const k = durum.kaynaklar.find((x) => x.id === id && !x.silindi);
  if (!k) throw new ApiError(404, "Test verisi kaynağı bulunamadı");
  return k;
}

function kaynakIsiEkle(tur: KaynakIsKaydi["tur"], sonuc: Record<string, unknown>): { job_id: string } {
  const id = `kis-${++durum.sayac}`;
  durum.kaynakIsleri.push({ id, tur, sorgulama: 0, sonuc });
  return { job_id: id };
}

function onizle(t: Tanim): Record<string, unknown> {
  try {
    const { kolonlar, satirlar } = sorguCalistir(t.sorgu);
    const tum = kayitlariUret(t, kolonlar, satirlar);
    const ilk = satirlar.slice(0, 20);
    const gosterilen = kayitlariUret(t, kolonlar, ilk).kayitlar;
    const gizliler = new Set<string>(); // örnek veride gizli değer tutulmaz
    return {
      kolonlar,
      satirlar: ilk,
      toplam_satir: satirlar.length,
      kesildi: false,
      kayit_sayisi: tum.kayitlar.length,
      kayitlar: gosterilen.map((r) => {
        const k = durum.katalog.filter((x) => x.anahtar === r.anahtar).sort((a, b) => Number(a.silindi) - Number(b.silindi))[0];
        const d = gizliler.has(r.deger)
          ? "gizli_cakisma"
          : !k
            ? "yeni"
            : k.silindi
              ? "silinmis"
              : k.gizli
                ? "gizli_kayit"
                : k.deger === r.deger
                  ? "ayni"
                  : "degisecek";
        return { anahtar: r.anahtar, deger: d.startsWith("gizli") ? null : r.deger, durum: d };
      }),
      uyarilar: tum.uyarilar.slice(0, 20),
    };
  } catch (e) {
    return { hata: e instanceof Error ? e.message : String(e) };
  }
}

const bosOzet = () => ({ eklenen: 0, guncellenen: 0, ayni: 0, kaynakta_yok: 0, geri_gelen: 0, atlanan: 0, satir: 0, kesildi: false, uyarilar: [] as string[] });

function kaynagiYenile(k: KaynakKaydi, aktor: string, denetim: (eylem: string, nesne: string, ozet: string) => void) {
  const o = { ...bosOzet(), hata: null as string | null };
  try {
    const { kolonlar, satirlar } = sorguCalistir(k.sorgu);
    const { kayitlar, uyarilar } = kayitlariUret(k, kolonlar, satirlar);
    o.satir = satirlar.length;
    o.uyarilar = uyarilar.slice(0, 20);
    const donen = new Set<string>();
    for (const r of kayitlar) {
      donen.add(r.anahtar);
      const v = durum.katalog.find((x) => x.anahtar === r.anahtar && !x.silindi);
      if (durum.katalog.some((x) => x.anahtar === r.anahtar && x.silindi) && !v) {
        o.atlanan += 1; // elle silinen kayıt kaynaktan geri açılmaz
        continue;
      }
      if (v?.gizli || (v && v.kaynak_id && v.kaynak_id !== k.id)) {
        o.atlanan += 1;
        continue;
      }
      if (!v) {
        const yeni: KatalogKaydi = {
          id: `tv-${++durum.sayac}`,
          anahtar: r.anahtar,
          grup: k.grup,
          aciklama: r.aciklama || null,
          deger: r.deger,
          gizli: false,
          sir_adi: null,
          surum: 1,
          silindi: false,
          guncelleyen: aktor,
          guncelleme: simdi(),
          kaynak_id: k.id,
          kaynakta_yok: false,
        };
        durum.katalog.push(yeni);
        surumYaz(yeni, "olustur", aktor);
        o.eklenen += 1;
        continue;
      }
      if (v.kaynakta_yok) o.geri_gelen += 1;
      v.kaynakta_yok = false;
      v.kaynak_id = k.id;
      if (v.deger === r.deger) {
        o.ayni += 1;
      } else {
        v.deger = r.deger;
        v.surum += 1;
        v.guncelleyen = aktor;
        v.guncelleme = simdi();
        surumYaz(v, "guncelle", aktor);
        o.guncellenen += 1;
      }
    }
    for (const v of etkin().filter((x) => x.kaynak_id === k.id && !donen.has(x.anahtar))) {
      v.kaynakta_yok = true;
      o.kaynakta_yok += 1;
    }
  } catch (e) {
    o.hata = e instanceof Error ? e.message : String(e);
  }
  k.son_yenileme = simdi();
  k.son_durum = { ...o, aktor };
  denetim("testveri.kaynak_yenile", `kaynak:${k.grup}`, o.hata ? `Kaynak yenilenemedi: ${o.hata}` : `Kaynak yenilendi (${o.eklenen} yeni, ${o.guncellenen} güncellendi)`);
  return { id: k.id, grup: k.grup, ...o };
}

export function otomasyonRotalari(
  izinGerekli: (...izinler: [Izin, ...Izin[]]) => Kullanici,
  demoGerekli: () => Kullanici,
  caselerAl: () => TestCase[],
  denetim: (eylem: string, nesne: string, ozet: string) => void,
): Rota[] {
  // 012 kataloğu: test verisi okuma `case.read`, düzenleme `testdata.manage`; ayarlar
  // `dashboard.read` / `automation.manage`, tetik durumu `automation.jira_status`.
  const duzenleyici = () => izinGerekli("testdata.manage");
  return [
    [
      "GET",
      /^\/test-data$/,
      () => {
        izinGerekli("case.read");
        return etkin().map((k) => gorunum(k, caselerAl()));
      },
    ],
    [
      "POST",
      /^\/test-data$/,
      (_m, _q, g) => {
        const u = duzenleyici();
        const b = (g ?? {}) as Record<string, unknown>;
        const anahtar = metinMi(b.anahtar) ? b.anahtar.trim() : "";
        if (!ANAHTAR_RE.test(anahtar)) throw new ApiError(422, "Anahtar küçük harf, rakam, alt çizgi ve nokta ile yazılmalı (ör. bayi.bayi1.ad).");
        if (durum.katalog.some((k) => k.anahtar === anahtar && !k.silindi)) throw new ApiError(409, `Bu anahtar zaten var: ${anahtar}`);
        const gizli = b.gizli === true;
        const sir_adi = istegeBagli(b.sir_adi);
        const deger = metinMi(b.deger) ? b.deger : null;
        if (gizli && !sir_adi) throw new ApiError(422, "Gizli kayıt için ortam sırrı adı zorunlu; değer kataloğa yazılmaz.");
        if (gizli && !SIR_ADI_RE.test(sir_adi ?? "")) throw new ApiError(422, "sir_adi TP_TESTVERI_ ile başlamalı (büyük harf, rakam, alt çizgi).");
        if (gizli && deger) throw new ApiError(422, "Gizli kaydın değeri kataloğa yazılmaz; ortam sırrında tanımlayın.");
        if (!gizli && !deger) throw new ApiError(422, "Değer zorunlu.");
        const k: KatalogKaydi = {
          id: `tv-${++durum.sayac}`,
          anahtar,
          grup: istegeBagli(b.grup) ?? anahtar.split(".")[0],
          aciklama: istegeBagli(b.aciklama),
          deger: gizli ? null : deger,
          gizli,
          sir_adi: gizli ? sir_adi : null,
          surum: 1,
          silindi: false,
          guncelleyen: u.kullanici_adi,
          guncelleme: simdi(),
          kaynak_id: null,
          kaynakta_yok: false,
        };
        durum.katalog.push(k);
        surumYaz(k, "olustur", u.kullanici_adi);
        denetim("testveri.olustur", anahtar, `Test verisi eklendi (sürüm 1)`);
        return gorunum(k, caselerAl());
      },
    ],
    [
      "PUT",
      /^\/test-data\/([^/]+)$/,
      (m, _q, g) => {
        const u = duzenleyici();
        const k = bulKayit(decodeURIComponent(m[1]));
        const b = (g ?? {}) as Record<string, unknown>;
        if (typeof b.beklenen_surum !== "number") throw new ApiError(422, "beklenen_surum zorunlu.");
        if (b.beklenen_surum !== k.surum) {
          throw new ApiError(409, `Kayıt siz görüntüledikten sonra değişti (güncel sürüm ${k.surum}).`, { govde: { detail: "surum", guncel_surum: k.surum } });
        }
        const once = JSON.stringify([k.deger, k.aciklama, k.grup, k.sir_adi]);
        if ("deger" in b) {
          if (k.gizli && b.deger) throw new ApiError(422, "Gizli kaydın değeri kataloğa yazılmaz; ortam sırrında tanımlayın.");
          if (!k.gizli) {
            if (!metinMi(b.deger) || !b.deger) throw new ApiError(422, "Değer zorunlu.");
            k.deger = b.deger;
          }
        }
        if ("aciklama" in b) k.aciklama = istegeBagli(b.aciklama);
        // core: null "değiştirme"; boş metin grubu anahtarın ilk parçasına döndürür.
        if (b.grup === "") k.grup = k.anahtar.split(".")[0];
        else if ("grup" in b && b.grup !== null) k.grup = istegeBagli(b.grup) ?? k.grup;
        if ("sir_adi" in b && k.gizli) {
          const s = istegeBagli(b.sir_adi);
          if (!s) throw new ApiError(422, "Gizli kayıt için ortam sırrı adı zorunlu.");
          k.sir_adi = s;
        }
        if (JSON.stringify([k.deger, k.aciklama, k.grup, k.sir_adi]) === once) throw new ApiError(422, "Değişiklik yok.");
        k.surum += 1;
        k.guncelleyen = u.kullanici_adi;
        k.guncelleme = simdi();
        surumYaz(k, "guncelle", u.kullanici_adi);
        denetim("testveri.guncelle", k.anahtar, `Test verisi güncellendi (sürüm ${k.surum})`);
        return gorunum(k, caselerAl());
      },
    ],
    [
      "DELETE",
      /^\/test-data\/([^/]+)$/,
      (m, q) => {
        const u = duzenleyici();
        const k = bulKayit(decodeURIComponent(m[1]));
        const beklenen = Number(q.get("beklenen_surum"));
        if (!q.get("beklenen_surum") || beklenen !== k.surum) {
          throw new ApiError(409, `Kayıt siz görüntüledikten sonra değişti (güncel sürüm ${k.surum}).`);
        }
        const atif = atifYapanlar(k.anahtar, caselerAl());
        if (atif.length) {
          throw new ApiError(409, `Bu test verisine ${atif.length} etkin case atıf yapıyor; önce case'lerden atfı kaldırın.`, {
            kod: "cakisma",
            govde: {
              kod: "cakisma",
              kullanan: atif.map((c) => ({
                case_id: c.id,
                case_ref: `${c.jira_key ?? "FT"} #${c.sira_no}`,
                baslik: c.icerik.title,
                durum: c.durum,
                requirement_id: c.requirement_id,
              })),
            },
          });
        }
        k.silindi = true;
        k.surum += 1;
        surumYaz(k, "sil", u.kullanici_adi);
        denetim("testveri.sil", k.anahtar, "Test verisi silindi");
        return { id: k.id, anahtar: k.anahtar, silindi: true, surum: k.surum };
      },
    ],
    [
      "GET",
      /^\/test-data\/([^/]+)\/history$/,
      (m) => {
        izinGerekli("case.read");
        const id = decodeURIComponent(m[1]);
        if (!durum.katalog.some((k) => k.id === id)) throw new ApiError(404, `Test verisi bulunamadı: ${id}`);
        return durum.surumler
          .filter((s) => s.test_verisi_id === id)
          .map(({ test_verisi_id: _t, ...s }) => s)
          .sort((a, b) => b.surum - a.surum);
      },
    ],
    [
      "GET",
      /^\/test-data-sources$/,
      () => {
        izinGerekli("case.read");
        return durum.kaynaklar.filter((k) => !k.silindi).sort((a, b) => a.sira - b.sira).map(kaynakGorunum);
      },
    ],
    [
      "POST",
      /^\/test-data-sources\/preview$/,
      (_m, _q, g) => {
        duzenleyici();
        return kaynakIsiEkle("onizle", onizle(tanimDogrula((g ?? {}) as Record<string, unknown>)));
      },
    ],
    [
      "POST",
      /^\/test-data-sources\/refresh$/,
      (_m, _q, g) => {
        const u = duzenleyici();
        const b = (g ?? {}) as Record<string, unknown>;
        const hedef = metinMi(b.kaynak_id) && b.kaynak_id ? [bulKaynak(b.kaynak_id)] : durum.kaynaklar.filter((k) => !k.silindi);
        // Örnek veride iş hemen koşar; sonuç ilk yoklamadan sonra görünür.
        const kaynaklar = hedef.map((k) => kaynagiYenile(k, u.kullanici_adi, denetim));
        const toplam = { ...bosOzet(), hata: null as number | null };
        for (const s of kaynaklar) {
          for (const a of ["eklenen", "guncellenen", "ayni", "kaynakta_yok", "geri_gelen", "atlanan", "satir"] as const) toplam[a] += s[a];
          toplam.kesildi ||= s.kesildi;
          toplam.uyarilar.push(...s.uyarilar);
        }
        const hatali = kaynaklar.filter((s) => s.hata).length;
        toplam.hata = hatali || null;
        return kaynakIsiEkle("yenile", { kaynaklar, toplam });
      },
    ],
    [
      "GET",
      /^\/test-data-sources\/jobs\/([^/]+)$/,
      (m) => {
        duzenleyici();
        const j = durum.kaynakIsleri.find((x) => x.id === decodeURIComponent(m[1]));
        if (!j) throw new ApiError(404, "İş bulunamadı");
        j.sorgulama += 1;
        const bitti = j.sorgulama > 1;
        return { id: j.id, tur: j.tur, durum: bitti ? "tamam" : "calisiyor", sonuc: bitti ? j.sonuc : null, hata: null };
      },
    ],
    [
      "POST",
      /^\/test-data-sources$/,
      (_m, _q, g) => {
        const u = duzenleyici();
        const t = tanimDogrula((g ?? {}) as Record<string, unknown>);
        if (durum.kaynaklar.some((k) => k.grup === t.grup && !k.silindi)) throw new ApiError(409, `Bu grup için zaten bir kaynak var: ${t.grup}`);
        const k: KaynakKaydi = {
          ...t,
          id: `kyn-${++durum.sayac}`,
          sira: Math.max(-1, ...durum.kaynaklar.map((x) => x.sira)) + 1,
          on_tanimli: false,
          surum: 1,
          silindi: false,
          guncelleyen: u.kullanici_adi,
          guncelleme: simdi(),
          son_yenileme: null,
          son_durum: null,
        };
        durum.kaynaklar.push(k);
        denetim("testveri.kaynak_olustur", `kaynak:${k.grup}`, "Test verisi kaynağı eklendi");
        return kaynakGorunum(k);
      },
    ],
    [
      "PUT",
      /^\/test-data-sources\/([^/]+)$/,
      (m, _q, g) => {
        const u = duzenleyici();
        const k = bulKaynak(decodeURIComponent(m[1]));
        const b = (g ?? {}) as Record<string, unknown>;
        if (typeof b.beklenen_surum !== "number") throw new ApiError(422, "beklenen_surum zorunlu.");
        if (b.beklenen_surum !== k.surum) throw new ApiError(409, `Kaynak siz görüntüledikten sonra değişti (güncel sürüm ${k.surum}).`);
        const t = tanimDogrula({ ...k, ...Object.fromEntries(Object.entries(b).filter(([, v]) => v !== undefined && v !== null)), grup: k.grup });
        const once = JSON.stringify([k.sorgu, k.anahtar_kolonu, k.deger_kolonlari, k.aciklama]);
        if (JSON.stringify([t.sorgu, t.anahtar_kolonu, t.deger_kolonlari, t.aciklama]) === once) throw new ApiError(422, "Değişiklik yok");
        Object.assign(k, { sorgu: t.sorgu, anahtar_kolonu: t.anahtar_kolonu, deger_kolonlari: t.deger_kolonlari, aciklama: t.aciklama });
        k.surum += 1;
        k.guncelleyen = u.kullanici_adi;
        k.guncelleme = simdi();
        denetim("testveri.kaynak_guncelle", `kaynak:${k.grup}`, `Test verisi kaynağı güncellendi (sürüm ${k.surum})`);
        return kaynakGorunum(k);
      },
    ],
    [
      "DELETE",
      /^\/test-data-sources\/([^/]+)$/,
      (m, q) => {
        duzenleyici();
        const k = bulKaynak(decodeURIComponent(m[1]));
        if (!q.get("beklenen_surum") || Number(q.get("beklenen_surum")) !== k.surum) {
          throw new ApiError(409, `Kaynak siz görüntüledikten sonra değişti (güncel sürüm ${k.surum}).`);
        }
        k.silindi = true;
        k.surum += 1;
        // Kaynağın kayıtları kalır: elle girilmiş kayıt olur.
        for (const v of durum.katalog.filter((x) => x.kaynak_id === k.id)) Object.assign(v, { kaynak_id: null, kaynakta_yok: false });
        denetim("testveri.kaynak_sil", `kaynak:${k.grup}`, "Test verisi kaynağı silindi");
        return { id: k.id, grup: k.grup, silindi: true, surum: k.surum };
      },
    ],
    [
      "GET",
      /^\/automation-settings$/,
      () => {
        izinGerekli("dashboard.read");
        return durum.ayarlar;
      },
    ],
    [
      "PUT",
      /^\/automation-settings\/([^/]+)$/,
      (m, _q, g) => {
        const u = izinGerekli("automation.manage");
        const anahtar = decodeURIComponent(m[1]);
        const b = (g ?? {}) as Record<string, unknown>;
        if (anahtar === "otomatik_kod_uretimi") {
          if ("acik" in b && typeof b.acik !== "boolean") throw new ApiError(422, "geçersiz ayar alanı: acik");
          if (typeof b.acik === "boolean") durum.ayarlar.otomatik_kod_uretimi.acik = b.acik;
          Object.assign(durum.ayarlar.otomatik_kod_uretimi, { guncelleyen: u.kullanici_adi, guncelleme: simdi() });
        } else if (anahtar === "jira_tetik") {
          // K14: tetikleyen durumu yalnız engineer değiştirir.
          if ("durum" in b) izinGerekli("automation.jira_status");
          const j = durum.ayarlar.jira_tetik;
          const hatali: string[] = [];
          if ("acik" in b && typeof b.acik !== "boolean") hatali.push("acik");
          if ("otomatik_case" in b && typeof b.otomatik_case !== "boolean") hatali.push("otomatik_case");
          if ("durum" in b && (!metinMi(b.durum) || !b.durum.trim() || b.durum.length > 100)) hatali.push("durum");
          if ("aralik_s" in b && (typeof b.aralik_s !== "number" || !Number.isInteger(b.aralik_s) || b.aralik_s < 30 || b.aralik_s > 3600)) hatali.push("aralik_s");
          if (hatali.length) throw new ApiError(422, `geçersiz ayar alanı: ${hatali.sort().join(", ")}`);
          Object.assign(j, b, { guncelleyen: u.kullanici_adi, guncelleme: simdi() });
          if (metinMi(b.durum)) j.durum = b.durum.trim();
        } else {
          throw new ApiError(404, `Ayar bulunamadı: ${anahtar}`);
        }
        denetim("otomasyon.ayar", `ayar:${anahtar}`, "Otomasyon ayarı değişti");
        return durum.ayarlar;
      },
    ],
    [
      "GET",
      /^\/automation\/jira-trigger$/,
      () => {
        izinGerekli("requirement.read");
        const j = durum.ayarlar.jira_tetik;
        return { acik: j.acik, durum: j.durum, aralik_s: j.aralik_s, son_tur: durum.sonTur, son_tetiklenenler: durum.sonTetiklenenler.slice(0, 10) };
      },
    ],
    [
      "POST",
      /^\/demo\/jira-status$/,
      (_m, _q, g) => {
        demoGerekli();
        const b = (g ?? {}) as Record<string, unknown>;
        if (!metinMi(b.jira_key) || !/^[A-Z][A-Z0-9]*-\d+$/.test(b.jira_key)) throw new ApiError(422, "Geçerli bir Jira anahtarı girin (ör. TPD-2).");
        if (!metinMi(b.durum) || !b.durum.trim()) throw new ApiError(422, "Hedef durum zorunlu.");
        const z = simdi();
        // Örnek veri: tetik turu hemen işlenmiş sayılır (gerçekte worker aralik_s içinde görür).
        if (durum.ayarlar.jira_tetik.acik && b.durum === durum.ayarlar.jira_tetik.durum) {
          durum.sonTetiklenenler.unshift({ jira_key: b.jira_key, zaman: z, sonuc: "tetiklendi", neden: "Story QA durumuna girdi; ön incelemeye alındı." });
          durum.sonTur = { zaman: z, bulunan: 1, tetiklenen: 1, ertelenen: 0, taban: false, hata: null, sonuclar: [{ jira_key: b.jira_key, sonuc: "tetiklendi", neden: null }] };
        }
        denetim("demo.jira_status", b.jira_key, `jira-sim: ${b.jira_key} → ${b.durum}`);
        return { jira_key: b.jira_key, durum: b.durum, degisti: true, mesaj: `${b.jira_key} jira-sim'de "${b.durum}" durumuna taşındı.` };
      },
    ],
  ];
}

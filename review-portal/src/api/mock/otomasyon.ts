// 013 sprint otomasyonu örnek arka ucu: test verisi kataloğu, otomasyon ayarları, Jira tetiği durumu ve
// jira-sim durum değişikliği (specs/013-sprint-otomasyonu §3.1, §3.3, §3.4). Core sözleşmesindeki
// kurallar taklit edilir: rol kapısı (analyst | engineer düzenler), iyimser kilit (beklenen_surum → 409),
// atıf yapan case varken silme 409 + liste, gizli kayıtta değer yok.
import { ApiError } from "../http";
import type { Kullanici, Rol, TestCase, TestCaseIcerik } from "../types";
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

const durum = {
  katalog: ilkKatalog(),
  surumler: [] as SurumKaydi[],
  sayac: 100,
  ayarlar: {
    otomatik_kod_uretimi: { acik: true, guncelleyen: null as string | null, guncelleme: null as string | null },
    jira_tetik: { acik: true, durum: "QA To Do", aralik_s: 60, otomatik_case: true, guncelleyen: null as string | null, guncelleme: null as string | null },
  },
  sonTetiklenenler: [] as { jira_key: string; zaman: string; sonuc: string }[],
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
function alanMetinleri(i: TestCaseIcerik): string[] {
  return [...i.preconditions, ...i.steps.flatMap((s) => [s.action, s.data ?? "", s.expected]), i.expected_result];
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

export function otomasyonRotalari(
  girisGerekli: () => Kullanici,
  rolGerekli: (...roller: Rol[]) => Kullanici,
  caselerAl: () => TestCase[],
  denetim: (eylem: string, nesne: string, ozet: string) => void,
): Rota[] {
  const duzenleyici = () => rolGerekli("analyst", "engineer");
  return [
    [
      "GET",
      /^\/test-data$/,
      () => {
        girisGerekli();
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
        girisGerekli();
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
      /^\/automation-settings$/,
      () => {
        girisGerekli();
        return durum.ayarlar;
      },
    ],
    [
      "PUT",
      /^\/automation-settings\/([^/]+)$/,
      (m, _q, g) => {
        const u = duzenleyici();
        const anahtar = decodeURIComponent(m[1]);
        const b = (g ?? {}) as Record<string, unknown>;
        if (anahtar === "otomatik_kod_uretimi") {
          if ("acik" in b && typeof b.acik !== "boolean") throw new ApiError(422, "geçersiz ayar alanı: acik");
          if (typeof b.acik === "boolean") durum.ayarlar.otomatik_kod_uretimi.acik = b.acik;
          Object.assign(durum.ayarlar.otomatik_kod_uretimi, { guncelleyen: u.kullanici_adi, guncelleme: simdi() });
        } else if (anahtar === "jira_tetik") {
          // K14: tetikleyen durumu yalnız engineer değiştirir.
          if ("durum" in b && u.rol !== "engineer") throw new ApiError(403, "Tetikleyen Jira durumunu yalnız Otomasyon mühendisi değiştirir.");
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
        girisGerekli();
        const j = durum.ayarlar.jira_tetik;
        return { acik: j.acik, durum: j.durum, aralik_s: j.aralik_s, son_tur: durum.sonTur, son_tetiklenenler: durum.sonTetiklenenler.slice(0, 10) };
      },
    ],
    [
      "POST",
      /^\/demo\/jira-status$/,
      (_m, _q, g) => {
        rolGerekli("presenter");
        const b = (g ?? {}) as Record<string, unknown>;
        if (!metinMi(b.jira_key) || !/^[A-Z][A-Z0-9]*-\d+$/.test(b.jira_key)) throw new ApiError(422, "Geçerli bir Jira anahtarı girin (ör. TPD-2).");
        if (!metinMi(b.durum) || !b.durum.trim()) throw new ApiError(422, "Hedef durum zorunlu.");
        const z = simdi();
        // Örnek veri: tetik turu hemen işlenmiş sayılır (gerçekte worker aralik_s içinde görür).
        if (durum.ayarlar.jira_tetik.acik && b.durum === durum.ayarlar.jira_tetik.durum) {
          durum.sonTetiklenenler.unshift({ jira_key: b.jira_key, zaman: z, sonuc: "tetiklendi" });
          durum.sonTur = { zaman: z, bulunan: 1, tetiklenen: 1, ertelenen: 0, taban: false, hata: null, sonuclar: [{ jira_key: b.jira_key, sonuc: "tetiklendi", neden: null }] };
        }
        denetim("demo.jira_status", b.jira_key, `jira-sim: ${b.jira_key} → ${b.durum}`);
        return { jira_key: b.jira_key, durum: b.durum, degisti: true, mesaj: `${b.jira_key} jira-sim'de "${b.durum}" durumuna taşındı.` };
      },
    ],
  ];
}

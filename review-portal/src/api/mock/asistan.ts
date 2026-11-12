// Mock arka uç: portal asistanı uçları (AI-ASISTAN-PLANI §9). Gerçek API'nin kurallarını taklit
// eder — kullanıcı başı tek bekleyen soru (409 `bekleyen_var`), `ust_mesaj_id` doğrulaması
// (409 `zaten_derin`), sır içeriği (422 `sir_icerik`), kapalı asistan (503 `asistan_kapali`),
// hız/bütçe (429/402) — ve `assistant.step` / `assistant.answered` olaylarını süreç içi olay
// yolundan yayımlar. Cevaplar hazırlanmış örneklerdir ve `ornek_veri: true` taşır: arayüz
// "ÖRNEK VERİ" gösterir (sahte canlı gösterim yok). Model çağrısı yapılmaz.
import { ApiError, BU_FAZDA_YOK } from "../http";
import type {
  AsistanCevabi,
  AsistanDurumu,
  AsistanMesaji,
  AsistanOnerisi,
  CevapKaynagiOgesi,
  GuvenGosterimi,
  Sohbet,
} from "../asistan";
import type { Kullanici } from "../types";
import { mockOlayYayinla } from "./olaylar";
import { MOCK_KURALLAR } from "./oneri";

const testModu = import.meta.env.MODE === "test";

/** Mock davranış ayarları (testler değiştirir). */
export interface AsistanMockAyar {
  etkin: boolean;
  neden: string | null;
  mod: "live" | "off";
  kalanSoru: number;
  /** false: mesajlar kendiliğinden işlenmez; test `asistanMockIsle` ile ilerletir. */
  otomatikIsle: boolean;
  /** İşleme adımları arası bekleme (ms). */
  adimMs: number;
  mesgul: boolean;
  butceDoldu: boolean;
  gecersizOneriler: string[];
  /** status ucu yokmuş gibi 501 (canlı derlemede "bu fazda yok"). */
  statusYok: boolean;
  /**
   * Bütçe %20 altı vb. (§6.2): otomatik yükseltme ön koşulu tutmaz; "Emin değil" cevap çocuk
   * açmaz, `derin_onerilir: true` taşır (core flow). Soruda "bütçe düşük" geçince de (demo).
   */
  butceDusuk: boolean;
  /**
   * Çalışırken (`running`) durdurulan cevabın işi tur başında durana dek sayılma süresi (ms):
   * bu pencerede yeni soru 409 "Durdurulan cevap kapanıyor" alır (core `_bekleyen_var`). 0: yok.
   */
  kapanmaMs: number;
}

function ilkAyar(): AsistanMockAyar {
  return {
    etkin: true,
    neden: null,
    mod: "live",
    kalanSoru: 30,
    otomatikIsle: true,
    adimMs: testModu ? 0 : 700,
    mesgul: false,
    butceDoldu: false,
    gecersizOneriler: [],
    statusYok: false,
    butceDusuk: false,
    kapanmaMs: testModu ? 0 : 3000,
  };
}

export const asistanMockAyar: AsistanMockAyar = ilkAyar();

export function asistanMockAyarla(d: Partial<AsistanMockAyar>): void {
  Object.assign(asistanMockAyar, d);
}

interface MockSohbet extends Sohbet {
  kullanici_id: string;
  silindi: boolean;
}

interface MockMesaj extends AsistanMesaji {
  /** İç durum: core bunları mesaj yanıtında döndürmez (`mesaj_ozeti`); `disaVer` atar. */
  adim_kodu: string | null;
  basladi: boolean;
  kullanici_id: string;
  baglam: Record<string, unknown> | null;
  oneri_kural_id: string | null;
}

let sohbetler: MockSohbet[] = [];
let mesajlar: MockMesaj[] = [];
let sayac = 0;

/** Testler için: asistan mock durumunu ilk haline getirir (handlers.mockSifirla çağırır). */
export function asistanMockSifirla(): void {
  zamanlayicilar.forEach((z) => clearTimeout(z));
  zamanlayicilar.clear();
  kapananlar.clear();
  sohbetler = [];
  mesajlar = [];
  sayac = 0;
  Object.assign(asistanMockAyar, ilkAyar());
}

function kimlik(onek: string): string {
  sayac += 1;
  return `${onek}-${sayac.toString().padStart(4, "0")}`;
}

const simdi = () => new Date().toISOString();

function disaVer(m: MockMesaj): AsistanMesaji {
  // Sunucu `kullanici_id`/`baglam`/adım kodu/"başladı"yı mesaj yanıtında döndürmez (core `mesaj_ozeti`).
  const { kullanici_id: _k, baglam: _b, oneri_kural_id: _o, adim_kodu: _a, basladi: _ba, ...geri } = m;
  void _k;
  void _b;
  void _o;
  void _a;
  void _ba;
  return geri;
}

function sohbetBul(id: string, k: Kullanici): MockSohbet {
  const s = sohbetler.find((x) => x.id === id && x.kullanici_id === k.id && !x.silindi);
  if (!s) throw new ApiError(404, "Sohbet bulunamadı.", { kod: "bulunamadi" });
  return s;
}

function mesajBul(id: string, k: Kullanici): MockMesaj {
  const m = mesajlar.find((x) => x.id === id && x.kullanici_id === k.id);
  if (!m || sohbetler.find((s) => s.id === m.sohbet_id)?.silindi) throw new ApiError(404, "Mesaj bulunamadı.", { kod: "bulunamadi" });
  return m;
}

// scrub_secret_patterns'ın portal tarafı karşılığı yok; mock yalnız yaygın biçimleri tanır.
const SIR_DESENLERI = [/gh[pousr]_[A-Za-z0-9]{20,}/, /sk-ant-[A-Za-z0-9_-]{10,}/, /tpt_[A-Za-z0-9_-]{10,}/, /AKIA[0-9A-Z]{16}/, /xox[abp]-[A-Za-z0-9-]{10,}/];

function sirVar(metin: string): boolean {
  return SIR_DESENLERI.some((d) => d.test(metin));
}

function durum(k: Kullanici): AsistanDurumu {
  if (asistanMockAyar.statusYok) throw new ApiError(501, BU_FAZDA_YOK);
  const kalan = Math.max(0, asistanMockAyar.kalanSoru);
  void k;
  return {
    etkin: asistanMockAyar.etkin,
    neden: asistanMockAyar.etkin ? null : asistanMockAyar.neden ?? "worker_yok",
    mod: asistanMockAyar.mod,
    varsayilan_model: "claude-haiku-5-5",
    degerlendirme: { durum: "pending", etiket: null },
    paket_commit: "ornek-veri",
    kalan_soru: kalan,
    model_hazir: asistanMockAyar.etkin && asistanMockAyar.mod === "live",
  };
}

/** Çalışırken durdurulan cevaplar → işin kapanacağı an (ms). Core bunları da bekleyen sayar. */
const kapananlar = new Map<string, number>();

function bekleyenKullaniciMesaji(k: Kullanici): MockMesaj | undefined {
  return mesajlar.find(
    (m) => m.kullanici_id === k.id && m.rol === "assistant" && m.tetik === "kullanici" && (m.durum === "pending" || m.durum === "running"),
  );
}

/** Core `_sayac_kontrol` ile aynı: bekleyen yoksa ama durdurulan iş hâlâ kapanıyorsa "kapanıyor" metni. */
function bekleyenVarKontrol(k: Kullanici): void {
  if (bekleyenKullaniciMesaji(k)) throw new ApiError(409, "Yanıt bekleyen bir sorunuz var; bitmesini bekleyin.", { kod: "bekleyen_var" });
  const simdiMs = Date.now();
  for (const [id, son] of kapananlar) {
    if (son <= simdiMs) {
      kapananlar.delete(id);
      continue;
    }
    const m = mesajlar.find((x) => x.id === id);
    if (m && m.kullanici_id === k.id && m.tetik === "kullanici") {
      throw new ApiError(409, "Durdurulan cevap kapanıyor; birkaç saniye sonra yeniden deneyin.", { kod: "bekleyen_var" });
    }
  }
}

function yeniMesaj(s: MockSohbet, k: Kullanici, alan: Partial<MockMesaj>): MockMesaj {
  const sira = mesajlar.filter((m) => m.sohbet_id === s.id).length + 1;
  const m: MockMesaj = {
    id: kimlik("msg"),
    sohbet_id: s.id,
    sira,
    rol: "assistant",
    ust_mesaj_id: null,
    icerik: null,
    cevap: null,
    durum: "pending",
    hata_kodu: null,
    kaynak: null,
    amac: null,
    kip: "soru",
    tetik: "kullanici",
    adim_kodu: "sirada",
    maliyet_usd: null,
    sure_ms: null,
    geri_bildirim: null,
    olusturma: simdi(),
    tamamlanma: null,
    basladi: false,
    kullanici_id: k.id,
    baglam: null,
    oneri_kural_id: null,
    ...alan,
  };
  mesajlar.push(m);
  s.guncelleme = m.olusturma;
  return m;
}

function soruGonder(sohbetId: string, govde: unknown, k: Kullanici): { mesaj_id: string } {
  const s = sohbetBul(sohbetId, k);
  const g = (govde && typeof govde === "object" ? govde : {}) as Record<string, unknown>;
  if (!asistanMockAyar.etkin) throw new ApiError(503, "Asistan şu an kapalı.", { kod: "asistan_kapali" });

  // "Daha ayrıntılı incele": soru ve amaç üst mesajdan türetilir (istemcinin sorusu yok sayılır).
  if (typeof g.ust_mesaj_id === "string") {
    const ust = mesajlar.find((m) => m.id === g.ust_mesaj_id && m.kullanici_id === k.id);
    if (!ust || ust.sohbet_id !== s.id) throw new ApiError(404, "Mesaj bulunamadı.", { kod: "bulunamadi" });
    if (ust.rol !== "assistant" || ust.durum !== "done" || ust.amac === "assistant_deep") {
      throw new ApiError(422, "Bu cevap ayrıntılı incelenemez.", { kod: "gecersiz_istek" });
    }
    if (mesajlar.some((m) => m.ust_mesaj_id === ust.id)) throw new ApiError(409, "Bu cevap zaten ayrıntılı incelendi.", { kod: "zaten_derin" });
    bekleyenVarKontrol(k);
    hizKontrol(2);
    const kok = kokSoru(ust);
    const cocuk = yeniMesaj(s, k, {
      ust_mesaj_id: ust.id,
      amac: "assistant_deep",
      icerik: kok?.icerik ?? null,
      baglam: kok?.baglam ?? null,
      tetik: "kullanici",
    });
    planla(cocuk.id);
    return { mesaj_id: cocuk.id };
  }

  const kip = g.kip === "oneri" ? "oneri" : "soru";
  let soru = typeof g.soru === "string" ? g.soru.trim() : "";
  if (kip === "oneri" && !soru) soru = "Bu ekranda başka ne yapabilirim?";
  if (!soru) throw new ApiError(422, "Soru boş olamaz.", { kod: "gecersiz_istek" });
  if (soru.length > 2000) throw new ApiError(422, "Soru en çok 2000 karakter olabilir.", { kod: "gecersiz_istek" });
  const baglam = g.baglam && typeof g.baglam === "object" ? (g.baglam as Record<string, unknown>) : null;
  const baglamMetni = baglam ? JSON.stringify(baglam) : "";
  if (new TextEncoder().encode(baglamMetni).length > 2048) throw new ApiError(422, "Ekran bağlamı 2 KB'ı aşıyor.", { kod: "gecersiz_istek" });
  if (sirVar(soru) || sirVar(baglamMetni)) {
    throw new ApiError(422, "Soru veya bağlam gizli bilgi (token/parola) içeriyor.", { kod: "sir_icerik" });
  }
  const oneriKuralId = typeof g.oneri_kural_id === "string" ? g.oneri_kural_id : null;
  if (oneriKuralId && asistanMockAyar.gecersizOneriler.includes(oneriKuralId)) {
    throw new ApiError(409, "Öneri artık geçerli değil.", { kod: "oneri_gecersiz" });
  }
  // Sunucu (`oneri_gecerli_mi`) kuralı bağlamdaki ekranla yeniden değerlendirir: rota yoksa ya da
  // kuralın ekranı değilse 409. (Bilinmeyen test kuralları yalnız `gecersizOneriler` ile sınanır.)
  if (oneriKuralId) {
    const kural = MOCK_KURALLAR.find((x) => x.id === oneriKuralId);
    const rota = typeof baglam?.rota_kalibi === "string" ? baglam.rota_kalibi : null;
    if (kural && rota !== kural.ekran) throw new ApiError(409, "Öneri artık geçerli değil.", { kod: "oneri_gecersiz" });
  }
  bekleyenVarKontrol(k);
  hizKontrol(1);

  if (oneriKuralId) s.oneri_kural_id = oneriKuralId;
  if (!s.baslik) s.baslik = soru.slice(0, 60);
  yeniMesaj(s, k, { rol: "user", icerik: soru, durum: "done", kip, adim_kodu: null, baglam, tamamlanma: simdi() });
  const yanit = yeniMesaj(s, k, { kip, icerik: soru, baglam, oneri_kural_id: oneriKuralId ?? s.oneri_kural_id ?? null });
  planla(yanit.id);
  return { mesaj_id: yanit.id };
}

function hizKontrol(maliyet: number): void {
  if (asistanMockAyar.mesgul) throw new ApiError(429, "Asistan şu an meşgul.", { kod: "mesgul" });
  if (asistanMockAyar.butceDoldu) throw new ApiError(402, "Asistan bütçesi doldu.", { kod: "butce_asildi" });
  if (asistanMockAyar.kalanSoru < maliyet) throw new ApiError(429, "Saatlik soru sınırı doldu.", { kod: "hiz_siniri" });
  asistanMockAyar.kalanSoru -= maliyet;
}

function kokSoru(m: MockMesaj): MockMesaj | undefined {
  let ust: MockMesaj | undefined = m;
  while (ust?.ust_mesaj_id) ust = mesajlar.find((x) => x.id === ust!.ust_mesaj_id);
  return ust;
}

const zamanlayicilar = new Map<string, ReturnType<typeof setTimeout>>();

function planla(id: string): void {
  if (!asistanMockAyar.otomatikIsle) return;
  const adimlar: (() => boolean)[] = [() => adimBaslat(id), () => adimArac(id), () => adimBitir(id)];
  const sonraki = (i: number) => {
    const z = setTimeout(() => {
      zamanlayicilar.delete(id);
      if (adimlar[i]() && i + 1 < adimlar.length) sonraki(i + 1);
    }, asistanMockAyar.adimMs);
    zamanlayicilar.set(id, z);
  };
  sonraki(0);
}

/** Testler için: bekleyen mesajı tek seferde sonuna kadar işler (iptal edildiyse hiçbir şey yapmaz). */
export function asistanMockIsle(id: string): void {
  const z = zamanlayicilar.get(id);
  if (z) clearTimeout(z);
  zamanlayicilar.delete(id);
  if (adimBaslat(id) && adimArac(id)) adimBitir(id);
}

/** Testler için: mesajı yalnız `running`'e alır (iptal notu "işlenen kısım ücretlendi" vakası). */
export function asistanMockBaslat(id: string): void {
  adimBaslat(id);
}

/** Testler için: bekleyen mesajı hata koduyla bitirir. */
export function asistanMockHata(id: string, hataKodu: string): void {
  const m = mesajlar.find((x) => x.id === id);
  if (!m || (m.durum !== "pending" && m.durum !== "running")) return;
  m.durum = "error";
  m.hata_kodu = hataKodu;
  m.tamamlanma = simdi();
  mockOlayYayinla({ type: "assistant.answered", id: m.id, data: { mesaj_id: m.id, kullanici_id: m.kullanici_id, durum: "error" } });
}

/** Testler için: bekleyen (pending/running) mesaj kimlikleri. */
export function asistanMockBekleyenler(): string[] {
  return mesajlar.filter((m) => m.durum === "pending" || m.durum === "running").map((m) => m.id);
}

function adimYayinla(m: MockMesaj, adim: string): void {
  m.adim_kodu = adim;
  mockOlayYayinla({ type: "assistant.step", id: m.id, data: { mesaj_id: m.id, kullanici_id: m.kullanici_id, adim_kodu: adim } });
}

function adimBaslat(id: string): boolean {
  const m = mesajlar.find((x) => x.id === id);
  if (!m || m.durum !== "pending") return m?.durum === "running";
  m.durum = "running";
  m.basladi = true;
  adimYayinla(m, "yanitlaniyor");
  return true;
}

function adimArac(id: string): boolean {
  const m = mesajlar.find((x) => x.id === id);
  if (!m || m.durum !== "running") return false;
  adimYayinla(m, aracAdimi(m.icerik ?? ""));
  return true;
}

function aracAdimi(soru: string): string {
  if (/[A-Z][A-Z0-9]+-\d+/.test(soru)) return "jira";
  if (/lint|log|koşu/i.test(soru)) return "ci_log";
  return "urun_kodu";
}

function adimBitir(id: string): boolean {
  const m = mesajlar.find((x) => x.id === id);
  if (!m || m.durum !== "running") return false;
  const { cevap, kaynak, amac } = cevapUret(m);
  m.cevap = cevap;
  m.kaynak = kaynak;
  m.amac = amac;
  m.durum = "done";
  m.adim_kodu = null;
  m.tamamlanma = simdi();
  m.sure_ms = 1800;
  m.maliyet_usd = kaynak === "model" ? (amac === "assistant_deep" ? 0.089 : 0.0045) : null;
  // Otomatik yükseltme (§6.2): Haiku "Emin değil" → ayrı çocuk mesaj, tetik=otomatik.
  const s = sohbetler.find((x) => x.id === m.sohbet_id)!;
  const yukseltilebilir =
    kaynak === "model" &&
    amac === "assistant" &&
    m.kip === "soru" &&
    !cevap.eylem_reddi &&
    cevap.guven_gosterimi === "Emin değil" &&
    !mesajlar.some((x) => x.ust_mesaj_id === m.id);
  // Ön koşul tutmadı (bütçe düşük): çocuk açılmaz, kart "Daha ayrıntılı incele"yi önerir (core flow).
  const onKosulYok = asistanMockAyar.butceDusuk || /bütçe düşük/i.test(m.icerik ?? "");
  const derin = yukseltilebilir && !onKosulYok;
  if (yukseltilebilir && onKosulYok) m.cevap = { ...cevap, derin_onerilir: true };
  mockOlayYayinla({
    type: "assistant.answered",
    id: m.id,
    data: { mesaj_id: m.id, kullanici_id: m.kullanici_id, durum: "done", derin_bekliyor: derin },
  });
  if (derin) {
    const k = { id: m.kullanici_id } as Kullanici;
    const cocuk = yeniMesaj(s, k, { ust_mesaj_id: m.id, amac: "assistant_deep", tetik: "otomatik", icerik: m.icerik, baglam: m.baglam });
    planla(cocuk.id);
  }
  return true;
}

const ORNEK = "ÖRNEK VERİ — hazırlanmış örnek cevap; gerçek asistan cevabı değil.";

function bos(alan: Partial<AsistanCevabi>): AsistanCevabi {
  return {
    cevap_bloklari: [],
    kaynaklar: [],
    yonlendirmeler: [],
    jira_baglantilari: [],
    jira_anahtarlari: [],
    eylem_reddi: false,
    oneriler: [],
    notlar: [],
    ornek_veri: true,
    ...alan,
  };
}

/**
 * Örnek sözlük maddeleri hata durumuna göre ayrılır: 404 için "içerik değişti" demek yanlış açıklamaya
 * yeşil güven çipi düşürürdü. Tanınmayan durumda kaynak gösterilmez, güven "Kısmen" olur.
 */
function sozlukMaddesi(status: number | null): {
  anlam: string;
  yapilacaklar: string[];
  kaynak: CevapKaynagiOgesi | null;
} {
  switch (status) {
    case 409:
      return {
        anlam: "işlem sırasında ekrandaki içeriğin ya da durumun değiştiğini gösterir.",
        yapilacaklar: ["Ekranı yenileyin.", "İçeriği yeniden inceleyip kararınızı yeniden verin."],
        kaynak: { tur: "dokuman", ref: "docs/MIMARI-SOZLESME.md:120", alinti: "409: içerik görüntülendikten sonra değişti", dogrulandi: true },
      };
    case 404:
      return {
        anlam: "istenen kaydın bulunamadığını gösterir: kimlik yanlış olabilir ya da kayıt silinmiş olabilir.",
        yapilacaklar: ["Adresteki kimliği kontrol edin.", "Kaydı listeden yeniden açın."],
        kaynak: { tur: "dokuman", ref: "docs/MIMARI-SOZLESME.md:340", alinti: "bulunamadi | 404, 410 | genel", dogrulandi: true },
      };
    case 403:
      return {
        anlam: "rolünüzün bu işlem için yetkisi olmadığını gösterir.",
        yapilacaklar: ["İşlemi yetkili rolden birine yönlendirin.", "Rolünüzün doğru olduğunu yöneticinize sorun."],
        kaynak: { tur: "dokuman", ref: "docs/MIMARI-SOZLESME.md:339", alinti: "yasak | 403 | genel (`require_role` reddi)", dogrulandi: true },
      };
    default:
      return {
        anlam: "işlemin tamamlanamadığını gösterir; kesin neden bu örnek sözlükte yok.",
        yapilacaklar: ["İşlemi yeniden deneyin.", "Sürerse hatanın ayrıntısıyla asistana yeniden sorun."],
        kaynak: null,
      };
  }
}

function cevapUret(m: MockMesaj): { cevap: AsistanCevabi; kaynak: AsistanMesaji["kaynak"]; amac: AsistanMesaji["amac"] } {
  const soru = m.icerik ?? "";
  const baglam = m.baglam ?? {};
  const sonHata = baglam.son_hata as
    | { gorunen_metin?: string | null; detail?: string; uc?: string | null; status?: number | null; kod?: string | null }
    | undefined;
  const anahtar = /([A-Z][A-Z0-9]+-\d+)/.exec(soru)?.[1];
  const derin = m.amac === "assistant_deep";

  if (m.kip === "oneri") {
    if (asistanMockAyar.mod === "off") {
      return {
        kaynak: "kapali",
        amac: null,
        cevap: bos({ cevap_bloklari: [{ tur: "paragraf", metin: "Ek öneri için canlı model gerekir; kural önerileri Öneriler sekmesinde." }] }),
      };
    }
    const oneriler: AsistanOnerisi[] = [
      {
        baslik: "Kapsam bulgularını gözden geçirin",
        neden: "Açık bulgu kalırsa case üretimi başlamaz (ÖRNEK VERİ).",
        eylem: { tur: "rota", rota: "/gereksinimler", anahtar: null, taslak: null },
      },
    ];
    return {
      kaynak: "model",
      amac: "assistant",
      cevap: bos({
        cevap_bloklari: [{ tur: "paragraf", metin: `${ORNEK} Bu ekranda kural önerilerine ek olarak şunu yapabilirsiniz.` }],
        guven: "orta",
        guven_gosterimi: "Kısmen",
        oneriler,
      }),
    };
  }

  // Asistan denetimi (011 F7): talimat manipülasyonu sorusu modele gitmeden engellenir; rakip
  // firma hakkında soru uyarı notuyla cevaplanır (core'da kararı kod verir; burada örnek).
  if (/önceki (tüm )?talimat|sistem prompt/i.test(soru)) {
    return {
      kaynak: "denetim",
      amac: null,
      cevap: bos({
        cevap_bloklari: [
          { tur: "paragraf", metin: `${ORNEK} Bu soru içerik kontrolünden geçmedi (Talimat manipülasyonu) ve asistana iletilmedi. Sorunuzu iş akışıyla ilgili olarak yeniden yazabilirsiniz.` },
        ],
        denetim: {
          karar: "engelle",
          engellenen: "soru",
          soru: { puan: 8, karar: "engelle", kategoriler: ["prompt_injection"], gerekce: "Sistem talimatlarını açıklatma girişimi.", kaynak: "sim" },
          cevap: null,
        },
      }),
    };
  }
  if (asistanMockAyar.mod !== "off" && /rakip/i.test(soru)) {
    return {
      kaynak: "model",
      amac: derin ? "assistant_deep" : "assistant",
      cevap: bos({
        cevap_bloklari: [{ tur: "paragraf", metin: `${ORNEK} Rakip ürünler hakkında doğrulanmamış karşılaştırma yapmıyorum; kendi ürünümüzün test durumunu anlatabilirim.` }],
        guven: "orta",
        guven_gosterimi: "Genel bilgi",
        notlar: ["Denetim uyarısı: soru rakip firmaya ilişkin (Rekabete aykırı); cevabı dikkatle değerlendirin."],
        denetim: {
          karar: "uyar",
          engellenen: null,
          soru: { puan: 62, karar: "uyar", kategoriler: ["rekabete_aykiri"], gerekce: "Rakip firma hakkında yorum isteniyor.", kaynak: "sim" },
          cevap: { puan: 90, karar: "gec", kategoriler: ["temiz"], gerekce: "Cevap tarafsız.", kaynak: "sim" },
        },
      }),
    };
  }

  // Sözlük: son hata bağlamı + "ne demek/neden" sınıfı (modelsiz, ücretsiz).
  if (!derin && sonHata && /ne demek|neden|hata/i.test(soru)) {
    const metin = sonHata.gorunen_metin || sonHata.detail || "bu hata";
    const madde = sozlukMaddesi(sonHata.status ?? null);
    return {
      kaynak: "sozluk",
      amac: null,
      cevap: bos({
        cevap_bloklari: [
          { tur: "baslik", metin: "Hata açıklaması" },
          { tur: "paragraf", metin: `${ORNEK} "${metin}" mesajı, ${madde.anlam}` },
          { tur: "liste", metin: "Ne yapmalı:", maddeler: madde.yapilacaklar },
        ],
        ...(madde.kaynak
          ? { guven: "yuksek" as const, guven_gosterimi: "Kaynakla doğrulandı" as const, kaynaklar: [madde.kaynak] }
          : { guven: "orta" as const, guven_gosterimi: "Kısmen" as const }),
      }),
    };
  }

  // Şablon: kayıt durumu ve "bugün ne yapmalıyım" (modelsiz).
  if (!derin && (/ne yapmalıyım/i.test(soru) || (anahtar && /neden|durum|nerede|bekliyor/i.test(soru)))) {
    return {
      kaynak: "sablon",
      amac: null,
      cevap: bos({
        cevap_bloklari: anahtar
          ? [
              { tur: "paragraf", metin: `${ORNEK} ${anahtar} PO onayı bekliyor; case üretimi bu kapı geçilince başlar.` },
              { tur: "liste", metin: "Bekleyen kapı:", maddeler: ["PO onayı (sorumlu rol: PO)"] },
            ]
          : [{ tur: "liste", metin: `${ORNEK} Rolünüzün bekleyen işleri:`, maddeler: ["TPD-3: kapsam bulgusu kararı", "TPD-5: case incelemesi"] }],
        guven: "yuksek",
        guven_gosterimi: "Kaynakla doğrulandı",
        kaynaklar: [{ tur: "probe_verisi", ref: "k1", alinti: anahtar ? `${anahtar} · po_bekliyor` : "kuyruk: 2 iş", dogrulandi: true }],
        yonlendirmeler: [{ etiket: "Gereksinimler", rota: "/gereksinimler" }],
        jira_baglantilari: anahtar ? [{ anahtar, url: `http://127.0.0.1:8080/browse/${anahtar}` }] : [],
        jira_anahtarlari: anahtar ? [anahtar] : [],
      }),
    };
  }

  if (asistanMockAyar.mod === "off") {
    return {
      kaynak: "kapali",
      amac: null,
      cevap: bos({
        cevap_bloklari: [
          { tur: "paragraf", metin: "Canlı model kapalı; hata mesajlarını ve gereksinim/iş durumunu sorabilirsiniz." },
          { tur: "liste", metin: "Örnek sorular:", maddeler: ["Az önceki hata ne demek?", "Bugün ne yapmalıyım?", "TPD-3 neden bekliyor?"] },
        ],
      }),
    };
  }

  const amac = derin ? "assistant_deep" : "assistant";

  if (/onayla|reddet|merge et|sil\b|jira'da .*aç|oluştur/i.test(soru)) {
    return {
      kaynak: "model",
      amac,
      cevap: bos({
        cevap_bloklari: [{ tur: "paragraf", metin: `${ORNEK} Asistan işlem yapmaz. Onayı ilgili ekranda siz verirsiniz.` }],
        guven: "yuksek",
        guven_gosterimi: "Kaynakla doğrulandı",
        eylem_reddi: true,
        yonlendirmeler: [{ etiket: "Gereksinimler", rota: "/gereksinimler" }],
        kaynaklar: [{ tur: "urun_kodu", ref: "review-portal/src/pages/CaseReview.tsx:42-44", alinti: "Onayla", dogrulandi: true }],
      }),
    };
  }

  if (!derin && /emin|kısmen/i.test(soru)) {
    return {
      kaynak: "model",
      amac,
      cevap: bos({
        cevap_bloklari: [{ tur: "paragraf", metin: `${ORNEK} Muhtemelen rol kısıtı nedeniyle; kaynakla doğrulanamadı.` }],
        guven: "dusuk",
        guven_gosterimi: "Emin değil",
        kaynaklar: [{ tur: "genel_bilgi", ref: "", alinti: "", dogrulandi: false }],
        notlar: ["Ürün kaynağıyla doğrulanmadı."],
      }),
    };
  }

  const kaynaklar: CevapKaynagiOgesi[] = [
    {
      tur: "urun_kodu",
      ref: "review-portal/src/pages/ScriptDetay.tsx:118-121",
      alinti: 'roller={["engineer"]}',
      dogrulandi: true,
    },
    { tur: "dokuman", ref: "docs/DEMO-AKISI.md:88", alinti: "Kırarak doğrulama yalnızca mühendis rolüne açıktır.", dogrulandi: false },
  ];
  const notlar: string[] = [];
  let guven: GuvenGosterimi = "Kaynakla doğrulandı";
  if (/jira|yorum/i.test(soru) || anahtar) {
    const k = anahtar ?? "TPD-3";
    kaynaklar.push({
      tur: "jira",
      ref: "k2",
      alinti: "Kampanya sınırında 6. adetin bedava olduğu açıkça yazılsın.",
      dogrulandi: true,
      jira: { anahtar: k, tarih: new Date(Date.now() - 2 * 86400_000).toISOString(), url: `http://127.0.0.1:8080/browse/${k}`, yorum: true },
    });
  }
  if (/lint|log|koşu/i.test(soru)) {
    kaynaklar.push({
      tur: "ci_log",
      ref: "k3",
      alinti: "src/e2e/kampanya.spec.ts:14 'page' is declared but never used",
      dogrulandi: true,
      ci: { run_id: "run-0007", kosu_no: "7", satir_bas: 412, satir_bit: 418 },
    });
    if (/jira/i.test(soru)) notlar.push("Jira şu an yanıt vermiyor; cevap Jira kaydı olmadan hazırlandı.");
  }
  if (/genel|flaky/i.test(soru)) {
    guven = "Genel bilgi";
    kaynaklar.splice(0, kaynaklar.length, { tur: "genel_bilgi", ref: "", alinti: "", dogrulandi: false });
  }
  return {
    kaynak: "model",
    amac,
    cevap: bos({
      cevap_bloklari: [
        { tur: "baslik", metin: derin ? "Ayrıntılı inceleme" : "Kısa cevap" },
        { tur: "paragraf", metin: `${ORNEK} Bu düğme yalnızca mühendis rolüne açıktır; diğer rollerde pasif görünür ve üzerine gelince nedenini söyler.` },
        { tur: "kod", metin: '<IslemDugmesi roller={["engineer"]}>Kırarak doğrula</IslemDugmesi>' },
      ],
      guven: guven === "Genel bilgi" ? "orta" : "yuksek",
      guven_gosterimi: guven,
      kaynaklar,
      notlar,
      yonlendirmeler: [{ etiket: "Kod üretimi", rota: "/kod" }],
      jira_baglantilari: kaynaklar
        .filter((x) => x.jira?.url)
        .map((x) => ({ anahtar: x.jira!.anahtar, url: x.jira!.url! })),
    }),
  };
}

// Core ile aynı (api.py `iptal`): kullanıcı mesajı 422; `iptal` idempotent; bitmiş cevap 409 (kodsuz).
function iptal(id: string, k: Kullanici): AsistanMesaji {
  const m = mesajBul(id, k);
  if (m.rol !== "assistant") throw new ApiError(422, "Yalnız asistan cevabı iptal edilebilir.", { kod: "gecersiz_istek" });
  if (m.durum === "done" || m.durum === "error") throw new ApiError(409, "Cevap zaten tamamlandı; iptal edilemez.");
  if (m.durum === "pending" || m.durum === "running") {
    const z = zamanlayicilar.get(id);
    if (z) clearTimeout(z);
    zamanlayicilar.delete(id);
    m.durum = "iptal";
    m.tamamlanma = simdi();
    if (m.basladi) m.maliyet_usd = 0.001;
    // Çalışan iş tur başında durana dek sayılır (core `kullanici_kapanan`); sıradaki iş hemen düşer.
    if (m.basladi && asistanMockAyar.kapanmaMs > 0) kapananlar.set(m.id, Date.now() + asistanMockAyar.kapanmaMs);
    mockOlayYayinla({ type: "assistant.answered", id: m.id, data: { mesaj_id: m.id, kullanici_id: m.kullanici_id, durum: "iptal" } });
  }
  return disaVer(m);
}

function geriBildirim(id: string, govde: unknown, k: Kullanici): void {
  const m = mesajBul(id, k);
  const d = (govde as { deger?: unknown } | null)?.deger;
  if (d !== 1 && d !== -1) throw new ApiError(422, "Geri bildirim -1 ya da 1 olmalı.", { kod: "gecersiz_istek" });
  // Core (api.py `geri_bildirim`) yalnız rolü denetler; durum şartı yoktur.
  if (m.rol !== "assistant") throw new ApiError(422, "Yalnız asistan cevabına geri bildirim verilir.", { kod: "gecersiz_istek" });
  m.geri_bildirim = d;
}

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

/** handlers.ts ROTALAR'ına eklenen asistan uçları; oturum kontrolü çağıranın `girisGerekli`'si. */
export function asistanRotalari(girisGerekli: () => Kullanici): Rota[] {
  const sohbetlerim = (k: Kullanici) =>
    sohbetler
      .filter((s) => s.kullanici_id === k.id && !s.silindi)
      .sort((a, b) => b.guncelleme.localeCompare(a.guncelleme))
      .slice(0, 50)
      .map(({ kullanici_id: _k, silindi: _s, ...geri }) => {
        void _k;
        void _s;
        return geri;
      });
  return [
    ["GET", /^\/assistant\/status$/, () => durum(girisGerekli())],
    ["GET", /^\/assistant\/conversations$/, () => sohbetlerim(girisGerekli())],
    [
      "POST",
      /^\/assistant\/conversations$/,
      (_m, _q, g) => {
        const k = girisGerekli();
        const baslik = (g as { baslik?: unknown } | null)?.baslik;
        const s: MockSohbet = {
          id: kimlik("sohbet"),
          baslik: typeof baslik === "string" && baslik ? baslik.slice(0, 80) : null,
          olusturma: simdi(),
          guncelleme: simdi(),
          oneri_kural_id: null,
          kullanici_id: k.id,
          silindi: false,
        };
        sohbetler.push(s);
        const { kullanici_id: _k, silindi: _s, ...geri } = s;
        void _k;
        void _s;
        return geri;
      },
    ],
    [
      "DELETE",
      /^\/assistant\/conversations\/([^/]+)$/,
      (m) => {
        const s = sohbetBul(decodeURIComponent(m[1]), girisGerekli());
        s.silindi = true;
        return null;
      },
    ],
    [
      "GET",
      /^\/assistant\/conversations\/([^/]+)\/messages$/,
      (m) => {
        const s = sohbetBul(decodeURIComponent(m[1]), girisGerekli());
        return mesajlar.filter((x) => x.sohbet_id === s.id).sort((a, b) => a.sira - b.sira).map(disaVer);
      },
    ],
    ["POST", /^\/assistant\/conversations\/([^/]+)\/messages$/, (m, _q, g) => soruGonder(decodeURIComponent(m[1]), g, girisGerekli())],
    ["GET", /^\/assistant\/messages\/([^/]+)$/, (m) => disaVer(mesajBul(decodeURIComponent(m[1]), girisGerekli()))],
    ["POST", /^\/assistant\/messages\/([^/]+)\/cancel$/, (m) => iptal(decodeURIComponent(m[1]), girisGerekli())],
    ["POST", /^\/assistant\/messages\/([^/]+)\/feedback$/, (m, _q, g) => geriBildirim(decodeURIComponent(m[1]), g, girisGerekli())],
  ];
}

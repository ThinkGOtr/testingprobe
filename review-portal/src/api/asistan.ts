// Portal asistanı istemcisi (AI-ASISTAN-PLANI §9 uçları, §7.2–7.3 cevap biçimi, §8 mesaj).
// Uçlar yalnız çerez oturumuyla çalışır; core sunmuyorsa mock arka uç (api/mock/asistan.ts)
// "ÖRNEK VERİ" etiketli cevap verir. Hata `kod`ları (`bekleyen_var`, `hiz_siniri` …) `ApiError.kod`'da.
import type { Degerlendirme } from "./types";
import { ApiError, istek } from "./http";

/** `GET /assistant/status` (§9). `mod` yalnız rozet kuralı içindir: canlı kipte metin gösterilmez. */
export interface AsistanDurumu {
  etkin: boolean;
  /** `etkin=false` nedeni: `worker_yok`, `maskeleme_kapali`, `kapali` … */
  neden?: string | null;
  mod: "live" | "off";
  /** `assistant` amacının model kimliği (ör. `claude-haiku-5-5`); kip rozeti kısa adını gösterir (013 §7). */
  varsayilan_model?: string | null;
  /** `assistant_deep` amacının model kimliği; core yazmıyorsa derin cevap rozeti yalnız `CANLI` der. */
  derin_model?: string | null;
  degerlendirme?: Degerlendirme | null;
  paket_commit?: string | null;
  /** Kullanıcının bu saat kalan yaklaşık soru hakkı (core `SAATLIK_SORU - saatlik_soru`; günlük sayaç yok). */
  kalan_soru?: number | null;
  /** Model hazır mı (öneri "Başka ne yapabilirim?" ve "Daha ayrıntılı incele" için); yoksa `mod==="live"`. */
  model_hazir?: boolean | null;
}

export interface Sohbet {
  id: string;
  baslik: string | null;
  olusturma: string;
  guncelleme: string;
  oneri_kural_id?: string | null;
}

export type MesajDurumu = "pending" | "running" | "done" | "error" | "iptal";
export type CevapKaynagi = "model" | "sozluk" | "sablon" | "kapali";
export type AsistanAmaci = "assistant" | "assistant_deep";

export type BlokTuru = "baslik" | "paragraf" | "liste" | "kod";

export interface CevapBlogu {
  tur: BlokTuru;
  metin: string;
  maddeler?: string[];
}

export type KaynakTuru = "urun_kodu" | "uygulama_kodu" | "uygulama_verisi" | "probe_verisi" | "jira" | "ci_log" | "dokuman" | "genel_bilgi";

export interface CevapKaynagiOgesi {
  tur: KaynakTuru;
  ref: string;
  alinti: string;
  /** §7.3 deterministik doğrulama sonucu; doğrulanmayan silinmez, soluk gösterilir. */
  dogrulandi?: boolean;
  /** Jira kaynağı: sunucunun kurduğu bağlantı ve yorum tarihi (`issue_url` modele gitmez). */
  jira?: { anahtar: string; tarih?: string | null; url?: string | null; yorum?: boolean } | null;
  /** CI kaynağı: koşu ve satır aralığı. */
  ci?: { run_id: string; kosu_no?: number | string | null; satir_bas?: number | null; satir_bit?: number | null } | null;
}

export interface Yonlendirme {
  etiket: string;
  rota: string;
}

export type GuvenGosterimi = "Kaynakla doğrulandı" | "Kısmen" | "Emin değil" | "Genel bilgi";

/** Model destekli ek öneri (§7.2 `oneriler`); kartı Öneriler şeridi çizer. */
export interface AsistanOnerisi {
  baslik: string;
  neden: string;
  eylem: {
    tur: "rota" | "jira_taslak" | "jira_yorum" | "jira_kaydi" | "bilgi";
    rota: string | null;
    anahtar: string | null;
    taslak: { tur: string; ozet: string; aciklama: string } | null;
    baglanti?: string | null;
  };
}

/** Saklanan ve gösterilen cevap (§7.3 son işlemden geçmiş). */
export interface AsistanCevabi {
  cevap_bloklari: CevapBlogu[];
  guven?: "yuksek" | "orta" | "dusuk";
  guven_gosterimi?: GuvenGosterimi | null;
  kaynaklar: CevapKaynagiOgesi[];
  yonlendirmeler: Yonlendirme[];
  /** Sunucunun kurduğu Jira bağlantıları (yalnız bilinen anahtarlar). */
  jira_baglantilari?: { anahtar: string; url: string }[];
  jira_anahtarlari?: string[];
  eylem_reddi: boolean;
  oneriler?: AsistanOnerisi[];
  /** Cevap içi notlar ("Jira şu an yanıt vermiyor", "log alınamadı", "ürün kaynağıyla doğrulanmadı"). */
  notlar?: string[];
  /** Toparlama ile bitti (güven "Emin değil"). */
  toparlama?: boolean;
  /** §7.3 doğrulama sonucu, `ref` başına (contracts/assistant-schema.md "Saklanan cevap biçimi"). */
  dogrulama?: Record<string, { dogrulandi: boolean; sha256?: string | null }> | null;
  urune_ozgu?: boolean;
  /** Otomatik yükseltme ön koşulu tutmadı (flow.py): kart "Daha ayrıntılı incele"yi önerir (§6.2). */
  derin_onerilir?: boolean;
  /** Mock arka uç cevabı: arayüz "ÖRNEK VERİ" gösterir. */
  ornek_veri?: boolean;
  /** Sunucu niyet sinyali kimlikleri (013 §5.2); kayıt içindir, arayüzde gösterilmez. */
  sinyaller?: string[];
}

export interface AsistanMesaji {
  id: string;
  sohbet_id: string;
  sira: number;
  rol: "user" | "assistant";
  ust_mesaj_id: string | null;
  icerik: string | null;
  cevap: AsistanCevabi | null;
  durum: MesajDurumu;
  hata_kodu: string | null;
  kaynak: CevapKaynagi | null;
  amac: AsistanAmaci | null;
  kip: "soru" | "oneri";
  tetik: "kullanici" | "otomatik";
  maliyet_usd: number | string | null;
  sure_ms: number | null;
  geri_bildirim: -1 | 1 | null;
  olusturma: string;
  tamamlanma: string | null;
  // Core `mesaj_ozeti` adım kodu ve "başladı" bilgisi yazmaz: adım yalnız `assistant.step`
  // olayıyla gelir, başlama `durum === "running"` ile anlaşılır.
}

/** Soru gövdesi (§9). `baglam` ≤ 2 KB (istemci kırpar, sunucu doğrular). */
export interface SoruGovdesi {
  soru?: string;
  baglam?: Record<string, unknown> | null;
  kip?: "soru" | "oneri";
  oneri_kural_id?: string | null;
}

export const SORU_AZAMI = 2000;
export const BAGLAM_AZAMI_BAYT = 2048;

const yol = (s: string) => encodeURIComponent(s);

export const asistanApi = {
  durum: () => istek<AsistanDurumu>("GET", "/assistant/status"),
  sohbetler: () => istek<Sohbet[]>("GET", "/assistant/conversations"),
  sohbetOlustur: (baslik?: string | null) => istek<Sohbet>("POST", "/assistant/conversations", { govde: { baslik: baslik ?? null } }),
  sohbetSil: (id: string) => istek<void>("DELETE", `/assistant/conversations/${yol(id)}`),
  mesajlar: (sohbetId: string) => istek<AsistanMesaji[]>("GET", `/assistant/conversations/${yol(sohbetId)}/messages`),
  soruGonder: (sohbetId: string, govde: SoruGovdesi) =>
    istek<{ mesaj_id: string }>("POST", `/assistant/conversations/${yol(sohbetId)}/messages`, { govde }),
  derinIncele: (sohbetId: string, ustMesajId: string) =>
    istek<{ mesaj_id: string }>("POST", `/assistant/conversations/${yol(sohbetId)}/messages`, { govde: { ust_mesaj_id: ustMesajId } }),
  mesaj: (id: string) => istek<AsistanMesaji>("GET", `/assistant/messages/${yol(id)}`),
  iptal: (id: string) => istek<AsistanMesaji | void>("POST", `/assistant/messages/${yol(id)}/cancel`),
  geriBildirim: (id: string, deger: -1 | 1) => istek<void>("POST", `/assistant/messages/${yol(id)}/feedback`, { govde: { deger } }),
};

/** Kaynağın doğrulama sonucu: kaynak üzerindeki alan, yoksa `cevap.dogrulama[ref]`; bilinmiyorsa undefined. */
export function kaynakDogrulandi(c: Pick<AsistanCevabi, "dogrulama">, k: CevapKaynagiOgesi): boolean | undefined {
  if (typeof k.dogrulandi === "boolean") return k.dogrulandi;
  const d = k.ref ? c.dogrulama?.[k.ref] : undefined;
  return d ? d.dogrulandi : undefined;
}

/**
 * Model kimliğinden kısa ad: `claude-haiku-5-5` → "Haiku 5.5", `claude-sonnet-4-6-20260101` →
 * "Sonnet 4.6", `us.anthropic.claude-opus-5-v1:0` → "Opus 5". Tanınmazsa null (rozet yalnız `CANLI`).
 */
export function modelKisaAdi(model: string | null | undefined): string | null {
  if (!model) return null;
  const m = /(haiku|sonnet|opus)(?:[-_.](\d{1,2})(?!\d))?(?:[-_.](\d{1,2})(?!\d))?/i.exec(model);
  if (!m) return null;
  const aile = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
  const surum = m[2] ? (m[3] ? `${m[2]}.${m[3]}` : m[2]) : "";
  return surum ? `${aile} ${surum}` : aile;
}

export type KipRozetTuru = "canli" | "sablon" | "kapali";

export interface KipRozeti {
  tur: KipRozetTuru;
  /** Görünen rozet metni: `CANLI · Haiku 5.5` / `CANLI` / `ŞABLON` / `MODEL KAPALI`. */
  metin: string;
  /** Açıklama (title + ekran okuyucu metni). */
  aciklama: string;
}

/**
 * Cevap kartının kip rozeti (013 §7, K12). `model` → `CANLI · <kısa ad>` (derin cevapta derin
 * model; status bildirmiyorsa yalnız `CANLI`); `sozluk|sablon` → `ŞABLON`; `kapali` → `MODEL KAPALI`.
 */
export function kipRozeti(
  m: Pick<AsistanMesaji, "kaynak" | "amac">,
  durum?: Pick<AsistanDurumu, "varsayilan_model" | "derin_model"> | null,
): KipRozeti | null {
  switch (m.kaynak) {
    case "model": {
      const ad = modelKisaAdi(m.amac === "assistant_deep" ? durum?.derin_model : durum?.varsayilan_model);
      return {
        tur: "canli",
        metin: ad ? `CANLI · ${ad}` : "CANLI",
        aciklama: m.amac === "assistant_deep" ? "Canlı model cevabı · ayrıntılı inceleme" : "Canlı model cevabı",
      };
    }
    case "sozluk":
      return { tur: "sablon", metin: "ŞABLON", aciklama: "Hazır cevap · hata sözlüğü" };
    case "sablon":
      return { tur: "sablon", metin: "ŞABLON", aciklama: "Hazır cevap · kayıt durumu" };
    case "kapali":
      return { tur: "kapali", metin: "MODEL KAPALI", aciklama: "Hazır cevap · canlı model kapalı" };
    default:
      return null;
  }
}

/** Bitmemiş mesaj (bekleme göstergesi, yoklama). */
export function bekliyor(m: Pick<AsistanMesaji, "durum">): boolean {
  return m.durum === "pending" || m.durum === "running";
}

/** `assistant.step adim_kodu` → kullanıcı metni (sabit sözlük; argüman/soru metni yok, §9). */
export const ADIM_METINLERI: Record<string, string> = {
  sirada: "Sırada bekliyor…",
  yanitlaniyor: "Soru inceleniyor…",
  arac: "Kaynaklar okunuyor…",
  dogrulaniyor: "Kaynaklar doğrulanıyor…",
  baglam: "Ekran bağlamı okunuyor…",
  sozluk: "Hata sözlüğüne bakılıyor…",
  sablon: "Kayıt durumu okunuyor…",
  urun_kodu: "Ürün kodu inceleniyor…",
  dokuman: "Dokümanlar inceleniyor…",
  probe_verisi: "Testing Probe kayıtları okunuyor…",
  uygulama_kodu: "Test edilen uygulamanın kodu inceleniyor…",
  uygulama_verisi: "Test edilen uygulamanın verisi sorgulanıyor…",
  jira: "Jira kaydı okunuyor…",
  ci_log: "CI koşu logu okunuyor…",
  dogrulama: "Kaynaklar doğrulanıyor…",
  toparlama: "Cevap toparlanıyor…",
};

export function adimMetni(kod: string | null | undefined): string {
  if (!kod) return "Soru inceleniyor…";
  return ADIM_METINLERI[kod] ?? "Soru inceleniyor…";
}

/**
 * Mesaj hata kodu (`hata_kodu`) → kullanıcı metni (§11 Durumlar). `butce_asildi` dört kapsamdan
 * (soru başı, kullanıcı, asistan, genel) hangisinin dolduğunu taşımaz: metin ikisini de söyler,
 * "yarın" diye kesinlemez (soru başı bütçe dolduysa hemen yeni soru sorulabilir). Core soru başı
 * kapsamına ayrı kod yazarsa (`soru_butcesi`) o ayrıca karşılanır.
 */
export const MESAJ_HATALARI: Record<string, string> = {
  butce_asildi:
    "Asistan bütçesi doldu. Bu soru için ayrılan bütçe dolduysa soruyu daraltıp yeni soru sorabilirsiniz; günlük bütçe dolduysa yarın yeniden deneyin.",
  soru_butcesi: "Bu soru için ayrılan bütçe doldu; soruyu daraltıp yeni soru sorabilirsiniz.",
  girdi_tavani: "Soru çok geniş. Tek bir ekran, kayıt ya da hata üzerine daraltarak sorun.",
  zaman_asimi: "Cevap zamanında hazırlanamadı (zaman aşımı). Soruyu daraltıp yeniden deneyin.",
  model_hatasi: "Model şu an cevap veremedi. Biraz sonra yeniden deneyin.",
};

export function mesajHataMetni(kod: string | null | undefined): string {
  return (kod && MESAJ_HATALARI[kod]) || "Cevap hazırlanamadı.";
}

/** Yanıt bekleyen soru varken yeni soru (409 bekleyen_var ya da istemcide önceden engellenen). */
export const BEKLEYEN_VAR_METNI = "Yanıt bekleyen bir sorunuz var (bu ya da başka bir sekmede). O cevap gelince yeniden sorun.";

/**
 * Gönderim hatası kodları (`ApiError.kod`). 013: `donduruldu` (429, gövdede `kalan_s`: art arda
 * engellenen istekler sonrası dondurma) ve `kisisel_veri` (422, soruda kart numarası).
 */
export type GonderimHataKodu =
  | "bekleyen_var"
  | "zaten_derin"
  | "hiz_siniri"
  | "mesgul"
  | "butce_asildi"
  | "sir_icerik"
  | "kisisel_veri"
  | "donduruldu"
  | "asistan_kapali"
  | "oneri_gecersiz"
  | "gecersiz_istek"
  | "bulunamadi";

/** Core `DONDURMA_SURE_S` (013 §6.2): gövdede `kalan_s` yoksa istemci bu süreyi varsayar. */
export const DONDURMA_SURE_S = 600;

export const KISISEL_VERI_METNI = "Soru kart numarası gibi kişisel veri içeriyor; çıkarıp yeniden deneyin.";

/** 429 `donduruldu` metni: N = ⌈kalan_s / 60⌉ dk (en az 1). */
export function dondurulduMetni(kalanS: number): string {
  const dk = Math.max(1, Math.ceil((Number.isFinite(kalanS) ? kalanS : DONDURMA_SURE_S) / 60));
  return `Asistan, art arda engellenen istekler nedeniyle ~${dk} dk kullanılamıyor.`;
}

/** 429 `donduruldu` ise kalan saniye (gövdedeki `kalan_s`, yoksa `DONDURMA_SURE_S`); değilse null. */
export function dondurmaKalanS(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.kod !== "donduruldu") return null;
  const k = e.ek.kalan_s;
  return typeof k === "number" && Number.isFinite(k) && k > 0 ? k : DONDURMA_SURE_S;
}

/** Gönderim hatası (`ApiError.kod`) → kullanıcı metni. */
export function gonderimHataMetni(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : "Soru gönderilemedi.";
  switch (e.kod as GonderimHataKodu | undefined) {
    case "bekleyen_var":
      // Core iki gerekçe yazar (api.py `_bekleyen_var`): bekleyen soru (genel metin) ya da az önce
      // durdurulan cevabın işi hâlâ kapanıyor. İkincisinde sunucu metni gösterilir: kullanıcının
      // ekranında bekleyen soru yoktur, "başka sekmede" demek yanıltır.
      return e.detail && /kapan/i.test(e.detail) ? e.detail : BEKLEYEN_VAR_METNI;
    case "zaten_derin":
      return "Bu cevap zaten ayrıntılı incelendi.";
    case "hiz_siniri":
      // Sunucu kovayı (saatlik soru, sık sohbet açma, öneri sorusu dakikalık) kendi metniyle söyler.
      return e.detail?.trim() || "Çok sık soru gönderildi. Biraz sonra yeniden deneyin.";
    case "mesgul":
      return "Asistan şu an meşgul. Birkaç saniye sonra yeniden deneyin.";
    case "butce_asildi":
      // Core hangi kapsamın (soru başı / kullanıcı / asistan / genel) dolduğunu kendi metniyle söyler.
      return e.detail?.trim() || MESAJ_HATALARI.butce_asildi;
    case "sir_icerik":
      return "Soru veya bağlam parola/token benzeri bir değer içeriyor. O kısmı çıkarıp yeniden sorun.";
    case "kisisel_veri":
      return KISISEL_VERI_METNI;
    case "donduruldu":
      return dondurulduMetni(dondurmaKalanS(e) ?? DONDURMA_SURE_S);
    case "asistan_kapali":
      return "Asistan şu an kapalı.";
    case "oneri_gecersiz":
      return "Bu öneri artık geçerli değil (ekrandaki durum değişti); öneriler yenilendi.";
    default:
      return e.detail;
  }
}

/** `etkin=false` nedeni → kullanıcı metni. */
export function kapaliNedeni(neden: string | null | undefined): string {
  switch (neden) {
    case "worker_yok":
      return "Asistan şu an çalışmıyor: arka plan işleyicisi yanıt vermiyor.";
    case "maskeleme_kapali":
      return "Müşteri verisi kurulumunda kişisel veri maskeleme kapalı olduğu için asistan kapalı.";
    default:
      return "Asistan bu kurulumda kapalı.";
  }
}

/** Bağlam nesnesini 2 KB'a sığdırır: önce uzun metinler kırpılır, sonra isteğe bağlı alanlar düşer. */
export function baglamiSigdir(baglam: Record<string, unknown>, azami = BAGLAM_AZAMI_BAYT): Record<string, unknown> {
  const boyut = (o: unknown) => new TextEncoder().encode(JSON.stringify(o)).length;
  if (boyut(baglam) <= azami) return baglam;
  const kirp = (o: unknown, sinir: number): unknown => {
    if (typeof o === "string") return o.length > sinir ? `${o.slice(0, sinir)}…` : o;
    if (Array.isArray(o)) return o.map((x) => kirp(x, sinir));
    if (o && typeof o === "object") return Object.fromEntries(Object.entries(o).map(([k, v]) => [k, kirp(v, sinir)]));
    return o;
  };
  for (const sinir of [200, 120, 60]) {
    const k = kirp(baglam, sinir) as Record<string, unknown>;
    if (boyut(k) <= azami) return k;
  }
  const geri = { ...(kirp(baglam, 60) as Record<string, unknown>) };
  for (const alan of ["secili_eleman", "son_hata", "oneri"]) {
    delete geri[alan];
    if (boyut(geri) <= azami) return geri;
  }
  return { rota_kalibi: baglam.rota_kalibi ?? null };
}

// ------------------------------------------------------------------ Öneri düğmesi (§17, uç 10–11)

/** Kural kartının eylem türü (§17.2). `bilgi` düğmesizdir ("Neden? Sor" her kartta var). */
export type OneriEylemTuru = "rota" | "jira_taslak" | "jira_yorum" | "jira_kaydi" | "bilgi";

/** Jira taslağı: düz metin; kullanıcı kopyalar, kaydı kendisi açar (İlke I). */
export interface OneriTaslagi {
  proje?: string | null;
  /** Task | Bug | Story | yorum */
  tur: string;
  ozet: string;
  aciklama: string;
  etiketler?: string[];
}

/** Kartın eylemi. `baglanti`'yı yalnız sunucu kurar (§17.4); taslak metni URL'e konmaz. */
export interface OneriEylemi {
  tur: OneriEylemTuru;
  /** `rota`: iç portal yolu (`:id` sunucuda doldurulmuş). */
  rota?: string | null;
  /** Sayfa içi bölüm (ör. `bulgular`, `po-onay`). */
  capa?: string | null;
  anahtar?: string | null;
  taslak?: OneriTaslagi | null;
  baglanti?: string | null;
  /** "Proje: TPD, Tür: Task seçin; metni yapıştırın." */
  adim_notu?: string | null;
  /** "Bu bir öneridir; kaydı siz açarsınız." */
  not?: string | null;
  /** Simülatörde kayıt oluşturma sayfası yok: "Demo Jira'sında kayıt oluşturma sayfası yok". */
  baglanti_yok_nedeni?: string | null;
}

export interface KuralOnerisi {
  kural_id: string;
  baslik: string;
  neden: string;
  /** "Açıklamayı göster" (model kapalı) uzun metni. */
  aciklama?: string | null;
  oncelik: number;
  eylem: OneriEylemi;
}

/** "Yaptım" ile bastırılan kural: kartın yerinde "{kisi} yaptım dedi · TPD-12 · 2 sa önce". */
export interface BastirilanOneri {
  kural_id: string;
  baslik: string;
  kisi: string;
  jira_anahtari?: string | null;
  zaman: string;
}

/** `GET /assistant/suggestions` gövdesi. */
export interface OneriListesi {
  oneriler: KuralOnerisi[];
  /** false: bu (rota × rol) için kural yok → düğme gizli. */
  ekranda_kural_var: boolean;
  bastirilan: BastirilanOneri[];
  /** "Diğer ekranlarda sizi bekleyen N iş" (rozete sayılmaz); henüz hesaplanmıyorsa null. */
  diger_ekranlar: { sayi: number; rota?: string | null } | null;
  hesaplandi: string;
  rota_kalibi?: string | null;
}

export interface OneriSorgusu {
  /** Gerçek yol ya da kalıp; sunucu `rotalar.json` kalıbına indirger. */
  rota: string;
  varlik_tur?: string | null;
  varlik_id?: string | null;
}

/** Gizle (-1) / Faydalı (1) / Yaptım (2). */
export type OneriGeriBildirimDegeri = -1 | 1 | 2;

export interface OneriGeriBildirimGovdesi {
  deger: OneriGeriBildirimDegeri;
  varlik_id?: string | null;
  jira_anahtari?: string | null;
}

/** "Yaptım" alanındaki isteğe bağlı Jira anahtarı (sunucu aynı regex'le doğrular). */
export const JIRA_ANAHTARI = /^[A-Z][A-Z0-9]+-\d+$/;

export const oneriApi = {
  liste: (s: OneriSorgusu) =>
    istek<OneriListesi>("GET", "/assistant/suggestions", {
      sorgu: { rota: s.rota, varlik_tur: s.varlik_tur ?? null, varlik_id: s.varlik_id ?? null },
    }),
  geriBildirim: (kuralId: string, govde: OneriGeriBildirimGovdesi) =>
    istek<unknown>("POST", `/assistant/suggestions/${yol(kuralId)}/feedback`, { govde }),
};

/** Öneri geri bildirimi hatası → kullanıcı metni. */
export function oneriHataMetni(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : "İşlem yapılamadı.";
  if (e.status === 429) return "Çok sık istek gönderildi; biraz sonra yeniden deneyin.";
  if (e.status === 404) return "Bu kayıt artık bulunamıyor ya da rolünüze kapalı.";
  return e.detail;
}

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
  varsayilan_model?: string | null;
  degerlendirme?: Degerlendirme | null;
  paket_commit?: string | null;
  /** Kullanıcının bugün kalan yaklaşık soru hakkı. */
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
  /** Mock arka uç cevabı: arayüz "ÖRNEK VERİ" gösterir. */
  ornek_veri?: boolean;
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
  /** Son `assistant.step` adımı (sayfa yenilenince bekleyen mesajın adımı). */
  adim_kodu?: string | null;
  maliyet_usd: number | string | null;
  sure_ms: number | null;
  geri_bildirim: -1 | 1 | null;
  olusturma: string;
  tamamlanma: string | null;
  /** Mesaj işlenmeye başladı mı (`running` görülmüşse); iptal notu için. */
  basladi?: boolean;
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

/** Mesaj hata kodu (`hata_kodu`) → kullanıcı metni (§11 Durumlar). */
export const MESAJ_HATALARI: Record<string, string> = {
  butce_asildi: "Bugünkü asistan bütçesi doldu; yarın yeniden deneyin.",
  girdi_tavani: "Soru çok geniş. Tek bir ekran, kayıt ya da hata üzerine daraltarak sorun.",
  zaman_asimi: "Cevap zamanında hazırlanamadı (zaman aşımı). Soruyu daraltıp yeniden deneyin.",
  model_hatasi: "Model şu an cevap veremedi. Biraz sonra yeniden deneyin.",
};

export function mesajHataMetni(kod: string | null | undefined): string {
  return (kod && MESAJ_HATALARI[kod]) || "Cevap hazırlanamadı.";
}

/** Gönderim hatası (`ApiError.kod`) → kullanıcı metni. */
export function gonderimHataMetni(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : "Soru gönderilemedi.";
  switch (e.kod) {
    case "bekleyen_var":
      return "Başka bir sekmede yanıt bekleyen sorunuz var. O cevap gelince yeniden sorun.";
    case "zaten_derin":
      return "Bu cevap zaten ayrıntılı incelendi.";
    case "hiz_siniri":
      return "Saatlik soru sınırına ulaştınız. Biraz sonra yeniden deneyin.";
    case "mesgul":
      return "Asistan şu an meşgul. Birkaç saniye sonra yeniden deneyin.";
    case "butce_asildi":
      return MESAJ_HATALARI.butce_asildi;
    case "sir_icerik":
      return "Soru veya bağlam parola/token benzeri bir değer içeriyor. O kısmı çıkarıp yeniden sorun.";
    case "asistan_kapali":
      return "Asistan şu an kapalı.";
    case "oneri_gecersiz":
      return "Bu öneri artık geçerli değil (ekrandaki durum değişti). Öneriler sekmesini yenileyin.";
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

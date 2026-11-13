// Mock arka uç: Öneri düğmesi uçları (AI-ASISTAN-PLANI §9 uç 10–11, §17). Gerçek uç gibi modelsizdir:
// kural fixture'ları (rules/assistant/oneriler.yaml'ın örnek veri karşılığı; metinler aynı) mock
// verisinin olgularıyla değerlendirilir. "Yaptım" (2) o kuralı o varlık aynı durumdayken tüm rollerde,
// "Gizle" (-1) yalnız o kullanıcı için bastırır. `baglanti`'yı yalnız bu "sunucu" kurar (§17.4):
// jira-sim gezinme adresi bilinen anahtar için; kayıt oluşturma sayfası simülatörde yok.
import { IZINLER } from "../../lib/yetki";
import type { AsistanKuleOlcumu, MaliyetGrubu } from "../../components/asistan/OnerilerOlcumKarti";
import { ApiError, BU_FAZDA_YOK } from "../http";
import { JIRA_ANAHTARI, type BastirilanOneri, type KuralOnerisi, type OneriEylemi, type OneriListesi } from "../asistan";
import type { Kullanici, Rol } from "../types";
import { ekranBaglamiCikar } from "../../lib/ekranBaglami";
import type { MockVeri } from "./fixtures";

/** Mock davranış ayarları (testler değiştirir). */
export interface OneriMockAyar {
  /** false: `TP_ASISTAN_ONERI=0` gibi — iki uç da 404 `bulunamadi`. */
  etkin: boolean;
  /** true: uç yokmuş gibi 501 (canlı derlemede "bu fazda yok"). */
  ucYok: boolean;
  /** true: liste ucu 429 `hiz_siniri` döner. */
  hizSiniri: boolean;
  /** Genel günlük model bütçesi kullanımı (Kontrol Kulesi kuralı). */
  butceOrani: number;
}

function ilkAyar(): OneriMockAyar {
  return { etkin: true, ucYok: false, hizSiniri: false, butceOrani: 0.42 };
}

export const oneriMockAyar: OneriMockAyar = ilkAyar();

export function oneriMockAyarla(d: Partial<OneriMockAyar>): void {
  Object.assign(oneriMockAyar, d);
}

/** Jira simülatörünün tarayıcıdan açılan gezinme adresi (fixtures.ts JIRA ile aynı). */
const JIRA_GEZINME = "http://127.0.0.1:8090/browse";
const JIRA_PROJE = "TPD";
const UYARI_NOTU = "Bu bir öneridir; kaydı siz açarsınız.";
const SIM_BAGLANTI_YOK = "Demo Jira'sında kayıt oluşturma sayfası yok";

type Olgu = Record<string, string | number | boolean | null | undefined>;

interface Taslak {
  tur: string;
  ozet: string;
  aciklama: string;
  etiketler: string[];
}

/** rules/assistant/jira-taslaklari.yaml (aynı metinler). */
const TASLAKLAR: Record<string, Taslak> = {
  "po-hatirlatma": {
    tur: "yorum",
    ozet: "",
    aciklama:
      "Merhaba, {jira_key} kaydının PO onayı {po_bekleme_gun} gündür bekliyor.\nCase üretimi PO onayından sonra başlayabiliyor. Uygunsanız güncel içeriği gözden geçirip onayınızı verebilir misiniz?\nDeğişiklik gerekiyorsa lütfen bu kayda yorum olarak yazın.",
    etiketler: [],
  },
  "ac-eksik": {
    tur: "yorum",
    ozet: "",
    aciklama:
      "Merhaba, {jira_key} kaydında kabul kriterleri eksik görünüyor.\nKabul kriterleri olmadan test case'leri üretilemiyor. Beklenen davranışı ölçülebilir kriterler olarak (ör. tutar, sınır, mesaj) ekleyebilir misiniz?\nKriterler eklenince gereksinim yeniden incelenecek.",
    etiketler: [],
  },
  "flaky-task": {
    tur: "Task",
    ozet: "Kararsız (flaky) test incelenmeli",
    aciklama:
      "Bir otomasyon testi son 10 koşuda {flaky_tekrar} kez kararsız sonuç verdi (aynı kodla bazen geçti, bazen kırmızı oldu).\nİstenen: kararsızlığın nedenini (zamanlama, test verisi, ortam ya da sıralama bağımlılığı) bulmak ve kalıcı olarak gidermek.\nKabul: test aynı ortamda art arda tekrarlarda tutarlı sonuç verir.\nKaynak: (test adını ve Testing Probe hata kimliğini buraya ekleyin); kanıtlar ve koşu geçmişi hata detay ekranındadır.",
    etiketler: ["flaky", "otomasyon"],
  },
  "ortam-hatasi-task": {
    tur: "Task",
    ozet: "CI ortam hatası testlerin koşmasını engelliyor",
    aciklama:
      "Son CI koşusu testler çalışmadan ortam hatasıyla bitti; bu koşunun test sonucu yok.\nİstenen: başarısız adımın (ör. kurulum, lint ya da sağlık yoklaması) nedenini bulmak ve düzeltmek.\nKabul: yeni bir koşuda testler çalışır ve sonuç üretir.\nKaynak: (Testing Probe koşu numarasını buraya ekleyin); adım özetleri ve log koşu detay ekranındadır.",
    etiketler: ["ci", "ortam"],
  },
  "test-verisi-task": {
    tur: "Task",
    ozet: "Test verisi ön koşulu sağlanmalı",
    aciklama:
      "Bir otomasyon testi, ön koşul verisi ortamda olmadığı ya da beklenenden farklı olduğu için başarısız oldu (triage sınıfı: test verisi).\nİstenen: testin ihtiyaç duyduğu veriyi test ortamında hazırlamak ya da veri kurulumunu düzeltmek.\nKabul: test aynı ortamda veri hatası olmadan koşar.\nKaynak: (test adını ve Testing Probe hata kimliğini buraya ekleyin); kanıtlar hata detay ekranındadır.",
    etiketler: ["test-verisi"],
  },
};

type KuralEylemi =
  | { tur: "rota"; rota: string; capa?: string; id_olgusu?: string }
  | { tur: "jira_taslak" | "jira_yorum"; sablon: string }
  | { tur: "jira_kaydi" }
  | { tur: "bilgi" };

/** Kural fixture'ı: rules/assistant/oneriler.yaml'ın örnek veri karşılığı (koşul TS işlevi). */
export interface MockKural {
  id: string;
  ekran: string;
  roller: Rol[];
  kosul: (o: Olgu) => boolean;
  oncelik: number;
  baslik: string;
  neden: string;
  eylem: KuralEylemi;
  aciklama: string;
  tekrar_saat?: number;
}

const var_ = (v: unknown) => v !== null && v !== undefined && v !== "";

export const MOCK_KURALLAR: MockKural[] = [
  {
    id: "gereksinim-bulgu-karari",
    ekran: "/gereksinimler/:id",
    roller: ["analyst"],
    kosul: (o) => o.durum === "findings_open" && Number(o.acik_bulgu_sayisi) >= 1,
    oncelik: 90,
    baslik: "{acik_bulgu_sayisi} tutarlılık bulgusu kararınızı bekliyor",
    neden: "Doküman bulgular kararlaştırılmadan finalize edilemez; PO onayı ve case üretimi bu adımı bekler.",
    eylem: { tur: "rota", rota: "/gereksinimler/:id", capa: "bulgular" },
    aciklama:
      'Tutarlılık denetimi dokümanı kodla ve veriyle karşılaştırdı ve kanıtı doğrulanmış bulgular buldu. Her bulgu için karar verin: dokümanı düzeltin, kod hatası olarak işaretleyin ya da farkı gerekçesiyle kabul edin. Bütün bulgular kararlaşmadan doküman "son hal" olmaz; PO onayı ve case üretimi bu yüzden bekler.',
  },
  {
    id: "gereksinim-ac-eksik-jira",
    ekran: "/gereksinimler/:id",
    roller: ["analyst"],
    kosul: (o) => o.ac_eksik === true && var_(o.jira_key),
    oncelik: 85,
    baslik: "Kabul kriteri eksik; story kaynağında güncellenmeli",
    neden: "Kabul kriteri olmayan gereksinimden case üretilmez; story Jira'da tamamlanmadıkça akış ilerlemez.",
    eylem: { tur: "jira_yorum", sablon: "ac-eksik" },
    aciklama:
      "Case'ler kabul kriterlerinden üretilir ve kriterleri eksik gereksinim case üretimine gönderilmez. Kriterlerin sahibi story'yi yazan taraftır; Jira kaydına kriterlerin tamamlanmasını isteyen bir yorum yazın. Story güncellenince gereksinim yeniden senkronize edilip incelemeye alınır.",
  },
  {
    id: "gereksinim-ac-eksik",
    ekran: "/gereksinimler/:id",
    roller: ["analyst"],
    kosul: (o) => o.ac_eksik === true && !var_(o.jira_key),
    oncelik: 85,
    baslik: "Kabul kriteri eksik; story kaynağında güncellenmeli",
    neden: "Kabul kriteri olmayan gereksinimden case üretilmez; metin kaynağında tamamlanmadıkça akış ilerlemez.",
    eylem: { tur: "bilgi" },
    aciklama:
      "Bu gereksinimin Jira kaydı yok (serbest metinle girilmiş). Kabul kriterleri metnin kaynağında tamamlanmalı ve gereksinim güncel metinle yeniden girilmelidir; kriterler olmadan case üretimi başlatılamaz.",
  },
  {
    id: "gereksinim-po-hatirlatma-jira",
    ekran: "/gereksinimler/:id",
    roller: ["analyst"],
    kosul: (o) => o.durum === "pending_po" && Number(o.po_bekleme_saat) >= 24 && o.po_kanal === "jira" && var_(o.jira_key),
    oncelik: 80,
    baslik: "PO onayı {po_bekleme_gun} gündür bekliyor; hatırlatın",
    neden: "Case üretimi PO onayı olmadan başlamaz. Bekleme demo takvimini kaydırır; PO'ya Jira'da hatırlatın.",
    eylem: { tur: "jira_yorum", sablon: "po-hatirlatma" },
    aciklama:
      "Gereksinim PO onayında ve PO onayı Jira kanalından bekleniyor (tp-po-approved etiketi). Onay gelmeden case üretimi başlatılamaz (insan onay kapısı). Jira kaydına kısa bir hatırlatma yorumu yazın; PO etiketi koyunca durum kendiliğinden güncellenir.",
    tekrar_saat: 24,
  },
  {
    id: "gereksinim-po-bekliyor-portal",
    ekran: "/gereksinimler/:id",
    roller: ["analyst"],
    kosul: (o) => o.durum === "pending_po" && Number(o.po_bekleme_saat) >= 24 && o.po_kanal === "portal",
    oncelik: 80,
    baslik: "PO onayı {po_bekleme_gun} gündür bekliyor; onay portalda (serbest metin)",
    neden: "Case üretimi PO onayı olmadan başlamaz. Serbest metin gereksinimde onay portalda verilir; PO'ya ekrana bakmasını hatırlatın.",
    eylem: { tur: "bilgi" },
    aciklama:
      "Serbest metin gereksinim PO onayında; Jira kaydı olmadığı için onay portaldan bekleniyor. Onay gelmeden case üretimi başlatılamaz. PO bu gereksinimin detay ekranında onay bölümünü görür; kendisine ekranın yolunu iletin.",
    tekrar_saat: 24,
  },
  {
    id: "gereksinim-po-onayi-portal",
    ekran: "/gereksinimler/:id",
    roller: ["po"],
    kosul: (o) => o.durum === "pending_po" && o.po_kanal === "portal",
    oncelik: 95,
    baslik: "Onayınız bekleniyor; case üretimi buna bağlı",
    neden: "Testçi case üretimini ancak sizin onayınızdan sonra başlatabilir; onay içeriğin bu hâline bağlanır.",
    eylem: { tur: "rota", rota: "/gereksinimler/:id", capa: "po-onay" },
    aciklama:
      "Serbest metin gereksinimin dokümanı son hâline geldi ve onayınızı bekliyor; Jira kaydı olmadığı için onay portalda verilir. Onay, gördüğünüz içeriğe bağlanır; içerik sonradan değişirse onay yenilenmelidir. Onayınızdan sonra Testçi case üretimini başlatır.",
  },
  {
    id: "gereksinim-po-onayi-jira",
    ekran: "/gereksinimler/:id",
    roller: ["po"],
    kosul: (o) => o.durum === "pending_po" && o.po_kanal === "jira" && var_(o.jira_key),
    oncelik: 95,
    baslik: "Onayınız bekleniyor; case üretimi buna bağlı",
    neden: "Testçi case üretimini ancak sizin onayınızdan sonra başlatabilir; bu gereksinimde onay Jira'dan verilir.",
    eylem: { tur: "jira_kaydi" },
    aciklama:
      "Bu gereksinimde PO onayı Jira kanalından alınır: Jira kaydına tp-po-approved etiketini koyun. Testing Probe etiketi kendi hesabınızdan gelen teyitle tanır ve durumu günceller; portalda onay düğmesi yoktur.",
  },
  {
    id: "gereksinim-case-uret",
    ekran: "/gereksinimler/:id",
    roller: ["tester"],
    kosul: (o) => o.durum === "po_approved" && o.ac_eksik === false,
    oncelik: 90,
    baslik: "PO onayladı; case üretimini başlatın",
    neden: "Onaylı içerikten case üretilmeden inceleme, yayın ve otomasyon adımları başlayamaz.",
    eylem: { tur: "rota", rota: "/gereksinimler/:id", capa: "case-uret" },
    aciklama:
      "PO gereksinimin bu hâlini onayladı. Case üretimi yalnızca onaylı içerikten yapılır; üretim bitince case'ler inceleme ekranına düşer ve kararınızı bekler; Analist son onayı verir.",
  },
  {
    id: "gereksinim-basarisiz",
    ekran: "/gereksinimler/:id",
    roller: ["analyst"],
    kosul: (o) => o.durum === "failed",
    oncelik: 70,
    baslik: "Son işlem başarısız; nedenini sorun",
    neden: "Gereksinim hata durumunda kaldıkça inceleme ve case üretimi ilerlemez.",
    eylem: { tur: "bilgi" },
    aciklama:
      'Bu gereksinimde son çalışan iş (inceleme ya da case üretimi) hatayla bitti. Ekrandaki hata mesajına ve iş geçmişine bakın; "Neden? Sor" ile asistana nedenini sorabilirsiniz. Sorun giderilince işlem yeniden başlatılabilir.',
  },
  {
    id: "case-inceleme-bekliyor",
    ekran: "/gereksinimler/:id/caseler",
    roller: ["tester"],
    kosul: (o) => Number(o.inceleme_bekleyen_case) >= 1,
    oncelik: 90,
    baslik: "{inceleme_bekleyen_case} case kararınızı bekliyor",
    neden: "Kararınız verilmeyen case Analist'in son onayına gidemez; yayın ve otomasyon bekler.",
    eylem: { tur: "rota", rota: "/gereksinimler/:id/caseler" },
    aciklama:
      "Üretilen case'ler taslak durumunda. Her case'i kabul edin, düzelterek kabul edin ya da gerekçesiyle reddedin. Kabul edilen case'ler Analist'in son onayına gider; yayın ve otomasyon yalnızca son onaylı case'lerle yapılır.",
  },
  {
    id: "case-son-onay-bekliyor",
    ekran: "/gereksinimler/:id/caseler",
    roller: ["analyst"],
    kosul: (o) => Number(o.son_onay_bekleyen_case) >= 1,
    oncelik: 90,
    baslik: "{son_onay_bekleyen_case} case son onayınızı bekliyor",
    neden: "Son onay verilmeyen case yayımlanamaz ve otomasyona geçemez.",
    eylem: { tur: "rota", rota: "/gereksinimler/:id/caseler" },
    aciklama:
      "Testçi bu case'leri kabul etti; onaya hazır durumdalar. Her case'i onaylayın ya da gerekçesiyle Testçi'ye geri gönderin. Yalnızca onayladığınız case'ler yayımlanabilir.",
  },
  {
    id: "case-yayina-hazir",
    ekran: "/gereksinimler/:id/caseler",
    roller: ["tester"],
    kosul: (o) =>
      o.durum === "cases_ready" && Number(o.inceleme_bekleyen_case) === 0 && Number(o.son_onay_bekleyen_case ?? 0) === 0 && Number(o.onayli_case) >= 1,
    oncelik: 85,
    baslik: "İnceleme tamam; yayına hazır",
    neden: "Onaylı case'ler yayımlanınca test yönetimine geçer ve otomasyon üretimi başlayabilir.",
    eylem: { tur: "rota", rota: "/gereksinimler/:id/yayin" },
    aciklama:
      "Bu gereksinimin bütün case'leri kararlaştırıldı. Yayın ekranında onaylı case'leri seçip yayımlayın; yayın Testing Probe'un kendi onaylı hattıyla yapılır.",
  },
  {
    id: "case-inceleme-analistte",
    ekran: "/gereksinimler/:id/caseler",
    roller: ["tester"],
    kosul: (o) => Number(o.son_onay_bekleyen_case) >= 1,
    oncelik: 40,
    baslik: "{son_onay_bekleyen_case} case Analist'in son onayında",
    neden: "Son onayı Analist verir; onaylanan case'leri yayımlayabilirsiniz.",
    eylem: { tur: "bilgi" },
    aciklama:
      "Kabul ettiğiniz case'ler Analist'in son onayını bekliyor. Analist onaylarsa yayın ekranından yayımlayabilirsiniz; geri gönderirse case gerekçesiyle taslağa döner.",
  },
  {
    id: "script-kirarak-dogrula",
    ekran: "/kod/:id",
    roller: ["engineer"],
    kosul: (o) => o.durum === "pr_open" && ["not_started", "weak", "failed"].includes(String(o.kirarak_dogrulama)),
    oncelik: 90,
    baslik: "Merge öncesi kırarak doğrulayın (yeşil→kırmızı→yeşil)",
    neden: "Kırarak doğrulanmamış test, hatayı yakalayıp yakalamadığı bilinmeden ana dala girer.",
    eylem: { tur: "rota", rota: "/kod/:id", capa: "kirarak-dogrula" },
    aciklama:
      "Kırarak doğrulama, testi önce yeşilde, sonra uygulama bilinçli olarak bozulmuşken kırmızıda, sonra yeniden yeşilde koşturur. Böylece testin gerçekten hatayı yakaladığı kanıtlanır. Zayıf ya da başarısız sonuçta merge açık insan kabulü ister.",
  },
  {
    id: "script-merge-karari",
    ekran: "/kod/:id",
    roller: ["engineer"],
    kosul: (o) => o.durum === "pr_open" && o.kirarak_dogrulama === "passed",
    oncelik: 85,
    baslik: "PR merge kararınızı bekliyor",
    neden: "Doğrulanmış test merge edilmeden gece koşularına ve regresyon setine girmez.",
    eylem: { tur: "rota", rota: "/kod/:id", capa: "pr" },
    aciklama: "Script'in PR'ı açık ve kırarak doğrulama geçti. Değişikliği inceleyip merge kararını verin; merge yalnızca Automation Engineer onayıyla yapılır.",
  },
  {
    id: "script-insana-dustu",
    ekran: "/kod/:id",
    roller: ["engineer"],
    kosul: (o) => o.durum === "blocked" && o.defect_adayi === false,
    oncelik: 80,
    baslik: "Üretim insana düştü; nedenini sorun",
    neden: "Script üretimi otomatik olarak ilerleyemedi; insan incelemesi olmadan PR açılmaz.",
    eylem: { tur: "rota", rota: "/kod" },
    aciklama:
      'Script üretimi doğrulama ya da yerel kontrol adımında takıldı ve insana bırakıldı. Ekrandaki sınıfa (locator, derleme, ortam) bakın; nedeni giderdiyseniz Kod listesinde bu kaydın satırındaki "Yeniden üret" ile aynı onaylı case için kodu yeniden üretin. "Neden? Sor" ile asistandan ayrıntı isteyebilirsiniz.',
  },
  {
    id: "kosu-ortam-hatasi-task",
    ekran: "/kosular/:id",
    roller: ["engineer"],
    kosul: (o) => o.ci_sonuc === "error",
    oncelik: 85,
    baslik: "Testler koşmadı: CI ortam hatası",
    neden: "Ortam hatasında test sonucu yoktur; düzeltilmezse sonraki koşular da aynı yerde durur.",
    eylem: { tur: "jira_taslak", sablon: "ortam-hatasi-task" },
    aciklama:
      "Koşu, testler çalışmadan altyapı hatasıyla bitti (ör. lint, kurulum ya da sağlık yoklaması). Koşu detayındaki başarısız adıma bakın; kalıcı bir sorunsa takip için bir görev kaydı açın.",
  },
  {
    id: "kosu-ortam-hatasi-bilgi",
    ekran: "/kosular/:id",
    roller: ["admin"],
    kosul: (o) => o.ci_sonuc === "error",
    oncelik: 60,
    baslik: "Koşu ortam hatasıyla bitti; mühendis inceliyor",
    neden: "Bu koşunun test sonucu yok; demo öncesi güncel ve başarılı bir koşu gerekir.",
    eylem: { tur: "bilgi" },
    aciklama: "Koşu testler çalışmadan bitti. İnceleme Automation Engineer rolündedir; düzeltildikten sonra yeni bir koşu tetiklenebilir.",
  },
  {
    id: "hata-bakim-onarim",
    ekran: "/hatalar/:id",
    roller: ["engineer"],
    // 012 §4.4: test beklentisi farkında (alt tür `beklenti`) locator onarımı önerilmez.
    kosul: (o) => o.hata_sinifi === "test_maintenance" && o.onarim_durumu === "none" && o.beklenti_farki === false,
    oncelik: 85,
    baslik: "Bakım hatası; otomatik onarımı başlatın",
    neden: "Test, değişmeyen bir niyet için güncelliğini yitirdi; onarılmazsa her koşuda kırmızı kalır.",
    eylem: { tur: "rota", rota: "/hatalar/:id", capa: "onarim" },
    aciklama:
      "Triage bu hatayı test bakımı (ör. locator) olarak sınıfladı. Otomatik onarım bir öneri PR'ı hazırlar; PR'ı siz inceler ve merge edersiniz, beklenen değerlere dokunulmaz.",
  },
  {
    id: "hata-beklenti-case-duzelt",
    ekran: "/hatalar/:id",
    roller: ["analyst"],
    kosul: (o) => o.hata_sinifi === "test_maintenance" && o.beklenti_farki === true,
    oncelik: 85,
    baslik: "Case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor; case'i düzeltin",
    neden:
      "Uygulama PO onaylı karar tablosuna uygun, test beklentisi değil; case düzeltilmeden test her koşuda kırmızı kalır ve otomatik onarım beklenen değere dokunmaz.",
    eylem: { tur: "bilgi" },
    aciklama:
      "Triage bu hatayı test beklentisi farkı olarak sınıfladı: testin beklediği değer onaylı karar tablosundan farklı, uygulamanın ürettiği değer tabloyla aynı. Gereksinimin case ekranında bu case'i düzeltme formuyla tablodaki değere getirin; önerilen içerik onaydan önce tabloyla yeniden kontrol edilir. Bug taslağı ve locator onarımı açılmaz.",
  },
  {
    id: "hata-beklenti-bilgi",
    ekran: "/hatalar/:id",
    roller: ["engineer"],
    kosul: (o) => o.hata_sinifi === "test_maintenance" && o.beklenti_farki === true,
    oncelik: 60,
    baslik: "Test beklentisi karar tablosundan farklı; case'i analist düzeltir",
    neden: "Sorun locator'da ya da kodda değil, case'in beklenen değerinde; otomatik onarım bunu düzeltmez.",
    eylem: { tur: "bilgi" },
    aciklama:
      "Bu hata test beklentisi farkı olarak sınıflandı (uygulama onaylı karar tablosuna uygun). Case düzeltmesi Analist rolündedir; düzeltilen case onaylanınca test yeniden üretilip koşturulabilir.",
  },
  {
    id: "hata-bug-taslagi-karari",
    ekran: "/hatalar/:id",
    roller: ["tester"],
    kosul: (o) => o.hata_sinifi === "product_defect" && o.bug_taslagi_var === true,
    oncelik: 90,
    baslik: "Bug taslağı kararınızı bekliyor",
    neden: "Ürün hatası kayda geçmeden geliştiriciye ulaşmaz; mükerrer kontrolü ve yayın taslak kararına bağlı.",
    eylem: { tur: "rota", rota: "/bug-taslaklari/:id", id_olgusu: "bug_taslagi_id" },
    aciklama:
      "Bu hata ürün hatası olarak sınıflandı ve bir bug taslağı hazırlandı. Taslağı inceleyip yeni kayıt açın, mevcut bir kayda bağlayın ya da kapatın; yayın Testing Probe'un kendi hattıyla yapılır.",
  },
  {
    id: "hata-flaky-task",
    ekran: "/hatalar/:id",
    roller: ["engineer"],
    kosul: (o) => o.hata_sinifi === "flaky" && Number(o.flaky_tekrar) >= 3,
    oncelik: 75,
    baslik: "Bu test son 10 koşuda {flaky_tekrar} kez kararsız çıktı; takip kaydı açın",
    neden: "Kararsız test gerçek hataları gölgeler ve koşu sonuçlarına güveni azaltır.",
    eylem: { tur: "jira_taslak", sablon: "flaky-task" },
    aciklama:
      "Aynı test yakın koşularda tekrar tekrar kararsız sonuç verdi. Kararsızlık zamanlama, veri ya da ortam kaynaklı olabilir; kalıcı çözüm için bir görev kaydı açıp nedeni araştırın.",
  },
  {
    id: "hata-test-verisi-task",
    ekran: "/hatalar/:id",
    roller: ["tester"],
    kosul: (o) => o.hata_sinifi === "test_data",
    oncelik: 80,
    baslik: "Test verisi sorunu; veri sahibine iletin",
    neden: "Ön koşul verisi sağlanmadıkça test anlamlı sonuç vermez ve her koşuda aynı yerde düşer.",
    eylem: { tur: "jira_taslak", sablon: "test-verisi-task" },
    aciklama:
      "Triage bu hatayı test verisi sorunu olarak sınıfladı: testin ön koşulu olan veri ortamda yok ya da beklenenden farklı. Verinin sahibine iletmek için bir görev kaydı açın.",
  },
  {
    id: "hata-test-verisi-bilgi",
    ekran: "/hatalar/:id",
    roller: ["engineer"],
    kosul: (o) => o.hata_sinifi === "test_data",
    oncelik: 50,
    baslik: "Test verisi sorunu; Testçi takip ediyor",
    neden: "Hata kodda değil verideyse kod değişikliği sorunu çözmez.",
    eylem: { tur: "bilgi" },
    aciklama: "Bu hata test verisi sorunu olarak sınıflandı. Takibi Testçi rolündedir; veri düzeltilince test yeniden koşturulabilir.",
  },
  {
    id: "bug-taslagi-karari",
    ekran: "/bug-taslaklari/:id",
    roller: ["tester"],
    kosul: (o) => o.durum === "draft",
    oncelik: 90,
    baslik: "Taslak kararınızı bekliyor (yeni/bağla/kapat)",
    neden: "Karar verilmeyen taslak Jira'ya geçmez; ürün hatası geliştiriciye ulaşmaz.",
    eylem: { tur: "rota", rota: "/bug-taslaklari/:id" },
    aciklama:
      "Taslağı ve mükerrer adaylarını inceleyin; yeni kayıt açın, mevcut bir kayda bağlayın ya da gerekçesiyle kapatın. Yayın Testing Probe'un kendi onaylı hattıyla yapılır.",
  },
  {
    id: "bug-taslagi-bulgudan",
    ekran: "/bug-taslaklari/:id",
    roller: ["analyst"],
    kosul: (o) => o.durum === "draft" && o.bulgu_kaynakli === true,
    oncelik: 40,
    baslik: "Bulgudan bug taslağı hazır; karar Testçide",
    neden: 'Tutarlılık bulgusunda verdiğiniz "kod hatası" kararı bu taslağı üretti; yayın kararı Testçinin.',
    eylem: { tur: "bilgi" },
    aciklama: "Bu taslak, tutarlılık bulgusunu kod hatası olarak işaretlemenizden üretildi. Taslağı Jira'ya açma, bağlama ya da kapatma kararı Testçi rolündedir.",
  },
  {
    id: "butce-uyarisi",
    ekran: "/kontrol-kulesi",
    roller: ["admin"],
    kosul: (o) => Number(o.butce_orani) >= 0.8,
    oncelik: 70,
    baslik: "Model bütçesinin %{butce_yuzde} kadarı kullanıldı",
    neden: "Günlük tavan dolunca AI adımları duraklar; demo sırasında bütçe bitmemeli.",
    eylem: { tur: "bilgi" },
    aciklama:
      "Genel günlük model bütçesinin büyük kısmı kullanıldı. Tavan dolarsa AI adımları ertesi güne (UTC) kadar çalışmaz. Harcama dağılımı bu ekranda; gerekirse tavanı yöneticiyle değerlendirin.",
  },
  {
    id: "guncel-kosu-yok",
    ekran: "/kosular",
    roller: ["admin"],
    kosul: (o) => Number(o.son_kosu_saat) >= 24,
    oncelik: 60,
    baslik: "Güncel koşu yok; demo öncesi koşu tetikleyin",
    neden: "Son koşu {son_kosu_gun} gün önce; demoda gösterilecek sonuçlar güncel olmayabilir.",
    eylem: { tur: "rota", rota: "/kosular" },
    aciklama:
      "Son 24 saatte koşu yapılmadı. Demo öncesi bir koşu tetikleyerek sonuçların güncel olduğundan emin olun; koşu birkaç dakika sürebilir.",
  },
];

/** `rotalar.json`'da rolü kısıtlı ekranlar (diğerleri herkese açık); izinler `lib/yetki.ts` ile aynı. */
const EKRAN_ROLLERI: Record<string, readonly Rol[]> = { "/claude-code": IZINLER["token.issue"], "/demo": IZINLER["demo.manage"] };

/** Ekranın varlık türü (rotalar.json `varlik`). */
const EKRAN_VARLIGI: Record<string, string> = {
  "/gereksinimler/:id": "requirement",
  "/gereksinimler/:id/caseler": "requirement",
  "/gereksinimler/:id/yayin": "requirement",
  "/kod/:id": "script",
  "/kosular/:id": "run",
  "/hatalar/:id": "failure",
  "/bug-taslaklari/:id": "bug_draft",
};

interface GeriBildirimKaydi {
  kural_id: string;
  kullanici_id: string;
  kisi: string;
  deger: -1 | 1 | 2;
  varlik_id: string | null;
  varlik_durum: string;
  jira_anahtari: string | null;
  zaman: string;
}

let geriBildirimler: GeriBildirimKaydi[] = [];

/** Testler için (handlers.mockSifirla çağırır). */
export function oneriMockSifirla(): void {
  geriBildirimler = [];
  Object.assign(oneriMockAyar, ilkAyar());
}

/** Testler için: "Yaptım"/"Gizle" kayıtları. */
export function oneriMockGeriBildirimleri(): readonly GeriBildirimKaydi[] {
  return geriBildirimler;
}

/**
 * Kontrol Kulesi "Öneriler ve asistan" bölümü (core `control_tower/asistan.py` biçimi): kural başına bu
 * oturumdaki Faydalı / Gizle / Yaptım kayıtları. Örnek veride asistan model çağırmaz: asistan maliyeti ve
 * "Neden? Sor" sayısı 0 (uydurulmaz); `diger` çağıranın AI katkısı toplamıdır. Başlıktaki yer tutucular
 * core gibi "…" olur.
 */
export function oneriKuleOlcumu(diger: MaliyetGrubu): AsistanKuleOlcumu {
  const satirlar = MOCK_KURALLAR.map((k) => {
    const kayitlar = geriBildirimler.filter((g) => g.kural_id === k.id);
    const say = (d: -1 | 1 | 2) => kayitlar.filter((g) => g.deger === d).length;
    return {
      kural_id: k.id,
      baslik: k.baslik.replace(/\{[^}]*\}/g, "…"),
      ekran: k.ekran,
      kural_setinde: true,
      neden_sor: 0,
      faydali: say(1),
      gizle: say(-1),
      yaptim: say(2),
    };
  });
  const top = (a: "faydali" | "gizle" | "yaptim") => satirlar.reduce((t, s) => t + s[a], 0);
  const bos = { cagri: 0, maliyet_usd: 0, maliyet_usd_bugun: 0, amaclar: [] };
  return {
    maliyet: { asistan: bos, diger },
    oneriler: satirlar.sort((a, b) => b.faydali + b.gizle + b.yaptim - (a.faydali + a.gizle + a.yaptim)),
    oneri_toplam: { neden_sor: 0, faydali: top("faydali"), gizle: top("gizle"), yaptim: top("yaptim") },
    saklama_gun: 90,
  };
}

const saatFarki = (iso: string | null | undefined, simdi: number): number | null =>
  iso ? Math.max(0, Math.floor((simdi - new Date(iso).getTime()) / 3_600_000)) : null;

/** Varlığın olguları (core `olgular(varlik)` karşılığı; mock verisinden). Varlık yoksa null. */
function olgular(veri: MockVeri, tur: string | null, id: string | null, simdi: number): Olgu | null {
  const genel: Olgu = {
    butce_orani: oneriMockAyar.butceOrani,
    son_kosu_saat: saatFarki(
      veri.kosular.map((k) => k.baslangic).sort().at(-1),
      simdi,
    ),
  };
  if (!tur) return genel;
  if (!id) return null;
  if (tur === "requirement") {
    const g = veri.gereksinimler.find((x) => x.id === id);
    if (!g) return null;
    const caseler = veri.caseler.filter((c) => c.requirement_id === id && c.durum !== "superseded");
    return {
      durum: g.durum,
      ac_eksik: !!g.ac_missing,
      jira_key: g.jira_key,
      po_kanal: g.po?.kanal ?? null,
      po_bekleme_saat: g.durum === "pending_po" ? saatFarki(g.cekim_zamani, simdi) : null,
      acik_bulgu_sayisi: veri.bulgular.filter((b) => b.requirement_id === id && b.durum === "open").length,
      inceleme_bekleyen_case: caseler.filter((c) => c.durum === "draft").length,
      son_onay_bekleyen_case: caseler.filter((c) => c.durum === "ready").length,
      onayli_case: caseler.filter((c) => c.durum === "approved").length,
    };
  }
  if (tur === "script") {
    const s = veri.scriptler.find((x) => x.id === id);
    return s
      ? {
          durum: s.durum,
          kirarak_dogrulama: s.break_verify?.durum ?? "not_started",
          defect_adayi: s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate",
        }
      : null;
  }
  if (tur === "run") {
    const k = veri.kosular.find((x) => x.id === id);
    return k ? { ci_sonuc: k.durum === "error" || k.durum === "passed" || k.durum === "failed" ? k.durum : null } : null;
  }
  if (tur === "failure") {
    const f = veri.hatalar.find((x) => x.id === id);
    if (!f) return null;
    const taslak = veri.bugTaslaklari.find((b) => b.failure_id === id);
    const oneri = f.oneri as { tur?: string; durum?: string; bug_draft_id?: string } | null;
    const bugId = taslak?.id ?? (oneri?.tur === "bug_draft" ? oneri.bug_draft_id : undefined) ?? null;
    const onarim = !oneri || oneri.tur === "bug_draft" ? "none" : typeof oneri.durum === "string" ? oneri.durum : "proposed";
    const son10 = veri.kosular.slice(-10);
    const flaky = son10.filter((k) => (k as { sonuclar?: { test_adi: string; durum: string }[] }).sonuclar?.some((s) => s.test_adi === f.test_adi && s.durum === "flaky")).length;
    return {
      hata_sinifi: f.sinif,
      // core `beklenti_farki`: sınıf test_maintenance ve alt tür `beklenti` (012 §4.4).
      beklenti_farki: f.sinif === "test_maintenance" && (f as { alt_tur?: string | null }).alt_tur === "beklenti",
      onarim_durumu: onarim,
      flaky_tekrar: flaky,
      bug_taslagi_var: !!bugId,
      bug_taslagi_id: bugId,
    };
  }
  if (tur === "bug_draft") {
    const b = veri.bugTaslaklari.find((x) => x.id === id);
    return b ? { durum: b.durum, bulgu_kaynakli: b.finding_id != null, jira_key: b.jira_key } : null;
  }
  return null;
}

/** Bastırma anahtarı: zamanla değişen olgular hariç (core `varlik_durumu`). */
function varlikDurumu(o: Olgu): string {
  const { po_bekleme_saat: _p, son_kosu_saat: _s, ...geri } = o;
  void _p;
  void _s;
  return JSON.stringify(geri);
}

/** Yer tutucular: yalnız olgular ve türevleri; tek geçişli güvenli değiştirme (değer yeniden açılmaz). */
function yerDoldur(metin: string, o: Olgu): string {
  const degerler: Record<string, string> = {};
  for (const [k, v] of Object.entries(o)) if (v !== null && v !== undefined) degerler[k] = String(v);
  if (typeof o.po_bekleme_saat === "number") degerler.po_bekleme_gun = String(Math.max(1, Math.floor(o.po_bekleme_saat / 24)));
  if (typeof o.son_kosu_saat === "number") degerler.son_kosu_gun = String(Math.floor(o.son_kosu_saat / 24));
  if (typeof o.butce_orani === "number") degerler.butce_yuzde = String(Math.round(o.butce_orani * 100));
  return metin.replace(/\{([a-z_]+)\}/g, (tam, ad: string) => degerler[ad] ?? tam);
}

function eylemKur(k: MockKural, varlikId: string | null, o: Olgu): OneriEylemi | null {
  const e = k.eylem;
  if (e.tur === "bilgi") return { tur: "bilgi" };
  if (e.tur === "rota") {
    let hedef = e.rota;
    if (hedef.includes(":id")) {
      const kimlik = e.id_olgusu ? o[e.id_olgusu] : varlikId;
      if (!var_(kimlik)) return null;
      hedef = hedef.replace(":id", encodeURIComponent(String(kimlik)));
    }
    return { tur: "rota", rota: hedef, ...(e.capa ? { capa: e.capa } : {}) };
  }
  const anahtar = typeof o.jira_key === "string" && JIRA_ANAHTARI.test(o.jira_key) ? o.jira_key : null;
  if (e.tur === "jira_kaydi") {
    if (!anahtar) return null;
    return { tur: "jira_kaydi", anahtar, not: UYARI_NOTU, baglanti: `${JIRA_GEZINME}/${anahtar}` };
  }
  const s = TASLAKLAR[e.sablon];
  const taslak = { proje: JIRA_PROJE, tur: s.tur, ozet: yerDoldur(s.ozet, o), aciklama: yerDoldur(s.aciklama, o), etiketler: [...s.etiketler] };
  if (e.tur === "jira_yorum") {
    if (!anahtar) return null;
    return {
      tur: "jira_yorum",
      anahtar,
      taslak,
      adim_notu: `${anahtar} kaydını açın; metni yorum olarak yapıştırın.`,
      not: UYARI_NOTU,
      baglanti: `${JIRA_GEZINME}/${anahtar}`,
    };
  }
  // Simülatörde kayıt oluşturma sayfası yok: bağlantı kurulmaz, yalnız kopyala.
  return {
    tur: "jira_taslak",
    taslak,
    adim_notu: `Proje: ${JIRA_PROJE}, Tür: ${s.tur} seçin; metni yapıştırın.`,
    not: UYARI_NOTU,
    baglanti_yok_nedeni: SIM_BAGLANTI_YOK,
  };
}

function ekranKurallari(kalip: string, rol: Rol): MockKural[] {
  return MOCK_KURALLAR.filter((k) => k.ekran === kalip && k.roller.includes(rol));
}

interface Ekran {
  kalip: string;
  varlikTur: string | null;
  varlikId: string | null;
}

function ekranCoz(k: Kullanici, rota: string, varlikTur: string | null, varlikId: string | null): Ekran {
  const b = ekranBaglamiCikar(rota.split(/[?#]/)[0]);
  if (!b.rota_kalibi || b.rota_kalibi === "/giris") throw new ApiError(404, "Ekran bulunamadı", { kod: "bulunamadi" });
  const roller = EKRAN_ROLLERI[b.rota_kalibi];
  if (roller && !roller.includes(k.rol)) throw new ApiError(404, "Ekran bulunamadı", { kod: "bulunamadi" });
  const tur = EKRAN_VARLIGI[b.rota_kalibi] ?? null;
  if (!tur) return { kalip: b.rota_kalibi, varlikTur: null, varlikId: null };
  if (varlikTur && varlikTur !== tur) throw new ApiError(404, "Kayıt bulunamadı", { kod: "bulunamadi" });
  const yolId = b.varlik?.id && !b.varlik.id.startsWith(":") ? decodeURIComponent(b.varlik.id) : null;
  if (varlikId && yolId && varlikId !== yolId) throw new ApiError(404, "Kayıt bulunamadı", { kod: "bulunamadi" });
  const id = varlikId || yolId;
  if (!id) throw new ApiError(404, "Kayıt bulunamadı", { kod: "bulunamadi" });
  return { kalip: b.rota_kalibi, varlikTur: tur, varlikId: id };
}

/** Bir ekranın kartları ve "Yaptım" bastırmaları (çağıran olguları verir). */
function ekranOnerileri(k: Kullanici, ekran: Ekran, o: Olgu, simdi: number): { kartlar: KuralOnerisi[]; bastirilan: BastirilanOneri[] } {
  const durum = varlikDurumu(o);
  const kartlar: KuralOnerisi[] = [];
  const bastirilan: BastirilanOneri[] = [];
  for (const kural of ekranKurallari(ekran.kalip, k.rol)) {
    if (!kural.kosul(o)) continue;
    const ilgili = geriBildirimler.filter((g) => g.kural_id === kural.id && g.varlik_id === ekran.varlikId && g.varlik_durum === durum);
    if (ilgili.some((g) => g.deger === -1 && g.kullanici_id === k.id)) continue;
    const eylem = eylemKur(kural, ekran.varlikId, o);
    if (!eylem) continue;
    const baslik = yerDoldur(kural.baslik, o);
    const yapildi = ilgili
      .filter((g) => g.deger === 2)
      .filter((g) => kural.tekrar_saat == null || simdi - new Date(g.zaman).getTime() < kural.tekrar_saat * 3_600_000)
      .at(-1);
    if (yapildi) {
      bastirilan.push({ kural_id: kural.id, baslik, kisi: yapildi.kisi, jira_anahtari: yapildi.jira_anahtari, zaman: yapildi.zaman });
      continue;
    }
    kartlar.push({
      kural_id: kural.id,
      baslik,
      neden: yerDoldur(kural.neden, o),
      aciklama: yerDoldur(kural.aciklama, o),
      oncelik: kural.oncelik,
      eylem,
    });
  }
  kartlar.sort((a, b) => b.oncelik - a.oncelik || a.kural_id.localeCompare(b.kural_id));
  return { kartlar, bastirilan };
}

/** "Diğer ekranlarda sizi bekleyen N iş" (`probe_my_queue` karşılığı; rozete sayılmaz). */
function digerEkranlar(veri: MockVeri, k: Kullanici, ekran: Ekran, simdi: number): OneriListesi["diger_ekranlar"] {
  const kimlikler: Record<string, string[]> = {
    requirement: veri.gereksinimler.map((x) => x.id),
    script: veri.scriptler.map((x) => x.id),
    run: veri.kosular.map((x) => x.id),
    failure: veri.hatalar.map((x) => x.id),
    bug_draft: veri.bugTaslaklari.map((x) => x.id),
  };
  let sayi = 0;
  let ilk: string | null = null;
  const kaliplar = [...new Set(MOCK_KURALLAR.filter((r) => r.roller.includes(k.rol)).map((r) => r.ekran))];
  for (const kalip of kaliplar) {
    const tur = EKRAN_VARLIGI[kalip] ?? null;
    for (const id of tur ? kimlikler[tur] : [null]) {
      if (kalip === ekran.kalip && id === ekran.varlikId) continue;
      const o = olgular(veri, tur, id, simdi);
      if (!o) continue;
      const n = ekranOnerileri(k, { kalip, varlikTur: tur, varlikId: id }, o, simdi).kartlar.length;
      if (n > 0 && !ilk) ilk = id ? kalip.replace(":id", encodeURIComponent(id)) : kalip;
      sayi += n;
    }
  }
  return sayi > 0 ? { sayi, rota: ilk } : { sayi: 0, rota: null };
}

function kapiKontrol(): void {
  if (oneriMockAyar.ucYok) throw new ApiError(501, BU_FAZDA_YOK);
  if (!oneriMockAyar.etkin) throw new ApiError(404, "Öneriler bu kurulumda kapalı", { kod: "bulunamadi" });
}

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

/** handlers.ts ROTALAR'ına eklenen öneri uçları (uç 10–11). */
export function oneriRotalari(girisGerekli: () => Kullanici, veriAl: () => MockVeri): Rota[] {
  return [
    [
      "GET",
      /^\/assistant\/suggestions$/,
      (_m, q) => {
        const k = girisGerekli();
        kapiKontrol();
        if (oneriMockAyar.hizSiniri) throw new ApiError(429, "Çok sık istek gönderildi; biraz sonra yeniden deneyin", { kod: "hiz_siniri" });
        const rota = q.get("rota");
        if (!rota) throw new ApiError(422, "rota gerekli", { kod: "gecersiz_istek" });
        const ekran = ekranCoz(k, rota, q.get("varlik_tur"), q.get("varlik_id"));
        const simdi = Date.now();
        const veri = veriAl();
        const o = olgular(veri, ekran.varlikTur, ekran.varlikId, simdi);
        if (!o) throw new ApiError(404, "Kayıt bulunamadı", { kod: "bulunamadi" });
        const { kartlar, bastirilan } = ekranOnerileri(k, ekran, o, simdi);
        const sonuc: OneriListesi = {
          rota_kalibi: ekran.kalip,
          ekranda_kural_var: ekranKurallari(ekran.kalip, k.rol).length > 0,
          oneriler: kartlar,
          bastirilan,
          diger_ekranlar: digerEkranlar(veri, k, ekran, simdi),
          hesaplandi: new Date(simdi).toISOString(),
        };
        return sonuc;
      },
    ],
    [
      "POST",
      /^\/assistant\/suggestions\/([^/]+)\/feedback$/,
      (m, _q, g) => {
        const k = girisGerekli();
        kapiKontrol();
        const kuralId = decodeURIComponent(m[1]);
        const kural = MOCK_KURALLAR.find((r) => r.id === kuralId);
        if (!kural) throw new ApiError(422, "Bilinmeyen öneri kuralı", { kod: "gecersiz_istek" });
        if (!kural.roller.includes(k.rol)) throw new ApiError(404, "Kayıt bulunamadı", { kod: "bulunamadi" });
        const govde = (g ?? {}) as { deger?: unknown; varlik_id?: unknown; jira_anahtari?: unknown };
        const deger = govde.deger;
        if (deger !== -1 && deger !== 1 && deger !== 2) throw new ApiError(422, "deger -1, 1 ya da 2 olmalı", { kod: "gecersiz_istek" });
        let jira: string | null = null;
        if (govde.jira_anahtari != null && govde.jira_anahtari !== "") {
          if (deger !== 2) throw new ApiError(422, "Jira anahtarı yalnız 'Yaptım' ile verilir", { kod: "gecersiz_istek" });
          if (typeof govde.jira_anahtari !== "string" || !JIRA_ANAHTARI.test(govde.jira_anahtari)) {
            throw new ApiError(422, "Jira anahtarı biçimi geçersiz (ör. TPD-12)", { kod: "gecersiz_istek" });
          }
          jira = govde.jira_anahtari;
        }
        const tur = EKRAN_VARLIGI[kural.ekran] ?? null;
        const varlikId = tur ? (typeof govde.varlik_id === "string" ? govde.varlik_id : null) : null;
        if (tur && !varlikId) throw new ApiError(422, "Bu öneri varlık kimliği ister", { kod: "gecersiz_istek" });
        const o = olgular(veriAl(), tur, varlikId, Date.now());
        if (!o) throw new ApiError(404, "Kayıt bulunamadı", { kod: "bulunamadi" });
        const kayit: GeriBildirimKaydi = {
          kural_id: kuralId,
          kullanici_id: k.id,
          kisi: k.kullanici_adi,
          deger,
          varlik_id: varlikId,
          varlik_durum: varlikDurumu(o),
          jira_anahtari: jira,
          zaman: new Date().toISOString(),
        };
        geriBildirimler.push(kayit);
        return { kural_id: kuralId, deger, varlik_id: varlikId, varlik_durum: kayit.varlik_durum, jira_anahtari: jira };
      },
    ],
  ];
}

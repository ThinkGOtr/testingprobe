// IA-12: iç kod, ortam değişkeni ve komut adlarının kullanıcı diline çevrilmesi. Ham metin kaybolmaz:
// arayüz kullanıcı cümlesini gösterir, ham metni "Ayrıntı" açılırında (ya da title) verir.

/** Bilinen teknik hata/ileti kalıbının kullanıcı cümlesi; tanınmazsa null (metin olduğu gibi gösterilir). */
export function teknikMetniCevir(ham: string | null | undefined): string | null {
  if (!ham) return null;
  if (/ForgeNotFoundError|forge deposu bulunamadı|forge-init\.sh/i.test(ham))
    return "Kurulum eksik: projenin kod deposu tanımlı değil. Sistem Yöneticisi AI Probe › Proje › Depo ayarından tanımlamalı.";
  const sauce = /SAUCE_TETIKLER(?:\s*([=:])\s*(\S.*))?/.exec(ham);
  if (sauce) return sauce[1] === ":" ? `bu koşu türünde Sauce çalıştırılmıyor (proje ayarı: ${sauce[2]})` : sauceNedeni(sauce[2]);
  if (/TP_MANUAL_BASELINE_S/.test(ham)) return "Varsayılan manuel süre (yönetici ayarı) ölçüm sayılmaz; story için ölçülmüş süre girilmeli.";
  return null;
}

const TETIK_ADI: Record<string, string> = {
  push: "main'e push",
  deploy: "deploy sonrası",
  nightly: "gece",
  pr: "PR",
  manual: "elle",
};

/** "SAUCE_TETIKLER=push,deploy,nightly" → "Bu koşu türünde Sauce çalıştırılmıyor (Sauce yalnız şu tetiklerde: …)". */
function sauceNedeni(deger: string | undefined): string {
  const liste = (deger ?? "")
    .split(/[,\s]+/)
    .map((t) => t.trim().toLowerCase())
    .filter((t) => TETIK_ADI[t]);
  return liste.length
    ? `bu koşu türünde Sauce çalıştırılmıyor (proje ayarı: yalnız ${liste.map((t) => TETIK_ADI[t]).join(", ")} koşularında)`
    : "bu koşu türünde Sauce çalıştırılmıyor (proje ayarı)";
}

// ---------------------------------------------------------------- denetim olayı etiketleri

const OLAY_ETIKETI: Record<string, string> = {
  "auth.login": "Giriş yapıldı",
  "auth.logout": "Çıkış yapıldı",
  "auth.login_failed": "Giriş başarısız",
  "auth.login_rejected": "Giriş reddedildi",
  "auth.role_switch": "Rol değiştirildi",
  "auth.proje_degisti": "Proje değiştirildi",
  "auth.jit_user": "Kullanıcı ilk girişte oluşturuldu",
  "auth.aiprobe_rejected": "AI Probe oturumu reddedildi",
  "auth.aiprobe_revoked": "AI Probe oturumu iptal edildi",
  "auth.aiprobe_degraded_timeout": "AI Probe kimlik servisi yanıt vermedi",
  "authz.denied": "Yetkisiz işlem reddedildi",
  "ai_call.recorded": "AI çağrısı kaydedildi",
  "tool_call.recorded": "Araç çağrısı kaydedildi",
  "review.recorded": "Karar kaydedildi",
  "workflow.started": "Akış başlatıldı",
  "requirements.sync": "Jira'dan gereksinim çekildi",
  "requirements.free_text": "Serbest metin gereksinim eklendi",
  "requirement.created": "Gereksinim oluşturuldu",
  "requirement.content_changed": "Gereksinim içeriği değişti",
  "requirement.pre_review": "Ön inceleme yapıldı",
  "requirement.consistency_checked": "Tutarlılık denetimi yapıldı",
  "requirement.doc_final": "Doküman son hal olarak onaylandı",
  "requirement.doc_fixed": "Doküman düzeltmeleri yazıldı",
  "requirement.baseline_set": "Manuel baz değer girildi",
  "requirement.baseline_cleared": "Manuel baz değer silindi",
  "requirement.po_withdrawn": "PO teyidi geri çekildi",
  "cases.generated": "Case'ler üretildi",
  "cases.bulk_decision": "Toplu case kararı",
  "cases.reviewed": "Case seti gözden geçirildi (AI)",
  "cases.audited": "Agent Probe denetimi tamamlandı",
  "case.reopen": "Case taslağa alındı",
  "design_model.generated": "Tasarım modeli üretildi",
  "codegen.requested": "Kod üretimi istendi",
  "codegen.pr_opened": "PR açıldı",
  "codegen.merged": "PR birleştirildi",
  "codegen.blocked": "Kod üretimi insana düştü",
  "codegen.break_verified": "Kırarak doğrulama yapıldı",
  "ci.queued": "Koşu kuyruğa alındı",
  "ci.started": "Koşu başladı",
  "ci.completed": "Koşu bitti",
  "triage.classified": "Hata sınıflandırıldı",
  "bug_draft.created": "Bug taslağı oluşturuldu",
  "bug.published": "Bug Jira'da açıldı",
  "bug.linked": "Bug mevcut kayda bağlandı",
  "publish.completed": "Case'ler yayınlandı",
  "repair.proposed": "Onarım önerildi",
  "repair.merged": "Onarım birleştirildi",
  "token.issued": "IDE token'ı oluşturuldu",
  "token.revoked": "IDE token'ı iptal edildi",
  "demo.reset": "Demo sıfırlandı",
  "demo.break": "Demo uygulaması kırıldı",
  "otomasyon.ayar": "Otomasyon ayarı değişti",
  "seed.applied": "Örnek veri yüklendi",
};

const ALAN_ETIKETI: Record<string, string> = {
  auth: "Oturum",
  authz: "Yetki",
  requirement: "Gereksinim",
  requirements: "Gereksinim",
  case: "Case",
  cases: "Case",
  design_model: "Tasarım modeli",
  codegen: "Kod üretimi",
  ci: "Koşu",
  triage: "Triage",
  bug: "Bug",
  bug_draft: "Bug taslağı",
  publish: "Yayın",
  repair: "Onarım",
  token: "IDE token",
  mcp: "IDE kanalı",
  demo: "Demo",
  hata_kosusu: "Hata koşusu",
  karar_tablosu: "Karar tablosu",
  metamorfik: "Metamorfik ilişki",
  oracle: "Karar tablosu kontrolü",
  agent_probe: "Agent Probe",
  asistan: "Asistan",
  acik_soru: "Açık soru",
  testveri: "Test verisi",
  otomasyon: "Otomasyon",
  musteri_ci: "Müşteri CI",
  jira: "Jira",
  pr: "PR",
  external_ref: "Dış kayıt",
  admin: "Yönetim",
  ai_call: "AI çağrısı",
  tool_call: "Araç çağrısı",
  workflow: "Akış",
  review: "Karar",
  seed: "Örnek veri",
};

const FIIL_ETIKETI: Record<string, string> = {
  created: "oluşturuldu",
  updated: "güncellendi",
  edited: "düzenlendi",
  requested: "istendi",
  failed: "başarısız",
  completed: "tamamlandı",
  finished: "bitti",
  started: "başladı",
  merged: "birleştirildi",
  opened: "açıldı",
  closed: "kapandı",
  refused: "reddedildi",
  rejected: "reddedildi",
  denied: "reddedildi",
  recorded: "kaydedildi",
  published: "yayınlandı",
  linked: "bağlandı",
  invalidated: "geçersiz oldu",
  reset: "sıfırlandı",
  proposed: "önerildi",
  checked: "denetlendi",
  generated: "üretildi",
  classified: "sınıflandırıldı",
  revoked: "iptal edildi",
  issued: "oluşturuldu",
};

/**
 * Denetim olay kodunun okunur etiketi: "auth.role_switch" → "Rol değiştirildi". Bilinmeyen kod alan +
 * fiilden kurulur ("codegen.pr_sync_failed" → "Kod üretimi: pr sync başarısız"); kod ayrıca ikinci satırda
 * gösterilir (Denetim ekranı).
 */
export function olayEtiketi(kod: string): string {
  if (OLAY_ETIKETI[kod]) return OLAY_ETIKETI[kod];
  const [alan, ...geri] = kod.split(".");
  const alanAd = ALAN_ETIKETI[alan] ?? alan;
  const fiil = geri.join(" ").split("_");
  const son = fiil[fiil.length - 1];
  if (son && FIIL_ETIKETI[son]) fiil[fiil.length - 1] = FIIL_ETIKETI[son];
  const metin = fiil.join(" ").trim();
  return metin ? `${alanAd}: ${metin}` : alanAd;
}

/** Denetim nesne kimliği: "app_user:9c1c…" → "Kullanıcı 9c1c…" (tablo adı okunur). */
const NESNE_ETIKETI: Record<string, string> = {
  app_user: "Kullanıcı",
  requirement: "Gereksinim",
  test_case: "Case",
  script: "Script",
  run: "Koşu",
  failure: "Hata",
  bug_draft: "Bug taslağı",
  tasarim_modeli: "Tasarım modeli",
  karar_tablosu: "Karar tablosu",
  metamorfik_iliski: "Metamorfik ilişki",
  pull_request: "PR",
  mcp_token: "IDE token",
  job: "İş",
  ai_call: "AI çağrısı",
  hata_kosusu: "Hata koşusu",
  tp_proje: "Proje",
};

export function nesneEtiketi(nesne: string): string {
  const i = nesne.indexOf(":");
  if (i <= 0) return nesne;
  const tur = nesne.slice(0, i);
  const kimlik = nesne.slice(i + 1);
  const ad = NESNE_ETIKETI[tur];
  if (!ad) return nesne;
  return `${ad} ${/^[0-9a-f-]{20,}$/i.test(kimlik) ? `${kimlik.slice(0, 8)}…` : kimlik}`;
}

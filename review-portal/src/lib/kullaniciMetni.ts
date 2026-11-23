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
  sauce: "Sauce Labs turu",
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
  // Oturum ve yetki
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
  "admin.kimlik_bagi.bagla": "Kimlik bağı kuruldu",
  "admin.kimlik_bagi.kaldir": "Kimlik bağı kaldırıldı",
  "token.issued": "IDE token'ı oluşturuldu",
  "token.revoked": "IDE token'ı iptal edildi",
  "mcp.auth_failed": "IDE kanalında kimlik doğrulanamadı",
  "config.proje_reddedildi": "Proje yapılandırması AI Probe'da reddedildi",
  // Kayıt ve akış
  "ai_call.recorded": "AI çağrısı kaydedildi",
  "tool_call.recorded": "Araç çağrısı kaydedildi",
  "review.recorded": "Karar kaydedildi",
  "workflow.started": "Akış başlatıldı",
  "worker.model_mode": "Model kipi değişti",
  "seed.applied": "Örnek veri yüklendi",
  "otomasyon.ayar": "Otomasyon ayarı değişti",
  "external_ref.stale": "Dış kayıt güncelliğini yitirdi",
  "jira.comment": "Jira'ya yorum yazıldı",
  // İnsan kararları (review.<karar>)
  "review.accept": "Karar: kabul edildi",
  "review.accept_difference": "Karar: fark kabul edildi",
  "review.approve": "Karar: onaylandı",
  "review.code_defect": "Karar: kod/veri hatası",
  "review.dismiss": "Karar: reddedildi (bug açılmadı)",
  "review.edit": "Karar: düzenlendi",
  "review.fix_doc": "Karar: doküman düzeltilecek",
  "review.link": "Karar: mevcut kayda bağlandı",
  "review.merge": "Karar: PR birleştirildi",
  "review.new": "Karar: yeni kayıt açılacak",
  "review.po_approve": "PO onayı",
  "review.po_reject": "PO reddi",
  "review.reject": "Karar: reddedildi",
  "review.reopen": "Karar: yeniden açıldı",
  "review.request_changes": "Karar: değişiklik istendi",
  "review.send_back": "Karar: geri gönderildi",
  // Durum geçişleri (<nesne>.transition)
  "requirement.transition": "Gereksinim durumu değişti",
  "requirement_review.transition": "Gereksinim incelemesinin durumu değişti",
  "consistency_finding.transition": "Tutarlılık bulgusunun durumu değişti",
  "test_case.transition": "Case durumu değişti",
  "design_model.transition": "Tasarım modelinin durumu değişti",
  "script.transition": "Script durumu değişti",
  "bug_draft.transition": "Bug taslağının durumu değişti",
  "karar_tablosu.transition": "Karar tablosunun durumu değişti",
  "metamorfik_iliski.transition": "Metamorfik ilişkinin durumu değişti",
  "workflow_instance.transition": "Akış durumu değişti",
  // Gereksinim
  "requirements.sync": "Jira'dan gereksinim çekildi",
  "requirements.free_text": "Serbest metin gereksinim eklendi",
  "requirements.jira_tetik": "Jira tetiği alındı",
  "requirements.otomatik_case": "Case üretimi otomatik başlatıldı",
  "requirement.created": "Gereksinim oluşturuldu",
  "requirement.content_changed": "Gereksinim içeriği değişti",
  "requirement.pre_review": "Ön inceleme yapıldı",
  "requirement.review_complete": "Gereksinim incelemesi tamamlandı",
  "requirement.consistency_checked": "Tutarlılık denetimi yapıldı",
  "requirement.decision_conflict_confirmed": "Karar çelişkisi teyit edildi",
  "requirement.doc_final": "Doküman son hal olarak onaylandı",
  "requirement.doc_fixed": "Doküman düzeltmeleri yazıldı",
  "requirement.baseline_set": "Manuel baz değer girildi",
  "requirement.baseline_cleared": "Manuel baz değer silindi",
  "requirement.po_withdrawn": "PO teyidi geri çekildi",
  "requirement.po_label_removed": "PO etiketi kaldırıldı",
  "requirement.po_label_stale": "PO etiketi güncelliğini yitirdi",
  "requirement.po_request_requeued": "PO teyit isteği yeniden kuyruğa alındı",
  "requirement.recovered": "Gereksinim kurtarıldı",
  "acik_soru.gonderildi": "Açık soru gönderildi",
  "acik_soru.yanitlandi": "Açık soru yanıtlandı",
  // Case
  "cases.generated": "Case'ler üretildi",
  "cases.bulk_decision": "Toplu case kararı",
  "cases.submitted": "Case'ler incelemeye gönderildi",
  "cases.invalidated": "Case seti geçersiz oldu",
  "cases.review_requested": "AI gözden geçirme istendi",
  "cases.review_skipped": "AI gözden geçirme atlandı",
  "cases.review_failed": "AI gözden geçirme başarısız",
  "cases.reviewed": "Case seti gözden geçirildi (AI)",
  "cases.audit_requested": "Agent Probe denetimi istendi",
  "cases.audit_failed": "Agent Probe denetimi başarısız",
  "cases.audited": "Agent Probe denetimi tamamlandı",
  "cases.deepen_started": "Case derinleştirme başladı",
  "cases.deepened": "Case'ler derinleştirildi",
  "cases.deepen_dropped": "Case derinleştirme bırakıldı",
  "cases.deepen_failed": "Case derinleştirme başarısız",
  "cases.deepen_rejected": "Case derinleştirme reddedildi",
  "case.reopen": "Case taslağa alındı",
  "case.po_yaniti_kaynak": "PO yanıtı case'e kaynak oldu",
  "design_model.generated": "Tasarım modeli üretildi",
  "design_model.invalidated": "Tasarım modeli geçersiz oldu",
  "publish.requested": "Case yayını istendi",
  "publish.completed": "Case'ler yayınlandı",
  "publish.failed": "Case yayını başarısız",
  "publish.anchored": "Yayın kaydı sabitlendi",
  // Karar tablosu ve metamorfik ilişki
  "karar_tablosu.ai_draft": "Karar tablosu AI taslağı hazırlandı",
  "karar_tablosu.draft_requested": "Karar tablosu taslağı istendi",
  "karar_tablosu.draft_failed": "Karar tablosu taslağı başarısız",
  "karar_tablosu.created": "Karar tablosu oluşturuldu",
  "karar_tablosu.updated": "Karar tablosu güncellendi",
  "karar_tablosu.submitted": "Karar tablosu onaya gönderildi",
  "karar_tablosu.withdrawn": "Karar tablosu onaydan çekildi",
  "karar_tablosu.approved": "Karar tablosu onaylandı",
  "karar_tablosu.changes_requested": "Karar tablosunda değişiklik istendi",
  "karar_tablosu.reopened": "Karar tablosu yeniden açıldı",
  "karar_tablosu.superseded": "Karar tablosunun yerine yenisi geldi",
  "metamorfik.derived": "Metamorfik ilişkiler türetildi",
  "metamorfik_iliski.ai_draft": "Metamorfik ilişki AI taslağı hazırlandı",
  "metamorfik_iliski.created": "Metamorfik ilişki oluşturuldu",
  "metamorfik_iliski.updated": "Metamorfik ilişki güncellendi",
  "metamorfik_iliski.submitted": "Metamorfik ilişki onaya gönderildi",
  "metamorfik_iliski.withdrawn": "Metamorfik ilişki onaydan çekildi",
  "metamorfik_iliski.approved": "Metamorfik ilişki onaylandı",
  "metamorfik_iliski.changes_requested": "Metamorfik ilişkide değişiklik istendi",
  "metamorfik_iliski.reopened": "Metamorfik ilişki yeniden açıldı",
  "metamorfik_iliski.superseded": "Metamorfik ilişkinin yerine yenisi geldi",
  "oracle.checked": "Karar tablosu kontrolü yapıldı",
  "oracle.onayli_uyumsuz": "Onaylı tabloyla uyumsuzluk bulundu",
  "oracle.warning": "Karar tablosu kontrolü uyarı verdi",
  "oracle.exception": "Karar tablosu istisnası kaydedildi",
  "oracle.exception_reused": "Karar tablosu istisnası yeniden kullanıldı",
  "oracle.dusurme": "Karar tablosu kontrolü düşürüldü",
  "oracle.tablo_yanlis": "Karar tablosu yanlış işaretlendi",
  // Agent Probe
  "agent_probe.case_audit": "Agent Probe case denetimi",
  "agent_probe.case_audit_failed": "Agent Probe case denetimi başarısız",
  "agent_probe.test_baslatildi": "Agent Probe testi başlatıldı",
  "agent_probe.test_durumu": "Agent Probe test durumu alındı",
  "agent_probe.sonuc_islendi": "Agent Probe sonucu işlendi",
  "agent_probe.urun_baglandi": "Agent Probe ürünü bağlandı",
  "agent_probe.urun_baglantisi_kaldirildi": "Agent Probe ürün bağlantısı kaldırıldı",
  // Kod üretimi
  "codegen.requested": "Kod üretimi istendi",
  "codegen.otomatik_hata": "Otomatik kod üretimi başarısız",
  "codegen.committed": "Kod commit'lendi",
  "codegen.blocked": "Kod üretimi insana düştü",
  "codegen.unverified": "Kod doğrulanamadı",
  "codegen.latency_budget": "Kod üretimi süre bütçesini aştı",
  "codegen.tablolar": "Kod üretiminde karar tabloları kullanıldı",
  "codegen.ci_enqueue_failed": "Kod koşusu kuyruğa alınamadı",
  "codegen.run_record_failed": "Kod koşusu kaydedilemedi",
  "codegen.break_verify_requested": "Kırarak doğrulama istendi",
  "codegen.break_verified": "Kırarak doğrulama yapıldı",
  "codegen.review_rejected": "Kod incelemede reddedildi",
  "codegen.pr_opened": "PR açıldı",
  "codegen.pr_updated": "PR güncellendi",
  "codegen.pr_sync_failed": "PR eşitlenemedi",
  "codegen.pr_closed": "PR kapatıldı",
  "codegen.pr_close_failed": "PR kapatılamadı",
  "codegen.pr_closed_external": "PR dışarıda kapatıldı",
  "codegen.pr_superseded": "PR'ın yerine yenisi açıldı",
  "codegen.pr_supersede_failed": "PR yenisiyle değiştirilemedi",
  "codegen.superseded_pr_merged": "Eskimiş PR birleştirildi",
  "codegen.branch_update_requested": "Dal güncellemesi istendi",
  "codegen.branch_updated": "Dal güncellendi",
  "codegen.branch_update_failed": "Dal güncellenemedi",
  "codegen.branch_stale": "Dal geride kaldı",
  "codegen.branch_foreign_commit": "Dalda başkasının commit'i var",
  "codegen.merged": "PR birleştirildi",
  "codegen.merged_foreign_head": "PR farklı bir son commit ile birleştirildi",
  "codegen.merge_refused": "PR birleştirme reddedildi",
  "codegen.merge_acknowledged": "PR birleştirmesi teyit edildi",
  "codegen.merge_ack_comment_failed": "Birleştirme teyit yorumu yazılamadı",
  "musteri_ci.kurulum_pr_acildi": "CI kurulum PR'ı açıldı",
  "musteri_ci.kurulum_pr_mevcut": "CI kurulum PR'ı zaten açık",
  "musteri_ci.kurulum_pr_basarisiz": "CI kurulum PR'ı açılamadı",
  // Koşu
  "ci.dispatch_requested": "Koşu tetiklemesi istendi",
  "ci.github_dispatched": "Koşu GitHub'da tetiklendi",
  "ci.github_dispatch_recovered": "GitHub koşu tetiği kurtarıldı",
  "ci.github_artifacts_mirrored": "GitHub koşu çıktıları kopyalandı",
  "ci.queued": "Koşu kuyruğa alındı",
  "ci.started": "Koşu başladı",
  "ci.completed": "Koşu bitti",
  "ci.pr_comment": "PR'a koşu yorumu yazıldı",
  "ci.diller_dagitildi": "Koşu dillere dağıtıldı",
  "ci.aria_snapshots_backfilled": "Ekran anlık görüntüleri sonradan eklendi",
  "ci.failure_context_backfilled": "Hata bağlamı sonradan eklendi",
  // Hata, triage, bug
  "failure.classified": "Hata sınıflandırıldı",
  "triage.classified": "Hata sınıflandırıldı",
  "triage.reset": "Triage sıfırlandı",
  "triage.run_done": "Koşunun triage'ı tamamlandı",
  "triage.run_skipped": "Koşunun triage'ı atlandı",
  "triage.bug_draft_request_failed": "Bug taslağı istenemedi",
  "hata_kosusu.requested": "Hata koşusu istendi",
  "hata_kosusu.cancel_requested": "Hata koşusunun iptali istendi",
  "hata_kosusu.finished": "Hata koşusu bitti",
  "hata_kosusu.adim_detayi": "Hata koşusu adım ayrıntısı kaydedildi",
  "bug_draft.prepare_requested": "Bug taslağı hazırlığı istendi",
  "bug_draft.prepared": "Bug taslağı hazırlandı",
  "bug_draft.prepare_failed": "Bug taslağı hazırlanamadı",
  "bug_draft.created": "Bug taslağı oluşturuldu",
  "bug_draft.edited": "Bug taslağı düzenlendi",
  "bug_draft.adopted": "Bug taslağı devralındı",
  "bug_draft.failure_attached": "Bug taslağına hata eklendi",
  "bug_draft.jira_deleted": "Bug Jira'da silinmiş",
  "bug.publish_requested": "Bug yayını istendi",
  "bug.publish_retry": "Bug yayını yeniden denendi",
  "bug.publish_failed": "Bug yayını başarısız",
  "bug.publish_changed": "Bug yayını değişti",
  "bug.published": "Bug Jira'da açıldı",
  "bug.linked": "Bug mevcut kayda bağlandı",
  // Onarım
  "repair.requested": "Onarım istendi",
  "repair.retry": "Onarım yeniden denendi",
  "repair.proposed": "Onarım önerildi",
  "repair.checked": "Onarım denetlendi",
  "repair.blocked": "Onarım insana düştü",
  "repair.refused": "Onarım reddedildi",
  "repair.pr_opened": "Onarım PR'ı açıldı",
  "repair.pr_closed_external": "Onarım PR'ı dışarıda kapatıldı",
  "repair.ci_failed": "Onarım koşusu başarısız",
  "repair.run_record_failed": "Onarım koşusu kaydedilemedi",
  "repair.merge_refused": "Onarım birleştirmesi reddedildi",
  "repair.merged": "Onarım birleştirildi",
  "repair.merged_foreign_head": "Onarım farklı bir son commit ile birleştirildi",
  // Test verisi
  "testveri.olustur": "Test verisi eklendi",
  "testveri.guncelle": "Test verisi güncellendi",
  "testveri.sil": "Test verisi silindi",
  "testveri.tohumla": "Test verisi örnek kayıtlarla dolduruldu",
  "testveri.gizli_duzeltme": "Gizli test verisi düzeltildi",
  "testveri.gizli_cakisma_reddi": "Gizli değer çakışması reddedildi",
  "testveri.kaynak_olustur": "Test verisi kaynağı eklendi",
  "testveri.kaynak_guncelle": "Test verisi kaynağı güncellendi",
  "testveri.kaynak_sil": "Test verisi kaynağı silindi",
  "testveri.kaynak_yenile": "Test verisi kaynağı yenilendi",
  // Asistan
  "asistan.denetim": "Asistan güvenlik denetimi",
  "asistan.denetim_calismiyor": "Asistan güvenlik denetimi çalışmıyor",
  "asistan.supheli": "Asistan şüpheli istek nedeniyle donduruldu",
  // Demo
  "demo.break_requested": "Demo kırma istendi",
  "demo.break": "Demo uygulaması kırıldı",
  "demo.break_forced": "Demo uygulaması zorla kırıldı",
  "demo.break_refused": "Demo kırma reddedildi",
  "demo.break_failed": "Demo kırma başarısız",
  "demo.reset_requested": "Demo sıfırlama istendi",
  "demo.reset": "Demo sıfırlandı",
  "demo.reset_failed": "Demo sıfırlama başarısız",
  "demo.tam_sifirlama.istendi": "Demo tam sıfırlaması istendi (Home)",
  "demo.tam_sifirlama.tamam": "Demo tam sıfırlaması tamamlandı",
  "demo.tam_sifirlama.hata": "Demo tam sıfırlaması başarısız",
  "demo.ci_enqueued": "Demo koşusu kuyruğa alındı",
  "demo.ci_skipped": "Demo koşusu atlandı",
  "demo.web_timeout": "Demo uygulaması zamanında hazır olmadı",
  "demo.jira_status": "Demo Jira durumu güncellendi",
};

/** Etiket haritasındaki kodlar (sözleşme testi: core'un yazdığı her olay kodunun etiketi olmalı). */
export const OLAY_ETIKETI_KODLARI: readonly string[] = Object.keys(OLAY_ETIKETI);

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
  asistan_mesaj: "Asistan mesajı",
  kimlik: "Kimlik",
  forge: "Kod deposu",
  test_verisi: "Test verisi",
  test_verisi_kaynagi: "Test verisi kaynağı",
  api_token: "IDE token",
  tool_call: "Araç çağrısı",
  workflow_instance: "Akış",
  external_ref: "Dış kayıt",
  pr: "PR",
  proje: "Proje",
  jira: "Jira",
  takma_ad: "Takma ad",
  ayar: "Ayar",
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

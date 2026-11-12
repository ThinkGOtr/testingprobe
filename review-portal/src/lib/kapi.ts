// Demo-B kapıları ve sınıfları: merge kapısının gerekçeleri, yerel kontrol sınıfının açıklaması.
// Karar core'dadır (request_merge + ForgePort.merge_pr); portal core'un `merge_engelleri`ni olduğu gibi
// gösterir. Zayıf test / kırarak doğrulama yok → kapı değil, açık insan kabulü isteyen uyarı.

import type { PrCheck, RetNedeni, ScriptDetay, YerelKontrolSinifi } from "../api/types";
import type { Ton } from "./etiketler";

export const YEREL_SINIF: Record<YerelKontrolSinifi, { etiket: string; ton: Ton; aciklama: string }> = {
  gecti: {
    etiket: "Yerel kontrol yeşil",
    ton: "basari",
    aciklama: "tsc --strict, eslint --no-inline-config, AST koruması ve Playwright (repeat-each) geçti.",
  },
  defect_adayi: {
    etiket: "Defect adayı",
    ton: "hata",
    aciklama:
      "Test, onaylı case'in beklenen değerinde (assertion) kırmızı. Adımlar ve locator'lar uygulamada doğrulandığı için hata büyük olasılıkla üründe. Otomatik onarım yapılmaz, assertion değiştirilmez; karar insanındır (Faz 4 triage bug taslağına çevirir).",
  },
  kararsiz: {
    etiket: "Kararsız (flaky)",
    ton: "uyari",
    aciklama: "Aynı test tekrarlarda hem geçti hem kırmızı oldu. Defect adayı sayılmaz, PR açılmaz; pass@1 geçmedi sayılır. Ortamı ya da testi inceleyip yeniden üretin.",
  },
  locator: {
    etiket: "Locator / eşleme hatası",
    ton: "uyari",
    aciklama: "Hata eleman bulma ya da adım eşlemesinden kaynaklı. En fazla 1 yeniden eşleme turu yapılır; beklenen değerlere dokunulmaz.",
  },
  derleme: {
    etiket: "Derleme / kural hatası",
    ton: "hata",
    aciklama: "tsc, eslint ya da AST koruması geçmedi; test koşturulmadı.",
  },
  ortam: {
    etiket: "Ortam sorunu",
    ton: "notr",
    aciklama: "Koşu öncesi sağlık yoklaması başarısız (demo uygulaması yanıt vermedi); test sonucu güvenilir değil, yeniden denenmeli.",
  },
  bilinmiyor: { etiket: "Sınıflandırılamadı", ton: "notr", aciklama: "Başarısızlık deterministik kurallarla sınıflandırılamadı; insan incelemesi gerekir." },
};

function checkOzeti(checks: PrCheck[] | undefined): string {
  const kirik = (checks ?? []).filter((c) => (c.zorunlu ?? true) && (c.durum === "failed" || c.durum === "error"));
  return kirik.length ? `: ${kirik.map((c) => c.ad).join(", ")}` : "";
}

type KapiGirdisi = Pick<ScriptDetay, "pr" | "zayif_test" | "break_verify" | "yerel_sinif" | "durum"> & {
  merge_engelleri?: string[] | null;
  merge_kabul_gerekli?: string[] | null;
};

/** core'un ham enum'larını (ör. "durum: merged") Türkçe etikete çevirir. */
const DURUM_TR: Record<string, string> = {
  pending: "bekliyor",
  verifying: "ajan doğruluyor",
  checking: "yerel kontrol",
  blocked: "insana düştü",
  pr_open: "PR açık",
  merged: "birleştirildi",
  closed: "kapatıldı",
  failed: "başarısız",
};
function turkcele(n: string): string {
  return n.replace(/\(durum: ([a-z_]+)\)/g, (t, d: string) => (DURUM_TR[d] ? `(durum: ${DURUM_TR[d]})` : t));
}

/**
 * Merge kapısının kapalı olma nedenleri (boş = kapı açık). Kapı politikasının TEK kaynağı core'dur
 * (`views.merge_engelleri` ↔ `service.request_merge`): core `merge_engelleri` gönderiyorsa portal onu
 * olduğu gibi gösterir, kendi kuralını eklemez. Core göndermiyorsa (eski core / mock) yalnızca core'un
 * da uyguladığı kurallar türetilir: PR açık mı, zorunlu check'ler, kırarak doğrulama sürüyor mu.
 *
 * "Zayıf test" ve "kırarak doğrulama yapılmadı" kapı DEĞİLDİR (TEKNIK-TASARIM §2 adım 6: PR "zayıf test"
 * olarak işaretlenir, ardından merge): bunlar `mergeUyarilari` ile açık insan onayı ister.
 */
export function mergeEngelleri(s: KapiGirdisi): string[] {
  // Core PR yokken ya da PR merge edildiyse [] döner; portal da kapıyı yalnızca açık PR'da gösterir.
  if (s.merge_engelleri) return s.merge_engelleri.map(turkcele);
  return turetilenEngeller(s);
}

function turetilenEngeller(s: KapiGirdisi): string[] {
  const n: string[] = [];
  if (!s.pr) {
    n.push(s.yerel_sinif === "defect_adayi" ? "PR açılmadı: yerel kontrol defect adayı buldu (insan kararı bekleniyor)." : "PR henüz açılmadı.");
    return n;
  }
  if (s.pr.durum === "merged") return ["PR zaten birleştirildi."];
  if (s.pr.durum !== "open") return ["PR kapalı."];
  if (s.pr.ci === "failed") n.push(`CI kırmızı${checkOzeti(s.pr.checks)}.`);
  else if (s.pr.ci !== "passed") n.push("CI sonucu bekleniyor (zorunlu check: local-ci).");
  if (s.break_verify.durum === "running") n.push("Kırarak doğrulama sürüyor.");
  return n;
}

/**
 * Merge'i engellemeyen ama insanın açıkça kabul etmesi gereken uyarılar (açık PR'da). Kabul notu merge
 * isteğiyle core'a gider (`onay_notu`) ki denetimde "zayıf olarak merge edildi" izi kalsın.
 */
export function mergeUyarilari(s: KapiGirdisi): string[] {
  if (s.pr?.durum !== "open") return [];
  // Core gönderiyorsa politikanın tek kaynağı odur (`merge_kabul_gerekli` ↔ request_merge).
  if (Array.isArray(s.merge_kabul_gerekli)) return s.merge_kabul_gerekli.map(turkcele);
  const bv = s.break_verify.durum;
  if (s.zayif_test || bv === "weak") {
    return [
      "Zayıf test: BREAK_CAMPAIGN ile kırılan uygulamada da yeşil kaldı. BREAK_CAMPAIGN yalnızca kampanya kuralını bozar; test kampanya dışı bir davranışı (ör. sepet adedi, minimum sipariş) doğruluyorsa bu beklenen bir sonuçtur.",
    ];
  }
  if (bv === "failed") return ["Kırarak doğrulama tamamlanamadı: testin hata yakaladığına dair kanıt yok."];
  if (bv === "not_started") return ["Kırarak doğrulama yapılmadı (merge öncesi önerilir; yeşil → kırmızı → yeşil)."];
  return [];
}

/** Kabul edilen uyarılar için denetime yazılacak kısa not. */
export function mergeOnayNotu(s: KapiGirdisi): string | null {
  if (s.pr?.durum !== "open") return null;
  if (Array.isArray(s.merge_kabul_gerekli) && s.merge_kabul_gerekli.length === 0) return null;
  const bv = s.break_verify.durum;
  if (s.zayif_test || bv === "weak") return "Zayıf test olarak merge edildi (insan kabulü).";
  if (bv === "failed") return "Kırarak doğrulama tamamlanmadan merge edildi (insan kabulü).";
  if (bv === "not_started") return "Kırarak doğrulama yapılmadan merge edildi (insan kabulü).";
  if (s.merge_kabul_gerekli?.length) return `Uyarı kabul edilerek merge edildi (insan kabulü): ${s.merge_kabul_gerekli.join(" ")}`;
  return null;
}

/**
 * Koşu kimliği `/kosular/:id` sayfasında açılabilir mi. core `GET /runs/{id}` yalnızca UUID kabul eder;
 * yerel kontrol / kırarak doğrulama koşuları toolchain etiketidir (`cg-…`) ve koşu tablosunda yoktur
 * (bağlanırsa 422). Mock veri kimlikleri `run-<n>` biçimindedir ve mock koşu listesinde vardır.
 */
export function kosuKimligiMi(id: string | null | undefined): id is string {
  return !!id && (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) || /^run-[0-9a-z]+$/i.test(id));
}

/** core `script_codegen.engel_turu`: neden insana düştü. */
export const ENGEL_TURU: Record<string, string> = {
  missing_method: "Page object'te eksik metot",
  unknown_method: "Eşlemedeki metot sembol tablosunda yok / imza uymuyor",
  unsourced_value: "Beklenen değer onaylı case metninde yok",
  unverified_step: "Adım uygulamada doğrulanamadı",
  replay_miss: "REPLAY-MISS: kayıtlı doğrulama yok",
  agent_error: "Ajan / model geçidi hatası",
  defect_candidate: "Defect adayı (assertion kırmızı)",
  locator: "Locator / eşleme hatası (düzeltme turundan sonra da)",
  static: "tsc / eslint / AST koruması",
  environment: "Ortam hatası",
  check_unknown: "Sınıflandırılamayan kırmızı",
  case_changed: "Case onaydan sonra değişti",
  flaky: "Kararsız test (tekrarlarda hem geçti hem kırmızı)",
  human_rejected: "İnsan review'ı: değişiklik istendi / reddedildi",
  // 013 K19: test verisi çözülemedi — gizli kaydın ortam sırrı tanımsız ya da anahtar katalogda yok
  // (model hatası değil; ayrıntı engel nedeninde).
  test_verisi: "Test verisi çözülemedi (sır tanımsız ya da kayıt yok)",
};

/** Script review ret nedenleri (sabit taksonomi; core RET_NEDENLERI). */
export const RET_NEDENI: Record<RetNedeni, string> = {
  hallucinated_step: "Uydurma adım (uygulamada olmayan)",
  missing_ac: "Kabul kriteri eksik",
  wrong_test_data: "Yanlış test verisi",
  out_of_scope: "Kapsam dışı",
  duplicate: "Yinelenen test",
  wrong_element: "Yanlış eleman",
};

// Örnek veri: İşlerim (`GET /work-queue`), kayıt yeri (`GET /locate`) ve insan sınıflandırması
// (`POST /failures/:id/classify`). Core `features/islerim/service.py` kaynaklarının sadeleştirilmiş
// karşılığıdır (aynı grup anahtarları, izinler ve roller); örnek veri tek projelidir. Grup bir izinle
// tanımlanır; izni taşıyan her rolün "benim" işidir (YD-06: sınıflandırma Test Uzmanı + Otomasyon Müh.).
import { ApiError } from "../http";
import type { HataAnalizi, Kullanici, Rol } from "../types";
import type { Izin } from "../../lib/yetki";
import { IZINLER, izinVar, normalizeRol, ROL_ETIKETLERI, rolIzinleri } from "../../lib/yetki";
import type { MockVeri } from "./fixtures";
import { INSAN_SINIFLARI, type IsGrubu, type IsOgesi, type IsTuru } from "../islerim";

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

const TUR_IZNI: Record<IsTuru, Izin> = {
  requirement: "requirement.read",
  case: "case.analysis_read",
  script: "code.read",
  run: "run.read",
  failure: "failure.read",
  bug_draft: "case.analysis_read",
};
const TUR_ROTASI: Record<IsTuru, string> = {
  requirement: "/gereksinimler",
  case: "/caseler",
  script: "/kod",
  run: "/kosular",
  failure: "/hatalar",
  bug_draft: "/bug-taslaklari",
};

type HamGrup = Omit<IsGrubu, "sayi" | "oge_sayisi" | "rol_etiketi">;

/** Core `islerim.ROL_SIRASI`: iş akışı sırası; Sistem Yöneticisi başka rol varsa listelenmez. */
const ROL_SIRASI: Rol[] = ["analyst", "po", "tester", "engineer", "developer", "admin", "auditor", "viewer"];
function izinRolleri(izin: Izin): Rol[] {
  const r = IZINLER[izin] as readonly Rol[];
  const sirali = ROL_SIRASI.filter((x) => r.includes(x));
  const isci = sirali.filter((x) => x !== "admin");
  return isci.length ? isci : sirali;
}
/** "Test Uzmanı ya da Otomasyon Mühendisi" (core `roller_etiketi`). */
export function rollerEtiketi(roller: readonly string[]): string {
  const ad = roller.map((r) => ROL_ETIKETLERI[r as Rol] ?? r);
  return ad.length <= 1 ? ad.join("") : `${ad.slice(0, -1).join(", ")} ya da ${ad[ad.length - 1]}`;
}

function grup(anahtar: string, tur: IsTuru, izin: Izin, baslik: string, sonraki_adim: string, ogeler: IsOgesi[]): HamGrup {
  const roller = izinRolleri(izin);
  return { anahtar, tur, rol: roller[0], roller, baslik, sonraki_adim, ogeler };
}

function kaynaklar(v: MockVeri): HamGrup[] {
  const req = (durumlar: string[]) => v.gereksinimler.filter((g) => durumlar.includes(g.durum));
  const reqOge = (g: MockVeri["gereksinimler"][number], neden: string): IsOgesi => ({
    id: g.id,
    tur: "requirement",
    etiket: `${g.jira_key ?? "Serbest metin"} · ${g.baslik}`,
    neden,
    rota: `/gereksinimler/${g.id}`,
    zaman: g.cekim_zamani ?? null,
    jira_key: g.jira_key,
    sayi: 1,
  });
  const caseGrubu = (durum: string, neden: (n: number) => string): IsOgesi[] => {
    const say = new Map<string, number>();
    for (const c of v.caseler) if (c.durum === durum && !c.onceki_icerik) say.set(c.requirement_id, (say.get(c.requirement_id) ?? 0) + 1);
    return [...say].flatMap(([rid, n]) => {
      const g = v.gereksinimler.find((x) => x.id === rid);
      if (!g) return [];
      return [{ ...reqOge(g, neden(n)), tur: "case" as const, rota: `/gereksinimler/${g.id}/caseler`, sayi: n }];
    });
  };
  const hataOge = (h: HataAnalizi, neden: string): IsOgesi => ({
    id: h.id,
    tur: "failure",
    etiket: h.test_adi,
    neden,
    rota: `/hatalar/${h.id}`,
    zaman: h.zaman,
    jira_key: null,
    sayi: 1,
  });
  return [
    grup("on_inceleme", "requirement", "requirement.review", "Ön inceleme bekleyen gereksinim", "Gereksinimi açın, ön incelemeyi başlatın",
      req(["new"]).map((g) => reqOge(g, g.ac_missing ? "Kabul kriteri yok: PO'ya sorun" : "İncelemeye alınmalı (ön inceleme + tutarlılık denetimi)"))),
    grup("bulgu_karari", "requirement", "requirement.review", "Bulgu kararı bekleyen", "Tutarlılık bulgularına karar verin",
      req(["findings_open"]).map((g) => reqOge(g, "Tutarlılık bulguları analist kararı bekliyor"))),
    grup("po_gonder", "requirement", "requirement.review", "PO onayına gönderilecek", "Doküman son hal: PO teyidi için gönderin",
      req(["doc_final"]).map((g) => reqOge(g, "Doküman son hal; PO onayına gönderilmeli"))),
    grup("po_teyidi", "requirement", "requirement.po_approve_free_text", "PO teyidi bekleyen", "Jira story'sini inceleyip onay etiketini ekleyin (serbest metinde portalda onaylayın)",
      req(["pending_po"]).map((g) => reqOge(g, g.kaynak === "jira" ? "Jira'da onay etiketi bekleniyor" : "Serbest metin: portalda onaylayın"))),
    grup("case_uretimi", "requirement", "case.generate", "Case üretimi bekleyen", "Tasarım modelini üretin ya da kararını verin",
      req(["po_approved", "model_ready"]).map((g) => reqOge(g, "PO onayladı; case üretimi başlatılmalı"))),
    grup("case_karari", "case", "case.decide", "Case kararı bekleyen", "Case review'da kabul / düzelterek kabul / ret kararı verin",
      caseGrubu("draft", (n) => `${n} case Test Uzmanı kararı bekliyor`)),
    grup("case_son_onay", "case", "case.approve", "Son onay bekleyen case", "Case review'da onaylayın ya da gerekçeyle geri gönderin",
      caseGrubu("ready", (n) => `${n} case Analist son onayı bekliyor`)),
    grup("case_yayini", "case", "case.publish", "Yayın bekleyen onaylı case", "Yayın önizlemesinden Jira'ya yayınlayın",
      caseGrubu("approved", (n) => `${n} onaylı case yayın bekliyor`)),
    grup("kod_insana", "script", "code.generate", "Kod üretiminde insana düşen", "Script'i açın; engeli giderin ya da yeniden üretin",
      v.scriptler.filter((s) => s.durum === "blocked").map((s) => ({
        id: s.id, tur: "script" as const, etiket: `${s.requirement_key ?? "—"} · ${s.baslik}`,
        neden: s.engel?.neden ?? "Üretim insana düştü; engel incelenmeli", rota: `/kod/${s.id}`, zaman: null, jira_key: s.requirement_key, sayi: 1,
      }))),
    grup("acik_pr", "script", "code.merge", "Açık PR", "PR'ı inceleyin, kırarak doğrulayın ve birleştirin",
      v.scriptler.filter((s) => s.durum === "pr_open").map((s) => ({
        id: s.id, tur: "script" as const, etiket: `${s.requirement_key ?? "—"} · ${s.baslik}`,
        neden: s.pr ? `PR #${s.pr.number} açık: kırarak doğrulama ve birleştirme kararı` : "PR açık", rota: `/kod/${s.id}`, zaman: null, jira_key: s.requirement_key, sayi: 1,
      }))),
    grup("siniflandirma", "failure", "failure.classify", "Sınıflandırma bekleyen hata", "Hatayı açın; ürün hatası, test bakımı, veri ya da ortam olarak sınıflandırın",
      // Hatalar listesinin "Sınıflandırılmamış" sekmesiyle aynı tanım (kasıtlı kırma hariç, tekilleştirme yok).
      v.hatalar.filter((h) => h.sinif === "unknown" && !h.kirma).map((h) => hataOge(h, h.mode === "replay_miss" ? "REPLAY-MISS: AI yorumu alınamadı; sınıfı siz belirleyin" : "Kural eşleşmedi, AI sınıflandıramadı; sınıfı siz belirleyin"))),
    grup("test_bakimi", "failure", "code.repair", "Test bakımı / ortam hatası", "Hatayı açın; otomatik onarımı başlatın ya da ortamı inceleyin",
      v.hatalar.filter((h) => ["test_maintenance", "flaky", "environment"].includes(h.sinif) && h.alt_tur !== "beklenti" && h.oneri?.tur !== "bug_draft").map((h) => hataOge(h, "İnceleyin"))),
    grup("bug_karari", "bug_draft", "bug.decide", "Bug taslağı kararı", "Taslağı açın: yeni kayıt, mevcut kayda bağla ya da reddet",
      v.bugTaslaklari.filter((b) => b.durum === "draft" || b.durum === "approved").map((b) => ({
        id: b.id, tur: "bug_draft" as const, etiket: b.icerik.summary, neden: b.durum === "draft" ? "Bug taslağı kararı bekleniyor (yeni / bağla / kapat)" : "Onaylı; Jira'ya yayın bekleniyor",
        rota: `/bug-taslaklari/${b.id}`, zaman: null, jira_key: null, sayi: 1,
      }))),
    grup("kosu_hatasi", "run", "run.trigger_scheduled", "Başarısız ya da hatalı koşu", "Koşuyu açın; kırmızı testlerin triage sonucuna ya da CI günlüğüne bakın",
      v.kosular.filter((k) => (k.durum === "failed" || k.durum === "error") && k.tetik !== "break_verify").slice(0, 20).map((k) => ({
        id: k.id, tur: "run" as const, etiket: `${k.tetik} koşusu`, neden: k.durum === "error" ? "Testler koşmadı: CI ortam hatası" : "Kırmızı test var: triage sonucunu inceleyin",
        rota: `/kosular/${k.id}`, zaman: k.baslangic, jira_key: null, sayi: 1,
      }))),
  ];
}

export function isKuyruguHesapla(v: MockVeri, rolHam: string) {
  const rol = normalizeRol(rolHam) ?? rolHam;
  const izinler = new Set<string>(rolIzinleri(rol));
  const tam = (g: HamGrup, ust: number): IsGrubu => ({
    ...g,
    rol_etiketi: rollerEtiketi(g.roller ?? [g.rol]),
    sayi: g.ogeler.reduce((t, o) => t + o.sayi, 0),
    oge_sayisi: g.ogeler.length,
    ogeler: izinVar(izinler, TUR_IZNI[g.tur]) ? g.ogeler.slice(0, ust) : [],
  });
  const dolu = kaynaklar(v).filter((g) => g.ogeler.length > 0);
  const benimMi = (g: HamGrup) => (g.roller ?? [g.rol]).includes(rol);
  const benim = dolu.filter(benimMi).map((g) => tam(g, 20));
  const ekip = dolu.filter((g) => !benimMi(g)).map((g) => ({ ...tam(g, 5), kisiler: [] as string[] }));
  const menu: Record<string, number> = { "/islerim": 0, ...Object.fromEntries(Object.values(TUR_ROTASI).map((r) => [r, 0])) };
  for (const g of benim) {
    // Hatalar rozeti yalnız varsayılan sekme (Sınıflandırılmamış): rozet = listedeki sayı (core ROZET_GRUPLARI).
    if (g.tur !== "failure" || g.anahtar === "siniflandirma") menu[TUR_ROTASI[g.tur]] += g.sayi;
    menu["/islerim"] += g.sayi;
  }
  return {
    rol,
    rol_etiketi: ROL_ETIKETLERI[rol as keyof typeof ROL_ETIKETLERI] ?? rol,
    toplam: menu["/islerim"],
    ekip_toplam: ekip.reduce((t, g) => t + g.sayi, 0),
    benim,
    ekip,
    menu,
  };
}

export function islerimRotalari(
  girisGerekli: () => Kullanici,
  izinGerekli: (...izinler: [Izin, ...Izin[]]) => Kullanici,
  veri: () => MockVeri,
  kayit: (eylem: string, nesne: string, ozet: string) => void,
): Rota[] {
  return [
    [
      "GET",
      /^\/work-queue$/,
      () => {
        const k = izinGerekli("dashboard.read");
        return isKuyruguHesapla(veri(), k.rol);
      },
    ],
    [
      "GET",
      /^\/locate$/,
      (_m, q) => {
        girisGerekli();
        const id = q.get("id") ?? "";
        const v = veri();
        const listeler: { id: string }[][] = [v.gereksinimler, v.caseler, v.scriptler, v.kosular, v.hatalar, v.bugTaslaklari];
        const var_ = listeler.some((l) => l.some((x) => x.id === id));
        return var_ ? { bulundu: true, ayni_proje: true, proje: { pid: "varsayilan", name: "Örnek proje" } } : { bulundu: false, ayni_proje: false, proje: null };
      },
    ],
    [
      "POST",
      /^\/failures\/([^/]+)\/classify$/,
      (m, _q, govde) => {
        const k = izinGerekli("failure.classify");
        const id = decodeURIComponent(m[1]);
        const g = (govde ?? {}) as { sinif?: string; gerekce?: string };
        if (!g.sinif || !(INSAN_SINIFLARI as string[]).includes(g.sinif)) throw new ApiError(422, "Geçersiz sınıf");
        if (!g.gerekce?.trim()) throw new ApiError(422, "Gerekçe zorunlu");
        const v = veri();
        const h = v.hatalar.find((x) => x.id === id);
        if (!h) throw new ApiError(404, "Triage kaydı bulunamadı");
        if (h.oneri?.tur === "bug_draft" && g.sinif !== "product_defect") {
          throw new ApiError(409, "Bu hataya bağlı bir bug taslağı var; önce taslağı reddedin, sonra sınıfı değiştirin");
        }
        const once = h.sinif;
        h.sinif = g.sinif as HataAnalizi["sinif"];
        h.karar_kaynagi = "human";
        h.gerekce = g.gerekce.trim();
        if (once !== h.sinif) h.alt_tur = null;
        let acilan: string | null = null;
        if (h.sinif === "product_defect" && h.oneri?.tur !== "bug_draft") {
          acilan = `bug-${id}`;
          v.bugTaslaklari.unshift({
            id: acilan,
            kaynak: "triage",
            failure_id: id,
            finding_id: null,
            icerik: { summary: h.test_adi, steps: [], expected: "", actual: h.hata_mesaji, environment: "", evidence: [], story_key: null, test_case_key: null, severity_suggestion: "major", labels: [], uretim: "sablon" },
            mukerrer_adaylari: [],
            karar: null,
            durum: "draft",
            link_key: null,
            icerik_hash: `h-${id}`,
            onaylayan: null,
            onay_zamani: null,
            jira_key: null,
            mode: null,
          } as unknown as MockVeri["bugTaslaklari"][number]);
          h.oneri = { tur: "bug_draft", bug_draft_id: acilan };
        }
        kayit("failure.classified", `failure:${id}`, `${once} → ${h.sinif} (${k.kullanici_adi})`);
        return { ...h, karar_kaynagi: "human", acilan_bug_draft_id: acilan };
      },
    ],
  ];
}

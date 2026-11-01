// Demo yol haritası: TEKNIK-TASARIM §2'deki 14 adım + locator yolu, demo story'si (TPD-1) için
// gerçek API durumundan türetilir. Hiçbir adım varsayımla "tamam" sayılmaz: kanıt yoksa
// "bekliyor"; yerine yedek kullanılan adım (Sauce yerine yerel Chromium) "yedek" olarak açıkça yazılır.
import type {
  BugTaslagi,
  CiktiModu,
  DemoDurumu,
  GereksinimDetay,
  HataAnalizi,
  KontrolKulesi,
  Kosu,
  PaketDegerlendirmesi,
  Script,
  TestCase,
} from "../api/types";
import { api } from "../api/client";
import { AKIS_ADIMLARI } from "./etiketler";

export const DEMO_STORY = "TPD-1";

export type AdimHali = "tamam" | "suruyor" | "bekliyor" | "engel" | "yedek";

export interface YolAdimi {
  no: number | string;
  ad: string;
  tur: "sistem" | "ai" | "insan" | "ai_insan";
  hal: AdimHali;
  /** Gerçek durumdan kısa kanıt (sayı, anahtar, koşu). */
  kanit: string;
  /** Sunucu notu (DEMO-VERISI sahne notları) ya da bir sonraki eylem. */
  ipucu?: string | null;
  baglanti?: { yol: string; etiket: string } | null;
  /** Bu adımın çıktısı hazır (golden) çıktıdan (REPLAY) mı. */
  mode?: CiktiModu | null;
  /** Adım gerçek dış sistem yerine simülatörle tamamlandıysa adı (jira-sim, LocalForge, yerel CI). */
  simulator?: string | null;
}

export interface YolGirdisi {
  gereksinim: GereksinimDetay | null;
  caseler: TestCase[];
  scriptler: Script[];
  kosular: Kosu[];
  hatalar: HataAnalizi[];
  bugTaslaklari: BugTaslagi[];
  kule: KontrolKulesi | null;
  demo: DemoDurumu | null;
}

const kodla = (s: string) => encodeURIComponent(s);
const CI_TETIKLERI = new Set(["pr", "push", "nightly", "deploy", "manual"]);
const TETIK_ADI: Record<string, string> = { pr: "PR", push: "push", nightly: "gece", deploy: "deploy", manual: "elle" };

function enYeni<T>(liste: T[], zaman: (x: T) => string): T | null {
  return [...liste].sort((a, b) => zaman(b).localeCompare(zaman(a)))[0] ?? null;
}

/** "C3" gibi case etiketi (sıra no); bilinmiyorsa null. */
function caseEtiketi(s: Script, caseler: TestCase[]): string | null {
  const c = caseler.find((x) => s.case_ids.includes(x.id));
  return c ? `C${c.sira_no}` : null;
}

/** Demo story'sinin script'leri: requirement_key ya da case bağı (kapatılan yeniden üretimler hariç). */
export function storyScriptleri(g: Pick<GereksinimDetay, "jira_key"> | null, scriptler: Script[], caseler: TestCase[]): Script[] {
  if (!g) return [];
  const ids = new Set(caseler.map((c) => c.id));
  return scriptler.filter((s) => s.durum !== "closed" && (s.requirement_key === g.jira_key || s.case_ids.some((id) => ids.has(id))));
}

function etiketliListe(ss: Script[], caseler: TestCase[]): string {
  const e = ss.map((s) => caseEtiketi(s, caseler)).filter((x): x is string => !!x);
  return [...new Set(e)].sort((a, b) => Number(a.slice(1)) - Number(b.slice(1))).join(", ");
}

const YEREL_HOST = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|jira-sim|jira_sim|[^.]+)$|\.local$|\.internal$/i;

/** Jira adresi simülatörü (jira-sim) mi: localhost / compose servis adı / .local. Adres bilinmiyorsa null. */
export function jiraSimMi(x: { gereksinim: { jira_url?: string | null } | null; bugTaslaklari: BugTaslagi[] }): boolean | null {
  const adresler = [x.gereksinim?.jira_url, ...x.bugTaslaklari.flatMap((b) => [b.jira_browse_url, b.jira_url])].filter((u): u is string => !!u);
  for (const u of adresler) {
    try {
      return YEREL_HOST.test(new URL(u).hostname);
    } catch {
      /* geçersiz adres: sonrakine bak */
    }
  }
  return null;
}

/** Kırma koşusu mu (core Kontrol Kulesi ile aynı kural: tetik `break_verify` ya da `ortam.break_campaign`). */
export function kirmaKosusuMu(k: Pick<Kosu, "tetik" | "break_campaign">): boolean {
  return k.tetik === "break_verify" || k.break_campaign === true;
}

/** Bug taslağı kasıtlı kırma koşusunun kırmızısından mı (kaynak hata → koşu). Bilinmiyorsa false. */
export function kirmaTaslagiMi(b: BugTaslagi, hatalar: HataAnalizi[], kosular: Kosu[]): boolean {
  if (!b.failure_id) return false;
  const h = hatalar.find((x) => x.id === b.failure_id);
  const k = h ? kosular.find((x) => x.id === h.run_id) : undefined;
  return !!k && kirmaKosusuMu(k);
}

function zamanMs(z: string | null | undefined): number | null {
  if (!z) return null;
  const n = Date.parse(z);
  return Number.isNaN(n) ? null : n;
}

/**
 * Koşu bu story'ye mi ait: story script'lerinden birinin PR'ının koşusu ya da story'nin ilk merge'ünden
 * (bilinmiyorsa merge edilen script'in oluşturulmasından) sonra başlayan koşu. Merge yoksa yalnız PR koşuları.
 */
export function storyKosusuMu(k: Pick<Kosu, "pr_no" | "baslangic">, ss: Script[]): boolean {
  if (k.pr_no != null && ss.some((s) => s.pr?.number === k.pr_no)) return true;
  const mergeler = ss
    .filter((s) => s.durum === "merged" || s.pr?.durum === "merged")
    .map((s) => zamanMs(s.pr?.merge_zamani) ?? zamanMs(s.olusturma))
    .filter((n): n is number => n !== null);
  if (mergeler.length === 0) return false;
  const bas = zamanMs(k.baslangic);
  return bas !== null && bas >= Math.min(...mergeler);
}

const JIRA_SIM = "simülatör: jira-sim (Jira Cloud yerine)";
const FORGE_SIM = "simülatör: LocalForge (GitHub ruleset yerine yerel zorunlu local-ci kontrolü)";

export function demoAdimlari(x: YolGirdisi): YolAdimi[] {
  const g = x.gereksinim;
  const ad = (n: number) => AKIS_ADIMLARI[n - 1];
  const adim = (n: number, a: Omit<YolAdimi, "no" | "ad" | "tur">): YolAdimi => ({ no: n, ad: ad(n).ad, tur: ad(n).tur, ...a });
  const gYolu = g ? `/gereksinimler/${kodla(g.id)}` : "/gereksinimler";
  const cs = x.caseler.filter((c) => c.durum !== "superseded");
  const denetimSonrasi = ["doc_final", "pending_po", "po_approved", "generating", "cases_ready", "done"];
  const poSonrasi = ["po_approved", "generating", "cases_ready", "done"];

  // Simülatörler: sunucu sahnede adını söyler (DEMO-AKISI); "tamam" gerçek dış sistem sanılmasın.
  const jiraSim = jiraSimMi(x) === true ? JIRA_SIM : null;

  // 1 — Jira
  const a1 = g
    ? adim(1, { hal: "tamam", kanit: `${g.jira_key ?? "story"} çekildi · ${g.kabul_kriterleri.length} AC`, baglanti: { yol: gYolu, etiket: "Story'yi aç" }, simulator: g.kaynak === "jira" ? jiraSim : null })
    : adim(1, {
        hal: "bekliyor",
        kanit: `${DEMO_STORY} henüz çekilmedi.`,
        ipucu: "Analist: Gereksinimler → \"Jira'dan çek\".",
        baglanti: { yol: "/gereksinimler", etiket: "Gereksinimler" },
      });

  // 2 — Ön inceleme + kod/veri tutarlılığı
  const mode2 = g?.son_kontrol?.mode ?? g?.on_inceleme?.mode ?? null;
  const tur = g ? `kontrol turu ${g.kontrol_turu}/${g.kontrol_turu_ust_sinir}` : "";
  const a2 = !g
    ? adim(2, { hal: "bekliyor", kanit: "Story yok." })
    : denetimSonrasi.includes(g.durum) || (g.durum === "failed" && g.son_hata?.job_tur === "cases.generate")
      ? adim(2, { hal: "tamam", kanit: `Doküman son hal · ${tur}`, baglanti: { yol: gYolu, etiket: "Bulgular" }, mode: mode2 })
      : g.durum === "in_review" || g.durum === "findings_open"
        ? adim(2, {
            hal: "suruyor",
            kanit: g.durum === "in_review" ? `Denetim sürüyor · ${tur}` : `${g.sayaclar.bulgu_acik} bulgu karar bekliyor · ${tur}`,
            ipucu: "Sahne: F1 ve F3 \"Dokümanı düzelt\", F2 kampanya ve F4 kredi limiti \"Kod/veri hatalı\"; sonra \"Düzeltmeleri Jira'ya yaz\".",
            baglanti: { yol: gYolu, etiket: "Bulgulara karar ver" },
            mode: mode2,
          })
        : g.durum === "failed"
          ? adim(2, { hal: "engel", kanit: g.son_hata?.neden ?? "Denetim hata ile bitti.", ipucu: "\"Yeniden denetle\".", baglanti: { yol: gYolu, etiket: "Story" } })
          : adim(2, { hal: "bekliyor", kanit: "Ön inceleme başlatılmadı.", ipucu: "Analist: \"Ön incelemeyi başlat\".", baglanti: { yol: gYolu, etiket: "Story" } });

  // 3 — PO teyidi
  const poGuncel = !!g && g.po.durum === "approved" && (!g.po.onaylanan_hash || !g.icerik_hash || g.po.onaylanan_hash === g.icerik_hash);
  const a3 = !g
    ? adim(3, { hal: "bekliyor", kanit: "Story yok." })
    : poGuncel && poSonrasi.includes(g.durum)
      ? adim(3, { hal: "tamam", kanit: `PO onaylı: ${g.po.onaylayan ?? "—"} (${g.po.kanal === "jira" ? "Jira etiketi" : "portal"})`, baglanti: { yol: gYolu, etiket: "PO teyidi" } })
      : g.po.durum === "pending" || g.durum === "pending_po"
        ? adim(3, {
            hal: "suruyor",
            kanit: "PO cevabı bekleniyor.",
            ipucu: g.kaynak === "jira" ? "PO Jira'da (po@sim.local) cevaplar ve tp-po-approved etiketini koyar; 15 sn'de bir okunur." : "PO portalda onaylar.",
            baglanti: { yol: gYolu, etiket: "PO teyidi" },
          })
        : adim(3, { hal: "bekliyor", kanit: "Doküman son hal olunca PO teyidi istenir." });

  // 4 — Test case (QA onayı + yayın)
  const onayli = cs.filter((c) => c.durum === "approved" || c.durum === "published").length;
  const yayinli = cs.filter((c) => c.durum === "published" || c.jira_test_key).length;
  const taslak = cs.filter((c) => c.durum === "draft").length;
  const mode4 = cs.find((c) => c.mode)?.mode ?? null;
  const a4 =
    cs.length === 0
      ? adim(4, {
          hal: g?.durum === "generating" ? "suruyor" : "bekliyor",
          kanit: g?.durum === "generating" ? "Case üretimi sürüyor." : "Henüz case yok.",
          ipucu: poGuncel ? "Analist: \"Case üret\"." : null,
          baglanti: g ? { yol: gYolu, etiket: "Story" } : null,
        })
      : adim(4, {
          hal: taslak === 0 && yayinli > 0 ? "tamam" : "suruyor",
          kanit: `${cs.length} case · ${onayli} onaylı · ${yayinli} Jira'da${taslak ? ` · ${taslak} karar bekliyor` : ""}`,
          ipucu: taslak ? "QA (analist) case'lere karar verir." : yayinli < onayli ? "Onaylı case'leri yayınla (önizleme → yayın)." : null,
          baglanti: g ? { yol: taslak || yayinli >= onayli ? `${gYolu}/caseler` : `${gYolu}/yayin`, etiket: taslak || yayinli >= onayli ? "Case review" : "Yayın" } : null,
          mode: mode4,
        });

  return [a1, a2, a3, a4, ...sonrakiAdimlar(x)];
}

/** Adım 5–14'ün girdisi: story'nin yalnızca kimliği ve anahtarı gerekir (liste satırında da kullanılır). */
export type SonrakiGirdi = Omit<YolGirdisi, "gereksinim"> & {
  gereksinim: (Pick<GereksinimDetay, "id" | "jira_key" | "kaynak"> & { jira_url?: string | null }) | null;
};

/**
 * Adım 5–14 (kod, review, merge, CI, sonuçlar, Kontrol Kulesi, triage, bug): gereksinim makinesi
 * `done` ile biter; sonrası script/koşu/triage/bug nesnelerinden okunur.
 */
export function sonrakiAdimlar(x: SonrakiGirdi): YolAdimi[] {
  const g = x.gereksinim;
  const ad = (n: number) => AKIS_ADIMLARI[n - 1];
  const adim = (n: number, a: Omit<YolAdimi, "no" | "ad" | "tur">): YolAdimi => ({ no: n, ad: ad(n).ad, tur: ad(n).tur, ...a });
  const cs = x.caseler.filter((c) => c.durum !== "superseded");
  const ss = storyScriptleri(g, x.scriptler, cs);
  const ssIds = new Set(ss.map((s) => s.id));
  const jiraSim = jiraSimMi({ gereksinim: g, bugTaslaklari: x.bugTaslaklari }) === true ? JIRA_SIM : null;
  const forgeSim = x.demo?.locator_demo?.destekleniyor === true ? FORGE_SIM : null;

  // 5 — Kod taslağı
  const prli = ss.filter((s) => s.pr);
  const defect = ss.filter((s) => s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate");
  const suren5 = ss.filter((s) => ["pending", "verifying", "checking"].includes(s.durum));
  const mode5 = ss.find((s) => s.mode)?.mode ?? null;
  const a5 =
    ss.length === 0
      ? adim(5, {
          hal: "bekliyor",
          kanit: "Kod üretilmedi.",
          ipucu: "Mühendis: Kod üretimi → C1, C2, C3, C5 seç → üret.",
          baglanti: { yol: "/kod", etiket: "Kod üretimi" },
        })
      : adim(5, {
          hal: prli.length > 0 && suren5.length === 0 ? "tamam" : "suruyor",
          kanit: [
            prli.length ? `PR: ${etiketliListe(prli, cs) || prli.length}` : null,
            defect.length ? `defect adayı: ${etiketliListe(defect, cs) || defect.length} (PR yok)` : null,
            suren5.length ? `${suren5.length} sürüyor` : null,
          ]
            .filter(Boolean)
            .join(" · ") || `${ss.length} script`,
          baglanti: { yol: "/kod", etiket: "Kod üretimi" },
          mode: mode5,
        });

  // 6 — Review + kasıtlı kırma
  const kirma = ss.filter((s) => s.break_verify.durum === "passed");
  const zayif = ss.filter((s) => s.break_verify.durum === "weak" || s.zayif_test);
  const kirmaSuruyor = ss.some((s) => s.break_verify.durum === "running");
  const merged = ss.filter((s) => s.durum === "merged" || s.pr?.durum === "merged");
  const ilkKirma = kirma[0] ?? null;
  const a6 =
    kirma.length > 0 && kirma.some((s) => merged.includes(s))
      ? adim(6, {
          hal: "tamam",
          kanit: `Test hata yakalıyor ✓ ${etiketliListe(kirma, cs)}${zayif.length ? ` · zayıf (açık kabul): ${etiketliListe(zayif, cs)}` : ""}`,
          baglanti: ilkKirma ? { yol: `/kod/${kodla(ilkKirma.id)}`, etiket: "Kırarak doğrula" } : null,
        })
      : kirma.length > 0 || kirmaSuruyor || prli.length > 0
        ? adim(6, {
            hal: "suruyor",
            kanit: kirmaSuruyor ? "Kırarak doğrulama sürüyor." : kirma.length ? `Kırarak doğrula ✓ ${etiketliListe(kirma, cs)}; merge bekleniyor.` : "PR review bekliyor.",
            ipucu: "C2'de \"Kırarak doğrula\": yeşil → kırmızı → yeşil; C1/C5 zayıf test, merge açık kabul notu ister.",
            baglanti: { yol: `/kod/${kodla((ilkKirma ?? prli[0] ?? ss[0]).id)}`, etiket: "Script" },
          })
        : adim(6, { hal: "bekliyor", kanit: "PR yok." });

  // 7 — Korumalı ana dal (merge)
  const sonMerge = enYeni(merged, (s) => s.pr?.merge_zamani ?? s.olusturma);
  const a7 = sonMerge
    ? adim(7, {
        hal: "tamam",
        kanit: `${merged.length} PR merge edildi (${etiketliListe(merged, cs)})${sonMerge.pr?.merge_eden ? ` · son: ${sonMerge.pr.merge_eden}` : ""}`,
        baglanti: { yol: `/kod/${kodla(sonMerge.id)}`, etiket: "Merge edilen PR" },
        simulator: forgeSim,
      })
    : adim(7, { hal: "bekliyor", kanit: "Merge edilmiş PR yok.", ipucu: "Mühendis: zorunlu local-ci yeşilken \"Merge et\"." });

  // 8 — CI tetikleri. Yalnızca BU story'nin koşuları sayılır: story PR'ının CI'ı ya da story'nin ilk
  // merge'ünden sonra başlayan koşular. `make reset` + `make demo-reset`in main için kuyruğa aldığı temel
  // push koşusu (story yokken) story'ye ait değildir; açılışta yol haritası 0/14 okunmalıdır.
  const tumCi = x.kosular.filter((k) => CI_TETIKLERI.has(k.tetik));
  const ci = tumCi.filter((k) => storyKosusuMu(k, ss));
  const haricCi = tumCi.length - ci.length;
  const haricNotu = haricCi > 0 ? ` (${haricCi} koşu story'den önce/ilgisiz — sayılmaz)` : "";
  const ciSim = ci.length > 0 && ci.every((k) => k.kaynak === "local") ? "simülatör: yerel CI (test-runner; GitHub Actions yerine)" : null;
  const tetikler = [...new Set(ci.map((k) => k.tetik))];
  const anaTetik = tetikler.includes("push") && (tetikler.includes("nightly") || tetikler.includes("deploy"));
  const a8 =
    ci.length === 0
      ? adim(8, {
          hal: "bekliyor",
          kanit: merged.length === 0 ? `Story'nin merge edilmiş PR'ı yok; CI koşusu story'ye sayılmaz.${haricNotu}` : `Story için CI koşusu yok.${haricNotu}`,
          baglanti: { yol: "/kosular", etiket: "Koşular" },
        })
      : adim(8, {
          hal: anaTetik ? "tamam" : "suruyor",
          kanit: `Tetikler: ${tetikler.map((t) => TETIK_ADI[t] ?? t).join(", ")} · ${ci.length} koşu`,
          ipucu: anaTetik ? null : "Sunucu: Koşular → \"Deploy tetikle\" ya da \"Gece koşusu\" (merge sonrası push CI otomatik).",
          baglanti: { yol: "/kosular", etiket: "Koşular" },
          simulator: ciSim,
        });

  // 9 — Sauce + QA (Sauce kimliği yok: yerel Chromium job'u zorunlu yedek)
  const sauce = ci.filter((k) => k.kaynak === "sauce");
  const bitenYerel = ci.filter((k) => k.kaynak !== "sauce" && ["passed", "failed"].includes(k.durum));
  const a9 =
    sauce.length > 0
      ? adim(9, { hal: "tamam", kanit: `${sauce.length} Sauce Labs koşusu`, baglanti: { yol: "/kosular", etiket: "Koşular" } })
      : bitenYerel.length > 0
        ? adim(9, {
            hal: "yedek",
            kanit: `Sauce Labs kimliği yok — yerel Chromium job'u koştu (${bitenYerel.length} koşu).`,
            ipucu: "Sahnede açıkça söyleyin: bulut tarayıcı yerine yerel yedek job (TEKNIK-TASARIM §16).",
            baglanti: { yol: "/kosular", etiket: "Koşular" },
          })
        : adim(9, { hal: "bekliyor", kanit: "Story için biten CI koşusu yok (Sauce Labs kimliği de yok)." });

  // 10 — Sonuçlar: JUnit XML + Allure
  const raporlu = enYeni(
    ci.filter((k) => k.junit_url || k.allure_url),
    (k) => k.baslangic,
  );
  const a10 = raporlu
    ? adim(10, {
        hal: "tamam",
        kanit: `JUnit${raporlu.junit_url ? " ✓" : " —"} · Allure${raporlu.allure_url ? " ✓" : " —"} (${TETIK_ADI[raporlu.tetik] ?? raporlu.tetik} koşusu)`,
        baglanti: { yol: `/kosular/${kodla(raporlu.id)}`, etiket: "Koşu raporu" },
      })
    : adim(10, { hal: "bekliyor", kanit: "Story için raporlu koşu yok." });

  // 11 — Kontrol Kulesi: story'nin sonuçları (adım 10) gelmeden "tamam" denmez.
  const a11 = !raporlu
    ? adim(11, { hal: "bekliyor", kanit: "Story'nin CI sonucu henüz yok (adım 10 bekleniyor).", baglanti: { yol: "/kontrol-kulesi", etiket: "Kontrol Kulesi" } })
    : x.kule
    ? adim(11, {
        hal: x.kule.son_kosular.length > 0 ? "tamam" : "suruyor",
        kanit:
          x.kule.son_kosular.length > 0
            ? `Geçme oranı ${x.kule.gecme_orani.oran === null ? "—" : `%${Math.round(x.kule.gecme_orani.oran * 100)}`} · ${x.kule.flaky.length} flaky`
            : "Henüz CI koşusu yok.",
        baglanti: { yol: "/kontrol-kulesi", etiket: "Kontrol Kulesi" },
      })
    : adim(11, { hal: "bekliyor", kanit: "Kontrol Kulesi verisi okunamadı.", baglanti: { yol: "/kontrol-kulesi", etiket: "Kontrol Kulesi" } });

  // 12 — Triage (story'nin script'lerinden ürün hatası)
  const storyHatalari = x.hatalar.filter((h) => (h.script_id && ssIds.has(h.script_id)) || (h.oneri?.tur === "bug_draft" && x.bugTaslaklari.some((b) => b.id === (h.oneri as { bug_draft_id: string }).bug_draft_id && b.icerik.story_key === g?.jira_key)));
  // Ana yolun anı C3 defect adayıdır (kırma koşusunun kasıtlı kırmızısı değil): önce defect adayı script'lerinin hatası.
  const defectIds = new Set(ss.filter((s) => s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate").map((s) => s.id));
  const urunHatalari = storyHatalari.filter((h) => h.sinif === "product_defect");
  const urunHatasi =
    enYeni(
      urunHatalari.filter((h) => h.script_id && defectIds.has(h.script_id)),
      (h) => h.zaman,
    ) ?? enYeni(urunHatalari, (h) => h.zaman);
  const a12 = urunHatasi
    ? adim(12, {
        hal: "tamam",
        kanit: `${urunHatasi.test_adi.slice(0, 80)} → ürün hatası (${urunHatasi.karar_kaynagi === "rule" ? "kural" : "LLM"})`,
        baglanti: { yol: `/hatalar/${kodla(urunHatasi.id)}`, etiket: "Triage" },
        mode: urunHatasi.mode,
      })
    : defect.length > 0
      ? adim(12, {
          hal: "suruyor",
          kanit: `Defect adayı ${etiketliListe(defect, cs)} triage bekliyor.`,
          baglanti: defect[0].failure_id ? { yol: `/hatalar/${kodla(defect[0].failure_id)}`, etiket: "Triage" } : { yol: `/kod/${kodla(defect[0].id)}`, etiket: "Script" },
        })
      : adim(12, { hal: "bekliyor", kanit: "Story için triage kaydı yok." });

  // 13–14 — Bug taslağı: testçi kararı ve Jira
  // Kasıtlı kırma koşusunun (break_verify / BREAK_CAMPAIGN) taslağı bilerek açık kalır: ana yolun
  // bekleyen kararı sayılmaz (Kontrol Kulesi ile aynı kural), ayrıca belirtilir.
  const tumBuglar = x.bugTaslaklari.filter((b) => g?.jira_key && b.icerik.story_key === g.jira_key);
  const kirmaTaslaklari = tumBuglar.filter((b) => kirmaTaslagiMi(b, x.hatalar, x.kosular));
  const buglar = tumBuglar.filter((b) => !kirmaTaslaklari.includes(b));
  const kararli = buglar.filter((b) => b.durum === "approved" || b.durum === "published");
  const yayinliBug = buglar.filter((b) => b.durum === "published" && (b.jira_key || b.link_key));
  const bekleyen = buglar.filter((b) => b.durum === "draft");
  const ilkBug = bekleyen[0] ?? kararli[0] ?? buglar[0] ?? null;
  // Sahne notu yalnızca ilgili kararlar hâlâ bekliyorsa (mükerrer bağlantısı yapılmışsa gösterilmez).
  const tpd5Bagli = buglar.some((b) => b.karar === "link" && (b.link_key ?? b.jira_key) === "TPD-5");
  const kirmaNotu = kirmaTaslaklari.length ? ` · ${kirmaTaslaklari.length} kasıtlı kırma taslağı (bilerek açık, sayılmaz)` : "";
  const a13 =
    buglar.length === 0
      ? adim(13, { hal: "bekliyor", kanit: `Story için bug taslağı yok.${kirmaNotu}` })
      : adim(13, {
          hal: kararli.length > 0 && bekleyen.length === 0 ? "tamam" : "suruyor",
          kanit: `${buglar.length} taslak · ${kararli.length} karar verildi${bekleyen.length ? ` · ${bekleyen.length} testçi kararı bekliyor` : ""}${kirmaNotu}`,
          ipucu: bekleyen.length
            ? tpd5Bagli
              ? "Kalan taslaklara testçi kararı verin (onayla / bağla / reddet)."
              : "Sahne: F2 ve C3 taslakları açık TPD-5'in mükerreri → \"TPD-5 kaydına bağla\"; F4 → \"Onayla ve Jira'da aç\"."
            : null,
          baglanti: ilkBug ? { yol: `/bug-taslaklari/${kodla(ilkBug.id)}`, etiket: "Bug taslağı" } : null,
          mode: ilkBug?.mode ?? null,
        });
  const a14 =
    yayinliBug.length === 0
      ? adim(14, { hal: kararli.length ? "suruyor" : "bekliyor", kanit: kararli.length ? "Jira yayını sürüyor." : "Jira'ya yazılan bug yok." })
      : adim(14, {
          hal: "tamam",
          kanit: [
            ...new Set(
              yayinliBug.map((b) => (b.karar === "link" ? `${b.link_key ?? b.jira_key}'e bağlandı` : b.jira_silindi ? `Silindi: ${b.jira_key}` : `${b.jira_key} açıldı`)),
            ),
          ].join(" · "),
          baglanti: { yol: `/bug-taslaklari/${kodla(yayinliBug[0].id)}`, etiket: "Yayın sonucu" },
          simulator: jiraSim,
        });

  return [a5, a6, a7, a8, a9, a10, a11, a12, a13, a14];
}

/** Locator yolu (TEKNIK-TASARIM §2 ikinci kırılma): yeşil temel → kır → kırmızı + triage → onarım PR'ı → merge + yeşil. */
export function locatorAdimlari(x: Pick<YolGirdisi, "demo" | "hatalar" | "kosular">): YolAdimi[] {
  const d = x.demo;
  const destek = d?.locator_demo?.destekleniyor !== false;
  const neden = d?.locator_demo?.neden ?? "Locator demosu yalnızca yerel forge'da (TP_FORGE=local).";
  const ld = d?.locator_durumu ?? null;
  const kirildi = ld === "kirik" || ld === "onarildi";
  const loc = x.hatalar.filter((h) => h.sinif === "test_maintenance");
  const onarimli = loc.filter((h) => h.oneri?.tur === "locator_fix" && ["pr_open", "merged"].includes(h.oneri.durum));
  const mergeli = onarimli.find((h) => h.oneri?.tur === "locator_fix" && h.oneri.durum === "merged") ?? null;
  const on = d?.onarim_on_kosulu ?? null;
  const yap = (no: string, ad: string, tur: YolAdimi["tur"], a: Omit<YolAdimi, "no" | "ad" | "tur">): YolAdimi => ({ no, ad, tur, ...a });
  if (!destek) {
    return [yap("L", "Locator demosu", "sistem", { hal: "engel", kanit: neden })];
  }
  const ilkLoc = enYeni(loc, (h) => h.zaman);
  return [
    yap("L1", "Yeşil temel koşu", "sistem", {
      hal: on?.hazir ? "tamam" : on?.hazir === false ? (kirildi ? "engel" : "bekliyor") : "bekliyor",
      kanit: on?.hazir
        ? on.son_yesil_kosu?.tetik || on.son_yesil_kosu?.commit
          ? `Son yeşil: ${on.son_yesil_kosu.tetik ?? "koşu"} ${on.son_yesil_kosu.commit?.slice(0, 8) ?? ""}`.trim()
          : "Yeşil temel koşu var."
        : on?.hazir === false
          ? "Yeşil temel koşu yok: kırılma reddedilir (onarım 'son yeşil yok' der)."
          : "Ön koşul bilinmiyor (çekirdek bildirmedi).",
      ipucu: on?.hazir === false ? (on.yonerge ?? "make demo-reset, yeşil koşudan sonra kırın.") : null,
      baglanti: on?.son_yesil_kosu?.run_id ? { yol: `/kosular/${kodla(on.son_yesil_kosu.run_id)}`, etiket: "Koşu" } : { yol: "/kosular", etiket: "Koşular" },
    }),
    yap("L2", "Locator'ı kır (add-to-cart → cart-add)", "insan", {
      hal: kirildi ? "tamam" : "bekliyor",
      kanit: kirildi ? `Uygulama testId: ${typeof d?.forge?.testid === "string" ? d.forge.testid : "cart-add"}` : "Main baseline'da.",
      ipucu: kirildi ? null : "Sunucu: Demo kontrolleri → \"Locator'ı kır\" (host'ta make demo-web-sync A=--watch açık) ya da make break.",
      baglanti: { yol: "/demo", etiket: "Demo kontrolleri" },
    }),
    yap("L3", "Push CI kırmızı → triage: test bakımı / locator", "ai", {
      hal: loc.length > 0 ? "tamam" : kirildi ? "suruyor" : "bekliyor",
      kanit: loc.length > 0 ? `${loc.length} hata test bakımı/locator (kural)` : kirildi ? "CI koşusu ve triage bekleniyor." : "—",
      baglanti: ilkLoc ? { yol: `/hatalar/${kodla(ilkLoc.id)}`, etiket: "Onarım önerisi" } : null,
    }),
    yap("L4", "Onarım PR'ı (yalnızca testId)", "ai", {
      hal: onarimli.length > 0 ? "tamam" : loc.length > 0 ? "suruyor" : "bekliyor",
      kanit: onarimli.length > 0 ? "Bot PR açıldı (AST koruması + tam paket yerel kontrol)." : loc.length > 0 ? "Mühendis: \"Onarım PR'ı aç\"." : "—",
      baglanti: (onarimli[0] ?? ilkLoc) ? { yol: `/hatalar/${kodla((onarimli[0] ?? ilkLoc)!.id)}`, etiket: "Onarım" } : null,
    }),
    yap("L5", "Merge → CI yeniden yeşil", "insan", {
      hal: ld === "onarildi" ? "tamam" : mergeli ? "suruyor" : "bekliyor",
      kanit: ld === "onarildi" ? "Uygulama ve testler cart-add; main CI yeşil." : mergeli ? "Merge edildi; push CI bekleniyor." : "—",
      ipucu: ld === "onarildi" ? "Tekrar prova için Demo kontrolleri → \"Demo'yu sıfırla\"." : null,
      baglanti: { yol: "/demo", etiket: "Demo kontrolleri" },
    }),
  ];
}

// ------------------------------------------------------------------ model kipi ve değerlendirme

export interface ModOzeti {
  /** "replay" | "live" | "karisik" | null (bilinmiyor). */
  mod: "replay" | "live" | "karisik" | null;
  /** Gösterilecek metin. */
  metin: string;
  /** Çekirdek mi bildirdi, gözlemden mi türetildi. */
  kaynak: "cekirdek" | "gozlem" | "yok";
  replay_miss: number;
  strict: boolean | null;
}

/**
 * Model kipi: çekirdek `/demo/status` `model` verirse o; yoksa ekrandaki çıktıların modlarından
 * (ve Kontrol Kulesi'nin REPLAY çağrı sayısından) türetilir. "live" asla varsayılmaz.
 */
export function modOzeti(x: YolGirdisi): ModOzeti {
  const gozlenen: (CiktiModu | null | undefined)[] = [
    x.gereksinim?.on_inceleme?.mode,
    x.gereksinim?.son_kontrol?.mode,
    ...x.caseler.map((c) => c.mode),
    ...x.scriptler.map((s) => s.mode),
    ...x.hatalar.map((h) => h.mode),
    ...x.bugTaslaklari.map((b) => b.mode),
  ];
  const modlar = gozlenen.filter((m): m is CiktiModu => !!m);
  const miss = modlar.filter((m) => m === "replay_miss").length;
  const strict = x.demo?.model?.replay_strict ?? null;
  const m = x.demo?.model?.mod ?? null;
  if (m) {
    const mod = m === "replay" ? "replay" : m === "live" || m === "record" ? "live" : null;
    const metin =
      m === "replay"
        ? "REPLAY — girdisi doğrulanmış hazır (golden) çıktılar; canlı model çağrısı yok"
        : m === "live"
          ? "Canlı model"
          : m === "record"
            ? "Canlı model + REPLAY kaydı"
            : `Kip: ${m}`;
    return { mod, metin, kaynak: "cekirdek", replay_miss: miss, strict };
  }
  const ai = x.kule?.ai_katkisi;
  const toplam = ai?.cagri_sayisi ?? null;
  const replay = ai?.replay_cagri ?? null;
  if (toplam !== null && replay !== null && toplam > 0) {
    if (replay === toplam) return { mod: "replay", metin: `REPLAY — ${toplam}/${toplam} AI çağrısı hazır (golden) çıktıdan`, kaynak: "gozlem", replay_miss: miss, strict };
    if (replay === 0) return { mod: "live", metin: `Canlı model — ${toplam} çağrı`, kaynak: "gozlem", replay_miss: miss, strict };
    return { mod: "karisik", metin: `Karışık — ${replay}/${toplam} çağrı REPLAY`, kaynak: "gozlem", replay_miss: miss, strict };
  }
  if (modlar.length > 0) {
    const live = modlar.filter((x) => x === "live").length;
    if (live === 0) return { mod: "replay", metin: `REPLAY — ekrandaki ${modlar.length} çıktının hepsi hazır (golden) çıktıdan`, kaynak: "gozlem", replay_miss: miss, strict };
    if (live === modlar.length) return { mod: "live", metin: "Canlı model", kaynak: "gozlem", replay_miss: miss, strict };
    return { mod: "karisik", metin: `Karışık — ${modlar.length - live}/${modlar.length} çıktı REPLAY`, kaynak: "gozlem", replay_miss: miss, strict };
  }
  return { mod: null, metin: "Bilinmiyor — henüz AI çıktısı yok, çekirdek kipi bildirmiyor", kaynak: "yok", replay_miss: miss, strict };
}

export interface DegerlendirmeOzeti {
  metin: string;
  bekleyen: number;
  toplam: number | null;
  paketler: PaketDegerlendirmesi[];
  kaynak: "cekirdek" | "gozlem" | "yok";
}

export function degerlendirmeOzeti(x: YolGirdisi): DegerlendirmeOzeti {
  const p = x.demo?.degerlendirme ?? null;
  if (p && p.length > 0) {
    const bekleyen = p.filter((d) => d.durum !== "evaluated" && d.durum !== "waived").length;
    const metin =
      bekleyen === 0
        ? `${p.length} prompt paketi canlı değerlendirildi ya da onaylı istisnada`
        : `${bekleyen}/${p.length} prompt paketi canlı değerlendirme bekliyor`;
    return { metin, bekleyen, toplam: p.length, paketler: p, kaynak: "cekirdek" };
  }
  const gozlenen = [...x.hatalar.map((h) => h.degerlendirme), ...x.bugTaslaklari.map((b) => b.degerlendirme)].filter(
    (d): d is NonNullable<typeof d> => !!d,
  );
  if (gozlenen.length > 0) {
    const bekleyen = gozlenen.filter((d) => d.durum !== "evaluated" && d.durum !== "waived").length;
    return {
      metin: bekleyen ? "Canlı değerlendirme bekliyor (triage/bug çıktılarında)" : "Gözlenen çıktıların paketleri değerlendirilmiş",
      bekleyen,
      toplam: null,
      paketler: [],
      kaynak: "gozlem",
    };
  }
  return { metin: "Bilinmiyor — çekirdek değerlendirme durumunu bildirmiyor", bekleyen: 0, toplam: null, paketler: [], kaynak: "yok" };
}

/** Tamamlanan / toplam (yedek de tamam sayılır, ama ayrıca belirtilir). */
export function ilerleme(adimlar: YolAdimi[]): { tamam: number; yedek: number; toplam: number; sonraki: YolAdimi | null } {
  const tamam = adimlar.filter((a) => a.hal === "tamam" || a.hal === "yedek").length;
  return {
    tamam,
    yedek: adimlar.filter((a) => a.hal === "yedek").length,
    toplam: adimlar.length,
    sonraki: adimlar.find((a) => a.hal !== "tamam" && a.hal !== "yedek") ?? null,
  };
}

/**
 * Gereksinimin 14 adımlı akıştaki güncel adımı. `done` sonrası (kod → bug) gereksinim durumundan
 * çıkarılamaz: yol haritasıyla aynı kanıtlardan (script, koşu, triage, bug) ilk tamamlanmamış adım.
 * Hepsi tamamsa `AKIS_ADIMLARI.length + 1` (akış tamam). Kanıt okunamadıysa (`x` null) durum adımı.
 */
export function guncelAdim(
  g: Pick<GereksinimDetay, "id" | "jira_key" | "kaynak" | "durum"> & { adim?: number | null },
  x: Omit<SonrakiGirdi, "gereksinim"> | null,
  temel: number,
): number {
  if (g.durum !== "done" || !x) return temel;
  const sonraki = sonrakiAdimlar({ ...x, gereksinim: g }).find((a) => a.hal !== "tamam" && a.hal !== "yedek");
  const turetilen = sonraki ? Number(sonraki.no) : AKIS_ADIMLARI.length + 1;
  return Math.max(temel, turetilen);
}

/**
 * `done` sonrası adım kanıtları (script, koşu, triage, bug; story'nin case'leri verilirse case bağı
 * da). Script listesi okunamazsa null: adım durumdan gösterilir (tahmin edilmez).
 */
export async function akisKanitlari(requirementId?: string): Promise<Omit<SonrakiGirdi, "gereksinim"> | null> {
  const bos = <T,>(p: Promise<T[]>) => p.catch(() => [] as T[]);
  try {
    const [scriptler, kosular, hatalar, bugTaslaklari, caseler, demo] = await Promise.all([
      api.scriptler(),
      bos(api.kosular()),
      bos(api.hatalar()),
      bos(api.bugTaslaklari()),
      requirementId ? bos(api.caseler(requirementId)) : Promise.resolve([] as TestCase[]),
      api.demoDurumu().catch(() => null),
    ]);
    const kule = await api.kontrolKulesi().catch(() => null);
    return { scriptler, kosular, hatalar, bugTaslaklari, caseler, demo, kule };
  } catch {
    return null;
  }
}

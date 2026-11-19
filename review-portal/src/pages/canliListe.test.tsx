// Canlı UX doğrulaması, liste şeridi (CL-02…CL-09): okunur metin, başarısız özeti gruplama, denetim özeti,
// satır eylemleri tek durak.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SatirEylemleri } from "../components/tasarim";
import { icTerimleriAyikla, modelCagriAmaci, tekrarsizAyrinti, testAdiGoster } from "../lib/etiketler";
import { basarisizGruplari } from "./Kosular";
import { okunurOzet } from "./Denetim";
import { forgeHatasiMetni } from "./DemoKontrolleri";

describe("CL-07 okunur metin", () => {
  it("test adındaki @tp-* etiketleri ayıklanır", () => {
    expect(testAdiGoster("TPD-1 · C3 › 6 adet kampanyalı üründe bedava ürün verilmez @tp-uretilen")).toBe(
      "TPD-1 · C3 › 6 adet kampanyalı üründe bedava ürün verilmez",
    );
    expect(testAdiGoster(null)).toBeNull();
  });

  it("S4:, REPLAY-MISS:, BREAK_CAMPAIGN, jira-sim kullanıcı diline çevrilir", () => {
    expect(icTerimleriAyikla("S4: page object'te eksik metot")).toBe("Page object'te eksik metot");
    expect(icTerimleriAyikla("Kural eşleşmedi; REPLAY-MISS: bu hata için kayıtlı model çıktısı yok")).toBe(
      "Kural eşleşmedi; bu hata için kayıtlı model çıktısı yok",
    );
    expect(icTerimleriAyikla("Kampanya bozulur (BREAK_CAMPAIGN ile aynı etki)")).toBe("Kampanya bozulur (kasıtlı kırma ile aynı etki)");
    expect(icTerimleriAyikla("jira-sim kaydı")).toBe("Jira simülatörü kaydı");
    // Bug taslağı ortamı (eski kayıtlar; core artık üretimde çeviriyor).
    expect(icTerimleriAyikla("Yerel demo ortamı (demo-app main); kampanya kırılması (BREAK_CAMPAIGN) kapalı")).toBe(
      "Yerel demo ortamı (demo-app main); kasıtlı kırma yok (normal koşu)",
    );
    expect(icTerimleriAyikla("Kampanya kırılması (BREAK_CAMPAIGN): açık")).toBe("Kampanya kuralı kasıtlı kırılmış (kırarak doğrula koşusu)");
    // Case kimliği ve S harfi geçen olağan metin dokunulmaz.
    expect(icTerimleriAyikla("TPD-1·C3 Sepet S2 boyutu")).toBe("TPD-1·C3 Sepet S2 boyutu");
  });

  it("ayrıntı başlığı tekrarlıyorsa atılır", () => {
    expect(tekrarsizAyrinti("İnsana düştü: page object'te eksik metot", "S4: page object'te eksik metot.")).toBeNull();
    expect(tekrarsizAyrinti("Defect adayı: test kırmızı", "Defect adayı: sepet toplamı 0 TL yerine 30 TL.")).toBe("Sepet toplamı 0 TL yerine 30 TL.");
    expect(tekrarsizAyrinti("İnsana düştü: ortam hatası", "Uygulama yanıt vermedi.")).toBe("Uygulama yanıt vermedi.");
  });

  it("model çağrısı amaçları okunur", () => {
    expect(["assistant", "assistant_deep", "assistant_guard"].map(modelCagriAmaci)).toEqual(["soru-cevap", "derin yanıt", "güvenlik denetimi"]);
  });

  it("demo kod deposu hatası ortam değişkeni göstermez", () => {
    const m = forgeHatasiMetni("forge kullanılamıyor: GitHub App bağlantısı yalnız core-worker'da kullanılabilir (TP_BAGLANTI_TOKENI)");
    expect(m).not.toMatch(/TP_BAGLANTI_TOKENI|core-worker|forge/);
  });
});

describe("CL-07 denetim özeti", () => {
  it("teknik kimlikler kısa özete girmez, alanlar Türkçe, pr_no → PR #n; ham JSON tam metinde", () => {
    const o = okunurOzet('{"sid":"9c1c-…","kanal":"portal","onceki":"analyst","yeni":"engineer","ai_call_id":"a1","job_id":"j1","pr_no":12,"head_sha":"abc","from":"pr_open"}');
    expect(o.kisa).toBe("Kanal: portal · Önceki: analyst · Yeni: engineer · PR #12 · Kaynak: PR açılışı");
    expect(o.kisa).not.toMatch(/sid|ai_call_id|job_id|head_sha/);
    expect(o.tam).toContain('"ai_call_id": "a1"');
    expect(okunurOzet('{"sid":"x","review_id":"r"}').kisa).toBe("Teknik ayrıntı (2 alan)");
  });
});

describe("CL-05 başarısız özeti", () => {
  it("aynı case'in testleri tek öğe: sayı + benzersiz sınıf + ilk triage", () => {
    const g = basarisizGruplari([
      { test_adi: "TPD-1 · C3 › a @tp-uretilen", case_ref: "TPD-1·C3", failure_id: null, sinif: null },
      { test_adi: "TPD-1 · C3 › b", case_ref: "TPD-1·C3", failure_id: "f2", sinif: "product_defect" },
      { test_adi: "TPD-1 · C3 › c", case_ref: "TPD-1·C3", failure_id: "f3", sinif: "product_defect" },
      { test_adi: "TPD-1 · C9 › d", case_ref: "TPD-1·C9", failure_id: null, sinif: null },
    ]);
    expect(g).toHaveLength(2);
    expect(g[0]).toMatchObject({ ad: "TPD-1·C3", sayi: 3, siniflar: ["product_defect"], failure_id: "f2" });
    expect(g[0].testler[0]).toBe("TPD-1 · C3 › a");
    expect(g[1]).toMatchObject({ ad: "TPD-1·C9", sayi: 1 });
  });
});

describe("CL-03 satır eylemleri", () => {
  it("kapalıyken tek düğme; açılınca eylemler; Esc kapatır ve odak düğmeye döner; seçimde grup kapanır", async () => {
    const u = userEvent.setup();
    const duzenle = vi.fn();
    render(
      <SatirEylemleri
        etiket="urun.p_001.ad"
        eylemler={[
          { ad: "Geçmiş", erisilebilirAd: "urun.p_001.ad sürüm geçmişi", sec: () => undefined },
          { ad: "Düzenle", erisilebilirAd: "urun.p_001.ad düzenle", sec: duzenle },
        ]}
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(1);
    const ac = screen.getByRole("button", { name: "İşlemler: urun.p_001.ad" });
    expect(ac).toHaveAttribute("aria-expanded", "false");
    await u.click(ac);
    expect(ac).toHaveAttribute("aria-expanded", "true");
    await u.tab();
    expect(screen.getByRole("button", { name: "urun.p_001.ad sürüm geçmişi" })).toHaveFocus();
    await u.keyboard("{Escape}");
    expect(ac).toHaveFocus();
    expect(screen.queryByRole("button", { name: "urun.p_001.ad düzenle" })).toBeNull();
    await u.click(ac);
    await u.click(screen.getByRole("button", { name: "urun.p_001.ad düzenle" }));
    expect(duzenle).toHaveBeenCalledOnce();
    expect(ac).toHaveFocus();
    expect(ac).toHaveAttribute("aria-expanded", "false");
  });

  it("tek eylemde açılır yok, düğme doğrudan", () => {
    render(<SatirEylemleri etiket="x" eylemler={[{ ad: "Geçmiş", erisilebilirAd: "x sürüm geçmişi", sec: () => undefined }]} />);
    expect(screen.getByRole("button", { name: "x sürüm geçmişi" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /İşlemler/ })).toBeNull();
  });
});

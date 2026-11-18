// UX denetimi (iş akışı) şerit D: IA-13 Kod üretimi nedenleri, IA-15 Koşular (sayfalama, başarısız
// test adı, kasıtlı kırma varsayılan gizli, boş durum), IA-19 Kontrol Kulesi (boş proje kartı).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import type { Script } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { dikkatNedeni, ilkCumle, scriptGrubu } from "../lib/kodDikkat";
import { basarisizAdi, BasarisizOzetSatiri, KOSU_SAYFA } from "./Kosular";
import { kuleBosMu } from "./KontrolKulesi";

const OPENAPI = { paths: Object.fromEntries(["/auth/me", "/runs", "/runs/{run_id}", "/events"].map((p) => [p, { get: {} }])) };

/** Yalnız GET yanıtları; `/runs` sorgusu (offset) çağrılarda kayıtlıdır. */
function sahteCore(runs: (offset: number) => unknown[], sorgular: URLSearchParams[] = []) {
  return vi.fn().mockImplementation((url: string) => {
    const j = (status: number, govde: unknown) => Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    if (url === "/api/openapi.json") return j(200, OPENAPI);
    if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: "muhendis", rol: "engineer" });
    const [yol, q = ""] = url.replace(/^\/api/, "").split("?");
    if (yol === "/runs") {
      const p = new URLSearchParams(q);
      sorgular.push(p);
      return j(200, runs(Number(p.get("offset") ?? 0)));
    }
    return j(404, { detail: "Not Found" });
  });
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const kosu = (i: number, ek: Record<string, unknown> = {}) => ({
  id: `${String(i).padStart(8, "0")}-0770-4afb-9f58-c9d437cf659d`,
  tetik: "nightly",
  kaynak: "local",
  commit: "abc1234",
  pr_no: null,
  durum: "passed",
  baslangic: "2026-11-18T02:00:00+00:00",
  sure_ms: 1000,
  toplam: 2,
  gecen: 2,
  basarisiz: 0,
  flaky: 0,
  atlanan: 0,
  break_campaign: false,
  script_id: null,
  saglik_hatasi: null,
  ...ek,
});

describe("IA-15 Koşular", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("başarısız koşu satırında test adı, sınıf ve Triage bağlantısı; kasıtlı kırma varsayılan gizli; sayfalama", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const sorgular: URLSearchParams[] = [];
    const ilkSayfa = [
      kosu(1, {
        durum: "failed",
        gecen: 1,
        basarisiz: 1,
        basarisiz_ozet: [{ test_adi: "TPD-1 › 7 adet → 1 bedava", case_ref: "TPD-1·C10", failure_id: "f-1", sinif: "unknown" }],
      }),
      kosu(2, { tetik: "break_verify", break_campaign: true, durum: "failed", basarisiz: 1 }),
      ...Array.from({ length: KOSU_SAYFA - 2 }, (_, i) => kosu(i + 3)),
    ];
    vi.stubGlobal("fetch", sahteCore((o) => (o === 0 ? ilkSayfa : [kosu(999)]), sorgular));
    const u = userEvent.setup();
    uygulama("/kosular");
    const ozet = await screen.findByTestId("kosu-basarisiz-ozet");
    expect(ozet).toHaveTextContent("1 başarısız: TPD-1·C10 (Belirsiz) Triage");
    expect(within(ozet).getByRole("link", { name: "TPD-1·C10 triage sonucu" })).toHaveAttribute("href", "/hatalar/f-1");
    // Kırma koşusu varsayılan gizli; kutu işaretlenince görünür.
    expect(screen.getByText(`${KOSU_SAYFA - 1}/${KOSU_SAYFA} koşu (daha eskileri var)`)).toBeInTheDocument();
    const kirma = screen.getByRole("checkbox", { name: /Kasıtlı kırma koşularını göster/ });
    expect(kirma).not.toBeChecked();
    await u.click(kirma);
    expect(await screen.findByText(`${KOSU_SAYFA}/${KOSU_SAYFA} koşu (daha eskileri var)`)).toBeInTheDocument();
    // Süzgeç varken "temizle" görünür ve süzgeci kaldırır.
    await u.click(screen.getByRole("button", { name: "Süzgeçleri temizle" }));
    expect(await screen.findByText(`${KOSU_SAYFA - 1}/${KOSU_SAYFA} koşu (daha eskileri var)`)).toBeInTheDocument();
    // Daha eski sayfa offset ile istenir ve listeye eklenir.
    await u.click(screen.getByRole("button", { name: `Daha eski ${KOSU_SAYFA} koşu` }));
    await waitFor(() => expect(sorgular.some((q) => q.get("offset") === String(KOSU_SAYFA))).toBe(true));
    expect(await screen.findByText(`${KOSU_SAYFA}/${KOSU_SAYFA + 1} koşu`)).toBeInTheDocument();
    expect(screen.queryByTestId("kosu-sayfalama")).toBeNull();
  });

  it("boş durum: ne olacak + kim + bağlantı", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore(() => []));
    uygulama("/kosular");
    expect(await screen.findByText("Henüz koşu yok.")).toBeInTheDocument();
    expect(screen.getByText(/main'e birleşince CI'da başlar \(Otomasyon Mühendisi\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kod üretimine git" })).toHaveAttribute("href", "/kod");
  });

  it("testler koşmadıysa nedeni tek satır; ad kısaltması", () => {
    render(<BasarisizOzetSatiri k={{ durum: "error", basarisiz: 0, toplam: 0, saglik_hatasi: "Uygulama ayağa kalkmadı" }} />);
    expect(screen.getByTestId("kosu-basarisiz-ozet")).toHaveTextContent("Testler koşmadı: Uygulama ayağa kalkmadı");
    expect(basarisizAdi({ test_adi: "Sepet › 7 adet → 1 bedava", case_ref: null, failure_id: null, sinif: null })).toBe("7 adet → 1 bedava");
  });
});

const script = (ek: Partial<Script>): Script => ({ id: "s1", durum: "merged", engel: null, yerel_sinif: null, mode: "live", failure_id: null, hata: null, ...ek }) as Script;

describe("IA-13 Kod üretimi: dikkat nedeni ve grup", () => {
  it("insana düşen: neden + doğru eylem; defect adayı triage'a; REPLAY-MISS ve ortam yeniden üretime", () => {
    const eksik = dikkatNedeni(script({ durum: "blocked", engel: { tur: "missing_method", neden: "S4: page object'te eksik metot. Ayrıntı." } }))!;
    expect(eksik.metin).toBe("İnsana düştü: page object'te eksik metot");
    expect(eksik.ayrinti).toBe("S4: page object'te eksik metot.");
    expect(eksik.eylem).toEqual({ tur: "baglanti", etiket: "Page object'e metot ekle (script'i aç)", yol: "/kod/s1" });
    const defect = dikkatNedeni(script({ durum: "blocked", engel: { tur: "defect_candidate", neden: null }, failure_id: "f9" }))!;
    expect(defect.eylem).toEqual({ tur: "baglanti", etiket: "Triage sonucunu aç", yol: "/hatalar/f9" });
    expect(dikkatNedeni(script({ durum: "blocked", engel: { tur: "replay_miss", neden: null } }))!.metin).toBe(
      "İnsana düştü: kayıtlı model çıktısı yok, canlı model gerekir",
    );
    expect(dikkatNedeni(script({ durum: "failed", engel: { tur: "environment", neden: "x" } }))!.eylem?.tur).toBe("yeniden_uret");
    expect(scriptGrubu(script({ durum: "merged" }))).toBe("birlesen");
    expect(scriptGrubu(script({ durum: "pr_open" }))).toBe("suren");
    expect(scriptGrubu(script({ durum: "merged" }), true)).toBe("dikkat");
    expect(ilkCumle("x".repeat(200))).toHaveLength(140);
  });
});

describe("IA-19 Kontrol Kulesi: boş proje", () => {
  it("story, koşu ve hazırlık yoksa boş sayılır", () => {
    const bos = { karne: [], son_kosular: [], hazirlik: [], gecme_orani: { toplam: 0 } } as unknown as Parameters<typeof kuleBosMu>[0];
    expect(kuleBosMu(bos)).toBe(true);
    expect(kuleBosMu({ ...bos, gecme_orani: { toplam: 3 } } as unknown as Parameters<typeof kuleBosMu>[0])).toBe(false);
  });
});

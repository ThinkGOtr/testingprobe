// Portal review bulgularının düzeltmeleri (2. tur): denetim sürerken/hata ile bitince "tutarlı"
// denmemesi, AC eksik story'de ön inceleme açık / case üretimi kapalı, karar değişince eski doğrulama
// mesajı, Önce/Sonra farkı, ölçülmemiş review süresi, case düzeltme formu ve yayında kapsam uyarısı.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, hataMesaji } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import type { GereksinimDetay as Detay } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { BulguKarti } from "../components/BulguKarti";
import { CaseKarti } from "../components/CaseKarti";
import { FarkGorunumu } from "../components/FarkGorunumu";
import { degisimOrani, kelimeFarki, ONCE_SONRA_ESIGI } from "../lib/diff";
import { oturumAc, sar } from "../test/yardimci";
import {
  AC_YOK_CASE_URETILEMEZ,
  bosBulguMetni,
  caseUretHatasi,
  DENETIM_HATALI,
  DENETIM_SURUYOR,
  DENETIM_TAMAMLANMADI,
} from "./GereksinimDetay";

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

const gereksinim = (id: string) => mockVerisi().gereksinimler.find((g) => g.id === id)! as Detay;
const TUTARLI = "Bulgu yok: doküman kod ve veriyle tutarlı.";

describe("tutarlılık kartı: tamamlanmamış denetim 'tutarlı' sayılmaz", () => {
  const temiz = { mode: "replay" as const, bulgu: 0, dogrulanan: 0, elenen: 0, zaman: null };

  it("in_review: 'Denetim sürüyor' (son_kontrol null ya da önceki turdan kalmış olsa da)", () => {
    expect(bosBulguMetni({ durum: "in_review", kontrol_turu: 1, son_kontrol: null } as unknown as Detay, 0, 0)).toBe(DENETIM_SURUYOR);
    expect(bosBulguMetni({ durum: "in_review", kontrol_turu: 2, son_kontrol: temiz } as unknown as Detay, 0, 0)).toBe(DENETIM_SURUYOR);
    expect(bosBulguMetni({ durum: "in_review", kontrol_turu: 0, son_kontrol: null } as unknown as Detay, 0, 0)).toBe(DENETIM_SURUYOR);
  });

  it("failed: 'tamamlanmadı' — önceki temiz koşu kaydı olsa bile tutarlı denmez", () => {
    expect(bosBulguMetni({ durum: "failed", kontrol_turu: 1, son_kontrol: null } as unknown as Detay, 0, 0)).toBe(DENETIM_HATALI);
    expect(bosBulguMetni({ durum: "failed", kontrol_turu: 1, son_kontrol: temiz } as unknown as Detay, 0, 0)).toBe(DENETIM_HATALI);
    expect(DENETIM_HATALI).toMatch(/tutarlılık doğrulanmadı/);
  });

  it("kontrol turu var ama tamamlanmış koşu kaydı (son_kontrol) yok: tamamlanmadı", () => {
    expect(bosBulguMetni({ durum: "findings_open", kontrol_turu: 1, son_kontrol: null } as unknown as Detay, 0, 0)).toBe(
      DENETIM_TAMAMLANMADI,
    );
    expect(bosBulguMetni({ durum: "pending_po", kontrol_turu: 1 } as unknown as Detay, 0, 0)).toBe(DENETIM_TAMAMLANMADI);
  });

  it("'tutarlı' yalnızca tamamlanmış, REPLAY-MISS olmayan ve eleme olmayan koşuda", () => {
    expect(bosBulguMetni({ durum: "pending_po", kontrol_turu: 1, son_kontrol: temiz } as unknown as Detay, 0, 0)).toBe(TUTARLI);
    expect(
      bosBulguMetni({ durum: "pending_po", kontrol_turu: 1, son_kontrol: { ...temiz, mode: "live" } } as unknown as Detay, 0, 0),
    ).toBe(TUTARLI);
  });

  it("ekran: denetim sürerken boş kart 'Denetim sürüyor' der ve dönen gösterge taşır, 'tutarlı' demez", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-ft-1");
    g.durum = "in_review";
    g.son_kontrol = null;
    for (const b of mockVerisi().bulgular) if (b.requirement_id === "req-ft-1") b.durum = "discarded";
    uygulama("/gereksinimler/req-ft-1");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    const bos = await within(kart).findByTestId("bulgu-bos");
    expect(bos).toHaveTextContent(DENETIM_SURUYOR);
    expect(within(bos).getByRole("status")).toBeInTheDocument();
    expect(within(kart).queryByText(TUTARLI)).toBeNull();
  });

  it("ekran: iş hata ile bittiyse (failed) 'tamamlanmadı' der, 'tutarlı' demez", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-ft-1");
    g.durum = "failed";
    g.son_kontrol = null;
    g.elenen_bulgu = 0;
    mockVerisi().bulgular = mockVerisi().bulgular.filter((b) => b.requirement_id !== "req-ft-1");
    uygulama("/gereksinimler/req-ft-1");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    expect(await within(kart).findByTestId("bulgu-bos")).toHaveTextContent(DENETIM_HATALI);
    expect(within(kart).queryByText(TUTARLI)).toBeNull();
  });
});

describe("kabul kriteri eksik story (TPD-2): ön inceleme açık, case üretimi kapalı", () => {
  it("'Ön incelemeyi başlat' etkin; tıklayınca PO soruları için inceleme başlar", async () => {
    await oturumAc("analist");
    const casus = vi.spyOn(api, "incelemeBaslat");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-2");
    const dugme = await screen.findByRole("button", { name: "Ön incelemeyi başlat" });
    await waitFor(() => expect(dugme).toBeEnabled());
    expect(dugme).toHaveAttribute("title", expect.stringContaining("PO'ya sorar"));
    await u.click(dugme);
    await waitFor(() => expect(casus).toHaveBeenCalledWith("req-tpd-2"));
    // Mock core gibi davranır: AC eksik story incelemeye alınır, PO soruları üretilir (golden TPD-2).
    await waitFor(() => expect(gereksinim("req-tpd-2").on_inceleme).not.toBeNull(), { timeout: 3000 });
    expect(gereksinim("req-tpd-2").son_kontrol).toMatchObject({ mode: "replay" });
  });

  it("PO onaylı olsa da üretim düğmesi pasif ve nedeni söylenir", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-2");
    g.durum = "po_approved";
    g.po = { durum: "approved", onaylayan: "po", zaman: "2026-10-30T10:00:00Z", kanal: "jira" };
    uygulama("/gereksinimler/req-tpd-2");
    const dugme = await screen.findByRole("button", { name: "Tasarım modelini üret (iki tur)" });
    expect(dugme).toBeDisabled();
    expect(dugme).toHaveAttribute("title", AC_YOK_CASE_URETILEMEZ);
  });

  it("core 422 (ac_missing) mesajı alan öneki ve iç kod olmadan Türkçe gösterilir", () => {
    const ham = new ApiError(422, "requirement: kabul kriteri eksik (ac_missing) gereksinim case üretimine gönderilmez");
    let yakalanan: unknown;
    try {
      caseUretHatasi(ham);
    } catch (e) {
      yakalanan = e;
    }
    const mesaj = hataMesaji(yakalanan);
    expect(mesaj).not.toMatch(/requirement:|ac_missing/);
    expect(mesaj).toMatch(/^Kabul kriteri olmayan gereksinimden case üretilemez/);
    // Diğer hatalar aynen geçer.
    const diger = new ApiError(409, "Bu durumda case üretilemez.");
    expect(() => caseUretHatasi(diger)).toThrow(diger);
  });
});

describe("bulgu kararı: karar değişince eski doğrulama mesajı kalmaz", () => {
  it("Bilinçli fark (gerekçesiz) → hata; 'Dokümanı düzelt' seçilince hata silinir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-5")!} guncellendi={() => {}} />);
    await u.click(await screen.findByLabelText("Bilinçli fark"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Kararı kaydet" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Kararı kaydet" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Bilinçli fark için gerekçe zorunludur.");
    await u.click(screen.getByLabelText("Dokümanı düzelt"));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Bilinçli fark için gerekçe zorunludur.")).toBeNull();
  });
});

describe("fark görünümü: büyük yeniden yazımda Önce / Sonra", () => {
  it("küçük düzeltme (7 → 6) kelime farkı olarak kalır", () => {
    const eski = "AC2: 7 adet alana 1 adet bedava verilir.";
    const yeni = "AC2: 6 adet alana 1 adet bedava verilir.";
    expect(degisimOrani(kelimeFarki(eski, yeni))).toBeLessThan(ONCE_SONRA_ESIGI);
    sar(<FarkGorunumu eski={eski} yeni={yeni} />);
    expect(screen.queryByTestId("fark-once-sonra")).toBeNull();
    expect(screen.getByLabelText("Önerilen değişiklik farkı").querySelector("ins")).toHaveTextContent("6");
  });

  it("çoğu değişen metin iki satır gösterilir: Önce (silinen) / Sonra (eklenen)", () => {
    const eski = "Sepette 7 adet kampanyalı ürün varsa bir tanesi ücretsiz olur.";
    const yeni = "Kampanya kapsamındaki her 6 adet üründen biri bedava; indirim sepet toplamından düşülür.";
    expect(degisimOrani(kelimeFarki(eski, yeni))).toBeGreaterThan(ONCE_SONRA_ESIGI);
    sar(<FarkGorunumu eski={eski} yeni={yeni} />);
    const kutu = screen.getByTestId("fark-once-sonra");
    expect(within(kutu).getByText("Önce")).toBeInTheDocument();
    expect(within(kutu).getByText("Sonra")).toBeInTheDocument();
    expect(kutu.querySelector("del")).toHaveTextContent(eski);
    expect(kutu.querySelector("ins")).toHaveTextContent(yeni);
  });

  it("değişiklik yoksa oran 0", () => {
    expect(degisimOrani(kelimeFarki("aynı metin", "aynı metin"))).toBe(0);
    expect(degisimOrani([])).toBe(0);
  });
});

describe("case review özeti: ölçülmeyen süre '0 ms' değil '—'", () => {
  it("hiç review süresi ölçülmediyse Review süresi '—' ve 'henüz ölçülmedi'", async () => {
    await oturumAc("analist");
    for (const c of mockVerisi().caseler) if (c.requirement_id === "req-tpd-1") c.review_sure_ms = null;
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const etiket = await screen.findByText("Review süresi");
    const kutu = etiket.closest(".metrik") as HTMLElement;
    await waitFor(() => expect(within(kutu).getByText("henüz ölçülmedi")).toBeInTheDocument());
    expect(kutu.querySelector(".metrik-deger")).toHaveTextContent(/^—$/);
    expect(kutu).not.toHaveTextContent("0 ms");
  });
});

describe("case düzeltme formu", () => {
  it("adım alanları çok satırlı; ön koşul, tür, risk ve AC atfı düzeltilip gönderilir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    const tc = mockVerisi().caseler.find((c) => c.id === "case-1-5")!;
    sar(<CaseKarti tc={tc} guncellendi={guncellendi} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    for (const ad of ["S1 eylem", "S1 veri", "S1 beklenen"]) expect(screen.getByLabelText(ad).tagName).toBe("TEXTAREA");
    const onKosul = screen.getByLabelText(/Ön koşullar/);
    await u.clear(onKosul);
    await u.type(onKosul, "Kullanıcı giriş yapmış{enter}Sepet boş");
    await u.selectOptions(screen.getByLabelText("Tür"), "boundary");
    await u.selectOptions(screen.getByLabelText("Risk"), "low");
    const ac = screen.getByLabelText("Kabul kriteri atıfları");
    await u.clear(ac);
    await u.type(ac, "ac2, AC3");
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const [, girdi] = spy.mock.calls[0];
    expect(girdi.karar).toBe("edit");
    expect(girdi.icerik).toMatchObject({
      preconditions: ["Kullanıcı giriş yapmış", "Sepet boş"],
      type: "boundary",
      risk: "low",
      acceptance_criteria_refs: ["AC2", "AC3"],
    });
  });

  it("AC atfı boşsa gönderilmez, Türkçe uyarı verir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    const u = userEvent.setup();
    sar(<CaseKarti tc={mockVerisi().caseler.find((c) => c.id === "case-1-5")!} guncellendi={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    await u.clear(screen.getByLabelText("Kabul kriteri atıfları"));
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    expect(screen.getByRole("alert")).toHaveTextContent("En az bir kabul kriteri atfı gerekir");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("yayın önizleme: kapsanmayan kabul kriteri uyarısı", () => {
  it("bir AC'nin tek case'i reddedilmişse yayın ekranı uyarır", async () => {
    await oturumAc("analist");
    // req-tpd-1'de AC2'ye atıf yapan tüm case'ler reddedilmiş olsun.
    for (const c of mockVerisi().caseler) {
      if (c.requirement_id === "req-tpd-1" && c.icerik.acceptance_criteria_refs.includes("AC2")) c.durum = "rejected";
    }
    expect((await api.caseMetrikleri("req-tpd-1")).kapsanmayan_ac).toEqual(["AC2"]);
    uygulama("/gereksinimler/req-tpd-1/yayin");
    const uyari = await screen.findByTestId("yayin-kapsam-uyarisi");
    expect(uyari).toHaveTextContent("Kapsanmayan kabul kriteri");
    expect(uyari).toHaveTextContent("AC2");
    expect(uyari).toHaveTextContent("test edilmemiş kalır");
  });

  it("tüm AC'ler kapsanıyorsa uyarı yok", async () => {
    await oturumAc("analist");
    expect((await api.caseMetrikleri("req-tpd-1")).kapsanmayan_ac).toEqual([]);
    uygulama("/gereksinimler/req-tpd-1/yayin");
    await screen.findByTestId("yayin-hedefi");
    expect(screen.queryByTestId("yayin-kapsam-uyarisi")).toBeNull();
    expect(screen.queryByText(/Dry-run/)).toBeNull();
  });
});

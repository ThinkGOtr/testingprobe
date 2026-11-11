import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { mockVerisi } from "../api/mock/handlers";
import { oturumAc, sar } from "../test/yardimci";
import { BulguKarti } from "./BulguKarti";
import { CaseKarti } from "./CaseKarti";
import { FarkGorunumu } from "./FarkGorunumu";
import { KodGorunumu } from "./KodGorunumu";
import { AkisAdimlari } from "./AkisAdimlari";
import { ReplayRozeti } from "./ui";

describe("ReplayRozeti", () => {
  it("live için hiçbir şey, replay ve replay_miss için ayrı rozet gösterir", () => {
    const { container, rerender } = render(<ReplayRozeti mode="live" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ReplayRozeti mode="replay" />);
    expect(screen.getByText("REPLAY")).toHaveClass("rozet-replay");
    rerender(<ReplayRozeti mode="replay_miss" />);
    expect(screen.getByText("REPLAY-MISS")).toHaveClass("rozet-replay-miss");
  });
});

describe("AkisAdimlari", () => {
  it("14 adımı ve şu anki adımı gösterir", () => {
    render(<AkisAdimlari adim={6} />);
    const adimlar = screen.getAllByRole("listitem");
    expect(adimlar).toHaveLength(14);
    expect(adimlar[5]).toHaveAttribute("aria-current", "step");
    expect(adimlar[5]).toHaveTextContent("Review + kırma");
    expect(adimlar[0]).toHaveTextContent("tamamlandı");
  });
});

describe("KodGorunumu ve FarkGorunumu", () => {
  it("kodu metin olarak basar (HTML yorumlanmaz) ve satırı vurgular", () => {
    const { container } = render(<KodGorunumu kod={'const x = "<b>kalın</b>";\nbedava = adet // 6'} baslangicSatiri={13} vurguSatiri={14} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain('"<b>kalın</b>"');
    expect(container.querySelector(".kod-vurgu")?.textContent).toContain("14");
  });

  it("farkı ins/del ile gösterir", () => {
    const { container } = render(<FarkGorunumu eski="tutar 500,00 TL" yeni="tutar 750,00 TL" />);
    expect(container.querySelector("del")?.textContent).toContain("500,00");
    expect(container.querySelector("ins")?.textContent).toContain("750,00");
  });
});

describe("BulguKarti", () => {
  it("kanıtı (dosya:satır ve kod) ve doğrulama rozetini gösterir", async () => {
    await oturumAc("analist");
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-5")!} guncellendi={() => {}} />);
    expect(await screen.findByText("api/src/demoapp_api/campaign.py:23")).toBeInTheDocument();
    expect(screen.getByText("demo-app")).toBeInTheDocument();
    expect(screen.getByText(/kanıt doğrulandı/)).toBeInTheDocument();
    expect(screen.getByText("REPLAY")).toBeInTheDocument();
  });

  it("bilinçli fark gerekçesiz gönderilmez; gerekçeyle kaydedilir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "bulguKarari");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-6")!} guncellendi={guncellendi} />);
    await u.click(await screen.findByLabelText("Bilinçli fark"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Kararı kaydet" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Kararı kaydet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("gerekçe zorunludur");
    expect(spy).not.toHaveBeenCalled();

    await u.type(screen.getByLabelText(/Gerekçe/), "Ürün kararı");
    await u.click(screen.getByRole("button", { name: "Kararı kaydet" }));
    await waitFor(() => expect(guncellendi).toHaveBeenCalled());
    // Gösterilen bulgunun hash'i karar gövdesindedir (TOCTOU bağı).
    const h = mockVerisi().bulgular.find((b) => b.id === "fnd-6")!.icerik_hash;
    expect(h).toMatch(/^sha256:/);
    expect(spy).toHaveBeenCalledWith("fnd-6", { icerik_hash: h, karar: "accept_difference", gerekce: "Ürün kararı" });
  });

  it("dokümanı düzelt: düzenlenen metni ve farkı gösterir, metni gönderir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "bulguKarari");
    const u = userEvent.setup();
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-6")!} guncellendi={() => {}} />);
    await u.click(await screen.findByLabelText("Dokümanı düzelt"));
    const alan = screen.getByLabelText(/Önerilen doküman metni/);
    // Golden SERBEST F2 önerisi (AC öneki atılmış) aynen.
    expect(alan).toHaveValue(mockVerisi().bulgular.find((b) => b.id === "fnd-6")!.suggested_doc_text);
    // Öneri metni büyük ölçüde yeniden yazdığı için fark "Önce / Sonra" görünümünde (eklenen: Sonra).
    const eklenen = [...screen.getByLabelText(/^Önerilen değişiklik/).querySelectorAll("ins")].map((x) => x.textContent).join(" ");
    expect(eklenen).toContain("750,00");
    await u.clear(alan);
    await u.type(alan, "Sepet tutarı 750,00 TL altındaysa uyarı gösterilir.");
    await waitFor(() => expect(screen.getByRole("button", { name: "Kararı kaydet" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Kararı kaydet" }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("fnd-6", {
        icerik_hash: mockVerisi().bulgular.find((b) => b.id === "fnd-6")!.icerik_hash,
        karar: "fix_doc",
        metin: "Sepet tutarı 750,00 TL altındaysa uyarı gösterilir.",
      }),
    );
  });

  it("eski hash'le karar 409 alınca yeniden yükler ve 'İçerik değişti' der", async () => {
    await oturumAc("analist");
    const yenile = vi.fn();
    const u = userEvent.setup();
    const bulgu = { ...mockVerisi().bulgular.find((b) => b.id === "fnd-5")!, icerik_hash: "sha256:eski0000000000" };
    sar(<BulguKarti bulgu={bulgu} guncellendi={() => {}} yenile={yenile} />);
    await u.click(await screen.findByLabelText("Kod/veri hatalı"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Kararı kaydet" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Kararı kaydet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("İçerik değişti, yeniden inceleyin.");
    expect(yenile).toHaveBeenCalledTimes(1);
    expect(mockVerisi().bulgular.find((b) => b.id === "fnd-5")!.karar).toBeNull();
  });

  it("kanıtı doğrulanmamış (unverified) bulgu doğrulanmış görünmez ve karar formu açmaz", async () => {
    await oturumAc("analist");
    const bulgu = { ...mockVerisi().bulgular.find((b) => b.id === "fnd-5")!, durum: "unverified" as const };
    sar(<BulguKarti bulgu={bulgu} guncellendi={() => {}} />);
    expect(screen.queryByText(/kanıt doğrulandı/)).toBeNull();
    expect(screen.getByText("kanıt doğrulanamadı")).toBeInTheDocument();
    expect(screen.getByText("Kanıt doğrulanmadı")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("karar verilemez");
    expect(screen.queryByRole("button", { name: "Kararı kaydet" })).toBeNull();
  });

  it("fix_doc yazılmış (resolved) bulgu 'Jira'ya yazıldı' gösterir, karar değiştirilemez", async () => {
    await oturumAc("analist");
    // fnd-2 (F3 min tutar): ana yolda fix_doc kararı Jira'ya yazılmış bulgu.
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-2")!} guncellendi={() => {}} />);
    expect(screen.getByText("Jira'ya yazıldı")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kararı değiştir" })).toBeNull();
  });

  it("veri kanıtının sorgu sonucu (dar ekranda yatay kayar) klavyeyle odaklanır: adlı bölge, tabindex 0", async () => {
    await oturumAc("analist");
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-2")!} guncellendi={() => {}} />);
    const sonuc = screen.getByRole("region", { name: "Sorgu sonucu" });
    expect(sonuc.tagName).toBe("PRE");
    expect(sonuc).toHaveAttribute("tabindex", "0");
    expect(screen.getAllByRole("region", { name: "Sorgu sonucu" })).toHaveLength(1);
  });

  it("analist olmayan rolde karar düğmesi pasif ve nedenini söyler", async () => {
    await oturumAc("testci");
    sar(<BulguKarti bulgu={mockVerisi().bulgular.find((b) => b.id === "fnd-5")!} guncellendi={() => {}} />);
    const d = await screen.findByRole("button", { name: "Kararı kaydet" });
    await waitFor(() => expect(d).toHaveAttribute("title", "Bu işlem için gereken rol: Analist"));
    expect(d).toBeDisabled();
  });
});

describe("CaseKarti", () => {
  it("ret nedeni seçmeden reddetmez; taksonomiden seçilince gönderir", async () => {
    await oturumAc("testci");
    const spy = vi.spyOn(api, "caseKarari");
    const u = userEvent.setup();
    const tc = mockVerisi().caseler.find((c) => c.id === "case-1-5")!;
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByText("REPLAY")).toBeInTheDocument();
    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Reddet" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Reddet" }));
    await u.click(screen.getByRole("button", { name: "Reddi kaydet" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Ret nedeni seçilmelidir");
    expect(spy).not.toHaveBeenCalled();
    const secenekler = within(screen.getByLabelText("Ret nedeni")).getAllByRole("option").map((o) => o.textContent);
    expect(secenekler).toEqual(["Seçin…", "Halüsinasyon adımı", "Eksik kabul kriteri", "Yanlış test verisi", "Kapsam dışı", "Tekrar", "Yanlış eleman/aksiyon"]);
    await u.selectOptions(screen.getByLabelText("Ret nedeni"), "wrong_test_data");
    await u.click(screen.getByRole("button", { name: "Reddi kaydet" }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("case-1-5", { icerik_hash: tc.icerik_hash, karar: "reject", ret_nedeni: "wrong_test_data" }),
    );
  });

  it("düzeltme: adımları düzenleyip edit kararı gönderir", async () => {
    await oturumAc("testci");
    const spy = vi.spyOn(api, "caseKarari");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    const tc = mockVerisi().caseler.find((c) => c.id === "case-1-5")!;
    const gorulenHash = tc.icerik_hash; // tc canlı mock nesnesi: karardan sonra hash değişir
    sar(<CaseKarti tc={tc} guncellendi={guncellendi} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelterek kabul" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelterek kabul" }));
    const veri = screen.getByLabelText("S1 veri");
    await u.clear(veri);
    await u.type(veri, "81");
    await u.click(screen.getByRole("button", { name: "Düzeltip kabul et" }));
    await waitFor(() => expect(guncellendi).toHaveBeenCalled());
    const [, girdi] = spy.mock.calls[0];
    expect(girdi.karar).toBe("edit");
    // Düzeltmede de düzeltme ÖNCESİ (ekranda görülen) içeriğin hash'i gider.
    expect(girdi.icerik_hash).toBe(gorulenHash);
    expect(girdi.icerik?.steps[0].data).toBe("81");
  });

  it("eski hash'le kabul 409 alınca listeyi yeniden yükler ve 'İçerik değişti' der", async () => {
    await oturumAc("testci");
    const yenile = vi.fn();
    const u = userEvent.setup();
    const tc = { ...mockVerisi().caseler.find((c) => c.id === "case-1-7")!, icerik_hash: "sha256:eski0000000000" };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} yenile={yenile} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Kabul et" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Kabul et" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("İçerik değişti, yeniden inceleyin.");
    expect(yenile).toHaveBeenCalledTimes(1);
    expect(mockVerisi().caseler.find((c) => c.id === "case-1-7")!.durum).toBe("draft");
  });

  it("yerini yenisi alan (superseded) case için karar düğmesi göstermez", async () => {
    await oturumAc("analist");
    const tc = { ...mockVerisi().caseler.find((c) => c.id === "case-1-7")!, durum: "superseded" as const };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByText("Yerini yenisi aldı")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
  });

  it("yayınlanmış case için karar düğmesi göstermez", async () => {
    await oturumAc("analist");
    sar(<CaseKarti tc={mockVerisi().caseler.find((c) => c.id === "case-1-1")!} guncellendi={() => {}} />);
    expect(screen.getByText("TPD-9")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
  });

  // core test_case makinesi: Testçi kararı yalnızca draft'tan (rejected → ready, approved → rejected yok).
  it.each([
    ["rejected", "Reddedildi"],
    ["approved", "Onaylı"],
    ["ready", "Onaya hazır"],
  ] as const)("%s case (Testçi): Kabul/Düzelt/Reddet gösterilmez, yalnızca 'Taslağa al'; istek gitmez", async (durum, etiket) => {
    await oturumAc("testci");
    const spy = vi.spyOn(api, "caseKarari");
    const tc = { ...mockVerisi().caseler.find((c) => c.id === "case-1-7")!, durum };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByText(etiket)).toBeInTheDocument();
    // Rol yüklendikten sonra da karar düğmeleri yok (pasif düğme "Yeniden aç"ın yanında kafa karıştırıyordu).
    await waitFor(() => expect(screen.getByRole("button", { name: "Taslağa al" })).toBeEnabled());
    for (const ad of ["Kabul et", "Düzelterek kabul", "Reddet"]) expect(screen.queryByRole("button", { name: ad })).toBeNull();
    // Son onay düğmeleri Testçide etkin değil.
    if (durum === "ready") expect(screen.getByRole("button", { name: "Onayla" })).toBeDisabled();
    else expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByTestId("case-karar-kilit")).toHaveTextContent("taslağa alın");
  });

  it("taslak case (Testçi): üç karar da açık, son onay düğmesi ve kilit notu yok", async () => {
    await oturumAc("testci");
    sar(<CaseKarti tc={mockVerisi().caseler.find((c) => c.id === "case-1-7")!} guncellendi={() => {}} />);
    for (const ad of ["Kabul et", "Düzelterek kabul", "Reddet"]) await waitFor(() => expect(screen.getByRole("button", { name: ad })).toBeEnabled());
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
    expect(screen.queryByTestId("case-karar-kilit")).toBeNull();
  });

  it("taslak case (Analist): Testçi kararları pasif ve nedenini söyler; son onay yok", async () => {
    await oturumAc("analist");
    sar(<CaseKarti tc={mockVerisi().caseler.find((c) => c.id === "case-1-7")!} guncellendi={() => {}} />);
    const kabul = await screen.findByRole("button", { name: "Kabul et" });
    await waitFor(() => expect(kabul).toBeDisabled());
    expect(kabul).toHaveAttribute("data-yetkisiz", "true");
    expect(screen.getByText("Bu işlem için gereken rol: Testçi")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
  });

  it("onaya hazır case (Analist): Onayla gönderir; Geri gönder gerekçesiz gitmez", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari").mockImplementation(async (id, g) => ({ ...tc, id, durum: g.karar === "approve" ? "approved" : "draft" }));
    const u = userEvent.setup();
    const tc = { ...mockVerisi().caseler.find((c) => c.id === "case-1-7")!, durum: "ready" as const, karar: "accept" as const };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByText("Onaya hazır")).toBeInTheDocument();
    for (const ad of ["Kabul et", "Düzelterek kabul", "Reddet"]) expect(screen.queryByRole("button", { name: ad })).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Geri gönder" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Geri gönder" }));
    const form = screen.getByTestId("geri-gonder-formu");
    await u.click(within(form).getByRole("button", { name: "Geri gönder" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("gerekçesi zorunludur");
    expect(spy).not.toHaveBeenCalled();
    await u.type(within(form).getByLabelText("Geri gönderme gerekçesi"), "AC2 adımı eksik");
    await u.click(within(form).getByRole("button", { name: "Geri gönder" }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("case-1-7", { icerik_hash: tc.icerik_hash, karar: "send_back", gerekce: "AC2 adımı eksik" }),
    );
    spy.mockClear();
    await u.click(await screen.findByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("case-1-7", { icerik_hash: tc.icerik_hash, karar: "approve" }));
    spy.mockRestore();
  });

  it("developer: salt okunur; karar düğmesi, karar geçmişi ve AI farkı yok", async () => {
    await oturumAc("gelistirici");
    const tc = {
      ...mockVerisi().caseler.find((c) => c.id === "case-1-7")!,
      durum: "approved" as const,
      karar_veren: "testci",
      karar_zamani: "2026-11-10T10:00:00Z",
      fark: [{ alan: "title", etiket: "Başlık", once: "a", sonra: "b" }],
    };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByText("Onaylı")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryAllByRole("button")).toHaveLength(0));
    expect(screen.queryByTestId("case-fark")).toBeNull();
    expect(screen.queryByTestId("case-karar-kilit")).toBeNull();
    expect(screen.queryByText(/Fatih Arslan/)).toBeNull();
  });
});

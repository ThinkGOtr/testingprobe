// 012 Ş7 — triage alt türü `beklenti` (Ş3, ANALIZ §4.4): etiket, "Case düzeltilmeli" kutusu;
// ilişkiden türetilen case çipi; `karar_tablosu.updated` olayı.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../../App";
import { olayKonulari } from "../../api/events";
import { mockVerisi } from "../../api/mock/handlers";
import { altTurEtiketi, KARAR_TABLOSU_SINYALI, sinyalBasligi } from "../../lib/etiketler";
import { OturumProvider } from "../../auth";
import { BildirimProvider } from "../../components/Bildirim";
import { oturumAc } from "../../test/yardimci";

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

describe("triage: test beklentisi (karar tablosu)", () => {
  it("alt tür etiketi; bilinmeyen alt tür ham kalır; sinyal etiketleri", () => {
    expect(altTurEtiketi("beklenti")).toBe("Test beklentisi (karar tablosu)");
    expect(altTurEtiketi("locator")).toBe("locator");
    expect(altTurEtiketi(null)).toBeNull();
    expect(Object.keys(KARAR_TABLOSU_SINYALI)).toEqual([
      "karar_tablosu_uyumlu",
      "karar_tablosu_beklenti_farkli",
      "karar_tablosu_ikisi_de_farkli",
      "karar_tablosu_tablo_suphesi",
    ]);
    expect(KARAR_TABLOSU_SINYALI.karar_tablosu_tablo_suphesi).toBe("Tablo da yanlış olabilir");
  });

  it("sinyal başlığı (R3): core `baslik` başlık, `aciklama` ayrıntı; başlık yoksa karar tablosu etiketi; diğer sinyal tek satır", () => {
    expect(sinyalBasligi({ kod: "karar_tablosu_uyumlu", baslik: "Uygulama onaylı kurala aykırı (T1 · R2: adet 6 → bedava_adet 0)", aciklama: "ayrıntı" })).toEqual({
      baslik: "Uygulama onaylı kurala aykırı (T1 · R2: adet 6 → bedava_adet 0)",
      ayrinti: "ayrıntı",
    });
    expect(sinyalBasligi({ kod: "karar_tablosu_beklenti_farkli", aciklama: "uzun teknik metin" })).toEqual({
      baslik: "Uygulama onaylı karar tablosuyla aynı; test beklentisi farklı",
      ayrinti: "uzun teknik metin",
    });
    expect(sinyalBasligi({ kod: "health_ok", aciklama: "Sağlık kontrolü başarılı" })).toEqual({ baslik: "Sağlık kontrolü başarılı", ayrinti: null });
  });

  it("HataDetay (C3 defect adayı): karar tablosu sinyali tek satır başlıkla, ayrıntı altında; beklenti için bug taslağı düğmesi eklenmez", async () => {
    await oturumAc("analist");
    uygulama("/hatalar/fail-4");
    const sinyal = await screen.findByTestId("sinyal-karar_tablosu_uyumlu");
    expect(within(sinyal).getByText("Uygulama onaylı kurala aykırı (T1 · R2: adet 6 → bedava_adet 0)").tagName).toBe("STRONG");
    expect(sinyal).toHaveTextContent(/Test beklentisi 0, gerçekleşen 1, onaylı karar tablosu \(T1, satır R2\) 0/);
    // Diğer sinyaller değişmeden tek satır.
    expect(within(screen.getByTestId("sinyal-health_ok")).getByText("Koşu öncesi sağlık kontrolü başarılı")).toBeInTheDocument();
  });

  it("HataDetay: 'Case düzeltilmeli' kutusu case'e bağlanır; 'Öneri üretilmedi' gösterilmez", async () => {
    await oturumAc("analist");
    const h = mockVerisi().hatalar.find((x) => x.id === "fail-2")!;
    Object.assign(h, {
      sinif: "test_maintenance",
      alt_tur: "beklenti",
      oneri: null,
      oneri_yok_nedeni: "Case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor; case düzeltilmeli",
      case_id: "case-1-2",
      requirement_id: "req-tpd-1",
    });
    uygulama("/hatalar/fail-2");
    expect(await screen.findByTestId("triage-alt-tur")).toHaveTextContent("Test beklentisi (karar tablosu)");
    const kutu = screen.getByTestId("case-duzeltilmeli");
    expect(within(kutu).getByText("Case düzeltilmeli")).toBeInTheDocument();
    expect(within(kutu).getByRole("link", { name: /Case'i aç/ })).toHaveAttribute("href", "/gereksinimler/req-tpd-1/caseler");
    expect(screen.queryByText("Öneri üretilmedi")).toBeNull();
  });

  it("gerçek core şekli (`GET /failures/{id}` case/gereksinim kimliği taşımaz): script'e, o da yoksa koşuya bağlanır", async () => {
    await oturumAc("analist");
    const h = mockVerisi().hatalar.find((x) => x.id === "fail-2")!;
    const ortak = { sinif: "test_maintenance", alt_tur: "beklenti", oneri: null, oneri_yok_nedeni: "Case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor; case düzeltilmeli" };
    Object.assign(h, { ...ortak, script_id: "scr-2" });
    delete (h as { case_id?: unknown }).case_id;
    delete (h as { requirement_id?: unknown }).requirement_id;
    const ilk = uygulama("/hatalar/fail-2");
    expect(within(await screen.findByTestId("case-duzeltilmeli")).getByRole("link", { name: "Script ve bağlı case'i aç" })).toHaveAttribute("href", "/kod/scr-2");
    ilk.unmount();
    Object.assign(h, { script_id: null });
    uygulama("/hatalar/fail-2");
    const link = within(await screen.findByTestId("case-duzeltilmeli")).getByRole("link", { name: /^Koşuyu aç/ });
    expect(link).toHaveAttribute("href", `/kosular/${h.run_id}`);
    expect(link).toHaveTextContent(h.test_adi);
  });

  it("diğer alt türlerde mevcut görünüm korunur", async () => {
    await oturumAc("analist");
    uygulama("/hatalar/fail-2");
    expect(await screen.findByTestId("triage-sinif")).toHaveTextContent("locator");
    expect(screen.queryByTestId("case-duzeltilmeli")).toBeNull();
  });
});

describe("ilişkiden türetilen case ve olay", () => {
  it("etiket `metamorfik` taşıyan case kartında 'İlişkiden türetildi' çipi (mor değil)", async () => {
    await oturumAc("analist");
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-8")!;
    c.icerik = { ...c.icerik, tags: [...c.icerik.tags, "metamorfik"] };
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const cipler = await screen.findAllByTestId("turetme-cip");
    expect(cipler).toHaveLength(1);
    expect(cipler[0]).toHaveTextContent("İlişkiden türetildi");
    expect(cipler[0].querySelector(".cip-vurgu")).toBeNull();
  });

  it("`karar_tablosu.updated` kendi konusudur; durum olayları aynı konuya çevrilir", () => {
    expect(olayKonulari({ type: "karar_tablosu.updated", data: { requirement_id: "r" } })).toContain("karar_tablosu.updated");
    expect(olayKonulari({ type: "metamorfik_iliski.state", data: {} })).toContain("karar_tablosu.updated");
  });
});

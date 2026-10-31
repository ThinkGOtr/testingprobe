// Faz 2 entegrasyonu (1. inceleme turu sonrası): core'un yeni alanları portalda görünür.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockVerisi } from "../api/mock/handlers";
import { bulguUyarla, caseUyarla, gereksinimDetayUyarla } from "../api/uyum";
import { BulguKarti } from "../components/BulguKarti";
import { CaseKarti } from "../components/CaseKarti";
import { sar } from "../test/yardimci";

describe("core alan uyarlamaları", () => {
  it("son_hata ve po_istegi detayda korunur", () => {
    const g = gereksinimDetayUyarla({
      id: "r1",
      durum: "failed",
      son_hata: { neden: "REPLAY yok", zaman: "2026-10-31T10:00:00Z", job_tur: "requirements.consistency", is_hatasi: null, oneri: "canlı model gerekir", yeniden_denemek_ise_yarar: false },
      po_istegi: { durum: "basarisiz", jira_comment_id: null, hata: "HTTP 503" },
    });
    expect(g.son_hata?.neden).toBe("REPLAY yok");
    expect(g.son_hata?.yeniden_denemek_ise_yarar).toBe(false);
    expect(g.po_istegi).toEqual({ durum: "basarisiz", jira_comment_id: null, hata: "HTTP 503" });
  });

  it("bulgu_etiketi ve case farkı uyarlanır", () => {
    expect(bulguUyarla({ id: "f", bulgu_etiketi: "F2 (tur 1)" }).bulgu_etiketi).toBe("F2 (tur 1)");
    const c = caseUyarla({
      id: "c",
      fark: [{ alan: "expected_result", etiket: "Beklenen sonuç", once: "a", sonra: "b" }],
      duzeltme_nedeni: "Küçük düzeltme sayılmadı",
      onceki_icerik: true,
    });
    expect(c.fark).toEqual([{ alan: "expected_result", etiket: "Beklenen sonuç", once: "a", sonra: "b" }]);
    expect(c.duzeltme_nedeni).toBe("Küçük düzeltme sayılmadı");
    expect(c.onceki_icerik).toBe(true);
  });
});

describe("görünüm", () => {
  it("bulgu kartı Jira yorumundaki etiketi gösterir", () => {
    const b = { ...mockVerisi().bulgular[0], bulgu_etiketi: "F2 (tur 1)" };
    sar(<BulguKarti bulgu={b} guncellendi={() => {}} />);
    expect(screen.getByTestId("bulgu-etiketi")).toHaveTextContent("F2 (tur 1)");
  });

  it("case kartı AI özgünü → düzeltme farkını ve nedenini gösterir", () => {
    const tc = {
      ...mockVerisi().caseler[0],
      fark: [{ alan: "expected_result", etiket: "Beklenen sonuç", once: "Sipariş onaylanır", sonra: "Sipariş reddedilir" }],
      duzeltme_nedeni: "Küçük düzeltme sayılmadı: beklenen sonuç anlamca değişti",
    };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    const fark = screen.getByTestId("case-fark");
    expect(fark).toHaveTextContent("Beklenen sonuç");
    expect(fark).toHaveTextContent("Küçük düzeltme sayılmadı");
  });
});

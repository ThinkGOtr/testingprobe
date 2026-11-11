// Asistan denetimi gösterimi (011 F7, K11): engellenen soru/cevap açıklaması, uyarı notu, kısa
// puan + ayrıntı ipucu, fail-closed "denetim çalışmıyor" ve denetimli cevapta derin inceleme yok.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { AsistanMesaji, CevapDenetimi } from "../../api/asistan";
import { BildirimProvider } from "../Bildirim";
import { CevapKarti } from "./CevapKarti";
import { denetimPuani } from "./DenetimKutusu";

function mesaj(denetim: CevapDenetimi, ek: Partial<AsistanMesaji> = {}, notlar: string[] = []): AsistanMesaji {
  return {
    id: "m1",
    sohbet_id: "s1",
    sira: 2,
    rol: "assistant",
    ust_mesaj_id: null,
    icerik: "soru",
    cevap: { cevap_bloklari: [{ tur: "paragraf", metin: "Sunucu açıklaması" }], kaynaklar: [], yonlendirmeler: [], eylem_reddi: false, notlar, denetim },
    durum: "done",
    hata_kodu: null,
    kaynak: "model",
    amac: "assistant",
    kip: "soru",
    tetik: "kullanici",
    maliyet_usd: null,
    sure_ms: null,
    geri_bildirim: null,
    olusturma: new Date().toISOString(),
    tamamlanma: null,
    ...ek,
  };
}

function kart(m: AsistanMesaji) {
  return render(
    <MemoryRouter>
      <BildirimProvider>
        <CevapKarti mesaj={m} derinIncelenebilir derinIncele={() => undefined} />
      </BildirimProvider>
    </MemoryRouter>,
  );
}

const ENGEL_SORU: CevapDenetimi = {
  karar: "engelle",
  engellenen: "soru",
  soru: { puan: 5, karar: "engelle", kategoriler: ["nefret_irkcilik"], gerekce: "Irkçı genelleme.", kaynak: "tp-gecit" },
  cevap: null,
};

describe("DenetimKutusu", () => {
  it("engellenen soru: açıklama kutusu, kategori etiketi, puan; derin inceleme yok", () => {
    kart(mesaj(ENGEL_SORU, { kaynak: "denetim", amac: null }));
    const kutu = screen.getByTestId("denetim-kutusu");
    expect(kutu).toHaveAttribute("role", "alert");
    expect(kutu).toHaveTextContent("Soru engellendi");
    expect(kutu).toHaveTextContent("asistana iletilmedi");
    expect(within(kutu).getByText("Nefret söylemi / ırkçılık")).toBeInTheDocument();
    expect(screen.getByText("Denetim 5/100")).toBeInTheDocument();
    expect(screen.getByText("Sunucu açıklaması")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
  });

  it("engellenen cevap: 'Cevap gösterilmedi' ve kişisel veri etiketi", () => {
    kart(
      mesaj(
        {
          karar: "engelle",
          engellenen: "cevap",
          soru: { puan: 95, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "tp-gecit" },
          cevap: { puan: 20, karar: "engelle", kategoriler: ["kisisel_veri"], gerekce: "TCKN içeriyor.", kaynak: "tp-gecit" },
        },
        { kaynak: "denetim" },
      ),
    );
    const kutu = screen.getByTestId("denetim-kutusu");
    expect(kutu).toHaveTextContent("Cevap gösterilmedi");
    expect(within(kutu).getByText("Kişisel veri")).toBeInTheDocument();
    expect(screen.getByText("Denetim 20/100")).toBeInTheDocument();
  });

  it("uyarı: cevap gösterilir, uyarı kutusu + not stili, ipucunda kategoriler/gerekçe/kaynak", () => {
    const d: CevapDenetimi = {
      karar: "uyar",
      engellenen: null,
      soru: { puan: 62, karar: "uyar", kategoriler: ["rekabete_aykiri"], gerekce: "Rakip hakkında doğrulanmamış iddia isteniyor.", kaynak: "tp-gecit" },
      cevap: { puan: 88, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "tp-gecit" },
    };
    kart(mesaj(d, {}, ["Denetim uyarısı: rekabete aykırı içerik"]));
    expect(screen.getByTestId("denetim-kutusu")).toHaveAttribute("role", "note");
    expect(screen.getByTestId("denetim-kutusu")).toHaveTextContent("Rekabete aykırı");
    expect(screen.getByText("Denetim uyarısı: rekabete aykırı içerik")).toHaveClass("asistan-not-denetim");
    const rozet = screen.getByText("Denetim 62/100");
    const ipucu = rozet.closest("[title]")!.getAttribute("title")!;
    expect(ipucu).toContain("Soru: 62/100");
    expect(ipucu).toContain("Cevap: 88/100");
    expect(ipucu).toContain("Rakip hakkında doğrulanmamış iddia isteniyor.");
    expect(ipucu).toContain("Testing Probe geçidi (model)");
    // Model cevabı: derin inceleme düğmesi kalır.
    expect(screen.getByRole("button", { name: "Daha ayrıntılı incele" })).toBeInTheDocument();
  });

  it("geçti: kutu yok, yalnız kısa puan", () => {
    kart(
      mesaj({
        karar: "gec",
        engellenen: null,
        soru: { puan: 97, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "sim" },
        cevap: { puan: 92, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "sim" },
      }),
    );
    expect(screen.queryByTestId("denetim-kutusu")).toBeNull();
    expect(screen.getByText("Denetim 92/100")).toBeInTheDocument();
  });

  it("denetim çalışmıyor (fail-closed): açıklama, puan yok", () => {
    kart(mesaj({ karar: "calismiyor", engellenen: null, soru: null, cevap: null }, { kaynak: "denetim" }));
    expect(screen.getByTestId("denetim-kutusu")).toHaveTextContent("Denetim çalışmıyor");
    expect(screen.queryByTestId("denetim-rozeti")).toBeNull();
    expect(screen.queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
  });

  it("puan iki yönün düşüğüdür", () => {
    expect(denetimPuani(ENGEL_SORU)!.puan).toBe(5);
    expect(denetimPuani({ karar: "gec", engellenen: null, soru: null, cevap: null })).toBeNull();
  });
});

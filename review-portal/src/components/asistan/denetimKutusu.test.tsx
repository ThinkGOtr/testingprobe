// Asistan içerik kontrolü gösterimi (011 F7, K11, UX-9): engel/uyarıda puan yalnız <details> ayrıntısında,
// geçen cevapta işaret yok, engel başlığı "Bu soruyu yanıtlayamıyorum", kategori uyarı tonunda (kırmızı değil),
// backend notu tek kez yazılır, fail-closed "çalışmıyor" ve denetimli cevapta derin inceleme yok.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  it("engellenen soru: 'Bu soruyu yanıtlayamıyorum', kategori uyarı tonunda, puan görünmez; derin inceleme yok", () => {
    kart(mesaj(ENGEL_SORU, { kaynak: "denetim", amac: null }));
    const kutu = screen.getByTestId("denetim-kutusu");
    expect(kutu).toHaveAttribute("role", "note");
    expect(kutu).toHaveClass("uyari-uyari");
    expect(kutu).not.toHaveClass("uyari-hata");
    expect(within(kutu).getByText("Bu soruyu yanıtlayamıyorum")).toBeInTheDocument();
    const kategori = within(kutu).getByText("Nefret söylemi / ırkçılık");
    expect(kategori).toHaveClass("cip-uyari");
    // Puan özet satırında yok; yalnız kapalı ayrıntıda.
    expect(screen.queryByText(/Denetim \d+\/100/)).toBeNull();
    expect(screen.getByText(/puan 5\/100/)).not.toBeVisible();
    // Açıklama backend cevap bloğunda bir kez; kutu aynı açıklamayı tekrar yazmaz.
    expect(screen.getByText("Sunucu açıklaması")).toBeInTheDocument();
    expect(kutu).not.toHaveTextContent("Sunucu açıklaması");
    expect(kutu).not.toHaveTextContent("asistana iletilmedi");
    // Kaynak notu yeni adla; engelde ayrı rozet yok.
    expect(screen.getByText("İçerik kontrolü")).toBeInTheDocument();
    expect(screen.queryByTestId("denetim-rozeti")).toBeNull();
    expect(screen.queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
  });

  // <summary> tarayıcıda yerel olarak odaklanır ve Enter/Boşluk ile açılır; jsdom klavye etkinleştirmesini
  // uygulamadığı için burada tıklama (dokunma) ile doğrulanır.
  it("ayrıntı yerel <details>/<summary>: dokunarak açılır; puan, gerekçe, kaynak içinde", async () => {
    const k = userEvent.setup();
    kart(mesaj(ENGEL_SORU, { kaynak: "denetim", amac: null }));
    const ayrinti = screen.getByTestId("denetim-ayrinti");
    expect(ayrinti.tagName).toBe("DETAILS");
    expect(ayrinti).not.toHaveAttribute("open");
    const ozet = within(ayrinti).getByText("Kontrol ayrıntısı");
    expect(ozet.tagName).toBe("SUMMARY");
    await k.click(ozet);
    expect(ayrinti).toHaveAttribute("open");
    expect(ayrinti).toHaveTextContent("puan 5/100");
    expect(ayrinti).toHaveTextContent("Gerekçe: Irkçı genelleme.");
    expect(ayrinti).toHaveTextContent("Kaynak: Testing Probe geçidi (model)");
  });

  it("engellenen cevap: aynı başlık, kişisel veri etiketi; ayrıntıda iki yön", () => {
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
    expect(kutu).toHaveTextContent("Bu soruyu yanıtlayamıyorum");
    expect(within(kutu).getByText("Kişisel veri")).toBeInTheDocument();
    const ayrinti = screen.getByTestId("denetim-ayrinti");
    expect(ayrinti).toHaveTextContent("Soru");
    expect(ayrinti).toHaveTextContent("puan 20/100");
  });

  it("uyarı: 'İçerik kontrolü' rozeti (puansız), backend notu kutuda bir kez; cevap gösterilir", () => {
    const d: CevapDenetimi = {
      karar: "uyar",
      engellenen: null,
      soru: { puan: 62, karar: "uyar", kategoriler: ["rekabete_aykiri"], gerekce: "Rakip hakkında doğrulanmamış iddia isteniyor.", kaynak: "tp-gecit" },
      cevap: { puan: 88, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "tp-gecit" },
    };
    kart(mesaj(d, {}, ["Denetim uyarısı: rekabete aykırı içerik", "Başka not"]));
    const kutu = screen.getByTestId("denetim-kutusu");
    expect(kutu).toHaveAttribute("role", "note");
    expect(kutu).toHaveTextContent("İçerik kontrolü uyarısı");
    expect(within(kutu).getByText("rekabete aykırı içerik")).toBeInTheDocument();
    // Not ayrı paragraf olarak tekrar yazılmaz; diğer notlar kalır.
    expect(screen.queryByText("Denetim uyarısı: rekabete aykırı içerik")).toBeNull();
    expect(screen.getAllByText(/rekabete aykırı içerik/)).toHaveLength(1);
    expect(screen.getByText("Başka not")).toBeInTheDocument();
    const rozet = screen.getByTestId("denetim-rozeti");
    expect(rozet).toHaveTextContent(/^İçerik kontrolü$/);
    expect(rozet.querySelector("[title]")).toBeNull();
    expect(screen.getByTestId("denetim-ayrinti")).toHaveTextContent("puan 62/100");
    expect(screen.getByTestId("denetim-ayrinti")).toHaveTextContent("puan 88/100");
    expect(screen.getByText("Sunucu açıklaması")).toBeInTheDocument();
    // Model cevabı: derin inceleme düğmesi kalır.
    expect(screen.getByRole("button", { name: "Daha ayrıntılı incele" })).toBeInTheDocument();
  });

  it("uyarı, backend notu yoksa: kısa cümle + kategori etiketi", () => {
    kart(
      mesaj({
        karar: "uyar",
        engellenen: null,
        soru: { puan: 62, karar: "uyar", kategoriler: ["rekabete_aykiri"], gerekce: "", kaynak: "sim" },
        cevap: null,
      }),
    );
    const kutu = screen.getByTestId("denetim-kutusu");
    expect(kutu).toHaveTextContent("Bu cevabı dikkatle değerlendirin.");
    expect(within(kutu).getByText("Rekabete aykırı")).toHaveClass("cip-uyari");
  });

  it("geçti: kutu yok, rozet yok, puan yok", () => {
    kart(
      mesaj({
        karar: "gec",
        engellenen: null,
        soru: { puan: 97, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "sim" },
        cevap: { puan: 92, karar: "gec", kategoriler: ["temiz"], gerekce: "", kaynak: "sim" },
      }),
    );
    expect(screen.queryByTestId("denetim-kutusu")).toBeNull();
    expect(screen.queryByTestId("denetim-rozeti")).toBeNull();
    expect(screen.queryByText(/\/100/)).toBeNull();
  });

  it("içerik kontrolü çalışmıyor (fail-closed): açıklama, puan yok", () => {
    kart(mesaj({ karar: "calismiyor", engellenen: null, soru: null, cevap: null }, { kaynak: "denetim" }));
    expect(screen.getByTestId("denetim-kutusu")).toHaveTextContent("İçerik kontrolü çalışmıyor");
    expect(screen.queryByTestId("denetim-rozeti")).toBeNull();
    expect(screen.queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
  });

  it("puan iki yönün düşüğüdür", () => {
    expect(denetimPuani(ENGEL_SORU)!.puan).toBe(5);
    expect(denetimPuani({ karar: "gec", engellenen: null, soru: null, cevap: null })).toBeNull();
  });
});

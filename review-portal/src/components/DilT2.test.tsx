// Deploy sonrası T2: Yakında + Müşteri CI rozeti birlikte (T2-3), sayfa açıklaması yalnız açık dillerden
// söz eder ve Java web kapalı nedeni açma yolunu söyler (T2-2), algılama worker'da sürerken "depo
// okunamadı" denmez (T2-1).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DilSecenegi, KodDilleri } from "../api/types";
import { algilamaSuruyorMu, dilNedeni, DilSecici, JAVA_WEB_KAPALI, secenekRozeti, uretimAciklamasi } from "./Dil";

function secenek(p: Partial<DilSecenegi> & Pick<DilSecenegi, "dil" | "etiket">): DilSecenegi {
  return {
    cati: "Çatı",
    hat: "tam",
    durum: "acik",
    kirarak_dogrulama: true,
    check: "local-ci",
    kurulum: null,
    kullanilabilir: true,
    neden: null,
    ...p,
  } as DilSecenegi;
}

function veri(secenekler: DilSecenegi[], ek: Partial<KodDilleri> = {}): KodDilleri {
  return { platform: "web", algilanan: "ts", kaynak: "algilandi", neden: null, sayilar: {}, en_az: [], secenekler, ...ek } as KodDilleri;
}

describe("T2-3 seçenek rozeti", () => {
  it("Yakında ve Müşteri CI birlikte", () => {
    expect(secenekRozeti({ durum: "yakinda", hat: "musteri_ci" })).toBe("Yakında · Müşteri CI");
    expect(secenekRozeti({ durum: "acik", hat: "musteri_ci" })).toBe("Müşteri CI");
    expect(secenekRozeti({ durum: "yakinda", hat: "tam" })).toBe("Yakında");
    expect(secenekRozeti({ durum: "acik", hat: "tam" })).toBeNull();
  });

  it("seçicide Kotlin rozeti iki bilgiyi gösterir", () => {
    const d = veri(
      [
        secenek({ dil: "java", etiket: "Java" }),
        secenek({ dil: "kotlin", etiket: "Kotlin", hat: "musteri_ci", durum: "yakinda", kullanilabilir: false, neden: "Değerlendirme sürüyor" }),
      ],
      { platform: "android", algilanan: "java" },
    );
    render(<DilSecici diller={d} deger="java" degistir={() => {}} elle={false} algilananaDon={() => {}} />);
    expect(screen.getAllByTestId("secenek-rozeti").map((r) => r.textContent?.trim())).toEqual(["Yakında · Müşteri CI."]);
  });
});

describe("T2-2 açıklama ve Java kapalı nedeni", () => {
  it("Java web kapalıyken açıklama Java'dan söz etmez", () => {
    const m = uretimAciklamasi(
      veri([
        secenek({ dil: "ts", etiket: "TypeScript" }),
        secenek({ dil: "java", etiket: "Java", kullanilabilir: false, neden: "GitHub kipinde Java web hattı etkin değil (TP_WEB_DILLERI java içermiyor)" }),
        secenek({ dil: "csharp", etiket: "C#", durum: "yakinda", kullanilabilir: false }),
        secenek({ dil: "python", etiket: "Python", durum: "yakinda", kullanilabilir: false }),
      ]),
    );
    expect(m).toContain("TypeScript için yerel kontrol yeşilse bot ayrı dalda PR açar.");
    expect(m).not.toMatch(/Java|C#|Python/);
  });

  it("açık diller hatlarına göre anılır", () => {
    const m = uretimAciklamasi(
      veri([
        secenek({ dil: "ts", etiket: "TypeScript" }),
        secenek({ dil: "java", etiket: "Java" }),
        secenek({ dil: "python", etiket: "Python", hat: "dogrulanmamis" }),
        secenek({ dil: "kotlin", etiket: "Kotlin", hat: "musteri_ci" }),
      ]),
    );
    expect(m).toContain("TypeScript ve Java için yerel kontrol yeşilse");
    expect(m).toContain("Kotlin testleri müşteri CI'da koşar");
    expect(m).toContain("Python kodu doğrulanmamış olarak çıkar");
  });

  it("Java kapalı nedeni açma yolunu söyler", () => {
    const ham = "GitHub kipinde Java web hattı etkin değil (TP_WEB_DILLERI java içermiyor; web-java iş akışı zorunlu check değil)";
    expect(dilNedeni(ham).metin).toBe(JAVA_WEB_KAPALI);
    expect(JAVA_WEB_KAPALI).toContain("AI Probe › Proje › Platform ayarları › Web › Test dilleri bölümünde Java seçeneğini işaretleyin");
  });
});

describe("T2-1 algılama sürüyor", () => {
  it("depo okunamadı yerine algılanıyor notu", () => {
    const d = veri([secenek({ dil: "ts", etiket: "TypeScript" }), secenek({ dil: "java", etiket: "Java" })], {
      kaynak: "varsayilan",
      neden: "Dil algılanamadı (algılama sürüyor; birkaç saniye sonra yeniden deneyin); varsayılan dil önerildi",
    });
    expect(algilamaSuruyorMu(d)).toBe(true);
    render(<DilSecici diller={d} deger="ts" degistir={() => {}} elle={false} algilananaDon={() => {}} />);
    expect(screen.getByTestId("dil-notu")).toHaveTextContent(/Dil algılanıyor/);
    expect(screen.getByTestId("dil-notu")).not.toHaveTextContent(/Depo okunamadı/);
  });
});

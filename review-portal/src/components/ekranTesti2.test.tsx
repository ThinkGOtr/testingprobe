// Ekran testi 2 (TP-1, TP-2, TP-3, TP-7): müşteri CI kurulum yolu, engelli algılanan dil notu, kapalı dil
// nedenleri (açma yolu, iç ad yok) ve genel süzgeç bileşeni.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DilSecenegi, KodDilleri, Kosu } from "../api/types";
import { dilListesiYolu, dilNedeni, DilSecici, engelliAlgilanan, listeEngeliMetni, YAKINDA_ACIKLAMA } from "./Dil";
import { musteriCiKurulumAdimi, MusteriCiKurulumYolu } from "./KurulumPrEylemi";
import { suzgecSecenekleri } from "./Suzgec";
import { kosulariSuz, dilSecimiOku } from "../pages/Kosular";

function secenek(p: Partial<DilSecenegi> & Pick<DilSecenegi, "dil" | "etiket">): DilSecenegi {
  return { cati: "Çatı", hat: "tam", durum: "acik", kirarak_dogrulama: true, check: "c", kurulum: null, kullanilabilir: true, neden: null, ...p } as DilSecenegi;
}

function veri(secenekler: DilSecenegi[], ek: Partial<KodDilleri> = {}): KodDilleri {
  return { platform: "web", algilanan: "ts", kaynak: "algilandi", neden: null, sayilar: {}, en_az: [], secenekler, ...ek } as KodDilleri;
}

describe("TP-3 kapalı dil nedenleri", () => {
  it("açma yolu Home'daki adlarla", () => {
    expect(dilListesiYolu("android")).toBe("AI Probe › Proje › Platform ayarları › Android › Test dilleri");
    expect(listeEngeliMetni("ios", "Swift")).toContain("Platform ayarları › iOS › Test dilleri bölümünde Swift");
  });

  it("eski core metni platformla açma yoluna çevrilir; iç ad görünmez", () => {
    const ham = "GitHub kipinde Kotlin hattı etkin değil (TP_DILLERI_ANDROID kotlin içermiyor; mobil-android-kotlin iş akışı zorunlu check değil)";
    const r = dilNedeni(ham, "android");
    expect(r.metin).toBe(listeEngeliMetni("android", "Kotlin"));
    expect(r.metin).not.toMatch(/TP_|check/);
    expect(r.ayrinti).toBe(ham);
  });

  it("yeni core metni olduğu gibi; Yakında açıklanır", () => {
    const yeni = listeEngeliMetni("web", "C#");
    expect(dilNedeni(yeni, "web")).toEqual({ metin: yeni, ayrinti: null });
    expect(dilNedeni("Değerlendirme sürüyor").metin).toBe(YAKINDA_ACIKLAMA);
    const yap = "Yapılandırma hatası: Web test dilleri ayarı geçersiz. AI Probe › Proje › Platform ayarları › Web › Test dilleri bölümünü kontrol edip yeniden kaydedin";
    expect(dilNedeni(yap, "web").metin).toBe(yap);
  });
});

describe("TP-2 engelli algılanan dil", () => {
  const sec = [
    secenek({ dil: "ts", etiket: "TypeScript" }),
    secenek({ dil: "java", etiket: "Java", kullanilabilir: false, engel: "liste" }),
    secenek({ dil: "csharp", etiket: "C#", kullanilabilir: false, engel: "liste" }),
    secenek({ dil: "python", etiket: "Python", kullanilabilir: false, engel: "liste" }),
  ];
  const sayilar = { ts: 8, java: 5, csharp: 9, python: 7 };

  it("core alanıyla: 'test bulunamadı' denmez, sayılar gösterilir", () => {
    const d = veri(sec, { kaynak: "varsayilan", sayilar, engelli_algilanan: { dil: "csharp", sayi: 9, en_az: false, engel: "liste", neden: "x" } });
    render(<DilSecici diller={d} deger="ts" degistir={() => {}} elle={false} algilananaDon={() => {}} />);
    const not = screen.getByTestId("dil-notu");
    expect(not).toHaveTextContent("Depoda en çok C# testi var (9) ama C# bu projede seçili değil; varsayılan: TypeScript.");
    expect(not).toHaveTextContent("TypeScript 8, Java 5, C# 9, Python 7");
    expect(not).not.toHaveTextContent(/bulunamadı/);
  });

  it("eski core: sayılardan çıkarılır; yeni core null → çıkarılmaz", () => {
    expect(engelliAlgilanan(veri(sec, { kaynak: "varsayilan", sayilar }))?.dil).toBe("csharp");
    expect(engelliAlgilanan(veri(sec, { kaynak: "varsayilan", sayilar, engelli_algilanan: null }))).toBeNull();
    expect(engelliAlgilanan(veri(sec, { kaynak: "varsayilan", sayilar: {} }))).toBeNull();
  });
});

describe("TP-1 müşteri CI kurulum yolu", () => {
  const kotlin = secenek({
    dil: "kotlin",
    etiket: "Kotlin",
    hat: "musteri_ci",
    kullanilabilir: false,
    engel: "liste",
    acma_yolu: "AI Probe › Proje › Platform ayarları › Android › Test dilleri",
    kurulum: { durum: "gerekli", number: null, url: null, baslik: null, eksikler: ["iş akışı"], elle_adimlar: [] },
  });

  it("dil listede değilken kurulum eylemi ve sıra yönlendirmesi görünür", () => {
    render(<MusteriCiKurulumYolu platform="android" secenekler={[secenek({ dil: "java", etiket: "Java" }), kotlin]} seciliDil="java" />);
    const kutu = screen.getByTestId("kurulum-pr-yolu");
    expect(kutu).toHaveTextContent("kurulum dil seçilmeden önce yapılabilir");
    expect(kutu).toHaveTextContent("Platform ayarları › Android › Test dilleri bölümünde Kotlin");
    expect(screen.getByTestId("kurulum-pr-ac")).toBeInTheDocument();
  });

  it("Yakında, web ve yapılandırma hatasında çizilmez", () => {
    const { container } = render(
      <>
        <MusteriCiKurulumYolu platform="android" secenekler={[{ ...kotlin, durum: "yakinda" }]} seciliDil="java" />
        <MusteriCiKurulumYolu platform="web" secenekler={[kotlin]} seciliDil="ts" />
        <MusteriCiKurulumYolu platform="android" secenekler={[{ ...kotlin, engel: "yapilandirma" }]} seciliDil="java" />
      </>,
    );
    expect(container.querySelector("[data-testid=kurulum-pr-yolu]")).toBeNull();
  });

  it("kurulum birleştiyse yalnız dil seçimi kalır; depo engelinde birleşince seçilebilir", () => {
    expect(musteriCiKurulumAdimi({ ...kotlin, kurulum: { ...kotlin.kurulum!, durum: "birlesti" } }, "android")).toMatch(/^Kurulum tamam/);
    expect(musteriCiKurulumAdimi({ ...kotlin, engel: "depo" }, "android")).toContain("Kurulum PR'ı birleşince Kotlin bu ekranda seçilebilir");
  });
});

describe("TP-7 dil süzgeci", () => {
  const k = (id: string, dil: Kosu["dil"]) => ({ id, dil, tetik: "pr", kaynak: "local", durum: "passed", break_campaign: null, platform: "web" }) as unknown as Kosu;
  const kosular = [k("1", "ts"), k("2", "python"), k("3", null), k("4", "csharp")];

  it("dil seçimi yalnız o dildeki koşuları bırakır; dili bilinmeyen girmez", () => {
    const f = { tetik: "", kaynak: "", durum: "", kirma: true, platform: "", dil: "python" } as const;
    expect(kosulariSuz(kosular, f).map((x) => x.id)).toEqual(["2"]);
    expect(kosulariSuz(kosular, { ...f, dil: "" }).map((x) => x.id)).toEqual(["1", "2", "3", "4"]);
    expect(dilSecimiOku("csharp")).toBe("csharp");
    expect(dilSecimiOku("go")).toBe("");
  });

  it("seçenekler veriden, sırayla; seçili değer kalır", () => {
    const s = suzgecSecenekleri(kosular, (x) => x.dil, (d) => d, { sira: ["ts", "java", "csharp", "python"], secili: "java" });
    expect(s.map((x) => x.deger)).toEqual(["ts", "java", "csharp", "python"]);
  });
});

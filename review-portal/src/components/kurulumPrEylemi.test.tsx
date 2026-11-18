// 014 müşteri CI "Kurulum PR'ı aç" eylemi: Kod üretimi ekranında form, önizleme, PR açma, idempotent
// (açık PR varken yenisi açılmaz), sunucu doğrulama hataları, rol ve EN metinler; istemci + uyum katmanı.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { ayar, mockSifirla } from "../api/mock/handlers";
import { kurulumPrSonucuUyarla } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "./Bildirim";
import { eksikZorunlular, formParametreleri, kurulumMetni } from "../lib/kurulumPr";
import { izinRolleri } from "../lib/yetki";
import { oturumAc } from "../test/yardimci";
import { KurulumPrEylemi } from "./KurulumPrEylemi";

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

async function kotlinSec(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("radio", { name: /^Android/ }));
  await u.click(await screen.findByRole("radio", { name: "Kotlin" }));
}

beforeEach(() => {
  mockSifirla();
  ayar.isAdimiMs = 0;
  ayar.senaryolar.add("diller-acik");
});
afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.lang = "tr";
});

describe("lib/kurulumPr", () => {
  it("zorunlu alanlar platforma göre; boşlar atılır, API düzeyi sayıya çevrilir", () => {
    expect(eksikZorunlular("android", {}, "tr")).toEqual(["Test paketi"]);
    expect(eksikZorunlular("ios", { sema: "X" }, "en")).toEqual(["Xcode project (.xcodeproj / .xcworkspace)", "UI test target"]);
    expect(formParametreleri("android", { test_paketi: " com.a.b ", emulator_api: "33", hazirlik_betigi: "", xcode_proje: "x" })).toEqual({ test_paketi: "com.a.b", emulator_api: 33 });
    expect(formParametreleri("ios", { hazirlik_betigi: ".github/tp/h.sh", node_surumu: "22", yapilandirma: "Release" })).toEqual({
      hazirlik_betigi: ".github/tp/h.sh",
      node_surumu: "22",
      yapilandirma: "Release",
    });
  });

  it("rol: yalnız Sistem Yöneticisi ve Otomasyon Mühendisi", () => {
    expect([...izinRolleri("code.ci_setup")].sort()).toEqual(["admin", "engineer"]);
  });
});

describe("istemci + uyum", () => {
  it("yanıt uyarlanır; tanınmayan durum hata; 202 sürüyor", () => {
    expect(kurulumPrSonucuUyarla({ durum: "acildi", pr_no: 7, url: "https://github.com/a/b/pull/7", dosyalar: ["x"], kurulum: { durum: "acildi", number: 7 } })).toMatchObject({
      durum: "acildi",
      pr_no: 7,
      url: "https://github.com/a/b/pull/7",
      dosyalar: ["x"],
      hazir: true,
    });
    expect(kurulumPrSonucuUyarla({ durum: "onizleme", pr: { number: 3, url: null }, hazir: false })).toMatchObject({ pr_no: 3, hazir: false });
    expect(kurulumPrSonucuUyarla({ durum: "suruyor", job_id: "j", mesaj: "bekleyin" })).toMatchObject({ durum: "suruyor", pr_no: null, mesaj: "bekleyin" });
    expect(() => kurulumPrSonucuUyarla({ durum: "belki" })).toThrow();
  });

  it("idempotent: ikinci istek yeni PR açmaz, var olanı döner; 422 hatalar[] taşır", async () => {
    await oturumAc("muhendis");
    const a = await api.kurulumPrAc("android", "kotlin", { test_paketi: "com.acme.bayi.tp" });
    expect(a.durum).toBe("acildi");
    const b = await api.kurulumPrAc("android", "kotlin", { test_paketi: "com.acme.bayi.tp", emulator_api: 33 });
    expect(b).toMatchObject({ durum: "mevcut", pr_no: a.pr_no, url: a.url });
    const hata = await api.kurulumPrAc("ios", "swift", { sema: "X" }).catch((e: unknown) => e);
    expect(hata).toBeInstanceOf(ApiError);
    expect((hata as ApiError).status).toBe(422);
    expect((hata as ApiError).kod).toBe("kurulum_parametre");
    expect((hata as ApiError).hatalar).toEqual(["xcode_proje gerekli", "ui_test_hedefi gerekli"]);
  });

  it("yetkisiz rol 403", async () => {
    await oturumAc("testci");
    await expect(api.kurulumPrAc("android", "kotlin", { test_paketi: "a.b" })).rejects.toMatchObject({ status: 403 });
  });
});

describe("Kod üretimi: Kurulum PR'ı aç", () => {
  it("form → zorunlu alan uyarısı → önizleme → PR açılır; bağlantı ve açık durum gösterilir, eylem kaybolur", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    await kotlinSec(u);
    expect(screen.getByTestId("kurulum-pr")).toHaveAttribute("data-durum", "gerekli");
    await u.click(screen.getByRole("button", { name: "Kurulum PR'ı aç" }));
    const form = screen.getByTestId("kurulum-pr-form");
    expect(within(form).getByRole("group", { name: /İsteğe bağlı/ })).toHaveTextContent("Hazırlık betiği");

    await u.click(within(form).getByRole("button", { name: "PR'ı aç" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Zorunlu alanları doldurun: Test paketi");

    await u.type(within(form).getByLabelText(/Test paketi/), "com.acme.bayi.tp");
    await u.type(within(form).getByLabelText("Hazırlık betiği"), ".github/tp/hazirlik.sh");
    await u.click(within(form).getByRole("button", { name: "Önizle" }));
    const onizleme = await within(form).findByTestId("kurulum-pr-onizleme");
    expect(within(onizleme).getByRole("list", { name: "Önizleme: PR'a girecek dosyalar" })).toHaveTextContent(".github/workflows/mobil-android-kotlin.yml");
    expect(within(onizleme).getByRole("list", { name: "Elle yapılacak" })).toHaveTextContent("Hazırlık betiği yok");

    await u.click(within(form).getByRole("button", { name: "PR'ı aç" }));
    const sonuc = await screen.findByTestId("kurulum-pr-sonuc");
    expect(sonuc).toHaveAttribute("data-durum", "acildi");
    expect(sonuc).toHaveTextContent("Kurulum PR'ı açıldı");
    expect(within(sonuc).getByRole("link", { name: /#60/ })).toHaveAttribute("href", "https://github.com/antreklabs/bayi-siparis/pull/60");
    // Dil seçenekleri yenilendi: kurulum PR'ı açık (#60); yeni "aç" düğmesi yok.
    expect(await screen.findByText(/Kurulum PR'ı birleşene kadar Kotlin testleri/)).toBeInTheDocument();
    expect(screen.getByTestId("kurulum-pr")).toHaveAttribute("data-durum", "acik");
    expect(screen.queryByRole("button", { name: "Kurulum PR'ı aç" })).toBeNull();
  });

  it("TP3-3: engel (Xcode projesi bulunamadı) hazır değil başlığıyla ve ayrı listede gösterilir", async () => {
    expect(kurulumPrSonucuUyarla({ durum: "onizleme", hazir: false, engeller: ["Xcode projesi bulunamadı (ios/X.xcodeproj)."] }).engeller).toEqual([
      "Xcode projesi bulunamadı (ios/X.xcodeproj).",
    ]);
    vi.spyOn(api, "kurulumPrAc").mockResolvedValue(
      kurulumPrSonucuUyarla({ durum: "onizleme", hazir: false, dosyalar: [], eksikler: [], elle_adimlar: [], engeller: ["Xcode projesi bulunamadı (ios/X.xcodeproj)."] }),
    );
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    await kotlinSec(u);
    await u.click(screen.getByRole("button", { name: "Kurulum PR'ı aç" }));
    const form = screen.getByTestId("kurulum-pr-form");
    await u.type(within(form).getByLabelText(/Test paketi/), "com.acme.bayi.tp");
    await u.click(within(form).getByRole("button", { name: "Önizle" }));
    const onizleme = await within(form).findByTestId("kurulum-pr-onizleme");
    expect(onizleme).toHaveTextContent("Kurulum engeli var; PR açılamaz.");
    expect(within(onizleme).getByRole("list", { name: "PR'ı engelleyenler" })).toHaveTextContent("Xcode projesi bulunamadı");
  });

  it("sunucu doğrulama hatası alan listesiyle gösterilir", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    await kotlinSec(u);
    await u.click(screen.getByRole("button", { name: "Kurulum PR'ı aç" }));
    const form = screen.getByTestId("kurulum-pr-form");
    await u.type(within(form).getByLabelText(/Test paketi/), "com.acme.bayi.tp");
    await u.type(within(form).getByLabelText("Hazırlık betiği"), "kötü betik");
    await u.click(within(form).getByRole("button", { name: "PR'ı aç" }));
    expect(await within(form).findByText(/Kurulum parametreleri geçersiz/)).toBeInTheDocument();
    expect(within(form).getByText(/hazırlık betiği geçersiz \(depo içi \.sh yolu\)/)).toBeInTheDocument();
    expect(screen.queryByTestId("kurulum-pr-sonuc")).toBeNull();
  });

  it("forge hatası (409) Türkçe iletiyle gösterilir", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "kurulumPrAc").mockRejectedValue(new ApiError(409, "Kurulum PR'ı açılamadı: Resource not accessible by integration", { kod: "kurulum_pr_basarisiz" }));
    const u = userEvent.setup();
    uygulama("/kod");
    await kotlinSec(u);
    await u.click(screen.getByRole("button", { name: "Kurulum PR'ı aç" }));
    const form = screen.getByTestId("kurulum-pr-form");
    await u.type(within(form).getByLabelText(/Test paketi/), "com.acme.bayi.tp");
    await u.click(within(form).getByRole("button", { name: "PR'ı aç" }));
    expect(await within(form).findByText(/Resource not accessible by integration/)).toBeInTheDocument();
  });

  it("iOS: kurulum PR'ı zaten açık → eylem gösterilmez (var olan PR bağlantısı)", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    await u.click(await screen.findByRole("radio", { name: /^iOS/ }));
    await u.click(await screen.findByRole("radio", { name: "Swift" }));
    expect(screen.getByTestId("kurulum-pr")).toHaveAttribute("data-durum", "acik");
    expect(within(screen.getByTestId("kurulum-pr")).getByRole("link", { name: /#41/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kurulum PR'ı aç" })).toBeNull();
  });
});

describe("bileşen", () => {
  it("EN metinler; kapalı PR'da 'yeniden aç'; mevcut sonuç bilgisi", async () => {
    await oturumAc("sunucu");
    document.documentElement.lang = "en";
    vi.spyOn(api, "kurulumPrAc").mockResolvedValue(
      kurulumPrSonucuUyarla({ durum: "mevcut", pr_no: 41, url: "https://github.com/a/b/pull/41", taban: "main", kurulum: { durum: "acik", number: 41 } }),
    );
    const degisti = vi.fn();
    const u = userEvent.setup();
    render(
      <MemoryRouter>
        <OturumProvider>
          <KurulumPrEylemi platform="ios" kurulum={{ durum: "kapali", number: 9, url: null, baslik: null, eksikler: [], elle_adimlar: [] }} degisti={degisti} />
        </OturumProvider>
      </MemoryRouter>,
    );
    await u.click(await screen.findByRole("button", { name: "Reopen setup PR" }));
    const form = screen.getByTestId("kurulum-pr-form");
    await u.type(within(form).getByLabelText(/Xcode project/), "ios/B.xcworkspace");
    await u.type(within(form).getByLabelText(/^Scheme/), "B");
    await u.type(within(form).getByLabelText(/UI test target/), "BUITests");
    await u.click(within(form).getByRole("button", { name: "Open PR" }));
    const sonuc = await screen.findByTestId("kurulum-pr-sonuc");
    expect(sonuc).toHaveTextContent(kurulumMetni("mevcut", "en"));
    expect(within(sonuc).getByRole("link", { name: /#41/ })).toBeInTheDocument();
    expect(api.kurulumPrAc).toHaveBeenCalledWith("ios", "swift", { xcode_proje: "ios/B.xcworkspace", sema: "B", ui_test_hedefi: "BUITests" }, false);
    expect(degisti).toHaveBeenCalledOnce();
  });

  it("yetkisiz rolde düğme pasif ve nedenini söyler; açık/birleşmiş kurulumda çizilmez", async () => {
    await oturumAc("analist");
    const { rerender } = render(
      <MemoryRouter>
        <OturumProvider>
          <KurulumPrEylemi platform="android" kurulum={{ durum: "gerekli", number: null, url: null, baslik: null, eksikler: [], elle_adimlar: [] }} />
        </OturumProvider>
      </MemoryRouter>,
    );
    const dugme = await screen.findByRole("button", { name: "Kurulum PR'ı aç" });
    expect(dugme).toBeDisabled();
    rerender(
      <MemoryRouter>
        <OturumProvider>
          <KurulumPrEylemi platform="android" kurulum={{ durum: "birlesti", number: 4, url: null, baslik: null, eksikler: [], elle_adimlar: [] }} />
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByRole("button", { name: "Kurulum PR'ı aç" })).toBeNull();
  });
});

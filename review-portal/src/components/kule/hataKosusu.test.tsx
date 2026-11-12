// 012/Ş8: Kontrol Kulesi kalite KPI'ları ve "Ekilmiş hata koşusu" kartı (ANALIZ §4.6, §4.7, §7).
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { hataKosusuApi } from "../../api/client";
import { OlayProvider } from "../../api/events";
import { kuleAyar, kuleMockIlerlet, kuleMockKosulariBosalt } from "../../api/mock/kule";
import type { KontrolKulesi as Kule, Kosu } from "../../api/types";
import { kontrolKulesiUyarla } from "../../api/uyumDemoB";
import { OturumProvider } from "../../auth";
import { KontrolKulesi } from "../../pages/KontrolKulesi";
import { KosuTablosu } from "../../pages/Kosular";
import { oturumAc, sar } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { HataKosusuKarti } from "./HataKosusuKarti";
import { BeklentiDogruluguKarosu, HataYakalamaKarosu } from "./KaliteKpilari";

/** Olay akışıyla (süreç içi mock olay yolu) sarar: kart `hata_kosusu.ilerleme` olaylarını dinler. */
function olayli(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <OturumProvider>
        <OlayProvider etkin>
          <BildirimProvider>{ui}</BildirimProvider>
        </OlayProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const kule = (ek: Record<string, unknown>): Kule => kontrolKulesiUyarla({ gecme_orani: { oran: 1, toplam: 1, gecen: 1 }, ai_katkisi: {}, ...ek });
const kart = () => screen.findByRole("region", { name: "Ekilmiş hata koşusu" });
const hucre = (platform: string, kod: string) => screen.getByTestId(`hk-hucre-${platform}-${kod}`);

describe("KPI şeridi: Beklenti doğruluğu ve Hata yakalama oranı", () => {
  it("örnek veride iki karo şeridin sonunda; oran, sayılar, kapsam, istisna ve (i) kaynak ipucu", async () => {
    await oturumAc("sunucu");
    sar(<KontrolKulesi />);
    const serit = await screen.findByTestId("kule-kpi");
    expect(serit.children).toHaveLength(7);
    expect(serit.children[5]).toHaveTextContent("Beklenti doğruluğu");
    expect(serit.children[6]).toHaveTextContent("Hata yakalama oranı");
    expect(within(serit).getByTestId("beklenti-dogrulugu")).toHaveTextContent("%83");
    expect(within(serit).getByTestId("beklenti-ayrinti")).toHaveTextContent("5 uyumlu · 1 uyuşmayan · kapsam %70 · 1 kontrol edilemedi · 1 istisnayla onaylanan");
    expect(within(serit).getByTestId("hata-yakalama")).toHaveTextContent("%71");
    expect(within(serit).getByTestId("hata-yakalama-ayrinti")).toHaveTextContent(/^12\/17 hata yakalandı · 1 geçersiz \(orana girmez\) · son koşu 10 Kas/);
    expect(within(serit).getByRole("img", { name: /^Kaynak: case_oracle_kontrol/ })).toBeInTheDocument();
    expect(within(serit).getByRole("img", { name: /^Kaynak: hata_kosusu_adim/ })).toBeInTheDocument();
    // Var olan öğeler yerinde ve tekil.
    for (const id of ["gecme-orani", "defect-adayi-ozet", "hazirlik-kazanci"]) expect(within(serit).getAllByTestId(id)).toHaveLength(1);
    expect(screen.getAllByText("ölçülmüş baz yok")).toHaveLength(1);
  });

  it("anahtarlar yanıtta yoksa (eski core): 'ölçülmedi' + 'çekirdek bildirmedi'; sıfır ya da yüzde yazılmaz", () => {
    const k = kule({});
    render(
      <>
        <BeklentiDogruluguKarosu k={k} />
        <HataYakalamaKarosu k={k} />
      </>,
    );
    for (const id of ["beklenti-dogrulugu", "hata-yakalama"]) {
      expect(screen.getByTestId(id)).toHaveTextContent(/^ölçülmedi$/);
      expect(screen.getByTestId(id)).not.toHaveTextContent(/%|\d/);
    }
    expect(screen.getByTestId("beklenti-ayrinti")).toHaveTextContent("çekirdek bu ölçüyü bildirmedi");
    expect(screen.getByTestId("hata-yakalama-ayrinti")).toHaveTextContent("çekirdek bu ölçüyü bildirmedi");
    expect(screen.getAllByRole("img", { name: "Kaynak: core bu ölçünün kaynağını bildirmedi" })).toHaveLength(2);
  });

  it("beklenti doğruluğu: payda 0 (oran null) → ölçülmedi, sayılar yine görünür; anahtar null → ölçülmedi", () => {
    const { unmount } = render(
      <BeklentiDogruluguKarosu
        k={kule({ beklenti_dogrulugu: { oran: null, uyumlu: 0, uyumsuz: 0, kapsam_disi: 4, kontrol_edilemedi: 2, istisna: 0, kapsam_orani: null } })}
      />,
    );
    expect(screen.getByTestId("beklenti-dogrulugu")).toHaveTextContent(/^ölçülmedi$/);
    expect(screen.getByTestId("beklenti-ayrinti")).toHaveTextContent("tabloyla karşılaştırılan case yok · 4 kapsam dışı · 2 kontrol edilemedi · 0 istisnayla onaylanan");
    unmount();
    render(<BeklentiDogruluguKarosu k={kule({ beklenti_dogrulugu: null })} />);
    expect(screen.getByTestId("beklenti-dogrulugu")).toHaveTextContent(/^ölçülmedi$/);
  });

  it("hata yakalama: koşu yok (null) → 'ölçülmedi · henüz ekilmiş hata koşusu yok'; yalnız geçersiz adım → ölçülmedi", () => {
    const { unmount } = render(<HataYakalamaKarosu k={kule({ hata_yakalama: null })} />);
    expect(screen.getByTestId("hata-yakalama")).toHaveTextContent(/^ölçülmedi$/);
    expect(screen.getByTestId("hata-yakalama-ayrinti")).toHaveTextContent("henüz ekilmiş hata koşusu yok");
    unmount();
    render(
      <HataYakalamaKarosu
        k={kule({ hata_yakalama: { son_kosu: { id: "f1", bitis: "2026-11-10T10:00:00+03:00", durum: "done" }, oran: null, yakalanan: 0, kacan: 0, gecersiz: 3 } })}
      />,
    );
    expect(screen.getByTestId("hata-yakalama")).toHaveTextContent(/^ölçülmedi$/);
    expect(screen.getByTestId("hata-yakalama-ayrinti")).toHaveTextContent(/^sayılan adım yok · 3 geçersiz \(orana girmez\) · son koşu 10 Kas/);
  });

  it("örnek veride hiç koşu yokken: karo ölçülmedi, kart boş durum", async () => {
    await oturumAc("sunucu");
    kuleMockKosulariBosalt();
    sar(<KontrolKulesi />);
    expect(await screen.findByTestId("hata-yakalama")).toHaveTextContent(/^ölçülmedi$/);
    const k = await kart();
    expect(await within(k).findByText("Henüz ekilmiş hata koşusu yok.")).toBeInTheDocument();
    expect(within(k).queryByTestId("hk-sonuc")).toBeNull();
    expect(within(k).queryByTestId("hk-gecmis")).toBeNull();
  });
});

describe("Ekilmiş hata koşusu kartı: form ve rol kapısı", () => {
  it("açıklama; web işaretli, diğer platformlar boş (V5); dokuz hata türüne göre gruplu ve hepsi seçili; süre notu", async () => {
    await oturumAc("sunucu");
    sar(<HataKosusuKarti />);
    const k = await kart();
    expect(within(k).getByTestId("hk-aciklama")).toHaveTextContent(/tek bir hatayla bilerek bozulur.*yakalandı.*kaçtı.*kasıtlı kırma/);
    const platformlar = within(k).getByRole("group", { name: "Platformlar" });
    expect(within(platformlar).getByRole("checkbox", { name: "Web" })).toBeChecked();
    for (const ad of ["Android", "iOS", "Windows"]) expect(within(platformlar).getByRole("checkbox", { name: ad })).not.toBeChecked();
    const kod = await within(k).findByRole("group", { name: "Kod hatası (5)" });
    const veri = within(k).getByRole("group", { name: "Veri hatası (4)" });
    expect(within(kod).getAllByRole("checkbox")).toHaveLength(5);
    expect(within(veri).getAllByRole("checkbox")).toHaveLength(4);
    for (const c of [...within(kod).getAllByRole("checkbox"), ...within(veri).getAllByRole("checkbox")]) expect(c).toBeChecked();
    expect(within(kod).getByRole("checkbox", { name: "Kampanya eşiği 6 yerine 7" })).toHaveAccessibleDescription(/adet \/\/ 7.*Yakalaması beklenen kural: kampanya \(6'nın katlarında\)\..*kampanya_esik_7/);
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("Seçim: 9 hata × 1 platform = 11 koşu");
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("Android, iOS ve Windows'ta her hata 3–5 dakika sürer");
    expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toBeEnabled();
  });

  it("uygulama platformu seçilince süre tahmini; platform ya da hata kalmayınca düğme pasif ve nedeni görünür", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const k = await kart();
    await within(k).findByRole("group", { name: "Kod hatası (5)" });
    await u.click(within(k).getByRole("checkbox", { name: "Android" }));
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("9 hata × 2 platform = 22 koşu");
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("yaklaşık 27–45 dakika");
    await u.click(within(k).getByRole("checkbox", { name: "Android" }));
    await u.click(within(k).getByRole("checkbox", { name: "Web" }));
    const dugme = within(k).getByRole("button", { name: "Koşuyu başlat" });
    expect(dugme).toBeDisabled();
    expect(dugme).toHaveAccessibleDescription("En az bir platform seçin.");
    expect(within(k).getByText("En az bir platform seçin.")).toHaveClass("dugme-neden");
    await u.click(within(k).getByRole("checkbox", { name: "Web" }));
    for (const c of within(k).getAllByRole("checkbox").filter((x) => (x as HTMLInputElement).checked && !x.dataset.testid)) await u.click(c);
    expect(dugme).toHaveAccessibleDescription("En az bir hata seçin.");
  });

  it.each([
    ["analist", false],
    ["po", false],
    ["testci", false],
    ["muhendis", true],
    ["sunucu", true],
  ])("%s: başlatabilir mi → %s (diğer rollerde form pasif, neden görünür; sonuçlar yine okunur)", async (kullanici, yetkili) => {
    await oturumAc(kullanici);
    sar(<HataKosusuKarti />);
    const k = await kart();
    await within(k).findByRole("group", { name: "Kod hatası (5)" });
    const dugme = within(k).getByRole("button", { name: "Koşuyu başlat" });
    if (yetkili) {
      expect(dugme).toBeEnabled();
      expect(within(k).getByRole("checkbox", { name: "Android" })).toBeEnabled();
      expect(k.querySelector(".dugme-neden")).toBeNull();
    } else {
      expect(dugme).toBeDisabled();
      expect(dugme).toHaveAccessibleDescription("Bu işlem için gereken rol: Mühendis / Sunucu");
      expect(within(k).getByText("Bu işlem için gereken rol: Mühendis / Sunucu")).toHaveClass("dugme-neden");
      for (const c of within(k).getAllByRole("checkbox")) expect(c).toBeDisabled();
    }
    expect(await within(k).findByTestId("hk-sonuc")).toBeInTheDocument();
  });
});

describe("Ekilmiş hata koşusu kartı: sonuç tablosu, kaçan hatalar, geçmiş", () => {
  it("satırlar hata, sütunlar platform; ✓ yakalandı / ✗ kaçtı / ⚠ geçersiz metin olarak; koşu bağlantıları; kıran testler açılır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const tablo = within(await screen.findByRole("region", { name: "Ekilmiş hata sonuç tablosu" }));
    expect(tablo.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Hata", "Web", "Android"]);
    // Temel + dokuz hata + kapanış + oran satırı.
    expect(tablo.getAllByRole("rowheader")).toHaveLength(12);
    expect(tablo.getByRole("rowheader", { name: /Kampanya eşiği 6 yerine 7.*Kod hatası.*kampanya_esik_7/ })).toBeInTheDocument();

    expect(hucre("web", "kampanya_bedava_yok")).toHaveTextContent("✓ yakalandı");
    expect(hucre("web", "kampanya_esik_7")).toHaveTextContent("✗ kaçtı");
    expect(hucre("android", "min_siparis_1000")).toHaveTextContent("⚠ geçersiz");
    // Geçersizin nedeni görünür metin (yalnız ipucu değil); koşusu olmadığı için bağlantı yok.
    expect(within(hucre("android", "min_siparis_1000")).getByText(/Neden: Appium oturumu koptu/)).toBeVisible();
    expect(within(hucre("android", "min_siparis_1000")).queryByRole("link")).toBeNull();
    // Temel ve kapanış koşusu platform başına.
    for (const p of ["web", "android"]) {
      expect(screen.getByTestId(`hk-temel-${p}`)).toHaveTextContent("✓ yeşil");
      expect(screen.getByTestId(`hk-kapanis-${p}`)).toHaveTextContent("✓ yeşil");
    }
    // Her hücre kendi koşusuna bağlanır.
    expect(within(hucre("web", "kampanya_bedava_yok")).getByRole("link", { name: /koşuyu aç: Kampanyada bedava ürün verilmiyor · Web/ })).toHaveAttribute("href", "/kosular/hk-1-r2");
    expect(within(hucre("web", "kampanya_esik_7")).getByRole("link")).toHaveAttribute("href", "/kosular/hk-1-r3");
    expect(within(screen.getByTestId("hk-temel-android")).getByRole("link")).toHaveAttribute("href", "/kosular/hk-1-r12");
    // Yakalayan testler: açılır liste.
    const ozet = within(hucre("web", "kampanya_bedava_yok")).getByText(/^2 test yakaladı/);
    expect(ozet.closest("details")).not.toHaveAttribute("open");
    await u.click(ozet);
    expect(ozet.closest("details")).toHaveAttribute("open");
    expect(within(hucre("web", "kampanya_bedava_yok")).getAllByRole("listitem").map((x) => x.textContent)).toEqual([
      "TPD-1 C2 · 7 adet kampanyalı üründe 1 adet bedava",
      "TPD-1 C7 · Kampanya indirimi sepet toplamından bir kez düşülür",
    ]);
    expect(within(hucre("web", "kampanya_esik_7")).queryByText(/test yakaladı/)).toBeNull();
  });

  it("platform başına oran; geçersiz adım paydaya girmez ve bunu ekran söyler", async () => {
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    await screen.findByTestId("hk-sonuc");
    expect(screen.getByTestId("hk-oran-web")).toHaveTextContent(/^%78 \(7\/9\)$/);
    // Android: 5 yakalandı, 3 kaçtı, 1 geçersiz → 5/8 (5/9 değil).
    expect(screen.getByTestId("hk-oran-android")).toHaveTextContent("%63 (5/8)");
    expect(screen.getByTestId("hk-oran-android")).toHaveTextContent("⚠ 1 geçersiz (orana girmez)");
    expect(screen.getByTestId("hk-oran-genel")).toHaveTextContent("%71 (12/17)");
    expect(screen.getByTestId("hk-oran-notu")).toHaveTextContent(/Oran = yakalanan \/ \(yakalanan \+ kaçan\)\. ⚠ Geçersiz adımlar .* orana girmez/);
  });

  it("'Kaçan hatalar' ayrı ve görünür: hiçbir testin yakalamadığı hatalar, platformlarıyla; yakalanan ya da geçersiz hata listede yok", async () => {
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    const liste = within(await screen.findByTestId("hk-kacanlar"));
    expect(liste.getByRole("heading", { name: "Kaçan hatalar", level: 3 })).toBeVisible();
    expect(liste.getAllByRole("listitem")).toHaveLength(3);
    expect(liste.getByTestId("hk-kacan-kampanya_esik_7")).toHaveTextContent("✗ Kampanya eşiği 6 yerine 7 · Web, Android");
    expect(liste.getByTestId("hk-kacan-fiyat_p004_31")).toHaveTextContent("P-004 fiyatı 30 yerine 31 · Web, Android");
    expect(liste.getByTestId("hk-kacan-kampanya_cift_indirim")).toHaveTextContent("Kampanya indirimi iki kez düşülüyor · Android");
    expect(liste.queryByTestId("hk-kacan-min_siparis_1000")).toBeNull();
    expect(liste.queryByTestId("hk-kacan-kampanya_bedava_yok")).toBeNull();
    expect(liste.getByText(/bütün onaylı testler yeşil kaldı/)).toBeInTheDocument();
  });

  it("geçmiş: tarih, başlatan, platformlar, oran; eski koşu açılabilir", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok", "kampanya_esik_7"] });
    while (kuleMockIlerlet());
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const gecmis = within(await screen.findByTestId("hk-gecmis"));
    expect(gecmis.getByRole("heading", { name: "Son koşular", level: 3 })).toBeInTheDocument();
    const yeni = within(gecmis.getByTestId("hk-gecmis-hk-2"));
    const eski = within(gecmis.getByTestId("hk-gecmis-hk-1"));
    expect(gecmis.getAllByRole("row").map((r) => r.getAttribute("data-testid"))).toEqual([null, "hk-gecmis-hk-2", "hk-gecmis-hk-1"]);
    expect(yeni.getByText("%50 (1/2)")).toBeInTheDocument();
    expect(yeni.getByText("Web")).toBeInTheDocument();
    expect(yeni.getByText("Gokhan Sipahi · Mühendis")).toBeInTheDocument();
    expect(yeni.getByText("gösteriliyor")).toBeInTheDocument();
    expect(eski.getByText("%71 (12/17)")).toBeInTheDocument();
    expect(eski.getByText("Web, Android")).toBeInTheDocument();
    expect(eski.getByText("· 1 geçersiz")).toBeInTheDocument();
    expect(eski.getByText(/^10 Kas/)).toBeInTheDocument();
    // En yeni koşu gösterilir; eskisi "Aç" ile açılır.
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-2"));
    expect(screen.queryByTestId("hk-oran-android")).toBeNull();
    await u.click(eski.getByRole("button", { name: /^Aç: 10 Kas/ }));
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-1"));
    expect(screen.getByTestId("hk-oran-android")).toBeInTheDocument();
    expect(within(screen.getByTestId("hk-gecmis-hk-1")).getByText("gösteriliyor")).toBeInTheDocument();
  });

  it("koşu listesinde ekilmiş hata adımı 'Ekilmiş hata: <ad>' okunur; diğer koşuların metni değişmez", () => {
    const k = (ek: Partial<Kosu>): Kosu => ({
      id: "run-1",
      tetik: "break_verify",
      kaynak: "local",
      commit: "abc",
      pr_no: null,
      durum: "failed",
      baslangic: "2026-11-10T10:00:00+03:00",
      sure_ms: 1000,
      toplam: 6,
      gecen: 5,
      basarisiz: 1,
      flaky: 0,
      atlanan: 0,
      allure_url: null,
      rapor_url: null,
      sauce_url: null,
      ci_url: null,
      break_campaign: false,
      script_id: null,
      saglik_hatasi: null,
      ...ek,
    });
    sar(<KosuTablosu kosular={[k({ id: "run-1", hata_kodu: "min_siparis_500" }), k({ id: "run-2", break_campaign: true })]} kompakt />);
    const satirlar = screen.getAllByRole("row");
    expect(satirlar[1]).toHaveTextContent("Ekilmiş hata: Minimum sipariş 750 yerine 500");
    expect(satirlar[2]).not.toHaveTextContent("Ekilmiş hata");
    expect(satirlar[2]).toHaveTextContent("kırma");
    expect(satirlar[1]).toHaveTextContent("Kırarak doğrula");
  });
});

describe("Ekilmiş hata koşusu kartı: başlat → ilerleme → bitiş, 409, iptal", () => {
  it("sunucu web koşusu başlatır: ilerleme (platform, hata, adım sayacı) olaylarla güncellenir; bitince tablo ve Kule ölçüsü yenilenir", async () => {
    await oturumAc("sunucu");
    kuleAyar.adimMs = 3_600_000; // zamanlayıcı ateşlemez; adımlar kuleMockIlerlet ile sürülür
    const u = userEvent.setup();
    const olcuDegisti = vi.fn();
    olayli(<HataKosusuKarti olcuDegisti={olcuDegisti} />);
    const k = await kart();
    // Yalnız iki hata: bir kod, bir veri.
    for (const c of within(await within(k).findByRole("group", { name: "Kod hatası (5)" })).getAllByRole("checkbox").slice(1)) await u.click(c);
    for (const c of within(within(k).getByRole("group", { name: "Veri hatası (4)" })).getAllByRole("checkbox").slice(0, 3)) await u.click(c);
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("2 hata × 1 platform = 4 koşu");
    await u.click(within(k).getByRole("button", { name: "Koşuyu başlat" }));

    const ilerleme = within(await within(k).findByTestId("hk-ilerleme"));
    expect(ilerleme.getByText("Koşu sırada")).toBeInTheDocument();
    expect(await ilerleme.findByTestId("hk-sayac")).toHaveTextContent("adım 1 / 4");
    expect(ilerleme.getByTestId("hk-simdiki")).toHaveTextContent("Web · Temel koşu (hatasız)");
    // Süren koşu varken yenisi başlatılamaz; neden görünür.
    expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toBeDisabled();
    expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toHaveAccessibleDescription("Süren koşu bitmeden yenisi başlatılamaz.");
    expect(within(k).getByRole("checkbox", { name: "Web" })).toBeDisabled();
    // Süren koşunun tablosu: adımlar henüz bekliyor, oran "sürüyor".
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-2"));
    expect(hucre("web", "kampanya_bedava_yok")).toHaveTextContent("bekliyor");
    expect(screen.getByTestId("hk-oran-web")).toHaveTextContent("sürüyor");
    expect(screen.getByTestId("hk-kacan-yok")).toHaveTextContent("Koşu sürüyor");

    act(() => void kuleMockIlerlet()); // queued → running
    expect(await ilerleme.findByText("Koşu sürüyor")).toBeInTheDocument();
    act(() => void kuleMockIlerlet()); // temel
    act(() => void kuleMockIlerlet()); // kampanya_bedava_yok
    await waitFor(() => expect(ilerleme.getByTestId("hk-sayac")).toHaveTextContent("adım 3 / 4"));
    expect(ilerleme.getByTestId("hk-simdiki")).toHaveTextContent("Web · Kampanyalı ürün P-001 yerine P-002");
    expect(ilerleme.getByRole("meter", { name: "Ekilmiş hata koşusu ilerlemesi" })).toHaveAttribute("aria-valuenow", "50");
    expect(hucre("web", "kampanya_bedava_yok")).toHaveTextContent("✓ yakalandı");
    expect(olcuDegisti).not.toHaveBeenCalled();

    act(() => void kuleMockIlerlet()); // kampanya_urunu_p002
    act(() => void kuleMockIlerlet()); // kapanış → done
    await waitFor(() => expect(within(k).queryByTestId("hk-ilerleme")).toBeNull());
    expect(screen.getByTestId("hk-oran-web")).toHaveTextContent("%100 (2/2)");
    expect(screen.getByTestId("hk-kapanis-web")).toHaveTextContent("✓ yeşil");
    expect(screen.getByTestId("hk-kacan-yok")).toHaveTextContent("Kaçan hata yok");
    expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toBeEnabled();
    expect(within(screen.getByTestId("hk-gecmis-hk-2")).getByText("Tamamlandı")).toBeInTheDocument();
    await waitFor(() => expect(olcuDegisti).toHaveBeenCalledTimes(1));
  });

  it("409 hata_kosusu_suruyor: 'süren koşu var' mesajı; süren koşu ekrana gelir", async () => {
    await oturumAc("sunucu");
    kuleAyar.adimMs = 3_600_000;
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const k = await kart();
    await within(k).findByRole("group", { name: "Kod hatası (5)" });
    await within(k).findByTestId("hk-sonuc");
    // Ekran açıldıktan sonra başka biri koşu başlattı (ekran bunu henüz bilmiyor).
    await hataKosusuApi.baslat({ platformlar: ["web"] });
    await u.click(within(k).getByRole("button", { name: "Koşuyu başlat" }));
    expect(await within(k).findByTestId("hk-hata")).toHaveTextContent("Süren bir ekilmiş hata koşusu var. Bitmesini bekleyin ya da koşuyu iptal edin.");
    expect(within(k).getByTestId("hk-hata").closest("[role='alert']")).not.toBeNull();
    expect(await within(k).findByTestId("hk-ilerleme")).toBeInTheDocument();
    expect((await hataKosusuApi.liste()).map((x) => x.id)).toEqual(["hk-2", "hk-1"]);
  });

  it("iptal: süren koşu 'İptal edildi' olur, ilerleme kapanır, koşmayan adımlar bekliyor kalır; form yeniden açılır", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok", "kampanya_esik_7"] });
    kuleMockIlerlet();
    kuleMockIlerlet();
    kuleMockIlerlet();
    const u = userEvent.setup();
    olayli(<HataKosusuKarti />);
    const k = await kart();
    const ilerleme = within(await within(k).findByTestId("hk-ilerleme"));
    expect(await ilerleme.findByTestId("hk-sayac")).toHaveTextContent("adım 3 / 4");
    await u.click(ilerleme.getByRole("button", { name: "İptal et" }));
    await waitFor(() => expect(within(k).queryByTestId("hk-ilerleme")).toBeNull());
    expect((await hataKosusuApi.detay("hk-2")).durum).toBe("cancelled");
    expect(await within(screen.getByTestId("hk-gecmis-hk-2")).findByText("İptal edildi")).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByTestId("hk-sonuc")).getByText(/Koşu iptal edildi/)).toBeInTheDocument());
    expect(hucre("web", "kampanya_bedava_yok")).toHaveTextContent("✓ yakalandı");
    expect(hucre("web", "kampanya_esik_7")).toHaveTextContent("bekliyor");
    // Sayılan tek adım yakalandı: oran 1/1; kalan adım orana girmez.
    expect(screen.getByTestId("hk-oran-web")).toHaveTextContent("%100 (1/1)");
    expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toBeEnabled();
  });

  it("iptal düğmesi de rol kapılı: analist süren koşuyu görür ama iptal edemez (neden görünür)", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web"] });
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    const ilerleme = within(await screen.findByTestId("hk-ilerleme"));
    expect(ilerleme.getByRole("button", { name: "İptal et" })).toBeDisabled();
    expect(ilerleme.getByRole("button", { name: "İptal et" })).toHaveAccessibleDescription("Bu işlem için gereken rol: Mühendis / Sunucu");
  });
});

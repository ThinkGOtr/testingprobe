// 012/Ş8: Kontrol Kulesi kalite KPI'ları ve "Ekilmiş hata koşusu" kartı (ANALIZ §4.6, §4.7, §7).
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { hataKosusuApi } from "../../api/client";
import { OlayProvider } from "../../api/events";
import { kuleAyar, kuleMockIlerlet, kuleMockKosulariBosalt } from "../../api/mock/kule";
import type { KontrolKulesi as Kule, Kosu } from "../../api/types";
import { kontrolKulesiUyarla } from "../../api/uyumDemoB";
import { hataKosusuDetayUyarla } from "../../api/uyumKule";
import { OturumProvider } from "../../auth";
import { KontrolKulesi } from "../../pages/KontrolKulesi";
import { KosuTablosu } from "../../pages/Kosular";
import { oturumAc, sar } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { HataKosusuKarti } from "./HataKosusuKarti";
import { BeklentiDogruluguKarosu, HataYakalamaKarosu, OnayliUyumsuzKarti } from "./KaliteKpilari";

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
    // §13.2: kısmen ayrı (orana girmez), kapsamın paydası etiketli, kontrolsüz onay sayacı; n ve "gösterge".
    expect(within(serit).getByTestId("beklenti-ayrinti")).toHaveTextContent(
      "5 uyumlu · 1 uyuşmayan · 1 kısmen (orana girmez) · tablosu olan story'lerde kapsam %70 · tablosu olan story: 1 / 4 · 1 istisnayla onaylanan · 0 kontrolsüz onay",
    );
    expect(within(serit).getByTestId("beklenti-n")).toHaveTextContent(/^n = 10 case · 1 story · REPLAY \/ elle golden gösterge$/);
    // K12: ana oran yalnız AI testleri — demo deposunda üretilmiş test yok → ölçülmedi; el yazısı suite ayrı.
    expect(within(serit).getByTestId("hata-yakalama")).toHaveTextContent(/^ölçülmedi$/);
    expect(within(serit).getByTestId("hata-yakalama-ayrinti")).toHaveTextContent(
      /^AI testleri: ölçülmedi \(üretilmiş test yok\) · el yazısı suite %88 \(15\/17\) · 9 ekilmiş hata üzerinde · Web, Android · 1 geçersiz \(orana girmez\) · son koşu 10 Kas/,
    );
    // Kaynak metinleri core'unkiyle aynı (`metrik.KAYNAK`, `hata_yakalama_ozeti`).
    expect(within(serit).getByRole("img", { name: /^Kaynak: AI'ın ürettiği case içeriklerinin/ })).toBeInTheDocument();
    expect(within(serit).getByRole("img", { name: /^Kaynak: Son tamamlanan tam katalog ekilmiş hata koşusu \(2026-11-10 14:46; web, android\)/ })).toBeInTheDocument();
    // Var olan öğeler yerinde ve tekil.
    for (const id of ["gecme-orani", "defect-adayi-ozet", "hazirlik-kazanci"]) expect(within(serit).getAllByTestId(id)).toHaveLength(1);
    expect(screen.getAllByText("ölçülmüş baz yok")).toHaveLength(1);
  });

  it("anahtarlar yanıtta yoksa (eski core): 'ölçülmedi' + 'çekirdek bildirmiyor'; sıfır ya da yüzde yazılmaz", () => {
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
    // Oracle metriğiyle aynı tek ifade.
    expect(screen.getByTestId("beklenti-ayrinti")).toHaveTextContent("çekirdek bu ölçümü bildirmiyor");
    expect(screen.getByTestId("hata-yakalama-ayrinti")).toHaveTextContent("çekirdek bu ölçümü bildirmiyor");
    expect(screen.queryByTestId("beklenti-n")).toBeNull();
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
    expect(within(kod).getByRole("checkbox", { name: "Kampanyada en çok 1 bedava" })).toHaveAccessibleDescription(
      /min\(1, adet \/\/ 6\).*Yakalaması beklenen kural: Kampanya \(katlarda bedava adet\)\..*kampanya_tek_bedava/,
    );
    // Aritmetik açık: hata + çerçeve koşuları (temel, kapanış) = platform başına koşu; toplam ve web süresi.
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent(
      "Seçim: 9 hata + 2 çerçeve koşusu (temel, kapanış) = 11 koşu / platform; 1 platform × 11 = toplam 11 koşu.",
    );
    expect(within(k).getByTestId("hk-sure-tahmini")).toHaveTextContent("Tahmini süre: yaklaşık 11 dakika (web'de koşu başına ~1 dk)");
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("Android, iOS ve Windows'ta her koşu 3–5 dakika sürer");
    expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toBeEnabled();
  });

  it("uygulama platformu seçilince süre tahmini; platform ya da hata kalmayınca düğme pasif ve nedeni görünür", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const k = await kart();
    await within(k).findByRole("group", { name: "Kod hatası (5)" });
    await u.click(within(k).getByRole("checkbox", { name: "Android" }));
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("2 platform × 11 = toplam 22 koşu");
    // Web 11 × 1 dk + Android 11 × 3–5 dk (temel ve kapanış dahil).
    expect(within(k).getByTestId("hk-sure-tahmini")).toHaveTextContent("yaklaşık 44–66 dakika");
    await u.click(within(k).getByRole("checkbox", { name: "Android" }));
    await u.click(within(k).getByRole("checkbox", { name: "Web" }));
    const dugme = within(k).getByRole("button", { name: "Koşuyu başlat" });
    expect(dugme).toBeDisabled();
    expect(dugme).toHaveAccessibleDescription("En az bir platform seçin.");
    expect(within(k).getByText("En az bir platform seçin.")).toHaveClass("dugme-neden");
    await u.click(within(k).getByRole("checkbox", { name: "Web" }));
    for (const c of within(k).getAllByRole("checkbox").filter((x) => (x as HTMLInputElement).checked && !x.dataset.testid)) await u.click(c);
    expect(dugme).toHaveAccessibleDescription("En az bir hata seçin.");
  }, 20_000);

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
    // Temel + dokuz hata + kapanış + üç oran satırı (AI, el yazısı, tüm testler).
    expect(tablo.getAllByRole("rowheader")).toHaveLength(14);
    expect(tablo.getByRole("rowheader", { name: /Kampanyada en çok 1 bedava.*Kod hatası.*kampanya_tek_bedava/ })).toBeInTheDocument();

    expect(hucre("web", "kampanya_bedava_yok")).toHaveTextContent("✓ yakalandı");
    expect(hucre("web", "kampanya_tek_bedava")).toHaveTextContent("✗ kaçtı");
    expect(hucre("android", "min_siparis_1000")).toHaveTextContent("⚠ geçersiz");
    // Geçersizin nedeni görünür metin (yalnız ipucu değil); koşusu olmadığı için bağlantı yok.
    expect(within(hucre("android", "min_siparis_1000")).getByText(/Neden: Cihaz\/Appium erişilemiyor/)).toBeVisible();
    expect(within(hucre("android", "min_siparis_1000")).queryByRole("link")).toBeNull();
    // Temel ve kapanış koşusu platform başına.
    for (const p of ["web", "android"]) {
      expect(screen.getByTestId(`hk-temel-${p}`)).toHaveTextContent("✓ yeşil");
      expect(screen.getByTestId(`hk-kapanis-${p}`)).toHaveTextContent("✓ yeşil");
    }
    // Her hücre kendi koşusuna bağlanır.
    expect(within(hucre("web", "kampanya_bedava_yok")).getByRole("link", { name: /koşuyu aç: Kampanyada bedava ürün verilmiyor · Web/ })).toHaveAttribute("href", "/kosular/hk-1-r2");
    expect(within(hucre("web", "kampanya_tek_bedava")).getByRole("link")).toHaveAttribute("href", "/kosular/hk-1-r3");
    expect(within(screen.getByTestId("hk-temel-android")).getByRole("link")).toHaveAttribute("href", "/kosular/hk-1-r12");
    // Yakalayan testler: açılır liste.
    const ozet = within(hucre("web", "kampanya_bedava_yok")).getByText(/^3 test yakaladı \(3 el yazısı\)/);
    expect(ozet.closest("details")).not.toHaveAttribute("open");
    await u.click(ozet);
    expect(ozet.closest("details")).toHaveAttribute("open");
    // Her kıran test kaynağıyla (§13.2): demo deposunda hepsi el yazısı.
    expect(within(hucre("web", "kampanya_bedava_yok")).getAllByRole("listitem").map((x) => x.textContent)).toEqual([
      "kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL el yazısı",
      "onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir el yazısı",
      "7 adet Portakal Gazozu sepette 1 bedava adet ve sayaç 7 gösterir el yazısı",
    ]);
    expect(within(hucre("web", "kampanya_tek_bedava")).queryByText(/test yakaladı/)).toBeNull();
  }, 20_000);

  it("platform başına oran; geçersiz adım paydaya girmez ve bunu ekran söyler", async () => {
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    await screen.findByTestId("hk-sonuc");
    // Web: demo uygulamada ölçülen gerçek matris (8/9).
    expect(screen.getByTestId("hk-oran-web")).toHaveTextContent(/^%89 \(8\/9\)$/);
    // Android: 7 yakalandı, 1 kaçtı, 1 geçersiz → 7/8 (7/9 değil).
    expect(screen.getByTestId("hk-oran-android")).toHaveTextContent("%88 (7/8)");
    expect(screen.getByTestId("hk-oran-android")).toHaveTextContent("⚠ 1 geçersiz (orana girmez)");
    expect(screen.getByTestId("hk-oran-genel")).toHaveTextContent("%88 (15/17)");
    // K12: AI (ana oran) ve el yazısı ayrı satır; üretilmiş test yokken AI ölçülmedi (sıfır yazılmaz).
    for (const p of ["web", "android"]) expect(screen.getByTestId(`hk-oran-ai-${p}`)).toHaveTextContent(/^ölçülmedi — üretilmiş test yok$/);
    expect(screen.getByTestId("hk-oran-el-web")).toHaveTextContent(/^%89 \(8\/9\)$/);
    expect(screen.getByTestId("hk-oran-el-android")).toHaveTextContent(/^%88 \(7\/8\)$/);
    expect(screen.getByTestId("hk-oran-ayrik")).toHaveTextContent("AI testleri: ölçülmedi (üretilmiş test yok) · El yazısı: %88 (15/17)");
    expect(screen.getByTestId("hk-oran-notu")).toHaveTextContent(/Ana oran yalnız onaylı case'lerden üretilen \(AI\) testlerle/);
    // Kapsam ve suite satırı; kural × hata dağılımı.
    expect(screen.getByTestId("hk-kapsam")).toHaveTextContent(/^Kapsam: 9\/9 katalog hatası · Web, Android$/);
    expect(screen.getByTestId("hk-suite")).toHaveTextContent("Suite: temel koşuda kırmızı test yok; bütün testler sayıldı.");
    const dagilim = within(screen.getByTestId("hk-kural-dagilim"));
    expect(dagilim.getByText(/^9 ekilmiş hata üzerinde \(mutation score değildir/)).toBeInTheDocument();
    expect(dagilim.getAllByRole("rowheader").map((x) => x.textContent)).toEqual(["T1 · AC2", "T2 · AC3", "T2 · AC6", "AC1 (tablo yok)"]);
    expect(dagilim.getByRole("rowheader", { name: "T1 · AC2" }).closest("tr")).toHaveTextContent(/^T1 · AC2\s*43 \/ 4 · ✗ 1 kaçtı3 \/ 4 · ✗ 1 kaçtı$/);
    expect(screen.getByTestId("hk-oran-notu")).toHaveTextContent(/Oran = yakalanan \/ \(yakalanan \+ kaçan\)\. ⚠ Geçersiz adımlar .* orana girmez/);
  });

  it("'Kaçan hatalar' ayrı ve görünür: hiçbir testin yakalamadığı hatalar, platformlarıyla; yakalanan ya da geçersiz hata listede yok", async () => {
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    const liste = within(await screen.findByTestId("hk-kacanlar"));
    expect(liste.getByRole("heading", { name: "Kaçan hatalar", level: 3 })).toBeVisible();
    // Gerçek web matrisinde yalnız kampanya_tek_bedava kaçar.
    expect(liste.getAllByRole("listitem")).toHaveLength(1);
    expect(liste.getByTestId("hk-kacan-kampanya_tek_bedava")).toHaveTextContent("✗ Kampanyada en çok 1 bedava · Web, Android");
    expect(liste.queryByTestId("hk-kacan-fiyat_p004_31")).toBeNull();
    expect(liste.queryByTestId("hk-kacan-min_siparis_1000")).toBeNull();
    expect(liste.queryByTestId("hk-kacan-kampanya_bedava_yok")).toBeNull();
    expect(liste.getByText(/bütün onaylı testler yeşil kaldı/)).toBeInTheDocument();
  });

  it("kaçan hata uygulanabilir: kural bağlantısı (T1 · AC2), ayırt edici girdi, 'Bu girdiyle ek case türet' ve kopyalanabilir case isteği", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const yaz = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: yaz }, configurable: true });
    sar(<HataKosusuKarti />);
    const kacan = within(await screen.findByTestId("hk-kacan-kampanya_tek_bedava"));
    // Kural: karar tablosuna bağlantı (T1 = gereksinimin 1 numaralı tablosu).
    expect(await kacan.findByRole("link", { name: /^T1 · AC2\s*karar tablosunu aç$/ })).toHaveAttribute("href", "/gereksinimler/req-tpd-1/karar-tablolari#tablo-kt-1");
    expect(kacan.getByTestId("hk-kacan-ayrinti-kampanya_tek_bedava")).toHaveTextContent("Ayırt edici girdiadet = 14 → doğru bedava_adet = 2, hatalı uygulama bedava_adet = 1");
    expect(kacan.getByRole("link", { name: "Bu girdiyle ek case türet" })).toHaveAttribute("href", "/gereksinimler/req-tpd-1/karar-tablolari#ek-case-turet");
    const istek =
      'Case isteği: ekilmiş hata "Kampanyada en çok 1 bedava" (kampanya_tek_bedava) Web, Android koşusunda hiçbir onaylı testle yakalanmadı. ' +
      "Kural: T1 · AC2. Ayırt edici örnek: adet = 14 → doğru: bedava_adet = 2; hatalı uygulama: bedava_adet = 1. " +
      "Bu girdiyle beklenen değeri onaylı karar tablosuna göre yazan bir case ekleyin.";
    expect(kacan.getByTestId("hk-istek-kampanya_tek_bedava")).toHaveTextContent(istek);
    await u.click(kacan.getByRole("button", { name: "Case isteğini kopyala" }));
    expect(yaz).toHaveBeenCalledWith(istek);
    expect(await screen.findByText("Case isteği panoya kopyalandı.")).toBeInTheDocument();
  });

  it("geçmiş: tarih, başlatan, platformlar, oran; eski koşu açılabilir", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok", "kampanya_tek_bedava"] });
    while (kuleMockIlerlet());
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const gecmis = within(await screen.findByTestId("hk-gecmis"));
    expect(gecmis.getByRole("heading", { name: "Son koşular", level: 3 })).toBeInTheDocument();
    const yeni = within(gecmis.getByTestId("hk-gecmis-hk-2"));
    const eski = within(gecmis.getByTestId("hk-gecmis-hk-1"));
    expect(gecmis.getAllByRole("row").map((r) => r.getAttribute("data-testid"))).toEqual([null, "hk-gecmis-hk-2", "hk-gecmis-hk-1"]);
    // §13.2: AI ve el yazısı ayrı; üretilmiş test yokken AI ölçülmedi.
    expect(yeni.getByRole("cell", { name: "AI ölçülmedi · el yazısı %50 (1/2)" })).toBeInTheDocument();
    expect(yeni.getByText("Web")).toBeInTheDocument();
    expect(yeni.getByText("Gokhan Sipahi · Mühendis")).toBeInTheDocument();
    expect(yeni.getByText("gösteriliyor")).toBeInTheDocument();
    expect(eski.getByText(/el yazısı %88 \(15\/17\)/)).toBeInTheDocument();
    expect(eski.getByText("Web, Android")).toBeInTheDocument();
    expect(eski.getByText("· 1 geçersiz")).toBeInTheDocument();
    expect(eski.getByText(/^10 Kas/)).toBeInTheDocument();
    // En yeni koşu gösterilir; eskisi "Aç" ile açılır.
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-2"));
    expect(screen.queryByTestId("hk-oran-android")).toBeNull();
    await u.click(eski.getByRole("button", { name: /^Aç: 10 Kas/ }));
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-1"));
    // "Aç" düğmesi kaybolur; odak açılan koşunun sonuç başlığına geçer.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sonuç tablosu", level: 3 })).toHaveFocus());
    expect(screen.getByTestId("hk-oran-android")).toBeInTheDocument();
    expect(within(screen.getByTestId("hk-gecmis-hk-1")).getByText("gösteriliyor")).toBeInTheDocument();
  }, 20_000);

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
    expect(satirlar[1]).toHaveTextContent("Ekilmiş hata: Minimum sipariş tutarı 500");
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
    expect(within(k).getByTestId("hk-tahmin")).toHaveTextContent("2 hata + 2 çerçeve koşusu (temel, kapanış) = 4 koşu / platform; 1 platform × 4 = toplam 4 koşu");
    // Kısa koşu (≤ 15 dk): onay adımı yok.
    await u.click(within(k).getByRole("button", { name: "Koşuyu başlat" }));
    expect(within(k).queryByTestId("hk-onay")).toBeNull();

    const ilerleme = within(await within(k).findByTestId("hk-ilerleme"));
    // Başlatınca odak ilerleme bölümüne geçer.
    await waitFor(() => expect(within(k).getByTestId("hk-ilerleme")).toHaveFocus());
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
    expect(ilerleme.getByTestId("hk-simdiki")).toHaveTextContent("Web · Kampanyalı ürün P-002");
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
  }, 20_000);

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
    await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok", "kampanya_tek_bedava"] });
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
    await waitFor(() => expect(within(screen.getByTestId("hk-sonuc")).getByText(/muhendis tarafından iptal edildi/)).toBeInTheDocument());
    // İptalden sonra odak kaybolmaz: sonuç başlığına geçer.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sonuç tablosu", level: 3 })).toHaveFocus());
    expect(hucre("web", "kampanya_bedava_yok")).toHaveTextContent("✓ yakalandı");
    expect(hucre("web", "kampanya_tek_bedava")).toHaveTextContent("bekliyor");
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

describe("review turu 1: süre, onay, odak, duyuru ve olaysız yenileme", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uzun seçim (> 15 dk) onay ister: onay bölümü odak alır; Vazgeç başlat düğmesine döner; 'Evet, başlat' koşuyu başlatır", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    const u = userEvent.setup();
    sar(<HataKosusuKarti />);
    const k = await kart();
    await within(k).findByRole("group", { name: "Kod hatası (5)" });
    await u.click(within(k).getByRole("checkbox", { name: "Android" }));
    await u.click(within(k).getByRole("button", { name: "Koşuyu başlat" }));
    const onay = await within(k).findByTestId("hk-onay");
    expect(onay).toHaveTextContent("Bu seçim yaklaşık 44–66 dakika sürer (22 koşu).");
    await waitFor(() => expect(onay).toHaveFocus());
    expect((await hataKosusuApi.liste()).map((x) => x.id)).toEqual(["hk-1"]);
    await u.click(within(onay).getByRole("button", { name: "Vazgeç" }));
    expect(within(k).queryByTestId("hk-onay")).toBeNull();
    await waitFor(() => expect(within(k).getByRole("button", { name: "Koşuyu başlat" })).toHaveFocus());
    await u.click(within(k).getByRole("button", { name: "Koşuyu başlat" }));
    await u.click(within(await within(k).findByTestId("hk-onay")).getByRole("button", { name: "Evet, başlat" }));
    expect(await within(k).findByTestId("hk-ilerleme")).toBeInTheDocument();
    expect((await hataKosusuApi.liste()).map((x) => x.id)).toEqual(["hk-2", "hk-1"]);
  }, 20_000);

  it("sahte saat: ilerlemede başlangıç, geçen süre ve kalan tahmini; canlı bölge yalnız adım değişince değişir", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: new Date("2026-11-12T12:04:00+03:00") });
    await oturumAc("sunucu");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok", "kampanya_tek_bedava"] });
    kuleMockIlerlet(); // running (baslama = 12:04)
    sar(<HataKosusuKarti />);
    const ilerleme = async () => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      return screen.getByTestId("hk-ilerleme");
    };
    let i = await ilerleme();
    await act(async () => void (await vi.advanceTimersByTimeAsync(10)));
    i = await ilerleme();
    expect(within(i).getByTestId("hk-sure")).toHaveTextContent(/^başladı 12:04 · geçen <1 dk · tahmini kalan ~4 dk$/);
    const duyuru = within(i).getByTestId("hk-duyuru");
    expect(duyuru).toHaveAttribute("role", "status");
    expect(duyuru).toHaveTextContent("Koşu sürüyor · Web · Temel koşu (hatasız) · adım 1 / 4");
    const ilkDuyuru = duyuru.textContent;

    // İki adım 6 dakikada bitti: kalan = ortalama adım süresi × kalan adım.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6 * 60_000);
      kuleMockIlerlet();
      kuleMockIlerlet();
      await vi.advanceTimersByTimeAsync(5000); // yoklama (olay akışı yok)
      await vi.advanceTimersByTimeAsync(400);
    });
    i = screen.getByTestId("hk-ilerleme");
    expect(within(i).getByTestId("hk-sure")).toHaveTextContent(/^başladı 12:04 · geçen 6 dk · tahmini kalan ~6 dk$/);
    expect(within(i).getByTestId("hk-duyuru")).toHaveTextContent("adım 3 / 4");
    expect(within(i).getByTestId("hk-duyuru").textContent).not.toBe(ilkDuyuru);
    // Süre canlı bölgede değil.
    expect(within(i).getByTestId("hk-duyuru")).not.toHaveTextContent(/geçen|dk/);
    expect(within(i).getByTestId("hk-sure").closest("[aria-live]")).toBeNull();
  });

  it("olay akışı yokken: yoklama süren koşunun bittiğini görünce Kule ölçüleri bir kez yenilenir", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok"] });
    const olcuDegisti = vi.fn();
    sar(<HataKosusuKarti olcuDegisti={olcuDegisti} />); // OlayProvider yok
    await act(async () => void (await vi.advanceTimersByTimeAsync(10)));
    expect(screen.getByTestId("hk-ilerleme")).toBeInTheDocument();
    await act(async () => {
      while (kuleMockIlerlet());
    });
    expect(olcuDegisti).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000); // yoklama
      await vi.advanceTimersByTimeAsync(400); // birleştirilmiş yenileme
    });
    expect(screen.queryByTestId("hk-ilerleme")).toBeNull();
    expect(olcuDegisti).toHaveBeenCalledTimes(1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(20_000)));
    expect(olcuDegisti).toHaveBeenCalledTimes(1);
  });

  it("eski çekirdek biçimi (kaynaksız kıran test, el_yazisi yok): AI/el satırı ve suite satırı çizilmez", async () => {
    const eski = hataKosusuDetayUyarla({
      id: "e1",
      durum: "done",
      platformlar: ["web"],
      hatalar: ["a"],
      ozet: { oran: 1, yakalanan: 1, kacan: 0, gecersiz: 0, platformlar: [], kacanlar: [] },
      adimlar: [
        { id: "1", platform: "web", asama: "temel", sonuc: "yesil", sira: 1 },
        { id: "2", platform: "web", asama: "hata", hata_kodu: "a", sonuc: "yakalandi", kiran_testler: ["T"], sira: 2 },
        { id: "3", platform: "web", asama: "kapanis", sonuc: "yesil", sira: 3 },
      ],
    });
    vi.spyOn(hataKosusuApi, "liste").mockResolvedValue([eski]);
    vi.spyOn(hataKosusuApi, "detay").mockResolvedValue(eski);
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    await screen.findByTestId("hk-sonuc");
    expect(screen.queryByTestId("hk-oran-ai-web")).toBeNull();
    expect(screen.queryByTestId("hk-oran-el-web")).toBeNull();
    expect(screen.queryByTestId("hk-suite")).toBeNull();
    expect(screen.getByRole("rowheader", { name: "Yakalama oranı" })).toBeInTheDocument();
    expect(screen.getByTestId("hk-oran-web")).toHaveTextContent("%100 (1/1)");
    expect(within(screen.getByTestId("hk-gecmis-e1")).getByText("%100 (1/1)")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("temelde kırmızı testler suite satırında hariç tutulduğu söylenerek listelenir", async () => {
    const d = hataKosusuDetayUyarla({
      id: "t1",
      durum: "done",
      platformlar: ["web"],
      hatalar: ["a"],
      adimlar: [
        { id: "1", platform: "web", asama: "temel", sonuc: "yesil", temelde_kirmizi: ["C3: 6 adette bedava yok"], sira: 1 },
        { id: "2", platform: "web", asama: "hata", hata_kodu: "a", sonuc: "kacti", kiran_testler: [], temelde_kirmizi: ["C3: 6 adette bedava yok"], sira: 2 },
      ],
    });
    vi.spyOn(hataKosusuApi, "liste").mockResolvedValue([d]);
    vi.spyOn(hataKosusuApi, "detay").mockResolvedValue(d);
    await oturumAc("analist");
    sar(<HataKosusuKarti />);
    expect(await screen.findByTestId("hk-suite")).toHaveTextContent(
      "Suite: temel koşuda zaten kırmızı olan testler sayılmadı (açık defect adayı olabilir) — Web: 1 test (C3: 6 adette bedava yok).",
    );
    vi.restoreAllMocks();
  });
});

describe("Kule: onaylı ama tabloyla uyuşmayan case'ler kartı", () => {
  it("liste case review'a bağlanır; boş liste 'hepsi uyumlu'; anahtar yoksa kart yok", () => {
    const { unmount } = sar(<OnayliUyumsuzKarti k={kule({ onayli_uyumsuz: [{ case_id: "case-1-7", requirement_id: "req-tpd-1", baslik: "750 TL'de uyarı" }] })} />);
    const kartEl = screen.getByRole("region", { name: "Onaylandıktan sonra tabloyla uyuşmayan case'ler" });
    expect(within(kartEl).getByRole("link", { name: "750 TL'de uyarı" })).toHaveAttribute("href", "/gereksinimler/req-tpd-1/caseler#case-case-1-7");
    unmount();
    const { unmount: u2 } = sar(<OnayliUyumsuzKarti k={kule({ onayli_uyumsuz: [] })} />);
    expect(screen.getByTestId("onayli-uyumsuz")).toHaveTextContent("Onaylı case'lerin hepsi güncel onaylı tablolarla uyumlu ya da kapsam dışı.");
    u2();
    sar(<OnayliUyumsuzKarti k={kule({})} />);
    expect(screen.queryByTestId("onayli-uyumsuz")).toBeNull();
  });
});

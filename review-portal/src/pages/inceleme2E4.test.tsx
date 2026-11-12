// 011 inceleme turu 2 — E4 portal: MİM-B1 (dil algılanamadı), QA-Y4 (Otomasyon sütunu liste sınırı),
// K-T12 (kod üretiminde dil çakışması ve toplu yanıtın case başına sonuçları).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { DEPO_OKUNAMADI } from "../api/mock/diller";
import { ayar } from "../api/mock/handlers";
import { kodDilleriUyarla, kodUretYanitiUyarla, SCRIPT_LISTE_SINIRI, scriptListesiUyarla } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { algilanamadiMesaji } from "../components/Dil";
import { DIL_CAKISMASI_CIKIS, dilCakismasiMi, uretimBildirimi } from "../components/UretimSonuclari";
import { oturumAc } from "../test/yardimci";
import { OTOMASYON_BILINMIYOR } from "./TestCaseleri";

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

beforeEach(() => {
  ayar.isAdimiMs = 0;
  vi.restoreAllMocks();
});

describe("MİM-B1: dil algılanamadı (depo okunamadı)", () => {
  it("uyarlayıcı üst düzey `neden`i taşır; yoksa null", () => {
    const d = kodDilleriUyarla(
      { algilanan: "ts", kaynak: "varsayilan", neden: "Dil algılanamadı (forge kurulamadı: X); varsayılan dil önerildi", secenekler: [{ dil: "ts", neden: DEPO_OKUNAMADI }] },
      "web",
    )!;
    expect(d.neden).toBe("Dil algılanamadı (forge kurulamadı: X); varsayılan dil önerildi");
    expect(d.secenekler[0]).toMatchObject({ kullanilabilir: true, neden: DEPO_OKUNAMADI });
    expect(kodDilleriUyarla({ algilanan: "ts", secenekler: [{ dil: "ts" }] }, "web")!.neden).toBeNull();
  });

  it("örnek arka uç `depo-okunamadi`: kaynak varsayılan, neden dolu, her seçenek açık + DEPO_OKUNAMADI", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("depo-okunamadi");
    const w = (await api.kodDilleri("web"))!;
    expect(w).toMatchObject({ algilanan: "ts", kaynak: "varsayilan" });
    expect(w.neden).toMatch(/^Dil algılanamadı/);
    expect(w.secenekler.every((s) => s.kullanilabilir && s.neden === DEPO_OKUNAMADI)).toBe(true);
  });

  it("Kod üretimi: dürüst ileti ('test bulunamadı' denmez); açık seçeneklerde neden görünür ve tanım olarak okunur", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("depo-okunamadi");
    const u = userEvent.setup();
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Dil" });
    const not = screen.getByTestId("dil-notu");
    expect(not).toHaveTextContent(algilanamadiMesaji("TypeScript"));
    expect(not).toHaveTextContent("Depo okunamadığı için dil algılanamadı; varsayılan: TypeScript. Dili elle seçebilirsiniz.");
    expect(not).not.toHaveTextContent("test bulunamadı");
    expect(not).toHaveAttribute("data-kaynak", "algilanamadi");
    const java = within(grup).getByRole("radio", { name: "Java" });
    expect(java).not.toHaveAttribute("aria-disabled");
    expect(java).toHaveAccessibleDescription(/^Playwright for Java \+ TestNG\.\s?Depo okunamadı; bu dilin test projesi doğrulanamadı \(kullanılabilirlik bilinmiyor\)$/);
    const nedenler = within(grup).getAllByTestId("secenek-neden");
    expect(nedenler).toHaveLength(4);
    for (const n of nedenler) {
      expect(n).toBeVisible();
      expect(n).toHaveAttribute("data-pasif", "hayir");
      expect(n).not.toHaveTextContent("Kullanılamıyor");
    }
    // Açık seçenek seçilebilir; üretim engellenmez.
    await u.click(java);
    expect(java).toBeChecked();
    expect(screen.getByTestId("dil-notu")).toHaveTextContent("Java elle seçildi.");
    await u.click(screen.getByRole("button", { name: "Varsayılana dön (TypeScript)" }));
    await u.click(await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ }));
    expect(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" })).toBeEnabled();
  });

  it("tek dilli platform: seçenek nedeni ve algılanamadı notu (elle seçim önerilmez)", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("depo-okunamadi");
    const u = userEvent.setup();
    uygulama("/kod");
    await screen.findByRole("group", { name: "Dil" });
    await u.click(screen.getByRole("radio", { name: /^Android/ }));
    const bilgi = await screen.findByTestId("dil-bilgi");
    expect(bilgi).toHaveTextContent(DEPO_OKUNAMADI);
    expect(bilgi).not.toHaveTextContent("Kullanılamıyor");
    // Tek seçenek: elle seçim önerisi yok; metin parçalardan kurulur (kırpma yok).
    expect(within(bilgi).getByTestId("dil-notu").textContent).toBe("Depo okunamadığı için dil algılanamadı; varsayılan: Java.");
    expect(algilanamadiMesaji("Java", false)).toBe("Depo okunamadığı için dil algılanamadı; varsayılan: Java.");
    expect(bilgi).not.toHaveTextContent("elle seçebilirsiniz");
  });
});

describe("QA-Y4: Otomasyon sütunu ve script listesi sınırı", () => {
  it("scriptListesiUyarla: düz dizi sınıra ulaşınca, zarf açık bilgiyle", () => {
    const n = (k: number) => Array.from({ length: k }, (_, i) => ({ id: `s${i}`, case_ids: [`c${i}`] }));
    expect(scriptListesiUyarla(n(SCRIPT_LISTE_SINIRI - 1)).sinira_ulasti).toBe(false);
    expect(scriptListesiUyarla(n(SCRIPT_LISTE_SINIRI))).toMatchObject({ sinira_ulasti: true });
    expect(scriptListesiUyarla(n(SCRIPT_LISTE_SINIRI)).kayitlar).toHaveLength(SCRIPT_LISTE_SINIRI);
    expect(scriptListesiUyarla({ items: n(3), daha_fazla: true }).sinira_ulasti).toBe(true);
    expect(scriptListesiUyarla({ items: n(3), toplam: 3 }).sinira_ulasti).toBe(false);
    expect(scriptListesiUyarla({ kayitlar: n(3), toplam: 10 }).sinira_ulasti).toBe(true);
    expect(scriptListesiUyarla({ items: n(50), limit: 50 }).sinira_ulasti).toBe(true);
    expect(scriptListesiUyarla({ items: n(SCRIPT_LISTE_SINIRI), has_more: false }).sinira_ulasti).toBe(false);
    expect(() => scriptListesiUyarla("x")).toThrow();
  });

  it("sınır altında: eşleşmeyen case 'Kod yok'; PR numarası ve script /kod/:id bağlantısı", async () => {
    await oturumAc("analist");
    uygulama("/caseler");
    const satir = await screen.findByRole("row", { name: /TPD-9/ });
    const pr = await within(satir).findByTestId("otomasyon-pr");
    expect(pr).toHaveAttribute("href", "/kod/scr-1#pr");
    expect(pr).toHaveAccessibleName(/PR #11 \(açık\) · script/);
    // PR'sız (doğrulanmamış) script: "Script" bağlantısı.
    const py = screen.getByRole("row", { name: /TPD-12/ });
    expect(within(py).getByTestId("otomasyon-script-baglanti")).toHaveAttribute("href", "/kod/scr-py");
    expect(screen.getAllByText("Kod yok").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("otomasyon-bilinmiyor")).toBeNull();
    expect(screen.queryByTestId("otomasyon-sinir-notu")).toBeNull();
  });

  it("sınıra ulaşıldıysa eşleşmeyen case 'Bilinmiyor' (title + ekran okuyucu açıklaması), 'Kod yok' değil", async () => {
    await oturumAc("analist");
    ayar.senaryolar.add("uzun-gecmis");
    uygulama("/caseler");
    const satir = await screen.findByRole("row", { name: /TPD-9/ });
    const b = await within(satir).findByTestId("otomasyon-bilinmiyor");
    expect(b).toHaveTextContent(`Bilinmiyor: ${OTOMASYON_BILINMIYOR}`);
    expect(b).toHaveAttribute("title", OTOMASYON_BILINMIYOR);
    // D-3 (tur 3): Kod üretimi de aynı sınırlı listeyi kullanır — oraya yönlendiren döngüsel öneri yok.
    expect(OTOMASYON_BILINMIYOR).toBe("Kod listesi en yeni 200 kayıtla sınırlı; bu case'in listede görünmeyen daha eski bir kodu olabilir.");
    expect(screen.queryByText("Kod yok")).toBeNull();
    expect(screen.getByTestId("otomasyon-sinir-notu")).toHaveTextContent("en yeni 200 script kaydından");
  });
});

describe("K-T12: kod üretiminde dil çakışması", () => {
  it("yanıt uyarlayıcı: sonuclar case başına; alan yoksa boş; bildirim sayıları", () => {
    const y = kodUretYanitiUyarla({
      job_id: "j",
      durum: "started",
      mesaj: "1 case için kod üretimi başlatıldı",
      sonuclar: [
        { case_id: "a", durum: "basladi", script_id: "s1" },
        { case_id: "b", durum: "cakisma", neden: "Bu case'in web testi Java ile merge edildi" },
        { case_id: "c", durum: "pr_acik", script_id: "s2", neden: "PR var" },
        { durum: "cakisma" },
      ],
    });
    expect(y.sonuclar.map((s) => [s.case_id, s.durum])).toEqual([
      ["a", "basladi"],
      ["b", "cakisma"],
      ["c", "pr_acik"],
    ]);
    expect(uretimBildirimi(y, "x")).toBe("1 case için kod üretimi başlatıldı. 2 case için üretim başlamadı (1 dil çakışması); ayrıntı listede.");
    expect(kodUretYanitiUyarla({ job_id: "j", durum: "started" }).sonuclar).toEqual([]);
    expect(uretimBildirimi(kodUretYanitiUyarla({ durum: "started" }), "Kod üretimi başladı.")).toBe("Kod üretimi başladı.");
    // MİM-D1/D2: `cakisma_sayisi` varsa core iletisi çakışmayı söyler; ileti hangi kelimeyle olursa olsun yinelenmez.
    const coreMesaji = "1 case için kod üretimi başlatıldı. 1 case başka dilde merge edilmiş testi olduğu için üretilmedi (mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin).";
    const yapisal = kodUretYanitiUyarla({ durum: "started", mesaj: coreMesaji, cakisma_sayisi: 1, sonuclar: [
      { case_id: "a", durum: "basladi" }, { case_id: "b", durum: "cakisma", neden: "x" },
    ] });
    expect(yapisal.cakisma_sayisi).toBe(1);
    expect(uretimBildirimi(yapisal, "x")).toBe(coreMesaji);
    const karisik = kodUretYanitiUyarla({ ...yapisal, sonuclar: [...yapisal.sonuclar, { case_id: "c", durum: "pr_acik" }] });
    expect(uretimBildirimi(karisik, "x")).toBe(`${coreMesaji} Ayrıca 1 case için üretim başlamadı; ayrıntı listede.`);
    // core mesaj vermeyip yalnız sayıyı verirse sayı yapısal alandan.
    expect(uretimBildirimi({ ...yapisal, mesaj: undefined, sonuclar: [] }, "Başladı")).toBe("Başladı. 1 case için üretim başlamadı (1 dil çakışması); ayrıntı listede.");
    // Geçersiz sayı alınmaz.
    expect(kodUretYanitiUyarla({ durum: "started", cakisma_sayisi: "2" }).cakisma_sayisi).toBeUndefined();
    expect(dilCakismasiMi(new ApiError(409, "x", { kod: "dil_cakismasi" }))).toBe(true);
    expect(dilCakismasiMi(new ApiError(409, "Yalnızca onaylı case'ler için kod üretilebilir."))).toBe(false);
  });

  it("örnek arka uç `uzun-gecmis`: tümü çakışırsa 409 dil_cakismasi; karışıkta case başına sonuç", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("uzun-gecmis");
    await expect(api.kodUret(["case-1-9"], "web")).rejects.toMatchObject({ status: 409, kod: "dil_cakismasi" });
    // Aynı dilde (Java) istek çakışmaz: merge edilmiş değil, liste dışı Java kaydı aynı dil.
    const y = await api.kodUret(["case-1-9", "case-1-2", "case-1-4"], "web");
    expect(y.sonuclar.map((s) => [s.case_id, s.durum])).toEqual([
      ["case-1-9", "cakisma"],
      ["case-1-2", "merge_edildi"],
      ["case-1-4", "basladi"],
    ]);
    expect(y.sonuclar[0].neden).toBe("Bu case'in web testi Java ile merge edildi; dil değiştirmek için önce mevcut testi kaldırın: mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin");
    // MİM-D1/D2: core'un birebir iletisi ve yapısal `cakisma_sayisi`.
    expect(y.cakisma_sayisi).toBe(1);
    expect(y.mesaj).toBe(
      "1 case için kod üretimi başlatıldı. 1 case başka dilde merge edilmiş testi olduğu için üretilmedi (mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin).",
    );
    // Doğrulanmamış dil tam hat testine dokunmaz: çakışma yok.
    const py = await api.kodUret(["case-1-9"], "web", "python");
    expect(py.sonuclar[0].durum).toBe("basladi");
  });

  it("Kod üretimi: 409 dil çakışması açık iletiyle ve çıkış yoluyla", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("uzun-gecmis");
    const u = userEvent.setup();
    uygulama("/kod");
    await u.click(await screen.findByRole("checkbox", { name: /TPD-13/ }));
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" }));
    const kutu = await screen.findByTestId("dil-cakismasi");
    expect(within(kutu).getByRole("alert")).toHaveTextContent("Kod üretilemedi: dil çakışması");
    expect(kutu).toHaveTextContent("Bu case'in web testi Java ile merge edildi; dil değiştirmek için önce mevcut testi kaldırın: mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin");
    // core iletisi çıkış yolunu söylüyor: portal yinelemez.
    expect(kutu).not.toHaveTextContent("Çıkış yolu");
    expect(kutu.textContent!.match(/silen bir PR/gi)).toHaveLength(1);
  });

  it("core iletisi çıkış yolunu söylüyorsa yinelenmez", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "kodUret").mockRejectedValue(
      new ApiError(409, "Bu case'in web testi Java ile merge edildi; mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin.", { kod: "dil_cakismasi" }),
    );
    const u = userEvent.setup();
    uygulama("/kod");
    await u.click(await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ }));
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" }));
    const kutu = await screen.findByTestId("dil-cakismasi");
    expect(kutu).not.toHaveTextContent("Çıkış yolu");
    expect(kutu.textContent!.match(/silen bir PR/gi)).toHaveLength(1);
  });

  it("Kod üretimi: karışık toplu yanıtta başlamayan case'ler ve nedenleri liste altında; bildirimde sayı", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("uzun-gecmis");
    const u = userEvent.setup();
    uygulama("/kod");
    for (const k of [/TPD-13/, /TPD-10/, /minimum tutarın altında uyarı/]) await u.click(await screen.findByRole("checkbox", { name: k }));
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (3)" }));
    const liste = await screen.findByTestId("uretim-atlananlar");
    expect(liste).toHaveTextContent("2 case için üretim başlamadı");
    const ogeler = within(liste).getAllByRole("listitem");
    expect(ogeler).toHaveLength(2);
    const cakisan = ogeler.find((o) => o.dataset.durum === "cakisma")!;
    const merged = ogeler.find((o) => o.dataset.durum === "merge_edildi")!;
    expect(cakisan).toHaveTextContent(/TPD-13 · .+ — Dil çakışması: Bu case'in web testi Java ile merge edildi/);
    expect(merged).toHaveTextContent(/TPD-10 · .+ — Zaten merge edildi: bu onaylı içerik için bu platformda PR zaten var/);
    expect(liste).toHaveTextContent(`Dil çakışmasından çıkış: ${DIL_CAKISMASI_CIKIS}`);
    // MİM-D1: çakışma core iletisinde bir kez; portal yalnız çakışma dışında başlamayanı ekler.
    const bildirim = await screen.findByText(/^1 case için kod üretimi başlatıldı\. 1 case başka dilde merge edilmiş testi olduğu için üretilmedi/);
    expect(bildirim).toHaveTextContent(
      "1 case için kod üretimi başlatıldı. 1 case başka dilde merge edilmiş testi olduğu için üretilmedi (mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin). Ayrıca 1 case için üretim başlamadı; ayrıntı listede.",
    );
    expect(bildirim.textContent!.match(/üretilmedi|çakışma/gi)).toHaveLength(1);
    await u.click(within(liste).getByRole("button", { name: "Listeyi kapat" }));
    await waitFor(() => expect(screen.queryByTestId("uretim-atlananlar")).toBeNull());
  });
});

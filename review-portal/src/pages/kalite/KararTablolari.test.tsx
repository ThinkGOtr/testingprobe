// 012 Ş7 — "Karar tabloları" sayfası: liste ve çipler, düzenleyici (ekle/kaldır/sırala, 422 alan
// mesajları, 409 çakışma), rol kapıları, her durum geçişi, "örnekle dene", AI taslağı, ilişkiler ve
// "Ek case türet".
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { api } from "../../api/client";
import { bekleyenMockIs, mockVerisi } from "../../api/mock/handlers";
import { kaliteVerisi } from "../../api/mock/kalite";
import { MIN_SIPARIS_TABLOSU, YEDI_ARTIS_ILISKISI } from "../../api/mock/kaliteVerisi";
import { mockOlayYayinla } from "../../api/mock/olaylar";
import { OturumProvider } from "../../auth";
import { BildirimProvider } from "../../components/Bildirim";
import { t2Duzelt, t2Taslak } from "../../test/kaliteYardimci";
import { oturumAc } from "../../test/yardimci";

const REQ = "req-tpd-1";
const YOL = `/gereksinimler/${REQ}/karar-tablolari`;

function uygulama(yol = YOL) {
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
const kart = async (ad: RegExp) => screen.findByRole("region", { name: ad });
const KAMPANYA = /T1 · Kampanya/;
const MIN = /T2 · Minimum sipariş/;
const kalite = () => kaliteVerisi(mockVerisi());

describe("liste", () => {
  it("durum çipleri, AI taslağı işareti, AC atıfları, onay bilgisi; gereksinim ve case review bağlantıları", async () => {
    await oturumAc("analist");
    uygulama();
    expect(await screen.findByRole("heading", { level: 1, name: "Karar tabloları" })).toBeInTheDocument();
    const t1 = await kart(KAMPANYA);
    expect(within(t1).getByText("Onaylı")).toBeInTheDocument();
    // Onyüz 15: PO onayından geçmiş kayıtta köken nötr "AI kökenli" (mor "AI taslağı" yalnız taslakta).
    expect(within(t1).getByText("AI kökenli")).toBeInTheDocument();
    expect(within(t1).queryByText("AI taslağı")).toBeNull();
    expect(within(t1).getByText("AC2")).toBeInTheDocument();
    expect(within(t1).getByTestId("kt-onay")).toHaveTextContent("PO onayı:");
    expect(t1).toHaveClass("insan-kapisi", "kapi-gecti");
    const t2 = await kart(MIN);
    // u2 N2: T2 AI taslağı PO onayı bekliyor (AI kökenli, amber şerit).
    expect(within(t2).getByText("PO onayı bekliyor")).toBeInTheDocument();
    expect(within(t2).getByText("AI kökenli")).toBeInTheDocument();
    expect(t2).toHaveClass("kt-ai", "kapi-bekliyor");
    expect(t2).not.toHaveClass("kapi-gecti");
    // g2 O2: dürüst bağımsızlık notu.
    expect(screen.getByTestId("kt-bagimsizlik")).toHaveTextContent("Bağımsızlık insan onayına dayanır: tablo AI taslağıdır, PO onayıyla bağımsızlaşır.");
    // Satırlar tablosu: her çıktı için bir sütun.
    const satirlar = within(t1).getByRole("region", { name: /satırlar/ });
    expect(within(satirlar).getByRole("columnheader", { name: "indirim" })).toBeInTheDocument();
    expect(within(satirlar).getByText("adet >= 7")).toBeInTheDocument();
    // İlişkiler bölümü.
    const iliskiler = screen.getByTestId("iliskiler");
    expect(within(iliskiler).getAllByTestId("iliski-kart")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Case review" })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler`);
    expect(screen.getByRole("link", { name: /← TPD-1/ })).toHaveAttribute("href", `/gereksinimler/${REQ}`);
  });

  it("u2 N8, N13, N18, N19: satır anlamı iş dilinde, hücrelerde Türkçe; PO ızgarada 750'deki AI sınır hatasını story cümlesiyle görür", async () => {
    await oturumAc("po");
    uygulama();
    const t1 = await kart(KAMPANYA);
    const anlam = within(t1).getByTestId("kt-anlam");
    expect(anlam).toHaveTextContent(
      "Eğer adet 7 ya da daha fazla → bedava adet = adet ÷ 7 (tam kısım); indirim = bedava adetlerin tutarı, kuruşa yuvarlanır; toplam = indirim düşülmüş satır tutarı, kuruşa yuvarlanır",
    );
    expect(anlam).toHaveTextContent("Diğer tüm durumlarda → bedava adet 0; indirim 0; toplam = ara toplam");
    expect(within(t1).queryByTestId("kt-analist-degistirdi")).toBeNull();
    // N13: okuma görünümünde `dogru` → "doğru".
    expect(within(within(t1).getByRole("region", { name: /satırlar/ })).getByText("doğru")).toBeInTheDocument();
    const t2 = await kart(MIN);
    // Analist değiştirmedi: AI taslağı olduğu gibi PO'da (işaret yok).
    expect(within(t2).queryByTestId("kt-analist-degistirdi")).toBeNull();
    const t2Anlam = within(t2).getByTestId("kt-anlam");
    expect(t2Anlam).toHaveTextContent("Eğer sepet tutarı 750 ya da daha az → uyarı görünür");
    expect(t2Anlam).toHaveTextContent("Eğer kampanyalı sepet ise → uyarı görünmez");
    // Sınır örnekleri PO onayı beklerken açık gelir.
    const ornek = within(t2).getByTestId("kt-ornek");
    const izgara = await within(ornek).findByRole("region", { name: /sınır örnekleri/ });
    expect(within(izgara).getByRole("columnheader", { name: "Story ne diyor" })).toBeInTheDocument();
    const satirlar = within(izgara).getAllByRole("row");
    const esik = satirlar.filter((r) => r.getAttribute("data-esik") === "true");
    // N19: eşik satırı (750,00) işaretli ve story cümlesi yanında; AI'ın `<=` hatası "uyarı görünür" der.
    const satir750 = esik.find((r) => /^yanlış750/.test(r.textContent ?? ""))!;
    expect(satir750).toHaveTextContent("eşik");
    expect(satir750).toHaveTextContent("R2");
    expect(satir750).toHaveTextContent("uyarı görünür");
    expect(satir750).toHaveTextContent("AC3:");
    expect(satir750).toHaveTextContent(/altında/);
    // Eşik dışı satırda story sütunu boş.
    expect(satirlar.find((r) => /^yanlış749,99/.test(r.textContent ?? ""))).toHaveTextContent(/—$/);
  });

  it("u2 N2, N9: analist `< 750` düzeltmesi 'analist değiştirdi' + AI'ın özgün koşulu; PO geçmişte değişiklik isteğini görür", async () => {
    await t2Duzelt();
    await oturumAc("po");
    uygulama();
    const t2 = await kart(MIN);
    const degisen = within(t2).getAllByTestId("kt-analist-degistirdi");
    expect(degisen).toHaveLength(1);
    expect(degisen[0].closest("tr")).toHaveTextContent("R2");
    expect(within(t2).getByTestId("kt-ai-ozgun")).toHaveTextContent("AI taslağında: sepet_tutari <= 750");
    expect(within(t2).getByTestId("kt-anlam")).toHaveTextContent("Eğer sepet tutarı 750'den az → uyarı görünür");
    const gecmis = within(t2).getByTestId("kt-gecmis");
    await userEvent.click(within(gecmis).getByText(/^Geçmiş/));
    expect(gecmis).toHaveTextContent("Değişiklik istedi — “AC3 'altında' diyor; tam 750,00 TL'de uyarı olmamalı.”");
    expect(gecmis).toHaveTextContent("İçeriği düzenledi");
    // Düzeltilmiş tabloda 750,00 TL'de uyarı yok.
    const izgara = await within(within(t2).getByTestId("kt-ornek")).findByRole("region", { name: /sınır örnekleri/ });
    expect(within(izgara).getAllByRole("row").find((r) => /^yanlış750 eşik/.test(r.textContent ?? ""))).toHaveTextContent("uyarı görünmez");
  });

  it("onyüz 12: gereksinim okunamazsa hata kutusu ve analist eylemleri nedenle kapalı", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("analist");
    vi.spyOn(api, "gereksinim").mockRejectedValue(new Error("ağ hatası"));
    uygulama();
    expect(await screen.findByTestId("gereksinim-hata")).toHaveTextContent("Gereksinim okunamadı");
    await waitFor(() => expect(screen.getByRole("button", { name: "AI taslağı üret" })).toBeDisabled());
    const t2 = await kart(MIN);
    expect(within(t2).getByRole("button", { name: "Düzenle" })).toBeDisabled();
  });

  it("gereksinim onaydan sonra değişince onaylı tablo 'Bayat' ve uyarı gösterir", async () => {
    await oturumAc("analist");
    kalite();
    mockVerisi().gereksinimler.find((x) => x.id === REQ)!.aciklama += " (değişti)";
    uygulama();
    const t1 = await kart(KAMPANYA);
    expect(within(t1).getByText("Bayat")).toBeInTheDocument();
    expect(within(t1).getByText("Tablo bayat")).toBeInTheDocument();
    expect(t1).not.toHaveClass("kapi-gecti");
  });

  it("gereksinim detayından sayfaya bağlantı (mevcut bağlantılar yerinde)", async () => {
    await oturumAc("analist");
    uygulama(`/gereksinimler/${REQ}`);
    expect(await screen.findByRole("link", { name: "Karar tabloları" })).toHaveAttribute("href", YOL);
  });
});

describe("düzenleyici", () => {
  async function ac() {
    await t2Taslak();
    uygulama();
    const t2 = await kart(MIN);
    await userEvent.click(within(t2).getByRole("button", { name: "Düzenle" }));
    const form = within(t2).getByTestId("kt-duzenleyici");
    await waitFor(() => expect(within(form).getByLabelText("Tablo adı")).toHaveFocus());
    return { t2, form };
  }

  it("satır ekle / kaldır / sırala; kayıt yeni içeriği ve görülen hash'i gönderir", async () => {
    const { t2, form } = await ac();
    expect(within(form).getAllByTestId("kt-satir")).toHaveLength(3);
    await userEvent.click(within(form).getByRole("button", { name: "Satır ekle" }));
    const satirlar = within(form).getAllByTestId("kt-satir");
    expect(satirlar).toHaveLength(4);
    const yeni = satirlar[3];
    expect(within(yeni).getByText("R4")).toBeInTheDocument();
    await waitFor(() => expect(within(yeni).getByLabelText("Koşul")).toHaveFocus());
    await userEvent.type(within(yeni).getByLabelText("Koşul"), "sepet_tutari < 0");
    await userEvent.type(within(yeni).getByLabelText(/minimum_uyarisi ifadesi/), "dogru");
    // R4'ü en üste taşı, sonra R1'i kaldır.
    await userEvent.click(within(yeni).getByRole("button", { name: "Satır R4 yukarı taşı" }));
    await userEvent.click(within(form).getByRole("button", { name: "Satır R4 yukarı taşı" }));
    await userEvent.click(within(form).getByRole("button", { name: "Satır R4 yukarı taşı" }));
    expect(within(form).getAllByTestId("kt-satir")[0]).toHaveAccessibleName("Satır R4");
    expect(within(form).getAllByTestId("kt-satir")[0].querySelector("button[aria-label$='yukarı taşı']")).toBeNull();
    await userEvent.click(within(form).getByRole("button", { name: "Satır R1 kaldır" }));
    expect(within(form).getAllByTestId("kt-satir")).toHaveLength(3);
    await waitFor(() => expect(within(form).getByRole("button", { name: "Satır ekle" })).toHaveFocus());
    // Sınır düzeltmesi (golden'daki gibi): `sepet_tutari <= 750` → `sepet_tutari < 750`.
    const r2 = within(form).getByRole("group", { name: "Satır R2" });
    await userEvent.clear(within(r2).getByLabelText("Koşul"));
    await userEvent.type(within(r2).getByLabelText("Koşul"), "sepet_tutari < 750");
    const kaydet = vi.spyOn(api, "kararTablosuKaydet");
    const onceki = kalite().tablolar.find((x) => x.id === "kt-2")!.icerik_hash;
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(within(t2).queryByTestId("kt-duzenleyici")).toBeNull());
    expect(kaydet).toHaveBeenCalledWith("kt-2", expect.objectContaining({ icerik_hash: onceki }));
    const t = kalite().tablolar.find((x) => x.id === "kt-2")!;
    expect(t.icerik.satirlar.map((s) => [s.id, s.kosul])).toEqual([
      ["R4", "sepet_tutari < 0"],
      ["R2", "sepet_tutari < 750"],
      ["R3", "dogru"],
    ]);
    expect(t.icerik_hash).not.toBe(onceki);
    expect(within(t2).getByText("sepet_tutari < 750")).toBeInTheDocument();
    await waitFor(() => expect(within(t2).getByRole("button", { name: "Düzenle" })).toHaveFocus());
  });

  it("girdi / çıktı ekle-kaldır; çıktı adı değişince satır ifadeleri yeni ada bağlı kalır", async () => {
    const { form } = await ac();
    await userEvent.click(within(form).getByRole("button", { name: "Girdi ekle" }));
    expect(within(form).getAllByTestId("kt-girdiler")).toHaveLength(3);
    await waitFor(() => expect(within(within(form).getAllByTestId("kt-girdiler")[2]).getByLabelText("Ad")).toHaveFocus());
    await userEvent.click(within(form).getByRole("button", { name: "Girdi 3 kaldır" }));
    expect(within(form).getAllByTestId("kt-girdiler")).toHaveLength(2);
    // Kaldırınca odak "Girdi ekle"ye geçer (sonraki yazım oraya kaçmasın diye beklenir).
    await waitFor(() => expect(within(form).getByRole("button", { name: "Girdi ekle" })).toHaveFocus());
    const cikti = within(form).getAllByTestId("kt-ciktilar")[0];
    await userEvent.clear(within(cikti).getByLabelText("Ad"));
    await userEvent.type(within(cikti).getByLabelText("Ad"), "uyari_var");
    expect(within(form).getAllByLabelText(/uyari_var ifadesi/)).toHaveLength(3);
    // Mantıksal çıktıda tolerans kullanılmaz.
    expect(within(cikti).getByLabelText("Tolerans")).toHaveAttribute("readonly");
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(kalite().tablolar.find((x) => x.id === "kt-2")!.icerik.ciktilar[0].ad).toBe("uyari_var"));
    expect(kalite().tablolar.find((x) => x.id === "kt-2")!.icerik.satirlar[0].cikti).toEqual({ uyari_var: "yanlis" });
  });

  it("422 karar_tablosu_gecersiz: mesajlar ilgili alanın yanında, alan aria-invalid; düzenleme açık kalır", async () => {
    const { t2, form } = await ac();
    const r1 = within(form).getByRole("group", { name: "Satır R1" });
    await userEvent.clear(within(r1).getByLabelText("Koşul"));
    await userEvent.type(within(r1).getByLabelText("Koşul"), "kampanyali_sepet ve bilinmeyen");
    await userEvent.clear(within(r1).getByLabelText(/minimum_uyarisi ifadesi/));
    const girdi = within(form).getAllByTestId("kt-girdiler")[1];
    await userEvent.clear(within(girdi).getByLabelText("Ad"));
    await userEvent.type(within(girdi).getByLabelText("Ad"), "1tutar");
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    expect(await within(form).findByTestId("kt-kayit-hatasi")).toHaveTextContent("doğrulama hatası");
    const kosul = within(r1).getByLabelText("Koşul");
    expect(kosul).toHaveAttribute("aria-invalid", "true");
    const bagli = kosul.getAttribute("aria-describedby")!.split(" ").map((x) => document.getElementById(x)?.textContent ?? "");
    expect(bagli.some((m) => /bilinmeyen/.test(m))).toBe(true);
    // Onyüz 4: koşul alanı ifade dili özetine de bağlı.
    expect(bagli.some((m) => /İfade dili/.test(m))).toBe(true);
    expect(within(r1).getByLabelText(/minimum_uyarisi ifadesi/)).toHaveAttribute("aria-invalid", "true");
    expect(within(girdi).getByLabelText("Ad")).toHaveAttribute("aria-invalid", "true");
    expect(within(t2).getByTestId("kt-duzenleyici")).toBeInTheDocument();
    expect(kalite().tablolar.find((x) => x.id === "kt-2")!.icerik.girdiler[1].ad).toBe("sepet_tutari");
    // Yapı değişince eski yol mesajları temizlenir (yanlış alana düşmez).
    await userEvent.click(within(form).getByRole("button", { name: "Satır ekle" }));
    expect(within(form).queryByTestId("kt-kayit-hatasi")).toBeNull();
  });

  it("409: içerik başka yerde değişti; düzenleme ezilmez, 'Güncel içeriği yükle' sunucudaki içeriği getirir", async () => {
    const { t2, form } = await ac();
    await userEvent.type(within(form).getByLabelText("Tablo adı"), " (benim)");
    // Başka bir analist aynı tabloyu kaydetti.
    const t = kalite().tablolar.find((x) => x.id === "kt-2")!;
    await api.kararTablosuKaydet(t.id, { icerik: { ...t.icerik, ad: "Minimum sipariş (başkası)" }, icerik_hash: t.icerik_hash });
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    expect(await within(form).findByText(/değişti|değişmiş/)).toBeInTheDocument();
    expect(kalite().tablolar.find((x) => x.id === "kt-2")!.icerik.ad).toBe("Minimum sipariş (başkası)");
    expect(within(form).getByLabelText("Tablo adı")).toHaveValue(`${MIN_SIPARIS_TABLOSU.ad} (benim)`);
    await userEvent.click(within(form).getByRole("button", { name: "Güncel içeriği yükle" }));
    await waitFor(() => expect(within(form).getByLabelText("Tablo adı")).toHaveValue("Minimum sipariş (başkası)"));
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(within(t2).queryByTestId("kt-duzenleyici")).toBeNull());
  });

  it("Vazgeç değişikliği atar, odak 'Düzenle'ye döner; düzenleme açıkken geçişler nedenle kapalı", async () => {
    const { t2, form } = await ac();
    expect(within(t2).getByRole("button", { name: "PO onayına gönder" })).toBeDisabled();
    expect(within(t2).getByText("Önce düzenlemeyi kaydedin ya da vazgeçin.")).toHaveClass("dugme-neden");
    await userEvent.type(within(form).getByLabelText("Tablo adı"), "!!!");
    await userEvent.click(within(form).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(within(t2).getByRole("button", { name: "Düzenle" })).toHaveFocus());
    expect(kalite().tablolar.find((x) => x.id === "kt-2")!.icerik.ad).toBe(MIN_SIPARIS_TABLOSU.ad);
  });

  it("boş tablo ekle: elle tablo düzenleyicide açılır; eksik içerik PO'ya gönderilemez (mesajlar listelenir)", async () => {
    await oturumAc("analist");
    uygulama();
    await kart(KAMPANYA);
    await userEvent.click(screen.getByRole("button", { name: "Boş tablo ekle" }));
    const t3 = await kart(/T3 · Yeni karar tablosu/);
    expect(within(t3).queryByText("AI taslağı")).toBeNull();
    const form = within(t3).getByTestId("kt-duzenleyici");
    await userEvent.click(within(form).getByRole("button", { name: "Vazgeç" }));
    await userEvent.click(within(t3).getByRole("button", { name: "PO onayına gönder" }));
    const h = await within(t3).findByTestId("gecis-hatalari");
    expect(h).toHaveTextContent("girdiler: en az bir girdi gerekir");
    expect(h).toHaveTextContent("ac_refs: en az bir kabul kriteri atfı gerekir");
  });
});

describe("rol kapıları ve durum geçişleri", () => {
  it("PO: düzenleme ve analist geçişleri pasif + rol nedeni; analist: PO kararları pasif", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("po");
    uygulama();
    const t2 = await kart(MIN);
    expect(within(t2).getByRole("button", { name: "Düzenle" })).toBeDisabled();
    expect(within(t2).getByRole("button", { name: "PO onayına gönder" })).toBeDisabled();
    expect(within(t2).getAllByText(/Bu işlem için gereken rol: Analist/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "AI taslağı üret" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Boş tablo ekle" })).toBeDisabled();
  });

  it("gönder → geri çek → gönder → değişiklik iste (gerekçe) → gönder → PO onayı → yeniden aç", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("analist");
    const { unmount } = uygulama();
    let t2 = await kart(MIN);
    await userEvent.click(within(t2).getByRole("button", { name: "PO onayına gönder" }));
    expect(await within(t2).findByText("PO onayı bekliyor")).toBeInTheDocument();
    expect(t2).toHaveClass("kapi-bekliyor");
    expect(within(t2).getByRole("button", { name: "PO olarak onayla" })).toBeDisabled();
    expect(within(t2).queryByRole("button", { name: "Düzenle" })).toBeNull();
    await userEvent.click(within(t2).getByRole("button", { name: "Geri çek" }));
    expect(await within(t2).findByText("Taslak")).toBeInTheDocument();
    await userEvent.click(within(t2).getByRole("button", { name: "PO onayına gönder" }));
    await within(t2).findByText("PO onayı bekliyor");
    unmount();

    await oturumAc("po");
    uygulama();
    t2 = await kart(MIN);
    expect(within(t2).getByRole("button", { name: "Geri çek" })).toBeDisabled();
    await userEvent.click(within(t2).getByRole("button", { name: "Değişiklik iste" }));
    const alan = within(t2).getByLabelText("Değişiklik gerekçesi");
    await waitFor(() => expect(alan).toHaveFocus());
    await userEvent.click(within(t2).getByRole("button", { name: "Değişiklik isteğini gönder" }));
    expect(within(t2).getByText("Değişiklik isteği için gerekçe yazın.")).toBeInTheDocument();
    await userEvent.type(alan, "Sınır 750 dahil olmalı (AC3).");
    await userEvent.click(within(t2).getByRole("button", { name: "Değişiklik isteğini gönder" }));
    expect(await within(t2).findByText("PO değişiklik istedi")).toBeInTheDocument();
    // Gerekçe uyarıda ve (kapalı) geçmişte görünür.
    expect(within(t2).getAllByText(/Sınır 750 dahil olmalı/).length).toBeGreaterThan(0);

    await oturumAc("analist");
    await api.kararTablosuGecis("kt-2", "submit", { icerik_hash: kalite().tablolar.find((x) => x.id === "kt-2")!.icerik_hash });
    await oturumAc("po");
    const onayla = vi.spyOn(api, "kararTablosuGecis");
    await within(t2).findByText("PO onayı bekliyor", undefined, { timeout: 2000 });
    await userEvent.click(within(t2).getByRole("button", { name: "PO olarak onayla" }));
    expect(await within(t2).findByText("Onaylı")).toBeInTheDocument();
    expect(onayla).toHaveBeenCalledWith("kt-2", "approve", { icerik_hash: kalite().tablolar.find((x) => x.id === "kt-2")!.icerik_hash });
    expect(t2).toHaveClass("kapi-gecti");
    await waitFor(() => expect(bekleyenMockIs()).toBe(0));

    cleanup();
    await oturumAc("analist");
    uygulama();
    t2 = await kart(MIN);
    await userEvent.click(within(t2).getByRole("button", { name: "Yeniden aç" }));
    expect(await within(t2).findByText("Taslak")).toBeInTheDocument();
    expect(kalite().tablolar.find((x) => x.id === "kt-2")).toMatchObject({ durum: "draft", onaylanan_hash: null });
  });

  it("onyüz 6, 7: PO incelerken içerik değişirse uyarı ve onay kapalı; gözden geçirince onay notuyla onaylar, duyuru satırı odak alır", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("analist");
    const t = () => kalite().tablolar.find((x) => x.id === "kt-2")!;
    await api.kararTablosuGecis("kt-2", "submit", { icerik_hash: t().icerik_hash });
    await oturumAc("po");
    uygulama();
    const t2 = await kart(MIN);
    expect(within(t2).getByRole("button", { name: "PO olarak onayla" })).toBeEnabled();
    // Analist arka planda geri çekip R2'yi düzeltti ve yeniden gönderdi.
    await oturumAc("analist");
    await api.kararTablosuGecis("kt-2", "withdraw");
    const yeni = { ...t().icerik, satirlar: t().icerik.satirlar.map((x) => (x.id === "R2" ? { ...x, kosul: "sepet_tutari < 750" } : x)) };
    await api.kararTablosuKaydet("kt-2", { icerik: yeni, icerik_hash: t().icerik_hash });
    await api.kararTablosuGecis("kt-2", "submit", { icerik_hash: t().icerik_hash });
    await oturumAc("po");
    mockOlayYayinla({ type: "karar_tablosu.updated", id: "kt-2", data: { id: "kt-2", requirement_id: REQ, durum: "pending_po", eylem: "duzenle" } });
    expect(await within(t2).findByTestId("kt-icerik-degisti", undefined, { timeout: 3000 })).toHaveTextContent("İçerik siz bakarken değişti");
    expect(within(t2).getByRole("button", { name: "PO olarak onayla" })).toBeDisabled();
    await userEvent.click(within(t2).getByRole("button", { name: "Güncel içeriği gözden geçirdim" }));
    expect(within(t2).queryByTestId("kt-icerik-degisti")).toBeNull();
    const onayla = vi.spyOn(api, "kararTablosuGecis");
    await userEvent.type(within(t2).getByLabelText("PO onay notu (isteğe bağlı)"), "Örneklerle kontrol edildi");
    await userEvent.click(within(t2).getByRole("button", { name: "PO olarak onayla" }));
    expect(await within(t2).findByText("Onaylı")).toBeInTheDocument();
    expect(onayla).toHaveBeenCalledWith("kt-2", "approve", { icerik_hash: t().icerik_hash, gerekce: "Örneklerle kontrol edildi" });
    const duyuru = within(t2).getByTestId("kt-duyuru");
    expect(duyuru).toHaveTextContent("PO olarak onaylandı.");
    expect(duyuru).toHaveAttribute("role", "status");
    await waitFor(() => expect(duyuru).toHaveFocus());
  });

  it("görülen hash eskiyse geçiş 409 verir ve liste yenilenir", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("analist");
    uygulama();
    const t2 = await kart(MIN);
    const t = kalite().tablolar.find((x) => x.id === "kt-2")!;
    t.icerik = { ...t.icerik, ad: "Minimum sipariş tutarı" , aciklama: "değişti" };
    t.icerik_hash = "sha256:baska";
    await userEvent.click(within(t2).getByRole("button", { name: "PO onayına gönder" }));
    expect((await within(t2).findAllByText(/değişti|değişmiş/)).length).toBeGreaterThan(0);
    // Liste yenilendi: güncel açıklama ekranda.
    expect(await within(t2).findByText("değişti")).toBeInTheDocument();
    expect(t.durum).toBe("draft");
  });
});

describe("örnekle dene", () => {
  async function dene(baslik: RegExp, girdiler: Record<string, string>) {
    const t = await kart(baslik);
    const d = within(t).getByTestId("kt-dene");
    await userEvent.click(within(d).getByText("Örnekle dene"));
    for (const [ad, deger] of Object.entries(girdiler)) {
      const alan = within(d).getByLabelText(new RegExp(`^${ad}`));
      if (alan.tagName === "SELECT") await userEvent.selectOptions(alan, deger);
      else await userEvent.type(alan, deger);
    }
    await userEvent.click(within(d).getByRole("button", { name: "Dene" }));
    return d;
  }

  it("eşleşen satır ve çıktılar", async () => {
    await oturumAc("po");
    uygulama();
    const d = await dene(KAMPANYA, { adet: "14", ara_toplam: "350,00" });
    const s = await within(d).findByTestId("kt-dene-sonuc");
    expect(s).toHaveTextContent("Eşleşen satır: R1");
    expect(within(s).getByRole("row", { name: /bedava_adet 2/ })).toBeInTheDocument();
    expect(within(s).getByRole("row", { name: /indirim 50 TL/ })).toBeInTheDocument();
    expect(within(s).getByRole("row", { name: /toplam 300 TL/ })).toBeInTheDocument();
    await waitFor(() => expect(s).toHaveFocus());
  });

  it("eksik girdi", async () => {
    await oturumAc("analist");
    uygulama();
    const d = await dene(KAMPANYA, { adet: "7" });
    expect(await within(d).findByText("Eksik girdi")).toBeInTheDocument();
    expect(within(d).getByTestId("kt-dene-sonuc")).toHaveTextContent("ara_toplam");
  });

  it("eşleşen satır yok", async () => {
    await oturumAc("analist");
    const t = kalite().tablolar.find((x) => x.id === "kt-1")!;
    t.icerik = { ...t.icerik, satirlar: t.icerik.satirlar.filter((s) => s.id === "R1") };
    uygulama();
    const d = await dene(KAMPANYA, { adet: "3", ara_toplam: "75" });
    expect(await within(d).findByText("Eşleşen satır yok")).toBeInTheDocument();
  });

  it("hata: sayı girdisine metin", async () => {
    await oturumAc("analist");
    uygulama();
    const d = await dene(KAMPANYA, { adet: "yedi", ara_toplam: "25" });
    expect(await within(d).findByText("Değerlendirilemedi")).toBeInTheDocument();
    expect(within(d).getByTestId("kt-dene-sonuc")).toHaveTextContent("'adet' girdisi sayi türünde olmalı");
  });

  it("mantıksal girdi seçimle: kampanyalı sepet R1", async () => {
    await oturumAc("analist");
    uygulama();
    const d = await dene(MIN, { sepet_tutari: "500", kampanyali_sepet: "dogru" });
    expect(await within(d).findByTestId("kt-dene-sonuc")).toHaveTextContent("Eşleşen satır: R1");
  });
});

describe("AI taslağı", () => {
  it("mevcut kayıtlar varken onay ister; üretim sürerken durum görünür, bitince yeni taslaklar ve eskiler ayrı", async () => {
    await oturumAc("analist");
    uygulama();
    await kart(KAMPANYA);
    await userEvent.click(screen.getByRole("button", { name: "AI taslağı üret" }));
    const onay = screen.getByTestId("taslak-onay");
    expect(onay).toHaveTextContent("2 tablo ve 1 ilişki");
    await userEvent.click(within(onay).getByRole("button", { name: "Evet, yeni taslak üret" }));
    expect(screen.queryByTestId("taslak-onay")).toBeNull();
    await waitFor(() => expect(bekleyenMockIs()).toBe(0), { timeout: 3000 });
    expect(screen.queryByTestId("taslak-suruyor")).toBeNull();
    expect(await kart(/T3 · Kampanya/)).toBeInTheDocument();
    expect(await kart(/T4 · Minimum/)).toBeInTheDocument();
    expect(screen.getByText("Yerini yenisi alan tablolar (2)")).toBeInTheDocument();
    expect(screen.getByText("Yerini yenisi alan ilişkiler (1)")).toBeInTheDocument();
  });

  it("onyüz 22: yeniden üretim onayında Vazgeç odağı 'AI taslağı üret'e döndürür", async () => {
    await oturumAc("analist");
    uygulama();
    await kart(KAMPANYA);
    await userEvent.click(screen.getByRole("button", { name: "AI taslağı üret" }));
    await userEvent.click(within(screen.getByTestId("taslak-onay")).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "AI taslağı üret" })).toHaveFocus());
  });

  it("iş sürerken 'AI taslağı üretiliyor…' durumu ve meşgul düğme; sonuç olayı gelince kalkar", async () => {
    await oturumAc("analist");
    const k = kalite();
    k.tablolar = [];
    k.iliskiler = [];
    vi.spyOn(api, "kararTablosuTaslagiUret").mockResolvedValue({ job_id: "job-x", workflow_id: "wf-x", durum: "started", uretim_no: null });
    uygulama();
    await screen.findByText("Bu gereksinim için karar tablosu yok.");
    await userEvent.click(screen.getByRole("button", { name: "AI taslağı üret" }));
    const durum = await screen.findByTestId("taslak-suruyor");
    expect(durum).toHaveTextContent("AI taslağı üretiliyor…");
    expect(screen.getByRole("button", { name: "AI taslağı üret" })).toHaveAttribute("aria-busy", "true");
    mockOlayYayinla({ type: "karar_tablosu.updated", id: "kt-x", data: { id: "kt-x", tur: "karar_tablosu", requirement_id: REQ, durum: "draft", eylem: "ai_taslak" } });
    await waitFor(() => expect(screen.queryByTestId("taslak-suruyor")).toBeNull());
  });

  it("gereksinim PO onaylı değilse düğme pasif ve nedeni görünür", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-3/karar-tablolari");
    const d = await screen.findByRole("button", { name: "AI taslağı üret" });
    await waitFor(() => expect(d).toBeDisabled());
    expect(screen.getAllByText("Karar tablosu için gereksinim PO onaylı olmalı.").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Boş tablo ekle" })).toBeDisabled();
    expect(screen.getByText("Bu gereksinim için karar tablosu yok.")).toBeInTheDocument();
  });
});

describe("ilişkiler", () => {
  it("taslak ilişki düzenlenir; geçersiz ifade alanın yanında, geçerli kayıt sonrası PO onayına gider", async () => {
    await oturumAc("analist");
    // Örnek veride taslak ilişki yok (golden'da yalnız I1): elle eklenir.
    await api.iliskiEkle(REQ, { icerik: YEDI_ARTIS_ILISKISI, karar_tablosu_id: "kt-1" });
    uygulama();
    const r = (await screen.findAllByTestId("iliski-kart")).find((x) => within(x).queryByText("Taslak"))!;
    await userEvent.click(within(r).getByRole("button", { name: "Düzenle" }));
    const form = within(r).getByTestId("iliski-duzenleyici");
    await waitFor(() => expect(within(form).getByLabelText("İlişki adı")).toHaveFocus());
    const on = within(form).getByLabelText("Ön koşul");
    await userEvent.clear(on);
    await userEvent.type(on, "adet >=");
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    await within(form).findByTestId("kt-kayit-hatasi");
    expect(on).toHaveAttribute("aria-invalid", "true");
    await userEvent.clear(on);
    await userEvent.type(on, "adet >= 1");
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(within(r).queryByTestId("iliski-duzenleyici")).toBeNull());
    expect(within(r).getByText("adet >= 1")).toBeInTheDocument();
    await userEvent.click(within(r).getByRole("button", { name: "PO onayına gönder" }));
    expect(await within(r).findByText("PO onayı bekliyor")).toBeInTheDocument();
  });

  it("Ek case türet: onaylı ilişki + seçili kaynaklar → türetilen bağlantılı, atlananlar nedenli; ikinci kez 'zaten türetildi'", async () => {
    await oturumAc("testci"); // 012 rol modeli: türetme `case.generate` (Testçi)
    uygulama();
    const bolum = await screen.findByTestId("ek-case-turet");
    const turet = vi.spyOn(api, "ekCaseTuret");
    await waitFor(() => expect(within(bolum).getAllByRole("checkbox").length).toBeGreaterThan(0));
    await userEvent.click(within(bolum).getByLabelText(/^C2 7 adet/));
    await userEvent.click(within(bolum).getByLabelText(/^C3 6 adet/));
    await userEvent.click(within(bolum).getByRole("button", { name: "Ek case türet" }));
    const s = await within(bolum).findByTestId("turet-sonuc");
    expect(turet).toHaveBeenCalledWith(REQ, { iliski_id: "mi-1", case_ids: ["case-1-2", "case-1-3"] });
    expect(within(s).getByText("Türetilen (1)")).toBeInTheDocument();
    // Onyüz 13: bağlantı türetilen case'in kartına gider.
    const yeniId = mockVerisi().caseler.at(-1)!.id;
    expect(within(s).getByRole("link", { name: /\(ilişki: Adet iki katına/ })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler#case-${yeniId}`);
    expect(within(s).getByText("Atlanan (1)")).toBeInTheDocument();
    // Onyüz 17: atlama nedeni düz dil.
    expect(within(s).getByText("Atlandı: ilişkinin ön koşulu bu case için sağlanmıyor")).toBeInTheDocument();
    expect(within(s).getByText(/Ön koşul sağlanmıyor/)).toBeInTheDocument();
    await waitFor(() => expect(s).toHaveFocus());

    await userEvent.click(within(bolum).getByRole("button", { name: "Ek case türet" }));
    await waitFor(() => expect(within(bolum).getByText("Atlandı: bu case'ten bu ilişkiyle daha önce türetildi")).toBeInTheDocument());
    expect(within(bolum).getByRole("link", { name: "Türetilen case'i aç" })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler#case-${yeniId}`);
    // Onyüz 14: türetme geçmişi açılınca yüklenir.
    const gecmis = within(bolum).getByTestId("turetme-gecmisi");
    await userEvent.click(within(gecmis).getByText("Türetme geçmişi"));
    expect(await within(gecmis).findByText("Türetildi")).toBeInTheDocument();
    expect(within(gecmis).getByRole("link", { name: "Türetilen case" })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler#case-${yeniId}`);
  });

  it("onaylı ilişki yoksa düğme pasif ve nedeni görünür; PO türetemez", async () => {
    await oturumAc("testci"); // 012 rol modeli: türetme `case.generate` (Testçi)
    const r = kalite().iliskiler.find((x) => x.id === "mi-1")!;
    r.durum = "draft";
    uygulama();
    const bolum = await screen.findByTestId("ek-case-turet");
    expect(within(bolum).getByRole("button", { name: "Ek case türet" })).toBeDisabled();
    expect(within(bolum).getByText("Önce bir ilişkiyi PO onayına gönderip onaylatın.")).toHaveClass("dugme-neden");
  });
});

describe("çekirdek sözleşmesi: son taslak, elle ilişki, örnekle dene (kaydedilmemiş)", () => {
  it("son taslakta atılan öğeler listelenir; süren iş açılışta gösterilir", async () => {
    await oturumAc("analist");
    const k = kalite();
    k.taslaklar = {
      [REQ]: { job_id: "j1", workflow_id: "w1", durum: "done", hata: null, olusturma: null, sonuc: { atilan: [{ tur: "karar_tablosu", ref: "T3", ad: "KDV", hatalar: ["satirlar[0].kosul: bilinmeyen ad 'kdv'"] }] } },
    };
    const { unmount } = uygulama();
    const atilan = await screen.findByTestId("taslak-atilan");
    expect(atilan).toHaveTextContent("1 öğe yazılmadı");
    expect(atilan).toHaveTextContent("bilinmeyen ad 'kdv'");
    unmount();
    k.taslaklar[REQ] = { ...k.taslaklar[REQ], durum: "started", sonuc: null };
    uygulama();
    expect(await screen.findByTestId("taslak-suruyor")).toBeInTheDocument();
  });

  it("PO 'Değişiklik iste' gerekçesi `son_karar`dan gösterilir", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("analist");
    const t = kalite().tablolar.find((x) => x.id === "kt-2")!;
    t.son_karar = { karar: "request_changes", gerekce: "Sınır dahil olmalı.", kullanici: "po", zaman: null };
    uygulama();
    const t2 = await kart(MIN);
    expect(within(t2).getByText("PO değişiklik istedi")).toBeInTheDocument();
    expect(within(t2).getByText(/Sınır dahil olmalı\./)).toBeInTheDocument();
  });

  it("düzenleyici açıkken 'Örnekle dene' kaydedilmemiş içeriği değerlendirir", async () => {
    // T2 başlangıçta PO onayı bekler (u2 N2); bu senaryo taslaktan başlar.
    await t2Taslak();
    await oturumAc("analist");
    uygulama();
    const t2 = await kart(MIN);
    await userEvent.click(within(t2).getByRole("button", { name: "Düzenle" }));
    const form = within(t2).getByTestId("kt-duzenleyici");
    const r2 = within(form).getByRole("group", { name: "Satır R2" });
    await userEvent.clear(within(r2).getByLabelText("Koşul"));
    await userEvent.type(within(r2).getByLabelText("Koşul"), "sepet_tutari >= 750");
    const dene = vi.spyOn(api, "kararTablosuDene");
    const d = within(t2).getByTestId("kt-dene");
    await userEvent.click(within(d).getByText("Örnekle dene"));
    expect(within(d).getByText("Düzenleyicideki kaydedilmemiş içerikle denenir.")).toBeInTheDocument();
    await userEvent.type(within(d).getByLabelText(/^sepet_tutari/), "750");
    await userEvent.selectOptions(within(d).getByLabelText(/^kampanyali_sepet/), "yanlis");
    await userEvent.click(within(d).getByRole("button", { name: "Dene" }));
    expect(await within(d).findByTestId("kt-dene-sonuc")).toHaveTextContent("Eşleşen satır: R2");
    expect(dene).toHaveBeenCalledWith("kt-2", { kampanyali_sepet: false, sepet_tutari: "750" }, expect.objectContaining({ satirlar: expect.any(Array) }));
    expect(kalite().tablolar.find((x) => x.id === "kt-2")!.icerik.satirlar[1].kosul).toBe("sepet_tutari <= 750");
  });

  it("Yeni ilişki: form odak alır, tabloya bağlanarak oluşturulur", async () => {
    await oturumAc("analist");
    uygulama();
    const bolum = await screen.findByTestId("iliskiler");
    await userEvent.click(within(bolum).getByRole("button", { name: "Yeni ilişki" }));
    const form = within(bolum).getByRole("form", { name: "Yeni ilişki" });
    await waitFor(() => expect(within(form).getByLabelText("İlişki adı")).toHaveFocus());
    await userEvent.type(within(form).getByLabelText("İlişki adı"), "Adet bir artınca toplam değişmez");
    await userEvent.selectOptions(within(form).getByLabelText("Bağlı tablo"), "kt-1");
    await userEvent.click(within(form).getByLabelText("AC2"));
    const on = within(form).getByLabelText("Ön koşul");
    await userEvent.clear(on);
    await userEvent.type(on, "adet < 6");
    await userEvent.click(within(form).getByRole("button", { name: "Girdi ekle" }));
    await userEvent.type(within(form).getByLabelText("Girdi"), "adet");
    await userEvent.type(within(form).getAllByLabelText("İfade")[0], "adet + 1");
    await userEvent.click(within(form).getByRole("button", { name: "Çıktı ekle" }));
    await userEvent.type(within(form).getByLabelText("Çıktı"), "bedava_adet");
    await userEvent.type(within(form).getAllByLabelText("İfade")[1], "bedava_adet");
    await userEvent.click(within(form).getByRole("button", { name: "İlişkiyi oluştur" }));
    await waitFor(() => expect(within(bolum).queryByRole("form", { name: "Yeni ilişki" })).toBeNull());
    expect(await within(bolum).findByText(/Adet bir artınca toplam değişmez/)).toBeInTheDocument();
    expect(kalite().iliskiler.at(-1)).toMatchObject({ karar_tablosu_id: "kt-1", ai_generated: false, durum: "draft" });
  });
});

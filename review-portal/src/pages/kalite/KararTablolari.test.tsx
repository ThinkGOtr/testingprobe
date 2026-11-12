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
import { MIN_SIPARIS_TABLOSU } from "../../api/mock/kaliteVerisi";
import { mockOlayYayinla } from "../../api/mock/olaylar";
import { OturumProvider } from "../../auth";
import { BildirimProvider } from "../../components/Bildirim";
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
    expect(within(t1).getByText("AI taslağı")).toBeInTheDocument();
    expect(within(t1).getByText("AC2")).toBeInTheDocument();
    expect(within(t1).getByTestId("kt-onay")).toHaveTextContent("PO onayı:");
    expect(t1).toHaveClass("insan-kapisi", "kapi-gecti");
    const t2 = await kart(MIN);
    expect(within(t2).getByText("Taslak")).toBeInTheDocument();
    expect(t2).toHaveClass("kt-ai");
    expect(t2).not.toHaveClass("kapi-gecti");
    // Satırlar tablosu: her çıktı için bir sütun.
    const satirlar = within(t1).getByRole("region", { name: /satırlar/ });
    expect(within(satirlar).getByRole("columnheader", { name: "indirim" })).toBeInTheDocument();
    expect(within(satirlar).getByText("adet >= 7")).toBeInTheDocument();
    // İlişkiler bölümü.
    const iliskiler = screen.getByTestId("iliskiler");
    expect(within(iliskiler).getAllByTestId("iliski-kart")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Case review" })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler`);
    expect(screen.getByRole("link", { name: /← TPD-1/ })).toHaveAttribute("href", `/gereksinimler/${REQ}`);
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
    await oturumAc("analist");
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
    expect(document.getElementById(kosul.getAttribute("aria-describedby")!)).toHaveTextContent(/bilinmeyen/);
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
    expect(within(t2).getByText(/Sınır 750 dahil olmalı/)).toBeInTheDocument();


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

  it("görülen hash eskiyse geçiş 409 verir ve liste yenilenir", async () => {
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
    const d = await dene(KAMPANYA, { adet: "14", birim_fiyat: "25,00" });
    const s = await within(d).findByTestId("kt-dene-sonuc");
    expect(s).toHaveTextContent("Eşleşen satır: R1");
    expect(within(s).getByRole("row", { name: /bedava_adet 2/ })).toBeInTheDocument();
    expect(within(s).getByRole("row", { name: /indirim 50 TL/ })).toBeInTheDocument();
    await waitFor(() => expect(s).toHaveFocus());
  });

  it("eksik girdi", async () => {
    await oturumAc("analist");
    uygulama();
    const d = await dene(KAMPANYA, { adet: "7" });
    expect(await within(d).findByText("Eksik girdi")).toBeInTheDocument();
    expect(within(d).getByTestId("kt-dene-sonuc")).toHaveTextContent("birim_fiyat");
  });

  it("eşleşen satır yok", async () => {
    await oturumAc("analist");
    const t = kalite().tablolar.find((x) => x.id === "kt-1")!;
    t.icerik = { ...t.icerik, satirlar: t.icerik.satirlar.filter((s) => s.id === "R1") };
    uygulama();
    const d = await dene(KAMPANYA, { adet: "3", birim_fiyat: "25" });
    expect(await within(d).findByText("Eşleşen satır yok")).toBeInTheDocument();
  });

  it("hata: sayı girdisine metin", async () => {
    await oturumAc("analist");
    uygulama();
    const d = await dene(KAMPANYA, { adet: "yedi", birim_fiyat: "25" });
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
    expect(onay).toHaveTextContent("2 tablo ve 2 ilişki");
    await userEvent.click(within(onay).getByRole("button", { name: "Evet, yeni taslak üret" }));
    expect(screen.queryByTestId("taslak-onay")).toBeNull();
    await waitFor(() => expect(bekleyenMockIs()).toBe(0), { timeout: 3000 });
    expect(screen.queryByTestId("taslak-suruyor")).toBeNull();
    expect(await kart(/T3 · Kampanya/)).toBeInTheDocument();
    expect(await kart(/T4 · Minimum/)).toBeInTheDocument();
    expect(screen.getByText("Yerini yenisi alan tablolar (2)")).toBeInTheDocument();
    expect(screen.getByText("Yerini yenisi alan ilişkiler (2)")).toBeInTheDocument();
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
    await oturumAc("analist");
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
    expect(within(s).getByRole("link", { name: /\(ilişki: Adet iki katına/ })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler`);
    expect(within(s).getByText("Atlanan (1)")).toBeInTheDocument();
    expect(within(s).getByText("Atlandı: ilişki geçersiz")).toBeInTheDocument();
    expect(within(s).getByText(/Ön koşul sağlanmıyor/)).toBeInTheDocument();
    await waitFor(() => expect(s).toHaveFocus());

    await userEvent.click(within(bolum).getByRole("button", { name: "Ek case türet" }));
    await waitFor(() => expect(within(bolum).getByText("Atlandı: zaten türetildi")).toBeInTheDocument());
    expect(within(bolum).getByRole("link", { name: "Türetilen case'i aç" })).toBeInTheDocument();
  });

  it("onaylı ilişki yoksa düğme pasif ve nedeni görünür; PO türetemez", async () => {
    await oturumAc("analist");
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
    await oturumAc("analist");
    const t = kalite().tablolar.find((x) => x.id === "kt-2")!;
    t.son_karar = { karar: "request_changes", gerekce: "Sınır dahil olmalı.", kullanici: "po", zaman: null };
    uygulama();
    const t2 = await kart(MIN);
    expect(within(t2).getByText("PO değişiklik istedi")).toBeInTheDocument();
    expect(within(t2).getByText(/Sınır dahil olmalı\./)).toBeInTheDocument();
  });

  it("düzenleyici açıkken 'Örnekle dene' kaydedilmemiş içeriği değerlendirir", async () => {
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

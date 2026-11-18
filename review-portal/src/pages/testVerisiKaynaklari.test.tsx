// Test verisi sayfası: veritabanı kaynakları bölümü (`/test-data-sources`; liste, önizleme, yenileme yoklaması).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import { mockIstek } from "../api/mock/handlers";
import { kaynakIsiUyarla, testVerisiKaynagiUyarla, testVerisiUyarla } from "../api/uyumOtomasyon";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { KAYNAKTA_YOK_IPUCU } from "./TestVerisi";
import { kaynakIsAyari } from "./TestVerisiKaynaklari";

function uygulama() {
  return render(
    <MemoryRouter initialEntries={["/test-verisi"]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

type Cagri = { method: string; path: string; govde: unknown };
function izle(ozel?: (c: Cagri) => unknown) {
  const cagrilar: Cagri[] = [];
  yapilandir({
    mock: async (method, path, q, govde) => {
      const c = { method, path, govde };
      cagrilar.push(c);
      const o = ozel?.(c);
      if (o !== undefined) return o;
      return mockIstek(method, path, q, govde);
    },
  });
  return cagrilar;
}

const kaynakOgesi = (grup: string) => document.querySelector(`li[data-kaynak="${grup}"]`) as HTMLElement;
const bolum = () => screen.getByRole("region", { name: "Veritabanı kaynakları" });

beforeEach(() => {
  kaynakIsAyari.aralikMs = 5;
});
afterEach(() => {
  kaynakIsAyari.aralikMs = 1500;
});

describe("Test verisi: veritabanı kaynakları", () => {
  it("ön tanımlı kaynakları listeler; katalog kaydında kaynak rozeti", async () => {
    await oturumAc("analist");
    uygulama();
    await waitFor(() => expect(kaynakOgesi("bayi")).not.toBeNull());
    expect([...document.querySelectorAll("li[data-kaynak]")].map((e) => e.getAttribute("data-kaynak"))).toEqual(["bayi", "urun", "kampanya", "ayar"]);
    const urun = kaynakOgesi("urun");
    expect(urun).toHaveTextContent("Ön tanımlı");
    expect(urun).toHaveTextContent("Aktif ürünler");
    expect(urun).toHaveTextContent("kod, ad, fiyat (tutar)");
    expect(urun).toHaveTextContent("Henüz yenilenmedi");
    // ayar: tek değer kolonu, alan boş → anahtar `ayar.<anahtar>`.
    expect(kaynakOgesi("ayar")).toHaveTextContent("deger→(anahtar)");
    expect(within(urun).getByText("2", { selector: "dd" })).toBeInTheDocument(); // urun.p_001.ad + fiyat
    expect(within(bolum()).getByRole("button", { name: "Kaynak ekle" })).toBeInTheDocument();

    const fiyat = await waitFor(() => {
      const t = document.querySelector('tr[data-anahtar="urun.p_001.fiyat"]') as HTMLElement;
      expect(t).toHaveTextContent("kaynak: urun");
      return t;
    });
    expect(fiyat).not.toHaveTextContent("Kaynakta yok");
    // Elle girilmiş gizli kayıt kaynak rozetsizdir.
    expect(document.querySelector('tr[data-anahtar="ortak.demo_parola"]')).not.toHaveTextContent("kaynak:");
  });

  it("kaynakta_yok kaydında uyarı rozeti (ipucuyla)", async () => {
    await oturumAc("analist");
    izle((c) =>
      c.method === "GET" && c.path === "/test-data"
        ? mockIstek("GET", "/test-data", new URLSearchParams(), undefined).then((l) =>
            (l as Record<string, unknown>[]).map((k) => (k.anahtar === "urun.p_001.ad" ? { ...k, kaynakta_yok: true } : k)),
          )
        : undefined,
    );
    uygulama();
    const satir = await waitFor(() => {
      const t = document.querySelector('tr[data-anahtar="urun.p_001.ad"]') as HTMLElement;
      expect(t).toHaveTextContent("Kaynakta yok");
      return t;
    });
    expect(within(satir).getByText("Kaynakta yok")).toHaveAttribute("title", KAYNAKTA_YOK_IPUCU);
    expect(document.querySelector('tr[data-anahtar="urun.p_001.fiyat"]')).not.toHaveTextContent("Kaynakta yok");
  });

  it("kaynak ekle: önizleme yoklanır, satırlar + anahtar durumları görünür; kaydet POST gövdesi", async () => {
    await oturumAc("analist");
    const cagrilar = izle();
    uygulama();
    const u = userEvent.setup();
    await u.click(await within(await screen.findByRole("region", { name: "Veritabanı kaynakları" })).findByRole("button", { name: "Kaynak ekle" }));
    await u.type(screen.getByLabelText("Kaynak grubu"), "fiyat");
    await u.type(screen.getByLabelText("Kaynak açıklaması"), "Ürün fiyatları");
    await u.type(screen.getByLabelText("SQL sorgusu"), "SELECT kod, fiyat FROM urun ORDER BY kod");
    await u.type(screen.getByLabelText("Anahtar kolonu"), "kod");
    await u.type(screen.getByLabelText("Değer kolonu 1"), "fiyat");
    await u.selectOptions(screen.getByLabelText("Biçim 1"), "tutar");
    await u.click(screen.getByRole("button", { name: "Önizle" }));

    const o = await screen.findByTestId("kaynak-onizleme");
    expect(o).toHaveTextContent("Sorgu 2 satır döndü");
    expect(o).toHaveTextContent("2 katalog kaydı üretir");
    expect(within(o).getByRole("columnheader", { name: "fiyat" })).toBeInTheDocument();
    expect(within(o).getByRole("cell", { name: "P-002" })).toBeInTheDocument();
    const anahtar = o.querySelector('li[data-anahtar="fiyat.p_001"]') as HTMLElement;
    expect(anahtar).toHaveTextContent("= 30,00 TL");
    expect(anahtar).toHaveTextContent("yeni");
    // İş ilk yoklamada "çalışıyor": en az iki kez sorgulanır.
    expect(cagrilar.filter((c) => c.method === "GET" && c.path.startsWith("/test-data-sources/jobs/")).length).toBeGreaterThanOrEqual(2);
    expect(cagrilar.find((c) => c.path === "/test-data-sources/preview")?.govde).toMatchObject({
      grup: "fiyat",
      anahtar_kolonu: "kod",
      deger_kolonlari: [{ kolon: "fiyat", alan: "", bicim: "tutar" }],
    });

    // Tanım değişince önizleme eski sayılır.
    await u.type(screen.getByLabelText("Alan 1"), "tl");
    expect(screen.getByText(/Tanım önizlemeden sonra değişti/)).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Kaynağı ekle" }));
    await waitFor(() => expect(kaynakOgesi("fiyat")).not.toBeNull());
    expect(kaynakOgesi("fiyat")).not.toHaveTextContent("Ön tanımlı");
    expect(cagrilar.find((c) => c.method === "POST" && c.path === "/test-data-sources")?.govde).toEqual({
      grup: "fiyat",
      sorgu: "SELECT kod, fiyat FROM urun ORDER BY kod",
      anahtar_kolonu: "kod",
      deger_kolonlari: [{ kolon: "fiyat", alan: "tl", bicim: "tutar", aciklama: null }],
      aciklama: "Ürün fiyatları",
    });
  });

  it("önizlemede sorgu hatası (hassas kolon) gösterilir; aynı grup 409 detail metni", async () => {
    await oturumAc("analist");
    uygulama();
    const u = userEvent.setup();
    await u.click(await within(await screen.findByRole("region", { name: "Veritabanı kaynakları" })).findByRole("button", { name: "Kaynak ekle" }));
    await u.type(screen.getByLabelText("Kaynak grubu"), "bayi");
    await u.type(screen.getByLabelText("SQL sorgusu"), "SELECT kullanici_adi, parola_hash FROM bayi");
    await u.type(screen.getByLabelText("Anahtar kolonu"), "kullanici_adi");
    await u.type(screen.getByLabelText("Değer kolonu 1"), "parola_hash");
    await u.click(screen.getByRole("button", { name: "Önizle" }));
    expect(await screen.findByText(/Sorgu muhafızı: hassas kolon okunamaz/)).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Kaynağı ekle" }));
    expect(await screen.findByText("Bu grup için zaten bir kaynak var: bayi")).toBeInTheDocument();
  });

  it("tümünü yenile: iş yoklanır, düğmeler pasif, özet görünür; kaynak ve katalog yeniden yüklenir", async () => {
    // Ara durumu yük altında da gözlemlemek için yoklama aralığı bu testte daha uzun.
    kaynakIsAyari.aralikMs = 400;
    await oturumAc("muhendis");
    const cagrilar = izle();
    uygulama();
    const u = userEvent.setup();
    await waitFor(() => expect(kaynakOgesi("bayi")).not.toBeNull());
    expect(document.querySelector('tr[data-anahtar="bayi.bayi2.ad"]')).toBeNull();
    const listeOnce = cagrilar.filter((c) => c.method === "GET" && c.path === "/test-data").length;

    await u.click(within(bolum()).getByRole("button", { name: "Tümünü yenile" }));
    // İş sürerken (ilk yoklama "calisiyor"): düğmeler pasif ve ilerleme satırı görünür (aynı anda).
    expect(within(bolum()).getByRole("button", { name: "bayi kaynağını yenile" })).toBeDisabled();
    expect(screen.getByTestId("kaynak-yenileme-durumu")).toHaveTextContent("Tüm kaynaklar yenileniyor");

    const durum = screen.getByTestId("kaynak-yenileme-durumu");
    await waitFor(() => expect(durum).toHaveTextContent("Yenileme tamamlandı"), { timeout: 3000 });
    // bayi: kullanici_adi ×2 aynı, bayi1.ad aynı, bayi2.ad + bayi1.kredi_limiti yeni; urun: p_001.kod + p_002 ×3 yeni; kampanya: kod yeni.
    expect(durum).toHaveTextContent("7 yeni · 0 güncellendi · 0 kaynakta yok");
    expect(durum).toHaveTextContent("bayi: 2 satır · 2 yeni");
    expect(cagrilar.find((c) => c.path === "/test-data-sources/refresh")?.govde).toEqual({});
    expect(cagrilar.filter((c) => c.method === "GET" && c.path.startsWith("/test-data-sources/jobs/")).length).toBeGreaterThanOrEqual(2);

    await waitFor(() => expect(document.querySelector('tr[data-anahtar="bayi.bayi2.ad"]')).toHaveTextContent("Ege Bayi"));
    expect(document.querySelector('tr[data-anahtar="bayi.bayi1.kredi_limiti"]')).toHaveTextContent("10.000,00 TL");
    expect(cagrilar.filter((c) => c.method === "GET" && c.path === "/test-data").length).toBeGreaterThan(listeOnce);
    await waitFor(() => expect(kaynakOgesi("bayi")).toHaveTextContent("2 yeni · 0 güncellendi · 0 kaynakta yok"));
    expect(within(bolum()).getByRole("button", { name: "bayi kaynağını yenile" })).toBeEnabled();

    // Tek kaynak yenileme kaynak_id gönderir.
    await u.click(within(bolum()).getByRole("button", { name: "urun kaynağını yenile" }));
    await waitFor(() => expect(cagrilar.filter((c) => c.path === "/test-data-sources/refresh")).toHaveLength(2));
    expect(cagrilar.filter((c) => c.path === "/test-data-sources/refresh")[1].govde).toEqual({ kaynak_id: "kyn-urun" });
    await waitFor(() => expect(durum).toHaveTextContent("0 yeni · 0 güncellendi · 0 kaynakta yok"));
  });

  it("kaynak silme onayı kayıtların kaldığını söyler; silinince katalog rozeti düşer", async () => {
    await oturumAc("analist");
    uygulama();
    const u = userEvent.setup();
    await waitFor(() => expect(kaynakOgesi("kampanya")).not.toBeNull());
    await u.click(within(bolum()).getByRole("button", { name: "kampanya kaynağını sil" }));
    const onay = screen.getByRole("group", { name: "kampanya kaynağı silme onayı" });
    expect(onay).toHaveTextContent("1 katalog kaydı silinmez");
    await u.click(within(onay).getByRole("button", { name: "Evet, kaynağı sil" }));
    await waitFor(() => expect(kaynakOgesi("kampanya")).toBeNull());
    await waitFor(() => expect(document.querySelector('tr[data-anahtar="kampanya.k6_1.ad"]')).not.toHaveTextContent("kaynak:"));
  });

  it("düzenleme: grup salt okunur; araya giren değişiklikte 409 anlaşılır mesaj", async () => {
    await oturumAc("analist");
    uygulama();
    const u = userEvent.setup();
    await waitFor(() => expect(kaynakOgesi("ayar")).not.toBeNull());
    // Form sürüm 1'i taşır; araya başka biri girer (sürüm 2).
    await u.click(within(bolum()).getByRole("button", { name: "ayar kaynağını düzenle" }));
    expect(screen.getByLabelText("Kaynak grubu")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Kaynak grubu")).toHaveValue("ayar");
    await mockIstek("PUT", "/test-data-sources/kyn-ayar", new URLSearchParams(), { aciklama: "Başkası", beklenen_surum: 1 });
    await u.type(screen.getByLabelText("Kolon açıklaması 1"), " (düzenlendi)");
    await u.click(screen.getByRole("button", { name: "Kaynağı kaydet" }));
    expect(await screen.findByText(/Bu kaynak siz düzenlerken değişti/)).toBeInTheDocument();
  });

  it("PO listeyi görür, eylem düğmelerini görmez", async () => {
    await oturumAc("po");
    uygulama();
    await waitFor(() => expect(kaynakOgesi("bayi")).not.toBeNull());
    expect(within(bolum()).queryByRole("button", { name: "Kaynak ekle" })).toBeNull();
    expect(within(bolum()).queryByRole("button", { name: "Tümünü yenile" })).toBeNull();
    expect(within(bolum()).queryByRole("button", { name: /kaynağını (yenile|düzenle|sil)$/ })).toBeNull();
    expect(kaynakOgesi("bayi")).toHaveTextContent("kullanici_adi");
  });
});

describe("kaynak uyarlayıcıları", () => {
  it("eski katalog yanıtında kaynak alanları güvenli varsayılan", () => {
    const k = testVerisiUyarla({ id: "1", anahtar: "x.y", deger: "d" });
    expect(k.kaynak_id).toBeNull();
    expect(k.kaynakta_yok).toBe(false);
  });

  it("kaynak ve iş yanıtı uyarlanır; gizli önizleme değeri süzülür", () => {
    const k = testVerisiKaynagiUyarla({ id: "k1", grup: "g", deger_kolonlari: [{ kolon: "a", bicim: "?" }], son_durum: { eklenen: 2, hata: null } });
    expect(k.deger_kolonlari).toEqual([{ kolon: "a", alan: "", bicim: "metin", aciklama: "" }]);
    expect(k.son_durum).toMatchObject({ eklenen: 2, guncellenen: 0, hata: null, uyarilar: [] });
    const is = kaynakIsiUyarla({
      id: "j",
      tur: "onizle",
      durum: "tamam",
      sonuc: { kolonlar: ["a"], satirlar: [[1, null]], kayitlar: [{ anahtar: "g.x", deger: "s", durum: "gizli_cakisma" }] },
    });
    expect(is.tur === "onizle" && is.sonuc).toMatchObject({ hata: null, satirlar: [["1", null]], kayitlar: [{ anahtar: "g.x", deger: null }] });
    expect(kaynakIsiUyarla({ id: "j", tur: "onizle", durum: "tamam", sonuc: { hata: "bozuk" } }).sonuc).toEqual({ hata: "bozuk" });
    expect(kaynakIsiUyarla({ id: "j", tur: "yenile", durum: "?" }).durum).toBe("hata");
  });
});

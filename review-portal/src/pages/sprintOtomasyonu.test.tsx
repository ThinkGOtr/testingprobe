// 013 sprint otomasyonu portal şeridi (specs/013-sprint-otomasyonu §3.5): toplu onay, atıf çipleri,
// "Test verisi ekle", Test verisi kataloğu (CRUD + 409), Otomasyon ayarları, kod üretimi rozetleri,
// demo Jira durumu ve rol görünürlüğü.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, istek, yapilandir } from "../api/http";
import { mockIstek, mockVerisi } from "../api/mock/handlers";
import type { TestCase } from "../api/types";
import { atifYapanlarUyarla, testVerisiUyarla, topluKararUyarla } from "../api/uyumOtomasyon";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { goruntulenenleriSifirla } from "../components/CaseKarti";
import { AtifliMetin } from "../components/VeriAtfi";
import { sahteSunucu } from "../test/sahteSunucu";
import { oturumAc } from "../test/yardimci";
import { topluOnayAdaylari } from "./CaseReview";
import { SURUM_CAKISMASI } from "./TestVerisi";

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

type Cagri = { method: string; path: string; govde: unknown };
/** Mock arka ucu sarar: her isteğin gövdesi kaydedilir; `ozel` bir yanıtı değiştirebilir. */
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

/** Birinci gereksinime üç taslak case: #1 ve #2 görüntülenmiş, #3 görülmemiş. */
function taslaklariKur(): { rid: string; caseler: TestCase[] } {
  const v = mockVerisi();
  const rid = v.gereksinimler[0].id;
  const temel = v.caseler[0];
  const caseler = [1, 2, 3].map((n) => ({
    ...JSON.parse(JSON.stringify(temel)),
    id: `tc-013-${n}`,
    requirement_id: rid,
    sira_no: n,
    durum: "draft",
    karar: null,
    karar_veren: null,
    karar_zamani: null,
    onaylanan_hash: null,
    jira_test_key: null,
    goruntulenme: n < 3 ? "2026-11-11T09:00:00+03:00" : null,
    icerik: { ...JSON.parse(JSON.stringify(temel.icerik)), title: `Taslak ${n}` },
  })) as TestCase[];
  v.caseler = [...v.caseler.filter((c) => c.requirement_id !== rid), ...caseler];
  v.scriptler = v.scriptler.filter((s) => !s.case_ids.some((id) => id.startsWith("tc-013-")));
  return { rid, caseler };
}

beforeEach(() => {
  goruntulenenleriSifirla();
});

describe("topluOnayAdaylari (K3)", () => {
  const c = (id: string, ek: Partial<TestCase>) => ({ id, durum: "draft", ...ek }) as TestCase;
  it("yalnız görülmüş, engelsiz taslaklar; görülmeyen ve engelli sayılır", () => {
    const l = [
      c("a", { goruldu: true }),
      c("b", { goruldu: false }),
      c("c", {}),
      c("d", { goruldu: true, onay_engeli: "AC yok" }),
      c("e", { goruldu: true, durum: "approved" }),
    ];
    const t = topluOnayAdaylari(l);
    expect(t.uygun.map((x) => x.id)).toEqual(["a"]);
    expect(t.gorulmeyen).toBe(2);
    expect(t.engelli).toBe(1);
    // Bu oturumda kaydedilen görüntüleme de sayılır.
    expect(topluOnayAdaylari(l, new Set(["b"])).uygun.map((x) => x.id)).toEqual(["a", "b"]);
  });
});

describe("Case review: toplu onay", () => {
  it("Tümünü onayla yalnız görülenleri gönderir (kendi hash'iyle), görülmeyen notu ve satır içi özet", async () => {
    const { rid, caseler } = taslaklariKur();
    await oturumAc("analist");
    vi.spyOn(api, "caseGoruntulendi").mockRejectedValue(new Error("ölçüm yok"));
    const cagrilar = izle();
    uygulama(`/gereksinimler/${rid}/caseler`);
    const tumu = await screen.findByRole("button", { name: "Tümünü onayla (2)" });
    expect(screen.getByTestId("toplu-onay-notu")).toHaveTextContent("1 case açılmadığı için dışarıda.");
    expect(screen.getByRole("button", { name: "Seçili onayla (0)" })).toBeDisabled();
    // Görülmeyen #3'ün kutusu pasif.
    expect(screen.getByRole("checkbox", { name: /#3 toplu onay için seç/ })).toBeDisabled();

    const u = userEvent.setup();
    await u.click(tumu);
    const teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    const onayla = within(teyit).getByRole("button", { name: "Onayla (2)" });
    expect(onayla).toBeDisabled();
    await u.click(within(teyit).getByRole("checkbox"));
    await u.click(onayla);

    const sonuc = await screen.findByTestId("toplu-onay-sonucu");
    expect(sonuc).toHaveTextContent("Toplu onay: 2 onaylandı · 0 atlandı");
    expect(screen.getByTestId("toplu-otokod")).toHaveTextContent("Otomatik kod üretimi: 2 kuyrukta");
    const istek = cagrilar.find((c) => c.method === "POST" && c.path === "/cases/bulk-decision");
    const hash = (id: string) => mockVerisi().caseler.find((x) => x.id === id)!.icerik_hash;
    expect(istek?.govde).toEqual({
      karar: "approve",
      ogeler: [
        { case_id: caseler[0].id, icerik_hash: hash(caseler[0].id) },
        { case_id: caseler[1].id, icerik_hash: hash(caseler[1].id) },
      ],
    });
    expect(mockVerisi().caseler.filter((x) => x.id.startsWith("tc-013-")).map((x) => x.durum)).toEqual(["approved", "approved", "draft"]);
  });

  it("Seçili onayla: seçilen sayısı, atlanan neden ve otomatik kod notu gösterilir", async () => {
    const { rid, caseler } = taslaklariKur();
    await oturumAc("analist");
    vi.spyOn(api, "caseGoruntulendi").mockRejectedValue(new Error("ölçüm yok"));
    const cagrilar = izle((c) =>
      c.path === "/cases/bulk-decision"
        ? {
            sonuclar: [
              { case_id: caseler[0].id, durum: "onaylandi", neden: null, otomatik_kod: { durum: "reddedildi", neden: "test verisi sırrı tanımsız: ortak.demo_parola", script_id: null } },
              { case_id: caseler[1].id, durum: "atlandi", neden: "Bu case'i açıp görmediniz", otomatik_kod: null },
            ],
            ozet: { onaylandi: 1, atlandi: 1, hata: 0 },
          }
        : undefined,
    );
    uygulama(`/gereksinimler/${rid}/caseler`);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("checkbox", { name: /#1 toplu onay için seç/ }));
    await u.click(screen.getByRole("checkbox", { name: /#2 toplu onay için seç/ }));
    await u.click(screen.getByRole("button", { name: "Seçili onayla (2)" }));
    const teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await u.click(within(teyit).getByRole("checkbox"));
    await u.click(within(teyit).getByRole("button", { name: "Onayla (2)" }));
    const sonuc = await screen.findByTestId("toplu-onay-sonucu");
    expect(sonuc).toHaveTextContent("1 onaylandı · 1 atlandı");
    expect(within(sonuc).getByRole("list", { name: "Onaylanmayan case'ler" })).toHaveTextContent("#2 Taslak 2 — Bu case'i açıp görmediniz");
    expect(within(sonuc).getByRole("list", { name: "Otomatik kod üretimi notları" })).toHaveTextContent("test verisi sırrı tanımsız");
    expect((cagrilar.find((c) => c.path === "/cases/bulk-decision")?.govde as { ogeler: unknown[] }).ogeler).toHaveLength(2);
  });

  it("otomatik kod kapalıysa özet 'kapalı' der; tekli onay kısa bildirim gösterir", async () => {
    const { rid } = taslaklariKur();
    await oturumAc("analist");
    await api.otomasyonAyariKaydet("otomatik_kod_uretimi", { acik: false });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article")!;
    await userEvent.click(within(kart as HTMLElement).getByRole("button", { name: "Onayla" }));
    expect(await screen.findByText(/Otomatik kod üretimi kapalı/)).toBeInTheDocument();
  });

  it("analist olmayan rol toplu onay çubuğunu ve seçim kutularını görmez", async () => {
    const { rid } = taslaklariKur();
    await oturumAc("po");
    uygulama(`/gereksinimler/${rid}/caseler`);
    await screen.findByRole("heading", { name: "Taslak 1" });
    expect(screen.queryByRole("region", { name: "Toplu onay" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /toplu onay için seç/ })).toBeNull();
  });
});

describe("Case kartı: test verisi atıfları", () => {
  it("değer, gizli ve bilinmeyen atıf çipleri", async () => {
    const { rid, caseler } = taslaklariKur();
    const c = mockVerisi().caseler.find((x) => x.id === caseler[0].id)!;
    c.icerik.steps[0] = { id: "S1", action: "{veri:bayi.bayi1.kullanici_adi} ile giriş yap", data: "{veri:ortak.demo_parola}", expected: "{veri:yok.boyle} görünür" };
    await oturumAc("analist");
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    const cip = (a: string) => kart.querySelector(`.veri-atif[data-anahtar="${a}"]`) as HTMLElement;
    await waitFor(() => expect(cip("bayi.bayi1.kullanici_adi")).not.toBeNull());
    expect(cip("bayi.bayi1.kullanici_adi")).toHaveTextContent("Test verisi bayi.bayi1.kullanici_adi: bayi1");
    expect(cip("ortak.demo_parola")).toHaveTextContent("••• (gizli)");
    expect(cip("ortak.demo_parola")).not.toHaveTextContent("Demo123!");
    expect(cip("yok.boyle")).toHaveAttribute("data-durum", "yok");
    expect(cip("yok.boyle")).toHaveClass("veri-atif-yok");
    expect(cip("yok.boyle")).toHaveTextContent("Bilinmeyen test verisi yok.boyle: katalogda yok");
  });

  it("veri alanı yoksa (eski core) atıf nötr çip, kırmızı değil", () => {
    render(<AtifliMetin metin="{veri:a.b} ile" />);
    const el = document.querySelector(".veri-atif")!;
    expect(el).toHaveAttribute("data-durum", "bilinmiyor");
    expect(el.parentElement).toHaveTextContent("a.b ile");
  });

  it("Düzelt: 'Test verisi ekle' seçilen anahtarı son alanda imlece ekler", async () => {
    const { rid } = taslaklariKur();
    await oturumAc("analist");
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    const u = userEvent.setup();
    await u.click(within(kart).getByRole("button", { name: "Düzelt" }));
    const veri = within(kart).getByLabelText("S1 veri") as HTMLTextAreaElement;
    await u.clear(veri);
    await u.type(veri, "kullanıcı: ");
    const secici = await within(kart).findByLabelText("Eklenecek test verisi");
    await u.selectOptions(secici, "bayi.bayi1.kullanici_adi");
    await u.click(within(kart).getByRole("button", { name: "İmlece ekle (S1 veri)" }));
    expect(veri.value).toBe("kullanıcı: {veri:bayi.bayi1.kullanici_adi}");
    // Gizli kayıt seçicide de değer göstermez.
    expect(within(kart).getByRole("option", { name: "ortak.demo_parola — ••• (gizli)" })).toBeInTheDocument();
  });
});

describe("Test verisi sayfası", () => {
  it("grup tabloları, arama, gizli rozet; analist ekler; aynı anahtar 409", async () => {
    await oturumAc("analist");
    uygulama("/test-verisi");
    expect(await screen.findByRole("heading", { name: /bayi/ })).toBeInTheDocument();
    const parola = document.querySelector('tr[data-anahtar="ortak.demo_parola"]') as HTMLElement;
    expect(parola).toHaveTextContent("••• (gizli)");
    expect(parola).toHaveTextContent("sır tanımlı");
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Ara"), "gazoz");
    expect(screen.getByText("1 / 9 kayıt")).toBeInTheDocument();
    expect(document.querySelectorAll("tbody tr")).toHaveLength(1);
    await u.clear(screen.getByLabelText("Ara"));

    await u.click(screen.getByRole("button", { name: "Yeni kayıt" }));
    await u.type(screen.getByLabelText("Anahtar"), "urun.p_002.ad");
    await u.type(screen.getByLabelText("Değer"), "Limonata 1L");
    await u.click(screen.getByRole("button", { name: "Ekle" }));
    await waitFor(() => expect(document.querySelector('tr[data-anahtar="urun.p_002.ad"]')).toHaveTextContent("Limonata 1L"));

    await u.click(screen.getByRole("button", { name: "Yeni kayıt" }));
    await u.type(screen.getByLabelText("Anahtar"), "urun.p_002.ad");
    await u.type(screen.getByLabelText("Değer"), "x");
    await u.click(screen.getByRole("button", { name: "Ekle" }));
    expect(await screen.findByText("Bu anahtar zaten var: urun.p_002.ad")).toBeInTheDocument();
  });

  it("düzenleme beklenen_surum gönderir; araya giren değişiklikte 409 anlaşılır mesaj + güncel sürümü yükle", async () => {
    await oturumAc("analist");
    const cagrilar = izle();
    uygulama("/test-verisi");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "urun.p_001.fiyat düzenle" }));
    const deger = screen.getByLabelText("Değer");
    await u.clear(deger);
    await u.type(deger, "32,00 TL");
    await u.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(document.querySelector('tr[data-anahtar="urun.p_001.fiyat"]')).toHaveTextContent("32,00 TL"));
    expect(cagrilar.find((c) => c.method === "PUT")?.govde).toMatchObject({ deger: "32,00 TL", beklenen_surum: 1 });

    // Başka biri araya giriyor (sürüm 2 → 3) ve form eski sürümle (2) gönderiliyor.
    await u.click(screen.getByRole("button", { name: "urun.p_001.fiyat düzenle" }));
    await api.testVerisiGuncelle("tv-6", { deger: "35,00 TL", beklenen_surum: 2 });
    await u.clear(screen.getByLabelText("Değer"));
    await u.type(screen.getByLabelText("Değer"), "40,00 TL");
    await u.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(await screen.findByText(SURUM_CAKISMASI)).toBeInTheDocument();
    await u.click(await screen.findByRole("button", { name: "Güncel değeri yükle (sürüm 3)" }));
    expect(screen.getByLabelText("Değer")).toHaveValue("35,00 TL");
  });

  it("atıf yapan case varken silme 409 listesi; atıfsız kayıt silinir; sürüm geçmişi çekmecesi", async () => {
    const { caseler } = taslaklariKur();
    mockVerisi().caseler.find((x) => x.id === caseler[0].id)!.icerik.expected_result = "{veri:bayi.bayi2.kredi_limiti} aşıldı uyarısı";
    await oturumAc("muhendis");
    uygulama("/test-verisi");
    const u = userEvent.setup();
    const satir = () => document.querySelector('tr[data-anahtar="bayi.bayi2.kredi_limiti"]') as HTMLElement;
    await screen.findByRole("heading", { name: /bayi/ });
    expect(satir()).toHaveTextContent("1"); // kullanım
    await u.click(screen.getByRole("button", { name: "bayi.bayi2.kredi_limiti sil" }));
    await u.click(within(satir()).getByRole("button", { name: "Evet, sil" }));
    const liste = await screen.findByTestId("atif-yapan-caseler");
    // Core `kullanan[{case_id, case_ref, baslik, durum}]`: gereksinim kimliği yok, bağlantısız satır.
    expect(liste).toHaveTextContent("#1 · Taslak 1 (draft)");
    expect(screen.getByText(/1 etkin case bu test verisine atıf yapıyor/)).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "kampanya.k6_1.ad sil" }));
    const k = document.querySelector('tr[data-anahtar="kampanya.k6_1.ad"]') as HTMLElement;
    await u.click(within(k).getByRole("button", { name: "Evet, sil" }));
    await waitFor(() => expect(document.querySelector('tr[data-anahtar="kampanya.k6_1.ad"]')).toBeNull());

    await u.click(screen.getByRole("button", { name: "urun.p_001.ad sürüm geçmişi" }));
    const cekmece = await screen.findByTestId("surum-gecmisi");
    expect(await within(cekmece).findByText("oluşturuldu")).toBeInTheDocument();
    await waitFor(() => expect(within(cekmece).getByRole("heading")).toHaveFocus());
    await u.keyboard("{Escape}");
    expect(screen.queryByTestId("surum-gecmisi")).toBeNull();
  });

  it("testçi görür ama düzenleyemez; menüde Test verisi ve Otomasyon herkese görünür", async () => {
    await oturumAc("testci");
    uygulama("/test-verisi");
    await screen.findByRole("heading", { name: /bayi/ });
    expect(screen.queryByRole("button", { name: "Yeni kayıt" })).toBeNull();
    expect(screen.queryByRole("button", { name: /düzenle$/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: /sürüm geçmişi$/ }).length).toBeGreaterThan(0);
    expect(screen.getByText(/Kataloğu Analist ve Mühendis düzenler/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Test verisi/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /Otomasyon/ }).length).toBeGreaterThan(0);
  });
});

describe("Otomasyon sayfası", () => {
  it("analist otomatik kodu kapatır ve Jira tetiğini kısmi gövdeyle kaydeder; aralık doğrulanır", async () => {
    await oturumAc("analist");
    const cagrilar = izle();
    uygulama("/otomasyon");
    const u = userEvent.setup();
    const kod = await screen.findByRole("switch", { name: "Onaylanan case için kodu otomatik üret" });
    expect(kod).toBeChecked();
    await u.click(kod);
    const kodKarti = kod.closest("section") as HTMLElement;
    await u.click(within(kodKarti).getByRole("button", { name: "Kaydet" }));
    expect(await screen.findByText("Otomatik kod üretimi kapatıldı.")).toBeInTheDocument();
    expect(cagrilar.find((c) => c.method === "PUT" && c.path === "/automation-settings/otomatik_kod_uretimi")?.govde).toEqual({ acik: false });
    expect(within(kodKarti).getByText("kapalı")).toBeInTheDocument();

    const aralik = screen.getByLabelText("Sorgu aralığı (saniye)");
    const jiraKarti = aralik.closest("section") as HTMLElement;
    await u.clear(aralik);
    await u.type(aralik, "10");
    await u.click(within(jiraKarti).getByRole("button", { name: "Kaydet" }));
    expect(await within(jiraKarti).findByText("Sorgu aralığı 30–3600 saniye arasında tam sayı olmalı.")).toBeInTheDocument();
    await u.clear(aralik);
    await u.type(aralik, "120");
    const durum = screen.getByLabelText("Tetikleyen Jira durumu");
    await u.clear(durum);
    await u.type(durum, "QA Ready");
    await u.click(within(jiraKarti).getByRole("button", { name: "Kaydet" }));
    await screen.findByText("Jira tetiği ayarı kaydedildi.");
    expect(cagrilar.find((c) => c.method === "PUT" && c.path === "/automation-settings/jira_tetik")?.govde).toEqual({ durum: "QA Ready", aralik_s: 120 });
    await waitFor(() => expect(screen.getByTestId("jira-tetik-son-tur")).toHaveTextContent('"QA Ready" · her 120 sn'));
  });

  it("PO ayarları görür ama değiştiremez", async () => {
    await oturumAc("po");
    uygulama("/otomasyon");
    const kod = await screen.findByRole("switch", { name: "Onaylanan case için kodu otomatik üret" });
    expect(kod).toBeDisabled();
    expect(screen.getByLabelText("Sorgu aralığı (saniye)")).toBeDisabled();
    for (const d of screen.getAllByRole("button", { name: "Kaydet" })) expect(d).toBeDisabled();
    expect(screen.getByText(/Bu ayarları Analist ve Mühendis değiştirir/)).toBeInTheDocument();
  });
});

describe("Kod üretimi ve demo", () => {
  it("otomatik tetik rozeti ve 'test verisi değişti' uyarısı (liste + detay)", async () => {
    const s = mockVerisi().scriptler[0];
    Object.assign(s, { tetik: "otomatik", veri_degisti: true, veri_izi: { "urun.p_001.ad": 1 } });
    await oturumAc("muhendis");
    uygulama("/kod");
    expect(await screen.findByText("Onayla otomatik")).toBeInTheDocument();
    expect(screen.getByText("Test verisi değişti; yeniden üretin")).toBeInTheDocument();
  });

  it("script detayında veri değişti uyarısı üretimde kullanılan sürümü gösterir", async () => {
    const s = mockVerisi().scriptler[0];
    Object.assign(s, { tetik: "otomatik", veri_degisti: true, veri_izi: { "urun.p_001.ad": 1 } });
    await oturumAc("muhendis");
    uygulama(`/kod/${s.id}`);
    expect(await screen.findByText("Onayla otomatik")).toBeInTheDocument();
    const u = screen.getByText("Test verisi değişti; yeniden üretin").closest(".uyari-kutusu") as HTMLElement;
    expect(u).toHaveTextContent("urun.p_001.ad s1");
  });

  it("demo: story'yi QA To Do'ya taşı (presenter)", async () => {
    await oturumAc("sunucu");
    const cagrilar = izle();
    uygulama("/demo");
    const d = await screen.findByRole("button", { name: "Story'yi QA To Do'ya taşı" });
    await waitFor(() => expect((screen.getByLabelText("Story") as HTMLSelectElement).value).toMatch(/^TPD-/));
    await userEvent.click(d);
    const c = cagrilar.find((x) => x.path === "/demo/jira-status");
    expect(c?.govde).toEqual({ jira_key: (screen.getByLabelText("Story") as HTMLSelectElement).value, durum: "QA To Do" });
    expect((await screen.findAllByText(/jira-sim'de "QA To Do" durumuna taşındı/)).length).toBeGreaterThan(0);
  });
});

describe("013 uyarlayıcıları ve hata gövdesi", () => {
  it("toplu karar yanıtı: bilinmeyen durum hata, özet yoksa sayılır", () => {
    const y = topluKararUyarla({ sonuclar: [{ case_id: "a", durum: "onaylandi", otomatik_kod: { durum: "hata", neden: "onay geçerli, elle başlatın" } }, { case_id: "b", durum: "?" }] });
    expect(y.ozet).toEqual({ onaylandi: 1, atlandi: 0, hata: 1 });
    expect(y.sonuclar[0].otomatik_kod).toEqual({ durum: "hata", neden: "onay geçerli, elle başlatın", script_id: null });
  });

  it("gizli kaydın değeri sunucu gönderse de süzülür", () => {
    expect(testVerisiUyarla({ id: "1", anahtar: "x.y", gizli: true, deger: "sir", sir_adi: "S", sir_tanimli: false }).deger).toBeNull();
  });

  it("silme 409: yapılı detay mesajı ApiError'a, case listesi govde'ye taşınır", async () => {
    sahteSunucu({
      "DELETE /test-data/tv-1": {
        status: 409,
        govde: { detail: { mesaj: "Atıf yapan etkin case var", caseler: [{ id: "c1", requirement_id: "r1", jira_key: "TPD-2", sira_no: 3, title: "Giriş" }] } },
      },
    });
    const e = await istek("DELETE", "/test-data/tv-1").catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).detail).toBe("Atıf yapan etkin case var");
    expect(atifYapanlarUyarla((e as ApiError).govde)).toEqual([
      { id: "c1", case_ref: null, durum: null, requirement_id: "r1", jira_key: "TPD-2", sira_no: 3, baslik: "Giriş" },
    ]);
  });

  it("silme 409 core biçimi: {detail, kod: cakisma, kullanan[]}", async () => {
    sahteSunucu({
      "DELETE /test-data/tv-1": {
        status: 409,
        govde: { detail: "Test verisi kullanımda", kod: "cakisma", kullanan: [{ case_id: "c9", case_ref: "TPD-2 #3", baslik: "Giriş", durum: "approved" }] },
      },
    });
    const e = (await istek("DELETE", "/test-data/tv-1").catch((x: unknown) => x)) as ApiError;
    expect(e.kod).toBe("cakisma");
    expect(atifYapanlarUyarla(e.govde)).toEqual([
      { id: "c9", case_ref: "TPD-2 #3", durum: "approved", requirement_id: null, jira_key: null, sira_no: null, baslik: "Giriş" },
    ]);
  });
});

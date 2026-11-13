// İnceleme bulgularının düzeltmeleri: REPLAY/REPLAY-MISS tutarlılık kartı, son hâldeki bulgularda
// karar formu, serbest metin etiketleri, PO cevapları, case ölçümleri (REPLAY, baz değer), yayın
// rolü, örnek gereksinim ve dar ekran tabloları.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import type { Bulgu, CaseMetrikleri, GereksinimDetay as Detay } from "../api/types";
import { gereksinimDetayUyarla } from "../api/uyum";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { BulguKarti } from "../components/BulguKarti";
import { goruntulenenleriSifirla } from "../components/CaseKarti";
import { adimAdi } from "../lib/akis";
import { ORNEK_SERBEST_GEREKSINIM } from "../lib/ornekGereksinim";
import { oturumAc, sar } from "../test/yardimci";
import { aiModu, caseBazi, caseKazanci, caseOzeti } from "./CaseReview";
import { bosBulguMetni } from "./GereksinimDetay";

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

const gereksinim = (id: string) => mockVerisi().gereksinimler.find((g) => g.id === id)! as Detay;

beforeEach(() => goruntulenenleriSifirla());

describe("tutarlılık kartı: REPLAY / REPLAY-MISS ve dürüst boş durum", () => {
  it("REPLAY-MISS koşusunda bulgular elendiyse 'tutarlı' denmez, rozet gösterilir", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-ft-1");
    g.son_kontrol = { mode: "replay_miss", bulgu: 3, dogrulanan: 0, elenen: 3, zaman: null };
    for (const b of mockVerisi().bulgular) if (b.requirement_id === "req-ft-1") b.durum = "discarded";
    uygulama("/gereksinimler/req-ft-1");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    expect(await within(kart).findByText("REPLAY-MISS")).toBeInTheDocument();
    expect(within(kart).getByTestId("bulgu-bos")).toHaveTextContent(
      "Gösterilecek doğrulanmış bulgu yok (REPLAY-MISS; 3 bulgu kanıtı doğrulanamadığı için elendi) — tutarlılık doğrulanmadı.",
    );
    expect(within(kart).queryByText(/doküman kod ve veriyle tutarlı/)).toBeNull();
  });

  it("temiz REPLAY koşusu: REPLAY rozeti ve 'Bulgu yok' birlikte görünür", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-ft-1");
    g.son_kontrol = { mode: "replay", bulgu: 0, dogrulanan: 0, elenen: 0, zaman: null };
    mockVerisi().bulgular.splice(0, mockVerisi().bulgular.length, ...mockVerisi().bulgular.filter((b) => b.requirement_id !== "req-ft-1"));
    uygulama("/gereksinimler/req-ft-1");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    expect(await within(kart).findByText("Bulgu yok: doküman kod ve veriyle tutarlı.")).toBeInTheDocument();
    expect(within(kart).getByText("REPLAY")).toBeInTheDocument();
  });

  it("boş durum metni: çalıştırılmadı / doğrulanıyor / elenen / REPLAY-MISS / tutarlı", () => {
    const temel = { kontrol_turu: 1, son_kontrol: null } as unknown as Detay;
    expect(bosBulguMetni({ ...temel, kontrol_turu: 0 }, 0, 0)).toBe("Denetim henüz çalıştırılmadı.");
    expect(bosBulguMetni(temel, 0, 2)).toMatch(/doğrulanıyor/);
    expect(bosBulguMetni(temel, 2, 0)).toBe(
      "Gösterilecek doğrulanmış bulgu yok (2 bulgu kanıtı doğrulanamadığı için elendi) — tutarlılık doğrulanmadı.",
    );
    const miss = { ...temel, son_kontrol: { mode: "replay_miss" as const, bulgu: 0, dogrulanan: 0, elenen: 0, zaman: null } };
    expect(bosBulguMetni(miss, 0, 0)).toBe("Gösterilecek doğrulanmış bulgu yok (REPLAY-MISS) — tutarlılık doğrulanmadı.");
    // Önceki turda elenen bulgu, son temiz koşuyu "doğrulanmadı" yapmaz (son_kontrol esas).
    const temiz = { ...temel, son_kontrol: { mode: "replay" as const, bulgu: 0, dogrulanan: 0, elenen: 0, zaman: null } };
    expect(bosBulguMetni(temiz, 3, 0)).toBe("Bulgu yok: doküman kod ve veriyle tutarlı.");
  });

  it("çekirdek şekli: son_kontrol modu ve sayıları taşınır; null kalır", () => {
    const d = gereksinimDetayUyarla({
      id: "r1",
      durum: "pending_po",
      son_kontrol: { id: "k1", sira: 1, mode: "replay_miss", bulgu: 3, dogrulanan: 0, elenen: 3, zaman: "2026-10-30T10:00:00Z" },
    });
    expect(d.son_kontrol).toEqual({ mode: "replay_miss", bulgu: 3, dogrulanan: 0, elenen: 3, zaman: "2026-10-30T10:00:00Z" });
    expect(d.elenen_bulgu).toBe(3);
    expect(gereksinimDetayUyarla({ id: "r2", son_kontrol: null }).son_kontrol).toBeNull();
    expect(gereksinimDetayUyarla({ id: "r3" }).son_kontrol).toBeUndefined();
  });
});

describe("tutarlılık kartı: doküman son hâle geçtikten sonra", () => {
  it("işlevsiz düzeltme düğmesi yerine güncel durum ve 'karar gerekmez' notu gösterilir", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-3");
    g.durum = "pending_po";
    g.kontrol_turu = 2;
    uygulama("/gereksinimler/req-tpd-3");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    expect(await within(kart).findByTestId("son-hal-durumu")).toHaveTextContent("✓ Doküman son hâl · PO teyidi bekliyor");
    expect(within(kart).getByTestId("son-hal-notu")).toHaveTextContent("karar gerekmez");
    // PO teyidi beklemek uyarı değil sıradaki adım: çip uyarı tonunda değil.
    expect(within(kart).getByTestId("son-hal-durumu").querySelector(".cip-uyari")).toBeNull();
    expect(within(kart).queryByRole("button", { name: /Düzeltmeleri Jira'ya yaz|Son hâl olarak onayla/ })).toBeNull();
  });

  it("findings_open iken düğme yerinde, son hâl durumu yok", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-3");
    g.durum = "findings_open";
    uygulama("/gereksinimler/req-tpd-3");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    expect(await within(kart).findByRole("button", { name: /Düzeltmeleri Jira'ya yaz|Son hâl olarak onayla/ })).toBeInTheDocument();
    expect(within(kart).queryByTestId("son-hal-durumu")).toBeNull();
  });
});

describe("PO kartı: insan kapısı metni", () => {
  it("onay varsa ve içerik değişmediyse kapı geçildi yazar", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-3");
    g.durum = "po_approved";
    g.po = { ...g.po, durum: "approved", onaylayan: "po@sim.local", kanal: "jira", onaylanan_hash: g.icerik_hash };
    uygulama("/gereksinimler/req-tpd-3");
    expect(await screen.findByTestId("po-kapisi")).toHaveTextContent("✓ İnsan kapısı geçildi");
  });

  it("onay yokken kural metni kalır", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-3");
    g.po = { ...g.po, durum: "pending", kanal: "jira" };
    uygulama("/gereksinimler/req-tpd-3");
    expect(await screen.findByTestId("po-kapisi")).toHaveTextContent("PO teyidi olmadan case üretimine geçilmez");
  });
});

describe("bulgu kararı yalnızca findings_open iken", () => {
  const uyari = (): Bulgu => ({ ...mockVerisi().bulgular.find((b) => b.id === "fnd-8")! });

  it("son hâldeki gereksinimde açık uyarı salt okunur; form ve 'Kararı kaydet' yok", async () => {
    await oturumAc("analist");
    sar(<BulguKarti bulgu={uyari()} gereksinimDurumu="done" guncellendi={() => undefined} />);
    expect(await screen.findByTestId("bulgu-salt-okunur")).toHaveTextContent("Uyarı — karar gerekmiyor; doküman son hâl");
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button", { name: "Kararı kaydet" })).toBeNull();
  });

  it("findings_open iken karar formu açık", async () => {
    await oturumAc("analist");
    sar(<BulguKarti bulgu={uyari()} gereksinimDurumu="findings_open" guncellendi={() => undefined} />);
    expect(await screen.findByRole("button", { name: "Kararı kaydet" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("detay ekranı (TPD-3, PO teyidinde): açık uyarıda karar formu gösterilmez", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-3");
    expect(await screen.findByTestId("bulgu-salt-okunur")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kararı kaydet" })).toBeNull();
  });

  it("listede karar beklemeyen gereksinimin açık bulgusu 'uyarı' olarak, bulgu sayısı olarak değil gösterilir", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-3");
    uygulama("/gereksinimler");
    const satir = (await screen.findByRole("link", { name: g.baslik })).closest("tr")!;
    const hucre = within(satir).getByText("1 uyarı");
    expect(hucre.getAttribute("title")).toMatch(/kararı beklemiyor/);
  });
});

describe("serbest metin etiketleri", () => {
  const cozulmus = (): Bulgu => ({ ...mockVerisi().bulgular.find((b) => b.id === "fnd-2")! }); // fix_doc, resolved

  it("fix_doc çözüldüyse serbest metinde 'Dokümana uygulandı', Jira'da 'Jira'ya yazıldı'", async () => {
    await oturumAc("analist");
    const { unmount } = sar(<BulguKarti bulgu={cozulmus()} kaynak="free_text" guncellendi={() => undefined} />);
    expect(screen.getByText("Dokümana uygulandı")).toBeInTheDocument();
    expect(screen.queryByText("Jira'ya yazıldı")).toBeNull();
    unmount();
    sar(<BulguKarti bulgu={cozulmus()} kaynak="jira" guncellendi={() => undefined} />);
    expect(screen.getByText("Jira'ya yazıldı")).toBeInTheDocument();
  });

  it("akışın 1. adımı serbest metinde 'Serbest metin', Jira'da 'Jira'", async () => {
    expect(adimAdi(1, "free_text")).toBe("Serbest metin");
    expect(adimAdi(1, "jira")).toBe("Jira");
    expect(adimAdi(2, "free_text")).toBe("Ön inceleme");
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    const akis = await screen.findByRole("navigation", { name: /14 adımlı akış/ });
    expect(within(akis).getByText("Serbest metin")).toBeInTheDocument();
    expect(within(akis).queryByText("Jira")).toBeNull();
  });

  it("liste kartı 'Gereksinim listesi' adını taşır", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler");
    expect(await screen.findByRole("heading", { name: "Gereksinim listesi" })).toBeInTheDocument();
  });
});

describe("PO cevapları", () => {
  it("çekirdek şekli: po_cevaplari yazar/metin/zaman ve Jira yorum adresiyle eşlenir", () => {
    const d = gereksinimDetayUyarla({
      id: "r1",
      jira_url: "http://127.0.0.1:8090/browse/TPD-1",
      po_cevaplari: [{ id: "10031", yazar: "po@sim.local", metin: "Q1: kampanyalı siparişte minimum aranmaz. Onaylıyorum.", zaman: "2026-10-30T10:00:00Z" }, { id: "x", metin: "  " }],
    });
    expect(d.po_cevaplari).toEqual([
      {
        id: "10031",
        yazar: "po@sim.local",
        metin: "Q1: kampanyalı siparişte minimum aranmaz. Onaylıyorum.",
        zaman: "2026-10-30T10:00:00Z",
        url: "http://127.0.0.1:8090/browse/TPD-1?focusedCommentId=10031#comment-10031",
      },
    ]);
  });

  it("PO onayladıysa sorular 'Cevap bekleniyor' demez; PO'nun Jira cevabı altta görünür", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-1");
    for (const s of g.on_inceleme!.questions) s.cevap = null; // çekirdek soru bazında cevap eşlemez
    g.po_cevaplari = [
      { id: "10031", yazar: "po@sim.local", metin: "Q1: kampanyalı siparişte minimum aranmaz. Onaylıyorum.", zaman: "2026-10-30T10:00:00Z", url: "http://127.0.0.1:8090/browse/TPD-1" },
    ];
    uygulama("/gereksinimler/req-tpd-1");
    const cevaplar = await screen.findByTestId("po-cevaplari");
    expect(within(cevaplar).getByText(/minimum aranmaz\. Onaylıyorum\./)).toBeInTheDocument();
    expect(within(cevaplar).getByText("po@sim.local")).toBeInTheDocument();
    expect(within(cevaplar).getByRole("link", { name: /Jira yorumu #10031/ })).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-1");
    expect(screen.queryByText("Cevap bekleniyor")).toBeNull();
    expect(screen.getAllByText("PO Jira'da yanıtladı (aşağıda)")).toHaveLength(g.on_inceleme!.questions.length);
  });

  it("PO henüz onaylamadıysa 'Cevap bekleniyor' kalır", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-3");
    expect((await screen.findAllByText("Cevap bekleniyor")).length).toBeGreaterThan(0);
  });
});

const metrik = (ek: Partial<CaseMetrikleri> = {}): CaseMetrikleri => ({
  requirement_id: "req-tpd-1",
  uretilen: 5,
  karar_verilen: 0,
  bekleyen: 5,
  kabul: 0,
  kabul_orani: 0,
  kabul_hedefi: 0.7,
  ilk_kararlar: {},
  ret_nedenleri: {},
  ai_sure_ms: 0,
  review_sure_ms: 0,
  ort_review_sure_ms: null,
  maliyet_usd: 0,
  ai_cagri_modlari: { replay: 1 },
  ...ek,
});

describe("case ölçümleri", () => {
  it("hiç karar yokken kabul oranı '—' ve 'henüz karar yok'; hedefin altında denmez", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue(metrik());
    uygulama("/gereksinimler/req-tpd-1/caseler");
    expect(await screen.findByText(/henüz karar yok/)).toBeInTheDocument();
    expect(screen.queryByText(/hedefin altında/)).toBeNull();
    expect(caseOzeti([], metrik()).kabulOrani).toBeNull();
    expect(caseOzeti([], metrik({ karar_verilen: 2, kabul_orani: 0.4 })).kabulOrani).toBe(0.4);
  });

  it("REPLAY üretiminde AI süresi/maliyeti '0 ms / $0,00' değil 'REPLAY — ölçülmedi'", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue(metrik({ karar_verilen: 5, kabul: 4, kabul_orani: 0.8, review_sure_ms: 369_000, ort_review_sure_ms: 73_800 }));
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const ozet = await screen.findByRole("region", { name: "Özet" });
    expect(await within(ozet).findAllByText("REPLAY — ölçülmedi")).toHaveLength(2);
    expect(within(ozet).queryByText("0 ms")).toBeNull();
    expect(within(ozet).queryByText("$0,00")).toBeNull();
    expect(within(ozet).getAllByText("6 dk 09 sn").length).toBeGreaterThan(0);
    expect(within(ozet).getByText(/yalnız review; AI süresi REPLAY'de ölçülmedi/)).toBeInTheDocument();
    // Case kartlarında da (case mode=replay)
    expect(screen.getAllByText(/AI: REPLAY — ölçülmedi/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^AI 0 ms/)).toBeNull();
  });

  it("ÖLÇÜLMÜŞ manuel baz değer yan yana gösterilir ve kazanç hesaplanır (kaynak: ölçüm, giren, not)", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue(
      metrik({
        karar_verilen: 5,
        bekleyen: 0,
        review_sure_ms: 6 * 60_000,
        ort_review_sure_ms: 72_000,
        manuel_baz_ms: 30 * 60_000,
        manuel_baz_kaynagi: "olcum",
        manuel_baz: { deger_s: 1800, deger_ms: 1_800_000, kaynak: "olcum", giren: "analist", zaman: "2026-10-30T10:00:00Z", not: "F0 kronometre" },
      }),
    );
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const ozet = await screen.findByRole("region", { name: "Özet" });
    expect(await within(ozet).findByText("30 dk 00 sn")).toBeInTheDocument();
    expect(within(ozet).getByTestId("case-baz")).toHaveTextContent("Ölçüm");
    expect(within(ozet).getByTestId("case-baz-aciklama")).toHaveTextContent("ölçüm · Cengizhan Gunaydin · Analist · F0 kronometre");
    // REPLAY: AI süresi ölçülmedi → yalnız review süresiyle oran (1 − 6/30 = %80) verimlilik iddiası
    // değildir; hedef %30–50'ye karşı gösterilmez (core `kazanca_girer`, Kontrol Kulesi ile aynı kural).
    expect(within(ozet).getByTestId("case-kazanc")).toHaveTextContent("—");
    expect(within(ozet).queryByText("%80")).toBeNull();
    expect(within(ozet).queryByText(/hedef %30–50/)).toBeNull();
    expect(within(ozet).getByText(/REPLAY: AI süresi ölçülmedi — kazanç hesaplanmaz \(verimlilik iddiası değil\)/)).toBeInTheDocument();
    expect(within(ozet).queryByText(/F0 ölçümü/)).toBeNull();
  });

  it("VARSAYILAN baz değer (TP_MANUAL_BASELINE_S) gösterilir ama 'Varsayılan' etiketli ve kazanç hesaplanmaz", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue(
      metrik({
        karar_verilen: 5,
        bekleyen: 0,
        review_sure_ms: 6 * 60_000,
        ort_review_sure_ms: 72_000,
        manuel_baz_ms: 2_700_000,
        manuel_baz_kaynagi: "varsayilan",
        manuel_baz: { deger_s: 2700, deger_ms: 2_700_000, kaynak: "varsayilan", giren: null, zaman: null, not: "TP_MANUAL_BASELINE_S" },
      }),
    );
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const ozet = await screen.findByRole("region", { name: "Özet" });
    // Ölçüm verisi özet kartından sonra gelebilir (yük altında): metin gelene dek beklenir.
    await waitFor(() => expect(within(ozet).getByTestId("case-baz")).toHaveTextContent("45 dk 00 sn"));
    expect(within(ozet).getByTestId("case-baz")).toHaveTextContent("Varsayılan");
    expect(within(ozet).getByTestId("case-baz-aciklama")).toHaveTextContent("kazanca girmez");
    expect(within(ozet).getByTestId("case-kazanc")).toHaveTextContent("—");
    expect(within(ozet).queryByText(/hedef %30–50/)).toBeNull();
    expect(within(ozet).queryByText(/F0 ölçümü/)).toBeNull();
    expect(within(ozet).getByText(/varsayılan baz değer kazanca girmez/)).toBeInTheDocument();
  });

  it("ölçülmüş baz olsa da 5 sn altı (betik/API) review süresiyle kazanç hesaplanmaz; review 'ölçülmedi'", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue(
      metrik({ karar_verilen: 5, bekleyen: 0, review_sure_ms: 45, ort_review_sure_ms: 9, manuel_baz_ms: 2_700_000, manuel_baz_kaynagi: "olcum" }),
    );
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const ozet = await screen.findByRole("region", { name: "Özet" });
    expect(await within(ozet).findByTestId("case-kazanc")).toHaveTextContent("—");
    // "—" yükleme sırasında da görünür; metrik gelene kadar bekle (yük altında yarış).
    expect(await within(ozet).findByText(/5 sn altı \(betik\/API onayı\) — kazanç hesaplanmaz/)).toBeInTheDocument();
    expect(within(ozet).getByText(/betik\/API onayı, insan review'u sayılmaz/)).toBeInTheDocument();
  });

  it("caseBazi / caseKazanci: kaynak esastır; ortam (derleme) yedeği yok; aiModu canlı/replay/karışık", () => {
    // Kaynak bildirmeyen eski core değeri ölçüm sayılmaz.
    expect(caseBazi(metrik({ manuel_baz_ms: 1000 }))).toMatchObject({ ms: 1000, kaynak: "varsayilan" });
    expect(caseBazi(metrik({ manuel_baz_ms: 1000, manuel_baz_kaynagi: "olcum" }))).toMatchObject({ ms: 1000, kaynak: "olcum" });
    expect(caseBazi(metrik({ manuel_baz: { deger_s: 60, kaynak: "varsayilan" }, manuel_baz_ms: 60_000, manuel_baz_kaynagi: "olcum" }))).toMatchObject({ ms: 60_000, kaynak: "varsayilan" });
    expect(caseBazi(metrik({ manuel_baz_ms: null, manuel_baz_kaynagi: null }))).toMatchObject({ ms: null, kaynak: "olculmedi" });
    expect(caseBazi(metrik())).toMatchObject({ ms: null, kaynak: "olculmedi" });
    expect(caseBazi(null)).toMatchObject({ ms: null, kaynak: "olculmedi" });
    const olcum = caseBazi(metrik({ manuel_baz_ms: 1_800_000, manuel_baz_kaynagi: "olcum" }));
    const vars = caseBazi(metrik({ manuel_baz_ms: 1_800_000, manuel_baz_kaynagi: "varsayilan" }));
    const ozet = { aiSure: 0, reviewSure: 360_000, olculenReview: 5 };
    // REPLAY (AI süresi ölçülmedi): ölçülmüş baz + ≥ 5 sn review olsa da oran yok.
    expect(caseKazanci(olcum, ozet, true)).toMatchObject({ oran: null, reviewOlculdu: true, neden: expect.stringMatching(/^REPLAY: AI süresi ölçülmedi/) });
    expect(caseKazanci(vars, ozet, true).oran).toBeNull();
    expect(caseKazanci(olcum, { ...ozet, reviewSure: 4_999 }, true).oran).toBeNull();
    expect(caseKazanci(olcum, { ...ozet, reviewSure: 4_999 }, true).reviewOlculdu).toBe(false);
    expect(caseKazanci(olcum, { ...ozet, olculenReview: 0 }, true).oran).toBeNull();
    // Canlı: AI + review
    expect(caseKazanci(olcum, { aiSure: 180_000, reviewSure: 360_000, olculenReview: 5 }, false).oran).toBeCloseTo(0.7);
    expect(aiModu([], metrik({ ai_cagri_modlari: { replay: 2 } }))).toBe("replay");
    expect(aiModu([], metrik({ ai_cagri_modlari: { replay: 1, replay_miss: 1 } }))).toBe("replay_miss");
    expect(aiModu([], metrik({ ai_cagri_modlari: { live: 3 } }))).toBe("live");
    expect(aiModu([], metrik({ ai_cagri_modlari: { live: 3, replay: 1 } }))).toBe("karisik");
    expect(aiModu([], metrik({ ai_cagri_modlari: {} }))).toBeNull();
  });

  it("canlı üretimde ölçülen süre ve maliyet gösterilir", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue(metrik({ ai_cagri_modlari: { live: 1 }, ai_sure_ms: 6_800, maliyet_usd: 0.42 }));
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const ozet = await screen.findByRole("region", { name: "Özet" });
    expect((await within(ozet).findAllByText("6,8 sn")).length).toBeGreaterThan(0);
    expect(within(ozet).queryByText("REPLAY — ölçülmedi")).toBeNull();
  });
});

describe("yayın rolü", () => {
  it("Analist case review'dan yayın önizlemesine gider (publish.preview, salt okunur)", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-1/caseler");
    expect(await screen.findByRole("link", { name: "Yayın önizleme" })).toBeInTheDocument();
  });

  it("PO yayın önizlemesini salt okunur görür: yayınla düğmesi pasif ve nedeni Testçi", async () => {
    await oturumAc("po");
    uygulama("/gereksinimler/req-tpd-1/yayin");
    expect(await screen.findByText("Salt okunur önizleme")).toBeInTheDocument();
    const d = await screen.findByRole("button", { name: /Seçilenleri yayınla/ });
    expect(d).toBeDisabled();
    expect(d).toHaveAccessibleDescription("Bu işlem için gereken rol: Testçi");
  });

  it("Developer yayın ekranına gelirse önizleme istenmez; bilgi notu, 'Tekrar dene' yok", async () => {
    await oturumAc("gelistirici");
    const casus = vi.spyOn(api, "yayinOnizleme");
    uygulama("/gereksinimler/req-tpd-1/yayin");
    expect(await screen.findByText("Yayın önizleme bu rolde görünmez")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tekrar dene" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(casus).not.toHaveBeenCalled();
  });

  it("sunucu 403 dönerse bilgi notu gösterilir, yeniden deneme önerilmez", async () => {
    await oturumAc("testci");
    vi.spyOn(api, "yayinOnizleme").mockRejectedValue(new ApiError(403, "Bu işlem için yetkiniz yok."));
    uygulama("/gereksinimler/req-tpd-1/yayin");
    expect(await screen.findByText("Bu işlem için yetkiniz yok.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tekrar dene" })).toBeNull();
  });
});

describe("serbest metin örneği", () => {
  it("örnek metin REPLAY golden girdi beyanıyla birebir aynı", () => {
    const k = JSON.parse(readFileSync(resolve(__dirname, "../api/mock/golden/kaynaklar.json"), "utf8")) as {
      serbest_girdi: { acceptance_criteria: string[]; contains: string[] };
    };
    expect(ORNEK_SERBEST_GEREKSINIM.ac.map((a, i) => `AC${i + 1}: ${a}`)).toEqual(k.serbest_girdi.acceptance_criteria);
    expect(k.serbest_girdi.contains).toContain(ORNEK_SERBEST_GEREKSINIM.aciklama);
  });

  it("'Örnek gereksinimi doldur' formu doldurur; elle düzenleme açık kalır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const casus = vi.spyOn(api, "serbestMetin");
    uygulama("/gereksinimler");
    await u.click(await screen.findByRole("button", { name: "Serbest metin gereksinim" }));
    await u.click(screen.getByRole("button", { name: "Örnek gereksinimi doldur" }));
    expect(screen.getByLabelText("Başlık")).toHaveValue("Sepetten ürün çıkarma");
    expect(screen.getByLabelText("Açıklama")).toHaveValue(ORNEK_SERBEST_GEREKSINIM.aciklama);
    expect(screen.getByLabelText("AC3")).toHaveValue(ORNEK_SERBEST_GEREKSINIM.ac[2]);
    await u.clear(screen.getByLabelText("AC3"));
    await u.type(screen.getByLabelText("AC3"), "Elle girilen metin");
    await u.click(screen.getByRole("button", { name: "Gereksinimi oluştur" }));
    expect(casus).toHaveBeenCalledWith({
      baslik: "Sepetten ürün çıkarma",
      aciklama: ORNEK_SERBEST_GEREKSINIM.aciklama,
      ac: [ORNEK_SERBEST_GEREKSINIM.ac[0], ORNEK_SERBEST_GEREKSINIM.ac[1], "Elle girilen metin"],
    });
  });
});

describe("dar ekran tabloları", () => {
  it("gereksinim ve adım tablolarının her hücresi kart görünümü için etiket taşır", async () => {
    await oturumAc("analist");
    const { unmount } = uygulama("/gereksinimler");
    const tablo = (await screen.findByRole("region", { name: "Gereksinimler tablosu" })).querySelector("table")!;
    expect(tablo).toHaveClass("tablo-yigin");
    for (const td of tablo.querySelectorAll("tbody td")) expect(td.getAttribute("data-etiket")).toBeTruthy();
    unmount();
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const adim = (await screen.findAllByRole("region", { name: /^Adımlar:/ }))[0].querySelector("table")!;
    expect(adim).toHaveClass("tablo-yigin");
    expect([...adim.querySelectorAll("tbody tr:first-child td")].map((td) => td.getAttribute("data-etiket"))).toEqual(["#", "Adım", "Veri", "Beklenen"]);
  });

  it("stil: 640 px altında yığın görünüm kuralı var", () => {
    const css = readFileSync(resolve(__dirname, "../styles.css"), "utf8");
    expect(css).toMatch(/@media \(max-width: 640px\) \{\s*\.tablo-yigin thead/);
    expect(css).toMatch(/\.tablo-yigin td\[data-etiket\]::before \{\s*content: attr\(data-etiket\)/);
  });
});

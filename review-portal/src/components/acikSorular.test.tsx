// Açık soru döngüsü (specs/011 K16; D6): "Açık soruları PO'ya gönder" (analist, Jira story'si
// gerekir, aynı soru iki kez gitmez), PO yanıtının soruya bağlanması, case kartında durum/yanıt,
// düzelt önerisi ve düzeltme formunda yanıt metni; core yanıt biçiminin uyarlanması.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { ORNEK_PO_YANITI, STORY_YOK_ENGELI } from "../api/mock/acikSorular";
import { V3_GEREKSINIM_ID } from "../api/mock/caseV3";
import { mockVerisi } from "../api/mock/handlers";
import { caseUyarla } from "../api/uyum";
import { oturumAc, sar } from "../test/yardimci";
import { AcikSorularPaneli } from "./AcikSorular";
import { CaseKarti } from "./CaseKarti";

/** Örnek v3 gereksinimi serbest metindir; döngü Jira story'si ister. */
function jiraStorysiVer(anahtar = "TPD-9") {
  mockVerisi().gereksinimler.find((g) => g.id === V3_GEREKSINIM_ID)!.jira_key = anahtar;
}

const engelliCase = async () => (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.readiness === "blocked")!;

describe("açık soru uçları (örnek veri, core biçimi)", () => {
  it("gönderim → yanıt → case alanları; aynı soru iki kez gönderilmez", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    let d = await api.acikSorular(V3_GEREKSINIM_ID);
    expect(d.gonderilebilir).toBe(true);
    const soru = d.sorular.find((s) => s.tur === "soru")!;
    expect(soru).toMatchObject({ etiket: null, kaynak_id: "Q1", durum: "gonderilmedi", yanit: null });
    expect(soru.bekleyen_caseler.map((c) => c.readiness)).toEqual(["blocked"]);

    d = await api.acikSorulariGonder(V3_GEREKSINIM_ID);
    expect(d.sorular.find((s) => s.tur === "soru")).toMatchObject({ etiket: "CQ1", durum: "gonderildi" });
    expect(d.sorular.find((s) => s.tur === "varsayim")!.durum).toBe("gonderilmedi");
    await expect(api.acikSorulariGonder(V3_GEREKSINIM_ID)).rejects.toMatchObject({ status: 409 });
    d = await api.acikSorulariGonder(V3_GEREKSINIM_ID, true);
    expect(d.sorular.find((s) => s.tur === "varsayim")!.etiket).toBe("CA1");

    d = await api.acikSoruYanitlariniOku(V3_GEREKSINIM_ID);
    const yanitli = d.sorular.find((s) => s.tur === "soru")!;
    expect(yanitli.durum).toBe("yanitlandi");
    expect(yanitli.yanit?.metin).toBe(ORNEK_PO_YANITI);
    expect(yanitli.oneri?.eylem).toBe("duzelt_veya_yeniden_uret");

    const c = await engelliCase();
    expect(c.acik_sorular?.[0]).toMatchObject({ id: "Q1", po_etiketi: "CQ1", po_durumu: "yanitlandi" });
    expect(c.acik_sorular?.[0].po_yaniti?.metin).toBe(ORNEK_PO_YANITI);
    expect(c.po_yanit_onerisi?.etiketler).toEqual(["CQ1"]);
    expect(mockVerisi().denetim.map((x) => x.eylem)).toEqual(expect.arrayContaining(["acik_soru.gonderildi", "acik_soru.yanitlandi"]));
  });

  it("Jira story'si yoksa gönderilemez; analist dışı rol gönderemez", async () => {
    await oturumAc("analist");
    const d = await api.acikSorular(V3_GEREKSINIM_ID);
    expect(d.gonderilebilir).toBe(false);
    expect(d.gonderim_engeli).toBe(STORY_YOK_ENGELI);
    await expect(api.acikSorulariGonder(V3_GEREKSINIM_ID)).rejects.toBeInstanceOf(ApiError);
    jiraStorysiVer();
    await oturumAc("testci");
    await expect(api.acikSorulariGonder(V3_GEREKSINIM_ID)).rejects.toMatchObject({ status: 403 });
  });

  it("core `po_sorulari` atıf kayıtlarına katılır; alan yoksa eklenmez", () => {
    const ham = {
      id: "c1",
      icerik: { title: "x", readiness: "blocked", open_question_refs: ["Q1"] },
      acik_sorular: [{ id: "Q1", question: "Soru?", owner: "PO" }],
      varsayimlar: [{ id: "A1", statement: "V", owner: "" }],
      po_sorulari: {
        Q1: { tur: "soru", po_etiketi: "CQ1", po_durumu: "yanitlandi", po_yaniti: { metin: "5 deneme", yazar: "PO", zaman: "2026-11-12T10:00:00Z" } },
      },
      po_yanit_onerisi: { eylem: "duzelt_veya_yeniden_uret", etiketler: ["CQ1"], mesaj: "m" },
    };
    const c = caseUyarla(ham);
    expect(c.acik_sorular).toEqual([
      { id: "Q1", question: "Soru?", owner: "PO", po_etiketi: "CQ1", po_durumu: "yanitlandi", po_yaniti: { metin: "5 deneme", yazar: "PO", zaman: "2026-11-12T10:00:00Z" } },
    ]);
    expect(c.varsayimlar).toEqual([{ id: "A1", statement: "V", owner: "" }]);
    expect(c.po_yanit_onerisi?.etiketler).toEqual(["CQ1"]);
    expect(caseUyarla({ id: "c2", icerik: { title: "y" } }).po_yanit_onerisi).toBeUndefined();
  });
});

describe("AcikSorularPaneli", () => {
  it("analist gönderir, yanıtları kontrol eder; durum ve yanıt metni görünür", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    const user = userEvent.setup();
    sar(<AcikSorularPaneli requirementId={V3_GEREKSINIM_ID} />);
    const panel = await screen.findByRole("region", { name: "Açık sorular ve PO yanıtları" });
    expect(await within(panel).findAllByText("PO'ya gönderilmedi")).not.toHaveLength(0);
    await user.click(within(panel).getByRole("button", { name: "Açık soruları PO'ya gönder" }));
    expect(await within(panel).findByText("PO yanıtı bekleniyor")).toBeInTheDocument();
    expect(within(panel).getByText("CQ1")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Yanıtları kontrol et" }));
    expect(await within(panel).findByText("Yanıtlandı")).toBeInTheDocument();
    expect(within(panel).getByTestId("po-yaniti")).toHaveTextContent(ORNEK_PO_YANITI);
    expect(within(panel).getByTestId("acik-soru-onerisi")).toBeInTheDocument();
  });

  it("Jira story'si yoksa düğme kapalı ve nedeni görünür", async () => {
    await oturumAc("analist");
    sar(<AcikSorularPaneli requirementId={V3_GEREKSINIM_ID} />);
    const dugme = await screen.findByRole("button", { name: "Açık soruları PO'ya gönder" });
    expect(dugme).toBeDisabled();
    // B14: neden hangi düğmeye ait olduğunu söyler.
    expect(screen.getByText(`Gönderim: ${STORY_YOK_ENGELI}`)).toBeInTheDocument();
    expect(screen.getByText("Yanıt kontrolü: yanıt bekleyen soru yok.")).toBeInTheDocument();
  });
});

describe("CaseKarti: PO yanıtı", () => {
  it("soru bloğunda durum + yanıt, öneri kutusu; düzeltme formunda yanıt kaynağı", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    await api.acikSorulariGonder(V3_GEREKSINIM_ID);
    let c = await engelliCase();
    sar(<CaseKarti tc={c} guncellendi={() => undefined} />);
    // B7: atıf satırında PO'nun gördüğü kimlik (CQ1), rozet yalnız durumu söyler.
    const blok = within(screen.getByTestId("case-acik-sorular"));
    expect(blok.getByTestId("atif-kimlik")).toHaveTextContent(/^CQ1/);
    expect(blok.getByTestId("atif-kimlik")).toHaveAttribute("title", "Üretimdeki kimlik: Q1");
    expect(blok.getByText("PO yanıtı bekleniyor")).toBeInTheDocument();
    expect(screen.queryByTestId("po-yanit-onerisi")).not.toBeInTheDocument();

    await api.acikSoruYanitlariniOku(V3_GEREKSINIM_ID);
    c = await engelliCase();
    sar(<CaseKarti tc={c} guncellendi={() => undefined} />);
    const bloklar = screen.getAllByTestId("case-acik-sorular");
    const son = bloklar[bloklar.length - 1];
    expect(within(son).getByText("Yanıtlandı")).toBeInTheDocument();
    expect(within(son).getByTestId("po-yaniti")).toHaveTextContent(ORNEK_PO_YANITI);
    // B3: yanıt sonrası tek mesaj — öneri kutusu ayrıca çizilmez (yönlendirme kutusu söyler).
    expect(screen.queryAllByTestId("po-yanit-onerisi")).toHaveLength(0);

    const user = userEvent.setup();
    const dugmeler = screen.getAllByRole("button", { name: "Düzelt" });
    await user.click(dugmeler[dugmeler.length - 1]);
    await waitFor(() => expect(screen.getByTestId("duzeltme-kaynaklari")).toHaveTextContent(ORNEK_PO_YANITI));
  });
});

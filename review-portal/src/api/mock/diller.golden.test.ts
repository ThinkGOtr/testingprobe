// EKR-E1/E3 mock sadakati: örnek arka ucun web + Java, C# ve Python çıktısı gerçek şablon golden'larıyla
// (core/tests/unit/features/codegen/golden/) hash satırları dışında birebir aynıdır. Golden'lar Docker
// derleme bağlamında yoktur; D2 biçimi (C# `TPD1WebC2_…Tests.cs`) gelmeden önce de atlanır → skipIf.
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { csharpCiktisi, javaAdimlari, javaWebCiktisi, pythonCiktisi } from "./diller";
import type { AjanAdimi } from "../types";
const G = resolve(__dirname, "../../../../core/tests/unit/features/codegen/golden") + "/";
const VAR = existsSync(G + "TPD1WebC2_3f9b1c2eTests.cs");
const a = (step_id: string, po: string, method: string, args: unknown[]) => ({ sira: 0, step_id, arac: "x", aciklama: "x", po, method, args, verified: true }) as unknown as AjanAdimi;
const adimlar = [a("S1","LoginPage","goto",[]),a("S2","LoginPage","login",["bayi1","Demo123!"]),a("S3","CatalogPage","addToCart",["P-001",7]),a("S4","CatalogPage","openCart",[]),
 a("S4","CartPage","expectLineQuantity",["P-001",7]),a("S4","CartPage","expectFreeQuantity",["P-001",1]),a("S4","CartPage","expectSubtotal",["175,00 TL"]),a("S4","CartPage","expectDiscount",["25,00 TL"]),a("S4","CartPage","expectTotal",["150,00 TL"])];
const g = { story: "TPD-1", siraNo: 2, kisa: "3f9b1c2e", caseId: "3f9b1c2e-0000-5000-8000-0000000000c2", baslik: "7 adet kampanyalı üründe 1 adet bedava verilir", adimlar,
  caseAdimlari: [{id:"S1",action:"Giriş sayfasını aç"},{id:"S2",action:"Bayi kullanıcısıyla giriş yap"},{id:"S3",action:"\"Portakal Gazozu 1L\" (P-001) kartında adedi 7 yapıp \"Sepete ekle\" butonuna bas"},{id:"S4",action:"Üst menüden sepete git"}], testKey: "TPD-12" };
const norm = (x: string) => x.replace(/[0-9a-f]{64}/g, "<hash>").trimEnd();

describe.skipIf(!VAR)("mock kodu = şablon golden'ı", () => {
it("C#: TPD1WebC2_3f9b1c2eTests.cs (yol K-T6)", () => { const c = csharpCiktisi(g); expect(c.dosya_yolu).toBe("demo-app/e2e-csharp/tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"); expect(norm(c.kod)).toBe(norm(readFileSync(G+"TPD1WebC2_3f9b1c2eTests.cs","utf8"))); });
it("Python: test_tpd_1_c2_3f9b1c2e.py", () => { const c = pythonCiktisi(g); expect(c.dosya_yolu).toBe("demo-app/e2e-python/tests/generated/test_tpd_1_c2_3f9b1c2e.py"); expect(norm(c.kod)).toBe(norm(readFileSync(G+"test_tpd_1_c2_3f9b1c2e.py.golden","utf8"))); });
it("web + Java: TPD1WebC2_3f9b1c2eTest.java (goTo)", () => { const c = javaWebCiktisi({ ...g, adimlar: javaAdimlari(adimlar) }); expect(norm(c.kod)).toBe(norm(readFileSync(G+"TPD1WebC2_3f9b1c2eTest.java","utf8"))); });
});

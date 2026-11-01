"""Onarımın saf parçaları: locator çıkarımı, sembol tablosu, metin düzeyinde yama (§8.7 birim
testleri: 0 eşleşme, çoklu eşleşme, anahtar/niyet değişikliği denemesi, test dosyasına dokunan
yama — sonuncusu akış testinde AST koruması ile)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_core.features.repair import locators as L

REPO = Path(__file__).resolve().parents[5]
SYMBOLS = json.loads(
    (REPO / "core/tests/unit/features/codegen/symbols.json").read_text(encoding="utf-8")
)
CATALOG_TS = (REPO / "demo-app/e2e/pages/catalog/locators.ts").read_text(encoding="utf-8")
SUPPORT_TS = (REPO / "demo-app/e2e/pages/support.ts").read_text(encoding="utf-8")
LOCATOR_MSG = (
    "Error: locator.click: Timeout 5000ms exceeded.\nCall log:\n"
    "  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')"
)


def test_kirik_testid_ve_kapsam() -> None:
    assert L.kirik_testid(LOCATOR_MSG) == ("add-to-cart", "product-card-P-001")
    assert L.kirik_testid('waiting for getByTestId("nav-cart")') == ("nav-cart", None)
    assert L.kirik_testid("""locator('[data-testid="x-1"]')""") == ("x-1", None)
    assert L.kirik_testid("assertion failed") == (None, None)
    assert L.kirik_testid(None) == (None, None)


def test_sembol_tablosunda_locator() -> None:
    bulunan = L.find_locators(SYMBOLS, "add-to-cart")
    assert len(bulunan) == 1
    loc = bulunan[0]
    assert (loc.sinif, loc.tam_ad, loc.dosya) == (
        "CatalogPage",
        "catalog.addToCart",
        "pages/catalog/locators.ts",
    )
    assert (loc.rol, loc.ad, loc.within) == ("button", "Sepete ekle", "product-card-")
    assert L.kapsayici_rolu(loc) == ("article", "productCard")
    # Triage önerisindeki anahtar kısa ya da tam adla verilebilir.
    assert L.find_locators(SYMBOLS, "add-to-cart", anahtar="addToCart") == bulunan
    assert L.find_locators(SYMBOLS, "add-to-cart", anahtar="catalog.addToCart") == bulunan
    assert L.find_locators(SYMBOLS, "add-to-cart", anahtar="baska") == []


def test_onek_locator_onarim_kapsami_disi() -> None:
    assert L.find_locators(SYMBOLS, "product-card-") == []
    assert L.find_locators(SYMBOLS, "yok-boyle") == []


def test_cakisma_baska_locatorin_testidsi() -> None:
    loc = L.find_locators(SYMBOLS, "add-to-cart")[0]
    assert L.cakisma(SYMBOLS, "cart-add", loc) is None
    assert "nav-cart" in (L.cakisma(SYMBOLS, "nav-cart", loc) or "")
    # Önek locator'ın alanına düşen değer de reddedilir (product-card-P-001 bir kart).
    assert L.cakisma(SYMBOLS, "product-card-P-001", loc) is not None


def test_sayfa_yolu() -> None:
    paths = L.parse_paths(SUPPORT_TS)
    assert paths["catalog"] == "/katalog"
    assert L.url_path_for("pages/catalog/locators.ts", paths) == "/katalog"
    assert L.url_path_for("pages/order/locators.ts", paths) == "/siparisler"
    assert L.url_path_for("pages/bilinmeyen/locators.ts", paths) is None


def test_yama_yalnizca_testid_degerini_degistirir() -> None:
    sonra = L.patch_testid(CATALOG_TS, "addToCart", "add-to-cart", "cart-add")
    once_s, sonra_s = CATALOG_TS.splitlines(), sonra.splitlines()
    farkli = [(a, b) for a, b in zip(once_s, sonra_s, strict=True) if a != b]
    assert len(farkli) == 1
    a, b = farkli[0]
    assert a.replace('"add-to-cart"', '"cart-add"') == b
    # rol, ad, niyet, within ve anahtar kümesi aynı
    for alan in ('role: "button"', 'name: "Sepete ekle"', 'within: "product-card-"', "intent:"):
        assert alan in b
    assert sonra.count("addToCart") == CATALOG_TS.count("addToCart")
    fark = L.birlesik_fark("e2e/pages/catalog/locators.ts", CATALOG_TS, sonra)
    satirlar = fark.splitlines()
    assert [x for x in satirlar if x.startswith("-") and not x.startswith("---")] == ["-" + a]
    assert [x for x in satirlar if x.startswith("+") and not x.startswith("+++")] == ["+" + b]


def test_yama_tek_tirnak_korunur() -> None:
    kaynak = (
        "export const x = {\n"
        "  a: { testId: 'eski', role: 'button', name: 'A', intent: 'i' },\n"
        "} as const;\n"
    )
    assert "testId: 'yeni'" in L.patch_testid(kaynak, "a", "eski", "yeni")


@pytest.mark.parametrize(
    ("anahtar", "eski", "yeni", "parca"),
    [
        ("yok", "add-to-cart", "cart-add", "bulunamadı"),
        ("addToCart", "baska", "cart-add", "bulunamadı"),
        ("addToCart", "add-to-cart", 'x", role: "link', "geçersiz"),
        ("addToCart", "add-to-cart", "", "geçersiz"),
        ("addToCart", "add-to-cart", "add-to-cart", "aynı"),
        ("addToCart; evil", "add-to-cart", "cart-add", "geçersiz locator anahtarı"),
    ],
)
def test_yama_reddedilir(anahtar: str, eski: str, yeni: str, parca: str) -> None:
    with pytest.raises(L.PatchError, match=parca):
        L.patch_testid(CATALOG_TS, anahtar, eski, yeni)


def test_ayni_anahtar_iki_kez_varsa_yama_yok() -> None:
    kaynak = (
        "export const a = { k: { testId: 't', role: 'button', name: 'A', intent: 'i' } };\n"
        "export const b = { k: { testId: 't', role: 'button', name: 'B', intent: 'i' } };\n"
    )
    with pytest.raises(L.PatchError, match="birden çok"):
        L.patch_testid(kaynak, "k", "t", "u")


def test_fark_dogrulamasi_niyet_ya_da_rol_degisikligini_reddeder() -> None:
    once = 'a: { testId: "x", role: "button", name: "A", intent: "i" },\n'
    with pytest.raises(L.PatchError, match="testId dışında"):
        L.dogrula_fark(once, once.replace('"x"', '"y"').replace('"i"', '"j"'), "x", "y")
    with pytest.raises(L.PatchError, match="testId dışında"):
        L.dogrula_fark(once, once.replace('"x"', '"y"').replace("button", "link"), "x", "y")
    with pytest.raises(L.PatchError, match="satır"):
        L.dogrula_fark(once, once + "b: {},\n", "x", "y")
    L.dogrula_fark(once, once.replace('"x"', '"y"'), "x", "y")


def test_etkilenen_testler() -> None:
    loc = L.find_locators(SYMBOLS, "add-to-cart")[0]
    dosyalar = {
        "e2e/tests/cart.spec.ts": "await catalogPage.addToCart('P-001', 6)",
        "e2e/tests/login.spec.ts": "await loginPage.login(u, p)",
        "e2e/tests/locators.spec.ts": 'import { catalog } from "../pages/catalog/locators";',
        "e2e/tests/fixtures.ts": "new CatalogPage(page)",
    }
    assert L.etkilenen_testler(dosyalar, loc) == [
        "e2e/tests/cart.spec.ts",
        "e2e/tests/locators.spec.ts",
    ]


SOZLESME_SPEC = (REPO / "demo-app/e2e/tests/locators.spec.ts").read_text(encoding="utf-8")


@pytest.mark.parametrize("deger", ["cart-add\n", "cart-add\r\n", "\ncart-add", "cart add", ""])
def test_testid_bicimi_sondaki_satir_sonunu_reddeder(deger: str) -> None:
    # `$` + match() sondaki "\n"'i kabul ederdi; `\Z` etmez.
    assert L.TESTID_RE.match(deger) is None
    with pytest.raises(L.PatchError, match="geçersiz"):
        L.patch_testid(CATALOG_TS, "addToCart", "add-to-cart", deger or "x\n")


def test_locators_dosya_bicimi_sondaki_satir_sonunu_reddeder() -> None:
    assert L.LOCATORS_FILE_RE.match("e2e/pages/catalog/locators.ts")
    assert L.LOCATORS_FILE_RE.match("e2e/pages/catalog/locators.ts\n") is None


def test_sozlesme_basliklari_locatoru_sinayan_testi_secer() -> None:
    """Gerçek locators.spec.ts: catalog.addToCart'ı yalnızca katalog testi sınar; giriş sayfası
    testi (login grubu) kanıt değildir."""
    loc = L.find_locators(SYMBOLS, "add-to-cart")[0]
    assert loc.grup == "catalog"
    assert L.sozlesme_basliklari(SOZLESME_SPEC, loc) == [
        "menü, katalog, sepet ve sipariş sayfaları"
    ]
    login = L.LocatorRef("pages/login/locators.ts", "LoginPage", "submit", "login-submit",
                         "button", "Giriş yap", "", grup="login")  # fmt: skip
    assert L.sozlesme_basliklari(SOZLESME_SPEC, login) == ["giriş sayfası"]


def test_sozlesme_basliklari_yapi_bozmada_anahtara_bakar() -> None:
    spec = """
test("a", async ({ page }) => {
  const { orderTotal } = order;
  await check(page, { orderTotal });
});
signedInTest(
  "b",
  async ({ page }) => {
    const { ordersTable, orderRow } = order;
    await check(page, { ordersTable, orderRow });
  },
);
test("c", async ({ page }) => { await check(page, orderPage); });
"""
    ref = L.LocatorRef("pages/order/locators.ts", "OrderPage", "orderRow", "order-row",
                       "row", "Sipariş", "", grup="order")  # fmt: skip
    assert L.sozlesme_basliklari(spec, ref) == ["b"]
    # Grup bilinmiyorsa kapalı başarısızlık.
    grupsuz = L.LocatorRef("x/locators.ts", "X", "orderRow", "order-row", "row", "S", "")
    assert L.sozlesme_basliklari(spec, grupsuz) == []
    assert L.sozlesme_basliklari("", ref) == []

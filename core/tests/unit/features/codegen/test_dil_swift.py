"""Swift / XCUITest dil eklentisi (014, Ş4): golden çıktı, literal/tanımlayıcı güvenliği, ad/yol,
etiketler, gizli test verisi, kurulum iskeleti.

Golden güncelleme: `TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_dil_swift.py`.
Golden'ın toolchain korumasından geçtiği `toolchain/tests/test_dil_swift.py`'de doğrulanır (aynı
dosyayı okur).
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from tp_core.audit import content_hash
from tp_core.features.codegen import render
from tp_core.features.codegen.diller import swift
from tp_core.features.codegen.render import RenderError, RenderInput

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RULES = REPO / "rules"
GOLDEN = HERE / "golden"
GOLDEN_AD = "TPD1IosC2_3f9b1c2eTests.swift"
SEMBOLLER = json.loads((HERE / "symbols-swift.json").read_text(encoding="utf-8"))
UI_TEST_KOKU = REPO / "demo-app" / "mobile" / "ios-test" / "BayiSiparisUITests"
CASE_ID = uuid.UUID("3f9b1c2e-0000-5000-8000-0000000000c2")
APP_GOLDEN = json.loads(
    (RULES / "replay/verify_and_map_app/golden/TPD-1-C2-android.json").read_text("utf-8")
)
CASE = json.loads((RULES / "replay/case_generation/golden/TPD-1.json").read_text("utf-8"))[
    "output"
]["cases"][1]
DEALERS = swift.parse_dealers((UI_TEST_KOKU / swift.BAYILER_DOSYASI).read_text(encoding="utf-8"))


def girdi(**over: Any) -> RenderInput:
    alanlar: dict[str, Any] = {
        "case_id": CASE_ID,
        "case": CASE,
        "sira_no": 2,
        "story_key": "TPD-1",
        "test_key": "TPD-12",
        "case_hash": content_hash(CASE),
        "mode": "replay",
        "bundle_hash": "b" * 64,
        "mapping": APP_GOLDEN["output"],
        "dealers": DEALERS,
        "e2e_root": "demo-app/mobile/ios-test/BayiSiparisUITests",
    }
    alanlar.update(over)
    return RenderInput(**alanlar)


def uret(**over: Any) -> render.Rendered:
    tablo = over.pop("sembol_tablosu", SEMBOLLER)
    return swift.EKLENTI.render(girdi(**over), swift.CATI, RULES, sembol_tablosu=tablo)


# ------------------------------------------------------------------------------ golden


def test_golden() -> None:
    r = uret()
    hedef = GOLDEN / GOLDEN_AD
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.write_text(r.content, encoding="utf-8")
    assert r.content == hedef.read_text(encoding="utf-8")
    assert r.dil == "swift"
    assert r.sinif_adi == "TPD1IosC2_3f9b1c2eTests"
    assert r.test_adi == "testSenaryo"
    assert r.test_file == "TPUretilen/TPD1IosC2_3f9b1c2eTests.swift"
    assert r.repo_path == (
        "demo-app/mobile/ios-test/BayiSiparisUITests/TPUretilen/TPD1IosC2_3f9b1c2eTests.swift"
    )
    assert r.dealer == "bayi1"
    assert not r.dogrulanmamis
    # Deterministik: aynı girdi aynı bayt.
    assert uret().content == r.content


def test_golden_icerigi_etiketli_cagri_ve_bayi() -> None:
    c = uret().content
    assert 'girisEkrani.girisYap(kullaniciAdi: "bayi1", parola: "Demo123!")' in c
    assert 'katalogEkrani.sepeteEkle(urunKodu: "P-001", adet: 7)' in c
    assert 'override class var bayi: String? { "bayi1" }' in c
    assert "kırarak doğrulanmadı" in c
    assert "mobil-ios-swift" in c


def test_varsayilan_kok_ve_yol() -> None:
    r = uret(e2e_root=render.E2E_ROOT)
    assert r.repo_path == "UITests/TPUretilen/TPD1IosC2_3f9b1c2eTests.swift"
    assert swift.EKLENTI.uretilen_yol(swift.CATI, "", "TPD-1", 2, CASE_ID) == r.repo_path
    assert (
        swift.EKLENTI.uretilen_yol(swift.CATI, "/ios/AppUITests/", None, 3, CASE_ID)
        == "ios/AppUITests/TPUretilen/SerbestIosC3_3f9b1c2eTests.swift"
    )


def test_cati_alanlari_sozlesmeyle_ayni() -> None:
    c = swift.CATI
    assert (c.platform, c.dil, c.hat, c.sablon, c.kok_ayari, c.kok_varsayilan) == (
        "ios", "swift", "musteri_ci", "xcuitest.swift.j2", "TP_IOS_SWIFT_ROOT", "UITests",
    )  # fmt: skip
    assert (c.uretilen_alt_yol, c.sonuc, c.ajan, c.gh_is_akisi) == (
        "TPUretilen", "junit", "verify_and_map_app", "mobil-ios-swift",
    )  # fmt: skip
    # Ş0 matrisi geldiyse aynı satır (yoksa yerel tablo geçerli).
    from tp_core.features.codegen import platform as platformlar

    catilar = getattr(platformlar, "CATILAR", None)
    if catilar is not None:
        assert catilar[("ios", "swift")] == c


def test_eklenti_protokolu() -> None:
    e = swift.EKLENTI
    assert e.ad == "swift"
    assert e.proje_dosyasi == "Ekranlar/Kimlikler.swift"
    assert [(sorted(k.platformlar), k.kok_ayari) for k in e.algila_kaliplari] == [
        (["ios"], "TP_IOS_SWIFT_ROOT")
    ]
    assert e.eslemeyi_donustur({"a": 1}) == {"a": 1}
    assert e.sinif_adi("TPD-1", "ios", 2, CASE_ID) == "TPD1IosC2_3f9b1c2eTests"
    assert e.literal("x") == '"x"'
    assert e.ident("girisYap") == "girisYap"


# ------------------------------------------------------------------------------ süzgeçler


@pytest.mark.parametrize(
    ("deger", "beklenen"),
    [
        ("150,00 TL", '"150,00 TL"'),
        ('a"b\\c', '"a\\"b\\\\c"'),
        ("satır\nalt\tsekme\r", '"satır\\nalt\\tsekme\\r"'),
        ("Çğıöşü İ € 😀", '"Çğıöşü İ € 😀"'),
        ("\\(evil())", '"\\\\(evil())"'),  # interpolasyon açılamaz: ters bölü çiftlenir
        ("‮RLO", '"\\u{202E}RLO"'),
        ("\x00\x1b", '"\\u{0}\\u{1B}"'),
        (" ", '"\\u{2028}"'),
        ('#"ham"#', '"#\\"ham\\"#"'),
        (7, "7"),
        (-3, "-3"),
        (2**40, str(2**40)),
        (1.5, "1.5"),
        (1e20, "1e+20"),
        (True, "true"),
        (False, "false"),
    ],
)
def test_swift_literal(deger: Any, beklenen: str) -> None:
    assert swift.swift_literal(deger) == beklenen


@pytest.mark.parametrize(
    "deger", [float("nan"), float("inf"), 2**63, None, [1], {"a": 1}, "\ud800"]
)
def test_swift_literal_reddeder(deger: Any) -> None:
    with pytest.raises(RenderError):
        swift.swift_literal(deger)


@pytest.mark.parametrize(
    "ad", ["class", "func", "self", "_", "1a", "a-b", "a b", "", "import", None]
)
def test_swift_ident_reddeder(ad: Any) -> None:
    with pytest.raises(RenderError):
        swift.swift_ident(ad)


def test_yorum_tek_satir_ve_blok_yorum_kapatamaz() -> None:
    assert swift.swift_comment("a\nb */ evil() /* c‮") == "a b * / evil() / * c"


# ------------------------------------------------------------------------------ kötü değerler


KOTU = [
    '"); exit(0); //',
    "\\(Process())",
    '"""',
    "*/ evil(); /*",
    "satır\nkırığı\r\n// yorum",
    "#if DEBUG",
    '#"raw"#',
    "\\",
    "sonda ters bölü\\",
    "‮⁦​﻿",
]


@pytest.mark.parametrize("deger", KOTU)
def test_kotu_deger_tek_dize_literali_kalir(deger: str) -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["expects"][2]["args"] = [deger]
    c = uret(mapping=m).content
    satir = next(s for s in c.splitlines() if "sepetEkrani.dogrulaAraToplam(" in s)
    assert satir == f"        sepetEkrani.dogrulaAraToplam(tutar: {swift.swift_literal(deger)})"
    for ch in "‮⁦​﻿":
        assert ch not in c


def test_kotu_metot_adi_reddedilir() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["step_mapping"][0]["method"] = "ac(); evil"
    with pytest.raises(RenderError):
        uret(mapping=m)


def test_tabloda_olmayan_metot_reddedilir() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["step_mapping"][0]["method"] = "yokBoyle"
    with pytest.raises(RenderError, match="sembol tablosunda yok"):
        uret(mapping=m)


def test_fazla_arguman_reddedilir() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["step_mapping"][0]["args"] = ["fazla"]
    with pytest.raises(RenderError, match="en çok 0"):
        uret(mapping=m)


def test_sembol_tablosu_zorunlu() -> None:
    with pytest.raises(RenderError, match="sembol tablosu"):
        swift.EKLENTI.render(girdi(), swift.CATI, RULES)


def test_etiketsiz_parametre() -> None:
    tablo = copy.deepcopy(SEMBOLLER)
    po = next(p for p in tablo["page_objects"] if p["class"] == "SepetEkrani")
    m = next(x for x in po["methods"] if x["name"] == "dogrulaAraToplam")
    m["params"][0]["label"] = "_"
    c = uret(sembol_tablosu=tablo).content
    assert 'sepetEkrani.dogrulaAraToplam("175,00 TL")' in c


def test_gizli_test_verisi_ortamdan_okunur() -> None:
    r = uret(gizli_ortam={"Demo123!": "TP_TESTVERI_BAYI1_PAROLA"})
    assert 'parola: ortam("TP_TESTVERI_BAYI1_PAROLA")' in r.content
    assert "Demo123!" not in r.content


def test_gizli_sizinti_durdurur() -> None:
    with pytest.raises(render.GizliSizinti):
        uret(gizli_taranacak=("Demo123!",))


def test_bayisiz_sabitleme_yok() -> None:
    c = uret(dealers={}).content
    assert "override class var bayi" not in c


# ------------------------------------------------------------------------------ yardımcılar


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        ("UITests/GirisTesti.swift", True),
        ("UITests/LoginTests.swift", True),
        ("UITests/LoginTest.swift", True),
        ("UITests/TPUretilen/TPD1IosC2_3f9b1c2eTests.swift", False),
        ("UITests/Ekranlar/GirisEkrani.swift", False),
        ("UITests/Tests.kt", False),
    ],
)
def test_test_dosyasi_mi(yol: str, beklenen: bool) -> None:
    assert swift.test_dosyasi_mi(yol) is beklenen


def test_bayiler_ayristirilir() -> None:
    assert DEALERS == {
        "bayi1": {"password": "Demo123!", "name": "Merkez Bayi"},
        "bayi2": {"password": "Demo123!", "name": "Sahil Bayi"},
    }


def test_kurulum_iskeleti() -> None:
    dosyalar = swift.EKLENTI.iskelet("ios/AppUITests", RULES)
    assert set(dosyalar) == {
        "ios/AppUITests/Altyapi/TestTabani.swift",
        "ios/AppUITests/Altyapi/UygulamaOturumu.swift",
        "ios/AppUITests/Ekranlar/Ekran.swift",
        "ios/AppUITests/Ekranlar/Kimlikler.swift",
        "ios/AppUITests/TPUretilen/.gitkeep",
    }
    assert (
        "func ortam(_ ad: String) -> String" in dosyalar["ios/AppUITests/Altyapi/TestTabani.swift"]
    )
    assert swift.ELLE_ADIMLAR and all(
        "pbxproj" not in a or "dokunmaz" in a for a in swift.ELLE_ADIMLAR
    )


def test_semboller_dosyasi_demo_kutuphanesiyle_eslesir() -> None:
    """`symbols-swift.json` demo kütüphanesinin metot imzalarını taşır (toolchain testi aynı
    tabloyu tree-sitter ile yeniden üretip karşılaştırır)."""
    adlar = {p["class"] for p in SEMBOLLER["page_objects"]}
    assert adlar == {"GirisEkrani", "KatalogEkrani", "OnayEkrani", "SepetEkrani", "SiparisEkrani"}
    for p in SEMBOLLER["page_objects"]:
        assert (UI_TEST_KOKU / p["file"]).is_file()

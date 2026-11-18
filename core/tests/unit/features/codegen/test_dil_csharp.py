"""C# dil eklentisi (014 Ş2): şablon goldens, ad dönüşümü, enjeksiyon kapalılığı, yol/kimlik.

Golden'lar `golden/csharp/` altındadır; demo hedef projelerdeki örnek üretilen testler
(`demo-app/e2e-csharp/Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs`,
`demo-app/e2e-app-csharp/Tests/Generated/TPD1WindowsC2_3f9b1c2eTests.cs`) bunlarla bayt eşittir.
Güncelleme: `TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_dil_csharp.py`.
"""

from __future__ import annotations

import copy
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tp_core.audit import content_hash
from tp_core.features.codegen import render as r
from tp_core.features.codegen.diller import csharp as cs

from .test_checks import RULES, golden_case, golden_mapping
from .test_platform import APP_GOLDEN, CASE_ID, DEALERS

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "csharp"
REPO = HERE.parents[4]
DEMO_WEB = REPO / "demo-app" / "e2e-csharp" / "Tests" / "Generated"
DEMO_WIN = REPO / "demo-app" / "e2e-app-csharp" / "Tests" / "Generated"


def girdi(n: int = 2, *, app: bool = False, **over: Any) -> r.RenderInput:
    case = over.pop("case", golden_case(n))
    mapping = over.pop("mapping", copy.deepcopy(APP_GOLDEN["output"]) if app else golden_mapping(n))
    alanlar: dict[str, Any] = {
        "case_id": CASE_ID,
        "case": case,
        "sira_no": n,
        "story_key": "TPD-1",
        "test_key": "TPD-12",
        "case_hash": content_hash(case),
        "mode": "replay",
        "bundle_hash": "b" * 64,
        "mapping": mapping,
        "dealers": DEALERS,
        "e2e_root": "e2e-app-csharp" if app else "e2e-csharp",
    }
    alanlar.update(over)
    return r.RenderInput(**alanlar)


def golden_karsilastir(ad: str, icerik: str) -> None:
    hedef = GOLDEN / ad
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_text(icerik, encoding="utf-8")
    assert icerik == hedef.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------ çatı / ad


def test_cati_tanimlari() -> None:
    web, win = cs.cati("web"), cs.cati("windows")
    assert (web.platform, web.dil, web.hat, web.sablon) == (
        "web",
        "csharp",
        "tam",
        "playwright_nunit.cs.j2",
    )
    assert (win.platform, win.hat, win.sablon, win.ajan) == (
        "windows",
        "tam",
        "appium_nunit.cs.j2",
        "verify_and_map_app",
    )
    assert (web.kok_ayari, web.kok_varsayilan) == ("TP_E2E_CSHARP_ROOT", "e2e-csharp")
    assert (win.kok_ayari, win.kok_varsayilan) == ("TP_E2E_APP_CSHARP_ROOT", "e2e-app-csharp")
    assert (web.gh_is_akisi, win.gh_is_akisi) == ("web-csharp", "masaustu-windows-csharp")
    assert cs.check_adi("web") == "local-ci-web-csharp"
    assert cs.check_adi("windows") == "local-ci-windows-csharp"
    for p in ("android", "ios", "masa"):
        with pytest.raises(ValueError):
            cs.cati(p)


@pytest.mark.parametrize(
    ("ad", "platform", "beklenen"),
    [
        ("addToCart", "web", "AddToCartAsync"),
        ("goto", "web", "GotoAsync"),
        ("goTo", "web", "GotoAsync"),  # Java tablosundan gelen ayrılmış sözcük karşılığı
        ("LoginAsync", "web", "LoginAsync"),  # C# tablosundan gelen ad değişmez
        ("expectTotal", "web", "ExpectTotalAsync"),
        ("girisYap", "windows", "GirisYap"),
        ("ac", "windows", "Ac"),
        ("GirisYap", "windows", "GirisYap"),
    ],
)
def test_metot_adi(ad: str, platform: str, beklenen: str) -> None:
    assert cs.metot_adi(ad, platform) == beklenen


@pytest.mark.parametrize("ad", ["Task", "TestTabani", "Gizli", "Bayi", "Senaryo"])
def test_ayrilmis_erisimci_reddedilir(ad: str) -> None:
    with pytest.raises(r.RenderError):
        cs.erisimci_adi(ad)


def test_sinif_ve_yol() -> None:
    assert cs.sinif_adi("TPD-1", "web", 2, CASE_ID) == "TPD1WebC2_3f9b1c2eTests"
    assert cs.sinif_adi("TPD-1", "windows", 2, CASE_ID) == "TPD1WindowsC2_3f9b1c2eTests"
    assert cs.sinif_adi(None, "web", 3, CASE_ID) == "SerbestWebC3_3f9b1c2eTests"
    assert (
        cs.repo_yolu("demo-app/e2e-csharp", "TPD-1", "web", 2, CASE_ID)
        == "demo-app/e2e-csharp/Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    )
    assert cs.repo_yolu("", "TPD-1", "windows", 2, CASE_ID).startswith("e2e-app-csharp/")
    assert cs.junit_kimligi("TPD1WebC2_3f9b1c2eTests") == (
        "Antreklabs.Bayi.Tests.Generated.TPD1WebC2_3f9b1c2eTests.Senaryo"
    )


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        ("e2e-csharp/Tests/GirisTests.cs", True),
        ("e2e-csharp/Tests/SepetTest.cs", True),
        ("e2e-csharp/Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs", False),
        ("e2e-csharp/Birim/AyarlarTests.cs", False),
        ("e2e-csharp/obj/Debug/XTests.cs", False),
        ("e2e-csharp/Pages/LoginPage.cs", False),
    ],
)
def test_test_dosyasi_mi(yol: str, beklenen: bool) -> None:
    assert cs.test_dosyasi_mi(yol) is beklenen


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        ("Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs", True),
        ("Tests/GirisTests.cs", True),
        ("Birim/AyarlarTests.cs", False),
        ("Tests/../Birim/XTests.cs", False),
        ("Pages/LoginPage.cs", False),
    ],
)
def test_kapsam_dosyasi_mi(yol: str, beklenen: bool) -> None:
    assert cs.kapsam_dosyasi_mi(yol) is beklenen


# ---------------------------------------------------------------------------------- golden


def test_web_golden() -> None:
    sonuc = cs.render_platform(girdi(2), "web", RULES)
    golden_karsilastir("TPD1WebC2_3f9b1c2eTests.cs", sonuc.content)
    assert sonuc.repo_path == "e2e-csharp/Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    assert sonuc.test_file == "Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    assert (sonuc.dil, sonuc.sinif_adi, sonuc.test_adi) == (
        "csharp",
        "TPD1WebC2_3f9b1c2eTests",
        "Senaryo",
    )
    assert not sonuc.dogrulanmamis
    assert sonuc.dealer == "bayi1"
    assert 'await LoginPage.LoginAsync("bayi1", Gizli("TP_TESTVERI_KOSU_BAYI1"));' in sonuc.content
    assert "await LoginPage.GotoAsync();" in sonuc.content


def test_windows_golden() -> None:
    sonuc = cs.render_platform(girdi(2, app=True), "windows", RULES)
    golden_karsilastir("TPD1WindowsC2_3f9b1c2eTests.cs", sonuc.content)
    assert sonuc.repo_path == "e2e-app-csharp/Tests/Generated/TPD1WindowsC2_3f9b1c2eTests.cs"
    assert 'GirisEkrani.GirisYap("bayi1", Gizli("TP_TESTVERI_KOSU_BAYI1"));' in sonuc.content
    assert "await" not in sonuc.content.split("namespace", 1)[1]
    assert '[Category("windows")]' in sonuc.content


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
def test_tum_web_goldenlari_render_edilir_ve_deterministik(n: int) -> None:
    a = cs.render_platform(girdi(n), "web", RULES)
    b = cs.render_platform(girdi(n), "web", RULES)
    assert a == b
    assert a.content.startswith("// AI-generated — AI Testing Probe (CasesToCode).")


def test_demo_ornekleri_golden_ile_bayt_esit() -> None:
    """demo-app hedef projelerindeki örnek üretilen testler golden'ın kopyasıdır."""
    for demo, ad in (
        (DEMO_WEB, "TPD1WebC2_3f9b1c2eTests.cs"),
        (DEMO_WIN, "TPD1WindowsC2_3f9b1c2eTests.cs"),
    ):
        ornek = demo / ad
        if not ornek.exists():
            pytest.skip(f"demo örneği yok: {ornek}")
        assert ornek.read_text(encoding="utf-8") == (GOLDEN / ad).read_text(encoding="utf-8")


def test_sablon_hashi_baslikta() -> None:
    sonuc = cs.render_platform(girdi(2), "web", RULES)
    assert f"şablon: {sonuc.template_hash}" in sonuc.content


def test_ts_koku_verilirse_varsayilan_kok() -> None:
    assert cs.render_platform(girdi(2, e2e_root="e2e"), "web", RULES).repo_path.startswith(
        "e2e-csharp/"
    )


# ------------------------------------------------------------------ enjeksiyon / gizli veri


@pytest.mark.parametrize(
    "deger",
    [
        '"); System.IO.File.Delete("x"); //',
        '{0} $"{x}" @"y"',
        '"""ham"""',
        "satır\nyeni // */ /*",
        "‮RLO⁦ yön",
        "\\u0022 kaçış",
    ],
)
def test_degerler_duz_literal_olur(deger: str) -> None:
    m = copy.deepcopy(golden_mapping(5))
    m["expects"] = [{"po": "CartPage", "method": "expectMinOrderWarning", "args": [deger]}]
    sonuc = cs.render_platform(girdi(5, mapping=m), "web", RULES)
    satir = next(s for s in sonuc.content.splitlines() if "ExpectMinOrderWarningAsync(" in s)
    assert satir.strip() == f"await CartPage.ExpectMinOrderWarningAsync({cs.literal(deger)});"
    assert "\n" not in cs.literal(deger)


def test_gecersiz_metot_adi_reddedilir() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["method"] = "x(); System.Exit"
    with pytest.raises(r.RenderError):
        cs.render_platform(girdi(2, mapping=m), "web", RULES)


def test_desteklenmeyen_deger_turu_reddedilir() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["args"] = [["liste"]]
    with pytest.raises(r.RenderError):
        cs.render_platform(girdi(2, mapping=m), "web", RULES)


# Seed parolası case'teki parolayla eşleşmeyen bayiler: koşu hesabı ikamesi yapılmaz (K19 yolu).
SEEDSIZ = {u: {**d, "password": "seed-farkli"} for u, d in DEALERS.items()}


def test_gizli_veri_ortamdan_okunur_ve_sizinti_yok() -> None:
    sonuc = cs.render_platform(
        girdi(
            2,
            gizli_ortam={"Demo123!": "TP_TESTVERI_BAYI1_PAROLA"},
            gizli_taranacak=("Demo123!",),
            dealers=SEEDSIZ,
        ),
        "web",
        RULES,
    )
    assert (
        'await LoginPage.LoginAsync("bayi1", Gizli("TP_TESTVERI_BAYI1_PAROLA"));' in sonuc.content
    )
    assert "Demo123!" not in sonuc.content


def test_gizli_sizinti_fail_closed() -> None:
    case = copy.deepcopy(golden_case(2))
    case["title"] = "parola Demo123! ile giriş"
    with pytest.raises(r.GizliSizinti):
        cs.render_platform(
            girdi(2, case=case, gizli_taranacak=("Demo123!",), dealers=SEEDSIZ), "web", RULES
        )


def test_yanlis_cati_reddedilir() -> None:
    sahte = SimpleNamespace(platform="android", dil="csharp", sablon="appium_nunit.cs.j2")
    with pytest.raises(r.RenderError):
        cs.render(girdi(2), sahte, RULES)


def test_ornek_case_id_sabit() -> None:
    assert uuid.UUID("3f9b1c2e-0000-5000-8000-0000000000c2") == CASE_ID

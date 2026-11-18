"""Ş3 Kotlin / Espresso statik araçları (worker/diller/kotlin.py): sembol tablosu, koruma, onarım
farkı, kök çözümü ve `/check` statik adımı.

tree-sitter-kotlin yoksa (imaj dışı geliştirme ortamı) modül atlanır. Yerel koşu:
`uv run --with tree-sitter==0.26.1 --with tree-sitter-kotlin==1.1.0 pytest tests/test_kotlin.py`
(sürümler `toolchain/statik-deps/kotlin.txt` ile aynı).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tree_sitter_kotlin")

from worker.diller import kotlin as kt

from .conftest import Forge

TOOLCHAIN = Path(__file__).resolve().parents[1]
REPO = TOOLCHAIN.parent
DEMO_KOK = REPO / "demo-app" / "mobile" / "android-test" / "java"
LIB = "com/antreklabs/bayisiparis/tp"
GOLDEN = REPO / "core/tests/unit/features/codegen/golden/TPD1AndroidC2_3f9b1c2eTest.kt"
GOLDEN_YOL = f"{LIB}/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
JAVA_SEMBOLLER = json.loads(
    (REPO / "core/tests/unit/features/codegen/symbols-java.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def tablo() -> dict[str, Any]:
    return kt.sembol_tablosu_dizinden(DEMO_KOK)


# ============================================================================ sembol tablosu


def _ozet(t: dict[str, Any]) -> dict[str, Any]:
    return {
        po["class"]: {
            "methods": [
                (m["name"], [(p["name"], p["type"]) for p in m["params"]], m["kind"], m["returns"])
                for m in po["methods"]
            ],
            "locators": {
                k: (v["testId"], v["intent"], v["prefix"]) for k, v in po["locators"].items()
            },
        }
        for po in t["page_objects"]
    }


def test_sembol_tablosu_java_tablosuyla_esit(tablo: dict[str, Any]) -> None:
    """PO eşitliği (TASARIM §3 ortak ilke): Kotlin kütüphanesi Java e2e-app ile ad/tür/niyet eşit;
    ajan girdisi ve REPLAY golden'ları dilden bağımsız kalır."""
    assert tablo["errors"] == []
    assert _ozet(tablo) == _ozet(JAVA_SEMBOLLER)
    assert tablo["fixtures"] == JAVA_SEMBOLLER["fixtures"]
    assert [lf["exports"] for lf in tablo["locator_files"]] == [
        lf["exports"] for lf in JAVA_SEMBOLLER["locator_files"]
    ]
    assert (tablo["lang"], tablo["paket"], tablo["schema_version"]) == (
        "kotlin",
        "com.antreklabs.bayisiparis.tp",
        1,
    )


def test_sembol_tablosu_ozel_ve_degerli_metotlari_almaz(tablo: dict[str, Any]) -> None:
    adlar = {m["name"] for po in tablo["page_objects"] for m in po["methods"]}
    assert "siparisNumarasiniOku" not in adlar  # internal + String döndürür
    assert "kart" not in adlar and "sepetSayaci" not in adlar  # private
    assert "gorulenMetin" not in adlar  # Ekran'da protected


def test_sembol_tablosu_bozuk_dosyayi_hata_olarak_bildirir(tmp_path: Path) -> None:
    kok = tmp_path / "java"
    shutil.copytree(DEMO_KOK, kok)
    (kok / LIB / "ekranlar" / "Bozuk.kt").write_text("class Bozuk : Ekran(o) { fun x( }\n", "utf-8")
    t = kt.sembol_tablosu_dizinden(kok)
    assert [e["file"] for e in t["errors"]] == [f"{LIB}/ekranlar/Bozuk.kt"]
    assert len(t["page_objects"]) == 5


def test_desteklenmeyen_parametre_turu(tmp_path: Path) -> None:
    kok = tmp_path / "java"
    shutil.copytree(DEMO_KOK, kok)
    (kok / LIB / "ekranlar" / "Yeni.kt").write_text(
        "package com.antreklabs.bayisiparis.tp.ekranlar\n\n"
        "import com.antreklabs.bayisiparis.tp.altyapi.UygulamaOturumu\n\n"
        "class YeniEkran(oturum: UygulamaOturumu) : Ekran(oturum) {\n"
        "  /** Tutar. */\n  fun dogrulaTutar(t: Double) {}\n"
        "  fun liste(x: List<String>) {}\n  fun bos(x: String?) {}\n}\n",
        "utf-8",
    )
    t = kt.sembol_tablosu_dizinden(kok)
    yeni = next(po for po in t["page_objects"] if po["class"] == "YeniEkran")
    assert [(m["name"], m["params"][0]["type"], m["kind"]) for m in yeni["methods"]] == [
        ("dogrulaTutar", "double", "expect")
    ]
    assert {e["message"].split(":")[0] for e in t["errors"]} == {"liste", "bos"}


# ================================================================================ koruma


def test_golden_ve_demo_ornegi_korumadan_gecer(tablo: dict[str, Any]) -> None:
    assert kt.guard_kaynak(GOLDEN.read_bytes(), GOLDEN_YOL, tablo=tablo) == []
    rapor = kt.guard_dizin(DEMO_KOK)
    assert rapor["ok"], rapor
    assert rapor["files"] == [GOLDEN_YOL]


SENARYO = GOLDEN.read_text(encoding="utf-8")
CAGRI = '    sepetEkrani().dogrulaToplam("150,00 TL")\n'


def _degistir(eski: str, yeni: str) -> bytes:
    assert eski in SENARYO, eski
    return SENARYO.replace(eski, yeni, 1).encode("utf-8")


KOTU: list[tuple[str, str, str, str]] = [
    # (ad, eski, yeni, beklenen ihlal kodu)
    ("runtime_exec", CAGRI, CAGRI + '    Runtime.getRuntime().exec("x")\n', "forbidden_statement"),
    ("dize_sablonu", '"150,00 TL"', '"$x"', "forbidden_argument"),
    ("dize_ifade_sablonu", '"150,00 TL"', '"${System.exit(0)}"', "forbidden_argument"),
    ("unicode_kacisi", '"150,00 TL"', '"\\u0022"', "forbidden_argument"),
    ("ham_dize", '"150,00 TL"', '"""x"""', "forbidden_argument"),
    ("blok_yorum", CAGRI, CAGRI + "    /* gizli */\n", "forbidden_statement"),
    ("arguman_yorumu", '"150,00 TL"', '/* x */ "150,00 TL"', "forbidden_argument"),
    ("adli_arguman", '"150,00 TL"', 'tutar = "150,00 TL"', "forbidden_argument"),
    ("yayilmis", '"150,00 TL"', "*arr", "forbidden_argument"),
    ("lambda", '"150,00 TL"', '{ "x" }', "forbidden_argument"),
    ("ic_cagri", '"150,00 TL"', 'listOf("x")', "forbidden_argument"),
    ("sir_adi", '"150,00 TL"', 'testVerisi("PAROLA")', "forbidden_argument"),
    ("sir_degisken", '"150,00 TL"', "testVerisi(x)", "forbidden_argument"),
    (
        "bilinmeyen_erisimci",
        "sepetEkrani().dogrulaToplam",
        "kasaEkrani().dogrulaToplam",
        "unknown_fixture",
    ),
    ("bilinmeyen_metot", "sepetEkrani().dogrulaToplam", "sepetEkrani().sil", "unknown_method"),
    ("arite", '"150,00 TL"', '"150,00 TL", 1', "arity_mismatch"),
    ("tur", '"150,00 TL"', "150", "type_mismatch"),
    (
        "int_disi",
        '("P-001", 7)\n    sepetEkrani().dogrulaBedavaAdet',
        '("P-001", 3000000000)\n    sepetEkrani().dogrulaBedavaAdet',
        "forbidden_argument",
    ),
    (
        "erisimci_argumani",
        "sepetEkrani().dogrulaToplam",
        'sepetEkrani("x").dogrulaToplam',
        "forbidden_statement",
    ),
    ("degisken", CAGRI, CAGRI + '    val x = "y"\n', "forbidden_statement"),
    ("atama", CAGRI, CAGRI + "    x = 1\n", "forbidden_statement"),
    (
        "import",
        "import org.junit.Test\n",
        "import org.junit.Test\nimport java.lang.Runtime\n",
        "forbidden_import",
    ),
    ("yildizli_import", "import org.junit.Test\n", "import org.junit.*\n", "forbidden_import"),
    ("takma_ad", "import org.junit.Test\n", "import org.junit.Test as T\n", "forbidden_import"),
    ("ust_duzey_fun", "@RunWith", "fun x() {}\n\n@RunWith", "forbidden_top_level"),
    ("ust_duzey_val", "@RunWith", "val x = 1\n\n@RunWith", "forbidden_top_level"),
    ("object", "@RunWith", "object X\n\n@RunWith", "forbidden_top_level"),
    (
        "paket",
        "package com.antreklabs.bayisiparis.tp.uretilen",
        "package com.antreklabs.bayisiparis.tp",
        "wrong_package",
    ),
    ("sinif_adi", "class TPD1AndroidC2_3f9b1c2eTest", "class Baska", "class_name"),
    ("open", "class TPD1", "open class TPD1", "class_shape"),
    (
        "ek_notasyon",
        "@RunWith(AndroidJUnit4::class)\n",
        '@RunWith(AndroidJUnit4::class)\n@Suppress("x")\n',
        "class_shape",
    ),
    ("bayi_enjeksiyon", '@Bayi("bayi1")', '@Bayi("bayi1\\$x")', "class_shape"),
    ("taban", ": TestTabani()", ": Object()", "class_shape"),
    ("init", "  @Test\n", "  init { println() }\n  @Test\n", "class_shape"),
    ("ozellik", "  @Test\n", "  val x = 1\n  @Test\n", "class_shape"),
    ("ikinci_test", "  @Test\n", "  @Test\n  fun baska() {}\n  @Test\n", "method_count"),
    ("donus_turu", "fun senaryo() {", "fun senaryo(): Unit {", "method_shape"),
    ("parametre", "fun senaryo() {", "fun senaryo(x: Int = 1) {", "method_shape"),
    (
        "test_notasyonu",
        "  @Test\n  fun senaryo",
        "  @Test(timeout = 1)\n  fun senaryo",
        "method_shape",
    ),
    ("rlo", "// Beklenen", "// ‮ Beklenen", "forbidden_char"),
    ("sifir_genislik", '"150,00 TL"', '"150,00​ TL"', "forbidden_char"),
    ("cr", CAGRI, CAGRI.replace("\n", "\r\n"), "forbidden_char"),
    ("sekme", CAGRI, "\t" + CAGRI, "forbidden_char"),
    ("ayristirma", CAGRI, CAGRI + "    sepetEkrani().x(\n", "parse_error"),
]


@pytest.mark.parametrize(("eski", "yeni", "kod"), [k[1:] for k in KOTU], ids=[k[0] for k in KOTU])
def test_koruma_reddeder(tablo: dict[str, Any], eski: str, yeni: str, kod: str) -> None:
    ihlaller = kt.guard_kaynak(_degistir(eski, yeni), GOLDEN_YOL, tablo=tablo)
    assert kod in {v["code"] for v in ihlaller}, ihlaller


@pytest.mark.parametrize(
    ("eski", "yeni"),
    [
        ('"150,00 TL"', '"a\\"b\\\\c\\n\\t\\$x ğüş €"'),
        ('"150,00 TL"', 'testVerisi("TP_TESTVERI_TUTAR")'),
        (
            '("P-001", 7)\n    sepetEkrani().dogrulaBedavaAdet',
            '("P-001", -7)\n    sepetEkrani().dogrulaBedavaAdet',
        ),
        ("// Beklenen sonuç", "// yorumda $x ${y} \\u0022 /* serbest"),
    ],
)
def test_koruma_izinli_bicimleri_kabul_eder(tablo: dict[str, Any], eski: str, yeni: str) -> None:
    assert kt.guard_kaynak(_degistir(eski, yeni), GOLDEN_YOL, tablo=tablo) == []


def test_tur_denetimi_double_ve_long(tablo: dict[str, Any]) -> None:
    t = json.loads(json.dumps(tablo))
    sepet = next(po for po in t["page_objects"] if po["class"] == "SepetEkrani")
    sepet["methods"] += [
        {"name": "dogrulaOran", "params": [{"name": "o", "type": "double"}]},
        {"name": "dogrulaKimlik", "params": [{"name": "k", "type": "long"}]},
        {"name": "dogrulaAcik", "params": [{"name": "a", "type": "boolean"}]},
    ]

    def dene(satir: str) -> set[str]:
        return {
            v["code"] for v in kt.guard_kaynak(_degistir(CAGRI, CAGRI + satir), GOLDEN_YOL, tablo=t)
        }

    assert dene("    sepetEkrani().dogrulaOran(1.5)\n") == set()
    assert dene("    sepetEkrani().dogrulaOran(-1.5e3)\n") == set()
    assert dene("    sepetEkrani().dogrulaOran(2)\n") == {"type_mismatch"}  # Kotlin genişletmez
    assert dene("    sepetEkrani().dogrulaKimlik(2)\n") == set()
    assert dene("    sepetEkrani().dogrulaKimlik(3000000000L)\n") == set()
    assert dene("    sepetEkrani().dogrulaAcik(true)\n") == set()
    assert dene('    sepetEkrani().dogrulaAcik("true")\n') == {"type_mismatch"}


def test_tablosuz_yalniz_bicim_denetlenir() -> None:
    assert kt.guard_kaynak(_degistir("dogrulaToplam", "dogrulaYok"), GOLDEN_YOL) == []
    assert {v["code"] for v in kt.guard_kaynak(_degistir('"150,00 TL"', '"$x"'), GOLDEN_YOL)} == {
        "forbidden_argument"
    }


def test_yanlis_dizin(tablo: dict[str, Any]) -> None:
    ihlaller = kt.guard_kaynak(
        SENARYO.encode(), f"{LIB}/TPD1AndroidC2_3f9b1c2eTest.kt", tablo=tablo
    )
    assert "wrong_path" in {v["code"] for v in ihlaller}


def test_guard_dizin_uretilen_disini_reddeder(tmp_path: Path) -> None:
    kok = tmp_path / "java"
    shutil.copytree(DEMO_KOK, kok)
    rapor = kt.guard_dizin(kok, dosyalar=[f"{LIB}/testler/GirisTesti.kt"])
    assert [v["code"] for v in rapor["violations"]] == ["not_generated"]
    (kok / LIB / "uretilen" / "notlar.txt").write_text("x", "utf-8")
    (kok / LIB / "uretilen" / "Bag.kt").symlink_to(kok / LIB / "uretilen" / GOLDEN.name)
    kodlar = [v["code"] for v in kt.guard_dizin(kok)["violations"]]
    assert kodlar.count("forbidden_file") == 2


# ============================================================================== Kimlikler


KIMLIK = (DEMO_KOK / LIB / "ekranlar" / "Kimlikler.kt").read_text(encoding="utf-8")


def test_kimlikler_saf() -> None:
    assert kt.kimlikler_saf_mi(KIMLIK.encode(), "Kimlikler.kt") == []


@pytest.mark.parametrize(
    ("eski", "yeni"),
    [
        ('    const val KATALOG = "nav-catalog"\n', '    const val KATALOG = "nav-$x"\n'),
        ('    const val KATALOG = "nav-catalog"\n', '    val KATALOG = "nav-catalog"\n'),
        ('    const val KATALOG = "nav-catalog"\n', '    var KATALOG = "nav-catalog"\n'),
        ('    const val KATALOG = "nav-catalog"\n', '    const val KATALOG = "nav-" + x()\n'),
        ("  object Menu {\n", '  object Menu {\n    init { Runtime.getRuntime().exec("x") }\n'),
        ("  object Menu {\n", "  object Menu {\n    fun x() = 1\n"),
        ("object Kimlikler {\n", "object Kimlikler {\n  fun x() = 1\n"),
        ("object Kimlikler {\n", "object Kimlikler : Any() {\n"),
        ("object Kimlikler {\n", 'object Kimlikler {\n  class Gizli { val x = "y" }\n'),
        ("\nobject Kimlikler", "\nfun ust() = 1\nobject Kimlikler"),
        ("\nobject Kimlikler", "\nimport java.lang.Runtime\nobject Kimlikler"),
    ],
)
def test_kimlikler_saf_degil(eski: str, yeni: str) -> None:
    assert eski in KIMLIK
    ihlaller = kt.kimlikler_saf_mi(KIMLIK.replace(eski, yeni, 1).encode(), "Kimlikler.kt")
    assert ihlaller, (eski, yeni)


# ================================================================================ onarım


def _oku(base: str, head: str) -> Any:
    return lambda ref, _yol: (base if ref == "base" else head).encode()


def test_repair_yalniz_kimlik_degeri() -> None:
    yol = f"app/src/androidTest/java/{LIB}/ekranlar/Kimlikler.kt"
    head = KIMLIK.replace('"nav-catalog"', '"nav-katalog"')
    r = kt.repair_farki([("M", yol)], _oku(KIMLIK, head), kok="app/src/androidTest/java")
    assert r["ok"], r
    assert r["testid_changes"] == [
        {"key": "Menu.KATALOG", "from": "nav-catalog", "to": "nav-katalog", "file": yol}
    ]


@pytest.mark.parametrize(
    ("degisen", "head", "kod"),
    [
        ([("M", "app/src/androidTest/java/x/GirisEkrani.kt")], KIMLIK, "non_locator_file_changed"),
        (
            [("A", f"app/src/androidTest/java/{LIB}/ekranlar/Kimlikler.kt")],
            KIMLIK,
            "locator_file_added",
        ),
        (
            [("M", f"app/src/androidTest/java/{LIB}/ekranlar/Kimlikler.kt")],
            KIMLIK.replace('    const val CIKIS = "nav-logout"\n', ""),
            "locator_keys_changed",
        ),
        (
            [("M", f"app/src/androidTest/java/{LIB}/ekranlar/Kimlikler.kt")],
            KIMLIK.replace('"nav-catalog"', '"nav-$x"'),
            "locator_file_impure",
        ),
    ],
)
def test_repair_reddeder(degisen: list[tuple[str, str]], head: str, kod: str) -> None:
    r = kt.repair_farki(degisen, _oku(KIMLIK, head), kok="app/src/androidTest/java")
    assert not r["ok"]
    assert kod in {v["code"] for v in r["violations"]}


# ============================================================================ kök, dosya adı


def test_kok_coz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_ANDROID_KOTLIN_ROOT", raising=False)
    monkeypatch.delenv("TP_ANDROID_KOTLIN_ROOT_ANDROID", raising=False)
    assert kt.kok_coz(None) == "app/src/androidTest/java"
    monkeypatch.setenv("TP_ANDROID_KOTLIN_ROOT", "/a/java/")
    assert kt.kok_coz(None) == "a/java"
    monkeypatch.setenv("TP_ANDROID_KOTLIN_ROOT_ANDROID", "b/java")
    assert kt.kok_coz(None) == "b/java"

    @dataclass
    class Cfg:
        dil_kokleri: dict[str, str]

    assert kt.kok_coz(Cfg({"TP_ANDROID_KOTLIN_ROOT": "c/java"})) == "c/java"


@pytest.mark.parametrize(
    ("yol", "gecerli"),
    [
        (GOLDEN_YOL, True),
        ("com/x/GirisTesti.kt", True),
        ("../x/A.kt", False),
        ("/abs/A.kt", False),
        ("com/x/A.java", False),
        ("A.kt", False),
        ("com/x y/A.kt", False),
    ],
)
def test_validate_test_file(yol: str, gecerli: bool) -> None:
    if gecerli:
        assert kt.EKLENTI.validate_test_file(yol) == yol
    else:
        with pytest.raises(ValueError):
            kt.validate_test_file(yol)


# ==================================================================== forge (git) üzerinden


@dataclass
class _Cfg:
    git_timeout_s: float = 60
    dil_kokleri: dict[str, str] | None = None


@dataclass
class _Head:
    repo: Path
    sha: str


@dataclass
class _Req:
    platform: str = "android"
    ast_guard_mode: str = "pr"
    test_files: list[str] | None = None


def _kutuphane_dosyalari(kok: str) -> dict[str, str | None]:
    return {
        f"{kok}/{p.relative_to(DEMO_KOK).as_posix()}": p.read_text(encoding="utf-8")
        for p in DEMO_KOK.rglob("*.kt")
    }


def test_forge_symbols_guard_ve_run_static(forge: Forge) -> None:
    kok = "app/src/androidTest/java"
    cfg = _Cfg(dil_kokleri={"TP_ANDROID_KOTLIN_ROOT": kok})
    base = forge.commit("main", _kutuphane_dosyalari(kok), "kütüphane")
    t = kt.EKLENTI.symbols(cfg, base, forge.bare, "android")
    assert t["paket"] == "com.antreklabs.bayisiparis.tp" and len(t["page_objects"]) == 5

    rapor = kt.EKLENTI.guard(cfg, forge.bare, base, base, "pr", "android")
    assert rapor["ok"], rapor

    # Onarım: yalnız kimlik değeri değişir → geçer.
    kimlik_yolu = f"{kok}/{LIB}/ekranlar/Kimlikler.kt"
    head = forge.commit("onarim", {kimlik_yolu: KIMLIK.replace('"nav-catalog"', '"nav-katalog"')})
    rapor = kt.EKLENTI.guard(cfg, forge.bare, base, head, "repair", "android")
    assert rapor["ok"], rapor
    assert rapor["testid_changes"][0]["to"] == "nav-katalog"

    # Kötü üretilen test → /check statik adımı kırmızı (koşu adımı yok: musteri_ci).
    kotu = _degistir('"150,00 TL"', '"${System.exit(0)}"').decode()
    head = forge.commit("kotu", {f"{kok}/{GOLDEN_YOL}": kotu})
    steps: dict[str, dict[str, Any]] = {}
    out = kt.EKLENTI.run_static(
        cfg, _Req(test_files=[GOLDEN_YOL]), _Head(forge.bare, head), base, None, steps
    )
    assert set(out) == {"guard"}
    assert not out["guard"]["ok"]
    assert {v["code"] for v in out["guard"]["report"]["violations"]} == {"forbidden_argument"}

    # Eksik test dosyası açık hata.
    steps = {}
    out = kt.EKLENTI.run_static(
        cfg,
        _Req(test_files=[f"{LIB}/uretilen/YokC1_00000000Test.kt"]),
        _Head(forge.bare, base),
        base,
        None,
        steps,
    )
    assert out["guard"]["missing_test_files"]


def test_statik_deps_kilidi_surumleri() -> None:
    """İmaj kilidi (`statik-deps/kotlin.txt`) hash'li ve test sürümleriyle aynı."""
    kilit = (TOOLCHAIN / "statik-deps" / "kotlin.txt").read_text(encoding="utf-8")
    assert re.search(r"^tree-sitter==0\.26\.1 ", kilit, re.M)
    assert re.search(r"^tree-sitter-kotlin==1\.1\.0 ", kilit, re.M)
    assert kilit.count("--hash=sha256:") >= 2


def test_kotlin_sembol_fiksturu_guncel(tablo: dict[str, Any]) -> None:
    """Değerlendirme vakalarının `ajan_tablosu` fikstürü demo kütüphanesinden üretilmiş tabloyla
    aynı (kayma yok). Güncelleme: bu modüldeki `sembol_tablosu_dizinden` çıktısı JSON olarak."""
    fikstur = REPO / "core/tests/unit/features/codegen/symbols-kotlin.json"
    assert json.loads(fikstur.read_text(encoding="utf-8")) == tablo

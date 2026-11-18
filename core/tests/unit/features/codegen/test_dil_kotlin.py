"""Ş3 Kotlin / Espresso dil eklentisi (TASARIM test-dilleri §3.3): render, literal süzgeci,
enjeksiyon güvenliği, yollar, bayi sabitleme, sonuç kimliği ve kurulum iskeleti.

Kanıt düzeyi: golden (bayt eşit) + demo deposundaki örnek üretilen testle eşitlik + literallerin
Kotlin kaçış kurallarıyla geri okunması. Gerçek Kotlin derlemesi bu testte YOK (imajda Kotlin
derleyicisi yok; musteri_ci): ayrıştırma düzeyi koruma toolchain `tests/test_kotlin.py`'de
(tree-sitter) golden dosyanın kendisi üzerinde koşar; derleme + koşu müşteri CI'ındadır
(`.github/workflows/mobil-android-kotlin.yml`).

Golden güncelleme:
`TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_dil_kotlin.py`.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from tp_core.audit import content_hash
from tp_core.audit.canonical import sha256_hex
from tp_core.features.ci import parse as ciparse
from tp_core.features.codegen.diller import kotlin as kt
from tp_core.features.codegen.render import GizliSizinti, RenderError, RenderInput

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RULES = REPO / "rules"
GOLDEN = HERE / "golden" / "TPD1AndroidC2_3f9b1c2eTest.kt"
DEMO_KOK = "demo-app/mobile/android-test/java"
DEMO_LIB = REPO / DEMO_KOK / "com/antreklabs/bayisiparis/tp"
CASE_ID = uuid.UUID("3f9b1c2e-0000-5000-8000-0000000000c2")
DEALERS = {
    "bayi1": {"password": "Demo123!", "name": "Merkez Bayi"},
    "bayi2": {"password": "Demo123!", "name": "Sahil Bayi"},
}
APP_GOLDEN = json.loads(
    (RULES / "replay/verify_and_map_app/golden/TPD-1-C2-android.json").read_text("utf-8")
)
CASES = json.loads((RULES / "replay/case_generation/golden/TPD-1.json").read_text("utf-8"))[
    "output"
]["cases"]
JAVA_SEMBOLLER = json.loads((HERE / "symbols-java.json").read_text(encoding="utf-8"))


def girdi(**over: Any) -> RenderInput:
    case = over.pop("case", CASES[1])
    alanlar: dict[str, Any] = {
        "case_id": CASE_ID,
        "case": case,
        "sira_no": 2,
        "story_key": "TPD-1",
        "test_key": "TPD-12",
        "case_hash": content_hash(case),
        "mode": "replay",
        "bundle_hash": "b" * 64,
        "mapping": over.pop("mapping", APP_GOLDEN["output"]),
        "dealers": DEALERS,
        "e2e_root": DEMO_KOK,
    }
    alanlar.update(over)
    return RenderInput(**alanlar)


def kt_coz(literal: str) -> str:
    """Şablonun bastığı Kotlin dize literalini geri okur (yalnız izinli kaçışlar)."""
    assert re.fullmatch(r'"(?:[^"\\$\n\r]|\\[\\"nrt$])*"', literal), literal
    return re.sub(
        r"\\(.)",
        lambda m: {"n": "\n", "r": "\r", "t": "\t"}.get(m.group(1), m.group(1)),
        literal[1:-1],
    )


# ============================================================================ golden


def test_golden_bayt_esit_ve_demo_ornegi_ayni() -> None:
    r = kt.render(girdi(), None, RULES)
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(r.content, encoding="utf-8")
        (REPO / r.repo_path).write_text(r.content, encoding="utf-8")
    assert r.content == GOLDEN.read_text(encoding="utf-8")
    # Demo deposundaki örnek üretilen test golden'ın aynısıdır (iş akışı onu derler ve koşar).
    assert (REPO / r.repo_path).read_text(encoding="utf-8") == r.content
    assert r.repo_path == (
        f"{DEMO_KOK}/com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
    )
    assert r.test_file == "com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
    assert (r.dil, r.sinif_adi, r.test_adi, r.dealer) == (
        "kotlin",
        "TPD1AndroidC2_3f9b1c2eTest",
        "senaryo",
        "bayi1",
    )
    assert not r.dogrulanmamis


def test_sablon_hash_basliktadir() -> None:
    kaynak = (RULES / "templates" / kt.TEMPLATE_NAME).read_text(encoding="utf-8")
    r = kt.render(girdi(), None, RULES)
    assert r.template_hash == sha256_hex(kaynak)
    assert f"şablon: {r.template_hash}" in r.content
    assert "kırarak doğrulanmadı" in r.content


def test_uygulama_eslemesi_java_ile_ayni_cagrilari_uretir() -> None:
    """Kotlin ekran nesneleri Java ile ad eşit: aynı eşleme aynı erişimci/metot/argüman dizisi."""
    java = (HERE / "golden" / "TPD1AndroidC2_3f9b1c2eTest.java").read_text(encoding="utf-8")
    kotlin = GOLDEN.read_text(encoding="utf-8")
    cagri = re.compile(r"^\s+([a-z]\w*\(\)\.\w+\(.*\));?$", re.M)
    # Kotlin müşteri CI'ında koşar: koşu hesabı parolası ikamesi yok (case'teki parola literal).
    java = java.replace('System.getenv("TP_TESTVERI_KOSU_BAYI1")', '"Demo123!"')
    assert cagri.findall(java) == cagri.findall(kotlin)


def test_kok_bos_ya_da_java_varsayilaniysa_kotlin_koku() -> None:
    for kok in ("", "e2e", "e2e-app"):
        r = kt.render(girdi(e2e_root=kok), None, RULES)
        assert r.repo_path.startswith(
            f"{kt.KOK_VARSAYILAN}/com/antreklabs/bayisiparis/tp/uretilen/"
        )


def test_paket_sembol_tablosundan() -> None:
    tablo = {"paket": "com.acme.bayi.tp", "page_objects": []}
    r = kt.render(girdi(e2e_root="app/src/androidTest/java"), None, RULES, sembol_tablosu=tablo)
    assert "package com.acme.bayi.tp.uretilen\n" in r.content
    assert "import com.acme.bayi.tp.altyapi.TestTabani\n" in r.content
    assert r.repo_path == (
        "app/src/androidTest/java/com/acme/bayi/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
    )
    for kotu in ("com.Acme", "com..x", "com.in.x", "com.x;", "../x", ""):
        with pytest.raises(RenderError):
            kt.render(girdi(), None, RULES, paket=kotu or "1x")


def test_yalniz_android() -> None:
    class Cati:
        platform = "ios"

    with pytest.raises(RenderError, match="yalnız android"):
        kt.render(girdi(), Cati(), RULES)


def test_bayi_yoksa_bayi_importu_ve_notasyonu_yok() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["step_mapping"] = [s for s in m["step_mapping"] if s["method"] != "girisYap"]
    r = kt.render(girdi(mapping=m), None, RULES)
    assert r.dealer is None
    assert "@Bayi" not in r.content and ".altyapi.Bayi\n" not in r.content


# ============================================================================ literaller


@pytest.mark.parametrize(
    ("deger", "beklenen"),
    [
        ("150,00 TL", '"150,00 TL"'),
        ('a"b\\c', '"a\\"b\\\\c"'),
        ("satır\nalt\tsekme\r", '"satır\\nalt\\tsekme\\r"'),
        ("Çğıöşü İ €", '"Çğıöşü İ €"'),
        ("$ad ${x} $", '"\\$ad \\${x} \\$"'),
        ("\\u0022", '"\\\\u0022"'),
        (7, "7"),
        (-3, "-3"),
        (2**31 - 1, "2147483647"),
        (2**31, "2147483648L"),
        (-(2**63), "-9223372036854775808L"),
        (1.5, "1.5"),
        (1e20, "1e+20"),
        (True, "true"),
        (False, "false"),
    ],
)
def test_kotlin_literal(deger: Any, beklenen: str) -> None:
    assert kt.kotlin_literal(deger) == beklenen


@pytest.mark.parametrize("deger", [None, [1], {"a": 1}, float("nan"), float("inf"), 2**63])
def test_kotlin_literal_reddeder(deger: Any) -> None:
    with pytest.raises(RenderError):
        kt.kotlin_literal(deger)


@pytest.mark.parametrize(
    ("deger", "tur", "beklenen"),
    [
        (7, "double", "7.0"),
        (7, "long", "7L"),
        (7, "int", "7"),
        ("x", "String", '"x"'),
        (True, "boolean", "true"),
    ],
)
def test_tur_uyumu(deger: Any, tur: str, beklenen: str) -> None:
    assert kt.kotlin_literal(deger, tur) == beklenen


@pytest.mark.parametrize(
    ("deger", "tur"), [("7", "int"), (7, "String"), (1.5, "int"), (True, "int"), (2**31, "int")]
)
def test_tur_uyumsuzlugu_reddedilir(deger: Any, tur: str) -> None:
    with pytest.raises(RenderError):
        kt.kotlin_literal(deger, tur)


def test_sembol_tablosu_ile_double_parametre() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["expects"] = [{"po": "SepetEkrani", "method": "dogrulaTutar", "args": [150]}]
    tablo = {
        "paket": kt.VARSAYILAN_KUTUPHANE_PAKETI,
        "page_objects": [
            {
                "class": "SepetEkrani",
                "methods": [{"name": "dogrulaTutar", "params": [{"name": "t", "type": "double"}]}],
            }
        ],
    }
    r = kt.render(girdi(mapping=m), None, RULES, sembol_tablosu=tablo)
    assert "sepetEkrani().dogrulaTutar(150.0)\n" in r.content
    assert "sepetEkrani().dogrulaTutar(150)\n" in kt.render(girdi(mapping=m), None, RULES).content


KOTU = [
    '"); Runtime.getRuntime().exec("x"); //',
    '${Runtime.getRuntime().exec("x")}',
    "$x",
    "\\$x",
    "\\",
    'a\\"',
    "sonda ters bölü\\",
    "\\u0022); Evil(); //",
    "*/ evil(); /*",
    '"""',
    "satır\nkırığı\r\n// yorum",
    "{0} {evil} ${'$'}",
    "ğüşİıÖç € — 😀",
    "\t sekme",
    "",
]


def test_kotu_degerler_kod_olmaz_ve_aynen_geri_okunur() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["expects"] = [
        {"po": "SepetEkrani", "method": "dogrulaMinimumSiparisUyarisi", "args": [d]} for d in KOTU
    ]
    r = kt.render(girdi(mapping=m), None, RULES)
    satirlar = re.findall(
        r"^    sepetEkrani\(\)\.dogrulaMinimumSiparisUyarisi\((.*)\)$", r.content, re.M
    )
    assert len(satirlar) == len(KOTU)
    for ham, deger in zip(satirlar, KOTU, strict=True):
        assert kt_coz(ham) == deger
    # Hiçbir değer başlık/yorum dışında satır kırmaz ya da yorum açmaz.
    assert "Runtime.getRuntime" not in re.sub(r'"(?:[^"\\]|\\.)*"', '""', r.content)


@pytest.mark.parametrize(
    "deger",
    ["\u0085z", "\x00", "\x1b", "\u202e RLO", "sıfır\u200bgenişlik", "\U000e0001", "\ue000"],
)
def test_gorunmez_karakter_reddedilir(deger: str) -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["expects"] = [{"po": "SepetEkrani", "method": "dogrulaToplam", "args": [deger]}]
    with pytest.raises(RenderError, match="basılamayan karakter"):
        kt.render(girdi(mapping=m), None, RULES)


def test_yorum_tek_satir_ve_kacissiz() -> None:
    case = copy.deepcopy(CASES[1])
    case["steps"][0]["action"] = "çok\nsatırlı \\u000a yorum \u202e */ /* \r\n son"
    case["title"] = "başlık\nikinci satır"
    r = kt.render(girdi(case=case), None, RULES)
    for satir in r.content.splitlines():
        if satir.lstrip().startswith("//"):
            assert "\\" not in satir and "\u202e" not in satir
    assert "// başlık ikinci satır\n" in r.content


@pytest.mark.parametrize(
    "ad", ["class", "fun", "val", "in", "is", "object", "1abc", "a-b", "", "ğ"]
)
def test_ident_reddeder(ad: str) -> None:
    with pytest.raises(RenderError):
        kt.kotlin_ident(ad)


def test_esleme_po_ve_metot_tanimlayici_olmali() -> None:
    for alan, deger in (("po", "Sepet Ekrani"), ("method", "x); evil("), ("method", "fun")):
        m = copy.deepcopy(APP_GOLDEN["output"])
        m["expects"] = [
            {"po": "SepetEkrani", "method": "dogrulaToplam", "args": ["1"], alan: deger}
        ]
        with pytest.raises(RenderError):
            kt.render(girdi(mapping=m), None, RULES)


# ============================================================================ gizli veri


def test_gizli_test_verisi_ortamdan_ve_sizmaz() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["step_mapping"][1]["args"] = ["bayi1", "S3cr$t-parola"]
    r = kt.render(
        girdi(mapping=m, gizli_ortam={"S3cr$t-parola": "TP_TESTVERI_PAROLA"}), None, RULES
    )
    assert 'girisEkrani().girisYap("bayi1", testVerisi("TP_TESTVERI_PAROLA"))' in r.content
    assert "S3cr" not in r.content


def test_gizli_deger_kotlin_kacisli_bicimde_de_yakalanir() -> None:
    m = copy.deepcopy(APP_GOLDEN["output"])
    m["expects"] = [{"po": "SepetEkrani", "method": "dogrulaToplam", "args": ['gizli$"deger']}]
    with pytest.raises(GizliSizinti):
        kt.render(girdi(mapping=m, gizli_taranacak=['gizli$"deger']), None, RULES)


# ============================================================================ adlar, yollar


def test_sinif_adi_ve_uretilen_yol() -> None:
    assert kt.sinif_adi("TPD-1", "android", 3, CASE_ID) == "TPD1AndroidC3_3f9b1c2eTest"
    assert kt.sinif_adi(None, "android", 1, CASE_ID) == "SerbestAndroidC1_3f9b1c2eTest"
    assert kt.sinif_adi("x y", "android", 1, CASE_ID) == "SerbestAndroidC1_3f9b1c2eTest"
    assert kt.uretilen_yol(None, "", "TPD-1", 2, CASE_ID) == (
        "app/src/androidTest/java/com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
    )
    assert kt.EKLENTI.uretilen_yol(None, "x/java/", "TPD-1", 2, CASE_ID, paket="com.acme.tp") == (
        "x/java/com/acme/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
    )


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        ("com/acme/tp/testler/GirisTesti.kt", True),
        ("com/acme/tp/SepetTest.kt", True),
        ("com/acme/tp/SepetTests.kt", True),
        ("com/acme/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt", False),
        ("com/acme/tp/ekranlar/GirisEkrani.kt", False),
        ("com/acme/tp/altyapi/TestTabani.kt", False),
        ("com/acme/tp/GirisTesti.java", False),
        ("com/acme/Yardimci.kt", False),
    ],
)
def test_test_dosyasi_mi(yol: str, beklenen: bool) -> None:
    assert kt.test_dosyasi_mi(yol) is beklenen
    assert kt.EKLENTI.test_dosyasi_mi(yol) is beklenen


def test_bayiler_demo_kutuphanesinden() -> None:
    kaynak = (DEMO_LIB / "altyapi/Bayiler.kt").read_text(encoding="utf-8")
    assert kt.parse_dealers(kaynak) == DEALERS


# ===================================================================== musteri_ci kimlik


def test_test_kimligi_ve_donusturucu() -> None:
    fq = "com.antreklabs.bayisiparis.tp.uretilen.TPD1AndroidC2_3f9b1c2eTest"
    dosya, ad = kt.test_kimligi(fq, "senaryo", DEMO_KOK)
    assert (
        dosya == f"{DEMO_KOK}/com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt"
    )
    assert ad == "TPD1AndroidC2_3f9b1c2eTest › senaryo"
    # Üretilen script'in forge yoluyla birebir eşleşir.
    assert dosya == kt.render(girdi(), None, RULES).repo_path
    assert kt.test_kimligi("bozuk ad", "x") == ("bozuk ad", "x")
    satir = ciparse.TestSatiri(test_adi="senaryo", dosya=fq, sonuc="passed", sure_ms=10)
    yeni = kt.kimlik_donusturucu(DEMO_KOK)(satir)
    assert (yeni.dosya, yeni.test_adi) == (dosya, ad)
    assert yeni.sonuc == "passed"


# ===================================================================== kurulum iskeleti


def test_kurulum_iskeleti_paket_degistirilir() -> None:
    dosyalar = kt.kurulum_iskeleti(DEMO_LIB, "app/src/androidTest/java", "com.acme.bayi.tp")
    on = "app/src/androidTest/java/com/acme/bayi/tp"
    assert set(dosyalar) == {f"{on}/{d}" for d in (*kt.ISKELET_DOSYALARI, "ekranlar/Kimlikler.kt")}
    for yol, metin in dosyalar.items():
        assert "com.antreklabs.bayisiparis" not in metin, yol
        assert metin.startswith("package com.acme.bayi.tp."), yol
    assert "object Kimlikler\n" in dosyalar[f"{on}/ekranlar/Kimlikler.kt"]
    with pytest.raises(RenderError):
        kt.kurulum_iskeleti(DEMO_LIB, "x", "Com.Acme")


# ===================================================================== Ş0 sözleşmesi


def test_eklenti_protokolu() -> None:
    e = kt.EKLENTI
    assert (e.ad, e.hat, e.sablon, e.kok_ayari, e.kok_varsayilan, e.gh_is_akisi) == (
        "kotlin",
        "musteri_ci",
        "espresso_junit.kt.j2",
        "TP_ANDROID_KOTLIN_ROOT",
        "app/src/androidTest/java",
        "mobil-android-kotlin",
    )
    assert e.proje_dosyasi.endswith("altyapi/TestTabani.kt")
    assert [k.platformlar for k in e.algila_kaliplari] == [frozenset({"android"})]
    assert e.literal("$") == '"\\$"' and e.ident("girisEkrani") == "girisEkrani"
    assert e.sinif_adi("TPD-1", "android", 2, CASE_ID) == "TPD1AndroidC2_3f9b1c2eTest"
    assert e.eslemeyi_donustur(APP_GOLDEN["output"]) is APP_GOLDEN["output"]
    assert e.render(girdi(), None, RULES).content == GOLDEN.read_text(encoding="utf-8")


def test_java_sembol_tablosundaki_tum_metotlar_kotlin_tanimlayicisi() -> None:
    """Ajan Java/Kotlin tablosundan eşler: tüm sınıf/metot adları Kotlin'de de geçerli olmalı."""
    for po in JAVA_SEMBOLLER["page_objects"]:
        kt.kotlin_ident(po["class"])
        for m in po["methods"]:
            kt.kotlin_ident(m["name"])


# ===================================================================== değerlendirme vakaları


def test_degerlendirme_vakalari_kotlin() -> None:
    """`rules/evaluation/vakalar/verify-and-map-app/kotlin/*.json` Ş8 şemasına uyar: alanlar,
    android platformu, var olan Kotlin tablosu, onaylı case golden'ı."""
    alanlar = {
        "id",
        "story",
        "case_no",
        "platform",
        "baslik",
        "ajan_tablosu",
        "tablo_dili",
        "golden",
        "expects_include",
    }
    dizin = RULES / "evaluation/vakalar/verify-and-map-app/kotlin"
    vakalar = [json.loads(p.read_text("utf-8")) for p in sorted(dizin.glob("*.json"))]
    assert [v["id"] for v in vakalar] == ["tpd-1-c2-android-kotlin", "tpd-4-c2-android-kotlin"]
    for v in vakalar:
        assert set(v) <= alanlar
        assert (v["platform"], v["tablo_dili"]) == ("android", "kotlin")
        tablo = json.loads((REPO / v["ajan_tablosu"]).read_text("utf-8"))
        assert tablo["lang"] == "kotlin"
        metotlar = {
            f"{po['class']}.{m['name']}" for po in tablo["page_objects"] for m in po["methods"]
        }
        cases = json.loads(
            (RULES / f"replay/case_generation/golden/{v['story']}.json").read_text("utf-8")
        )
        assert len(cases["output"]["cases"]) >= v["case_no"]
        assert set(v.get("expects_include") or []) <= metotlar

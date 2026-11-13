"""011 üretim dili (Ş2 render): `render_dil` tek giriş noktası, web + Java şablonu, doğrulanmamış
C# / Python şablonları, `cs_literal` / `py_literal` süzgeçleri ve enjeksiyon güvenliği.

Kanıt düzeyi (şablon başına golden + gerçek araç):
- web + Java: gerçek `java-araclar guard` (jar yoksa atlanır: `toolchain/java-araclar/mvnw -q -B
  package -DskipTests`) ve `javac` — TS sembol tablosundan türetilen SAHTE `e2e-java` iskeletine
  karşı (gerçek `demo-app/e2e-java` varsa guard onu kullanır).
- C#: SDK ile gelen Roslyn `csc` ile sahte NUnit / Playwright / page object tanımlarına karşı TAM
  derleme + literallerin çalıştırılıp değerlerinin geri okunması (`dotnet` yoksa atlanır). Gerçek
  Microsoft.Playwright.NUnit / NUnit paketlerine karşı derleme ve koşu YAPILMAZ.
- Python: `ast.parse` + `compile` + AST biçim denetimi (yalnız `x = Sinif(page)` atamaları ve
  `x.metot(<literal>…)` çağrıları) + literallerin `ast.literal_eval` ile geri okunması.

Golden güncelleme:
`TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_render_dil.py`.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from tp_core.audit import content_hash
from tp_core.features.codegen import checks, render
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.render import RenderError, RenderInput

from .test_checks import FIXTURES, RULES, golden_case, golden_mapping, symbols

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
GOLDEN = HERE / "golden"
JAR = REPO / "toolchain" / "java-araclar" / "target" / "java-araclar.jar"
E2E_JAVA = REPO / "demo-app" / "e2e-java"  # Ş4 yazar; yoksa sahte iskelet kullanılır
SEMBOLLER = json.loads((HERE / "symbols.json").read_text(encoding="utf-8"))
CASE_ID = uuid.UUID("3f9b1c2e-0000-5000-8000-0000000000c2")
DEALERS = {
    "bayi1": {"password": "Demo123!", "name": "Merkez Bayi"},
    "bayi2": {"password": "Demo123!", "name": "Sahil Bayi"},
}
GOLDEN_NOLAR = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
# TS page object metodu `goto` Java'da ayrılmış sözcüktür; Java adı tek kaynak tablodan
# (011 §2.5 "birebir" kuralının tek istisnası).
JAVA_GOTO = platformlar.JAVA_AD_ESLEME["goto"]
UYARI = (
    "Doğrulanmamış çıktı: adımlar tarayıcıda doğrulandı; bu kod derlenmedi ve koşulmadı; "
    "page object kütüphanesi TypeScript tablosundan türetilen adları varsayar."
)

# Case metninden gelebilecek kötü niyetli / kenar değerler: hiçbiri koda dönüşmemeli.
KOTU = [
    '"); System.exit(0); //',
    '"); Environment.Exit(0); //',
    "'); import os; os.system('x') #",
    '"\n    __import__("os").system("x")\n    x = ("',
    "satır\nkırığı\r\n// yorum",
    "*/ evil(); /*",
    '"""',
    "'''",
    '""" + __import__("os").getcwd() + """',
    "\\",
    'a\\"',
    "sonda ters bölü\\",
    "\\u0022); Evil(); //",
    "\\x22",
    "\\N{QUOTATION MARK}",
    "\\0",
    "{0} {evil} ${x} {{ }}",
    '$"{Environment.Exit(0)}"',
    '@"verbatim"',
    "f\"{__import__('os')}\"",
    "%s %d %(x)s",
    "#if DEBUG",
    "\n#error x",
    "# -*- coding: utf-7 -*-",
    "ğüşİıÖç € — 😀",
    "\t sekme",
    "",
]
# Kontrol / biçim / satır ayırıcı karakterler: C# ve Python'da `\uXXXX` ile basılır (Java reddeder).
KOTU_GORUNMEZ = [
    " x y\u0085z",
    "\x00\x01\x1b\x7f",
    "‮RLO⁦ yön",
    "sıfır​genişlik﻿",
    "\U000e0001 etiket",
    "\x0b\x0c",
    " özel",
]


def girdi(n: int = 2, **over: Any) -> RenderInput:
    case = over.pop("case", golden_case(n))
    mapping = over.pop("mapping", golden_mapping(n))
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
    }
    alanlar.update(over)
    return RenderInput(**alanlar)


def java_web_eslemesi(mapping: dict[str, Any]) -> dict[str, Any]:
    m = copy.deepcopy(mapping)
    for item in [*m["step_mapping"], *m["expects"]]:
        if item["method"] == "goto":
            item["method"] = JAVA_GOTO
    return m


def java_web_girdi(n: int = 2, **over: Any) -> RenderInput:
    over.setdefault("mapping", java_web_eslemesi(golden_mapping(n)))
    over.setdefault("e2e_root", "e2e-java")
    return girdi(n, **over)


def kotu_esleme(degerler: list[str], n: int = 5) -> dict[str, Any]:
    """Golden eşleme + her kötü değer için bir `CartPage.expectMinOrderWarning(<değer>)`."""
    m = copy.deepcopy(golden_mapping(n))
    m["expects"] = [
        {"po": "CartPage", "method": "expectMinOrderWarning", "args": [d]} for d in degerler
    ]
    return m


def golden_karsilastir(ad: str, icerik: str) -> None:
    hedef = GOLDEN / ad
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.write_text(icerik, encoding="utf-8")
    assert icerik == hedef.read_text(encoding="utf-8")


# ====================================================================== render_dil: yönlendirme


@pytest.mark.parametrize("n", [2, 5, 8])
def test_render_dil_ts_bugunku_ciktiyi_bayt_bayt_korur(n: int) -> None:
    r = render.render_dil(girdi(n), dil="ts", platform="web", rules=RULES)
    assert r == render.render_test(girdi(n), RULES)
    assert r.content == (GOLDEN / f"tpd-1-c{n}.spec.ts").read_text(encoding="utf-8")
    assert r.kaynak == r.content
    assert r.repo_path == f"e2e/tests/generated/tpd-1-c{n}-3f9b1c2e.spec.ts"
    assert (r.dil, r.sinif_adi, r.dogrulanmamis, r.referans_dil) == ("ts", None, False, None)
    assert r.test_adi is not None and r.test_adi.endswith(" @tp-uretilen")
    assert json.dumps(r.test_adi, ensure_ascii=False) in r.content


def test_render_dil_uygulama_java_bugunku_ciktiyi_bayt_bayt_korur() -> None:
    from .test_platform import _girdi as app_girdi

    r = render.render_dil(app_girdi(), dil="java", platform="android", rules=RULES)
    assert r == render.render_java_test(app_girdi(), "android", RULES)
    assert r.content == (GOLDEN / "TPD1AndroidC2_3f9b1c2eTest.java").read_text(encoding="utf-8")
    assert (r.dil, r.sinif_adi, r.test_adi) == ("java", "TPD1AndroidC2_3f9b1c2eTest", "senaryo")
    assert not r.dogrulanmamis


def test_mevcut_sablonlar_degismedi() -> None:
    """ts ve uygulama-Java şablonları 011'de değişmez (şablon hash'i golden başlığındadır)."""
    for sablon, golden in (
        ("playwright_test.ts.j2", "tpd-1-c2.spec.ts"),
        ("appium_testng.java.j2", "TPD1AndroidC2_3f9b1c2eTest.java"),
    ):
        ozet = render.sha256_hex((RULES / "templates" / sablon).read_text(encoding="utf-8"))
        assert f"şablon: {ozet}" in (GOLDEN / golden).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("dil", "platform"),
    [
        ("ts", "android"),
        ("csharp", "ios"),
        ("python", "windows"),
        ("kotlin", "web"),
        ("", "web"),
        ("TS", "web"),
        ("java", "mac"),
        ("ts", ""),
    ],
)
def test_render_dil_gecersiz_cift(dil: str, platform: str) -> None:
    with pytest.raises(RenderError):
        render.render_dil(girdi(), dil=dil, platform=platform, rules=RULES)


def test_render_dil_gecerli_ciftler() -> None:
    """§2.1: web × her dil; uygulama × yalnız java."""
    from .test_platform import _girdi as app_girdi

    for dil in render.DILLER:
        inp = java_web_girdi() if dil == "java" else girdi()
        assert render.render_dil(inp, dil=dil, platform="web", rules=RULES).dil == dil
    for platform in ("android", "ios", "windows"):
        r = render.render_dil(app_girdi(), dil="java", platform=platform, rules=RULES)
        assert f'"{platform}"' in r.content


# ============================================================================ web + Java


def test_web_java_golden_cikti() -> None:
    r = render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES)
    golden_karsilastir("TPD1WebC2_3f9b1c2eTest.java", r.content)
    assert r.repo_path == (
        "e2e-java/src/test/java/com/antreklabs/bayi/uretilen/TPD1WebC2_3f9b1c2eTest.java"
    )
    assert r.test_file == "src/test/java/com/antreklabs/bayi/uretilen/TPD1WebC2_3f9b1c2eTest.java"
    assert (r.dil, r.sinif_adi, r.test_adi, r.dealer) == (
        "java", "TPD1WebC2_3f9b1c2eTest", "senaryo", "bayi1",
    )  # fmt: skip
    assert not r.dogrulanmamis
    k = r.content
    assert k.startswith("// AI-generated — AI Testing Probe (CasesToCode).")
    assert "// Eşleme: verify_and_map · platform: web · dil: java · mod: replay · bundle: " in k
    assert '@Bayi("bayi1")\npublic class TPD1WebC2_3f9b1c2eTest extends TestTabani {' in k
    # §2.5: gruplar [uretilen, web, tp-case-<uuid>] (+ story), page object adları TS ile aynı.
    assert f'@Test(groups = {{"uretilen", "web", "tp-case-{CASE_ID}", "TPD-1"}}, ' in k
    assert '    loginPage().login("bayi1", "Demo123!");' in k
    assert '    catalogPage().addToCart("P-001", 7);' in k
    assert '    cartPage().expectTotal("150,00 TL");' in k
    # Guard izin listesi: yalnız üç import; Playwright türü / ham sürücü yok.
    assert re.findall(r"^import (.*);$", k, re.M) == [
        "com.antreklabs.bayi.altyapi.Bayi",
        "com.antreklabs.bayi.altyapi.TestTabani",
        "org.testng.annotations.Test",
    ]
    for yasak in ("playwright", "Page ", "page()", "driver", "\\u", "/*", "await"):
        assert yasak not in k, yasak


def test_web_java_e2e_koku_ve_deterministik() -> None:
    a = render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES)
    assert a == render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES)
    b = render.render_dil(
        java_web_girdi(e2e_root="demo-app/e2e-java/"), dil="java", platform="web", rules=RULES
    )
    assert b.repo_path.startswith("demo-app/e2e-java/src/test/java/") and b.content == a.content
    c = render.render_dil(java_web_girdi(e2e_root=""), dil="java", platform="web", rules=RULES)
    assert c.repo_path.startswith("e2e-java/src/test/java/")
    # Uygulama Java'sıyla aynı case: ayrı sınıf / dosya (aynı pakette çakışmaz), ayrı şablon.
    from .test_platform import _girdi as app_girdi

    d = render.render_java_test(app_girdi(), "android", RULES)
    assert d.sinif_adi != a.sinif_adi and d.template_hash != a.template_hash


def test_web_java_ayrilmis_sozcuk_metot_adi_reddedilir() -> None:
    """TS `LoginPage.goto` Java'da metot adı olamaz: derlenmeyen kaynak yerine açık hata."""
    with pytest.raises(RenderError, match="ayrılmış sözcüğü"):
        render.render_dil(girdi(e2e_root="e2e-java"), dil="java", platform="web", rules=RULES)
    for ad in ("goto", "class", "new", "_", "int"):
        with pytest.raises(RenderError):
            render.java_ident(ad)
    assert render.java_ident("girisYap") == "girisYap"


def test_web_java_sablonu_enjeksiyona_kapali() -> None:
    m = java_web_eslemesi(golden_mapping(2))
    m["expects"][-1]["args"] = ['"); Runtime.getRuntime().exec("x']
    k = render.render_dil(java_web_girdi(mapping=m), dil="java", platform="web", rules=RULES)
    assert 'expectTotal("\\"); Runtime.getRuntime().exec(\\"x");' in k.content
    for kotu_deger in KOTU_GORUNMEZ:  # görünmez / kontrol karakteri: Java'da değer reddedilir
        m = java_web_eslemesi(golden_mapping(2))
        m["expects"][-1]["args"] = [kotu_deger]
        with pytest.raises(RenderError):
            render.render_dil(java_web_girdi(mapping=m), dil="java", platform="web", rules=RULES)
    m = java_web_eslemesi(golden_mapping(2))
    m["expects"][0]["method"] = "expectTotal(); x"
    with pytest.raises(RenderError):
        render.render_dil(java_web_girdi(mapping=m), dil="java", platform="web", rules=RULES)
    m = java_web_eslemesi(golden_mapping(2))
    m["expects"][0]["po"] = "Cart$Page"
    with pytest.raises(RenderError):
        render.render_dil(java_web_girdi(mapping=m), dil="java", platform="web", rules=RULES)


# ------------------------------------------------------- sahte e2e-java iskeleti (guard + javac)

_JAVA_TUR = {"string": "String", "number": "double", "boolean": "boolean"}
_PAKET = "src/test/java/com/antreklabs/bayi"


def _sahte_e2e_java(kok: Path) -> Path:
    """TS sembol tablosundan §2.5 konvansiyonunda en küçük Java projesi (yalnız imzalar)."""
    altyapi, ekranlar = kok / _PAKET / "altyapi", kok / _PAKET / "ekranlar"
    for d in (altyapi, ekranlar, kok / _PAKET / "uretilen"):
        d.mkdir(parents=True)
    (ekranlar / "Ekran.java").write_text(
        "package com.antreklabs.bayi.ekranlar;\n\npublic abstract class Ekran {}\n", "utf-8"
    )
    erisimciler = []
    for po in SEMBOLLER["page_objects"]:
        sinif = po["class"]
        metotlar = []
        for m in po["methods"]:
            if m["returns"] != "Promise<void>":
                continue  # sözleşme: ekran metodu void döner
            ad = JAVA_GOTO if m["name"] == "goto" else m["name"]
            params = ", ".join(f"{_JAVA_TUR[p['type']]} {p['name']}" for p in m["params"])
            metotlar.append(f"  public void {ad}({params}) {{}}\n")
        (ekranlar / f"{sinif}.java").write_text(
            "package com.antreklabs.bayi.ekranlar;\n\n"
            f"public class {sinif} extends Ekran {{\n{''.join(metotlar)}}}\n",
            "utf-8",
        )
        erisimciler.append(
            f"  protected {sinif} {checks.fixture_name(sinif)}() {{ return new {sinif}(); }}\n"
        )
    importlar = "".join(
        f"import com.antreklabs.bayi.ekranlar.{po['class']};\n" for po in SEMBOLLER["page_objects"]
    )
    (altyapi / "TestTabani.java").write_text(
        f"package com.antreklabs.bayi.altyapi;\n\n{importlar}\n"
        f"public abstract class TestTabani {{\n{''.join(erisimciler)}}}\n",
        "utf-8",
    )
    (altyapi / "Bayi.java").write_text(
        "package com.antreklabs.bayi.altyapi;\n\nimport java.lang.annotation.ElementType;\n"
        "import java.lang.annotation.Retention;\nimport java.lang.annotation.RetentionPolicy;\n"
        "import java.lang.annotation.Target;\n\n@Retention(RetentionPolicy.RUNTIME)\n"
        "@Target(ElementType.TYPE)\npublic @interface Bayi {\n  String value();\n}\n",
        "utf-8",
    )
    return kok


def _sahte_testng(kok: Path) -> Path:
    hedef = kok / "org/testng/annotations"
    hedef.mkdir(parents=True)
    (hedef / "Test.java").write_text(
        "package org.testng.annotations;\n\nimport java.lang.annotation.Retention;\n"
        "import java.lang.annotation.RetentionPolicy;\n\n@Retention(RetentionPolicy.RUNTIME)\n"
        "public @interface Test {\n  String[] groups() default {};\n  String description() "
        'default "";\n}\n',
        "utf-8",
    )
    return kok


def _guard(kok: Path, dosya_adi: str, icerik: str, kimlikler: bool) -> dict[str, Any]:
    hedef = kok / _PAKET / "uretilen" / dosya_adi
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(icerik, encoding="utf-8")
    komut = ["java", "-jar", str(JAR), "guard", "--root", str(kok)]
    komut += ["--kimlikler"] if kimlikler else []
    sonuc = subprocess.run(
        [*komut, "--", str(hedef.relative_to(kok))],
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert sonuc.returncode in (0, 1), sonuc.stderr
    return json.loads(sonuc.stdout)


def _kenar_degerli_web_java() -> render.Rendered:
    m = java_web_eslemesi(golden_mapping(2))
    m["expects"].append(
        {"po": "CartPage", "method": "expectMinOrderWarning",
         "args": ['Minimum "sipariş" tutarı: 750,00 TL\\yeni\nsatır — ğüşİ */ ${x} "); x(); //']}
    )  # fmt: skip
    m["expects"].append({"po": "CatalogPage", "method": "expectCartCount", "args": [-3]})
    m["expects"].append({"po": "CatalogPage", "method": "expectCartCount", "args": [7.5]})
    case = copy.deepcopy(golden_case(2))
    case["title"] = 'baş"lık */ \\ satır\nsonu'
    case["steps"][0]["action"] = "eylem\n    Runtime.getRuntime().exit(1); // \\u000a x();"
    return render.render_dil(
        java_web_girdi(mapping=m, case=case), dil="java", platform="web", rules=RULES
    )


guard_gerekli = pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None,
    reason="java-araclar.jar yok (toolchain/java-araclar/mvnw -q -B package -DskipTests)",
)


@guard_gerekli
def test_web_java_gercek_guard_dan_gecer(tmp_path: Path) -> None:
    """Web şablonu `java-araclar guard`'dan DEĞİŞTİRİLMEDEN geçer (sahte e2e-java iskeleti)."""
    kok = _sahte_e2e_java(tmp_path / "e2e-java")
    for r in (
        render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES),
        _kenar_degerli_web_java(),
    ):
        rapor = _guard(kok, Path(r.test_file).name, r.content, kimlikler=False)
        assert rapor["ok"], rapor["violations"]
        assert rapor["files"] == [r.test_file]


@guard_gerekli
def test_web_java_guard_bozuk_ciktiyi_yakalar(tmp_path: Path) -> None:
    """Kontrol: guard gerçekten koşuyor ve web çıktısında da şablon dışı içeriği reddediyor."""
    kok = _sahte_e2e_java(tmp_path / "e2e-java")
    r = render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES)
    ad = Path(r.test_file).name
    for bozuk, kod in (
        (r.content.replace("catalogPage().openCart();",
                           "catalogPage().openCart(); page().close();"), "raw_driver"),
        (r.content.replace("import org.testng",
                           "import com.microsoft.playwright.Page;\nimport org.testng"),
         "forbidden_import"),
        (r.content.replace('"uretilen", ', ""), "test_annotation"),
        (r.content.replace('addToCart("P-001", 7)', 'addToCart("P-001", "7")'), "arg_type"),
    ):  # fmt: skip
        assert bozuk != r.content
        rapor = _guard(kok, ad, bozuk, kimlikler=False)
        assert not rapor["ok"] and kod in {v["code"] for v in rapor["violations"]}, rapor


@guard_gerekli
@pytest.mark.skipif(not E2E_JAVA.is_dir(), reason="demo-app/e2e-java bu dalda yok (Ş4)")
def test_web_java_gercek_e2e_java_guard_dan_gecer(tmp_path: Path) -> None:
    """Birleştirme sonrası: gerçek hedef projeye karşı guard (golden C2'deki TS adlarıyla)."""
    kok = tmp_path / "e2e-java"
    shutil.copytree(E2E_JAVA, kok, ignore=shutil.ignore_patterns("target", ".mvn"))
    r = render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES)
    rapor = _guard(kok, Path(r.test_file).name, r.content, kimlikler=True)
    assert rapor["ok"], rapor["violations"]


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac yok")
def test_web_java_javac_ile_derlenir(tmp_path: Path) -> None:
    """Üretilen kaynak gerçek derleyiciden geçer (sahte TestTabani / page object / TestNG'ye
    karşı); kötü değerler koda dönüşseydi derleme ya da sınıf sayısı bozulurdu."""
    kok = _sahte_e2e_java(tmp_path / "e2e-java")
    testng = _sahte_testng(tmp_path / "testng")
    uretilenler = [
        render.render_dil(java_web_girdi(n), dil="java", platform="web", rules=RULES)
        for n in GOLDEN_NOLAR
        if n != 2
    ] + [_kenar_degerli_web_java()]
    for r in uretilenler:
        (kok / r.test_file).write_text(r.content, encoding="utf-8")
    cikti = tmp_path / "siniflar"
    kaynaklar = [str(p) for p in [*kok.rglob("*.java"), *testng.rglob("*.java")]]
    sonuc = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-Xlint:all", "-Werror", "-d", str(cikti), *kaynaklar],
        capture_output=True, text=True, timeout=180, check=False,
    )  # fmt: skip
    assert sonuc.returncode == 0, sonuc.stdout + sonuc.stderr
    uretilen_siniflar = sorted(
        p.stem for p in (cikti / "com/antreklabs/bayi/uretilen").glob("*.class")
    )
    # Her dosya tam bir sınıf üretir (iç / anonim sınıf yok).
    assert uretilen_siniflar == sorted(str(r.sinif_adi) for r in uretilenler)


# ================================================================== cs_literal / py_literal


@pytest.mark.parametrize(
    ("deger", "cs", "py"),
    [
        ("150,00 TL", '"150,00 TL"', '"150,00 TL"'),
        ('a"b\\c', '"a\\"b\\\\c"', '"a\\"b\\\\c"'),
        ("satır\nalt\tsekme\r", '"satır\\nalt\\tsekme\\r"', '"satır\\nalt\\tsekme\\r"'),
        ("Çğıöşü İ € 😀", '"Çğıöşü İ € 😀"', '"Çğıöşü İ € 😀"'),  # yazdırılabilir: ham UTF-8
        ("\\u0022", '"\\\\u0022"', '"\\\\u0022"'),  # ters bölü çiftlenir: kaçış oluşmaz
        ("{0} ${x} {{", '"{0} ${x} {{"', '"{0} ${x} {{"'),  # önek yok: interpolasyon olamaz
        ("'tek' '''", "\"'tek' '''\"", "\"'tek' '''\""),
        ('"""', '"\\"\\"\\""', '"\\"\\"\\""'),
        ("\x00", '"\\u0000"', '"\\u0000"'),
        ("a b c\u0085d", '"a\\u2028b\\u2029c\\u0085d"', '"a\\u2028b\\u2029c\\u0085d"'),
        ("‮​", '"\\u202e\\u200b"', '"\\u202e\\u200b"'),
        ("\U000e0001", '"\\U000e0001"', '"\\U000e0001"'),
        ("", '""', '""'),
        (7, "7", "7"),
        (-3, "-3", "-3"),
        (0, "0", "0"),
        (2**31 - 1, "2147483647", "2147483647"),
        (2**31, "2147483648L", "2147483648"),
        (-(2**31), "-2147483648", "-2147483648"),
        (-(2**63), "-9223372036854775808L", "-9223372036854775808"),
        (7.0, "7.0", "7.0"),  # ondalık tamsayıya düşmez
        (1.5, "1.5", "1.5"),
        (-0.25, "-0.25", "-0.25"),
        (1e20, "1e+20", "1e+20"),
        (1e-7, "1e-07", "1e-07"),
        (True, "true", "True"),
        (False, "false", "False"),
        (None, "null", "None"),
    ],
)
def test_cs_py_literal(deger: Any, cs: str, py: str) -> None:
    assert render.cs_literal(deger) == cs
    assert render.py_literal(deger) == py


@pytest.mark.parametrize(
    "deger",
    [float("nan"), float("inf"), float("-inf"), "\ud800", "a\udfffb", [1], (1, 2), {"a": 1},
     b"bayt", object(), 1 + 2j],
)  # fmt: skip
def test_cs_py_literal_reddeder(deger: Any) -> None:
    with pytest.raises(RenderError):
        render.cs_literal(deger)
    with pytest.raises(RenderError):
        render.py_literal(deger)


def test_cs_literal_long_asimi_ve_py_buyuk_tamsayi() -> None:
    for deger in (2**63, -(2**63) - 1):
        with pytest.raises(RenderError):
            render.cs_literal(deger)
    assert render.py_literal(2**70) == str(2**70)  # Python tamsayısı sınırsız


@pytest.mark.parametrize("deger", [*KOTU, *KOTU_GORUNMEZ])
def test_py_literal_geri_okunur_ve_tek_dugumdur(deger: str) -> None:
    """Literal tek bir `Constant` düğümüdür ve değeri AYNEN geri okunur (kod parçası olamaz)."""
    metin = render.py_literal(deger)
    agac = ast.parse(metin, mode="eval")
    assert isinstance(agac.body, ast.Constant) and agac.body.value == deger
    assert ast.literal_eval(metin) == deger
    assert "\n" not in metin and "\r" not in metin and metin.isprintable()
    # Çağrı içinde de tek argüman.
    cagri = ast.parse(f"f({render.py_args([deger, 1, deger])})", mode="eval").body
    assert isinstance(cagri, ast.Call) and len(cagri.args) == 3


@pytest.mark.parametrize("deger", [*KOTU, *KOTU_GORUNMEZ])
def test_cs_literal_tek_satir_duz_dize(deger: str) -> None:
    metin = render.cs_literal(deger)
    assert metin.startswith('"') and metin.endswith('"') and metin.isprintable()
    # Gövdede kaçışsız çift tırnak yok; C# kaçışları Python'un düz dize kaçışlarının alt kümesi:
    # aynı metin Python'da da aynı değeri verir.
    assert re.fullmatch(r'"(?:[^"\\]|\\[\\"nrt]|\\u[0-9a-f]{4}|\\U[0-9a-f]{8})*"', metin)
    assert ast.literal_eval(metin) == deger


@pytest.mark.parametrize(
    ("deger", "beklenen"),
    [
        ("düz metin", "düz metin"),
        ("satır\nsonu\r\n*/ kod();", "satır sonu */ kod();"),
        ("a b c\u0085d", "a b c d"),
        ("‮ters⁦ ​sıfır﻿", "ters sıfır"),
        ("", "-"),
        (None, "-"),
        ("\\u000a x();", "\\u000a x();"),  # C# / Python yorumda Unicode kaçışı işlemez
    ],
)
def test_cs_py_yorum_tek_satir(deger: Any, beklenen: str) -> None:
    assert render.cs_comment(deger) == beklenen
    assert render.py_comment(deger) == beklenen
    assert len(render.cs_comment("x" * 500)) == 160


def test_ad_turetme() -> None:
    assert render.cs_method_name("addToCart") == "AddToCartAsync"
    assert render.cs_method_name("goto") == "GotoAsync"
    assert render.cs_method_name("expectHTTPStatus") == "ExpectHTTPStatusAsync"
    assert render.cs_method_name("loadAsync") == "LoadAsync"  # sonek iki kez eklenmez
    assert render.cs_variable_name("CartPage") == "cartPage"
    assert render.cs_variable_name("Object") == "objectNesnesi"  # C# anahtar sözcüğü
    assert render.py_name("addToCart") == "add_to_cart"
    assert render.py_name("expectLineQuantity") == "expect_line_quantity"
    assert render.py_name("expectHTTPStatus") == "expect_http_status"
    assert render.py_name("LoginPage") == "login_page"
    assert render.py_name("goto") == "goto"
    assert render.py_name("step2Done") == "step2_done"
    assert render.py_name("pass") == "pass_" and render.py_name("Import") == "import_"
    # C# sınıf adı web + Java adıyla aynı kural (`…WebC<n>_<uuid8>Test` + `s`).
    assert render.cs_class_name("TPD-1", 2, CASE_ID) == "TPD1WebC2_3f9b1c2eTests"
    assert render.cs_class_name("TPD-1", 2, CASE_ID) == (
        render.java_class_name("TPD-1", "web", 2, CASE_ID) + "s"
    )
    assert render.cs_class_name("../x", 3, CASE_ID) == "SerbestWebC3_3f9b1c2eTests"
    assert render.py_test_name("TPD-1", 2, CASE_ID) == "test_tpd_1_c2_3f9b1c2e"
    assert render.py_test_name(None, 3, CASE_ID) == "test_serbest_c3_3f9b1c2e"
    for kotu in ("a b", "a;b", "a$b", "é", "", "1a", "a-b", "a\nb", None, 7):
        for f in (render.cs_ident, render.py_ident, render.cs_method_name, render.py_name):
            with pytest.raises(RenderError):
                f(kotu)  # type: ignore[arg-type]
    for f, ad in (
        (render.cs_ident, "class"),
        (render.cs_method_name, "_"),  # `_` C#'ta yok sayma (discard) adıdır
        (render.py_ident, "lambda"),
        (render.py_ident, "__class__"),
        (render.py_name, "__import__"),
        (render.py_name, "_ozel"),
    ):
        with pytest.raises(RenderError):
            f(ad)


# ================================================================================== Python


def _py_yapi(kaynak: str) -> dict[str, Any]:
    """Üretilen Python dosyasının AST'si yalnız izinli biçimi taşır; çağrıları döndürür."""
    agac = ast.parse(kaynak)
    compile(kaynak, "uretilen.py", "exec")  # sözdizimi + derleme (çalıştırılmaz)
    *importlar, islev = agac.body
    assert isinstance(importlar[0], ast.Import) and [a.name for a in importlar[0].names] == [
        "pytest"
    ]
    moduller = {}
    for imp in importlar[1:]:
        assert isinstance(imp, ast.ImportFrom) and imp.level == 0 and len(imp.names) == 1
        assert imp.names[0].asname is None
        moduller[imp.module] = imp.names[0].name
    assert moduller.pop("playwright.sync_api") == "Page"
    assert all(m.startswith("pages.") for m in moduller)
    assert isinstance(islev, ast.FunctionDef) and not ast.get_docstring(islev)
    assert [a.arg for a in islev.args.args] == ["page"]
    isaretler = []
    for d in islev.decorator_list:
        hedef = d.func if isinstance(d, ast.Call) else d
        assert isinstance(hedef, ast.Attribute) and ast.unparse(hedef.value) == "pytest.mark"
        degerler = [a.value for a in d.args] if isinstance(d, ast.Call) else []
        if isinstance(d, ast.Call):
            assert all(isinstance(a, ast.Constant) for a in d.args) and not d.keywords
        isaretler.append((hedef.attr, *degerler))
    nesneler, cagrilar = {}, []
    for deyim in islev.body:
        if isinstance(deyim, ast.Assign):
            assert not cagrilar, "nesne atamaları çağrılardan önce gelir"
            (hedef,) = deyim.targets
            c = deyim.value
            assert isinstance(hedef, ast.Name) and isinstance(c, ast.Call)
            assert isinstance(c.func, ast.Name) and ast.unparse(c) == f"{c.func.id}(page)"
            nesneler[hedef.id] = c.func.id
            continue
        assert isinstance(deyim, ast.Expr) and isinstance(deyim.value, ast.Call), ast.dump(deyim)
        c = deyim.value
        assert isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
        assert c.func.value.id in nesneler and not c.keywords
        cagrilar.append(
            (nesneler[c.func.value.id], c.func.attr, [ast.literal_eval(a) for a in c.args])
        )
    assert set(moduller.values()) == set(nesneler.values())
    # Hiçbir yerde f-string / üç tırnak / lambda / alt çağrı yok.
    for dugum in ast.walk(islev):
        assert not isinstance(dugum, ast.JoinedStr | ast.Lambda | ast.Subscript | ast.BinOp)
    return {"islev": islev.name, "isaretler": isaretler, "moduller": moduller, "cagrilar": cagrilar}


def _beklenen_cagrilar(mapping: dict[str, Any]) -> list[tuple[str, str, list[Any]]]:
    return [
        (i["po"], render.snake_case(i["method"]), list(i["args"]))
        for i in [*mapping["step_mapping"], *mapping["expects"]]
    ]


def test_python_golden_cikti() -> None:
    r = render.render_dil(
        girdi(), dil="python", platform="web", rules=RULES, sembol_tablosu=SEMBOLLER
    )
    # Uzantı `.golden`: pytest `test_*.py` toplar, ruff `.py` denetler; golden ikisine de girmez.
    golden_karsilastir("test_tpd_1_c2_3f9b1c2e.py.golden", r.content)
    assert r.test_file == "tests/generated/test_tpd_1_c2_3f9b1c2e.py"
    assert r.repo_path == "e2e-python/tests/generated/test_tpd_1_c2_3f9b1c2e.py"
    assert (r.dil, r.sinif_adi, r.test_adi, r.dealer) == (
        "python", None, "test_tpd_1_c2_3f9b1c2e", "bayi1",
    )  # fmt: skip
    assert r.dogrulanmamis and r.referans_dil == "ts" and r.kaynak == r.content
    satirlar = r.content.splitlines()
    assert satirlar[0].startswith("# AI-generated — AI Testing Probe (CasesToCode).")
    assert satirlar[2] == f"# {UYARI}"
    yapi = _py_yapi(r.content)
    assert yapi["islev"] == "test_tpd_1_c2_3f9b1c2e"
    assert yapi["isaretler"] == [
        ("uretilen",), ("web",), ("tp_case", str(CASE_ID)), ("story", "TPD-1"), ("dealer", "bayi1"),
    ]  # fmt: skip
    assert yapi["moduller"] == {
        "pages.cart_page": "CartPage",
        "pages.catalog_page": "CatalogPage",
        "pages.login_page": "LoginPage",
    }
    assert yapi["cagrilar"] == _beklenen_cagrilar(golden_mapping(2))
    assert '    catalog_page.add_to_cart("P-001", 7)' in satirlar
    assert '    cart_page.expect_total("150,00 TL")' in satirlar


@pytest.mark.parametrize("n", GOLDEN_NOLAR)
def test_python_tum_goldenlar_gecerli_python(n: int) -> None:
    """TS tablosuyla doğrulanmış her golden eşleme geçerli Python'a render edilir (§2.7)."""
    m = golden_mapping(n)
    sonuc = checks.check_mapping(m, golden_case(n), symbols(), fixtures=FIXTURES)
    # C7: bilinen eksik metot (missing_method) bulgusu; render yine de adları türetebilmeli.
    assert sonuc.ok or {b.tur for b in sonuc.bulgular} == {"missing_method"}
    r = render.render_dil(girdi(n), dil="python", platform="web", rules=RULES)
    assert _py_yapi(r.content)["cagrilar"] == _beklenen_cagrilar(m)


def test_python_enjeksiyona_kapali() -> None:
    degerler = [*KOTU, *KOTU_GORUNMEZ]
    m = kotu_esleme(degerler)
    temiz = render.render_dil(
        girdi(5, mapping=kotu_esleme(["x"] * len(degerler))),
        dil="python", platform="web", rules=RULES,
    )  # fmt: skip
    for kotu_metin in degerler:
        case = copy.deepcopy(golden_case(5))
        case["title"] = kotu_metin
        case["steps"][0]["action"] = kotu_metin
        r = render.render_dil(
            girdi(5, case=case, mapping=m, test_key=kotu_metin, mode=kotu_metin),
            dil="python", platform="web", rules=RULES,
        )  # fmt: skip
        k = r.content
        # Değerler AYNEN literal olarak geri okunur; çağrı listesi eşlemenin aynısıdır.
        assert _py_yapi(k)["cagrilar"] == _beklenen_cagrilar(m)
        # Yorumlar satır açamaz: satır sayısı ve kod satırları temiz girdidekiyle aynı.
        assert len(k.splitlines()) == len(temiz.content.splitlines()) == k.count("\n")
        kod = [s for s in k.splitlines() if s.strip() and not s.lstrip().startswith("#")]
        assert len(kod) == len(
            [s for s in temiz.content.splitlines() if s.strip() and not s.lstrip().startswith("#")]
        )
        # İlk iki satır sabit: kodlama bildirimi (PEP 263) enjekte edilemez.
        assert k.splitlines()[:2] == temiz.content.splitlines()[:2]
        assert k.isprintable() or set(c for c in k if not c.isprintable()) == {"\n"}


# ====================================================================================== C#


def test_csharp_golden_cikti() -> None:
    r = render.render_dil(
        girdi(), dil="csharp", platform="web", rules=RULES, sembol_tablosu=SEMBOLLER
    )
    golden_karsilastir("TPD1WebC2_3f9b1c2eTests.cs", r.content)
    assert r.test_file == "tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    assert r.repo_path == "e2e-csharp/tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    assert (r.dil, r.sinif_adi, r.test_adi, r.dealer) == (
        "csharp", "TPD1WebC2_3f9b1c2eTests", "Senaryo", "bayi1",
    )  # fmt: skip
    assert r.dogrulanmamis and r.referans_dil == "ts"
    k = r.content
    satirlar = k.splitlines()
    assert satirlar[0].startswith("// AI-generated — AI Testing Probe (CasesToCode).")
    assert satirlar[2] == f"// {UYARI}"
    assert re.findall(r"^using (.*);$", k, re.M) == [
        "System.Threading.Tasks",
        "Antreklabs.Bayi.Pages",
        "Microsoft.Playwright.NUnit",
        "NUnit.Framework",
    ]
    assert "public class TPD1WebC2_3f9b1c2eTests : PageTest" in k
    assert f'[Category("tp-case-{CASE_ID}")]' in k and '[Category("uretilen")]' in k
    assert '[Property("dealerUsername", "bayi1")]' in k
    assert '    [Description("7 adet kampanyalı üründe 1 adet bedava verilir")]' in k
    assert "        var loginPage = new LoginPage(Page);" in satirlar
    assert '        await loginPage.LoginAsync("bayi1", "Demo123!");' in satirlar
    assert '        await catalogPage.AddToCartAsync("P-001", 7);' in satirlar
    assert '        await cartPage.ExpectTotalAsync("150,00 TL");' in satirlar
    for yasak in ('$"', '@"', '"""', "/*", "#", "unsafe", "dynamic"):
        assert yasak not in k, yasak


_CS_KOD_SATIRI = re.compile(
    r"^        (?:var [A-Za-z_][A-Za-z0-9_]* = new [A-Za-z_][A-Za-z0-9_]*\(Page\);"
    r"|await [A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\(.*\);)$"
)


def test_csharp_enjeksiyona_kapali_sozdizimsel() -> None:
    degerler = [*KOTU, *KOTU_GORUNMEZ]
    m = kotu_esleme(degerler)
    temiz = render.render_dil(
        girdi(5, mapping=kotu_esleme(["x"] * len(degerler))),
        dil="csharp", platform="web", rules=RULES,
    ).content.splitlines()  # fmt: skip
    for kotu_metin in degerler:
        case = copy.deepcopy(golden_case(5))
        case["title"] = kotu_metin
        case["steps"][0]["action"] = kotu_metin
        k = render.render_dil(
            girdi(5, case=case, mapping=m, test_key=kotu_metin, mode=kotu_metin),
            dil="csharp", platform="web", rules=RULES,
        ).content  # fmt: skip
        satirlar = k.splitlines()
        assert len(satirlar) == len(temiz) == k.count("\n")
        assert set(c for c in k if not c.isprintable()) <= {"\n"}
        for i, (satir, temiz_satir) in enumerate(zip(satirlar, temiz, strict=True)):
            # Yorum satırı yorum kalır, kod satırı kod; başlık ilk üç satırda sabit.
            assert satir.lstrip().startswith("//") == temiz_satir.lstrip().startswith("//"), i
            if satir.startswith("        ") and not satir.lstrip().startswith("//"):
                assert _CS_KOD_SATIRI.match(satir), satir
        # Her kötü değer tek bir düz dize literali olarak tek çağrıda.
        for deger in degerler:
            assert (
                f"        await cartPage.ExpectMinOrderWarningAsync({render.cs_literal(deger)});"
                in satirlar
            )


def test_dogrulanmamis_referans_dil_ve_bos_esleme() -> None:
    for dil, on in (("csharp", "//"), ("python", "#")):
        r = render.render_dil(girdi(), dil=dil, platform="web", rules=RULES, referans_dil="java")
        assert r.referans_dil == "java"
        assert r.content.splitlines()[2] == f"{on} {UYARI.replace('TypeScript', 'Java')}"
        with pytest.raises(RenderError):
            render.render_dil(girdi(), dil=dil, platform="web", rules=RULES, referans_dil="go")
        with pytest.raises(RenderError, match="eşleme boş"):
            render.render_dil(
                girdi(mapping={"step_mapping": [], "expects": []}),
                dil=dil, platform="web", rules=RULES,
            )  # fmt: skip
        # Tam hat dilinde referans_dil yok sayılır.
    assert render.render_dil(
        girdi(), dil="ts", platform="web", rules=RULES, referans_dil="java"
    ) == render.render_test(girdi(), RULES)


def test_dogrulanmamis_bayisiz_ve_serbest_case() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"] = [s for s in m["step_mapping"] if s["method"] != "login"]
    cs = render.render_dil(
        girdi(mapping=m, story_key=None, test_key=None), dil="csharp", platform="web", rules=RULES
    )
    assert cs.dealer is None and "[Property(" not in cs.content
    assert cs.sinif_adi == "SerbestWebC2_3f9b1c2eTests" and "TPD-1" not in cs.content
    py = render.render_dil(
        girdi(mapping=m, story_key=None), dil="python", platform="web", rules=RULES
    )
    assert py.dealer is None and py.test_adi == "test_serbest_c2_3f9b1c2e"
    assert [i[0] for i in _py_yapi(py.content)["isaretler"]] == ["uretilen", "web", "tp_case"]


@pytest.mark.parametrize("dil", ["csharp", "python"])
def test_dogrulanmamis_gecersiz_ad_ve_cakisma(dil: str) -> None:
    def dene(**degisiklik: Any) -> None:
        m = copy.deepcopy(golden_mapping(2))
        m["expects"][0].update(degisiklik)
        with pytest.raises(RenderError):
            render.render_dil(girdi(mapping=m), dil=dil, platform="web", rules=RULES)

    dene(method="expectTotal(); evil")
    dene(method="expect$Total")
    dene(po="Cart Page")
    dene(po="Page")  # şablonun kendi `Page` adıyla çakışır
    dene(args=[{"a": 1}])
    dene(args=[float("nan")])
    dene(args=[["liste"]])
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["po"] = "cartPage"  # `CartPage` ile aynı değişken adına düşer
    with pytest.raises(RenderError, match="aynı değişken"):
        render.render_dil(girdi(mapping=m), dil=dil, platform="web", rules=RULES)


# ------------------------------------------------------------ C#: gerçek derleyici (Roslyn csc)

_CS_TUR = {"string": "string", "number": "double", "boolean": "bool"}


def _dotnet() -> dict[str, Any] | None:
    """SDK ile gelen Roslyn `csc.dll` + başvuru derlemeleri (ağ / NuGet gerekmez)."""
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        return None
    try:
        cikti = subprocess.run(
            [dotnet, "--list-sdks"], capture_output=True, text=True, timeout=60, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for satir in reversed(cikti.strip().splitlines()):
        m = re.match(r"^(\S+) \[(.+)\]$", satir.strip())
        if not m:
            continue
        sdk = Path(m.group(2)) / m.group(1)
        csc = sdk / "Roslyn" / "bincore" / "csc.dll"
        kok = Path(m.group(2)).parent
        refler = sorted((kok / "packs" / "Microsoft.NETCore.App.Ref").glob("*/ref/net*/*.dll"))
        calisma = sorted((kok / "shared" / "Microsoft.NETCore.App").glob("*"))
        if csc.is_file() and refler and calisma:
            return {
                "dotnet": dotnet,
                "csc": csc,
                "refler": refler,
                "tfm": refler[0].parent.name,
                "surum": calisma[-1].name,
            }
    return None


DOTNET = _dotnet()
dotnet_gerekli = pytest.mark.skipif(DOTNET is None, reason="dotnet SDK (Roslyn csc) yok")


def _csc(cikti: Path, kaynaklar: list[Path], hedef: str = "library") -> subprocess.CompletedProcess:
    assert DOTNET is not None
    return subprocess.run(
        [DOTNET["dotnet"], str(DOTNET["csc"]), "-nologo", f"-target:{hedef}", "-langversion:latest",
         "-warnaserror", "-nowarn:CS1701,CS1702", f"-out:{cikti}",
         *[f"-r:{r}" for r in DOTNET["refler"]], *[str(k) for k in kaynaklar]],
        capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip


def _sahte_cs_kutuphaneleri(dizin: Path) -> Path:
    """NUnit öznitelikleri, `PageTest`, `IPage` ve TS tablosundan türetilen page object'ler —
    yalnız imzalar (gerçek paketler DEĞİL)."""
    siniflar = []
    for po in SEMBOLLER["page_objects"]:
        metotlar = "".join(
            f"        public Task {render.cs_method_name(m['name'])}("
            + ", ".join(f"{_CS_TUR[p['type']]} {p['name']}" for p in m["params"])
            + ") => Task.CompletedTask;\n"
            for m in po["methods"]
            if m["returns"] == "Promise<void>"
        )
        siniflar.append(
            f"    public class {po['class']}\n    {{\n"
            f"        public {po['class']}(Microsoft.Playwright.IPage page) {{ }}\n"
            f"{metotlar}    }}\n"
        )
    hedef = dizin / "Sahte.cs"
    hedef.write_text(
        "using System;\nusing System.Threading.Tasks;\n\n"
        "namespace NUnit.Framework\n{\n"
        "    [AttributeUsage(AttributeTargets.Class)]\n"
        "    public sealed class TestFixtureAttribute : Attribute { }\n"
        "    [AttributeUsage(AttributeTargets.Method)]\n"
        "    public sealed class TestAttribute : Attribute { }\n"
        "    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Method,"
        " AllowMultiple = true)]\n"
        "    public sealed class CategoryAttribute : Attribute\n"
        "    { public CategoryAttribute(string name) { } }\n"
        "    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Method)]\n"
        "    public sealed class DescriptionAttribute : Attribute\n"
        "    { public DescriptionAttribute(string description) { } }\n"
        "    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Method,"
        " AllowMultiple = true)]\n"
        "    public sealed class PropertyAttribute : Attribute\n"
        "    { public PropertyAttribute(string name, string value) { } }\n}\n\n"
        "namespace Microsoft.Playwright\n{\n    public interface IPage { }\n}\n\n"
        "namespace Microsoft.Playwright.NUnit\n{\n    public class PageTest\n    {\n"
        "        public Microsoft.Playwright.IPage Page { get; } = null!;\n    }\n}\n\n"
        f"namespace {render.CS_PO_NAMESPACE}\n{{\n{''.join(siniflar)}}}\n",
        encoding="utf-8",
    )
    return hedef


@dotnet_gerekli
def test_csharp_roslyn_ile_derlenir(tmp_path: Path) -> None:
    """Tüm golden'lar + kötü değerli çıktı, sahte kütüphanelere karşı uyarısız TAM derlenir
    (sözdizimi + bağlama: PascalCase metot adları, argüman türleri, öznitelikler)."""
    sahte = _sahte_cs_kutuphaneleri(tmp_path)
    case = copy.deepcopy(golden_case(5))
    case["title"] = '"); Environment.Exit(0); //\n*/ {0} $"{x}" ‮'
    case["steps"][0]["action"] = "eylem\n        Environment.Exit(1); //   Environment.Exit(2);"
    uretilenler = [
        render.render_dil(girdi(n), dil="csharp", platform="web", rules=RULES) for n in GOLDEN_NOLAR
    ] + [
        render.render_dil(
            girdi(5, case=case, mapping=kotu_esleme([*KOTU, *KOTU_GORUNMEZ]), sira_no=99),
            dil="csharp",
            platform="web",
            rules=RULES,
        )
    ]
    kaynaklar = [sahte]
    for r in uretilenler:
        hedef = tmp_path / r.repo_path
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_text(r.content, encoding="utf-8")
        kaynaklar.append(hedef)
    sonuc = _csc(tmp_path / "uretilen.dll", kaynaklar)
    assert sonuc.returncode == 0, sonuc.stdout + sonuc.stderr
    assert (tmp_path / "uretilen.dll").stat().st_size > 0


@dotnet_gerekli
def test_csharp_derleyici_bozuk_ciktiyi_yakalar(tmp_path: Path) -> None:
    """Kontrol: derleme gerçekten koşuyor (bilinmeyen metot / tür uyumsuzluğu reddedilir)."""
    sahte = _sahte_cs_kutuphaneleri(tmp_path)
    r = render.render_dil(girdi(), dil="csharp", platform="web", rules=RULES)
    for i, (eski, yeni, hata) in enumerate(
        (
            ("cartPage.ExpectTotalAsync(", "cartPage.ExpectTotal(", "CS1061"),
            ('AddToCartAsync("P-001", 7)', 'AddToCartAsync("P-001", "7")', "CS1503"),
            ('"150,00 TL");', '"150,00 TL"); System.Environment.Exit(0) //', "CS1002"),
        )
    ):
        assert eski in r.content
        hedef = tmp_path / f"Bozuk{i}.cs"
        hedef.write_text(r.content.replace(eski, yeni), encoding="utf-8")
        sonuc = _csc(tmp_path / f"bozuk{i}.dll", [sahte, hedef])
        assert sonuc.returncode != 0 and hata in sonuc.stdout, sonuc.stdout


@dotnet_gerekli
def test_cs_literal_derlenip_calistirilinca_ayni_deger(tmp_path: Path) -> None:
    """`cs_literal` çıktıları gerçek C# derleyicisinden geçer ve ÇALIŞTIRILINCA özgün değeri verir
    (dize: UTF-16 kod birimleri; sayı: tür + değer)."""
    assert DOTNET is not None
    degerler: list[Any] = [
        *KOTU, *KOTU_GORUNMEZ, 0, 7, -3, 2**31 - 1, -(2**31), 2**31, -(2**63), 2**63 - 1,
        7.0, 1.5, -0.25, 1e20, 1e-7, 1.7976931348623157e308, 5e-324, True, False, None,
    ]  # fmt: skip
    ogeler = ",\n            ".join(render.cs_literal(d) for d in degerler)
    (tmp_path / "Program.cs").write_text(
        "using System;\nusing System.Globalization;\nusing System.Linq;\n\n"
        "public static class Program\n{\n    public static void Main()\n    {\n"
        f"        object[] degerler = new object[]\n        {{\n            {ogeler}\n        }};\n"
        "        foreach (var d in degerler)\n        {\n"
        '            if (d is null) Console.WriteLine("null");\n'
        '            else if (d is string s) Console.WriteLine("String:" + string.Join(",", '
        "s.Select(c => ((int)c).ToString(CultureInfo.InvariantCulture))));\n"
        '            else if (d is double x) Console.WriteLine("Double:" + '
        'x.ToString("R", CultureInfo.InvariantCulture));\n'
        '            else Console.WriteLine(d.GetType().Name + ":" + '
        "Convert.ToString(d, CultureInfo.InvariantCulture));\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    sonuc = _csc(tmp_path / "program.dll", [tmp_path / "Program.cs"], hedef="exe")
    assert sonuc.returncode == 0, sonuc.stdout + sonuc.stderr
    (tmp_path / "program.runtimeconfig.json").write_text(
        json.dumps(
            {"runtimeOptions": {"tfm": DOTNET["tfm"], "framework": {
                "name": "Microsoft.NETCore.App", "version": DOTNET["surum"]}}}
        ),
        encoding="utf-8",
    )  # fmt: skip
    kosu = subprocess.run(
        [DOTNET["dotnet"], str(tmp_path / "program.dll")],
        capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"},
    )  # fmt: skip
    assert kosu.returncode == 0, kosu.stdout + kosu.stderr
    satirlar = kosu.stdout.splitlines()
    assert len(satirlar) == len(degerler)
    for deger, satir in zip(degerler, satirlar, strict=True):
        tur, _, govde = satir.partition(":")
        if deger is None:
            assert satir == "null"
        elif isinstance(deger, bool):
            assert (tur, govde) == ("Boolean", str(deger))
        elif isinstance(deger, str):
            ham = deger.encode("utf-16-le")
            birimler = [int.from_bytes(ham[i : i + 2], "little") for i in range(0, len(ham), 2)]
            assert tur == "String" and [int(b) for b in govde.split(",") if b] == birimler, deger
        elif isinstance(deger, int):
            assert tur == ("Int32" if -(2**31) <= deger < 2**31 else "Int64")
            assert int(govde) == deger
        else:
            assert tur == "Double" and math.isclose(float(govde), deger, rel_tol=0, abs_tol=0)


# ================================================================= tür uyumu (checks, §5)


def test_referans_tablo_turleri_csharp_python_literaline_uyar() -> None:
    """`_tur_uyar`'ın kabul ettiği her (tür, değer) çifti C# / Python literaline basılabilir:
    doğrulanmamış diller için `checks.py`'de ek tür eşlemesi gerekmez (TS ve Java tabloları)."""
    ornekler: dict[str, list[Any]] = {
        "string": ["a", ""], "String": ["a"], "number": [7, 7.5, -1], "boolean": [True, False],
        "int": [7, -(2**31)], "long": [2**40, -(2**63)], "double": [7, 7.5, 2**62],
    }  # fmt: skip
    for tip, degerler in ornekler.items():
        for deger in degerler:
            assert checks._tur_uyar(tip, deger) is True
            cs, py = render.cs_literal(deger), render.py_literal(deger)
            assert type(ast.literal_eval(py)) is type(deger) and ast.literal_eval(py) == deger
            # C#: tamsayı tamsayı, ondalık ondalık kalır (int → double genişletmesi derleyicide).
            if not isinstance(deger, str | bool):
                assert ("." in cs or "e" in cs) == isinstance(deger, float)
    # Sonlu olmayan sayı iki katmanda da reddedilir.
    assert checks._tur_uyar("double", float("inf")) is False
    assert checks._tur_uyar("number", float("nan")) is True  # TS `number`: render reddeder
    with pytest.raises(RenderError):
        render.py_literal(float("nan"))


# ============================================================ inceleme turu 1 (D2 render-şablon)

SONEKLER = ("\n", "\r\n", " ")


@pytest.mark.parametrize("sonek", SONEKLER)
def test_suzgecler_sondaki_satir_sonunu_reddeder(sonek: str) -> None:
    """GÜV-D1: `^…$` + `match` sondaki `\\n`'i geçirirdi; tüm kalıplar `fullmatch` ile."""
    for f, ad in (
        (render.ident, "addToCart"),
        (render.java_ident, "addToCart"),
        (render.cs_ident, "AddToCart"),
        (render.py_ident, "add_to_cart"),
        (render.py_name, "addToCart"),
        (render.cs_method_name, "addToCart"),
        (render.cs_variable_name, "CartPage"),
    ):
        f(ad)  # sonek olmadan geçer
        with pytest.raises(RenderError):
            f(ad + sonek)
    assert checks.IDENT_RE.match("addToCart" + sonek) is None
    assert checks.IDENT_RE.fullmatch("addToCart" + sonek) is None
    # Story anahtarı sonekle geçersizdir: sınıf / test / dosya adlarına girmez ("Serbest").
    story = "TPD-1" + sonek
    assert render.slug(story, 2, CASE_ID) == "serbest-c2-3f9b1c2e"
    assert render.java_class_name(story, "web", 2, CASE_ID) == "SerbestWebC2_3f9b1c2eTest"
    assert render.cs_class_name(story, 2, CASE_ID) == "SerbestWebC2_3f9b1c2eTests"
    assert render.py_test_name(story, 2, CASE_ID) == "test_serbest_c2_3f9b1c2e"
    for kalip, gecerli in (
        (render._JAVA_SINIF_RE, "TPD1WebC2_3f9b1c2eTest"),
        (render._CS_SINIF_RE, "TPD1WebC2_3f9b1c2eTests"),
        (render._PY_TEST_RE, "test_tpd_1_c2_3f9b1c2e"),
        (render._JAVA_GRUP_RE, "tp-case-x"),
        (render._JAVA_BAYI_RE, "bayi1"),
        (render._STORY_RE, "TPD-1"),
    ):
        assert kalip.fullmatch(gecerli) and not kalip.fullmatch(gecerli + sonek)
    # Eşlemede sonekli ad: kontroller insana, render reddeder.
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["method"] = "expectTotal" + sonek
    bulgular = checks._imza(
        symbols(), "CartPage", m["expects"][0]["method"], ["x"], "expect",
        "beklenen", "s1",
    )  # fmt: skip
    assert [b.tur for b in bulgular] == ["unknown_method"] and "geçersiz ad" in bulgular[0].mesaj
    for dil in ("ts", "java", "csharp", "python"):
        with pytest.raises(RenderError):
            render.render_dil(girdi(mapping=m), dil=dil, platform="web", rules=RULES)
    # Bayi adı sonekle sabitlenmez (bilinen bayi listesinde yok) ve doğrudan da reddedilir.
    assert render._JAVA_BAYI_RE.fullmatch("bayi1" + sonek) is None


def test_story_rakamlari_ascii() -> None:
    assert render.slug("TPD-١٢", 2, CASE_ID) == "serbest-c2-3f9b1c2e"  # Unicode rakam


def test_dogrulanmamis_yol_tek_kaynak() -> None:
    """K-T6: `<e2e-csharp|e2e-python kökü>/<alt yol>`; render ve başlangıç yolu aynı işlev."""
    yol = render.dogrulanmamis_repo_path
    assert yol("csharp", "TPD-1", 2, CASE_ID) == (
        "e2e-csharp/tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    )
    assert yol("python", "TPD-1", 2, CASE_ID) == (
        "e2e-python/tests/generated/test_tpd_1_c2_3f9b1c2e.py"
    )
    assert yol("csharp", "TPD-1", 2, CASE_ID, "demo-app/e2e-csharp/") == (
        "demo-app/e2e-csharp/tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    )
    # Boş ya da ts kökü (`RenderInput` varsayılanı) → dilin varsayılan kökü.
    for kok in (None, "", "/", "e2e"):
        assert yol("python", None, 3, CASE_ID, kok) == (
            "e2e-python/tests/generated/test_serbest_c3_3f9b1c2e.py"
        )
    with pytest.raises(RenderError):
        yol("ts", "TPD-1", 2, CASE_ID)
    for dil in ("csharp", "python"):
        for kok, beklenen in (
            (render.E2E_ROOT, None),
            ("demo-app/e2e-" + dil, "demo-app/e2e-" + dil),
        ):
            r = render.render_dil(girdi(e2e_root=kok), dil=dil, platform="web", rules=RULES)
            assert r.repo_path == yol(dil, "TPD-1", 2, CASE_ID, beklenen)
            assert r.repo_path.endswith("/" + r.test_file)
        # Sınıf / test adı yolun dosya adıyla aynı kuralı kullanır.
        r = render.render_dil(girdi(), dil=dil, platform="web", rules=RULES)
        assert Path(r.repo_path).stem == (r.sinif_adi or r.test_adi)


@pytest.mark.parametrize("dil", ["csharp", "python"])
def test_dogrulanmamis_baslik_uyarlama_ve_imzalar(dil: str) -> None:
    """K-T9 küçük kısım: "Elle düzenlemeyin" yok; varsayılan PO imzaları listelenir. Tablo
    verilmezse türler değerden, adlar `argN`."""
    on = "//" if dil == "csharp" else "#"
    r = render.render_dil(girdi(), dil=dil, platform="web", rules=RULES)
    assert "Elle düzenlemeyin" not in r.content
    assert "uyarlanmak üzere" in r.content.splitlines()[0]
    satirlar = r.content.splitlines()
    if dil == "csharp":
        assert f"{on}     Task AddToCartAsync(string arg1, int arg2)" in satirlar
        assert f"{on}     Task GotoAsync()" in satirlar
        assert f"{on}   CartPage" in satirlar
    else:
        assert f"{on}     def add_to_cart(self, arg1: str, arg2: int) -> None" in satirlar
        assert f"{on}   pages.catalog_page.CatalogPage" in satirlar
    # Tablolu: referans türleri hedef dile çevrilir (TS number → double / float; Java int → int).
    java_tablo = json.loads((HERE / "symbols-java-web.json").read_text(encoding="utf-8"))
    tr = render.render_dil(
        girdi(),
        dil=dil,
        platform="web",
        rules=RULES,
        referans_dil="java",
        sembol_tablosu=java_tablo,
    )
    beklenen = (
        f"{on}     Task AddToCartAsync(string productCode, int quantity)"
        if dil == "csharp"
        else f"{on}     def add_to_cart(self, product_code: str, quantity: int) -> None"
    )
    assert beklenen in tr.content.splitlines()
    # Tablodaki kötü parametre adı / bilinmeyen tür imzaya taşınmaz (`argN`, değerden tür).
    kotu = copy.deepcopy(SEMBOLLER)
    for po in kotu["page_objects"]:
        for m in po["methods"]:
            for p in m["params"]:
                p["name"] = 'x");\nEvil(); //'
                p["type"] = "Promise<any>"
    kr = render.render_dil(girdi(), dil=dil, platform="web", rules=RULES, sembol_tablosu=kotu)
    assert kr.content == r.content.replace(r.template_hash, kr.template_hash)


@pytest.mark.parametrize("dil", ["ts", "java"])
def test_tam_hat_basligi_degismedi(dil: str) -> None:
    """Tam hat dillerinde başlık ("Elle düzenlemeyin") ve çıktı aynen kalır."""
    inp = girdi() if dil == "ts" else java_web_girdi()
    r = render.render_dil(inp, dil=dil, platform="web", rules=RULES, sembol_tablosu=SEMBOLLER)
    assert r == render.render_dil(inp, dil=dil, platform="web", rules=RULES)
    assert "Elle düzenlemeyin" in r.content


def test_python_strict_markers_parcasi_sablonla_birebir() -> None:
    """QA-O7: başlıktaki `conftest.py` parçası çalıştırılınca şablonun kullandığı tüm işaretleri
    kaydeder (`--strict-markers` kırılmaz)."""
    r = render.render_dil(girdi(), dil="python", platform="web", rules=RULES)
    satirlar = r.content.splitlines()
    bas = satirlar.index("#   def pytest_configure(config):")
    parca = []
    for satir in satirlar[bas:]:
        if not satir.startswith("#   "):
            break
        parca.append(satir[4:])
    kayitlar: list[tuple[str, str]] = []

    class Config:
        def addinivalue_line(self, ad: str, deger: str) -> None:
            kayitlar.append((ad, deger))

    alan: dict[str, Any] = {}
    exec(compile("\n".join(parca), "conftest.py", "exec"), alan)  # sabit parça (şablondan)
    alan["pytest_configure"](Config())
    kayitli = {d.split(":")[0].split("(")[0] for ad, d in kayitlar if ad == "markers"}
    kullanilan = {i[0] for i in _py_yapi(r.content)["isaretler"]}  # story + dealer dahil
    assert kullanilan == kayitli == {ad.split("(")[0] for ad, _ in render.PY_ISARETLER}


# --------------------------------------------- 013 K19 × 011: doğrulanmamış dilde gizli test verisi


@pytest.mark.parametrize(
    ("dil", "okuma"),
    [
        ("csharp", 'System.Environment.GetEnvironmentVariable("TP_TESTVERI_DEMO_PAROLA")'),
        ("python", '__import__("os").environ["TP_TESTVERI_DEMO_PAROLA"]'),
    ],
)
def test_dogrulanmamis_dilde_gizli_deger_ortamdan_okunur(dil: str, okuma: str) -> None:
    """Gizli değer argümanı ortam değişkeninden okunur; başlık/adım etiketinde `•••`; boş harita
    çıktıyı (golden) değiştirmez."""
    gizli = {"Demo123!": "TP_TESTVERI_DEMO_PAROLA"}
    case = copy.deepcopy(golden_case(2))
    case["title"] = "bayi1 / Demo123! ile giriş"
    for adim in case.get("steps") or []:
        adim["action"] = f"{adim.get('action')} (Demo123!)"
    r = render.render_dil(
        girdi(2, case=case, gizli_ortam=gizli), dil=dil, platform="web", rules=RULES
    )
    assert okuma in r.content
    assert "Demo123!" not in r.content and "•••" in r.content
    assert (
        render.render_dil(girdi(2, gizli_ortam={}), dil=dil, platform="web", rules=RULES).content
        == render.render_dil(girdi(2), dil=dil, platform="web", rules=RULES).content
    )


@pytest.mark.parametrize("dil", ["csharp", "python"])
def test_dogrulanmamis_dilde_sirri_tanimsiz_gizli_deger_sizinti_taramasina_takilir(
    dil: str,
) -> None:
    """Sırrı tanımsız (yalnız taranacak) gizli değer düz literal kalırsa render fail-closed."""
    with pytest.raises(render.GizliSizinti):
        render.render_dil(
            girdi(2, gizli_taranacak=("Demo123!",)), dil=dil, platform="web", rules=RULES
        )

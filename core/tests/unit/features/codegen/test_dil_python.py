"""014 Ş1: Python dil eklentisi (`codegen/diller/python.py`) — tam hat render.

Kanıt düzeyi:
- golden: web (TPD-1 C2) ve uygulama (android TPD-1 C2) çıktısı bayt bayt;
- gerçek araç: üretilen her dosya `toolchain/py-guard/py_guard.py guard`'dan (toolchain'in /check
  koruması) geçer ve `compile` edilir (çalıştırılmaz);
- PO eşitliği uçtan uca: 10 web golden eşlemesinin ve uygulama golden eşlemesinin Python'a
  çevrilmiş her çağrısı demo hedef projedeki (`demo-app/e2e-python/pages`,
  `demo-app/e2e-app-python/ekranlar`) py-guard sembol tablosunda vardır (parametre sayısıyla);
- enjeksiyon: kötü niyetli case değerleri yalnız literal olur (`ast.literal_eval` geri okuma).

Golden güncelleme:
`TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_dil_python.py`.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tp_core.features.codegen import render
from tp_core.features.codegen.diller import python as py
from tp_core.features.codegen.render import RenderError

from .test_checks import RULES, golden_mapping
from .test_platform import APP_GOLDEN
from .test_platform import _girdi as app_girdi
from .test_render_dil import CASE_ID, KOTU, KOTU_GORUNMEZ, girdi, kotu_esleme

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
GOLDEN = HERE / "golden" / "python"
PY_GUARD = REPO / "toolchain" / "py-guard" / "py_guard.py"
E2E_PYTHON = REPO / "demo-app" / "e2e-python"
E2E_APP_PYTHON = REPO / "demo-app" / "e2e-app-python"
NOLAR = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def web(n: int = 2, **over: Any) -> render.Rendered:
    over.setdefault("e2e_root", "e2e-python")
    return py.render_python(girdi(n, **over), "web", RULES)


def app(platform: str = "android", **over: Any) -> render.Rendered:
    over.setdefault("e2e_root", "e2e-app-python")
    return py.render_python(app_girdi(**over), platform, RULES)


def golden_karsilastir(ad: str, icerik: str) -> None:
    hedef = GOLDEN / ad
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_text(icerik, encoding="utf-8")
    assert icerik == hedef.read_text(encoding="utf-8")


def guard(root: Path, *dosyalar: str) -> dict[str, Any]:
    out = subprocess.run(
        [sys.executable, "-I", str(PY_GUARD), "guard", "--root", str(root), "--", *dosyalar],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode in (0, 1), out.stderr
    return json.loads(out.stdout)


def sembol_tablosu(root: Path, kind: str) -> dict[tuple[str, str], int]:
    out = subprocess.run(
        [sys.executable, "-I", str(PY_GUARD), "symbols", "--root", str(root), "--kind", kind],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    tablo = json.loads(out.stdout)
    assert not tablo["errors"], tablo["errors"]
    return {
        (po["class"], m["name"]): len(m["params"])
        for po in tablo["page_objects"]
        for m in po["methods"]
    }


def yaz(tmp: Path, rendered: render.Rendered) -> Path:
    """Üretilen testi geçici bir proje köküne `tests/generated/` altına yazar."""
    hedef = tmp / rendered.test_file
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(rendered.content, encoding="utf-8")
    return hedef


def cagrilar(kaynak: str) -> list[tuple[str, str, list[Any]]]:
    """Test gövdesindeki `<değişken>.<metot>(<literal>…)` çağrıları (literal değerleriyle)."""
    agac = ast.parse(kaynak)
    fn = next(n for n in agac.body if isinstance(n, ast.FunctionDef))
    out = []
    for st in fn.body:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            c = st.value
            assert isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
            out.append((c.func.value.id, c.func.attr, [ast.literal_eval(a) for a in c.args]))
    return out


# ========================================================================= golden + yol


def test_web_golden() -> None:
    r = web()
    golden_karsilastir("test_tpd_1_c2_3f9b1c2e.py.golden", r.content)
    assert r.test_file == "tests/generated/test_tpd_1_c2_3f9b1c2e.py"
    assert r.repo_path == "e2e-python/tests/generated/test_tpd_1_c2_3f9b1c2e.py"
    assert (r.dil, r.sinif_adi, r.test_adi, r.dealer) == (
        "python", None, "test_tpd_1_c2_3f9b1c2e", "bayi1",
    )  # fmt: skip
    assert not r.dogrulanmamis and r.referans_dil is None
    ozet = render.sha256_hex((RULES / "templates" / py.WEB_SABLONU).read_text(encoding="utf-8"))
    assert f"şablon: {ozet}" in r.content


def test_uygulama_golden() -> None:
    r = app("android")
    golden_karsilastir("test_tpd_1_android_c2_3f9b1c2e.py.golden", r.content)
    assert r.test_file == "tests/generated/test_tpd_1_android_c2_3f9b1c2e.py"
    assert r.repo_path == "e2e-app-python/tests/generated/test_tpd_1_android_c2_3f9b1c2e.py"
    assert r.dealer == "bayi1"
    ozet = render.sha256_hex(
        (RULES / "templates" / py.UYGULAMA_SABLONU).read_text(encoding="utf-8")
    )
    assert f"şablon: {ozet}" in r.content


@pytest.mark.parametrize("platform", ["android", "ios", "windows"])
def test_uygulama_platform_basina_ayri_dosya_ve_isaret(platform: str) -> None:
    r = app(platform)
    assert r.test_adi == f"test_tpd_1_{platform}_c2_3f9b1c2e"
    assert f"@pytest.mark.{platform}\n" in r.content
    assert "playwright" not in r.content and "(driver) -> None:" in r.content
    for diger in {"android", "ios", "windows", "web"} - {platform}:
        assert f"@pytest.mark.{diger}\n" not in r.content


@pytest.mark.parametrize(
    ("kok", "beklenen"),
    [("", "e2e-python"), ("e2e", "e2e-python"), ("demo-app/e2e-python/", "demo-app/e2e-python")],
)
def test_web_kok(kok: str, beklenen: str) -> None:
    assert web(e2e_root=kok).repo_path == f"{beklenen}/tests/generated/test_tpd_1_c2_3f9b1c2e.py"


def test_uretilen_yol_render_ile_ayni() -> None:
    """K-T6: başlangıç yolu (service) ve render yolu tek kaynaktan."""
    for platform, kok, r in (
        ("web", "e2e-python", web()),
        ("ios", "", app("ios", e2e_root="")),
    ):
        cati = SimpleNamespace(platform=platform, kok_varsayilan=py.varsayilan_kok(platform))
        assert py.EKLENTI.uretilen_yol(cati, kok, "TPD-1", 2, CASE_ID) == r.repo_path
    assert py.alt_yol(None, "web", 3, CASE_ID) == "tests/generated/test_serbest_c3_3f9b1c2e.py"
    assert py.alt_yol("x y", "windows", 3, CASE_ID) == (
        "tests/generated/test_serbest_windows_c3_3f9b1c2e.py"
    )


def test_eklenti_protokolu() -> None:
    e = py.EKLENTI
    assert (e.ad, e.proje_dosyasi) == ("python", "pyproject.toml")
    assert {k.kok_ayari for k in e.algila_kaliplari} == {
        "TP_E2E_PYTHON_ROOT", "TP_E2E_APP_PYTHON_ROOT",
    }  # fmt: skip
    assert e.sinif_adi("TPD-1", "web", 2, CASE_ID) is None
    assert e.literal('a"b') == '"a\\"b"' and e.ident("cart_page") == "cart_page"
    cati = SimpleNamespace(platform="android", kok_varsayilan="e2e-app-python")
    assert e.render(app_girdi(e2e_root="e2e-app-python"), cati, RULES) == app("android")


# ===================================================== gerçek araç: py-guard + derleme


@pytest.mark.parametrize("n", NOLAR)
def test_web_tum_goldenlar_guarddan_gecer(n: int, tmp_path: Path) -> None:
    r = web(n)
    compile(r.content, r.test_file, "exec", dont_inherit=True)
    yaz(tmp_path, r)
    rapor = guard(tmp_path, r.test_file)
    assert rapor["ok"], rapor["violations"]


@pytest.mark.parametrize("platform", ["android", "ios", "windows"])
def test_uygulama_guarddan_gecer(platform: str, tmp_path: Path) -> None:
    r = app(platform)
    yaz(tmp_path, r)
    rapor = guard(tmp_path, r.test_file)
    assert rapor["ok"], rapor["violations"]


def test_guard_kirik_ciktiyi_yakalar(tmp_path: Path) -> None:
    """Koruma gerçekten koruyor mu: üretilen dosyaya eklenen tek bir yasak satır reddedilir."""
    r = web()
    hedef = yaz(tmp_path, r)
    hedef.write_text(r.content + "    __import__('os').system('x')\n", encoding="utf-8")
    assert not guard(tmp_path, r.test_file)["ok"]


# ============================================ PO eşitliği uçtan uca (demo hedef projeler)


@pytest.mark.skipif(not E2E_PYTHON.is_dir(), reason="demo-app/e2e-python yok")
@pytest.mark.parametrize("n", NOLAR)
def test_web_esleme_demo_page_objectlerinde_var(n: int) -> None:
    tablo = sembol_tablosu(E2E_PYTHON, "web")
    r = web(n)
    siniflar = {
        n.names[0].asname or n.names[0].name: n.module
        for n in ast.parse(r.content).body
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("pages.")
    }
    degisken = {render.py_name(s): s for s in siniflar}
    for var, metot, args in cagrilar(r.content):
        anahtar = (degisken[var], metot)
        assert anahtar in tablo, f"{anahtar} demo e2e-python'da yok"
        assert tablo[anahtar] == len(args), anahtar
        assert (E2E_PYTHON / (siniflar[degisken[var]].replace(".", "/") + ".py")).is_file()


@pytest.mark.skipif(not E2E_APP_PYTHON.is_dir(), reason="demo-app/e2e-app-python yok")
def test_uygulama_esleme_demo_ekranlarinda_var() -> None:
    tablo = sembol_tablosu(E2E_APP_PYTHON, "app")
    r = app()
    degisken = {
        render.py_name(n.names[0].name): n.names[0].name
        for n in ast.parse(r.content).body
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("ekranlar.")
    }
    for var, metot, args in cagrilar(r.content):
        assert tablo.get((degisken[var], metot)) == len(args), (degisken[var], metot)


@pytest.mark.skipif(not E2E_PYTHON.is_dir(), reason="demo-app/e2e-python yok")
def test_demo_ornek_uretilen_testler_guarddan_gecer() -> None:
    for kok in (E2E_PYTHON, E2E_APP_PYTHON):
        rapor = guard(kok)
        assert rapor["ok"] and rapor["files"], rapor


# ======================================================== eşleme dönüşümü ve adlar


def test_eslemeyi_donustur_snake_case_ve_esguclu() -> None:
    m = golden_mapping(2)
    bir = py.eslemeyi_donustur(m)
    assert bir is not m and m == golden_mapping(2)  # girdi değişmez
    metotlar = [x["method"] for x in bir["step_mapping"] + bir["expects"]]
    assert all(x == x.lower() for x in metotlar)
    assert py.eslemeyi_donustur(bir) == bir
    assert py.eslemeyi_donustur("yok") == "yok"
    # Dönüştürülmüş eşleme aynı kodu üretir (yalnız eşleme hash'i farklıdır).
    a, b = web(mapping=m), web(mapping=bir)
    assert cagrilar(a.content) == cagrilar(b.content)


def test_java_tablosuyla_eslenen_uygulama_ve_python_tablosu_ayni_kodu_uretir() -> None:
    dogrudan = app()
    cevrilmis = app(mapping=py.eslemeyi_donustur(APP_GOLDEN["output"]))
    assert cagrilar(dogrudan.content) == cagrilar(cevrilmis.content)
    assert ("giris_ekrani", "giris_yap", ["bayi1", "Demo123!"]) in cagrilar(dogrudan.content)


@pytest.mark.parametrize(
    ("po", "metot"),
    [("Page", "goto"), ("Driver", "goto"), ("Os", "x"), ("CartPage", "__init__"),
     ("CartPage", "_ozel"), ("Cart Page", "x"), ("CartPage", "a.b")],
)  # fmt: skip
def test_ayrilmis_ve_gecersiz_adlar_reddedilir(po: str, metot: str) -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"] = [{"po": po, "method": metot, "args": []}]
    with pytest.raises(RenderError):
        web(mapping=m)


def test_bos_esleme_reddedilir() -> None:
    with pytest.raises(RenderError):
        web(mapping={"step_mapping": [], "expects": []})


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        ("tests/test_login.py", True),
        ("tests/sepet/test_sepet.py", True),
        ("tests/login_test.py", True),
        ("test_kok.py", True),
        ("tests/generated/test_tpd_1_c2_3f9b1c2e.py", False),
        ("tests/birim/test_po_esitligi.py", False),
        ("tests/conftest.py", False),
        ("pages/login_page.py", False),
        ("tests/test_login.ts", False),
        ("tests/LoginTest.java", False),
    ],
)
def test_test_dosyasi_mi(yol: str, beklenen: bool) -> None:
    assert py.EKLENTI.test_dosyasi_mi(yol) is beklenen


# =============================================================== enjeksiyon ve sırlar


def test_kotu_degerler_yalniz_literal_olur(tmp_path: Path) -> None:
    degerler = [*KOTU, *KOTU_GORUNMEZ]
    r = web(5, mapping=kotu_esleme(degerler))
    gorulen = [args[0] for var, metot, args in cagrilar(r.content)
               if metot == "expect_min_order_warning"]  # fmt: skip
    assert gorulen == degerler
    yaz(tmp_path, r)
    assert guard(tmp_path, r.test_file)["ok"]


def test_gizli_test_verisi_ortamdan_okunur(tmp_path: Path) -> None:
    r = web(gizli_ortam={"Demo123!": "TP_TESTVERI_DEMO_PAROLA"})
    assert 'os.environ["TP_TESTVERI_DEMO_PAROLA"]' in r.content
    assert "Demo123!" not in r.content and "__import__" not in r.content
    assert r.content.count("\nimport os\n") == 1
    yaz(tmp_path, r)
    assert guard(tmp_path, r.test_file)["ok"]
    # Sır yoksa `os` içe aktarılmaz.
    assert "import os" not in web().content


def test_maskelenmemis_gizli_deger_sizintisi_reddedilir() -> None:
    with pytest.raises(render.GizliSizinti):
        web(gizli_taranacak=["Demo123!"])


def test_dealer_python_giris_metoduyla_da_sabitlenir() -> None:
    m = py.eslemeyi_donustur(APP_GOLDEN["output"])
    assert app(mapping=m).dealer == "bayi1"


# ================================ değerlendirme vakaları (Ş8 düzeni) ve sembol fikstürleri

VAKALAR = REPO / "rules" / "evaluation" / "vakalar"
# Ş8 `build_eval_sets._VAKA_ALANLARI` ile aynı küme (kaynak alanları).
VAKA_ALANLARI = {
    "id", "story", "case_no", "platform", "baslik", "ajan_tablosu", "tablo_dili", "golden",
    "expects_include",
}  # fmt: skip


@pytest.mark.parametrize(
    ("fikstur", "kok", "kind"),
    [
        ("symbols-python.json", E2E_PYTHON, "web"),
        ("symbols-python-app.json", E2E_APP_PYTHON, "app"),
    ],
)
def test_python_sembol_fiksturleri_demo_ile_esit(fikstur: str, kok: Path, kind: str) -> None:
    """Ajan tablosu fikstürü demo hedef projeden üretilir (bayatlamaz). Güncelleme:
    `python3.12 -I toolchain/py-guard/py_guard.py symbols --root <kök> --kind <web|app>`."""
    out = subprocess.run(
        [sys.executable, "-I", str(PY_GUARD), "symbols", "--root", str(kok), "--kind", kind],
        capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    assert json.loads(out.stdout) == json.loads((HERE / fikstur).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("paket", "platformlar", "adet"),
    [("verify-and-map", {"web"}, 3), ("verify-and-map-app", {"android", "ios", "windows"}, 3)],
)
def test_python_degerlendirme_vakalari(paket: str, platformlar: set[str], adet: int) -> None:
    """TASARIM §3.1: web 3 (tpd-1-c3, tpd-4-c1, tpd-4-c2), uygulama 3 (platform başına bir);
    ajan Python tablosunu görür (TS/Java gizli, R10) ve beklenen assertion'lar o tabloda var."""
    dosyalar = sorted((VAKALAR / paket / "python").glob("*.json"))
    assert len(dosyalar) == adet
    gorulen = set()
    for f in dosyalar:
        v = json.loads(f.read_text(encoding="utf-8"))
        assert set(v) <= VAKA_ALANLARI and v["tablo_dili"] == "python"
        assert v["id"].endswith("-python") and v["platform"] in platformlar
        gorulen.add(v["platform"])
        tablo = json.loads((REPO / v["ajan_tablosu"]).read_text(encoding="utf-8"))
        assert tablo["lang"] == "python"
        adlar = {
            f"{po['class']}.{m['name']}" for po in tablo["page_objects"] for m in po["methods"]
        }
        assert v["expects_include"] and set(v["expects_include"]) <= adlar
        alt = "verify_and_map" if paket == "verify-and-map" else "verify_and_map_app"
        assert (REPO / "rules" / "replay" / alt / "golden" / f"{v['golden']}.json").is_file()
    assert gorulen == platformlar

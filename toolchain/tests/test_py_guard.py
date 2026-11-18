# ruff: noqa: E501  (izin listesi fikstürleri tek satırlık değiştirmelerdir)
"""py-guard (Ş1, toolchain/py-guard/py_guard.py): sembol tablosu, üretilen test izin listesi,
derleme tanıları, kimlik onarım farkı ve yaması. Analiz edilen kod hiç çalıştırılmaz."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.conftest import TOOLCHAIN

GUARD_PATH = TOOLCHAIN / "py-guard" / "py_guard.py"
_spec = importlib.util.spec_from_file_location("py_guard", GUARD_PATH)
assert _spec and _spec.loader
pg = importlib.util.module_from_spec(_spec)
sys.modules["py_guard"] = pg
_spec.loader.exec_module(pg)

GEN = "tests/generated/test_tpd_1_c2_3f9b1c2e.py"
APP_GEN = "tests/generated/test_tpd_1_android_c2_3f9b1c2e.py"

GOOD_WEB = """\
# AI-generated — AI Testing Probe (CasesToCode).
# Case: TPD-1 C2 · bayi: bayi1
import os

import pytest
from playwright.sync_api import Page

from pages.cart_page import CartPage
from pages.login_page import LoginPage


@pytest.mark.uretilen
@pytest.mark.web
@pytest.mark.tp_case("3f9b1c2e-0000-0000-0000-000000000000")
@pytest.mark.story("TPD-1")
@pytest.mark.dealer("bayi1")
def test_tpd_1_c2_3f9b1c2e(page: Page) -> None:
    login_page = LoginPage(page)
    cart_page = CartPage(page)

    # s1 — giriş
    login_page.goto()
    login_page.login("bayi1", os.environ["TP_TESTVERI_DEMO_PAROLA"])
    # Beklenen sonuç
    cart_page.expect_line_quantity("P-001", 3)
    cart_page.expect_total("150,00 TL")
    cart_page.expect_ratio(-1.5, True, None)
"""

GOOD_APP = """\
import pytest

from ekranlar.giris_ekrani import GirisEkrani


@pytest.mark.uretilen
@pytest.mark.android
@pytest.mark.tp_case("3f9b1c2e-0000-0000-0000-000000000000")
def test_tpd_1_android_c2_3f9b1c2e(driver) -> None:
    giris_ekrani = GirisEkrani(driver)
    giris_ekrani.ac()
    giris_ekrani.giris_yap("bayi1", "Demo123!")
    giris_ekrani.dogrula_giris_yapildi("Merkez Bayi")
"""

KIMLIKLER = '''\
"""Giriş ve sepet kimlikleri (saf veri)."""

LOGIN = {
    "username": {"test_id": "login-username", "intent": "Kullanıcı adı alanı"},
    "submit": {"test_id": "login-submit", "intent": "Giriş butonu"},
}
CART = {"total": "cart-total"}
'''

PAGE = '''\
"""Bayi giriş sayfası."""

from playwright.sync_api import Page, expect

from pages.kimlikler import LOGIN


class LoginPage:
    """Bayi giriş sayfası."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self) -> None:
        """Giriş sayfasını açar."""

    def login(self, username: str, password: str) -> None:
        """Giriş yapar."""

    def expect_line_quantity(self, product_code: str, quantity: int, strict: bool = True) -> None:
        pass

    def _ozel(self) -> None:
        pass


class _Gizli:
    def x(self) -> None:
        pass
'''


def _root(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "proje"
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _codes(report: dict) -> list[str]:
    return [v["code"] for v in report["violations"]]


# --------------------------------------------------------------------------------- symbols


def test_symbols_web_tp_symbols_semasi(tmp_path: Path) -> None:
    root = _root(tmp_path, {"pages/login_page.py": PAGE, "pages/kimlikler.py": KIMLIKLER,
                            "pages/__init__.py": ""})  # fmt: skip
    t = pg.symbols(root)
    assert t["schema_version"] == 1 and t["lang"] == "python" and t["root"] == "pages"
    assert t["errors"] == []
    (po,) = t["page_objects"]
    assert po["class"] == "LoginPage" and po["file"] == "pages/login_page.py"
    assert po["doc"] == "Bayi giriş sayfası."
    names = [m["name"] for m in po["methods"]]
    assert names == ["goto", "login", "expect_line_quantity"]
    login = po["methods"][1]
    assert login["params"] == [
        {"name": "username", "type": "string", "optional": False},
        {"name": "password", "type": "string", "optional": False},
    ]
    assert login["kind"] == "action" and login["returns"] == "void" and login["async"] is False
    exp = po["methods"][2]
    assert exp["kind"] == "assertion"
    assert [p["type"] for p in exp["params"]] == ["string", "int", "boolean"]
    assert exp["params"][2]["optional"] is True
    assert t["locator_files"] == [{"file": "pages/kimlikler.py", "exports": ["LOGIN", "CART"]}]


def test_symbols_uygulama_ekranlar_ve_bozuk_dosya(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        {
            "ekranlar/giris_ekrani.py": "class GirisEkrani:\n    def dogrula_hata(self, b: str):\n"
            "        pass\n    def ac(self, n: float = 1.0) -> None:\n        pass\n",
            "ekranlar/bozuk.py": "class (:\n",
        },
    )
    t = pg.symbols(root)
    assert t["kind"] == "app" and t["root"] == "ekranlar"
    (po,) = t["page_objects"]
    assert [(m["name"], m["kind"]) for m in po["methods"]] == [
        ("dogrula_hata", "assertion"), ("ac", "action"),
    ]  # fmt: skip
    assert po["methods"][1]["params"][0]["type"] == "double"
    assert t["errors"][0]["file"] == "ekranlar/bozuk.py"


# ----------------------------------------------------------------------------------- guard


def test_guard_iyi_web_ve_uygulama_testi_gecer(tmp_path: Path) -> None:
    root = _root(tmp_path, {GEN: GOOD_WEB, APP_GEN: GOOD_APP, "pages/kimlikler.py": KIMLIKLER,
                            "tests/generated/__init__.py": ""})  # fmt: skip
    rep = pg.guard(root, None, kimlikler=True)
    assert rep["ok"], rep["violations"]
    assert rep["files"] == [APP_GEN, GEN] and rep["kimlikler"] == ["pages/kimlikler.py"]


BAD = [
    ("eval", "    cart_page.expect_total(eval('1'))\n", "argument_not_allowed"),
    ("exec", "    exec('x=1')\n", "statement_not_allowed"),
    ("__import__", '    cart_page.expect_total(__import__("os").environ["TP_TESTVERI_X"])\n',
     "argument_not_allowed"),
    ("getattr", "    getattr(cart_page, 'expect_total')('1')\n", "statement_not_allowed"),
    ("open", "    open('/etc/passwd')\n", "statement_not_allowed"),
    ("kwargs", '    cart_page.expect_total(amount="1")\n', "statement_not_allowed"),
    ("fstring", '    cart_page.expect_total(f"{1}")\n', "argument_not_allowed"),
    ("bytes", '    cart_page.expect_total(b"1")\n', "argument_not_allowed"),
    ("dunder attr", "    cart_page.__class__.x()\n", "statement_not_allowed"),
    ("private method ok? no: attr chain", "    cart_page.page.goto('x')\n",
     "statement_not_allowed"),
    ("os misuse", '    cart_page.expect_total(os.environ["HOME"])\n', "argument_not_allowed"),
    ("os.system", "    os.system('id')\n", "statement_not_allowed"),
    ("late assign", "    x = LoginPage(page)\n", "statement_not_allowed"),
    ("docstring", '    """belge"""\n', "statement_not_allowed"),
    ("loop", "    for i in range(3):\n        cart_page.goto()\n", "statement_not_allowed"),
]  # fmt: skip


@pytest.mark.parametrize(("ad", "ek", "kod"), BAD, ids=[b[0] for b in BAD])
def test_guard_govde_ihlalleri(tmp_path: Path, ad: str, ek: str, kod: str) -> None:
    root = _root(tmp_path, {GEN: GOOD_WEB + ek})
    rep = pg.guard(root, [GEN], kimlikler=False)
    assert not rep["ok"] and kod in _codes(rep), (ad, rep["violations"])


MODULE_BAD = [
    ("extra import", GOOD_WEB.replace("import os\n", "import os\nimport subprocess\n"),
     "import_not_allowed"),
    ("from os import", GOOD_WEB.replace("import os\n", "from os import system\n"),
     "import_not_allowed"),
    ("relative", GOOD_WEB.replace("from pages.cart_page", "from .cart_page"),
     "import_not_allowed"),
    ("alias", GOOD_WEB.replace("import CartPage", "import CartPage as C"), "import_not_allowed"),
    ("star", GOOD_WEB.replace("import CartPage", "import *"), "import_not_allowed"),
    ("second function", GOOD_WEB + "\n\ndef yardimci() -> None:\n    pass\n", "function_count"),
    ("module code", GOOD_WEB + "\nprint('x')\n", "statement_not_allowed"),
    ("module docstring", '"""belge"""\n' + GOOD_WEB, "statement_not_allowed"),
    ("bad decorator", GOOD_WEB.replace("@pytest.mark.web\n", "@pytest.fixture\n@pytest.mark.web\n"),
     "decorator_not_allowed"),
    ("marker kwargs", GOOD_WEB.replace('@pytest.mark.story("TPD-1")', '@pytest.mark.story(k="TPD-1")'),
     "decorator_not_allowed"),
    ("skip marker", GOOD_WEB.replace("@pytest.mark.uretilen\n", "@pytest.mark.uretilen\n@pytest.mark.skip\n"),
     "decorator_not_allowed"),
    ("missing tp_case", GOOD_WEB.replace('@pytest.mark.tp_case("3f9b1c2e-0000-0000-0000-000000000000")\n', ""),
     "missing_marker"),
    ("wrong name", GOOD_WEB.replace("def test_tpd_1_c2_3f9b1c2e", "def test_baska"), "function_name"),
    ("signature", GOOD_WEB.replace("(page: Page) -> None", "(page: Page, x=1) -> None"),
     "signature"),
    ("async", GOOD_WEB.replace("def test_tpd", "async def test_tpd"), "function_count"),
    ("kimlikler import", GOOD_WEB.replace("from pages.cart_page import CartPage",
                                          "from pages.kimlikler import CartPage"),
     "import_not_allowed"),
    ("ekranlar on web", GOOD_WEB.replace("from pages.cart_page", "from ekranlar.cart_page"),
     "import_not_allowed"),
    ("bidi", GOOD_WEB.replace("# s1 — giriş", "# s1 ‮ giriş"), "invisible_char"),
    ("coding", "# -*- coding: latin-1 -*-\n" + GOOD_WEB, "bad_encoding"),
]  # fmt: skip


@pytest.mark.parametrize(("ad", "src", "kod"), MODULE_BAD, ids=[b[0] for b in MODULE_BAD])
def test_guard_modul_ihlalleri(tmp_path: Path, ad: str, src: str, kod: str) -> None:
    root = _root(tmp_path, {GEN: src})
    rep = pg.guard(root, [GEN], kimlikler=False)
    assert not rep["ok"] and kod in _codes(rep), (ad, rep["violations"])


def test_guard_dosya_adi_bag_ve_boyut(tmp_path: Path) -> None:
    root = _root(tmp_path, {"tests/generated/Test_X.py": GOOD_WEB, "dis.py": GOOD_WEB})
    assert "bad_file_name" in _codes(pg.guard(root, ["tests/generated/Test_X.py"], False))
    (root / GEN).symlink_to(root / "dis.py")
    assert "unsafe_path" in _codes(pg.guard(root, [GEN], False))
    (root / GEN).unlink()
    (root / GEN).write_text("#" * (pg.MAX_BYTES + 1), encoding="utf-8")
    assert "file_too_large" in _codes(pg.guard(root, [GEN], False))
    (root / GEN).write_bytes(b"# \xff\xfe\n")
    assert "bad_encoding" in _codes(pg.guard(root, [GEN], False))


def test_guard_uygulama_imzasi_ve_platform(tmp_path: Path) -> None:
    bad = GOOD_APP.replace("(driver)", "(page)")
    root = _root(tmp_path, {APP_GEN: bad})
    assert "signature" in _codes(pg.guard(root, [APP_GEN], False))
    two = GOOD_APP.replace("@pytest.mark.android\n", "@pytest.mark.android\n@pytest.mark.ios\n")
    root2 = _root(tmp_path / "b", {APP_GEN: two})
    assert "missing_marker" in _codes(pg.guard(root2, [APP_GEN], False))


KIMLIK_BAD = [
    ("function", KIMLIKLER + "\ndef f():\n    pass\n"),
    ("import", "import os\n" + KIMLIKLER),
    ("call value", 'LOGIN = {"a": str(1)}\n'),
    ("int value", 'LOGIN = {"a": 1}\n'),
    ("dup key", 'LOGIN = {"a": "x", "a": "y"}\n'),
    ("fstring", 'LOGIN = {"a": f"x{1}"}\n'),
    ("too deep", 'LOGIN = {"a": {"b": {"c": {"d": "x"}}}}\n'),
]


@pytest.mark.parametrize(("ad", "src"), KIMLIK_BAD, ids=[k[0] for k in KIMLIK_BAD])
def test_kimlikler_saf_veri(tmp_path: Path, ad: str, src: str) -> None:
    root = _root(tmp_path, {"ekranlar/kimlikler.py": src})
    rep = pg.guard(root, [], kimlikler=True)
    assert not rep["ok"], ad


# --------------------------------------------------------------------------------- compile


def test_compile_tanilari_ve_calistirmaz(tmp_path: Path) -> None:
    marker = tmp_path / "calisti"
    root = _root(
        tmp_path,
        {
            "conftest.py": f"open({str(marker)!r}, 'w').write('x')\n",
            "pages/a.py": "def f(:\n",
            "venv/lib/x.py": "def f(:\n",
            "results/y.py": "def f(:\n",
        },
    )
    rep = pg.compile_files(root, None)
    assert not rep["ok"] and not marker.exists()
    assert [d["file"] for d in rep["diagnostics"]] == ["pages/a.py"]
    d = rep["diagnostics"][0]
    assert d["line"] == 1 and d["severity"] == "error" and "SyntaxError" in d["message"]
    assert set(rep["files"]) == {"conftest.py", "pages/a.py"}


# -------------------------------------------------------------------------------- locators


def test_locators_diff_ve_patch(tmp_path: Path) -> None:
    base = tmp_path / "base.py"
    head = tmp_path / "head.py"
    base.write_text(KIMLIKLER, encoding="utf-8")
    new = pg.locators_patch(KIMLIKLER, "LOGIN.submit.test_id", 'login-gönder"x', "kimlikler.py")
    # Yalnız literal değişti; geri kalan bayt bayt aynı.
    assert new.replace('"login-gönder\\"x"', '"login-submit"') == KIMLIKLER
    head.write_text(new, encoding="utf-8")
    rep = pg.locators_diff(base, head, "pages/kimlikler.py")
    assert rep["ok"]
    assert rep["testid_changes"] == [
        {"key": "LOGIN.submit.test_id", "old": "login-submit", "new": 'login-gönder"x'}
    ]
    head.write_text(KIMLIKLER.replace('CART = {"total": "cart-total"}', "CART = {}"), "utf-8")
    assert "locator_key_removed" in _codes(pg.locators_diff(base, head, "k.py"))
    head.write_text(KIMLIKLER + "X = {'a': 'b'}\n", "utf-8")
    assert "locator_key_added" in _codes(pg.locators_diff(base, head, "k.py"))
    with pytest.raises(pg.GuardError):
        pg.locators_patch(KIMLIKLER, "LOGIN.yok", "x")
    with pytest.raises(pg.GuardError):
        pg.locators_patch(KIMLIKLER, "CART.total", "a‮b")
    with pytest.raises(pg.GuardError):
        pg.locators_patch(KIMLIKLER, "CART.total", "")


# ------------------------------------------------------------------------------------- CLI


def _cli(*args: str) -> tuple[int, dict]:
    res = subprocess.run(
        [sys.executable, "-I", str(GUARD_PATH), *args], capture_output=True, text=True, check=False
    )
    return res.returncode, json.loads(res.stdout.strip().splitlines()[-1])


def test_cli_cikis_kodlari(tmp_path: Path) -> None:
    root = _root(tmp_path, {GEN: GOOD_WEB, "pages/login_page.py": PAGE})
    code, rep = _cli("guard", "--root", str(root), "--kimlikler")
    assert code == 0 and rep["ok"] and rep["tool"] == "py-guard"
    (root / GEN).write_text(GOOD_WEB + "exec('1')\n", encoding="utf-8")
    code, rep = _cli("guard", "--root", str(root), "--", GEN)
    assert code == 1 and not rep["ok"]
    code, rep = _cli("symbols", "--root", str(root), "--kind", "web")
    assert code == 0 and rep["page_objects"][0]["class"] == "LoginPage"
    code, rep = _cli("symbols", "--root", str(tmp_path / "yok"))
    assert code == 2 and "error" in rep
    code, rep = _cli("compile", "--root", str(root))
    assert code == 0 and rep["ok"]


def test_cli_patch_write(tmp_path: Path) -> None:
    f = tmp_path / "kimlikler.py"
    f.write_text(KIMLIKLER, encoding="utf-8")
    code, rep = _cli("locators", "patch", "--file", str(f), "--key", "CART.total",
                     "--value", "cart-grand-total", "--write")  # fmt: skip
    assert code == 0 and rep["ok"]
    assert '"cart-grand-total"' in f.read_text(encoding="utf-8")


def test_iyi_ornek_ast_ile_tutarli() -> None:
    """Örnek üretilen test gerçekten geçerli Python (derlenir, çalıştırılmaz)."""
    compile(textwrap.dedent(GOOD_WEB), GEN, "exec", dont_inherit=True)

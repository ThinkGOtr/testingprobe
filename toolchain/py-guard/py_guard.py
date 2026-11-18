"""py-guard — Python test hattının statik aracı (Ş1, TASARIM §3.1; java-araclar karşılığı).

Yalnız standart kütüphane. Analiz edilen kod ASLA içe aktarılmaz ve çalıştırılmaz: kaynak `ast` ile
ayrıştırılır, `compile()` yalnız bayt koduna çevirir (çalıştırmaz).

Alt komutlar (çıktı stdout'a JSON; çıkış kodu 0 = temiz, 1 = ihlal, 2 = araç hatası):

- `symbols --root R [--kind web|app]`: page/screen object tablosu (`pages/*.py` web, `ekranlar/*.py`
  uygulama), TS `tp-symbols` şemasında (`page_objects[].methods[].params[]`, `locator_files`).
- `guard --root R [--kimlikler] [-- dosyalar…]`: üretilen testlerin izin listesi (varsayılan:
  `tests/generated/**/test_*.py`) + (`--kimlikler`) `pages|ekranlar/kimlikler.py` saf veri mi.
- `compile --root R [-- dosyalar…]`: sözdizimi/derleme tanıları (varsayılan: kökteki tüm .py).
- `locators diff --base A --head B --file F`: onarım modu — yalnız kimlik dizgileri değişir.
- `locators patch --file F --key Grup.anahtar --value V [--write]`: tek dizgi literalini
  bayt düzeyinde değiştirir (dosyanın geri kalanı aynen kalır).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

TOOL = "py-guard"
SCHEMA_VERSION = 1
MAX_BYTES = 256 * 1024
MAX_COMPILE_BYTES = 1024 * 1024
MAX_DIAGNOSTICS = 200
GENERATED_DIR = "tests/generated"
TEST_FILE_RE = re.compile(r"\Atests/(?:[a-z0-9_]+/)*test_[a-z0-9_]+\.py\Z")
GENERATED_FILE_RE = re.compile(r"\Atests/generated/test_[a-z0-9_]+\.py\Z")
IDENT_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9_]*\Z")
SNAKE_RE = re.compile(r"\A[a-z][a-z0-9_]*\Z")
CLASS_RE = re.compile(r"\A[A-Z][A-Za-z0-9]*\Z")
TESTVERI_RE = re.compile(r"\ATP_TESTVERI_[A-Z0-9_]{1,64}\Z")
CODING_RE = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
MARKERS = frozenset({"uretilen", "web", "android", "ios", "windows", "tp_case", "story", "dealer"})
PLATFORM_MARKERS = ("web", "android", "ios", "windows")
REQUIRED_MARKERS = ("uretilen", "tp_case")
ARG_MARKERS = frozenset({"tp_case", "story", "dealer"})
PO_PACKAGES = {"web": "pages", "app": "ekranlar"}
FIXTURE_ARG = {"web": "page", "app": "driver"}
KIMLIK_FILES = ("pages/kimlikler.py", "ekranlar/kimlikler.py")
SKIP_DIRS = frozenset({"venv", ".venv", "results", "__pycache__", "node_modules", ".git"})
TYPE_MAP = {"str": "string", "int": "int", "float": "double", "bool": "boolean", "None": "void"}
ASSERTION_PREFIXES = ("expect_", "dogrula")
# Görünmez/yön denetimi karakterleri (Trojan Source): kaynakta hiç bulunamaz.
_BIDI = frozenset(
    [*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x2028, 0x2029]
)
MAX_KIMLIK_DEPTH = 3
MAX_VALUE = 200


class GuardError(RuntimeError):
    """Araç çalışamadı (çıkış kodu 2)."""


def _v(code: str, file: str, line: int, message: str) -> dict[str, Any]:
    return {"code": code, "file": file, "line": line, "message": message}


# ------------------------------------------------------------------------------- okuma


def _inside(root: Path, rel: str) -> Path | None:
    """`root/rel` (yol bileşenlerinin hiçbiri sembolik bağ değil, kök dışına çıkmıyor)."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        return None
    cur = root
    for part in Path(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            return None
    return cur


def read_source(root: Path, rel: str, limit: int = MAX_BYTES) -> tuple[str | None, dict | None]:
    """Kaynak metin ya da (None, ihlal)."""
    p = _inside(root, rel)
    if p is None:
        return None, _v("unsafe_path", rel, 0, "sembolik bağ ya da kök dışı yol kabul edilmez")
    if not p.is_file():
        return None, _v("missing_file", rel, 0, "dosya yok")
    data = p.read_bytes()
    if len(data) > limit:
        return None, _v("file_too_large", rel, 0, f"dosya {limit} bayttan büyük")
    for line in data.splitlines()[:2]:
        m = CODING_RE.match(line)
        if m and m.group(1).decode("ascii", "replace").lower().replace("_", "-") not in (
            "utf-8",
            "utf8",
        ):
            return None, _v("bad_encoding", rel, 1, "kodlama bildirimi yalnız utf-8 olabilir")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, _v("bad_encoding", rel, 0, "dosya UTF-8 değil")
    if text.startswith("﻿"):
        text = text[1:]
    for i, line in enumerate(text.splitlines(), 1):
        for ch in line:
            if ord(ch) in _BIDI or (
                unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\t\x0c"
            ):
                return None, _v(
                    "invisible_char", rel, i, f"görünmez/yön denetimi karakteri U+{ord(ch):04X}"
                )
    return text, None


def _parse(text: str, rel: str) -> tuple[ast.Module | None, dict | None]:
    try:
        return ast.parse(text, filename=rel), None
    except SyntaxError as exc:
        return None, _v("syntax_error", rel, exc.lineno or 0, f"sözdizimi hatası: {exc.msg}")
    except (ValueError, RecursionError, MemoryError) as exc:
        return None, _v("syntax_error", rel, 0, f"ayrıştırılamadı: {type(exc).__name__}")


# ----------------------------------------------------------------------------- symbols


def _type_name(node: ast.expr | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and node.value is None:
        return "void"
    if isinstance(node, ast.Name):
        return TYPE_MAP.get(node.id, node.id)
    try:
        return ast.unparse(node)[:100]
    except Exception:  # pragma: no cover - savunma
        return ""


def _method(fn: ast.FunctionDef) -> dict[str, Any]:
    args = fn.args
    pos = [*args.posonlyargs, *args.args]
    if pos and pos[0].arg in ("self", "cls"):
        pos = pos[1:]
    n_def = len(args.defaults)
    params = []
    for i, a in enumerate(pos):
        params.append(
            {"name": a.arg, "type": _type_name(a.annotation), "optional": i >= len(pos) - n_def}
        )
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=False):
        params.append({"name": a.arg, "type": _type_name(a.annotation), "optional": d is not None})
    return {
        "name": fn.name,
        "params": params,
        "returns": _type_name(fn.returns) or "void",
        "kind": "assertion" if fn.name.startswith(ASSERTION_PREFIXES) else "action",
        "async": False,
        "doc": (ast.get_docstring(fn) or "").strip(),
        "line": fn.lineno,
    }


def _assigned_names(tree: ast.Module) -> list[str]:
    out: list[str] = []
    for st in tree.body:
        targets = st.targets if isinstance(st, ast.Assign) else []
        if isinstance(st, ast.AnnAssign):
            targets = [st.target]
        out += [t.id for t in targets if isinstance(t, ast.Name)]
    return out


def detect_kind(root: Path) -> str:
    return "web" if (root / "pages").is_dir() else "app"


def symbols(root: Path, kind: str | None = None) -> dict[str, Any]:
    kind = kind or detect_kind(root)
    pkg = PO_PACKAGES[kind]
    base = root / pkg
    page_objects: list[dict[str, Any]] = []
    locator_files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not base.is_dir() or base.is_symlink():
        errors.append({"file": pkg, "message": f"{pkg}/ dizini yok"})
        files: list[Path] = []
    else:
        files = sorted(p for p in base.glob("*.py") if p.name != "__init__.py")
    for p in files:
        rel = p.relative_to(root).as_posix()
        text, viol = read_source(root, rel)
        tree = None
        if viol is None:
            tree, viol = _parse(text or "", rel)
        if viol is not None or tree is None:
            errors.append({"file": rel, "message": (viol or {}).get("message", "okunamadı")})
            continue
        if p.name == "kimlikler.py":
            locator_files.append({"file": rel, "exports": _assigned_names(tree)})
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            methods = [
                _method(fn)
                for fn in node.body
                if isinstance(fn, ast.FunctionDef) and not fn.name.startswith("_")
            ]
            if not methods:
                # Ortak taban (`Ekran`, yardımcı sınıf): eşlenecek metodu yok; Java tablosu da
                # soyut tabanı listelemez (`java-araclar symbols`).
                continue
            page_objects.append(
                {
                    "class": node.name,
                    "file": rel,
                    "doc": (ast.get_docstring(node) or "").strip(),
                    "methods": methods,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "root": pkg,
        "lang": "python",
        "kind": kind,
        "page_objects": page_objects,
        "locator_files": locator_files,
        "errors": errors,
    }


# ------------------------------------------------------------------------------- guard


def _mark_name(dec: ast.expr) -> tuple[str | None, ast.Call | None]:
    call = dec if isinstance(dec, ast.Call) else None
    target = call.func if call else dec
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Attribute)
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
        and target.value.attr == "mark"
    ):
        return target.attr, call
    return None, None


def _literal_ok(node: ast.expr, has_os: bool) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None or type(node.value) in (str, int, float, bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)
    if isinstance(node, ast.Subscript):
        v, s = node.value, node.slice
        return (
            has_os
            and isinstance(v, ast.Attribute)
            and v.attr == "environ"
            and isinstance(v.value, ast.Name)
            and v.value.id == "os"
            and isinstance(s, ast.Constant)
            and isinstance(s.value, str)
            and bool(TESTVERI_RE.match(s.value))
        )
    return False


def _docstring_like(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def guard_file(root: Path, rel: str) -> list[dict[str, Any]]:
    if not GENERATED_FILE_RE.match(rel):
        return [_v("bad_file_name", rel, 0, "üretilen test yalnız tests/generated/test_<ad>.py")]
    text, viol = read_source(root, rel)
    if viol:
        return [viol]
    tree, viol = _parse(text or "", rel)
    if viol or tree is None:
        return [viol] if viol else []
    out: list[dict[str, Any]] = []
    stem = Path(rel).stem
    imported_classes: dict[str, str] = {}
    has_os = has_page_import = has_pytest = False
    pkgs: set[str] = set()
    funcs: list[ast.FunctionDef] = []
    for st in tree.body:
        line = getattr(st, "lineno", 0)
        if isinstance(st, ast.Import):
            for a in st.names:
                if a.asname is None and a.name == "pytest":
                    has_pytest = True
                elif a.asname is None and a.name == "os":
                    has_os = True
                else:
                    out.append(_v("import_not_allowed", rel, line, f"izinsiz import: {a.name}"))
        elif isinstance(st, ast.ImportFrom):
            mod = st.module or ""
            names = [(a.name, a.asname) for a in st.names]
            if st.level:
                out.append(_v("import_not_allowed", rel, line, "göreli import yasak"))
            elif mod == "playwright.sync_api" and names == [("Page", None)]:
                has_page_import = True
            elif (
                len(mod.split(".")) == 2
                and mod.split(".")[0] in PO_PACKAGES.values()
                and SNAKE_RE.match(mod.split(".")[1])
                and mod.split(".")[1] != "kimlikler"
                and len(names) == 1
                and names[0][1] is None
                and CLASS_RE.match(names[0][0])
                and names[0][0] not in ("Page",)
            ):
                if names[0][0] in imported_classes:
                    out.append(_v("import_not_allowed", rel, line, "sınıf iki kez içe aktarıldı"))
                imported_classes[names[0][0]] = mod
                pkgs.add(mod.split(".")[0])
            else:
                shown = ", ".join(n for n, _ in names)
                out.append(_v("import_not_allowed", rel, line, f"izinsiz import: {mod} ({shown})"))
        elif isinstance(st, ast.FunctionDef):
            funcs.append(st)
        elif _docstring_like(st):
            out.append(_v("statement_not_allowed", rel, line, "belge dizgisi/ifade yasak"))
        else:
            out.append(
                _v("statement_not_allowed", rel, line, f"izinsiz deyim: {type(st).__name__}")
            )
    if not has_pytest:
        out.append(_v("missing_import", rel, 1, "import pytest gerekli"))
    if len(funcs) != 1:
        out.append(_v("function_count", rel, 1, "tam olarak bir test işlevi olmalı"))
        return out
    fn = funcs[0]
    line = fn.lineno
    if fn.name != stem:
        out.append(_v("function_name", rel, line, f"işlev adı dosya adıyla aynı olmalı: {stem}"))
    # İşaretler
    seen: list[str] = []
    for dec in fn.decorator_list:
        name, call = _mark_name(dec)
        if name is None or name not in MARKERS:
            out.append(_v("decorator_not_allowed", rel, dec.lineno, "yalnız @pytest.mark.<izinli>"))
            continue
        if name in seen:
            out.append(_v("decorator_not_allowed", rel, dec.lineno, f"yinelenen işaret: {name}"))
        seen.append(name)
        if name in ARG_MARKERS:
            ok = (
                call is not None
                and not call.keywords
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            )
        else:
            ok = call is None
        if not ok:
            out.append(_v("decorator_not_allowed", rel, dec.lineno, f"işaret biçimi: {name}"))
    for req in REQUIRED_MARKERS:
        if req not in seen:
            out.append(_v("missing_marker", rel, line, f"@pytest.mark.{req} gerekli"))
    platforms = [m for m in seen if m in PLATFORM_MARKERS]
    if len(platforms) != 1:
        out.append(_v("missing_marker", rel, line, "tam olarak bir platform işareti gerekli"))
    kind = "web" if platforms == ["web"] else "app"
    # İmza
    a = fn.args
    arg_ok = (
        not a.posonlyargs
        and not a.kwonlyargs
        and a.vararg is None
        and a.kwarg is None
        and not a.defaults
        and len(a.args) == 1
        and a.args[0].arg == FIXTURE_ARG[kind]
    )
    if arg_ok and kind == "web":
        ann = a.args[0].annotation
        arg_ok = isinstance(ann, ast.Name) and ann.id == "Page" and has_page_import
    elif arg_ok:
        arg_ok = a.args[0].annotation is None and not has_page_import
    returns_ok = isinstance(fn.returns, ast.Constant) and fn.returns.value is None
    if not arg_ok or not returns_ok:
        want = "(page: Page) -> None" if kind == "web" else "(driver) -> None"
        out.append(_v("signature", rel, line, f"imza tam olarak {want} olmalı"))
    if pkgs and pkgs != {PO_PACKAGES[kind]}:
        out.append(_v("import_not_allowed", rel, line, f"yalnız {PO_PACKAGES[kind]}.* import"))
    # Gövde
    fixture = FIXTURE_ARG[kind]
    reserved = {"page", "driver", "pytest", "os", "Page", *imported_classes}
    variables: set[str] = set()
    calls = 0
    for st in fn.body:
        sl = getattr(st, "lineno", line)
        if (
            isinstance(st, ast.Assign)
            and calls == 0
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Name)
            and st.value.func.id in imported_classes
            and not st.value.keywords
            and len(st.value.args) == 1
            and isinstance(st.value.args[0], ast.Name)
            and st.value.args[0].id == fixture
        ):
            var = st.targets[0].id
            if not SNAKE_RE.match(var) or var in reserved or var in variables:
                out.append(_v("statement_not_allowed", rel, sl, f"geçersiz değişken adı: {var}"))
            variables.add(var)
            continue
        if (
            isinstance(st, ast.Expr)
            and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Attribute)
            and isinstance(st.value.func.value, ast.Name)
            and st.value.func.value.id in variables
            and IDENT_RE.match(st.value.func.attr)
            and not st.value.keywords
        ):
            calls += 1
            for arg in st.value.args:
                if not _literal_ok(arg, has_os):
                    out.append(
                        _v("argument_not_allowed", rel, getattr(arg, "lineno", sl),
                           "argüman yalnız literal ya da os.environ[\"TP_TESTVERI_…\"]")
                    )  # fmt: skip
            continue
        out.append(
            _v("statement_not_allowed", rel, sl,
               "gövdede yalnız <değişken> = <Sınıf>(fikstür) ve <değişken>.<metot>(literal…)")
        )  # fmt: skip
    if calls == 0:
        out.append(_v("empty_test", rel, line, "test en az bir page/screen object çağrısı yapmalı"))
    return out


def _kimlik_dict(node: ast.expr, depth: int, rel: str, out: list, prefix: str, flat: dict) -> None:
    if not isinstance(node, ast.Dict) or depth > MAX_KIMLIK_DEPTH:
        line = getattr(node, "lineno", 0)
        out.append(_v("locator_not_pure", rel, line, "yalnız sözlük literali"))
        return
    keys: set[str] = set()
    for k, val in zip(node.keys, node.values, strict=False):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            line = getattr(val, "lineno", 0)
            out.append(_v("locator_not_pure", rel, line, "anahtar dizgi olmalı"))
            continue
        if k.value in keys:
            out.append(_v("locator_duplicate_key", rel, k.lineno, f"yinelenen anahtar: {k.value}"))
        keys.add(k.value)
        path = f"{prefix}.{k.value}"
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            flat[path] = (val.value, val)
        else:
            _kimlik_dict(val, depth + 1, rel, out, path, flat)


def kimlik_report(text: str, rel: str) -> tuple[list[dict], dict[str, tuple[str, ast.Constant]]]:
    """`kimlikler.py` saflık denetimi + düzleştirilmiş `Grup.anahtar[.alan]` → (değer, düğüm)."""
    tree, viol = _parse(text, rel)
    if viol or tree is None:
        return [viol] if viol else [], {}
    out: list[dict[str, Any]] = []
    flat: dict[str, tuple[str, ast.Constant]] = {}
    names: set[str] = set()
    for i, st in enumerate(tree.body):
        if i == 0 and _docstring_like(st) and isinstance(st.value.value, str):  # type: ignore[attr-defined]
            continue
        if (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and IDENT_RE.match(st.targets[0].id)
        ):
            name = st.targets[0].id
            if name in names:
                out.append(_v("locator_duplicate_key", rel, st.lineno, f"yinelenen ad: {name}"))
            names.add(name)
            _kimlik_dict(st.value, 1, rel, out, name, flat)
            continue
        out.append(
            _v("locator_not_pure", rel, getattr(st, "lineno", 0),
               "kimlikler.py yalnız AD = {sözlük literali} atamaları içerebilir")
        )  # fmt: skip
    return out, flat


def guard(root: Path, files: list[str] | None, kimlikler: bool) -> dict[str, Any]:
    if files is None or not files:
        gen = root / GENERATED_DIR
        files = []
        if gen.is_dir() and not gen.is_symlink():
            files = sorted(
                p.relative_to(root).as_posix() for p in gen.rglob("*.py") if p.name != "__init__.py"
            )
    violations: list[dict[str, Any]] = []
    for rel in files:
        violations += guard_file(root, rel)
    checked_kimlik: list[str] = []
    if kimlikler:
        for rel in KIMLIK_FILES:
            if not (root / rel).exists() and not (root / rel).is_symlink():
                continue
            checked_kimlik.append(rel)
            text, viol = read_source(root, rel)
            if viol:
                violations.append(viol)
                continue
            violations += kimlik_report(text or "", rel)[0]
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "ok": not violations,
        "files": files,
        "kimlikler": checked_kimlik,
        "violations": violations,
    }


# ----------------------------------------------------------------------------- compile


def _all_py(root: Path) -> tuple[list[str], list[dict]]:
    out: list[str] = []
    viol: list[dict] = []
    stack = [root]
    while stack:
        d = stack.pop()
        for p in sorted(d.iterdir()):
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                if p.suffix == ".py" or p.is_dir():
                    viol.append(_v("unsafe_path", rel, 0, "sembolik bağ kabul edilmez"))
                continue
            if p.is_dir():
                if p.name not in SKIP_DIRS:
                    stack.append(p)
            elif p.suffix == ".py":
                out.append(rel)
    return sorted(out), viol


def compile_files(root: Path, files: list[str] | None) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    if not files:
        files, violations = _all_py(root)
    diagnostics: list[dict[str, Any]] = []
    for rel in files:
        text, viol = read_source(root, rel, MAX_COMPILE_BYTES)
        if viol:
            violations.append(viol)
            continue
        try:
            compile(text or "", rel, "exec", flags=0, dont_inherit=True)
        except SyntaxError as exc:
            if len(diagnostics) < MAX_DIAGNOSTICS:
                diagnostics.append(
                    {
                        "file": rel,
                        "line": exc.lineno or 0,
                        "column": exc.offset or 0,
                        "severity": "error",
                        "message": f"{type(exc).__name__}: {exc.msg}"[:500],
                    }
                )
        except (ValueError, RecursionError, MemoryError) as exc:
            diagnostics.append(
                {"file": rel, "line": 0, "column": 0, "severity": "error",
                 "message": f"derlenemedi: {type(exc).__name__}"}
            )  # fmt: skip
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "ok": not diagnostics and not violations,
        "files": files,
        "diagnostics": diagnostics,
        "violations": violations,
    }


# ---------------------------------------------------------------------------- locators


def _read_any(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise GuardError(f"dosya okunamadı: {path.name}")
    root, rel = path.parent, path.name
    text, viol = read_source(root, rel)
    if viol:
        raise GuardError(viol["message"])
    return text or ""


def locators_diff(base: Path, head: Path, file: str) -> dict[str, Any]:
    bv, bflat = kimlik_report(_read_any(base), file)
    hv, hflat = kimlik_report(_read_any(head), file)
    violations = [dict(v, code=f"base_{v['code']}") for v in bv] + hv
    for k in sorted(set(bflat) - set(hflat)):
        violations.append(_v("locator_key_removed", file, 0, f"kimlik anahtarı silinemez: {k}"))
    for k in sorted(set(hflat) - set(bflat)):
        violations.append(_v("locator_key_added", file, 0, f"kimlik anahtarı eklenemez: {k}"))
    changes = [
        {"key": k, "old": bflat[k][0], "new": hflat[k][0]}
        for k in sorted(set(bflat) & set(hflat))
        if bflat[k][0] != hflat[k][0]
    ]
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "ok": not violations,
        "file": file,
        "testid_changes": changes,
        "violations": violations,
    }


def _validate_value(value: str) -> None:
    if not value or len(value) > MAX_VALUE:
        raise GuardError(f"değer 1–{MAX_VALUE} karakter olmalı")
    for ch in value:
        if ord(ch) in _BIDI or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Zl", "Zp"):
            raise GuardError(f"değerde izinsiz karakter U+{ord(ch):04X}")


def locators_patch(text: str, key: str, value: str, file: str = "kimlikler.py") -> str:
    """`key` (`Grup.anahtar[.alan]`) dizgi literalini `value` yapar; diğer baytlar aynı kalır."""
    _validate_value(value)
    viol, flat = kimlik_report(text, file)
    if viol:
        raise GuardError(f"kimlik dosyası saf değil: {viol[0]['message']}")
    if key not in flat:
        raise GuardError(f"kimlik anahtarı yok: {key}")
    node = flat[key][1]
    data = text.encode("utf-8")
    lines = data.splitlines(keepends=True)
    if node.end_lineno is None or node.end_col_offset is None:  # pragma: no cover
        raise GuardError("konum bilgisi yok")
    start = sum(len(x) for x in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(x) for x in lines[: node.end_lineno - 1]) + node.end_col_offset
    literal = json.dumps(value, ensure_ascii=False).encode("utf-8")
    new = (data[:start] + literal + data[end:]).decode("utf-8")
    _v2, flat2 = kimlik_report(new, file)
    if _v2 or flat2.get(key, ("",))[0] != value:  # pragma: no cover - savunma
        raise GuardError("yama doğrulanamadı")
    return new


# --------------------------------------------------------------------------------- CLI


def _emit(report: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0 if report.get("ok", True) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="py-guard", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("symbols")
    s.add_argument("--root", required=True)
    s.add_argument("--kind", choices=("web", "app"))
    g = sub.add_parser("guard")
    g.add_argument("--root", required=True)
    g.add_argument("--kimlikler", action="store_true")
    g.add_argument("files", nargs="*")
    c = sub.add_parser("compile")
    c.add_argument("--root", required=True)
    c.add_argument("files", nargs="*")
    loc = sub.add_parser("locators")
    lsub = loc.add_subparsers(dest="lcmd", required=True)
    d = lsub.add_parser("diff")
    d.add_argument("--base", required=True)
    d.add_argument("--head", required=True)
    d.add_argument("--file", required=True)
    p = lsub.add_parser("patch")
    p.add_argument("--file", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "symbols":
            root = Path(args.root)
            if not root.is_dir():
                raise GuardError("kök dizin yok")
            rep = symbols(root, args.kind)
            sys.stdout.write(json.dumps(rep, ensure_ascii=False) + "\n")
            return 0
        if args.cmd == "guard":
            return _emit(guard(Path(args.root), args.files, args.kimlikler))
        if args.cmd == "compile":
            return _emit(compile_files(Path(args.root), args.files))
        if args.lcmd == "diff":
            return _emit(locators_diff(Path(args.base), Path(args.head), args.file))
        path = Path(args.file)
        new = locators_patch(_read_any(path), args.key, args.value, path.name)
        if args.write:
            path.write_text(new, encoding="utf-8")
            return _emit({"tool": TOOL, "schema_version": SCHEMA_VERSION, "ok": True,
                          "file": args.file, "key": args.key})  # fmt: skip
        sys.stdout.write(new)
        return 0
    except GuardError as exc:
        sys.stdout.write(json.dumps({"tool": TOOL, "ok": False, "error": str(exc)}) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

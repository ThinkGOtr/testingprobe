"""Python dil eklentisi (Ş1; TASARIM §3.1, plan.md §3.1) — sembol tablosu, statik kontrol, koruma.

İki hedef proje, tek hat (Java yolunun `JavaKok` deseni): web (`TP_E2E_PYTHON_ROOT`, varsayılan
`e2e-python`; pytest + Playwright) ve uygulama (`TP_E2E_APP_PYTHON_ROOT[_<P>]`, varsayılan
`e2e-app-python`; pytest + Appium, platform android | ios | windows). Adımlar:

  app → deps → guard → compile → run

- **deps:** commit'teki `<kök>/requirements.lock` imajdaki güvenilir kilitle
  (`TP_E2E_PYTHON_DEPS/requirements.lock`, kaynak `toolchain/e2e-python-deps/`) bayt bayt aynı
  olmalı; koşu imajdaki venv ile yapılır, commit hiçbir paket kuramaz. `pyproject.toml` zorunludur.
  Kökte hiçbir sembolik bağ olamaz (`conftest.py`, `.pth` vb. dışarı yönelemez). pytest'in
  yapılandırma okuduğu diğer dosyalar (`pytest.ini`, `tox.ini`, `setup.cfg`) reddedilir: tek
  yapılandırma kaynağı `pyproject.toml`'dur (çakışan `addopts`/eklenti yüklemesi engellenir).
  `sitecustomize.py` / `usercustomize.py` / `*.pth` kökte hiç bulunamaz.
- **guard:** `py-guard guard --kimlikler` (yalnız ayrıştırır): `tests/generated/test_*.py` izin
  listesi + `pages|ekranlar/kimlikler.py` saf veri. `repair` modunda base..head farkında yalnız
  `kimlikler.py` dizgi değerleri değişebilir (`py-guard locators diff`).
- **compile:** `py-guard compile` (`compile()` — çalıştırmaz) kökteki tüm .py.
- **run:** test-runner `/run` `{"lang": "python", "platform": p}` (runner/diller/python_run.py).

Not (koruma sırası): guard derlemeden ÖNCE koşar; pytest hiçbir aşamada worker'da başlatılmaz
(conftest.py içe aktarılınca kod çalıştırır).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from toolchain_common import gitforge, proc

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from toolchain_common import repos
    from toolchain_common.settings import Settings
    from worker.check import CheckRequest

DIL = "python"
WEB = "web"
APP_PLATFORMS = ("android", "ios", "windows")
PLATFORMLAR = (WEB, *APP_PLATFORMS)
STEPS = ("app", "deps", "guard", "compile", "run")
HAT = "tam"
WEB_KOK_AYARI, WEB_KOK = "TP_E2E_PYTHON_ROOT", "e2e-python"
APP_KOK_AYARI, APP_KOK = "TP_E2E_APP_PYTHON_ROOT", "e2e-app-python"
LOCK_NAME = "requirements.lock"
GENERATED_DIR = "tests/generated"
TEST_FILE_RE = re.compile(r"\Atests/(?:[a-z0-9_]+/)*test_[a-z0-9_]+\.py\Z")
KIMLIK_RE = re.compile(r"\A(?:pages|ekranlar)/kimlikler\.py\Z")
# pytest'in kök dizinden okuduğu ve `pyproject.toml` dışında yapılandırma taşıyan dosyalar.
YASAK_YAPILANDIRMA = ("pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg")
YASAK_ADLAR = ("sitecustomize.py", "usercustomize.py")
# Analiz aracına kullanıcı ortamından Python seçeneği sızmasın.
PY_ENV_DROP = ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PYTHONINSPECT", "PYTHONUSERBASE")


class PyAracError(RuntimeError):
    """py-guard çalışamadı (süre aşımı, bozuk çıktı, beklenmeyen çıkış kodu)."""


# --------------------------------------------------------------------------------- ayarlar


def _ayar(cfg: Any, attr: str, env: str, default: str) -> str:
    """Settings alanı (Ş0 ekleyince) > ortam değişkeni > varsayılan."""
    val = getattr(cfg, attr, None)
    if isinstance(val, Path):
        return str(val)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return os.environ.get(env, "").strip() or default


def deps_dir(cfg: Any) -> Path:
    return Path(_ayar(cfg, "e2e_python_deps", "TP_E2E_PYTHON_DEPS", "/opt/e2e-python"))


def venv_python(cfg: Any) -> str:
    return _ayar(cfg, "python_e2e", "TP_PYTHON_E2E", "/opt/e2e-python/venv/bin/python")


def guard_script(cfg: Any) -> str:
    return _ayar(cfg, "py_guard", "TP_PY_GUARD", str(deps_dir(cfg) / "py-guard" / "py_guard.py"))


def guard_python(cfg: Any) -> str:
    sistem = "/usr/bin/python3.12"
    return _ayar(
        cfg, "py_guard_python", "TP_PY_GUARD_PYTHON",
        sistem if Path(sistem).exists() else sys.executable,
    )  # fmt: skip


def dil_timeout_s(cfg: Any) -> float:
    val = getattr(cfg, "dil_timeout_s", None)
    if isinstance(val, int | float) and val > 0:
        return float(val)
    try:
        return float(os.environ.get("TP_DIL_TIMEOUT_S", "") or 300)
    except ValueError:
        return 300.0


def _kok_coz(cfg: Any, kok_ayari: str, varsayilan: str, platform: str | None) -> str:
    """Ş0 `worker.diller.kok` (proje bloğu `dil_kokleri` > `<ayar>_<P>` > `<ayar>` > varsayılan);
    Ş0 öncesi aynı kuralın env yedeği."""
    try:
        from worker.diller import kok as s0_kok  # type: ignore[attr-defined]
    except ImportError:
        s0_kok = None
    if s0_kok is not None:
        return s0_kok(cfg, kok_ayari, varsayilan, platform)
    if platform and platform != WEB:
        deger = os.environ.get(f"{kok_ayari}_{platform.upper()}", "").strip()
        if deger:
            return deger
    return os.environ.get(kok_ayari, "").strip() or varsayilan


@dataclass(frozen=True)
class PyKok:
    platform: str
    root: str  # forge deposunda proje kökü
    deps: Path  # imajdaki güvenilir kilit + venv dizini
    ad: str  # iletilerdeki proje adı (e2e-python | e2e-app-python)

    @property
    def web(self) -> bool:
        return self.platform == WEB

    @property
    def kind(self) -> str:
        return "web" if self.web else "app"


def py_kok(cfg: Any, platform: str | None) -> PyKok:
    p = platform or WEB
    if p not in PLATFORMLAR:
        raise ValueError(f"platform yalnızca {PLATFORMLAR} olabilir")
    if p == WEB:
        return PyKok(WEB, _kok_coz(cfg, WEB_KOK_AYARI, WEB_KOK, None).strip("/"), deps_dir(cfg),
                     WEB_KOK)  # fmt: skip
    root = _kok_coz(cfg, APP_KOK_AYARI, APP_KOK, p).strip("/")
    return PyKok(p, root, deps_dir(cfg), APP_KOK)


def validate_test_file(value: str) -> str:
    if not isinstance(value, str) or not TEST_FILE_RE.match(value) or ".." in value:
        raise ValueError(
            f"geçersiz Python test dosyası: {value!r} (beklenen: tests/**/test_<ad>.py)"
        )
    return value


# ------------------------------------------------------------------------------ py-guard


def _guard_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in PY_ENV_DROP}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def guard_argv(cfg: Any, *args: str) -> list[str]:
    # -I: yalıtılmış kip (PYTHON* ortamı, kullanıcı site-packages ve betik/çalışma dizini sys.path'e
    # girmez); analiz edilen kökteki hiçbir modül içe aktarılamaz.
    return [guard_python(cfg), "-I", guard_script(cfg), *args]


def _run_guard_tool(cfg: Any, args: list[str], what: str, timeout_s: float) -> dict[str, Any]:
    import json

    res = proc.run(guard_argv(cfg, *args), env=_guard_env(), timeout_s=timeout_s,
                   keep_full_stdout=True)  # fmt: skip
    if res.timed_out:
        raise PyAracError(f"py-guard {what} süre sınırını aştı")
    try:
        report = json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else None
    except (json.JSONDecodeError, IndexError) as exc:
        raise PyAracError(f"py-guard {what} çıktısı okunamadı: {res.stderr.strip()[:500]}") from exc
    if not isinstance(report, dict) or res.exit_code == 2:
        msg = report.get("error") if isinstance(report, dict) else None
        raise PyAracError(f"py-guard {what} çalışamadı: {msg or res.stderr.strip()[:500]}")
    if res.exit_code not in (0, 1) or bool(report.get("ok", True)) != (res.exit_code == 0):
        raise PyAracError(f"py-guard {what} beklenmeyen çıkış kodu {res.exit_code}")
    return report


def run_symbols(cfg: Any, root: Path, kok: PyKok) -> dict[str, Any]:
    timeout = float(getattr(cfg, "symbols_timeout_s", 60) or 60)
    return _run_guard_tool(
        cfg, ["symbols", "--root", str(root), "--kind", kok.kind], "symbols", timeout
    )


def symbols_table(cfg: Any, root: Path, kok: PyKok) -> dict[str, Any]:
    """`/symbols` tablosu (plan.md §3.3): `page_objects` (tp-symbols şeması) + normalleştirilmiş
    görünüm (`classes`, `ids`)."""
    table = run_symbols(cfg, root, kok)
    table["classes"] = [
        {
            "name": po["class"],
            "methods": [
                {"name": m["name"], "kind": m["kind"],
                 "params": [{"name": p["name"], "type": p["type"]} for p in m["params"]]}
                for m in po.get("methods", [])
            ],
        }
        for po in table.get("page_objects", [])
    ]  # fmt: skip
    table.setdefault("ids", [])
    table["lang"] = DIL
    if kok.web:
        table["platform"] = WEB
    return table


def symbols(cfg: Any, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
    kok = py_kok(cfg, platform)
    with gitforge.checkout(repo, full_sha, kok.root, cfg.git_timeout_s) as root:
        return symbols_table(cfg, root, kok)


# ---------------------------------------------------------------------------------- deps


def _sha256(path: Path) -> str | None:
    import hashlib

    try:
        if path.is_symlink() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def check_deps(cfg: Any, root: Path, kok: PyKok) -> dict[str, Any]:
    """Kilit bayt eşitliği + kökte bağ / yasak yapılandırma yok + `pyproject.toml` var."""
    want = _sha256(kok.deps / LOCK_NAME)
    if want is None:
        return {"ok": False, "error": f"İmajda {kok.ad} {LOCK_NAME} yok (toolchain imajı hatalı)."}
    if root.is_symlink():
        return {"ok": False, "error": f"{kok.root} sembolik bağ olamaz."}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            return {"ok": False, "error": f"{rel}: sembolik bağ kabul edilmez.", "file": rel}
        if p.name in YASAK_ADLAR or p.suffix == ".pth":
            return {
                "ok": False,
                "error": f"{rel}: Python başlatıcısının yüklediği dosya kabul edilmez.",
                "file": rel,
            }
    for name in YASAK_YAPILANDIRMA:
        if (root / name).exists():
            return {
                "ok": False,
                "error": (
                    f"{kok.root}/{name}: pytest yapılandırması yalnız pyproject.toml'da olabilir "
                    "(ek yapılandırma dosyası eklenti/addopts yükleyebilir)."
                ),
                "config_file": name,
            }
    if not (root / "pyproject.toml").is_file():
        return {"ok": False, "error": f"Commit'te {kok.root}/pyproject.toml yok."}
    have = _sha256(root / LOCK_NAME)
    if have is None:
        return {"ok": False, "error": f"Commit'te {kok.root}/{LOCK_NAME} yok."}
    if have != want:
        return {
            "ok": False,
            "error": (
                f"{kok.root}/{LOCK_NAME} imajdaki güvenilir kilitten farklı; koşu ortamında yeni "
                "paket kurulamaz (toolchain imajı yeniden derlenmeli: "
                "toolchain/e2e-python-deps/requirements.lock)."
            ),
            "lock_sha256": have,
            "image_lock_sha256": want,
        }
    return {"ok": True, "lock_sha256": have}


# --------------------------------------------------------------------------------- guard


def generated_files(root: Path) -> list[str]:
    gen = root / GENERATED_DIR
    if not gen.is_dir() or gen.is_symlink():
        return []
    return sorted(
        p.relative_to(root).as_posix() for p in gen.rglob("*.py") if p.name != "__init__.py"
    )


def run_guard(cfg: Any, root: Path, files: list[str] | None = None) -> dict[str, Any]:
    files = generated_files(root) if files is None else files
    timeout = float(getattr(cfg, "ast_guard_timeout_s", 60) or 60)
    return _run_guard_tool(
        cfg, ["guard", "--root", str(root), "--kimlikler", "--", *files], "guard", timeout
    )


def _git_bytes(cfg: Any, repo: Path, *args: str) -> bytes:
    try:
        out = subprocess.run(
            gitforge._git_argv(repo, *args),
            env=gitforge.git_env(),
            capture_output=True,
            timeout=cfg.git_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitforge.ForgeError("git süre aşımı") from exc
    if out.returncode != 0:
        msg = out.stderr.decode("utf-8", "replace").strip()
        raise gitforge.ForgeError(f"git {args[0]} başarısız: {msg[:300]}")
    return out.stdout


def repair_guard(cfg: Any, repo: Path, base: str, head: str, kok: PyKok) -> dict[str, Any]:
    """Onarım modu: base..head'de yalnız `pages|ekranlar/kimlikler.py` dizgi değerleri değişir."""
    raw = _git_bytes(
        cfg, repo, "diff", "--name-status", "--no-renames", "-z", "--end-of-options", base, head
    ).decode("utf-8", "replace")
    parts = [p for p in raw.split("\0") if p]
    prefix = kok.root.strip("/") + "/"
    changed: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    testid_changes: list[dict[str, Any]] = []
    timeout = float(getattr(cfg, "ast_guard_timeout_s", 60) or 60)
    for status, path in zip(parts[0::2], parts[1::2], strict=False):
        rel = path[len(prefix) :] if path.startswith(prefix) else None
        locator = rel is not None and bool(KIMLIK_RE.match(rel))
        st = {"A": "added", "D": "deleted"}.get(status[:1], "modified")
        changed.append({"path": path, "status": st, "locator": locator})
        if not locator:
            violations.append({"code": "non_locator_file_changed", "file": path,
                               "message": "onarımda yalnız kimlikler.py değişebilir"})  # fmt: skip
            continue
        if st != "modified":
            fiil = "eklenemez" if st == "added" else "silinemez"
            violations.append({"code": f"locator_file_{st}", "file": path,
                               "message": f"kimlikler.py onarımda {fiil}"})  # fmt: skip
            continue
        with tempfile.TemporaryDirectory(prefix="tp-py-kimlik-") as tmp:
            a, b = Path(tmp) / "base.py", Path(tmp) / "head.py"
            a.write_bytes(_git_bytes(cfg, repo, "show", f"{base}:{path}"))
            b.write_bytes(_git_bytes(cfg, repo, "show", f"{head}:{path}"))
            rep = _run_guard_tool(
                cfg,
                ["locators", "diff", "--base", str(a), "--head", str(b), "--file", path],
                "locators diff",
                timeout,
            )
        violations += rep.get("violations") or []
        testid_changes += rep.get("testid_changes") or []
    ok = not violations
    return {
        "tool": "py-guard",
        "schema_version": 1,
        "mode": "repair",
        "ok": ok,
        "noop": not changed,
        "base": base,
        "head": head,
        "root": kok.root,
        "changed_files": changed,
        "testid_changes": testid_changes,
        "added_entries": [],
        "removed_entries": [],
        "violations": violations,
        "summary": (
            f"Kimlik koruması {'geçti' if ok else 'başarısız'} (mod: repair) · değişen dosya: "
            f"{len(changed)} · kimlik değişikliği: {len(testid_changes)}"
        ),
    }


def guard_report(
    cfg: Any, repo: Path, base: str, head: str, mode: str, root: Path, kok: PyKok
) -> dict[str, Any]:
    """`/ast-guard` ve `/check` tek raporu (worker/java.py `guard_report` biçimi)."""
    gen = run_guard(cfg, root)
    rep = repair_guard(cfg, repo, base, head, kok) if mode == "repair" else None
    violations = list(gen.get("violations") or []) + list((rep or {}).get("violations") or [])
    ok = not violations
    return {
        "tool": "py-guard",
        "schema_version": 1,
        "mode": mode,
        "ok": ok,
        "noop": False,
        "base": base,
        "head": head,
        "root": kok.root,
        "files": gen.get("files", []),
        "changed_files": (rep or {}).get("changed_files", []),
        "testid_changes": (rep or {}).get("testid_changes", []),
        "added_entries": [],
        "removed_entries": [],
        "violations": violations,
        "summary": (
            f"Python AST koruması {'geçti' if ok else 'başarısız'} (mod: {mode}) · üretilen "
            f"test: {len(gen.get('files', []))} · ihlal: {len(violations)}"
        ),
        "generated": gen,
        "repair": rep,
    }


def guard(cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str) -> dict[str, Any]:
    kok = py_kok(cfg, platform)
    with gitforge.checkout(repo, head, kok.root, cfg.git_timeout_s) as root:
        return guard_report(cfg, repo, base, head, mode, root, kok)


# ------------------------------------------------------------------------------- compile


def run_compile(cfg: Any, root: Path, kok: PyKok) -> dict[str, Any]:
    try:
        rep = _run_guard_tool(cfg, ["compile", "--root", str(root)], "compile", dil_timeout_s(cfg))
    except PyAracError as exc:
        return {"ok": False, "error": str(exc), "diagnostics": []}
    out: dict[str, Any] = {
        "ok": bool(rep.get("ok")),
        "diagnostics": rep.get("diagnostics") or [],
        "files": len(rep.get("files") or []),
        "violations": rep.get("violations") or [],
    }
    if not out["ok"]:
        d = out["diagnostics"][:1] or out["violations"][:1]
        where = f": {d[0].get('file')}:{d[0].get('line')} {d[0].get('message')}" if d else ""
        out["error"] = f"Python derleme denetimi başarısız ({kok.root}){where}"
    return out


# ------------------------------------------------------------------------------ /check


def run_static(
    cfg: Settings,
    req: CheckRequest,
    head: repos.Located,
    base: str | None,
    runner_client: httpx.Client | None,
    steps: dict[str, dict[str, Any]],
    *,
    run: bool = True,
) -> dict[str, dict[str, Any]]:
    """app → deps → guard → compile → (run). worker/check.py `_run_java_steps` ile aynı düzen;
    ilk başarısız adımda durulur. `run=False` statik adımlarla yetinir."""
    from worker import check as checks

    full = head.sha
    kok = py_kok(cfg, req.platform)
    steps["app"] = checks.app_step(cfg, head)
    if not steps["app"]["ok"]:
        return steps
    base_sha = base or gitforge.merge_base(head.repo, full, "main", cfg.git_timeout_s) or full
    with gitforge.checkout(head.repo, full, kok.root, cfg.git_timeout_s) as root:
        missing = [f for f in req.test_files if not (root / f).is_file()]
        if missing:
            steps["deps"] = {
                "ok": False,
                "error": "Test dosyası commit'te yok: " + ", ".join(missing),
                "missing_test_files": missing,
            }
            return steps
        steps["deps"] = check_deps(cfg, root, kok)
        if not steps["deps"]["ok"]:
            return steps
        try:
            rep = guard_report(cfg, head.repo, base_sha, full, req.ast_guard_mode, root, kok)
            steps["guard"] = {"ok": bool(rep.get("ok")), "mode": req.ast_guard_mode,
                              "base_sha": base_sha, "report": rep}  # fmt: skip
        except PyAracError as exc:
            steps["guard"] = {"ok": False, "mode": req.ast_guard_mode, "error": str(exc)}
        if not steps["guard"]["ok"]:
            return steps
        steps["compile"] = run_compile(cfg, root, kok)
        if not steps["compile"]["ok"] or not run:
            return steps

    body: dict[str, Any] = {
        "sha": full,
        "run_id": req.run_id or checks.default_run_id(full),
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "test_files": list(req.test_files),
        "env": req.runner_env(),
        "keep": req.keep,
        "lang": DIL,
        "platform": kok.platform,
    }
    steps["run"] = checks._call_runner(cfg, body, runner_client)
    return steps


def run_steps(
    cfg: Settings,
    req: CheckRequest,
    head: repos.Located,
    base: str | None,
    runner_client: httpx.Client | None,
    steps: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return run_static(cfg, req, head, base, runner_client, steps, run=True)


class _PythonEklentisi:
    """plan.md §3.1 `WorkerDili` (Ş0 keşfi `EKLENTI`'yi okur)."""

    ad = DIL
    platformlar = PLATFORMLAR
    steps = STEPS
    hat = HAT

    def validate_test_file(self, yol: str) -> str:
        return validate_test_file(yol)

    def symbols(self, cfg: Settings, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        return symbols(cfg, full_sha, repo, platform)

    def guard(
        self, cfg: Settings, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]:
        return guard(cfg, repo, base, head, mode, platform)

    def run_static(
        self,
        cfg: Settings,
        req: CheckRequest,
        head: repos.Located,
        base: str | None,
        runner_client: httpx.Client | None,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return run_static(cfg, req, head, base, runner_client, steps)


EKLENTI = _PythonEklentisi()

__all__ = ["EKLENTI", "PyAracError", "PyKok", "py_kok"]

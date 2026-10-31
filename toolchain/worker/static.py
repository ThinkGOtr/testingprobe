"""Statik kontroller: bağımlılık kilidi, `tsc --noEmit`, `eslint --no-inline-config`.

toolchain-worker test kodu ÇALIŞTIRMAZ (TEKNIK-TASARIM §4/§5). `tsc` kodu yalnızca ayrıştırır;
ESLint ise yapılandırma dosyasını (`eslint.config.js`) Node ile yükler. Bu yüzden commit'teki
yapılandırma imajdaki güvenilir kopyayla (demo-app/e2e/eslint.config.js'in imaja alınmış hali)
bayt bayt aynı olmalıdır; farklıysa ESLint koşmaz ve kontrol başarısız olur.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from toolchain_common import proc
from toolchain_common.settings import Settings

TSC_LINE = re.compile(
    r"^(?P<file>[^\s(][^(]*)\((?P<line>\d+),(?P<col>\d+)\): (?P<sev>error|warning) "
    r"(?P<code>TS\d+): (?P<msg>.*)$"
)
MAX_DIAGNOSTICS = 200


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def check_deps(cfg: Settings, e2e: Path) -> dict[str, Any]:
    """Commit'in `package-lock.json`'ı imajdaki çevrimdışı bağımlılıklarla aynı mı."""
    have = _sha256(e2e / "package-lock.json")
    want = _sha256(cfg.e2e_deps / "package-lock.json")
    if want is None:
        return {"ok": False, "error": "İmajda e2e bağımlılık kilidi yok (toolchain imajı hatalı)."}
    if have is None:
        return {"ok": False, "error": "Commit'te e2e/package-lock.json yok."}
    if have != want:
        return {
            "ok": False,
            "error": (
                "e2e/package-lock.json imajdaki bağımlılıklardan farklı; çevrimdışı ortamda yeni "
                "bağımlılık kurulamaz (toolchain imajı yeniden derlenmeli)."
            ),
            "lock_sha256": have,
            "image_lock_sha256": want,
        }
    return {"ok": True, "lock_sha256": have}


def _relpath(raw: str, e2e: Path) -> str:
    p = Path(raw)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(e2e.resolve()))
        except ValueError:
            return p.name
    return raw


def parse_tsc(output: str, e2e: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = TSC_LINE.match(line.strip())
        if not m:
            continue
        out.append(
            {
                "file": _relpath(m["file"], e2e),
                "line": int(m["line"]),
                "column": int(m["col"]),
                "severity": m["sev"],
                "code": m["code"],
                "message": m["msg"][:500],
            }
        )
        if len(out) >= MAX_DIAGNOSTICS:
            break
    return out


def run_tsc(cfg: Settings, e2e: Path) -> dict[str, Any]:
    tsc = e2e / "node_modules" / "typescript" / "bin" / "tsc"
    res = proc.run(
        [cfg.node, str(tsc), "--noEmit", "-p", "tsconfig.json", "--pretty", "false"],
        cwd=e2e,
        timeout_s=cfg.tsc_timeout_s,
    )
    diagnostics = parse_tsc(res.stdout, e2e)
    result: dict[str, Any] = {
        "ok": res.ok,
        "exit_code": res.exit_code,
        "duration_ms": res.duration_ms,
        "diagnostics": diagnostics,
        "output": proc.truncate(res.stdout + res.stderr, 16 * 1024),
    }
    if res.timed_out:
        result["error"] = f"tsc süre sınırını aştı ({int(cfg.tsc_timeout_s)} sn)"
    elif not res.ok and not diagnostics:
        result["error"] = "tsc başarısız (ayrıntı: output)"
    return result


def parse_eslint(stdout: str, e2e: Path) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out: list[dict[str, Any]] = []
    for f in data:
        if not isinstance(f, dict):
            continue
        for m in f.get("messages") or []:
            if not isinstance(m, dict):
                continue
            out.append(
                {
                    "file": _relpath(str(f.get("filePath", "")), e2e),
                    "line": m.get("line"),
                    "column": m.get("column"),
                    "severity": "error" if m.get("severity") == 2 else "warning",
                    "rule": m.get("ruleId"),
                    "message": str(m.get("message", ""))[:500],
                }
            )
            if len(out) >= MAX_DIAGNOSTICS:
                return out
    return out


# ESLint'in kod olarak yüklediği yerel dosyalar: yapılandırma ve (varsa) onun içe aktardığı yerel
# modüller (`/opt/e2e/tools/**.js`). Her biri imajdaki güvenilir kopyayla bayt bayt aynı olmalıdır;
# aksi halde commit, içe aktarılan bir modül üzerinden toolchain-worker'da kod çalıştırabilirdi.
# Yapılandırmanın göreli içe aktarmalarının bu kümede olduğunu tests/test_e2e_deps.py denetler.
CONFIG_FILE = "eslint.config.js"
TRUSTED_TOOLS_DIR = "tools"


def trusted_config_files(e2e_deps: Path) -> list[str]:
    tools = e2e_deps / TRUSTED_TOOLS_DIR
    extra = (
        sorted(str(p.relative_to(e2e_deps)) for p in tools.rglob("*.js") if p.is_file())
        if tools.is_dir()
        else []
    )
    return [CONFIG_FILE, *extra]


def run_eslint(cfg: Settings, e2e: Path) -> dict[str, Any]:
    for rel in trusted_config_files(cfg.e2e_deps):
        trusted = _sha256(cfg.e2e_deps / rel)
        have = _sha256(e2e / rel)
        if trusted is None:
            return {
                "ok": False,
                "error": f"İmajda güvenilir {rel} yok (toolchain imajı hatalı).",
            }
        if have != trusted:
            return {
                "ok": False,
                "error": (
                    f"{rel} güvenilir kopyadan farklı; yapılandırma kod olarak "
                    "yüklendiği için toolchain-worker değiştirilmiş yapılandırmayı çalıştırmaz "
                    "(imaj güncellenmeli)."
                ),
                "config_file": rel,
                "config_sha256": have,
            }
    eslint = e2e / "node_modules" / "eslint" / "bin" / "eslint.js"
    res = proc.run(
        [
            cfg.node,
            str(eslint),
            "--no-inline-config",
            "--max-warnings=0",
            "--format",
            "json",
            ".",
        ],
        cwd=e2e,
        timeout_s=cfg.eslint_timeout_s,
        keep_full_stdout=True,
    )
    messages = parse_eslint(res.stdout, e2e)
    result: dict[str, Any] = {
        "ok": res.ok,
        "exit_code": res.exit_code,
        "duration_ms": res.duration_ms,
        "messages": messages or [],
    }
    if res.timed_out:
        result["error"] = f"eslint süre sınırını aştı ({int(cfg.eslint_timeout_s)} sn)"
    elif messages is None:
        result["error"] = "eslint çıktısı okunamadı"
        result["output"] = proc.truncate(res.stdout + res.stderr, 16 * 1024)
    elif not res.ok and not messages:
        result["output"] = proc.truncate(res.stderr, 16 * 1024)
    return result

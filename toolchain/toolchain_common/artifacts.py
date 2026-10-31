"""`TP_ARTIFACTS_PATH` yazımı: kök içinde kalan yollar, atomik JSON."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from toolchain_common.validation import SHA_RE, validate_run_id


def ensure_inside(root: Path, path: Path) -> Path:
    """`path` gerçekten `root`'un altında mı (symlink çözülerek)."""
    root_r = root.resolve()
    path_r = path.resolve()
    if path_r != root_r and root_r not in path_r.parents:
        raise ValueError(f"yol artefakt kökü dışında: {path}")
    return path


def run_dir(root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    return ensure_inside(root, root / "runs" / run_id)


def checks_file(root: Path, sha: str) -> Path:
    if not SHA_RE.match(sha) or len(sha) < 40:
        raise ValueError(f"checks dosyası için tam sha gerekir: {sha!r}")
    return ensure_inside(root, root / "checks" / f"{sha}.json")


def atomic_write_json(path: Path, data: Any) -> None:
    """Geçici dosya + `os.replace`: okuyucu (LocalForge) yarım dosya görmez."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        # core-api/core-worker (uid 10001) salt okur.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check_writable(root: Path) -> str:
    """`/health`: artefakt kökü var ve yazılabilir mi."""
    if not root.is_dir():
        return f"error: {root} yok"
    if not os.access(root, os.W_OK | os.X_OK):
        return f"error: {root} yazılamıyor (uid {os.getuid()})"
    return "ok"

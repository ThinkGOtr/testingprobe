"""İmaja giren e2e bağımlılık manifestleri demo-app/e2e ile birebir aynı olmalı.

Fark varsa: `cp demo-app/e2e/{package.json,package-lock.json,eslint.config.js} toolchain/e2e-deps/`
(yapılandırma yerel bir modül içe aktarıyorsa onu da `toolchain/e2e-deps/tools/` altına) ve
toolchain imajını yeniden derleyin. Aksi halde /check `deps` veya `eslint` adımında başarısız olur.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import DEMO_E2E, TOOLCHAIN
from worker.static import trusted_config_files

DEPS = TOOLCHAIN / "e2e-deps"
RELATIVE_IMPORT = re.compile(r"""^\s*import\b[^;]*?from\s+["'](\.{1,2}/[^"']+)["']""", re.M)


@pytest.mark.parametrize("name", ["package.json", "package-lock.json", "eslint.config.js"])
def test_vendored_e2e_manifest_matches_demo_app(name: str) -> None:
    assert (DEPS / name).read_bytes() == (DEMO_E2E / name).read_bytes(), name


def test_trusted_config_modules_match_demo_app() -> None:
    for rel in trusted_config_files(DEPS):
        assert (DEPS / rel).read_bytes() == (DEMO_E2E / rel).read_bytes(), rel


def test_config_imports_only_trusted_local_modules() -> None:
    """eslint.config.js'in içe aktardığı her yerel modül güvenilir kümede olmalı.

    Yoksa commit, yapılandırmanın içe aktardığı (hash'i denetlenmeyen) modülü değiştirerek
    toolchain-worker'da kod çalıştırabilirdi.
    """
    trusted = set(trusted_config_files(DEPS))
    seen: set[str] = set()
    todo = [Path("eslint.config.js")]
    while todo:
        rel = todo.pop()
        if str(rel) in seen:
            continue
        seen.add(str(rel))
        assert str(rel) in trusted, f"{rel} güvenilir kopyalar arasında değil"
        text = (DEPS / rel).read_text(encoding="utf-8")
        for spec in RELATIVE_IMPORT.findall(text):
            todo.append(Path(_norm((rel.parent / spec).as_posix())))


def _norm(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            assert parts, f"yapılandırma e2e kökü dışından içe aktarıyor: {path}"
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)

"""İmaja giren e2e bağımlılık manifestleri demo-app/e2e ile birebir aynı olmalı.

Fark varsa: `cp demo-app/e2e/{package.json,package-lock.json,eslint.config.js} toolchain/e2e-deps/`
ve toolchain imajını yeniden derleyin. Aksi halde /check `deps` veya `eslint` adımında
başarısız olur.
"""

from __future__ import annotations

import pytest

from tests.conftest import DEMO_E2E, TOOLCHAIN


@pytest.mark.parametrize("name", ["package.json", "package-lock.json", "eslint.config.js"])
def test_vendored_e2e_manifest_matches_demo_app(name: str) -> None:
    assert (TOOLCHAIN / "e2e-deps" / name).read_bytes() == (DEMO_E2E / name).read_bytes(), name

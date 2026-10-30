"""Anayasa II: golden-drift ortamında ajan bağımlılığı ve geçit kodu YOK.

Bu paket CI'da `uv run --no-project --with-requirements requirements.txt` ile koşar; ortam yalnızca
pytest + jsonschema + pyyaml içerir. Biri requirements.txt'e ajan SDK'sı ekler ya da job'u core
venv'ine geri taşırsa bu test kırmızı olur.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

FORBIDDEN = ("anthropic", "mcp", "tp_core", "claude_agent_sdk")
HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize("module", FORBIDDEN)
def test_agent_dependency_not_importable(module: str) -> None:
    assert importlib.util.find_spec(module) is None, f"{module} bu ortamda kurulu olmamalı"


def test_requirements_pin_only_data_tools() -> None:
    names = {
        line.split("==", 1)[0].strip().lower()
        for line in (HERE / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert names == {"pytest", "jsonschema", "pyyaml"}


def test_suite_sources_do_not_import_agent_code() -> None:
    for path in sorted(HERE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not roots & set(FORBIDDEN), f"{path.name}: {sorted(roots & set(FORBIDDEN))}"

"""Prompt paketi (bundle): rules/ altındaki prompt + şema + few-shot + model kimliği + parametreler.

`bundle_hash` = sha256(kanonik JSON {prompt dosyası, ortak güvenlik kuralları, şema, few-shot,
model, parametreler}) — TEKNIK-TASARIM §8.8. Herhangi biri değişirse hash değişir; replay kaydı
birebir eşleşmez ve adlandırılmış golden kayda (REPLAY-MISS) düşülür.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tp_core.gateway.canonical import canonical_json, sha256_hex
from tp_core.gateway.config import PurposeConfig
from tp_core.gateway.errors import GatewayConfigError

GUARDRAILS_FILE = "_guardrails.md"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Bundle:
    name: str
    id: str
    version: int
    system_prompt: str  # model'e giden son hal (prompt + güvenlik kuralları + few-shot)
    hash: str

    @property
    def label(self) -> str:
        return f"{self.id}@v{self.version}"


def _check_name(name: str, what: str) -> None:
    if not _NAME_RE.match(name):
        raise GatewayConfigError(f"Geçersiz {what} adı: {name!r}")


def parse_prompt_file(text: str, path: Path) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        raise GatewayConfigError(f"{path}: YAML ön bilgisi (--- id/version ---) yok")
    meta = yaml.safe_load(match.group(1)) or {}
    if "id" not in meta or "version" not in meta:
        raise GatewayConfigError(f"{path}: ön bilgide 'id' ve 'version' zorunlu")
    return meta, match.group(2).strip()


def load_schema(rules_dir: Path, purpose: str) -> dict[str, Any]:
    """rules/schemas/<purpose>.schema.json"""
    _check_name(purpose, "amaç")
    path = rules_dir / "schemas" / f"{purpose}.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı") from None


def _load_fewshot(rules_dir: Path, name: str) -> list[dict[str, Any]]:
    directory = rules_dir / "fewshot" / name
    if not directory.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def _render_system(body: str, guardrails: str, fewshot: list[dict[str, Any]]) -> str:
    parts = [body, guardrails]
    if fewshot:
        rendered = "\n\n".join(
            f'<example index="{i}">\n{json.dumps(ex, ensure_ascii=False, indent=2)}\n</example>'
            for i, ex in enumerate(fewshot, start=1)
        )
        parts.append("## Examples\n\n" + rendered)
    return "\n\n".join(p for p in parts if p)


def load_bundle(
    rules_dir: Path, name: str, schema: dict[str, Any], purpose: PurposeConfig
) -> Bundle:
    _check_name(name, "bundle")
    path = rules_dir / "prompts" / f"{name}.md"
    try:
        prompt_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı") from None
    meta, body = parse_prompt_file(prompt_text, path)
    guardrails_path = rules_dir / "prompts" / GUARDRAILS_FILE
    guardrails_text = (
        guardrails_path.read_text(encoding="utf-8") if guardrails_path.is_file() else ""
    )
    guardrails = parse_prompt_file(guardrails_text, guardrails_path)[1] if guardrails_text else ""
    fewshot = _load_fewshot(rules_dir, name)
    digest = sha256_hex(
        canonical_json(
            {
                "prompt": prompt_text,
                "guardrails": guardrails_text,
                "schema": schema,
                "fewshot": fewshot,
                "model": purpose.model,
                "params": purpose.params,
                "max_tokens": purpose.max_tokens,
            }
        )
    )
    return Bundle(
        name=name,
        id=str(meta["id"]),
        version=int(meta["version"]),
        system_prompt=_render_system(body, guardrails, fewshot),
        hash=digest,
    )

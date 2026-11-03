"""rules/schemas/* canlı Anthropic API ile uyumlu mu (anahtar yokken de denetlenir).

İki kullanım (anthropic_provider.py):
1. Tek çağrı: `output_config.format = {type: json_schema, schema: transform_schema(...)}`
   (structured outputs). API'nin desteklediği alt küme: object/array/string/integer/number/
   boolean/null, enum, const, anyOf, allOf, $ref/$defs, desteklenen string format'ları,
   minItems 0/1; her nesnede `additionalProperties: false`. Desteklenmeyen kısıtlar (minLength,
   maxLength, pattern, minimum, maxItems, contains …) SDK'nın `transform_schema`'sı ile açıklamaya
   taşınır ve geçitte jsonschema ile ayrıca doğrulanır (constitution III).
2. Ajan: son çıktı aracı `submit_result`'ın `input_schema`'sı = çıktı şeması (strict olmayan araç;
   tam JSON Schema kabul edilir ama kök `type: object` olmalı, araç adı `^[a-zA-Z0-9_-]{1,64}$`).

Bu test, `transform_schema`'nın şemanın anlamını sessizce değiştirmediğini de doğrular: SDK her
nesneyi `additionalProperties: false` yapar; şemalarımızdaki her nesne zaten kapalıdır.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    FINAL_TOOL,
    find_rules_dir,
    load_model_table,
    load_schema,
)
from tp_core.gateway.providers.anthropic_provider import AnthropicProvider, strip_meta
from tp_core.gateway.providers.base import ProviderRequest
from tp_core.ports import ToolSpec

RULES = find_rules_dir()
PURPOSES = sorted(p.name.removesuffix(".schema.json") for p in (RULES / "schemas").glob("*.json"))
AGENT_PURPOSES = ("consistency_check", "verify_and_map", "assistant", "assistant_deep")
TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Structured outputs'un kabul ettiği anahtarlar (transform_schema sonrası).
STRUCTURED_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "anyOf",
    "allOf",
    "description",
    "title",
    "format",
    "minItems",
    "$ref",
    "$defs",
}
SUPPORTED_FORMATS = {
    "date-time",
    "time",
    "date",
    "duration",
    "email",
    "hostname",
    "uri",
    "ipv4",
    "ipv6",
    "uuid",
}
# Kaynak şemada bilerek kullanılmayan (desteklenmeyen veya anlamı transform'da kaybolan) anahtarlar.
FORBIDDEN_SOURCE_KEYS = {
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "patternProperties",
    "propertyNames",
    "dependentSchemas",
    "dependentRequired",
    "prefixItems",
    "unevaluatedProperties",
    "unevaluatedItems",
    "$dynamicRef",
}
PRIMITIVES = (str, int, float, bool, type(None))


def _subschemas(schema: Any, path: str = "#") -> Iterator[tuple[str, dict[str, Any]]]:
    if not isinstance(schema, dict):
        return
    yield path, schema
    for key, value in schema.get("properties", {}).items():
        yield from _subschemas(value, f"{path}/properties/{key}")
    if isinstance(schema.get("items"), dict):
        yield from _subschemas(schema["items"], f"{path}/items")
    for key in ("anyOf", "allOf"):
        for i, value in enumerate(schema.get(key) or []):
            yield from _subschemas(value, f"{path}/{key}/{i}")
    for key, value in (schema.get("$defs") or {}).items():
        yield from _subschemas(value, f"{path}/$defs/{key}")


def test_every_model_purpose_has_a_schema() -> None:
    assert set(load_model_table(RULES).purposes) <= set(PURPOSES)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_source_schema_is_valid_and_closed(purpose: str) -> None:
    schema = load_schema(RULES, purpose)
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object", "kök nesne olmalı (araç input_schema'sı da bu şema)"
    for path, sub in _subschemas(schema):
        bad = sorted(set(sub) & FORBIDDEN_SOURCE_KEYS)
        assert not bad, f"{purpose} {path}: desteklenmeyen anahtar {bad}"
        assert "$ref" not in sub, f"{purpose} {path}: $ref kullanılmıyor (özyineleme yasak)"
        assert "type" in sub or "anyOf" in sub or "allOf" in sub or "const" in sub, path
        if sub.get("type") == "object":
            assert sub.get("additionalProperties") is False, f"{purpose} {path}: açık nesne"
            props = set(sub.get("properties", {}))
            assert props, f"{purpose} {path}: özelliksiz nesne"
            # Tüm alanlar zorunlu; isteğe bağlılık `anyOf [..., null]` ile (structured outputs).
            assert set(sub.get("required", [])) == props, f"{purpose} {path}: required eksik"
        # "Yok" değeri yalnız `anyOf [..., {type: null}]` ile: tip dizisi (`["string", "null"]`)
        # SDK'nın `transform_schema`'sını çökertir (AI-ASISTAN-PLANI §7.2).
        assert not isinstance(sub.get("type"), list), f"{purpose} {path}: tip dizisi yasak (anyOf)"
        if "enum" in sub:
            assert sub["enum"] and len(set(map(str, sub["enum"]))) == len(sub["enum"]), path
            assert all(isinstance(v, PRIMITIVES) for v in sub["enum"]), path
        if "format" in sub:
            assert sub["format"] in SUPPORTED_FORMATS, f"{purpose} {path}: format"
        if "pattern" in sub:
            re.compile(sub["pattern"])
            assert not re.search(r"\(\?[=!<]|\\[1-9]|\\b", sub["pattern"]), (
                f"{purpose} {path}: lookaround/geri başvuru/kelime sınırı yok"
            )


@pytest.mark.parametrize("purpose", PURPOSES)
def test_structured_output_schema_uses_only_supported_keywords(purpose: str) -> None:
    sent = transform_schema(strip_meta(load_schema(RULES, purpose)))
    Draft202012Validator.check_schema(sent)
    json.dumps(sent)
    for path, sub in _subschemas(sent):
        extra = sorted(set(sub) - STRUCTURED_KEYS)
        assert not extra, f"{purpose} {path}: API'ye giden desteklenmeyen anahtar {extra}"
        if sub.get("type") == "object":
            assert sub["additionalProperties"] is False
        if "minItems" in sub:
            assert sub["minItems"] in (0, 1), path
        if "format" in sub:
            assert sub["format"] in SUPPORTED_FORMATS


@pytest.mark.parametrize("purpose", PURPOSES)
def test_transform_preserves_structure(purpose: str) -> None:
    """transform_schema yalnızca kısıtları açıklamaya taşır; alan/zorunluluk/enum değişmez."""
    source = load_schema(RULES, purpose)
    sent = transform_schema(strip_meta(source))
    src = dict(_subschemas(source))
    out = dict(_subschemas(sent))
    assert set(src) == set(out), f"{purpose}: alt şema yolları farklı"
    for path, sub in src.items():
        for key in ("type", "required", "enum"):
            assert sub.get(key) == out[path].get(key), f"{purpose} {path}: {key}"


@pytest.mark.parametrize("purpose", PURPOSES)
def test_golden_outputs_validate_against_sent_schema(purpose: str) -> None:
    """API'nin dayattığı (gevşek) şemaya da golden çıktılar uyar: canlı kayıt aynı biçimde."""
    sent = Draft202012Validator(transform_schema(strip_meta(load_schema(RULES, purpose))))
    for path in sorted((RULES / "replay" / purpose / "golden").glob("*.json")):
        output = json.loads(path.read_text(encoding="utf-8"))["output"]
        errors = [e.message for e in sent.iter_errors(output)]
        assert not errors, (path.name, errors[:3])


def _provider_kwargs(purpose: str, *, agent: bool) -> dict[str, Any]:
    schema = load_schema(RULES, purpose)
    request = ProviderRequest(
        model="claude-sonnet-5-5",
        system="s",
        messages=[{"role": "user", "content": "x"}],
        output_schema=None if agent else schema,
        tools=[ToolSpec(name=FINAL_TOOL, description="son sonuç", input_schema=schema)]
        if agent
        else [],
    )
    return AnthropicProvider(client=object()).build_kwargs(request)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_call_request_body_is_serialisable(purpose: str) -> None:
    kwargs = _provider_kwargs(purpose, agent=False)
    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] == transform_schema(strip_meta(load_schema(RULES, purpose)))
    json.dumps(kwargs)


@pytest.mark.parametrize("purpose", AGENT_PURPOSES)
def test_agent_tool_definitions_are_valid(purpose: str) -> None:
    kwargs = _provider_kwargs(purpose, agent=True)
    assert kwargs["tool_choice"] == {"type": "auto"}  # Sonnet 5.5: zorunlu araç seçimi 400
    for tool in kwargs["tools"]:
        assert TOOL_NAME_RE.match(tool["name"]), tool["name"]
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert not {k for k, _ in _walk_keys(schema) if k in ("$schema", "$id")}
        assert not {k for k, _ in _walk_keys(schema) if k.startswith("x-")}
        Draft202012Validator.check_schema(schema)
    json.dumps(kwargs)


def test_type_array_is_rejected_by_the_closed_schema_rule() -> None:
    """Kural kendini denetler: tip dizisi taşıyan alt şema yakalanır, `anyOf` ile null geçer."""
    bad = {"type": "object", "properties": {"a": {"type": ["string", "null"]}}}
    good = {
        "type": "object",
        "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    }
    assert [p for p, s in _subschemas(bad) if isinstance(s.get("type"), list)] == ["#/properties/a"]
    assert not [p for p, s in _subschemas(good) if isinstance(s.get("type"), list)]


def test_assistant_schemas_are_identical() -> None:
    """`assistant` paketi iki amaçta ortak; şema amaç adıyla aranır → iki dosya birebir aynı."""
    deep = (RULES / "schemas" / "assistant_deep.schema.json").read_bytes()
    assert (RULES / "schemas" / "assistant.schema.json").read_bytes() == deep


def test_allowed_agent_tool_names_are_valid() -> None:
    for names in ALLOWED_AGENT_TOOLS.values():
        for name in names:
            assert TOOL_NAME_RE.match(name), name
    assert TOOL_NAME_RE.match(FINAL_TOOL)


def _walk_keys(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from _walk_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_keys(v)

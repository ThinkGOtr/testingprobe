"""Golden testleri için bağlayıcı kaynakları okuyan yardımcılar (demo-app kodu, page object'ler,
docs/DEMO-VERISI.md). Golden kayıtlar bu kaynaklarla sürüklenirse testler kırmızı olur."""

from __future__ import annotations

import importlib
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from tp_core.gateway import find_rules_dir

RULES = find_rules_dir()
REPO = RULES.parent
DEMO_APP = REPO / "demo-app"
PAGES = DEMO_APP / "e2e" / "pages"
DEMO_VERISI = REPO / "docs" / "DEMO-VERISI.md"
DEMO_API_SRC = DEMO_APP / "api" / "src"

# docs/DEMO-VERISI.md ürün tablosu (fiyat, kampanya)
PRODUCTS: dict[str, tuple[Decimal, bool]] = {
    "P-001": (Decimal("25.00"), True),
    "P-002": (Decimal("15.00"), False),
    "P-003": (Decimal("8.00"), False),
    "P-004": (Decimal("30.00"), False),
}


def goldens(purpose: str | None = None) -> Iterator[tuple[str, Path, dict[str, Any]]]:
    root = RULES / "replay"
    for path in sorted(root.glob("*/golden/*.json")):
        p = path.parent.parent.name
        if purpose is None or p == purpose:
            yield p, path, json.loads(path.read_text(encoding="utf-8"))


def load_golden(purpose: str, name: str) -> dict[str, Any]:
    path = RULES / "replay" / purpose / "golden" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ demo-app API (saf fonksiyonlar)


def demo_module(name: str) -> ModuleType:
    """demo-app API'nin saf modülleri (pricing, campaign, money) core venv'inde içe aktarılır."""
    src = str(DEMO_API_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)
    return importlib.import_module(f"demoapp_api.{name}")


def seed_setting(key: str) -> str:
    """demo-app seed'indeki `ayar` değeri (ör. min_siparis_tutari → "750.00")."""
    text = (DEMO_API_SRC / "demoapp_api" / "seed.py").read_text(encoding="utf-8")
    m = re.search(rf'"anahtar":\s*"{re.escape(key)}",\s*"deger":\s*"([^"]+)"', text)
    assert m, f"seed.py içinde ayar yok: {key}"
    return m.group(1)


def cart(lines: list[tuple[str, int]]) -> Any:
    pricing = demo_module("pricing")
    girdiler = [
        pricing.SatirGirdi(code, code, PRODUCTS[code][0], qty, PRODUCTS[code][1])
        for code, qty in lines
    ]
    return pricing.sepet_hesapla(girdiler, Decimal(seed_setting("min_siparis_tutari")))


# ------------------------------------------------------------------ page object sembolleri


@dataclass(frozen=True)
class Method:
    po: str
    name: str
    param_types: tuple[str, ...]

    @property
    def is_expect(self) -> bool:
        return self.name.startswith("expect")


_CLASS_RE = re.compile(r"export class (\w+)\s*\{(.*?)\n\}", re.DOTALL)
_METHOD_RE = re.compile(r"^\s+async (\w+)\(([^)]*)\)", re.MULTILINE)


def page_object_methods() -> dict[tuple[str, str], Method]:
    """`demo-app/e2e/pages/**/*.page.ts` içindeki public async metotlar ve parametre türleri."""
    out: dict[tuple[str, str], Method] = {}
    for path in sorted(PAGES.glob("**/*.page.ts")):
        for cls, body in _CLASS_RE.findall(path.read_text(encoding="utf-8")):
            for name, params in _METHOD_RE.findall(body):
                types = tuple(p.split(":", 1)[1].strip() for p in params.split(",") if p.strip())
                out[(cls, name)] = Method(cls, name, types)
    return out


def arg_matches(value: Any, ts_type: str) -> bool:
    if ts_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if ts_type == "string":
        return isinstance(value, str)
    if ts_type == "boolean":
        return isinstance(value, bool)
    raise AssertionError(f"desteklenmeyen parametre türü: {ts_type}")


# ------------------------------------------------------------------ Jira story metni


def story_acs(jira_key: str) -> dict[str, str]:
    """docs/DEMO-VERISI.md'deki `**<KEY> kabul kriterleri:**` listesi → {"AC1": "AC1: …"}."""
    text = DEMO_VERISI.read_text(encoding="utf-8")
    block = text.split(f"**{jira_key} kabul kriterleri:**", 1)[1]
    acs: dict[str, str] = {}
    for line in block.splitlines()[1:]:
        m = re.match(r"- (AC\d+): (.*)", line.strip())
        if not m:
            if acs:
                break
            continue
        acs[m.group(1)] = f"{m.group(1)}: {m.group(2)}"
    return acs


def apply_fix_doc(acs: dict[str, str], suggested: str) -> dict[str, str]:
    """Önerilen metnin her `ACn: …` satırı ilgili AC'nin yerine geçer (§8.2b adım 6)."""
    out = dict(acs)
    for line in suggested.splitlines():
        m = re.match(r"(AC\d+):", line.strip())
        assert m, f"önerilen metin AC satırı değil: {line!r}"
        assert m.group(1) in out, f"bilinmeyen AC: {m.group(1)}"
        out[m.group(1)] = line.strip()
    return out


def normalize_value(value: Any) -> str:
    """§8.4 adım 3: sayı, para ve boşluk biçimi normalize edilir (`1.250,00 TL` ≡ `1250`)."""
    text = str(value).strip()
    money = re.fullmatch(r"(-?[\d.]+),(\d{2})\s*TL", text)
    if money:
        whole = money.group(1).replace(".", "")
        cents = money.group(2)
        return whole if cents == "00" else f"{whole}.{cents}"
    return re.sub(r"\s+", " ", text)


def normalized_text_values(text: str) -> set[str]:
    values = {normalize_value(m) for m in re.findall(r"-?[\d.]+,\d{2}\s*TL", text)}
    values |= set(re.findall(r"\d+", text))
    return values

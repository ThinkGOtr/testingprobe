"""Test case şeması (TEKNIK-TASARIM §7) ve deterministik içerik kontrolleri.

Şemanın tek kaynağı `rules/schemas/case_generation.schema.json`'daki `cases.items` tanımıdır:
modelin ürettiği, insanın düzelttiği (`edit`) ve IDE'den gelen (`submit_draft_cases`) case'ler
aynı şemayla doğrulanır. Şemaya ek deterministik kural (Constitution XI): case'in andığı kabul
kriterleri gereksinimde bulunmalıdır.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tp_core.gateway import find_rules_dir

AC_DESENI = re.compile(r"^\s*(AC\s*\d+)\s*[:.)\-–]\s*(.*)$", re.IGNORECASE | re.DOTALL)
MAX_HATA = 20


@lru_cache(maxsize=4)
def _gen_schema(rules_dir: str) -> dict[str, Any]:
    path = Path(rules_dir) / "schemas" / "case_generation.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def generation_schema(rules_dir: Path | None = None) -> dict[str, Any]:
    """Model çıktısının şeması (`{"cases": [...]}`)."""
    return _gen_schema(str(find_rules_dir(rules_dir)))


def case_schema(rules_dir: Path | None = None) -> dict[str, Any]:
    """Tek bir case'in şeması (`$schema` korunarak `cases.items`)."""
    gen = generation_schema(rules_dir)
    item = dict(gen["properties"]["cases"]["items"])
    item["$schema"] = gen.get("$schema", "https://json-schema.org/draft/2020-12/schema")
    return item


def _yol(hata: Any) -> str:
    return "/".join(str(p) for p in hata.absolute_path) or "(kök)"


def validate_case(icerik: Any, rules_dir: Path | None = None) -> list[str]:
    """Şema hataları (boş liste = geçerli). Mesajlar `alan/yolu: açıklama` biçimindedir."""
    validator = Draft202012Validator(case_schema(rules_dir))
    hatalar = sorted(validator.iter_errors(icerik), key=lambda e: list(e.absolute_path))
    return [f"{_yol(h)}: {h.message}" for h in hatalar[:MAX_HATA]]


def acceptance_criteria(kabul_kriterleri: Sequence[Any]) -> list[tuple[str, str]]:
    """Gereksinimin kabul kriterleri `(ref, metin)` listesi.

    Kayıt biçimleri: `"AC1: metin"` (Jira adaptörü), `{"ref": "AC1", "metin": "..."}` (portal),
    `{"id"/"key": ..., "text": ...}`. Ref'i olmayan maddeler sırayla `AC<n>` alır.
    """
    out: list[tuple[str, str]] = []
    for i, ac in enumerate(kabul_kriterleri or [], start=1):
        if isinstance(ac, Mapping):
            ref = str(ac.get("ref") or ac.get("id") or ac.get("key") or f"AC{i}")
            metin = str(ac.get("metin") or ac.get("text") or ac.get("aciklama") or "")
        else:
            m = AC_DESENI.match(str(ac))
            ref, metin = (m.group(1), m.group(2)) if m else (f"AC{i}", str(ac))
        out.append((re.sub(r"\s+", "", ref).upper(), metin.strip()))
    return out


def unknown_ac_refs(icerik: Mapping[str, Any], kabul_kriterleri: Sequence[Any]) -> list[str]:
    """Case'in andığı ama gereksinimde olmayan kabul kriterleri (gereksinimde AC yoksa boş)."""
    bilinen = {ref for ref, _ in acceptance_criteria(kabul_kriterleri)}
    if not bilinen:
        return []
    refs = icerik.get("acceptance_criteria_refs") or []
    return sorted({str(r) for r in refs if str(r).upper() not in bilinen})


def uncovered_acs(cases: Sequence[Mapping[str, Any]], kabul_kriterleri: Sequence[Any]) -> list[str]:
    """Hiçbir case'in referans vermediği kabul kriterleri (prompt: her AC en az bir case'te)."""
    kapsanan = {
        str(r).replace(" ", "").upper()
        for c in cases
        for r in (c.get("acceptance_criteria_refs") or [])
    }
    return [ref for ref, _ in acceptance_criteria(kabul_kriterleri) if ref not in kapsanan]


def content_errors(
    icerik: Any, kabul_kriterleri: Sequence[Any], rules_dir: Path | None = None
) -> list[str]:
    """Şema + kabul kriteri referansı kontrolü (insan düzeltmesi ve IDE taslağı için)."""
    hatalar = validate_case(icerik, rules_dir)
    if hatalar or not isinstance(icerik, Mapping):
        return hatalar
    bilinmeyen = unknown_ac_refs(icerik, kabul_kriterleri)
    if bilinmeyen:
        hatalar.append(
            "acceptance_criteria_refs: gereksinimde olmayan kabul kriteri: " + ", ".join(bilinmeyen)
        )
    return hatalar

"""Model girdisini kuran özellik şeritleri için kanonik yardımcılar.

Aynı story iki kez (aynı veya farklı süreçte) işlendiğinde aynı replay anahtarına ve golden
eşleşmesine (`input_match`) varmak için gereksinim metni hep aynı biçimde kurulmalıdır. Şeritler
prompt'larını serbestçe kurabilir; ancak story/serbest metin bloğu için `requirement_block`
kullanılırsa REPLAY golden eşleşmesi garanti edilir (rules/replay/README.md).

- `requirement_block(...)`: Jira story'si veya serbest metin gereksinimi → tek `<untrusted>` blok.
  Kaynak: Jira'da `jira:<KEY>`, serbest metinde `serbest:<requirement_id>`.
- `wrap_tool_result(tool, text)`: ajan araç sonucunu (kod, veri, snapshot) türüne uygun
  `<untrusted>` bloğuna sarar (TEKNIK-TASARIM §5: kod ve veri içeriği güvenilmeyen girdidir).
- `FREE_TEXT_KEY`: serbest metin gereksinimlerinin golden adı kökü (`golden_name(FREE_TEXT_KEY)`
  → `SERBEST`, 2. tur `SERBEST-r2`). Golden, `input_match` ile yalnızca senaryodaki serbest metne
  eşleşir; başka metinler dürüstçe REPLAY-MISS olur.

Kod üretimi (verify_and_map, TEKNIK-TASARIM §8.4) için:
- Ajan girdisini TEK yer kurar: `features.codegen.service.mapping_messages` (case JSON'u
  `case:<ref>` bloğunda, `SymbolTable.for_prompt()` `symbols:<sha>` bloğunda). Testler de onu
  kullanır; burada ikinci bir girdi kurucusu yoktur (anahtar testleri gerçek girdiyi denesin).
- `approved_case_text(case)`: onaylı case'in kanonik düz metni. Golden'ların
  `input_match.case_text` beyanı budur; geçit JSON case bloğunu bu metne çevirip TAM karşılaştırır.
- `VERIFY_AGENT_DEALER` = demo-app seed'indeki `bayi3` ("Doğrulama Bayi"); e2e bayileri bayi1/bayi2
  ile çakışmaz. Case'teki giriş verisi eşleme argümanıdır; tarayıcıda bu bayi kullanılır.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from tp_core.gateway.untrusted import UntrustedKind, wrap_untrusted

FREE_TEXT_KEY = "SERBEST"
_AC_PREFIX = re.compile(r"^\s*AC\d+\s*:")

# Araç adı → güvenilmeyen içerik türü (ALLOWED_AGENT_TOOLS'taki araçlar).
_TOOL_KINDS: dict[str, UntrustedKind] = {
    "search_code": "code",
    "get_file_contents": "code",
    "db_schema": "data",
    "db_query": "data",
}


def numbered_acceptance_criteria(items: Sequence[str]) -> list[str]:
    """`ACn: ` öneki yoksa sırayla ekler (serbest metin girdisi önekisiz gelir).

    >>> numbered_acceptance_criteria(["A olur.", "AC2: B olur."])
    ['AC1: A olur.', 'AC2: B olur.']
    """
    return [
        item.strip() if _AC_PREFIX.match(item) else f"AC{i}: {item.strip()}"
        for i, item in enumerate(items, start=1)
    ]


def requirement_text(summary: str, description: str, acceptance_criteria: Sequence[str]) -> str:
    """Gereksinimin kanonik düz metni (blok gövdesi)."""
    acs = numbered_acceptance_criteria(acceptance_criteria)
    lines = [f"Özet: {summary.strip()}", "", "Açıklama:", description.strip(), ""]
    if acs:
        lines += ["Kabul Kriterleri:", *acs]
    else:
        lines += ["Kabul Kriterleri: (yok)"]
    return "\n".join(lines)


def requirement_block(
    *,
    summary: str,
    description: str,
    acceptance_criteria: Sequence[str],
    jira_key: str | None = None,
    requirement_id: str | None = None,
) -> str:
    """Story/serbest metin gereksinimini tek güvenilmeyen bloğa sarar.

    Jira: `jira_key` verilir (kaynak `jira:<KEY>`, tür `jira`). Serbest metin: `requirement_id`
    verilir (kaynak `serbest:<id>`, tür `text`). `JiraIssue.description` AC bölümünü de içerse
    sorun olmaz: aynı AC satırları iki kez görülür, çelişki yoktur.
    """
    if (jira_key is None) == (requirement_id is None):
        raise ValueError("jira_key veya requirement_id'den yalnızca biri verilmeli")
    text = requirement_text(summary, description, acceptance_criteria)
    if jira_key is not None:
        return wrap_untrusted(text, source=f"jira:{jira_key}", kind="jira")
    return wrap_untrusted(text, source=f"serbest:{requirement_id}", kind="text")


def wrap_tool_result(tool: str, text: str, *, ref: str | None = None) -> str:
    """Ajan araç sonucunu güvenilmeyen bloğa sarar (kaynak `tool:<araç>[:<ref>]`).

    `ref` isteğe bağlı bağlamdır (ör. dosya yolu). Tarayıcı ve app-mcp araçları `snapshot`
    türündedir (009 §2.6).
    """
    kind: UntrustedKind = _TOOL_KINDS.get(
        tool, "snapshot" if tool.startswith(("browser_", "app_")) else "text"
    )
    source = f"tool:{tool}" + (f":{ref}" if ref else "")
    return wrap_untrusted(text, source=source, kind=kind)


# ------------------------------------------------------------------ kod üretimi (§8.4)

# Doğrulama ajanının (Playwright MCP) bayisi: demo-app seed'i `bayi3` ("Doğrulama Bayi"); e2e
# koşuları bu bayiyi kullanmaz, ajanın sepeti test koşularını bozmaz (demo-app/e2e/tests/fixtures.ts
# `AGENT_DEALER`). Kod üretimi her case'ten önce bu bayinin sepetini sıfırlamalıdır.
VERIFY_AGENT_DEALER = "bayi3"
VERIFY_AGENT_DEALER_NAME = "Doğrulama Bayi"
VERIFY_BASE_URL = "http://demo-app-web:8080"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def approved_case_text(case: Mapping[str, Any]) -> str:
    """Onaylı case'in kanonik düz metni (blok gövdesi). Alan adları case şemasınınkidir."""
    lines = [f"Başlık: {_text(case.get('title'))}"]
    kind, risk = _text(case.get("type")), _text(case.get("risk"))
    if kind or risk:
        lines.append(f"Tür: {kind or '-'} · Risk: {risk or '-'}")
    refs = [str(r) for r in case.get("acceptance_criteria_refs") or []]
    if refs:
        lines.append(f"Kabul kriterleri: {', '.join(refs)}")
    pre = [_text(p) for p in case.get("preconditions") or [] if _text(p)]
    lines.append("Ön koşullar:" if pre else "Ön koşullar: (yok)")
    lines += [f"- {p}" for p in pre]
    lines.append("Adımlar:")
    for step in case.get("steps") or []:
        sid = _text(step.get("id"))
        lines.append(f"{sid}: {_text(step.get('action'))}")
        data = _text(step.get("data"))
        lines.append(f"  Veri: {data}" if data else "  Veri: (yok)")
        lines.append(f"  Beklenen: {_text(step.get('expected'))}")
    lines.append(f"Beklenen sonuç: {_text(case.get('expected_result'))}")
    tags = [str(t) for t in case.get("tags") or []]
    if tags:
        lines.append(f"Etiketler: {', '.join(tags)}")
    return "\n".join(lines)

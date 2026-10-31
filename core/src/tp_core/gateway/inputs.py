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
"""

from __future__ import annotations

import re
from collections.abc import Sequence

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

    `ref` isteğe bağlı bağlamdır (ör. dosya yolu). Tarayıcı araçları `snapshot` türündedir.
    """
    kind: UntrustedKind = _TOOL_KINDS.get(
        tool, "snapshot" if tool.startswith("browser_") else "text"
    )
    source = f"tool:{tool}" + (f":{ref}" if ref else "")
    return wrap_untrusted(text, source=source, kind=kind)

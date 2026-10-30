"""Atlassian Document Format (ADF) yardımcıları: düz metin ↔ ADF ve güvenli HTML çizimi.

Simülatör, Jira Cloud gibi açıklama ve yorum gövdelerini ADF olarak saklar. Bu modül yalnızca
simülatörün ihtiyacı olan alt kümeyi bilir; bilinmeyen düğümler metin içerikleriyle çizilir.
"""

from __future__ import annotations

import re
from typing import Any

from markupsafe import Markup, escape

AdfNode = dict[str, Any]

_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d{1,9})[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def is_adf_doc(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "doc"
        and value.get("version") == 1
        and isinstance(value.get("content"), list)
    )


def _inline(text: str) -> list[AdfNode]:
    """Tek satır sonlarını hardBreak'e çevirir."""
    out: list[AdfNode] = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append({"type": "hardBreak"})
        if line:
            out.append({"type": "text", "text": line})
    return out


def text_to_adf(text: str) -> AdfNode:
    """Düz metni ADF'ye çevirir.

    Boş satırla ayrılan bloklar paragraf olur; ``# `` ile başlayan satır başlık, ``- `` ile
    başlayan satırlar madde listesi olur. Numaralı liste yalnızca ``1. `` ile başlar ve ardışık
    numaralarla sürer; ``1990. yılda`` gibi satırlar paragraf metni kalır (numara kaybolmasın).
    """
    content: list[AdfNode] = []
    para: list[str] = []
    list_kind: str | None = None
    items: list[str] = []
    next_number = 0

    def flush_para() -> None:
        if para:
            content.append({"type": "paragraph", "content": _inline("\n".join(para))})
            para.clear()

    def flush_list() -> None:
        nonlocal list_kind, next_number
        if list_kind and items:
            node: AdfNode = {
                "type": list_kind,
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": _inline(it)}],
                    }
                    for it in items
                ],
            }
            if list_kind == "orderedList":
                node["attrs"] = {"order": 1}
            content.append(node)
        items.clear()
        list_kind = None
        next_number = 0

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            flush_list()
            continue
        if m := _HEADING.match(line):
            flush_para()
            flush_list()
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": len(m.group(1))},
                    "content": _inline(m.group(2).strip()),
                }
            )
            continue
        if bullet := _BULLET.match(line):
            flush_para()
            if list_kind != "bulletList":
                flush_list()
                list_kind = "bulletList"
            items.append(bullet.group(1).strip())
            continue
        if ordered := _ORDERED.match(line):
            number = int(ordered.group(1))
            continues = list_kind == "orderedList" and number == next_number
            if continues or number == 1:
                flush_para()
                if not continues:
                    flush_list()
                    list_kind = "orderedList"
                items.append(ordered.group(2).strip())
                next_number = number + 1
                continue
        flush_list()
        para.append(line)
    flush_para()
    flush_list()
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(node: Any) -> str:
    """ADF'den aranabilir düz metin (blok başına bir satır)."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    if kind in ("mention", "emoji", "status", "date"):
        attrs = node.get("attrs") or {}
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if kind == "inlineCard":
        return str((node.get("attrs") or {}).get("url", ""))
    children = node.get("content") or []
    if kind == "listItem":
        return "- " + " ".join(adf_to_text(c) for c in children).strip()
    if kind in ("tableRow",):
        return " | ".join(adf_to_text(c).strip() for c in children)
    inline_parent = kind in ("paragraph", "heading", "tableCell", "tableHeader")
    sep = "" if inline_parent else "\n"
    return sep.join(adf_to_text(c) for c in children)


_SAFE_URL = re.compile(r"^(https?://|mailto:|/)", re.IGNORECASE)


def _marks(html: Markup, marks: list[dict[str, Any]]) -> Markup:
    for mark in marks or []:
        t = mark.get("type")
        if t == "strong":
            html = Markup("<strong>%s</strong>") % html
        elif t == "em":
            html = Markup("<em>%s</em>") % html
        elif t == "code":
            html = Markup("<code>%s</code>") % html
        elif t == "strike":
            html = Markup("<s>%s</s>") % html
        elif t == "underline":
            html = Markup("<u>%s</u>") % html
        elif t == "link":
            href = str((mark.get("attrs") or {}).get("href", ""))
            if _SAFE_URL.match(href):
                html = Markup('<a href="%s" rel="noopener noreferrer">%s</a>') % (href, html)
    return html


_BLOCK_TAGS = {
    "paragraph": "p",
    "bulletList": "ul",
    "orderedList": "ol",
    "listItem": "li",
    "blockquote": "blockquote",
    "table": "table",
    "tableRow": "tr",
    "tableHeader": "th",
    "tableCell": "td",
}


def adf_to_html(node: Any) -> Markup:
    """ADF'yi kaçışlı HTML'e çizer. Ham HTML hiçbir zaman geçirilmez."""
    if not isinstance(node, dict):
        return Markup("")
    kind = node.get("type")
    children = Markup("").join(adf_to_html(c) for c in node.get("content") or [])
    if kind == "doc":
        return children
    if kind == "text":
        return _marks(escape(str(node.get("text", ""))), node.get("marks") or [])
    if kind == "hardBreak":
        return Markup("<br>")
    if kind == "rule":
        return Markup("<hr>")
    if kind == "heading":
        level = (node.get("attrs") or {}).get("level", 3)
        level = level if isinstance(level, int) and 1 <= level <= 6 else 3
        tag = f"h{min(level + 1, 6)}"  # sayfa başlıkları h1/h2'yi kullanır
        return Markup(f"<{tag}>") + children + Markup(f"</{tag}>")
    if kind == "codeBlock":
        return Markup("<pre><code>%s</code></pre>") % escape(adf_to_text(node))
    if kind == "table":
        return Markup('<table class="adf-table">') + children + Markup("</table>")
    if kind == "orderedList":
        start = (node.get("attrs") or {}).get("order", 1)
        if isinstance(start, int) and start != 1 and start >= 0:
            return Markup('<ol start="%d">') % start + children + Markup("</ol>")
        return Markup("<ol>") + children + Markup("</ol>")
    if kind in _BLOCK_TAGS:
        tag = _BLOCK_TAGS[kind]
        return Markup(f"<{tag}>") + children + Markup(f"</{tag}>")
    if kind in ("mention", "emoji", "status", "date", "inlineCard"):
        return escape(adf_to_text(node))
    return children

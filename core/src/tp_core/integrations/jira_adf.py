"""Atlassian Document Format (ADF) ↔ düz metin ve kabul kriteri (AC) ayrıştırma.

Story açıklaması iki biçimde okunur: (1) açıklama paragrafı, ardından "Kabul Kriterleri"
başlığı ve ``AC<n>: ...`` satırları (madde listesi ya da paragraf); (2) görev şablonu (demo
story'leri, docs/DEMO-VERISI.md) — AC'ler "🔑 Acceptance Criteria" bölümündedir. Gerçek
Jira'daki öneksiz madde listeleri de başlık altında AC olarak okunur. Bu modül hem okuma
(``parse_description``) hem yazma (``build_description``) yönünü sağlar; ikisi tur atlatıldığında
aynı içeriği verir.

Jira görev şablonu (``TEMPLATE_SECTIONS``): Objective, Scope, User Flow, Dependencies &
Integration, Other Information & Assets, Acceptance Criteria, QA Checklist. Ürünün açtığı Bug ve
Test kayıtları ``template_doc`` ile bu şablonda yazılır; şablonlu story'de AC bölümü
"🔑 Acceptance Criteria" başlığından okunur ve yeniden yazımda diğer bölümler yerinde kalır.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

AdfNode = dict[str, Any]

AC_HEADING = "Kabul Kriterleri"
# Başlık önünde emoji/simge, sonunda parantezli ikinci dil olabilir ("🔑 Acceptance Criteria
# (Kabul Kriterleri)"). Önek harf olmayan her şeydir ("ℹ" gibi simgeler Python'da \w sayılır)
# ya da metni olmayan ADF emoji düğümünün kısa adı (":key:").
_LEAD = r"^(?::[a-z0-9_+-]+:|[^A-Za-zÇĞİÖŞÜçğıöşü])*"
_AC_HEADING_RE = re.compile(
    _LEAD + r"(kabul\s+kriterleri|acceptance\s+criteria)\s*(?:\([^)]*\))?\s*:?\s*$", re.I
)

# Görev şablonu: (anahtar, başlık, tanınan adlar). Başlıklar şablondaki gibi iki dillidir.
TEMPLATE_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("objective", "🎯 Objective (Amaç)", ("objective", "amaç")),
    ("scope", "🚀 Scope (Kapsam)", ("scope", "kapsam")),
    ("user_flow", "🔄 User Flow (Kullanıcı Akışı)", ("user flow", "kullanıcı akışı")),
    (
        "dependencies",
        "🔗 Dependencies & Integration (Bağımlılıklar ve Entegrasyon)",
        ("dependencies & integration", "dependencies", "bağımlılıklar ve entegrasyon"),
    ),
    (
        "other",
        "ℹ️ Other Information & Assets (Diğer Bilgiler & Kaynaklar)",
        ("other information & assets", "other information", "diğer bilgiler & kaynaklar"),
    ),
    (
        "acceptance_criteria",
        "🔑 Acceptance Criteria (Kabul Kriterleri)",
        ("acceptance criteria", "kabul kriterleri"),
    ),
    ("qa_checklist", "🧪 QA Checklist", ("qa checklist", "qa kontrol listesi")),
)
TEMPLATE_AC_HEADING = next(t for k, t, _ in TEMPLATE_SECTIONS if k == "acceptance_criteria")
NOT_APPLICABLE = "Not applicable"
# AC bölümünde "boş bölüm" işaretleri: AC sayılmaz.
_EMPTY_MARKERS = frozenset({"not applicable", "n/a", "na", "yok", "uygulanamaz", "-", "—", "–"})
_SECTION_NAME_RE = re.compile(_LEAD + r"(.+?)\s*(?:\([^)]*\))?\s*:?\s*$")
_AC_LINE_RE = re.compile(r"^\s*(?:[-*•]\s*|\d+[.)]\s+)?AC\s*(\d+)\s*[:.)\-–]\s*(.+?)\s*$", re.I)
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d{1,9})[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


# ------------------------------------------------------------------ metin → ADF


def _inline(text: str) -> list[AdfNode]:
    out: list[AdfNode] = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append({"type": "hardBreak"})
        if line:
            out.append({"type": "text", "text": line})
    return out


def paragraph(text: str) -> AdfNode:
    return {"type": "paragraph", "content": _inline(text)}


def heading(text: str, level: int = 3) -> AdfNode:
    return {"type": "heading", "attrs": {"level": level}, "content": _inline(text)}


def code_block(text: str) -> AdfNode:
    """Kod bloğu: metin biçimlendirilmeden, olduğu gibi (satır sonları dahil) gösterilir."""
    return {"type": "codeBlock", "attrs": {}, "content": [{"type": "text", "text": text}]}


def bullet_list(items: Sequence[str], ordered: bool = False, start: int = 1) -> AdfNode:
    node: AdfNode = {
        "type": "orderedList" if ordered else "bulletList",
        "content": [{"type": "listItem", "content": [paragraph(it)]} for it in items],
    }
    if ordered:
        node["attrs"] = {"order": start}
    return node


def _list_start(node: AdfNode) -> int:
    order = (node.get("attrs") or {}).get("order", 1)
    return order if isinstance(order, int) and order >= 0 else 1


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> AdfNode:
    def cell(kind: str, text: str) -> AdfNode:
        return {"type": kind, "attrs": {}, "content": [paragraph(text)]}

    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [
            {"type": "tableRow", "content": [cell("tableHeader", h) for h in header]},
            *({"type": "tableRow", "content": [cell("tableCell", c) for c in row]} for row in rows),
        ],
    }


def doc(content: Sequence[AdfNode]) -> AdfNode:
    return {"type": "doc", "version": 1, "content": list(content)}


def text_to_blocks(text: str) -> list[AdfNode]:
    """Düz metni ADF bloklarına çevirir.

    Boş satır paragraf ayırır, tek satır sonu ``hardBreak`` olur; ``# `` başlık, ``- `` madde
    satırıdır. Numaralı liste yalnızca ``1. `` ile başlar ve ardışık numaralarla sürer
    (``2. ``, ``3. `` ...); başka bir sayıyla başlayan satır (ör. ``1990. yılda``) paragraf
    metni olarak kalır — ADF ``orderedList`` madde numarası taşımadığından yeniden
    numaralandırılıp veri kaybolmasın.
    """
    blocks: list[AdfNode] = []
    para: list[str] = []
    items: list[str] = []
    ordered = False
    next_number = 0  # açık numaralı listede beklenen sıradaki numara

    def flush() -> None:
        nonlocal ordered, next_number
        if para:
            blocks.append(paragraph("\n".join(para)))
            para.clear()
        if items:
            blocks.append(bullet_list(items, ordered))
            items.clear()
        next_number = 0

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if m := _HEADING.match(line):
            flush()
            blocks.append(heading(m.group(2).strip(), len(m.group(1))))
            continue
        if b := _BULLET.match(line):
            if para or (items and ordered):
                flush()
            ordered = False
            items.append(b.group(1).strip())
            continue
        o = _ORDERED.match(line)
        if o:
            number = int(o.group(1))
            continues = bool(items) and ordered and number == next_number
            if continues or number == 1:
                if not continues:
                    flush()
                ordered = True
                items.append(o.group(2).strip())
                next_number = number + 1
                continue
        if items:
            flush()
        para.append(line)
    flush()
    return blocks


def text_to_adf(text: str) -> AdfNode:
    return doc(text_to_blocks(text))


# ------------------------------------------------------------------ görev şablonu


def template_section(text: str) -> str | None:
    """Satır bir şablon bölüm başlığıysa bölüm anahtarı (ör. ``"scope"``), değilse ``None``."""
    if "\n" in text or len(text) > 120:
        return None
    m = _SECTION_NAME_RE.match(text.strip())
    if not m:
        return None
    adaylar = _name_keys(m.group(1))
    for key, _, names in TEMPLATE_SECTIONS:
        if adaylar & {k for n in names for k in _name_keys(n)}:
            return key
    return None


def _name_keys(name: str) -> set[str]:
    """Karşılaştırma anahtarları: hem varsayılan hem Türkçe küçük harf ("KULLANICI" → "kullanıcı",
    "Integration" → "integration"); "&"/"and"/"ve" ve boşluk farkı yok sayılır."""
    out = set()
    for low in (name.lower(), name.replace("I", "ı").replace("İ", "i").lower()):
        out.add(" ".join("&" if w in ("and", "ve") else w for w in low.split()))
    return out


def is_template(blocks: Sequence[tuple[str, str]]) -> bool:
    """Belge görev şablonunda mı: en az iki farklı şablon bölüm başlığı (tek "Kapsam" satırı
    şablon sayılmaz)."""
    keys = {template_section(text) for kind, text in blocks if kind in ("heading", "paragraph")}
    keys.discard(None)
    return len(keys) >= 2


def template_doc(
    sections: Mapping[str, Sequence[AdfNode] | str | None],
    *,
    preamble: Sequence[AdfNode] = (),
    trailer: Sequence[AdfNode] = (),
) -> AdfNode:
    """Görev şablonunda ADF belgesi: her bölüm seviye-3 başlık + içerik, şablon sırasıyla.

    Değer düz metinse ``text_to_blocks`` ile, blok listesiyse olduğu gibi yazılır; boş ya da
    verilmemiş bölüm ``Not applicable`` olur (şablon her bölümü ister); ``parse_description`` AC
    bölümündeki ``Not applicable``'ı AC saymaz. ``preamble`` ilk bölümden
    önce (ör. ürün imi), ``trailer`` son bölümden sonra (ör. kimlik/hash satırı) gelir.
    """
    content: list[AdfNode] = list(preamble)
    for key, title, _ in TEMPLATE_SECTIONS:
        value = sections.get(key)
        blocks = text_to_blocks(value.strip()) if isinstance(value, str) else list(value or [])
        content.append(heading(title, 3))
        content.extend(blocks or [paragraph(NOT_APPLICABLE)])
    content.extend(trailer)
    return doc(content)


# ------------------------------------------------------------- bot imi ve @bahsetme

# Ürünün yazdığı her Jira yorumunun ilk satırı. Yorumlar insan bir hesabın token'ıyla yazılabilir
# (Jira'da o kişinin adıyla görünür); bu im, yorumu ürünün yazdığını açıkça gösterir.
BOT_PREFIX = "🤖 AI Testing Probe:"
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9:_\-]{1,128}$")


def valid_account_id(value: str) -> bool:
    """Jira Cloud accountId biçimi (ör. ``712020:1a2b3c4d-…``); e-posta/görünen ad değildir."""
    return bool(_ACCOUNT_ID.match(value or ""))


def mention(account_id: str) -> AdfNode:
    """ADF bahsetme düğümü. Görünen ad gönderilmez: Jira onu accountId'den kendisi çözer."""
    return {"type": "mention", "attrs": {"id": account_id}}


def unique_mentions(account_ids: Sequence[str]) -> list[str]:
    """Boş/geçersiz kimlikleri atar, sırayı koruyarak tekilleştirir."""
    out: list[str] = []
    for a in account_ids:
        a = (a or "").strip()
        if a and valid_account_id(a) and a not in out:
            out.append(a)
    return out


def bot_header(mentions: Sequence[str] = ()) -> AdfNode:
    """``🤖 AI Testing Probe: @Kişi @Kişi`` paragrafı (bahsetme yoksa yalnızca im)."""
    content: list[AdfNode] = [{"type": "text", "text": BOT_PREFIX}]
    for a in unique_mentions(mentions):
        content += [{"type": "text", "text": " "}, mention(a)]
    return {"type": "paragraph", "content": content}


def has_bot_header(adf: Any) -> bool:
    blocks = (adf or {}).get("content") if isinstance(adf, dict) else None
    if not blocks:
        return False
    return inline_text(blocks[0]).startswith(BOT_PREFIX)


def with_bot_header(adf: AdfNode, mentions: Sequence[str] = ()) -> AdfNode:
    """ADF gövdesinin başına bot imi (+ bahsetmeler) ekler; zaten varsa gövde aynen döner."""
    if has_bot_header(adf):
        return adf
    out = dict(adf)
    out["content"] = [bot_header(mentions), *list(adf.get("content") or [])]
    return out


def strip_bot_header(text: str) -> str:
    """Okunan yorum metninden bot imi satırını atar (eski, imsiz yorumlar aynen döner)."""
    if not text.startswith(BOT_PREFIX):
        return text
    _, _, rest = text.partition("\n")
    return rest.lstrip("\n")


# ------------------------------------------------------------------ ADF → metin


def inline_text(node: Any) -> str:
    """Bir düğümün satır içi metni (hardBreak → ``\\n``)."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    attrs = node.get("attrs") or {}
    if kind == "mention":
        # Jira okumada görünen adı (``@Ad Soyad``) doldurur; yeni yazılmış düğümde yalnızca id var.
        return str(attrs.get("text") or (f"@{attrs['id']}" if attrs.get("id") else ""))
    if kind == "emoji":
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if kind in ("status", "date"):
        return str(attrs.get("text") or attrs.get("timestamp") or "")
    if kind == "inlineCard":
        return str(attrs.get("url") or "")
    return "".join(inline_text(c) for c in node.get("content") or [])


def _blocks(nodes: Sequence[Any]) -> list[tuple[str, str]]:
    """Blokları ``(tür, metin)`` olarak düzleştirir; tür: paragraph | heading | item | other."""
    out: list[tuple[str, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        if kind in ("bulletList", "orderedList"):
            start = _list_start(node)
            for n, item in enumerate(node.get("content") or [], start=start):
                inner = _blocks(item.get("content") or [])
                text = "\n".join(t for _, t in inner)
                marker = "- " if kind == "bulletList" else f"{n}. "
                out.append(("item", marker + text))
        elif kind == "heading":
            out.append(("heading", inline_text(node)))
        elif kind == "paragraph":
            out.append(("paragraph", inline_text(node)))
        elif kind == "table":
            rows = []
            for row in node.get("content") or []:
                cells = [inline_text(c).strip() for c in row.get("content") or []]
                rows.append(" | ".join(cells))
            out.append(("other", "\n".join(rows)))
        elif kind in ("blockquote", "panel", "expand", "nestedExpand", "layoutSection"):
            out.extend(_blocks(node.get("content") or []))
        elif kind == "codeBlock":
            out.append(("other", inline_text(node)))
        elif kind == "rule":
            continue
        else:
            text = inline_text(node)
            if text:
                out.append(("other", text))
    return out


def _join(blocks: list[tuple[str, str]]) -> str:
    """Paragraflar boş satırla, ardışık maddeler tek satır sonuyla birleşir."""
    parts: list[str] = []
    prev = ""
    for kind, text in blocks:
        if not text.strip():
            continue
        if parts and not (kind == "item" and prev == "item"):
            parts.append("\n\n")
        elif parts:
            parts.append("\n")
        parts.append(text.strip("\n"))
        prev = kind
    return "".join(parts)


def adf_to_text(adf: Any) -> str:
    if adf is None:
        return ""
    if isinstance(adf, str):  # REST v2 / eski kayıtlar
        return adf
    if not isinstance(adf, dict):
        return ""
    return _join(_blocks(adf.get("content") or []))


# ------------------------------------------------------------------- AC ayrıştırma


def normalize_ac(ac: str, index: int) -> str:
    """``AC<n>: metin`` biçimine getirir; numarası olmayan maddeye sıra numarası verir."""
    if m := _AC_LINE_RE.match(ac):
        return f"AC{int(m.group(1))}: {m.group(2).strip()}"
    return f"AC{index}: {ac.strip()}"


_ITEM_MARKER = re.compile(r"^\s*(?:[-*•]\s*|\d+[.)]\s+)")


def parse_description(adf: Any) -> tuple[str, list[str]]:
    """ADF açıklamasını (açıklama metni, ``["AC1: ...", ...]``) olarak ayırır.

    "Kabul Kriterleri" (ya da "Acceptance Criteria") başlığından sonra, bir sonraki başlığa
    kadar her madde ve her boş olmayan paragraf satırı bir AC'dir; ``AC<n>:`` öneki varsa o
    numara korunur, yoksa sıradaki numara verilir (gerçek Jira story'leri çoğunlukla öneksiz
    madde listesi kullanır). Başlık yoksa yalnızca ``AC<n>:`` ile başlayan satırlar AC sayılır.
    Kalan her şey açıklama metnidir.
    """
    if isinstance(adf, str):
        adf = text_to_adf(adf)
    blocks = _blocks((adf or {}).get("content") or []) if isinstance(adf, dict) else []
    desc: list[tuple[str, str]] = []
    acs: list[str] = []
    in_ac = False
    # Şablonda AC yalnızca AC bölümündedir: QA Checklist'teki "- AC1: … doğrulanır" maddesi AC
    # değildir (yoksa çift AC1 olur ve geri yazımda checklist'ten silinir).
    template = is_template(blocks)

    def next_index() -> int:
        # Öneksiz AC, şimdiye kadarki en büyük numaranın bir fazlasını alır (çakışma olmasın).
        used = [int(m.group(1)) for a in acs if (m := _AC_LINE_RE.match(a))]
        return max(used, default=0) + 1

    for kind, text in blocks:
        # Şablon bölüm başlığı gerçek Jira'da çoğu zaman düz paragraf satırıdır ("🧪 QA
        # Checklist"); AC bölümünü o da bitirir.
        if (
            kind == "heading"
            or (kind == "paragraph" and _AC_HEADING_RE.match(text))
            or (kind == "paragraph" and in_ac and template_section(text))
        ):
            if _AC_HEADING_RE.match(text):
                in_ac = True
                continue
            in_ac = False
            desc.append((kind, text))
            continue
        if in_ac:
            if _ITEM_MARKER.sub("", text.strip()).rstrip(".").strip().casefold() in _EMPTY_MARKERS:
                continue  # şablonun "boş bölüm" işareti, AC değil
            if kind == "item":
                # Çok satırlı madde tek AC'dir.
                body = " ".join(ln.strip() for ln in text.split("\n") if ln.strip())
                body = _ITEM_MARKER.sub("", body, count=1).strip()
                if body:
                    acs.append(normalize_ac(body, next_index()))
            else:
                for line in text.split("\n"):
                    line = _ITEM_MARKER.sub("", line, count=1).strip()
                    if line:
                        acs.append(normalize_ac(line, next_index()))
            continue
        if template:
            desc.append((kind, text))
            continue
        rest: list[str] = []
        for line in text.split("\n"):
            m = _AC_LINE_RE.match(line)
            if m:
                acs.append(f"AC{int(m.group(1))}: {m.group(2).strip()}")
            elif line.strip():
                rest.append(line)
        if rest:
            desc.append((kind, "\n".join(rest)))
    return _join(desc), acs


def build_description(description: str, acceptance_criteria: Sequence[str]) -> AdfNode:
    """Açıklama paragrafı + "Kabul Kriterleri" başlığı + AC maddeleri.

    Açıklama görev şablonundaysa (``parse_description`` şablon başlıklarını kendi satırlarında
    bırakır) başlıklar yeniden başlık olur ve AC bölümü şablondaki yerine ("🔑 Acceptance
    Criteria", QA Checklist'ten önce) yazılır; böylece doküman düzeltmesi diğer bölümleri bozmaz.
    """
    content = text_to_blocks(description.strip()) if description.strip() else []
    acs = [normalize_ac(ac, i) for i, ac in enumerate(acceptance_criteria, start=1) if ac.strip()]
    keys = [_block_section(b) for b in content]
    if not is_template([(b["type"], inline_text(b)) for b in content]):
        if acs:
            content.append(heading(AC_HEADING, 3))
            content.append(bullet_list(acs))
        return doc(content)
    # Başlık metni olduğu gibi kalır (yalnızca düğüm türü başlık olur): içerik hash'i değişmesin.
    content = [heading(inline_text(b), 3) if k else b for b, k in zip(content, keys, strict=True)]
    # AC'siz şablon story'sinde de bölüm kalır (şablon her bölümü ister; "Not applicable" AC
    # sayılmaz, tur atlatma aynı içeriği verir).
    order = [k for k, _, _ in TEMPLATE_SECTIONS]
    after_ac = order[order.index("acceptance_criteria") + 1 :]
    at = next((i for i, k in enumerate(keys) if k in after_ac), len(content))
    body = bullet_list(acs) if acs else paragraph(NOT_APPLICABLE)
    content[at:at] = [heading(TEMPLATE_AC_HEADING, 3), body]
    return doc(content)


def _block_section(block: AdfNode) -> str | None:
    if block.get("type") not in ("heading", "paragraph"):
        return None
    key = template_section(inline_text(block))
    return None if key == "acceptance_criteria" else key

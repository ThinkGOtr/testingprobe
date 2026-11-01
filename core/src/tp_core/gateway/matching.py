"""Golden kaydın hangi girdi için hazırlandığının deterministik denetimi (REPLAY ↔ REPLAY-MISS).

Sorun: anahtarsız demoda birebir replay kaydı (`rules/replay/<amaç>/<anahtar>.json`) yoktur; her
çağrı adlandırılmış golden'a düşer ve REPLAY-MISS olarak işaretlenir — senaryodaki girdi tam da
golden'ın hazırlandığı girdi olsa bile. Tersine, golden'ı koşulsuz "replay" saymak da yalan olur:
story değiştiyse golden başka bir dokümanın cevabıdır.

Çözüm: golden, hazırlandığı girdiyi `input_match` alanıyla beyan eder; geçit gerçek girdiyi bu
beyanla karşılaştırır. Eşleşirse mod `replay` (köken `golden_matched`, `ai_call.ek`), eşleşmezse
`replay_miss` ve nedenler `ai_call.ek.replay_eslesme`'ye yazılır. Mod asla `live` değildir.

```json
"input_match": {
  "sources": ["jira:TPD-1"],            // isteğe bağlı: yalnızca bu kaynaklı <untrusted> blokları
  "acceptance_criteria": ["AC1: …", …], // isteğe bağlı: bloklardaki ACn satırları TAM bu küme
  "contains": ["…"],                    // isteğe bağlı: her metin girdide geçmeli
  "case_text": "Başlık: …\nAdımlar: …",  // isteğe bağlı (`sources` zorunlu): onaylı case TAM bu
  "candidates": {                         // isteğe bağlı (dup_rank): Jira aramasının aday kümesi
    "required": ["TPD-5"], "optional": ["TPD-6"],
    "by_summary": {"kredi-limiti-yeni": "Kredi limiti aşıldığında"}
  }
}
```

- `sources`: `fnmatch` desenleri (`serbest:*`). Verilirse AC'ler ve `contains` yalnızca bu
  kaynaklı `<untrusted>` bloklarında aranır (önceki bulgular, PO cevapları gibi başka bloklardaki
  `AC3: …` alıntıları karışmaz). Verilmezse tüm mesaj metni.
- `acceptance_criteria`: bloklardaki `ACn: metin` satırları (madde imli `- AC1: …` ve JSON
  gövdeli bloklardaki dizgeler dahil) beyan edilen kümeye eşit olmalı: AC eklenmesi, silinmesi
  veya tek kelime değişmesi REPLAY-MISS'tir. `[]` = hiç AC yok (ör. TPD-2).
- `case_text`: kod üretimi (verify_and_map) golden'ları için onaylı case'in kanonik metni
  (`inputs.approved_case_text`). `sources` bloklarının HER biri — gövde JSON case ise kanonik
  metne çevrilerek — bu metne eşit olmalıdır: case'e tek kelime eklenmesi bile REPLAY-MISS'tir
  (`contains` yalnızca varlık denetler; eklenen beklenen değer onu geçerdi). Yalnızca case
  bloğuna bakılır; sembol tablosu ve geri bildirim bloğu karşılaştırmaya girmez.
- `candidates` (mükerrer sıralaması): aday kümesi `jira-arama:*` bloğundaki
  `Aday anahtarları: [...]` satırından okunur. `required` anahtarların hepsi kümede olmalı;
  kümedeki her anahtar ya `required`/`optional` listesindedir ya da özeti (`- KEY · durum: … ·
  özet: …`) `by_summary` içindeki BİR metni içerir (demo sırasında açılabilen, özeti golden
  taslaklarından bilinen Bug'lar: F4 "Yeni kayıt" → yeni kredi limiti Bug'ı). Beyan dışı her aday
  REPLAY-MISS'tir (golden bilmediği bir kaydı sıralamaz). Çıktı `matched_output` ile girdideki
  GERÇEK kümeye göre kurulur: yalnızca aramadaki anahtarlar, her biri bir kez, sıra 1..n; özetle
  tanınan adayın olasılığı/gerekçesi golden'ın `extra_candidates.<ad>` alanından gelir; öneri
  prompt kuralıyla (ilk `high` aday → `link`, yoksa `new`) hesaplanır.
- Karşılaştırma NFC + boşluk daraltma ile yapılır; başka gevşetme yoktur (`by_summary` ayrıca
  büyük/küçük harf duyarsızdır).
"""

from __future__ import annotations

import contextlib
import json
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

MATCHED = "golden_matched"

_BLOCK_RE = re.compile(
    r'<untrusted kind="(?P<kind>[^"]*)" source="(?P<source>[^"]*)" id="(?P<id>[0-9a-f]+)">\n'
    r'(?P<body>.*?)\n</untrusted id="(?P=id)">',
    re.DOTALL,
)
# `AC1: …`, `- AC1: …`, girintili JSON satırı `  "AC1: …",`
_AC_LINE_RE = re.compile(r'^\s*(?:[-*•]\s*)?"?(AC\d+)\s*:\s*(.+?)(?:",?)?\s*$', re.MULTILINE)
_WS_RE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Eşleme normu: NFC, boşluk daraltma, baş/son boşluk yok."""
    return _WS_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


@dataclass(frozen=True)
class UntrustedBlock:
    kind: str
    source: str
    body: str


def _content_texts(content: Any) -> Iterator[str]:
    if isinstance(content, str):
        yield content
    elif isinstance(content, Mapping):
        for key in ("text", "content"):
            if key in content:
                yield from _content_texts(content[key])
    elif isinstance(content, list):
        for item in content:
            yield from _content_texts(item)


def message_texts(messages: Sequence[Any]) -> list[str]:
    """Mesajların (dict veya `ModelMessage`) metin parçaları."""
    out: list[str] = []
    for m in messages:
        content = m.get("content") if isinstance(m, Mapping) else getattr(m, "content", None)
        out.extend(_content_texts(content))
    return out


def untrusted_blocks(messages: Sequence[Any]) -> list[UntrustedBlock]:
    """`wrap_untrusted` ile sarılmış blokları (tür, kaynak, gövde) çıkarır."""
    return [
        UntrustedBlock(m["kind"], m["source"], m["body"])
        for text in message_texts(messages)
        for m in _BLOCK_RE.finditer(text)
    ]


def _json_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _json_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _json_strings(v)


_JSON_ESCAPES = {'\\"': '"', "\\n": "\n", "\\t": "\t", "\\/": "/", "\\\\": "\\"}
_JSON_ESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})|\\["ntr/\\]')


def _unescape_json_fragments(text: str) -> str:
    """Metne gömülü JSON dizgelerinin kaçışlarını açar (`\\"`, `\\n`, `\\u00e7` …)."""
    return _JSON_ESCAPE_RE.sub(
        lambda m: chr(int(m.group(1), 16)) if m.group(1) else _JSON_ESCAPES.get(m.group(0), " "),
        text,
    )


def _views(text: str) -> list[str]:
    """Metnin aranacak görünümleri: kendisi; JSON ise içindeki dizgeler; kaçış varsa açılmış hâli.

    Böylece gereksinimi düz satırlarla, JSON gövdesiyle veya prompt'a gömülü
    `json.dumps(...)` (ensure_ascii dahil) ile veren şeritler aynı sonucu alır.
    """
    views = [text]
    stripped = text.strip()
    if stripped[:1] in "[{":
        with contextlib.suppress(ValueError):
            views.extend(_json_strings(json.loads(stripped)))
    if "\\" in text:
        views.append(_unescape_json_fragments(text))
    return views


def _ac_views(text: str) -> list[str]:
    """AC çıkarımı için TEK yorum (aynı metnin iki yorumu yapay çelişki üretmesin): JSON gövdesi
    ise içindeki dizgeler, JSON kaçışı varsa açılmış metin, yoksa metnin kendisi."""
    stripped = text.strip()
    if stripped[:1] in "[{":
        try:
            return list(_json_strings(json.loads(stripped)))
        except ValueError:
            pass
    if "\\" in text:
        return [_unescape_json_fragments(text)]
    return [text]


def acceptance_criteria(texts: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    """Metinlerdeki `ACn: …` satırları → ({"AC1": "metin"}, çelişki listesi)."""
    found: dict[str, str] = {}
    conflicts: list[str] = []
    for text in texts:
        for view in _ac_views(text):
            for ref, body in _AC_LINE_RE.findall(view):
                value = norm(body)
                if ref in found and found[ref] != value:
                    conflicts.append(ref)
                found.setdefault(ref, value)
    return found, sorted(set(conflicts))


def case_block_text(body: str) -> str:
    """Case bloğunun kanonik metni: JSON case gövdesi `approved_case_text`'e çevrilir."""
    from tp_core.gateway.inputs import approved_case_text

    stripped = body.strip()
    if stripped.startswith("{"):
        with contextlib.suppress(ValueError):
            data = json.loads(stripped)
            if isinstance(data, Mapping):
                return approved_case_text(data)
    return body


def input_mismatches(spec: Mapping[str, Any], messages: Sequence[Any]) -> list[str]:
    """Girdinin golden beyanına uymadığı noktalar (boş liste = eşleşir). Türkçe, kısa."""
    sources = spec.get("sources")
    case_text = spec.get("case_text")
    if case_text is not None and not sources:
        raise ValueError("input_match.case_text için input_match.sources gerekli")
    if sources:
        blocks = [
            b for b in untrusted_blocks(messages) if any(fnmatchcase(b.source, p) for p in sources)
        ]
        if not blocks:
            return [f"kaynak bloğu yok: {', '.join(sources)}"]
        texts = [b.body for b in blocks]
    else:
        texts = message_texts(messages)

    reasons: list[str] = []
    if case_text is not None:
        want_case = norm(str(case_text))
        if any(norm(case_block_text(t)) != want_case for t in texts):
            reasons.append("onaylı case metni golden'ın beyan ettiğinden farklı")
    expected_acs = spec.get("acceptance_criteria")
    if expected_acs is not None:
        want, bad = acceptance_criteria(expected_acs)
        if bad or len(want) != len(expected_acs):
            raise ValueError(f"input_match.acceptance_criteria geçersiz: {expected_acs!r}")
        got, conflicts = acceptance_criteria(texts)
        if conflicts:
            reasons.append(f"çelişkili kabul kriteri: {', '.join(conflicts)}")
        for ref in sorted(set(want) | set(got), key=lambda r: int(r[2:])):
            if ref not in got:
                reasons.append(f"{ref} girdide yok")
            elif ref not in want:
                reasons.append(f"{ref} golden'da yok")
            elif got[ref] != want[ref]:
                reasons.append(f"{ref} metni farklı")

    haystack = norm("\n".join(v for t in texts for v in _views(t)))
    for needle in spec.get("contains") or []:
        if norm(needle) not in haystack:
            reasons.append(f"girdide yok: {needle[:60]}")
    cand_spec = spec.get("candidates")
    if cand_spec is not None:
        found = search_candidates(texts)
        if found is None:
            reasons.append("aday listesi (Aday anahtarları) girdide yok")
        else:
            reasons.extend(assign_candidates(cand_spec, found)[1])
    return reasons


# ------------------------------------------------------------------ mükerrer aday kümesi

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
_CANDIDATE_KEYS_RE = re.compile(r"^Aday anahtarları: \[(?P<keys>[^\]]*)\]\s*$", re.MULTILINE)
_CANDIDATE_LINE_RE = re.compile(
    r"^- (?P<key>[A-Z][A-Z0-9]*-\d+) · durum: .*? · özet: (?P<summary>.*)$", re.MULTILINE
)
LIKELIHOOD_ORDER = {"high": 0, "medium": 1, "low": 2}


def search_candidates(texts: Sequence[str]) -> dict[str, str] | None:
    """`defects.candidates_text` biçimindeki arama sonucundan {anahtar: özet} (yoksa None)."""
    for text in texts:
        m = _CANDIDATE_KEYS_RE.search(text)
        if not m:
            continue
        keys = [k.strip() for k in m.group("keys").split(",") if k.strip()]
        summaries = {c.group("key"): c.group("summary") for c in _CANDIDATE_LINE_RE.finditer(text)}
        return {k: summaries.get(k, "") for k in keys}
    return None


def _candidate_spec(spec: Any) -> tuple[list[str], list[str], dict[str, str]]:
    if not isinstance(spec, Mapping) or set(spec) - {"required", "optional", "by_summary"}:
        raise ValueError(f"input_match.candidates geçersiz: {spec!r}")
    required = list(spec.get("required") or [])
    optional = list(spec.get("optional") or [])
    by_summary = dict(spec.get("by_summary") or {})
    keys = required + optional
    if any(not isinstance(k, str) or not _KEY_RE.match(k) for k in keys) or len(set(keys)) != len(
        keys
    ):
        raise ValueError(f"input_match.candidates anahtarları geçersiz: {keys!r}")
    if not keys and not by_summary:
        raise ValueError("input_match.candidates boş")
    if any(not isinstance(v, str) or not v.strip() for v in by_summary.values()):
        raise ValueError(f"input_match.candidates.by_summary geçersiz: {by_summary!r}")
    return required, optional, by_summary


def assign_candidates(
    spec: Any, found: Mapping[str, str]
) -> tuple[dict[str, str | None], list[str]]:
    """Aramadaki her adayın beyandaki karşılığı: {anahtar: None (anahtarla beyan) | by_summary adı}
    ve uyuşmazlık nedenleri (boş = küme beyana uyar)."""
    required, optional, by_summary = _candidate_spec(spec)
    reasons = [f"zorunlu aday aramada yok: {k}" for k in required if k not in found]
    if not found:
        reasons.append("aramada aday yok")
    assigned: dict[str, str | None] = {}
    for key, summary in found.items():
        if key in required or key in optional:
            assigned[key] = None
            continue
        folded = norm(summary).casefold()
        name = next((n for n, sub in by_summary.items() if norm(sub).casefold() in folded), None)
        if name is None:
            reasons.append(f"beyan dışı aday: {key} ({norm(summary)[:50]})")
        else:
            assigned[key] = name
    return assigned, reasons


def _key_order(key: str) -> tuple[str, int]:
    prefix, _, num = key.rpartition("-")
    return prefix, int(num) if num.isdigit() else 0


def matched_output(record: Mapping[str, Any], messages: Sequence[Any] | None) -> Any:
    """Eşleşen golden'ın girdiye göre çıktısı. `input_match.candidates` yoksa golden çıktısı
    aynen; varsa sıralama girdideki GERÇEK aday kümesinden kurulur (yukarıdaki kural)."""
    spec = record.get("input_match")
    cand_spec = spec.get("candidates") if isinstance(spec, Mapping) else None
    if cand_spec is None:
        return record["output"]
    sources = spec.get("sources")
    blocks = untrusted_blocks(messages or [])
    if sources:
        blocks = [b for b in blocks if any(fnmatchcase(b.source, p) for p in sources)]
    found = search_candidates([b.body for b in blocks])
    if found is None:
        raise ValueError("aday listesi girdide yok; golden eşleşmemeliydi")
    assigned, reasons = assign_candidates(cand_spec, found)
    if reasons:
        raise ValueError(f"aday kümesi beyana uymuyor: {reasons}")
    output = record["output"]
    base = {str(c["key"]): (i, c) for i, c in enumerate(output.get("candidates") or [])}
    extras = record.get("extra_candidates") or {}
    extra_names = list(extras)
    rows: list[tuple[tuple[int, int, int, tuple[str, int]], dict[str, Any]]] = []
    for key in sorted(found, key=_key_order):
        name = assigned[key]
        if name is None:
            if key not in base:
                raise ValueError(f"golden çıktısında beyan edilen aday yok: {key}")
            idx, src = base[key]
            origin = (0, idx)
        else:
            if name not in extras:
                raise ValueError(f"extra_candidates.{name} yok")
            src, origin = extras[name], (1, extra_names.index(name))
        likelihood = str(src["likelihood"])
        entry = {"key": key, "likelihood": likelihood, "rationale": src["rationale"]}
        rows.append(((LIKELIHOOD_ORDER[likelihood], *origin, _key_order(key)), entry))
    ranked = [
        {"key": e["key"], "rank": i, "likelihood": e["likelihood"], "rationale": e["rationale"]}
        for i, (_, e) in enumerate(sorted(rows, key=lambda r: r[0]), start=1)
    ]
    link = next((c["key"] for c in ranked if c["likelihood"] == "high"), None)
    return {
        "candidates": ranked,
        "recommendation": "link" if link else "new",
        "link_key": link,
    }

"""JQL alt kümesi: ayrıştırıcı ve değerlendirici.

Desteklenen:
- Alanlar: project, key/issuekey, labels, text, summary, description, status, statusCategory,
  issuetype/type, reporter, created, updated
- Operatörler: ``=``, ``!=``, ``~``, ``!~``, ``in``, ``not in``, ``is [not] EMPTY``
- ``AND``, ``OR``, ``NOT``, parantez; ``ORDER BY alan [ASC|DESC], ...``

Metin araması (``~``) Jira'daki gibi kelime tabanlıdır: her terim belgede bulunmalıdır; terimler
kaba bir kök eşleşmesiyle (Türkçe ekler için önek) karşılaştırılır; ``"\\"tam ifade\\""`` ifade
araması yapar; ``terim*`` önek araması yapar.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

SearchDoc = dict[str, Any]
Predicate = Callable[[SearchDoc], bool]


class JqlError(ValueError):
    """Jira'nın 400 yanıtındaki ``errorMessages`` karşılığı."""


TEXT_FIELDS = {"text", "summary", "description"}
LIST_FIELDS = {"project", "key", "labels", "status", "statuscategory", "issuetype", "reporter"}
ORDER_FIELDS = {"created", "updated", "key", "summary"}
ALIASES = {"issuekey": "key", "id": "key", "type": "issuetype", "label": "labels"}
KNOWN = TEXT_FIELDS | LIST_FIELDS | {"created", "updated"}


def fold(s: str) -> str:
    """Büyük/küçük harf ve Türkçe İ/ı farkını yok sayan karşılaştırma biçimi."""
    return s.lower().replace("̇", "").replace("ı", "i")


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<op>!=|!~|>=|<=|=|~|>|<|\(|\)|,)
      | (?P<word>[^\s"'(),=!~<>]+)
    )""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class Tok:
    kind: str  # str | op | word
    value: str


def tokenize(jql: str) -> list[Tok]:
    out: list[Tok] = []
    pos = 0
    jql = jql.strip()
    while pos < len(jql):
        m = _TOKEN.match(jql, pos)
        if not m or m.end() == pos:
            raise JqlError(f"Error in the JQL Query: unexpected character at position {pos}.")
        pos = m.end()
        if m.group("str") is not None:
            raw = m.group("str")[1:-1]
            out.append(Tok("str", re.sub(r"\\(.)", r"\1", raw)))
        elif m.group("op") is not None:
            out.append(Tok("op", m.group("op")))
        elif m.group("word") is not None:
            out.append(Tok("word", m.group("word")))
    return out


# ------------------------------------------------------------------ metin eşleme

_WORD = re.compile(r"[\w]+", re.UNICODE)


def _stem(term: str) -> str:
    return term if len(term) <= 4 else term[: max(4, len(term) - 3)]


def text_matches(haystack: str, query: str) -> bool:
    hay = fold(haystack)
    q = query.strip()
    if len(q) >= 2 and q[0] == '"' and q[-1] == '"':
        phrase = " ".join(fold(q[1:-1]).split())
        return phrase in " ".join(hay.split())
    words = _WORD.findall(hay)
    terms = [t for t in re.findall(r"[\w*]+", fold(q)) if t.strip("*")]
    if not terms:
        return False
    for term in terms:
        if term.endswith("*"):
            prefix = term.rstrip("*")
            ok = any(w.startswith(prefix) for w in words)
        else:
            stem = _stem(term)
            ok = any(w.startswith(stem) or (len(w) >= 4 and term.startswith(w)) for w in words)
        if not ok:
            return False
    return True


# -------------------------------------------------------------------- ayrıştırıcı


@dataclass
class Query:
    predicate: Predicate
    order: list[tuple[str, bool]]  # (alan, azalan_mı)


class _Parser:
    def __init__(self, toks: Sequence[Tok]) -> None:
        self.toks = list(toks)
        self.i = 0

    # yardımcılar
    def peek(self, offset: int = 0) -> Tok | None:
        j = self.i + offset
        return self.toks[j] if j < len(self.toks) else None

    def is_word(self, *words: str, offset: int = 0) -> bool:
        t = self.peek(offset)
        return t is not None and t.kind == "word" and t.value.lower() in words

    def is_op(self, op: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == "op" and t.value == op

    def take(self) -> Tok:
        t = self.peek()
        if t is None:
            raise JqlError("Error in the JQL Query: the query is incomplete.")
        self.i += 1
        return t

    def expect_op(self, op: str) -> None:
        t = self.take()
        if t.kind != "op" or t.value != op:
            raise JqlError(f"Error in the JQL Query: expecting '{op}' but got '{t.value}'.")

    # gramer
    def parse(self) -> Query:
        pred: Predicate = lambda _d: True  # noqa: E731
        if self.peek() is not None and not self.is_word("order"):
            pred = self.or_expr()
        order: list[tuple[str, bool]] = []
        if self.is_word("order"):
            self.take()
            if not self.is_word("by"):
                raise JqlError("Error in the JQL Query: expecting 'by' after 'order'.")
            self.take()
            while True:
                field = self.field_name(self.take())
                if field not in ORDER_FIELDS:
                    raise JqlError(f"Field '{field}' does not support sorting.")
                desc = False
                if self.is_word("asc", "desc"):
                    desc = self.take().value.lower() == "desc"
                order.append((field, desc))
                if self.is_op(","):
                    self.take()
                    continue
                break
        if self.peek() is not None:
            raise JqlError(f"Error in the JQL Query: unexpected '{self.take().value}'.")
        return Query(pred, order)

    def or_expr(self) -> Predicate:
        parts = [self.and_expr()]
        while self.is_word("or"):
            self.take()
            parts.append(self.and_expr())
        if len(parts) == 1:
            return parts[0]
        return lambda d: any(p(d) for p in parts)

    def and_expr(self) -> Predicate:
        parts = [self.unary()]
        while self.is_word("and"):
            self.take()
            parts.append(self.unary())
        if len(parts) == 1:
            return parts[0]
        return lambda d: all(p(d) for p in parts)

    def unary(self) -> Predicate:
        if self.is_word("not"):
            self.take()
            inner = self.unary()
            return lambda d: not inner(d)
        if self.is_op("("):
            self.take()
            inner = self.or_expr()
            self.expect_op(")")
            return inner
        return self.clause()

    @staticmethod
    def field_name(tok: Tok) -> str:
        name = tok.value.lower()
        name = ALIASES.get(name, name)
        if name not in KNOWN:
            raise JqlError(
                f"Field '{tok.value}' does not exist or you do not have permission to view it."
            )
        return name

    def value(self) -> str:
        t = self.take()
        if t.kind == "op":
            raise JqlError(f"Error in the JQL Query: expecting a value but got '{t.value}'.")
        if t.kind == "word" and self.is_op("("):
            raise JqlError(f"Unable to find JQL function '{t.value}()'.")
        return t.value

    def clause(self) -> Predicate:
        field = self.field_name(self.take())
        t = self.take()
        if t.kind == "word" and t.value.lower() == "not" and self.is_word("in"):
            self.take()
            op = "not in"
        elif t.kind == "word" and t.value.lower() == "in":
            op = "in"
        elif t.kind == "word" and t.value.lower() == "is":
            op = "is"
            if self.is_word("not"):
                self.take()
                op = "is not"
        elif t.kind == "op" and t.value in ("=", "!=", "~", "!~"):
            op = t.value
        else:
            raise JqlError(f"Error in the JQL Query: unsupported operator '{t.value}'.")

        if op in ("is", "is not"):
            v = self.take().value.lower()
            if v not in ("empty", "null"):
                raise JqlError("Error in the JQL Query: expecting EMPTY or NULL after 'is'.")
            empty = op == "is"
            return lambda d: (not d.get(field)) == empty

        if op in ("in", "not in"):
            self.expect_op("(")
            values = [self.value()]
            while self.is_op(","):
                self.take()
                values.append(self.value())
            self.expect_op(")")
            folded = {fold(v) for v in values}
            if field in TEXT_FIELDS:
                raise JqlError(f"The operator '{op}' is not supported by the '{field}' field.")
            hit = lambda d: any(fold(x) in folded for x in _as_list(d.get(field)))  # noqa: E731
            return hit if op == "in" else (lambda d: not hit(d))

        value = self.value()
        if op in ("~", "!~"):
            if field not in TEXT_FIELDS:
                raise JqlError(f"The operator '{op}' is not supported by the '{field}' field.")
            match = lambda d: text_matches(str(d.get(field) or ""), value)  # noqa: E731
            return match if op == "~" else (lambda d: not match(d))
        if field in TEXT_FIELDS:
            raise JqlError(f"The operator '{op}' is not supported by the '{field}' field.")
        fv = fold(value)
        eq = lambda d: any(fold(x) == fv for x in _as_list(d.get(field)))  # noqa: E731
        return eq if op == "=" else (lambda d: not eq(d))


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list | tuple | set):
        return [str(x) for x in v]
    return [str(v)]


def parse(jql: str) -> Query:
    return _Parser(tokenize(jql or "")).parse()


def _key_sort(key: str) -> tuple[str, int]:
    proj, _, num = key.rpartition("-")
    return (proj, int(num) if num.isdigit() else 0)


def sort_docs(docs: list[SearchDoc], order: list[tuple[str, bool]]) -> list[SearchDoc]:
    """Kararlı çok anahtarlı sıralama. Sıra verilmezse anahtar azalan (en yeni önce)."""
    result = list(docs)
    order = order or [("key", True)]
    for field, desc in reversed(order):
        if field == "key":
            result.sort(key=lambda d: _key_sort(d["key"][0]), reverse=desc)
        else:
            result.sort(key=lambda d, f=field: str(d.get(f) or ""), reverse=desc)
    return result

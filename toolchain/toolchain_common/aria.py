"""Aria snapshot (Playwright YAML) içinde rol + ad araması — model yok, deterministik.

TEKNIK-TASARIM §8.6 kural 3 ("niyete uyan eleman (rol + ad, aria snapshot'tan) aynı sayfada var")
ve §8.7 doğrulaması ("aday, son yeşil koşudaki aria snapshot'ının role + name değerleriyle
eşleşmeli") için girdi. Aria snapshot yalnızca rol ve ad içerir (data-testid yok); testId'yi
`/locator-probe` (çalışan uygulama) ya da `/trace-summary` (trace DOM snapshot'ı) okur.

Biçim (Playwright 1.64 `ariaSnapshot()` / `error-context.md`):

    - main:
      - article "Kola 330 ml":
        - heading "Kola 330 ml" [level=2]
        - spinbutton "Adet"
        - button "Sepete ekle" [ref=e4]
      - text: Adet

Snapshot güvenilmeyen veridir (test kodunun çalıştığı sayfa): yalnızca satır satır okunur,
boyut ve satır sayısı sınırlıdır, çıktıdaki metinler kırpılır.

Eşleme `getByRole(role, {name})` varsayılanıyla aynıdır: ad, boşluklar sadeleştirilip harf
duyarsız **alt dize** olarak aranır (`eslesen`); `tam_eslesen` birebir aynı adı sayar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runner.results import safe_read_bytes

MAX_ARIA_BYTES = 2_000_000
MAX_LINES = 20_000
MAX_PATHS = 20

_LINE_RE = re.compile(
    r"""^(?P<indent>\s*)-\s+(?P<role>[a-zA-Z][\w-]*)"""
    r"""(?:\s+(?P<name>"(?:[^"\\]|\\.)*"|/(?:[^/\\]|\\.)*/[a-z]*))?"""
    r"""(?P<rest>.*)$"""
)
_WS = re.compile(r"\s+")
_PAGE_SNAPSHOT_RE = re.compile(r"^# Page snapshot\s*\n+```(?:yaml)?\n(.*?)\n```", re.S | re.M)
_YAML_BLOCK_RE = re.compile(r"^```yaml\n(.*?)\n```", re.S | re.M)


@dataclass
class AriaNode:
    role: str
    name: str | None
    indent: int
    parent: AriaNode | None = None
    children: list[AriaNode] = field(default_factory=list)

    def label(self) -> str:
        return f'{self.role} "{self.name}"' if self.name is not None else self.role

    def path(self) -> list[str]:
        out: list[str] = []
        node: AriaNode | None = self
        while node is not None:
            out.append(node.label()[:120])
            node = node.parent
        return out[::-1]


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _name(raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw[1:-1]
        return str(value)
    # /regex/ adları (Playwright snapshot şablonu); metin olarak saklanır.
    return raw


def parse(text: str) -> list[AriaNode]:
    """YAML satırlarını rol + ad düğümlerine çevirir (girintiye göre ebeveynli)."""
    nodes: list[AriaNode] = []
    stack: list[AriaNode] = []
    for line in text.splitlines()[:MAX_LINES]:
        m = _LINE_RE.match(line)
        if not m:
            continue
        role = m["role"]
        rest = m["rest"] or ""
        name = _name(m["name"])
        if name is None and role == "text":
            # `- text: Adet` → metin düğümü (rolü yok sayılmaz ama ad metindir).
            name = rest.lstrip(":").strip() or None
        indent = len(m["indent"])
        while stack and stack[-1].indent >= indent:
            stack.pop()
        node = AriaNode(role=role, name=name, indent=indent, parent=stack[-1] if stack else None)
        if node.parent is not None:
            node.parent.children.append(node)
        nodes.append(node)
        stack.append(node)
    return nodes


def _name_matches(have: str | None, want: str, exact: bool) -> bool:
    if have is None:
        return want == ""
    if exact:
        return _norm(have) == _norm(want)
    return _norm(want).casefold() in _norm(have).casefold()


def match(
    text: str,
    role: str,
    name: str,
    *,
    scope_role: str | None = None,
    scope_name: str | None = None,
) -> dict[str, Any]:
    """`role` + `name` kaç düğümde var; `scope_*` verilirse yalnızca o kapsayıcının altında."""
    nodes = parse(text)
    scopes: list[AriaNode] | None = None
    if scope_role:
        scopes = [
            n
            for n in nodes
            if n.role == scope_role
            and (scope_name is None or _name_matches(n.name, scope_name, exact=False))
        ]

    def in_scope(n: AriaNode) -> bool:
        if scopes is None:
            return True
        p = n.parent
        while p is not None:
            if p in scopes:
                return True
            p = p.parent
        return False

    hits = [
        n for n in nodes if n.role == role and _name_matches(n.name, name, False) and in_scope(n)
    ]
    exact = [n for n in hits if _name_matches(n.name, name, True)]
    return {
        "rol": role,
        "ad": name,
        "kapsam": (
            {"rol": scope_role, "ad": scope_name, "eslesen": len(scopes)}
            if scopes is not None
            else None
        ),
        "eslesen": len(hits),
        "tam_eslesen": len(exact),
        "var": bool(hits),
        "yollar": [n.path() for n in hits[:MAX_PATHS]],
        "dugum_sayisi": len(nodes),
    }


class AriaSourceError(ValueError):
    """Aria snapshot dosyası okunamadı / izin verilen yerde değil."""


def resolve_artifact(artifacts: Path, rel: str, *, suffixes: tuple[str, ...]) -> Path:
    """`rel` (TP_ARTIFACTS_PATH'e göre) → `runs/` altında, sembolik bağsız düzenli dosya."""
    if (
        not isinstance(rel, str)
        or not rel
        or rel.startswith(("/", "-"))
        or ".." in rel.split("/")
        or "\\" in rel
        or any(ord(c) < 32 for c in rel)
    ):
        raise AriaSourceError(f"geçersiz kanıt yolu: {rel!r}")
    if not rel.startswith("runs/"):
        raise AriaSourceError("kanıt yolu runs/ altında olmalı")
    if not rel.endswith(suffixes):
        raise AriaSourceError(f"desteklenmeyen dosya türü (beklenen: {', '.join(suffixes)})")
    base = (artifacts / "runs").resolve()
    p = artifacts / rel
    try:
        real = p.resolve()
    except (OSError, RuntimeError) as exc:
        raise AriaSourceError(f"kanıt yolu çözülemedi: {exc}") from exc
    if base not in real.parents:
        raise AriaSourceError("kanıt yolu koşu dizinlerinin dışında")
    return p


def load_snapshot(artifacts: Path, rel: str) -> str:
    """`error-context.md` (aria bölümü) ya da ham `.yml/.yaml/.aria` snapshot metni."""
    p = resolve_artifact(artifacts, rel, suffixes=(".md", ".yml", ".yaml", ".aria"))
    try:
        text = safe_read_bytes(p, MAX_ARIA_BYTES).decode("utf-8", "replace")
    except FileNotFoundError as exc:
        raise AriaSourceError("kanıt dosyası yok") from exc
    except (OSError, ValueError) as exc:
        raise AriaSourceError(f"kanıt dosyası okunamadı: {exc}") from exc
    if p.name.endswith(".md"):
        # error-context.md: sayfa snapshot'ı (`# Page snapshot`) ya da hata ayrıntısındaki YAML.
        m = _PAGE_SNAPSHOT_RE.search(text) or _YAML_BLOCK_RE.search(text)
        if not m:
            raise AriaSourceError("dosyada aria snapshot bulunamadı")
        return m.group(1)
    return text

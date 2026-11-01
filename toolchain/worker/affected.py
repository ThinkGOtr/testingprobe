"""Etkilenen testler: bir commit'in e2e ağacında içe aktarma grafiği (TEKNIK-TASARIM §8.7).

§8.7: locator onarım PR'ı "yerel kontrol **etkilenen tüm testlerde** yeşilse" açılır (AI'ın
ürettikleri ve elle yazılanlar). Bu modül, değişen kaynak dosyalarını (ör.
`pages/catalog/locators.ts`) doğrudan ya da dolaylı (barrel `pages/index.ts`, `tests/fixtures.ts`)
içe aktaran tüm `tests/**/*.spec.ts` dosyalarını bulur.

Yalnızca metin olarak ayrıştırılır (kod çalıştırılmaz): `import … from "x"`, `export … from "x"`,
`import("x")`, `require("x")` ve yan etki içe aktarımı `import "x"`. Yalnızca göreli belirteçler
(`./`, `../`) çözülür; paketler (`@playwright/test`) grafiğe girmez. Çözüm TypeScript'in
`moduleResolution: bundler` kuralıdır: `x.ts`, `x.tsx`, `x.mts`, `x/index.ts`; `.js` uzantılı
belirteç `.ts` dosyasına eşlenir.

Belirsiz durumda **daha geniş** kapsam seçilir (yanlış yeşil yerine fazla test): bir hedef
grafikte hiç bulunamazsa ya da hiçbir spec onu içe aktarmıyorsa `tam_kapsam=True` döner ve
çağıran tüm testleri koşturur.
"""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any

from toolchain_common import gitforge, proc
from toolchain_common.validation import TEST_FILE_RE

MAX_FILES = 5_000
MAX_FILE_BYTES = 1_000_000
SOURCE_SUFFIXES = (".ts", ".tsx", ".mts", ".cts")
SKIP_DIRS = {"node_modules", "results", "test-results", "playwright-report", "dist", ".git"}

_SPEC_RE = re.compile(
    r"""(?:\bimport\s+(?:type\s+)?(?:[\w*{}\s,$]+?\s+from\s+)?|\bexport\s+(?:type\s+)?"""
    r"""(?:\*(?:\s+as\s+\w+)?|\{[^}]*\})\s+from\s+|\bimport\s*\(\s*|\brequire\s*\(\s*)"""
    r"""(["'])([^"'\n]{1,300})\1"""
)
# e2e köküne göre kaynak yolu (affected_by girdisi): pages/…, tests/…, tools/…
SOURCE_PATH_RE = re.compile(
    r"^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:ts|tsx|mts|cts)\Z"
)


def validate_source_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not SOURCE_PATH_RE.match(value)
        or ".." in value.split("/")
        or len(value) > 300
    ):
        raise ValueError(f"geçersiz kaynak yolu: {value!r} (ör. pages/catalog/locators.ts)")
    return value


def _sources(root: Path) -> list[str]:
    out: list[str] = []
    stack = [root]
    while stack and len(out) < MAX_FILES:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_symlink():
                continue
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif p.is_file() and p.name.endswith(SOURCE_SUFFIXES) and not p.name.endswith(".d.ts"):
                out.append(p.relative_to(root).as_posix())
    return out


def _resolve(spec: str, importer: str, files: set[str]) -> str | None:
    if not spec.startswith(("./", "../")):
        return None
    base = (Path(importer).parent / spec).as_posix()
    parts: list[str] = []
    for part in base.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None  # e2e kökünün dışı
            parts.pop()
        else:
            parts.append(part)
    stem = "/".join(parts)
    candidates = [stem]
    for js, ts in ((".js", ".ts"), (".jsx", ".tsx"), (".mjs", ".mts"), (".cjs", ".cts")):
        if stem.endswith(js):
            candidates.append(stem[: -len(js)] + ts)
    candidates += [stem + s for s in SOURCE_SUFFIXES]
    candidates += [f"{stem}/index{s}" for s in SOURCE_SUFFIXES]
    return next((c for c in candidates if c in files), None)


def import_graph(root: Path) -> dict[str, set[str]]:
    """dosya → içe aktardığı (çözülmüş, e2e içi) dosyalar."""
    files = _sources(root)
    known = set(files)
    graph: dict[str, set[str]] = {}
    for rel in files:
        try:
            raw = (root / rel).read_bytes()[:MAX_FILE_BYTES]
        except OSError:
            continue
        text = raw.decode("utf-8", "replace")
        deps: set[str] = set()
        for m in _SPEC_RE.finditer(text):
            target = _resolve(m.group(2), rel, known)
            if target is not None:
                deps.add(target)
        graph[rel] = deps
    return graph


def affected_tests(root: Path, changed: list[str]) -> dict[str, Any]:
    """`changed` dosyalarından etkilenen spec dosyaları (ters içe aktarma kapanışı)."""
    graph = import_graph(root)
    reverse: dict[str, set[str]] = {}
    for src, deps in graph.items():
        for d in deps:
            reverse.setdefault(d, set()).add(src)
    unknown = [c for c in changed if c not in graph]
    seen: set[str] = set()
    queue = deque(c for c in changed if c in graph)
    while queue:
        cur = queue.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        queue.extend(reverse.get(cur, ()))
    specs = sorted(f for f in seen if TEST_FILE_RE.match(f))
    tam = bool(unknown) or not specs
    if unknown:
        neden = "değişen dosya e2e ağacında bulunamadı: " + ", ".join(unknown[:10])
    elif not specs:
        neden = "değişen dosyayı içe aktaran test bulunamadı"
    else:
        neden = None
    return {
        "yontem": "import_grafi",
        "kaynak": list(changed),
        "test_files": specs,
        "tam_kapsam": tam,
        "tam_kapsam_nedeni": neden,
        "dosya_sayisi": len(graph),
    }


def changed_files(repo: Path, base: str, head: str, root: str, timeout_s: float = 60) -> list[str]:
    """`base..head` arasında `root/` altında değişen dosyalar, köke göre (ör. pages/x.ts).

    Kök dışındaki değişiklikler (ör. uygulama kodu) burada sayılmaz; onları `/check`'in `app`
    adımı ve AST koruması ele alır.
    """
    res = proc.run(
        gitforge._git_argv(
            repo, "diff", "--name-only", "--no-renames", "-z", "--end-of-options", base, head
        ),
        env=gitforge.git_env(),
        timeout_s=timeout_s,
        keep_full_stdout=True,
    )
    if res.timed_out or not res.ok:
        raise gitforge.ForgeError(f"git diff başarısız: {res.stderr.strip()[:300]}")
    prefix = root.rstrip("/") + "/"
    out = []
    for name in res.stdout.split("\0"):
        if name.startswith(prefix):
            out.append(name[len(prefix) :])
    return out[:MAX_FILES]

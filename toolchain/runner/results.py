"""Playwright JSON raporunun (`results.json`) özeti: sayılar, test bazında sonuç, hata girdileri.

Rapor test kodunun çıktısıdır (güvenilmeyen veri): yalnızca bilinen alanlar okunur, metinler
kırpılır ve ANSI kaçışları silinir. Ek yolları yalnızca koşu dizini içindeyse döner.

Başarısız her test için `failure` = Faz 3 yerel kontrolünün ve Faz 4 triage'ının deterministik
girdileri (TEKNIK-TASARIM §8.4 adım 5, §8.6 kural 1–5). Burada **karar verilmez**: `type` hata
metninin biçimsel türüdür (assertion mı, locator mı …), sınıf (defect adayı / bakım / ortam) core'un
işidir. Türler (öncelik sırasıyla):

- `test_data`        — veri hazırlığı (fixture: `/test/reset|break`) başarısız
                       (hata `tests/fixtures.ts`'te ya da bilinen fixture mesajı)
- `navigation`       — `page.goto/reload/…` hatası, `net::ERR_*`
- `locator_ambiguous`— strict mode: locator birden çok elemana çözüldü
- `locator_not_found`— `expect(locator)` zaman aşımında eleman yok ("element(s) not found")
- `locator_timeout`  — eylem (click/fill …) locator'ı beklerken zaman aşımı (test zaman aşımı dahil)
- `assertion`        — eleman bulundu ya da değer karşılaştırıldı, beklenen ≠ gerçekleşen
- `test_timeout`     — test zaman aşımı, bekleyen locator tespit edilemedi
- `other`            — yukarıdakilerin hiçbiri
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MAX_ERROR = 2000
MAX_FIELD = 500
MAX_TESTS = 500
MAX_ARIA = 8000
MAX_RESULTS_JSON = 64 * 1024 * 1024  # Playwright JSON raporu üst sınırı (bayt)

FAILURE_TYPES = (
    "test_data",
    "navigation",
    "locator_ambiguous",
    "locator_not_found",
    "locator_timeout",
    "assertion",
    "test_timeout",
    "other",
)

# Eklerin triage'daki adları (Playwright ek adı → anahtar).
EVIDENCE_NAMES = {
    "trace": "trace",
    "error-context": "error_context",
    "screenshot": "screenshot",
    "video": "video",
}

_ACTION_RE = re.compile(
    r"^(?:[A-Za-z]*Error:\s*)?((?:locator|page|frame|elementHandle|keyboard|mouse|request|"
    r"apiRequestContext)\.[A-Za-z]+):",
)
_MATCHER_RE = re.compile(r"expect\((?:locator|received|page|response)\)\.((?:not\.)?\w+)\(")
_LOCATOR_LINE_RE = re.compile(r"^Locator:\s+(.+)$", re.M)
_WAITING_RE = re.compile(
    r"waiting for ((?:getBy|locator\(|frameLocator\(|internal:)\S.*?)\s*$", re.M
)
_EXPECTED_RE = re.compile(r"^Expected(?: string| pattern| substring| value)?:\s*(.*)$", re.M)
_RECEIVED_RE = re.compile(r"^Received(?: string| value)?:\s*(.*)$", re.M)
_TIMEOUT_RE = re.compile(
    r"(?:Timeout:?\s+(\d+)\s*ms|Timeout (\d+)ms exceeded|Test timeout of (\d+)ms exceeded)"
)
_FRAME_RE = re.compile(r"(?:\(|\s)(/[^\s():]+):(\d+):(\d+)\)?\s*$", re.M)
_NAV_RE = re.compile(
    r"(^(?:[A-Za-z]*Error:\s*)?page\.(?:goto|reload|goBack|goForward|waitForURL|waitForNavigation):)"
    r"|net::ERR_|NS_ERROR_|navigating to \""
)
_TEST_DATA_RE = re.compile(
    r"POST /test/(?:reset|break) başarısız|sepet temizliği için giriş başarısız|sepet boşaltılamadı"
    r"|DEMOAPP_TEST_TOKEN"
)
FIXTURE_FILES = ("tests/fixtures.ts",)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _clip(text: Any, limit: int = MAX_ERROR) -> str:
    s = strip_ansi(str(text or ""))
    return s if len(s) <= limit else s[:limit] + "…"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_read_bytes(path: Path, limit: int) -> bytes:
    """Koşu çıktısını güvenle okur: sembolik bağ, FIFO/aygıt reddedilir; en fazla `limit` bayt.

    Test kodu `results/` altına `/dev/zero` ya da koşu dizini dışına bağ bırakabilir; runner
    RUN_LOCK tutarken bloklanmamalı ve dışarıdaki dosyayı kanıt diye okumamalı. Sınır aşılırsa
    `ValueError`; dosya yoksa `FileNotFoundError`; diğerleri `OSError`."""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise OSError(f"sembolik bağ okunmaz: {path.name}")
    if not stat.S_ISREG(st.st_mode):
        raise OSError(f"düzenli dosya değil: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"düzenli dosya değil: {path.name}")
        chunks: list[bytes] = []
        kalan = limit + 1
        while kalan > 0:
            parca = os.read(fd, min(kalan, 1 << 20))
            if not parca:
                break
            chunks.append(parca)
            kalan -= len(parca)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > limit:
        raise ValueError(f"{path.name} çok büyük (>{limit} bayt)")
    return data


def _inside(raw: Any, base: Path) -> Path | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        p = Path(raw).resolve()
        b = base.resolve()
    except (OSError, RuntimeError):
        return None
    return p if b in p.parents else None


def _attachment_path(raw: Any, base: Path) -> str | None:
    p = _inside(raw, base)
    return str(p) if p is not None else None


def _rel_source(raw: Any, e2e_dir: Path | None) -> str | None:
    """Kaynak dosya yolu e2e köküne göre (`pages/cart/cart.page.ts`); kök dışıysa yalnızca ad."""
    if not isinstance(raw, str) or not raw:
        return None
    p = Path(raw)
    if e2e_dir is not None and p.is_absolute():
        try:
            return str(p.resolve().relative_to(e2e_dir.resolve()))
        except (ValueError, OSError):
            return p.name
    return raw if not p.is_absolute() else p.name


def _location(raw: Any, e2e_dir: Path | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    file = _rel_source(raw.get("file"), e2e_dir)
    if not file:
        return None
    return {"file": file, "line": _int(raw.get("line")), "column": _int(raw.get("column"))}


def _frames(text: str, e2e_dir: Path | None) -> list[dict[str, Any]]:
    out = []
    for m in _FRAME_RE.finditer(text):
        file = _rel_source(m.group(1), e2e_dir)
        if file:
            out.append({"file": file, "line": int(m.group(2)), "column": int(m.group(3))})
    return out


def _first(regex: re.Pattern[str], text: str) -> str | None:
    m = regex.search(text)
    if not m:
        return None
    value = next((g for g in m.groups() if g is not None), None)
    return _clip(value.strip(), MAX_FIELD) if value is not None else None


def classify_error(messages: list[str], location_file: str | None = None) -> dict[str, Any]:
    """Hata metin(ler)inden biçimsel tür + çıkarılan alanlar (karar değil, girdi).

    `messages`: bir denemenin tüm hata mesajları (test zaman aşımında ikinci mesaj bekleyen
    eylemi taşır). `location_file`: hatanın e2e köküne göre dosyası (fixture tespiti için).
    """
    texts = [strip_ansi(m) for m in messages if m]
    joined = "\n".join(texts)
    first_line = texts[0].splitlines()[0].strip() if texts and texts[0].strip() else ""
    signals: list[str] = []

    action = None
    for t in texts:
        m = _ACTION_RE.match(t.strip())
        if m:
            action = m.group(1)
            break
    matcher_m = _MATCHER_RE.search(joined)
    matcher = matcher_m.group(1) if matcher_m else None
    locator = _first(_LOCATOR_LINE_RE, joined) or _first(_WAITING_RE, joined)
    expected = _first(_EXPECTED_RE, joined)
    received = _first(_RECEIVED_RE, joined)
    tm = _TIMEOUT_RE.search(joined)
    timeout_ms = int(next(g for g in tm.groups() if g)) if tm else None
    test_timeout = "Test timeout of" in joined
    if test_timeout:
        signals.append("test zaman aşımı")

    if location_file in FIXTURE_FILES or _TEST_DATA_RE.search(joined):
        kind = "test_data"
        signals.append("veri hazırlığı (fixture) başarısız")
    elif _NAV_RE.search(joined):
        kind = "navigation"
        signals.append("sayfa yüklenemedi / gezinme hatası")
    elif "strict mode violation" in joined:
        kind = "locator_ambiguous"
        signals.append("strict mode: locator birden çok elemana çözüldü")
    elif "element(s) not found" in joined:
        kind = "locator_not_found"
        signals.append("element(s) not found")
    elif (
        action is not None
        and action.startswith("locator.")
        and ("Timeout" in joined or test_timeout)
        and _WAITING_RE.search(joined)
    ):
        kind = "locator_timeout"
        signals.append(f"{action}: locator beklenirken zaman aşımı")
    elif matcher is not None or (expected is not None and received is not None):
        kind = "assertion"
        signals.append("beklenen ≠ gerçekleşen")
    elif test_timeout:
        kind = "test_timeout"
    else:
        kind = "other"
    return {
        "type": kind,
        "first_line": _clip(first_line, MAX_FIELD),
        "matcher": matcher,
        "action": action,
        "locator": locator,
        "expected": expected,
        "received": received,
        "timeout_ms": timeout_ms,
        "signals": signals,
    }


def _failed_step(steps: Any, path: list[str]) -> dict[str, Any] | None:
    """Hatayı taşıyan en derin `test.step` (üretilen testlerde adım başlığı case adımıdır)."""
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict) or not step.get("error"):
            continue
        title = _clip(step.get("title"), 200)
        deeper = _failed_step(step.get("steps"), [*path, title])
        return deeper or {"title": title, "path": [*path, title]}
    return None


def _aria_snapshot(path: Path | None) -> tuple[str | None, str | None]:
    """error-context.md'deki aria snapshot'ı (rol + ad ağacı; güvenilmeyen veri) ve kapsamı.

    `# Page snapshot` bölümü varsa sayfanın tamamıdır (`page`). expect hatalarında Playwright
    YAML'ı başlıksız olarak hata ayrıntısının altına koyar (`error_details`); kapsamı sayfa ya da
    eleman olabilir, bu yüzden ayrı etiketlenir.
    """
    if path is None:
        return None, None
    try:
        text = safe_read_bytes(path, 2_000_000)[:200_000].decode("utf-8", "replace")
    except (OSError, ValueError):
        return None, None
    m = re.search(r"^# Page snapshot\s*\n+```(?:yaml)?\n(.*?)\n```", text, re.S | re.M)
    if m:
        return _clip(m.group(1), MAX_ARIA), "page"
    m = re.search(r"^```yaml\n(.*?)\n```", text, re.S | re.M)
    if m:
        return _clip(m.group(1), MAX_ARIA), "error_details"
    return None, None


def failure_inputs(
    result: dict[str, Any],
    base: Path,
    e2e_dir: Path | None,
    rel_root: Path | None,
) -> dict[str, Any]:
    """Bir denemenin (`results[i]`) triage girdileri."""
    errors = [e for e in result.get("errors") or [] if isinstance(e, dict)]
    err = result.get("error") if isinstance(result.get("error"), dict) else {}
    messages = [str(e.get("message") or "") for e in errors] or [str(err.get("message") or "")]
    location = _location(result.get("errorLocation"), e2e_dir) or next(
        (loc for e in errors if (loc := _location(e.get("location"), e2e_dir))), None
    )
    stack = strip_ansi(str(err.get("stack") or "")) + "\n" + "\n".join(map(strip_ansi, messages))
    frames = _frames(stack, e2e_dir)
    test_location = next(
        (f for f in frames if f["file"].startswith("tests/") and f["file"].endswith(".spec.ts")),
        None,
    )
    if test_location is None and location and location["file"].endswith(".spec.ts"):
        test_location = location
    info = classify_error(messages, location["file"] if location else None)

    evidence: dict[str, Any] = {key: None for key in EVIDENCE_NAMES.values()}
    for a in result.get("attachments") or []:
        if not isinstance(a, dict):
            continue
        key = EVIDENCE_NAMES.get(str(a.get("name")))
        p = _inside(a.get("path"), base)
        if key is None or p is None or evidence[key] is not None:
            continue
        rel = None
        if rel_root is not None:
            try:
                rel = str(p.relative_to(rel_root.resolve()))
            except ValueError:
                rel = None
        evidence[key] = {"path": str(p), "rel": rel, "exists": p.is_file()}
    ctx = evidence["error_context"]
    aria, aria_scope = _aria_snapshot(Path(ctx["path"])) if ctx and ctx["exists"] else (None, None)

    return {
        **info,
        "message": _clip(messages[0] if messages else ""),
        "messages": [_clip(m) for m in messages[1:4]],
        "location": location,
        "test_location": test_location,
        "step": _failed_step(result.get("steps"), []),
        "attempt": _int(result.get("retry")),
        "status": str(result.get("status") or ""),
        "evidence": evidence,
        "aria_snapshot": aria,
        "aria_snapshot_scope": aria_scope,
    }


def _walk(
    suite: dict[str, Any],
    titles: list[str],
    out: list[dict[str, Any]],
    base: Path,
    e2e_dir: Path | None,
    rel_root: Path | None,
) -> None:
    title = suite.get("title")
    here = [*titles, title] if isinstance(title, str) and title else titles
    for spec in suite.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        for test in spec.get("tests") or []:
            if not isinstance(test, dict) or len(out) >= MAX_TESTS:
                continue
            results = [r for r in test.get("results") or [] if isinstance(r, dict)]
            failing = next(
                (r for r in results if r.get("status") not in ("passed", "skipped")), None
            )
            error = None
            failure = None
            if failing is not None:
                err = failing.get("error") or {}
                error = _clip(err.get("message") if isinstance(err, dict) else err)
                failure = failure_inputs(failing, base, e2e_dir, rel_root)
            attachments = []
            for r in results:
                for a in r.get("attachments") or []:
                    if not isinstance(a, dict):
                        continue
                    path = _attachment_path(a.get("path"), base)
                    if path:
                        attachments.append(
                            {
                                "name": _clip(a.get("name"), 100),
                                "path": path,
                                "retry": r.get("retry"),
                            }
                        )
            attempts = []
            for r in results:
                kind = None
                if r.get("status") not in ("passed", "skipped"):
                    kind = (
                        failure["type"]
                        if r is failing and failure
                        else failure_inputs(r, base, e2e_dir, rel_root)["type"]
                    )
                attempts.append(
                    {
                        "retry": _int(r.get("retry")),
                        "status": str(r.get("status") or ""),
                        "duration_ms": _int(r.get("duration")),
                        "type": kind,
                    }
                )
            out.append(
                {
                    "id": str(spec.get("id") or "")[:200],
                    "title": " › ".join([*here[1:], str(spec.get("title", ""))]) or "",
                    "file": str(spec.get("file") or suite.get("file") or ""),
                    "line": _int(spec.get("line")),
                    "column": _int(spec.get("column")),
                    "project": str(test.get("projectName") or ""),
                    "status": str(test.get("status") or ""),  # expected|unexpected|flaky|skipped
                    "tags": [str(t) for t in spec.get("tags") or []][:20],
                    "attempts": len(results),
                    "attempt_results": attempts[:20],
                    "duration_ms": sum(_int(r.get("duration")) for r in results),
                    "error": error,
                    "failure": failure,
                    "attachments": attachments[:20],
                }
            )
    for child in suite.get("suites") or []:
        if isinstance(child, dict):
            _walk(child, here, out, base, e2e_dir, rel_root)


def summarize(
    results_json: Path,
    attachments_base: Path,
    *,
    e2e_dir: Path | None = None,
    rel_root: Path | None = None,
) -> dict[str, Any]:
    """`results.json` → {stats, tests, errors}. Dosya yok/bozuksa `ValueError`.

    `e2e_dir`: kaynak konumlarını göreli yazmak için koşunun e2e kökü; `rel_root`: kanıt
    yollarının `rel` alanı için kök (TP_ARTIFACTS_PATH).
    """
    try:
        data = json.loads(safe_read_bytes(results_json, MAX_RESULTS_JSON).decode("utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("Playwright JSON raporu üretilmedi") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Playwright JSON raporu okunamadı: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Playwright JSON raporu nesne değil")
    raw_stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    stats = {
        k: _int(raw_stats.get(k))
        for k in ("expected", "unexpected", "flaky", "skipped", "duration")
    }
    stats["duration_ms"] = stats.pop("duration")
    tests: list[dict[str, Any]] = []
    for suite in data.get("suites") or []:
        if isinstance(suite, dict):
            _walk(suite, [], tests, attachments_base, e2e_dir, rel_root)
    # --repeat-each: her tekrar ayrı girdidir (aynı id). Sırayla 0,1,2… numaralanır.
    seen: dict[str, int] = {}
    for t in tests:
        key = _group_key(t)
        t["repeat_index"] = seen.get(key, 0)
        seen[key] = t["repeat_index"] + 1
    errors = [
        _clip(e.get("message") if isinstance(e, dict) else e) for e in (data.get("errors") or [])
    ][:20]
    return {"stats": stats, "tests": tests, "errors": errors}


def _group_key(t: dict[str, Any]) -> str:
    # Playwright her tekrara ayrı `id` verir; tekrarlar konum + başlık + projeyle eşlenir.
    parts = ("file", "line", "column", "title", "project")
    return "\x1f".join(str(t.get(p) or "") for p in parts)


def failure_groups(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tekrarlar (`--repeat-each`) birleştirilmiş, en az bir kez yeşil olmayan testler.

    `consistent`: tüm tekrarlar `unexpected` ve aynı hata türünde (ör. 3/3 assertion → defect
    adayı). Karışık sonuç (bazı tekrarlar yeşil, `flaky`, farklı türler) `consistent=false`'tur:
    kod üretimi bunu kararsızlık sayar, defect adayı demez (TEKNIK-TASARIM §8.4/§8.6).
    """
    groups: dict[str, dict[str, Any]] = {}
    for t in tests:
        key = _group_key(t)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "ids": [],
                "title": t.get("title"),
                "file": t.get("file"),
                "line": t.get("line"),
                "project": t.get("project"),
                "tags": t.get("tags", []),
                "repeats": 0,
                "statuses": {},
                "types": [],
                "failure": None,
            }
        g["repeats"] += 1
        g["ids"].append(t.get("id"))
        st = str(t.get("status") or "")
        g["statuses"][st] = g["statuses"].get(st, 0) + 1
        f = t.get("failure")
        if isinstance(f, dict):
            if f.get("type") not in g["types"]:
                g["types"].append(f.get("type"))
            if g["failure"] is None:
                g["failure"] = f
    out = []
    for g in groups.values():
        statuses = g["statuses"]
        if set(statuses) <= {"expected", "skipped"}:
            continue
        g["consistent"] = set(statuses) == {"unexpected"} and len(g["types"]) == 1
        out.append(g)
    return out


def failures_of(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Kırmızı (`unexpected`) ve kararsız (`flaky`) testlerin kısa listesi (triage girdisi)."""
    return [
        {
            "id": t.get("id"),
            "title": t["title"],
            "file": t["file"],
            "line": t["line"],
            "tags": t.get("tags", []),
            "status": t["status"],
            "repeat_index": t.get("repeat_index", 0),
            "attempts": t["attempts"],
            "attempt_results": t.get("attempt_results", []),
            "failure": t.get("failure"),
        }
        for t in tests
        if t.get("status") in ("unexpected", "flaky")
    ]


def decide_status(*, exit_code: int | None, timed_out: bool, summary: dict[str, Any] | None) -> str:
    """passed | failed | error.

    - süre aşımı, rapor yok, rapor düzeyinde hata veya hiç test koşmadıysa → error
    - beklenmeyen sonuç varsa → failed (assertion/locator; triage ayırır)
    - aksi halde çıkış kodu 0 → passed; 0 değilse → error
    """
    if timed_out or summary is None:
        return "error"
    stats = summary["stats"]
    if summary["errors"]:
        return "error"
    if stats["unexpected"] > 0:
        return "failed"
    if stats["expected"] + stats["flaky"] == 0:
        return "error"
    return "passed" if exit_code == 0 else "error"

"""Surefire JUnit XML'lerinin (Java + TestNG) özeti — 009 §2.7 (Appium, `demo-app/e2e-app`) ve
011 §2.6 (Playwright for Java, `demo-app/e2e-java`).

Çıktı, Playwright yolundaki `results.summarize()` ile AYNI biçimdedir (`{stats, tests, errors}`;
test girdisi ve `failure` alanları aynı adlarla): `failures_of`, `failure_groups`,
`decide_status`, toolchain-worker `/check` ve core aynı kodla okur. Ayrıca core'un JUnit
ayrıştırıcısı için tek, temiz bir `junit.xml` (`<testsuites>`) yazılır.

Rapor test kodunun çıktısıdır (güvenilmeyen veri): DTD/varlık bildirimi içeren belge reddedilir,
boyut sınırlıdır, yalnızca bilinen öznitelikler okunur, metinler kırpılır, kanıt yolları yalnızca
koşu dizini içindeyse döner.

**Hata türü** (`failure.type`; karar değil, girdi — `results.FAILURE_TYPES` ile aynı küme).
`ci/break-verify-app.sh` + `araclar/KirmiziDenetimi.java` anlamıyla birebir:

- `test_data`         — hazırlık (`/test/reset|break`, giriş, sepet boşaltma, token) başarısız
                        (`KirmiziDenetimi.KURULUM` kalıbı)
- `assertion`         — `<failure type="java.lang.AssertionError">` (`Bekle.dogrula`: beklenen ≠
                        görülen); kırarak doğrulamada kırmızı SAYILAN tek tür
- `locator_not_found` — `TimeoutException` "öğe görünmedi: kimlik …" ya da NoSuchElementException
- `locator_timeout`   — diğer `TimeoutException` (ör. "öğe tıklanabilir olmadı: kimlik …")
- `other`             — Appium oturumu açılamadı, beklenmeyen istisna …

**Playwright for Java (web)** — istisna `com.microsoft.playwright.*` ya da
`org.opentest4j.AssertionFailedError` (`PlaywrightAssertions.assertThat`) ise hata METNİ Playwright
sürücüsünün metnidir ("Call log: … waiting for getByTestId(\"x\")"); tür TS yoluyla aynı kural
sırasıyla çıkar (`results.classify_error` karşılığı): `test_data` → `navigation` (net::ERR_…,
`page.navigate`) → `locator_ambiguous` (strict mode violation) → `locator_not_found`
("element(s) not found") → `locator_timeout` (`TimeoutError` + "waiting for <locator>") →
`assertion` (`AssertionFailedError` / `AssertionError`) → `other`. Locator metninden testId zinciri
ve rol + ad çıkarılır (`locator_test_id`, `locator_role`, `locator_name`). Proje kendi `Bekle`
yardımcısıyla `java.lang.AssertionError` atıyorsa yukarıdaki (e2e-app) kurallar aynen geçerlidir.

Kanıt: `kanit/<Sınıf>.<metot>/{ekran.png, sayfa-kaynagi.xml}` (`altyapi/Kanit.java`) →
`evidence.screenshot`, `evidence.page_source` (+ `page_source_rel`; triage'ın erişilebilirlik
ağacı girdisi). Web + Java'da aynı dizinde `trace.zip` → `evidence.trace` (+ `trace_rel`) ve
`sayfa.html` → `evidence.page_html` (+ `page_html_rel`); olmayan dosyanın alanı `None` kalır.
"""

from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runner.results import (
    _EXPECTED_RE,
    _LOCATOR_LINE_RE,
    _NAV_RE,
    _RECEIVED_RE,
    _WAITING_RE,
    MAX_ERROR,
    MAX_FIELD,
    MAX_TESTS,
    _clip,
    _first,
    _unquote,
    parse_locator,
    safe_read_bytes,
)

MAX_XML = 32 * 1024 * 1024  # tek TEST-*.xml üst sınırı (bayt)
MAX_XML_FILES = 200
JAVA_SRC = "src/test/java"
ASSERTION = "java.lang.AssertionError"
# Playwright for Java (011 §2.6): istisna paketi ve `assertThat(...)` doğrulama hatası.
PLAYWRIGHT_PKG = "com.microsoft.playwright."
PLAYWRIGHT_ASSERTION = "org.opentest4j.AssertionFailedError"
# Sürücü metni: "Timeout 5000ms exceeded." / "Locator expected … with timeout 5000ms".
_PW_TIMEOUT_RE = re.compile(r"Timeout (\d+)\s*ms exceeded|with timeout (\d+)\s*ms")
# Java gezinme eylemleri (TS `page.goto` karşılığı `page.navigate`).
_PW_NAV_RE = re.compile(r"\bpage\.(?:navigate|reload|goBack|goForward|waitForURL):")
# PlaywrightException iletisi "Error {\n  message='<sürücü iletisi>\n  name='…" biçimindedir.
_PW_MESSAGE_RE = re.compile(r"^\s*message='(.+)$", re.M)
_PW_STRICT_RE = re.compile(r"strict mode violation: (.+?) resolved to \d+ elements")
# Java sürücüsünün locator yazımı: getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions()
# .setName("Sepete ekle")) — TS yazımını `parse_locator` çözer, bunu aşağıdaki kalıp.
_PW_ROLE_JAVA_RE = re.compile(
    r"getByRole\(\s*AriaRole\.([A-Z_]+)"
    r"(?:\s*,\s*new [\w.]+\(\)(?:\.set(?!Name\()\w+\([^()]*\))*"
    r"\.setName\(\s*\"((?:[^\"\\]|\\.)*)\"\s*\))?"
)
# KirmiziDenetimi.KURULUM birebir: AssertionError bu kalıba uyarsa kurulumdur (kırmızı sayılmaz).
_KURULUM_RE = re.compile(r"/test/|giriş başarısız|DEMOAPP_TEST_TOKEN")
# Assertion dışı istisnalarda ek hazırlık mesajları (TestVerisi): yalnızca tür ayrımı içindir;
# kırmızı denetimi zaten yalnız assertion'ı kırmızı sayar, bu yüzden referansla çelişmez.
_KURULUM_EK_RE = re.compile(r"sepet boşaltılamadı|demo API'ye ulaşılamadı")
# Bekle.dogrula: "<açıklama>: beklenen <x>, görülen <y> (N ms)"
_DOGRULA_RE = re.compile(r"beklenen <(.*?)>, görülen <(.*?)> \((\d+) ms\)", re.S)
# Ekran.ad(): "'kimlik'" ya da "'kapsayıcı' içinde 'kimlik'"
_KIMLIK_RE = re.compile(r"kimlik '([^']{1,200})'(?: içinde '([^']{1,200})')?")
_ILK_KIMLIK_RE = re.compile(r"^'([^']{1,200})' ")
_SURE_RE = re.compile(r"tried for (\d+) second")
# Yığın satırı: "at com.antreklabs.bayi.ekranlar.SepetEkrani.dogrulaToplam(SepetEkrani.java:45)"
_FRAME_RE = re.compile(
    r"^\s*at ((?:[A-Za-z_$][\w$]*\.)+)[A-Za-z_$<>][\w$<>]*\(([A-Za-z_$][\w$]*\.java):(\d+)\)", re.M
)
_PKG = "com/antreklabs/bayi/"


class SurefireError(ValueError):
    """JUnit XML okunamadı / güvenilmez biçim."""


def _no_dtd(data: bytes) -> None:
    """DTD/varlık bildirimi reddedilir (core `parse._dtd_yok` gibi: expat ön tarama)."""
    from xml.parsers import expat

    class _Dtd(Exception):
        pass

    def _reject(*_a: Any) -> None:
        raise _Dtd

    p = expat.ParserCreate()
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    p.StartDoctypeDeclHandler = _reject
    p.EntityDeclHandler = _reject
    p.UnparsedEntityDeclHandler = _reject
    p.ExternalEntityRefHandler = _reject
    try:
        p.Parse(data, True)
    except _Dtd as exc:
        raise SurefireError("JUnit XML DTD/varlık bildirimi içeremez") from exc
    except (expat.ExpatError, ValueError, LookupError) as exc:
        raise SurefireError(f"JUnit XML ayrıştırılamadı: {exc}") from exc


def parse_xml(path: Path) -> ET.Element:
    data = safe_read_bytes(path, MAX_XML)
    _no_dtd(data)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise SurefireError(f"{path.name} ayrıştırılamadı: {exc}") from exc


@dataclass(frozen=True)
class Repeat:
    """Bir tekrarın (`--repeat-each` karşılığı) rapor ve kanıt dizinleri."""

    index: int
    reports_dir: Path
    kanit_dir: Path


def _src_file(classname: str) -> str:
    """`com.antreklabs.bayi.x.YTest` → `src/test/java/com/antreklabs/bayi/x/YTest.java`."""
    outer = classname.split("$", 1)[0]
    if not re.fullmatch(r"(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*", outer):
        return _clip(outer, MAX_FIELD)
    return f"{JAVA_SRC}/{outer.replace('.', '/')}.java"


def _frames(text: str) -> list[dict[str, Any]]:
    out = []
    for m in _FRAME_RE.finditer(text):
        pkg = m.group(1).rstrip(".").rsplit(".", 1)[0] if m.group(1).count(".") > 1 else ""
        # Sınıf adı paketin son öğesidir; dosya adı yığından gelir.
        rel = f"{JAVA_SRC}/{pkg.replace('.', '/')}/{m.group(2)}" if pkg else m.group(2)
        if _PKG not in rel:
            continue  # yalnızca projenin kendi kodu (Selenium/TestNG çerçeveleri atlanır)
        out.append({"file": rel, "line": int(m.group(3)), "column": 0})
    return out


def classify(tag: str, exc_type: str, message: str, body: str) -> dict[str, Any]:
    """Tek bir `<failure|error>` → biçimsel tür + çıkarılan alanlar (bkz. modül belgesi)."""
    if exc_type.startswith(PLAYWRIGHT_PKG) or exc_type == PLAYWRIGHT_ASSERTION:
        return _classify_playwright(exc_type, message, body)
    text = f"{message}\n{body}"
    signals: list[str] = []
    expected = received = None
    timeout_ms: int | None = None
    kimlik = kapsam = None
    m = _KIMLIK_RE.search(message)
    if m:
        # "kimlik 'kart' içinde 'düğme'" → aranan düğme, kapsam kart.
        kimlik, kapsam = (m.group(2), m.group(1)) if m.group(2) else (m.group(1), None)
    elif (m2 := _ILK_KIMLIK_RE.match(message)) is not None:
        kimlik = m2.group(1)
    d = _DOGRULA_RE.search(message)
    if d:
        expected, received = _clip(d.group(1), MAX_FIELD), _clip(d.group(2), MAX_FIELD)
        timeout_ms = int(d.group(3))
    elif (s := _SURE_RE.search(text)) is not None:
        timeout_ms = int(s.group(1)) * 1000

    simple = exc_type.rsplit(".", 1)[-1]
    is_assertion = tag == "failure" and exc_type == ASSERTION
    if _KURULUM_RE.search(message) or (not is_assertion and _KURULUM_EK_RE.search(message)):
        kind = "test_data"
        signals.append("veri hazırlığı (/test/*, giriş) başarısız")
    elif is_assertion:
        kind = "assertion"
        signals.append("beklenen ≠ gerçekleşen")
        if received == "(öğe yok)":
            signals.append("görülen: öğe yok")
    elif simple == "NoSuchElementException" or (
        simple == "TimeoutException" and "öğe görünmedi" in message
    ):
        kind = "locator_not_found"
        signals.append("öğe bulunamadı")
    elif simple == "TimeoutException":
        kind = "locator_timeout"
        signals.append("eylem ön koşulu beklenirken zaman aşımı")
    else:
        kind = "other"
        if simple == "SessionNotCreatedException" or "Could not start a new session" in text:
            signals.append("Appium oturumu açılamadı")
    first = next((ln.strip() for ln in message.splitlines() if ln.strip()), "") or simple
    return {
        "type": kind,
        "first_line": _clip(first, MAX_FIELD),
        "matcher": None,
        "action": None,
        "exception": _clip(exc_type, 200) or None,
        "locator": _clip(m.group(0), MAX_FIELD) if m else None,
        "locator_test_ids": [x for x in (kapsam, kimlik) if x],
        "locator_test_id": kimlik,
        "locator_scope_test_id": kapsam,
        "locator_role": None,
        "locator_name": None,
        "expected": expected,
        "received": received,
        "timeout_ms": timeout_ms,
        "signals": signals,
    }


def _classify_playwright(exc_type: str, message: str, body: str) -> dict[str, Any]:
    """Playwright for Java hatası: TS yolundaki `results.classify_error` ile aynı kural sırası."""
    text = f"{message}\n{body}"
    simple = exc_type.rsplit(".", 1)[-1]
    signals: list[str] = []
    locator = (
        _first(_LOCATOR_LINE_RE, text) or _first(_WAITING_RE, text) or _first(_PW_STRICT_RE, text)
    )
    ids = parse_locator(locator)
    role = _PW_ROLE_JAVA_RE.search(locator or "")
    if role and ids["locator_role"] is None:
        # Zincirin sonu rol + adsa aranan eleman odur; testId (varsa) kapsayıcıdır.
        if ids["locator_test_id"] and (locator or "").rfind("getByTestId") < role.start():
            ids["locator_scope_test_id"], ids["locator_test_id"] = ids["locator_test_id"], None
        if ids["locator_test_id"] is None:
            ids["locator_role"] = _clip(role.group(1).lower(), 40)
            name = _unquote(None, role.group(2)) if role.group(2) is not None else None
            ids["locator_name"] = _clip(name, 200) if name is not None else None
    expected = _first(_EXPECTED_RE, text)
    received = _first(_RECEIVED_RE, text)
    tm = _PW_TIMEOUT_RE.search(text)
    timeout_ms = int(next(g for g in tm.groups() if g)) if tm else None
    action_m = re.search(r"\b((?:locator|page|frame)\.[A-Za-z]+):", message)
    action = action_m.group(1) if action_m else None
    is_assertion = exc_type == PLAYWRIGHT_ASSERTION
    if _KURULUM_RE.search(message) or _KURULUM_EK_RE.search(message):
        kind = "test_data"
        signals.append("veri hazırlığı (/test/*, giriş) başarısız")
    elif _NAV_RE.search(text) or _PW_NAV_RE.search(message):
        kind = "navigation"
        signals.append("sayfa yüklenemedi / gezinme hatası")
    elif "strict mode violation" in text:
        kind = "locator_ambiguous"
        signals.append("strict mode: locator birden çok elemana çözüldü")
    elif "element(s) not found" in text:
        kind = "locator_not_found"
        signals.append("element(s) not found")
    elif simple == "TimeoutError" and _WAITING_RE.search(text):
        kind = "locator_timeout"
        signals.append(f"{action or 'eylem'}: locator beklenirken zaman aşımı")
    elif is_assertion:
        kind = "assertion"
        signals.append("beklenen ≠ gerçekleşen")
    else:
        kind = "other"
        if "Executable doesn't exist" in text or "Failed to launch" in text:
            signals.append("tarayıcı başlatılamadı")
    first = (
        _first(_PW_MESSAGE_RE, message)
        or next((ln.strip() for ln in message.splitlines() if ln.strip()), "")
        or simple
    )
    return {
        "type": kind,
        "first_line": _clip(first, MAX_FIELD),
        "matcher": None,
        "action": action,
        "exception": _clip(exc_type, 200) or None,
        "locator": _clip(locator, MAX_FIELD) if locator else None,
        **ids,
        "expected": _clip(expected, MAX_FIELD) if expected is not None else None,
        "received": _clip(received, MAX_FIELD) if received is not None else None,
        "timeout_ms": timeout_ms,
        "signals": signals,
    }


def _evidence(kanit_dir: Path, simple_class: str, method: str, rel_root: Path | None) -> dict:
    """`Kanit.dizin` adlandırması: `[^A-Za-z0-9._-]` → `_`."""
    ad = re.sub(r"[^A-Za-z0-9._-]", "_", f"{simple_class}.{method}")
    base = kanit_dir / ad
    out: dict[str, Any] = {"trace": None, "error_context": None, "screenshot": None, "video": None}
    for key, name in (
        ("screenshot", "ekran.png"),
        ("page_source", "sayfa-kaynagi.xml"),
        # Web + Java (Playwright for Java): iz ve sayfanın HTML'i.
        ("trace", "trace.zip"),
        ("page_html", "sayfa.html"),
    ):
        p = base / name
        ok = False
        try:
            # Test kodu kanıt dizinini (ya da alt dizinini) bağla dışarı yöneltebilir: kanıt
            # yolunda bağ olmamalı; ayrıca artefakt kökü içinde kalmalı (aşağıda rel_root).
            ok = (
                p.is_file()
                and not any(x.is_symlink() for x in (kanit_dir, base, p))
                and kanit_dir.resolve() in p.resolve().parents
            )
        except OSError:
            ok = False
        rel = None
        if ok and rel_root is not None:
            try:
                rel = str(p.resolve().relative_to(rel_root.resolve()))
            except ValueError:
                ok = False  # artefakt kökü dışında: kanıt sayılmaz
        out[key] = {"path": str(p), "rel": rel, "exists": True} if ok else None
    return out


def _result_child(tc: ET.Element) -> ET.Element | None:
    for child in tc:
        if child.tag in ("failure", "error", "skipped"):
            return child
    return None


def _testcases(reports_dir: Path) -> tuple[list[ET.Element], list[str]]:
    errors: list[str] = []
    cases: list[ET.Element] = []
    if not reports_dir.is_dir() or reports_dir.is_symlink():
        return cases, ["Surefire rapor dizini yok"]
    files = sorted(reports_dir.glob("TEST-*.xml"))[:MAX_XML_FILES]
    if not files:
        return cases, ["Surefire JUnit XML'i (TEST-*.xml) üretilmedi"]
    for f in files:
        try:
            root = parse_xml(f)
        except (OSError, ValueError) as exc:
            errors.append(_clip(f"{f.name}: {exc}", MAX_ERROR))
            continue
        cases.extend(root.iter("testcase"))
    return cases, errors


def summarize(
    repeats: list[Repeat], *, project: str, rel_root: Path | None = None
) -> dict[str, Any]:
    """Tekrarların Surefire raporları → `{stats, tests, errors}` (results.summarize biçimi)."""
    tests: list[dict[str, Any]] = []
    errors: list[str] = []
    stats = {"expected": 0, "unexpected": 0, "flaky": 0, "skipped": 0, "duration_ms": 0}
    for rep in repeats:
        cases, errs = _testcases(rep.reports_dir)
        errors += [f"tekrar {rep.index + 1}: {e}" if len(repeats) > 1 else e for e in errs]
        seen_ids: dict[str, int] = {}  # aynı metodun birden çok çağrısı (data provider)
        for tc in cases:
            if len(tests) >= MAX_TESTS:
                break
            classname = _clip(tc.get("classname"), MAX_FIELD)
            method = _clip(tc.get("name"), MAX_FIELD)
            simple = classname.rsplit(".", 1)[-1]
            try:
                duration = int(float(tc.get("time") or 0) * 1000)
            except ValueError:
                duration = 0
            child = _result_child(tc)
            status, error, failure, kind = "expected", None, None, None
            if child is not None and child.tag == "skipped":
                status = "skipped"
            elif child is not None:
                status = "unexpected"
                exc_type = _clip(child.get("type"), 200)
                message = _clip(child.get("message"), MAX_ERROR)
                body = _clip((child.text or "").strip(), 8000)
                info = classify(child.tag, exc_type, message, body)
                frames = _frames(body)
                src = _src_file(classname)
                test_loc = next((f for f in frames if f["file"] == src), None)
                screen_loc = next((f for f in frames if "/ekranlar/" in f["file"]), None)
                evidence = _evidence(rep.kanit_dir, simple, method, rel_root)
                page_source = evidence.get("page_source")
                error = message or exc_type
                kind = info["type"]
                failure = {
                    **info,
                    "message": _clip(message or exc_type),
                    "messages": [],
                    "location": screen_loc or test_loc,
                    "test_location": test_loc,
                    "step": None,
                    "attempt": 0,
                    "status": "failed",
                    "evidence": evidence,
                    # Uygulamada aria snapshot yoktur; erişilebilirlik ağacı sayfa kaynağı XML'idir.
                    "aria_snapshot": None,
                    "aria_snapshot_scope": None,
                    "aria_snapshot_rel": None,
                    "page_source_rel": (page_source or {}).get("rel"),
                    "page_html_rel": (evidence.get("page_html") or {}).get("rel"),
                    "trace_rel": (evidence.get("trace") or {}).get("rel"),
                    "page_location": screen_loc,
                }
            stats[status] += 1
            stats["duration_ms"] += duration
            file = _src_file(classname)
            title = f"{simple} › {method}"
            base_id = f"{classname}.{method}#{rep.index}"
            n = seen_ids.get(base_id, 0)
            seen_ids[base_id] = n + 1
            tests.append(
                {
                    "id": _clip(base_id + (f".{n}" if n else ""), 200),
                    "title": title,
                    "file": file,
                    "line": 0,
                    "column": 0,
                    "project": project,
                    "status": status,
                    "tags": [],
                    "attempts": 1,
                    "attempt_results": [
                        {
                            "retry": 0,
                            "status": {"expected": "passed", "unexpected": "failed"}.get(
                                status, status
                            ),
                            "duration_ms": duration,
                            "type": kind,
                        }
                    ],
                    "duration_ms": duration,
                    "error": error,
                    "failure": failure,
                    "attachments": [],
                    "repeat_index": rep.index,
                }
            )
    return {"stats": stats, "tests": tests, "errors": errors[:20]}


def write_junit(repeats: list[Repeat], out: Path, name: str = "e2e-app") -> int:
    """Tüm tekrarların `<testcase>`'lerini tek `<testsuites>` belgesine yazar (core JUnit girdisi).

    Yalnızca bilinen öznitelikler ve ilk sonuç öğesi (mesaj + kırpılmış metin) taşınır;
    `<properties>`, `system-out/err` atılır. Dönen: yazılan test sayısı.
    """
    root = ET.Element("testsuites", {"name": name})
    n = 0
    for rep in repeats:
        cases, _errs = _testcases(rep.reports_dir)
        suite = ET.SubElement(
            root,
            "testsuite",
            {"name": f"tekrar-{rep.index + 1}" if len(repeats) > 1 else name},
        )
        for tc in cases:
            if n >= MAX_TESTS:
                break
            attrs = {
                k: _clip(tc.get(k), MAX_FIELD) for k in ("classname", "name", "time") if tc.get(k)
            }
            new = ET.SubElement(suite, "testcase", attrs)
            child = _result_child(tc)
            if child is not None:
                c = ET.SubElement(
                    new,
                    child.tag,
                    {
                        k: _clip(child.get(k), MAX_ERROR)
                        for k in ("type", "message")
                        if child.get(k)
                    },
                )
                c.text = _clip((child.text or "").strip(), 8000) or None
            n += 1
        suite.set("tests", str(len(suite)))
    out.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp (O_EXCL) + rename: önceden konmuş bir bağ (symlink) üzerinden başka yere yazılmaz.
    fd, tmp = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            ET.ElementTree(root).write(fh, encoding="utf-8", xml_declaration=True)
        os.chmod(tmp, 0o644)
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return n

#!/usr/bin/env python3
"""xcresult → JUnit XML (TP müşteri CI şablonu, iOS XCUITest; üçüncü taraf bağımlılığı yok).

Kaynak: testing-probe `rules/ci-sablonlari/xcresult_junit.py`. Kurulum PR'ıyla müşteri deposuna
`.github/tp/xcresult_junit.py` olarak girer; `ios-xcuitest.yml` iş akışı koşu sonunda çağırır.

    python3 xcresult_junit.py --xcresult TestResults.xcresult \
        --cikti tp-results/junit/xcresult-junit.xml [--ekler tp-results/ekler]
    python3 xcresult_junit.py --json test-results.json --cikti junit.xml   # xcrun'suz (test)

Girdi: `xcrun xcresulttool get test-results tests --path <xcresult> --format json` (Xcode 16+).
Düğüm türleri: Test Plan → Unit/UI test bundle → Test Suite → Test Case (+ Failure Message,
Repetition, Device …). Sonuçlar: Passed, Failed, Skipped, Expected Failure.

Çıkış kodu: 0 (rapor yazıldı ya da xcresult yok: derleme hatası iş akışının kendi adımında
görünür); `--siki` verilirse xcresult okunamadığında 2.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

TEST_CASE = "Test Case"
SUITE_TURLERI = ("Test Suite",)
BUNDLE_TURLERI = ("UI test bundle", "Unit test bundle", "Test Target")
HATA_TURLERI = ("Failure Message",)
MAX_MESAJ = 2000
_SURE_RE = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+(?:\.\d+)?)\s*m(?!s))?\s*"
    r"(?:(\d+(?:\.\d+)?)\s*s)?\s*(?:(\d+(?:\.\d+)?)\s*ms)?"
)
_KONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sure_saniye(dugum: dict[str, Any]) -> float:
    """`durationInSeconds` (sayı) ya da `duration` ("1.2s", "1m 3s", "250ms")."""
    sn = dugum.get("durationInSeconds")
    if isinstance(sn, (int, float)) and sn >= 0:
        return float(sn)
    metin = dugum.get("duration")
    if not isinstance(metin, str) or not metin.strip():
        return 0.0
    metin = metin.strip().replace(",", ".")
    try:
        return max(0.0, float(metin))
    except ValueError:
        pass
    m = _SURE_RE.fullmatch(metin)
    if not m or not any(m.groups()):
        return 0.0
    h, dk, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + dk * 60 + s + ms / 1000


def _temiz(metin: Any) -> str:
    s = _KONTROL_RE.sub("", str(metin or ""))
    return s if len(s) <= MAX_MESAJ else s[:MAX_MESAJ] + "…"


def _test_adi(ad: str) -> str:
    return ad[:-2] if ad.endswith("()") else ad


def testleri_topla(veri: dict[str, Any]) -> list[dict[str, Any]]:
    """`get test-results tests` JSON'u → [{suite, classname, name, sonuc, sure, mesajlar}]."""
    out: list[dict[str, Any]] = []

    def gez(dugum: Any, bundle: str | None, suite: str | None) -> None:
        if not isinstance(dugum, dict):
            return
        tur = dugum.get("nodeType")
        ad = str(dugum.get("name") or "")
        if tur in BUNDLE_TURLERI:
            bundle = ad or bundle
        elif tur in SUITE_TURLERI:
            suite = ad or suite
        if tur == TEST_CASE:
            mesajlar = [
                _temiz(c.get("name"))
                for c in dugum.get("children") or []
                if isinstance(c, dict) and c.get("nodeType") in HATA_TURLERI
            ]
            kimlik = str(dugum.get("nodeIdentifier") or "")
            s = suite or (kimlik.split("/", 1)[0] if "/" in kimlik else "") or "XCUITest"
            out.append(
                {
                    "suite": s,
                    "classname": f"{bundle}.{s}" if bundle else s,
                    "name": _test_adi(ad),
                    "sonuc": str(dugum.get("result") or ""),
                    "sure": sure_saniye(dugum),
                    "mesajlar": mesajlar,
                }
            )
            return
        for c in dugum.get("children") or []:
            gez(c, bundle, suite)

    for kok in veri.get("testNodes") or []:
        gez(kok, None, None)
    return out


def junit_xml(testler: list[dict[str, Any]]) -> bytes:
    kok = ET.Element("testsuites", {"name": "xcresult"})
    gruplar: dict[str, list[dict[str, Any]]] = {}
    for t in testler:
        gruplar.setdefault(t["classname"], []).append(t)
    for classname, grup in gruplar.items():
        hata = sum(1 for t in grup if t["sonuc"] == "Failed")
        atla = sum(1 for t in grup if t["sonuc"] == "Skipped")
        suite = ET.SubElement(
            kok,
            "testsuite",
            {
                "name": classname,
                "tests": str(len(grup)),
                "failures": str(hata),
                "skipped": str(atla),
                "errors": "0",
                "time": f"{sum(t['sure'] for t in grup):.3f}",
            },
        )
        for t in grup:
            tc = ET.SubElement(
                suite,
                "testcase",
                {"classname": classname, "name": t["name"], "time": f"{t['sure']:.3f}"},
            )
            if t["sonuc"] == "Failed":
                mesaj = t["mesajlar"][0] if t["mesajlar"] else "XCUITest başarısız"
                f = ET.SubElement(tc, "failure", {"message": mesaj})
                f.text = "\n".join(t["mesajlar"]) or mesaj
            elif t["sonuc"] == "Skipped":
                ET.SubElement(tc, "skipped")
            # "Expected Failure" ve "Passed" → geçti
    return ET.tostring(kok, encoding="utf-8", xml_declaration=True)


def _xcresulttool(*arglar: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["xcrun", "xcresulttool", *arglar], capture_output=True, text=True, check=False
    )


def xcresult_json(yol: Path) -> dict[str, Any]:
    r = _xcresulttool("get", "test-results", "tests", "--path", str(yol), "--format", "json")
    if r.returncode != 0:
        raise RuntimeError(f"xcresulttool başarısız ({r.returncode}): {r.stderr.strip()[:500]}")
    veri = json.loads(r.stdout)
    if not isinstance(veri, dict):
        raise RuntimeError("xcresulttool çıktısı nesne değil")
    return veri


def ekleri_cikar(yol: Path, hedef: Path) -> str | None:
    """`xcresulttool export attachments` (Xcode 16+); hata uyarıdır."""
    hedef.mkdir(parents=True, exist_ok=True)
    r = _xcresulttool("export", "attachments", "--path", str(yol), "--output-path", str(hedef))
    return None if r.returncode == 0 else f"ekler alınamadı: {r.stderr.strip()[:300]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    kaynak = ap.add_mutually_exclusive_group(required=True)
    kaynak.add_argument("--xcresult", type=Path)
    kaynak.add_argument("--json", type=Path, help="önceden alınmış test-results JSON'u")
    ap.add_argument("--cikti", type=Path, required=True)
    ap.add_argument("--ekler", type=Path)
    ap.add_argument("--siki", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.json is not None:
            veri = json.loads(a.json.read_text(encoding="utf-8"))
        else:
            if not a.xcresult.exists():
                print(f"xcresult yok: {a.xcresult} (derleme hatası?)", file=sys.stderr)
                return 2 if a.siki else 0
            veri = xcresult_json(a.xcresult)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"xcresult okunamadı: {exc}", file=sys.stderr)
        return 2 if a.siki else 0
    testler = testleri_topla(veri if isinstance(veri, dict) else {})
    a.cikti.parent.mkdir(parents=True, exist_ok=True)
    a.cikti.write_bytes(junit_xml(testler))
    gecen = sum(1 for t in testler if t["sonuc"] in ("Passed", "Expected Failure"))
    print(f"{len(testler)} test, {gecen} geçti → {a.cikti}")
    if a.ekler is not None and a.xcresult is not None:
        uyari = ekleri_cikar(a.xcresult, a.ekler)
        if uyari:
            print(uyari, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

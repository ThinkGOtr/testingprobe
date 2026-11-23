#!/usr/bin/env python3
"""Sauce Labs elle turunun (.github/workflows/sauce-demo.yml) platform özetleri ve toplam kayıt.

AI yok; yalnız stdlib. Çekirdek `sauce-results` artefaktının kökündeki `sauce.json`'u (job_url,
durum, neden, platformlar[]) ve `junit.xml`'i okur (core `ci/service.py` `_sauce_bilgisi`).

Alt komutlar:
  web    --out DIR --report saucectl-report.json --junit saucectl-junit.xml [--log saucectl.log]
         [--exit-code N] [--region R] [--neden-altyapi "..."]
         saucectl suite'leri → her suite bir satır (ad "Windows-11-Edge" → etiket "Windows 11 · Edge").
  mobil  --out DIR --platform android|ios --etiket "Android · emülatör" --surefire DIR
         --oturumlar oturumlar.jsonl [--exit-code N] [--region R] [--neden-altyapi "..."]
  atla   --out DIR --neden "..."            (tur bu tetikte / kimliksiz koşmaz)
  topla  --girdi DIR [--girdi DIR ...] --out DIR [--kota-once JSON] [--kota-sonra JSON]
         platform dizinlerini (her biri platformlar.json + junit*.xml) sauce.json + junit.xml +
         ci-meta.json olarak birleştirir; GitHub adım özetine tablo yazar.

Platform kaydı: {anahtar, platform, etiket, durum: passed|failed|error|atlandi, neden,
  toplam, gecen, basarisiz, atlanan, isler: [{ad, url, durum}]}
Sauce iş sayfası (app.<bölge>.saucelabs.com/tests/<id>) video + log barındırır.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

URL_RE = re.compile(r"^https://app\.([a-z0-9-]+\.)*saucelabs\.com/tests/[A-Za-z0-9]+$")
OTURUM_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
BOLGE_RE = re.compile(r"^[a-z0-9-]{1,30}$")
DURUMLAR = ("passed", "failed", "error", "atlandi")
MAX_JUNIT = 5 * 1024 * 1024


def _yaz(yol: Path, veri: object) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _kisalt(s: object, n: int = 200) -> str | None:
    if s is None:
        return None
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s)).strip()
    return t[:n] or None


def etiket_suite(ad: str) -> str:
    """`Windows-11-Edge` → `Windows 11 · Edge` (son parça tarayıcı, kalanı işletim sistemi)."""
    parcalar = [p for p in re.split(r"[-_]+", ad or "") if p]
    if len(parcalar) < 2:
        return ad or "web"
    return " ".join(parcalar[:-1]) + " · " + parcalar[-1]


def anahtar(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "platform"


def _junit_kok(yol: Path) -> ET.Element | None:
    try:
        if not yol.is_file() or yol.is_symlink() or yol.stat().st_size > MAX_JUNIT:
            return None
        veri = yol.read_bytes()
        if b"<!doctype" in veri[:4096].lower() or b"<!entity" in veri.lower():
            return None
        return ET.fromstring(veri)
    except (OSError, ET.ParseError):
        return None


def _sayilar(testcaseler: list[ET.Element]) -> dict[str, int]:
    s = {"toplam": 0, "gecen": 0, "basarisiz": 0, "atlanan": 0}
    for tc in testcaseler:
        s["toplam"] += 1
        etiketler = {c.tag for c in tc}
        if etiketler & {"failure", "error"}:
            s["basarisiz"] += 1
        elif "skipped" in etiketler:
            s["atlanan"] += 1
        else:
            s["gecen"] += 1
    return s


def _isler_raporundan(rapor: Path) -> list[dict]:
    """saucectl JSON raporundaki Sauce işleri (url + ad + durum)."""
    try:
        veri = json.loads(rapor.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[dict] = []

    def gez(x: object, d: int = 0) -> None:
        if d > 8:
            return
        if isinstance(x, dict):
            url = x.get("url")
            if isinstance(url, str) and URL_RE.fullmatch(url):
                out.append(
                    {
                        "ad": _kisalt(x.get("name") or x.get("suiteName"), 120),
                        "url": url,
                        "durum": _kisalt(x.get("status"), 30),
                    }
                )
            for v in x.values():
                gez(v, d + 1)
        elif isinstance(x, list):
            for v in x[:200]:
                gez(v, d + 1)

    gez(veri)
    goruldu: set[str] = set()
    return [i for i in out if not (i["url"] in goruldu or goruldu.add(i["url"]))]


def _durum(isler_durumlari: list[str | None], sayi: dict[str, int], exit_code: str | None) -> str:
    """Satırın kendi kanıtı (Sauce iş durumu, JUnit) önceliklidir: saucectl'in TEK çıkış kodu tüm
    suite'lere aittir, bir suite'in kırmızısı ötekini kırmızıya boyamamalı."""
    if sayi["basarisiz"] > 0:
        return "failed"
    kotu = [d for d in isler_durumlari if d and d.lower() not in ("passed", "complete", "completed")]
    if kotu:
        return "failed"
    if sayi["toplam"] > 0 and any(d for d in isler_durumlari):
        return "passed"
    if exit_code not in (None, "", "0"):
        return "failed" if sayi["toplam"] > 0 else "error"
    if sayi["toplam"] == 0:
        return "error"
    return "passed"


def _junit_kopyala(kok: ET.Element, hedef: Path, etiket: str, suite_adi: str | None = None) -> list[ET.Element]:
    """Testcase'leri `[etiket] ad` adıyla tek <testsuite>'e yazar (aynı test farklı platformda ayrı satır)."""
    tclar: list[ET.Element] = []
    suiteler = [kok] if kok.tag == "testsuite" else list(kok.iter("testsuite"))
    for ts in suiteler:
        if suite_adi is not None and suite_adi not in (ts.get("name") or ""):
            continue
        tclar.extend(ts.iter("testcase"))
    if suite_adi is not None and not tclar and len(suiteler) == 1:
        tclar = list(kok.iter("testcase"))
    yeni = ET.Element("testsuite", {"name": etiket})
    for tc in tclar:
        k = ET.SubElement(yeni, "testcase", {
            "name": f"[{etiket}] {tc.get('name') or ''}"[:300],
            "classname": (tc.get("classname") or "")[:300],
            "time": tc.get("time") or "0",
        })
        for c in tc:
            if c.tag in ("failure", "error", "skipped"):
                cc = ET.SubElement(k, c.tag, {"message": (c.get("message") or "")[:2000]})
                cc.text = (c.text or "")[:4000]
    s = _sayilar(tclar)
    yeni.set("tests", str(s["toplam"]))
    yeni.set("failures", str(s["basarisiz"]))
    yeni.set("skipped", str(s["atlanan"]))
    hedef.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(yeni).write(hedef, encoding="utf-8", xml_declaration=True)
    return tclar


def komut_web(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    isler = _isler_raporundan(Path(a.report)) if a.report else []
    if not isler and a.log and Path(a.log).is_file():
        for u in sorted(set(re.findall(r"https://app\.(?:[a-z0-9-]+\.)*saucelabs\.com/tests/[A-Za-z0-9]+",
                                       Path(a.log).read_text(encoding="utf-8", errors="replace")))):
            isler.append({"ad": None, "url": u, "durum": None})
    kok = _junit_kok(Path(a.junit)) if a.junit else None
    # Suite adları: rapordaki işler, yoksa JUnit testsuite adları, yoksa yapılandırmadaki adlar.
    adlar = [i["ad"] for i in isler if i.get("ad")]
    if not adlar and kok is not None:
        adlar = [ts.get("name") for ts in kok.iter("testsuite") if ts.get("name")]
    if not adlar:
        adlar = [s for s in (a.suite or [])]
    platformlar = []
    for i, ad in enumerate(dict.fromkeys(adlar)):
        etiket = etiket_suite(ad)
        ilgili = [j for j in isler if j.get("ad") == ad]
        tclar = (
            _junit_kopyala(kok, out / f"junit-{i}.xml", etiket, ad) if kok is not None else []
        )
        s = _sayilar(tclar)
        durum = _durum([j.get("durum") for j in ilgili], s, a.exit_code)
        neden = None
        if durum == "error":
            neden = _kisalt(a.neden_altyapi) or (
                "Sauce işi oluşmadı ya da sonuç okunamadı (tünel/kimlik/kota; saucectl.log)"
                if not ilgili else "Sauce işinin test sonucu okunamadı"
            )
        platformlar.append({
            "anahtar": "web-" + anahtar(ad), "platform": "web", "etiket": etiket, "durum": durum,
            "neden": neden, **s,
            "isler": [{"ad": j.get("ad") or ad, "url": j["url"], "durum": j.get("durum")} for j in ilgili],
        })
    if not platformlar:
        platformlar.append({
            "anahtar": "web", "platform": "web", "etiket": "Web", "durum": "error",
            "neden": _kisalt(a.neden_altyapi) or "saucectl çalışmadı ya da sonuç yok (saucectl.log)",
            "toplam": 0, "gecen": 0, "basarisiz": 0, "atlanan": 0, "isler": [],
        })
    _yaz(out / "platformlar.json", platformlar)
    return 0


def komut_mobil(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bolge = a.region if a.region and BOLGE_RE.fullmatch(a.region) else "us-west-1"
    isler = []
    if a.oturumlar and Path(a.oturumlar).is_file():
        for satir in Path(a.oturumlar).read_text(encoding="utf-8").splitlines()[:50]:
            try:
                k = json.loads(satir)
            except ValueError:
                continue
            oturum = str(k.get("oturum") or "")
            if not OTURUM_RE.fullmatch(oturum):
                continue
            url = f"https://app.{bolge}.saucelabs.com/tests/{oturum.replace('-', '')}"
            if URL_RE.fullmatch(url):
                isler.append({"ad": _kisalt(k.get("test"), 120), "url": url,
                              "durum": k.get("durum") if k.get("durum") in ("passed", "failed") else None})
    tclar: list[ET.Element] = []
    birlesik = ET.Element("testsuites")
    if a.surefire and Path(a.surefire).is_dir():
        for f in sorted(Path(a.surefire).glob("TEST-*.xml"))[:50]:
            k = _junit_kok(f)
            if k is not None:
                birlesik.append(k)
    if len(birlesik):
        tclar = _junit_kopyala(birlesik, out / "junit-0.xml", a.etiket)
    s = _sayilar(tclar)
    durum = _durum([i.get("durum") for i in isler], s, a.exit_code)
    neden = None
    if durum == "error":
        neden = _kisalt(a.neden_altyapi) or "Sauce oturumu açılamadı ya da test sonucu yok (run-app-checks.log)"
    _yaz(out / "platformlar.json", [{
        "anahtar": a.platform, "platform": a.platform, "etiket": a.etiket, "durum": durum,
        "neden": neden, **s, "isler": isler,
    }])
    return 0


def komut_atla(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    _yaz(out / "sauce.json", {
        "schema_version": 2, "kaynak": "sauce", "tur": "elle", "durum": "atlandi",
        "neden": _kisalt(a.neden, 300), "job_url": None, "platformlar": [],
    })
    ozet = f"### Sauce Labs turu\n\nAtlandı: {_kisalt(a.neden, 300)}\n"
    _ozet_yaz(ozet)
    return 0


def _ozet_yaz(metin: str) -> None:
    yol = os.environ.get("GITHUB_STEP_SUMMARY")
    if yol:
        with open(yol, "a", encoding="utf-8") as f:
            f.write(metin)
    else:
        sys.stdout.write(metin)


def _kota(ham: str | None) -> dict | None:
    if not ham:
        return None
    try:
        k = json.loads(ham)
    except ValueError:
        return None
    if not isinstance(k, dict):
        return None
    return {str(x)[:40]: v for x, v in list(k.items())[:20] if isinstance(v, (int, float)) or v is None}


def komut_topla(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    platformlar: list[dict] = []
    birlesik = ET.Element("testsuites")
    for d in a.girdi or []:
        dp = Path(d)
        pj = dp / "platformlar.json"
        try:
            liste = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in liste if isinstance(liste, list) else []:
            if not isinstance(p, dict) or p.get("durum") not in DURUMLAR:
                continue
            p["isler"] = [
                i for i in (p.get("isler") or [])
                if isinstance(i, dict) and isinstance(i.get("url"), str) and URL_RE.fullmatch(i["url"])
            ][:20]
            platformlar.append(p)
        for jf in sorted(dp.glob("junit-*.xml")):
            k = _junit_kok(jf)
            if k is not None:
                birlesik.append(k)
    beklenen = [s.strip() for s in (a.beklenen or "").split(",") if s.strip()]
    for b in beklenen:
        if not any(p.get("platform") == b for p in platformlar):
            platformlar.append({
                "anahtar": b, "platform": b, "etiket": {"android": "Android · emülatör",
                                                       "ios": "iOS · simülatör"}.get(b, b),
                "durum": "error", "neden": "Platform işi sonuç bırakmadı (derleme ya da altyapı adımı başarısız)",
                "toplam": 0, "gecen": 0, "basarisiz": 0, "atlanan": 0, "isler": [],
            })
    sira = {"web": 0, "android": 1, "ios": 2}
    platformlar.sort(key=lambda p: (sira.get(p.get("platform"), 9), p.get("etiket") or ""))
    durumlar = [p["durum"] for p in platformlar]
    if not platformlar:
        durum, neden = "error", "Hiçbir platform sonucu yok"
    elif "failed" in durumlar:
        durum, neden = "failed", None
    elif "error" in durumlar:
        durum = "error"
        neden = "Koşmayan platform: " + ", ".join(p["etiket"] for p in platformlar if p["durum"] == "error")
    else:
        durum, neden = "passed", None
    ET.ElementTree(birlesik).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
    ilk = next((i["url"] for p in platformlar for i in p["isler"]), None)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, run_id = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    kayit = {
        "schema_version": 2, "kaynak": "sauce", "tur": "elle", "durum": durum, "neden": neden,
        "tetik": os.environ.get("TP_TRIGGER") or None, "istek_id": os.environ.get("TP_ISTEK_ID") or None,
        "sha": os.environ.get("GITHUB_SHA") or None, "run_id": run_id,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None,
        "bolge": os.environ.get("SAUCE_REGION") or None,
        "job_url": ilk, "jobs": [i for p in platformlar for i in p["isler"]],
        "platformlar": platformlar,
        "kota": {"once": _kota(a.kota_once), "sonra": _kota(a.kota_sonra)},
    }
    _yaz(out / "sauce.json", kayit)
    _yaz(out / "ci-meta.json", {
        "schema_version": 1, "job": "sauce", "tetik": kayit["tetik"], "sha": kayit["sha"],
        "run_id": run_id, "durum": durum, "event": os.environ.get("GITHUB_EVENT_NAME") or None,
    })
    satirlar = ["### Sauce Labs turu", "", f"Sonuç: **{durum}**" + (f" — {neden}" if neden else ""), "",
                "| Platform | Durum | Test (geçen/toplam) | Sauce işleri (video + log) |", "|---|---|---|---|"]
    for p in platformlar:
        isler = " ".join(f"[{(i.get('ad') or 'iş')}]({i['url']})" for i in p["isler"]) or "—"
        satirlar.append(f"| {p['etiket']} | {p['durum']} | {p.get('gecen', 0)}/{p.get('toplam', 0)} | {isler} |")
    ko, ks = kayit["kota"]["once"], kayit["kota"]["sonra"]
    if ko or ks:
        satirlar += ["", f"Kota (önce): `{json.dumps(ko, ensure_ascii=False)}` · (sonra): `{json.dumps(ks, ensure_ascii=False)}`"]
    _ozet_yaz("\n".join(satirlar) + "\n")
    print(f"sauce.json: durum={durum} platform={len(platformlar)} ilk_is={ilk or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = ap.add_subparsers(dest="komut", required=True)
    w = alt.add_parser("web")
    w.add_argument("--out", required=True)
    w.add_argument("--report")
    w.add_argument("--junit")
    w.add_argument("--log")
    w.add_argument("--suite", action="append", help="rapor yoksa beklenen suite adları")
    w.add_argument("--exit-code")
    w.add_argument("--region")
    w.add_argument("--neden-altyapi")
    m = alt.add_parser("mobil")
    m.add_argument("--out", required=True)
    m.add_argument("--platform", required=True, choices=("android", "ios"))
    m.add_argument("--etiket", required=True)
    m.add_argument("--surefire")
    m.add_argument("--oturumlar")
    m.add_argument("--exit-code")
    m.add_argument("--region")
    m.add_argument("--neden-altyapi")
    s = alt.add_parser("atla")
    s.add_argument("--out", required=True)
    s.add_argument("--neden", required=True)
    t = alt.add_parser("topla")
    t.add_argument("--out", required=True)
    t.add_argument("--girdi", action="append")
    t.add_argument("--beklenen", help="virgülle; sonuç bırakmayan platform 'error' satırı olur")
    t.add_argument("--kota-once")
    t.add_argument("--kota-sonra")
    a = ap.parse_args(argv)
    return {"web": komut_web, "mobil": komut_mobil, "atla": komut_atla, "topla": komut_topla}[a.komut](a)


if __name__ == "__main__":
    sys.exit(main())

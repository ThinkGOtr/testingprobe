"""Müşteri CI testlerinin ortak yardımcıları (ağ/DB yok)."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

SHA = "a" * 40

JUNIT_GECEN = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.acme.tp.uretilen.GirisTest" tests="2" failures="0">
  <testcase classname="com.acme.tp.uretilen.GirisTest" name="senaryo" time="1.5"/>
  <testcase classname="com.acme.tp.uretilen.SepetTest" name="senaryo" time="2.0"/>
</testsuite>
"""

JUNIT_KIRMIZI = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.acme.tp.uretilen.GirisTest" tests="1" failures="1">
  <testcase classname="com.acme.tp.uretilen.GirisTest" name="senaryo" time="1.5">
    <failure message="androidx.test.espresso.NoMatchingViewException: giris-buton">yigin</failure>
  </testcase>
</testsuite>
"""


def meta(platform: str = "android", dil: str = "kotlin", sha: str = SHA, **ek: Any) -> bytes:
    return json.dumps(
        {"platform": platform, "dil": dil, "sha": sha, "run_id": "7", "job": "x", **ek}
    ).encode()


def zip_yap(dosyalar: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ad, icerik in dosyalar.items():
            zf.writestr(ad, icerik)
    return buf.getvalue()


@dataclass
class SahteGh:
    """`GitHubCi` yerine: yalnız artifacts / artifact_zip."""

    artefaktlar: list[dict[str, Any]] = field(default_factory=list)
    zipler: dict[int, bytes] = field(default_factory=dict)
    indirilen: list[int] = field(default_factory=list)
    hata: Exception | None = None

    def artifacts(self, run_id: Any) -> list[dict[str, Any]]:
        if self.hata is not None:
            raise self.hata
        return list(self.artefaktlar)

    def artifact_zip(self, art: Any) -> bytes:
        self.indirilen.append(int(art["id"]))
        return self.zipler[int(art["id"])]


def tp_results_gh(dosyalar: dict[str, bytes], art_id: int = 11) -> SahteGh:
    return SahteGh(
        artefaktlar=[{"id": art_id, "name": "tp-results", "expired": False}],
        zipler={art_id: zip_yap(dosyalar)},
    )

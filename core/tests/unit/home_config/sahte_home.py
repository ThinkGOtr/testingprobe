"""Sahte aiprobe-home (+ metadata, Secret Manager) taşıyıcısı: `yukleyici.Http` imzası."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from tp_core.home_config import yukleyici as y

HOME = "https://home.example.test"
SM_PROJESI = "sirlar-projesi"
REF = (
    f"projects/{SM_PROJESI}/secrets/aiprobe-o0123456789ab--pr-0123456789ab--jira-token"
    "/versions/latest"
)


def ornek_yanit(**ek: Any) -> dict[str, Any]:
    v: dict[str, Any] = {
        "org": {"oid": "0123456789ab", "name": "Örnek Org"},
        "project": {
            "pid": "aaaabbbbcccc",
            "code": "ornek",
            "name": "Örnek Proje",
            "features": {"web": True, "android": True, "ios": False, "windows": True},
            "products": ["ap", "tp"],
        },
        "product": "tp",
        "values": {},
        "secrets": {},
        "env": {"JIRA_PROJECT": "TPD", "TP_DENETIM_KAPISI": "on", "TP_CT_SON_KOSU": 25},
        "env_secrets": {"JIRA_READ_TOKEN": REF},
        "connections": {"jira": {"mode": "token", "public": {}}, "github": {"mode": "token"}},
        "etag": "v1",
    }
    v.update(ek)
    return v


@dataclass
class SahteHome:
    yanit: dict[str, Any] = field(default_factory=ornek_yanit)
    durum: int = 200
    kapali: bool = False
    sirlar: dict[str, str] = field(default_factory=lambda: {REF: "gizli-deger"})
    erisim: dict[str, Any] = field(default_factory=dict)  # tur → yanıt gövdesi
    erisim_durum: int = 200
    erisim_hata: str = "use_secret"  # erisim_durum != 200 iken gövdedeki `error`
    istekler: list[tuple[str, str, dict[str, str], bytes | None]] = field(default_factory=list)
    # Çok proje: pid → yanıt / durum (yoksa `yanit` / `durum`).
    projeler: dict[str, dict[str, Any]] = field(default_factory=dict)
    proje_durum: dict[str, int] = field(default_factory=dict)
    erisim_projeleri: list[str] = field(default_factory=list)
    # Test ortamları: (pid, eid) → ortam düzeyi yanıt (`?environment=`); yoksa 404.
    ortamlar: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def __call__(
        self, yontem: str, url: str, basliklar: Mapping[str, str], govde: bytes | None, _t: float
    ) -> y.HttpYanit:
        self.istekler.append((yontem, url, dict(basliklar), govde))
        u = urlsplit(url)
        if u.netloc == "metadata.google.internal":
            if u.path.endswith("/identity"):
                aud = parse_qs(u.query)["audience"][0]
                return y.HttpYanit(200, {}, f"idtoken-for:{aud}".encode())
            return y.HttpYanit(
                200, {}, json.dumps({"access_token": "at", "expires_in": 3600}).encode()
            )
        if u.netloc == "secretmanager.googleapis.com":
            ref = u.path.removeprefix("/v1/").removesuffix(":access")
            if ref not in self.sirlar:
                return y.HttpYanit(404, {}, b"{}")
            data = base64.b64encode(self.sirlar[ref].encode()).decode()
            return y.HttpYanit(200, {}, json.dumps({"payload": {"data": data}}).encode())
        if self.kapali:
            raise y.Ulasilamaz("bağlantı reddedildi")
        if u.path == "/v1/config/effective":
            pid = parse_qs(u.query).get("project", [""])[0]
            eid = parse_qs(u.query).get("environment", [""])[0]
            if eid:
                oy = self.ortamlar.get((pid, eid))
                if oy is None:
                    return y.HttpYanit(404, {}, b"{}")
                if basliklar.get("If-None-Match") == str(oy.get("etag")):
                    return y.HttpYanit(304, {}, b"")
                return y.HttpYanit(200, {"etag": str(oy.get("etag"))}, json.dumps(oy).encode())
            yanit = self.projeler.get(pid, self.yanit)
            durum = self.proje_durum.get(pid, self.durum)
            etag = str(yanit.get("etag"))
            if pid in self.proje_durum and durum != 200:  # erişim reddi ETag'den önce
                return y.HttpYanit(durum, {}, b"{}")
            if basliklar.get("If-None-Match") == etag:
                return y.HttpYanit(304, {}, b"")
            if durum != 200:
                return y.HttpYanit(durum, {}, b"{}")
            return y.HttpYanit(200, {"etag": etag}, json.dumps(yanit).encode())
        if u.path == "/v1/connections/access-token":
            istek = json.loads(govde or b"{}")
            tur = istek["type"]
            self.erisim_projeleri.append(str(istek.get("project")))
            if self.erisim_durum != 200:
                return y.HttpYanit(
                    self.erisim_durum, {}, json.dumps({"error": self.erisim_hata}).encode()
                )
            return y.HttpYanit(200, {}, json.dumps(self.erisim[tur]).encode())
        return y.HttpYanit(404, {}, b"{}")

    def sayi(self, yol: str) -> int:
        return sum(1 for _m, url, _h, _b in self.istekler if urlsplit(url).path == yol)

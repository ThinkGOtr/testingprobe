"""Portal API'si (rol başına oturum) ve jira-sim REST istemcileri — yalnızca standart kütüphane.

Portal çağrıları `http://127.0.0.1:<TP_PORTAL_PORT>/api` üzerinden gider (core-api host'a port
açmaz). İstemci tarayıcı değildir (Origin / Sec-Fetch-Site göndermez): `OriginGuard` geçirir,
`make demo-*` betikleriyle aynı yol. Her rol kendi çerez kavanozuyla giriş yapar; kararlar o rolün
oturumuyla kaydedilir (insan kapıları rolden bağımsız atlanamaz).
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

ROLLER = ("analist", "po", "muhendis", "sunucu", "testci")


class ApiHatasi(RuntimeError):
    def __init__(self, yontem: str, yol: str, durum: int, govde: Any) -> None:
        self.yontem, self.yol, self.durum, self.govde = yontem, yol, durum, govde
        detay = govde.get("detail") if isinstance(govde, dict) else govde
        super().__init__(f"{yontem} {yol} → HTTP {durum}: {str(detay)[:400]}")


@dataclass
class Yanit:
    durum: int
    govde: Any
    sure_s: float


@dataclass
class CagriKaydi:
    rol: str
    yontem: str
    yol: str
    durum: int
    sure_s: float


@dataclass
class PortalIstemcisi:
    taban: str
    parola: str
    zaman_asimi_s: float = 90.0
    kayitlar: list[CagriKaydi] = field(default_factory=list)
    _acicilar: dict[str, urllib.request.OpenerDirector] = field(default_factory=dict)

    def _acici(self, rol: str) -> urllib.request.OpenerDirector:
        if rol not in self._acicilar:
            kavanoz = http.cookiejar.CookieJar()
            acici = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(kavanoz))
            self._acicilar[rol] = acici
            y = self._ham(
                rol, acici, "POST", "/auth/login", {"kullanici_adi": rol, "parola": self.parola}
            )
            if y.durum != 200:
                del self._acicilar[rol]
                raise ApiHatasi("POST", f"/auth/login ({rol})", y.durum, y.govde)
        return self._acicilar[rol]

    def _ham(
        self,
        rol: str,
        acici: urllib.request.OpenerDirector,
        yontem: str,
        yol: str,
        govde: Any = None,
    ) -> Yanit:
        veri = json.dumps(govde).encode() if govde is not None else None
        istek = urllib.request.Request(
            self.taban + yol,
            data=veri,
            method=yontem,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        t0 = time.monotonic()
        try:
            with acici.open(istek, timeout=self.zaman_asimi_s) as r:
                durum, ham = r.status, r.read()
        except urllib.error.HTTPError as e:
            durum, ham = e.code, e.read()
        sure = time.monotonic() - t0
        try:
            cozulmus: Any = json.loads(ham) if ham else None
        except ValueError:
            cozulmus = ham.decode("utf-8", "replace")[:2000]
        self.kayitlar.append(CagriKaydi(rol, yontem, yol, durum, round(sure, 3)))
        return Yanit(durum, cozulmus, sure)

    def istek(self, rol: str, yontem: str, yol: str, govde: Any = None) -> Yanit:
        return self._ham(rol, self._acici(rol), yontem, yol, govde)

    def get(self, rol: str, yol: str) -> Any:
        y = self.istek(rol, "GET", yol)
        if y.durum != 200:
            raise ApiHatasi("GET", yol, y.durum, y.govde)
        return y.govde

    def post(
        self, rol: str, yol: str, govde: Any = None, beklenen: tuple[int, ...] = (200, 202)
    ) -> Any:
        y = self.istek(rol, "POST", yol, govde)
        if y.durum not in beklenen:
            raise ApiHatasi("POST", yol, y.durum, y.govde)
        return y.govde


@dataclass
class JiraSim:
    """jira-sim REST v3. Okuma `reader@sim.local` (salt okuma), PO onayı `po@sim.local` + parola."""

    taban: str
    po_parolasi: str = ""
    zaman_asimi_s: float = 20.0

    def _istek(self, kullanici: str, parola: str, yontem: str, yol: str, govde: Any = None) -> Any:
        jeton = base64.b64encode(f"{kullanici}:{parola}".encode()).decode()
        istek = urllib.request.Request(
            self.taban + yol,
            data=json.dumps(govde).encode() if govde is not None else None,
            method=yontem,
            headers={
                "Authorization": f"Basic {jeton}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(istek, timeout=self.zaman_asimi_s) as r:
                ham = r.read()
        except urllib.error.HTTPError as e:
            raise ApiHatasi(
                yontem, f"jira-sim {yol}", e.code, e.read().decode("utf-8", "replace")
            ) from e
        return json.loads(ham) if ham else None

    def issue(
        self, anahtar: str, alanlar: str = "summary,issuetype,labels,issuelinks,comment,status"
    ) -> dict:
        return self._istek(
            "reader@sim.local", "okuma", "GET", f"/rest/api/3/issue/{anahtar}?fields={alanlar}"
        )

    def po_onayla(self, anahtar: str) -> None:
        """PO insan kapısı: `tp-po-approved` etiketi PO kimliğiyle (arayüz düğmesinin eşi)."""
        if not self.po_parolasi:
            raise RuntimeError("JIRA_SIM_PO_PASSWORD yok (.env); PO onayı verilemez")
        self._istek(
            "po@sim.local",
            self.po_parolasi,
            "PUT",
            f"/rest/api/3/issue/{anahtar}",
            {"update": {"labels": [{"add": "tp-po-approved"}]}},
        )


def baglantilar(issue: dict) -> list[tuple[str, str]]:
    """issuelinks → [(tür adı, karşı anahtar)]."""
    sonuc = []
    for b in (issue.get("fields") or {}).get("issuelinks") or []:
        karsi = b.get("outwardIssue") or b.get("inwardIssue") or {}
        sonuc.append(((b.get("type") or {}).get("name", ""), karsi.get("key", "")))
    return sonuc

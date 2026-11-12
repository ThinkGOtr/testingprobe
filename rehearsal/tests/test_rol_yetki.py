"""012 rol modeli: case üretimi/kabulü/yayını testçi, son onay analist, CI tetikleri mühendis."""

from __future__ import annotations

from typing import Any

import pytest

from tp_rehearsal import steps
from tp_rehearsal.client import ApiHatasi
from tp_rehearsal.runner import PASS, UYARI, Basarisiz

REQ = "r1"
IZIN = {  # yetki.IZINLER'in provada kullanılan dilimi
    "case.decide": {"testci"},
    "case.approve": {"analist"},
    "case.publish": {"testci"},
    "case.generate": {"testci"},
}


class CaseApi:
    """Case yaşam döngüsünü (draft → ready → approved) ve izinleri taklit eden sahte portal."""

    def __init__(self, durum: str = "draft") -> None:
        self.cs = {
            f"c{n}": {
                "id": f"c{n}",
                "sira_no": n,
                "uretim_no": 1,
                "durum": durum,
                "icerik_hash": f"h{n}",
                "icerik": {"title": f"C{n}"},
                "mode": "replay",
            }
            for n in range(1, steps.CASE_SAYISI + 1)
        }
        self.kararlar: list[tuple[str, str, str]] = []  # (rol, case, karar)
        self.cagrilar: list[tuple[str, str, str]] = []

    def _izin(self, rol: str, izin: str, yol: str) -> None:
        if rol not in IZIN[izin]:
            raise ApiHatasi("POST", yol, 403, {"detail": "yetki_yok"})

    def get(self, rol: str, yol: str) -> Any:
        self.cagrilar.append((rol, "GET", yol))
        if yol == f"/cases?requirement_id={REQ}":
            return [dict(c) for c in self.cs.values()]
        if yol == f"/requirements/{REQ}/case-metrics":
            ilk: dict[str, int] = {}
            onay = 0
            for _r, _c, k in self.kararlar:
                if k in ("accept", "edit", "reject"):
                    ilk[k] = ilk.get(k, 0) + 1
                elif k == "approve":
                    onay += 1
            return {
                "ilk_kararlar": ilk,
                "kabul_orani": ilk.get("accept", 0) / steps.CASE_SAYISI,
                "kabul_hedefi": 0.7,
                "son_onay": {"onaylanan": onay, "geri_gonderilen": 0},
            }
        raise KeyError(yol)

    def post(self, rol: str, yol: str, govde: Any = None, beklenen=(200,)) -> Any:
        self.cagrilar.append((rol, "POST", yol))
        cid = yol.split("/")[2] if yol.startswith("/cases/") else None
        if yol.endswith("/viewed"):
            if rol not in IZIN["case.decide"] | IZIN["case.approve"]:
                raise ApiHatasi("POST", yol, 403, {})
            return {}
        if yol.endswith("/decision"):
            c = self.cs[cid]
            karar = govde["karar"]
            assert govde["icerik_hash"] == c["icerik_hash"]
            if karar in ("approve", "send_back"):
                self._izin(rol, "case.approve", yol)
                if c["durum"] != "ready":
                    raise ApiHatasi("POST", yol, 409, {})
                if any(r == rol and x == cid for r, x, _k in self.kararlar):
                    raise ApiHatasi("POST", yol, 403, {"detail": "görevler ayrılığı"})
                c["durum"] = "approved"
            else:
                self._izin(rol, "case.decide", yol)
                if c["durum"] != "draft":
                    raise ApiHatasi("POST", yol, 409, {})
                c["durum"] = "ready"
            self.kararlar.append((rol, cid, karar))
            return dict(c)
        raise KeyError(yol)


def _b(baglam, api: CaseApi, kip: str = "prova"):
    b = baglam(kip=kip, api=api)
    b.veri["req_id"] = REQ
    return b


def test_a7_testci_kabul_analist_son_onay(baglam):
    api = CaseApi()
    b = _b(baglam, api)
    steps.qa_kararlari(b)
    assert all(c["durum"] == "approved" for c in api.cs.values())
    assert {(r, k) for r, _c, k in api.kararlar} == {("testci", "accept"), ("analist", "approve")}
    # Önce tüm kabuller, sonra son onaylar.
    ilk_onay = next(i for i, x in enumerate(api.kararlar) if x[2] == "approve")
    assert all(x[2] == "accept" for x in api.kararlar[:ilk_onay])
    assert all(k.sonuc == PASS for k in b.kontroller)
    assert b.kanit["son_onay"]["onaylanan"] == steps.CASE_SAYISI


def test_a7_ready_kaldiysa_yalniz_son_onay_verilir(baglam):
    api = CaseApi("ready")
    api.kararlar = [("testci", cid, "accept") for cid in api.cs]
    b = _b(baglam, api)
    steps.qa_kararlari(b)
    assert [k for _r, _c, k in api.kararlar].count("accept") == steps.CASE_SAYISI
    assert all(c["durum"] == "approved" for c in api.cs.values())


def test_a7_son_onay_eksikse_fail(baglam):
    api = CaseApi("approved")
    api.kararlar = [("testci", cid, "accept") for cid in api.cs]
    b = _b(baglam, api)
    with pytest.raises(Basarisiz, match="son onay"):
        steps.qa_kararlari(b)


def test_a7_denetim_eski_akis_approve_uyari(baglam):
    api = CaseApi("published")
    b = _b(baglam, api, kip="denetim")
    api.get = lambda rol, yol: (  # type: ignore[method-assign]
        [dict(c) for c in api.cs.values()]
        if yol.startswith("/cases")
        else {
            "ilk_kararlar": {"approve": steps.CASE_SAYISI},
            "kabul_orani": 1.0,
            "kabul_hedefi": 0.7,
            "son_onay": {"onaylanan": 0, "geri_gonderilen": 0},
        }
    )
    steps.qa_kararlari(b)
    assert not api.kararlar
    assert [k.sonuc for k in b.kontroller if "son onay:" in k.ad] == [UYARI]


def test_adim_rolleri_012():
    roller = {a.no: a.rol for a in steps.adimlar()}
    assert roller["A6"] == "testci"
    assert roller["A7"] == "testci, analist"
    assert roller["A8"] == "testci"
    assert roller["B4"] == "muhendis"
    assert roller["C1"] == "testci"


def test_portal_hesaplari_seed_ile_ayni():
    from tp_rehearsal.client import ROLLER

    assert set(ROLLER) == set(steps.PORTAL_HESAPLARI)
    assert steps.PORTAL_HESAPLARI["sunucu"] == "admin"


class YayinApi(CaseApi):
    def get(self, rol: str, yol: str) -> Any:
        if yol.startswith("/publish/preview"):
            self.cagrilar.append((rol, "GET", yol))
            return {"kalemler": [{"case_id": c, "islem": "create"} for c in self.cs]}
        return super().get(rol, yol)

    def post(self, rol: str, yol: str, govde: Any = None, beklenen=(200,)) -> Any:
        if yol == "/publish":
            self.cagrilar.append((rol, "POST", yol))
            self._izin(rol, "case.publish", yol)
            for i, cid in enumerate(govde["case_ids"]):
                self.cs[cid] |= {"durum": "published", "jira_test_key": f"TPD-{100 + i}"}
            return {"sonuclar": [{"durum": "created"} for _ in govde["case_ids"]]}
        if yol.endswith("/generate-cases"):
            self.cagrilar.append((rol, "POST", yol))
            self._izin(rol, "case.generate", yol)
            return {}
        return super().post(rol, yol, govde, beklenen)


class SahteJira:
    def issue(self, _key: str, _alanlar: str) -> dict[str, Any]:
        return {"fields": {"issuetype": {"name": "Test"}, "labels": ["AI-generated"]}}


def test_a8_yayin_testci_oturumuyla(baglam):
    api = YayinApi("approved")
    b = _b(baglam, api)
    b.jira = SahteJira()
    steps.yayin(b)
    assert ("testci", "POST", "/publish") in api.cagrilar
    assert all(c["durum"] == "published" for c in api.cs.values())


def test_a6_uretim_testci_oturumuyla(baglam, monkeypatch):
    api = YayinApi()
    b = _b(baglam, api)
    monkeypatch.setattr(steps, "gereksinim_bekle", lambda *a, **k: {"durum": "cases_ready"})
    api.cs["c3"]["icerik"]["title"] = steps.C3_BASLIK
    steps.case_uret(b)
    assert ("testci", "POST", f"/requirements/{REQ}/generate-cases") in api.cagrilar

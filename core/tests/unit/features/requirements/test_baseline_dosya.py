"""Story başına F0 ölçümleri `make reset`'ten sağ çıkar: rules/baz-degerler.yaml story anahtarıyla
tutulur, Jira eşitlemesinde (yeni UUID'li) gereksinimlere uygulanır, `seed` aktörüyle denetlenir ve
portalda bir insanın girdiği değeri ezmez. Değer uydurulmaz: dosyada olmayan story ölçülmedi kalır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit import verify_chain
from tp_core.features.requirements import baseline_dosya
from tp_core.models import AuditEvent

from .conftest import login

pytestmark = pytest.mark.usefixtures("wired")

GECERLI = """
degerler:
  - story: TPD-1
    deger_s: 2700
    giren: İsmail
    not: "F0 kronometre ölçümü, 2026-10-20"
  - story: TPD-3
    deger_s: 1500
    giren: İsmail
    not: "F0 kronometre ölçümü"
"""


@pytest.fixture(autouse=True)
def _varsayilan_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)


def _liste(api: TestClient) -> dict[str, dict[str, Any]]:
    return {g["jira_key"]: g for g in api.get("/requirements").json()}


def _baz_olaylari(engine: Engine) -> list[AuditEvent]:
    with Session(engine) as s:
        return list(
            s.scalars(
                select(AuditEvent)
                .where(AuditEvent.eylem.like("requirement.baseline_%"))
                .order_by(AuditEvent.id)
            )
        )


def _sifirla(engine: Engine) -> None:
    """`make reset` benzeri: gereksinimler (ve cascade ile baz girişleri) gider."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM requirement"))


# ------------------------------------------------------------------------- dosya ayrıştırma


def test_dosya_yoksa_bos(_baz_dosyasi_yok: Path) -> None:
    o = baseline_dosya.oku()
    assert (o.var, o.girdiler, o.hatalar) == (False, {}, [])


def test_gecerli_dosya(_baz_dosyasi_yok: Path) -> None:
    _baz_dosyasi_yok.write_text(GECERLI, encoding="utf-8")
    o = baseline_dosya.oku()
    assert o.var and o.hatalar == []
    assert o.girdiler["TPD-1"] == baseline_dosya.Girdi(
        "TPD-1", 2700, "İsmail", "F0 kronometre ölçümü, 2026-10-20"
    )
    assert set(o.girdiler) == {"TPD-1", "TPD-3"}


@pytest.mark.parametrize(
    ("girdi", "parca"),
    [
        ("{story: TPD-1, deger_s: '2700', giren: İsmail, not: F0 ölçümü}", "tam sayı"),
        ("{story: TPD-1, deger_s: 2700.5, giren: İsmail, not: F0 ölçümü}", "tam sayı"),
        ("{story: TPD-1, deger_s: 0, giren: İsmail, not: F0 ölçümü}", "0'dan büyük"),
        ("{story: TPD-1, deger_s: 144001, giren: İsmail, not: F0 ölçümü}", "en çok"),
        ("{story: TPD-1, deger_s: 2700, not: F0 ölçümü}", "'giren' zorunlu"),
        ("{story: TPD-1, deger_s: 2700, giren: İsmail}", "Kaynak notu zorunlu"),
        ("{story: TPD-1, deger_s: 2700, giren: İsmail, not: a}", "en az 3"),
        ("{story: tpd-1, deger_s: 2700, giren: İsmail, not: F0 ölçümü}", "story anahtarı"),
        ("{story: TPD-1, deger_s: 2700, giren: İsmail, not: F0 ölçümü, tahmin: 1}", "bilinmeyen"),
    ],
)
def test_gecersiz_girdi_uygulanmaz(_baz_dosyasi_yok: Path, girdi: str, parca: str) -> None:
    _baz_dosyasi_yok.write_text(f"degerler:\n  - {girdi}\n", encoding="utf-8")
    o = baseline_dosya.oku()
    assert o.girdiler == {}
    assert len(o.hatalar) == 1 and parca in o.hatalar[0] and "uygulanmadı" in o.hatalar[0]


def test_yinelenen_story_ve_bozuk_dosya(_baz_dosyasi_yok: Path) -> None:
    _baz_dosyasi_yok.write_text(
        GECERLI + "  - {story: TPD-1, deger_s: 60, giren: Ayşe, not: başka ölçüm}\n",
        encoding="utf-8",
    )
    o = baseline_dosya.oku()
    assert set(o.girdiler) == {"TPD-3"} and "iki değer de uygulanmadı" in o.hatalar[0]
    for bozuk in ("degerler: [", "- TPD-1", "degerler: 3", "baska: []"):
        _baz_dosyasi_yok.write_text(bozuk, encoding="utf-8")
        o = baseline_dosya.oku()
        assert o.girdiler == {} and len(o.hatalar) == 1, bozuk
    _baz_dosyasi_yok.write_text("# yalnız yorum\n", encoding="utf-8")
    assert baseline_dosya.oku().hatalar == []


# ---------------------------------------------------------------------- eşitlemede uygulama


def test_esitlemede_uygulanir_ve_sifirlamadan_sag_cikar(
    api: TestClient, engine: Engine, make_user, _baz_dosyasi_yok: Path
) -> None:
    _baz_dosyasi_yok.write_text(GECERLI, encoding="utf-8")
    login(api, make_user("analyst", ad="analist1"))
    for tur in (1, 2):
        n0 = len(_baz_olaylari(engine))
        r = api.post("/requirements/sync")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["baz_dosyasi"]["sonuc"] == {"TPD-1": "uygulandi", "TPD-3": "uygulandi"}
        assert "2 story'ye baz değer ölçümü dosyadan uygulandı" in j["mesaj"]
        g = _liste(api)
        b = g["TPD-1"]["baseline"]
        assert (b["deger_s"], b["kaynak"], b["etiket"]) == (2700, "olcum", "ölçüm")
        assert (b["giren"], b["giren_rol"]) == ("İsmail", "dosya")
        assert b["not"] == "F0 kronometre ölçümü, 2026-10-20"
        # Dosyada olmayan story ölçülmedi kalır: değer uydurulmaz.
        assert g["TPD-2"]["baseline"]["kaynak"] is None
        assert g["TPD-2"]["baseline"]["deger_s"] is None
        olaylar = _baz_olaylari(engine)[n0:]
        assert [o.aktor for o in olaylar] == ["seed", "seed"]
        o1 = next(o for o in olaylar if o.ozet["jira_key"] == "TPD-1")
        assert o1.ozet["kaynak"] == "dosya" and o1.ozet["dosya"] == "rules/baz-degerler.yaml"
        assert o1.ozet["tetikleyen"] == "analist1" and o1.ozet["sonra"]["giren"] == "İsmail"
        with engine.connect() as c:
            assert verify_chain(c).ok
        if tur == 1:
            # Aynı dosya + yeniden eşitleme: yeni satır/denetim yok.
            assert api.post("/requirements/sync").json()["baz_dosyasi"]["sonuc"] == {
                "TPD-1": "ayni",
                "TPD-3": "ayni",
            }
            assert len(_baz_olaylari(engine)) == n0 + 2
            # `make reset`: gereksinimler ve baz girişleri gider; dosya kalır.
            _sifirla(engine)
            assert api.get("/requirements").json() == []


def test_portal_girisi_ezilmez_dosya_degisikligi_uygulanir(
    api: TestClient, engine: Engine, make_user, _baz_dosyasi_yok: Path
) -> None:
    _baz_dosyasi_yok.write_text(GECERLI, encoding="utf-8")
    login(api, make_user("analyst"))
    api.post("/requirements/sync")
    rid1, rid3 = (_liste(api)[k]["id"] for k in ("TPD-1", "TPD-3"))
    # Portal girişi (insan) dosyadan sonra gelir: dosya artık onu ezmez.
    r = api.put(f"/requirements/{rid3}/baseline", json={"deger_s": 1800, "not": "yeniden ölçüm"})
    assert r.status_code == 200, r.text
    _baz_dosyasi_yok.write_text(
        GECERLI.replace("2700", "3000").replace("1500", "900"), encoding="utf-8"
    )
    login(api, make_user("po"))
    r = api.post("/baseline-file/apply")
    assert r.status_code == 200, r.text
    assert r.json()["sonuc"] == {"TPD-1": "uygulandi", "TPD-3": "portal_girisi"}
    g = _liste(api)
    assert g["TPD-1"]["baseline"]["deger_s"] == 3000
    assert (g["TPD-3"]["baseline"]["deger_s"], g["TPD-3"]["baseline"]["giren_rol"]) == (
        1800,
        "analyst",
    )
    gecmis = api.get(f"/requirements/{rid1}/baseline").json()["gecmis"]
    assert [(x["deger_s"], x["onceki_s"], x["giren"]) for x in gecmis] == [
        (3000, 2700, "İsmail"),
        (2700, None, "İsmail"),
    ]


def test_dosya_durumu_ve_yetkiler(api: TestClient, make_user, _baz_dosyasi_yok: Path) -> None:
    _baz_dosyasi_yok.write_text(
        GECERLI + "  - {story: TPD-4, deger_s: 60, giren: '', not: F0 ölçümü}\n",
        encoding="utf-8",
    )
    assert api.get("/baseline-file").status_code == 401
    login(api, make_user("tester"))
    d = api.get("/baseline-file").json()
    assert d["var"] is True and d["girdi"] == 2 and len(d["hatalar"]) == 1
    # Gereksinim henüz eşitlenmedi: değer eşitlemede uygulanacak.
    assert {x["story"]: x["etkin_kaynak"] for x in d["girdiler"]} == {"TPD-1": None, "TPD-3": None}
    assert api.post("/baseline-file/apply").status_code == 403
    login(api, make_user("analyst"))
    r = api.post("/requirements/sync").json()
    assert "baz değer dosyasında 1 hata" in r["mesaj"]
    d = api.get("/baseline-file").json()
    t1 = next(x for x in d["girdiler"] if x["story"] == "TPD-1")
    # Demo öncesi denetim: TPD-1 "ölçüm" okunmalı.
    assert (t1["etkin_kaynak"], t1["etkin_etiket"], t1["etkin_deger_s"]) == (
        "olcum",
        "ölçüm",
        2700,
    )

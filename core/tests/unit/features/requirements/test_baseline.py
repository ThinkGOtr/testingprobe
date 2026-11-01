"""Faz 5: story başına manuel baz değer — gerçek Postgres: 0013 şeması, API, yetki, denetim,
geçmiş, varsayılana düşme ve case-metrics. Değer asla uydurulmaz."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.conftest import Db, run_alembic
from tests.unit.features.requirements.conftest import login
from tp_core.audit import verify_chain
from tp_core.features.requirements import baseline
from tp_core.models import AuditEvent, Base, Requirement, session_scope
from tp_core.models.baseline_feature import BAZ_UST_SINIR_S, RequirementBazDeger

TABLO = "requirement_baz_deger"


@pytest.fixture(autouse=True)
def _varsayilan_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)


def _req(jira_key: str | None = "TPD-1") -> uuid.UUID:
    with session_scope() as s:
        r = Requirement(
            kaynak="jira" if jira_key else "free_text",
            jira_key=jira_key,
            baslik="Kampanya",
            kaynak_hash="h",
        )
        s.add(r)
        s.flush()
        return r.id


def _put(api: TestClient, rid: uuid.UUID, body: dict[str, Any]) -> Any:
    return api.put(f"/requirements/{rid}/baseline", json=body)


def _olaylar(engine: Engine, rid: uuid.UUID) -> list[AuditEvent]:
    with Session(engine) as s:
        return list(
            s.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.nesne == f"requirement:{rid}",
                    AuditEvent.eylem.like("requirement.baseline_%"),
                )
                .order_by(AuditEvent.id)
            )
        )


# --------------------------------------------------------------------------- şema (0013)


def _farklar(url: str) -> list[object]:
    eng = create_engine(url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    return [f for f in farklar if TABLO in repr(f)]


def test_model_ve_migrasyon_ayni(db: Db) -> None:
    assert TABLO in Base.metadata.tables
    assert _farklar(db.owner_url) == []


def test_tp_app_gecmisi_degistiremez(db: Db) -> None:
    rid = _req()
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute(
            f"INSERT INTO {TABLO} (requirement_id, sira, islem, deger_s, giren, giren_rol) "
            "VALUES (%s, 1, 'set', 3600, 'a', 'analyst')",
            (rid,),
        )
        for sql in (f"UPDATE {TABLO} SET deger_s = 1", f"DELETE FROM {TABLO}"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
        # Değer kısıtları veritabanında da: 0, üst sınır üstü, clear'da değer.
        for islem, deger in (("set", 0), ("set", BAZ_UST_SINIR_S + 1), ("clear", 5), ("set", None)):
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(
                    f"INSERT INTO {TABLO} (requirement_id, sira, islem, deger_s, giren, giren_rol)"
                    " VALUES (%s, 9, %s, %s, 'a', 'analyst')",
                    (rid, islem, deger),
                )
        # Gereksinim silinirse geçmiş de gider (cascade, tp_app gereksinimi silebilir).
        c.execute("DELETE FROM requirement WHERE id = %s", (rid,))
        assert c.execute(f"SELECT count(*) FROM {TABLO}").fetchone() == (0,)


def test_downgrade_upgrade(db: Db) -> None:
    run_alembic(db.owner_url, "0012", "downgrade")
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        var = c.execute(f"SELECT count(*) FROM pg_tables WHERE tablename = '{TABLO}'")
        assert var.fetchone() == (0,)
    run_alembic(db.owner_url, "head")
    assert _farklar(db.owner_url) == []


# --------------------------------------------------------------------------- API + yetki


def test_olculmedi_iken_sayi_yok(api: TestClient, make_user) -> None:
    rid = _req()
    login(api, make_user("tester"))
    b = api.get(f"/requirements/{rid}").json()["baseline"]
    assert b["deger_s"] is None and b["kaynak"] is None and b["etiket"] == "ölçülmedi"
    assert b["giren"] is None and b["zaman"] is None and b["not"] is None
    liste = {x["id"]: x for x in api.get("/requirements").json()}
    assert liste[str(rid)]["baseline"]["kaynak"] is None


def test_varsayilan_etiketlenir(
    api: TestClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = _req()
    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "1800")
    login(api, make_user("engineer"))
    b = api.get(f"/requirements/{rid}").json()["baseline"]
    # Varsayılan ölçüm değildir: başlık değeri yok, ortam değeri yalnızca ikincil alanda.
    assert (b["deger_s"], b["deger_ms"]) == (None, None)
    assert (b["kaynak"], b["etiket"]) == ("varsayilan", "varsayılan")
    assert (b["varsayilan_s"], b["varsayilan_ms"]) == (1800, 1_800_000)
    assert b["aciklama"] == "ölçülmedi; varsayılan 30 dk (TP_MANUAL_BASELINE_S), ölçüm değil"
    assert b["giren"] is None and "TP_MANUAL_BASELINE_S" in b["not"]


@pytest.mark.parametrize("rol", ["engineer", "tester", "presenter"])
def test_yalnizca_analist_ve_po_girer(api: TestClient, make_user, rol: str) -> None:
    rid = _req()
    assert _put(api, rid, {"deger_s": 3600, "not": "F0 ölçümü"}).status_code == 401
    assert api.delete(f"/requirements/{rid}/baseline").status_code == 401
    login(api, make_user(rol))
    assert _put(api, rid, {"deger_s": 3600, "not": "F0 ölçümü"}).status_code == 403
    assert api.delete(f"/requirements/{rid}/baseline").status_code == 403
    assert api.get(f"/requirements/{rid}/baseline").status_code == 200


def test_analist_girer_po_gunceller_gecmis_ve_denetim(
    api: TestClient, engine: Engine, make_user
) -> None:
    rid = _req()
    analist = make_user("analyst", ad="ismail")
    login(api, analist)
    r = _put(api, rid, {"deger_s": 5400, "not": "  F0 ölçümü –   İsmail "})
    assert r.status_code == 200, r.text
    j = r.json()
    b = j["baseline"]
    assert (b["deger_s"], b["deger_ms"], b["kaynak"], b["etiket"]) == (
        5400,
        5_400_000,
        "olcum",
        "ölçüm",
    )
    assert (b["giren"], b["giren_rol"], b["not"], b["sira"]) == (
        "ismail",
        "analyst",
        "F0 ölçümü – İsmail",
        1,
    )
    assert b["zaman"] and j["degisti"] is True
    assert api.get(f"/requirements/{rid}").json()["baseline"] == b

    # Aynı değer + aynı not: yeni satır ve denetim yazılmaz.
    r = _put(api, rid, {"deger_s": 5400, "not": "F0 ölçümü – İsmail"})
    assert r.json()["degisti"] is False and len(r.json()["gecmis"]) == 1

    po = make_user("po", ad="po_ayse")
    login(api, po)
    r = _put(api, rid, {"deger_s": 4800, "not": "F0 tekrar ölçüm – İsmail"})
    assert r.status_code == 200
    gecmis = r.json()["gecmis"]
    assert [(g["sira"], g["islem"], g["deger_s"], g["onceki_s"], g["giren"]) for g in gecmis] == [
        (2, "set", 4800, 5400, "po_ayse"),
        (1, "set", 5400, None, "ismail"),
    ]

    olaylar = _olaylar(engine, rid)
    assert [o.eylem for o in olaylar] == ["requirement.baseline_set"] * 2
    ilk, ikinci = (o.ozet for o in olaylar)
    assert ilk["once"]["kaynak"] is None and ilk["once"]["deger_s"] is None
    assert ilk["sonra"] == {
        "deger_s": 5400,
        "kaynak": "olcum",
        "giren": "ismail",
        "not": "F0 ölçümü – İsmail",
        "sira": 1,
    }
    assert ikinci["once"]["deger_s"] == 5400 and ikinci["sonra"]["deger_s"] == 4800
    assert ikinci["rol"] == "po" and ikinci["jira_key"] == "TPD-1"
    assert olaylar[1].aktor == "po_ayse"
    with engine.connect() as c:
        assert verify_chain(c).ok


def test_silme_gecmisi_korur_ve_varsayilana_duser(
    api: TestClient, engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = _req()
    login(api, make_user("analyst"))
    _put(api, rid, {"deger_s": 3600, "not": "F0 ölçümü – İsmail"})
    r = api.delete(f"/requirements/{rid}/baseline", params={"not": "yanlış story'ye girildi"})
    assert r.status_code == 200
    j = r.json()
    assert j["degisti"] is True and j["baseline"]["kaynak"] is None
    assert [(g["islem"], g["deger_s"], g["onceki_s"], g["not"]) for g in j["gecmis"]] == [
        ("clear", None, 3600, "yanlış story'ye girildi"),
        ("set", 3600, None, "F0 ölçümü – İsmail"),
    ]
    # Zaten yokken silmek: değişiklik yok, denetim yok.
    assert api.delete(f"/requirements/{rid}/baseline").json()["degisti"] is False
    olaylar = _olaylar(engine, rid)
    assert [o.eylem for o in olaylar] == [
        "requirement.baseline_set",
        "requirement.baseline_cleared",
    ]
    assert olaylar[1].ozet["once"]["deger_s"] == 3600
    assert olaylar[1].ozet["sonra"]["kaynak"] is None

    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "2700")
    b = api.get(f"/requirements/{rid}").json()["baseline"]
    assert (b["deger_s"], b["kaynak"], b["varsayilan_s"]) == (None, "varsayilan", 2700)
    # Yeniden ölçüm varsayılanı ezer.
    _put(api, rid, {"deger_s": 3000, "not": "F0 ölçümü – İsmail (2)"})
    b = api.get(f"/requirements/{rid}").json()["baseline"]
    assert (b["deger_s"], b["kaynak"], b["sira"]) == (3000, "olcum", 3)


@pytest.mark.parametrize(
    "body",
    [
        {"deger_s": 0, "not": "F0 ölçümü"},
        {"deger_s": -60, "not": "F0 ölçümü"},
        {"deger_s": BAZ_UST_SINIR_S + 1, "not": "F0 ölçümü"},
        {"deger_s": "3600", "not": "F0 ölçümü"},
        {"deger_s": 3600.5, "not": "F0 ölçümü"},
        {"deger_s": True, "not": "F0 ölçümü"},
        {"deger_s": None, "not": "F0 ölçümü"},
        {"deger_s": 3600},
        {"deger_s": 3600, "not": "   "},
        {"deger_s": 3600, "not": "a"},
        {"deger_s": 3600, "not": " F0 "},
        {"deger_s": 3600, "not": "F 0"},
        {"deger_s": 3600, "not": "x" * 501},
    ],
)
def test_gecersiz_deger_reddedilir(
    api: TestClient, engine: Engine, make_user, body: dict[str, Any]
) -> None:
    rid = _req()
    login(api, make_user("analyst"))
    r = _put(api, rid, body)
    assert r.status_code == 422, r.text
    with Session(engine) as s:
        assert s.scalar(select(RequirementBazDeger).limit(1)) is None
    assert _olaylar(engine, rid) == []


def test_ust_sinir_kabul_ve_bilinmeyen_gereksinim(api: TestClient, make_user) -> None:
    rid = _req()
    login(api, make_user("po"))
    assert _put(api, rid, {"deger_s": BAZ_UST_SINIR_S, "not": "F0 ölçümü"}).status_code == 200
    yok = uuid.uuid4()
    assert _put(api, yok, {"deger_s": 60, "not": "F0 ölçümü"}).status_code == 404
    assert api.delete(f"/requirements/{yok}/baseline").status_code == 404
    assert api.get(f"/requirements/{yok}/baseline").status_code == 404


# --------------------------------------------------------------------------- case-metrics


def test_case_metrics_story_degerini_kullanir(
    api: TestClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.cases.service import (
        MANUEL_BAZ_VARSAYILAN_UYARISI,
        MANUEL_BAZ_YOK_UYARISI,
    )

    rid = _req()
    login(api, make_user("analyst"))
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["manuel_baz_ms"] is None and m["manuel_baz_kaynagi"] is None
    assert MANUEL_BAZ_YOK_UYARISI in m["uyarilar"]

    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "1800")
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    # Varsayılan ölçüm değildir: manuel_baz_ms boş (portal ondan kazanç hesaplayamaz).
    assert (m["manuel_baz_ms"], m["manuel_baz_kaynagi"]) == (None, "varsayilan")
    assert m["manuel_baz"]["varsayilan_ms"] == 1_800_000
    assert MANUEL_BAZ_VARSAYILAN_UYARISI in m["uyarilar"]
    assert MANUEL_BAZ_YOK_UYARISI not in m["uyarilar"]

    _put(api, rid, {"deger_s": 4200, "not": "F0 ölçümü – İsmail"})
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert (m["manuel_baz_ms"], m["manuel_baz_kaynagi"]) == (4_200_000, "olcum")
    assert m["manuel_baz"]["not"] == "F0 ölçümü – İsmail"
    assert not {MANUEL_BAZ_YOK_UYARISI, MANUEL_BAZ_VARSAYILAN_UYARISI} & set(m["uyarilar"])


# --------------------------------------------------------------------------- saf yardımcılar


def test_varsayilan_ayristirma(monkeypatch: pytest.MonkeyPatch) -> None:
    for ham, beklenen in (("", None), ("abc", None), ("0", None), ("-5", None), ("5400", 5400)):
        monkeypatch.setenv("TP_MANUAL_BASELINE_S", ham)
        assert baseline.varsayilan_s() == beklenen


def test_kapsam_metni_turkce_ekler() -> None:
    assert baseline.kapsam_metni(4, 3, 0, 1) == "4 story'den 3'ünde ölçüm var, 1'inde ölçülmedi"
    assert (
        baseline.kapsam_metni(4, 2, 2, 0)
        == "4 story'den 2'sinde ölçüm var, 2'sinde ölçüm yok (yalnız varsayılan "
        "TP_MANUAL_BASELINE_S; ölçüm sayılmaz)"
    )
    assert baseline.kapsam_metni(6, 0, 0, 6) == "6 story'den 0'ında ölçüm var, 6'sında ölçülmedi"
    ekler = {n: baseline.bulunma_eki(n) for n in (5, 7, 9, 10, 20, 40, 100, 1000)}
    assert ekler == {
        5: "inde",
        7: "sinde",
        9: "unda",
        10: "unda",
        20: "sinde",
        40: "ında",
        100: "ünde",
        1000: "inde",
    }


def test_kaynak_notu_en_az_uc_karakter(api: TestClient, make_user) -> None:
    """Portal (BAZ_NOT_EN_AZ=3) ile aynı kural: boşluk dışında en az 3 karakter, Türkçe 422."""
    rid = _req()
    login(api, make_user("analyst"))
    r = _put(api, rid, {"deger_s": 3600, "not": "a"})
    assert r.status_code == 422 and "en az 3 karakter" in r.json()["detail"]
    assert _put(api, rid, {"deger_s": 3600, "not": "a  b"}).status_code == 422
    r = _put(api, rid, {"deger_s": 3600, "not": "F0 "})
    assert r.status_code == 422
    r = _put(api, rid, {"deger_s": 3600, "not": "abc"})
    assert r.status_code == 200 and r.json()["baseline"]["not"] == "abc"
    # Silme notu isteğe bağlıdır; kısa not da kabul (zorunlu değil).
    assert api.delete(f"/requirements/{rid}/baseline", params={"not": "x"}).status_code == 200


def test_sure_metni() -> None:
    assert [baseline.sure_metni(x) for x in (2700, 2710, 5400, 3600, 45, 0)] == [
        "45 dk",
        "45 dk 10 sn",
        "1 sa 30 dk",
        "1 sa",
        "45 sn",
        "0 sn",
    ]

"""Akış kancaları: üretim/IDE eşlemesi, düzeltmede bilinmeyen atıf, serileştirme, yayın (Y4)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import case_icerik, latest_cases, login, run_jobs
from tp_core.audit import content_hash
from tp_core.features.cases.service import submit_drafts
from tp_core.features.publish import service as publish
from tp_core.features.testveri import service
from tp_core.gateway.testing import text_response
from tp_core.integrations.testmgmt import CaseContent, case_description_text
from tp_core.models import TestCase, session_scope
from tp_core.models.otomasyon_feature import TestVerisi
from tp_core.workflow.service import Principal

from .conftest import DEMO_PAROLA

PAROLA_ATFI = "{veri:ortak.demo_parola}"
BAYI_ATFI = "{veri:bayi.bayi1.kullanici_adi}"


def _uret(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, cases):
    fake_gateway([text_response({"cases": cases})])
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid, analist


def test_katalog_bossa_eslesme_yok(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    assert c["icerik"] == case_icerik() and c["icerik_hash"] == content_hash(case_icerik())
    assert c["veri"] == {}


def test_case_uretimi_eslenir_hash_eslenmis_icerikten(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    ham = case_icerik()
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [ham])
    (c,) = latest_cases(api, rid)
    adim = c["icerik"]["steps"][1]
    assert c["icerik"]["preconditions"] == [f"{BAYI_ATFI} kullanıcısı tanımlı"]
    assert adim["data"] == f"{BAYI_ATFI} / {PAROLA_ATFI}"
    assert DEMO_PAROLA not in str(c["icerik"])
    assert c["icerik"]["title"] == ham["title"]  # başlık değer kalır
    assert c["icerik_hash"] == content_hash(c["icerik"]) != content_hash(ham)
    # Serileştirme: atıf → değer (gizli → null), sürüm, var.
    assert c["veri"] == {
        "bayi.bayi1.kullanici_adi": {"deger": "bayi1", "gizli": False, "surum": 1, "var": True},
        "ortak.demo_parola": {"deger": None, "gizli": True, "surum": 1, "var": True},
        "etiket.katalog": {"deger": "Katalog", "gizli": False, "surum": 1, "var": True},
    }
    # Çözüm bugünkü metne döner.
    with session_scope() as s:
        cozulmus, izi = service.case_coz(s, c["icerik"])
    assert cozulmus == ham
    assert izi == {"bayi.bayi1.kullanici_adi": 1, "ortak.demo_parola": 1, "etiket.katalog": 1}


def test_ayni_icerik_yeniden_uretimde_tekrar_sayilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    """Katalogdan önce yazılmış (eşlenmemiş) onaylı case'in aynısı yeni taslak olarak düşmez."""
    with session_scope() as s:
        for k in s.scalars(select(TestVerisi)):
            k.silindi = True  # katalog "yokken" üret
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    assert c["veri"] == {}
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    with session_scope() as s:
        for k in s.scalars(select(TestVerisi)):
            k.silindi = False
    fake_gateway([text_response({"cases": [case_icerik()]})])
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.deger["case_sayisi"] == 0 and is_.deger["tekrar"] == [1]


def test_ide_taslaklari_da_eslenir(engine: Engine, make_user, make_requirement, katalog) -> None:
    make_requirement()
    analist = make_user("analyst")
    ide = Principal(analist.id, analist.kullanici_adi, "analyst", kanal="ide", kapsam="submit")
    with session_scope() as s:
        sonuc = submit_drafts(s, "TPD-4", [case_icerik()], ide)
    (e,) = sonuc["eklenen"]
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(e["case_id"]))
        assert tc.icerik["steps"][1]["data"] == f"{BAYI_ATFI} / {PAROLA_ATFI}"
        assert tc.icerik_hash == content_hash(tc.icerik)


def test_parola_sirri_yoksa_parola_eslenmez(
    api: TestClient,
    engine: Engine,
    make_user,
    make_requirement,
    fake_gateway,
    katalog,
    monkeypatch,
) -> None:
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["steps"][1]["data"] == f"{BAYI_ATFI} / {DEMO_PAROLA}"


def _duzelt(api: TestClient, c: dict[str, Any], icerik: dict[str, Any]):
    return api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "edit", "icerik_hash": c["icerik_hash"], "icerik": icerik},
    )


def test_duzeltmede_bilinmeyen_atif_422_duz_deger_kalir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    yeni = dict(c["icerik"], expected_result="{veri:bayi.yok.ad} kataloğu açılır")
    r = _duzelt(api, c, yeni)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Katalogda olmayan test verisi anahtarı: bayi.yok.ad")

    # Bilinen atıf eklenebilir; analistin yazdığı düz değer eşlenmez.
    yeni = dict(
        c["icerik"], expected_result="{veri:bayi.bayi1.ad} kataloğu açılır; Sahil Bayi değil"
    )
    r = _duzelt(api, c, yeni)
    assert r.status_code == 200, r.text
    (c2,) = latest_cases(api, rid)
    assert c2["icerik"]["expected_result"] == yeni["expected_result"]
    assert c2["veri"]["bayi.bayi1.ad"]["deger"] == "Merkez Bayi"


def test_katalog_degisince_onay_dusmez_veri_guncel(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200
    k = next(x for x in api.get("/test-data").json() if x["anahtar"] == "bayi.bayi1.kullanici_adi")
    r = api.put(f"/test-data/{k['id']}", json={"deger": "bayi1x", "beklenen_surum": 1})
    assert r.status_code == 200
    (c2,) = latest_cases(api, rid)
    assert c2["durum"] == "approved" and c2["icerik_hash"] == c["icerik_hash"]
    assert c2["veri"]["bayi.bayi1.kullanici_adi"] == {
        "deger": "bayi1x",
        "gizli": False,
        "surum": 2,
        "var": True,
    }


def test_yayinda_gizli_atif_korunur_digerleri_cozulur(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        mapping = publish.case_mapping(s, tc)
    assert mapping["steps"][1]["data"] == f"bayi1 / {PAROLA_ATFI}"
    assert mapping["preconditions"] == ["bayi1 kullanıcısı tanımlı"]
    metin = case_description_text(CaseContent.from_mapping(mapping), "TPD-4")
    assert PAROLA_ATFI in metin and DEMO_PAROLA not in metin and BAYI_ATFI not in metin
    # Önizleme (gönderilen gövdeyle aynı) da gizliyi açmaz.
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200
    on = api.get("/publish/preview", params={"requirement_id": str(rid)})
    assert on.status_code == 200 and DEMO_PAROLA not in on.text

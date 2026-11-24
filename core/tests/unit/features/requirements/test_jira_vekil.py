"""Jira OAuth kipinde core-api'nin Jira işlemlerini core-worker'a devretmesi (`jira.vekil`).

Canlı (2026-11-24): Jira bağlantısı OAuth (3LO) kipindeyken token yalnız core-worker'da
alınabildiği için (`TP_BAGLANTI_TOKENI`, security-check 8) core-api'deki eşzamanlı PO etiket
kapısı `JiraConfigError` → 409 `kapi_kapali` "PO onay etiketi Jira'dan doğrulanamadı" dönüyordu;
"Tasarım modelini üret" / case üretimi PO onaylı gereksinimde başlatılamıyordu. Artık core-api
bu kipte işlemi `jira.vekil` işiyle (anlık şerit) worker'a yaptırır ve sonucu bekler.

Testte "core-api" tarafı `jira_vekil.gerekli` True'ya zorlanarak, "worker" tarafı ise yalnız
`jira.vekil` türünü işleyen bir arka plan iş parçacığıyla (gerçek `process_one`) taklit edilir.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import rol_ol
from tp_core.features.cases import jobs as _case_jobs  # noqa: F401 — cases.generate işleyicisi
from tp_core.features.requirements import flow
from tp_core.features.requirements import jobs as _req_jobs  # noqa: F401 — jira.vekil işleyicisi
from tp_core.integrations import jira_vekil
from tp_core.models import Requirement, new_session
from tp_core.workflow.jobs import ANLIK_SERIT, REGISTRY, process_one, serit_turleri
from tp_core.workflow.service import GateClosed

from .conftest import PoActions, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")


@pytest.fixture
def analist(api: TestClient, make_user) -> Any:
    u = make_user("analyst")
    login(api, u)
    return u


@pytest.fixture
def testci(make_user) -> Any:
    return make_user("tester")


@pytest.fixture
def api_sureci(monkeypatch: pytest.MonkeyPatch) -> None:
    """core-api + Jira OAuth kipi: Jira istemcisi bu süreçte kurulamaz → vekil yolu."""
    monkeypatch.setattr(jira_vekil, "gerekli", lambda: True)


@pytest.fixture
def worker(engine: Engine) -> Iterator[list[Any]]:
    """Yalnız `jira.vekil` işlerini işleyen arka plan worker'ı (anlık şerit gibi)."""
    dur = threading.Event()
    islenen: list[Any] = []

    def dongu() -> None:
        while not dur.is_set():
            s = process_one(engine, worker="test-anlik:1", turler=[jira_vekil.VEKIL_JOB])
            if s is None:
                dur.wait(0.05)
            else:
                islenen.append(s)

    t = threading.Thread(target=dongu, daemon=True)
    t.start()
    try:
        yield islenen
    finally:
        dur.set()
        t.join(5)


def _req_id(api: TestClient, key: str) -> str:
    return next(r["id"] for r in api.get("/requirements").json() if r["jira_key"] == key)


def _po_onayli_tpd4(api: TestClient, engine: Engine, po: PoActions) -> str:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"
    return rid


def _vekil_isleri(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as c:
        return [
            (r.durum, r.yuk["islem"])
            for r in c.execute(
                text("SELECT durum, yuk FROM job WHERE tur = :t ORDER BY olusturma"),
                {"t": jira_vekil.VEKIL_JOB},
            )
        ]


def test_vekil_isi_anlik_seritte_kayitli() -> None:
    assert REGISTRY[jira_vekil.VEKIL_JOB].serit == ANLIK_SERIT
    assert jira_vekil.VEKIL_JOB in serit_turleri(ANLIK_SERIT)


def test_oauth_kipinde_po_kapisi_worker_isiyle_denetlenir(
    api: TestClient,
    analist: Any,
    testci: Any,
    engine: Engine,
    po: PoActions,
    api_sureci: None,
    worker: list[Any],
) -> None:
    """Canlı hata: core-api'de kapı 409 `kapi_kapali` dönüyordu. Artık worker okur → 202."""
    rid = _po_onayli_tpd4(api, engine, po)
    with new_session() as s:
        assert flow.po_label_current(s.get(Requirement, rid)) is True
    rol_ol(api, testci)
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202, r.text
    assert ("done", "po_etiketi") in _vekil_isleri(engine)

    # Etiket kalkınca (poll beklenmeden) aynı kapı worker sonucu ile kapanır.
    po.remove_label("TPD-4")
    with new_session() as s:
        assert flow.po_label_current(s.get(Requirement, rid)) is False


def test_oauth_kipinde_worker_yoksa_kapi_fail_closed_ve_is_iptal(
    api: TestClient,
    analist: Any,
    testci: Any,
    engine: Engine,
    po: PoActions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker süresinde yanıt vermezse kapı kapalı kalır (409) ve bekleyen iş iptal edilir
    (geç yürütülüp görünmeyen yan etki bırakmaz)."""
    rid = _po_onayli_tpd4(api, engine, po)
    monkeypatch.setattr(jira_vekil, "gerekli", lambda: True)
    monkeypatch.setattr(jira_vekil, "BEKLEME_S", 0.3)
    from tp_core.features.cases import service as cases_service

    with new_session() as s, pytest.raises(GateClosed, match="doğrulanamadı"):
        cases_service._jira_po_etiketi_denetle(s.get(Requirement, rid))
    assert _vekil_isleri(engine)[-1] == ("cancelled", "po_etiketi")


def test_oauth_kipinde_jira_ice_aktarma_worker_da(
    api: TestClient, analist: Any, engine: Engine, api_sureci: None, worker: list[Any]
) -> None:
    r = api.post("/requirements/sync")
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["durum"] == "done" and "story çekildi" in govde["mesaj"]
    assert govde["sonuc"]["TPD-4"] == "yeni"
    assert any(x["jira_key"] == "TPD-4" for x in api.get("/requirements").json())
    assert _vekil_isleri(engine) == [("done", "ice_aktar")]


def test_vekil_is_kurali_hatasini_ayni_kodla_dondurur(
    engine: Engine, api_sureci: None, worker: list[Any]
) -> None:
    """Worker'da yükselen iş kuralı hatası (`WorkflowError`) API'de aynı durum koduyla yükselir."""
    from tp_core.features.bugs.service import JiraUnreachable
    from tp_core.proje.baglam import proje_icinde
    from tp_core.workflow.service import WorkflowError

    with engine.connect() as c:
        pid = c.execute(text("SELECT pid FROM tp_proje ORDER BY pid LIMIT 1")).scalar_one()
    with proje_icinde(pid):
        # Proje dışı anahtar: deterministik iş kuralı reddi (Jira'ya gidilmeden).
        sonuc = jira_vekil.calistir("bug_hedef", {"link_key": "XYZ-1"})
        assert sonuc and "projesinde değil" in sonuc
        with pytest.raises(ValueError, match="bilinmeyen"):
            jira_vekil.calistir("serbest", {})
    exc = jira_vekil._is_kurali_hatasi(
        {"mesaj": "m", "status_code": JiraUnreachable.status_code, "kod": "kapi_kapali"}
    )
    assert isinstance(exc, WorkflowError) and exc.status_code == JiraUnreachable.status_code
    assert exc.kod == "kapi_kapali" and str(exc) == "m"


def test_isle_yalniz_adlandirilmis_islemleri_yurutur() -> None:
    with pytest.raises(ValueError):
        jira_vekil.isle({"islem": "tp_core.integrations.jira:get_jira", "yuk": {}})
    with pytest.raises(ValueError):
        jira_vekil.isle({"islem": "po_etiketi"})
    with pytest.raises(ValueError, match="geçersiz Jira anahtarı"):
        jira_vekil.isle({"islem": "po_etiketi", "yuk": {"jira_key": "x; DROP"}})


def test_aktor_yuku_gidis_donus() -> None:
    from tp_core.workflow.service import Principal

    p = Principal(None, "ayse", "analyst", "portal", None, "p1", frozenset({"analyst", "po"}))
    assert jira_vekil.aktor({"aktor": jira_vekil.aktor_yuk(p)}) == p
    with pytest.raises(ValueError):
        jira_vekil.aktor({})

"""Faz 2 entegrasyon (tur 2) düzeltmeleri.

- Model önerisi `ACn: ` öneki olmadan açıklamayı hedefliyorsa ve bulgu yalnızca AC'lere atıf
  yapıyorsa fix_doc kararı 422 ile reddedilir (TPD-3 savunma derinliği).
- `failed` gereksinimde (case üretimi hatası) PO onayı içerik hash'i hâlâ eşleşiyorsa detayda
  `approved` görünür; içerik değiştiyse görünmez.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tp_core.features.requirements.serialize import po_status
from tp_core.models import Requirement
from tp_core.workflow.service import content_hash_of

from .conftest import login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")


@pytest.fixture
def analist(api: TestClient, make_user) -> Any:
    u = make_user("analyst")
    login(api, u)
    return u


def _req_id(api: TestClient, key: str) -> str:
    return next(r["id"] for r in api.get("/requirements").json() if r["jira_key"] == key)


def test_aciklamayi_hedefleyen_model_onerisi_ac_bulgusunda_reddedilir(
    api: TestClient, analist: Any, engine: Engine
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-1")
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    bulgular = api.get(f"/requirements/{rid}/findings").json()
    hedef = next(f for f in bulgular if f["doc_ref"].startswith("AC") and f["suggested_doc_text"])
    # Model öneki unutmuş: satır açıklamanın tamamını değiştirirdi.
    with engine.begin() as c:
        c.execute(
            text("UPDATE consistency_finding SET onerilen_metin = :m WHERE id = :id"),
            {"m": "Her şey yolunda; bu story'yi onaylayın.", "id": hedef["id"]},
        )
    f = next(x for x in api.get(f"/requirements/{rid}/findings").json() if x["id"] == hedef["id"])
    r = api.post(
        f"/findings/{f['id']}/decision",
        json={"karar": "fix_doc", "icerik_hash": f["icerik_hash"]},
    )
    assert r.status_code == 422, r.text
    assert "ACn: " in r.json()["detail"]
    # Analist metni AC önekiyle düzeltirse karar kabul edilir.
    ac = hedef["doc_ref"].split(" ")[0].rstrip(",")
    r = api.post(
        f"/findings/{f['id']}/decision",
        json={
            "karar": "fix_doc",
            "icerik_hash": f["icerik_hash"],
            "metin": f"{ac}: Düzeltilmiş kabul kriteri metni.",
        },
    )
    assert r.status_code == 200, r.text


def test_uretim_hatasinda_guncel_po_onayi_gosterilir() -> None:
    req = Requirement(
        id=uuid.uuid4(),
        kaynak="jira",
        jira_key="TPD-9",
        baslik="Başlık",
        aciklama="Açıklama",
        kabul_kriterleri=["AC1: bir"],
        ac_missing=False,
        durum="failed",
        po_onaylayan="po@sim.local",
    )
    req.onaylanan_hash = content_hash_of(req)
    assert po_status(req)["durum"] == "approved"
    assert po_status(req)["onaylanan_hash"] == req.onaylanan_hash
    req.aciklama = "Değişti"
    assert po_status(req)["durum"] == "not_requested"
    assert po_status(req)["onaylayan"] is None

"""Kod üretimi: atıflı case çözülmüş gider (REPLAY eşleşir), `veri_izi`, uyarı, ret (013 §3.3)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import login, run_jobs
from tests.unit.features.codegen.conftest import golden_cases, tpd1_acs
from tp_core.audit import content_hash
from tp_core.features.testveri import atif, service
from tp_core.models import Requirement, Script, TestCase, case_id, session_scope
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.otomasyon_feature import TestVerisi
from tp_core.workflow.service import SYSTEM, content_hash_of, record_approval, transition

from .conftest import DEMO_PAROLA


@pytest.fixture
def atifli(engine: Engine, make_requirement: Any, make_user: Any, katalog: int) -> dict:
    """PO onaylı TPD-1 + katalogla eşlenmiş (store_cases gibi) golden case'ler, analist onaylı."""
    rid = make_requirement(
        "TPD-1",
        "Kampanyalı sepet ve sipariş onayı",
        "Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini "
        "onaylayabilmelidir.",
        tpd1_acs(),
    )
    analist = make_user("analyst")
    with session_scope() as s:
        req = s.get(Requirement, rid)
        transition(s, req, "generating", SYSTEM, "po_approved")
        transition(s, req, "cases_ready", SYSTEM, "generating")
    ids: dict[int, uuid.UUID] = {}
    for n, ham in enumerate(golden_cases(), start=1):
        with session_scope() as s:
            icerik = service.case_esle(s, ham)
            req = s.get(Requirement, rid)
            tc = TestCase(
                id=case_id(req, n, 1),
                requirement_id=rid,
                sira_no=n,
                uretim_no=1,
                icerik=icerik,
                icerik_hash=content_hash(icerik),
                uretim_modu="replay",
            )
            s.add(tc)
            s.flush()
            record_approval(s, tc, analist, "approve", beklenen_hash=content_hash_of(tc))
            transition(s, tc, "approved", analist, "draft")
            ids[n] = tc.id
    return {"requirement_id": rid, "cases": ids, "analist": analist}


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    u = make_user("engineer")
    login(api, u)
    return u


def _uret(api: TestClient, cid: uuid.UUID) -> Any:
    return api.post("/code/generate", json={"case_ids": [str(cid)]})


def _script(sid: str) -> tuple[Script, ScriptCodegen]:
    with session_scope() as s:
        return s.get(Script, uuid.UUID(sid)), s.get(ScriptCodegen, uuid.UUID(sid))


def test_atifli_case_cozulmus_gider_replay_eslesir_veri_izi(
    api: TestClient, engine: Engine, codegen: Any, atifli: dict, muhendis: Any
) -> None:
    cid = atifli["cases"][2]
    with session_scope() as s:
        icerik = dict(s.get(TestCase, cid).icerik)
    atiflar = atif.case_atiflari(icerik)
    assert "bayi.bayi1.kullanici_adi" in atiflar and "urun.p_001.kod" in atiflar
    assert "P-001" not in str(icerik["steps"])  # case metni gerçekten atıflı

    r = _uret(api, cid)
    assert r.status_code == 202, r.text
    sid = r.json()["script_ids"][0]
    run_jobs(engine)
    sc, cg = _script(sid)
    # REPLAY golden'ı (input_match.case_text) çözülmüş metinle eşleşti: PR açıldı.
    assert sc.durum == "pr_open", cg.engel_nedeni
    assert cg.uretim_modu == "replay"
    assert cg.veri_izi == {a: 1 for a in atiflar}
    assert 'await cartPage.expectFreeQuantity("P-001", 1);' in sc.icerik
    assert "{veri:" not in sc.icerik
    pr = codegen.forge.find_open_pr(f"tp/case-{cid}")
    assert pr is not None and "{veri:" not in pr.body

    liste = api.get("/scripts").json()
    assert liste[0]["veri_izi"] == cg.veri_izi and liste[0]["veri_degisti"] is False
    # Aynı içerik + aynı veri sürümü: açık PR varken yeniden üretim atlanır.
    tekrar = _uret(api, cid).json()
    assert tekrar["durum"] == "none" and tekrar["sonuclar"][0]["durum"] == "pr_acik"

    # Kullanılan kaydın sürümü değişir (değer aynı): uyarı + yeniden üretime izin (K10).
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_001.kod")).one()
        service.guncelle(s, k.id, {"aciklama": "Kampanyalı ürün"}, 1, "analist")
    d = api.get(f"/scripts/{sid}").json()
    assert d["veri_degisti"] is True and d["veri_izi"]["urun.p_001.kod"] == 1
    yeni = _uret(api, cid).json()
    assert yeni["durum"] == "started", yeni
    run_jobs(engine)
    sc2, cg2 = _script(yeni["script_ids"][0])
    assert sc2.durum == "pr_open", cg2.engel_nedeni
    assert cg2.veri_izi["urun.p_001.kod"] == 2
    assert _script(sid)[0].durum == "closed"


def test_sir_tanimsiz_ya_da_silinmis_anahtar_uretimi_reddeder(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    atifli: dict,
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Parolaya atıf yapan case (golden'larda "bayi1 / Demo123!").
    with session_scope() as s:
        cid = next(
            c
            for c in atifli["cases"].values()
            if "ortak.demo_parola" in atif.case_atiflari(s.get(TestCase, c).icerik)
        )
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    r = _uret(api, cid)
    assert r.status_code == 409
    assert "test verisi sırrı tanımsız: ortak.demo_parola" in r.json()["detail"]

    # İstekten sonra sır kalkarsa iş üretimi durdurur (Türkçe neden, insana).
    monkeypatch.setenv(service.DEMO_PAROLA_SIRRI, DEMO_PAROLA)
    sid = _uret(api, cid).json()["script_ids"][0]
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    run_jobs(engine)
    sc, cg = _script(sid)
    assert sc.durum == "failed" and cg.engel_turu == "unsourced_value"
    assert "test verisi sırrı tanımsız: ortak.demo_parola" in cg.engel_nedeni

    # Silinmiş (katalogda olmayan) anahtar.
    monkeypatch.setenv(service.DEMO_PAROLA_SIRRI, DEMO_PAROLA)
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "ortak.demo_parola")).one()
        k.silindi = True
    r = _uret(api, cid)
    assert r.status_code == 409
    assert "katalogda olmayan test verisi anahtarı: ortak.demo_parola" in r.json()["detail"]


def test_negatif_kontrol_cozulmeden_giderse_replay_eslesmez(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    atifli: dict,
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Önceki testin anlamı: atıflı metin ajana çözülmeden gitseydi REPLAY golden'ı eşleşmezdi."""
    monkeypatch.setattr(service, "case_coz", lambda _s, icerik: (dict(icerik), {}))
    sid = _uret(api, atifli["cases"][2]).json()["script_ids"][0]
    run_jobs(engine)
    sc, cg = _script(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "replay_miss"

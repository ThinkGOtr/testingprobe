"""011 canlı eval sonrası: şemaya uyan ama kural ihlalli üretim çıktısında geçit modelden
düzeltme ister (`Gateway.call(output_check=…)`); döngü bitince yalnız kural ihlali kalırsa
çıktı yine döner."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tp_core.features.cases.schema import generation_output_problems
from tp_core.gateway.testing import text_response

from .helpers import case_icerik, latest_cases, login, run_jobs, uretim_cikti


def _tutarsiz() -> dict:
    c = case_icerik()
    c["readiness"] = "ready"
    c["open_question_refs"] = ["Q9"]  # tanımsız soru + hazır case'te atıf: iki ihlal
    return uretim_cikti([c])


def test_kural_ihlali_duzeltme_istenir_ve_duzeltilmis_cikti_yazilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    duzgun = uretim_cikti([case_icerik()])
    provider = fake_gateway([text_response(_tutarsiz()), text_response(duzgun)])
    rid = make_requirement(acs=["AC1: Bayi giriş yapar."])
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    assert len(provider.requests) == 2
    ikinci = provider.requests[1].messages[-1]["content"]
    assert "consistency rules" in ikinci and "Q9" in ikinci
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["open_question_refs"] == []


def test_duzelmezse_cikti_yine_doner_ve_uyari_kalir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    fake_gateway([text_response(_tutarsiz())] * 3)
    rid = make_requirement(acs=["AC1: Bayi giriş yapar."])
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/generate-cases")
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    assert is_.deger["tutarsiz"]  # onay engeli / uyarı akışı devrede
    (c,) = latest_cases(api, rid)
    assert c["onay_engeli"]


@pytest.mark.parametrize("anahtar", ["off", "OFF"])
def test_anahtar_kapali_iken_tek_cagri(
    anahtar, api, engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", anahtar)
    provider = fake_gateway([text_response(_tutarsiz())])
    rid = make_requirement(acs=["AC1: Bayi giriş yapar."])
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    assert len(provider.requests) == 1


def test_korunan_case_kapsadigi_ac_eksik_sayilmaz() -> None:
    cikti = json.loads(json.dumps(uretim_cikti([case_icerik()])))
    acs = ["AC1: x", "AC2: y"]
    korunan = [case_icerik(ref="AC2", title="Korunan")]
    assert any("AC2" in p for p in generation_output_problems(cikti, acs))
    assert not any("AC2" in p for p in generation_output_problems(cikti, acs, korunan=korunan))

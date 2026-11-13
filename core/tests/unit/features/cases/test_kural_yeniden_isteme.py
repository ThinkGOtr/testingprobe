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
    login(api, make_user("tester"))
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
    login(api, make_user("tester"))
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
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    assert len(provider.requests) == 1


def test_korunan_case_kapsadigi_ac_eksik_sayilmaz() -> None:
    cikti = json.loads(json.dumps(uretim_cikti([case_icerik()])))
    acs = ["AC1: x", "AC2: y"]
    korunan = [case_icerik(ref="AC2", title="Korunan")]
    assert any("AC2" in p for p in generation_output_problems(cikti, acs))
    assert not any("AC2" in p for p in generation_output_problems(cikti, acs, korunan=korunan))


# ------------------------------------------- inceleme tur 2: anahtar açıkken akış etkileşimleri


def _bekleyen_isi_hemen(engine: Engine) -> None:
    from sqlalchemy import text

    with engine.begin() as c:
        c.execute(text("UPDATE job SET run_after = now() WHERE durum = 'retry'"))


def test_is_suresi_yetmezse_yeniden_istemez_cikti_uyariyla_doner(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    import tp_core.gateway.core as gecit

    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    monkeypatch.setattr(gecit, "kalan_sure", lambda: 1.0)  # iş süresinin sonuna gelinmiş
    provider = fake_gateway([text_response(_tutarsiz())])
    rid = make_requirement(acs=["AC1: Bayi giriş yapar."])
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    assert len(provider.requests) == 1
    assert any("kalan süresi" in u for u in is_.deger["uyarilar"])
    assert is_.deger["tutarsiz"]  # ihlal onay engeliyle kalır
    (c,) = latest_cases(api, rid)
    assert c["onay_engeli"]


def test_is_yeniden_denemesi_kural_ihlalli_ara_ciktiyi_kullanmaz(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    from tp_core.gateway.errors import ProviderRefusal

    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    duzgun = uretim_cikti([case_icerik()])
    provider = fake_gateway(
        [text_response(_tutarsiz()), ProviderRefusal("ret"), text_response(duzgun)]
    )
    rid = make_requirement(acs=["AC1: Bayi giriş yapar."])
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    (ilk,) = run_jobs(engine)
    assert ilk.durum == "retry", ilk
    _bekleyen_isi_hemen(engine)
    (ikinci,) = run_jobs(engine)
    assert ikinci.durum == "done", ikinci
    assert len(provider.requests) == 3  # ihlalli 1. deneme "tamamlanmış" sayılmadı
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["open_question_refs"] == [] and not c["onay_engeli"]


def test_hazir_casein_dusen_soru_atfi_uyariya_yazilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    ilk = case_icerik()
    ilk["readiness"] = "ready"
    ilk["open_question_refs"] = ["Q1"]  # hazır case'te açık soru atfı: kural ihlali
    sorulu = uretim_cikti(
        [ilk], open_questions=[{"id": "Q1", "question": "Kilit süresi?", "owner": "PO"}]
    )
    duzgun = uretim_cikti(
        [case_icerik()], open_questions=[{"id": "Q1", "question": "Kilit süresi?", "owner": "PO"}]
    )
    fake_gateway([text_response(sorulu), text_response(duzgun)])
    rid = make_requirement(acs=["AC1: Bayi giriş yapar."])
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    assert any("açık soru atfı silinen hazır" in u and "Q1" in u for u in is_.deger["uyarilar"])


def test_korunan_case_kapsami_yeniden_istemeye_yol_acmaz(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    """AC2'yi korunan (onaylı) case kapsıyorsa yeni üretimde AC2 eksikliği ihlal sayılmaz."""
    from tp_core.features.cases.service import generation_check

    korunan = [case_icerik(ref="AC2", title="Korunan")]
    cikti = json.loads(json.dumps(uretim_cikti([case_icerik()])))
    acs = ["AC1: x", "AC2: y"]
    assert any("AC2" in p for p in generation_check(acs, [], None)(cikti))
    assert not any("AC2" in p for p in generation_check(acs, korunan, None)(cikti))


def _golden(ad: str, amac: str) -> dict:
    from pathlib import Path

    kok = Path(__file__).resolve().parents[5] / "rules" / "replay"
    return json.loads((kok / amac / "golden" / f"{ad}.json").read_text())


def test_tur2_onayli_modelden_sapma_yeniden_istenir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    import tp_core.features.tasarim_modeli.jobs  # noqa: F401  (model.generate işleyicisi)

    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    model = _golden("TPD-4", "design_model")["output"]
    cases = _golden("TPD-4", "case_generation")["output"]
    sapan = json.loads(json.dumps(cases))
    sapan["coverage_items"] = sapan["coverage_items"][:-1]  # onaylı modelden bir öğe eksik
    provider = fake_gateway([text_response(model), text_response(sapan), text_response(cases)])
    rid = make_requirement()
    login(api, make_user("tester"))
    assert (
        api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"}).status_code == 202
    )
    run_jobs(engine)
    m = api.get(f"/requirements/{rid}/design-model").json()["model"]
    r = api.post(
        f"/design-models/{m['id']}/decision",
        json={"karar": "approve", "icerik_hash": m["icerik_hash"]},
    )
    assert r.status_code == 200, r.text
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    assert len(provider.requests) == 3
    reask = provider.requests[2].messages[-1]["content"]
    assert "approved design model" in reask and "coverage_items" in reask
    assert is_.deger["tur2_farklari"] == []


def test_derinlestirme_kural_ihlalinde_yeniden_ister(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, monkeypatch
) -> None:
    ilk = [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2", type="negative")]
    kotu = case_icerik(title="Ana akış — oturum süresi", covers=["UC-MF"])
    kotu["readiness"] = "ready"
    kotu["open_question_refs"] = ["Q9"]  # tanımsız soru + hazır case'te atıf
    iyi = case_icerik(title="Ana akış — oturum süresi", covers=["UC-MF"])
    provider = fake_gateway(
        [
            text_response(uretim_cikti(ilk)),
            text_response(uretim_cikti([kotu], coverage_items=[])),
            text_response(uretim_cikti([iyi], coverage_items=[])),
        ]
    )
    rid = make_requirement()
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "on")
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"}).status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_.hata
    assert len(provider.requests) == 3
    assert "Q9" in provider.requests[2].messages[-1]["content"]
    assert is_.deger["tutarsiz"] == {}


def test_derinlestirme_mevcut_case_atfini_gorur() -> None:
    """Tur 3 inceleme #8: derinleştirme mevcut bir soruyu (Q1) yeniden listeler ama yeni case'ler
    ona atıf yapmaz; Q1'e mevcut case atıf yapıyorsa soru yetim değildir, yeniden istenmez."""
    from tp_core.features.cases.deepen import _kural_denetimi

    soru = [{"id": "Q1", "question": "Kaç denemede kilitlenir?", "owner": "PO"}]
    mevcut = case_icerik(
        title="Kilitli hesap",
        readiness="blocked",
        open_question_refs=["Q1"],
        expected_result="",
    )
    birlesik = uretim_cikti([mevcut], open_questions=soru)
    birlesik.pop("cases")
    yeni = json.loads(
        json.dumps(
            uretim_cikti(
                [case_icerik(title="Ana akış — oturum süresi", covers=["UC-MF"])],
                open_questions=soru,
                coverage_items=[],
            )
        )
    )

    def yetim(sorunlar: list[str]) -> list[str]:
        return [p for p in sorunlar if "Q1" in p and "yetim" in p]

    assert yetim(_kural_denetimi()(yeni))  # yalnız çıktıya bakan denetim: yetim
    assert yetim(_kural_denetimi(birlesik)(yeni))  # birleşik özet atfı taşımaz
    assert yetim(_kural_denetimi(birlesik, [mevcut])(yeni)) == []

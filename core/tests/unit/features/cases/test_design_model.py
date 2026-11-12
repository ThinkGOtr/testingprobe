"""İki tur (011 F3): test tasarım modeli — golden'lar, model kontrolleri, akış, kararlar, tur 2."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

import tp_core.features.tasarim_modeli.jobs  # noqa: F401  (model.generate işleyicisi)
from tp_core.features.cases.model import (
    model_problems,
    model_summary,
    round2_differences,
    validate_model,
)
from tp_core.features.requirements.flow import apply_content_change
from tp_core.gateway.testing import text_response
from tp_core.models import AiCall, AuditEvent, Requirement, Review, TasarimModeli, session_scope
from tp_core.workflow.service import SYSTEM

from .helpers import TPD4, case_icerik, latest_cases, login, run_jobs, uretim_cikti

RULES = Path(__file__).resolve().parents[5] / "rules"
GOLDENS = sorted((RULES / "replay" / "design_model" / "golden").rglob("*.json"))


def _golden(ad: str, amac: str = "design_model") -> dict[str, Any]:
    return json.loads((RULES / "replay" / amac / "golden" / f"{ad}.json").read_text())


# ------------------------------------------------------------------ golden'lar (DB yok)


def test_golden_seti_tam() -> None:
    assert {p.stem for p in GOLDENS} == {"TPD-1", "TPD-3", "TPD-4", "SERBEST"}
    assert any(p.parent.name == "f2-kod-hatasi" for p in GOLDENS)


@pytest.mark.parametrize("yol", GOLDENS, ids=lambda p: p.parent.name + "/" + p.stem)
def test_golden_sema_model_kontrolu_ve_tur2_esitligi(yol: Path) -> None:
    d = json.loads(yol.read_text())
    ad = str(yol.relative_to(RULES / "replay" / "design_model" / "golden"))[: -len(".json")]
    case_golden = _golden(ad, "case_generation")
    assert d["purpose"] == "design_model" and d["golden"] == ad
    assert d["input_match"] == case_golden["input_match"]
    assert validate_model(d["output"]) == []
    assert model_problems(d["output"], d["input_match"]["acceptance_criteria"]) == []
    # Tur-2 eşitliği: üst listeler case golden'ıyla birebir aynı (REPLAY'de uyarı çıkmaz).
    assert round2_differences(d["output"], case_golden["output"]) == []
    assert model_summary(d["output"]) == {
        k: case_golden["output"][k] for k in ("coverage_items", "open_questions", "assumptions")
    }


@pytest.mark.parametrize(
    ("ad", "boz", "beklenen"),
    [
        ("cift_oge", lambda m: m["coverage_items"].append(m["coverage_items"][0]), "yinelenen"),
        ("tanimsiz_oge", lambda m: m["partitions"][0].update(item_id="EP-V99"), "olmayan öğe"),
        (
            "teknik_kosulsuz",
            lambda m: m["techniques"][0].update(condition_id="TCOND-99"),
            "tanımsız koşul",
        ),
        (
            "kosul_tekniksiz",
            lambda m: m["conditions"].append({**m["conditions"][0], "id": "TCOND-9"}),
            "teknik seçilmemiş",
        ),
        ("gecerlilik", lambda m: m["partitions"][4].update(valid=True), "çelişiyor"),
        (
            "ret_sinir_gecerli",
            lambda m: m["boundaries"][5].update(expected="accept"),
            "kabul edilen sınır",
        ),
        (
            "acik_soru_yok",
            lambda m: m["boundaries"][0].update(expected="open_question", inclusive_source=None),
            "open_questions boş",
        ),
        ("onek", lambda m: m["boundaries"][0].update(item_id="EP-V1"), "tekniğine uymuyor"),
        ("ayrintisiz", lambda m: m.update(flows=[]), "UC-MF: ayrıntılı modelde yok"),
        ("ac", lambda m: m["conditions"][0].update(ac_refs=["AC9"]), "AC9"),
    ],
)
def test_model_kontrolleri_bozulmayi_yakalar(ad: str, boz: Any, beklenen: str) -> None:
    m = copy.deepcopy(_golden("TPD-1")["output"])
    boz(m)
    acs = _golden("TPD-1")["input_match"]["acceptance_criteria"]
    sorunlar = model_problems(m, acs)
    assert any(beklenen in s for s in sorunlar), (ad, sorunlar)


def test_tur2_farki_raporlanir() -> None:
    m = _golden("TPD-4")["output"]
    ozet = copy.deepcopy(model_summary(m))
    ozet["coverage_items"].pop()
    ozet["open_questions"].append({"id": "Q1", "question": "Yeni soru", "owner": "PO"})
    farklar = round2_differences(m, ozet)
    assert any("coverage_items" in f and "eksik: EP-I2" in f for f in farklar)
    assert any("open_questions" in f and "fazla: Q1" in f for f in farklar)


# ------------------------------------------------------------------------- akış


def _durum(rid: uuid.UUID) -> str:
    with session_scope() as s:
        return s.get(Requirement, rid).durum


def _model(api: TestClient, rid: uuid.UUID) -> dict[str, Any]:
    r = api.get(f"/requirements/{rid}/design-model")
    assert r.status_code == 200, r.text
    return r.json()


def _karar(api: TestClient, model: dict[str, Any], karar: str, **ek: Any) -> Any:
    return api.post(
        f"/design-models/{model['id']}/decision",
        json={"karar": karar, "icerik_hash": model["icerik_hash"], **ek},
    )


def test_iki_tur_replay_uctan_uca(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    assert r.status_code == 202, r.text
    assert r.json()["kip"] == "iki_tur" and r.json()["asama"] == "model"
    assert _durum(rid) == "modeling"
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_.hata
    assert _durum(rid) == "model_ready"

    gorunum = _model(api, rid)
    m = gorunum["model"]
    assert (
        m["durum"] == "draft" and m["surum"] == 1 and m["guncel"] and m["uretim_modu"] == "replay"
    )
    assert m["icerik"] == _golden("TPD-4")["output"]
    assert m["sorunlar"] == [] and m["onay_engeli"] is None
    assert m["ozet"]["oge"] == 3 and m["ozet"]["teknik"] == {"EP": 2}
    assert gorunum["case_uretimi_hazir"] is False and gorunum["engel"]

    # Onaysız modelle tur 2 başlatılamaz.
    r = api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    assert r.status_code == 409 and "Onaylı tasarım modeli yok" in r.text
    # Görülen hash zorunlu ve güncel olmalı.
    assert _karar(api, {**m, "icerik_hash": "eski"}, "approve").status_code == 409
    r = _karar(api, m, "approve")
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "approved" and r.json()["onaylanan_hash"] == m["icerik_hash"]
    assert r.json()["kararlar"][0]["karar"] == "approve"
    # K20: onay tur 2'yi aynı işlemde başlatır (ayrı "Case üret" yok).
    assert r.json()["tur2_baslatildi"] is True and r.json()["tur2_engeli"] is None
    assert r.json()["tur2"]["asama"] == "case" and r.json()["tur2"]["uretim_no"] == 1
    assert r.json()["tur2"]["job_id"] and r.json()["tur2"]["kip"] == "iki_tur"
    assert _durum(rid) == "generating"
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_.hata
    assert is_.deger["tur2_farklari"] == [] and not any("sapma" in u for u in is_.deger["uyarilar"])
    assert _durum(rid) == "cases_ready"
    cases = latest_cases(api, rid)
    assert [c["icerik"] for c in cases] == _golden("TPD-4", "case_generation")["output"]["cases"]
    with session_scope() as s:
        ai = s.scalars(select(AiCall).order_by(AiCall.olusturma)).all()
        # Üretimden sonra otomatik review (011 F2, K4) kuyruğa girer; sıra ilk ikide sabittir.
        assert [a.amac for a in ai][:2] == ["design_model", "case_generation"]
        assert {a.amac for a in ai} <= {"design_model", "case_generation", "case_review"}
        assert {a.mod for a in ai} == {"replay"}
        girdi = json.dumps(ai[1].maskeli_girdi, ensure_ascii=False)
        assert 'source=\\"tasarim-modeli:jira:TPD-4\\"' in girdi
        assert "Onaylı test tasarım modeli" in girdi
        rev = s.scalars(select(Review).where(Review.nesne_turu == "design_model")).one()
        assert rev.karar == "approve"
        olay = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.generated")).one()
        assert olay.ozet["kip"] == "iki_tur" and olay.ozet["tasarim_modeli_id"] == m["id"]


def test_govdesiz_cagri_tek_tur(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202 and r.json()["kip"] == "tek_tur" and r.json()["asama"] == "case"
    assert _durum(rid) == "generating"
    r = api.post(f"/requirements/{rid}/generate-cases", json={"kip": "tek_tur"})
    assert r.status_code == 409  # üretim sürüyor


def test_replay_miss_model_failed(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement(acs=[*TPD4["acs"], "AC3: Yeni madde"])
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/design-model").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "failed" and "REPLAY-MISS" in (is_.hata or "")
    assert _durum(rid) == "failed"
    assert _model(api, rid)["model"] is None
    # failed'dan yeniden model üretimi başlatılabilir.
    assert api.post(f"/requirements/{rid}/design-model").status_code == 202


def _bozuk_model() -> dict[str, Any]:
    m = copy.deepcopy(_golden("TPD-4")["output"])
    m["partitions"][1]["valid"] = True  # EP-I1 öğesi valid:false → çelişki
    return m


def test_tutarsiz_model_onaylanamaz_duzelt_ve_ret(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response(_bozuk_model()), text_response(_golden("TPD-4")["output"])])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/design-model").status_code == 202
    run_jobs(engine)
    m = _model(api, rid)["model"]
    assert m["sorunlar"] and m["onay_engeli"]
    r = _karar(api, m, "approve")
    assert r.status_code == 422 and "çelişiyor" in r.text
    # Düzeltme de tutarsızsa 422 (hiçbir şey kaydedilmez).
    r = _karar(api, m, "edit", icerik=m["icerik"])
    assert r.status_code == 422
    # Ret → yeniden üretim (model_ready → modeling) → yeni sürüm; eskisi superseded.
    r = _karar(
        api, m, "reject", ret_nedeni="wrong_coverage_item", gerekce="bölüm geçerliliği yanlış"
    )
    assert r.status_code == 200 and r.json()["durum"] == "rejected"
    assert r.json()["tur2_baslatildi"] is False
    assert _durum(rid) == "model_ready"
    assert (
        api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"}).status_code == 409
    )
    assert api.post(f"/requirements/{rid}/design-model").status_code == 202
    run_jobs(engine)
    gorunum = _model(api, rid)
    assert gorunum["model"]["surum"] == 2 and gorunum["model"]["sorunlar"] == []
    assert [g["durum"] for g in gorunum["gecmis"]] == ["draft", "superseded"]

    # Alan bazlı düzeltme: soru ekle → onaylanır, düzeltme ölçüsü kaydedilir.
    m2 = gorunum["model"]
    yeni = copy.deepcopy(m2["icerik"])
    yeni["open_questions"].append(
        {"id": "Q1", "question": "Kayıtlı olmayan kullanıcı adında ne gösterilir?", "owner": "PO"}
    )
    r = _karar(api, m2, "edit", icerik=yeni)
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "approved" and r.json()["icerik"] == yeni
    with session_scope() as s:
        rev = s.scalars(
            select(Review).where(Review.nesne_turu == "design_model", Review.karar == "edit")
        ).one()
        assert rev.duzeltme_olculeri["degisen_alanlar"] == ["open_questions"]
        assert rev.duzeltme_olculeri["soru_farki"] == 1
        assert rev.onaylanan_hash != m2["icerik_hash"]


def test_tur2_sapmasi_uyari_ve_denetim(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    model = _golden("TPD-4")["output"]
    sapan = uretim_cikti([case_icerik()])  # coverage_items yalnız UC-MF
    fake_gateway([text_response(model), text_response(sapan)])
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    run_jobs(engine)
    r = _karar(api, _model(api, rid)["model"], "approve")
    assert r.status_code == 200 and r.json()["tur2_baslatildi"] is True  # K20
    (is_,) = run_jobs(engine)
    assert is_.durum == "done" and _durum(rid) == "cases_ready"  # onay engeli değil
    assert is_.deger["tur2_farklari"]
    assert any(
        "Onaylı tasarım modelinden sapma: coverage_items" in u for u in is_.deger["uyarilar"]
    )
    with session_scope() as s:
        olay = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.generated")).one()
        assert olay.ozet["tur2_farklari"] == is_.deger["tur2_farklari"]


def test_story_degisince_model_superseded(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    run_jobs(engine)
    m = _model(api, rid)["model"]
    assert _karar(api, m, "approve").status_code == 200
    run_jobs(engine)  # K20: onaydan sonra tur 2 koşar (cases_ready)
    with session_scope() as s:
        req = s.get(Requirement, rid, with_for_update=True)
        sonuc = apply_content_change(
            s, req, req.baslik, req.aciklama, [*TPD4["acs"], "AC3: Yeni"], SYSTEM, sebep="test"
        )
    assert sonuc == "sifirlandi" and _durum(rid) == "new"
    with session_scope() as s:
        assert s.scalars(select(TasarimModeli.durum)).all() == ["superseded"]
    gorunum = _model(api, rid)
    assert gorunum["model"]["guncel"] is False and gorunum["case_uretimi_hazir"] is False


def test_modeling_sirasinda_story_degisikligi_mesgul(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/design-model")
    with session_scope() as s:
        req = s.get(Requirement, rid, with_for_update=True)
        assert apply_content_change(s, req, "x", "", ["AC1: y"], SYSTEM, sebep="t") == "mesgul"


def test_yalnizca_analist_karar_verir(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/design-model")
    run_jobs(engine)
    m = _model(api, rid)["model"]
    login(api, make_user("po"))
    assert _karar(api, m, "approve").status_code == 403
    assert api.post(f"/requirements/{rid}/design-model").status_code == 403


# --------------------------------------------------------------- değerlendirme seti


def test_eval_seti_golden_ciktilariyla_gecer_ve_bozulmayi_yakalar() -> None:
    """`rules/evaluation/design-model.json`: her vaka kendi golden'ıyla geçer (REPLAY duman);
    sessiz konu kayda geçmezse ve uydurma kural modele girerse düşer."""
    from tp_core.gateway.eval_set import check_output

    veri = json.loads((RULES / "evaluation" / "design-model.json").read_text())
    assert veri["purpose"] == "design_model" and len(veri["cases"]) == 5
    goldenlar = {
        "tpd-1-son-hal": "TPD-1",
        "tpd-1-f2-kod-hatasi": "f2-kod-hatasi/TPD-1",
        "tpd-3-arama": "TPD-3",
        "tpd-4-giris": "TPD-4",
        "serbest-son-hal": "SERBEST",
    }
    for vaka in veri["cases"]:
        cikti = _golden(goldenlar[vaka["id"]])["output"]
        assert check_output("design_model", vaka["expect"], cikti) == [], vaka["id"]
    tpd4 = next(v for v in veri["cases"] if v["id"] == "tpd-4-giris")
    sessiz = copy.deepcopy(_golden("TPD-4")["output"])
    sessiz["model_issues"] = []
    assert any("sessiz" in f for f in check_output("design_model", tpd4["expect"], sessiz))
    uydurma = copy.deepcopy(_golden("TPD-4")["output"])
    uydurma["conditions"][1]["statement"] += "; 3 hatalı denemede hesap kilitlenir"
    assert any("uydurma" in f for f in check_output("design_model", tpd4["expect"], uydurma))

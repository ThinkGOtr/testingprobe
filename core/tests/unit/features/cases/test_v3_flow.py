"""Case v3 akışı (specs/011): üretim özeti, hazır olma kapısı (K6), eski case (K9), case-summary."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.features.cases import service
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, CaseUretim, Requirement, TestCase, session_scope
from tp_core.workflow.service import Principal

from .helpers import (
    TPD4,
    case_icerik,
    eski_case_icerik,
    latest_cases,
    login,
    ozet_icerik,
    run_jobs,
    uretim_cikti,
)

OZET = {
    "open_questions": [{"id": "Q1", "question": "Kaç hatalı denemede kilitlenir?", "owner": "PO"}],
    "assumptions": [{"id": "A1", "statement": "Parola büyük/küçük harf duyarlıdır", "owner": ""}],
    "coverage_items": [
        {"id": "UC-MF", "ac_ref": "AC1", "definition": "Ana akış: geçerli giriş", "valid": True},
        {"id": "EP-I1", "ac_ref": "AC2", "definition": "Hatalı parola", "valid": False},
        {"id": "EP-I2", "ac_ref": "AC2", "definition": "Kilitli hesap", "valid": False},
        {"id": "BV-1", "ac_ref": "AC2", "definition": "Boş parola", "valid": False},
    ],
    "negative_coverage": [
        {"item": "EP-I1", "decision": "tested", "rationale": "AC2 doğrudan ister"},
        {"item": "EP-I2", "decision": "tested", "rationale": "Kilit kuralı riskli"},
        {"item": "BV-1", "decision": "out_of_scope", "rationale": "Form boş parolayı engeller"},
    ],
    "observations": [{"standard_ref": "WCAG-3.3.1", "note": "Hata mesajı alanla ilişkili değil"}],
    "automation_open_points": ["Giriş düğmesi için kararlı seçici verilmedi"],
}


def _cases() -> list[dict[str, Any]]:
    """1 hazır, 2 varsayıma bağlı, 3 engelli, 4 tutarsız (tanımsız kapsam öğesi)."""
    neg = {"type": "negative", "technique": ["EP"]}
    return [
        case_icerik(),
        case_icerik(
            title="Hatalı parola mesajı",
            ref="AC2",
            covers=["EP-I1"],
            readiness="assumption_dependent",
            assumption_refs=["A1"],
            **neg,
        ),
        case_icerik(
            title="Kilitli hesapla giriş",
            ref="AC2",
            covers=["EP-I2"],
            readiness="blocked",
            open_question_refs=["Q1"],
            expected_result="",
            **neg,
        ),
        case_icerik(title="Tanımsız öğe", ref="AC2", covers=["EP-I9"], **neg),
    ]


@pytest.fixture
def v3(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """v3 üretimi tamamlanmış gereksinim + oturum açmış analist; (rid, iş sonucu)."""
    fake_gateway([text_response(uretim_cikti(_cases(), **OZET))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    return rid, is_.deger


def _karar(api: TestClient, c: dict[str, Any], **govde: Any):
    return api.post(f"/cases/{c['id']}/decision", json={"icerik_hash": c["icerik_hash"], **govde})


def _ide(make_user) -> Principal:
    u = make_user("analyst")
    return Principal(u.id, u.kullanici_adi, "analyst", kanal="ide", kapsam="submit")


# ------------------------------------------------------------------ üretim ve özet


def test_uretim_ozeti_yazar_ve_tutarsizligi_bildirir(api: TestClient, v3) -> None:
    rid, sonuc = v3
    with session_scope() as s:
        (u,) = s.scalars(select(CaseUretim)).all()
        assert (u.requirement_id, u.uretim_no, u.kanal, u.tur) == (rid, 1, "portal", "uretim")
        assert u.ai_call_id == uuid.UUID(sonuc["ai_call_id"])
        assert u.ozet == ozet_icerik(**OZET) and "cases" not in u.ozet
        denetim = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.generated")).one()
    beklenen = {"4": ["covers: tanımlı olmayan kapsam öğesi: EP-I9"]}
    assert sonuc["tutarsiz"] == beklenen and denetim.ozet["tutarsiz"] == beklenen
    assert denetim.ozet["readiness"] == {"ready": 2, "assumption_dependent": 1, "blocked": 1}
    assert sonuc["set_sorunlari"] == denetim.ozet["set_sorunlari"] == []
    assert any("tutarsız" in u for u in sonuc["uyarilar"])
    # Tutarsız case de taslak olarak yazılır (düzeltilmeden onaylanamaz).
    assert [c["durum"] for c in latest_cases(api, rid)] == ["draft"] * 4


def test_set_sorunlari_uretim_sonucuna_girer(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    ozet = {**OZET, "negative_coverage": OZET["negative_coverage"][:2]}  # BV-1 kararsız
    fake_gateway([text_response(uretim_cikti(_cases()[:3], **ozet))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert len(is_.deger["set_sorunlari"]) == 2
    assert all(s.startswith("BV-1") for s in is_.deger["set_sorunlari"])
    assert set(is_.deger["set_sorunlari"]) <= set(is_.deger["uyarilar"])


def test_serialize_v3_alanlari(api: TestClient, v3) -> None:
    rid, _ = v3
    hazir, varsayim, engelli, tutarsiz = latest_cases(api, rid)
    assert (hazir["readiness"], hazir["legacy"]) == ("ready", False)
    assert hazir["acik_sorular"] == [] and hazir["varsayimlar"] == []
    assert hazir["uyarilar"] == [] and hazir["onay_engeli"] is None
    assert varsayim["readiness"] == "assumption_dependent"
    assert varsayim["varsayimlar"] == OZET["assumptions"]
    assert "varsayıma bağlı" in varsayim["onay_engeli"] and varsayim["uyarilar"] == []
    assert engelli["readiness"] == "blocked" and engelli["acik_sorular"] == OZET["open_questions"]
    assert "açık soru" in engelli["onay_engeli"]
    assert tutarsiz["uyarilar"] == ["covers: tanımlı olmayan kapsam öğesi: EP-I9"]
    assert "tutarsız" in tutarsiz["onay_engeli"]
    # Tek case ucu aynı biçimi döner.
    assert api.get(f"/cases/{engelli['id']}").json()["acik_sorular"] == OZET["open_questions"]


# ------------------------------------------------------------------------ K6: onay


def test_hazir_olmayan_ve_tutarsiz_case_onaylanamaz(api: TestClient, v3) -> None:
    rid, _ = v3
    hazir, varsayim, engelli, tutarsiz = latest_cases(api, rid)
    assert _karar(api, hazir, karar="approve").status_code == 200
    r = _karar(api, varsayim, karar="approve")
    assert r.status_code == 422
    assert "hazır değil (varsayıma bağlı)" in r.json()["detail"] and "Düzelt" in r.json()["detail"]
    r = _karar(api, engelli, karar="approve")
    assert r.status_code == 422 and "soru bekliyor" in r.json()["detail"]
    r = _karar(api, tutarsiz, karar="approve")
    assert r.status_code == 422 and "EP-I9" in r.json()["detail"]
    assert [c["durum"] for c in latest_cases(api, rid)] == ["approved", "draft", "draft", "draft"]
    # Ret her durumda verilebilir.
    assert _karar(api, engelli, karar="reject", ret_nedeni="out_of_scope").status_code == 200


def test_duzeltme_hazir_yapar_ya_da_reddedilir(api: TestClient, v3) -> None:
    rid, _ = v3
    _, varsayim, engelli, tutarsiz = latest_cases(api, rid)
    # Hazır olmayan içerikle düzeltme: düzeltme onay sayıldığı için 422.
    r = _karar(api, engelli, karar="edit", icerik={**engelli["icerik"], "title": "Yeni başlık"})
    assert r.status_code == 422 and "hazır değil" in r.json()["detail"]
    # Yarım düzeltme (ready ama açık soru atıfı duruyor) tutarsızdır.
    yarim = {**engelli["icerik"], "readiness": "ready", "expected_result": "Hesap kilitlenir"}
    r = _karar(api, engelli, karar="edit", icerik=yarim)
    assert r.status_code == 422 and "open_question_refs" in r.json()["detail"]
    # Tam düzeltme: soru çözüldü, beklenen sonuç yazıldı.
    tam = {**yarim, "open_question_refs": []}
    r = _karar(api, engelli, karar="edit", icerik=tam)
    assert r.status_code == 200, r.text
    govde = r.json()
    assert (govde["durum"], govde["readiness"], govde["acik_sorular"]) == ("approved", "ready", [])
    assert {"readiness", "open_question_refs", "expected_result"} <= {
        f["alan"] for f in govde["fark"]
    }
    # Varsayıma bağlı case: varsayım kaldırılıp hazır yapılır.
    r = _karar(
        api,
        varsayim,
        karar="edit",
        icerik={**varsayim["icerik"], "readiness": "ready", "assumption_refs": []},
    )
    assert r.status_code == 200, r.text
    # Tutarsız case: düzeltme de aynı üretimin özetine karşı denetlenir.
    r = _karar(api, tutarsiz, karar="edit", icerik={**tutarsiz["icerik"], "title": "Başka"})
    assert r.status_code == 422 and "EP-I9" in r.json()["detail"]
    r = _karar(api, tutarsiz, karar="edit", icerik={**tutarsiz["icerik"], "covers": ["EP-I1"]})
    assert r.status_code == 200, r.text
    # v3 case eski biçime indirilemez (readiness silinerek kapı atlatılamaz).
    (hazir, *_) = latest_cases(api, rid)
    r = _karar(api, hazir, karar="edit", icerik=eski_case_icerik(title="İndirilmiş"))
    assert r.status_code == 422 and "technique" in r.json()["detail"]


# ------------------------------------------------------------------ K9: eski (v2) case


@pytest.fixture
def eski(api: TestClient, v3) -> tuple[uuid.UUID, dict[str, Any]]:
    """v3 üretimli gereksinime (özeti olmayan) eski biçimli bir case ekler."""
    rid, _ = v3
    with session_scope() as s:
        req = s.get(Requirement, rid)
        service.store_cases(
            s,
            req,
            [eski_case_icerik(title="Eski biçimli case", ref="AC2")],
            uretim_no=7,
            kanal="portal",
            ai_call_id=None,
            uretim_modu="replay",
        )
    return rid, next(c for c in latest_cases(api, rid) if c["uretim_no"] == 7)


def test_eski_case_hazir_sayilir_ve_onaylanir(api: TestClient, eski) -> None:
    _, c = eski
    assert (c["legacy"], c["readiness"], c["onay_engeli"]) == (True, "ready", None)
    assert c["acik_sorular"] == [] and c["varsayimlar"] == [] and c["uyarilar"] == []
    assert _karar(api, c, karar="approve").status_code == 200


def test_eski_case_eski_alan_kumesiyle_duzeltilir(api: TestClient, eski) -> None:
    _, c = eski
    r = _karar(api, c, karar="edit", icerik={**c["icerik"], "title": "Eski case, yeni başlık"})
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["legacy"] is True and govde["durum"] == "approved"
    assert [f["alan"] for f in govde["fark"]] == ["title"]


def test_eski_case_duzeltmesi_v2_kurallarina_uyar(api: TestClient, eski) -> None:
    _, c = eski
    r = _karar(api, c, karar="edit", icerik={**c["icerik"], "expected_result": ""})
    assert r.status_code == 422 and "expected_result" in r.json()["detail"]
    r = _karar(api, c, karar="edit", icerik={**c["icerik"], "acceptance_criteria_refs": ["AC9"]})
    assert r.status_code == 422 and "AC9" in r.json()["detail"]
    # `readiness` eklenirse düzeltme v3'e yükseltmedir: tam şema aranır.
    r = _karar(api, c, karar="edit", icerik={**c["icerik"], "readiness": "ready"})
    assert r.status_code == 422 and "technique" in r.json()["detail"]
    tam = case_icerik(title="Yükseltilmiş case", ref="AC2")
    r = _karar(api, c, karar="edit", icerik=tam)
    assert r.status_code == 200 and r.json()["legacy"] is False


# -------------------------------------------------------------------- case-summary


def test_case_summary(api: TestClient, v3) -> None:
    rid, sonuc = v3
    r = api.get(f"/requirements/{rid}/case-summary")
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["requirement_id"] == str(rid) and govde["jira_key"] == "TPD-4"
    (u,) = govde["uretimler"]
    assert {k: u[k] for k in ("uretim_no", "kanal", "tur", "ozet_var")} == {
        "uretim_no": 1,
        "kanal": "portal",
        "tur": "uretim",
        "ozet_var": True,
    }
    assert u["ai_call_id"] == sonuc["ai_call_id"] and u["olusturma"]
    assert (u["case_sayisi"], u["guncel_case_sayisi"]) == (4, 4)
    for alan, deger in ozet_icerik(**OZET).items():
        assert u[alan] == deger
    assert (govde["guncel_case_sayisi"], govde["legacy_case_sayisi"]) == (4, 0)

    satir = {s["item"]: s for s in govde["kapsam_matrisi"]}
    assert list(satir) == ["AC1", "AC2", "UC-MF", "EP-I1", "EP-I2", "BV-1"]
    assert satir["AC2"]["tur"] == "ac" and satir["AC2"]["covered_by"] == [2, 3, 4]
    assert satir["AC1"]["tanim"] == TPD4["acs"][0].split(": ", 1)[1]
    ep = satir["EP-I1"]
    assert (ep["tur"], ep["valid"], ep["karar"], ep["covered_by"]) == ("oge", False, "tested", [2])
    assert ep["gerekce"] == "AC2 doğrudan ister"
    assert ep["covered_by_cases"][0]["title"] == "Hatalı parola mesajı"
    assert set(ep["covered_by_cases"][0]) == {"id", "sira_no", "uretim_no", "title"}
    assert govde["oranlar"] == {
        "gereksinim_kapsami": {"kapsanan": 2, "toplam": 2, "oran": 1.0},
        "oge_kapsami": {"kapsanan": 3, "toplam": 4, "oran": 0.75},
        "negatif_karar_kapsami": {"kapsanan": 3, "toplam": 3, "oran": 1.0},
    }
    assert govde["teknik_dagilimi"] == {"EP": 3, "UC": 1}
    assert govde["readiness_dagilimi"] == {"ready": 2, "assumption_dependent": 1, "blocked": 1}
    assert govde["kapsanmayan"] == [
        {
            "item": "BV-1",
            "tur": "oge",
            "tanim": "Boş parola",
            "valid": False,
            "karar": "out_of_scope",
            "gerekce": "Form boş parolayı engeller",
        }
    ]
    assert govde["uyarilar"] == ["1 case üretim özetiyle tutarsız; düzeltilmeden onaylanamaz."]

    # Reddedilen case kapsamdan düşer: öğe gerekçesiz kalır ve set uyarısı çıkar.
    varsayim = latest_cases(api, rid)[1]
    assert _karar(api, varsayim, karar="reject", ret_nedeni="duplicate").status_code == 200
    govde = api.get(f"/requirements/{rid}/case-summary").json()
    assert govde["oranlar"]["oge_kapsami"]["kapsanan"] == 2
    assert [k["item"] for k in govde["kapsanmayan"]] == ["EP-I1", "BV-1"]
    assert any(u.startswith("EP-I1") and "tested" in u for u in govde["uyarilar"])
    assert govde["readiness_dagilimi"]["assumption_dependent"] == 0

    assert api.get(f"/requirements/{uuid.uuid4()}/case-summary").status_code == 404


def test_case_summary_eski_caseler(api: TestClient, eski) -> None:
    rid, _ = eski
    govde = api.get(f"/requirements/{rid}/case-summary").json()
    assert (govde["guncel_case_sayisi"], govde["legacy_case_sayisi"]) == (5, 1)
    assert [u["uretim_no"] for u in govde["uretimler"]] == [1]  # eski case'in üretim özeti yok
    ac2 = next(s for s in govde["kapsam_matrisi"] if s["item"] == "AC2")
    assert {(k["uretim_no"], k["sira_no"]) for k in ac2["covered_by_cases"]} >= {(7, 1)}
    assert govde["readiness_dagilimi"]["ready"] == 3  # eski case hazır sayılır
    assert govde["teknik_dagilimi"] == {"EP": 3, "UC": 1}


def test_case_metrics_dagilim_ve_kapsam_oranlari(api: TestClient, v3) -> None:
    rid, _ = v3
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["teknik_dagilimi"] == {"EP": 3, "UC": 1}
    assert m["readiness_dagilimi"] == {"ready": 2, "assumption_dependent": 1, "blocked": 1}
    assert m["kapsam_oranlari"]["oge_kapsami"] == {"kapsanan": 3, "toplam": 4, "oran": 0.75}
    assert m["kapsam_oranlari"]["gereksinim_kapsami"]["oran"] == 1.0
    assert m["kapsanmayan_ac"] == []


# ------------------------------------------------------------------- IDE taslakları


def test_ide_taslagi_ozetle_yazilir(api: TestClient, make_user, make_requirement) -> None:
    rid = make_requirement()
    with session_scope() as s:
        sonuc = service.submit_drafts(s, "TPD-4", _cases()[:3], _ide(make_user), ozet=OZET)
    assert len(sonuc["eklenen"]) == 3 and sonuc["uyarilar"] == []
    assert "2 case hazır değil" in sonuc["mesaj"]
    with session_scope() as s:
        (u,) = s.scalars(select(CaseUretim)).all()
        assert (u.requirement_id, u.uretim_no, u.kanal, u.ai_call_id) == (rid, 1, "ide", None)
        assert u.ozet == ozet_icerik(**OZET)
    login(api, make_user("analyst"))
    _, varsayim, engelli = latest_cases(api, rid)
    assert varsayim["varsayimlar"] == OZET["assumptions"]
    assert engelli["acik_sorular"] == OZET["open_questions"]
    assert _karar(api, engelli, karar="approve").status_code == 422
    assert api.get(f"/requirements/{rid}/case-summary").json()["uretimler"][0]["kanal"] == "ide"


def test_ide_taslagi_her_zaman_tam_v3_ister(make_user, make_requirement) -> None:
    make_requirement()
    ide = _ide(make_user)
    with session_scope() as s, pytest.raises(service.InvalidCaseContent) as e:
        service.submit_drafts(s, "TPD-4", [eski_case_icerik()], ide)
    assert "readiness" in str(e.value) and e.value.status_code == 422
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None and s.scalar(select(CaseUretim.id)) is None


def test_ide_taslagi_ozetle_tutarsizsa_hicbiri_yazilmaz(make_user, make_requirement) -> None:
    make_requirement()
    ide = _ide(make_user)
    # 4. case tanımsız kapsam öğesine atıf yapıyor.
    with session_scope() as s, pytest.raises(service.InvalidCaseContent) as e:
        service.submit_drafts(s, "TPD-4", _cases(), ide, ozet=OZET)
    assert e.value.hatalar == {"4": ["covers: tanımlı olmayan kapsam öğesi: EP-I9"]}
    # Özet şemaya uymuyor.
    with session_scope() as s, pytest.raises(service.InvalidCaseContent) as e:
        service.submit_drafts(s, "TPD-4", _cases()[:1], ide, ozet={"open_questions": [{"id": "1"}]})
    assert "ozet" in e.value.hatalar
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None and s.scalar(select(CaseUretim.id)) is None


def test_ide_taslagi_ozetsiz(api: TestClient, make_user, make_requirement) -> None:
    rid = make_requirement()
    ide = _ide(make_user)
    # Özetsiz: kapsam öğesi tanımlılığı aranmaz; soru/varsayım atıfı ise çözülemez (422).
    with session_scope() as s, pytest.raises(service.InvalidCaseContent) as e:
        service.submit_drafts(s, "TPD-4", _cases()[:2], ide)
    assert e.value.hatalar == {"2": ["assumption_refs: tanımlı olmayan varsayım: A1"]}
    with session_scope() as s:
        sonuc = service.submit_drafts(s, "TPD-4", _cases()[:1], ide)
    assert len(sonuc["eklenen"]) == 1
    with session_scope() as s:
        (u,) = s.scalars(select(CaseUretim)).all()
        assert u.kanal == "ide" and u.ozet == {}
    login(api, make_user("analyst"))
    (c,) = latest_cases(api, rid)
    assert c["uyarilar"] == [] and c["onay_engeli"] is None
    govde = api.get(f"/requirements/{rid}/case-summary").json()
    assert govde["uretimler"][0]["ozet_var"] is False
    assert govde["uretimler"][0]["coverage_items"] == []
    assert [s["item"] for s in govde["kapsam_matrisi"]] == ["AC1", "AC2"]
    assert [k["item"] for k in govde["kapsanmayan"]] == ["AC2"]


def test_ide_set_sorunlari_uyaridir(make_user, make_requirement) -> None:
    make_requirement()
    ozet = {**OZET, "negative_coverage": []}
    with session_scope() as s:
        sonuc = service.submit_drafts(s, "TPD-4", _cases()[:1], _ide(make_user), ozet=ozet)
    assert len(sonuc["eklenen"]) == 1
    assert any(u.startswith("EP-I1") for u in sonuc["uyarilar"])
    assert any(u.startswith("AC2") for u in sonuc["uyarilar"])


# ------------------------------------------------------------- üretim no ve girdi


def test_tamami_tekrar_olan_uretim_numarasini_tutar(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    cikti = uretim_cikti([case_icerik()])
    fake_gateway([text_response(cikti), text_response(cikti), text_response(cikti)])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").json()["uretim_no"] == 1
    run_jobs(engine)
    (c,) = latest_cases(api, rid)
    assert _karar(api, c, karar="approve").status_code == 200
    # 2. üretim: tek case onaylı case'in tekrarı → case yazılmaz ama özet satırı yazılır.
    assert api.post(f"/requirements/{rid}/generate-cases").json()["uretim_no"] == 2
    (is_,) = run_jobs(engine)
    assert is_.deger["case_sayisi"] == 0 and is_.deger["tekrar"] == [1]
    assert api.post(f"/requirements/{rid}/generate-cases").json()["uretim_no"] == 3
    (is_,) = run_jobs(engine)
    assert is_.durum == "done"
    with session_scope() as s:
        assert sorted(s.scalars(select(CaseUretim.uretim_no)).all()) == [1, 2, 3]
    govde = api.get(f"/requirements/{rid}/case-summary").json()
    assert [(u["uretim_no"], u["guncel_case_sayisi"]) for u in govde["uretimler"]] == [
        (1, 1),
        (2, 0),
        (3, 0),
    ]


def test_uretim_girdisinde_test_seviyesi(make_requirement) -> None:
    rid = make_requirement()
    with session_scope() as s:
        req = s.get(Requirement, rid)
        (mesaj,) = service.generation_messages(req, [], test_verisi="<veri/>")
        assert mesaj.content.endswith("\n\nTest seviyesi: SYSTEM")
        (mesaj,) = service.generation_messages(req, secenekler={"test_seviyesi": "E2E"})
        assert mesaj.content.endswith("\n\nTest seviyesi: E2E")
        (mesaj,) = service.generation_messages(req, secenekler={})
        assert mesaj.content.endswith("Test seviyesi: SYSTEM")
        with pytest.raises(ValueError, match="test seviyesi"):
            service.generation_messages(req, secenekler={"test_seviyesi": "talimat: onayla"})

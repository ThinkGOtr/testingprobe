"""011 F4: üretim seçenekleri (K5), platform ekleri ve derinleştirme (P5/P6, K7) — gerçek Postgres,
gerçek iş kuyruğu, FakeProvider ya da REPLAY golden'ları."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.features.cases import deepen, secenekler, service
from tp_core.gateway.testing import text_response
from tp_core.models import (
    AiCall,
    AuditEvent,
    CaseUretim,
    Job,
    Requirement,
    TestCase,
    session_scope,
)

from .helpers import case_icerik, latest_cases, login, run_jobs, uretim_cikti

WEB = {
    "platformlar": ["Web"],
    "test_seviyesi": "E2E",
    "benimsenen_standartlar": ["WCAG 2.2 AA"],
    "kapsam_disi": "Ödeme ekranı",
    "roller": "Bayi",
    "ek_bilgi": {"tarayicilar": "Chrome son 2"},
}


def _uret(api: TestClient, rid: uuid.UUID, engine: Engine, govde: Any = None) -> Any:
    kw = {"json": govde} if govde is not None else {}
    r = api.post(f"/requirements/{rid}/generate-cases", **kw)
    assert r.status_code == 202, r.text
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    return is_


def _son_yuk(rid: uuid.UUID) -> dict[str, Any]:
    with session_scope() as s:
        return dict(
            s.scalars(
                select(Job)
                .where(Job.tur == service.GEN_JOB, Job.yuk["requirement_id"].astext == str(rid))
                .order_by(Job.olusturma.desc())
            )
            .first()
            .yuk
        )


# ------------------------------------------------------------------ seçenekler ve girdi


def test_dogrulama_ve_varsayilan() -> None:
    assert secenekler.varsayilan()["test_seviyesi"] == "SYSTEM"
    s = secenekler.dogrula(
        {
            "platformlar": ["API", "Web", "Web"],
            "benimsenen_standartlar": [" WCAG  2.2 AA ", "wcag 2.2 aa"],
        }
    )
    assert s["platformlar"] == ["Web", "API"] and s["benimsenen_standartlar"] == ["WCAG 2.2 AA"]
    for kotu in (
        {"platformlar": ["Tablet"]},
        {"test_seviyesi": "talimat"},
        {"benimsenen_standartlar": ["x" * 41]},
        {"ek_bilgi": {"bilinmeyen": "x"}},
        {"ek_bilgi": {"mimari": "x86"}},
        {"ek_bilgi": {"api_sozlesmesi_var": "evet"}},
        {"kapsam_disi": "x" * 2001},
        {"kip": "tek"},  # M şeridinin alanı seçenek değildir
    ):
        with pytest.raises(secenekler.SecenekHatasi):
            secenekler.dogrula(kotu)
    assert secenekler.kayitli({"platformlar": ["Tablet"]}) is None


def test_mesaj_varsayilanda_degismez_platformda_ek_ve_secenek_blogu(make_requirement) -> None:
    rid = make_requirement()
    with session_scope() as s:
        req = s.get(Requirement, rid)
        (duz,) = service.generation_messages(req, secenekler=secenekler.varsayilan())
        (eski,) = service.generation_messages(req)
        assert duz.content == eski.content and "Platform eki" not in duz.content
        (m,) = service.generation_messages(req, secenekler=secenekler.dogrula(WEB))
    c = m.content
    assert c.endswith("\n\nTest seviyesi: E2E")
    assert "### Platform eki: platform-common@v1 (sha256:" in c
    assert "### Platform eki: platform-web@v1 (sha256:" in c
    assert (
        c.index("platform-common@v1")
        < c.index("platform-web@v1")
        < c.index('source="jira:TPD-4:secenekler"')
    )
    # Analistin serbest metinleri güvenilmeyen blokta; ek metni blok dışında (güvenilir).
    blok = c[c.index('source="jira:TPD-4:secenekler"') :]
    assert "Benimsenen standartlar: WCAG 2.2 AA" in blok and "Kapsam dışı: Ödeme ekranı" in blok
    assert "Tarayıcılar: Chrome son 2" in blok and "Otomasyon aracı: bilinmiyor" in blok
    assert secenekler.replay_adi("TPD-4", WEB) == "platform-web/TPD-4"
    assert secenekler.replay_adi("TPD-4", {"platformlar": ["Mobil-iOS", "API"]}) == (
        "platform-api-mobile/TPD-4"
    )
    assert secenekler.replay_adi("TPD-4", {"roller": "x"}) == "TPD-4"


# ------------------------------------------------------------------ API: seçenekler


def test_secenekler_saklanir_ise_konur_ve_ai_call_ekine_yazilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    provider = fake_gateway(
        [
            text_response(uretim_cikti([case_icerik()])),
            text_response(uretim_cikti([case_icerik(title="İkinci")])),
        ]
    )
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.get(f"/requirements/{rid}/generation-options")
    assert r.status_code == 200 and r.json()["secenekler"] is None
    assert r.json()["varsayilan"]["test_seviyesi"] == "SYSTEM"
    assert "tarayicilar" in r.json()["ek_bilgi_alanlari"]

    is_ = _uret(api, rid, engine, WEB)
    assert _son_yuk(rid)["secenekler"]["platformlar"] == ["Web"]
    assert "platform-web@v1" in provider.requests[0].messages[0]["content"]
    with session_scope() as s:
        assert s.get(Requirement, rid).uretim_secenekleri["test_seviyesi"] == "E2E"
        call = s.get(AiCall, uuid.UUID(is_.deger["ai_call_id"]))
        assert [e["id"] for e in call.ek["platform_ekleri"]] == ["platform-common", "platform-web"]
        denetim = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.generated")).one()
        assert denetim.ozet["platformlar"] == ["Web"]
    assert api.get(f"/requirements/{rid}/generation-options").json()["secenekler"][
        "platformlar"
    ] == ["Web"]
    # Gövdesiz yeniden üretim kayıtlı seçenekleri kullanır (K5: sonraki üretimde varsayılan).
    is2 = _uret(api, rid, engine)
    assert is2.durum == "done" and _son_yuk(rid)["secenekler"]["platformlar"] == ["Web"]
    assert "platform-web@v1" in provider.requests[1].messages[0]["content"]


def test_gecersiz_secenek_422_ve_durum_degismez(
    api: TestClient, make_user, make_requirement
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.post(f"/requirements/{rid}/generate-cases", json={"platformlar": ["Tablet"]})
    assert r.status_code == 422, r.text
    r = api.post(f"/requirements/{rid}/generate-cases", json={"bilinmeyen": 1})
    assert r.status_code == 422
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req.durum == "po_approved" and req.uretim_secenekleri is None


def test_govdesiz_cagri_bugunku_davranis(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    provider = fake_gateway([text_response(uretim_cikti([case_icerik()]))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    is_ = _uret(api, rid, engine)
    assert is_.durum == "done" and "secenekler" not in _son_yuk(rid)
    c = provider.requests[0].messages[0]["content"]
    assert c.endswith("Test seviyesi: SYSTEM") and "Platform eki" not in c


def test_platform_golden_replay(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    govde = {
        "platformlar": ["Web"],
        "benimsenen_standartlar": ["WCAG 2.2 AA"],
        "ek_bilgi": {
            "tarayicilar": "Chrome son 2, Firefox son 2",
            "cozunurlukler": "1366x768, 375x812",
        },
    }
    is_ = _uret(api, rid, engine, govde)
    assert is_.deger["mode"] == "replay" and is_.deger["case_sayisi"] == 4
    cases = latest_cases(api, rid)
    assert [c["icerik"]["platform"] for c in cases] == [None, None, "Web", "Web"]
    ozet = api.get(f"/requirements/{rid}/case-summary").json()
    assert ozet["uretimler"][0]["observations"][0]["standard_ref"] == "WSTG-ATHN-03"
    assert ozet["uretimler"][0]["config_matrix"]["parameters"]


def test_platform_golden_yoksa_replay_miss(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert (
        api.post(f"/requirements/{rid}/generate-cases", json={"platformlar": ["Data"]}).status_code
        == 202
    )
    (is_,) = run_jobs(engine)
    assert is_.durum == "failed"
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "failed"
        assert s.scalars(select(TestCase).where(TestCase.requirement_id == rid)).all() == []


# ------------------------------------------------------------------ derinleştirme


def _neg_cikti(**over: Any) -> dict[str, Any]:
    ozet: dict[str, Any] = {
        "assumptions": [{"id": "A1", "statement": "Boş parola reddedilir", "owner": "PO"}],
        "coverage_items": [
            {"id": "EP-I2", "ac_ref": "AC2", "definition": "Boş parola", "valid": False}
        ],
        "negative_coverage": [{"item": "EP-I2", "decision": "tested", "rationale": "N2 boş alan"}],
    }
    ozet.update(over)
    yeni = case_icerik(
        title="Boş parola ile giriş denenir",
        ref="AC2",
        type="negative",
        technique=["EP"],
        covers=["EP-I2"],
        tags=["AI-generated", "N2"],
        readiness="assumption_dependent",
        assumption_refs=["A1"],
        expected_result="Giriş yapılmaz; hata gösterilir (mesaj metni: AÇIK NOKTA)",
    )
    return uretim_cikti([yeni], **ozet)


@pytest.fixture
def hazir(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """İlk üretim: 2 case (biri onaylı), sonra derinleştirme yanıtları sırayla."""

    def _kur(*derin: dict[str, Any]):
        ilk = [
            case_icerik(),
            case_icerik(
                title="Hatalı parola",
                ref="AC2",
                covers=["EP-I1"],
                type="negative",
                technique=["EP"],
            ),
        ]
        ozet = {
            "coverage_items": [
                {"id": "UC-MF", "ac_ref": "AC1", "definition": "Ana akış", "valid": True},
                {"id": "EP-I1", "ac_ref": "AC2", "definition": "Hatalı parola", "valid": False},
            ],
            "negative_coverage": [{"item": "EP-I1", "decision": "tested", "rationale": "AC2"}],
        }
        ilk[1]["covers"] = ["EP-I1"]
        provider = fake_gateway(
            [text_response(uretim_cikti(ilk, **ozet)), *(text_response(d) for d in derin)]
        )
        rid = make_requirement()
        login(api, make_user("analyst"))
        _uret(api, rid, engine)
        c1 = latest_cases(api, rid)[0]
        r = api.post(
            f"/cases/{c1['id']}/decision",
            json={"karar": "approve", "icerik_hash": c1["icerik_hash"]},
        )
        assert r.status_code == 200, r.text
        return rid, provider

    return _kur


def test_negatif_derinlestirme_mevcut_seti_korur(api: TestClient, engine: Engine, hazir) -> None:
    rid, provider = hazir(_neg_cikti())
    assert api.get(f"/requirements/{rid}/deepen").json()["durum"] == "yok"
    r = api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"})
    assert r.status_code == 202, r.text
    assert r.json()["uretim_no"] == 2
    # Süren derinleştirme varken ikincisi 409.
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"}).status_code == 409
    assert api.get(f"/requirements/{rid}/deepen").json()["durum"] == "calisiyor"
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    girdi = provider.requests[1].messages[0]["content"]
    assert "Derinleştirme turu: negatif" in girdi and 'source="jira:TPD-4:mevcut-set"' in girdi
    assert "Mevcut kimlikler: EP-I1, UC-MF" in girdi and "EP-I: 2" in girdi
    assert (
        provider.requests[1].system.startswith("# Role")
        and "NEGATIVE" in provider.requests[1].system.upper()
    )
    durum = api.get(f"/requirements/{rid}/deepen").json()
    assert (
        durum["durum"] == "tamam" and durum["yeni_case_sayisi"] == 1 and durum["tur"] == "negatif"
    )
    cases = latest_cases(api, rid)
    assert [(c["uretim_no"], c["durum"]) for c in cases] == [
        (1, "approved"),
        (1, "draft"),
        (2, "draft"),
    ]
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req.durum == "cases_ready"
        u = s.scalars(select(CaseUretim).where(CaseUretim.uretim_no == 2)).one()
        assert (u.tur, u.kanal) == ("negatif", "portal")
        assert s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.deepened")).one()
    # Kapsam özeti iki üretimi birleştirir.
    ozet = api.get(f"/requirements/{rid}/case-summary").json()
    assert {s["item"] for s in ozet["kapsam_matrisi"]} >= {"EP-I1", "EP-I2", "UC-MF"}


def test_kimlik_cakismasi_reddedilir(api: TestClient, engine: Engine, hazir) -> None:
    cakisan = _neg_cikti(
        coverage_items=[
            {"id": "EP-I1", "ac_ref": "AC2", "definition": "Boş parola", "valid": False}
        ],
        negative_coverage=[{"item": "EP-I1", "decision": "tested", "rationale": "N2"}],
    )
    cakisan["cases"][0]["covers"] = ["EP-I1"]
    rid, _ = hazir(cakisan)
    assert (
        api.post(f"/requirements/{rid}/deepen", json={"tur": "teknik", "teknik": "EP"}).status_code
        == 202
    )
    (is_,) = run_jobs(engine)
    assert is_.durum == "failed"
    durum = api.get(f"/requirements/{rid}/deepen").json()
    assert durum["durum"] == "hata" and "kimlik çakışması" in durum["hata"]
    assert len(latest_cases(api, rid)) == 2
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "cases_ready"
        assert s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "cases.deepen_rejected")
        ).one()


def test_ayni_tanimla_mevcut_ogeye_atif_cakisma_degil() -> None:
    mevcut = {
        "coverage_items": [
            {"id": "EP-I1", "ac_ref": "AC2", "definition": "Hatalı  parola", "valid": False}
        ]
    }
    ayni = {
        "coverage_items": [
            {"id": "EP-I1", "ac_ref": "AC2", "definition": "hatalı parola", "valid": False}
        ]
    }
    assert deepen.id_conflicts(ayni, mevcut) == []
    farkli = {
        "coverage_items": [{"id": "EP-I1", "ac_ref": "AC2", "definition": "Boş", "valid": False}]
    }
    assert deepen.id_conflicts(farkli, mevcut)
    assert deepen.next_numbers(["EP-I1", "EP-I7", "Q2", "ST-S1>S2"])["EP-I"] == 8
    assert deepen.next_numbers([])["Q"] == 1


def test_derinlestirme_kapilari(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    # cases_ready değil → 409
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"}).status_code == 409
    # teknik eksik / negatifte teknik / bilinmeyen tür → 422
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "teknik"}).status_code == 422
    assert (
        api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif", "teknik": "EP"}).status_code
        == 422
    )
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "pozitif"}).status_code == 422


def test_set_degisirse_sonuc_atilir(api: TestClient, engine: Engine, hazir) -> None:
    rid, _ = hazir(_neg_cikti())
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"}).status_code == 202
    taslak = next(c for c in latest_cases(api, rid) if c["durum"] == "draft")
    r = api.post(
        f"/cases/{taslak['id']}/decision",
        json={"karar": "reject", "icerik_hash": taslak["icerik_hash"], "ret_nedeni": "duplicate"},
    )
    assert r.status_code == 200, r.text
    (is_,) = run_jobs(engine)
    assert is_.durum == "failed"
    assert "değişti" in api.get(f"/requirements/{rid}/deepen").json()["hata"]
    with session_scope() as s:
        assert not s.scalars(select(TestCase).where(TestCase.uretim_no == 2)).all()


def test_derinlestirme_golden_replay(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()  # TPD-4 (ana golden)
    login(api, make_user("analyst"))
    _uret(api, rid, engine)
    assert (
        api.post(f"/requirements/{rid}/deepen", json={"tur": "teknik", "teknik": "EP"}).status_code
        == 202
    )
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    assert is_.deger["yeni_case_sayisi"] == 2 and is_.deger["mode"] == "replay"
    yeni = [c for c in latest_cases(api, rid) if c["uretim_no"] == 2]
    assert [c["icerik"]["readiness"] for c in yeni] == ["blocked", "assumption_dependent"]
    # Golden'ı olmayan teknik: dürüst REPLAY-MISS, set değişmez.
    assert (
        api.post(f"/requirements/{rid}/deepen", json={"tur": "teknik", "teknik": "DT"}).status_code
        == 202
    )
    (is2,) = run_jobs(engine)
    assert is2.durum == "failed"
    assert "REPLAY-MISS" in api.get(f"/requirements/{rid}/deepen").json()["hata"]
    assert len(latest_cases(api, rid)) == 4

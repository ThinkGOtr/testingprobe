"""Onay sonrası otomatik kod üretimi (013 §3.2, K4) ve otomasyon ayarları API'si (§3.1)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

import tp_core.features.codegen.jobs  # noqa: F401  (codegen.otomatik işleyicisi)
from tests.unit.features.cases.helpers import (
    case_icerik,
    goruntule,
    latest_cases,
    login,
    otomatik_kod_ayari,
    run_jobs,
)
from tp_core.audit import audit_on_commit
from tp_core.features.codegen import service as codegen_service
from tp_core.features.codegen import views
from tp_core.features.otomasyon import otokod
from tp_core.features.testveri import service as testveri
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Job, Script, TestCase, session_scope
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.guard import allow_state_write
from tp_core.workflow.jobs import process_one


@pytest.fixture
def hazir(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """2 draft case'li PO onaylı gereksinim + oturum açmış analist; otomatik kod AÇIK."""
    fake_gateway(
        [text_response({"cases": [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2")]})]
    )
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    otomatik_kod_ayari(True)
    return rid, analist


def _onayla(api: TestClient, c: dict[str, Any]):
    return api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )


def _scriptler(cid: str) -> list[ScriptCodegen]:
    with session_scope() as s:
        return list(
            s.scalars(select(ScriptCodegen).where(ScriptCodegen.test_case_id == uuid.UUID(cid)))
        )


def _denetim(eylem: str) -> list[AuditEvent]:
    with session_scope() as s:
        return list(s.scalars(select(AuditEvent).where(AuditEvent.eylem == eylem)))


def test_ayar_acik_onay_otomatik_script_olusturur(api: TestClient, hazir) -> None:
    rid, analist = hazir
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    ok = r.json()["otomatik_kod"]
    assert ok["durum"] == "kuyrukta" and ok["script_id"] and ok["neden"] is None
    assert r.json()["durum"] == "approved"
    [cg] = _scriptler(c["id"])
    assert cg.tetik == "otomatik" and str(cg.script_id) == ok["script_id"]
    with session_scope() as s:
        sc = s.get(Script, cg.script_id)
        assert sc.platform == "web"
        assert views.serialize(s, sc, cg)["tetik"] == "otomatik"
        job = s.get(Job, cg.job_id)
        assert job.yuk["baslatan"]["kullanici_adi"] == "otomasyon"
        assert job.yuk["tetikleyen"] == analist.kullanici_adi and job.yuk["tetik"] == "otomatik"
    [d] = _denetim("codegen.requested")
    assert d.aktor == "otomasyon" and d.ozet["tetikleyen"] == analist.kullanici_adi

    # Aynı içerik için süren üretim varken ikinci çağrı yeni script açmaz.
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert otokod.kuyruga_al(s, tc, analist)["durum"] == "atlandi"
    assert len(_scriptler(c["id"])) == 1


def test_duzelt_karari_da_tetikler(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    yeni = {**c["icerik"], "title": c["icerik"]["title"] + " yapılır"}
    r = api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "edit", "icerik_hash": c["icerik_hash"], "icerik": yeni},
    )
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"]["durum"] == "kuyrukta"


def test_ret_karari_tetiklemez(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    r = api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "reject", "icerik_hash": c["icerik_hash"], "ret_nedeni": "duplicate"},
    )
    assert r.status_code == 200 and r.json()["otomatik_kod"] is None
    assert _scriptler(c["id"]) == []


def test_ayar_kapali_script_olusmaz(api: TestClient, hazir) -> None:
    rid, _ = hazir
    otomatik_kod_ayari(False)
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"]["durum"] == "kapali"
    assert _scriptler(c["id"]) == []


def test_codegen_reddi_onayi_geri_almaz(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, _ = hazir
    monkeypatch.setattr(codegen_service, "replay_temel_durum_engeli", lambda: "REPLAY engeli")
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    ok = r.json()["otomatik_kod"]
    assert ok["durum"] == "reddedildi" and "REPLAY engeli" in ok["neden"]
    assert r.json()["durum"] == "approved"
    assert _scriptler(c["id"]) == []
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(c["id"])).durum == "approved"


def test_beklenmeyen_hata_onayi_geri_almaz_ve_denetlenir(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, _ = hazir

    def patlayan(session, case_ids, user, **_kw):
        # SAVEPOINT içinde yazılan satır ve denetim kaydı geri alınmalı.
        session.add(Script(tur="test", dosya_yolu="x.spec.ts", platform="web"))
        session.flush()
        audit_on_commit(session, "otomasyon", "codegen.requested", "script:x", {})
        raise RuntimeError("beklenmedik")

    monkeypatch.setattr(otokod, "start_generation", patlayan)
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"]["durum"] == "hata"
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(c["id"])).durum == "approved"
        assert s.scalars(select(Script).where(Script.dosya_yolu == "x.spec.ts")).first() is None
    assert _denetim("codegen.requested") == []
    [d] = _denetim("codegen.otomatik_hata")
    assert d.aktor == "otomasyon" and d.nesne == f"test_case:{c['id']}"


def _pr_ac(script_id: str) -> None:
    """Test kurulumu: script'i `pr_open`'a çeker (forge/CI akışı olmadan)."""
    with allow_state_write(), session_scope() as s:
        s.get(Script, uuid.UUID(script_id)).durum = "pr_open"


def test_otomatik_uretim_acik_prye_dokunmaz_elle_uretim_kapatir(
    api: TestClient, hazir, make_user
) -> None:
    """K16: otomatik tetik açık PR'lı script'i kapatmaz (`atlandi`); elle üretim aynı kalır."""
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    sid = _onayla(api, c).json()["otomatik_kod"]["script_id"]
    _pr_ac(sid)
    # Aynı içerik bile olsa, farklı içerik (yeniden açma + düzeltme) de olsa: dokunulmaz.
    api.post(
        f"/cases/{c['id']}/decision", json={"karar": "reopen", "icerik_hash": c["icerik_hash"]}
    )
    yeni = {**c["icerik"], "title": c["icerik"]["title"] + " yapılır"}
    r = api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "edit", "icerik_hash": c["icerik_hash"], "icerik": yeni},
    )
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"] == {
        "durum": "atlandi", "neden": "Açık PR var; yeniden üretim mühendis kararıyla",
        "script_id": sid,
    }  # fmt: skip
    with session_scope() as s:
        assert s.get(Script, uuid.UUID(sid)).durum == "pr_open"
    assert len(_scriptler(c["id"])) == 1

    # Elle üretim (mühendis): içerik değiştiği için eski PR kapanır, yeni script açılır.
    with session_scope() as s:
        cevap = codegen_service.start_generation(s, [uuid.UUID(c["id"])], make_user("engineer"))
    assert cevap["sonuclar"][0]["durum"] == "basladi"
    with session_scope() as s:
        assert s.get(Script, uuid.UUID(sid)).durum == "closed"


def test_sir_tanimsizsa_acik_pr_reddedilmez_atlanir(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atıf çözümü atlama kararından SONRA: açık PR'lı case `pr_acik` döner, `reddedildi` değil."""
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    sid = _onayla(api, c).json()["otomatik_kod"]["script_id"]
    _pr_ac(sid)

    def cozulemez(_s, _icerik):
        raise testveri.TestVerisiCozulemedi("test verisi sırrı tanımsız: ortak.x", ["ortak.x"])

    monkeypatch.setattr(testveri, "case_coz", cozulemez)
    with session_scope() as s:
        cevap = codegen_service.start_generation(
            s, [uuid.UUID(c["id"])], otokod.OTOMASYON_AKTORU, tetik="otomatik"
        )
        assert cevap["sonuclar"][0]["durum"] == "pr_acik"
        # Elle, aynı hash: veri çözülemiyor → red; açık PR KAPATILMAZ.
        with pytest.raises(codegen_service.CodegenRejected, match="Test verisi sırrı tanımsız"):
            codegen_service.start_generation(s, [uuid.UUID(c["id"])], otokod.OTOMASYON_AKTORU)
        assert s.get(Script, uuid.UUID(sid)).durum == "pr_open"


def test_toplu_onay_tek_otomatik_is_parcalarla_uretir(
    api: TestClient, hazir, engine: Engine, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uçtan uca (K16): toplu onay → tek `codegen.otomatik` işi → worker → script'ler otomatik."""
    rid, analist = hazir
    monkeypatch.setattr(otokod, "MAX_CASE", 1)  # 2 case → 2 parça
    cagri: list[int] = []
    asil = otokod.start_generation

    def say(session, case_ids, user, **kw):
        cagri.append(len(case_ids))
        return asil(session, case_ids, user, **kw)

    monkeypatch.setattr(otokod, "start_generation", say)
    cs = latest_cases(api, rid)
    goruntule(api, db, *[c["id"] for c in cs])
    govde = {
        "karar": "approve",
        "ogeler": [{"case_id": c["id"], "icerik_hash": c["icerik_hash"]} for c in cs],
    }
    r = api.post("/cases/bulk-decision", json=govde)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [s["otomatik_kod"] for s in out["sonuclar"]] == [None, None]
    ok = out["otomatik_kod"]
    assert ok["durum"] == "kuyrukta" and ok["case_sayisi"] == 2 and ok["job_id"]
    assert cagri == [] and all(_scriptler(c["id"]) == [] for c in cs)  # istek içinde üretim yok
    with session_scope() as s:
        job = s.get(Job, uuid.UUID(ok["job_id"]))
        assert job.tur == "codegen.otomatik" and job.idempotency_key.startswith("codegen.otomatik:")
        assert job.yuk["tetikleyen"] == analist.kullanici_adi
    [d] = _denetim("cases.bulk_decision")
    assert d.ozet["otomatik_kod"]["job_id"] == ok["job_id"]

    sonuc = process_one(engine, "test-worker")
    assert sonuc is not None
    with session_scope() as s:
        job = s.get(Job, uuid.UUID(ok["job_id"]))
        assert job.durum == "done", job.hata
        assert job.sonuc["ozet"] == {"kuyrukta": 2} and cagri == [1, 1]
    for c in cs:
        [cg] = _scriptler(c["id"])
        assert cg.tetik == "otomatik"


def test_toplu_onay_ayar_kapali_is_yok(api: TestClient, hazir, db) -> None:
    rid, _ = hazir
    otomatik_kod_ayari(False)
    c = latest_cases(api, rid)[0]
    goruntule(api, db, c["id"])
    r = api.post(
        "/cases/bulk-decision",
        json={
            "karar": "approve",
            "ogeler": [{"case_id": c["id"], "icerik_hash": c["icerik_hash"]}],
        },
    )
    assert r.json()["otomatik_kod"] == {
        "durum": "kapali", "job_id": None, "case_sayisi": 0, "atlanan": [],
    }  # fmt: skip
    with session_scope() as s:
        assert s.scalars(select(Job).where(Job.tur == "codegen.otomatik")).first() is None


def test_toplu_kuyruga_al_sureni_once_ayirir_is_sonucu_uctan_okunur(
    api: TestClient, hazir, engine: Engine, make_user
) -> None:
    """QA #3: üretimi süren case işe alınmaz (`atlanan` + neden); `case_sayisi` yalnız işe
    alınanlar; iş sonucu case başına `GET /automation/codegen-jobs/{id}`'den okunur."""
    rid, analist = hazir
    c1, c2 = latest_cases(api, rid)
    assert _onayla(api, c1).json()["otomatik_kod"]["durum"] == "kuyrukta"  # script pending
    otomatik_kod_ayari(False)
    assert _onayla(api, c2).status_code == 200
    otomatik_kod_ayari(True)
    with session_scope() as s:
        ok = otokod.toplu_kuyruga_al(s, [uuid.UUID(c1["id"]), uuid.UUID(c2["id"])], analist)
    assert ok["durum"] == "kuyrukta" and ok["case_sayisi"] == 1
    assert ok["atlanan"] == [{"case_id": c1["id"], "neden": otokod.SURUYOR_NEDENI}]
    with session_scope() as s:
        assert s.get(Job, uuid.UUID(ok["job_id"])).yuk["case_ids"] == [c2["id"]]
        # Tümü atlanırsa iş yok.
        hepsi = otokod.toplu_kuyruga_al(s, [uuid.UUID(c1["id"])], analist)
    assert hepsi["durum"] == "yok" and hepsi["job_id"] is None and len(hepsi["atlanan"]) == 1

    login(api, make_user("po"))
    r = api.get(f"/automation/codegen-jobs/{ok['job_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "queued" and r.json()["sonuclar"] == []
    assert r.json()["case_ids"] == [c2["id"]] and r.json()["hata"] is None
    while process_one(engine, "test-worker") is not None:
        with session_scope() as s:
            if s.get(Job, uuid.UUID(ok["job_id"])).durum == "done":
                break
    g = api.get(f"/automation/codegen-jobs/{ok['job_id']}").json()
    assert g["durum"] == "done" and g["ozet"] == {"kuyrukta": 1}
    [o] = g["sonuclar"]
    assert o["case_id"] == c2["id"] and o["durum"] == "kuyrukta" and o["script_id"]
    assert api.get(f"/automation/codegen-jobs/{uuid.uuid4()}").status_code == 404
    with session_scope() as s:
        baska = s.scalars(select(Job).where(Job.tur != "codegen.otomatik")).first()
    if baska is not None:
        assert api.get(f"/automation/codegen-jobs/{baska.id}").status_code == 404


def test_toplu_uret_parca_hatasi_sonraki_parcalari_dusurmez(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mimar #6: bir parçadaki beklenmeyen hata yalnız o parçayı `hata` yapar ve denetlenir."""
    rid, _ = hazir
    otomatik_kod_ayari(False)
    cs = latest_cases(api, rid)
    for c in cs:
        assert _onayla(api, c).status_code == 200
    otomatik_kod_ayari(True)
    monkeypatch.setattr(otokod, "MAX_CASE", 1)
    asil = otokod.start_generation

    def ilki_patlar(session, case_ids, user, **kw):
        if str(case_ids[0]) == cs[0]["id"]:
            raise RuntimeError("forge erişilemedi")
        return asil(session, case_ids, user, **kw)

    monkeypatch.setattr(otokod, "start_generation", ilki_patlar)
    out = otokod.toplu_uret({"case_ids": [c["id"] for c in cs], "tetikleyen": "analist"})
    assert [o["durum"] for o in out["sonuclar"]] == ["hata", "kuyrukta"]
    assert out["sonuclar"][0]["neden"] == otokod.PARCA_HATA_NEDENI
    assert out["ozet"] == {"hata": 1, "kuyrukta": 1}
    [d] = _denetim("codegen.otomatik_hata")
    assert d.ozet["case_ids"] == [cs[0]["id"]] and d.ozet["hata"] == "RuntimeError"


# --------------------------------------------------------------------- ayar API'si


def test_ayar_api_rol_kapisi_ve_dogrulama(api: TestClient, make_user) -> None:
    login(api, make_user("po"))
    r = api.get("/automation-settings")
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod_uretimi"]["acik"] is False  # fikstür kapalı başlatır
    assert r.json()["jira_tetik"]["durum"] == "QA To Do"
    r = api.put("/automation-settings/otomatik_kod_uretimi", json={"acik": True})
    assert r.status_code == 403

    muhendis = make_user("engineer")
    login(api, muhendis)
    r = api.put("/automation-settings/otomatik_kod_uretimi", json={"acik": True})
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod_uretimi"]["acik"] is True
    assert r.json()["otomatik_kod_uretimi"]["guncelleyen"] == muhendis.kullanici_adi

    login(api, make_user("engineer"))  # durum alanı yalnız engineer (K14)
    r = api.put("/automation-settings/jira_tetik", json={"aralik_s": 120, "durum": "QA Hazır"})
    assert r.status_code == 200, r.text
    j = r.json()["jira_tetik"]
    assert j["aralik_s"] == 120 and j["durum"] == "QA Hazır" and j["acik"] is True

    r = api.put("/automation-settings/yok", json={"acik": True})
    assert r.status_code == 404 and "Bilinmeyen" in r.json()["detail"]
    for govde in ({"aralik_s": 5}, {"acik": "evet"}, {"bilinmeyen": 1}):
        r = api.put("/automation-settings/jira_tetik", json=govde)
        assert r.status_code == 422, (govde, r.text)
        assert "Geçersiz ayar" in r.json()["detail"]
    assert api.put("/automation-settings/jira_tetik", json=[1]).status_code == 422
    assert api.get("/automation-settings").json()["jira_tetik"]["aralik_s"] == 120
    assert len(_denetim("otomasyon.ayar")) == 2


def test_demo_ayarlari_otomatik_kodu_kapatir_k20(engine: Engine) -> None:
    """K20: seed (yalnız satır yoksa) ve demo sıfırlaması (zorla) otomatik kodu denetimli kapatır;
    ürün varsayılanı açık kalır."""
    from tp_core.features.demo import service as demo_service
    from tp_core.features.otomasyon import ayarlar
    from tp_core.seed import seed_otomasyon_demo

    with session_scope() as s:
        assert ayarlar.otomatik_kod(s).acik is True  # ürün varsayılanı
    assert seed_otomasyon_demo() == {"otomatik_kod_uretimi": "yazildi"}
    with session_scope() as s:
        assert ayarlar.otomatik_kod(s).acik is False
    [d] = _denetim("otomasyon.ayar")
    assert d.aktor == "seed" and d.ozet["yeni"] == {"acik": False}
    otomatik_kod_ayari(True)  # kullanıcı bilerek açtı
    assert seed_otomasyon_demo() == {"otomatik_kod_uretimi": "korundu"}
    with session_scope() as s:
        assert ayarlar.otomatik_kod(s).acik is True
    assert demo_service._otomasyon_demo_ayarlari() == {"otomatik_kod_uretimi": "yazildi"}
    assert demo_service._otomasyon_demo_ayarlari() == {"otomatik_kod_uretimi": "zaten"}
    with session_scope() as s:
        assert ayarlar.otomatik_kod(s).acik is False
    assert [d.aktor for d in _denetim("otomasyon.ayar")][-1] == "demo"

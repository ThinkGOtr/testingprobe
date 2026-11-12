"""011 D1 şeridi — iş akışı: zaman aşımı bütçeleri (#2), iki tur (#3, #4, #5/K20), kilit sırası
(#11), kimlik ad alanı (#13), derinleştirme özeti (#14), derinleştirme sürerken üretim (#15),
katman/guard kaydı (#16), model kararı girdisi (#17), IDE taslağından sonra review (#18).
"""

from __future__ import annotations

import ast
import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, event, select, text

import tp_core.features.tasarim_modeli.jobs  # noqa: F401  (model.generate işleyicisi)
from tp_core.features.cases import model_service, service
from tp_core.features.tasarim_modeli.api import MODEL_ICERIK_SINIRI, ModelKararGirdisi
from tp_core.gateway.errors import ProviderPermanentError
from tp_core.gateway.testing import text_response
from tp_core.models import (
    AiCall,
    CaseSetReview,
    Requirement,
    TasarimModeli,
    session_scope,
)
from tp_core.workflow import states
from tp_core.workflow.service import Principal

from .helpers import case_icerik, latest_cases, login, ozet_icerik, run_jobs, uretim_cikti

RULES = Path(__file__).resolve().parents[5] / "rules"
SRC = Path(__file__).resolve().parents[4] / "src" / "tp_core"


def _golden(ad: str, amac: str) -> dict[str, Any]:
    return json.loads((RULES / "replay" / amac / "golden" / f"{ad}.json").read_text())


def _durum(rid: uuid.UUID) -> str:
    with session_scope() as s:
        return s.get(Requirement, rid).durum


def _model(api: TestClient, rid: uuid.UUID) -> dict[str, Any]:
    return api.get(f"/requirements/{rid}/design-model").json()["model"]


def _karar(api: TestClient, m: dict[str, Any], karar: str, **ek: Any) -> Any:
    return api.post(
        f"/design-models/{m['id']}/decision",
        json={"karar": karar, "icerik_hash": m["icerik_hash"], **ek},
    )


def _bekleyen_isi_hemen(engine: Engine) -> None:
    """Yeniden denenecek işin beklemesini kaldırır (backoff testte beklenmez)."""
    with engine.begin() as c:
        c.execute(text("UPDATE job SET run_after = now() WHERE durum = 'retry'"))


# --------------------------------------------------------------- #2 zaman aşımı bütçesi

IS_AMACI = {
    "cases.generate": "case_generation",
    "cases.deepen": "case_deepening",
    "cases.review": "case_review",
    "cases.audit": "case_audit",
    "model.generate": "design_model",
}


def test_zaman_asimi_butcesi_is_suresini_asmaz() -> None:
    """Geçidin en kötü süresi iş süresini aşmaz; aksi halde iş zaman aşımına uğrar ve worker
    süreci çıkar (diğer şeritler sahipsiz kalır).

    - İlk çağrı: timeout × (1 + zaman aşımı yeniden denemesi) + 120 ≤ iş süresi.
    - Şema/kural yeniden istemeleri (en çok 1 + MAX_SCHEMA_REASKS çağrı): sınırsız toplam bazı
      amaçlarda iş süresini aşar; geçit her yeniden istemeden önce kalan iş süresine bakar
      (`reask_fits`). En kötü durum benzetimi (her çağrı tam timeout sürer) iş süresinde kalmalı."""
    import tp_core.features.cases.jobs  # noqa: F401
    from tp_core.gateway.config import find_rules_dir, load_model_table
    from tp_core.gateway.core import (
        MAX_SCHEMA_REASKS,
        YENIDEN_ISTEME_PAYI_S,
        RetryPolicy,
        reask_fits,
        worst_call_s,
    )
    from tp_core.workflow.jobs import REGISTRY

    tablo = load_model_table(find_rules_dir())
    sinirsiz_asan = []
    for tur, amac in IS_AMACI.items():
        cfg = tablo.purpose(amac)
        tekrar = (
            cfg.max_timeout_retries
            if cfg.max_timeout_retries is not None
            else RetryPolicy().max_timeout_retries
        )
        assert cfg.timeout_s is not None
        za = REGISTRY[tur].zaman_asimi_s
        tek = worst_call_s(cfg)
        assert tek == cfg.timeout_s * (1 + tekrar)
        assert za >= tek + 120, (tur, amac, tek)
        assert tekrar == 0, amac  # uzun amaçlarda zaman aşımını iş kuyruğu yeniden dener
        # En kötü durum: her deneme tam `tek` sürer; geçidin süre denetimiyle.
        gecen = tek
        for _ in range(MAX_SCHEMA_REASKS):
            if not reask_fits(cfg, za - gecen):
                break
            gecen += tek
        assert gecen + min(120.0, YENIDEN_ISTEME_PAYI_S) <= za, (tur, amac, gecen, za)
        if tek * (1 + MAX_SCHEMA_REASKS) + 120 > za:
            sinirsiz_asan.append(tur)
    # Denetim gerçekten gerekli (sınırsız döngü en az bir işte iş süresini aşardı).
    assert sinirsiz_asan


def test_is_kuyrugu_gecide_kalan_sureyi_verir(monkeypatch: pytest.MonkeyPatch) -> None:
    """`execute_with_timeout` işleyiciyi `is_suresi(zaman_asimi_s)` içinde koşar."""
    from tp_core.gateway.is_suresi import kalan_sure
    from tp_core.workflow.jobs import ClaimedJob, HandlerSpec, Sonuc, execute_with_timeout

    gorulen: list[float | None] = []

    def isleyici(job, kayit):
        gorulen.append(kalan_sure())
        return Sonuc("done", 0, None)

    import tp_core.workflow.jobs as jobs_mod

    spec = HandlerSpec("t.sure", lambda ctx: None, 1, 1.0, 1.0, 50, "genel")
    job = ClaimedJob(uuid.uuid4(), "t.sure", {}, 1, 1, None, 50)
    monkeypatch.setattr(jobs_mod, "execute", isleyici)
    sonuc = execute_with_timeout(job, {"t.sure": spec})
    assert sonuc.durum == "done"
    assert gorulen[0] is not None and 45 < gorulen[0] <= 50
    assert kalan_sure() is None  # iş dışında sınırsız


# ----------------------------------------------------------- #3/#5 iki tur ve K20


def test_tur2_hatasi_onayli_modeli_korur_ve_kip_saklanir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    model = _golden("TPD-4", "design_model")["output"]
    cases = _golden("TPD-4", "case_generation")["output"]
    provider = fake_gateway(
        [
            text_response(model),
            ProviderPermanentError("model erişilemiyor", status=400),
            ProviderPermanentError("model erişilemiyor", status=400),
            text_response(cases),
        ]
    )
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    assert r.status_code == 202 and r.json()["asama"] == "model"
    run_jobs(engine)
    secenek = api.get(f"/requirements/{rid}/generation-options").json()["secenekler"]
    assert secenek["kip"] == "iki_tur"  # açıkça seçilen kip saklanır (K20)
    m = _model(api, rid)
    r = _karar(api, m, "approve")
    assert r.status_code == 200 and r.json()["tur2_baslatildi"] is True
    # Tur 2 iki denemede de başarısız → failed; onaylı model korunur.
    run_jobs(engine)
    _bekleyen_isi_hemen(engine)
    run_jobs(engine)
    assert _durum(rid) == "failed"
    assert _model(api, rid)["durum"] == "approved"
    # Kipsiz (gövdesiz) çağrı kayıtlı kipi (iki_tur) kullanır ve doğrudan tur 2'ye gider.
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202, r.text
    assert (r.json()["kip"], r.json()["asama"]) == ("iki_tur", "case")
    (is_,) = run_jobs(engine)
    assert is_.durum == "done" and _durum(rid) == "cases_ready"
    with session_scope() as s:
        assert len(s.scalars(select(TasarimModeli)).all()) == 1  # model yeniden üretilmedi
        amaclar = [a.amac for a in s.scalars(select(AiCall)).all()]
    assert amaclar.count("design_model") == 1
    assert len(provider.requests) == 4
    # Model ancak açıkça yeniden üretilir.
    r = api.post(f"/requirements/{rid}/design-model")
    assert r.status_code == 202 and _durum(rid) == "modeling"


def test_govdesiz_cagri_kayit_yoksa_tek_tur_kip_verilirse_saklanir(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.json()["kip"] == "tek_tur"
    run_jobs(engine)
    secenek = api.get(f"/requirements/{rid}/generation-options").json()["secenekler"]
    assert secenek is None  # gövdesiz çağrı kayıt yazmaz (prova, IDE)
    r = api.post(f"/requirements/{rid}/generate-cases", json={"kip": "tek_tur"})
    assert r.status_code == 202
    secenek = api.get(f"/requirements/{rid}/generation-options").json()["secenekler"]
    assert secenek["kip"] == "tek_tur" and secenek["test_seviyesi"] == "SYSTEM"


def test_model_onayi_tur2_baslatamazsa_karar_kaydedilir(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway, monkeypatch
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/design-model")
    run_jobs(engine)
    m = _model(api, rid)

    def kapali(_req: Any) -> None:
        raise service.GateClosed("PO onay etiketi Jira'dan doğrulanamadı")

    monkeypatch.setattr(service, "_jira_po_etiketi_denetle", kapali)
    r = _karar(api, m, "approve")
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "approved" and r.json()["tur2_baslatildi"] is False
    assert "Jira'dan doğrulanamadı" in r.json()["tur2_engeli"]
    assert _durum(rid) == "model_ready"
    monkeypatch.undo()
    r = api.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    assert r.status_code == 202 and r.json()["asama"] == "case"


# --------------------------------------------------------------------- #4 seçenekler


def test_tasarim_modeli_uretim_seceneklerini_gorur(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    provider = fake_gateway([text_response(_golden("TPD-4", "design_model")["output"])])
    rid = make_requirement()
    login(api, make_user("analyst"))
    r = api.post(
        f"/requirements/{rid}/generate-cases",
        json={"kip": "iki_tur", "platformlar": ["Web"], "test_seviyesi": "E2E"},
    )
    assert r.status_code == 202, r.text
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_.hata
    girdi = provider.requests[0].messages[0]["content"]
    assert "Platform ekleri" in girdi and "Test seviyesi: E2E" in girdi
    assert 'source="jira:TPD-4:secenekler"' in girdi
    with session_scope() as s:
        cagri = s.scalars(select(AiCall).where(AiCall.amac == "design_model")).one()
        assert cagri.ek["platformlar"] == ["Web"]
        assert {e["id"] for e in cagri.ek["platform_ekleri"]} >= {"platform-web"}


# ------------------------------------------------------------------- #11 kilit sırası


def test_model_karari_once_gereksinimi_sonra_modeli_kilitler(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    api.post(f"/requirements/{rid}/design-model")
    run_jobs(engine)
    m = _model(api, rid)
    kilitler: list[str] = []

    def dinle(_c: Any, _cur: Any, sql: str, *_a: Any) -> None:
        if "FOR UPDATE" in sql:
            for tablo in ("tasarim_modeli", "requirement"):
                if f"FROM {tablo}" in sql:
                    kilitler.append(tablo)
                    break

    event.listen(Engine, "before_cursor_execute", dinle)
    try:
        with session_scope() as s:
            model_service.decide_model(
                s,
                uuid.UUID(m["id"]),
                Principal(analist.id, analist.kullanici_adi, "analyst"),
                karar="approve",
                icerik_hash=m["icerik_hash"],
            )
    finally:
        event.remove(Engine, "before_cursor_execute", dinle)
    assert kilitler[:2] == ["requirement", "tasarim_modeli"], kilitler


# ---------------------------------------------------------------- #13 kimlik ad alanı


def test_tam_yeniden_uretim_korunan_kimlikleri_bilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    ilk = [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2", type="negative")]
    ikinci = [case_icerik(title="Ana akış yeniden")]
    farkli = {
        "coverage_items": [
            {"id": "UC-MF", "ac_ref": "AC1", "definition": "Başka bir akış", "valid": True}
        ]
    }
    provider = fake_gateway(
        [text_response(uretim_cikti(ilk)), text_response(uretim_cikti(ikinci, **farkli))]
    )
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    assert "Korunan case'lerin kimlikleri" not in provider.requests[0].messages[0]["content"]
    c1 = latest_cases(api, rid)[0]
    api.post(
        f"/cases/{c1['id']}/decision", json={"karar": "approve", "icerik_hash": c1["icerik_hash"]}
    )
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    girdi = provider.requests[1].messages[0]["content"]
    assert "Korunan case'lerin kimlikleri" in girdi and "UC-MF" in girdi
    assert "Yeni kimlik numaraları: EP-V: 1" in girdi
    assert is_.deger["kimlik_cakismalari"] and any(
        "korunan case'lerin kimliklerini farklı tanımla" in u for u in is_.deger["uyarilar"]
    )


# ------------------------------------------------- #14/#15 derinleştirme ve özet


def _ilk_uretim(api: TestClient, engine: Engine, make_user, make_requirement, provider_kur, *ek):
    ilk = [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2", type="negative")]
    ozet = {
        "assumptions": [{"id": "A1", "statement": "Kilit 5 denemede", "owner": "PO"}],
    }
    provider = provider_kur([text_response(uretim_cikti(ilk, **ozet)), *ek])
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    return rid, provider


def test_derinlestirme_casei_mevcut_ogelere_atif_yapabilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    # Derinleştirme özeti UC-MF / A1'i yeniden tanımlamaz; case'ler onlara atıf yapar.
    yeni = case_icerik(title="Ana akış — oturum süresi", covers=["UC-MF"])
    varsayimli = case_icerik(
        title="Kilit sonrası giriş",
        ref="AC2",
        readiness="assumption_dependent",
        assumption_refs=["A1"],
    )
    cikti = uretim_cikti([yeni, varsayimli], coverage_items=[])
    rid, _ = _ilk_uretim(
        api, engine, make_user, make_requirement, fake_gateway, text_response(cikti)
    )
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"}).status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_.hata
    assert is_.deger["tutarsiz"] == {}
    cases = {c["icerik"]["title"]: c for c in latest_cases(api, rid)}
    d = cases["Ana akış — oturum süresi"]
    assert d["uretim_no"] == 2 and d["uyarilar"] == [] and d["onay_engeli"] is None
    assert cases["Kilit sonrası giriş"]["varsayimlar"][0]["id"] == "A1"
    r = api.post(
        f"/cases/{d['id']}/decision", json={"karar": "approve", "icerik_hash": d["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    ozet = api.get(f"/requirements/{rid}/case-summary").json()
    assert not any("tutarsız" in u for u in ozet["uyarilar"])


def test_derinlestirme_surerken_uretim_ve_model_409(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    rid, _ = _ilk_uretim(api, engine, make_user, make_requirement, fake_gateway)
    assert api.post(f"/requirements/{rid}/deepen", json={"tur": "negatif"}).status_code == 202
    for yol, govde in (
        ("generate-cases", None),
        ("generate-cases", {"kip": "iki_tur"}),
        ("design-model", None),
    ):
        r = api.post(f"/requirements/{rid}/{yol}", **({"json": govde} if govde else {}))
        assert r.status_code == 409 and "derinleştirme" in r.json()["detail"], (yol, r.text)
    assert _durum(rid) == "cases_ready"


# ------------------------------------------------------------- #16 katman / guard


def test_workflow_katmani_featurese_bagimli_degil() -> None:
    for yol in (SRC / "workflow").glob("*.py"):
        agac = ast.parse(yol.read_text())
        for dugum in ast.walk(agac):
            if isinstance(dugum, ast.ImportFrom) and dugum.module:
                assert not dugum.module.startswith("tp_core.features"), (yol.name, dugum.module)
            if isinstance(dugum, ast.Import):
                assert not any(a.name.startswith("tp_core.features") for a in dugum.names)


def test_kayitsiz_kosul_gecisi_reddeder(monkeypatch) -> None:
    import tp_core.features.agent_probe.service as ap

    monkeypatch.setattr(states, "_KAYITLI_KOSULLAR", {})
    assert states._ajan_testi_gecti(object()) is False  # kayıtsız: fail-closed
    states.register_guard(states.AJAN_TESTI_GECTI, lambda _r: True)
    assert states._ajan_testi_gecti(object()) is True
    monkeypatch.undo()
    assert states._KAYITLI_KOSULLAR[states.AJAN_TESTI_GECTI] is ap.ajan_testi_gecti


# ------------------------------------------------------------ #17 model kararı girdisi


def test_model_karari_girdisi_siki() -> None:
    temel = {"karar": "reject", "icerik_hash": "h", "ret_nedeni": "wrong_technique"}
    assert ModelKararGirdisi.model_validate(temel).ret_nedeni == "wrong_technique"
    with pytest.raises(ValidationError):  # bilinmeyen alan
        ModelKararGirdisi.model_validate({**temel, "onayla": True})
    with pytest.raises(ValidationError):  # case taksonomisi modele uygulanmaz
        ModelKararGirdisi.model_validate({**temel, "ret_nedeni": "hallucinated_step"})
    buyuk = {"x": "a" * (MODEL_ICERIK_SINIRI + 1)}
    with pytest.raises(ValidationError):
        ModelKararGirdisi.model_validate({"karar": "edit", "icerik_hash": "h", "icerik": buyuk})
    assert "wrong_technique" not in states.ret_nedenleri("test_case")
    assert "hallucinated_step" not in states.ret_nedenleri("design_model")
    assert states.ret_nedenleri("design_model") <= states.TUM_RET_NEDENLERI


def test_model_ret_nedeni_kaydedilir_case_nedeni_reddedilir(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("analyst"))
    api.post(f"/requirements/{rid}/design-model")
    run_jobs(engine)
    m = _model(api, rid)
    assert _karar(api, m, "reject", ret_nedeni="duplicate").status_code == 422
    r = _karar(api, m, "reject", ret_nedeni="invented_rule", gerekce="kaynakta yok")
    assert r.status_code == 200 and r.json()["kararlar"][0]["ret_nedeni"] == "invented_rule"
    kopya = copy.deepcopy(m)
    assert _karar(api, kopya, "approve", fazla=1).status_code == 422


# ----------------------------------------------------- #18 IDE taslağından sonra review


def test_ide_taslagi_review_planlar(make_user, make_requirement) -> None:
    rid = make_requirement()
    u = make_user("analyst")
    ide = Principal(u.id, u.kullanici_adi, "analyst", kanal="ide", kapsam="submit")
    with session_scope() as s:
        service.submit_drafts(s, "TPD-4", [case_icerik()], ide, ozet=ozet_icerik([case_icerik()]))
    with session_scope() as s:
        satir = s.scalars(select(CaseSetReview)).one()
        assert satir.requirement_id == rid and satir.uretim_no == 1 and satir.job_id

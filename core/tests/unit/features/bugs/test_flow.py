"""Bug taslağı → mükerrer araması → testçi kararı → publish_bug (gerçek Postgres + jira-sim)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.bugs.helpers import seed_failure, seed_finding_draft
from tests.unit.features.cases.helpers import login, run_jobs
from tp_core.audit import content_hash
from tp_core.features.bugs import api as bugs_api
from tp_core.features.bugs import content, service, services
from tp_core.gateway.testing import text_response
from tp_core.integrations.jira import RestJira
from tp_core.models import AiCall, AuditEvent, BugDraft, ExternalRef, Review, session_scope
from tp_core.models.bugs_feature import BugDraftEk
from tp_core.workflow.service import WorkflowError

pytestmark = pytest.mark.usefixtures("db")


def _ai_taslak(**over: Any) -> dict[str, Any]:
    taslak = {
        "summary": "Sepet: 6 adette kampanya bedava ürün erken veriliyor",
        "steps": [
            "1. bayi1 ile giriş yap",
            "2. Portakal Gazozu 1L ürününden 6 adet sepete ekle",
            "3. Sepetteki bedava adedi kontrol et",
        ],
        "expected": "Bedava adet 0 (indirim 0,00 TL)",
        "actual": "Bedava adet 1 (indirim 25,00 TL)",
        "environment": "Yerel demo ortamı, Chromium",
        "evidence": [
            {"kind": "trace", "ref": "kanit:trace"},
            {"kind": "trace", "ref": "https://kotu.example/trace.zip"},
            {"kind": "allure", "ref": "kanit:allure"},
            {"kind": "log", "ref": "kanit:error_context"},
        ],
        "story_key": "TPD-9",
        "test_case_key": None,
        "severity_suggestion": "critical",
        "labels": ["AI-generated"],
    }
    taslak.update(over)
    return taslak


def _ai_sira(link: bool = True, ek: list[str] | None = None) -> dict[str, Any]:
    adaylar = [
        {
            "key": "TPD-5",
            "rank": 1,
            "likelihood": "high",
            "rationale": "Aynı AC2 sınırı: 6 adette bedava 1 adet (beklenen 0).",
        }
    ]
    for i, k in enumerate(ek or [], start=2):
        adaylar.append({"key": k, "rank": i, "likelihood": "high", "rationale": "uydurma"})
    return {
        "candidates": adaylar,
        "recommendation": "link" if link else "new",
        "link_key": "TPD-5" if link else None,
    }


def _draft(draft_id: uuid.UUID) -> tuple[BugDraft, BugDraftEk]:
    with session_scope() as s:
        b = s.get(BugDraft, draft_id)
        ek = s.get(BugDraftEk, draft_id)
        assert b is not None and ek is not None
        return b, ek


def _yeni_taslak(**kw: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    ids = seed_failure(services.jira(), **kw)
    with session_scope() as s:
        did = service.create_draft_from_failure(s, ids["failure_id"])
    return did, ids


def _hazirla(engine: Engine) -> None:
    sonuclar = run_jobs(engine)
    assert sonuclar and all(r.durum == "done" for r in sonuclar), sonuclar


def _bugs(jira: RestJira) -> list[str]:
    return [i.key for i in jira.search('project = "TPD" AND issuetype = "Bug"', max_results=50)]


# ------------------------------------------------------------------ taslak açılışı


def test_taslak_sablonla_acilir_ve_idempotent(engine: Engine, bug_services: RestJira) -> None:
    did, ids = _yeni_taslak()
    b, ek = _draft(did)
    assert b.durum == "draft" and b.failure_id == ids["failure_id"]
    assert content.validation_errors(b.icerik) == []
    # Literal değerler başarısızlıktan (ANSI kodları ve tırnaklar temizlenmiş).
    assert "Gerçekleşen değer: 1" in b.icerik["actual"]
    assert "bedava adet 0" in b.icerik["expected"]
    assert b.icerik["story_key"] == "TPD-1"
    assert b.icerik["test_case_key"] == ids["test_key"]
    assert {e["kind"] for e in b.icerik["evidence"]} >= {"allure", "trace", "screenshot", "log"}
    kok = f"/api/artifacts/runs/{ids['run_id']}/"
    assert all(e["ref"].startswith(kok) for e in b.icerik["evidence"])
    assert ek.hazirlik_durum == "kuyrukta" and ek.uretim == "sablon"
    assert ek.imza["ac"] == "AC2" and ek.imza["case_ref"] == "TPD-1-C3"
    assert ek.imza["locator"] == "getByTestId('cart-line-free-P-001')"
    assert ek.imza["gerceklesen"] == '"1"' and "kampanyalı" in ek.imza["terimler"]
    # Aynı başarısızlık → aynı taslak; aynı imzalı yeni başarısızlık → aynı taslağa eklenir.
    with session_scope() as s:
        assert service.create_draft_from_failure(s, ids["failure_id"]) == did
    ids2 = seed_failure(bug_services, req_id=ids["requirement_id"], test_issue=False)
    with session_scope() as s:
        assert service.create_draft_from_failure(s, ids2["failure_id"]) == did
    _, ek = _draft(did)
    assert ek.ilgili_failure_ids == [str(ids2["failure_id"])]


def test_ortam_hatasi_taslak_acmaz(engine: Engine, bug_services: RestJira) -> None:
    ids = seed_failure(bug_services, sinif="environment")
    with session_scope() as s, pytest.raises(WorkflowError, match="product_defect"):
        service.create_draft_from_failure(s, ids["failure_id"])
    with session_scope() as s:
        assert s.scalar(select(BugDraft.id)) is None


# --------------------------------------------------------- hazırlık (FakeProvider)


def test_hazirlik_mukerrer_adayi_ve_deterministik_duzeltmeler(
    engine: Engine, bug_fake_gateway: Any
) -> None:
    provider = bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, ids = _yeni_taslak(triage_ek=True)
    _hazirla(engine)
    b, ek = _draft(did)
    assert ek.hazirlik_durum == "hazir" and ek.uretim == "ai" and ek.hazirlik_hatasi is None
    assert b.uretim_modu == "live" and ek.dup_uretim_modu == "live"
    # Güvenli JQL, yalnızca açık Bug'lar; TPD-5 bulunur, TPD-7 (Done) asla.
    assert ek.jql and ek.jql.startswith('project = "TPD" AND issuetype = "Bug"')
    keys = [a["key"] for a in b.mukerrer_adaylari]
    assert keys[0] == "TPD-5" and "TPD-7" not in keys and len(keys) <= service.MAX_ADAY
    tpd5 = b.mukerrer_adaylari[0]
    assert tpd5["likelihood"] == "high" and tpd5["ai"] and "AC2" in tpd5["rationale"]
    assert ek.oneri["recommendation"] == "link" and ek.oneri["link_key"] == "TPD-5"
    # Kanıt: yer tutucular koşunun (triage) bağlantılarına çevrilir; uydurma URL atılır.
    kok = f"/api/artifacts/runs/{ids['run_id']}/"
    refs = {(e["kind"], e["ref"]) for e in b.icerik["evidence"]}
    assert ("trace", kok + "results/t/trace.zip") in refs
    assert ("log", kok + "results/t/error-context.md") in refs
    assert ("allure", kok + "allure-report/index.html") in refs
    assert all("kotu.example" not in r for _, r in refs)
    alanlar = {d["alan"] for d in ek.duzeltmeler}
    assert {"story_key", "test_case_key"} <= alanlar and "actual" not in alanlar
    assert b.icerik["story_key"] == "TPD-1" and b.icerik["test_case_key"] == ids["test_key"]
    assert b.icerik["summary"].startswith("Sepet: 6 adette")
    assert b.icerik_hash == content_hash(b.icerik)
    # Model girdisi gateway.defects kanonik bloklarıyla, güvenilmeyen blokta.
    taslak_istegi, sira_istegi = (
        "\n".join(str(m.get("content")) for m in r.messages) for r in provider.requests
    )
    assert '<untrusted kind="ci_log" source="failure:TPD-1-C3"' in taslak_istegi
    assert '<untrusted kind="text" source="case:TPD-1-C3"' in taslak_istegi
    assert 'Gerçekleşen: "1"' in taslak_istegi
    assert "testdata:demo-app" in taslak_istegi
    assert 'source="jira-arama:Bug"' in sira_istegi and "Aday anahtarları: [TPD-5" in sira_istegi
    assert "results/t/trace.zip" not in taslak_istegi  # bağlantı modele gitmez, yalnızca ad
    with session_scope() as s:
        amaclar = sorted(s.scalars(select(AiCall.amac)))
    assert amaclar == ["bug_draft", "dup_rank"]


def test_uydurulan_aday_siralamayi_gecersiz_kilar(engine: Engine, bug_fake_gateway: Any) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira(ek=["TPD-99"]))])
    did, _ = _yeni_taslak()
    _hazirla(engine)
    b, ek = _draft(did)
    assert ek.oneri["recommendation"] == "new" and ek.oneri["atilan_anahtarlar"] == ["TPD-99"]
    assert all(a["ai"] is False and a["rank"] is None for a in b.mukerrer_adaylari)
    assert "TPD-99" not in [a["key"] for a in b.mukerrer_adaylari]


def test_gerceklesen_literal_degil_ise_sablon_kullanilir(
    engine: Engine, bug_fake_gateway: Any
) -> None:
    bug_fake_gateway(
        [
            text_response(_ai_taslak(actual="Bedava ürün yanlış hesaplanıyor")),
            text_response(_ai_sira(link=False)),
        ]
    )
    did, _ = _yeni_taslak()
    _hazirla(engine)
    b, ek = _draft(did)
    assert "Gerçekleşen değer: 1" in b.icerik["actual"]
    assert any(d["alan"] == "actual" for d in ek.duzeltmeler)
    assert ek.ai_icerik["actual"] == "Bedava ürün yanlış hesaplanıyor"
    assert ek.oneri["recommendation"] == "new"


def test_hazirlik_sirasinda_duzenlenen_icerik_ezilmez(
    engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, _ = _yeni_taslak()
    testci = make_user("tester")
    b, _ = _draft(did)
    yeni = {**b.icerik, "summary": "Testçinin özeti"}
    with session_scope() as s:
        service.decide(s, did, testci, "edit", b.icerik_hash, icerik=yeni)
    _hazirla(engine)
    b, ek = _draft(did)
    assert b.icerik["summary"] == "Testçinin özeti" and ek.duzenleyen == testci.kullanici_adi
    assert ek.hazirlik_durum == "hazir" and b.mukerrer_adaylari[0]["key"] == "TPD-5"


# ------------------------------------------------------------------ REPLAY golden'ları


def test_replay_c3_ana_yol(engine: Engine, bug_replay_gateway: Any) -> None:
    """f2-kod-hatasi: C3 defect adayı → golden taslak (REPLAY) + TPD-5 'bağla' önerisi."""
    did, ids = _yeni_taslak(triage_ek=True)
    _hazirla(engine)
    b, ek = _draft(did)
    assert ek.hazirlik_hatasi is None, ek.hazirlik_hatasi
    assert b.uretim_modu == "replay" and ek.dup_uretim_modu == "replay"
    assert ek.uretim == "ai"
    assert b.icerik["summary"].startswith("Sepet: 6 adet Portakal Gazozu")
    assert b.icerik["test_case_key"] == ids["test_key"]
    assert [a["key"] for a in b.mukerrer_adaylari] == ["TPD-5"]
    assert b.mukerrer_adaylari[0]["likelihood"] == "high"
    assert ek.oneri == {"recommendation": "link", "link_key": "TPD-5", "neden": None}
    assert all(e["ref"].startswith("/api/artifacts/runs/") for e in b.icerik["evidence"])
    view = _view(did)
    assert view["mode_label"].startswith("REPLAY (hazırlanmış örnek çıktı")


def _view(did: uuid.UUID) -> dict[str, Any]:
    from tp_core.features.bugs import serialize

    with session_scope() as s:
        b = s.get(BugDraft, did)
        assert b is not None
        return serialize.bug_draft_view(s, b)


def test_replay_kirma_kosusu(engine: Engine, bug_replay_gateway: Any) -> None:
    did, _ = _yeni_taslak(senaryo="c2_kirma", triage_ek=True)
    _hazirla(engine)
    b, ek = _draft(did)
    assert ek.hazirlik_hatasi is None, ek.hazirlik_hatasi
    assert b.uretim_modu == "replay" and ek.dup_uretim_modu == "replay"
    assert "BREAK_CAMPAIGN" in b.icerik["environment"]
    assert b.mukerrer_adaylari[0]["key"] == "TPD-5"
    assert b.mukerrer_adaylari[0]["likelihood"] == "medium"
    assert ek.oneri["recommendation"] == "new"
    assert ek.imza["kirma"] is True


def test_replay_golden_uymazsa_sablon_ve_siralanmamis_adaylar(
    engine: Engine, bug_replay_gateway: Any
) -> None:
    """Golden beyanına uymayan girdi (ör. bilinmeyen locator): dürüst şablon, AI yok."""
    from tp_core.models import TestResult

    did, ids = _yeni_taslak()
    with session_scope() as s:
        tr = s.scalars(select(TestResult).where(TestResult.run_id == ids["run_id"])).one()
        tr.hata_mesaji = (tr.hata_mesaji or "").replace("cart-line-free", "cart-line-other")
    _hazirla(engine)
    b, ek = _draft(did)
    assert ek.hazirlik_durum == "hazir"
    assert ek.uretim == "sablon" and b.uretim_modu is None
    assert ek.hazirlik_hatasi and "REPLAY-MISS" in ek.hazirlik_hatasi
    assert b.mukerrer_adaylari[0]["key"] == "TPD-5" and b.mukerrer_adaylari[0]["ai"] is False
    assert ek.oneri["recommendation"] == "new"
    assert ek.oneri["neden"] == "REPLAY kaydı yok: adaylar sıralanmadı; karar testçinin"
    assert _view(did)["mode_label"].startswith("şablon")


def test_replay_f2_tutarlilik_taslagi(engine: Engine, bug_replay_gateway: Any) -> None:
    ids = seed_finding_draft("F2")
    assert service.adopt_pending() == [str(ids["draft_id"])]
    _hazirla(engine)
    b, ek = _draft(ids["draft_id"])
    assert ek.hazirlik_hatasi is None, ek.hazirlik_hatasi
    assert b.finding_id == ids["finding_id"] and ek.kaynak == "finding"
    assert b.uretim_modu == "replay" and ek.dup_uretim_modu == "replay"
    assert b.icerik["evidence"] == [{"kind": "code", "ref": "api/src/demoapp_api/campaign.py:23"}]
    assert b.icerik["test_case_key"] is None
    assert ek.oneri["link_key"] == "TPD-5"


# --------------------------------------------------------------- karar ve yayın


def _api_taslak(
    api: TestClient, engine: Engine, bug_fake_gateway: Any, make_user: Any, link: bool = True
) -> tuple[uuid.UUID, dict[str, Any], dict[str, Any]]:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira(link=link))])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    login(api, make_user("tester"))
    r = api.get(f"/bug-drafts/{did}/detail")
    assert r.status_code == 200, r.text
    return did, ids, r.json()


def test_mevcut_kayda_bagla(
    api: TestClient,
    engine: Engine,
    bug_fake_gateway: Any,
    make_user: Any,
    request: pytest.FixtureRequest,
) -> None:
    did, ids, gorunum = _api_taslak(api, engine, bug_fake_gateway, make_user)
    jira = services.jira()
    assert gorunum["oneri"]["link_key"] == "TPD-5" and gorunum["mukerrer_aramasi_yapildi"]
    assert gorunum["mukerrer_adaylari"][0]["url"].endswith("/browse/TPD-5")
    once = _bugs(jira)
    request.getfixturevalue("worker")
    r = api.post(
        f"/bug-drafts/{did}/decision",
        json={"karar": "link", "link_key": "TPD-5", "icerik_hash": gorunum["icerik_hash"]},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["yayin_sonucu"]["is_durumu"] == "done", out["yayin_sonucu"]
    assert out["durum"] == "published" and out["jira_key"] == "TPD-5" and out["karar"] == "link"
    assert _bugs(jira) == once  # yeni Bug açılmadı
    yorumlar = jira.get_comments("TPD-5")
    assert len(yorumlar) == 1 and f"tp-{did}" in yorumlar[0].body
    assert "Gerçekleşen: Bedava adet 1" in yorumlar[0].body
    assert "denetim zinciri son hash" in yorumlar[0].body
    baglar = {(b["rol"], b["hedef"], b["tur"]) for b in out["yayin"]["baglantilar"]}
    assert baglar == {("story", "TPD-1", "Relates"), ("test", ids["test_key"], "Test")}
    # Tekrar yayın: yorum ikinci kez yazılmaz.
    assert service.publish_bug(did)["durum"] == "exists"
    assert len(jira.get_comments("TPD-5")) == 1
    with session_scope() as s:
        rev = s.scalars(select(Review).where(Review.nesne_id == did)).all()
        assert [r.karar for r in rev] == ["link"]
        assert rev[0].onaylanan_hash == gorunum["icerik_hash"]
        eylemler = set(s.scalars(select(AuditEvent.eylem)))
    assert {"review.link", "bug.publish_requested", "bug.linked"} <= eylemler


def test_yeni_kayit_duzenlemeyle(
    api: TestClient,
    engine: Engine,
    bug_fake_gateway: Any,
    make_user: Any,
    request: pytest.FixtureRequest,
) -> None:
    did, ids, gorunum = _api_taslak(api, engine, bug_fake_gateway, make_user)
    jira = services.jira()
    duzenli = {**gorunum["icerik"], "summary": "Sepet: 6 adette bedava ürün veriliyor (AC2)"}
    request.getfixturevalue("worker")
    r = api.post(
        f"/bug-drafts/{did}/decision",
        json={"karar": "new", "icerik": duzenli, "icerik_hash": gorunum["icerik_hash"]},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["yayin_sonucu"]["is_durumu"] == "done", out["yayin_sonucu"]
    key = out["jira_key"]
    assert out["durum"] == "published" and key not in ("TPD-5", None)
    issue = jira.get_issue(key)
    assert issue.issue_type == "Bug" and issue.summary == duzenli["summary"]
    assert {"AI-generated", f"tp-{did}", "tp-mod-live"} <= set(issue.labels)
    assert f"onaylanan içerik hash: {content_hash(duzenli)}" in issue.description
    assert out["icerik_hash"] == content_hash(duzenli) == out["onaylanan_hash"]
    raw = jira.raw_fields(key, ["issuelinks"])["issuelinks"]
    hedefler = {
        (lk["type"]["name"], (lk.get("inwardIssue") or lk.get("outwardIssue"))["key"]) for lk in raw
    }
    assert hedefler == {("Relates", "TPD-1"), ("Test", ids["test_key"])}
    with session_scope() as s:
        ref = s.scalars(select(ExternalRef).where(ExternalRef.entity_id == did)).one()
        assert ref.durum == "created" and ref.external_key == key


def test_yeniden_denemede_ikinci_bug_acilmaz(
    engine: Engine, bug_fake_gateway: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira(link=False))])
    did, _ = _yeni_taslak()
    _hazirla(engine)
    jira = services.jira()
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    gercek = service._links
    cagri = {"n": 0}

    def bozuk(*a: Any, **k: Any) -> Any:
        cagri["n"] += 1
        if cagri["n"] == 1:
            raise RuntimeError("bağlantı sırasında ağ hatası")
        return gercek(*a, **k)

    monkeypatch.setattr(service, "_links", bozuk)
    assert [r.durum for r in run_jobs(engine)] == ["retry"]
    b, ek = _draft(did)
    assert b.durum == "approved" and ek.yayin["durum"] == "basarisiz"
    with engine.begin() as c:  # yeniden deneme beklemesini atla
        c.exec_driver_sql("UPDATE job SET run_after = now() WHERE durum = 'retry'")
    assert [r.durum for r in run_jobs(engine)] == ["done"]
    etiketli = jira.search(f'project = "TPD" AND labels = "tp-{did}"', max_results=10)
    assert len(etiketli) == 1
    b, ek = _draft(did)
    assert b.durum == "published" and b.jira_key == etiketli[0].key
    assert ek.yayin["durum"] == "tamam"


def test_onaydan_sonra_degisen_icerik_yayinlanmaz(
    engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, _ = _yeni_taslak()
    _hazirla(engine)
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    with session_scope() as s:
        taslak = s.get(BugDraft, did)
        assert taslak is not None
        yeni = {**taslak.icerik, "summary": "onaydan sonra değişti"}
        taslak.icerik = yeni
        taslak.icerik_hash = content_hash(yeni)
    assert [r.durum for r in run_jobs(engine)] == ["failed"]
    b, _ = _draft(did)
    assert b.durum == "approved" and b.jira_key is None
    assert len(_bugs(services.jira())) == 3  # yalnızca seed (TPD-5/6/7)


def test_karar_kurallari(
    api: TestClient, engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    did, _, gorunum = _api_taslak(api, engine, bug_fake_gateway, make_user)
    yol = f"/bug-drafts/{did}/decision"
    assert api.post(yol, json={"karar": "new"}).status_code == 422  # hash yok
    assert api.post(yol, json={"karar": "new", "icerik_hash": "eski"}).status_code == 409
    h = gorunum["icerik_hash"]
    r = api.post(yol, json={"karar": "link", "icerik_hash": h, "link_key": 'TPD-5" OR x'})
    assert r.status_code == 422
    kotu = {**gorunum["icerik"], "labels": []}
    r = api.post(yol, json={"karar": "edit", "icerik_hash": h, "icerik": kotu})
    assert r.status_code == 422 and "şemaya uymuyor" in r.json()["detail"]
    assert api.post(yol, json={"karar": "dismiss", "icerik_hash": h}).status_code == 422
    # Testçi olmayan karar veremez.
    api.post("/auth/logout")
    login(api, make_user("analyst"))
    assert api.post(yol, json={"karar": "new", "icerik_hash": h}).status_code == 403
    api.post("/auth/logout")
    login(api, make_user("tester"))
    r = api.post(yol, json={"karar": "dismiss", "icerik_hash": h, "gerekce": "mükerrer"})
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "dismissed" and r.json()["ret_gerekcesi"] == "mükerrer"
    r = api.post(yol, json={"karar": "reopen", "icerik_hash": h})
    assert r.status_code == 200 and r.json()["durum"] == "draft"
    # Taslakta onaylı değil: yayın yeniden denemesi reddedilir.
    assert api.post(f"/bug-drafts/{did}/publish").status_code == 409
    assert api.post(f"/bug-drafts/{did}/prepare").status_code == 202


# -------------------------------------------------------- tutarlılık taslağı (Faz 2)


def test_tutarlilik_taslagi_hatta_alinir_ve_yayinlanir(
    engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    jira = services.jira()
    ids = seed_finding_draft("F4")
    did = ids["draft_id"]
    taslak = {
        "summary": "Sepet: Kredi limiti aşımında uyarı gösterilmiyor",
        "steps": ["1. bayi2 ile giriş yap", "2. 750,00 TL sepet oluştur", "3. Sepete git"],
        "expected": '"Kredi limiti aşıldı" uyarısı gösterilir',
        "actual": "Uyarı gösterilmiyor",
        "environment": "Yerel demo ortamı",
        "evidence": [
            {"kind": "code", "ref": "api/src/demoapp_api/pricing.py:97"},
            {"kind": "code", "ref": "api/src/demoapp_api/uydurma.py:1"},
        ],
        "story_key": "TPD-1",
        "test_case_key": "TPD-77",
        "severity_suggestion": "critical",
        "labels": ["AI-generated"],
    }
    bug_fake_gateway(
        [
            text_response(taslak),
            text_response(
                {
                    "candidates": [
                        {"key": "TPD-5", "rank": 1, "likelihood": "low", "rationale": "Farklı AC"}
                    ],
                    "recommendation": "new",
                    "link_key": None,
                }
            ),
        ]
    )
    assert service.adopt_pending() == [str(did)]
    assert service.adopt_pending() == []
    _hazirla(engine)
    b, ek = _draft(did)
    assert b.finding_id == ids["finding_id"] and ek.kaynak == "finding"
    assert content.validation_errors(b.icerik) == []
    assert b.icerik["test_case_key"] is None  # bulguda Test issue yok
    assert b.icerik["evidence"] == [{"kind": "code", "ref": "api/src/demoapp_api/pricing.py:97"}]
    assert ek.imza["ac"] == "AC4" and ek.uretim == "ai"
    testci = make_user("tester")
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    assert [r.durum for r in run_jobs(engine)] == ["done"]
    b, ek = _draft(did)
    assert b.durum == "published" and b.jira_key
    assert [x["rol"] for x in ek.yayin["baglantilar"]] == ["story"]
    assert "Kredi limiti" in jira.get_issue(b.jira_key).summary


def test_on_worker_start_supurme_isi(engine: Engine, bug_services: RestJira) -> None:
    from tp_core.features.bugs import jobs

    seed_finding_draft()
    with engine.begin() as c:
        jobs.on_worker_start(c)
        jobs.on_worker_start(c)
    with engine.connect() as c:
        n = c.exec_driver_sql(
            "SELECT count(*) FROM job WHERE tur = 'bugs.adopt_sweep'"
        ).scalar_one()
    assert n == 1


def test_api_bekleme_suresi_sabit() -> None:
    assert 0 < bugs_api.BEKLEME_S <= 25

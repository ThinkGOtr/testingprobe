"""Karar korumaları: bağlantı hedefi doğrulaması, takılan yayından kurtulma, insan düzenlemesinin
bağlam korumaları, Jira'daki mutlak kanıt bağlantıları ve sıralanmamış aday listesinin dürüstlüğü.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.bugs.helpers import seed_finding_draft
from tests.unit.features.bugs.test_flow import (
    _ai_sira,
    _ai_taslak,
    _api_taslak,
    _draft,
    _hazirla,
    _yeni_taslak,
)
from tests.unit.features.cases.helpers import run_jobs
from tp_core.features.bugs import service, services
from tp_core.features.bugs.context import finding_context
from tp_core.gateway.errors import ReplayNoOutput
from tp_core.gateway.testing import text_response
from tp_core.integrations.jira import RestJira
from tp_core.models import AuditEvent, Review, session_scope

pytestmark = pytest.mark.usefixtures("db")


def _reviewler(did: uuid.UUID) -> list[str]:
    with session_scope() as s:
        return [r.karar for r in s.scalars(select(Review).where(Review.nesne_id == did))]


# ------------------------------------------------------------ bağlantı hedefi (karar anı)


def test_bag_hedefi_karar_aninda_dogrulanir(
    api: TestClient,
    engine: Engine,
    bug_fake_gateway: Any,
    make_user: Any,
    request: pytest.FixtureRequest,
) -> None:
    did, _, gorunum = _api_taslak(api, engine, bug_fake_gateway, make_user)
    yol = f"/bug-drafts/{did}/decision"
    h = gorunum["icerik_hash"]
    beklenen = {
        "TPD-1": "TPD-1 bir Bug değil (Story)",  # story: Bug'a bağlanır
        "TPD-999": "TPD-999 Jira'da bulunamadı",  # yazım hatası
        "TPD-7": "TPD-7 kapalı (Done)",  # kapanmış Bug
        "ABC-5": "ABC-5 TPD projesinde değil",  # başka proje
    }
    for key, mesaj in beklenen.items():
        r = api.post(yol, json={"karar": "link", "link_key": key, "icerik_hash": h})
        assert r.status_code == 422, (key, r.text)
        assert mesaj in r.json()["detail"], r.json()
    b, _ = _draft(did)
    assert b.durum == "draft" and b.karar is None and b.link_key is None
    assert _reviewler(did) == []  # reddedilen karar onay kaydı bırakmaz
    # Doğru hedef hâlâ seçilebilir.
    request.getfixturevalue("worker")
    r = api.post(yol, json={"karar": "link", "link_key": "TPD-5", "icerik_hash": h})
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "published" and r.json()["jira_key"] == "TPD-5"
    assert _reviewler(did) == ["link"]


def test_gecersiz_hedefle_takilan_yayin_taslaga_doner(
    engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    """Onaydan sonra hedef kapanırsa yayın kalıcı hata verir; taslak takılmaz, yeniden karar."""
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, _ = _yeni_taslak()
    _hazirla(engine)
    jira: RestJira = services.jira()
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "link", b.icerik_hash, link_key="TPD-5")
    done = next(t for t in jira.transitions("TPD-5") if t["name"] == "Done")
    jira.transition("TPD-5", done["id"])
    assert [r.durum for r in run_jobs(engine)] == ["failed"]
    b, ek = _draft(did)
    assert b.durum == "draft" and b.karar is None and b.link_key is None
    assert b.onaylanan_hash is None and b.jira_key is None
    assert "TPD-5 kapalı" in ek.yayin["hata"] and "taslağa alındı" in ek.yayin["hata"]
    assert jira.get_comments("TPD-5") == []
    with session_scope() as s:
        olay = s.scalars(
            select(AuditEvent)
            .where(AuditEvent.eylem == "bug.publish_failed")
            .order_by(AuditEvent.id.desc())
        ).first()
        assert olay is not None and olay.ozet["taslaga_dondu"] is True
    # Testçi yeniden karar verir: önceki kapılar 409 vermez, yeni kayıt açılır.
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    assert [r.durum for r in run_jobs(engine)] == ["done"]
    b, ek = _draft(did)
    assert b.durum == "published" and b.karar == "new" and b.jira_key not in (None, "TPD-5")
    assert _reviewler(did) == ["link", "new"]


# ------------------------------------------------- insan düzenlemesinin bağlam korumaları


def test_duzenleme_baglam_alanlarini_degistiremez(
    api: TestClient, engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    did, ids, gorunum = _api_taslak(api, engine, bug_fake_gateway, make_user)
    yol = f"/bug-drafts/{did}/decision"
    h, icerik = gorunum["icerik_hash"], gorunum["icerik"]
    kotu = [
        ("edit", {"story_key": "OTHER-9"}, "story_key düzenlenemez"),
        ("new", {"test_case_key": "not a key; anything"}, "test_case_key"),
        ("new", {"test_case_key": "TPD-6"}, "test_case_key düzenlenemez"),
        (
            "link",
            {"evidence": [{"kind": "log", "ref": "https://evil.example/x"}]},
            "evil.example",
        ),
    ]
    for karar, degisiklik, mesaj in kotu:
        govde: dict[str, Any] = {"karar": karar, "icerik_hash": h, "icerik": icerik | degisiklik}
        if karar == "link":
            govde["link_key"] = "TPD-5"
        r = api.post(yol, json=govde)
        assert r.status_code == 422, (degisiklik, r.text)
        assert mesaj in r.json()["detail"], r.json()
    b, _ = _draft(did)
    assert b.durum == "draft" and b.icerik_hash == h and _reviewler(did) == []
    # Kanıt çıkarmak ve metin düzeltmek serbest; bağlam alanları korunur.
    duzenli = icerik | {
        "summary": "Sepet: 6 adette bedava (AC2)",
        "evidence": icerik["evidence"][:1],
    }
    r = api.post(yol, json={"karar": "edit", "icerik_hash": h, "icerik": duzenli})
    assert r.status_code == 200, r.text
    assert r.json()["icerik"]["test_case_key"] == ids["test_key"]
    assert r.json()["icerik"]["story_key"] == "TPD-1"


# ------------------------------------------------------- Jira'da mutlak kanıt bağlantısı


def _hrefler(n: Any) -> list[str]:
    if isinstance(n, list):
        return [h for c in n for h in _hrefler(c)]
    if not isinstance(n, dict):
        return []
    out = [m["attrs"]["href"] for m in n.get("marks") or [] if m.get("type") == "link"]
    return out + _hrefler(n.get("content") or [])


def test_jira_kanit_baglantilari_portal_kokuyle_mutlak(
    engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    b, _ = _draft(did)
    # Portal görünümü göreli yolu korur (onaylanan içerik hash'i değişmez).
    assert all(e["ref"].startswith("/api/artifacts/runs/") for e in b.icerik["evidence"])
    testci = make_user("tester")
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    with services.override(public_base_url=lambda: "https://probe.example"):
        assert [r.durum for r in run_jobs(engine)] == ["done"]
    b, _ = _draft(did)
    jira: RestJira = services.jira()
    hrefler = _hrefler(jira.raw_fields(b.jira_key, ["description"])["description"])
    kok = f"https://probe.example/api/artifacts/runs/{ids['run_id']}/"
    assert hrefler and all(h.startswith(kok) for h in hrefler), hrefler
    assert f"trace: {kok}" in jira.get_issue(b.jira_key).description


def test_varsayilan_kok_yerel_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("TP_PORTAL_PORT", "8181")
    assert services.public_base_url() == "http://127.0.0.1:8181"
    monkeypatch.setenv("TP_PUBLIC_BASE_URL", "https://probe.example/")
    assert services.public_base_url() == "https://probe.example"
    monkeypatch.setenv("TP_FORGE", "github")
    monkeypatch.setenv("GITHUB_REPO", "acme/demo-app")
    assert services.code_url("api/x.py", "23", "abc") == (
        "https://github.com/acme/demo-app/blob/abc/api/x.py#L23"
    )
    monkeypatch.setenv("TP_FORGE", "local")
    assert services.code_url("api/x.py", "23", "abc") is None


# --------------------------------------------------- sıralanmamış adaylar (sahne dürüstlüğü)


def test_siralama_hatasi_turkce() -> None:
    metin = service.siralama_hatasi_metni(ReplayNoOutput("dup_rank", "k" * 40, None))
    assert metin == "REPLAY kaydı yok: adaylar sıralanmadı; karar testçinin"
    assert "Replay" not in metin and "Error" not in metin


def test_kredi_limiti_bulgusunda_alakasiz_aday_yok(engine: Engine, bug_services: RestJira) -> None:
    """F4 (kredi limiti): kampanya (TPD-5) ve sipariş geçmişi (TPD-6) aday gösterilmez."""
    ids = seed_finding_draft("F4")
    with session_scope() as s:
        ctx = finding_context(s, ids["finding_id"])
    terimler = ctx.terms()
    assert "ac4" not in terimler and not any(t.startswith(("bayi", "sipariş")) for t in terimler)
    _, arama, adaylar = service.search_candidates(bug_services, "TPD", ctx, set())
    assert [a["key"] for a in adaylar] == []
    assert arama["durum"] == "yapildi"

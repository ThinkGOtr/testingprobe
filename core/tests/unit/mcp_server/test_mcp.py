"""MCP (IDE kanalı): SDK istemcisi ASGI uygulamasına karşı; bearer, kapsam, localhost, kayıt."""

from __future__ import annotations

import uuid
from typing import Any

import anyio
import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import case_icerik, latest_cases, login
from tp_core.auth.tokens import issue_token, revoke_token
from tp_core.models import Requirement, TestCase, ToolCall, session_scope
from tp_core.workflow.service import Principal

URL = "http://127.0.0.1:8000/mcp"
MCP_H = {"Accept": "application/json, text/event-stream"}


def _token(user: Principal, kapsam: str) -> str:
    with session_scope() as s:
        _, raw = issue_token(s, user, kapsam, 3600)
    return raw


def _mcp(app: Any, token: str | None, **ek: Any):
    async def calistir(fn):
        basliklar = {"Authorization": f"Bearer {token}"} if token else {}
        async with (
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), headers=basliklar, timeout=60
            ) as http,
            Client(streamable_http_client(URL, http_client=http), **ek) as client,
        ):
            return await fn(client)

    return calistir


def _cagir(api: TestClient, token: str, arac: str, args: dict[str, Any]):
    async def fn(client: Client):
        return await client.call_tool(arac, args)

    return anyio.run(_mcp(api.app, token), fn)


def _tool_calls() -> list[ToolCall]:
    with session_scope() as s:
        return list(s.scalars(select(ToolCall).order_by(ToolCall.zaman)))


def _hash(anahtar: str = "TPD-4") -> str:
    """Gereksinimin PO onaylı hash'i (IDE bunu get_requirement ile okur)."""
    with session_scope() as s:
        req = s.scalars(select(Requirement).where(Requirement.jira_key == anahtar)).one()
        return req.onaylanan_hash or "onaysiz"


def _jira_issue_count(jira) -> int:
    return len(jira.search('project = "TPD" AND labels = "AI-generated"', max_results=100))


def test_arac_listesi_sdk_istemcisiyle(api: TestClient, make_user) -> None:
    token = _token(make_user("analyst"), "submit")

    async def fn(client: Client):
        return await client.list_tools()

    sonuc = anyio.run(_mcp(api.app, token), fn)
    adlar = {t.name: t for t in sonuc.tools}
    assert set(adlar) == {"get_requirement", "submit_draft_cases", "publish_test_cases"}
    sema = adlar["submit_draft_cases"].input_schema
    assert sema["required"] == ["requirement_key", "onaylanan_hash", "cases"]
    assert adlar["get_requirement"].input_schema["required"] == ["requirement_key"]
    assert "steps" in sema["properties"]["cases"]["items"]["properties"]


def test_submit_draft_cases_taslak_dusurur_jiraya_yazmaz(
    api: TestClient, make_user, make_requirement, jira
) -> None:
    rid = make_requirement()
    gelistirici = make_user("analyst")
    token = _token(gelistirici, "submit")
    once = _jira_issue_count(jira)
    cases = [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2")]
    sonuc = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": cases},
    )
    assert sonuc.is_error is False, sonuc
    govde = sonuc.structured_content
    assert len(govde["eklenen"]) == 2 and govde["durum"] == "draft"
    assert _jira_issue_count(jira) == once

    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "cases_ready"
        tcs = s.scalars(select(TestCase).order_by(TestCase.sira_no)).all()
        assert [t.kanal for t in tcs] == ["ide", "ide"] and {t.durum for t in tcs} == {"draft"}
        assert [t.icerik for t in tcs] == cases and all(t.uretim_modu is None for t in tcs)
    (tc,) = _tool_calls()
    assert tc.kanal == "ide" and tc.cagiran_user_id == gelistirici.id
    assert tc.arac == "submit_draft_cases" and tc.izin_verildi is True
    assert tc.arguman_ozeti["case_sayisi"] == 2 and tc.arguman_ozeti["requirement_key"] == "TPD-4"
    assert str(govde["tool_call_id"]) == str(tc.id)

    # Aynı taslakların tekrar gönderimi yeni satır açmaz.
    tekrar = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": cases},
    )
    assert tekrar.structured_content["eklenen"] == []
    assert tekrar.structured_content["tekrar_sira"] == [1, 2]

    # Portalda görünür; mod yok (IDE çıktısı asla "live" etiketlenmez).
    login(api, make_user("analyst"))
    gorunen = latest_cases(api, rid)
    assert {c["kanal"] for c in gorunen} == {"ide"} and {c["mode"] for c in gorunen} == {None}


def test_semaya_uymayan_taslak_hicbirini_yazmaz(
    api: TestClient, make_user, make_requirement
) -> None:
    make_requirement()
    token = _token(make_user("analyst"), "submit")
    cases = [case_icerik(), case_icerik(tags=["manual"]), case_icerik(ref="AC9")]
    sonuc = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": cases},
    )
    assert sonuc.is_error is True
    hata = sonuc.structured_content["hata"]
    assert '"2"' in hata and '"3"' in hata and "AC9" in hata
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None
    (tc,) = _tool_calls()
    assert tc.izin_verildi is True and "şemaya uymuyor" in tc.sonuc_ozeti


def test_po_onaysiz_gereksinime_taslak_gonderilemez(
    api: TestClient, make_user, make_requirement
) -> None:
    make_requirement(po_onayli=False)
    token = _token(make_user("analyst"), "submit")
    sonuc = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": [case_icerik()]},
    )
    assert sonuc.is_error is True and "PO onaylı" in sonuc.structured_content["hata"]


def test_yanlis_kapsam_reddedilir_ve_kaydedilir(
    api: TestClient, make_user, make_requirement
) -> None:
    make_requirement()
    u = make_user("analyst")
    token = _token(u, "publish")
    sonuc = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": [case_icerik()]},
    )
    assert sonuc.is_error is True and "kapsam" in sonuc.structured_content["hata"]
    (tc,) = _tool_calls()
    assert tc.izin_verildi is False and tc.cagiran_user_id == u.id
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None


def test_publish_test_cases_portal_onayi_ve_hash_kapisi(
    api: TestClient, engine: Engine, make_user, make_requirement, jira, targets, worker
) -> None:
    make_requirement()
    gelistirici = make_user("analyst", ad="gelistirici")
    submit = _token(gelistirici, "submit")
    yayin = _token(gelistirici, "publish")
    cases = [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2")]
    eklenen = _cagir(
        api,
        submit,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": cases},
    )
    a_id, b_id = (e["case_id"] for e in eklenen.structured_content["eklenen"])

    # Onaysız: yayınlanmaz (aynı sunucu yolu, worker'daki kontrol).
    sonuc = _cagir(api, yayin, "publish_test_cases", {"case_ids": [a_id]})
    assert sonuc.is_error is False
    assert sonuc.structured_content["sonuclar"][0]["durum"] == "failed"
    assert "Onaylı değil" in sonuc.structured_content["sonuclar"][0]["hata"]

    # Portalda başka bir analist onaylar; IDE yalnızca kimlikle yayınlar.
    onaylayan = make_user("analyst", ad="qa_onaylayan")
    login(api, onaylayan)
    a = next(
        c
        for c in latest_cases(api, eklenen.structured_content["requirement_id"])
        if c["id"] == a_id
    )
    r = api.post(
        f"/cases/{a_id}/decision", json={"karar": "approve", "icerik_hash": a["icerik_hash"]}
    )
    assert r.status_code == 200, r.text

    sonuc = _cagir(api, yayin, "publish_test_cases", {"case_ids": [a_id, b_id]})
    durum = {s["case_id"]: s for s in sonuc.structured_content["sonuclar"]}
    assert durum[a_id]["durum"] == "created" and durum[a_id]["onaylayan"] == "qa_onaylayan"
    assert durum[b_id]["durum"] == "failed"
    key = durum[a_id]["external_key"]
    # IDE taslağı: üretim modu etiketi "ide" (REPLAY/canlı model değil).
    assert jira.get_issue(key).labels == ["AI-generated", f"tp-{a_id}", "tp-mod-ide"]

    kayit = [t for t in _tool_calls() if t.arac == "publish_test_cases"][-1]
    assert kayit.kanal == "ide" and kayit.cagiran_user_id == gelistirici.id
    assert kayit.arguman_ozeti["onaylayanlar"] == {a_id: "qa_onaylayan", b_id: None}
    assert kayit.arguman_ozeti["case_ids"] == [a_id, b_id]
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(a_id)).durum == "published"


# ------------------------------------------------------------------ HTTP sınırı


def _raw(api: TestClient, token: str | None, govde: dict, **basliklar: str):
    h = dict(MCP_H)
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(basliklar)
    return api.post("/mcp", json=govde, headers=h)


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "claude-code", "version": "2.0"},
    },
}


def test_claude_code_el_sikismasi_ve_arac_cagrisi(
    api: TestClient, make_user, make_requirement
) -> None:
    make_requirement()
    token = _token(make_user("analyst"), "submit")
    r = _raw(api, token, INIT)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "testing-probe"
    r = _raw(
        api,
        token,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "submit_draft_cases",
                "arguments": {
                    "requirement_key": "TPD-4",
                    "onaylanan_hash": _hash(),
                    "cases": [case_icerik()],
                },
            },
        },
        **{"mcp-protocol-version": "2025-06-18"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"]["isError"] is False


def test_tokensiz_gecersiz_iptal_ve_cerezle_401(api: TestClient, make_user) -> None:
    u = make_user("analyst")
    assert _raw(api, None, INIT).status_code == 401
    assert _raw(api, "tpt_uydurma", INIT).status_code == 401
    r = _raw(api, None, INIT, Authorization="Basic eHg6eXk=")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    login(api, u)  # oturum çerezi MCP'de kimlik sayılmaz
    assert _raw(api, None, INIT).status_code == 401
    token = _token(u, "submit")
    assert _raw(api, token, INIT).status_code == 200
    with session_scope() as s:
        from tp_core.models import ApiToken

        tok = s.scalars(select(ApiToken).where(ApiToken.user_id == u.id)).one()
        assert revoke_token(s, u, tok.id)
    assert _raw(api, token, INIT).status_code == 401


def test_yalnizca_localhost_ve_vekilsiz(api: TestClient, make_user) -> None:
    token = _token(make_user("analyst"), "submit")
    assert _raw(api, token, INIT, Host="core-api:8000").status_code == 421
    assert _raw(api, token, INIT, Host="evil.example").status_code == 421
    assert _raw(api, token, INIT, Host="localhost:8000").status_code == 200
    assert _raw(api, token, INIT, **{"X-Forwarded-For": "172.18.0.5"}).status_code == 403


def test_tarayici_kaynakli_istek_reddedilir(api: TestClient, make_user) -> None:
    token = _token(make_user("analyst"), "submit")
    # Başka siteden gelen tarayıcı isteği OriginGuard'da durur (bearer olsa bile).
    r = _raw(api, token, INIT, Origin="http://evil.example")
    assert r.status_code == 403
    r = _raw(api, token, INIT, **{"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_ide_tokeni_portal_kararinda_gecmez(api: TestClient, make_user, make_requirement) -> None:
    rid = make_requirement()
    u = make_user("analyst")
    token = _token(u, "submit")
    sonuc = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": _hash(), "cases": [case_icerik()]},
    )
    cid = sonuc.structured_content["eklenen"][0]["case_id"]
    with session_scope() as s:
        h = s.get(TestCase, uuid.UUID(cid)).icerik_hash
    r = api.post(
        f"/cases/{cid}/decision",
        json={"karar": "approve", "icerik_hash": h},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401  # onay yalnızca portal oturumuyla
    assert rid


@pytest.mark.parametrize("kapsam", ["submit", "publish"])
def test_bilinmeyen_arac_kaydedilir(api: TestClient, make_user, kapsam: str) -> None:
    token = _token(make_user("analyst"), kapsam)
    sonuc = _cagir(api, token, "delete_everything", {})
    assert sonuc.is_error is True
    (tc,) = _tool_calls()
    assert tc.arac == "delete_everything" and tc.izin_verildi is False


# ------------------------------------------------------------- get_requirement


def test_get_requirement_po_onayli_metni_guvenilmeyen_blokta_doner(
    api: TestClient, make_user, make_requirement
) -> None:
    rid = make_requirement(po_cevaplari=[{"id": "1", "metin": "Kilit yok", "yazar": "po@x"}])
    u = make_user("analyst")
    token = _token(u, "submit")
    sonuc = _cagir(api, token, "get_requirement", {"requirement_key": "TPD-4"})
    assert sonuc.is_error is False, sonuc
    govde = sonuc.structured_content
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert govde["onaylanan_hash"] == req.onaylanan_hash
    assert govde["kabul_kriterleri"] == ["AC1", "AC2"]
    girdi = govde["girdi"]
    assert 'source="jira:TPD-4"' in girdi and "Hatalı parola girildiğinde" in girdi
    assert 'source="jira:TPD-4:po"' in girdi and "Kilit yok" in girdi
    assert 'source="testdata:demo-app"' in girdi and "Demo123!" in girdi
    (tc,) = _tool_calls()
    assert tc.arac == "get_requirement" and tc.izin_verildi is True and tc.kanal == "ide"
    assert tc.arguman_ozeti == {"requirement_key": "TPD-4"}

    # Okunan hash'le gönderim kabul edilir.
    ok = _cagir(
        api,
        token,
        "submit_draft_cases",
        {
            "requirement_key": "TPD-4",
            "onaylanan_hash": govde["onaylanan_hash"],
            "cases": [case_icerik()],
        },
    )
    assert ok.is_error is False, ok


def test_get_requirement_po_onaysiz_ve_publish_kapsami_reddedilir(
    api: TestClient, make_user, make_requirement
) -> None:
    make_requirement(po_onayli=False)
    u = make_user("analyst")
    sonuc = _cagir(api, _token(u, "submit"), "get_requirement", {"requirement_key": "TPD-4"})
    assert sonuc.is_error is True and "PO onaylı değil" in sonuc.structured_content["hata"]
    sonuc = _cagir(api, _token(u, "publish"), "get_requirement", {"requirement_key": "TPD-4"})
    assert sonuc.is_error is True and "kapsam" in sonuc.structured_content["hata"]


def test_submit_hashsiz_ya_da_bayat_hashle_reddedilir(
    api: TestClient, make_user, make_requirement
) -> None:
    make_requirement()
    token = _token(make_user("analyst"), "submit")
    hashsiz = _cagir(
        api, token, "submit_draft_cases", {"requirement_key": "TPD-4", "cases": [case_icerik()]}
    )
    assert hashsiz.is_error is True
    assert "onaylanan_hash" in hashsiz.structured_content["hata"]
    bayat = _cagir(
        api,
        token,
        "submit_draft_cases",
        {"requirement_key": "TPD-4", "onaylanan_hash": "eski-hash", "cases": [case_icerik()]},
    )
    assert bayat.is_error is True
    assert "onaylanan_hash farklı" in bayat.structured_content["hata"]
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None

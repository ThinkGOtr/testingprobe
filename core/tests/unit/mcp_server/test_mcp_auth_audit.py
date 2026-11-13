"""MCP kimlik reddi denetim kaydı (Anayasa VIII): 401/403/421 iz bırakır, ham token yazılmaz."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.unit.mcp_server.test_mcp import INIT, _raw, _token
from tp_core.auth.tokens import revoke_token, token_hash
from tp_core.models import ApiToken, AuditEvent, ToolCall, session_scope


def _redler() -> list[AuditEvent]:
    with session_scope() as s:
        return list(
            s.scalars(
                select(AuditEvent)
                .where(AuditEvent.eylem == "mcp.auth_failed")
                .order_by(AuditEvent.id)
            )
        )


def test_iptal_edilmis_token_kullanimi_denetime_yazilir(api: TestClient, make_user) -> None:
    u = make_user("tester")
    token = _token(u, "publish")
    with session_scope() as s:
        tok = s.scalars(select(ApiToken).where(ApiToken.user_id == u.id)).one()
        assert revoke_token(s, u, tok.id)
        tok_id = str(tok.id)

    r = _raw(api, token, INIT)
    assert r.status_code == 401
    (ev,) = _redler()
    assert ev.aktor == "anonim" and ev.nesne == "mcp"
    o = ev.ozet
    assert o["http_durum"] == 401 and o["token_bilinen"] is True
    assert o["token_durumu"] == "iptal" and o["token_id"] == tok_id
    assert o["token_sahibi"] == u.kullanici_adi and o["token_kapsam"] == "publish"
    assert o["token_izi"] == token_hash(token)[:12]
    assert token not in json.dumps(o, ensure_ascii=False)  # ham token asla yazılmaz
    with session_scope() as s:  # reddedilen istek araç çağrısı değildir
        assert s.scalar(select(ToolCall.id)) is None

    # Hız sınırı: aynı token + istemci için pencere içinde yeni satır yok, bastırılan sayılır.
    assert _raw(api, token, INIT).status_code == 401
    assert _raw(api, token, INIT).status_code == 401
    assert len(_redler()) == 1
    from tp_core.mcp_server import server

    server._son_red.update({k: (v[0] - 60, v[1]) for k, v in server._son_red.items()})
    assert _raw(api, token, INIT).status_code == 401
    son = _redler()[-1]
    assert len(_redler()) == 2 and son.ozet["bastirilan_onceki"] == 2


def test_bilinmeyen_token_ve_tokensiz_istek(api: TestClient) -> None:
    assert _raw(api, "tpt_uydurma", INIT).status_code == 401
    assert _raw(api, None, INIT).status_code == 401
    uydurma, tokensiz = _redler()
    assert uydurma.ozet["token_bilinen"] is False and uydurma.ozet["token_izi"]
    assert tokensiz.ozet["neden"] == "token yok" and tokensiz.ozet["token_izi"] is None


def test_localhost_disi_ve_vekil_istekleri_denetime_yazilir(api: TestClient, make_user) -> None:
    token = _token(make_user("tester"), "submit")
    assert _raw(api, token, INIT, Host="evil.example").status_code == 421
    assert _raw(api, token, INIT, **{"X-Forwarded-For": "172.18.0.5"}).status_code == 403
    host, vekil = _redler()
    assert host.ozet["http_durum"] == 421 and "Host" in host.ozet["neden"]
    assert vekil.ozet["http_durum"] == 403 and "X-Forwarded-For" in vekil.ozet["neden"]
    # Geçerli token'ın bilgisi 401 dışı retlerde sorgulanmaz; yalnızca iz yazılır.
    assert "token_durumu" not in host.ozet and host.ozet["token_izi"] == token_hash(token)[:12]


def test_basarili_istek_denetime_red_yazmaz(api: TestClient, make_user) -> None:
    token = _token(make_user("tester"), "submit")
    assert _raw(api, token, INIT).status_code == 200
    assert _redler() == []

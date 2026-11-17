"""Çok proje — proje seçimi, istek bağlamı ve proje rolleri (TP-COK-PROJE-PLANI §2.2, §6).

Sahte aiprobe-home (`test_aiprobe_sso`) ile: `GET /projeler` / `PUT /proje` yanıt biçimleri (portal
Şerit 6 sözleşmesi), `/auth/me` proje alanları, `X-TP-Proje` 409 `proje_degisti`, seçili projede
rol yoksa 403 `proje_rolu_yok` (iptal değil), girişte kayıtlı seçim, rol hesabı geçişi (JIT),
"Rol değiştir" listesinin projeye süzülmesi, istek bağlamı (`proje.varsa()`), MCP token'ının
projeye bağlanması.
"""

# ruff: noqa: F811  (fikstürler test_aiprobe_sso'dan içe aktarılır)
from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.unit.platform.test_aiprobe_sso import (  # noqa: F401  (fikstürler)
    UID,
    SahteHome,
    _giris,
    _sifirla,
    client,
    home,
)
from tp_core.auth import aiprobe
from tp_core.auth.deps import CurrentUser
from tp_core.auth.tokens import issue_token, verify_bearer
from tp_core.proje import proje_kaydet, varsa
from tp_core.workflow.service import Principal

A = "aaaabbbbcccc"  # TP_HOME_PROJECT (varsayılan proje)
B = "ddddeeeeffff"
C = "cccc00001111"  # kurulumda kayıtlı değil


def _p(pid: str, roller: list[str], ad: str) -> dict[str, Any]:
    return {"oid": "0123456789ab", "org_name": "Örnek Org", "pid": pid, "code": ad[:3].upper(),
            "name": ad, "features": {"web": True}, "roles": roller}  # fmt: skip


@pytest.fixture
def cok(monkeypatch: pytest.MonkeyPatch, engine: Engine, home: SahteHome) -> SahteHome:
    monkeypatch.setenv("TP_HOME_PROJECT", A)
    with engine.begin() as c:
        proje_kaydet(c, B, kod="MOB", ad="Mobil", kaynak="env")
    aiprobe.kurulu_temizle()
    home.projeler[UID] = [
        _p(A, ["tester", "analyst"], "Bayi Portalı"),
        _p(B, ["tester"], "Mobil"),
        _p(C, ["analyst"], "Kayıtsız"),
    ]
    return home


def _eylemler(engine: Engine, eylem: str) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return [
            r[0]
            for r in c.execute(
                text("SELECT ozet FROM audit_event WHERE eylem = :e ORDER BY id"), {"e": eylem}
            )
        ]


def _tazele() -> None:
    aiprobe.PROJE_ROLLERI.temizle()
    aiprobe.ONBELLEK.temizle()


# ------------------------------------------------------------------ GET /projeler


def test_projeler_kip_kapali_enabled_false(
    client: TestClient, home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TP_HOME_PROJECT", raising=False)
    assert _giris(client, home, ["tester"]).status_code == 302
    v = client.get("/projeler").json()
    assert v["enabled"] is False and v["active"] == {"pid": "varsayilan"}
    me = client.get("/auth/me").json()
    assert not {"roller", "projeler_sayisi", "proje"} & set(me)
    # Kip kapalıyken başlık yine tutarlılık için denetlenir (tek proje).
    assert client.get("/tokens", headers={"X-TP-Proje": "varsayilan"}).status_code == 200


def test_projeler_bicimi_portal_sozlesmesi(cok: SahteHome, client: TestClient) -> None:
    assert _giris(client, cok, ["tester"]).status_code == 302
    r = client.get("/projeler")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["enabled"] is True
    assert v["active"] == {"pid": A}
    # Kurulumda kayıtlı olmayan C listelenmez (CONFIG_SOURCE=env: keşif yok).
    assert v["projects"] == [
        {"pid": A, "name": "Bayi Portalı", "org_name": "Örnek Org", "roles": ["tester", "analyst"]},
        {"pid": B, "name": "Mobil", "org_name": "Örnek Org", "roles": ["tester"]},
    ]
    assert v["role_labels"] == {
        "analyst": {"tr": "Analist", "en": "Analyst"},
        "tester": {"tr": "Test Uzmanı", "en": "Tester"},
    }


def test_acr1_yonetici_rolu_projede_sayilmaz(cok: SahteHome, client: TestClient) -> None:
    cok.projeler[UID] = [_p(A, ["tester"], "Bayi"), _p(B, ["po"], "Mobil")]
    assert _giris(client, cok, ["tester"], acr="1").status_code == 302
    v = client.get("/projeler").json()
    assert [p["pid"] for p in v["projects"]] == [A]  # B'de yalnız po: acr=1 → rol yok


# ------------------------------------------------------------------ /auth/me


def test_me_proje_alanlari(cok: SahteHome, client: TestClient) -> None:
    _giris(client, cok, ["tester"])
    me = client.get("/auth/me").json()
    assert me["proje"]["pid"] == A and me["proje"]["ad"] == "Bayi Portalı"
    assert me["proje"]["kod"] == "BAY"
    assert me["organizasyon"] == {"id": "0123456789ab", "ad": "Örnek Org"}
    assert me["roller"] == ["analyst", "tester"] and me["projeler_sayisi"] == 2
    assert me["rol"] == "tester" and "case.generate" in me["izinler"]


# ------------------------------------------------------------------ X-TP-Proje / rol yok


def test_baslik_uyusmazsa_409_get_dahil_auth_muaf(cok: SahteHome, client: TestClient) -> None:
    _giris(client, cok, ["tester"])
    assert client.get("/tokens", headers={"X-TP-Proje": A}).status_code == 200
    r = client.get("/tokens", headers={"X-TP-Proje": B})
    assert r.status_code == 409 and r.json()["kod"] == "proje_degisti"
    assert client.get("/auth/me", headers={"X-TP-Proje": B}).status_code == 200
    assert client.get("/projeler", headers={"X-TP-Proje": B}).status_code == 200
    assert client.get("/tokens").status_code == 200  # başlıksız: oturum projesi


def test_secili_projede_rol_yoksa_403_iptal_yok(
    cok: SahteHome, client: TestClient, engine: Engine
) -> None:
    _giris(client, cok, ["tester"])
    cok.projeler[UID] = [_p(A, ["analyst"], "Bayi"), _p(B, ["tester"], "Mobil")]
    _tazele()
    r = client.get("/tokens")
    assert r.status_code == 403 and r.json()["kod"] == "proje_rolu_yok"
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["izinler"] == []
    assert _eylemler(engine, "auth.aiprobe_revoked") == []
    # Rol tüm projelerden kalkınca iptal (bugünkü kural).
    cok.projeler[UID] = [_p(A, ["analyst"], "Bayi")]
    _tazele()
    with engine.begin() as c:
        c.execute(text("UPDATE oturum SET son_kontrol = now() - interval '2 minutes'"))
    assert client.get("/auth/me").status_code == 401


# ------------------------------------------------------------------ PUT /proje


def test_proje_degistir_ayni_hesap(cok: SahteHome, client: TestClient, engine: Engine) -> None:
    _giris(client, cok, ["tester"])
    r = client.put("/proje", json={"pid": B})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["proje"]["pid"] == B and me["rol"] == "tester" and me["roller"] == ["tester"]
    with engine.connect() as c:
        assert c.execute(
            text("SELECT project_id FROM oturum WHERE iptal_zamani IS NULL")
        ).all() == [(B,)]
        assert set(c.execute(text("SELECT secili_proje FROM app_user")).scalars()) == {B}
    assert client.get("/auth/me").json()["proje"]["pid"] == B
    assert client.get("/projeler").json()["active"] == {"pid": B}
    # Eski sekme A'yı gösteriyor: 409.
    assert client.get("/tokens", headers={"X-TP-Proje": A}).json()["kod"] == "proje_degisti"
    olay = _eylemler(engine, "auth.proje_degisti")
    assert olay[-1]["onceki"] == A and olay[-1]["yeni"] == B and not olay[-1]["hesap_degisti"]


def test_proje_yok_404_rol_yok_403(cok: SahteHome, client: TestClient) -> None:
    _giris(client, cok, ["tester"])
    r = client.put("/proje", json={"pid": C})  # kurulumda yok
    assert r.status_code == 404 and r.json()["kod"] == "proje_yok"
    assert client.put("/proje", json={"pid": "baska"}).status_code == 404
    cok.projeler[UID] = [_p(A, ["tester"], "Bayi"), _p(B, ["po"], "Mobil")]
    r = client.put("/proje", json={"pid": B})  # acr=2 devir; po var → geçer
    assert r.status_code == 200
    cok.projeler[UID] = [_p(A, ["tester"], "Bayi"), _p(B, ["bilinmeyen"], "Mobil")]
    r = client.put("/proje", json={"pid": B})
    assert r.status_code == 403 and r.json()["kod"] == "proje_rolu_yok"


def test_proje_degisince_rol_hesabi_gecer_jit(
    cok: SahteHome, client: TestClient, engine: Engine
) -> None:
    cok.projeler[UID] = [_p(A, ["tester"], "Bayi"), _p(B, ["analyst"], "Mobil")]
    _giris(client, cok, ["tester", "analyst"])
    assert client.get("/auth/me").json()["rol"] == "tester"
    r = client.put("/proje", json={"pid": B})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "analyst" and r.json()["proje"]["pid"] == B
    assert any(h.startswith("__Host-tp_session=") for h in r.headers.get_list("set-cookie"))
    me = client.get("/auth/me").json()
    assert me["rol"] == "analyst" and me["roles"] == ["analyst"]
    with engine.connect() as c:
        roller = sorted(c.execute(text("SELECT rol FROM app_user")).scalars())
        acik = c.execute(text("SELECT count(*) FROM oturum WHERE iptal_zamani IS NULL")).scalar()
    assert roller == ["analyst", "tester"] and acik == 1
    # "Rol değiştir" listesi seçili projeye süzülür.
    hesaplar = client.get("/auth/aiprobe/hesaplar").json()["hesaplar"]
    assert [h["rol"] for h in hesaplar] == ["analyst"]


def test_giriste_kayitli_secim_kullanilir(
    cok: SahteHome, client: TestClient, engine: Engine
) -> None:
    _giris(client, cok, ["tester"])
    client.put("/proje", json={"pid": B})
    _tazele()
    assert _giris(client, cok, ["tester"]).status_code == 302
    assert client.get("/auth/me").json()["proje"]["pid"] == B
    # Devirdeki proje kişinin projelerindeyse önceliklidir.
    assert _giris(client, cok, ["tester"], project_id=A).status_code == 302
    assert client.get("/auth/me").json()["proje"]["pid"] == A


def test_rol_degistir_hedef_rol_projede_olmali(
    cok: SahteHome, client: TestClient, engine: Engine
) -> None:
    cok.projeler[UID] = [_p(A, ["tester"], "Bayi"), _p(B, ["analyst"], "Mobil")]
    _giris(client, cok, ["tester", "analyst"])
    client.put("/proje", json={"pid": B})
    client.put("/proje", json={"pid": A})  # tester'a dönüş; analyst hesabı var ama A'da değil
    hesaplar = client.get("/auth/aiprobe/hesaplar").json()["hesaplar"]
    assert [h["rol"] for h in hesaplar] == ["tester"]
    with engine.connect() as c:
        analyst = c.execute(text("SELECT id FROM app_user WHERE rol = 'analyst'")).scalar_one()
    r = client.post("/auth/aiprobe/rol-degistir", json={"app_user_id": str(analyst)})
    assert r.status_code == 403 and r.json()["kod"] == "proje_rolu_yok"


# ------------------------------------------------------------------ istek bağlamı


def test_istek_baglami_oturum_projesi(cok: SahteHome, client: TestClient) -> None:
    app = client.app
    router = APIRouter()
    gorulen: list[Any] = []

    @router.get("/_test/baglam")
    def uc(user: CurrentUser) -> dict[str, Any]:
        b = varsa()
        gorulen.append((b.pid, b.kaynak) if b else None)
        return {"pid": user.project_id}

    app.include_router(router)  # type: ignore[attr-defined]
    _giris(client, cok, ["tester"])
    assert client.get("/_test/baglam").json() == {"pid": A}
    client.put("/proje", json={"pid": B})
    assert client.get("/_test/baglam").json() == {"pid": B}
    assert gorulen == [(A, "oturum"), (B, "oturum")]
    assert varsa() is None


# ------------------------------------------------------------------ MCP token


def test_token_projeye_bagli_ve_projedeki_rolle_sinirli(
    cok: SahteHome, client: TestClient, engine: Engine
) -> None:
    _giris(client, cok, ["tester"])
    client.put("/proje", json={"pid": B})
    with engine.connect() as c:
        o = c.execute(text("SELECT user_id, auth_time, acr, session_epoch_ms FROM oturum "
                           "WHERE iptal_zamani IS NULL")).one()  # fmt: skip
    u = Principal(o.user_id, "x", "tester", project_id=B)
    with Session(engine) as s:
        _tok, raw = issue_token(s, u, "submit", 600, auth_time=o.auth_time, acr=o.acr,
                                session_epoch_ms=o.session_epoch_ms)  # fmt: skip
        s.commit()
    from tp_core.auth.tokens import token_projesi

    with Session(engine) as s:
        beklenen = token_projesi(s, raw)
        p = verify_bearer(s, raw, "submit")
    assert p is not None and p.project_id == beklenen and p.kanal == "ide"
    if beklenen == B:  # Şerit 1 şeması (api_token.project_id) birleşince
        cok.projeler[UID] = [_p(A, ["tester"], "Bayi"), _p(B, ["analyst"], "Mobil")]
        _tazele()
        with Session(engine) as s:
            assert verify_bearer(s, raw, "submit") is None


def test_require_token_baglami(cok: SahteHome, client: TestClient, engine: Engine) -> None:
    from tp_core.auth.deps import require_token

    _giris(client, cok, ["tester"])
    with engine.connect() as c:
        o = c.execute(text("SELECT user_id, auth_time, acr, session_epoch_ms FROM oturum "
                           "WHERE iptal_zamani IS NULL")).one()  # fmt: skip
    with Session(engine) as s:
        _t, raw = issue_token(s, Principal(o.user_id, "x", "tester", project_id=A), "submit", 600,
                              auth_time=o.auth_time, acr=o.acr,
                              session_epoch_ms=o.session_epoch_ms)  # fmt: skip
        s.commit()
    app = FastAPI()

    @app.get("/t")
    def t(p: Principal = Depends(require_token("submit"))) -> dict[str, Any]:  # noqa: B008
        b = varsa()
        return {"pid": b.pid if b else None, "kaynak": b.kaynak if b else None}

    with TestClient(app) as c:
        r = c.get("/t", headers={"Authorization": f"Bearer {raw}"})
    assert r.json() == {"pid": A, "kaynak": "token"}


# ------------------------------------------------------------------ SSE ?proje=


def test_sse_sorgu_projesi(cok: SahteHome, client: TestClient) -> None:
    from tp_core.api.routers.events import proje_eslesir

    _giris(client, cok, ["tester"])
    r = client.get("/events", params={"proje": B})
    assert r.status_code == 409 and r.json()["kod"] == "proje_degisti"
    assert proje_eslesir({"event": "x", "data": {"project_id": A}}, A)
    assert not proje_eslesir({"event": "x", "data": {"project_id": B}}, A)
    assert not proje_eslesir({"event": "x", "project_id": B, "data": {}}, A)
    assert not proje_eslesir({"event": "x", "data": {}}, A)  # işaretsiz olay projeli akışa gitmez
    assert proje_eslesir({"event": "x", "project_id": "_kurulum", "data": {}}, A)
    assert proje_eslesir({"event": "x", "data": {}}, None)

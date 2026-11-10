"""AI Probe ortak girişi (specs/010-aiprobe-sso): sahte aiprobe-home (httpx.MockTransport) ile.

Kapsam: giriş turu, state uyuşmazlığı, JIT, rol seçici, rol değiştir, iptal → 401 + `tpt_` red,
rol kaldırma, home erişilemez → oturum korunur, boşta/mutlak süre, çıkış yönlendirmesi, admin
`/admin/kimlik-bagi` yalnız aiprobe-home servis kimliği, `local` kipte uçlar yok.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.api import main
from tp_core.auth import aiprobe
from tp_core.auth.login import THROTTLE
from tp_core.auth.passwords import verify_password
from tp_core.auth.sessions import AIPROBE_COOKIE_NAME, COOKIE_NAME
from tp_core.auth.tokens import issue_token, verify_bearer
from tp_core.config import get_settings
from tp_core.workflow.service import Principal

from .conftest import PAROLA, Db

MakeUser = Callable[..., Principal]

HOME = "https://home.test"
ID = "https://id.test"
HOME_SA = "home-run@aiprobe-platform.iam.gserviceaccount.com"
TP_AUD = "https://testing.test"
TP_SA_TOKEN = "tp-sa-id-token"
UID = "uid-ayse"
EPOCH_MS = 1_762_780_000_123


@dataclass
class SahteHome:
    """CONTRACT v1 `/v1/*` uçlarının sahtesi."""

    kodlar: dict[str, dict[str, Any]] = field(default_factory=dict)
    kisiler: dict[str, dict[str, Any]] = field(default_factory=dict)
    kapali: bool = False
    cagrilar: list[tuple[str, dict[str, Any], str]] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        if self.kapali:
            raise httpx.ConnectError("home kapalı", request=req)
        import json

        govde = json.loads(req.content or b"{}")
        self.cagrilar.append((req.url.path, govde, req.headers.get("authorization", "")))
        if req.headers.get("authorization") != f"Bearer {TP_SA_TOKEN}":
            return httpx.Response(401, json={"error": "invalid_caller"})
        if req.url.path == "/v1/handoff/redeem":
            kayit = self.kodlar.pop(govde.get("code", ""), None)  # tek kullanımlık
            if kayit is None:
                return httpx.Response(400, json={"error": "invalid_code"})
            # Home `acr="1"` iken ürünün `admin_roles`'unu (TP: po) devre eklemez.
            kayit = dict(kayit)
            kayit["roles"] = _admin_suz(kayit["roles"], kayit.get("acr"))
            kayit["products"] = {
                k: _admin_suz(v, kayit.get("acr")) for k, v in kayit.get("products", {}).items()
            }
            return httpx.Response(200, json=kayit)
        if req.url.path == "/v1/session/check":
            k = self.kisiler.get(govde["uid"])
            if k is None:
                return httpx.Response(200, json={"valid": False, "reason": "not_found"})
            if not k.get("valid", True):
                return httpx.Response(200, json={"valid": False, "reason": k.get("reason")})
            if _iptal_edildi(k, govde):
                return httpx.Response(200, json={"valid": False, "reason": "revoked"})
            roller = _admin_suz(k["roles"], govde.get("acr"))
            if not roller:
                return httpx.Response(200, json={"valid": False, "reason": "no_access"})
            urunler = {"tp": roller, **k.get("diger", {})}
            return httpx.Response(
                200, json={"valid": True, "roles": roller, "products": urunler, "acr_ok": True}
            )
        return httpx.Response(404)

    def kontroller(self) -> list[dict[str, Any]]:
        return [c[1] for c in self.cagrilar if c[0] == "/v1/session/check"]

    def sayi(self, yol: str) -> int:
        return sum(1 for c in self.cagrilar if c[0] == yol)


ADMIN_ROLLERI = frozenset({"po"})  # products/testing-probe.yaml `admin_roles`


def _admin_suz(roller: list[str], acr: Any) -> list[str]:
    return list(roller) if acr == "2" else [r for r in roller if r not in ADMIN_ROLLERI]


def _iptal_edildi(k: dict[str, Any], govde: dict[str, Any]) -> bool:
    """CONTRACT v1.2 `revoked` kuralı: V = `valid_after` (sn), E = `session_epoch_ms`, R =
    `revoked_at_ms` (home'un iptal anı, ms)."""
    v, r = k.get("valid_after"), k.get("revoked_at_ms")
    e = govde.get("session_epoch_ms")
    if v is None and r is None:
        return False
    if e is None:
        return v is not None and v > govde["auth_time"]
    if r is not None and v is not None and r // 1000 == v:
        return bool(r >= e)
    return v is not None and v >= e // 1000


def sahte_dogrulayici(token: str, audience: str) -> dict[str, Any]:
    assert audience == TP_AUD
    tablo = {
        "home-ok": {"email": HOME_SA, "email_verified": True},
        "baska-sa": {"email": "kotu@x.iam.gserviceaccount.com", "email_verified": True},
        "dogrulanmamis": {"email": HOME_SA, "email_verified": False},
    }
    if token not in tablo:
        raise ValueError("imza geçersiz")
    return tablo[token]


@pytest.fixture(autouse=True)
def _sifirla() -> Iterator[None]:
    THROTTLE._kayit.clear()
    aiprobe.reset()
    yield
    aiprobe.reset()
    THROTTLE._kayit.clear()


@pytest.fixture
def home(db: Db, monkeypatch: pytest.MonkeyPatch) -> SahteHome:
    monkeypatch.setenv("TP_AUTH_MODE", "aiprobe")
    monkeypatch.setenv("AIPROBE_HOME_RUN_URL", HOME)
    monkeypatch.setenv("AIPROBE_ID_ORIGIN", ID)
    monkeypatch.setenv("AIPROBE_ALLOWED_ORGS", "antreklabs")
    monkeypatch.setenv("AIPROBE_HOME_SA", HOME_SA)
    monkeypatch.setenv("AIPROBE_TP_AUDIENCE", TP_AUD)
    get_settings.cache_clear()
    h = SahteHome()
    aiprobe.configure(
        transport=httpx.MockTransport(h.handler),
        token_saglayici=lambda aud: TP_SA_TOKEN if aud == HOME else "yanlis-aud",
        dogrulayici=sahte_dogrulayici,
    )
    return h


@pytest.fixture
def client(home: SahteHome) -> Iterator[TestClient]:
    # `__Host-` çerezleri Secure: istemci https üzerinden konuşur.
    with TestClient(main.create_app(), base_url="https://testserver") as c:
        yield c


def _devir(state: str, roles: list[str], uid: str = UID, **ek: Any) -> dict[str, Any]:
    return {
        "uid": uid,
        "email": "ayse.yilmaz@antreklabs.com",
        "name": "Ayşe Yılmaz",
        "locale": "tr",
        "org": "antreklabs",
        "roles": roles,
        "ap_uid": None,
        "auth_time": 1_762_780_000,
        "session_epoch_ms": EPOCH_MS,
        "acr": "2",
        "products": {"tp": roles, "ap": ["user"]},
        "state": state,
        "continue": "/x",
        **ek,
    }


def _giris(
    client: TestClient,
    home: SahteHome,
    roles: list[str],
    *,
    devam: str = "/x",
    **ek: Any,
) -> httpx.Response:
    r = client.get("/auth/aiprobe/login", params={"continue": devam}, follow_redirects=False)
    assert r.status_code == 302, r.text
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    kod = uuid.uuid4().hex
    home.kodlar[kod] = _devir(state, roles, **ek)
    home.kisiler.setdefault(ek.get("uid", UID), {"roles": roles})
    return client.get(
        "/auth/aiprobe/callback", params={"code": kod, "state": state}, follow_redirects=False
    )


def _bagla(engine: Engine, user: Principal, uid: str = UID) -> None:
    with engine.begin() as c:
        c.exec_driver_sql(
            "INSERT INTO kimlik_bagi (external_uid, app_user_id) VALUES (%s, %s)", (uid, user.id)
        )


def _kontrol_zamanini_eskit(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("UPDATE oturum SET son_kontrol = now() - interval '2 minutes'"))
    aiprobe.ONBELLEK.temizle()


def _epoch(engine: Engine, user_id: uuid.UUID | str) -> int:
    with engine.connect() as c:
        return c.execute(
            text("SELECT auth_epoch FROM app_user WHERE id = :i"), {"i": str(user_id)}
        ).scalar_one()


def _eylemler(engine: Engine) -> list[str]:
    with engine.connect() as c:
        return list(c.execute(text("SELECT eylem FROM audit_event ORDER BY id")).scalars())


# ------------------------------------------------------------------ yerel kip değişmez


def test_local_kipte_aiprobe_uclari_yok_ve_cerez_tp_session(db: Db, make_user: MakeUser) -> None:
    assert get_settings().auth_mode == "local"
    u = make_user("analyst")
    with TestClient(main.create_app()) as c:
        assert c.get("/auth/aiprobe/login", follow_redirects=False).status_code == 404
        assert c.get("/auth/aiprobe/callback").status_code == 404
        assert c.get("/admin/kimlik-bagi").status_code == 404
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        assert COOKIE_NAME in r.cookies and AIPROBE_COOKIE_NAME not in r.cookies
        assert "secure" not in r.headers["set-cookie"].lower().split("tp_cihaz")[0]
        assert c.get("/auth/me").status_code == 200


def test_both_kipte_yerel_giris_host_cerezi(
    home: SahteHome, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_AUTH_MODE", "both")
    get_settings.cache_clear()
    u = make_user("analyst")
    with TestClient(main.create_app(), base_url="https://testserver") as c:
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        cerez = next(h for h in r.headers.get_list("set-cookie") if h.startswith("__Host-"))
        assert "secure" in cerez.lower() and "path=/" in cerez.lower()
        assert c.get("/auth/me").status_code == 200
    assert home.cagrilar == []  # yerel oturum home'a sorulmaz


def test_aiprobe_kipte_yerel_giris_kapali(client: TestClient, make_user: MakeUser) -> None:
    u = make_user("analyst")
    r = client.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 404


# ------------------------------------------------------------------ giriş turu + JIT


def test_giris_turu_ve_jit(client: TestClient, home: SahteHome, engine: Engine) -> None:
    r = client.get("/auth/aiprobe/login", params={"continue": "/x?y=1"}, follow_redirects=False)
    assert r.status_code == 302
    hedef = urlsplit(r.headers["location"])
    assert f"{hedef.scheme}://{hedef.netloc}{hedef.path}" == f"{ID}/login"
    q = parse_qs(hedef.query)
    assert q["product"] == ["testing-probe"] and q["continue"] == ["/x?y=1"]
    assert len(q["state"][0]) >= 43
    durum_cerezi = next(
        h for h in r.headers.get_list("set-cookie") if h.startswith("__Host-aiprobe_state=")
    )
    assert "secure" in durum_cerezi.lower() and "httponly" in durum_cerezi.lower()

    kod = "kod-1"
    home.kodlar[kod] = _devir(q["state"][0], ["tester", "bilinmeyen-rol"])
    home.kisiler[UID] = {"roles": ["tester"]}
    r = client.get(
        "/auth/aiprobe/callback",
        params={"code": kod, "state": q["state"][0]},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/x?y=1"
    assert AIPROBE_COOKIE_NAME in r.cookies
    # Takas TP servis kimliğiyle yapıldı.
    assert home.cagrilar[0][0] == "/v1/handoff/redeem"
    assert home.cagrilar[0][2] == f"Bearer {TP_SA_TOKEN}"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["rol"] == "tester"
    assert me.json()["ad_soyad"] == "Ayşe Yılmaz"
    assert me.json()["gorunen_ad"] == "Ayşe Yılmaz · Testçi"
    with engine.connect() as c:
        bag = c.execute(
            text(
                "SELECT u.kullanici_adi, u.rol, u.parola_hash FROM kimlik_bagi b "
                "JOIN app_user u ON u.id = b.app_user_id WHERE b.external_uid = :u"
            ),
            {"u": UID},
        ).all()
        oturum = c.execute(text("SELECT external_uid, auth_time FROM oturum")).one()
    assert len(bag) == 1 and bag[0].rol == "tester"
    assert bag[0].kullanici_adi == "ayse.yilmaz-tester"
    assert not verify_password(bag[0].parola_hash, "herhangi")  # yerel girişle açılamaz
    assert tuple(oturum) == (UID, 1_762_780_000)
    assert "auth.jit_user" in _eylemler(engine) and "auth.login" in _eylemler(engine)

    # İkinci giriş yeni hesap açmaz.
    assert _giris(client, home, ["tester"]).status_code == 302
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app_user")).scalar_one() == 1


def test_state_uyusmazligi_takas_yapmaz(client: TestClient, home: SahteHome) -> None:
    r = client.get("/auth/aiprobe/login", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    home.kodlar["k"] = _devir(state, ["tester"])
    r = client.get(
        "/auth/aiprobe/callback",
        params={"code": "k", "state": state[:-1] + ("A" if state[-1] != "A" else "B")},
        follow_redirects=False,
    )
    assert r.status_code == 400 and r.json()["kod"] == "durum_uyusmuyor"
    assert home.cagrilar == [] and AIPROBE_COOKIE_NAME not in r.cookies
    # Çerez hiç yoksa da red.
    client.cookies.clear()
    r = client.get("/auth/aiprobe/callback", params={"code": "k", "state": state})
    assert r.status_code == 400 and r.json()["kod"] == "durum_uyusmuyor"
    assert client.get("/auth/me").status_code == 401


def test_kod_tekrari_ve_org_reddi(client: TestClient, home: SahteHome) -> None:
    r = client.get("/auth/aiprobe/login", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = client.get("/auth/aiprobe/callback", params={"code": "yok", "state": state})
    assert r.status_code == 400 and r.json()["kod"] == "giris_kodu_gecersiz"
    r = _giris(client, home, ["tester"], org="baska-org")
    assert r.status_code == 403 and r.json()["kod"] == "org_reddi"
    r = _giris(client, home, ["admin"])  # TP rolü değil
    assert r.status_code == 403 and r.json()["kod"] == "rol_yok"


@pytest.mark.parametrize(
    ("girdi", "beklenen"),
    [
        ("/x?y=1", "/x?y=1"),
        ("//evil.com", "/"),
        ("/\\evil.com", "/"),
        ("https://evil.com", "/"),
        ("javascript:alert(1)", "/"),
        ("/a\nb", "/"),
        ("", "/"),
        (None, "/"),
        ("/" + "a" * 3000, "/"),
    ],
)
def test_guvenli_continue(girdi: str | None, beklenen: str) -> None:
    assert aiprobe.guvenli_continue(girdi) == beklenen


# ------------------------------------------------------------------ rol seçici + rol değiştir


def test_rol_secici(
    client: TestClient, home: SahteHome, make_user: MakeUser, engine: Engine
) -> None:
    analist, po = make_user("analyst"), make_user("po")
    _bagla(engine, analist)
    _bagla(engine, po)
    r = _giris(client, home, ["analyst", "po"])
    assert r.status_code == 302
    assert r.headers["location"] == "/rol-sec?continue=%2Fx"
    assert AIPROBE_COOKIE_NAME not in r.cookies  # henüz oturum yok
    assert client.get("/auth/me").status_code == 401

    liste = client.get("/auth/aiprobe/hesaplar")
    assert liste.status_code == 200
    assert {h["id"] for h in liste.json()["hesaplar"]} == {str(analist.id), str(po.id)}
    assert liste.json()["continue"] == "/x"

    yabanci = make_user("tester")
    assert (
        client.post("/auth/aiprobe/rol-sec", json={"app_user_id": str(yabanci.id)}).status_code
        == 403
    )
    r = client.post("/auth/aiprobe/rol-sec", json={"app_user_id": str(po.id)})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "po" and r.json()["continue"] == "/x"
    assert client.get("/auth/me").json()["rol"] == "po"
    # Seçim çerezi tek kullanımlık.
    assert (
        client.post("/auth/aiprobe/rol-sec", json={"app_user_id": str(analist.id)}).status_code
        == 401
    )
    # JIT yapılmadı: her rolün bağlı hesabı vardı.
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app_user")).scalar_one() == 3


def test_rol_degistir_yeni_oturum_kimligi(
    client: TestClient, home: SahteHome, make_user: MakeUser, engine: Engine
) -> None:
    analist, po, yabanci = make_user("analyst"), make_user("po"), make_user("tester")
    _bagla(engine, analist)
    _bagla(engine, po)
    _bagla(engine, yabanci, uid="baska-kisi")
    _giris(client, home, ["analyst", "po"])
    assert client.post("/auth/aiprobe/rol-sec", json={"app_user_id": str(analist.id)}).is_success
    with engine.connect() as c:
        eski_sid = c.execute(text("SELECT id FROM oturum WHERE iptal_zamani IS NULL")).scalar_one()

    menu = client.get("/auth/aiprobe/hesaplar").json()
    assert menu["aktif_id"] == str(analist.id) and len(menu["hesaplar"]) == 2

    r = client.post("/auth/aiprobe/rol-degistir", json={"app_user_id": str(yabanci.id)})
    assert r.status_code == 403
    r = client.post("/auth/aiprobe/rol-degistir", json={"app_user_id": str(po.id)})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "po"
    assert client.get("/auth/me").json()["rol"] == "po"
    with engine.connect() as c:
        satirlar = c.execute(text("SELECT id, iptal_zamani FROM oturum ORDER BY olusturma")).all()
    acik = [s.id for s in satirlar if s.iptal_zamani is None]
    assert len(acik) == 1 and acik[0] != eski_sid
    assert "auth.role_switch" in _eylemler(engine)

    # Rol AI Probe hesabından kaldırıldıysa geçiş yok (taze kontrol).
    home.kisiler[UID] = {"roles": ["po"]}
    r = client.post("/auth/aiprobe/rol-degistir", json={"app_user_id": str(analist.id)})
    assert r.status_code == 403


def test_rol_degistir_yerel_oturumda_yok(
    home: SahteHome, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_AUTH_MODE", "both")
    get_settings.cache_clear()
    u = make_user("analyst")
    with TestClient(main.create_app(), base_url="https://testserver") as c:
        c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        r = c.post("/auth/aiprobe/rol-degistir", json={"app_user_id": str(u.id)})
        assert r.status_code == 403


# ------------------------------------------------------------------ iptal ve süreler


def test_kontrol_60_sn_onbellekli(client: TestClient, home: SahteHome, engine: Engine) -> None:
    _giris(client, home, ["tester"])
    for _ in range(3):
        assert client.get("/auth/me").status_code == 200
    assert home.sayi("/v1/session/check") == 0  # devirden beri < 60 sn
    _kontrol_zamanini_eskit(engine)
    assert client.get("/auth/me").status_code == 200
    assert client.get("/auth/me").status_code == 200
    assert home.sayi("/v1/session/check") == 1  # son_kontrol yenilendi
    assert home.cagrilar[-1][1] == {
        "uid": UID,
        "auth_time": 1_762_780_000,
        "acr": "2",
        "session_epoch_ms": EPOCH_MS,
    }


def test_oturum_iptali_401_ve_tpt_token_reddi(
    client: TestClient, home: SahteHome, engine: Engine, session: Session
) -> None:
    _giris(client, home, ["analyst"])
    me = client.get("/auth/me").json()
    p = Principal(uuid.UUID(me["id"]), me["kullanici_adi"], "analyst")
    _tok, raw = issue_token(session, p, "publish", 3600)
    session.commit()
    assert verify_bearer(session, raw, "publish") is not None
    session.commit()

    home.kisiler[UID] = {"valid": False, "reason": "revoked"}
    _kontrol_zamanini_eskit(engine)
    assert client.get("/auth/me").status_code == 401
    assert _epoch(engine, me["id"]) == 1
    assert "auth.aiprobe_revoked" in _eylemler(engine)
    session.expire_all()
    assert verify_bearer(session, raw, "publish") is None
    # Home yeniden "geçerli" dese de epoch artmış çerez ve token geri gelmez.
    home.kisiler[UID] = {"roles": ["analyst"]}
    aiprobe.ONBELLEK.temizle()
    assert client.get("/auth/me").status_code == 401
    assert verify_bearer(session, raw, "publish") is None


def test_tpt_token_kendi_kontroluyle_duser(
    client: TestClient, home: SahteHome, engine: Engine, session: Session
) -> None:
    """Oturum hiç istek yapmasa da MCP token'ı 60 sn kontrolüyle iptali görür."""
    _giris(client, home, ["analyst"])
    me = client.get("/auth/me").json()
    p = Principal(uuid.UUID(me["id"]), me["kullanici_adi"], "analyst")
    _tok, raw = issue_token(session, p, "publish", 3600)
    session.commit()
    home.kisiler[UID] = {"valid": False, "reason": "disabled"}
    aiprobe.ONBELLEK.temizle()
    assert verify_bearer(session, raw, "publish") is None
    session.commit()
    assert _epoch(engine, me["id"]) == 1
    assert client.get("/auth/me").status_code == 401  # aynı kişinin oturumu da düştü


def _mcp_istemci(home: SahteHome) -> TestClient:
    app = main.create_app()

    @app.post("/mcp")
    def _mcp() -> dict[str, Any]:  # POST /tokens yalnızca /mcp bağlıyken token üretir
        return {}

    return TestClient(app, base_url="https://testserver")


def _token_auth_time(engine: Engine) -> list[int | None]:
    with engine.connect() as c:
        return list(c.execute(text("SELECT auth_time FROM api_token ORDER BY olusturma")).scalars())


def test_tpt_token_oturumun_auth_time_ini_tasir(
    home: SahteHome, engine: Engine, session: Session
) -> None:
    """Oturum açıldıktan sonra, token üretilmeden önce yapılan iptal token'ı da düşürür.

    Token'ın kontrolü üretim anıyla yapılsaydı (iptal anı < üretim anı) iptal görülmezdi; token
    oturumun `auth_time`/`acr`/`session_epoch_ms`'ini taşıdığı için görülür.
    """
    with _mcp_istemci(home) as client:
        _giris(client, home, ["analyst"])
        r = client.post("/tokens", json={"kapsam": "publish"})
        assert r.status_code == 201, r.text
        raw = r.json()["token"]
    assert _token_auth_time(engine) == [1_762_780_000]
    with engine.connect() as c:
        assert tuple(c.execute(text("SELECT acr, session_epoch_ms FROM api_token")).one()) == (
            "2",
            EPOCH_MS,
        )
    # Kişi oturum açıldıktan 50 ms sonra (aynı saniye; token üretiminden önce) home üzerinden
    # iptal edildi; TP'nin bunu henüz görmemiş olması önbellekten gelir.
    iptal_ms = EPOCH_MS + 50
    home.kisiler[UID] = {
        "roles": ["analyst"],
        "revoked_at_ms": iptal_ms,
        "valid_after": iptal_ms // 1000,
    }
    aiprobe.ONBELLEK.temizle()
    assert verify_bearer(session, raw, "publish") is None
    session.commit()
    assert home.kontroller()[-1] == {
        "uid": UID,
        "auth_time": 1_762_780_000,
        "acr": "2",
        "session_epoch_ms": EPOCH_MS,
    }


def test_yerel_oturumdan_uretilen_token_uretim_aniyla_kontrol_edilir(
    home: SahteHome, engine: Engine, session: Session, make_user: MakeUser
) -> None:
    """`auth_time` boş token (yerel oturumdan üretildi): kontrol eskisi gibi üretim anıyla."""
    u = make_user("analyst")
    _bagla(engine, u)
    tok, raw = issue_token(session, u, "publish", 3600)
    session.commit()
    assert tok.auth_time is None
    uretim = int(tok.olusturma.timestamp())
    home.kisiler[UID] = {"roles": ["analyst"], "valid_after": uretim - 60}
    assert verify_bearer(session, raw, "publish") is not None
    session.commit()
    assert home.kontroller()[-1] == {"uid": UID, "auth_time": uretim, "acr": "1"}
    home.kisiler[UID] = {"roles": ["analyst"], "valid_after": uretim + 60}
    aiprobe.ONBELLEK.temizle()
    assert verify_bearer(session, raw, "publish") is None


def test_local_kipte_token_auth_time_bos(db: Db, make_user: MakeUser, engine: Engine) -> None:
    app = main.create_app()

    @app.post("/mcp")
    def _mcp() -> dict[str, Any]:
        return {}

    u = make_user("analyst")
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        assert client.post("/tokens", json={"kapsam": "publish"}).status_code == 201
    assert _token_auth_time(engine) == [None]


def test_rol_kaldirma_oturumu_dusurur(client: TestClient, home: SahteHome, engine: Engine) -> None:
    _giris(client, home, ["po"])
    home.kisiler[UID] = {"roles": ["analyst"]}
    _kontrol_zamanini_eskit(engine)
    assert client.get("/auth/me").status_code == 401


def test_home_erisilemez_oturum_korunur(
    client: TestClient, home: SahteHome, engine: Engine
) -> None:
    _giris(client, home, ["tester"])
    home.kapali = True
    _kontrol_zamanini_eskit(engine)
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.headers.get("x-aiprobe-degraded") == "1"
    # Yeni giriş yapılamaz: anlamlı 503.
    r = client.get("/auth/aiprobe/login", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = client.get("/auth/aiprobe/callback", params={"code": "k", "state": state})
    assert r.status_code == 503 and r.json()["kod"] == "kimlik_servisi_yok"
    # Home dönünce uyarı kalkar.
    home.kapali = False
    _kontrol_zamanini_eskit(engine)
    r = client.get("/auth/me")
    assert r.status_code == 200 and "x-aiprobe-degraded" not in r.headers


def test_bosta_kayan_ve_mutlak_sure(client: TestClient, home: SahteHome, engine: Engine) -> None:
    _giris(client, home, ["tester"])
    with engine.connect() as c:
        ilk = c.execute(text("SELECT son_kullanma - olusturma FROM oturum")).scalar_one()
    assert timedelta(minutes=29) < ilk <= timedelta(minutes=30, seconds=5)

    with engine.begin() as c:  # 25 dk sonra istek: süre kayar
        c.execute(text("UPDATE oturum SET son_kullanma = now() + interval '5 minutes'"))
    assert client.get("/auth/me").status_code == 200
    with engine.connect() as c:
        kalan = c.execute(text("SELECT son_kullanma - now() FROM oturum")).scalar_one()
    assert kalan > timedelta(minutes=29)

    with engine.begin() as c:  # mutlak sınır: 8 sa'yı aşmaz
        c.execute(
            text(
                "UPDATE oturum SET olusturma = now() - interval '7 hours 50 minutes', "
                "son_kullanma = now() + interval '1 minute'"
            )
        )
    assert client.get("/auth/me").status_code == 200
    with engine.connect() as c:
        fark = c.execute(text("SELECT (olusturma + interval '8 hours') - son_kullanma FROM oturum"))
        assert fark.scalar_one() >= timedelta(0)

    with engine.begin() as c:  # 30 dk hiç istek yok → 401
        c.execute(text("UPDATE oturum SET son_kullanma = now() - interval '1 second'"))
    assert client.get("/auth/me").status_code == 401


def test_cikis_tum_urunlere_yonlendirir(client: TestClient, home: SahteHome) -> None:
    _giris(client, home, ["tester"])
    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert r.json()["redirect"] == f"{ID}/logout?product=testing-probe&auto=1"
    assert client.get("/auth/me").status_code == 401


def test_cikis_form_postu_303_ile_home_cikisina(client: TestClient, home: SahteHome) -> None:
    _giris(client, home, ["tester"])
    r = client.post("/auth/logout", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"{ID}/logout?product=testing-probe&auto=1"
    assert client.get("/auth/me").status_code == 401
    # Oturum yokken form POST'u: yerel giriş ekranı.
    r = client.post("/auth/logout", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/giris"


def test_yerel_kipe_donulunce_aiprobe_oturumu_reddedilir(
    client: TestClient, home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    _giris(client, home, ["tester"])
    cerez = client.cookies.get(AIPROBE_COOKIE_NAME)
    monkeypatch.setenv("TP_AUTH_MODE", "local")
    get_settings.cache_clear()
    with TestClient(main.create_app(), base_url="https://testserver") as c:
        c.cookies.set(COOKIE_NAME, cerez)
        assert c.get("/auth/me").status_code == 401
    assert home.sayi("/v1/session/check") == 0


# ------------------------------------------------------------------ admin /admin/kimlik-bagi


def _yetki(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_kimlik_bagi_yalniz_home_servisi(
    client: TestClient, home: SahteHome, make_user: MakeUser, engine: Engine
) -> None:
    hedef = make_user("analyst", ad="analist2")
    govde = {"external_uid": UID, "kullanici_adi": "analist2"}
    assert client.put("/admin/kimlik-bagi", json=govde).status_code == 401
    for token, durum in (("bozuk", 401), ("baska-sa", 403), ("dogrulanmamis", 403)):
        r = client.put("/admin/kimlik-bagi", json=govde, headers=_yetki(token))
        assert r.status_code == durum, token
        assert client.get("/admin/kimlik-bagi", headers=_yetki(token)).status_code == durum
    # Kullanıcı oturumu ile de olmaz.
    _giris(client, home, ["tester"], uid="baska-uid")
    assert client.get("/auth/me").status_code == 200
    assert client.get("/admin/kimlik-bagi").status_code == 401
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM kimlik_bagi WHERE app_user_id = :i"), {"i": hedef.id}
            ).scalar_one()
            == 0
        )

    r = client.put("/admin/kimlik-bagi", json=govde, headers=_yetki("home-ok"))
    assert r.status_code == 200, r.text
    assert r.json()["app_user_id"] == str(hedef.id) and r.json()["rol"] == "analyst"
    # İdempotent; başka kişiye bağlama 409.
    assert client.put("/admin/kimlik-bagi", json=govde, headers=_yetki("home-ok")).is_success
    r = client.put(
        "/admin/kimlik-bagi",
        json={"external_uid": "baska", "app_user_id": str(hedef.id)},
        headers=_yetki("home-ok"),
    )
    assert r.status_code == 409
    liste = client.get(
        "/admin/kimlik-bagi", params={"external_uid": UID}, headers=_yetki("home-ok")
    )
    assert [b["kullanici_adi"] for b in liste.json()["baglar"]] == ["analist2"]
    hesaplar = client.get("/admin/kimlik-bagi/hesaplar", headers=_yetki("home-ok")).json()
    assert {h["kullanici_adi"]: h["bagli_uid"] for h in hesaplar["hesaplar"]}["analist2"] == UID

    r = client.delete(f"/admin/kimlik-bagi/{hedef.id}", headers=_yetki("home-ok"))
    assert r.status_code == 204
    assert _epoch(engine, hedef.id) == 1
    assert {"admin.kimlik_bagi.bagla", "admin.kimlik_bagi.kaldir"} <= set(_eylemler(engine))


def test_bag_kaldirma_acik_oturumu_dusurur(
    client: TestClient, home: SahteHome, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user("tester")
    _bagla(engine, u)
    _giris(client, home, ["tester"])
    assert client.get("/auth/me").json()["id"] == str(u.id)
    r = client.delete(f"/admin/kimlik-bagi/{u.id}", headers=_yetki("home-ok"))
    assert r.status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_epoch_cerezle_uyusmazsa_red(client: TestClient, home: SahteHome, engine: Engine) -> None:
    _giris(client, home, ["tester"])
    with engine.begin() as c:
        c.execute(text("UPDATE app_user SET auth_epoch = auth_epoch + 1"))
    assert client.get("/auth/me").status_code == 401


def test_oturum_kontrolu_suresi_saatle(home: SahteHome) -> None:
    """`aiprobe.simdi` enjekte edilebilir (oturum kontrolü aralığı sahte saatle sınanabilir)."""
    sabit = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    aiprobe.configure(saat=lambda: sabit)
    assert aiprobe.simdi() == sabit


# ------------------------------------------------------------------ portal sözleşmesi


def test_kimlik_kipi_basligi_yalniz_aiprobe_kipinde(db: Db, make_user: MakeUser) -> None:
    assert get_settings().auth_mode == "local"
    with TestClient(main.create_app()) as c:
        assert "x-tp-kimlik" not in c.get("/auth/me").headers
        assert "x-tp-kimlik" not in c.get("/health").headers


def test_kimlik_kipi_basligi_401_dahil(client: TestClient, home: SahteHome) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.headers["x-tp-kimlik"] == f"kip=aiprobe; home={ID}; urun=testing-probe"


def test_me_aiprobe_oturumunda_product_ve_roles(
    client: TestClient, home: SahteHome, make_user: MakeUser, engine: Engine, db: Db
) -> None:
    analist, po = make_user("analyst"), make_user("po")
    _bagla(engine, analist)
    _bagla(engine, po)
    _giris(client, home, ["analyst", "po"])
    client.post("/auth/aiprobe/rol-sec", json={"app_user_id": str(po.id)})
    me = client.get("/auth/me").json()
    assert me["product"] == "testing-probe" and me["roles"] == ["analyst", "po"]


def test_me_yerel_oturumda_ek_alan_yok(db: Db, make_user: MakeUser) -> None:
    u = make_user("analyst")
    with TestClient(main.create_app()) as c:
        c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        me = c.get("/auth/me").json()
    assert "product" not in me and "roles" not in me


HTML = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


def test_callback_hatasi_tarayicida_turkce_sayfa(client: TestClient, home: SahteHome) -> None:
    r = client.get("/auth/aiprobe/login", params={"continue": "/gereksinimler"},
                   follow_redirects=False)  # fmt: skip
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = client.get(
        "/auth/aiprobe/callback", params={"code": "k", "state": state + "x"}, headers=HTML
    )
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    govde = r.text
    assert '<html lang="tr">' in govde and "Giriş isteği doğrulanamadı" in govde
    assert "Tekrar dene" in govde and 'href="login?continue=%2Fgereksinimler"' in govde
    assert "<script" not in govde
    assert home.cagrilar == []
    # Geçersiz kod ve home kapalı da sayfa.
    r = client.get("/auth/aiprobe/login", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = client.get("/auth/aiprobe/callback", params={"code": "yok", "state": state}, headers=HTML)
    assert r.status_code == 400 and "Giriş bağlantısının süresi doldu" in r.text
    home.kapali = True
    r = client.get("/auth/aiprobe/login", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = client.get("/auth/aiprobe/callback", params={"code": "k", "state": state}, headers=HTML)
    assert r.status_code == 503 and "kimlik servisine ulaşılamıyor" in r.text


def test_callback_hata_sayfasi_kacislanir(client: TestClient, home: SahteHome) -> None:
    r = client.get("/auth/aiprobe/login", params={"continue": '/x"><b>'}, follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = client.get("/auth/aiprobe/callback", params={"code": "k", "state": "x"}, headers=HTML)
    assert r.status_code == 400 and "<b>" not in r.text
    assert state  # çerezdeki continue yalnız kaçışlı/kodlanmış olarak sayfaya girer


def test_login_yapilandirma_eksik_sayfa(
    client: TestClient, home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIPROBE_HOME_RUN_URL", "")
    get_settings.cache_clear()
    r = client.get("/auth/aiprobe/login", headers=HTML, follow_redirects=False)
    assert r.status_code == 503 and "Tekrar dene" in r.text
    r = client.get("/auth/aiprobe/login", follow_redirects=False)
    assert r.status_code == 503 and r.json()["kod"] == "kimlik_servisi_yok"


# ------------------------------------------------------------------ CONTRACT v1.2: acr + epoch


def test_mfa_po_oturumu_ve_tokeni_kontrolde_korunur(
    home: SahteHome, engine: Engine, session: Session
) -> None:
    """`acr=2` saklanır ve gönderilir: home `admin_roles` (po) süzgeci MFA'lı oturumu düşürmez."""
    with _mcp_istemci(home) as client:
        _giris(client, home, ["po"])
        me = client.get("/auth/me").json()
        assert me["rol"] == "po"
        _kontrol_zamanini_eskit(engine)
        assert client.get("/auth/me").status_code == 200
        assert home.kontroller()[-1]["acr"] == "2"
    with engine.connect() as c:
        assert c.execute(text("SELECT acr FROM oturum")).scalar_one() == "2"
    p = Principal(uuid.UUID(me["id"]), me["kullanici_adi"], "po")
    _tok, raw = issue_token(session, p, "publish", 3600, auth_time=1_762_780_000, acr="2",
                            session_epoch_ms=EPOCH_MS)  # fmt: skip
    session.commit()
    aiprobe.ONBELLEK.temizle()
    assert verify_bearer(session, raw, "publish") is not None


def test_acr1_devrinde_po_rolu_gelmez(client: TestClient, home: SahteHome, engine: Engine) -> None:
    r = _giris(client, home, ["analyst", "po"], acr="1")
    assert r.status_code == 302 and r.headers["location"] == "/x"  # tek aday: analyst
    assert client.get("/auth/me").json()["rol"] == "analyst"
    with engine.connect() as c:
        assert c.execute(text("SELECT rol FROM app_user")).scalars().all() == ["analyst"]


def test_ayni_saniyedeki_iptal_oturumu_dusurur_sonraki_giris_gecer(
    client: TestClient, home: SahteHome, engine: Engine
) -> None:
    _giris(client, home, ["tester"])
    iptal_ms = EPOCH_MS + 400  # girişle aynı saniye, sonra
    home.kisiler[UID] = {
        "roles": ["tester"],
        "revoked_at_ms": iptal_ms,
        "valid_after": iptal_ms // 1000,
    }
    _kontrol_zamanini_eskit(engine)
    assert client.get("/auth/me").status_code == 401
    # Çıkıştan sonra aynı saniyede yeni giriş (E > R) geçer.
    r = _giris(client, home, ["tester"], session_epoch_ms=iptal_ms + 100)
    assert r.status_code == 302
    _kontrol_zamanini_eskit(engine)
    assert client.get("/auth/me").status_code == 200


def test_me_products_haritasi_devir_ve_kontrolden(
    client: TestClient, home: SahteHome, engine: Engine
) -> None:
    _giris(client, home, ["tester"])
    assert client.get("/auth/me").json()["products"] == {"tp": ["tester"], "ap": ["user"]}
    home.kisiler[UID] = {"roles": ["tester"], "diger": {"ap": ["admin"]}}
    _kontrol_zamanini_eskit(engine)
    assert client.get("/auth/me").json()["products"] == {"tp": ["tester"], "ap": ["admin"]}


def test_alembic_tek_bas() -> None:
    """Göç zinciri tek başlı. `feat/mobil-masaustu`'nun `0018_script_platform`'u (down_revision
    0017) bu dalla birleşince iki baş olur: `0019.down_revision = "0018"` yapın (tasks.md T051)."""
    from alembic.script import ScriptDirectory

    from tests.unit.conftest import alembic_config

    script = ScriptDirectory.from_config(alembic_config())
    bas = script.get_heads()
    assert bas == ["0019"], f"birden çok Alembic başı: {bas} — 0019'u yeniden ebeveynleyin (T051)"

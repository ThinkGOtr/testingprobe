"""HTTP API: giriş/oturum, roller, token'lar, denetim ucu, hata biçimi, router kaydı."""

from __future__ import annotations

import sys
import textwrap
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.api import main, registry
from tp_core.api.deps import DbSession, Principal, require_role, require_token
from tp_core.audit import append_audit
from tp_core.auth.login import THROTTLE
from tp_core.auth.passwords import hash_password
from tp_core.auth.sessions import COOKIE_NAME
from tp_core.auth.tokens import token_hash, verify_bearer
from tp_core.workflow.service import GateClosed

from .conftest import PAROLA, Db

MakeUser = Callable[..., Principal]


@pytest.fixture(autouse=True)
def _throttle_sifirla() -> Iterator[None]:
    THROTTLE._kayit.clear()
    yield
    THROTTLE._kayit.clear()


@pytest.fixture
def client(db: Db) -> Iterator[TestClient]:
    with TestClient(main.create_app()) as c:
        yield c


def _mcp_bagla(app: FastAPI) -> None:
    """MCP sunucusu yerine geçen sahte uç (POST /tokens yalnızca /mcp bağlıyken token üretir)."""

    @app.post("/mcp")
    def _mcp() -> dict:
        return {}


@pytest.fixture
def mcp_client(db: Db) -> Iterator[TestClient]:
    app = main.create_app()
    _mcp_bagla(app)
    with TestClient(app) as c:
        yield c


def _giris(client: TestClient, user: Principal, parola: str = PAROLA) -> None:
    r = client.post("/auth/login", json={"kullanici_adi": user.kullanici_adi, "parola": parola})
    assert r.status_code == 200, r.text


def _eylemler(engine: Engine) -> list[str]:
    with engine.connect() as c:
        return list(c.execute(text("SELECT eylem FROM audit_event ORDER BY id")).scalars())


# ------------------------------------------------------------------------ giriş


def test_giris_cerez_ve_me(client: TestClient, make_user: MakeUser, engine: Engine) -> None:
    u = make_user("analyst")
    r = client.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200
    govde = r.json()
    assert {k: govde[k] for k in ("id", "kullanici_adi", "rol")} == {
        "id": str(u.id),
        "kullanici_adi": u.kullanici_adi,
        "rol": "analyst",
    }
    # Eşlemede olmayan kullanıcı: kullanıcı adı · rol etiketi (yalnızca gösterim).
    assert govde["gorunen_ad"] == f"{u.kullanici_adi} · Analist"
    assert govde["ad_soyad"] is None
    cerez = r.headers["set-cookie"]
    assert cerez.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in cerez and "SameSite=lax" in cerez and "Path=/" in cerez
    assert client.get("/auth/me").json()["kullanici_adi"] == u.kullanici_adi
    assert _eylemler(engine) == ["auth.login"]


@pytest.mark.parametrize("ad_degistir", [False, True])
def test_hatali_giris_401_ve_denetlenir(
    client: TestClient, make_user: MakeUser, engine: Engine, ad_degistir: bool
) -> None:
    u = make_user("analyst")
    ad = "olmayan_kullanici" if ad_degistir else u.kullanici_adi
    r = client.post("/auth/login", json={"kullanici_adi": ad, "parola": "yanlis"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Kullanıcı adı veya parola hatalı", "kod": "yetkisiz"}
    assert "set-cookie" not in r.headers
    assert _eylemler(engine) == ["auth.login_failed"]  # yanıt 401 olsa da commit edildi


def test_giris_deneme_siniri(client: TestClient, make_user: MakeUser) -> None:
    u = make_user("analyst")
    for _ in range(5):
        client.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
    r = client.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 429


def test_baska_istemcinin_denemeleri_kullaniciyi_kilitlemez(db: Db, make_user: MakeUser) -> None:
    """Sınır (kullanıcı adı, istemci IP) çiftinedir: saldırgan adresi kurbanı kilitleyemez."""
    u = make_user("admin")
    app = main.create_app()
    with TestClient(app, client=("10.0.0.66", 5000)) as saldirgan:
        for _ in range(6):
            saldirgan.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
        r = saldirgan.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429
    with TestClient(app, client=("10.0.0.7", 5000)) as kurban:
        r = kurban.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200


PORTAL_IP = "172.21.0.8"  # review-portal nginx'in core-net adresi (canlı olaydaki)


@pytest.fixture
def portal_guvenilir(monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.config import get_settings

    monkeypatch.setenv("TP_TRUSTED_PROXIES", f"{PORTAL_IP}, 10.99.0.0/16")
    get_settings.cache_clear()


def _portal_istemcisi(app: FastAPI, gercek_ip: str, sahte_xff: str | None = None) -> TestClient:
    """review-portal nginx'i gibi: bağlantı portal IP'sinden; XFF = <istemcinin yolladığı>, <eş>."""
    xff = f"{sahte_xff}, {gercek_ip}" if sahte_xff else gercek_ip
    return TestClient(app, client=(PORTAL_IP, 40000), headers={"X-Forwarded-For": xff})


def test_portal_arkasinda_bir_istemcinin_denemeleri_digerini_kilitlemez(
    db: Db, make_user: MakeUser, engine: Engine, portal_guvenilir: None
) -> None:
    """Canlı olay: 5 hatalı deneme portal üzerinden (tek proxy IP'si) testci'yi herkes için 300 sn
    kilitliyordu. Artık güvenilen proxy'nin XFF'sindeki gerçek istemci sayılır."""
    u = make_user("tester")
    app = main.create_app()
    with _portal_istemcisi(app, "192.168.65.10") as saldirgan:
        yanlis = {"kullanici_adi": u.kullanici_adi, "parola": "x"}
        for _ in range(5):
            assert saldirgan.post("/auth/login", json=yanlis).status_code == 401
        r = saldirgan.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429
    with _portal_istemcisi(app, "192.168.65.20") as kurban:
        r = kurban.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
    with engine.connect() as c:
        istemciler = set(
            c.execute(
                text("SELECT ozet->>'istemci' FROM audit_event WHERE eylem = 'auth.login_failed'")
            ).scalars()
        )
    assert istemciler == {"192.168.65.10"}  # denetimde proxy IP'si değil gerçek istemci


def test_sahte_xff_soldaki_degerle_kilit_atlatilamaz(
    db: Db, make_user: MakeUser, portal_guvenilir: None
) -> None:
    """nginx `$proxy_add_x_forwarded_for` istemcinin XFF'sinin SONUNA eşi ekler; yalnızca en sağ
    öğe güvenilir. Saldırgan her denemede farklı sol değer yollayarak sayaçtan kaçamaz."""
    u = make_user("tester")
    app = main.create_app()
    for i in range(5):
        with _portal_istemcisi(app, "192.168.65.10", sahte_xff=f"1.2.3.{i}") as c:
            c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
    with _portal_istemcisi(app, "192.168.65.10", sahte_xff="9.9.9.9") as c:
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429


def test_dogrudan_baglantida_xff_yok_sayilir(
    db: Db, make_user: MakeUser, portal_guvenilir: None
) -> None:
    """Yayınlanmış 127.0.0.1:8000 portuna doğrudan gelen XFF'ye güvenilmez (TCP eşi sayılır)."""
    u = make_user("tester")
    app = main.create_app()
    for i in range(5):
        with TestClient(
            app, client=("172.21.0.1", 5000), headers={"X-Forwarded-For": f"10.1.1.{i}"}
        ) as c:
            c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
    with TestClient(app, client=("172.21.0.1", 5000), headers={"X-Forwarded-For": "8.8.8.8"}) as c:
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429


def test_guvenilen_proxy_cidr_ve_ad_cozumu(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    from tp_core.auth import client_ip
    from tp_core.config import get_settings

    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+psycopg://x@127.0.0.1:1/x")
    monkeypatch.setenv("TP_TRUSTED_PROXIES", "10.99.0.0/16, review-portal")
    get_settings.cache_clear()
    monkeypatch.setattr(client_ip, "_onbellek", {})
    monkeypatch.setattr(
        client_ip.socket,
        "getaddrinfo",
        lambda ad, _p: [(0, 0, 0, "", ("172.30.0.5", 0))] if ad == "review-portal" else [],
    )

    def istek(es: str, xff: str | None) -> Request:
        basliklar = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "client": (es, 1), "headers": basliklar})

    assert client_ip.client_address(istek("10.99.3.4", "5.5.5.5")) == "5.5.5.5"
    assert client_ip.client_address(istek("172.30.0.5", "a, 6.6.6.6")) == "6.6.6.6"
    assert client_ip.client_address(istek("172.30.0.6", "6.6.6.6")) == "172.30.0.6"
    assert client_ip.client_address(istek("172.30.0.5", "bozuk-deger")) == "172.30.0.5"
    assert client_ip.client_address(istek("172.30.0.5", None)) == "172.30.0.5"
    get_settings.cache_clear()


def test_taninan_cihaz_ayni_ipdeki_saldirgandan_etkilenmez(
    db: Db, make_user: MakeUser, portal_guvenilir: None
) -> None:
    """Yerel demoda tüm tarayıcılar aynı adresten gelir (Docker ağ geçidi). Kullanıcı daha önce bu
    tarayıcıdan giriş yaptıysa imzalı `tp_cihaz` çerezi sayacını ayırır: aynı IP'deki biri yanlış
    parolalarla onu kilitleyemez. Başkasının adına verilmiş cihaz çerezi işe yaramaz."""
    from tp_core.auth.sessions import DEVICE_COOKIE_NAME

    u = make_user("po")
    app = main.create_app()
    ortak_ip = "192.168.65.1"
    with _portal_istemcisi(app, ortak_ip) as kurban:
        r = kurban.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        cihaz = kurban.cookies.get(DEVICE_COOKIE_NAME)
        assert cihaz
        cerezler = r.headers.get_list("set-cookie")
        cihaz_cerezi = next(c for c in cerezler if c.startswith(f"{DEVICE_COOKIE_NAME}="))
        assert "HttpOnly" in cihaz_cerezi and "SameSite=strict" in cihaz_cerezi
        kurban.post("/auth/logout")
    with _portal_istemcisi(app, ortak_ip) as saldirgan:
        for _ in range(6):
            saldirgan.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
        r = saldirgan.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429  # cihazsız istemci aynı IP'de kilitli
    with _portal_istemcisi(app, ortak_ip) as kurban:
        kurban.cookies.set(DEVICE_COOKIE_NAME, cihaz)
        r = kurban.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        assert any(c.startswith(DEVICE_COOKIE_NAME) for c in r.headers.get_list("set-cookie"))
    baska = make_user("analyst")
    with _portal_istemcisi(app, ortak_ip) as c:
        # Kendi cihaz çerezini başka kullanıcı için kullanan, o kullanıcının IP kovasına düşer.
        for _ in range(5):
            c.post("/auth/login", json={"kullanici_adi": baska.kullanici_adi, "parola": "x"})
        c.cookies.set(DEVICE_COOKIE_NAME, cihaz)
        r = c.post("/auth/login", json={"kullanici_adi": baska.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429
        c.cookies.set(DEVICE_COOKIE_NAME, cihaz[:-3] + "xyz")  # imzası bozuk
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
        assert r.status_code == 429  # bozuk çerez → IP kovası (zaten kilitli)


def test_cihazli_istemci_de_kaba_kuvvete_kilitlenir(
    db: Db, make_user: MakeUser, portal_guvenilir: None
) -> None:
    from tp_core.auth.sessions import DEVICE_COOKIE_NAME

    u = make_user("po")
    app = main.create_app()
    with _portal_istemcisi(app, "192.168.65.1") as c:
        _giris(c, u)
        assert c.cookies.get(DEVICE_COOKIE_NAME)
        for _ in range(5):
            c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "x"})
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 429


def test_basarisiz_giris_aktoru_cagirandan_gelmez(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """Kimliği doğrulanmamış çağıran denetim kaydının aktör kolonunu belirleyemez."""
    u = make_user("analyst")
    client.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "yanlis"})
    client.post("/auth/login", json={"kullanici_adi": "sistem yöneticisi", "parola": "x"})
    with engine.connect() as c:
        satirlar = c.execute(text("SELECT aktor, eylem, ozet FROM audit_event ORDER BY id")).all()
    assert [(a, e) for a, e, _ in satirlar] == [("anonim", "auth.login_failed")] * 2
    assert satirlar[0].ozet["denenen_kullanici"] == u.kullanici_adi
    assert satirlar[1].ozet["denenen_kullanici"] == "sistem yöneticisi"
    assert satirlar[0].ozet["istemci"] == "testclient"


def test_oturumsuz_ve_bozuk_cerez(client: TestClient, make_user: MakeUser) -> None:
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me").json() == {
        "detail": "Oturum açmanız gerekiyor",
        "kod": "yetkisiz",
    }
    _giris(client, make_user("po"))
    gecerli = client.cookies[COOKIE_NAME]
    assert client.get("/auth/me").status_code == 200
    yuk, zaman, imza = gecerli.rsplit(".", 2)
    for bozuk in (
        f"{yuk}.{zaman}.{'A' * len(imza)}",  # imza değişti
        f"{yuk[:-2]}xx.{zaman}.{imza}",  # yük değişti
        "rastgele",
    ):
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, bozuk)
        assert client.get("/auth/me").status_code == 401, bozuk


def test_parola_degisince_oturum_duser(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user("tester")
    _giris(client, u)
    with engine.begin() as c:
        c.execute(
            text("UPDATE app_user SET parola_hash = :h WHERE id = :i"),
            {"h": hash_password("Yeni-Parola-1"), "i": u.id},
        )
    assert client.get("/auth/me").status_code == 401


def test_cikis(client: TestClient, make_user: MakeUser, engine: Engine) -> None:
    _giris(client, make_user("engineer"))
    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert f'{COOKIE_NAME}=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert client.get("/auth/me").status_code == 401
    assert _eylemler(engine) == ["auth.login", "auth.logout"]


def test_cikistan_sonra_kopyalanan_cerez_gecersiz(
    db: Db, client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """Çıkış sunucu tarafında oturumu iptal eder: çıkıştan önce kopyalanan çerez işe yaramaz."""
    u = make_user("analyst")
    _giris(client, u)
    kopya = client.cookies[COOKIE_NAME]
    # İkinci tarayıcı (aynı kullanıcı, ayrı oturum) çıkıştan etkilenmez.
    with TestClient(main.create_app()) as diger:
        _giris(diger, u)
        assert client.post("/auth/logout").json() == {"ok": True}
        assert diger.get("/auth/me").status_code == 200
    with TestClient(main.create_app()) as saldirgan:
        saldirgan.cookies.set(COOKIE_NAME, kopya)
        assert saldirgan.get("/auth/me").status_code == 401
        # Kopyayla tekrar çıkış yeni bir 'auth.logout' kaydı üretmez.
        assert saldirgan.post("/auth/logout").status_code == 200
    with engine.connect() as c:
        satirlar = c.execute(
            text("SELECT iptal_zamani IS NOT NULL FROM oturum ORDER BY olusturma")
        ).scalars()
        assert list(satirlar) == [True, False]
    assert _eylemler(engine) == ["auth.login", "auth.login", "auth.logout"]


def test_suresi_dolan_oturum_reddedilir_ve_temizlenir(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user("po")
    _giris(client, u)
    with engine.begin() as c:
        c.execute(text("UPDATE oturum SET son_kullanma = now() - interval '1 second'"))
    assert client.get("/auth/me").status_code == 401
    _giris(client, u)  # yeni giriş süresi dolmuş satırı siler
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM oturum")).scalar_one() == 1
    assert client.get("/auth/me").status_code == 200


def test_sid_olmayan_eski_cerez_reddedilir(client: TestClient, make_user: MakeUser) -> None:
    from itsdangerous import URLSafeTimedSerializer

    from tp_core.auth.sessions import password_fingerprint

    from .conftest import SESSION_SECRET

    u = make_user("analyst")
    eski = URLSafeTimedSerializer(SESSION_SECRET, salt="tp-session-v1").dumps(
        {"uid": str(u.id), "pv": password_fingerprint(hash_password(PAROLA))}
    )
    client.cookies.set(COOKIE_NAME, eski)
    assert client.get("/auth/me").status_code == 401


def test_oturum_sirri_yoksa_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.config import get_settings

    monkeypatch.delenv("TP_SESSION_SECRET")
    get_settings.cache_clear()
    r = client.post("/auth/login", json={"kullanici_adi": "a", "parola": "b"})
    assert r.status_code == 503


def test_dogrulama_hatasi_tek_metin(client: TestClient) -> None:
    r = client.post("/auth/login", json={"kullanici_adi": ""})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert "kullanici_adi" in r.json()["detail"] and "parola" in r.json()["detail"]


# ---------------------------------------------------------------------- token'lar


def test_mcp_ucu_yokken_token_uretilmez(
    db: Db, make_user: MakeUser, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Özellik router'ları (ve onlarla gelen /mcp) olmadan kurulan uygulama.
    monkeypatch.setattr(registry, "discover_feature_routers", lambda *a, **k: [])
    with TestClient(main.create_app()) as client:
        _giris(client, make_user("tester"))
        r = client.post("/tokens", json={"kapsam": "submit"})
    assert r.status_code == 501
    assert "MCP" in r.json()["detail"]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM api_token")).scalar_one() == 0


def test_parola_degisince_token_gecersiz(
    mcp_client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user("tester")
    _giris(mcp_client, u)
    raw = mcp_client.post("/tokens", json={"kapsam": "submit"}).json()["token"]
    with Session(engine) as s:
        assert verify_bearer(s, raw, "submit") is not None
        s.commit()
    with engine.begin() as c:
        c.execute(
            text("UPDATE app_user SET parola_hash = :h WHERE id = :i"),
            {"h": hash_password("Yeni-Parola-1"), "i": u.id},
        )
    with Session(engine) as s:
        assert verify_bearer(s, raw, "submit") is None


def test_token_uret_listele_iptal(
    mcp_client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    client = mcp_client
    u = make_user("tester")
    _giris(client, u)
    r = client.post("/tokens", json={"kapsam": "submit"})
    assert r.status_code == 201
    tok = r.json()
    assert tok["token"].startswith("tpt_") and tok["kapsam"] == "submit"
    assert tok["mcp_url"].endswith("/mcp")
    sure = datetime.fromisoformat(tok["son_kullanma"]) - datetime.now(UTC)
    assert timedelta(hours=7, minutes=59) < sure <= timedelta(hours=8)
    with engine.connect() as c:
        saklanan = c.execute(text("SELECT token_hash FROM api_token")).scalar_one()
    assert saklanan == token_hash(tok["token"]) and tok["token"] not in saklanan
    liste = client.get("/tokens").json()
    assert [t["id"] for t in liste] == [tok["id"]] and "token" not in liste[0]

    with Session(engine) as s:
        p = verify_bearer(s, tok["token"], "submit")
        assert p is not None and (p.kanal, p.kapsam, p.id) == ("ide", "submit", u.id)
        assert verify_bearer(s, tok["token"], "publish") is None
        assert verify_bearer(s, "tpt_uydurma", "submit") is None
        assert verify_bearer(s, None, "submit") is None
        s.commit()

    assert client.delete(f"/tokens/{tok['id']}").status_code == 204
    assert client.delete(f"/tokens/{tok['id']}").status_code == 404
    with Session(engine) as s:
        assert verify_bearer(s, tok["token"], "submit") is None
    assert _eylemler(engine) == ["auth.login", "token.issued", "token.revoked"]


def test_suresi_dolan_token_gecersiz(
    mcp_client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    client = mcp_client
    _giris(client, make_user("tester"))
    raw = client.post("/tokens", json={"kapsam": "publish"}).json()["token"]
    with engine.begin() as c:
        c.execute(text("UPDATE api_token SET son_kullanma = now() - interval '1 second'"))
    with Session(engine) as s:
        assert verify_bearer(s, raw, "publish") is None


@pytest.mark.parametrize("rol", ["engineer", "admin", "po", "analyst"])
def test_token_yalnizca_testci(
    client: TestClient, make_user: MakeUser, engine: Engine, rol: str
) -> None:
    """012: IDE token'ı Testçi ve Developer'ındır (`token.issue`, 2026-11-14); red `authz.denied`
    yazar."""
    _giris(client, make_user(rol))
    r = client.post("/tokens", json={"kapsam": "submit"})
    assert r.status_code == 403 and r.json() == {
        "detail": "Bu işlem için yetkiniz yok",
        "kod": "yetki_yok",
    }
    with engine.connect() as c:
        ozet = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'authz.denied'")
        ).scalar_one()
    assert ozet["izin"] == "token.issue" and ozet["rol"] == rol


def test_developer_kendi_submit_tokenini_uretir_publish_uretemez(
    mcp_client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """2026-11-14: Developer IDE kanalını kullanır (`token.issue`); `publish` kapsamı
    `case.publish` ister (Testçi). Başkasının token'ını göremez ve iptal edemez."""
    client = mcp_client
    testci = make_user("tester")
    _giris(client, testci)
    testci_tok = client.post("/tokens", json={"kapsam": "submit"}).json()
    client.post("/auth/logout")
    client.cookies.clear()

    _giris(client, make_user("developer"))
    r = client.post("/tokens", json={"kapsam": "submit"})
    assert r.status_code == 201 and r.json()["kapsam"] == "submit"
    r = client.post("/tokens", json={"kapsam": "publish"})
    assert r.status_code == 403 and r.json()["kod"] == "yetki_yok"
    with engine.connect() as c:
        ozet = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'authz.denied'")
        ).scalar_one()
    assert ozet["izin"] == "case.publish" and ozet["rol"] == "developer"
    assert [t["kapsam"] for t in client.get("/tokens").json()] == ["submit"]
    assert client.delete(f"/tokens/{testci_tok['id']}").status_code == 404
    with Session(engine) as s:
        assert verify_bearer(s, testci_tok["token"], "submit") is not None
        s.commit()


def test_gecersiz_kapsam(client: TestClient, make_user: MakeUser) -> None:
    _giris(client, make_user("tester"))
    assert client.post("/tokens", json={"kapsam": "admin"}).status_code == 422


def test_bearer_bagimliligi(db: Db, make_user: MakeUser, engine: Engine) -> None:
    app = FastAPI()
    router = APIRouter()

    @router.post("/mcp-test")
    def uc(p: Principal = Depends(require_token("publish"))) -> dict:  # noqa: B008
        return {"kanal": p.kanal, "kapsam": p.kapsam}

    app.include_router(router)
    u = make_user("tester")
    from tp_core.auth.tokens import issue_token

    with Session(engine) as s:
        _, raw = issue_token(s, u, "publish", 60)
        s.commit()
    with TestClient(app) as c:
        assert c.post("/mcp-test").status_code == 401
        assert c.post("/mcp-test", headers={"Authorization": "Basic x"}).status_code == 401
        r = c.post("/mcp-test", headers={"Authorization": f"Bearer {raw}"})
        assert r.json() == {"kanal": "ide", "kapsam": "publish"}
    with engine.connect() as c:
        assert c.execute(text("SELECT son_kullanim IS NOT NULL FROM api_token")).scalar_one()


# ------------------------------------------------------------------------ denetim


def test_audit_dogrulama_ai_call_kurcalamasini_gosterir(
    client: TestClient, make_user: MakeUser, engine: Engine, db: Db
) -> None:
    from tp_core.audit import PgCallRecorder

    _giris(client, make_user("admin"))
    cid = PgCallRecorder(engine).record_ai_call(
        {"amac": "generate_cases", "saglayici": "anthropic", "model": "m", "mod": "live",
         "maliyet": 0.0123, "cikti": {"b": 1, "a": [1.5]}}
    )  # fmt: skip
    body = client.get("/audit", params={"verify": "true"}).json()["verify"]
    assert body["ok"] is True
    assert body["anchors"] == {"ok": True, "checked": 1, "eski": 0, "sabitsiz": 0, "broken": []}
    with db.srv.super_conn(db.name) as c:
        c.execute("SET session_replication_role = replica")
        c.execute("UPDATE ai_call SET maliyet = 0 WHERE id = %s", (cid,))
    body = client.get("/audit", params={"verify": "true"}).json()["verify"]
    assert body["ok"] is False and "çapa" in body["reason"]
    assert body["anchors"]["broken"] == [
        {"nesne": f"ai_call:{cid}", "reason": "satır içeriği çapayla uyuşmuyor (değiştirilmiş)"}
    ]
    assert body["broken_at"] is None  # zincirin kendisi sağlam


def test_audit_dogrulama_ve_sayfalama(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    assert client.get("/audit").status_code == 401
    _giris(client, make_user("admin"))
    with engine.begin() as c:
        for i in range(5):
            append_audit(c, "system", "x.y", f"n:{i % 2}", {"i": i})
    r = client.get("/audit", params={"verify": "true", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["verify"]["ok"] is True and body["verify"]["count"] == 6
    assert body["tip_hash"] == body["events"][0]["hash"] == body["verify"]["tip_hash"]
    assert [e["eylem"] for e in body["events"]] == ["x.y", "x.y", "x.y"]
    sonraki = client.get("/audit", params={"limit": 3, "before_id": body["next_before_id"]}).json()
    assert sonraki["verify"] is None
    assert [e["eylem"] for e in sonraki["events"]] == ["x.y", "x.y", "auth.login"]
    assert sonraki["next_before_id"] is not None
    filtre = client.get("/audit", params={"nesne": "n:1"}).json()["events"]
    assert [e["ozet"]["i"] for e in filtre] == [3, 1]
    assert client.get("/audit", params={"limit": 0}).status_code == 422


def test_audit_ozetinde_sid_kisaltilir_zincir_gecerli_kalir(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """Canlı: Denetçi auth.login / auth.role_switch özetinde tam oturum kimliğini görüyordu."""
    sid = str(uuid.uuid4())
    with engine.begin() as c:
        append_audit(c, "system", "auth.role_switch", "app_user:x", {"sid": sid, "onceki": "a"})
    _giris(client, make_user("auditor"))
    body = client.get("/audit", params={"verify": "true"}).json()
    ozetler = [
        e["ozet"] for e in body["events"] if e["eylem"] in ("auth.role_switch", "auth.login")
    ]
    assert ozetler and all(sid not in str(o) for o in ozetler)
    assert any(o.get("sid") == f"{sid[:8]}…" for o in ozetler)
    assert body["verify"]["ok"] is True  # yalnız gösterim: kayıt değişmedi


def test_audit_kurcalama_api_da_gorunur(client: TestClient, make_user: MakeUser, db: Db) -> None:
    _giris(client, make_user("auditor"))
    with db.srv.super_conn(db.name) as c:
        c.execute("SET session_replication_role = replica")
        c.execute("UPDATE audit_event SET ozet = '{\"x\": 1}'")
    v = client.get("/audit", params={"verify": "true"}).json()["verify"]
    assert v["ok"] is False and v["broken_at"] is not None


# ---------------------------------------------------------- hata biçimi ve registry


def test_is_akisi_hatasi_409_detail(db: Db) -> None:
    app = main.create_app()
    r = APIRouter()

    @r.get("/patlat")
    def patlat() -> None:
        raise GateClosed("onay yok")

    app.include_router(r)
    with TestClient(app) as c:
        resp = c.get("/patlat")
    assert resp.status_code == 409 and resp.json() == {"detail": "onay yok", "kod": "kapi_kapali"}


def test_ozellik_router_kesfi_ve_cakisma(tmp_path: Path, db: Db) -> None:
    paket = f"tp_fake_api_{uuid.uuid4().hex[:6]}"
    (tmp_path / paket / "ornek").mkdir(parents=True)
    (tmp_path / paket / "__init__.py").write_text("")
    (tmp_path / paket / "ornek" / "__init__.py").write_text("")
    (tmp_path / paket / "ornek" / "api.py").write_text(
        textwrap.dedent(
            """
            from fastapi import APIRouter, Depends
            from tp_core.api.deps import require_role

            router = APIRouter()

            @router.get("/ornek", dependencies=[Depends(require_role("analyst"))])
            def ornek():
                return {"ok": True}
            """
        )
    )
    sys.path.insert(0, str(tmp_path))
    try:
        app = FastAPI()
        adlar = registry.mount_all(app, [], package=paket)
        assert adlar == [f"{paket}.ornek.api"]
        with TestClient(app) as c:
            assert c.get("/ornek").status_code == 401
        app2 = FastAPI()
        with pytest.raises(RuntimeError, match="çakışan uç"):
            registry.mount_all(app2, [registry.discover_feature_routers(paket)[0][1]], paket)
    finally:
        sys.path.remove(str(tmp_path))


def test_require_role_bos_olamaz() -> None:
    with pytest.raises(ValueError):
        require_role()


def test_db_session_istisnada_geri_alir(db: Db, engine: Engine) -> None:
    app = FastAPI()

    @app.post("/yaz-ve-patla")
    def yaz(session: DbSession) -> None:
        append_audit(session.connection(), "t", "geri.alinmali")
        raise RuntimeError("patladı")

    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.post("/yaz-ve-patla").status_code == 500
    assert _eylemler(engine) == []


def test_platform_uclari_kayitli() -> None:
    yollar = {(m, p) for m, p, _ in registry.route_table(main.app)}
    for beklenen in [
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("GET", "/auth/me"),
        ("GET", "/audit"),
        ("GET", "/events"),
        ("POST", "/tokens"),
        ("GET", "/tokens"),
        ("DELETE", "/tokens/{token_id}"),
    ]:
        assert beklenen in yollar


def test_ozellik_router_icindeki_mcp_ucu_gorunur(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """`/mcp` bir özellik router'ı içinden (include_router sarmalayıcısında) bağlanır; görülmeli."""
    _giris(client, make_user("tester"))
    r = client.post("/tokens", json={"kapsam": "submit"})
    assert r.status_code == 201, r.text
    assert r.json()["mcp_url"].endswith("/mcp")


# ------------------------------------------------------------------ görünen adlar


def test_me_gorunen_ad_ve_kisi_eslemesi(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.config import get_settings

    analist = make_user("analyst", ad="analist")
    make_user("admin", ad="sunucu")
    make_user("tester", ad="testci")
    _giris(client, analist)
    me = client.get("/auth/me").json()
    assert me["rol"] == "analyst"
    assert me["gorunen_ad"] == "Cengizhan Gunaydin · Analist"
    assert me["ad_soyad"] == "Cengizhan Gunaydin"
    assert me["kisiler"]["sunucu"] == "Sistem Yöneticisi"
    assert me["kisiler"]["testci"] == "Fatih Arslan · Testçi"

    # TP_GORUNEN_ADLAR demo varsayılanlarını geçersiz kılar; rol değişmez.
    monkeypatch.setenv("TP_GORUNEN_ADLAR", "analist=Ayşe  Yılmaz,testci=")
    get_settings.cache_clear()
    try:
        me = client.get("/auth/me").json()
    finally:
        monkeypatch.delenv("TP_GORUNEN_ADLAR")
        get_settings.cache_clear()
    assert me["gorunen_ad"] == "Ayşe Yılmaz · Analist" and me["rol"] == "analyst"
    assert me["kisiler"]["testci"] == "Testçi"


def test_yetki_ada_degil_role_bakar(client: TestClient, make_user: MakeUser) -> None:
    """Görünen ad yalnızca gösterimdir: "po" adlı bir analistin rolü analist kalır."""
    from tp_core.auth.display import display_name

    assert display_name("po", "analyst", {"po": "Cengizhan Gunaydin"}) == (
        "Cengizhan Gunaydin · Analist"
    )
    u = make_user("analyst", ad="po")
    _giris(client, u)
    assert client.get("/auth/me").json()["rol"] == "analyst"

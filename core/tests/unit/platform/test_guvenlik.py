"""Güvenlik: giriş deneme sınırının atomikliği ve bellek sınırı; CSRF (Origin) savunması."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tp_core.api import main
from tp_core.api.csrf import istek_kabul_mu, parse_origins
from tp_core.auth.login import MAX_DENEME, THROTTLE, LoginThrottle
from tp_core.config import get_settings
from tp_core.workflow.service import Principal

from .conftest import PAROLA, Db

MakeUser = Callable[..., Principal]


@pytest.fixture(autouse=True)
def _throttle_sifirla() -> Iterator[None]:
    THROTTLE._kayit.clear()
    yield
    THROTTLE._kayit.clear()


# ------------------------------------------------------------------ deneme sınırı (birim)


def test_try_acquire_esz_amanli_en_fazla_max_deneme_verir() -> None:
    t = LoginThrottle(max_deneme=5, pencere_s=60)
    bariyer = threading.Barrier(40)
    sonuclar: list[bool] = []
    kilit = threading.Lock()

    def dene() -> None:
        bariyer.wait()
        ok = t.try_acquire("kurban|ip:1.2.3.4")
        with kilit:
            sonuclar.append(ok)

    with ThreadPoolExecutor(40) as ex:
        for _ in range(40):
            ex.submit(dene)
    assert sonuclar.count(True) == 5
    assert t.blocked("kurban|ip:1.2.3.4")


def test_basari_anahtari_temizler_ve_pencere_dolunca_hak_geri_gelir() -> None:
    zaman = [1000.0]
    t = LoginThrottle(max_deneme=2, pencere_s=10)
    import tp_core.auth.login as login_mod

    orijinal = login_mod.time.monotonic
    login_mod.time.monotonic = lambda: zaman[0]  # type: ignore[assignment]
    try:
        assert t.try_acquire("a") and t.try_acquire("a")
        assert not t.try_acquire("a")
        zaman[0] += 11
        assert t.try_acquire("a")  # eski kayıtlar pencereden çıktı
        t.success("a")
        assert "a" not in t._kayit
    finally:
        login_mod.time.monotonic = orijinal  # type: ignore[assignment]


def test_blocked_kayit_olusturmaz_ve_bos_kuyruklar_silinir() -> None:
    zaman = [0.0]
    import tp_core.auth.login as login_mod

    orijinal = login_mod.time.monotonic
    login_mod.time.monotonic = lambda: zaman[0]  # type: ignore[assignment]
    try:
        t = LoginThrottle(max_deneme=3, pencere_s=5)
        for i in range(1000):
            assert not t.blocked(f"saldirgan-{i}|ip:9.9.9.9")
        assert t._kayit == {}
        t.try_acquire("x")
        zaman[0] += 6
        assert not t.blocked("x")
        assert t._kayit == {}  # süresi dolan kuyruk silindi
    finally:
        login_mod.time.monotonic = orijinal  # type: ignore[assignment]


def test_anahtar_sayisi_sinirli() -> None:
    t = LoginThrottle(max_deneme=3, pencere_s=300, max_anahtar=100)
    for i in range(1000):
        assert t.try_acquire(f"ad-{i}|ip:9.9.9.9")
    assert len(t._kayit) <= 100
    assert "ad-999|ip:9.9.9.9" in t._kayit  # en yeniler tutulur


# ------------------------------------------------------------------ deneme sınırı (gerçek sunucu)


def test_paralel_yanlis_parolalar_en_fazla_max_deneme_kez_dogrulanir(
    sunucu: str, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user("analyst")

    def dene(_i: int) -> int:
        with httpx.Client(base_url=sunucu, timeout=30) as c:
            return c.post(
                "/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": "yanlis-parola"}
            ).status_code

    with ThreadPoolExecutor(20) as ex:
        kodlar = list(ex.map(dene, range(20)))
    assert kodlar.count(401) <= MAX_DENEME
    assert kodlar.count(401) + kodlar.count(429) == 20
    with engine.connect() as c:
        basarisiz = c.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'auth.login_failed'")
        ).scalar_one()
    assert basarisiz <= MAX_DENEME  # yalnızca ayrılan denemeler doğrulandı ve denetlendi
    # Kilitliyken doğru parola da 429 alır (sayaç yarışta atlatılamadı).
    with httpx.Client(base_url=sunucu, timeout=30) as c:
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 429


# ------------------------------------------------------------------ CSRF / Origin


IZINLI = parse_origins("http://127.0.0.1:8080, http://localhost:8080/")


@pytest.mark.parametrize(
    ("method", "fetch_site", "origin", "beklenen"),
    [
        ("GET", "cross-site", "http://kotu.example", True),  # güvenli yöntem
        ("POST", "same-origin", None, True),
        ("POST", "none", None, True),
        ("POST", "same-site", "http://127.0.0.1:8081", False),  # demo uygulaması
        ("POST", "cross-site", "http://kotu.example", False),
        ("DELETE", "same-site", None, False),
        ("POST", None, "http://127.0.0.1:8080", True),
        ("POST", None, "http://LOCALHOST:8080", True),
        ("PATCH", None, "http://127.0.0.1:8081", False),
        ("PUT", None, "null", False),
        ("POST", None, None, True),  # tarayıcı dışı istemci (curl, MCP bearer)
    ],
)
def test_istek_kabul_kurali(
    method: str, fetch_site: str | None, origin: str | None, beklenen: bool
) -> None:
    assert istek_kabul_mu(method, fetch_site, origin, IZINLI) is beklenen


def _giris(c: TestClient, ad: str) -> None:
    assert c.post("/auth/login", json={"kullanici_adi": ad, "parola": PAROLA}).status_code == 200


def test_yabanci_origin_govdesiz_post_reddedilir(db: Db, make_user: MakeUser) -> None:
    u = make_user("analyst")
    with TestClient(main.create_app()) as c:
        _giris(c, u.kullanici_adi)
        r = c.post("/auth/logout", headers={"Origin": "http://127.0.0.1:8081"})
        assert r.status_code == 403
        assert r.json() == {
            "detail": "İstek başka bir kaynaktan geldi; işlem reddedildi",
            "kod": "kaynak_reddi",
        }
        r = c.post(
            "/auth/logout",
            headers={"Sec-Fetch-Site": "same-site", "Origin": "http://127.0.0.1:8081"},
        )
        assert r.status_code == 403
        assert c.get("/auth/me").status_code == 200  # oturum hâlâ açık
        # Portalın kendi isteği geçer.
        r = c.post(
            "/auth/logout",
            headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://127.0.0.1:8080"},
        )
        assert r.status_code == 200
        assert c.get("/auth/me").status_code == 401


def test_yabanci_origin_giris_csrf_reddedilir(db: Db, make_user: MakeUser) -> None:
    u = make_user("analyst")
    with TestClient(main.create_app()) as c:
        r = c.post(
            "/auth/login",
            json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA},
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://kotu.example"},
        )
        assert r.status_code == 403
        assert "tp_session" not in c.cookies


def test_izinli_origin_listesi_ortamdan_okunur(
    db: Db, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_ALLOWED_ORIGINS", "http://portal.yerel:9000")
    get_settings.cache_clear()
    u = make_user("analyst")
    with TestClient(main.create_app()) as c:
        r = c.post(
            "/auth/login",
            json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA},
            headers={"Origin": "http://portal.yerel:9000"},
        )
        assert r.status_code == 200
        r = c.post("/auth/logout", headers={"Origin": "http://127.0.0.1:8080"})
        assert r.status_code == 403  # varsayılan liste artık geçerli değil


def test_get_ve_sse_origin_kontrolunden_etkilenmez(db: Db, make_user: MakeUser) -> None:
    u = make_user("analyst")
    with TestClient(main.create_app()) as c:
        _giris(c, u.kullanici_adi)
        r = c.get("/auth/me", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 200

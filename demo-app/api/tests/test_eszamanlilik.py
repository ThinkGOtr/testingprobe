"""Eşzamanlı sepet/sipariş istekleri: gerçek bir uvicorn sunucusuna paralel HTTP istekleri.

SQLite (BEGIN IMMEDIATE ile zaten sıralı) her zaman çalışır; asıl kanıt Postgres'tir
(`DEMOAPP_TEST_PG_URL` tanımlıysa). Kilit olmadan Postgres'te tek sepetten birden çok sipariş
oluşuyor, sepete paralel eklemede UniqueViolation (500) ve kayıp güncelleme görülüyordu.
"""

import contextlib
import os
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn

from demoapp_api import db, main
from demoapp_api.main import app

PG_URL = os.environ.get("DEMOAPP_TEST_PG_URL")
TOKEN = "eszamanli-test-tokeni"
PARALEL = 12
# Yarış penceresini genişletir: sepet ve satırları okunduktan sonra, yazmadan önce beklenir.
# Yerelde istekler o kadar hızlı biter ki kilitsiz kod da çoğu zaman şans eseri geçer.
GECIKME_SN = 0.05


def _bos_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def _sunucu(monkeypatch, url: str) -> Iterator[str]:
    monkeypatch.setenv("DEMOAPP_DATABASE_URL", url)
    monkeypatch.setenv("DEMOAPP_TEST_MODE", "1")
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", TOKEN)
    db.clear_caches()
    port = _bos_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn başlamadı"
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    try:
        r = httpx.post(f"{base}/test/reset", headers={"X-Demoapp-Test-Token": TOKEN})
        assert r.status_code == 200, r.text
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        db.get_engine().dispose()
        db.clear_caches()


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(not PG_URL, reason="DEMOAPP_TEST_PG_URL tanımlı değil"),
            ],
        ),
    ]
)
def sunucu(request, monkeypatch, tmp_path) -> Iterator[str]:
    asil_sepet_al = main.sepet_al

    def yavas_sepet_al(s, bayi, olustur=True):
        sepet = asil_sepet_al(s, bayi, olustur)
        if sepet is not None:
            list(sepet.satirlar)
        time.sleep(GECIKME_SN)
        return sepet

    monkeypatch.setattr(main, "sepet_al", yavas_sepet_al)
    url = f"sqlite:///{tmp_path / 'eszamanli.db'}" if request.param == "sqlite" else PG_URL
    assert url
    with _sunucu(monkeypatch, url) as base:
        yield base


def _oturum(base: str, kullanici: str = "bayi2") -> str:
    r = httpx.post(f"{base}/auth/login", json={"kullanici_adi": kullanici, "parola": "Demo123!"})
    assert r.status_code == 200, r.text
    return r.cookies["bayi_oturum"]


def _paralel(n: int, fn) -> list[httpx.Response]:
    barrier = threading.Barrier(n)

    def calis(_i: int) -> httpx.Response:
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(calis, range(n)))


def test_paralel_siparis_tek_sepetten_tek_siparis(sunucu):
    cerez = {"bayi_oturum": _oturum(sunucu)}
    r = httpx.post(f"{sunucu}/cart/lines", json={"urun_kod": "P-002", "adet": 50}, cookies=cerez)
    assert r.status_code == 200 and r.json()["onaylanabilir"], r.text

    sonuclar = _paralel(PARALEL, lambda: httpx.post(f"{sunucu}/orders", cookies=cerez, timeout=60))

    kodlar = sorted(x.status_code for x in sonuclar)
    assert kodlar == [201] + [422] * (PARALEL - 1), kodlar
    assert all(x.json()["detail"] == "Sepetiniz boş" for x in sonuclar if x.status_code == 422)
    siparisler = httpx.get(f"{sunucu}/orders", cookies=cerez).json()
    assert len(siparisler) == 1
    assert siparisler[0]["toplam"] == "750.00"
    assert httpx.get(f"{sunucu}/cart", cookies=cerez).json()["satirlar"] == []


def test_paralel_sepete_ekleme_kayipsiz(sunucu):
    """Sepet satırı da sepet de yokken aynı ürünü paralel ekleme: 500 yok, adet kaybı yok."""
    cerez = {"bayi_oturum": _oturum(sunucu)}

    sonuclar = _paralel(
        PARALEL,
        lambda: httpx.post(
            f"{sunucu}/cart/lines",
            json={"urun_kod": "P-003", "adet": 1},
            cookies=cerez,
            timeout=60,
        ),
    )

    assert [x.status_code for x in sonuclar] == [200] * PARALEL, [
        (x.status_code, x.text[:200]) for x in sonuclar
    ]
    sepet = httpx.get(f"{sunucu}/cart", cookies=cerez).json()
    assert [(x["urun_kod"], x["adet"]) for x in sepet["satirlar"]] == [("P-003", PARALEL)]


def test_paralel_farkli_urunler_bos_sepete(sunucu):
    """Sepet kaydı yokken farklı ürünler: sepet bir kez oluşur, her ürün tek satır."""
    cerez = {"bayi_oturum": _oturum(sunucu)}
    kodlar = ["P-001", "P-002", "P-003", "P-004"] * 3

    sayac = iter(range(len(kodlar)))
    kilit = threading.Lock()

    def ekle() -> httpx.Response:
        with kilit:
            kod = kodlar[next(sayac)]
        return httpx.post(
            f"{sunucu}/cart/lines", json={"urun_kod": kod, "adet": 2}, cookies=cerez, timeout=60
        )

    sonuclar = _paralel(len(kodlar), ekle)

    assert all(x.status_code == 200 for x in sonuclar), [
        (x.status_code, x.text[:200]) for x in sonuclar
    ]
    sepet = httpx.get(f"{sunucu}/cart", cookies=cerez).json()
    assert sorted((x["urun_kod"], x["adet"]) for x in sepet["satirlar"]) == [
        ("P-001", 6),
        ("P-002", 6),
        ("P-003", 6),
        ("P-004", 6),
    ]


def test_paralel_ekleme_ust_siniri_asmaz(sunucu):
    """Sınıra yakın satıra paralel ekleme: toplam asla MAX_ADET'i geçmez, fazlası 422 alır."""
    cerez = {"bayi_oturum": _oturum(sunucu)}
    r = httpx.put(f"{sunucu}/cart/lines/P-001", json={"adet": 995}, cookies=cerez)
    assert r.status_code == 200, r.text

    sonuclar = _paralel(
        8,
        lambda: httpx.post(
            f"{sunucu}/cart/lines",
            json={"urun_kod": "P-001", "adet": 1},
            cookies=cerez,
            timeout=60,
        ),
    )

    kodlar = sorted(x.status_code for x in sonuclar)
    assert kodlar == [200] * 4 + [422] * 4, kodlar
    sepet = httpx.get(f"{sunucu}/cart", cookies=cerez).json()
    assert sepet["satirlar"][0]["adet"] == 999

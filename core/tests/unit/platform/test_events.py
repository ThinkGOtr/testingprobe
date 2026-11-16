"""Olay yolu: LISTEN/NOTIFY dağıtıcısı (yeniden bağlanma dahil) ve gerçek uvicorn üstünde SSE."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tp_core.api import main
from tp_core.api.routers import events as events_router
from tp_core.auth.passwords import hash_password
from tp_core.auth.sessions import SessionData
from tp_core.events import Broadcaster, PgEventBus, build_payload, libpq_dsn, publish_tx
from tp_core.proje import KURULUM, proje_icinde, varsayilan_pid
from tp_core.workflow.service import Principal

from .conftest import PAROLA, Db

MakeUser = Callable[..., Principal]


class _ProjeliBus(PgEventBus):
    """Testte olayı (oturumun) varsayılan projesinin bağlamında yayınlar: bağlamsız işaretsiz
    olay artık reddedilir (TP-COK-PROJE-PLANI §5.1)."""

    def publish(self, event: str, data: Mapping[str, Any]) -> None:
        with proje_icinde(varsayilan_pid(), kaynak="test"):
            super().publish(event, data)


def test_libpq_dsn() -> None:
    assert libpq_dsn("postgresql+psycopg://u:p%40x@h:5/db") == "postgresql://u:p%40x@h:5/db"


def test_yavas_abone_en_eskiyi_dusurur() -> None:
    async def senaryo() -> list[int]:
        b = Broadcaster("postgresql://yok", queue_size=2)
        q = b.subscribe()
        for i in range(5):
            b.fanout(build_payload("x.y", {"i": i}))
        b.fanout("bozuk json değil")  # yutulur, dağıtıcı çökmez
        sonuc = [q.get_nowait()["data"]["i"] for _ in range(q.qsize())]
        b.unsubscribe(q)
        assert b.subscriber_count == 0
        return sonuc

    assert asyncio.run(senaryo()) == [3, 4]


def test_dagitici_gercek_notify_ve_yeniden_baglanma(db: Db, engine: Engine) -> None:
    bus = _ProjeliBus(engine)

    async def bekle(q: asyncio.Queue, olay: str) -> dict:
        while True:
            o = await asyncio.wait_for(q.get(), timeout=5)
            if o["event"] == olay:
                return o

    async def senaryo() -> None:
        b = Broadcaster(libpq_dsn(db.app_url))
        await b.ensure_started()
        q1, q2 = b.subscribe(), b.subscribe()
        await asyncio.to_thread(bus.publish, "case.generated", {"id": "c1", "n": 3})
        for q in (q1, q2):
            o = await bekle(q, "case.generated")
            assert o["data"] == {"id": "c1", "n": 3}
        # dinleyici bağlantısını öldür → dağıtıcı yeniden bağlanmalı
        with db.srv.super_conn(db.name) as c:
            c.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE query ILIKE 'LISTEN%' AND datname = current_database()"
            )
        teslim = False
        for _ in range(50):
            await asyncio.to_thread(bus.publish, "ci.status", {"id": "r1"})
            try:
                await asyncio.wait_for(bekle(q1, "ci.status"), timeout=0.3)
                teslim = True
                break
            except TimeoutError:
                continue
        assert teslim, "yeniden bağlandıktan sonra olay gelmedi"
        await b.stop()

    asyncio.run(senaryo())


# ----------------------------------------------------------------- SSE uç noktası


def test_events_oturum_ister(db: Db) -> None:
    with TestClient(main.create_app()) as c:
        r = c.get("/events")
    assert r.status_code == 401


def test_sse_canli_akis(sunucu: str, make_user: MakeUser, engine: Engine) -> None:
    u = make_user("admin")
    with httpx.Client(base_url=sunucu, timeout=10) as c:
        r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        with c.stream("GET", "/events") as akis:
            assert akis.status_code == 200
            assert akis.headers["content-type"].startswith("text/event-stream")
            satirlar = akis.iter_lines()
            olay = None
            for satir in satirlar:
                if satir.startswith("event:"):
                    olay = satir.split(":", 1)[1].strip()
                    if olay == "stream.open":
                        break
            assert olay == "stream.open"
            _ProjeliBus(engine).publish("pr.opened", {"id": "pr-7", "url": "local://7"})
            gelen: dict | None = None
            olay = None
            for satir in satirlar:
                if satir.startswith("event:"):
                    olay = satir.split(":", 1)[1].strip()
                elif satir.startswith("data:") and olay == "pr.opened":
                    gelen = json.loads(satir.split(":", 1)[1])
                    break
            assert gelen is not None
            assert gelen["data"] == {"id": "pr-7", "url": "local://7"}
            assert "ts" in gelen


def _olaylari_oku(satirlar: Iterator[str]) -> Iterator[tuple[str, str | None]]:
    """SSE satırlarından (olay adı, data) çiftleri üretir; ping yorumlarını atlar."""
    olay: str | None = None
    for satir in satirlar:
        if satir.startswith("event:"):
            olay = satir.split(":", 1)[1].strip()
        elif satir.startswith("data:") and olay is not None:
            yield olay, satir.split(":", 1)[1].strip()
            olay = None


def test_sse_cikistan_sonra_olay_teslim_etmez_ve_kapanir(
    sunucu: str, make_user: MakeUser, engine: Engine
) -> None:
    """Açık akış, çıkıştan sonra yayımlanan olayı almaz; session.ended ile kapanır."""
    u = make_user("admin")
    with httpx.Client(base_url=sunucu, timeout=10) as c:
        assert (
            c.post(
                "/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA}
            ).status_code
            == 200
        )
        cerez = c.cookies.get("tp_session")
        with c.stream("GET", "/events") as akis:
            assert akis.status_code == 200
            olaylar = _olaylari_oku(akis.iter_lines())
            assert next(olaylar)[0] == "stream.open"
            # Çerezin kopyasıyla başka bir istemciden çıkış: sunucu tarafı oturum iptal edilir.
            with httpx.Client(base_url=sunucu, timeout=10) as diger:
                diger.cookies.set("tp_session", cerez)
                assert diger.post("/auth/logout").status_code == 200
                assert diger.get("/auth/me").status_code == 401
            _ProjeliBus(engine).publish("requirement.state", {"id": "gizli-1"})
            kalan = list(olaylar)  # akış kapanınca iterasyon biter (zaman aşımı = başarısız)
    assert kalan == [("session.ended", "{}")]


def test_sse_parola_degisince_kapanir(sunucu: str, make_user: MakeUser, engine: Engine) -> None:
    u = make_user("admin")
    with httpx.Client(base_url=sunucu, timeout=10) as c:
        c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        with c.stream("GET", "/events") as akis:
            olaylar = _olaylari_oku(akis.iter_lines())
            assert next(olaylar)[0] == "stream.open"
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "UPDATE app_user SET parola_hash = %s WHERE id = %s",
                    (hash_password("Yeni-Parola-9!"), u.id),
                )
            _ProjeliBus(engine).publish("case.generated", {"id": "c9"})
            kalan = list(olaylar)
    assert kalan == [("session.ended", "{}")]


def test_sse_gecerli_oturumda_olaylar_akmaya_devam_eder(
    sunucu: str, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user("analyst")
    with httpx.Client(base_url=sunucu, timeout=10) as c:
        c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
        with c.stream("GET", "/events") as akis:
            olaylar = _olaylari_oku(akis.iter_lines())
            assert next(olaylar)[0] == "stream.open"
            bus = _ProjeliBus(engine)
            for i in range(3):
                bus.publish("script.state", {"i": i})
            gelen = [json.loads(next(olaylar)[1] or "{}")["data"]["i"] for _ in range(3)]
    assert gelen == [0, 1, 2]


class _SahteIstek:
    async def is_disconnected(self) -> bool:
        return False


def test_akis_bostayken_de_oturumu_periyodik_denetler() -> None:
    """Olay gelmese de kontrol aralığı dolunca oturum yeniden denetlenir ve akış kapanır."""
    durum = {"gecerli": True, "cagri": 0}

    async def kontrol() -> bool:
        durum["cagri"] += 1
        return durum["gecerli"]

    async def senaryo() -> list[str]:
        b = Broadcaster("postgresql://yok")
        q = b.subscribe()
        gen = events_router._akis(_SahteIstek(), b, q, kontrol, kontrol_s=0.0)  # type: ignore[arg-type]
        adlar = [(await anext(gen))["event"]]
        durum["gecerli"] = False
        async for olay in gen:
            adlar.append(olay["event"])
        assert b.subscriber_count == 0  # kapanınca abonelik bırakılır
        return adlar

    adlar = asyncio.run(asyncio.wait_for(senaryo(), timeout=10))
    assert adlar == ["stream.open", "session.ended"]
    assert durum["cagri"] >= 1


def test_oturum_kontrolu_hata_verirse_gecersiz_sayar(monkeypatch: pytest.MonkeyPatch) -> None:
    def patla(_veri: object) -> bool:
        raise RuntimeError("db yok")

    monkeypatch.setattr(events_router, "_oturum_gecerli_mi", patla)
    veri = SessionData(uuid.uuid4(), "pv", uuid.uuid4())
    assert asyncio.run(events_router.oturum_kontrolu(veri)()) is False


# --------------------------------------------- olay yükünde proje (TP-COK-PROJE-PLANI §5.1, Ş1)


def test_olay_yuku_projeyi_tasir_kirpmada_da() -> None:
    assert json.loads(build_payload("x.y", {"i": 1}))["project_id"] is None  # bağlamsız: işaretsiz
    assert json.loads(build_payload("x.y", {}, project_id=KURULUM))["project_id"] == KURULUM
    with proje_icinde("a", kaynak="test"):
        assert json.loads(build_payload("x.y", {"i": 1}))["project_id"] == "a"
        assert json.loads(build_payload("x.y", {}, project_id="b"))["project_id"] == "b"
        kirpik = json.loads(build_payload("x.y", {"id": "k", "buyuk": "x" * 9000}))
    assert kirpik["data"] == {"id": "k", "truncated": True} and kirpik["project_id"] == "a"


def test_abone_yalniz_kendi_projesinin_ve_kurulum_olaylarini_alir() -> None:
    async def senaryo() -> tuple[list[str], list[str], list[str]]:
        b = Broadcaster("postgresql://yok")
        qa, qb, hepsi = b.subscribe("a"), b.subscribe("b"), b.subscribe()
        b.fanout(build_payload("x.a", {}, project_id="a"))
        b.fanout(build_payload("x.b", {}, project_id="b"))
        b.fanout(build_payload("x.kurulum", {}, project_id=KURULUM))
        b.fanout(build_payload("x.isaretsiz", {}))  # bağlamsız, işaretsiz: projeli aboneye gitmez
        return tuple(  # type: ignore[return-value]
            [q.get_nowait()["event"] for _ in range(q.qsize())] for q in (qa, qb, hepsi)
        )

    qa, qb, hepsi = asyncio.run(senaryo())
    assert qa == ["x.a", "x.kurulum"]
    assert qb == ["x.b", "x.kurulum"]
    assert hepsi == ["x.a", "x.b", "x.kurulum", "x.isaretsiz"]


def test_publish_tx_baglamdaki_projeyi_yazar(db: Db, engine: Engine) -> None:
    async def senaryo() -> dict:
        b = Broadcaster(libpq_dsn(db.app_url))
        await b.ensure_started()
        q = b.subscribe("p1")

        def yayinla() -> None:
            with proje_icinde("p2", kaynak="test"), engine.begin() as c:
                publish_tx(c, "x.diger", {})
            with proje_icinde("p1", kaynak="test"), engine.begin() as c:
                publish_tx(c, "x.benim", {"id": "1"})

        await asyncio.to_thread(yayinla)
        olay = await asyncio.wait_for(q.get(), timeout=5)
        await b.stop()
        return olay

    olay = asyncio.run(senaryo())
    assert (olay["event"], olay["project_id"]) == ("x.benim", "p1")


def test_publish_tx_baglamsiz_isaretsiz_olayi_reddeder(
    db: Db, engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    async def senaryo() -> list[dict]:
        b = Broadcaster(libpq_dsn(db.app_url))
        await b.ensure_started()
        q, hepsi = b.subscribe("p1"), b.subscribe()

        def yayinla() -> None:
            with engine.begin() as c:
                publish_tx(c, "x.isaretsiz", {})  # bağlam yok, işaret yok → gönderilmez
                publish_tx(c, "x.kurulum", {}, project_id=KURULUM)

        await asyncio.to_thread(yayinla)
        olay = await asyncio.wait_for(q.get(), timeout=5)
        diger = await asyncio.wait_for(hepsi.get(), timeout=5)
        await b.stop()
        return [olay, diger]

    with caplog.at_level("WARNING", logger="tp_core.events"):
        olay, diger = asyncio.run(senaryo())
    assert (olay["event"], olay["project_id"]) == ("x.kurulum", KURULUM)
    assert diger["event"] == "x.kurulum"  # işaretsiz olay iç aboneye de ulaşmadı (NOTIFY yok)
    assert "projesiz olay yayınlanmadı: x.isaretsiz" in caplog.text

"""SSE kişiye özel olay filtresi (AI-ASISTAN-PLANI §9, §13 "SSE"): `assistant.*` olayı yalnız
`kullanici_id`'si oturum kullanıcısı olan akışa gider; kimliksiz olay kimseye gitmez; kırpılmış
yükte kimlik alanları korunur."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
from sqlalchemy import Engine

from tests.unit.conftest import PAROLA
from tp_core.api.routers import events as events_router
from tp_core.events import Broadcaster, PgEventBus, build_payload, parse_payload
from tp_core.events.bus import KIMLIK_ALANLARI, MAX_PAYLOAD

# ------------------------------------------------------------------ saf fonksiyon


def test_teslim_kurallari() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    olay = {"event": "assistant.answered", "data": {"mesaj_id": "m", "kullanici_id": str(a)}}
    assert events_router.teslim_edilir_mi(olay, a) is True
    assert events_router.teslim_edilir_mi(olay, str(a).upper()) is True
    assert events_router.teslim_edilir_mi(olay, b) is False
    assert events_router.teslim_edilir_mi(olay, None) is False  # akış kullanıcısı bilinmiyor
    kimliksiz = {"event": "assistant.step", "data": {"mesaj_id": "m"}}
    assert events_router.teslim_edilir_mi(kimliksiz, a) is False
    bos = {"event": "assistant.step", "data": {"kullanici_id": ""}}
    assert events_router.teslim_edilir_mi(bos, a) is False
    veri_yok = {"event": "assistant.step", "data": None}
    assert events_router.teslim_edilir_mi(veri_yok, a) is False
    # diğer olaylar herkese (değişmeyen davranış)
    assert events_router.teslim_edilir_mi({"event": "case.generated", "data": {}}, None) is True
    assert events_router.teslim_edilir_mi({"event": "assistantx.y", "data": {}}, None) is True


def test_kirpilmis_yukte_kimlik_alanlari_korunur() -> None:
    assert {"mesaj_id", "kullanici_id"} <= set(KIMLIK_ALANLARI)
    k = str(uuid.uuid4())
    yuk = parse_payload(
        build_payload(
            "assistant.answered",
            {"mesaj_id": "m-1", "kullanici_id": k, "durum": "done", "dolgu": "x" * MAX_PAYLOAD},
        )
    )
    assert yuk["data"] == {"mesaj_id": "m-1", "kullanici_id": k, "durum": "done", "truncated": True}
    assert events_router.teslim_edilir_mi(yuk, k) is True


class _SahteIstek:
    async def is_disconnected(self) -> bool:
        return False


def test_akis_baskasinin_olayini_atlar() -> None:
    ben, o = uuid.uuid4(), uuid.uuid4()

    async def kontrol() -> bool:
        return True

    async def senaryo() -> list[dict[str, Any]]:
        b = Broadcaster("postgresql://yok")
        q = b.subscribe()
        for olay in (
            {"event": "assistant.step", "data": {"mesaj_id": "1", "kullanici_id": str(o)}},
            {"event": "assistant.step", "data": {"mesaj_id": "2"}},
            {"event": "assistant.step", "data": {"mesaj_id": "3", "kullanici_id": str(ben)}},
            {"event": "case.generated", "data": {"id": "c"}},
        ):
            q.put_nowait(olay)
        gen = events_router._akis(_SahteIstek(), b, q, kontrol, kullanici_id=ben)  # type: ignore[arg-type]
        alinan = [await anext(gen) for _ in range(3)]
        await gen.aclose()
        return alinan

    alinan = asyncio.run(asyncio.wait_for(senaryo(), timeout=10))
    assert [a["event"] for a in alinan] == ["stream.open", "assistant.step", "case.generated"]
    assert json.loads(alinan[1]["data"])["data"]["mesaj_id"] == "3"


# ------------------------------------------------------------------ gerçek akış


def _okuyucu(satirlar):
    olay = None
    for satir in satirlar:
        if satir.startswith("event:"):
            olay = satir.split(":", 1)[1].strip()
        elif satir.startswith("data:") and olay is not None:
            yield olay, json.loads(satir.split(":", 1)[1])
            olay = None


def test_sse_b_kullanicisi_a_nin_olayini_almaz(sunucu: str, make_user, engine: Engine) -> None:
    from tp_core.auth.login import THROTTLE

    THROTTLE._kayit.clear()
    a, b = make_user("analyst"), make_user("tester")
    with httpx.Client(base_url=sunucu, timeout=10) as c:
        r = c.post("/auth/login", json={"kullanici_adi": b.kullanici_adi, "parola": PAROLA})
        assert r.status_code == 200
        with c.stream("GET", "/events") as akis:
            olaylar = _okuyucu(akis.iter_lines())
            assert next(olaylar)[0] == "stream.open"
            bus = PgEventBus(engine)
            bus.publish("assistant.step", {"mesaj_id": "a1", "kullanici_id": str(a.id)})
            bus.publish("assistant.answered", {"mesaj_id": "x", "durum": "done"})
            bus.publish("assistant.answered", {"mesaj_id": "b1", "kullanici_id": str(b.id)})
            ad, veri = next(olaylar)
    assert ad == "assistant.answered"
    assert veri["data"] == {"mesaj_id": "b1", "kullanici_id": str(b.id)}

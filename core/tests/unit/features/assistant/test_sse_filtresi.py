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


def test_developer_rol_suzgeci() -> None:
    """specs/012 §4.2: developer yalnız onaylı/yayınlanmış case ve açılmış bug görür."""
    gor = events_router.rol_gorur_mu
    taslak = {"event": "case.generated", "data": {"id": "c"}}
    karar = {"event": "review.recorded", "data": {"nesne_turu": "test_case", "karar": "accept"}}
    bug_karar = {"event": "review.recorded", "data": {"nesne_turu": "bug_draft"}}
    script_karar = {"event": "review.recorded", "data": {"nesne_turu": "script"}}
    hazir = {"event": "test_case.state", "data": {"id": "c", "durum": "ready"}}
    onayli = {"event": "test_case.state", "data": {"id": "c", "durum": "approved"}}
    yayinda = {"event": "test_case.state", "data": {"id": "c", "durum": "published"}}
    bug_taslak = {"event": "bug_draft.state", "data": {"durum": "ready"}}
    bug_yayinda = {"event": "bug_draft.state", "data": {"durum": "published"}}
    ci = {"event": "ci.status", "data": {}}
    for rol in ("developer", "tester", "analyst", None):
        gorur = {
            n: gor(o, rol)
            for n, o in {
                "taslak": taslak, "karar": karar, "bug_karar": bug_karar,
                "script_karar": script_karar, "hazir": hazir, "onayli": onayli,
                "yayinda": yayinda, "bug_taslak": bug_taslak, "bug_yayinda": bug_yayinda,
                "ci": ci,
            }.items()
        }  # fmt: skip
        if rol == "developer":
            assert {n for n, v in gorur.items() if v} == {
                "script_karar", "onayli", "yayinda", "bug_yayinda", "ci",
            }  # fmt: skip
        else:
            assert all(gorur.values()), rol


def test_akis_developer_taslak_case_olayini_atlar() -> None:
    async def kontrol() -> bool:
        return True

    async def senaryo() -> list[dict[str, Any]]:
        b = Broadcaster("postgresql://yok")
        q = b.subscribe()
        for olay in (
            {"event": "case.generated", "data": {"id": "c"}},
            {"event": "test_case.state", "data": {"id": "c", "durum": "ready"}},
            {"event": "test_case.state", "data": {"id": "c", "durum": "approved"}},
        ):
            q.put_nowait(olay)
        gen = events_router._akis(_SahteIstek(), b, q, kontrol, rol="developer")  # type: ignore[arg-type]
        alinan = [await anext(gen) for _ in range(2)]
        await gen.aclose()
        return alinan

    alinan = asyncio.run(asyncio.wait_for(senaryo(), timeout=10))
    assert [a["event"] for a in alinan] == ["stream.open", "test_case.state"]
    assert json.loads(alinan[1]["data"])["data"]["durum"] == "approved"


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

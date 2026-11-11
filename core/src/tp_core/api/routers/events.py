"""GET /events — SSE olay akışı (oturum ve `events.read` izni gerekir; auditor/viewer hariç).

İlk olay `stream.open`'dır (abonelik hazır). Sonra Postgres NOTIFY ile gelen her olay
`event: <ad>` + `data: <JSON>` olarak akar; 15 sn'de bir ping (nginx 30 sn okuma zaman aşımı).

Oturum yalnızca bağlantı açılırken değil akış boyunca da denetlenir (MIMARI-SOZLESME §5: çıkış
çerezin kopyalarını da geçersizleştirir): her olay teslim edilmeden önce ve boşta en geç
`OTURUM_KONTROL_S` saniyede bir. Oturum iptal edilmiş, süresi dolmuş, parola değişmiş veya
kullanıcı silinmişse son olarak `event: session.ended` gönderilir ve akış kapanır; bekleyen olay
teslim edilmez. Portal bunu alınca kullanıcıyı /giris'e yönlendirir.

Kişiye özel olaylar (AI-ASISTAN-PLANI §9): `assistant.*` olayları yalnız `data.kullanici_id`'si
oturum kullanıcısı olan akışa teslim edilir. Kimlik yoksa, eşleşmiyorsa ya da akışın kullanıcısı
bilinmiyorsa olay hiç gönderilmez (fail-closed). Diğer olaylar önceki gibi herkese gider.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from tp_core.auth.deps import Codec
from tp_core.auth.sessions import SessionData, cookie_name, session_valid
from tp_core.auth.yetki import izin
from tp_core.config import get_settings
from tp_core.events.listener import Broadcaster, libpq_dsn
from tp_core.models import new_session
from tp_core.workflow.service import Principal

router = APIRouter(tags=["events"])
log = logging.getLogger(__name__)

PING_S = 15
OTURUM_KONTROL_S = 15.0
OTURUM_BITTI = "session.ended"

OturumKontrol = Callable[[], Awaitable[bool]]

# Yalnız sahibine teslim edilen olay ad önekleri (yük `kullanici_id` taşımalı).
KISIYE_OZEL_ONEKLER = ("assistant.",)


def teslim_edilir_mi(olay: Mapping[str, Any], kullanici_id: object | None) -> bool:
    """Olay bu akışa gidebilir mi? Kişiye özel olayda kimlik eksik/uyuşmaz → hayır."""
    ad = str(olay.get("event") or "")
    if not ad.startswith(KISIYE_OZEL_ONEKLER):
        return True
    if kullanici_id is None:
        return False
    veri = olay.get("data")
    sahip = veri.get("kullanici_id") if isinstance(veri, Mapping) else None
    if not isinstance(sahip, str) or not sahip:
        return False
    return sahip.strip().lower() == str(kullanici_id).strip().lower()


def broadcaster_for(request: Request) -> Broadcaster:
    b = getattr(request.app.state, "broadcaster", None)
    if b is None:
        b = Broadcaster(libpq_dsn(get_settings().database_url))
        request.app.state.broadcaster = b
    return b


def _oturum_gecerli_mi(veri: SessionData) -> bool:
    # AI Probe oturumunda aynı 60 sn önbellekli kontrol; `son_kontrol` güncellemesi commit edilir.
    # Süre uzatılmaz (yalnız kullanıcı istekleri uzatır).
    with new_session() as s:
        gecerli = session_valid(s, veri) is not None
        s.commit()
        return gecerli


def oturum_kontrolu(veri: SessionData) -> OturumKontrol:
    """Oturumu veritabanından yeniden denetleyen eşzamansız kontrol (hata = geçersiz sayılır)."""

    async def kontrol() -> bool:
        try:
            return await asyncio.to_thread(_oturum_gecerli_mi, veri)
        except Exception:  # veritabanı erişilemiyorsa akış güvenli tarafta kapanır
            log.warning("SSE oturum kontrolü başarısız; akış kapatılıyor", exc_info=True)
            return False

    return kontrol


async def _akis(
    request: Request,
    b: Broadcaster,
    q: asyncio.Queue[dict[str, Any]],
    oturum_gecerli: OturumKontrol,
    kontrol_s: float = OTURUM_KONTROL_S,
    *,
    kullanici_id: object | None = None,
) -> AsyncIterator[dict[str, str]]:
    bitti = {"event": OTURUM_BITTI, "data": "{}"}
    try:
        yield {"event": "stream.open", "data": "{}"}
        son_kontrol = time.monotonic()
        while True:
            if await request.is_disconnected():
                break
            try:
                olay = await asyncio.wait_for(q.get(), timeout=1.0)
            except TimeoutError:
                if time.monotonic() - son_kontrol >= kontrol_s:
                    if not await oturum_gecerli():
                        yield bitti
                        break
                    son_kontrol = time.monotonic()
                continue
            if not teslim_edilir_mi(olay, kullanici_id):
                continue
            # Teslimden önce: çıkıştan sonra yayımlanan olay eski bağlantıya ulaşmamalı.
            if not await oturum_gecerli():
                yield bitti
                break
            son_kontrol = time.monotonic()
            yield {
                "event": str(olay.get("event")),
                "data": json.dumps(
                    {"data": olay.get("data"), "ts": olay.get("ts")}, ensure_ascii=False
                ),
            }
    finally:
        b.unsubscribe(q)


@router.get("/events")
async def events(
    request: Request, user: Annotated[Principal, Depends(izin("events.read"))], codec: Codec
) -> EventSourceResponse:
    veri = codec.loads(request.cookies.get(cookie_name(), ""))
    if veri is None:  # izin bağımlılığı oturumu zaten doğruladı; yine de tür daraltma için
        raise HTTPException(401, "Oturumunuz geçersiz veya süresi dolmuş")
    b = broadcaster_for(request)
    try:
        await b.ensure_started()
    except TimeoutError as exc:
        raise HTTPException(503, "Olay akışı şu anda kullanılamıyor") from exc
    q = b.subscribe()
    return EventSourceResponse(
        _akis(request, b, q, oturum_kontrolu(veri), kullanici_id=user.id),
        ping=PING_S,
        headers={"X-Accel-Buffering": "no"},
    )

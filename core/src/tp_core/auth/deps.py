"""FastAPI bağımlılıkları: veritabanı oturumu, oturumdaki kullanıcı, rol ve bearer token kontrolü.

`DbSession` işlemi **yanıt gönderilmeden önce** commit eder (scope="function"): onay gibi kayıtlar
commit edilemezse istemci başarı yanıtı almaz.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from tp_core.auth.sessions import (
    OturumDurumu,
    SessionCodec,
    cookie_name,
    session_valid,
)
from tp_core.auth.tokens import verify_bearer
from tp_core.config import get_settings
from tp_core.models import db_session
from tp_core.workflow.service import Principal

DbSession = Annotated[Session, Depends(db_session, scope="function")]


def session_codec() -> SessionCodec:
    ayar = get_settings()
    if ayar.session_secret is None or not ayar.session_secret.get_secret_value():
        raise HTTPException(503, "Oturum yapılandırılmamış (TP_SESSION_SECRET tanımlı değil)")
    return SessionCodec(ayar.session_secret.get_secret_value(), ayar.session_max_age_s)


Codec = Annotated[SessionCodec, Depends(session_codec)]


DEGRADED_HEADER = "X-Aiprobe-Degraded"


def current_user(
    request: Request, response: Response, session: DbSession, codec: Codec
) -> Principal:
    raw = request.cookies.get(cookie_name())
    if not raw:
        raise HTTPException(401, "Oturum açmanız gerekiyor")
    veri = codec.loads(raw)
    if veri is None:
        raise HTTPException(401, "Oturumunuz geçersiz veya süresi dolmuş")
    durum = OturumDurumu()
    user = session_valid(session, veri, uzat=True, durum=durum)
    if user is None:
        raise HTTPException(401, "Oturumunuz geçersiz veya süresi dolmuş")
    if durum.degraded:
        # aiprobe-home erişilemedi: oturum süre sınırları içinde korunur; portal uyarı bandı
        # gösterir.
        response.headers[DEGRADED_HEADER] = "1"
    request.state.oturum_external_uid = durum.external_uid
    request.state.oturum_durumu = durum
    p = Principal(user.id, user.kullanici_adi, user.rol)
    request.state.principal = p
    return p


CurrentUser = Annotated[Principal, Depends(current_user)]


def require_role(*roller: str) -> Callable[[Principal], Principal]:
    """KULLANIMDAN KALKTI: yerine `tp_core.auth.yetki.izin("<izin>")` (specs/012-rol-yetki §4.3).

    Yalnızca verilen rollerden birine izin verir; reddi denetime yazmaz. Case/yayın/token uçları
    S2 şeridi birleşene kadar kullanır; yeni uçta kullanılmaz (katalog testi izin ister).
    """
    if not roller:
        raise ValueError("en az bir rol verilmeli")
    izinli = frozenset(roller)

    def kontrol(user: CurrentUser) -> Principal:
        if user.rol not in izinli:
            raise HTTPException(403, "Bu işlem için yetkiniz yok")
        return user

    kontrol.__name__ = f"require_role_{'_'.join(sorted(izinli))}"
    return kontrol


def require_token(kapsam: str) -> Callable[[Request, Session], Principal]:
    """MCP kanalı: `Authorization: Bearer tpt_...` başlığındaki kapsamlı token'ı doğrular."""

    def kontrol(request: Request, session: DbSession) -> Principal:
        baslik = request.headers.get("authorization", "")
        tur, _, deger = baslik.partition(" ")
        p = verify_bearer(session, deger.strip() if tur.lower() == "bearer" else None, kapsam)
        if p is None:
            raise HTTPException(
                401, "Geçersiz veya süresi dolmuş token", headers={"WWW-Authenticate": "Bearer"}
            )
        request.state.principal = p
        return p

    kontrol.__name__ = f"require_token_{kapsam}"
    return kontrol

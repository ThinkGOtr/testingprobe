"""POST /auth/login · POST /auth/logout · GET /auth/me"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.client_ip import client_address
from tp_core.auth.deps import Codec, CurrentUser, DbSession, session_codec
from tp_core.auth.display import display_name, display_names, person_name
from tp_core.auth.login import THROTTLE, authenticate
from tp_core.auth.sessions import (
    COOKIE_NAME,
    DEVICE_COOKIE_NAME,
    DEVICE_MAX_AGE_S,
    SessionCodec,
    open_session,
    revoke_session,
)
from tp_core.config import get_settings
from tp_core.models import AppUser

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    kullanici_adi: str = Field(min_length=1, max_length=64)
    parola: str = Field(min_length=1, max_length=256)


class Me(BaseModel):
    id: uuid.UUID
    kullanici_adi: str
    rol: str
    # Yalnızca gösterim (yetki rolle): "Cengizhan Gunaydin · Analist"; ad tanımsızsa rol etiketi.
    gorunen_ad: str
    ad_soyad: str | None = None
    # Portalın denetim/onay görünümlerinde kullanıcı adlarını çevirmesi için tüm portal
    # kullanıcılarının görünen adları ({kullanici_adi: gorunen_ad}).
    kisiler: dict[str, str] = Field(default_factory=dict)


def me_of(session: Session, user_id: uuid.UUID, kullanici_adi: str, rol: str) -> Me:
    kullanicilar = session.execute(select(AppUser.kullanici_adi, AppUser.rol)).all()
    return Me(
        id=user_id,
        kullanici_adi=kullanici_adi,
        rol=rol,
        gorunen_ad=display_name(kullanici_adi, rol),
        ad_soyad=person_name(kullanici_adi),
        kisiler=display_names((k, r) for k, r in kullanicilar),
    )


def throttle_key(request: Request, kullanici_adi: str, codec: SessionCodec) -> str:
    """Deneme sınırı anahtarı.

    - İstemci bu kullanıcı için daha önce başarıyla giriş yapmışsa (imzalı `tp_cihaz` çerezi) sayaç
      o cihaza özeldir: aynı IP'yi paylaşan başka biri (portal proxy'si, NAT, aynı makine) yanlış
      parolalarla bu kullanıcıyı kendi tarayıcısından kilitleyemez.
    - Değilse (kullanıcı adı, gerçek istemci adresi): adres güvenilen proxy'nin
      X-Forwarded-For'undan (`client_address`); doğrudan bağlantıda TCP eşi.
    """
    ad = kullanici_adi.strip().lower()
    raw = request.cookies.get(DEVICE_COOKIE_NAME)
    cihaz = codec.loads_device(raw) if raw else None
    if cihaz is not None and cihaz.kullanici == ad:
        return f"{ad}|cihaz:{cihaz.cihaz}"
    return f"{ad}|ip:{client_address(request)}"


@router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, session: DbSession, codec: Codec) -> JSONResponse:
    anahtar = throttle_key(request, body.kullanici_adi, codec)
    # Hak, (yavaş) argon2 doğrulamasından önce atomik olarak ayrılır: eşzamanlı yanlış parolalar
    # pencerede en çok MAX_DENEME kez doğrulanır.
    if not THROTTLE.try_acquire(anahtar):
        return JSONResponse(
            {"detail": "Çok fazla hatalı deneme. Birkaç dakika sonra tekrar deneyin."},
            status_code=429,
        )
    user = authenticate(session, body.kullanici_adi, body.parola, client_address(request))
    if user is None:
        # İstisna değil yanıt: başarısız deneme denetim kaydıyla birlikte commit edilir.
        return JSONResponse({"detail": "Kullanıcı adı veya parola hatalı"}, status_code=401)
    THROTTLE.success(anahtar)
    sid = open_session(session, user.id, codec.max_age_s)
    yanit = JSONResponse(
        me_of(session, user.id, user.kullanici_adi, user.rol).model_dump(mode="json")
    )
    yanit.set_cookie(
        COOKIE_NAME,
        codec.dumps(user.id, user.parola_hash, sid),
        max_age=codec.max_age_s,
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
        path="/",
    )
    # Tanınan cihaz: mevcut geçerli çerez korunur (cihaz kimliği sabit kalır), yoksa yenisi.
    raw = request.cookies.get(DEVICE_COOKIE_NAME)
    mevcut = codec.loads_device(raw) if raw else None
    cihaz = mevcut.cihaz if mevcut is not None else None
    yanit.set_cookie(
        DEVICE_COOKIE_NAME,
        codec.dumps_device(user.kullanici_adi, cihaz),
        max_age=DEVICE_MAX_AGE_S,
        httponly=True,
        samesite="strict",
        secure=get_settings().session_cookie_secure,
        path="/",
    )
    return yanit


@router.post("/logout")
def logout(
    request: Request, session: DbSession, codec: Annotated[SessionCodec, Depends(session_codec)]
) -> JSONResponse:
    raw = request.cookies.get(COOKIE_NAME)
    veri = codec.loads(raw) if raw else None
    if veri is not None:
        user = session.get(AppUser, veri.user_id)
        # Yalnızca etkin bir oturum iptal edildiyse denetime yazılır (çerez kopyasıyla tekrar
        # çıkış "logout" kaydı üretmez).
        if user is not None and revoke_session(session, veri):
            audit_on_commit(
                session, user.kullanici_adi, "auth.logout", f"app_user:{user.id}", {"sid": veri.sid}
            )
    yanit = JSONResponse({"ok": True})
    yanit.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return yanit


@router.get("/me", response_model=Me)
def me(user: CurrentUser, session: DbSession) -> Me:
    assert user.id is not None
    return me_of(session, user.id, user.kullanici_adi, user.rol)

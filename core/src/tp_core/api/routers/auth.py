"""POST /auth/login · POST /auth/logout · GET /auth/me

`TP_AUTH_MODE=aiprobe` kipinde yerel giriş kapalıdır (`/auth/login` 404); giriş
`/auth/aiprobe/*` uçlarındandır (api/routers/aiprobe.py, TEKNIK-TASARIM §8.14). `both` kipinde
bir AI Probe kişisine bağlı (`kimlik_bagi`) hesap yerel parolayla açılmaz (403 `aiprobe_gerekli`).
"""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.client_ip import client_address
from tp_core.auth.deps import Codec, CurrentUser, DbSession, session_codec
from tp_core.auth.display import configured_names, display_name, person_name
from tp_core.auth.login import THROTTLE, OrtakKimlikGerekli, authenticate
from tp_core.auth.sessions import (
    DEVICE_COOKIE_NAME,
    DEVICE_MAX_AGE_S,
    SessionCodec,
    aiprobe_acik,
    cookie_name,
    cookie_secure,
    open_session,
    revoke_session,
)
from tp_core.config import get_settings
from tp_core.models import AppUser, Oturum

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
    kullanicilar = session.execute(
        select(AppUser.kullanici_adi, AppUser.rol, AppUser.ad_soyad)
    ).all()
    # Yapılandırılmış adlar önce gelir; JIT (AI Probe) hesaplarında ad veritabanındadır.
    names = configured_names()
    for k, _r, ad_soyad in kullanicilar:
        if ad_soyad and k.strip().lower() not in names:
            names[k.strip().lower()] = ad_soyad
    return Me(
        id=user_id,
        kullanici_adi=kullanici_adi,
        rol=rol,
        gorunen_ad=display_name(kullanici_adi, rol, names),
        ad_soyad=person_name(kullanici_adi, names),
        kisiler={k: display_name(k, r, names) for k, r, _a in kullanicilar},
    )


def set_session_cookie(yanit: Response, codec: SessionCodec, user: AppUser, sid: uuid.UUID) -> None:
    """Oturum çerezi: ad ve Secure kipe göre (`local` → `tp_session`, diğer → `__Host-`)."""
    yanit.set_cookie(
        cookie_name(),
        codec.dumps(user.id, user.parola_hash, sid, user.auth_epoch or 0),
        max_age=codec.max_age_s,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
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
    if get_settings().auth_mode == "aiprobe":
        raise HTTPException(404, "Yerel giriş kapalı; AI Probe hesabıyla giriş yapın")
    anahtar = throttle_key(request, body.kullanici_adi, codec)
    # Hak, (yavaş) argon2 doğrulamasından önce atomik olarak ayrılır: eşzamanlı yanlış parolalar
    # pencerede en çok MAX_DENEME kez doğrulanır.
    if not THROTTLE.try_acquire(anahtar):
        return JSONResponse(
            {
                "detail": "Çok fazla hatalı deneme. Birkaç dakika sonra tekrar deneyin.",
                "kod": "hiz_siniri",
            },
            status_code=429,
        )
    try:
        user = authenticate(session, body.kullanici_adi, body.parola, client_address(request))
    except OrtakKimlikGerekli:
        THROTTLE.success(anahtar)
        return JSONResponse(
            {
                "detail": "Bu hesap AI Probe hesabınıza bağlı; AI Probe ile giriş yapın",
                "kod": "aiprobe_gerekli",
            },
            status_code=403,
        )
    if user is None:
        # İstisna değil yanıt: başarısız deneme denetim kaydıyla birlikte commit edilir.
        return JSONResponse(
            {"detail": "Kullanıcı adı veya parola hatalı", "kod": "yetkisiz"}, status_code=401
        )
    THROTTLE.success(anahtar)
    sid = open_session(session, user.id, codec.max_age_s)
    yanit = JSONResponse(
        me_of(session, user.id, user.kullanici_adi, user.rol).model_dump(mode="json")
    )
    set_session_cookie(yanit, codec, user, sid)
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
        secure=cookie_secure(),
        path="/",
    )
    return yanit


@router.post("/logout")
def logout(
    request: Request, session: DbSession, codec: Annotated[SessionCodec, Depends(session_codec)]
) -> Response:
    """Yerel oturumu kapatır. AI Probe oturumunda tüm ürünlerden çıkış sayfası
    `{home}/logout?product=<id>&auto=1` (yerel çıkış yapıldı → home onay istemez).

    Yanıt her zaman JSON `{"ok", "redirect"?}`: portal (fetch) yönlendirmeyi kendisi izler. Form
    POST'u ile 303 yönlendirme yoktur (CSP `form-action 'self'` home kaynağına izin vermez).
    """
    raw = request.cookies.get(cookie_name())
    veri = codec.loads(raw) if raw else None
    govde: dict[str, object] = {"ok": True}
    if veri is not None:
        user = session.get(AppUser, veri.user_id)
        harici = session.scalar(
            select(Oturum.external_uid).where(Oturum.id == veri.sid, Oturum.user_id == veri.user_id)
        )
        # Yalnızca etkin bir oturum iptal edildiyse denetime yazılır (çerez kopyasıyla tekrar
        # çıkış "logout" kaydı üretmez).
        if user is not None and revoke_session(session, veri):
            audit_on_commit(
                session, user.kullanici_adi, "auth.logout", f"app_user:{user.id}", {"sid": veri.sid}
            )
        # AI Probe oturumu: çıkış tüm ürünlerden yapılır (id. çıkış sayfası; PLAN §2.3).
        if harici is not None and aiprobe_acik():
            ayar = get_settings()
            govde["redirect"] = f"{ayar.aiprobe_id_origin.rstrip('/')}/logout?" + urlencode(
                {"product": ayar.aiprobe_product_id, "auto": "1"}
            )
    yanit = JSONResponse(govde)
    yanit.delete_cookie(
        cookie_name(), path="/", httponly=True, samesite="lax", secure=cookie_secure()
    )
    return yanit


class MeYaniti(Me):
    """`GET /auth/me`: AI Probe oturumunda ayrıca `product`, `roles` (değiştirici, "Rol değiştir").

    Alanlar yalnız AI Probe oturumunda yazılır (`response_model_exclude_unset`): yerel oturumun
    yanıtı bugünküyle aynıdır.
    """

    product: str | None = None
    # Kişiye bağlı rol hesaplarından AI Probe'un şu an verdiği rollerdekiler (sıralı).
    roles: list[str] | None = None
    # Kişinin tüm AI Probe ürünlerindeki rolleri (`{"tp": [...], "ap": [...]}`; devir/kontrol
    # yanıtından, oturumda saklanır). Değiştirici diğer ürünlere erişimi buradan bilir.
    products: dict[str, list[str]] | None = None


@router.get("/me", response_model=MeYaniti, response_model_exclude_unset=True)
def me(user: CurrentUser, request: Request, session: DbSession) -> MeYaniti:
    assert user.id is not None
    yanit = MeYaniti(**me_of(session, user.id, user.kullanici_adi, user.rol).model_dump())
    uid = getattr(request.state, "oturum_external_uid", None)
    if uid is not None:
        from tp_core.auth import aiprobe

        yanit.product = get_settings().aiprobe_product_id
        durum = getattr(request.state, "oturum_durumu", None)
        urunler = getattr(durum, "urunler", None) or {}
        yanit.products = urunler
        # Yalnız AI Probe'un şu an verdiği roller (bağlı hesap rolleriyle kesişim): oturumdaki ürün
        # haritası (devirde ve her kontrolde home'dan yenilenir); yoksa önbellekli kontrol; home'a
        # ulaşılamazsa yalnız etkin rol.
        tp_haritasi = urunler.get(aiprobe.URUN_KODU)
        if isinstance(tp_haritasi, list):
            verilen: set[str] = {str(r) for r in tp_haritasi}
        else:
            try:
                verilen = set(aiprobe.kontrol_et(uid, aiprobe.OturumKimligi.of(durum)).roles)
            except aiprobe.HomeUlasilamaz:
                verilen = {user.rol}
        bagli = {h.rol for h in aiprobe.bagli_hesaplar(session, uid)}
        yanit.roles = sorted(bagli & verilen)
    return yanit

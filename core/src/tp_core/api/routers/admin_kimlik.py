"""`/admin/kimlik-bagi` — AI Probe kişisi ↔ TP rol hesabı bağları (TEKNIK-TASARIM §8.14).

Yalnız `aiprobe-home` servis kimliği çağırabilir: `Authorization: Bearer <Google ID token>`;
imza (Google JWKS), `aud` = `AIPROBE_TP_AUDIENCE`, `iss` Google, `email_verified` ve `email` =
`AIPROBE_HOME_SA` doğrulanır (doğrulayıcı `tp_core.auth.aiprobe.configure` ile değiştirilebilir).
Kullanıcı oturumu (çerez), `tpt_` token'ı ya da başka servis hesabı kabul edilmez. `local`
kipte 404.

- `GET    /admin/kimlik-bagi?external_uid=` → bağlar
- `GET    /admin/kimlik-bagi/hesaplar` → TP rol hesapları (bağ ekranı için)
- `PUT    /admin/kimlik-bagi {external_uid, app_user_id | kullanici_adi}` → bağ (aynıysa idempotent;
  hesap başka kişiye bağlıysa 409)
- `DELETE /admin/kimlik-bagi/{app_user_id}` → bağı kaldırır; hesabın epoch'u artar, oturumu düşer.
  Bağı kaldırmak tek başına erişimi kesmez: kişinin AI Probe'da TP rolü sürdükçe sonraki girişte
  JIT o rol için yeni bir hesap açar. Erişimi kesen, rolün AI Probe'dan kaldırılmasıdır.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tp_core.api.errors import KodluHata
from tp_core.audit import audit_on_commit
from tp_core.auth import aiprobe
from tp_core.auth.deps import DbSession
from tp_core.auth.sessions import aiprobe_acik
from tp_core.config import get_settings
from tp_core.models import AppUser, KimlikBagi

log = logging.getLogger(__name__)
AKTOR = "aiprobe-home"


def home_servisi(request: Request) -> str:
    """Çağıran `aiprobe-home` servis hesabı mı? Değilse 401/403 (404: `local` kip)."""
    if not aiprobe_acik():
        raise KodluHata(404, "bulunamadi", "Not Found")
    ayar = get_settings()
    beklenen = ayar.aiprobe_home_sa.strip().lower()
    if not beklenen or not ayar.aiprobe_tp_audience:
        raise KodluHata(
            503, "kimlik_servisi_yok", "Yönetim ucu yapılandırılmamış (AIPROBE_HOME_SA eksik)"
        )
    tur, _, token = request.headers.get("authorization", "").partition(" ")
    if tur.lower() != "bearer" or not token.strip():
        raise KodluHata(401, "yetkisiz", "Servis kimliği gerekli", {"WWW-Authenticate": "Bearer"})
    try:
        iddialar = aiprobe.dogrulayici()(token.strip(), ayar.aiprobe_tp_audience)
    except Exception as exc:  # imza/aud/iss/süre: ayrıntı yalnız logda
        log.warning("kimlik-bagi: servis kimliği doğrulanamadı (%s)", type(exc).__name__)
        raise KodluHata(
            401, "yetkisiz", "Servis kimliği doğrulanamadı", {"WWW-Authenticate": "Bearer"}
        ) from exc
    email = str(iddialar.get("email") or "").strip().lower()
    if iddialar.get("email_verified") is not True or not hmac.compare_digest(
        email.encode("utf-8"), beklenen.encode("utf-8")
    ):
        log.warning("kimlik-bagi: yetkisiz servis hesabı reddedildi")
        raise KodluHata(403, "yasak", "Bu uç yalnız aiprobe-home servis kimliğine açıktır")
    return email


HomeServisi = Annotated[str, Depends(home_servisi)]
router = APIRouter(prefix="/admin/kimlik-bagi", tags=["admin"])


class Bag(BaseModel):
    external_uid: str
    app_user_id: uuid.UUID
    kullanici_adi: str
    rol: str
    olusturma: datetime


class Baglar(BaseModel):
    baglar: list[Bag]


class RolHesabi(BaseModel):
    id: uuid.UUID
    kullanici_adi: str
    rol: str
    ad_soyad: str | None
    bagli_uid: str | None


class RolHesaplari(BaseModel):
    hesaplar: list[RolHesabi]


class BagIn(BaseModel):
    external_uid: str = Field(min_length=1, max_length=128)
    app_user_id: uuid.UUID | None = None
    kullanici_adi: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _tek_hedef(self) -> BagIn:
        if (self.app_user_id is None) == (self.kullanici_adi is None):
            raise ValueError("app_user_id ya da kullanici_adi'dan tam olarak biri verilmeli")
        return self


def _bag_sorgusu():
    return select(
        KimlikBagi.external_uid,
        KimlikBagi.app_user_id,
        AppUser.kullanici_adi,
        AppUser.rol,
        KimlikBagi.olusturma,
    ).join(AppUser, AppUser.id == KimlikBagi.app_user_id)


@router.get("", response_model=Baglar)
def list_baglar(
    session: DbSession,
    _home: HomeServisi,
    external_uid: Annotated[str | None, Query(max_length=128)] = None,
) -> Baglar:
    q = _bag_sorgusu().order_by(KimlikBagi.external_uid, AppUser.rol)
    if external_uid is not None:
        q = q.where(KimlikBagi.external_uid == external_uid)
    return Baglar(baglar=[Bag.model_validate(r._asdict()) for r in session.execute(q)])


@router.get("/hesaplar", response_model=RolHesaplari)
def list_hesaplar(session: DbSession, _home: HomeServisi) -> RolHesaplari:
    rows = session.execute(
        select(
            AppUser.id,
            AppUser.kullanici_adi,
            AppUser.rol,
            AppUser.ad_soyad,
            KimlikBagi.external_uid.label("bagli_uid"),
        )
        .outerjoin(KimlikBagi, KimlikBagi.app_user_id == AppUser.id)
        .order_by(AppUser.rol, AppUser.kullanici_adi)
    )
    return RolHesaplari(hesaplar=[RolHesabi.model_validate(r._asdict()) for r in rows])


@router.put("", response_model=Bag)
def put_bag(body: BagIn, session: DbSession, home: HomeServisi) -> Bag:
    if body.app_user_id is not None:
        user = session.get(AppUser, body.app_user_id)
    else:
        user = session.scalars(
            select(AppUser).where(AppUser.kullanici_adi == (body.kullanici_adi or "").strip())
        ).first()
    if user is None:
        raise KodluHata(404, "bulunamadi", "Rol hesabı bulunamadı")
    mevcut = session.scalars(select(KimlikBagi).where(KimlikBagi.app_user_id == user.id)).first()
    if mevcut is not None and mevcut.external_uid != body.external_uid:
        raise KodluHata(409, "cakisma", "Bu rol hesabı başka bir kişiye bağlı")
    if mevcut is None:
        # Eşzamanlı iki PUT aynı hesaba farklı kişi bağlamaya çalışırsa `app_user_id UNIQUE`
        # ikincisini durdurur: 500 değil 409 (aynı kişiyse idempotent sonuç).
        try:
            with session.begin_nested():
                session.add(KimlikBagi(external_uid=body.external_uid, app_user_id=user.id))
                session.flush()
            # Hesabın bağdan önce açılmış yerel oturumları ve token'ları düşer: bundan sonra
            # hesaba yalnız AI Probe kişisi (oturum kontrolüyle) erişir.
            aiprobe.epoch_artir(session, [user.id])
        except IntegrityError:
            sahip = session.scalar(
                select(KimlikBagi.external_uid).where(KimlikBagi.app_user_id == user.id)
            )
            if sahip != body.external_uid:
                raise KodluHata(409, "cakisma", "Bu rol hesabı başka bir kişiye bağlı") from None
            row = session.execute(_bag_sorgusu().where(KimlikBagi.app_user_id == user.id)).one()
            return Bag.model_validate(row._asdict())
        audit_on_commit(
            session,
            AKTOR,
            "admin.kimlik_bagi.bagla",
            f"app_user:{user.id}",
            {"kimlik": body.external_uid, "kullanici": user.kullanici_adi, "cagiran": home},
        )
    row = session.execute(_bag_sorgusu().where(KimlikBagi.app_user_id == user.id)).one()
    return Bag.model_validate(row._asdict())


@router.delete("/{app_user_id}", status_code=204)
def delete_bag(app_user_id: uuid.UUID, session: DbSession, home: HomeServisi) -> Response:
    bag = session.scalars(select(KimlikBagi).where(KimlikBagi.app_user_id == app_user_id)).first()
    if bag is None:
        raise KodluHata(404, "bulunamadi", "Bağ bulunamadı")
    uid = bag.external_uid
    session.delete(bag)
    # Hesabın açık AI Probe oturumları ve token'ları düşer (epoch).
    aiprobe.epoch_artir(session, [app_user_id])
    audit_on_commit(
        session,
        AKTOR,
        "admin.kimlik_bagi.kaldir",
        f"app_user:{app_user_id}",
        {"kimlik": uid, "cagiran": home},
    )
    aiprobe.ONBELLEK.unut(uid)
    return Response(status_code=204)

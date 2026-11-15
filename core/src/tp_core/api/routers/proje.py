"""GET /projeler · PUT /proje — proje seçimi (TP-COK-PROJE-PLANI §6.2).

- `GET /projeler` → `{"enabled", "projects": [{"pid", "name", "org_name", "roles"}],
  "active": {"pid"}, "role_labels": {"<kod>": {"tr", "en"}}}`. Proje kipi kapalıyken
  (`TP_AUTH_MODE=local` ya da `TP_HOME_PROJECT` yok) `enabled: false` ve tek (varsayılan) proje;
  açıkken tek proje olsa da aynı biçim. `roles` kişinin o projedeki kullanılabilir (`acr`
  süzgeçli) TP rolleridir; rolü kalmayan proje listelenmez.
- `PUT /proje {"pid"}` → yanıt yeni `/auth/me`. Üyelik (Home `/v1/projects`, taze) + kurulumda etkin
  proje (`tp_proje.aktif`) + o projede ≥1 TP rolü denetlenir: proje yoksa 404 `proje_yok`, rol
  yoksa 403 `proje_rolu_yok`. Seçim `oturum.project_id` ve kişinin tüm bağlı hesaplarının
  `app_user.secili_proje`'sine yazılır; `_kurulum` zincirine `auth.proje_degisti`. Etkin rol hesabı
  yeni projede yoksa oturum o projedeki bir rol hesabına geçer (gerekirse JIT; önce mevcut rol
  sırası) — yeni `sid`, yeni çerez. CSRF: güvensiz yöntem, `api/csrf.py` Origin denetimi.

İkisi de `X-TP-Proje` ve "seçili projede rol" denetimlerinden muaftır (`auth.proje_secimi`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from tp_core.api.errors import KodluHata, proje_rolu_yok, proje_yok
from tp_core.api.routers.auth import me_yaniti, set_session_cookie
from tp_core.audit import append_audit
from tp_core.auth import aiprobe, yetki
from tp_core.auth.deps import Codec, CurrentUser, DbSession
from tp_core.auth.proje_secimi import ROL_ETIKETLERI_EN
from tp_core.auth.sessions import OturumDurumu, cookie_name, open_session, revoke_session
from tp_core.models import AppUser, Oturum
from tp_core.models.tp_proje import TpProje
from tp_core.proje import KURULUM, proje_icinde, varsayilan_pid
from tp_core.workflow.service import Principal

router = APIRouter(tags=["auth"])


class ProjeSec(BaseModel):
    pid: str = Field(min_length=1, max_length=64)


def _etiketler(kodlar: set[str]) -> dict[str, dict[str, str]]:
    return {
        k: {"tr": yetki.ROL_ETIKETLERI.get(k, k), "en": ROL_ETIKETLERI_EN.get(k, k)}
        for k in sorted(kodlar)
    }


def _durum(request: Request) -> OturumDurumu | None:
    return getattr(request.state, "oturum_durumu", None)


def _tek_proje(session: Session, user: Principal, enabled: bool) -> dict[str, Any]:
    pid = user.project_id or varsayilan_pid()
    satir = session.get(TpProje, pid)
    return {
        "enabled": enabled,
        "projects": [
            {
                "pid": pid,
                "name": (satir.ad if satir else None) or pid,
                "org_name": "",
                "roles": [user.rol],
            }
        ],
        "active": {"pid": pid},
        "role_labels": _etiketler({user.rol}),
    }


@router.get("/projeler")
def projeler(user: CurrentUser, request: Request, session: DbSession) -> dict[str, Any]:
    durum = _durum(request)
    uid = getattr(durum, "external_uid", None)
    if not aiprobe.proje_kipi():
        return _tek_proje(session, user, enabled=False)
    if uid is None:  # `both` kipinde yerel oturum: yalnız varsayılan proje
        return _tek_proje(session, user, enabled=True)
    try:
        liste = aiprobe.kullanici_projeleri(uid)
    except aiprobe.HomeUlasilamaz as exc:
        raise KodluHata(
            503, "kimlik_servisi_yok", "AI Probe kimlik servisine ulaşılamıyor"
        ) from exc
    acr = getattr(durum, "acr", None)
    projeler_: list[dict[str, Any]] = []
    kodlar: set[str] = set()
    for p in liste:
        roller = list(aiprobe.tp_rolleri(p.roller, acr))
        if not roller:
            continue
        kodlar |= set(roller)
        projeler_.append(
            {"pid": p.pid, "name": p.ad or p.kod or p.pid, "org_name": p.org_ad or "",
             "roles": roller}
        )  # fmt: skip
    return {
        "enabled": True,
        "projects": projeler_,
        "active": {"pid": user.project_id},
        "role_labels": _etiketler(kodlar),
    }


def _oturum(request: Request, session: Session, codec: Any) -> Oturum | None:
    veri = codec.loads(request.cookies.get(cookie_name(), "") or "")
    if veri is None:
        return None
    return session.scalar(
        select(Oturum).where(
            Oturum.id == veri.sid, Oturum.user_id == veri.user_id, Oturum.iptal_zamani.is_(None)
        )
    )


def _hedef_hesap(session: Session, uid: str, user: Principal, roller: tuple[str, ...]) -> AppUser:
    """Yeni projede kullanılacak rol hesabı: etkin rol oradaysa aynısı; değilse projedeki ilk
    rolün bağlı hesabı (yoksa JIT, kişi kilidiyle)."""
    if user.rol in roller:
        mevcut = session.get(AppUser, user.id)
        assert mevcut is not None
        return mevcut
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:u))"), {"u": f"tp-jit:{uid}"})
    hesaplar = {h.rol: h for h in aiprobe.bagli_hesaplar(session, uid)}
    for rol in roller:
        if rol in hesaplar:
            return hesaplar[rol]
    ornek = session.get(AppUser, user.id)
    assert ornek is not None
    yerel = ornek.kullanici_adi.removesuffix(f"-{ornek.rol}")
    return aiprobe.jit_hesap(session, uid, f"{yerel}@", ornek.ad_soyad or "", roller[0])


@router.put("/proje")
def proje_sec(
    body: ProjeSec, user: CurrentUser, request: Request, session: DbSession, codec: Codec
) -> JSONResponse:
    durum = _durum(request)
    uid = getattr(durum, "external_uid", None)
    onceki = user.project_id
    if not aiprobe.proje_kipi() or uid is None:
        if body.pid != (user.project_id or varsayilan_pid()):
            raise proje_yok()
        govde = me_yaniti(session, user, durum).model_dump(mode="json", exclude_unset=True)
        return JSONResponse(govde)
    try:
        liste = aiprobe.kullanici_projeleri(uid, taze=True)
    except aiprobe.HomeUlasilamaz as exc:
        raise KodluHata(
            503, "kimlik_servisi_yok", "AI Probe kimlik servisine ulaşılamıyor"
        ) from exc
    hedef = next((p for p in liste if p.pid == body.pid), None)
    if hedef is None:
        raise proje_yok()
    roller = aiprobe.tp_rolleri(hedef.roller, getattr(durum, "acr", None))
    if not roller:
        raise proje_rolu_yok()
    o = _oturum(request, session, codec)
    if o is None:
        raise KodluHata(401, "yetkisiz", "Oturumunuz geçersiz veya süresi dolmuş")
    hesap = _hedef_hesap(session, uid, user, roller)
    yanit_durumu = durum
    ids = [h.id for h in aiprobe.bagli_hesaplar(session, uid)]
    session.execute(update(AppUser).where(AppUser.id.in_(ids)).values(secili_proje=body.pid))
    hesap_degisti = hesap.id != user.id
    if hesap_degisti:
        veri = codec.loads(request.cookies.get(cookie_name(), "") or "")
        if veri is not None:
            revoke_session(session, veri)
        sid = open_session(
            session, hesap.id, codec.max_age_s, external_uid=uid, auth_time=o.auth_time,
            acr=o.acr, session_epoch_ms=o.session_epoch_ms, urunler=o.urunler,
            org_id=o.org_id, project_id=body.pid,
        )  # fmt: skip
    else:
        sid = o.id
        session.execute(update(Oturum).where(Oturum.id == o.id).values(project_id=body.pid))
    # Kurulum geneli olay: `_kurulum` zinciri (seçim kişiye aittir, projeye değil).
    with proje_icinde(KURULUM, kaynak="sistem"):
        append_audit(
            session.connection(),
            hesap.kullanici_adi,
            "auth.proje_degisti",
            f"app_user:{hesap.id}",
            {"onceki": onceki, "yeni": body.pid, "sid": str(sid),
             "hesap_degisti": hesap_degisti, "onceki_hesap": user.kullanici_adi},
        )  # fmt: skip
    if yanit_durumu is not None:
        yanit_durumu.project_id = body.pid
    yeni = Principal(
        hesap.id, hesap.kullanici_adi, hesap.rol, project_id=body.pid,
        roller=frozenset(roller),
    )  # fmt: skip
    govde = me_yaniti(session, yeni, yanit_durumu).model_dump(mode="json", exclude_unset=True)
    yanit = JSONResponse(govde)
    if hesap_degisti:
        set_session_cookie(yanit, codec, hesap, sid)
    return yanit

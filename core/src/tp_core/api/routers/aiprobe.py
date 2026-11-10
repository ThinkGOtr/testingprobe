"""AI Probe ortak girişi (TEKNIK-TASARIM §8.14, CONTRACT v1 "Ürün tarafı").

Yalnız `TP_AUTH_MODE=aiprobe|both`; `local` kipte bütün uçlar 404 (rota yok gibi).

- `GET  /auth/aiprobe/login?continue=` → `state` çerezi + 302 `{AIPROBE_ID_ORIGIN}/login`.
- `GET  /auth/aiprobe/callback?code=&state=` → state eşleşmesi → sunucudan takas → JIT → oturum
  (302 `continue`) ya da rol seçici (302 `/rol-sec?continue=`).
- `GET  /auth/aiprobe/hesaplar` → rol seçici / "Rol değiştir" listesi.
- `POST /auth/aiprobe/rol-sec {app_user_id}` → seçim çereziyle oturum.
- `POST /auth/aiprobe/rol-degistir {app_user_id}` → bağ + rol taze kontrolle doğrulanır, yeni sid.

Çerezler hep `__Host-` önekli (Secure, Path=/, alan adı yok); tek istisna CONTRACT'a göre yerel
geliştirme: düz `http://localhost` isteğinde state çerezi Secure'suz `aiprobe_state` adıyla
yazılır. Hata gövdesi `{"detail", "kod"}`;
`login` ve `callback` tarayıcı gezintisidir: istek `Accept: text/html` taşıyorsa aynı durum kodu
Türkçe bir hata sayfasıyla döner ("Tekrar dene" → yeniden giriş; JSON gösterilmez).
"""

from __future__ import annotations

import hmac
import html
import logging
import secrets
import uuid
from typing import Annotated, Any
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.api.errors import KodluHata
from tp_core.api.routers.auth import me_of, set_session_cookie
from tp_core.audit import audit_on_commit
from tp_core.auth import aiprobe
from tp_core.auth.deps import Codec, CurrentUser, DbSession
from tp_core.auth.display import display_name
from tp_core.auth.sessions import (
    SessionCodec,
    aiprobe_acik,
    cookie_name,
    open_session,
    revoke_session,
)
from tp_core.config import get_settings
from tp_core.models import AppUser, KimlikBagi, Oturum

router = APIRouter(prefix="/auth/aiprobe", tags=["auth"])
log = logging.getLogger(__name__)

STATE_COOKIE = "__Host-aiprobe_state"
# CONTRACT "Ürün tarafı": yerel http'de (yalnız localhost) Secure'suz ad.
STATE_COOKIE_YEREL = "aiprobe_state"
YEREL_HOSTLAR = frozenset({"localhost", "127.0.0.1", "::1"})
STATE_MAX_AGE_S = 600
SECIM_COOKIE = "__Host-tp_rol_secimi"
SECIM_SALT = "tp-rol-secimi-v1"
SECIM_MAX_AGE_S = 600
ROL_SEC_SAYFASI = "/rol-sec"


def _acik() -> None:
    if not aiprobe_acik():
        raise KodluHata(404, "bulunamadi", "Not Found")


router.dependencies.append(Depends(_acik))


def _yapilandirma_eksik() -> bool:
    ayar = get_settings()
    return not ayar.aiprobe_home_run_url or not ayar.aiprobe_id_origin


YAPILANDIRMA_YOK = "AI Probe girişi yapılandırılmamış (AIPROBE_* eksik)"


def _guvenli_cerez(ad: str) -> bool:
    return ad != STATE_COOKIE_YEREL


def _cerez(yanit: Response, ad: str, deger: str, max_age: int) -> None:
    yanit.set_cookie(
        ad,
        deger,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=_guvenli_cerez(ad),
        path="/",
    )


def _cerez_sil(yanit: Response, ad: str) -> None:
    yanit.delete_cookie(ad, path="/", httponly=True, samesite="lax", secure=_guvenli_cerez(ad))


def _state_cerezi(request: Request) -> str:
    """İsteğin kanalına göre state çerezinin adı: düz http + localhost → Secure'suz yerel ad.

    Okuma da aynı kuralla yapılır: https'de Secure'suz (araya girilerek yazılabilen) çerez kabul
    edilmez.
    """
    if request.url.scheme == "http" and request.url.hostname in YEREL_HOSTLAR:
        return STATE_COOKIE_YEREL
    return STATE_COOKIE


def _onceki_oturumu_kapat(request: Request, session: Session, codec: SessionCodec) -> bool:
    """Tarayıcıda önceki bir oturum çerezi varsa o `oturum` satırı iptal edilir (yeni girişte eski
    sid kopyası geçerli kalmasın). İptal edildiyse True."""
    raw = request.cookies.get(cookie_name())
    veri = codec.loads(raw) if raw else None
    return veri is not None and revoke_session(session, veri)


def _hata(status: int, kod: str, detail: str, *sil: str) -> JSONResponse:
    """İstisna değil yanıt: denetim kaydı commit edilir, tek kullanımlık çerezler silinir."""
    yanit = JSONResponse({"detail": detail, "kod": kod}, status_code=status)
    for ad in sil:
        _cerez_sil(yanit, ad)
    return yanit


HATA_BASLIGI = {
    "durum_uyusmuyor": "Giriş isteği doğrulanamadı",
    "giris_kodu_gecersiz": "Giriş bağlantısının süresi doldu",
    "kimlik_servisi_yok": "AI Probe kimlik servisine ulaşılamıyor",
    "org_reddi": "Kuruluşunuzun erişimi yok",
    "rol_yok": "Testing Probe'da rolünüz yok",
}


def _html_ister(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "").lower()


def _hata_sayfasi(
    request: Request, status: int, kod: str, detail: str, devam: str, *sil: str
) -> Response:
    """Tarayıcı gezintisinde Türkçe hata sayfası (aynı durum kodu); API istemcisine JSON.

    "Tekrar dene" göreli bağlantıdır (`login?continue=`): sayfa `…/auth/aiprobe/callback`
    (portal önekiyle `/api/auth/aiprobe/callback`) altında sunulduğu için önekten bağımsız olarak
    aynı dizindeki giriş ucuna gider. Betik yok (portal CSP'si `script-src 'self'`).
    """
    if not _html_ister(request):
        return _hata(status, kod, detail, *sil)
    baslik = html.escape(HATA_BASLIGI.get(kod, "Giriş yapılamadı"))
    tekrar = html.escape("login?" + urlencode({"continue": aiprobe.guvenli_continue(devam)}))
    govde = f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{baslik} · Testing Probe</title>
<style>
:root {{ color-scheme: light dark; --zemin: #f6f7fb; --kart: #fff; --metin: #0b0b14;
  --soluk: #4b5263; --kenar: #d9dbea; --vurgu: #4338ca; --vurgu-metin: #fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --zemin: #07070f; --kart: #0f0f1c; --metin: #f0f0ff;
  --soluk: #a3acbf; --kenar: #2e2e58; --vurgu: #6366f1; --vurgu-metin: #fff; }} }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
  background: var(--zemin); color: var(--metin); font: 16px/1.5 system-ui, sans-serif; }}
main {{ width: min(460px, 100%); background: var(--kart); border: 1px solid var(--kenar);
  border-radius: 14px; padding: 28px 24px; }}
h1 {{ margin: 0 0 8px; font-size: 1.35rem; }}
p {{ margin: 0 0 12px; }}
.kod {{ color: var(--soluk); font-size: .875rem; }}
.eylemler {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 20px; }}
.dugme {{ display: inline-block; padding: 10px 18px; border-radius: 10px; background: var(--vurgu);
  color: var(--vurgu-metin); text-decoration: none; font-weight: 600; }}
a {{ color: inherit; }}
a:focus-visible {{ outline: 2px solid var(--vurgu); outline-offset: 2px; }}
</style>
</head>
<body>
<main>
<h1>{baslik}</h1>
<p>{html.escape(detail)}.</p>
<p class="kod">Hata kodu: <code>{html.escape(kod)}</code></p>
<div class="eylemler">
<a class="dugme" href="{tekrar}">Tekrar dene</a>
<a href="/">Ana sayfa</a>
</div>
</main>
</body>
</html>
"""
    yanit = HTMLResponse(govde, status_code=status, headers={"Cache-Control": "no-store"})
    for ad in sil:
        _cerez_sil(yanit, ad)
    return yanit


# ------------------------------------------------------------------ giriş


@router.get("/login")
def login(
    request: Request, continue_: Annotated[str | None, Query(alias="continue")] = None
) -> Response:
    ayar = get_settings()
    devam = aiprobe.guvenli_continue(continue_)
    if _yapilandirma_eksik():
        return _hata_sayfasi(request, 503, "kimlik_servisi_yok", YAPILANDIRMA_YOK, devam)
    state = secrets.token_urlsafe(32)
    hedef = f"{ayar.aiprobe_id_origin.rstrip('/')}/login?" + urlencode(
        {"product": ayar.aiprobe_product_id, "state": state, "continue": devam}
    )
    yanit = RedirectResponse(hedef, status_code=302)
    _cerez(yanit, _state_cerezi(request), f"{state}|{quote(devam, safe='')}", STATE_MAX_AGE_S)
    return yanit


def _oturum_ac(
    session: Session,
    codec: SessionCodec,
    user: AppUser,
    devir_uid: str,
    kimlik: aiprobe.OturumKimligi,
    urunler: dict[str, list[str]] | None,
    yanit: Response,
    *,
    eylem: str = "auth.login",
    ozet: dict[str, Any] | None = None,
) -> None:
    sid = open_session(
        session,
        user.id,
        codec.max_age_s,
        external_uid=devir_uid,
        auth_time=kimlik.auth_time,
        acr=kimlik.acr,
        session_epoch_ms=kimlik.session_epoch_ms,
        urunler=urunler,
    )
    audit_on_commit(
        session,
        user.kullanici_adi,
        eylem,
        f"app_user:{user.id}",
        {"kanal": "aiprobe", "sid": sid, **(ozet or {})},
    )
    set_session_cookie(yanit, codec, user, sid)


@router.get("/callback")
def callback(
    request: Request,
    session: DbSession,
    codec: Codec,
    code: Annotated[str, Query(max_length=512)] = "",
    state: Annotated[str, Query(max_length=256)] = "",
) -> Response:
    state_adi = _state_cerezi(request)
    raw = request.cookies.get(state_adi) or ""
    cerez_state, _, cerez_devam = raw.partition("|")
    devam = aiprobe.guvenli_continue(unquote(cerez_devam) or "/")

    def hata(status: int, kod: str, detail: str) -> Response:
        return _hata_sayfasi(request, status, kod, detail, devam, state_adi)

    if _yapilandirma_eksik():
        return hata(503, "kimlik_servisi_yok", YAPILANDIRMA_YOK)
    if not cerez_state or not state or not hmac.compare_digest(cerez_state, state):
        log.warning("AI Probe girişi: state uyuşmadı (login CSRF ya da süresi dolmuş çerez)")
        audit_on_commit(session, aiprobe.AKTOR, "auth.aiprobe_rejected", None, {"neden": "state"})
        return hata(400, "durum_uyusmuyor", "Giriş isteği doğrulanamadı; yeniden deneyin")
    try:
        devir = aiprobe.home().redeem(code)
    except aiprobe.GecersizKod:
        audit_on_commit(session, aiprobe.AKTOR, "auth.aiprobe_rejected", None, {"neden": "kod"})
        return hata(400, "giris_kodu_gecersiz", "Giriş kodu geçersiz veya süresi dolmuş")
    except aiprobe.HomeUlasilamaz:
        return hata(503, "kimlik_servisi_yok", "AI Probe kimlik servisine ulaşılamıyor")
    if not hmac.compare_digest(devir.state, state):
        audit_on_commit(session, aiprobe.AKTOR, "auth.aiprobe_rejected", None, {"neden": "state"})
        return hata(400, "durum_uyusmuyor", "Giriş isteği doğrulanamadı; yeniden deneyin")
    if not aiprobe.izinli_org(devir.org):
        audit_on_commit(
            session, aiprobe.AKTOR, "auth.aiprobe_rejected", f"kimlik:{devir.uid}", {"neden": "org"}
        )
        return hata(403, "org_reddi", "Bu kuruluşun Testing Probe erişimi yok")
    roller = aiprobe.tp_rolleri(devir.roles)
    if not roller:
        audit_on_commit(
            session, aiprobe.AKTOR, "auth.aiprobe_rejected", f"kimlik:{devir.uid}", {"neden": "rol"}
        )
        return hata(403, "rol_yok", "Testing Probe'da rolünüz yok")

    aiprobe.jit_hesaplar(session, devir, roller)
    adaylar = [h for h in aiprobe.bagli_hesaplar(session, devir.uid) if h.rol in roller]
    kimlik = aiprobe.OturumKimligi(devir.auth_time, devir.acr, devir.session_epoch_ms)
    onceki_kapandi = _onceki_oturumu_kapat(request, session, codec)
    if len(adaylar) == 1:
        yanit: Response = RedirectResponse(devam, status_code=302)
        _oturum_ac(session, codec, adaylar[0], devir.uid, kimlik, devir.products, yanit,
                   ozet={"acr": devir.acr})  # fmt: skip
        _cerez_sil(yanit, state_adi)
        return yanit
    secim = {
        "x": devir.uid,
        "t": devir.auth_time,
        "r": list(roller),
        "h": [str(h.id) for h in adaylar],
        "c": devam,
        "a": devir.acr,
        "e": devir.session_epoch_ms,
        "p": devir.products,
    }
    yanit = RedirectResponse(f"{ROL_SEC_SAYFASI}?continue={quote(devam, safe='')}", 302)
    _cerez(yanit, SECIM_COOKIE, codec.dumps_signed(SECIM_SALT, secim), SECIM_MAX_AGE_S)
    _cerez_sil(yanit, state_adi)
    if onceki_kapandi:
        _cerez_sil(yanit, cookie_name())
    return yanit


# ------------------------------------------------------------------ rol seçici / rol değiştir


class Hesap(BaseModel):
    id: uuid.UUID
    kullanici_adi: str
    rol: str
    gorunen_ad: str


class Hesaplar(BaseModel):
    hesaplar: list[Hesap]
    aktif_id: uuid.UUID | None = None


class HesapSec(BaseModel):
    app_user_id: uuid.UUID


def _secim(request: Request, codec: SessionCodec) -> dict[str, Any] | None:
    raw = request.cookies.get(SECIM_COOKIE)
    veri = codec.loads_signed(SECIM_SALT, raw, SECIM_MAX_AGE_S) if raw else None
    if not isinstance(veri, dict) or not {"x", "t", "r", "h", "c"} <= veri.keys():
        return None
    return veri


def _hesap(u: AppUser) -> Hesap:
    ad = {u.kullanici_adi.lower(): u.ad_soyad} if u.ad_soyad else None
    return Hesap(
        id=u.id,
        kullanici_adi=u.kullanici_adi,
        rol=u.rol,
        gorunen_ad=display_name(u.kullanici_adi, u.rol, ad),
    )


def _oturum_satiri(request: Request, session: Session, codec: SessionCodec) -> Oturum | None:
    raw = request.cookies.get(cookie_name())
    veri = codec.loads(raw) if raw else None
    if veri is None:
        return None
    return session.scalar(
        select(Oturum).where(
            Oturum.id == veri.sid,
            Oturum.user_id == veri.user_id,
            Oturum.iptal_zamani.is_(None),
            Oturum.external_uid.is_not(None),
        )
    )


@router.get("/hesaplar", response_model=Hesaplar)
def hesaplar(request: Request, session: DbSession, codec: Codec) -> JSONResponse:
    secim = _secim(request, codec)
    if secim is not None:
        izinli = set(secim["h"])
        liste = [
            _hesap(h)
            for h in aiprobe.bagli_hesaplar(session, secim["x"])
            if str(h.id) in izinli and h.rol in secim["r"]
        ]
        govde = Hesaplar(hesaplar=liste).model_dump(mode="json")
        return JSONResponse(govde | {"continue": aiprobe.guvenli_continue(secim["c"])})
    # Etkin AI Probe oturumu: "Rol değiştir" menüsü (oturumun kendisi current_user ile doğrulanır).
    from tp_core.auth.deps import current_user

    p = current_user(request, Response(), session, codec)
    o = _oturum_satiri(request, session, codec)
    if o is None or o.external_uid is None:
        raise KodluHata(403, "yasak", "Yalnız AI Probe oturumunda kullanılabilir")
    try:
        roller: frozenset[str] | None = aiprobe.kontrol_et(
            o.external_uid, aiprobe.OturumKimligi.of(o)
        ).roles
    except aiprobe.HomeUlasilamaz:
        roller = None
    liste = [
        _hesap(h)
        for h in aiprobe.bagli_hesaplar(session, o.external_uid)
        if roller is None or h.rol in roller
    ]
    return JSONResponse(Hesaplar(hesaplar=liste, aktif_id=p.id).model_dump(mode="json"))


@router.post("/rol-sec")
def rol_sec(body: HesapSec, request: Request, session: DbSession, codec: Codec) -> JSONResponse:
    secim = _secim(request, codec)
    if secim is None:
        raise KodluHata(401, "yetkisiz", "Rol seçiminin süresi doldu; yeniden giriş yapın")
    hedef = session.get(AppUser, body.app_user_id)
    bag = session.scalar(
        select(KimlikBagi.external_uid).where(KimlikBagi.app_user_id == body.app_user_id)
    )
    if (
        hedef is None
        or str(hedef.id) not in secim["h"]
        or bag != secim["x"]
        or hedef.rol not in secim["r"]
    ):
        raise KodluHata(403, "yasak", "Bu rol hesabı size bağlı değil")
    kimlik = aiprobe.OturumKimligi(
        int(secim["t"]), str(secim.get("a") or "1"), int(secim["e"]) if secim.get("e") else None
    )
    # Seçim çerezi 10 dk geçerli: bu arada AI Probe'da iptal/rol kaldırma olmuş olabilir; oturum
    # açmadan önce taze kontrol.
    try:
        sonuc = aiprobe.kontrol_et(secim["x"], kimlik, taze=True)
    except aiprobe.HomeUlasilamaz as exc:
        raise KodluHata(
            503, "kimlik_servisi_yok", "AI Probe kimlik servisine ulaşılamıyor"
        ) from exc
    if not sonuc.valid:
        aiprobe.iptal_et(secim["x"], None, sonuc.reason or "gecersiz")
        return _hata(401, "yetkisiz", "Oturumunuz sonlandırıldı; yeniden giriş yapın", SECIM_COOKIE)
    if hedef.rol not in sonuc.roles:
        raise KodluHata(403, "yasak", "Bu rol AI Probe hesabınızda tanımlı değil")
    _onceki_oturumu_kapat(request, session, codec)
    yanit = JSONResponse(
        me_of(session, hedef.id, hedef.kullanici_adi, hedef.rol).model_dump(mode="json")
        | {"continue": aiprobe.guvenli_continue(secim["c"])}
    )
    _oturum_ac(session, codec, hedef, secim["x"], kimlik, sonuc.products or secim.get("p"), yanit,
               ozet={"acr": kimlik.acr, "secim": True})  # fmt: skip
    _cerez_sil(yanit, SECIM_COOKIE)
    return yanit


@router.post("/rol-degistir")
def rol_degistir(
    body: HesapSec, request: Request, session: DbSession, codec: Codec, user: CurrentUser
) -> JSONResponse:
    o = _oturum_satiri(request, session, codec)
    if o is None or o.external_uid is None:
        raise KodluHata(403, "yasak", "Rol değiştirme yalnız AI Probe oturumunda kullanılabilir")
    uid, kimlik = o.external_uid, aiprobe.OturumKimligi.of(o)
    hedef = session.get(AppUser, body.app_user_id)
    bag = session.scalar(
        select(KimlikBagi.external_uid).where(KimlikBagi.app_user_id == body.app_user_id)
    )
    if hedef is None or bag != uid:
        raise KodluHata(403, "yasak", "Bu rol hesabı size bağlı değil")
    try:
        sonuc = aiprobe.kontrol_et(uid, kimlik, taze=True)
    except aiprobe.HomeUlasilamaz as exc:
        raise KodluHata(
            503, "kimlik_servisi_yok", "AI Probe kimlik servisine ulaşılamıyor"
        ) from exc
    if not sonuc.valid:
        # Bu isteğin işlemi oturum satırını kilitlemiş olabilir: iptal aynı işlemde yazılır ve
        # yanıt istisna değil (commit edilir).
        ids = [h.id for h in aiprobe.bagli_hesaplar(session, uid)]
        aiprobe.epoch_artir(session, ids)
        audit_on_commit(session, aiprobe.AKTOR, "auth.aiprobe_revoked", f"kimlik:{uid}",
                        {"neden": sonuc.reason or "gecersiz"})  # fmt: skip
        aiprobe.ONBELLEK.unut(uid)
        yanit = _hata(401, "yetkisiz", "Oturumunuz sonlandırıldı; yeniden giriş yapın")
        yanit.delete_cookie(cookie_name(), path="/", httponly=True, samesite="lax", secure=True)
        return yanit
    if hedef.rol not in sonuc.roles:
        raise KodluHata(403, "yasak", "Bu rol AI Probe hesabınızda tanımlı değil")
    veri = codec.loads(request.cookies.get(cookie_name(), ""))
    if veri is not None:
        revoke_session(session, veri)
    yanit = JSONResponse(
        me_of(session, hedef.id, hedef.kullanici_adi, hedef.rol).model_dump(mode="json")
    )
    _oturum_ac(session, codec, hedef, uid, kimlik, sonuc.products or o.urunler, yanit,
               eylem="auth.role_switch", ozet={"onceki": user.kullanici_adi})  # fmt: skip
    return yanit

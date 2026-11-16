"""FastAPI bağımlılıkları: veritabanı oturumu, oturumdaki kullanıcı, rol ve bearer token kontrolü.

`DbSession` işlemi **yanıt gönderilmeden önce** commit eder (scope="function"): onay gibi kayıtlar
commit edilemezse istemci başarı yanıtı almaz.

Çok proje (TP-COK-PROJE-PLANI §2.1, §6.1): `current_user` oturumun seçili projesini ve o projedeki
rolleri çözer (`Principal.project_id`, `Principal.roller`; `auth.proje_secimi`), `X-TP-Proje`
tutarlılığını (409 `proje_degisti`) ve seçili projede rolü (403 `proje_rolu_yok`) denetler.
`CurrentUser` (ve onu kullanan `yetki.izin(...)`) `kullanici_baglami` üzerinden isteğin geri
kalanını `proje_icinde(pid, kaynak="oturum")` içinde koşturur: senkron bağımlılıklar thread
havuzunda çözüldüğünden bağlam eşzamansız bir `yield` bağımlılığında kurulur (uç ve
`DbSession`'ın commit'i — scope="function", bağlamdan önce kapanır — aynı bağlamı görür).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
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
from tp_core.proje import proje_icinde
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
    from tp_core.auth import proje_secimi  # döngü: proje_secimi → aiprobe → yetki → deps

    pid = proje_secimi.oturum_projesi(user, durum.project_id, durum.external_uid is not None)
    roller = proje_secimi.proje_rolleri(durum.external_uid, pid, durum.acr, user.rol)
    p = Principal(user.id, user.kullanici_adi, user.rol, project_id=pid, roller=roller)
    request.state.principal = p
    yol = request.url.path
    proje_secimi.denetle(
        yol, proje_secimi.istek_projesi(yol, request.headers, request.query_params), pid,
        user.rol, roller,
    )  # fmt: skip
    return p


async def kullanici_baglami(
    user: Annotated[Principal, Depends(current_user)],
) -> AsyncIterator[Principal]:
    """Oturum kullanıcısı + isteğin geri kalanı için proje bağlamı (`kaynak="oturum"`)."""
    assert user.project_id is not None
    with proje_icinde(user.project_id, kaynak="oturum"):
        yield user


CurrentUser = Annotated[Principal, Depends(kullanici_baglami)]


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


def require_token(kapsam: str) -> Callable[..., AsyncIterator[Principal]]:
    """MCP kanalı: `Authorization: Bearer tpt_...` başlığındaki kapsamlı token'ı doğrular; istek
    token'ın bağlı olduğu projenin bağlamında (`kaynak="token"`) sürer."""

    def dogrula(request: Request, session: DbSession) -> Principal:
        baslik = request.headers.get("authorization", "")
        tur, _, deger = baslik.partition(" ")
        p = verify_bearer(session, deger.strip() if tur.lower() == "bearer" else None, kapsam)
        if p is None:
            raise HTTPException(
                401, "Geçersiz veya süresi dolmuş token", headers={"WWW-Authenticate": "Bearer"}
            )
        request.state.principal = p
        return p

    dogrula.__name__ = f"require_token_{kapsam}_dogrula"

    # Varsayılan değerle (Annotated değil): `from __future__ import annotations` altında yerel
    # `dogrula` adı dize ek açıklamadan çözülemez.
    async def kontrol(p: Principal = Depends(dogrula)) -> AsyncIterator[Principal]:  # noqa: B008
        assert p.project_id is not None
        with proje_icinde(p.project_id, kaynak="token"):
            yield p

    kontrol.__name__ = f"require_token_{kapsam}"
    return kontrol

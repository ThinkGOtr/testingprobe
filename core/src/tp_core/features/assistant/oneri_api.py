"""Öneri uçları (AI-ASISTAN-PLANI §9, §17): `GET /assistant/suggestions` ve
`POST /assistant/suggestions/{kural_id}/feedback`.

Modelsizdir: worker gerekmez, model kapalıyken de çalışır, `ai_call` yazmaz. Rol oturumdan gelir
(`CurrentUser`: yalnız çerez; `tpt_` bearer 401). Liste ucu yalnız okur (tek yazım, ayrı bağlantıda
hemen commit edilen hız sayacıdır);
geri bildirim ucu yalnız `asistan_oneri_geri_bildirim`'e satır ekler.

`router` asistan uçlarıyla birlikte `features/assistant/api.py`'de bağlanır
(`router.include_router(oneri_api.router)`); bu modül kendi başına keşfedilmez.
`TP_ASISTAN_ONERI=0` iken iki uç da 404 `bulunamadi` (portal yetenek kapısı düğmeyi gizler).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from tp_core.api.deps import CurrentUser, DbSession
from tp_core.api.errors import KodluHata
from tp_core.features.assistant import oneri
from tp_core.features.assistant.hiz import (
    KOVA_ONERI_GERI_BILDIRIM,
    KOVA_ONERI_LISTE,
    kova_kontrol,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])

KAPALI_MESAJI = "Öneriler bu kurulumda kapalı"
HIZ_MESAJI = "Çok sık istek gönderildi; biraz sonra yeniden deneyin"


def _etkin() -> None:
    if not oneri.oneri_etkin():
        raise KodluHata(404, "bulunamadi", KAPALI_MESAJI)


def _hiz(session: Session, kova: str, user: CurrentUser) -> None:
    """Sayaç ayrı, hemen commit edilen kısa bir bağlantıda artar: isteğin kendi işlemi 404/422
    ile geri alınsa da istek sayılmış olur (geçersiz rota/varlık istekleri de sınıra takılır)."""
    with session.get_bind().begin() as conn:
        izinli = kova_kontrol(conn, kova, kullanici_id=user.id)
    if not izinli:
        raise KodluHata(429, "hiz_siniri", HIZ_MESAJI)


@router.get("/suggestions")
def suggestions(
    session: DbSession,
    user: CurrentUser,
    rota: Annotated[str, Query(min_length=1, max_length=300)],
    varlik_tur: Annotated[str | None, Query(max_length=40)] = None,
    varlik_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    """Bu ekranda bu rolün şimdi yapması gereken işler (kural tabanlı; öncelik sırasıyla)."""
    _etkin()
    _hiz(session, KOVA_ONERI_LISTE, user)
    try:
        ekran = oneri.ekran_coz(user, rota, varlik_tur, varlik_id)
        anahtar = (user.id, user.rol, ekran.rota.kalip, ekran.varlik_tur, ekran.varlik_id)
        onceki = oneri.ONBELLEK.al(anahtar)
        if onceki is not None:
            return onceki
        sonuc = oneri.oneriler_ekran(session, user, ekran)
    except oneri.EkranBulunamadi:
        raise HTTPException(404, "Ekran bulunamadı") from None
    except oneri.VarlikBulunamadi:
        raise HTTPException(404, "Kayıt bulunamadı") from None
    oneri.ONBELLEK.koy(anahtar, sonuc)
    return sonuc


class GeriBildirim(BaseModel):
    # `varlik_durum` gibi istemci alanları yok sayılır: durum sunucuda hesaplanır.
    model_config = ConfigDict(extra="ignore")

    deger: Literal[-1, 1, 2]
    varlik_id: uuid.UUID | None = None
    jira_anahtari: str | None = Field(default=None, max_length=64)


@router.post("/suggestions/{kural_id}/feedback")
def suggestion_feedback(
    kural_id: Annotated[str, Path(max_length=100)],
    body: GeriBildirim,
    session: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Gizle (-1) / Faydalı (1) / Yaptım (2, isteğe bağlı Jira anahtarıyla)."""
    _etkin()
    _hiz(session, KOVA_ONERI_GERI_BILDIRIM, user)
    try:
        sonuc = oneri.geri_bildirim_yaz(
            session, user, kural_id, body.deger, body.varlik_id, body.jira_anahtari
        )
    except oneri.KuralBulunamadi:
        raise HTTPException(422, "Bilinmeyen öneri kuralı") from None
    except oneri.VarlikBulunamadi:
        raise HTTPException(404, "Kayıt bulunamadı") from None
    except oneri.GecersizGeriBildirim as exc:
        # Metin `oneri`'deki sabit Türkçe iletidir (istisna adı ya da ham girdi değil).
        raise HTTPException(422, str(exc)) from None
    # "Yaptım" tüm rollerde bastırır: eski sonuçlar 10 sn beklemesin.
    oneri.ONBELLEK.temizle()
    return sonuc

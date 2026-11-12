"""Otomasyon uçları (specs/013-sprint-otomasyonu §3.1, §3.4).

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/automation-settings` | herkes — `{anahtar: {...}, model_kipi, replay, ortam}` |
| PUT | `/automation-settings/{anahtar}` | analyst, engineer — gövde kısmi nesne → güncel hepsi |

Ayar değil, yazılamaz (K23; portalın REPLAY uyarısı): üst düzey `model_kipi:
live|replay|record|null`, `replay: bool` ve ayrıntı `ortam: {model_kipi, replay, jira_sim,
demo_ortami}`.

`jira_tetik` gövdesinde `durum` alanı varsa yalnız engineer (K14; analist 403). `jira_tetik`
yazılınca bekleyen tetik turu öne çekilir (`jira_tetik.ayar_degisti`): tetik açıldıysa ya da durum
değiştiyse hemen, değilse en geç yeni `aralik_s` sonra.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.otomasyon import ayarlar, jira_tetik
from tp_core.workflow.service import Principal

router = APIRouter(tags=["otomasyon"])

AyarYoneticisi = Annotated[Principal, Depends(require_role("analyst", "engineer"))]


@router.get("/automation-settings")
def ayarlari_getir(session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    return _govde(session)


def _govde(session: Any) -> dict[str, Any]:
    ortam = ayarlar.ortam(session)
    return {
        **ayarlar.hepsi(session),
        "model_kipi": ortam["model_kipi"],
        "replay": ortam["replay"],
        "ortam": ortam,
    }


@router.put("/automation-settings/{anahtar}")
def ayari_guncelle(
    anahtar: str,
    session: DbSession,
    user: AyarYoneticisi,
    deger: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    if anahtar not in ayarlar.VARSAYILAN:
        raise HTTPException(404, f"Bilinmeyen otomasyon ayarı: {anahtar}")
    if anahtar == ayarlar.JIRA_TETIK and "durum" in deger and user.rol != "engineer":
        raise HTTPException(403, "Jira tetiğinin durum adını yalnız Otomasyon mühendisi değiştirir")
    onceki = ayarlar.oku(session, anahtar)
    try:
        yeni = ayarlar.yaz(session, anahtar, deger, user.kullanici_adi)
    except ValueError as exc:
        raise HTTPException(422, f"Geçersiz ayar: {exc}") from exc
    if anahtar == ayarlar.JIRA_TETIK:
        jira_tetik.ayar_degisti(
            session.connection(),
            hemen=(yeni.acik and not onceki.acik) or yeni.durum != onceki.durum,
            aralik_s=yeni.aralik_s,
        )
    return _govde(session)

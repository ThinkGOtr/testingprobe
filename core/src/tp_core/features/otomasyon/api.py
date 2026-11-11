"""Otomasyon uçları (specs/013-sprint-otomasyonu §3.1, §3.4).

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/automation-settings` | herkes — `{anahtar: {...değerler, guncelleyen, guncelleme}}` |
| PUT | `/automation-settings/{anahtar}` | analyst, engineer — gövde kısmi nesne → güncel hepsi |
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.otomasyon import ayarlar
from tp_core.workflow.service import Principal

router = APIRouter(tags=["otomasyon"])

AyarYoneticisi = Annotated[Principal, Depends(require_role("analyst", "engineer"))]


@router.get("/automation-settings")
def ayarlari_getir(session: DbSession, _user: CurrentUser) -> dict[str, dict[str, Any]]:
    return ayarlar.hepsi(session)


@router.put("/automation-settings/{anahtar}")
def ayari_guncelle(
    anahtar: str,
    session: DbSession,
    user: AyarYoneticisi,
    deger: Annotated[dict[str, Any], Body()],
) -> dict[str, dict[str, Any]]:
    if anahtar not in ayarlar.VARSAYILAN:
        raise HTTPException(404, f"Bilinmeyen otomasyon ayarı: {anahtar}")
    try:
        ayarlar.yaz(session, anahtar, deger, user.kullanici_adi)
    except ValueError as exc:
        raise HTTPException(422, f"Geçersiz ayar: {exc}") from exc
    return ayarlar.hepsi(session)


# Ş2 uçları buraya (jira_tetik.py router'ı: router.include_router(...)).

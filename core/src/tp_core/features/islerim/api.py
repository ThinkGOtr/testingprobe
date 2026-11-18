"""İşlerim ve kayıt yeri uçları (TP UX denetimi IA-01/IA-02/IA-05).

| Yöntem | Yol | İzin |
|---|---|---|
| GET | `/work-queue` | `dashboard.read` — rolün bekleyen işleri (`benim`), ekipte bekleyenler (`ekip`), menü rozet sayıları (`menu`) |
| GET | `/locate?tur=&id=` | `dashboard.read` — kaydın hangi projede olduğu (yalnız kişinin rolü olan projeler) |

`/work-queue` yanıtı: `{rol, rol_etiketi, toplam, ekip_toplam, benim: [Grup], ekip: [Grup +
kisiler], menu: {rota: sayı}}`; Grup `{anahtar, tur, rol, rol_etiketi, baslik, sonraki_adim, sayi,
oge_sayisi, ogeler: [{id, tur, etiket, neden, rota, zaman, jira_key, sayi}]}`. Rolün okuyamadığı
türde (`TUR_IZNI`) `ogeler` boştur, sayılar kalır.

`/locate` yanıtı: `{bulundu, ayni_proje, proje: {pid, name} | null}`. Kayıt kişinin erişemediği
bir projedeyse `bulundu: false` (varlığı sızdırılmaz).
"""  # noqa: E501

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.islerim import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["islerim"])

Okur = Annotated[Principal, Depends(izin("dashboard.read"))]

KayitTuru = Literal["requirement", "case", "script", "run", "failure", "bug_draft"]


@router.get("/work-queue")
def work_queue(session: DbSession, user: Okur) -> dict[str, Any]:
    return service.is_kuyrugu(session, user.rol)


@router.get("/locate")
def locate(
    tur: KayitTuru, id: uuid.UUID, request: Request, session: DbSession, user: Okur
) -> dict[str, Any]:
    from tp_core.api.routers.proje import projeler
    from tp_core.features.assistant.tools.probe import MODELLER
    from tp_core.proje.bul import kayit_projesi

    yok: dict[str, Any] = {"bulundu": False, "ayni_proje": False, "proje": None}
    pid = kayit_projesi(session, MODELLER[tur], id)
    if pid is None:
        return yok
    liste = projeler(user, request, session)
    aktif = (liste.get("active") or {}).get("pid") or user.project_id
    for p in liste.get("projects") or []:
        if p.get("pid") == pid:
            return {
                "bulundu": True,
                "ayni_proje": pid == aktif,
                "proje": {"pid": pid, "name": p.get("name") or pid},
            }
    return yok

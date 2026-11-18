"""Kaydın projesi (TP UX denetimi IA-05): başka projeye ait bir kaydın bağlantısı açıldığında
"Bu kayıt X projesinde — projeye geç" diyebilmek için kaydın `project_id`'si okunur.

Yalnız `project_id` döner (içerik değil); çağıran (`GET /locate`) sonucu kişinin rolü olan
projelerle süzer. Bilinçli kurulum geneli okuma: `tum_projeler` kaçışı (bu modül izinli listede).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def kayit_projesi(session: Session, model: Any, kimlik: uuid.UUID) -> str | None:
    return session.execute(
        select(model.project_id).where(model.id == kimlik).execution_options(tum_projeler=True)
    ).scalar_one_or_none()

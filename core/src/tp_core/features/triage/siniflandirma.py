"""İnsan sınıflandırması (TP UX denetimi IA-16): kuralın ya da AI'ın sınıflandıramadığı
("Belirsiz" / REPLAY-MISS) başarısızlığa Test Uzmanı ya da Otomasyon Mühendisi sınıf verir.

- `sinif`: `FAILURE_SINIF` − {`unknown`}; `gerekce` zorunlu. `karar_kaynagi = "human"` (0049).
- `product_defect` → bug taslağı açılır (`bugs.service.create_draft_from_failure`; idempotent) ve
  başarısızlık Test Uzmanının bug kararı kuyruğuna düşer. `test_maintenance` / `flaky` /
  `environment` → Otomasyon Mühendisi kuyruğu (mevcut kapı mantığı, `oneri_durumu = none`).
- Onarım PR'ı açık/birleşmiş ya da bug taslağı bağlı başarısızlık başka sınıfa alınamaz (409):
  önce o karar geri alınır.
- Denetim: `failure.classified` (önce/sonra sınıf, gerekçe, aktör); olay: `failure.classified`.
"""

from __future__ import annotations

import uuid
from typing import Any

from tp_core.audit import audit_on_commit
from tp_core.events import publish_tx
from tp_core.models import BugDraft, Failure
from tp_core.models.enums import FAILURE_SINIF
from tp_core.workflow.service import Principal, WorkflowError

INSAN_SINIFLARI = FAILURE_SINIF - {"unknown"}
GEREKCE_UST = 2000


class SiniflandirmaBulunamadi(WorkflowError):
    status_code = 404


class SiniflandirmaReddi(WorkflowError):
    status_code = 409


def classify(
    session: Any, failure_id: uuid.UUID, user: Principal, sinif: str, gerekce: str
) -> dict[str, Any]:
    from tp_core.features.bugs.service import create_draft_from_failure
    from tp_core.features.triage.service import bug_taslagi_id

    if sinif not in INSAN_SINIFLARI:
        raise SiniflandirmaReddi(f"Geçersiz sınıf: {sinif}")
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise SiniflandirmaReddi("Gerekçe zorunlu")
    f = session.get(Failure, failure_id, with_for_update=True)
    if f is None:
        raise SiniflandirmaBulunamadi("Triage kaydı bulunamadı")
    once = f.sinif
    if f.oneri_durumu in ("pr_open", "merged") and sinif != once:
        raise SiniflandirmaReddi(
            "Bu hata için onarım PR'ı açık ya da birleşmiş; sınıf değiştirilemez"
        )
    mevcut_bug = bug_taslagi_id(session, f.id)
    if mevcut_bug is not None and sinif != "product_defect":
        taslak = session.get(BugDraft, mevcut_bug)
        if taslak is not None and taslak.durum != "dismissed":
            raise SiniflandirmaReddi(
                "Bu hataya bağlı bir bug taslağı var; önce taslağı reddedin, sonra sınıfı "
                "değiştirin"
            )
    f.sinif = sinif
    if sinif != once:
        f.alt_tur = None
    f.karar_kaynagi = "human"
    f.gerekce = gerekce[:GEREKCE_UST]
    if sinif == "product_defect":
        f.oneri_turu = "bug_draft"
    elif f.oneri_turu == "bug_draft":
        f.oneri_turu = "none"
    session.flush()
    bug_id: uuid.UUID | None = None
    if sinif == "product_defect":
        bug_id = create_draft_from_failure(session, f.id, aktor=user.kullanici_adi)
    audit_on_commit(
        session,
        user.kullanici_adi,
        "failure.classified",
        f"failure:{f.id}",
        {
            "once": once,
            "sonra": sinif,
            "gerekce": f.gerekce,
            "rol": user.rol,
            "bug_draft_id": str(bug_id) if bug_id else None,
        },
    )
    publish_tx(
        session.connection(),
        "failure.classified",
        {
            "id": str(f.id),
            "failure_id": str(f.id),
            "run_id": str(f.run_id),
            "test_adi": f.test_adi,
            "sinif": f.sinif,
            "alt_tur": f.alt_tur,
            "karar_kaynagi": f.karar_kaynagi,
            "oneri_turu": f.oneri_turu,
        },
    )
    return {"bug_draft_id": str(bug_id) if bug_id else None}

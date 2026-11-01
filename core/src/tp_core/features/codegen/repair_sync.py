"""GitHub kipi PR senkronu: locator onarım PR'larının (`script.tur = 'locator_fix'`) forge durumu.

GitHub kipinde App'in merge yetkisi yoktur (§14); onarım PR'ı da GitHub arayüzünde insan
tarafından merge edilir/kapatılır. `codegen.pr_sync` bu PR'ları codegen semantiğiyle
(`ScriptCodegen` satırı, `codegen.merged`) işleyemez; burada onarım semantiğiyle işlenir —
yerel kipteki `repair.run_merge` ile aynı sonuç:

- `merged` → dış insan onayı `review` (`harici_onaylayan`, `kanal='github'`), script `merged`,
  PR kaydı, hata ve kardeşlerinde `oneri_durumu='merged'`, `repair.merged` denetimi,
  `pr.merged` + `repair.merged` olayları, merge sonrası `push` CI'ı.
- `closed` → script `closed`, PR kaydı `closed`, hata ve kardeşlerinde `oneri_durumu='rejected'`,
  `repair.pr_closed_external` denetimi (onarım yeniden istenebilir).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.events.bus import publish_tx
from tp_core.models import Failure, PullRequest, Script, session_scope
from tp_core.workflow.jobs import PermanentJobError
from tp_core.workflow.service import SYSTEM, approved_hash_matches, transition

ONARIM_TURU = "locator_fix"


def _oneri_durumu_yaz(s: Session, fid: uuid.UUID | None, durum: str) -> int:
    """Hata ve aynı locator değişikliğini öneren kardeşlerinin `oneri_durumu` alanı."""
    if fid is None:
        return 0
    from tp_core.features.repair.service import kardes_failure_ids

    f = s.get(Failure, fid, with_for_update=True)
    if f is None:
        return 0
    f.oneri_durumu = durum
    ids = kardes_failure_ids(s, f)
    if not ids:
        return 1
    res = s.execute(
        text(
            "UPDATE failure SET oneri_durumu = :d WHERE id = ANY(:ids) "
            "AND oneri_durumu IN ('proposed', 'pr_open', 'none')"
        ),
        {"d": durum, "ids": ids},
    )
    return 1 + int(res.rowcount or 0)


def _yukle(s: Session, sid: uuid.UUID) -> Script:
    sc = s.get(Script, sid, with_for_update=True)
    if sc is None or sc.tur != ONARIM_TURU:
        raise PermanentJobError("onarım script'i bulunamadı")
    return sc


def merged_isaretle(
    engine: Engine,
    sid: uuid.UUID,
    number: int,
    head: str,
    merge_sha: str | None,
    actor: str,
) -> dict[str, Any]:
    """Forge arayüzünde insanın merge ettiği onarım PR'ını çekirdeğe işler (idempotent)."""
    from tp_core.features.codegen.service import _ci_tetikle, _harici_merge_onayi

    with session_scope() as s:
        sc = _yukle(s, sid)
        if sc.durum == "merged":
            return {"durum": "merged", "pr": number, "merge_sha": merge_sha, "zaten": True}
        fid = sc.failure_id
        yabanci = bool(sc.head_sha) and head != sc.head_sha
        sc.insan_review_sonucu = "kabul_yabanci_head" if yabanci else "kabul"
        if yabanci:
            # Onaylanan/yerel kontrolden geçen head değil: yalnızca testId değişikliği güvencesi
            # (Constitution VI) merge edilen head için geçerli sayılmaz; denetime açıkça yazılır.
            audit_on_commit(
                s,
                actor,
                "repair.merged_foreign_head",
                f"script:{sid}",
                {"pr": number, "uretilen_head": sc.head_sha, "merge_edilen_head": head},
            )
        if not approved_hash_matches(s, sc, frozenset({"merge"})):
            _harici_merge_onayi(s, sc, actor, number, head)
        transition(
            s,
            sc,
            "merged",
            actor,
            "pr_open",
            sebep="forge'da insan onarım PR'ını merge etti",
            ozet={"pr": number, "kaynak": "forge"},
        )
        kayit = s.get(PullRequest, number)
        if kayit is not None:
            kayit.durum = "merged"
            kayit.merge_sha = merge_sha
            kayit.merge_eden = actor
        _oneri_durumu_yaz(s, fid, "merged")
        audit_on_commit(
            s,
            actor,
            "repair.merged",
            f"script:{sid}",
            {"pr": number, "head_sha": head, "merge_sha": merge_sha, "kaynak": "forge",
             "failure_id": str(fid) if fid else None},
        )  # fmt: skip
        baglanti = s.connection()
        publish_tx(baglanti, "pr.merged", {"script_id": sid, "pr_number": number,
                                           "merge_sha": merge_sha, "aktor": actor,
                                           "tur": ONARIM_TURU})  # fmt: skip
        publish_tx(baglanti, "repair.merged", {"script_id": sid, "failure_id": fid,
                                               "pr_number": number, "merge_sha": merge_sha,
                                               "aktor": actor})  # fmt: skip
    ci = _ci_tetikle(engine, merge_sha, None, trigger="push", script_id=sid, isteyen=actor)
    return {"durum": "merged", "pr": number, "merge_sha": merge_sha, "ci": ci}


def closed_isaretle(sid: uuid.UUID, number: int) -> dict[str, Any]:
    """Forge'da merge edilmeden kapatılan onarım PR'ı: öneri reddedildi (yeniden istenebilir)."""
    with session_scope() as s:
        sc = _yukle(s, sid)
        if sc.durum != "pr_open":
            return {"durum": sc.durum, "pr": number, "zaten": True}
        fid = sc.failure_id
        transition(s, sc, "closed", SYSTEM, "pr_open", sebep="onarım PR'ı forge'da kapatıldı")
        kayit = s.get(PullRequest, number)
        if kayit is not None:
            kayit.durum = "closed"
        _oneri_durumu_yaz(s, fid, "rejected")
        audit_on_commit(
            s,
            "system",
            "repair.pr_closed_external",
            f"script:{sid}",
            {"pr": number, "failure_id": str(fid) if fid else None},
        )
    return {"durum": "closed", "pr": number}

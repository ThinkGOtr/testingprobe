"""Portal `BugTaslagi` görünümü (Faz 4 ayrıntılarıyla).

Faz 2 biçimindeki alanlar (`requirements.serialize.bug_draft_out`) aynen korunur; Faz 4 alanları
eklenir: `hazirlik` (iş durumu), `imza`, `jql`, `arama`, `oneri` (AI önerisi `new|link`),
`dup_mode` (sıralamanın REPLAY rozeti), `uretim` (`ai|sablon`), `mode_label`, `duzeltmeler`,
`ilgili_failure_ids`, `yayin`, `jira_url`, `onay_zamani`, `ret_gerekcesi`, `sema` (düzenleme
formu için şema).
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tp_core.features.bugs.service import _requirement_id, mod_label_of
from tp_core.features.testveri.atif import maskele_obje
from tp_core.features.testveri.service import gizli_degerler
from tp_core.models import AppUser, BugDraft, Review
from tp_core.models.bugs_feature import BugDraftEk


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def jira_url(key: str | None) -> str | None:
    if not key:
        return None
    from tp_core.integrations.jira import get_jira_settings

    s = get_jira_settings()
    return f"{(s.jira_browse_url or s.jira_base_url).rstrip('/')}/browse/{quote(key, safe='')}"


def _son_karar(s: Session, b: BugDraft) -> Review | None:
    return s.scalars(
        select(Review)
        .where(Review.nesne_turu == "bug_draft", Review.nesne_id == b.id)
        .order_by(Review.sira.desc())
        .limit(1)
    ).first()


def sonuc_metni(b: BugDraft, ek: BugDraftEk | None) -> str:
    """Triage / script sayfasının taslak kutusundaki Türkçe durum (bekleyen metin yerine)."""
    yayin = (ek.yayin if ek else None) or {}
    if b.durum == "published" and yayin.get("jira_silindi"):
        return f"Jira'da açılmıştı: {b.jira_key} (demo sıfırlamasında silindi)"
    if b.durum == "published" and b.karar == "link":
        return f"Mevcut kayda bağlandı: {b.jira_key}"
    if b.durum == "published":
        return f"Jira'da açıldı: {b.jira_key}"
    if b.durum == "dismissed":
        return "Testçi taslağı reddetti (Jira kaydı açılmadı)"
    if b.durum == "approved" and yayin.get("durum") == "basarisiz":
        return "Testçi onayladı; Jira yayını başarısız (yeniden dene ya da taslağa al)"
    if b.durum == "approved":
        return "Testçi onayladı; Jira'ya yazılıyor"
    return "Bug taslağı testçi kararı bekliyor"


def bug_draft_view(s: Session, b: BugDraft) -> dict[str, Any]:
    onaylayan = s.get(AppUser, b.onaylayan_id).kullanici_adi if b.onaylayan_id else None
    ek = s.get(BugDraftEk, b.id)
    son = _son_karar(s, b)
    mod_metni, _ = mod_label_of(s, b)
    rid = _requirement_id(s, b)
    jira_silindi = bool(((ek.yayin if ek else None) or {}).get("jira_silindi"))
    gizli = gizli_degerler(s) if ek else []
    adaylar = []
    for a in b.mukerrer_adaylari or []:
        if isinstance(a, dict):
            adaylar.append({**a, "url": jira_url(a.get("key"))})
    return {
        "id": str(b.id),
        "kaynak": "consistency" if b.finding_id else "triage",
        "failure_id": str(b.failure_id) if b.failure_id else None,
        "finding_id": str(b.finding_id) if b.finding_id else None,
        "requirement_id": str(rid) if rid else None,
        "icerik": b.icerik,
        "mukerrer_adaylari": adaylar,
        "karar": b.karar,
        "durum": b.durum,
        "link_key": b.link_key,
        "icerik_hash": b.icerik_hash,
        "onaylanan_hash": b.onaylanan_hash,
        "onaylayan": onaylayan,
        "onay_zamani": _iso(son.zaman)
        if son is not None and son.karar in ("new", "link")
        else None,
        "ret_gerekcesi": son.gerekce if son is not None and son.karar == "dismiss" else None,
        "jira_key": b.jira_key,
        "jira_url": None if jira_silindi else jira_url(b.jira_key),
        "jira_silindi": jira_silindi,
        "mode": b.uretim_modu or None,
        "mode_label": mod_metni,
        "olusturma": _iso(b.olusturma),
        "hazirlik": {
            "durum": ek.hazirlik_durum if ek else None,
            "no": ek.hazirlik_no if ek else 0,
            "hata": maskele_obje(ek.hazirlik_hatasi, gizli) if ek else None,
            "job_id": str(ek.job_id) if ek and ek.job_id else None,
        },
        "uretim": ek.uretim if ek else None,
        # 013 K19 (güvenlik #1): eski kayıtlar dahil imza / JQL / arama maskeli döner.
        "imza": maskele_obje(ek.imza, gizli) if ek else {},
        "jql": maskele_obje(ek.jql, gizli) if ek else None,
        "arama": maskele_obje(ek.arama, gizli) if ek else {},
        "oneri": ek.oneri if ek else {},
        "dup_mode": ek.dup_uretim_modu if ek else None,
        "duzeltmeler": ek.duzeltmeler if ek else [],
        "ilgili_failure_ids": ek.ilgili_failure_ids if ek else [],
        "yayin": ek.yayin if ek else {},
        "mukerrer_aramasi_yapildi": bool(ek and (ek.arama or {}).get("durum") == "yapildi"),
        "sonuc_metni": sonuc_metni(b, ek),
        "yeniden_acilabilir": b.durum == "dismissed"
        or (b.durum == "approved" and (ek.yayin if ek else {}).get("durum") == "basarisiz"),
    }


def bug_draft_list(
    s: Session,
    requirement_id: uuid.UUID | None = None,
    failure_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    q = select(BugDraft).order_by(BugDraft.olusturma.desc())
    if failure_id is not None:
        # Kendi taslağı ya da aynı hata imzasıyla mevcut taslağa eklenmiş başarısızlık.
        ekli = select(BugDraftEk.bug_draft_id).where(
            BugDraftEk.ilgili_failure_ids.contains([str(failure_id)])
        )
        q = q.where(or_(BugDraft.failure_id == failure_id, BugDraft.id.in_(ekli)))
    out = [bug_draft_view(s, b) for b in s.scalars(q)]
    if requirement_id is not None:
        out = [o for o in out if o["requirement_id"] == str(requirement_id)]
    return out

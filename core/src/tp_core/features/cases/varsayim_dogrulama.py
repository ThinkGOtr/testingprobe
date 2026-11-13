"""Doğrulanan varsayımın aynı varsayıma dayanan diğer case'lere yansıması (specs/011 K20; UX B2).

"Varsayım doğrulandı" (`toplu.assumption_verified`) yalnız o case'i onaylar ve review satırına
`duzeltme_olculeri.varsayim_dogrulandi=[kimlikler]` yazar. Aynı varsayıma (aynı metin) dayanan
diğer taslak case'ler bunu bilmiyordu: "A1 varsayımı doğrulanmadı" diyordu. Bu modül, güncel
setteki onaylı/yayınlanmış case'lerin doğrulama kayıtlarından varsayım metni → doğrulama
bilgisini çıkarır ve case listesindeki `varsayimlar[]` kayıtlarına `dogrulama` olarak ekler.

Kimlik eşlemesi metinle yapılır (`acik_sorular.text_hash`): aynı `A1` farklı üretimlerde farklı
varsayım olabilir. Doğrulama case'i onaylamaz; yalnız bilgi verir (her case kendi kararıyla
onaylanır).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.models import AppUser, Requirement, Review

# 012 (dev birleştirmesi): "Varsayım doğrulandı" Testçinin `edit`'idir ve case'i `ready` yapar;
# doğrulama Analist son onayını beklemeden diğer case'lere yansır.
ONAYLI = frozenset({"ready", "approved", "published"})


def verified_assumptions(session: Session, req: Requirement) -> dict[str, dict[str, Any]]:
    """Varsayım metin hash'i → `{case_id, sira_no, kim, zaman}` (ilk doğrulama kaydı).

    Yalnız güncel setteki (ret/superseded/eski içerik olmayan) onaylı ya da yayınlanmış case'lerin
    `varsayim_dogrulandi` işaretli review'ları sayılır; taslağa alınan case'in doğrulaması
    sayılmaz."""
    from tp_core.features.cases import ozet as ozet_modulu
    from tp_core.features.cases.acik_sorular import text_hash

    cases = {
        tc.id: tc
        for tc in ozet_modulu.current_cases(session, req, include_legacy=False)
        if tc.durum in ONAYLI
    }
    if not cases:
        return {}
    reviews = session.scalars(
        select(Review)
        .where(
            Review.nesne_turu == "test_case",
            Review.nesne_id.in_(list(cases)),
            Review.karar == "edit",
        )
        .order_by(Review.sira)
    ).all()
    isaretli = [r for r in reviews if (r.duzeltme_olculeri or {}).get("varsayim_dogrulandi")]
    if not isaretli:
        return {}
    kullanicilar = dict(
        session.execute(
            select(AppUser.id, AppUser.kullanici_adi).where(
                AppUser.id.in_({r.user_id for r in isaretli if r.user_id})
            )
        ).all()
    )
    ozetler = ozet_modulu.AuditSummaries(session, req)
    out: dict[str, dict[str, Any]] = {}
    for r in isaretli:
        tc = cases[r.nesne_id]
        tanim = {
            str(a.get("id")): str(a.get("statement") or "")
            for a in (ozetler.of(tc.uretim_no) or {}).get("assumptions") or []
            if isinstance(a, Mapping)
        }
        for kimlik in r.duzeltme_olculeri["varsayim_dogrulandi"]:
            metin = tanim.get(str(kimlik))
            if not metin or not metin.strip():
                continue
            out.setdefault(
                text_hash("varsayim", metin),
                {
                    "case_id": str(tc.id),
                    "sira_no": tc.sira_no,
                    "kimlik": str(kimlik),
                    "kim": kullanicilar.get(r.user_id) if r.user_id else r.harici_onaylayan,
                    "zaman": r.zaman,
                },
            )
    return out


def case_fields(session: Session, cases: list[dict[str, Any]]) -> None:
    """`serialize_cases` çıktısındaki `varsayimlar[]` kayıtlarına `dogrulama` ekler (yerinde).

    Varsayım başka bir case'te doğrulandıysa `dogrulama = {case_id, sira_no, kimlik, kim, zaman}`;
    doğrulanmadıysa alan eklenmez. Case'in kendi doğrulaması (onaylı case'te atıf zaten boş)
    eklenmez."""
    from tp_core.features.cases.acik_sorular import text_hash

    req_ids = {uuid.UUID(c["requirement_id"]) for c in cases if c.get("varsayimlar")}
    if not req_ids:
        return
    reqs = session.scalars(select(Requirement).where(Requirement.id.in_(req_ids))).all()
    dogrulanan = {str(r.id): verified_assumptions(session, r) for r in reqs}
    for c in cases:
        harita = dogrulanan.get(c["requirement_id"]) or {}
        if not harita:
            continue
        for kayit in c.get("varsayimlar") or []:
            d = harita.get(text_hash("varsayim", kayit.get("statement") or ""))
            if d is not None and d["case_id"] != c["id"]:
                kayit["dogrulama"] = d

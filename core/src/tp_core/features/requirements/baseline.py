"""Story başına manuel test tasarımı baz değeri (TEKNIK-TASARIM §12 "Hazırlık süresi", §17 ölçüt 6).

Baz değer, bir story'nin case'lerinin elle tasarlanmasının ne kadar sürdüğüdür (saniye; F0
haftasında İsmail'in ölçümü). Kaynak sırası:

1. **ölçüm** (`kaynak='olcum'`): `PUT /requirements/{id}/baseline` ile girilmiş ya da gözden
   geçirilmiş `rules/baz-degerler.yaml` dosyasından Jira eşitlemesinde uygulanmış story'ye özel
   değer (`requirement_baz_deger`, kim/ne zaman/kaynak notu ile; geçmiş append-only). Dosya
   `make reset`'ten etkilenmez (bkz. `baseline_dosya`).
2. **varsayılan** (`kaynak='varsayilan'`): story'ye özel ölçüm yoksa `TP_MANUAL_BASELINE_S`
   vardır ama **ölçüm değildir**: `deger_s`/`deger_ms` boş kalır (başlık değeri "ölçülmedi"),
   ortam değeri yalnızca ikincil `varsayilan_s`/`varsayilan_ms` + `aciklama`'da görünür; kazanca
   ve ortalamaya girmez.
3. **ölçülmedi** (`kaynak=None`): ikisi de yoksa sayı yoktur. Değer asla uydurulmaz.

Her giriş/temizleme hash zincirli denetim olayı yazar (`requirement.baseline_set`,
`requirement.baseline_cleared`; `once`/`sonra`).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.models import Requirement
from tp_core.models.baseline_feature import BAZ_UST_SINIR_S, RequirementBazDeger
from tp_core.workflow.service import Principal

ORTAM_DEGISKENI = "TP_MANUAL_BASELINE_S"
NOT_UST_SINIR = 500
# Kaynak notunun en az boşluk olmayan karakter sayısı (portal BAZ_NOT_EN_AZ ile aynı kural).
NOT_EN_AZ = 3
KAYNAK_OLCUM = "olcum"
KAYNAK_VARSAYILAN = "varsayilan"
ETIKETLER = {KAYNAK_OLCUM: "ölçüm", KAYNAK_VARSAYILAN: "varsayılan", None: "ölçülmedi"}
VARSAYILAN_NOTU = (
    "TP_MANUAL_BASELINE_S (varsayılan; bu story için ölçüm girilmedi — story'ye özel değer değil)"
)
# Portal/API bu satırı ölçüm yerine ikincil metin olarak gösterebilir.
VARSAYILAN_ACIKLAMA = "ölçülmedi; varsayılan {sure} (TP_MANUAL_BASELINE_S), ölçüm değil"


class BaselineError(ValueError):
    """Geçersiz baz değer girişi (API 422)."""


@dataclass(frozen=True)
class Giren:
    """Girişi yapan: portal kullanıcısı ya da gözden geçirilmiş dosyadaki adlı kişi.

    `aktor` denetim kaydının aktörüdür (boşsa `ad`); dosyadan uygulamada "seed" olur ve kişi adı
    `giren` sütununda/denetim özetinde kalır. `ek` denetim özetine eklenir (kaynak dosya vb.).
    """

    ad: str
    rol: str
    aktor: str | None = None
    ek: dict[str, Any] = field(default_factory=dict)


def varsayilan_s() -> int | None:
    """`TP_MANUAL_BASELINE_S` (saniye); boş/geçersiz/≤0 → None (ölçülmedi)."""
    ham = (os.environ.get(ORTAM_DEGISKENI) or "").strip()
    try:
        deger = int(float(ham)) if ham else 0
    except ValueError:
        return None
    return deger if deger > 0 else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def sure_metni(saniye: int) -> str:
    """Saniye → "45 dk", "1 sa 30 dk", "45 dk 10 sn" (Türkçe kısa biçim)."""
    sa, kalan = divmod(int(saniye), 3600)
    dk, sn = divmod(kalan, 60)
    parcalar = [f"{sa} sa"] if sa else []
    if dk:
        parcalar.append(f"{dk} dk")
    if sn or not parcalar:
        parcalar.append(f"{sn} sn")
    return " ".join(parcalar)


def view(row: RequirementBazDeger | None, varsayilan: int | None) -> dict[str, Any]:
    """Story'nin etkin baz değeri: ölçüm → varsayılan (sayı değil) → ölçülmedi.

    `deger_s`/`deger_ms` yalnızca ölçümde doludur. Varsayılan (`TP_MANUAL_BASELINE_S`) ölçüm
    değildir: başlık değeri olarak gösterilmesin diye yalnızca `varsayilan_s`/`varsayilan_ms` ve
    `aciklama`'da taşınır.
    """
    deger: int | None = None
    kaynak: str | None = None
    giren = rol = zaman = notu = aciklama = None
    sira: int | None = None
    if row is not None and row.islem == "set" and row.deger_s:
        deger, kaynak = int(row.deger_s), KAYNAK_OLCUM
        giren, rol, zaman, notu, sira = (
            row.giren,
            row.giren_rol,
            _iso(row.zaman),
            row.not_metni,
            row.sira,
        )
    elif varsayilan is not None:
        kaynak, notu = KAYNAK_VARSAYILAN, VARSAYILAN_NOTU
        aciklama = VARSAYILAN_ACIKLAMA.format(sure=sure_metni(varsayilan))
    return {
        "deger_s": deger,
        "deger_ms": deger * 1000 if deger is not None else None,
        "kaynak": kaynak,
        "etiket": ETIKETLER[kaynak],
        "giren": giren,
        "giren_rol": rol,
        "zaman": zaman,
        "not": notu,
        "sira": sira,
        # Ölçüm olmayan ortam değeri: yalnızca ikincil bilgi (kazanca/ortalamaya girmez).
        "varsayilan_s": varsayilan if kaynak == KAYNAK_VARSAYILAN else None,
        "varsayilan_ms": varsayilan * 1000
        if kaynak == KAYNAK_VARSAYILAN and varsayilan is not None
        else None,
        "aciklama": aciklama,
        "ust_sinir_s": BAZ_UST_SINIR_S,
    }


def current_rows(
    session: Session, req_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RequirementBazDeger]:
    """Gereksinim başına en son giriş (set ya da clear); girişsiz gereksinim sözlükte yok."""
    ids = list(dict.fromkeys(req_ids))
    if not ids:
        return {}
    son = (
        select(
            RequirementBazDeger.requirement_id.label("rid"),
            func.max(RequirementBazDeger.sira).label("sira"),
        )
        .where(RequirementBazDeger.requirement_id.in_(ids))
        .group_by(RequirementBazDeger.requirement_id)
        .subquery()
    )
    rows = session.scalars(
        select(RequirementBazDeger).join(
            son,
            (RequirementBazDeger.requirement_id == son.c.rid)
            & (RequirementBazDeger.sira == son.c.sira),
        )
    ).all()
    return {r.requirement_id: r for r in rows}


def baselines_for(
    session: Session, req_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    ids = list(dict.fromkeys(req_ids))
    rows = current_rows(session, ids)
    varsayilan = varsayilan_s()
    return {rid: view(rows.get(rid), varsayilan) for rid in ids}


def baseline_for(session: Session, req_id: uuid.UUID) -> dict[str, Any]:
    return baselines_for(session, [req_id])[req_id]


def history(session: Session, req_id: uuid.UUID) -> list[dict[str, Any]]:
    """Tüm girişler, en yeniden eskiye (append-only)."""
    rows = session.scalars(
        select(RequirementBazDeger)
        .where(RequirementBazDeger.requirement_id == req_id)
        .order_by(RequirementBazDeger.sira.desc())
    ).all()
    return [
        {
            "sira": r.sira,
            "islem": r.islem,
            "deger_s": r.deger_s,
            "onceki_s": r.onceki_s,
            "giren": r.giren,
            "giren_rol": r.giren_rol,
            "not": r.not_metni,
            "zaman": _iso(r.zaman),
        }
        for r in rows
    ]


def _not(not_metni: str | None, *, zorunlu: bool) -> str | None:
    metin = " ".join((not_metni or "").split())
    if not metin:
        if zorunlu:
            raise BaselineError(
                "Kaynak notu zorunlu (ör. 'F0 ölçümü – İsmail'): değerin nereden geldiği yazılmalı"
            )
        return None
    if zorunlu and len("".join(metin.split())) < NOT_EN_AZ:
        raise BaselineError(
            f"Kaynak notu en az {NOT_EN_AZ} karakter olmalı (boşluklar sayılmaz); kim, hangi "
            "yöntemle ölçtü yazılmalı (ör. 'F0 ölçümü – İsmail')"
        )
    if len(metin) > NOT_UST_SINIR:
        raise BaselineError(f"Kaynak notu en çok {NOT_UST_SINIR} karakter olabilir")
    return metin


def validate_value(deger_s: Any) -> int:
    if isinstance(deger_s, bool) or not isinstance(deger_s, int):
        raise BaselineError("Baz değer tam sayı (saniye) olmalı")
    if deger_s <= 0:
        raise BaselineError("Baz değer 0'dan büyük olmalı (saniye)")
    if deger_s > BAZ_UST_SINIR_S:
        raise BaselineError(
            f"Baz değer en çok {BAZ_UST_SINIR_S} sn (40 saat) olabilir; birim saniyedir"
        )
    return deger_s


def _ozet(v: dict[str, Any]) -> dict[str, Any]:
    return {k: v[k] for k in ("deger_s", "kaynak", "giren", "not", "sira")}


def _yaz(
    session: Session,
    req: Requirement,
    user: Principal | Giren,
    islem: str,
    deger_s: int | None,
    not_metni: str | None,
) -> tuple[dict[str, Any], bool]:
    """Kilitli gereksinim için yeni giriş satırı + denetim; değişiklik yoksa yazmaz."""
    giren = user if isinstance(user, Giren) else Giren(user.kullanici_adi, user.rol)
    onceki_satir = current_rows(session, [req.id]).get(req.id)
    varsayilan = varsayilan_s()
    once = view(onceki_satir, varsayilan)
    onceki_s = (
        onceki_satir.deger_s if onceki_satir is not None and onceki_satir.islem == "set" else None
    )
    if islem == "clear" and onceki_s is None:
        return once, False
    if (
        islem == "set"
        and onceki_satir is not None
        and onceki_s == deger_s
        and onceki_satir.not_metni == not_metni
    ):
        return once, False
    sira = (
        session.scalar(
            select(func.max(RequirementBazDeger.sira)).where(
                RequirementBazDeger.requirement_id == req.id
            )
        )
        or 0
    ) + 1
    row = RequirementBazDeger(
        requirement_id=req.id,
        sira=sira,
        islem=islem,
        deger_s=deger_s,
        onceki_s=onceki_s,
        giren=giren.ad,
        giren_rol=giren.rol,
        not_metni=not_metni,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    sonra = view(row, varsayilan)
    audit_on_commit(
        session,
        giren.aktor or giren.ad,
        "requirement.baseline_set" if islem == "set" else "requirement.baseline_cleared",
        f"requirement:{req.id}",
        {
            "jira_key": req.jira_key,
            "rol": giren.rol,
            "once": _ozet(once),
            "sonra": _ozet(sonra),
            **giren.ek,
        },
    )
    _olay(session, req, sonra)
    return sonra, True


def _olay(session: Session, req: Requirement, v: dict[str, Any]) -> None:
    # `requirement.updated` (alan='baseline'): portal gereksinim detayını yeniler.
    from tp_core.features.requirements.flow import emit_requirement

    emit_requirement(session, req, alan="baseline", baseline=_ozet(v))


def set_baseline(
    session: Session, req: Requirement, user: Principal, deger_s: Any, not_metni: str | None
) -> tuple[dict[str, Any], bool]:
    """Story'ye özel ölçümü yazar (analist/PO). Dönüş: (etkin baz değer, değişti mi)."""
    deger = validate_value(deger_s)
    notu = _not(not_metni, zorunlu=True)
    return _yaz(session, req, user, "set", deger, notu)


def clear_baseline(
    session: Session, req: Requirement, user: Principal, not_metni: str | None = None
) -> tuple[dict[str, Any], bool]:
    """Story'ye özel ölçümü kaldırır (geçmiş kalır); varsa varsayılana düşer."""
    return _yaz(session, req, user, "clear", None, _not(not_metni, zorunlu=False))


def kapsam_metni(toplam: int, olcum: int, varsayilan: int, olculmedi: int) -> str:
    """Kapsam metni, ör. "4 story'den 3'ünde ölçüm var, 1'inde ölçülmedi" (Türkçe ek uyumuyla)."""
    if toplam == 0:
        return "Hazırlık süresi olan story yok: manuel baz değer kapsamı hesaplanmadı."
    parcalar = [f"{toplam} story'den {olcum}'{bulunma_eki(olcum)} ölçüm var"]
    if varsayilan:
        parcalar.append(
            f"{varsayilan}'{bulunma_eki(varsayilan)} ölçüm yok (yalnız varsayılan "
            "TP_MANUAL_BASELINE_S; ölçüm sayılmaz)"
        )
    if olculmedi:
        parcalar.append(f"{olculmedi}'{bulunma_eki(olculmedi)} ölçülmedi")
    return ", ".join(parcalar)


_BIRLER = {1: "inde", 2: "sinde", 3: "ünde", 4: "ünde", 5: "inde", 6: "sında", 7: "sinde",
           8: "inde", 9: "unda"}  # fmt: skip
_ONLAR = {1: "unda", 2: "sinde", 3: "unda", 4: "ında", 5: "sinde", 6: "ında", 7: "inde",
          8: "inde", 9: "ında"}  # fmt: skip


def bulunma_eki(n: int) -> str:
    """Sayının iyelik + bulunma eki (3 → "ünde", 6 → "sında", 10 → "unda", 0 → "ında")."""
    n = abs(int(n))
    if n == 0:
        return "ında"
    if n % 10:
        return _BIRLER[n % 10]
    if n % 100:
        return _ONLAR[(n % 100) // 10]
    if n % 1000:
        return "ünde"  # yüz
    if n % 1_000_000:
        return "inde"  # bin
    return "unda"  # milyon

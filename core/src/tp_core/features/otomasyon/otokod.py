"""Case onayı sonrası otomatik kod üretimi (specs/013-sprint-otomasyonu §3.2, K4).

Tekli karar (`approve` / `edit`) ve toplu onay, onay yazıldıktan sonra `kuyruga_al`ı çağırır.
Kod üretimi sistem aktörüyle (`OTOMASYON_AKTORU`) başlar; onaylayan kullanıcı `tetikleyen`
olarak iş akışı yüküne ve denetime yazılır. Engineer rol kapısı bilinçli olarak atlanır: kod
üretimi yalnızca onaylı içerikle başlar (Constitution I), PR merge'ü yine insan işidir.

Kural: otomatik kod üretimi **onayı asla geri almaz**. Üretim kendi SAVEPOINT'inde başlar;
reddedilir ya da beklenmedik biçimde patlarsa yalnız o SAVEPOINT geri alınır.

Toplu onay (K16) üretimi onay isteğinden ayırır: `toplu_kuyruga_al` tek `codegen.otomatik` işi
kuyruğa alır; iş (`toplu_uret`, işleyici `codegen/jobs.py`) `MAX_CASE`'lik parçalarla
`start_generation` çağırır. Otomatik üretim süren ya da açık PR'lı script'e dokunmaz (K16,
`codegen.service.start_generation`).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tp_core.audit.session import _ANAHTAR as _DENETIM_ANAHTARI
from tp_core.audit.session import audit_on_commit
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.service import MAX_CASE, CodegenRejected, start_generation
from tp_core.features.otomasyon import ayarlar
from tp_core.models import Review, TestCase, session_scope
from tp_core.workflow.jobs import enqueue
from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)

OTOMASYON_AKTORU = ayarlar.OTOMASYON_AKTORU
JOB_OTOMATIK_KOD = "codegen.otomatik"

# start_generation'ın "zaten var" sonuçları: yeni üretim gerekmiyor.
ATLANAN_SONUCLAR = frozenset({"suruyor", "pr_acik", "merge_edildi"})

HATA_NEDENI = (
    "Otomatik kod üretimi beklenmedik bir hatayla başlatılamadı; onay geçerli. "
    "Kod üretimi ekranından elle başlatın."
)


class _GeriAl(Exception):
    """`savepoint` içinden yalnız SAVEPOINT'i geri almak için (dışarı sızmaz)."""


@contextmanager
def savepoint(session: Session) -> Iterator[None]:
    """SAVEPOINT + bekleyen denetim kayıtlarının birlikte geri alınması.

    `audit_on_commit` kayıtları oturumda bekler ve SAVEPOINT geri alımında atılmaz
    (`audit/session.py`); burada geri alınan bölümün eklediği kayıtlar da düşürülür.
    Hata yeniden fırlatılır (çağıran yakalar).
    """
    bekleyen = session.info.get(_DENETIM_ANAHTARI)
    once = len(bekleyen) if bekleyen else 0
    sp = session.begin_nested()
    try:
        yield
    except BaseException:
        if sp.is_active:
            sp.rollback()
        liste = session.info.get(_DENETIM_ANAHTARI)
        if liste is not None:
            del liste[once:]
        raise
    else:
        if sp.is_active:
            sp.commit()


def _sonuc(durum: str, neden: str | None = None, script_id: str | None = None) -> dict[str, Any]:
    return {"durum": durum, "neden": neden, "script_id": script_id}


def kuyruga_al(session: Session, tc: TestCase, onaylayan: Principal) -> dict[str, Any]:
    """Onaylanan case için web kod üretimini kuyruğa alır.

    Dönen `durum`: `kuyrukta` (script_id dolu) | `atlandi` (süren üretim / açık ya da merge
    edilmiş PR) | `reddedildi` (kod üretimi kapısı; neden Türkçe) | `kapali` (ayar kapalı) |
    `hata` (beklenmedik; onay geçerli, denetim `codegen.otomatik_hata`).
    """
    if not ayarlar.otomatik_kod(session).acik:
        return _sonuc("kapali", "Otomatik kod üretimi ayarı kapalı")
    if tc.durum != "approved":
        return _sonuc("atlandi", f"case onaylı değil (durum: {tc.durum})")
    try:
        with savepoint(session):
            cevap = start_generation(
                session,
                [tc.id],
                OTOMASYON_AKTORU,
                platform=platformlar.WEB,
                tetik="otomatik",
                tetikleyen=onaylayan.kullanici_adi,
            )
    except CodegenRejected as exc:
        return _sonuc("reddedildi", str(exc))
    except Exception as exc:
        log.exception("otomatik kod üretimi başlatılamadı (case %s)", tc.id)
        audit_on_commit(
            session,
            OTOMASYON_AKTORU.kullanici_adi,
            "codegen.otomatik_hata",
            f"test_case:{tc.id}",
            {"tetikleyen": onaylayan.kullanici_adi, "hata": type(exc).__name__,
             "mesaj": str(exc)[:500]},
        )  # fmt: skip
        return _sonuc("hata", HATA_NEDENI)
    return _ogeden((cevap.get("sonuclar") or [{}])[0], cevap.get("mesaj"))


def _ogeden(oge: dict[str, Any], mesaj: str | None = None) -> dict[str, Any]:
    """`start_generation` öğe sonucu → otomatik kod sonucu."""
    durum = oge.get("durum")
    if durum == "basladi":
        return _sonuc("kuyrukta", None, oge.get("script_id"))
    if durum in ATLANAN_SONUCLAR:
        return _sonuc("atlandi", oge.get("neden"), oge.get("script_id"))
    return _sonuc("reddedildi", oge.get("neden") or mesaj)


# ---------------------------------------------------------------- toplu onay (K16)


def toplu_kuyruga_al(
    session: Session, case_ids: Sequence[uuid.UUID], onaylayan: Principal
) -> dict[str, Any]:
    """Toplu onayda onaylanan case'ler için tek `codegen.otomatik` işi (onayla aynı işlemde).

    Dönen (bulk yanıtı üst düzey `otomatik_kod`): `{durum: "kuyrukta"|"kapali"|"yok", job_id,
    case_sayisi}`. İdempotent anahtar onay review kayıtlarından türer (aynı onay kümesi = aynı iş).
    """
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return {"durum": "yok", "job_id": None, "case_sayisi": 0}
    if not ayarlar.otomatik_kod(session).acik:
        return {"durum": "kapali", "job_id": None, "case_sayisi": 0}
    son_review = {
        nesne_id: rid
        for nesne_id, rid in session.execute(
            select(Review.nesne_id, func.max(Review.sira))
            .where(Review.nesne_turu == "test_case", Review.nesne_id.in_(ids))
            .group_by(Review.nesne_id)
        ).all()
    }
    ozet = "|".join(f"{cid}:{son_review.get(cid)}" for cid in sorted(ids))
    anahtar = f"{JOB_OTOMATIK_KOD}:{hashlib.sha256(ozet.encode()).hexdigest()[:32]}"
    job_id = enqueue(
        session.connection(),
        JOB_OTOMATIK_KOD,
        {
            "case_ids": [str(c) for c in ids],
            "tetikleyen": onaylayan.kullanici_adi,
        },
        idempotency_key=anahtar,
    )
    return {"durum": "kuyrukta", "job_id": str(job_id), "case_sayisi": len(ids)}


def toplu_uret(yuk: dict[str, Any]) -> dict[str, Any]:
    """`codegen.otomatik` işinin gövdesi: `MAX_CASE`'lik parçalarla `start_generation`.

    Her parça kendi işleminde (önceki parçaların üretimi kalıcı). Ayar iş sırasında kapanırsa
    kalan case'ler `kapali`. Yeniden denemede başlamış üretimler `atlandi` (süren üretim) döner.
    """
    ids = [uuid.UUID(str(c)) for c in yuk.get("case_ids") or []]
    tetikleyen = yuk.get("tetikleyen")
    sonuclar: list[dict[str, Any]] = []
    for i in range(0, len(ids), MAX_CASE):
        parca = ids[i : i + MAX_CASE]
        with session_scope() as s:
            if not ayarlar.otomatik_kod(s).acik:
                sonuclar += [
                    {"case_id": str(c), **_sonuc("kapali", "Otomatik kod üretimi ayarı kapalı")}
                    for c in parca
                ]
                continue
            try:
                with savepoint(s):
                    cevap = start_generation(
                        s,
                        parca,
                        OTOMASYON_AKTORU,
                        platform=platformlar.WEB,
                        tetik="otomatik",
                        tetikleyen=tetikleyen,
                    )
            except CodegenRejected as exc:
                sonuclar += [{"case_id": str(c), **_sonuc("reddedildi", str(exc))} for c in parca]
                continue
            sonuclar += [
                {"case_id": o.get("case_id"), **_ogeden(o, cevap.get("mesaj"))}
                for o in cevap.get("sonuclar") or []
            ]
    ozet: dict[str, int] = {}
    for o in sonuclar:
        ozet[o["durum"]] = ozet.get(o["durum"], 0) + 1
    return {"tetikleyen": tetikleyen, "case_sayisi": len(ids), "ozet": ozet, "sonuclar": sonuclar}

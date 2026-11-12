"""Toplu onay ve "Varsayım doğrulandı" (specs/011 K20; K6 kuralları aynen).

İki eylem de yeni bir karar türü getirmez; her case için mevcut `service.decide` çağrılır. Böylece
her case'e ayrı `review` kaydı (görülen içerik hash'iyle), durum geçişi ve denetim zinciri kaydı
düşer; onay kuralları (hazır olma, tutarlılık, PO onayının güncelliği) tek yerde kalır.

1. `bulk_approve` (`POST /cases/bulk-decision`, "Seçilenleri onayla"): kalemler gövde sırasıyla,
   her biri kendi SAVEPOINT'inde (`session.begin_nested()`) onaylanır. Bir kalem hata verirse
   yalnız o kalem geri alınır, diğerleri sürer; yanıt kalem kalem sonuç taşır (hepsi başarısız
   olsa bile 200). Gerekçe: her onay bağımsız bir insan kararıdır ve kendi görülen hash'ine
   bağlıdır; bir case'in bayat hash'i ya da hazır olmaması diğer case'lerdeki geçerli kararı
   geçersiz kılmaz; portal sonucu kalem kalem gösterir. Kalem hatasının `kod`'u tekil uçtaki
   HTTP karşılığıdır (`WorkflowError.status_code`: 409 bayat hash / taslak değil / story değişti,
   422 hazır değil / tutarsız, 404 case yok); `hata` aynı Türkçe mesajdır.
2. `assumption_verified` (`POST /cases/{id}/assumption-verified`, "Varsayım doğrulandı"):
   varsayıma bağlı taslak case'te analist varsayımı doğruladığını tek eylemle bildirir. Yeni
   içerik = mevcut içerik − doğrulanan `assumption_refs`; başka varsayım/soru kalmadıysa
   `readiness=ready`. Karar `edit` olarak verilir (denetim zincirine düzeltme olarak; K20),
   `beklenen_anlam_degisti=False` ve `duzeltme_olculeri.varsayim_dogrulandi=[kimlikler]` ile.
   Başka atıf kalıyorsa ya da beklenen sonuç boşsa 422: o durumda analist 'Düzelt' kullanır.

Denetim kaydı notu: `audit_on_commit` kayıtları oturumda bekler ve SAVEPOINT geri alımı onları
silmez (`audit/session.py`). Başarısız kalemin bekleyen kayıtları burada elle atılır; aksi halde
geri alınan karar zincire "verilmiş" gibi yazılırdı.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from tp_core.audit.session import _ANAHTAR as _BEKLEYEN_DENETIM
from tp_core.features.cases import service
from tp_core.features.cases.schema import READY, is_legacy
from tp_core.models import TestCase
from tp_core.workflow.service import (
    InvalidDecision,
    OnayHashUyusmuyor,
    Principal,
    WorkflowError,
)

AZAMI_KALEM = 50
GEREKCE_AZAMI = 2000


# ------------------------------------------------------------------------- toplu onay


@contextmanager
def _kalem_savepoint(session: Session) -> Iterator[None]:
    """Kalemi SAVEPOINT'te çalıştırır; hata olursa kalemin bekleyen denetim kayıtlarını da atar."""
    bekleyen = session.info.get(_BEKLEYEN_DENETIM)
    onceki = len(bekleyen) if bekleyen is not None else 0
    try:
        with session.begin_nested():
            yield
    except BaseException:
        kalan = session.info.get(_BEKLEYEN_DENETIM)
        if kalan is not None:
            del kalan[onceki:]
        raise


def bulk_approve(
    session: Session, user: Principal, kalemler: Sequence[tuple[Any, str]]
) -> dict[str, Any]:
    """`kalemler`: `(case_id, icerik_hash)` (gövde sırası). Kalem bazlı sonuç döner."""
    if not kalemler:
        raise InvalidDecision("En az bir case seçilmeli")
    if len(kalemler) > AZAMI_KALEM:
        raise InvalidDecision(f"Tek seferde en fazla {AZAMI_KALEM} case onaylanır")
    sonuclar: list[dict[str, Any]] = []
    onaylanan: dict[int, TestCase] = {}
    for sira, (cid, icerik_hash) in enumerate(kalemler):
        try:
            with _kalem_savepoint(session):
                tc = service.decide(session, cid, user, karar="approve", icerik_hash=icerik_hash)
                session.flush()
        except WorkflowError as exc:
            sonuclar.append(
                {
                    "case_id": str(cid),
                    "basarili": False,
                    "hata": str(exc),
                    "kod": exc.status_code,
                    "case": None,
                }
            )
            continue
        onaylanan[sira] = tc
        sonuclar.append(
            {"case_id": str(cid), "basarili": True, "hata": None, "kod": None, "case": None}
        )
    if onaylanan:
        sirali = sorted(onaylanan)
        for sira, govde in zip(
            sirali, service.serialize_cases(session, [onaylanan[i] for i in sirali]), strict=True
        ):
            sonuclar[sira]["case"] = govde
    return {
        "karar": "approve",
        "onaylanan": len(onaylanan),
        "basarisiz": len(sonuclar) - len(onaylanan),
        "sonuclar": sonuclar,
    }


# ----------------------------------------------------------------- varsayım doğrulandı


def _kimlikler(varsayim_id: str | Sequence[str]) -> list[str]:
    ham = [varsayim_id] if isinstance(varsayim_id, str) else list(varsayim_id)
    out: list[str] = []
    for k in ham:
        k = str(k).strip()
        if k and k not in out:
            out.append(k)
    if not out:
        raise InvalidDecision("Doğrulanan varsayımın kimliği (varsayim_id) verilmeli")
    return out


def _beklenen_bos(icerik: Mapping[str, Any]) -> bool:
    if not str(icerik.get("expected_result") or "").strip():
        return True
    adimlar = icerik.get("steps") or []
    return any(isinstance(a, Mapping) and not str(a.get("expected") or "").strip() for a in adimlar)


def _varsayilan_gerekce(session: Session, tc: TestCase, kimlikler: Sequence[str]) -> str:
    ozet = service.summary_for(session, tc) or {}
    metinler = {
        str(v.get("id")): str(v.get("statement") or "").strip()
        for v in ozet.get("assumptions") or []
        if isinstance(v, Mapping)
    }
    parcalar = [f"{k} — {metinler[k]}" if metinler.get(k) else k for k in kimlikler]
    return ("Varsayım doğrulandı: " + "; ".join(parcalar))[:GEREKCE_AZAMI]


def assumption_verified(
    session: Session,
    cid: Any,
    user: Principal,
    *,
    icerik_hash: str,
    varsayim_id: str | Sequence[str],
    gerekce: str | None = None,
) -> TestCase:
    """Varsayımı doğrulanan case'i `edit` kararıyla hazır yapıp onaylar (K20)."""
    tc = service.get_case(session, cid, lock=True)
    if is_legacy(tc.icerik):
        raise InvalidDecision("Eski biçimli case'te varsayım yok")
    if tc.durum != "draft":
        raise WorkflowError(
            f"Karar yalnızca taslak durumundaki case için verilir (durum: {tc.durum}); "
            "önce 'Taslağa al' kullanın"
        )
    if icerik_hash != tc.icerik_hash:
        raise OnayHashUyusmuyor(
            "test_case: içerik siz görüntüledikten sonra değişmiş; yenileyip tekrar karar verin"
        )
    engel = service.requirement_change_reason(service.get_requirement(session, tc.requirement_id))
    if engel is not None:
        raise service.RequirementChanged(engel)

    kimlikler = _kimlikler(varsayim_id)
    atiflar = [str(r) for r in tc.icerik.get("assumption_refs") or []]
    bilinmeyen = [k for k in kimlikler if k not in atiflar]
    if bilinmeyen:
        raise InvalidDecision(f"{', '.join(bilinmeyen)} bu case'in varsayımları arasında yok")
    kalan = [r for r in atiflar if r not in kimlikler]
    sorular = [str(q) for q in tc.icerik.get("open_question_refs") or []]
    if kalan or sorular:
        raise InvalidDecision(
            f"Case'in başka varsayımı/sorusu var ({', '.join(kalan + sorular)}); önce onları "
            "çözün ya da 'Düzelt' kullanın"
        )
    if _beklenen_bos(tc.icerik):
        raise InvalidDecision("Beklenen sonuç boş; 'Düzelt' ile yazın")

    yeni = copy.deepcopy(dict(tc.icerik))
    yeni["assumption_refs"] = []
    yeni["readiness"] = READY
    metin = (gerekce or "").strip() or _varsayilan_gerekce(session, tc, kimlikler)
    return service.decide(
        session,
        tc.id,
        user,
        karar="edit",
        icerik=yeni,
        icerik_hash=icerik_hash,
        gerekce=metin,
        beklenen_anlam_degisti=False,
        ek_olculer={"varsayim_dogrulandi": kimlikler},
    )

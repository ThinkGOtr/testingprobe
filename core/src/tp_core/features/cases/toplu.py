"""Toplu onay ve "Varsayım doğrulandı" (specs/011 K20; K6 kuralları aynen).

İki eylem de yeni bir karar türü getirmez; her case için mevcut `service.decide` çağrılır. Böylece
her case'e ayrı `review` kaydı (görülen içerik hash'iyle), durum geçişi ve denetim zinciri kaydı
düşer; onay kuralları (hazır olma, tutarlılık, PO onayının güncelliği) tek yerde kalır.

1. `bulk_approve` (`POST /cases/bulk-decision`, "Seçilenleri onayla"): önce seçilen case
   satırları `case_id` sırasıyla kilitlenir (kesişen iki toplu istek ters sırayla gelse de
   deadlock olmaz; tekil karar da önce case'i kilitler), sonra kalemler gövde sırasıyla,
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
   Varsayım PO'ya doğrulatılmak üzere gönderildiyse (K16, `acik_soru`) PO kaydı esastır: yanıt
   bekleniyorsa ya da PO "doğru" dışında bir yanıt verdiyse 409 (analist PO yanıtına göre
   'Düzelt' kullanır); PO "doğru" dediyse kayıt kaynağı olarak `CAn` yazılır.

Denetim kaydı notu: `audit_on_commit` kayıtları oturumda bekler ve SAVEPOINT geri alımı onları
silmez (`audit/session.py`). Başarısız kalemin bekleyen kayıtları burada elle atılır; aksi halde
geri alınan karar zincire "verilmiş" gibi yazılırdı.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
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


def _kilitle(session: Session, kimlikler: Sequence[Any]) -> None:
    """Seçilen case satırlarını tek sorguda `id` sırasıyla kilitler (tutarlı kilit sırası)."""
    gecerli: set[uuid.UUID] = set()
    for k in kimlikler:
        try:
            gecerli.add(k if isinstance(k, uuid.UUID) else uuid.UUID(str(k)))
        except ValueError:
            continue
    if gecerli:
        session.scalars(
            select(TestCase.id)
            .where(TestCase.id.in_(sorted(gecerli)))
            .order_by(TestCase.id)
            .with_for_update()
        ).all()


def bulk_approve(
    session: Session, user: Principal, kalemler: Sequence[tuple[Any, str]]
) -> dict[str, Any]:
    """`kalemler`: `(case_id, icerik_hash)` (gövde sırası). Kalem bazlı sonuç döner."""
    if not kalemler:
        raise InvalidDecision("En az bir case seçilmeli")
    if len(kalemler) > AZAMI_KALEM:
        raise InvalidDecision(f"Tek seferde en fazla {AZAMI_KALEM} case onaylanır")
    _kilitle(session, [cid for cid, _ in kalemler])
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

    po_kaynak = _po_dogrulamasi(session, tc, kimlikler)

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
        ek_olculer={
            "varsayim_dogrulandi": kimlikler,
            **({"po_dogruladi": po_kaynak} if po_kaynak else {}),
        },
    )


# PO'nun "doğru" yanıtı (`CAn: doğru`, "Evet, doğru.", "doğrudur", "onaylıyorum"); olumsuzluk
# içeren yanıt ("doğru değil", "yanlış", "hayır") sayılmaz.
_DOGRU = re.compile(r"^\W*(?:evet\W*)?(?:doğru(?:dur)?|dogru(?:dur)?|onayl[ıi]yorum|teyit)\b", re.I)
_OLUMSUZ = re.compile(r"\b(?:değil|degil|yanlış|yanlis|hayır|hayir)\b", re.I)


def po_dogru_dedi(yanit: str | None) -> bool:
    metin = " ".join(str(yanit or "").split())
    return bool(_DOGRU.search(metin)) and not _OLUMSUZ.search(metin)


def _po_dogrulamasi(session: Session, tc: TestCase, kimlikler: Sequence[str]) -> list[str]:
    """Varsayımlar PO'ya gönderildiyse (K16) PO kaydına uyulur (tur 2 güvenlik #8): yanıt
    bekleniyorsa ya da PO "doğru" dışında yanıt verdiyse 409. PO "doğru" dediyse kaynak
    etiketlerini (`CAn`) döner; hiç gönderilmemişse boş (analistin kendi doğrulaması)."""
    from tp_core.features.cases import acik_sorular

    ozet = service.summary_for(session, tc) or {}
    metinler = {
        str(v.get("id")): str(v.get("statement") or "")
        for v in ozet.get("assumptions") or []
        if isinstance(v, Mapping)
    }
    req = service.get_requirement(session, tc.requirement_id)
    satirlar = acik_sorular._rows(session, req)
    kaynak: list[str] = []
    for k in kimlikler:
        metin = metinler.get(k)
        satir = (
            satirlar.get(("varsayim", acik_sorular.text_hash("varsayim", metin))) if metin else None
        )
        if satir is None or satir.durum == "bekliyor":
            continue
        if satir.durum == "gonderildi":
            raise WorkflowError(
                f"{k} varsayımı PO'ya doğrulatılmak üzere gönderildi ({satir.etiket}); PO yanıtı "
                "bekleniyor. Yanıt gelince 'Varsayım doğrulandı' ya da 'Düzelt' kullanın"
            )
        if not po_dogru_dedi(satir.yanit):
            raise WorkflowError(
                f"PO {satir.etiket} ({k}) varsayımına 'doğru' dışında yanıt verdi; case'i PO "
                "yanıtına göre 'Düzelt' ile güncelleyin"
            )
        kaynak.append(satir.etiket)
    return kaynak

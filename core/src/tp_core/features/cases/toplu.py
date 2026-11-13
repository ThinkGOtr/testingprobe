"""Toplu onay ve "Varsayım doğrulandı" (specs/011 K20; K6 kuralları aynen).

İki eylem de yeni bir karar türü getirmez; her case için mevcut `service.decide` çağrılır. Böylece
her case'e ayrı `review` kaydı (görülen içerik hash'iyle), durum geçişi ve denetim zinciri kaydı
düşer; onay kuralları (hazır olma, tutarlılık, PO onayının güncelliği) tek yerde kalır.

1. Toplu karar ("Seçilenleri onayla"): dev birleştirmesinde 013/012'nin `POST /cases/bulk-decision`
   ucuna (`service.bulk_decide`: Testçi toplu kabul / Analist toplu son onay; öğe başına
   SAVEPOINT, görülme şartı, denetim kaydı) katıldı; 011'in ayrı `bulk_approve`'u kaldırıldı.
2. `assumption_verified` (`POST /cases/{id}/assumption-verified`, "Varsayım doğrulandı"):
   varsayıma bağlı taslak case'te Testçi (012: `case.decide`) varsayımı doğruladığını tek
   eylemle bildirir. Yeni içerik = mevcut içerik − doğrulanan `assumption_refs`; başka
   varsayım/soru kalmadıysa `readiness=ready`. Karar `edit` olarak verilir (denetim zincirine
   düzeltme olarak; K20; 012'de case draft → ready olur, son onay Analistindir),
   `beklenen_anlam_degisti=False` ve `duzeltme_olculeri.varsayim_dogrulandi=[kimlikler]` ile.
   Başka atıf kalıyorsa ya da beklenen sonuç boşsa 422: o durumda analist 'Düzelt' kullanır.
   Varsayım PO'ya doğrulatılmak üzere gönderildiyse (K16, `acik_soru`) PO kaydı esastır: yanıt
   bekleniyorsa ya da PO "doğru" dışında bir yanıt verdiyse 409 (analist PO yanıtına göre
   'Düzelt' kullanır); PO "doğru" dediyse kayıt kaynağı olarak `CAn` yazılır.

"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

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


# PO'nun kesin "doğru" yanıtı (tur 3 güvenlik #9): yanıt yalnız onay sözcüklerinden ve
# noktalamadan oluşmalı ("CAn: doğru", "Evet", "Evet, doğru.", "doğrudur", "onaylıyorum"). Ek
# koşul ya da açıklama ("Doğru, ama yalnız mobilde", "doğru değil", "evet ama…") kesin onay
# sayılmaz; analist PO yanıtına göre "Düzelt" kullanır.
_ONAY_SOZCUKLERI = frozenset(
    {
        "evet",
        "doğru",
        "dogru",
        "doğrudur",
        "dogrudur",
        "onaylıyorum",
        "onayliyorum",
        "teyit",
        "ediyorum",
    }
)
_SOZCUK = re.compile(r"\w+")


def po_dogru_dedi(yanit: str | None) -> bool:
    sozcukler = [w.casefold() for w in _SOZCUK.findall(str(yanit or ""))]
    return bool(sozcukler) and all(w in _ONAY_SOZCUKLERI for w in sozcukler)


def _po_dogrulamasi(session: Session, tc: TestCase, kimlikler: Sequence[str]) -> list[str]:
    """Varsayımlar PO'ya gönderildiyse (K16) PO kaydına uyulur (tur 2 güvenlik #8): yanıt
    bekleniyorsa, gönderim sürüyor/belirsizse (`bekliyor`) ya da PO kesin "doğru" dışında
    (ek koşullu dahil) yanıt verdiyse 409. PO "doğru" dediyse kaynak
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
        if satir is None:
            continue
        if satir.durum == "bekliyor":  # Jira çağrısı sürüyor ya da sonucu belirsiz
            raise WorkflowError(
                f"{k} varsayımının PO'ya gönderimi sürüyor ya da sonucu belirsiz "
                f"({satir.etiket}); açık sorular ekranından gönderimi tamamlayın"
            )
        if satir.durum == "gonderildi":
            raise WorkflowError(
                f"{k} varsayımı PO'ya doğrulatılmak üzere gönderildi ({satir.etiket}); PO yanıtı "
                "bekleniyor. Yanıt gelince 'Varsayım doğrulandı' ya da 'Düzelt' kullanın"
            )
        if not po_dogru_dedi(satir.yanit):
            raise WorkflowError(
                f"PO {satir.etiket} ({k}) varsayımına kesin 'doğru' dışında (ek koşullu ya da "
                "açıklamalı) yanıt verdi; case'i PO yanıtına göre 'Düzelt' ile güncelleyin"
            )
        kaynak.append(satir.etiket)
    return kaynak

"""Oracle DB testlerinin yardımcıları: onaylı tablo, elle kontrol kaydı, sahte olgu modeli."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import func, select

from tp_core.audit import content_hash
from tp_core.features.oracle import service
from tp_core.features.oracle.tablolar import tablo_hashleri
from tp_core.gateway.matching import untrusted_blocks
from tp_core.gateway.testing import text_response
from tp_core.models import KararTablosu, Requirement, TestCase, session_scope
from tp_core.workflow.service import Principal, content_hash_of, record_approval, transition

# Basit tablo: toplam = adet × 10 (AC1). Case metni "adet N" / "Toplam X,00 TL" yazar.
BASIT = {
    "ad": "Basit toplam",
    "ac_refs": ["AC1"],
    "aciklama": "Her adet 10 TL",
    "girdiler": [{"ad": "adet", "tur": "sayi", "aciklama": "Sepetteki adet"}],
    "ciktilar": [{"ad": "toplam", "tur": "sayi", "birim": "TL", "tolerans": "0.01"}],
    "satirlar": [{"id": "R1", "kosul": "adet >= 1", "cikti": {"toplam": "adet * 10"}}],
}


def basit_case(adet: int = 3, toplam: str = "30,00", risk: str = "high", **over: Any) -> dict:
    icerik = {
        "title": f"{adet} adette toplam {toplam} TL",
        "type": "positive",
        "risk": risk,
        "acceptance_criteria_refs": ["AC1"],
        "preconditions": ["Sepet boş"],
        "steps": [
            {
                "id": "S1",
                "action": "Ürünü sepete ekle",
                "data": f"adet {adet}",
                "expected": "Eklenir",
            },
            {"id": "S2", "action": "Sepete git", "data": None, "expected": f"Toplam {toplam} TL"},
        ],
        "expected_result": f"Toplam {toplam} TL",
        "tags": ["AI-generated"],
    }
    icerik.update(over)
    return icerik


def tablo_ekle(rid: uuid.UUID, icerik: dict, analist: Principal, po: Principal) -> uuid.UUID:
    """Taslak → PO onayına → PO onayı (gerçek geçişler); `gereksinim_hash` güncel."""
    with session_scope() as s:
        req = s.get(Requirement, rid)
        n = (
            s.scalar(
                select(func.max(KararTablosu.sira_no)).where(KararTablosu.requirement_id == rid)
            )
            or 0
        ) + 1
        t = KararTablosu(
            requirement_id=rid,
            sira_no=n,
            icerik=icerik,
            icerik_hash=content_hash(icerik),
            olusturan_id=analist.id,
        )
        s.add(t)
        s.flush()
        transition(s, t, "pending_po", analist, "draft")
        record_approval(s, t, po, "approve", beklenen_hash=t.icerik_hash)
        t.gereksinim_hash = content_hash_of(req)  # geçişten önce (0022 onay_hash_ck)
        transition(s, t, "approved", po, "pending_po")
        return t.id


def tablo_degistir(tid: uuid.UUID, icerik: dict, analist: Principal, po: Principal) -> None:
    """Yeniden aç → içerik değiştir → yeniden onayla (yeni `icerik_hash`)."""
    with session_scope() as s:
        t = s.get(KararTablosu, tid)
        transition(s, t, "draft", analist, "approved")
        t.icerik = icerik
        t.icerik_hash = content_hash(icerik)
        s.flush()
        transition(s, t, "pending_po", analist, "draft")
        record_approval(s, t, po, "approve", beklenen_hash=t.icerik_hash)
        transition(s, t, "approved", po, "pending_po")


def uyumsuz_ayrinti(tablo_id: str = "t", case_degeri: str = "40.00") -> dict[str, Any]:
    return {
        "gruplar": [
            {
                "tablo_id": tablo_id,
                "tablo_ad": "Basit toplam",
                "satir_id": "R1",
                "girdiler": [
                    {"column": "adet", "value": "3", "field": "steps[0].data", "quote": "adet 3"}
                ],
                "karsilastirmalar": [
                    {
                        "column": "toplam",
                        "alan": "expected_result",
                        "alinti": f"{case_degeri.replace('.', ',')} TL",
                        "case_degeri": case_degeri,
                        "tablo_degeri": "30",
                        "uyumlu": False,
                    }
                ],
                "durum": "uyumsuz",
                "neden": None,
            }
        ],
        "atilan_olgular": 0,
    }


def kayit_yaz(
    cid: uuid.UUID,
    sonuc: str,
    ayrintilar: dict | None = None,
    *,
    icerik_hash: str | None = None,
    icerik: dict | None = None,
    hashler: dict[str, str] | None = None,
    ai_icerik: bool = True,
) -> None:
    """Elle kontrol kaydı (güncel kapsayan tablolarla; `hashler` verilirse onunla)."""
    with session_scope() as s:
        tc = s.get(TestCase, cid)
        h = icerik_hash or tc.icerik_hash
        if hashler is None:
            hashler = tablo_hashleri(service.kapsayan_tablolar(s, tc, icerik))
        service._kaydet(
            s,
            cid,
            h,
            sonuc=sonuc,
            ayrintilar=ayrintilar or {"gruplar": [], "atilan_olgular": 0},
            hashler=hashler,
            ai_icerik=ai_icerik,
            call_id=None,
            mod=None,
        )


def olgu_modeli(request: Any) -> Any:
    """Sahte `case_facts` modeli: case bloğundan `adet N` ve `Toplam X TL`'yi alıntılar."""
    bloklar = untrusted_blocks(request.messages)
    case = json.loads(next(b.body for b in bloklar if b.source.startswith("case:")))
    tablolar = json.loads(next(b.body for b in bloklar if b.source == "karar-tablosu:kolonlar"))
    veri = case["steps"][0]["data"] or ""
    adet = re.search(r"adet (\d+)", veri)
    toplam = re.search(r"(\d+,\d\d) TL", case["expected_result"])
    grup: dict[str, Any] = {"table_ref": tablolar[0]["ref"], "inputs": [], "expected": []}
    if adet:
        grup["inputs"].append(
            {
                "column": "adet",
                "value": adet.group(1),
                "field": "steps[0].data",
                "quote": adet.group(0),
            }
        )
    # Beklenen alanlardaki her geçiş ayrı olgu (tamlık denetimi; prompt v2).
    alanlar = [("expected_result", case["expected_result"])] + [
        (f"steps[{i}].expected", adim.get("expected") or "") for i, adim in enumerate(case["steps"])
    ]
    if toplam:
        for alan, metin in alanlar:
            m = re.search(r"(\d+,\d\d) TL", metin)
            if m:
                grup["expected"].append(
                    {
                        "column": "toplam",
                        "value": m.group(1).replace(",", "."),
                        "field": alan,
                        "quote": f"{m.group(1)} TL",
                    }
                )
    return text_response({"groups": [grup], "ignored": []})

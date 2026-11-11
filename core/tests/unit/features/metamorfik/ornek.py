"""Metamorfik testlerinin ortak örnek verisi: P-004 (kampanyasız, 30,00 TL) × 25 = 750,00 TL."""

from __future__ import annotations

import copy
from typing import Any

TABLO_ID = "11111111-1111-1111-1111-111111111111"

ILISKI: dict[str, Any] = {
    "ad": "Adet iki katı",
    "ac_refs": ["AC1"],
    "tablo_ref": "T1",
    "on_kosul": "adet >= 1 ve adet * 2 <= 999",
    "donusum": {"adet": "adet * 2"},
    "iliski": {"ara_tutar": "ara_tutar * 2"},
    "aciklama": "Kampanyasız üründe geçerlidir",
}

TABLO: dict[str, Any] = {
    "ad": "Ara tutar",
    "ac_refs": ["AC1"],
    "girdiler": [{"ad": "adet", "tur": "sayi"}, {"ad": "birim_fiyat", "tur": "sayi"}],
    "ciktilar": [{"ad": "ara_tutar", "tur": "sayi", "tolerans": "0.01"}],
    "satirlar": [{"id": "R1", "kosul": "dogru", "cikti": {"ara_tutar": "adet * birim_fiyat"}}],
}


def case_icerik() -> dict[str, Any]:
    return {
        "title": "Kampanyasız üründe satır tutarı (P-004)",
        "type": "positive",
        "risk": "medium",
        "acceptance_criteria_refs": ["AC1"],
        "preconditions": ["bayi1 ile giriş yapılmış", "P-004 birim fiyatı 30,00 TL"],
        "steps": [
            {
                "id": "S1",
                "action": "Ürün kataloğunu aç",
                "data": None,
                "expected": "Katalog açılır",
            },
            {
                "id": "S2",
                "action": "P-004 ürününden sepete ekle",
                "data": "25",
                "expected": "Sepette 25 adet P-004 görünür",
            },
            {
                "id": "S3",
                "action": "Sepeti aç",
                "data": None,
                "expected": "Satır tutarı 750,00 TL görünür",
            },
        ],
        "expected_result": "Ara toplam 750,00 TL olarak gösterilir",
        "tags": ["AI-generated", "sepet"],
    }


def olgu(column: str, value: str, field: str, quote: str) -> dict[str, Any]:
    return {"column": column, "value": value, "field": field, "quote": quote}


def karsilastirma(column: str, alan: str, alinti: str, deger: str) -> dict[str, Any]:
    return {
        "column": column,
        "alan": alan,
        "alinti": alinti,
        "case_degeri": deger,
        "tablo_degeri": deger,
        "uyumlu": True,
    }


def grup(tablo_id: str = TABLO_ID, **over: Any) -> dict[str, Any]:
    g: dict[str, Any] = {
        "tablo_id": tablo_id,
        "tablo_ad": "Ara tutar",
        "satir_id": "R1",
        "girdiler": [
            olgu("adet", "25", "steps[1].data", "25"),
            olgu("adet", "25", "steps[1].expected", "25"),
            olgu("birim_fiyat", "30.00", "preconditions[1]", "30,00 TL"),
        ],
        "karsilastirmalar": [
            karsilastirma("ara_tutar", "steps[2].expected", "750,00 TL", "750.00"),
            karsilastirma("ara_tutar", "expected_result", "750,00 TL", "750.00"),
        ],
        "durum": "uyumlu",
        "neden": None,
    }
    g.update(over)
    return g


def ayrintilar(*gruplar: dict[str, Any]) -> dict[str, Any]:
    return {"gruplar": [copy.deepcopy(g) for g in (gruplar or (grup(),))], "atilan_olgular": 0}

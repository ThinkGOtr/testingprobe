"""Demo story TPD-1 için karar tabloları ve `case_facts` golden'larının kaynağı (012 §4.3 REPLAY).

`TABLOLAR`: TPD-1'in PO onaylı metnine (AC2, AC3, AC6) göre iki karar tablosu — T1 kampanya,
T2 minimum sipariş. Ş1'in TPD-1 taslak golden'ı (decision_table_draft) aynı kolon adlarını
kullanmalıdır; ad farklı olursa olgular "bilinmeyen kolon" olarak atılır ve sonuç dürüstçe
`kontrol_edilemedi` olur.

`OLGULAR`: `rules/replay/case_generation/golden/TPD-1.json` case'lerinden dikkatli bir modelin
çıkaracağı olgular (case sıra no → `groups`). Alıntılar case alanlarından birebir kopyalanmıştır;
deterministik doğrulama (`features/oracle/dogrulama.py`) hepsini kabul eder. AC1/AC4/AC5 case'leri
(C1, C7, C8) hiçbir tabloyla kesişmez (`kapsam_disi`, model çağrılmaz) ve golden'ı yoktur.

Golden'lar bu modülden üretilir:

    cd core && uv run python -m tests.unit.features.oracle.tpd1

`test_tpd1_goldens.py` depodaki golden'ların bu modülün çıktısıyla aynı olduğunu denetler.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from tp_core.gateway import approved_case_text, find_rules_dir, golden_name

RULES = find_rules_dir()
STORY = "TPD-1"
_NS = uuid.UUID("6c1b5a1e-0f6e-4a55-9d5e-012000000001")

T1 = {
    "ad": "Kampanya: 6 al 1 bedava",
    "ac_refs": ["AC2"],
    "aciklama": "Kampanyalı üründe her 6 adette 1 adet bedava; indirim bedava adet × birim fiyat.",
    "girdiler": [
        {"ad": "adet", "tur": "sayi", "aciklama": "Kampanyalı üründen sepetteki adet"},
        {
            "ad": "ara_toplam",
            "tur": "sayi",
            "birim": "TL",
            "aciklama": "Kampanyalı ürün satırının indirim öncesi tutarı (adet × birim fiyat)",
        },
    ],
    "ciktilar": [
        {"ad": "bedava_adet", "tur": "sayi", "aciklama": "Bedava verilen adet"},
        {
            "ad": "indirim",
            "tur": "sayi",
            "birim": "TL",
            "tolerans": "0.01",
            "aciklama": "Kampanya indirimi",
        },
        {
            "ad": "toplam",
            "tur": "sayi",
            "birim": "TL",
            "tolerans": "0.01",
            "aciklama": "İndirim sonrası tutar",
        },
    ],
    "satirlar": [
        {
            "id": "R1",
            "kosul": "adet >= 1",
            "cikti": {
                "bedava_adet": "adet // 6",
                "indirim": "(adet // 6) * (ara_toplam / adet)",
                "toplam": "ara_toplam - (adet // 6) * (ara_toplam / adet)",
            },
        }
    ],
}

T2 = {
    "ad": "Minimum sipariş tutarı",
    "ac_refs": ["AC3", "AC6"],
    "aciklama": "Kampanyasız siparişte indirim sonrası toplam en az 750,00 TL; kampanyalı muaf.",
    "girdiler": [
        {"ad": "toplam", "tur": "sayi", "birim": "TL", "aciklama": "İndirim sonrası sepet toplamı"},
        {"ad": "kampanyali", "tur": "mantiksal", "aciklama": "Sepette kampanyalı ürün var mı"},
    ],
    "ciktilar": [
        {
            "ad": "minimum_uyarisi",
            "tur": "mantiksal",
            "aciklama": "Minimum sipariş tutarı uyarısı gösterilir mi",
        },
        {"ad": "onay_aktif", "tur": "mantiksal", "aciklama": "Siparişi onayla butonu aktif mi"},
    ],
    "satirlar": [
        {
            "id": "R1",
            "kosul": "kampanyali",
            "cikti": {"minimum_uyarisi": "yanlis", "onay_aktif": "dogru"},
        },
        {
            "id": "R2",
            "kosul": "toplam < 750",
            "cikti": {"minimum_uyarisi": "dogru", "onay_aktif": "yanlis"},
        },
        {
            "id": "R3",
            "kosul": "toplam >= 750",
            "cikti": {"minimum_uyarisi": "yanlis", "onay_aktif": "dogru"},
        },
    ],
}

TABLOLAR = {1: T1, 2: T2}  # sira_no → içerik (ref `T<sira_no>`)


def tablo_id(sira_no: int) -> str:
    """Değerlendirme setinde ve birim testlerde kullanılan sabit tablo kimliği."""
    return str(uuid.uuid5(_NS, f"{STORY}:T{sira_no}"))


def kolon_girdisi() -> list[dict[str, Any]]:
    """`cikarma.facts_messages`'a giden tablo listesi (sabit kimliklerle)."""
    return [{"ref": f"T{n}", "id": tablo_id(n), "icerik": TABLOLAR[n]} for n in sorted(TABLOLAR)]


def _o(column: str, value: Any, field: str, quote: str) -> dict[str, Any]:
    return {"column": column, "value": value, "field": field, "quote": quote}


def _kampanya(adet: str, ara: str, bedava: str, indirim: str, toplam: str) -> dict[str, Any]:
    """T1 grubu: S3 verisi `P-001 × n`, S4 beklenen satır/tutar metni (`steps[3].expected`)."""
    s4 = "steps[3].expected"
    return {
        "table_ref": "T1",
        "inputs": [
            _o("adet", adet, "steps[2].data", adet),
            _o("ara_toplam", ara.replace(",", "."), s4, f"{ara} TL"),
        ],
        "expected": [
            _o("bedava_adet", bedava, s4, f"adet {bedava}"),
            _o("indirim", indirim.replace(",", "."), s4, f"{indirim} TL"),
            _o("toplam", toplam.replace(",", "."), s4, f"{toplam} TL"),
        ],
    }


def _minimum(
    toplam: str, kampanyali: bool, kampanya_alintisi: str, uyari: bool, onay: bool
) -> dict[str, Any]:
    s4 = "steps[3].expected"
    return {
        "table_ref": "T2",
        "inputs": [
            _o("toplam", toplam.replace(",", "."), s4, f"{toplam} TL"),
            _o("kampanyali", kampanyali, "preconditions[1]", kampanya_alintisi),
        ],
        "expected": [
            _o("minimum_uyarisi", uyari, s4, "uyarısı görünür" if uyari else "uyarısı görünmez"),
            _o("onay_aktif", onay, s4, "butonu aktiftir" if onay else "butonu pasiftir"),
        ],
    }


KAMPANYALI = 'P-001 "6 al 1 bedava" kampanyasında'
KAMPANYASIZ = "Sepette kampanyalı ürün yok"

OLGULAR: dict[int, list[dict[str, Any]]] = {
    2: [_kampanya("7", "175,00", "1", "25,00", "150,00")],
    3: [_kampanya("6", "150,00", "1", "25,00", "125,00")],
    4: [_kampanya("5", "125,00", "0", "0,00", "125,00")],
    5: [_minimum("150,00", False, KAMPANYASIZ, True, False)],
    6: [_minimum("750,00", False, KAMPANYASIZ, False, True)],
    9: [_minimum("150,00", True, KAMPANYALI, False, True)],
    10: [_kampanya("7", "175,00", "1", "25,00", "150,00")],
}
# Golden'ı olmayan (hiçbir tabloyla kesişmeyen) case'ler ve beklenen sonuçlar.
KAPSAM_DISI = (1, 7, 8)
BEKLENEN_SONUC = {n: "uyumlu" for n in OLGULAR} | {n: "kapsam_disi" for n in KAPSAM_DISI}

NOTE = (
    "Adlandırılmış golden kayıt (REPLAY-MISS yedeği). Olgular elle hazırlandı (canlı model çıktısı "
    "değil; ai_call.model = golden-elle): case_generation/golden/TPD-1 case'inden dikkatli bir "
    "modelin çıkaracağı değerler, alıntılar case alanlarından birebir. Kolon adları TPD-1 demo "
    "tablolarınındır (T1 kampanya, T2 minimum sipariş; core/tests/unit/features/oracle/tpd1.py). "
    "Üretildi: python -m tests.unit.features.oracle.tpd1 (elle düzenlemeyin). Girdi beyanı "
    "(input_match.case_text) eşleşirse mod REPLAY (köken golden_matched); case düzeltilir ya da "
    "önerilen içerik farklıysa REPLAY-MISS ve nötr çıktı (groups: [] → kontrol_edilemedi). "
    "Canlı modelle yeniden kaydedilmeli (TP_MODEL_MODE=record)."
)


def tpd1_cases() -> list[dict[str, Any]]:
    path = RULES / "replay" / "case_generation" / "golden" / f"{STORY}.json"
    return json.loads(path.read_text(encoding="utf-8"))["output"]["cases"]


def build_goldens() -> dict[str, dict[str, Any]]:
    cases = tpd1_cases()
    out = {}
    for n, groups in OLGULAR.items():
        case = cases[n - 1]
        ad = golden_name(STORY, case_no=n)
        out[ad] = {
            "kind": "call",
            "purpose": "case_facts",
            "golden": ad,
            "note": NOTE,
            "input_match": {"sources": [f"case:{ad}"], "case_text": approved_case_text(case)},
            "case": {"jira_key": STORY, "sira_no": n, "title": case["title"], "case_golden": STORY},
            "output": {"groups": groups},
        }
    return out


def dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def golden_dir(rules_dir: Path = RULES) -> Path:
    return rules_dir / "replay" / "case_facts" / "golden"


def write_goldens(rules_dir: Path = RULES) -> list[Path]:
    out = []
    for ad, data in build_goldens().items():
        path = golden_dir(rules_dir) / f"{ad}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(data), encoding="utf-8")
        out.append(path)
    return out


if __name__ == "__main__":  # pragma: no cover
    for p in write_goldens():
        print(p)

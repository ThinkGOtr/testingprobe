"""Demo story TPD-1 için karar tabloları ve `case_facts` golden'larının kaynağı (012 §4.3 REPLAY).

`TABLOLAR`: Ş1'in AI taslak golden'ından (`rules/replay/decision_table_draft/golden/TPD-1.json`)
YÜKLENİR — analistin düzenleyip PO'nun demoda onayladığı tablolar bunlardır; burada kopya yoktur.
Model çıktısı `karar_tablosu.service.taslak_tablo_icerigi` ile içerik biçimine çevrilir (worker'ın
yazdığıyla aynı). T1 "Kampanya: 6 al 1 bedava (7 adette 1 bedava)" (AC2; girdiler `adet`,
`birim_fiyat`; çıktılar `bedava_adet = adet // 7`, `indirim`), T2 "Minimum sipariş tutarı" (AC3,
AC6; girdiler `kampanyali_sepet`, `sepet_tutari`; çıktı `minimum_uyarisi`, eşik 750). Tablolar
story'yi izler (7 adette 1 bedava), demo uygulamanın kodunu değil (`adet // 6`).

`OLGULAR`: case_generation golden'larının case'lerinden dikkatli bir modelin çıkaracağı olgular.
Alıntılar case alanlarından birebirdir; deterministik doğrulama (`features/oracle/dogrulama.py`)
hepsini kabul eder (`test_cikarma_golden.py` denetler). Bir değer case'te birden çok yerde
geçiyorsa (başlık, eylem, veri, beklenen, sonuç) her geçiş ayrı olgudur: metamorfik türetme
değişen her alıntının bütün kopyalarını ister. Case'lerde birim fiyat yazmaz: `birim_fiyat` olgusu
YOKTUR (uydurulmaz); T1'de birim fiyata dayanan `indirim` yalnız R2'de (7'den az, sabit 0)
karşılaştırılır, R1'de `karsilastirilamayan` olur (`dogrulama.kismi_degerlendir`).

İki case kaynağı vardır:

- Ana golden (`case_generation/golden/TPD-1.json`): F2 `fix_doc` alternatifi + senaryonun
  değişmeyen case'leri. C3 burada "6 adette 1 bedava"dır (koda uyarlanmış AC2).
- Senaryo golden'ı `f2-kod-hatasi/TPD-1.json` (demo ANA yolu, AC2 özgün): tek farkı C3'tür —
  "6 adette bedava yok" (story). `case_facts` golden'ı `f2-kod-hatasi/TPD-1-C3.json`'dur.

AC1/AC4/AC5 case'leri (C1, C7, C8) hiçbir tabloyla kesişmez (`kapsam_disi`, model çağrılmaz) ve
golden'ı yoktur.

Golden'lar bu modülden üretilir:

    cd core && uv run python -m tests.unit.features.oracle.tpd1

`test_cikarma_golden.py` depodaki golden'ların bu modülün çıktısıyla aynı olduğunu denetler.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from tp_core.gateway import approved_case_text, find_rules_dir, golden_name

RULES = find_rules_dir()
STORY = "TPD-1"
SENARYO = "f2-kod-hatasi"  # demo ana yolu (AC2 özgün; F2 code_defect)
_NS = uuid.UUID("6c1b5a1e-0f6e-4a55-9d5e-012000000001")


def taslak_golden() -> dict[str, Any]:
    path = RULES / "replay" / "decision_table_draft" / "golden" / f"{STORY}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _tablolar() -> dict[int, dict[str, Any]]:
    from tp_core.features.karar_tablosu.service import taslak_tablo_icerigi

    out: dict[int, dict[str, Any]] = {}
    for n, oge in enumerate(taslak_golden()["output"]["tables"], start=1):
        icerik, hatalar = taslak_tablo_icerigi(oge)
        assert not hatalar, hatalar
        out[n] = icerik
    return out


def _iliski() -> dict[str, Any]:
    from tp_core.features.karar_tablosu.service import taslak_iliski_icerigi

    [oge] = taslak_golden()["output"]["relations"]
    icerik, hatalar = taslak_iliski_icerigi(oge)
    assert not hatalar, hatalar
    return {**icerik, "tablo_ref": oge["tablo_ref"]}


TABLOLAR = _tablolar()  # sira_no → içerik (ref `T<sira_no>`)
T1, T2 = TABLOLAR[1], TABLOLAR[2]
ILISKI = _iliski()  # T1: adet 7'nin katıyken ×2 → bedava adet ve indirim ×2


def tablo_id(sira_no: int) -> str:
    """Değerlendirme setinde ve birim testlerde kullanılan sabit tablo kimliği."""
    return str(uuid.uuid5(_NS, f"{STORY}:T{sira_no}"))


def kolon_girdisi() -> list[dict[str, Any]]:
    """`cikarma.facts_messages`'a giden tablo listesi (sabit kimliklerle)."""
    return [{"ref": f"T{n}", "id": tablo_id(n), "icerik": TABLOLAR[n]} for n in sorted(TABLOLAR)]


def _o(column: str, value: Any, field: str, quote: str) -> dict[str, Any]:
    return {"column": column, "value": value, "field": field, "quote": quote}


S3_EYLEM, S3_VERI, S3_BEKLENEN = "steps[2].action", "steps[2].data", "steps[2].expected"
S4 = "steps[3].expected"
SONUC = "expected_result"


def _kampanya(
    adet: str, bedava: str, indirim: str, *, adet_baslikta: bool, bedava_metinde: bool
) -> dict[str, Any]:
    """T1 grubu. Adet: S3 eylemi ("adedi 7"), verisi ("P-001 × 7"), beklenen sayaç ("Sepet sayacı
    7"), S4 satırı ("adet 7"), sonuç ("7 adette") ve varsa başlık. Bedava: S4 ve sonuçtaki
    "bedava adet N" ("adet N" alıntısı) ya da "N adet bedava" ("N adet"). İndirim: S4 ve sonuç."""
    girdi = [
        _o("adet", adet, alan, adet)
        for alan in (
            *(("title",) if adet_baslikta else ()),
            S3_EYLEM,
            S3_VERI,
            S3_BEKLENEN,
            S4,
            SONUC,
        )
    ]
    bedava_olgulari = [_o("bedava_adet", bedava, S4, f"adet {bedava}")]
    if bedava_metinde:  # "… 1 adet bedava verilir" (başlık ve sonuç)
        bedava_olgulari = [
            _o("bedava_adet", bedava, "title", f"{bedava} adet"),
            *bedava_olgulari,
            _o("bedava_adet", bedava, SONUC, f"{bedava} adet"),
        ]
    else:  # "… bedava adet 0 olur" (sonuç)
        bedava_olgulari.append(_o("bedava_adet", bedava, SONUC, f"adet {bedava}"))
    deger = indirim.replace(",", ".")
    return {
        "table_ref": "T1",
        "inputs": girdi,
        "expected": [
            *bedava_olgulari,
            _o("indirim", deger, S4, f"{indirim} TL"),
            _o("indirim", deger, SONUC, f"{indirim} TL"),
        ],
    }


KAMPANYASIZ = (False, "preconditions[1]", "Sepette kampanyalı ürün yok")


def _minimum(
    kampanya: tuple[bool, str, str],
    tutar: str,
    tutar_alanlari: tuple[str, ...],
    uyari: bool,
    uyari_alintilari: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    kampanyali, k_alan, k_alinti = kampanya
    return {
        "table_ref": "T2",
        "inputs": [
            _o("kampanyali_sepet", kampanyali, k_alan, k_alinti),
            *[
                _o("sepet_tutari", tutar.replace(",", "."), a, f"{tutar} TL")
                for a in tutar_alanlari
            ],
        ],
        "expected": [_o("minimum_uyarisi", uyari, a, q) for a, q in uyari_alintilari],
    }


C2 = _kampanya("7", "1", "25,00", adet_baslikta=True, bedava_metinde=True)
OLGULAR: dict[int, list[dict[str, Any]]] = {
    2: [C2],
    # Ana golden C3 (fix_doc alternatifi: "6 adette 1 bedava"): story tablosuyla uyuşmaz.
    3: [_kampanya("6", "1", "25,00", adet_baslikta=True, bedava_metinde=True)],
    4: [_kampanya("5", "0", "0,00", adet_baslikta=True, bedava_metinde=False)],
    5: [
        _minimum(
            KAMPANYASIZ,
            "150,00",
            (S4,),
            True,
            (
                (S4, '"Minimum sipariş tutarı 750,00 TL" uyarısı görünür'),
                (SONUC, '"Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir'),
            ),
        )
    ],
    6: [
        _minimum(
            KAMPANYASIZ,
            "750,00",
            (S4, SONUC),
            False,
            ((S4, "minimum sipariş uyarısı görünmez"), (SONUC, "uyarı gösterilmez")),
        )
    ],
    9: [
        _minimum(
            (True, SONUC, "Kampanyalı sepette"),
            "150,00",
            (S4, SONUC),
            False,
            (
                (S4, "minimum sipariş uyarısı görünmez"),
                (SONUC, "minimum sipariş uyarısı gösterilmez"),
            ),
        )
    ],
    # C10, C2'nin bilerek tekrarıdır; başlığında "7" geçer, bedava adet geçmez.
    10: [_kampanya("7", "1", "25,00", adet_baslikta=True, bedava_metinde=False)],
}
# C10'un sonuç metni "7 adette 1 adet bedava verilir" (C2 ile aynı): bedava olgusu "1 adet".
OLGULAR[10][0]["expected"][1] = _o("bedava_adet", "1", SONUC, "1 adet")

# Senaryo (demo ana yolu) C3: "6 adette bedava adet 0 olur (bedava 7. adette başlar)".
SENARYO_OLGULARI: dict[int, list[dict[str, Any]]] = {
    3: [_kampanya("6", "0", "0,00", adet_baslikta=True, bedava_metinde=False)],
}

# Golden'ı olmayan (hiçbir tabloyla kesişmeyen) case'ler.
KAPSAM_DISI = (1, 7, 8)

# Story tablolarıyla (T1 `adet // 7`, T2 eşik 750) dürüst sonuçlar. Ana yol = senaryo.
BEKLENEN_SONUC_ANA_YOL: dict[int, str] = {
    1: "kapsam_disi",
    2: "uyumlu",  # bedava 1 = 7 // 7; indirim karşılaştırılamadı (birim fiyat case'te yok)
    3: "uyumlu",  # bedava 0, indirim 0 = R2 (uygulama 6 // 6 = 1 verir → defect adayı)
    4: "uyumlu",
    5: "uyumlu",
    6: "uyumlu",
    7: "kapsam_disi",
    8: "kapsam_disi",
    9: "uyumlu",
    10: "uyumlu",
}
# Ana golden (fix_doc alternatifi) yalnız C3'te farklıdır: "6 adette 1 bedava" story tablosuyla
# uyuşmaz (bu yolda AC2 değiştiği için Ş1 taslağı REPLAY-MISS olur; tablo elle yazılmadıkça C3
# kontrol edilmez). Onay kapısının gösterimi için saf testlerde kullanılır.
BEKLENEN_SONUC_FIX_DOC = {**BEKLENEN_SONUC_ANA_YOL, 3: "uyumsuz"}

NOTE = (
    "Adlandırılmış golden kayıt (REPLAY-MISS yedeği). Olgular elle hazırlandı (canlı model çıktısı "
    "değil; ai_call.model = golden-elle): case_generation golden'ındaki case'ten dikkatli bir "
    "modelin çıkaracağı değerler, alıntılar case alanlarından birebir; birim fiyat case'te "
    "yazmadığı için çıkarılmadı. Kolon adları Ş1'in TPD-1 taslak golden'ındaki demo "
    "tablolarınındır (T1 kampanya: adet, birim_fiyat → bedava_adet, indirim; T2 minimum sipariş: "
    "kampanyali_sepet, sepet_tutari → minimum_uyarisi). Üretildi: python -m "
    "tests.unit.features.oracle.tpd1 (elle düzenlemeyin). Girdi beyanı (input_match.case_text) "
    "eşleşirse mod REPLAY (köken golden_matched); case düzeltilir ya da önerilen içerik farklıysa "
    "REPLAY-MISS ve nötr çıktı (groups: [] → kontrol_edilemedi). Canlı modelle yeniden "
    "kaydedilmeli (TP_MODEL_MODE=record)."
)


def tpd1_cases(senaryo: str | None = None) -> list[dict[str, Any]]:
    """Ana (`None`) ya da senaryo (`f2-kod-hatasi`) case_generation golden'ının case'leri."""
    alt = f"{senaryo}/" if senaryo else ""
    path = RULES / "replay" / "case_generation" / "golden" / f"{alt}{STORY}.json"
    return json.loads(path.read_text(encoding="utf-8"))["output"]["cases"]


def ana_yol_cases() -> list[dict[str, Any]]:
    return tpd1_cases(SENARYO)


def _golden(senaryo: str | None, n: int, groups: list[dict[str, Any]]) -> tuple[str, dict]:
    case = tpd1_cases(senaryo)[n - 1]
    ad = golden_name(STORY, case_no=n)
    tam = f"{senaryo}/{ad}" if senaryo else ad
    return tam, {
        "kind": "call",
        "purpose": "case_facts",
        "golden": tam,
        "note": NOTE,
        "input_match": {"sources": [f"case:{ad}"], "case_text": approved_case_text(case)},
        "case": {
            "jira_key": STORY,
            "sira_no": n,
            "title": case["title"],
            "case_golden": f"{senaryo}/{STORY}" if senaryo else STORY,
        },
        "output": {"groups": groups},
    }


def build_goldens() -> dict[str, dict[str, Any]]:
    """`<ad>` ya da `<senaryo>/<ad>` → golden kaydı."""
    out = dict(_golden(None, n, g) for n, g in OLGULAR.items())
    out.update(_golden(SENARYO, n, g) for n, g in SENARYO_OLGULARI.items())
    return out


def olgular(n: int, senaryo: str | None = SENARYO) -> list[dict[str, Any]] | None:
    """Case'in golden olguları (senaryo case'i varsa o; golden yoksa None)."""
    if senaryo and n in SENARYO_OLGULARI:
        return SENARYO_OLGULARI[n]
    return OLGULAR.get(n)


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

"""Düzeltme ölçüsü ve kabul oranı (TEKNIK-TASARIM §12, Constitution X).

**Düzeltme ölçüsü (alan bazlı normalize karakter düzenleme mesafesi):** case şemasının her alanı
(başlık, tür, risk, AC referansları, ön koşullar, her adımın eylem/veri/beklenen metni, beklenen
sonuç, etiketler) NFKC + küçük harf + boşluk sadeleştirmesiyle normalize edilir. Alan başına
Levenshtein mesafesi hesaplanır; toplam mesafe / toplam (alan başına uzun olanın uzunluğu)
= `mesafe` (0 = aynı, 1 = tamamen farklı).

**Küçük düzeltme:** `mesafe ≤ 0,15` **ve** beklenen sonuç anlamca değişmemiş. "Anlamca" insan
yargısıdır (§12 etiketleme protokolü); portal bu yargıyı göndermezse deterministik vekil kullanılır:
normalize `expected_result` metni aynı kaldıysa "değişmedi" sayılır. Hangi kaynağın kullanıldığı
`beklenen_sonuc_kaynagi` alanında (`insan` | `metin_karsilastirma`) kayıtlıdır.

**Kabul oranı:** ilk insan kararına göre (yeniden açıp tekrar onaylamak oranı şişirmez):
`approve` veya küçük düzeltmeli `edit` sayılır; payda üretilen (AI) case sayısıdır.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

KUCUK_DUZELTME_ESIGI = 0.15
KABUL_HEDEFI = 0.70


def normalize_text(deger: Any) -> str:
    if deger is None:
        return ""
    metin = unicodedata.normalize("NFKC", str(deger)).casefold()
    return re.sub(r"\s+", " ", metin).strip()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    onceki = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        simdiki = [i]
        for j, cb in enumerate(b, start=1):
            simdiki.append(min(onceki[j] + 1, simdiki[j - 1] + 1, onceki[j - 1] + (ca != cb)))
        onceki = simdiki
    return onceki[-1]


def _liste(deger: Any) -> str:
    return "\n".join(normalize_text(x) for x in (deger or []))


def fields(icerik: Mapping[str, Any]) -> dict[str, str]:
    """Case içeriğinin normalize alanları (adımlar konuma göre: `steps[1].action` …)."""
    out = {
        "title": normalize_text(icerik.get("title")),
        "type": normalize_text(icerik.get("type")),
        "risk": normalize_text(icerik.get("risk")),
        "acceptance_criteria_refs": _liste(icerik.get("acceptance_criteria_refs")),
        "preconditions": _liste(icerik.get("preconditions")),
        "expected_result": normalize_text(icerik.get("expected_result")),
        "tags": _liste(sorted(str(t) for t in icerik.get("tags") or [])),
    }
    for i, adim in enumerate(icerik.get("steps") or [], start=1):
        adim = adim if isinstance(adim, Mapping) else {}
        for alan in ("action", "data", "expected"):
            out[f"steps[{i}].{alan}"] = normalize_text(adim.get(alan))
    return out


def edit_metrics(
    once: Mapping[str, Any],
    sonra: Mapping[str, Any],
    *,
    beklenen_anlam_degisti: bool | None = None,
) -> dict[str, Any]:
    """İnsan düzeltmesinin ölçüleri (`review.duzeltme_olculeri`'ne yazılır)."""
    a, b = fields(once), fields(sonra)
    toplam_mesafe = 0
    toplam_uzunluk = 0
    alanlar: dict[str, float] = {}
    for alan in sorted(set(a) | set(b)):
        x, y = a.get(alan, ""), b.get(alan, "")
        uzunluk = max(len(x), len(y))
        if uzunluk == 0:
            continue
        d = levenshtein(x, y)
        toplam_mesafe += d
        toplam_uzunluk += uzunluk
        if d:
            alanlar[alan] = round(d / uzunluk, 4)
    mesafe = round(toplam_mesafe / toplam_uzunluk, 4) if toplam_uzunluk else 0.0
    if beklenen_anlam_degisti is None:
        degisti = a["expected_result"] != b["expected_result"]
        kaynak = "metin_karsilastirma"
    else:
        degisti = bool(beklenen_anlam_degisti)
        kaynak = "insan"
    return {
        "mesafe": mesafe,
        "duzenlenen_karakter": toplam_mesafe,
        "alanlar": alanlar,
        "degisen_alanlar": sorted(alanlar),
        "beklenen_sonuc_degisti": degisti,
        "beklenen_sonuc_kaynagi": kaynak,
        "esik": KUCUK_DUZELTME_ESIGI,
        "kucuk_duzeltme": mesafe <= KUCUK_DUZELTME_ESIGI and not degisti,
    }


def first_decision_accepted(karar: str, olculer: Mapping[str, Any] | None) -> bool:
    """İlk insan kararı "kabul" mü (approve ya da küçük düzeltmeli edit)?"""
    if karar == "approve":
        return True
    if karar == "edit":
        return bool((olculer or {}).get("kucuk_duzeltme"))
    return False

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

**Kabul oranı:** Testçinin ilk içerik kararına göre (yeniden açıp tekrar kabul etmek oranı
şişirmez): `accept` (012 öncesi kayıtlarda analistin doğrudan `approve`'u) veya küçük düzeltmeli
`edit` sayılır; payda üretilen (AI) case sayısıdır. Analistin son onayı (`approve` / `send_back`)
bu orana girmez; ayrı "son onay" ölçümüdür (specs/012-rol-yetki/ANALIZ.md §5).
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
    """İlk Testçi kararı "kabul" mü (accept / eski approve ya da küçük düzeltmeli edit)?"""
    if karar in ("accept", "approve"):
        return True
    if karar == "edit":
        return bool((olculer or {}).get("kucuk_duzeltme"))
    return False


# ------------------------------------------------- AI özgün ↔ insan düzeltmesi farkı (§8.10)

ALAN_ETIKETI = {
    "title": "Başlık",
    "type": "Tür",
    "risk": "Risk",
    "acceptance_criteria_refs": "AC atıfları",
    "preconditions": "Ön koşullar",
    "expected_result": "Beklenen sonuç",
    "tags": "Etiketler",
}
ADIM_ETIKETI = {"action": "eylem", "data": "veri", "expected": "beklenen"}


def _ham(deger: Any, ayirici: str = "\n") -> str:
    if deger is None:
        return ""
    if isinstance(deger, list | tuple):
        return ayirici.join("" if x is None else str(x) for x in deger)
    return str(deger)


def display_fields(icerik: Mapping[str, Any]) -> dict[str, str]:
    """Gösterim için alanlar (normalize EDİLMEMİŞ ham metin; anahtarlar `fields()` ile aynı)."""
    out = {
        "title": _ham(icerik.get("title")),
        "type": _ham(icerik.get("type")),
        "risk": _ham(icerik.get("risk")),
        "acceptance_criteria_refs": _ham(icerik.get("acceptance_criteria_refs"), ", "),
        "preconditions": _ham(icerik.get("preconditions")),
        "expected_result": _ham(icerik.get("expected_result")),
        "tags": _ham(sorted(str(t) for t in icerik.get("tags") or []), ", "),
    }
    for i, adim in enumerate(icerik.get("steps") or [], start=1):
        adim = adim if isinstance(adim, Mapping) else {}
        for alan in ("action", "data", "expected"):
            out[f"steps[{i}].{alan}"] = _ham(adim.get(alan))
    return out


def _etiket(alan: str) -> str:
    if alan in ALAN_ETIKETI:
        return ALAN_ETIKETI[alan]
    m = re.fullmatch(r"steps\[(\d+)\]\.(\w+)", alan)
    if m:
        return f"Adım {m.group(1)} — {ADIM_ETIKETI.get(m.group(2), m.group(2))}"
    return alan


def field_diff(once: Mapping[str, Any], sonra: Mapping[str, Any]) -> list[dict[str, str]]:
    """Alan bazlı fark: `[{alan, etiket, once, sonra}]` (yalnızca değişen alanlar, şema sırası).

    Değişiklik ölçüsüyle aynı alan kümesi kullanılır; yalnızca normalize (büyük/küçük harf,
    boşluk) farkı olan alanlar ölçüye girmediği için burada da gösterilmez.
    """
    a, b = display_fields(once), display_fields(sonra)
    na, nb = fields(once), fields(sonra)
    sira = list(a) + [k for k in b if k not in a]
    return [
        {"alan": k, "etiket": _etiket(k), "once": a.get(k, ""), "sonra": b.get(k, "")}
        for k in sira
        if na.get(k, "") != nb.get(k, "")
    ]


def _sayi(x: Any) -> str:
    return f"{float(x):.3f}".replace(".", ",")


def edit_reason(olculer: Mapping[str, Any] | None) -> str | None:
    """Düzeltmenin neden "küçük düzeltme" sayıldığı/sayılmadığı (Türkçe, kullanıcıya gösterilir)."""
    if not olculer or "mesafe" not in olculer:
        return None
    mesafe = olculer.get("mesafe") or 0.0
    esik = olculer.get("esik", KUCUK_DUZELTME_ESIGI)
    degisti = bool(olculer.get("beklenen_sonuc_degisti"))
    kaynak = (
        "analistin beyanı"
        if olculer.get("beklenen_sonuc_kaynagi") == "insan"
        else "beklenen sonuç metni değişti"
    )
    if olculer.get("kucuk_duzeltme"):
        return (
            f"Küçük düzeltme sayıldı: düzeltme ölçüsü {_sayi(mesafe)} ≤ {_sayi(esik)} ve "
            "beklenen sonuç değişmedi (ilk karar kabul sayılır)."
        )
    nedenler = []
    if degisti:
        nedenler.append(f"beklenen sonuç anlamca değişti ({kaynak})")
    if mesafe > esik:
        nedenler.append(f"düzeltme ölçüsü {_sayi(mesafe)} > eşik {_sayi(esik)}")
    return (
        "Küçük düzeltme sayılmadı: "
        + (" ve ".join(nedenler) or "ölçü eşiği aşıldı")
        + " (ilk karar kabul oranına girmez)."
    )


def union_ms(araliklar: list[tuple[Any, Any]]) -> int:
    """[başlangıç, bitiş] zaman aralıklarının birleşiminin toplam süresi (ms).

    Review süresi oturum başına duvar saatidir: aynı anda ekranda olan kartların örtüşen
    süreleri bir kez sayılır (kart başına sürelerin toplamı değil).
    """
    toplam = 0.0
    son_bas = son_bit = None
    for bas, bit in sorted((a, b) for a, b in araliklar if b >= a):
        if son_bit is None or bas > son_bit:
            if son_bit is not None:
                toplam += (son_bit - son_bas).total_seconds()
            son_bas, son_bit = bas, bit
        elif bit > son_bit:
            son_bit = bit
    if son_bit is not None:
        toplam += (son_bit - son_bas).total_seconds()
    return round(toplam * 1000)

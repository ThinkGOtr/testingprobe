"""`{veri:anahtar}` atfı: saf fonksiyonlar (veritabanı yok; specs/013-sprint-otomasyonu §3.3).

Sözleşme:
- Atıf biçimi `{veri:<anahtar>}`; anahtar `^[a-z0-9_]+(\\.[a-z0-9_]+){0,5}$`.
- `esle(metin, katalog)`: katalogdaki değerlerin metindeki tam geçişlerini atfa çevirir.
  Kurallar: değer en az 3 karakter; eşleşme kelime sınırında (önünde/arkasında harf-rakam yok);
  uzun değer önce; aynı değer birden çok anahtarda varsa (belirsiz) eşlenmez; zaten atıf içinde
  olan metne dokunulmaz.
- `coz(metin, degerler)`: atıfları değere çevirir. Değişmez: katalog değişmediyse
  `coz(esle(m, k), k) == m` (replay girdileri ve kod üretimindeki kaynak kontrolü bunu bekler).
- Case içeriğinde yalnız şu alanlar eşlenir/çözülür: `preconditions[]`, `steps[].action`,
  `steps[].data`, `steps[].expected`, `expected_result` (başlık okunabilirlik için değer kalır).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

ANAHTAR_DESEN = r"[a-z0-9_]+(?:\.[a-z0-9_]+){0,5}"
ANAHTAR_RE = re.compile(rf"^{ANAHTAR_DESEN}$")
ATIF_RE = re.compile(rf"\{{veri:({ANAHTAR_DESEN})\}}")
MIN_DEGER = 3


def atif(anahtar: str) -> str:
    if not ANAHTAR_RE.match(anahtar):
        raise ValueError(f"geçersiz test verisi anahtarı: {anahtar!r}")
    return f"{{veri:{anahtar}}}"


def atiflar(metin: str) -> list[str]:
    """Metindeki atıf anahtarları (sırayla, tekrarsız)."""
    return list(dict.fromkeys(ATIF_RE.findall(metin or "")))


def _tekil_degerler(katalog: Mapping[str, str]) -> dict[str, str]:
    """değer → anahtar; belirsiz (birden çok anahtarlı) ve kısa değerler çıkarılır."""
    sayac: dict[str, list[str]] = {}
    for anahtar, deger in katalog.items():
        if isinstance(deger, str) and len(deger.strip()) >= MIN_DEGER and deger == deger.strip():
            sayac.setdefault(deger, []).append(anahtar)
    return {d: a[0] for d, a in sayac.items() if len(a) == 1}


def esle(metin: str, katalog: Mapping[str, str]) -> str:
    """Değerleri atfa çevirir (yukarıdaki kurallar). `katalog`: anahtar → değer."""
    if not metin:
        return metin
    tekil = _tekil_degerler(katalog)
    if not tekil:
        return metin
    degerler = sorted(tekil, key=len, reverse=True)
    desen = re.compile(r"(?<![\w])(" + "|".join(re.escape(d) for d in degerler) + r")(?![\w])")
    # Mevcut atıfları koru: metni atıflar ve aradaki parçalar olarak böl.
    out: list[str] = []
    son = 0
    for m in ATIF_RE.finditer(metin):
        out.append(desen.sub(lambda x: atif(tekil[x.group(1)]), metin[son : m.start()]))
        out.append(m.group(0))
        son = m.end()
    out.append(desen.sub(lambda x: atif(tekil[x.group(1)]), metin[son:]))
    return "".join(out)


def coz(metin: str, degerler: Mapping[str, str], *, bilinmeyen: str = "hata") -> str:
    """Atıfları değerlerle değiştirir. `bilinmeyen`: "hata" (KeyError) | "birak"."""

    def _yerine(m: re.Match[str]) -> str:
        anahtar = m.group(1)
        if anahtar in degerler:
            return degerler[anahtar]
        if bilinmeyen == "birak":
            return m.group(0)
        raise KeyError(anahtar)

    return ATIF_RE.sub(_yerine, metin or "")


def _alanlari_donustur(case: Mapping[str, Any], f: Callable[[str], str]) -> dict[str, Any]:
    out = dict(case)
    if isinstance(out.get("preconditions"), list):
        out["preconditions"] = [f(p) if isinstance(p, str) else p for p in out["preconditions"]]
    if isinstance(out.get("steps"), list):
        adimlar = []
        for s in out["steps"]:
            if isinstance(s, Mapping):
                s = dict(s)
                for k in ("action", "data", "expected"):
                    if isinstance(s.get(k), str):
                        s[k] = f(s[k])
            adimlar.append(s)
        out["steps"] = adimlar
    if isinstance(out.get("expected_result"), str):
        out["expected_result"] = f(out["expected_result"])
    return out


def case_esle(case: Mapping[str, Any], katalog: Mapping[str, str]) -> dict[str, Any]:
    return _alanlari_donustur(case, lambda m: esle(m, katalog))


def case_coz(
    case: Mapping[str, Any], degerler: Mapping[str, str], *, bilinmeyen: str = "hata"
) -> dict[str, Any]:
    return _alanlari_donustur(case, lambda m: coz(m, degerler, bilinmeyen=bilinmeyen))


def case_atiflari(case: Mapping[str, Any]) -> list[str]:
    toplanan: list[str] = []

    def _topla(m: str) -> str:
        toplanan.extend(atiflar(m))
        return m

    _alanlari_donustur(case, _topla)
    return list(dict.fromkeys(toplanan))


def bilinmeyen_atiflar(case: Mapping[str, Any], anahtarlar: Iterable[str]) -> list[str]:
    bilinen = set(anahtarlar)
    return [a for a in case_atiflari(case) if a not in bilinen]

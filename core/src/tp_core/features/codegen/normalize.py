"""Beklenen değer kaynağı denetimi için metin normu (TEKNIK-TASARIM §8.4 adım 3).

Üretilen testin her assertion değeri onaylı case'in beklenen metninde **literal** geçmelidir
(Constitution IV: model değer uyduramaz). Karşılaştırma öncesi:

- Unicode NFC; tırnak/eksi benzeri işaretler tek biçime iner (`“”` → `"`, `−` → `-`).
- Türkçe büyük/küçük harf: `İ` → `i`, `I` → `ı`, sonra `lower()` (Python'un `casefold`'u `I`'yı
  `i` yapar; Türkçede yanlıştır).
- Sayılar tr-TR biçiminden kanonik ondalığa: `1.250,00` ≡ `1250` ≡ `1250,0`; `25,00 TL` → `25 tl`.
  Para birimi bir sözcük olarak kalır (`TL`), böylece `"150,00 TL"` değeri metinde `150,00 TL`
  sırasıyla geçmelidir.
- Ürün kodu gibi harf-tire-rakam öbekleri tek simgedir (`P-001`); içindeki `001` ayrı bir `1`
  sayısı sayılmaz (yanlış kaynak eşleşmesini önler).
- Boşluk farkları yok sayılır; noktalama ve işaretler **korunur**: her noktalama karakteri ayrı
  bir simgedir (`1)` ≠ `1`, `+1` ≠ `1`). Sayının önündeki eksi işareti (önünde harf/rakam yoksa)
  sayının parçasıdır: `-5` ≠ `5` (metindeki `−25,00 TL` değeri `25,00 TL`'nin kaynağı değildir).
  Böylece string bir değerin boşluk dışındaki tüm karakterleri eşleşen metin aralığında bulunur.

Bir değer, simge dizisi metnin simge dizisinde **ardışık** geçiyorsa kaynaklıdır.

Biçim denetimi (`find_exact_source`): doğrulama metotları uygulamadaki metni birebir karşılaştırır
(`toHaveText("150,00 TL")`). Sayı normu `150 TL`'yi `150,00 TL`'nin kaynağı sayar; ama şablon
modelin literal'ini basar ve test uygulamanın `150,00 TL`'sine karşı kırmızı olur — modelin biçim
hatası "defect adayı" gibi görünür. Bu yüzden metin (str) beklenen değerleri ayrıca, yalnızca
NFC + işaret eşdeğerleri + boşluk daraltma sonrası, case metninde **aynen** geçmelidir.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

_ESDEGER = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "−": "-",
        "–": "-",
        "—": "-",
        " ": " ",
        " ": " ",
    }
)

# Sıra önemli: kod öbeği > (işaretli) binlik ayraçlı sayı > düz sayı > sözcük > noktalama.
_SIMGE_RE = re.compile(
    r"(?P<kod>[^\W\d_]+(?:-[0-9A-Za-z]+)+)"
    r"|(?P<sayi>(?:(?<![\w.,])-)?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?))"
    r"|(?P<soz>[^\W\d_]+)"
    r"|(?P<nok>[^\w\s])",
    re.UNICODE,
)


def tr_lower(text: str) -> str:
    """Türkçe kurallı küçük harf (`İ`→`i`, `I`→`ı`)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def _kanonik_sayi(ham: str) -> str:
    """tr-TR sayı → kanonik ondalık metni (`1.250,00` → `1250`, `12,5` → `12.5`, `-5` → `-5`)."""
    isaret = ""
    if ham.startswith("-"):
        isaret, ham = "-", ham[1:]
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", ham):
        ham = ham.replace(".", "").replace(",", ".")
    else:
        # Binlik ayraçsız: tek ayraç ondalıktır (tr-TR virgül; nokta da kabul edilir: 12.5).
        ham = ham.replace(",", ".")
    try:
        d = Decimal(ham)
    except InvalidOperation:  # pragma: no cover - regex yalnızca rakam/ayraç verir
        return ham
    d = d.normalize()
    metin = format(d, "f")
    if "." in metin:
        metin = metin.rstrip("0").rstrip(".")
    metin = metin or "0"
    return metin if metin == "0" else isaret + metin


def tokens(text: str) -> list[str]:
    """Normalleştirilmiş simge dizisi (sayılar kanonik, sözcükler Türkçe küçük harf)."""
    metin = unicodedata.normalize("NFC", str(text)).translate(_ESDEGER)
    out: list[str] = []
    for m in _SIMGE_RE.finditer(metin):
        if m.group("sayi") is not None:
            out.append("#" + _kanonik_sayi(m.group("sayi")))
        elif m.group("kod") is not None:
            out.append(tr_lower(m.group("kod")))
        elif m.group("soz") is not None:
            out.append(tr_lower(m.group("soz")))
        else:
            out.append(m.group("nok"))
    return out


def value_tokens(value: Any) -> list[str]:
    """Bir argüman değerinin simgeleri. Sayı → tek kanonik sayı simgesi."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        if isinstance(value, float) and value != value:  # NaN
            return []
        metin = format(Decimal(str(value)), "f")
        return ["#" + _kanonik_sayi(metin)]
    return tokens(str(value))


def _contains(hay: Sequence[str], needle: Sequence[str]) -> bool:
    n = len(needle)
    if n == 0:
        return False
    return any(list(hay[i : i + n]) == list(needle) for i in range(len(hay) - n + 1))


def _birebir_norm(metin: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(metin)).translate(_ESDEGER).split())


def find_exact_source(value: Any, texts: Iterable[str]) -> str | None:
    """Metin değerinin (boşluk/NFC/işaret eşdeğerleri dışında) **aynen** geçtiği ilk metin.

    Sayı (int/float) değerler için `find_source` ile aynıdır (biçim sorunu yoktur: şablon sayıyı
    sayı olarak basar ve page object biçimlendirmez)."""
    if not isinstance(value, str):
        return find_source(value, texts)
    igne = _birebir_norm(value)
    if not igne:
        return None
    for t in texts:
        if t and igne in _birebir_norm(t):
            return t
    return None


def find_source(value: Any, texts: Iterable[str]) -> str | None:
    """Değerin literal geçtiği ilk metni döner; yoksa None (boolean/boş değer kaynaksızdır)."""
    needle = value_tokens(value)
    if not needle:
        return None
    for t in texts:
        if t and _contains(tokens(t), needle):
            return t
    return None

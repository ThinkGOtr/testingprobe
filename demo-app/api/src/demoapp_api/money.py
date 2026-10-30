"""Tutar yardımcıları. Para her yerde Decimal ve iki ondalık; biçim tr-TR (`1.250,00 TL`)."""

from decimal import ROUND_HALF_UP, Decimal

KURUS = Decimal("0.01")


def tutar(value: Decimal | int | str) -> Decimal:
    """Değeri iki ondalığa yuvarlanmış Decimal'e çevirir."""
    return Decimal(value).quantize(KURUS, rounding=ROUND_HALF_UP)


def tutar_str(value: Decimal | int | str) -> str:
    """JSON için kanonik metin: `1250.00`."""
    return f"{tutar(value):.2f}"


def format_tl(value: Decimal | int | str) -> str:
    """tr-TR para biçimi: `1.250,00 TL`, `-25,00 TL`."""
    q = tutar(value)
    sign = "-" if q < 0 else ""
    whole, frac = f"{abs(q):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{'.'.join(groups)},{frac} TL"

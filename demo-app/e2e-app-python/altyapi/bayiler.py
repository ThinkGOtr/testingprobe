"""e2e bayi kullanıcıları ve testin bayisini seçme kuralı (web: tests/fixtures.ts `DEALERS`,
`pickDealer`; uygulama: altyapi/Bayiler.java)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bayi:
    kullanici_adi: str
    parola: str
    ad: str  # arayüzde gösterilen bayi adı (ör. "Merkez Bayi")


# Paralel işçi başına bir bayi. Parola seed verisidir (demo-app/api seed.py), sır değildir.
E2E: tuple[Bayi, ...] = (
    Bayi("bayi1", "Demo123!", "Merkez Bayi"),
    Bayi("bayi2", "Demo123!", "Sahil Bayi"),
)

# Doğrulama ajanının (playwright-mcp / app-mcp) bayisi; e2e testleri kullanamaz ve sıfırlamaz.
AJAN_BAYISI = "bayi3"


def sec(sabit: str | None, isci_sirasi: int) -> Bayi:
    """Testin bayisi: `sabit` (`@pytest.mark.dealer("bayi2")`) verilmişse o, yoksa işçinin bayisi."""
    if sabit is not None:
        for b in E2E:
            if b.kullanici_adi == sabit:
                return b
        ayrilmis = " (doğrulama ajanına ayrılmıştır)" if sabit == AJAN_BAYISI else ""
        izinli = ", ".join(b.kullanici_adi for b in E2E)
        raise ValueError(f"dealer({sabit!r}) bir e2e bayisi değil{ayrilmis}; izinli: {izinli}")
    if not 0 <= isci_sirasi < len(E2E):
        raise ValueError(
            f"En fazla {len(E2E)} paralel işçi desteklenir (bayi kullanıcısı sayısı); "
            f"işçi sırası {isci_sirasi}"
        )
    return E2E[isci_sirasi]

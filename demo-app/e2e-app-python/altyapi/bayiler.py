"""e2e bayi kullanıcıları ve testin bayisini seçme kuralı (web: tests/fixtures.ts `DEALERS`,
`pickDealer`; uygulama: altyapi/Bayiler.java)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace


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


KOSU_PAROLALARI_ENV = "TP_RUN_DEALER_PASSWORDS"


def kosu_parolalari(ham: str | None = None) -> dict[str, str]:
    """Koşu hesabı başına parola: test-runner `TP_RUN_DEALER_PASSWORDS` = JSON
    `{"<kullanıcı>": "<parola>"}` verir (AI Probe › Test kullanıcıları; yalnız parolası girilenler).
    Değişken yoksa {}. Bozuk değer açık hatayla durur (değer iletiye yazılmaz)."""
    ham = os.environ.get(KOSU_PAROLALARI_ENV, "") if ham is None else ham
    if not ham.strip():
        return {}
    try:
        v = json.loads(ham)
    except ValueError:
        raise ValueError(f"{KOSU_PAROLALARI_ENV} geçerli JSON değil") from None
    if not isinstance(v, dict):
        raise ValueError(f"{KOSU_PAROLALARI_ENV} bir JSON nesnesi olmalı")
    return {k: p for k, p in v.items() if isinstance(k, str) and isinstance(p, str) and p}


def kosu_parolasiyla(bayi: Bayi, parolalar: dict[str, str] | None = None) -> Bayi:
    """Bayinin bu koşudaki parolası: koşu ortamında girilmişse o, yoksa seed (ortak) parolası."""
    p = (kosu_parolalari() if parolalar is None else parolalar).get(bayi.kullanici_adi)
    return replace(bayi, parola=p) if p else bayi


def sec(sabit: str | None, isci_sirasi: int) -> Bayi:
    """Testin bayisi: `sabit` (`@pytest.mark.dealer("bayi2")`) verilmişse o, yoksa işçinin bayisi
    (parola koşu ortamından, yoksa seed)."""
    if sabit is not None:
        for b in E2E:
            if b.kullanici_adi == sabit:
                return kosu_parolasiyla(b)
        ayrilmis = " (doğrulama ajanına ayrılmıştır)" if sabit == AJAN_BAYISI else ""
        izinli = ", ".join(b.kullanici_adi for b in E2E)
        raise ValueError(f"dealer({sabit!r}) bir e2e bayisi değil{ayrilmis}; izinli: {izinli}")
    if not 0 <= isci_sirasi < len(E2E):
        raise ValueError(
            f"En fazla {len(E2E)} paralel işçi desteklenir (bayi kullanıcısı sayısı); "
            f"işçi sırası {isci_sirasi}"
        )
    return kosu_parolasiyla(E2E[isci_sirasi])

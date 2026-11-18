"""Page object yardımcıları (TS: pages/support.ts). Sembol tablosuna girmez: sınıf yok."""

from __future__ import annotations

from collections.abc import Mapping

PATHS = {
    "login": "/giris",
    "catalog": "/katalog",
    "cart": "/sepet",
    "orders": "/siparisler",
}


def test_id_of(spec: Mapping[str, str], suffix: str | None = None) -> str:
    """Locator'ın testId değeri; önek locator'larda (sonu `-`) sonek eklenir."""
    test_id = spec["testId"]
    onek = test_id.endswith("-")
    if onek and not suffix:
        raise ValueError(f"'{test_id}' önek locator'ı için sonek (ürün kodu / sipariş no) gerekli")
    if not onek and suffix:
        raise ValueError(f"'{test_id}' sabit locator'dır; sonek verilmemeli")
    return f"{test_id}{suffix or ''}" if onek else test_id


def scope_test_id_of(spec: Mapping[str, str], suffix: str) -> str:
    """Kapsamlı locator'ın kapsayıcı testId'si: `within` + sonek (ör. "product-card-P-001")."""
    within = spec.get("within")
    if not within:
        raise ValueError(f"'{spec['testId']}' kapsamlı bir locator değil (within yok)")
    if not within.endswith("-"):
        raise ValueError(f"'{within}' kapsam öneki '-' ile bitmeli")
    if not suffix:
        raise ValueError(f"'{spec['testId']}' kapsamı için sonek (ürün kodu) gerekli")
    return f"{within}{suffix}"

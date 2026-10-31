"""`result_digest`: veri kanıtının deterministik özeti (§8.2b adım 4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.unit.gateway.demo_sources import demo_query
from tp_core.gateway import digest_matches, result_digest
from tp_core.gateway.evidence import EMPTY_DIGEST, MAX_DIGEST_ROWS


def test_single_setting_row_is_key_equals_value() -> None:
    assert result_digest([("min_siparis_tutari", "750.00")]) == "min_siparis_tutari=750.00"
    assert result_digest([{"anahtar": "min_siparis_tutari", "deger": "750.00"}]) == (
        "min_siparis_tutari=750.00"
    )


def test_row_order_does_not_matter_but_column_order_does() -> None:
    a = result_digest([("P-002", "15.00"), ("P-001", "25.00")])
    b = result_digest([("P-001", "25.00"), ("P-002", "15.00")])
    assert a == b == "P-001=25.00; P-002=15.00"
    assert result_digest([("25.00", "P-001")]) != result_digest([("P-001", "25.00")])


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "NULL"),
        (True, "true"),
        (False, "false"),
        (Decimal("750.00"), "750.00"),  # Postgres NUMERIC(12,2): ölçek korunur
        (Decimal("7.5E+2"), "750"),  # üstel gösterim yok
        (6, "6"),
        (date(2026, 10, 31), "2026-10-31"),
        (datetime(2026, 10, 31, 9, 0, tzinfo=UTC), "2026-10-31T09:00:00+00:00"),
        (b"\x01\xff", "01ff"),
    ],
)
def test_cell_canonicalisation(value: object, text: str) -> None:
    assert result_digest([(value,)]) == text


def test_separators_inside_values_are_escaped() -> None:
    assert result_digest([("a=b", "c;d")]) == "a\\=b=c\\;d"
    # Kaçış olmasa bu iki sonuç aynı özete düşerdi.
    assert result_digest([("a=b",)]) != result_digest([("a", "b")])


def test_empty_and_large_results() -> None:
    assert result_digest([]) == EMPTY_DIGEST
    many = [(f"P-{i:03d}", i) for i in range(MAX_DIGEST_ROWS + 1)]
    digest = result_digest(many)
    assert digest.startswith("sha256:") and digest.endswith(f"({MAX_DIGEST_ROWS + 1} satır)")
    assert digest == result_digest(list(reversed(many)))  # yine sıradan bağımsız
    assert result_digest([("x" * 300,)]).startswith("sha256:")


def test_sqlalchemy_rows_from_the_demo_database() -> None:
    rows = demo_query("SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'")
    assert result_digest(rows) == "min_siparis_tutari=750.00"
    assert digest_matches(" min_siparis_tutari=750.00\n", rows)
    assert not digest_matches("min_siparis_tutari=500.00", rows)
    assert not digest_matches("min_siparis_tutari | 750.00", rows)  # serbest biçim kabul edilmez


def test_helper_docstring_examples() -> None:
    """Şeritlere açık yardımcıların docstring örnekleri doğru kalır."""
    import doctest

    from tp_core.gateway import canonical, evidence, inputs, replay, untrusted

    for module in (canonical, evidence, inputs, replay, untrusted):
        assert doctest.testmod(module).failed == 0, module.__name__

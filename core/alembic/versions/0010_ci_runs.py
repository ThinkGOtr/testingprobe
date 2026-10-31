"""Faz 3 ci_runs şeridi şema değişiklikleri (şerit dolduracak; boşsa no-op).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31
"""

from collections.abc import Sequence

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

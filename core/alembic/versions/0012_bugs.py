"""Faz 4 bugs şeridi şema değişiklikleri (şerit dolduracak; boşsa no-op).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-31
"""

from collections.abc import Sequence

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

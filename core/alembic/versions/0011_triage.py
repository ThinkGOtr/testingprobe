"""Faz 4 triage şeridi şema değişiklikleri (şerit dolduracak; boşsa no-op).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-31
"""

from collections.abc import Sequence

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

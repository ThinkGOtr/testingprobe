"""Faz 2 cases şeridi şema değişiklikleri (şerit dolduracak; boşsa no-op).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31
"""

from collections.abc import Sequence

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

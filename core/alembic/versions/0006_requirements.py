"""Faz 2 requirements şeridi şema değişiklikleri (şerit dolduracak; boşsa no-op).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31
"""

from collections.abc import Sequence

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

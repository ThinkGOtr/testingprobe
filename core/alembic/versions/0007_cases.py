"""Faz 2 cases şeridi: case görüntüleme kaydı (review süresi ölçümü, TEKNIK-TASARIM §12).

`case_goruntuleme` (tp_core.models.cases_feature): portal case kartını açtığında yazılır; karar
anındaki insan review süresi = karar − kararı verenin bir önceki karardan sonraki ilk görüntülemesi.
Uygulama rolü (tp_app) yalnızca SELECT/INSERT yapabilir: ölçüm sonradan değiştirilemez.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_goruntuleme",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_case.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id"),
            nullable=False,
        ),
        sa.Column(
            "zaman", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("case_goruntuleme_ix", "case_goruntuleme", ["test_case_id", "user_id", "zaman"])
    op.execute("GRANT SELECT, INSERT ON case_goruntuleme TO tp_app")


def downgrade() -> None:
    op.drop_index("case_goruntuleme_ix", table_name="case_goruntuleme")
    op.drop_table("case_goruntuleme")

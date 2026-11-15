"""AI Probe oturumuna organizasyon/proje kimliği (Config R1, 0043): `oturum.org_id`, `project_id`.

Home `redeem` yanıtına (UYGULAMA-PLANI-R1 §6 "Handoff") isteğe bağlı `org_id`, `project_id`
eklendi; TP bunları oturumda saklar (portal başlığı, R2'de proje bazlı veri ayrımı). Yalnız
boş olabilen sütun ekler; mevcut satırlar NULL kalır. Downgrade sütunları siler.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("oturum", sa.Column("org_id", sa.String(64), nullable=True))
    op.add_column("oturum", sa.Column("project_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("oturum", "project_id")
    op.drop_column("oturum", "org_id")

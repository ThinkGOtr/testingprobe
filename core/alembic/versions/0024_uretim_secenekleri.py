"""Test üretimi v3 (specs/011 §4.3, K5): gereksinimin üretim seçenekleri.

`requirement.uretim_secenekleri` (JSONB, null olabilir): analistin "Üretimi başlat" formunda
seçtiği platformlar, test seviyesi, benimsenen standartlar, kapsam dışı, roller ve platforma özgü
ek bilgi (`tp_core.features.cases.secenekler`). Sonraki üretimde varsayılan olur. Null = seçim
yapılmadı (bugünkü davranış: SYSTEM, platform eki yok).

Yalnız ekleme yapar. Şerit düzeni (011 §4.3): P şeridi 0021'e bağlanır; birleştirmede zincir
0021→0022→0023→0024→0025 olarak doğrusallaştırılır.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requirement",
        sa.Column("uretim_secenekleri", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requirement", "uretim_secenekleri")

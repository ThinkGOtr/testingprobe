"""Test üretimi v3 (specs/011 §4.3, K5): gereksinimin üretim seçenekleri.

`requirement.uretim_secenekleri` (JSONB, null olabilir): analistin "Üretimi başlat" formunda
seçtiği platformlar, test seviyesi, benimsenen standartlar, kapsam dışı, roller ve platforma özgü
ek bilgi (`tp_core.features.cases.secenekler`). Sonraki üretimde varsayılan olur. Null = seçim
yapılmadı (bugünkü davranış: SYSTEM, platform eki yok).

Yalnız ekleme yapar. Şerit düzeni (011 §4.3): P şeridi 0035'e bağlanır; birleştirmede zincir
0035→0036→0037→0038→0039 olarak doğrusallaştırılır.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requirement",
        sa.Column("uretim_secenekleri", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requirement", "uretim_secenekleri")

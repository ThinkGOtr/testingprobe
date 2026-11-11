"""Test üretimi v3 (specs/011 §4.3): üretim başına üst düzey listeler.

`case_uretim` (tp_core.models.cases_feature): bir case üretiminin (portal model çağrısı ya da IDE
taslak gönderimi) case dışındaki çıktısı `ozet`'te tutulur: açık sorular, varsayımlar, kapsam
öğeleri, negatif kapsam kararları, kapsanmayanlar, gözlemler, otomasyon açık noktaları,
konfigürasyon matrisi, test edilebilirlik eksikleri. Case'ler `(requirement_id, uretim_no)` ile bu
satıra bağlanır; tutarlılık kuralları ve kapsam matrisi bu özetten kodda hesaplanır.

Yalnız ekleme yapar: mevcut (v2) case'lerin satırı yoktur ve etkilenmezler (K9).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_uretim",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "requirement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requirement.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uretim_no", sa.Integer(), nullable=False),
        sa.Column("kanal", sa.Text(), nullable=False, server_default="portal"),
        sa.Column("tur", sa.Text(), nullable=False, server_default="uretim"),
        sa.Column("ai_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "ozet", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "olusturma",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("kanal IN ('ide', 'portal')", name="case_uretim_kanal_ck"),
        sa.CheckConstraint("tur IN ('negatif', 'teknik', 'uretim')", name="case_uretim_tur_ck"),
        sa.UniqueConstraint("requirement_id", "uretim_no", name="case_uretim_uq"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON case_uretim TO tp_app")


def downgrade() -> None:
    op.drop_table("case_uretim")

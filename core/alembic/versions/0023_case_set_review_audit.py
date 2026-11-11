"""Test üretimi v3 (specs/011 §4.3, D şeridi): case seti review (P8) ve denetim (P9) kayıtları.

`case_set_review` (tp_core.models.case_kalite): üretimden sonra otomatik çalışan 12 maddelik
review; `skor` UYGUN madde sayısı (0–12), `icerik` modelin çıktısı + case eşlemesi.
`case_set_audit`: Agent Probe portu arkasındaki denetim kararı; `model_karari` modelin kararı,
`karar` deterministik sertleştirmeden sonraki karar (yayın kapısı bunu okur), `kaynak`
`tp-gecit` | `agent-probe` | `sim`, `talep_no` Agent Probe kayıt numarası.

İkisi de gereksinimin güncel v3 setinin `set_hash`'ine bağlıdır. Yalnız ekleme yapar.

Revision ID: 0023
Revises: 0021 (D şeridi; birleştirmede zincir 0021→0022→0023→… doğrusallaştırılır)
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DURUM = "durum IN ('bekliyor', 'hata', 'tamamlandi')"
KARARLAR = "IN ('DÜZELTME_GEREKLİ', 'ENGELLE', 'KABUL')"


def _ortak(tablo: str) -> list[sa.Column]:
    return [
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
        sa.Column("set_hash", sa.Text(), nullable=False),
        sa.Column("durum", sa.Text(), nullable=False, server_default="bekliyor"),
        sa.Column(
            "icerik", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("hata", sa.Text(), nullable=True),
        sa.Column("ai_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("isteyen", sa.Text(), nullable=False, server_default="system"),
        sa.Column(
            "olusturma", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "guncelleme",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "case_set_review",
        *_ortak("case_set_review"),
        sa.Column("uretim_no", sa.Integer(), nullable=True),
        sa.Column("skor", sa.Integer(), nullable=True),
        sa.CheckConstraint(DURUM, name="case_set_review_durum_ck"),
    )
    op.create_index("case_set_review_req_ix", "case_set_review", ["requirement_id", "olusturma"])
    op.create_table(
        "case_set_audit",
        *_ortak("case_set_audit"),
        sa.Column("karar", sa.Text(), nullable=True),
        sa.Column("model_karari", sa.Text(), nullable=True),
        sa.Column("kaynak", sa.Text(), nullable=False, server_default="tp-gecit"),
        sa.Column("talep_no", sa.Text(), nullable=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(DURUM, name="case_set_audit_durum_ck"),
        sa.CheckConstraint(f"karar IS NULL OR karar {KARARLAR}", name="case_set_audit_karar_ck"),
        sa.CheckConstraint(
            f"model_karari IS NULL OR model_karari {KARARLAR}",
            name="case_set_audit_model_karar_ck",
        ),
        sa.CheckConstraint(
            "kaynak IN ('agent-probe', 'sim', 'tp-gecit')", name="case_set_audit_kaynak_ck"
        ),
    )
    op.create_index("case_set_audit_req_ix", "case_set_audit", ["requirement_id", "olusturma"])
    # Geçmiş korunur: uygulama rolü satır silmez (her review/denetim ayrı kayıttır).
    op.execute("GRANT SELECT, INSERT, UPDATE ON case_set_review TO tp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON case_set_audit TO tp_app")


def downgrade() -> None:
    op.drop_index("case_set_audit_req_ix", table_name="case_set_audit")
    op.drop_table("case_set_audit")
    op.drop_index("case_set_review_req_ix", table_name="case_set_review")
    op.drop_table("case_set_review")

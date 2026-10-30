"""F0 başlangıç şeması: app_user, audit_event (append-only), job

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kullanici_adi", sa.Text, nullable=False, unique=True),
        sa.Column("rol", sa.Text, nullable=False),
        sa.Column("parola_hash", sa.Text, nullable=False),
        sa.Column("olusturma", sa.DateTime(timezone=True), server_default=NOW),
        sa.CheckConstraint(
            "rol IN ('analyst', 'engineer', 'presenter', 'po', 'tester')", name="app_user_rol_ck"
        ),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),  # bigserial
        sa.Column("zaman", sa.DateTime(timezone=True), server_default=NOW),
        sa.Column("aktor", sa.Text, nullable=False),
        sa.Column("eylem", sa.Text, nullable=False),
        sa.Column("nesne", sa.Text),
        sa.Column("ozet", JSONB),
    )
    op.create_table(
        "job",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tur", sa.Text, nullable=False),
        sa.Column("durum", sa.Text, nullable=False, server_default="queued"),
        sa.Column("yuk", JSONB),
        sa.Column("deneme", sa.Integer, nullable=False, server_default="0"),
        sa.Column("olusturma", sa.DateTime(timezone=True), server_default=NOW),
        sa.Column("guncelleme", sa.DateTime(timezone=True), server_default=NOW),
        sa.CheckConstraint("durum IN ('queued', 'running', 'done', 'failed')", name="job_durum_ck"),
    )
    op.create_index(
        "job_kuyruk_ix", "job", ["olusturma"], postgresql_where=sa.text("durum = 'queued'")
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app_user, job TO tp_app")
    op.execute("GRANT SELECT, INSERT ON audit_event TO tp_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM tp_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tp_app")


def downgrade() -> None:
    op.drop_table("job")
    op.drop_table("audit_event")
    op.drop_table("app_user")

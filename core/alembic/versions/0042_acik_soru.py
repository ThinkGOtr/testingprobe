"""Açık soru / varsayım döngüsü (specs/011 K16, 0042; D6 şeridi): `acik_soru` tablosu.

Case üretiminin açık sorularının (ve isteğe bağlı doğrulama bekleyen varsayımlarının) PO'ya Jira
yorumu olarak gönderim kaydı ve PO yanıtı. Yalnız ekleme yapar; downgrade tabloyu siler.

Yetki (en az yetki): `tp_app` yalnız SELECT, INSERT, UPDATE (satır silinmez; gereksinim silinirse
FK `ON DELETE CASCADE` sahibin yetkisiyle temizler).

Zincir doğrusaldır: 0040 (D1) → 0041 (D4) → 0042 (`down_revision = "0041"`).

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def _zaman(ad: str) -> sa.Column:
    return sa.Column(
        ad, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    op.create_table(
        "acik_soru",
        sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "requirement_id",
            _UUID,
            sa.ForeignKey("requirement.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tur", sa.Text(), nullable=False),
        sa.Column("etiket", sa.Text(), nullable=False),
        sa.Column("kaynak_id", sa.Text(), nullable=False),
        sa.Column("metin", sa.Text(), nullable=False),
        sa.Column("metin_hash", sa.Text(), nullable=False),
        sa.Column("sahip", sa.Text(), nullable=False, server_default=""),
        sa.Column("durum", sa.Text(), nullable=False, server_default="bekliyor"),
        sa.Column("gereksinim_hash", sa.Text(), nullable=False),
        sa.Column("gonderen", sa.Text(), nullable=False),
        sa.Column("gonderim_zamani", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jira_comment_id", sa.Text(), nullable=True),
        sa.Column("yanit", sa.Text(), nullable=True),
        sa.Column("yanit_yazari", sa.Text(), nullable=True),
        sa.Column("yanit_zamani", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yanit_yorum_id", sa.Text(), nullable=True),
        _zaman("olusturma"),
        _zaman("guncelleme"),
        sa.CheckConstraint("tur IN ('soru', 'varsayim')", name="acik_soru_tur_ck"),
        sa.CheckConstraint(
            "durum IN ('bekliyor', 'gonderildi', 'yanitlandi')", name="acik_soru_durum_ck"
        ),
        sa.UniqueConstraint(
            "requirement_id", "tur", "metin_hash", "gereksinim_hash", name="acik_soru_metin_uq"
        ),
        sa.UniqueConstraint("requirement_id", "etiket", name="acik_soru_etiket_uq"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON acik_soru TO tp_app")


def downgrade() -> None:
    op.drop_table("acik_soru")

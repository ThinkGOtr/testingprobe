"""Test üretimi v3 — iki tur (specs/011 F3, §4.3): test tasarım modeli.

- `tasarim_modeli`: gereksinim başına sürümlü test tasarım modeli (`icerik` JSONB; durum makinesi
  `design_model`: draft | approved | rejected | superseded). `gereksinim_hash` modelin üretildiği
  PO onaylı içeriğin hash'idir.
- Gereksinim durumlarına `modeling` (model üretiliyor) ve `model_ready` (model kararı / onaylı
  modelden case üretimi bekleniyor) eklenir.
- `review.nesne_turu` += `design_model` (insan kararı: approve | edit | reject).

Yalnız ekleme yapar: mevcut satırlar etkilenmez.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQ_ESKI = (
    "'cases_ready', 'doc_final', 'done', 'failed', 'findings_open', 'generating', 'in_review', "
    "'new', 'pending_po', 'po_approved'"
)
_REQ_YENI = (
    "'cases_ready', 'doc_final', 'done', 'failed', 'findings_open', 'generating', 'in_review', "
    "'model_ready', 'modeling', 'new', 'pending_po', 'po_approved'"
)
_NESNE_ESKI = "'bug_draft', 'consistency_finding', 'requirement', 'script', 'test_case'"
_NESNE_YENI = (
    "'bug_draft', 'consistency_finding', 'design_model', 'requirement', 'script', 'test_case'"
)


def upgrade() -> None:
    op.create_table(
        "tasarim_modeli",
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
        sa.Column("surum", sa.Integer(), nullable=False),
        sa.Column("icerik", postgresql.JSONB(), nullable=False),
        sa.Column("icerik_hash", sa.Text(), nullable=False),
        sa.Column("onaylanan_hash", sa.Text(), nullable=True),
        sa.Column("durum", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("gereksinim_hash", sa.Text(), nullable=True),
        sa.Column("ai_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uretim_modu", sa.Text(), nullable=True),
        sa.Column(
            "olusturma",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "guncelleme",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "durum IN ('approved', 'draft', 'rejected', 'superseded')",
            name="design_model_durum_ck",
        ),
        sa.CheckConstraint(
            "uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')",
            name="tasarim_modeli_mod_ck",
        ),
        sa.UniqueConstraint("requirement_id", "surum", name="tasarim_modeli_uq"),
    )
    op.create_index("tasarim_modeli_req_ix", "tasarim_modeli", ["requirement_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tasarim_modeli TO tp_app")

    op.drop_constraint("requirement_durum_ck", "requirement", type_="check")
    op.create_check_constraint("requirement_durum_ck", "requirement", f"durum IN ({_REQ_YENI})")
    op.drop_constraint("review_nesne_turu_ck", "review", type_="check")
    op.create_check_constraint("review_nesne_turu_ck", "review", f"nesne_turu IN ({_NESNE_YENI})")


def downgrade() -> None:
    # İki turun ara durumundaki gereksinimler `failed`'a alınır (yeniden üretim başlatılabilir).
    op.execute("UPDATE requirement SET durum = 'failed' WHERE durum IN ('modeling', 'model_ready')")
    op.drop_constraint("requirement_durum_ck", "requirement", type_="check")
    op.create_check_constraint("requirement_durum_ck", "requirement", f"durum IN ({_REQ_ESKI})")
    # `review` append-only'dir ve insan kararları silinmez: var olan 'design_model' satırları
    # korunur; eski kısıt yalnızca yeni satırlara uygulanır (NOT VALID, 0008 deseni).
    op.drop_constraint("review_nesne_turu_ck", "review", type_="check")
    op.execute(
        f"ALTER TABLE review ADD CONSTRAINT review_nesne_turu_ck "
        f"CHECK (nesne_turu IN ({_NESNE_ESKI})) NOT VALID"
    )
    op.drop_index("tasarim_modeli_req_ix", table_name="tasarim_modeli")
    op.drop_table("tasarim_modeli")

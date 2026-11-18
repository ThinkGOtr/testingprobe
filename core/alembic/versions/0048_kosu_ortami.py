"""Koşunun test ortamı (Home proje ortamları): `run.ortam_eid`, `run.ortam_adi`, `run.ortam_turu`.

Koşu başlatılırken seçilen (ya da projenin varsayılan) ortamın kimliği, adı ve türü koşu anında
yazılır (Home'da ortam sonradan yeniden adlandırılsa/silinse de sonuç hangi ortamda koştuğunu
söyler). Ortamsız koşu (proje ayarları; eski kayıtlar) üçünde de NULL. `ortam_turu` Home türü
(`dev|test|staging|prod`; `prod` = Canlı). Liste/Kontrol Kulesi süzgeci için
`(project_id, ortam_eid, olusturma)` dizini.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run", sa.Column("ortam_eid", sa.Text(), nullable=True))
    op.add_column("run", sa.Column("ortam_adi", sa.Text(), nullable=True))
    op.add_column("run", sa.Column("ortam_turu", sa.Text(), nullable=True))
    op.create_check_constraint(
        "run_ortam_turu_ck",
        "run",
        "ortam_turu IS NULL OR ortam_turu IN ('dev', 'prod', 'staging', 'test')",
    )
    op.create_index("run_proje_ortam_ix", "run", ["project_id", "ortam_eid", "olusturma"])


def downgrade() -> None:
    op.drop_index("run_proje_ortam_ix", table_name="run")
    op.drop_constraint("run_ortam_turu_ck", "run", type_="check")
    op.drop_column("run", "ortam_turu")
    op.drop_column("run", "ortam_adi")
    op.drop_column("run", "ortam_eid")

"""ai_call.ek: kolonu olmayan geçit ayrıntıları (jsonb)

Model geçidi `record_extras=True` ile `replay_kaynagi`, `replay_kokeni` (recorded |
golden_promoted), `sema_hatalari`, `yeniden_deneme` ve önbellek token sayılarını yazar. Böylece
yükseltilmiş bir golden'dan gelen replay çıktısı canlı kayıttan kaynak dosyası açılmadan ayrılır
(anayasa: replay çıktısı canlı gibi gösterilmez). Kolon NULL olabilir; satır çapasına yalnızca
NULL değilse girer (capa_surumu=2 çapaları bu kolon eklenmeden önceki satırlar için geçerli kalır).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_call ADD COLUMN ek JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE ai_call DROP COLUMN ek")

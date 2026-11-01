"""GitHub kipi PR check kopyası: `pull_request.checks|checks_sha|checks_zaman`.

core-api GitHub kimlik bilgisi taşımaz (yazma yetkisi yalnızca core-worker'da); GitHub kipinde
LocalForge'un `checks/<sha>.json` dosyaları da yoktur. core-worker'ın dakikalık PR senkronu
(`sync_prs`) açık PR'ların head check'lerini forge'dan okuyup buraya yazar; portal check listesi ve
merge kapısı bu kopyayı okur. `checks_sha` güncel head'den farklıysa kopya bayattır (bekliyor).

Kolonlar boş bırakılabilir; tablo düzeyindeki tp_app yetkileri (0002: SELECT/INSERT/UPDATE/DELETE)
yeni kolonları da kapsar. Model ↔ şema eşitliği tests/unit/platform/test_migrations.py'de ve
tests/unit/features/codegen/test_pr_checks.py'de doğrulanır.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pull_request ADD COLUMN checks JSONB")
    op.execute("ALTER TABLE pull_request ADD COLUMN checks_sha TEXT")
    op.execute("ALTER TABLE pull_request ADD COLUMN checks_zaman TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    op.execute("ALTER TABLE pull_request DROP COLUMN IF EXISTS checks_zaman")
    op.execute("ALTER TABLE pull_request DROP COLUMN IF EXISTS checks_sha")
    op.execute("ALTER TABLE pull_request DROP COLUMN IF EXISTS checks")

"""GitHub kipi PR merge kapısının zorunlu check listesi: `pull_request.zorunlu_checkler`.

011 K-T13 (MİM-D3): GitHub merge kapısı (`GitHubForge.zorunlu_checkler`) zorunlu listeyi PR'ın
hedef dalının güncel ucu ∪ head ağacından hesaplar (`web-java.yml`); core-api forge'a erişmez.
core-worker PR senkronu (`sync_prs`) check kopyasıyla birlikte bu listeyi de yazar; portal aynası
(`views.pr_checks`) kapıyla aynı listeyi okur. Liste `checks_sha` head'ine aittir. Boşsa (eski
kopya) portal kapalı tarafa düşer (`web-java` zorunlu sayılır).

Kolon boş bırakılabilir; tablo düzeyindeki tp_app yetkileri (0002) yeni kolonu da kapsar.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pull_request ADD COLUMN zorunlu_checkler JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE pull_request DROP COLUMN IF EXISTS zorunlu_checkler")

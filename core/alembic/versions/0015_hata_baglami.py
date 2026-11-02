"""GitHub kipi hata bağlamı: `test_result_ek.hata_baglami` (hata anı aria snapshot'ı).

Yerel kipte triage hata anı aria snapshot'ını koşu dizinindeki `run.json`'dan / `error-context.md`
dosyasından okur. GitHub kipinde yerel koşu dizini yoktur (artefakt GitHub'dadır, çekirdeğin
artefakt volume'ü salt okunurdur); `test-local-results` artefaktındaki `error-context.md` içe
aktarımda (`github_ingest`) ayrıştırılır ve test başına buraya yazılır:
`{aria_snapshot, aria_snapshot_scope, deneme, kaynak}`. Triage `run.json` yokken bu kopyayı okur.

Kolon boş bırakılabilir; tablo düzeyindeki tp_app yetkileri (0010) yeni kolonu da kapsar. Model ↔
şema eşitliği tests/unit/features/ci/test_migration.py'de doğrulanır.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE test_result_ek ADD COLUMN hata_baglami JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE test_result_ek DROP COLUMN IF EXISTS hata_baglami")

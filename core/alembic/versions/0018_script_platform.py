"""Script platform boyutu (009 mobil-masaüstü §2.1).

- `script.platform`: üretilen testin hedef platformu — `web` (Playwright/TypeScript, mevcut
  davranış), `android`, `ios`, `windows` (Appium/Java/TestNG). Kod üretimi (case, platform)
  çiftinedir: bir onaylı case'ten her platform için ayrı script, dal ve PR. Mevcut satırlar
  `web` olur (varsayılan; geriye uyum). Onarım script'leri (`locator_fix`) onardıkları testin
  platformunu taşır.

Model ↔ şema eşitliği tests/unit/features/codegen/test_platform.py'de doğrulanır.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORMLAR = ("android", "ios", "web", "windows")


def upgrade() -> None:
    op.execute("ALTER TABLE script ADD COLUMN platform TEXT DEFAULT 'web' NOT NULL")
    op.create_check_constraint(
        "script_platform_ck",
        "script",
        "platform IN (" + ", ".join(f"'{p}'" for p in PLATFORMLAR) + ")",
    )


def downgrade() -> None:
    op.drop_constraint("script_platform_ck", "script", type_="check")
    op.execute("ALTER TABLE script DROP COLUMN platform")

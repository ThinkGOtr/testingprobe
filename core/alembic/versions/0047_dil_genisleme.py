"""Test dilleri genişlemesi (specs/014-test-dilleri/plan.md §6): `script.dil` CHECK kümesine
`kotlin` (Android Espresso) ve `swift` (iOS XCUITest) eklenir.

Hat (`tam` | `musteri_ci` | `dogrulanmamis`) (platform, dil) çiftinden türetilir
(`codegen/platform.py` `CATILAR`); kolon değildir.

Downgrade yalnız `kotlin`/`swift` satırı yokken çalışır; aksi halde `RuntimeError`
(ileri-düzeltme gerekir).

Model ↔ şema eşitliği tests/unit/features/codegen/test_dil.py'de doğrulanır.

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESKI_DILLER = ("csharp", "java", "python", "ts")
YENI_DILLER = ("csharp", "java", "kotlin", "python", "swift", "ts")


def _in(kolon: str, degerler: Sequence[str]) -> str:
    return f"{kolon} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def upgrade() -> None:
    op.drop_constraint("script_dil_ck", "script", type_="check")
    op.create_check_constraint("script_dil_ck", "script", _in("dil", YENI_DILLER))


def downgrade() -> None:
    sayi = op.get_bind().execute(
        sa.text("SELECT count(*) FROM script WHERE dil IN ('kotlin', 'swift')")
    ).scalar_one()
    if sayi:
        raise RuntimeError(
            f"0047 geri alınamaz: {sayi} script kotlin/swift dilinde (ileri-düzeltme gerekir)"
        )
    op.drop_constraint("script_dil_ck", "script", type_="check")
    op.create_check_constraint("script_dil_ck", "script", _in("dil", ESKI_DILLER))

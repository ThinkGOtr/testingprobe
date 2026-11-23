"""Elle Sauce Labs turu: `run.tetik`, `test_result.tetik` ve `ci_tetik.tetik` CHECK kümelerine
`sauce` eklenir (Koşular › "Sauce Labs turunu başlat"; demo deposunun `sauce-demo.yml` iş akışı,
`POST /ci/trigger {tetik: sauce}`).

Downgrade yalnız `sauce` satırı yokken çalışır; aksi halde `RuntimeError` (ileri-düzeltme gerekir).

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_ESKI = ("break_verify", "deploy", "local_check", "manual", "nightly", "pr", "push")
CI_ESKI = ("deploy", "manual", "nightly", "pr", "push")
TABLOLAR = (("run", RUN_ESKI), ("test_result", RUN_ESKI), ("ci_tetik", CI_ESKI))


def _in(degerler: Sequence[str]) -> str:
    return "tetik IN (" + ", ".join(f"'{d}'" for d in sorted(degerler)) + ")"


def upgrade() -> None:
    for tablo, eski in TABLOLAR:
        op.drop_constraint(f"{tablo}_tetik_ck", tablo, type_="check")
        op.create_check_constraint(f"{tablo}_tetik_ck", tablo, _in((*eski, "sauce")))


def downgrade() -> None:
    baglanti = op.get_bind()
    for tablo, _ in TABLOLAR:
        sayi = baglanti.execute(
            sa.text(f"SELECT count(*) FROM {tablo} WHERE tetik = 'sauce'")
        ).scalar_one()
        if sayi:
            raise RuntimeError(f"0051 geri alınamaz: {tablo} içinde {sayi} 'sauce' satırı var")
    for tablo, eski in TABLOLAR:
        op.drop_constraint(f"{tablo}_tetik_ck", tablo, type_="check")
        op.create_check_constraint(f"{tablo}_tetik_ck", tablo, _in(eski))

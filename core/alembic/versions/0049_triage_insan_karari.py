"""Triage insan sınıflandırması (TP UX denetimi IA-16): `failure.karar_kaynagi` CHECK kümesine
`human` eklenir. Kural ya da AI sınıflandıramadığında ("Belirsiz", REPLAY-MISS) Test Uzmanı ya da
Otomasyon Mühendisi `POST /failures/{id}/classify` ile sınıfı gerekçeli belirler; karar
`failure.classified` denetim olayıyla kayda geçer.

Downgrade yalnız `human` satırı yokken çalışır; aksi halde `RuntimeError` (ileri-düzeltme gerekir).

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESKI = ("llm", "rule")
YENI = ("human", "llm", "rule")


def _in(kolon: str, degerler: Sequence[str]) -> str:
    return f"{kolon} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def upgrade() -> None:
    op.drop_constraint("failure_karar_kaynagi_ck", "failure", type_="check")
    op.create_check_constraint("failure_karar_kaynagi_ck", "failure", _in("karar_kaynagi", YENI))


def downgrade() -> None:
    sayi = op.get_bind().execute(
        sa.text("SELECT count(*) FROM failure WHERE karar_kaynagi = 'human'")
    ).scalar_one()
    if sayi:
        raise RuntimeError(
            f"0049 geri alınamaz: {sayi} başarısızlık insan kararıyla sınıflandı (ileri-düzeltme)"
        )
    op.drop_constraint("failure_karar_kaynagi_ck", "failure", type_="check")
    op.create_check_constraint("failure_karar_kaynagi_ck", "failure", _in("karar_kaynagi", ESKI))

"""Platform başına depo (platform-depo ANALIZ §3.2 madde 4, Şerit T2): `script.depo`,
`pull_request.depo` ve PR anahtarına depo.

Bir projenin uygulama platformları (android | ios | windows) varsayılan depodan ayrı GitHub
depolarına PR açabilir; PR numaraları depolar arasında çakışır. Kalıcı depo kimliği:

- `script.depo text NOT NULL DEFAULT ''` — script'in PR'ının açıldığı depo (`''` = projenin
  varsayılan deposu; ayrı depoda `sahip/ad`, küçük harf). Config sonradan değişse de açık PR
  kayıttaki depodan senkronlanır.
- `pull_request.depo text NOT NULL DEFAULT ''`; PK `(project_id, number)` →
  `(project_id, depo, number)`.

`run.ortam.depo` JSONB içindedir (şema değişmez); `ci_tetik.anahtar`'a depo eki kodda eklenir
(`@<depo>`; mevcut anahtarlar değişmez).

Veri: mevcut satırlar `depo = ''` alır (bugünkü tek depo = varsayılan depo); PG11+ hızlı varsayılan
satırları yeniden yazmaz.

Downgrade yalnız tüm satırlar varsayılan depodayken (`depo = ''`) çalışır; aksi halde PR numaraları
tek anahtara indirgenemez → `RuntimeError` (ileri-düzeltme gerekir).

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE script ADD COLUMN depo text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE pull_request ADD COLUMN depo text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE pull_request DROP CONSTRAINT pull_request_pkey")
    op.execute(
        "ALTER TABLE pull_request ADD CONSTRAINT pull_request_pkey "
        "PRIMARY KEY (project_id, depo, number)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    for tablo in ("pull_request", "script"):
        n = bind.execute(sa.text(f"SELECT count(*) FROM {tablo} WHERE depo <> ''")).scalar_one()
        if n:
            raise RuntimeError(
                f"0046 downgrade: {tablo} varsayılan dışı depoya ait {n} satır taşıyor; PR "
                "numaraları (project_id, number) anahtarına indirgenemez (ileri-düzeltme gerekir)"
            )
    op.execute("ALTER TABLE pull_request DROP CONSTRAINT pull_request_pkey")
    op.execute(
        "ALTER TABLE pull_request ADD CONSTRAINT pull_request_pkey PRIMARY KEY (project_id, number)"
    )
    op.execute("ALTER TABLE pull_request DROP COLUMN depo")
    op.execute("ALTER TABLE script DROP COLUMN depo")

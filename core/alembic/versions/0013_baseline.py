"""Faz 5: story başına manuel baz değer (append-only giriş geçmişi).

- requirement_baz_deger: `PUT /requirements/{id}/baseline` (`islem='set'`) ve `DELETE`
  (`islem='clear'`) girişleri; güncel değer gereksinimin en büyük `sira`'lı satırıdır. Değer
  saniyedir (0 < değer ≤ 144000 = 40 saat). Kim/ne zaman/kaynak notu satırdadır; ayrıca her giriş
  hash zincirli denetim olayı (`requirement.baseline_set|baseline_cleared`, önce/sonra) yazar.
  tp_app yalnızca SELECT/INSERT: geçmiş değiştirilemez ve silinemez (gereksinim silinirse cascade).

Platform tablosu `requirement`'a dokunulmaz. Model ↔ şema eşitliği
tests/unit/features/requirements/test_baseline.py'de doğrulanır.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE requirement_baz_deger (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    sira INTEGER NOT NULL,
    islem TEXT NOT NULL,
    deger_s INTEGER,
    onceki_s INTEGER,
    giren TEXT NOT NULL,
    giren_rol TEXT NOT NULL,
    not_metni TEXT,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT requirement_baz_deger_islem_ck CHECK (islem IN ('clear', 'set')),
    CONSTRAINT requirement_baz_deger_deger_ck CHECK ((islem = 'set' AND deger_s IS NOT NULL AND deger_s > 0 AND deger_s <= 144000) OR (islem = 'clear' AND deger_s IS NULL)),
    CONSTRAINT requirement_baz_deger_sira_uq UNIQUE (requirement_id, sira),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE
)
""",  # noqa: E501
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute("GRANT SELECT, INSERT ON requirement_baz_deger TO tp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS requirement_baz_deger")

"""Faz 3 ci_runs şeridi: CI tetik kaydı ve test sonucu ekleri (TEKNIK-TASARIM §8.5, §8.11).

- ci_tetik: her CI tetiği tek satır; `anahtar` UNIQUE (gece zamanlayıcısı aynı gün için iki kez
  koşu açamaz). GitHub kipinde dispatch isteğinin kaydı da buradadır.
- test_result_ek: Playwright JSON raporundan test başına a11y (axe) sayıları, ek dosya yolları,
  deneme sonuçları. Kontrol Kulesi'nin a11y sayıları yalnızca bu satırlardan türetilir.

- review_kanal_ck'ye `github` eklenir: GitHub kipinde PR GitHub arayüzünde (zorunlu insan review'u
  ve kontrollerle) merge edilir; çekirdek bu insan kararını `kanal='github'`, `user_id` boş,
  `harici_onaylayan`=merge eden olarak yazar (önceden `portal` görünüyordu — yanlış kanal).

Platform tablolarına (`run`, `test_result`) dokunulmaz. Model ↔ şema eşitliği
tests/unit/features/ci/test_migration.py'de (ve modeller içe aktarıldığında platform testinde)
doğrulanır.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("ci_tetik", "test_result_ek")

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE ci_tetik (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    anahtar TEXT NOT NULL,
    tetik TEXT NOT NULL,
    kaynak TEXT NOT NULL,
    run_id UUID,
    ref TEXT,
    commit TEXT,
    pr_no INTEGER,
    isteyen TEXT NOT NULL,
    dis_istek JSONB DEFAULT '{}'::jsonb NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ci_tetik_tetik_ck CHECK (tetik IN ('deploy', 'nightly', 'pr', 'push')),
    CONSTRAINT ci_tetik_kaynak_ck CHECK (kaynak IN ('github', 'local')),
    CONSTRAINT ci_tetik_anahtar_key UNIQUE (anahtar),
    FOREIGN KEY(run_id) REFERENCES run (id) ON DELETE SET NULL
)
""",
    "CREATE INDEX ci_tetik_run_ix ON ci_tetik (run_id)",
    """
CREATE TABLE test_result_ek (
    test_result_id UUID NOT NULL,
    a11y_ihlal INTEGER DEFAULT '0' NOT NULL,
    a11y_kritik INTEGER DEFAULT '0' NOT NULL,
    a11y JSONB DEFAULT '[]'::jsonb NOT NULL,
    ekler JSONB DEFAULT '[]'::jsonb NOT NULL,
    denemeler JSONB DEFAULT '[]'::jsonb NOT NULL,
    proje TEXT,
    satir INTEGER,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (test_result_id),
    FOREIGN KEY(test_result_id) REFERENCES test_result (id) ON DELETE CASCADE
)
""",
    # Kontrol Kulesi: aynı commit'te değişen sonuç (flaky) sorgusu.
    "CREATE INDEX IF NOT EXISTS test_result_commit_ix_ci ON test_result (commit, test_adi)",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO tp_app")
    op.drop_constraint("review_kanal_ck", "review", type_="check")
    op.create_check_constraint("review_kanal_ck", "review", "kanal IN ('github', 'jira', 'portal')")


def downgrade() -> None:
    # `review` append-only'dir (Anayasa VIII): var olan 'github' satırları silinmez; eski kural
    # yalnızca yeni satırlara uygulanır (NOT VALID; 0008 ile aynı yaklaşım).
    op.drop_constraint("review_kanal_ck", "review", type_="check")
    op.execute(
        "ALTER TABLE review ADD CONSTRAINT review_kanal_ck CHECK (kanal IN ('jira', 'portal')) "
        "NOT VALID"
    )
    op.execute("DROP INDEX IF EXISTS test_result_commit_ix_ci")
    op.execute("DROP TABLE IF EXISTS test_result_ek")
    op.execute("DROP TABLE IF EXISTS ci_tetik")

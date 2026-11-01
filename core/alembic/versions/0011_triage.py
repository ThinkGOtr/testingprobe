"""Faz 4 triage şeridi: triage ek kaydı ve koşu başına triage işareti (TEKNIK-TASARIM §8.6).

- failure_ek: failure ile 1:1; `anahtar` UNIQUE (`<run_id>:<test>` — aynı koşunun aynı testi iki
  kez sınıflandırılmaz), kanıt özeti, kanıt bağlantıları, locator onarım önerisi, LLM yorumu.
- triage_kosu: run ile 1:1; koşunun triage'ı yapıldı mı (`done` | `skipped`) ve neden. Süpürme
  işi bakılmamış kırmızı koşuları buradan bulur.

Platform tablosu `failure`'a dokunulmaz. Model ↔ şema eşitliği
tests/unit/features/triage/test_migration.py'de doğrulanır.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("failure_ek", "triage_kosu")

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE failure_ek (
    failure_id UUID NOT NULL,
    anahtar TEXT NOT NULL,
    kaynak TEXT DEFAULT 'ci' NOT NULL,
    kirma BOOLEAN DEFAULT false NOT NULL,
    script_id UUID,
    script_kontrol_id UUID,
    kural TEXT,
    kanit JSONB DEFAULT '{}'::jsonb NOT NULL,
    kanit_linkleri JSONB DEFAULT '[]'::jsonb NOT NULL,
    oneri JSONB,
    oneri_yok_nedeni TEXT,
    llm JSONB,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (failure_id),
    CONSTRAINT failure_ek_kaynak_ck CHECK (kaynak IN ('ci', 'codegen', 'kirma')),
    CONSTRAINT failure_ek_anahtar_key UNIQUE (anahtar),
    FOREIGN KEY(failure_id) REFERENCES failure (id) ON DELETE CASCADE,
    FOREIGN KEY(script_id) REFERENCES script (id) ON DELETE SET NULL
)
""",
    "CREATE INDEX failure_ek_script_ix ON failure_ek (script_id)",
    """
CREATE TABLE triage_kosu (
    run_id UUID NOT NULL,
    durum TEXT NOT NULL,
    neden TEXT,
    sayilar JSONB DEFAULT '{}'::jsonb NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (run_id),
    CONSTRAINT triage_kosu_durum_ck CHECK (durum IN ('done', 'skipped')),
    FOREIGN KEY(run_id) REFERENCES run (id) ON DELETE CASCADE
)
""",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO tp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS triage_kosu")
    op.execute("DROP TABLE IF EXISTS failure_ek")

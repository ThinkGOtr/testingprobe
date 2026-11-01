"""Faz 4 bugs şeridi: bug taslağının içerik dışı hazırlık/yayın ayrıntıları (TEKNIK-TASARIM §8.12).

- bug_draft_ek: bug_draft ile 1:1. Hata imzası, mükerrer araması (güvenli JQL + sonuç), AI
  sıralamasının çağrısı/modu ve önerisi, `bugs.prepare` işinin durumu, modelin ham taslağı ve
  deterministik düzeltmeler, aynı imzalı sonraki başarısızlıklar, Jira yayın sonucu. Bu alanlar
  onaya konu içerik (`bug_draft.icerik`) dışındadır; içerik hash'ini değiştirmez.

Platform tablosu `bug_draft`'a dokunulmaz. Model ↔ şema eşitliği
tests/unit/features/bugs/test_migration.py'de doğrulanır.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE bug_draft_ek (
    bug_draft_id UUID NOT NULL,
    kaynak TEXT NOT NULL,
    imza JSONB DEFAULT '{}'::jsonb NOT NULL,
    jql TEXT,
    arama JSONB DEFAULT '{}'::jsonb NOT NULL,
    dup_ai_call_id UUID,
    dup_uretim_modu TEXT,
    oneri JSONB DEFAULT '{}'::jsonb NOT NULL,
    hazirlik_durum TEXT DEFAULT 'kuyrukta' NOT NULL,
    hazirlik_no INTEGER DEFAULT '0' NOT NULL,
    hazirlik_hatasi TEXT,
    job_id UUID,
    uretim TEXT,
    ai_icerik JSONB,
    duzenleyen TEXT,
    duzeltmeler JSONB DEFAULT '[]'::jsonb NOT NULL,
    ilgili_failure_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
    yayin JSONB DEFAULT '{}'::jsonb NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (bug_draft_id),
    CONSTRAINT bug_draft_ek_kaynak_ck CHECK (kaynak IN ('failure', 'finding')),
    CONSTRAINT bug_draft_ek_hazirlik_ck CHECK (hazirlik_durum IN ('basarisiz', 'hazir', 'hazirlaniyor', 'kuyrukta')),
    CONSTRAINT bug_draft_ek_uretim_ck CHECK (uretim IS NULL OR uretim IN ('ai', 'sablon')),
    FOREIGN KEY(bug_draft_id) REFERENCES bug_draft (id) ON DELETE CASCADE
)
""",  # noqa: E501
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON bug_draft_ek TO tp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bug_draft_ek")

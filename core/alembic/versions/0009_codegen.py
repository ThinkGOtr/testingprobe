# ruff: noqa: E501 — CREATE TABLE ifadeleri modellerden (tp_core.models.codegen_feature) üretildi.
"""Faz 3 codegen şeridi (CasesToCode, TEKNIK-TASARIM §8.4): kod üretimi ek tabloları.

- script_codegen: script ile 1:1; kaynak case ve onaylı hash'i, sembol tablosu commit'i, ajan
  modu/bundle hash'i, ham eşleme (ilk tur ayrıca), deterministik kontroller, insana düşme nedeni
  (`engel_turu`; defect adayı dahil), son yerel kontrol özeti, PR adresi, denetim zinciri başı.
- script_adim: ajanın tarayıcı eylemleri (insan özeti, temizlenmiş ham çıktı, hata bayrağı) +
  model döngüsü dışında alınan ekran görüntüsü yolu.
- script_kontrol: yerel kontrol / kırarak doğrula koşularının zaman çizelgesi.

Model ↔ şema eşitliği tests/unit/platform/test_migrations.py'de doğrulanır.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("script_codegen", "script_adim", "script_kontrol")

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE script_codegen (
    script_id UUID NOT NULL,
    test_case_id UUID NOT NULL,
    requirement_id UUID,
    case_hash TEXT NOT NULL,
    story_key TEXT,
    test_key TEXT,
    sira_no INTEGER NOT NULL,
    baslik TEXT DEFAULT '' NOT NULL,
    workflow_id UUID,
    job_id UUID,
    symbols_sha TEXT,
    uretim_modu TEXT,
    ai_call_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
    bundle_hash TEXT,
    sablon_hash TEXT,
    ilk_eslesme JSONB,
    eslesme JSONB,
    dogrulama JSONB DEFAULT '[]'::jsonb NOT NULL,
    engel_turu TEXT,
    engel_nedeni TEXT,
    yerel_kontrol JSONB,
    duzeltme_turu INTEGER DEFAULT '0' NOT NULL,
    pr_url TEXT,
    denetim_hash TEXT,
    dal JSONB,
    break_durum TEXT DEFAULT 'not_started' NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (script_id),
    CONSTRAINT script_codegen_engel_ck CHECK (engel_turu IS NULL OR engel_turu IN ('agent_error', 'case_changed', 'check_unknown', 'defect_candidate', 'environment', 'flaky', 'human_rejected', 'locator', 'missing_method', 'replay_miss', 'static', 'unknown_method', 'unsourced_value', 'unverified_step')),
    CONSTRAINT script_codegen_break_ck CHECK (break_durum IN ('failed', 'not_started', 'passed', 'running', 'weak')),
    FOREIGN KEY(script_id) REFERENCES script (id) ON DELETE CASCADE,
    FOREIGN KEY(test_case_id) REFERENCES test_case (id) ON DELETE CASCADE,
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX script_codegen_case_ix ON script_codegen (test_case_id)",
    """
CREATE TABLE script_adim (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    script_id UUID NOT NULL,
    sira INTEGER NOT NULL,
    tur INTEGER DEFAULT '1' NOT NULL,
    arac TEXT NOT NULL,
    arguman JSONB DEFAULT '{}'::jsonb NOT NULL,
    ozet TEXT DEFAULT '' NOT NULL,
    ham TEXT DEFAULT '' NOT NULL,
    izinli BOOLEAN DEFAULT true NOT NULL,
    hata BOOLEAN DEFAULT false NOT NULL,
    ekran_goruntusu TEXT,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT script_adim_sira_uq UNIQUE (script_id, sira),
    FOREIGN KEY(script_id) REFERENCES script (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE script_kontrol (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    script_id UUID NOT NULL,
    tur TEXT NOT NULL,
    sha TEXT NOT NULL,
    kirma BOOLEAN DEFAULT false NOT NULL,
    run_id TEXT,
    sonuc TEXT NOT NULL,
    sinif TEXT,
    ozet JSONB DEFAULT '{}'::jsonb NOT NULL,
    sure_ms INTEGER,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT script_kontrol_tur_ck CHECK (tur IN ('break_baseline', 'break_green', 'break_red', 'local_check', 'remap_check')),
    CONSTRAINT script_kontrol_sonuc_ck CHECK (sonuc IN ('error', 'failure', 'skipped', 'success')),
    CONSTRAINT script_kontrol_sinif_ck CHECK (sinif IS NULL OR sinif IN ('bilinmiyor', 'defect_adayi', 'derleme', 'gecti', 'kararsiz', 'kirma_beklenen_kirmizi', 'locator', 'ortam')),
    FOREIGN KEY(script_id) REFERENCES script (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX script_kontrol_script_ix ON script_kontrol (script_id, zaman)",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO tp_app")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")

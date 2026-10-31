# ruff: noqa: E501 — CREATE TABLE ifadeleri modellerden (tp_core.models.requirements_feature) üretildi.
"""Gereksinim özelliği (F2 adım 1–3): tutarlılık denetimi koşuları, bulgu ayrıntısı, son hal hash'i

- requirement_kontrol: her tutarlılık denetimi koşusu (tur, belge hash'i, forge commit'i, model
  modu, doğrulanan/elenen bulgu sayısı).
- consistency_finding_ek: bulgunun model kimliği (F1…), iddia/gözlem, AI'ın ilk önerisi, bulgu
  anındaki belge metni ve deterministik kanıt doğrulamasının ayrıntısı.
- requirement_akis: belgenin son hal (doc_final) hash'i; Jira'daki PO onayı bu hash'e bağlanır.
- requirement_review_ek: ön inceleme model özeti ve incelenen belgenin anlık görüntüsü.

Model ↔ şema eşitliği tests/unit/platform/test_migrations.py'de doğrulanır.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "requirement_kontrol",
    "consistency_finding_ek",
    "requirement_akis",
    "requirement_review_ek",
)

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE requirement_kontrol (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    sira INTEGER NOT NULL,
    tur INTEGER NOT NULL,
    belge_hash TEXT NOT NULL,
    head_sha TEXT,
    workflow_id UUID,
    ai_call_id UUID,
    uretim_modu TEXT,
    bulgu_toplam INTEGER DEFAULT '0' NOT NULL,
    dogrulanan INTEGER DEFAULT '0' NOT NULL,
    elenen INTEGER DEFAULT '0' NOT NULL,
    engelleyici INTEGER DEFAULT '0' NOT NULL,
    notlar TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT requirement_kontrol_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    CONSTRAINT requirement_kontrol_sira_uq UNIQUE (requirement_id, sira),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE consistency_finding_ek (
    finding_id UUID NOT NULL,
    kontrol_id UUID NOT NULL,
    bulgu_no TEXT NOT NULL,
    iddia TEXT DEFAULT '' NOT NULL,
    gozlem TEXT DEFAULT '' NOT NULL,
    mevcut_doc_text TEXT,
    ref_metni TEXT,
    ai_onerisi TEXT,
    dogrulama JSONB DEFAULT '[]'::jsonb NOT NULL,
    onceki_finding_id UUID,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (finding_id),
    FOREIGN KEY(finding_id) REFERENCES consistency_finding (id) ON DELETE CASCADE,
    FOREIGN KEY(kontrol_id) REFERENCES requirement_kontrol (id) ON DELETE CASCADE,
    FOREIGN KEY(onceki_finding_id) REFERENCES consistency_finding (id) ON DELETE SET NULL
)
""",
    "CREATE INDEX ix_consistency_finding_ek_kontrol_id ON consistency_finding_ek (kontrol_id)",
    """
CREATE TABLE requirement_akis (
    requirement_id UUID NOT NULL,
    son_hal_hash TEXT,
    son_hal_zamani TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (requirement_id),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE requirement_review_ek (
    review_id UUID NOT NULL,
    ozet TEXT DEFAULT '' NOT NULL,
    aciklama TEXT DEFAULT '' NOT NULL,
    kabul_kriterleri JSONB DEFAULT '[]'::jsonb NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (review_id),
    FOREIGN KEY(review_id) REFERENCES requirement_review (id) ON DELETE CASCADE
)
""",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO tp_app")


def downgrade() -> None:
    for tablo in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {tablo}")

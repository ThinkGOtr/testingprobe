"""Test verisi kaynakları: katalog projenin salt okuma veritabanından sorguyla dolar.

- `test_verisi_kaynagi`: proje başına kaynak tanımı (grup, tek SELECT, anahtar kolonu, değer
  kolonları JSONB, sıra, ön tanımlı işareti, iyimser kilit sürümü, yumuşak silme, son yenileme
  zamanı ve özeti). Grup proje içinde tekildir (silinmiş kaynak aynı grupla yeniden etkinleşir).
- `test_verisi.kaynak_id` (FK, `ON DELETE SET NULL`): kaydı dolduran kaynak; elle kayıtta NULL.
- `test_verisi.kaynakta_yok`: kaynağın son yenilemesinde dönmeyen kayıt (silinmez, işaretlenir).

tp_app kaynak satırını silemez (silme yumuşaktır; katalog tablosuyla aynı kural).

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE test_verisi_kaynagi (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(64) NOT NULL,
    grup TEXT NOT NULL,
    aciklama TEXT NOT NULL DEFAULT '',
    sorgu TEXT NOT NULL,
    anahtar_kolonu TEXT NOT NULL,
    deger_kolonlari JSONB NOT NULL,
    sira INTEGER NOT NULL DEFAULT 0,
    on_tanimli BOOLEAN NOT NULL DEFAULT false,
    surum INTEGER NOT NULL DEFAULT 1,
    silindi BOOLEAN NOT NULL DEFAULT false,
    guncelleyen TEXT NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    guncelleme TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    son_yenileme TIMESTAMP WITH TIME ZONE,
    son_durum JSONB,
    CONSTRAINT test_verisi_kaynagi_grup_uq UNIQUE (project_id, grup),
    CONSTRAINT test_verisi_kaynagi_grup_ck CHECK (grup ~ '^[a-z0-9_]+$')
)
"""
    )
    op.execute(
        "ALTER TABLE test_verisi ADD COLUMN kaynak_id UUID "
        "REFERENCES test_verisi_kaynagi(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE test_verisi ADD COLUMN kaynakta_yok BOOLEAN NOT NULL DEFAULT false")
    op.execute("CREATE INDEX test_verisi_kaynak_ix ON test_verisi (project_id, kaynak_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON test_verisi_kaynagi TO tp_app")


def downgrade() -> None:
    op.execute("DROP INDEX test_verisi_kaynak_ix")
    op.execute("ALTER TABLE test_verisi DROP COLUMN kaynakta_yok")
    op.execute("ALTER TABLE test_verisi DROP COLUMN kaynak_id")
    op.execute("DROP TABLE test_verisi_kaynagi")

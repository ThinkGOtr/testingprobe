"""Platform inceleme düzeltmeleri: PO onayının içeriğe bağlanması, deterministik case kimliği

- requirement.onaylanan_hash: `po_approved`'a girişte yazılır; case üretimine giden geçişler
  (po_approved/cases_ready/failed → generating) güncel içerik hash'ini buna karşı denetler.
- requirement.icerik_degisim: içerik alanlarının son değişim anı. Jira kanalındaki PO onayı
  (etiket zamanı) bundan önceyse onay reddedilir (PO'nun görmediği içerik onaylanmış sayılmaz).
  Mevcut satırlar için `guncelleme` ile doldurulur (güvenli taraf: daha geç bir an).
- test_case.id: rastgele varsayılan kaldırıldı (kimlik `case_id()` uuid5'iyle verilir,
  Constitution XI); (requirement_id, sira_no, uretim_no) UNIQUE — yeniden denenen üretim işi
  ikinci bir case kümesi ekleyemez.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE requirement ADD COLUMN onaylanan_hash TEXT")
    op.execute("ALTER TABLE requirement ADD COLUMN icerik_degisim TIMESTAMP WITH TIME ZONE")
    op.execute("UPDATE requirement SET icerik_degisim = guncelleme")
    op.execute("ALTER TABLE requirement ALTER COLUMN icerik_degisim SET DEFAULT now()")
    op.execute("ALTER TABLE requirement ALTER COLUMN icerik_degisim SET NOT NULL")

    op.execute("ALTER TABLE test_case ALTER COLUMN id DROP DEFAULT")
    op.execute(
        "ALTER TABLE test_case ADD CONSTRAINT test_case_sira_uq "
        "UNIQUE (requirement_id, sira_no, uretim_no)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE test_case DROP CONSTRAINT test_case_sira_uq")
    op.execute("ALTER TABLE test_case ALTER COLUMN id SET DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE requirement DROP COLUMN icerik_degisim")
    op.execute("ALTER TABLE requirement DROP COLUMN onaylanan_hash")

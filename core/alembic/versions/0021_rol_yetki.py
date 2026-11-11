"""Rol ve yetki modeli v2 (specs/012-rol-yetki §3).

- `app_user.rol` kümesi 8 role çıkar: `admin`, `auditor`, `analyst`, `po`, `tester`, `engineer`,
  `developer`, `viewer`.
- Kaldırılan `presenter` rolündeki hesaplar `admin` olur. Hesap kimliği ve kullanıcı adı korunur
  (kimlik bağları, oturumlar ve denetim kaydındaki `aktor` geçmişi bozulmaz).
- Diğer tablolar dokunulmaz: `requirement_baz_deger.giren_rol` girişi yapanın o anki rolüdür (tarihsel;
  yalnız analist/PO yazabiliyordu), denetim kaydı append-only'dir.

Geri alma: `admin` → `presenter`. Yeni rollerde (`auditor`, `developer`, `viewer`) hesap varsa
geri alma durur (bu hesaplar eski modelde karşılıksızdır; bilerek silinmeleri gerekir).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

YENI = "('admin', 'auditor', 'analyst', 'po', 'tester', 'engineer', 'developer', 'viewer')"
ESKI = "('analyst', 'engineer', 'presenter', 'po', 'tester')"


def upgrade() -> None:
    op.execute("ALTER TABLE app_user DROP CONSTRAINT app_user_rol_ck")
    op.execute("UPDATE app_user SET rol = 'admin' WHERE rol = 'presenter'")
    op.execute(f"ALTER TABLE app_user ADD CONSTRAINT app_user_rol_ck CHECK (rol IN {YENI})")


def downgrade() -> None:
    bind = op.get_bind()
    yeni_rollu = bind.execute(
        text(
            "SELECT kullanici_adi FROM app_user WHERE rol IN ('auditor', 'developer', 'viewer') "
            "ORDER BY kullanici_adi"
        )
    ).scalars()
    adlar = list(yeni_rollu)
    if adlar:
        raise RuntimeError(
            "0021 geri alınamaz: eski rol modelinde karşılığı olmayan hesaplar var: "
            + ", ".join(adlar)
        )
    op.execute("ALTER TABLE app_user DROP CONSTRAINT app_user_rol_ck")
    op.execute("UPDATE app_user SET rol = 'presenter' WHERE rol = 'admin'")
    op.execute(f"ALTER TABLE app_user ADD CONSTRAINT app_user_rol_ck CHECK (rol IN {ESKI})")

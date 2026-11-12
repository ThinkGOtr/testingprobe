"""Rol ve yetki modeli v2 (specs/012-rol-yetki §3).

- `app_user.rol` kümesi 8 role çıkar: `admin`, `auditor`, `analyst`, `po`, `tester`, `engineer`,
  `developer`, `viewer`.
- Kaldırılan `presenter` rolündeki hesaplar `admin` olur. Hesap kimliği ve kullanıcı adı korunur
  (kimlik bağları, oturumlar ve denetim kaydındaki `aktor` geçmişi bozulmaz).
- `ci_tetik.tetik` kümesine `manual` eklenir (portaldan elle koşu, `run.trigger_manual`;
  `run.tetik` zaten kabul ediyordu).
- Diğer tablolar dokunulmaz: `requirement_baz_deger.giren_rol` girişi yapanın o anki rolüdür
  (tarihsel; yalnız analist/PO yazabiliyordu), denetim kaydı append-only'dir.

Geri alma: `admin` → `presenter`. Yeni rollerde (`auditor`, `developer`, `viewer`) hesap varsa
geri alma durur (bu hesaplar eski modelde karşılıksızdır; bilerek silinmeleri gerekir).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

YENI = "('admin', 'auditor', 'analyst', 'po', 'tester', 'engineer', 'developer', 'viewer')"
ESKI = "('analyst', 'engineer', 'presenter', 'po', 'tester')"
TETIK_YENI = "('deploy', 'manual', 'nightly', 'pr', 'push')"
TETIK_ESKI = "('deploy', 'nightly', 'pr', 'push')"


def upgrade() -> None:
    op.execute("ALTER TABLE app_user DROP CONSTRAINT app_user_rol_ck")
    op.execute("UPDATE app_user SET rol = 'admin' WHERE rol = 'presenter'")
    op.execute(f"ALTER TABLE app_user ADD CONSTRAINT app_user_rol_ck CHECK (rol IN {YENI})")
    op.execute("ALTER TABLE ci_tetik DROP CONSTRAINT ci_tetik_tetik_ck")
    op.execute(
        f"ALTER TABLE ci_tetik ADD CONSTRAINT ci_tetik_tetik_ck CHECK (tetik IN {TETIK_YENI})"
    )


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
            "0023 geri alınamaz: eski rol modelinde karşılığı olmayan hesaplar var: "
            + ", ".join(adlar)
        )
    op.execute("ALTER TABLE ci_tetik DROP CONSTRAINT ci_tetik_tetik_ck")
    # Elle koşu kayıtları (idempotency satırı) eski kümede karşılıksızdır; koşunun kendisi kalır.
    op.execute("DELETE FROM ci_tetik WHERE tetik = 'manual'")
    op.execute(
        f"ALTER TABLE ci_tetik ADD CONSTRAINT ci_tetik_tetik_ck CHECK (tetik IN {TETIK_ESKI})"
    )
    op.execute("ALTER TABLE app_user DROP CONSTRAINT app_user_rol_ck")
    op.execute("UPDATE app_user SET rol = 'presenter' WHERE rol = 'admin'")
    op.execute(f"ALTER TABLE app_user ADD CONSTRAINT app_user_rol_ck CHECK (rol IN {ESKI})")

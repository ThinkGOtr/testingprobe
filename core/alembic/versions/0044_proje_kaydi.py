"""Çok proje çekirdeği (TP-COK-PROJE-PLANI §1.4, Şerit 0): `tp_proje`, `proje_sayac`,
`app_user.secili_proje`.

- `tp_proje`: arka plan işi planlanan projeler (kimlik = Home `pid`); `kaynak` `env` (açılışta
  `TP_HOME_PROJECTS`) ya da `kesif` (kullanıcının proje listesinden doğrulanmış).
- `proje_sayac`: proje başına yarışsız sayaç (`'pr'`, `'talep'`; tohumları 0045 yazar).
- `app_user.secili_proje`: son seçili proje (girişte tercih edilir).

Varsayılan proje satırı: `TP_HOME_PROJECT` (env), yoksa `'varsayilan'` (yerel/on-prem
`CONFIG_SOURCE=env`). Yalnız ekleme yapar; downgrade siler.

Yetki: `tp_app` `tp_proje` üzerinde SELECT, INSERT, UPDATE (satır silinmez; pasifleştirilir),
`proje_sayac` üzerinde SELECT, INSERT, UPDATE.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-15
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _zaman(ad: str) -> sa.Column:
    return sa.Column(
        ad, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _varsayilan_pid() -> str:
    pid = (os.environ.get("TP_HOME_PROJECT") or "").strip()
    if len(pid) > 64:
        raise RuntimeError("TP_HOME_PROJECT 64 karakterden uzun")
    return pid or "varsayilan"


def upgrade() -> None:
    op.create_table(
        "tp_proje",
        sa.Column("pid", sa.String(64), primary_key=True),
        sa.Column("kod", sa.Text(), nullable=True),
        sa.Column("ad", sa.Text(), nullable=True),
        sa.Column("kaynak", sa.Text(), nullable=False),
        sa.Column("aktif", sa.Boolean(), nullable=False, server_default=sa.true()),
        _zaman("olusturma"),
        _zaman("guncelleme"),
        sa.CheckConstraint("kaynak IN ('env', 'kesif')", name="tp_proje_kaynak_ck"),
    )
    op.create_table(
        "proje_sayac",
        sa.Column("project_id", sa.String(64), primary_key=True),
        sa.Column("ad", sa.String(64), primary_key=True),
        sa.Column("deger", sa.BigInteger(), nullable=False),
    )
    op.add_column("app_user", sa.Column("secili_proje", sa.String(64), nullable=True))
    op.execute("GRANT SELECT, INSERT, UPDATE ON tp_proje TO tp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON proje_sayac TO tp_app")
    op.get_bind().execute(
        sa.text("INSERT INTO tp_proje (pid, kaynak) VALUES (:pid, 'env') ON CONFLICT DO NOTHING"),
        {"pid": _varsayilan_pid()},
    )


def downgrade() -> None:
    op.drop_column("app_user", "secili_proje")
    op.drop_table("proje_sayac")
    op.drop_table("tp_proje")

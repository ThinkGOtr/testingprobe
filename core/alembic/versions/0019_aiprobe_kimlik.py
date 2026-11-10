"""AI Probe ortak kimliği (ADR-0001, specs/010-aiprobe-sso).

- `kimlik_bagi(external_uid, app_user_id UNIQUE)`: AI Probe kişisi ↔ TP rol hesabı.
- `app_user.auth_epoch` (iptal sayacı, varsayılan 0), `app_user.ad_soyad` (boş bırakılabilir).
- `oturum.external_uid`, `oturum.auth_time` (epoch sn), `oturum.acr`, `oturum.session_epoch_ms`
  (CONTRACT v1.2), `oturum.son_kontrol`, `oturum.urunler` (JSONB ürün→rol haritası) — boş
  bırakılabilir; yerel oturumda boş.
- `api_token.auth_epoch` (varsayılan 0), `api_token.auth_time` / `acr` / `session_epoch_ms`
  (üreten AI Probe oturumundan kopya; yerel oturumdan üretilen token'da boş).

Tüm NOT NULL kolonlar `server_default`'lu: mevcut satırlar ve `local` kip etkilenmez.

Not: `feat/mobil-masaustu` birleştirildi; bu göç `0018_script_platform`'un ardından gelir (tasks.md
T051). Tek baş kalmazsa `tests/unit/platform/test_aiprobe_sso.py::test_alembic_tek_bas` başarısız olur.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_user ADD COLUMN auth_epoch INTEGER DEFAULT 0 NOT NULL")
    op.execute("ALTER TABLE app_user ADD COLUMN ad_soyad TEXT")
    op.execute("ALTER TABLE api_token ADD COLUMN auth_epoch INTEGER DEFAULT 0 NOT NULL")
    op.execute("ALTER TABLE api_token ADD COLUMN auth_time BIGINT")
    op.execute("ALTER TABLE api_token ADD COLUMN acr TEXT")
    op.execute("ALTER TABLE api_token ADD COLUMN session_epoch_ms BIGINT")
    op.execute("ALTER TABLE oturum ADD COLUMN external_uid TEXT")
    op.execute("ALTER TABLE oturum ADD COLUMN auth_time BIGINT")
    op.execute("ALTER TABLE oturum ADD COLUMN son_kontrol TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE oturum ADD COLUMN acr TEXT")
    op.execute("ALTER TABLE oturum ADD COLUMN session_epoch_ms BIGINT")
    op.execute("ALTER TABLE oturum ADD COLUMN urunler JSONB")
    op.execute(
        """
CREATE TABLE kimlik_bagi (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    external_uid TEXT NOT NULL,
    app_user_id UUID NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT kimlik_bagi_app_user_id_key UNIQUE (app_user_id),
    FOREIGN KEY(app_user_id) REFERENCES app_user (id) ON DELETE CASCADE
)
"""
    )
    op.execute("CREATE INDEX kimlik_bagi_external_ix ON kimlik_bagi (external_uid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON kimlik_bagi TO tp_app")


def downgrade() -> None:
    op.execute("DROP TABLE kimlik_bagi")
    op.execute("ALTER TABLE oturum DROP COLUMN urunler")
    op.execute("ALTER TABLE oturum DROP COLUMN session_epoch_ms")
    op.execute("ALTER TABLE oturum DROP COLUMN acr")
    op.execute("ALTER TABLE oturum DROP COLUMN son_kontrol")
    op.execute("ALTER TABLE oturum DROP COLUMN auth_time")
    op.execute("ALTER TABLE oturum DROP COLUMN external_uid")
    op.execute("ALTER TABLE api_token DROP COLUMN session_epoch_ms")
    op.execute("ALTER TABLE api_token DROP COLUMN acr")
    op.execute("ALTER TABLE api_token DROP COLUMN auth_time")
    op.execute("ALTER TABLE api_token DROP COLUMN auth_epoch")
    op.execute("ALTER TABLE app_user DROP COLUMN ad_soyad")
    op.execute("ALTER TABLE app_user DROP COLUMN auth_epoch")

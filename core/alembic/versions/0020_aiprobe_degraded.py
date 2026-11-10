"""AI Probe: degraded üst sınırı ve SSO kaynaklı ad (specs/010-aiprobe-sso, güvenlik turu 4).

- `oturum.degraded_baslangic`, `api_token.degraded_baslangic`: home'a ulaşılamayan ilk kontrol
  anı; kesintisiz degraded süre 10 dk ile sınırlı (platform kitaplığıyla aynı).
- `app_user.ad_kaynak`: "aiprobe" = ad JIT'te AI Probe devrindeki `name`'den geldi.

Hepsi boş bırakılabilir: mevcut satırlar ve `local` kip etkilenmez.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE oturum ADD COLUMN degraded_baslangic TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE api_token ADD COLUMN degraded_baslangic TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE app_user ADD COLUMN ad_kaynak TEXT")
    # Mevcut JIT hesapları (parolasız, AI Probe'a bağlı) adlarını devirden aldı.
    op.execute(
        "UPDATE app_user SET ad_kaynak = 'aiprobe' WHERE ad_soyad IS NOT NULL "
        "AND parola_hash = '!aiprobe'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app_user DROP COLUMN ad_kaynak")
    op.execute("ALTER TABLE api_token DROP COLUMN degraded_baslangic")
    op.execute("ALTER TABLE oturum DROP COLUMN degraded_baslangic")

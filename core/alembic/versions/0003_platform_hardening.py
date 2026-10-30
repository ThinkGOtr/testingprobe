"""Platform sertleştirme: sunucu tarafı oturum, append-only review, iş politikası, 'manual' tetik

- oturum: portal oturumları sunucuda tutulur; çıkış oturumu iptal eder (çerez kopyası ölür).
- api_token.parola_izi: token üretildiği andaki parola parmak izi; parola değişince token düşer.
- review: insan kararları (Constitution I/VIII) append-only — tp_app UPDATE/DELETE/TRUNCATE
  yapamaz; sahip dahil herkes için tetikleyici (0002'deki `tp_append_only()`).
- job.zaman_asimi_s: NULL olabilir (NULL = işleyicinin kayıttaki politikası); varsayılan 900
  kaldırıldı, böylece kayıtlı `zaman_asimi_s` satıra yazılmadığında sessizce 900'e düşmez.
- run/test_result tetik: CI'nin workflow_dispatch tetiği `manual` eklendi.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TETIK_ESKI = ("break_verify", "deploy", "local_check", "nightly", "pr", "push")
TETIK_YENI = (*TETIK_ESKI, "manual")


def _tetik_ck(tablo: str, degerler: Sequence[str]) -> None:
    liste = ", ".join(f"'{d}'" for d in sorted(degerler))
    op.execute(f"ALTER TABLE {tablo} DROP CONSTRAINT {tablo}_tetik_ck")
    op.execute(f"ALTER TABLE {tablo} ADD CONSTRAINT {tablo}_tetik_ck CHECK (tetik IN ({liste}))")


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE oturum (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    user_id UUID NOT NULL,
    son_kullanma TIMESTAMP WITH TIME ZONE NOT NULL,
    iptal_zamani TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE
)"""
    )
    op.execute("CREATE INDEX oturum_user_ix ON oturum (user_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON oturum TO tp_app")

    op.execute("ALTER TABLE api_token ADD COLUMN parola_izi TEXT")

    op.execute("ALTER TABLE job ALTER COLUMN zaman_asimi_s DROP DEFAULT")
    op.execute("ALTER TABLE job ALTER COLUMN zaman_asimi_s DROP NOT NULL")

    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON review FROM tp_app")
    op.execute(
        "CREATE TRIGGER review_append_only BEFORE UPDATE OR DELETE ON review "
        "FOR EACH ROW EXECUTE FUNCTION tp_append_only()"
    )
    op.execute(
        "CREATE TRIGGER review_no_truncate BEFORE TRUNCATE ON review "
        "FOR EACH STATEMENT EXECUTE FUNCTION tp_append_only()"
    )

    for tablo in ("run", "test_result"):
        _tetik_ck(tablo, TETIK_YENI)


def downgrade() -> None:
    for tablo in ("run", "test_result"):
        op.execute(f"UPDATE {tablo} SET tetik = 'deploy' WHERE tetik = 'manual'")
        _tetik_ck(tablo, TETIK_ESKI)

    op.execute("DROP TRIGGER IF EXISTS review_no_truncate ON review")
    op.execute("DROP TRIGGER IF EXISTS review_append_only ON review")
    op.execute("GRANT UPDATE, DELETE ON review TO tp_app")

    op.execute("UPDATE job SET zaman_asimi_s = 900 WHERE zaman_asimi_s IS NULL")
    op.execute("ALTER TABLE job ALTER COLUMN zaman_asimi_s SET NOT NULL")
    op.execute("ALTER TABLE job ALTER COLUMN zaman_asimi_s SET DEFAULT 900")

    op.execute("ALTER TABLE api_token DROP COLUMN parola_izi")
    op.execute("DROP TABLE oturum")

"""Faz 2 entegrasyonu: test_case 'reopen' ("Taslağa al") kayıtlı karar olur.

`review_karar_ck`'ye `reopen` eklenir. Taslağa alma artık `review` satırı yazar; son karar
onaylamayan `reopen` olduğu için eski bir `approve` kaydı, yeni bir insan kararı olmadan kapıyı
(draft → approved, approved → published) yeniden açamaz.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ESKI = (
    "'accept_difference', 'approve', 'code_defect', 'dismiss', 'edit', 'fix_doc', 'link', "
    "'merge', 'new', 'po_approve', 'reject', 'request_changes'"
)
_YENI = _ESKI + ", 'reopen'"


def upgrade() -> None:
    op.drop_constraint("review_karar_ck", "review", type_="check")
    op.create_check_constraint("review_karar_ck", "review", f"karar IN ({_YENI})")


def downgrade() -> None:
    # `review` append-only'dir (0003 tetikleyicisi) ve insan kararları silinmez (Anayasa VIII):
    # var olan 'reopen' satırları korunur; eski alan yalnızca yeni satırlara uygulanır (NOT VALID).
    op.drop_constraint("review_karar_ck", "review", type_="check")
    op.execute(
        f"ALTER TABLE review ADD CONSTRAINT review_karar_ck CHECK (karar IN ({_ESKI})) NOT VALID"
    )

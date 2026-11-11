"""012 rol/yetki S2: case `ready` durumu ve Testçi/Analist kararları (specs/012-rol-yetki §5).

- `test_case_durum_ck`'ye `ready` eklenir (Testçi kabul etti, Analist son onayı bekleniyor).
- `review_karar_ck`'ye `accept` (Testçi: olduğu gibi kabul) ve `send_back` (Analist: gerekçeli
  geri gönderme) eklenir.

Mevcut veri değişmez: `approved` / `published` / `draft` / `rejected` case'ler olduğu gibi kalır;
eski `approve` kayıtları (analist kararı) yayın kapısı için geçerlidir.

Not (birleştirme): S1 şeridi de 0021 numarasıyla rol göçü ekliyor. Birleştirmede bu göçün
`down_revision`'ı S1'in göçüne bağlanmalıdır (tek baş).

Revision ID: 0021b
Revises: 0020
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021b"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DURUM_ESKI = "'approved', 'draft', 'published', 'rejected', 'superseded'"
_DURUM_YENI = "'approved', 'draft', 'published', 'ready', 'rejected', 'superseded'"

_KARAR_ESKI = (
    "'accept_difference', 'approve', 'code_defect', 'dismiss', 'edit', 'fix_doc', 'link', "
    "'merge', 'new', 'po_approve', 'reject', 'request_changes', 'reopen'"
)
_KARAR_YENI = _KARAR_ESKI + ", 'accept', 'send_back'"


def upgrade() -> None:
    op.drop_constraint("test_case_durum_ck", "test_case", type_="check")
    op.create_check_constraint("test_case_durum_ck", "test_case", f"durum IN ({_DURUM_YENI})")
    op.drop_constraint("review_karar_ck", "review", type_="check")
    op.create_check_constraint("review_karar_ck", "review", f"karar IN ({_KARAR_YENI})")


def downgrade() -> None:
    # `ready` case'ler taslağa döner (eski akışta Testçi kabulü yoktur; karar kayıtları kalır).
    # `onaylanan_hash` ready'de yazılmaz; yine de taslağa dönüşteki kuralla silinir.
    op.execute("UPDATE test_case SET durum = 'draft', onaylanan_hash = NULL WHERE durum = 'ready'")
    op.drop_constraint("test_case_durum_ck", "test_case", type_="check")
    op.create_check_constraint("test_case_durum_ck", "test_case", f"durum IN ({_DURUM_ESKI})")
    # `review` append-only'dir (Anayasa VIII): `accept`/`send_back` satırları korunur; eski alan
    # yalnızca yeni satırlara uygulanır (NOT VALID).
    op.drop_constraint("review_karar_ck", "review", type_="check")
    op.execute(
        f"ALTER TABLE review ADD CONSTRAINT review_karar_ck CHECK (karar IN ({_KARAR_ESKI})) "
        "NOT VALID"
    )

"""012 rol/yetki inceleme düzeltmeleri: eski analist onayı işareti ve PO reddi.

- `review.eski_onay` (boolean, varsayılan false): 012 öncesi akışta analist hesabının test_case
  `edit` kararı son onaydı. Bu göç anında var olan, analist rolündeki hesabın verdiği test_case
  `edit` kayıtları `true` işaretlenir; yayın / kod üretimi kapısı bunu `approve` sayar. Önceki
  çözüm kararı verenin GÜNCEL rolüne bakıyordu (hesabın rolü sonradan değişince sonuç değişirdi).
  `review` append-only'dir (0003 tetikleyicisi): işaretleme yalnız bu göçte, tetikleyici geçici
  kapatılarak yapılır; uygulama kullanıcısı (tp_app) review'u güncelleyemez.
- `review_karar_ck`'ye `po_reject` eklenir (T04: serbest metin gereksiniminde gerekçeli PO reddi).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KARAR_ESKI = (
    "'accept_difference', 'approve', 'code_defect', 'dismiss', 'edit', 'fix_doc', 'link', "
    "'merge', 'new', 'po_approve', 'reject', 'request_changes', 'reopen', 'accept', 'send_back'"
)
_KARAR_YENI = _KARAR_ESKI + ", 'po_reject'"


def upgrade() -> None:
    op.execute("ALTER TABLE review ADD COLUMN eski_onay BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE review DISABLE TRIGGER review_append_only")
    op.execute(
        "UPDATE review r SET eski_onay = true FROM app_user u "
        "WHERE r.user_id = u.id AND u.rol = 'analyst' "
        "AND r.nesne_turu = 'test_case' AND r.karar = 'edit'"
    )
    op.execute("ALTER TABLE review ENABLE TRIGGER review_append_only")
    op.drop_constraint("review_karar_ck", "review", type_="check")
    op.create_check_constraint("review_karar_ck", "review", f"karar IN ({_KARAR_YENI})")


def downgrade() -> None:
    # `po_reject` satırları korunur (append-only, Anayasa VIII); eski küme yalnız yeni satırlara.
    op.drop_constraint("review_karar_ck", "review", type_="check")
    op.execute(
        f"ALTER TABLE review ADD CONSTRAINT review_karar_ck CHECK (karar IN ({_KARAR_ESKI})) "
        "NOT VALID"
    )
    op.execute("ALTER TABLE review DROP COLUMN eski_onay")

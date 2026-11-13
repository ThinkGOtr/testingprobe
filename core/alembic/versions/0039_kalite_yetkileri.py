"""Test üretimi v3 (specs/011, D1 #19): en az yetki ve denetim kararı bütünlüğü.

- `case_uretim` (0034) ve `tasarim_modeli` (0035): uygulama rolü (`tp_app`) satır SİLMEZ (üretim
  özetleri ve tasarım modelleri geçmiştir; geçersizleşen model `superseded` olur). 0034/0035'teki
  `DELETE` yetkisi geri alınır. Gereksinim silinince `ON DELETE CASCADE` tablo sahibi yetkisiyle
  çalışır; ayrı yetki gerekmez.
- `case_set_review` / `case_set_audit` (0036) zaten `DELETE`'siz verildi; yine de açıkça geri
  alınır (yetki kayması olmasın).
- `case_set_audit`: `durum = 'tamamlandi'` ⇒ `karar IS NOT NULL` (kararsız "tamamlandı" satırı
  yayın kapısını şaşırtamaz). `NOT VALID`: yeni ve güncellenen satırlarda uygulanır; mevcut
  satırlar uygulama kodunca zaten bu kurala uygun yazıldı (taramayla kilit tutulmaz).

- `review.ret_nedeni`: tasarım modeline özgü ret nedenleri (`workflow.states.MODEL_RET_NEDENLERI`;
  ModelKararGirdisi artık case taksonomisinin kopyası değildir) kısıta eklenir.

0038'in (`asistan_denetim`, `ajan_*`) yetkilerine dokunulmaz (ayrı şerit).

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLOLAR = ("case_uretim", "tasarim_modeli", "case_set_review", "case_set_audit")
KARAR_CK = "case_set_audit_tamam_karar_ck"
RET_CK = "review_ret_nedeni_ck"
CASE_RET = (
    "duplicate",
    "hallucinated_step",
    "missing_ac",
    "out_of_scope",
    "wrong_element",
    "wrong_test_data",
)
MODEL_RET = (
    "invented_rule",
    "missing_condition",
    "wrong_boundary",
    "wrong_coverage_item",
    "wrong_technique",
)


def _ret_ck(degerler: Sequence[str], ek: str = "") -> None:
    liste = ", ".join(f"'{d}'" for d in sorted(degerler))
    op.execute(f"ALTER TABLE review DROP CONSTRAINT IF EXISTS {RET_CK}")
    op.execute(
        f"ALTER TABLE review ADD CONSTRAINT {RET_CK} "
        f"CHECK (ret_nedeni IS NULL OR ret_nedeni IN ({liste})){ek}"
    )


def upgrade() -> None:
    for tablo in TABLOLAR:
        op.execute(f"REVOKE DELETE, TRUNCATE ON {tablo} FROM tp_app")
    op.execute(
        f"ALTER TABLE case_set_audit ADD CONSTRAINT {KARAR_CK} "
        "CHECK (durum <> 'tamamlandi' OR karar IS NOT NULL) NOT VALID"
    )
    _ret_ck((*CASE_RET, *MODEL_RET))


def downgrade() -> None:
    # Modele özgü nedenle yazılmış kararlar geçmiştir (silinmez): eski kısıt yalnız yeni satırda.
    _ret_ck(CASE_RET, " NOT VALID")
    op.execute(f"ALTER TABLE case_set_audit DROP CONSTRAINT IF EXISTS {KARAR_CK}")
    op.execute("GRANT DELETE ON case_uretim TO tp_app")
    op.execute("GRANT DELETE ON tasarim_modeli TO tp_app")

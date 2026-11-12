"""Test üretimi v3 (specs/011, D1 #19): en az yetki ve denetim kararı bütünlüğü.

- `case_uretim` (0021) ve `tasarim_modeli` (0022): uygulama rolü (`tp_app`) satır SİLMEZ (üretim
  özetleri ve tasarım modelleri geçmiştir; geçersizleşen model `superseded` olur). 0021/0022'deki
  `DELETE` yetkisi geri alınır. Gereksinim silinince `ON DELETE CASCADE` tablo sahibi yetkisiyle
  çalışır; ayrı yetki gerekmez.
- `case_set_review` / `case_set_audit` (0023) zaten `DELETE`'siz verildi; yine de açıkça geri
  alınır (yetki kayması olmasın).
- `case_set_audit`: `durum = 'tamamlandi'` ⇒ `karar IS NOT NULL` (kararsız "tamamlandı" satırı
  yayın kapısını şaşırtamaz). `NOT VALID`: yeni ve güncellenen satırlarda uygulanır; mevcut
  satırlar uygulama kodunca zaten bu kurala uygun yazıldı (taramayla kilit tutulmaz).

0025'in (`asistan_denetim`, `ajan_*`) yetkilerine dokunulmaz (ayrı şerit).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLOLAR = ("case_uretim", "tasarim_modeli", "case_set_review", "case_set_audit")
KARAR_CK = "case_set_audit_tamam_karar_ck"


def upgrade() -> None:
    for tablo in TABLOLAR:
        op.execute(f"REVOKE DELETE, TRUNCATE ON {tablo} FROM tp_app")
    op.execute(
        f"ALTER TABLE case_set_audit ADD CONSTRAINT {KARAR_CK} "
        "CHECK (durum <> 'tamamlandi' OR karar IS NOT NULL) NOT VALID"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE case_set_audit DROP CONSTRAINT IF EXISTS {KARAR_CK}")
    op.execute("GRANT DELETE ON case_uretim TO tp_app")
    op.execute("GRANT DELETE ON tasarim_modeli TO tp_app")

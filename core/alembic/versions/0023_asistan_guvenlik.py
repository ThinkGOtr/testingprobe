"""Asistan güvenlik olayı tablosu (specs/013-asistan-guvenlik §6.1; K4, K11).

- `asistan_guvenlik_olay`: kullanıcı başına güvenlik olayları — sorudaki sır (422 `sir_icerik`),
  kişisel veri (422 `kisisel_veri`), çıktıda kanarya / istem sızıntısı, niyet sinyali ve dondurma
  başlangıcı (`donduruldu`). `ciddi` = `tur` ∈ {`sir_icerik`, `kanarya`, `istem_sizintisi`}
  (dondurma sayacı yalnız bunları sayar; tutarlılık kısıtla zorlanır).
- `ayrinti` yalnız kimlik/sayı taşır (desen adı, sinyal kimlikleri, sayılar); değer, soru metni
  veya eşleşme **asla** yazılmaz (uygulama kuralı, `features/assistant/olay.py`).
- `mesaj_id` olayın ait olduğu **kullanıcı sorusudur** (`rol='user'`; derin çocuktaki sızıntı da
  zincirin kök sorusuna bağlanır, `olay.soru_kimligi`). Yabancı anahtardır ama boş bırakılabilir:
  reddedilen sorunun mesajı yoktur; mesaj saklama temizliğiyle silinince olay kalır
  (`ON DELETE SET NULL`).
- İndeks `(kullanici_id, zaman DESC)`: dondurma denetimi her POST'ta kullanıcının son olaylarına
  bakar. Kısmi indeks `(mesaj_id) WHERE mesaj_id IS NOT NULL`: dondurma sayımı "ciddi olay almış
  soru" denetimini soru kimliğiyle yapar (K11). Saklama 90 gün (`temizlik.py`,
  `TP_ASISTAN_SAKLAMA_GUN`).
- `tp_app` yetkisi SELECT, INSERT, DELETE (saklama temizliği): olay satırı yazıldıktan sonra
  değiştirilmez (UPDATE yok).

Model ↔ şema eşitliği tests/unit/features/assistant/test_migration.py'de doğrulanır.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLO = "asistan_guvenlik_olay"

CREATE_STATEMENTS = (
    """
CREATE TABLE asistan_guvenlik_olay (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kullanici_id UUID NOT NULL,
    mesaj_id UUID,
    tur TEXT NOT NULL,
    ciddi BOOLEAN NOT NULL,
    ayrinti JSONB DEFAULT '{}'::jsonb NOT NULL,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT asistan_guvenlik_olay_tur_ck CHECK (
        tur IN ('donduruldu', 'istem_sizintisi', 'kanarya', 'kisisel_veri', 'sinyal', 'sir_icerik')
    ),
    CONSTRAINT asistan_guvenlik_olay_ciddi_ck
        CHECK (ciddi = (tur IN ('istem_sizintisi', 'kanarya', 'sir_icerik'))),
    FOREIGN KEY(kullanici_id) REFERENCES app_user (id) ON DELETE CASCADE,
    FOREIGN KEY(mesaj_id) REFERENCES asistan_mesaj (id) ON DELETE SET NULL
)
""",
    "CREATE INDEX asistan_guvenlik_olay_kullanici_ix "
    "ON asistan_guvenlik_olay (kullanici_id, zaman DESC)",
    "CREATE INDEX asistan_guvenlik_olay_mesaj_ix "
    "ON asistan_guvenlik_olay (mesaj_id) WHERE mesaj_id IS NOT NULL",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {TABLO} TO tp_app")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLO}")

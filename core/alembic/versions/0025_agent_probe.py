"""Agent Probe bütünleşmesi (specs/011 §4.3, 0025; A şeridi): ajan ürünleri, asistan denetimi.

- `ajan_urunu_baglantisi` (gereksinim başına tek ürün; ayrı tablo: bağlantı içerik değildir, PO
  onayının hash'ine girmez, kaldırılabilir ve `requirement` tablosuna kolon eklenmez).
- `ajan_testi_talebi` (talep no tekil; durum queued|running|passed|failed|error; sonuç JSONB;
  Testing Probe'un sonucu işlemesi `islenme`/`surec`).
- `asistan_denetim` (asistan mesajı başına soru/cevap puanı, kategoriler, kodun kararı).
- `asistan_mesaj_kaynak_ck` += `denetim` (engellenen soru/cevap, denetim çalışmıyor).

Yalnız ekleme yapar. Downgrade, `kaynak='denetim'` mesajı varken kısıt geri daraltılamayacağı için
bu mesajları siler değil, `kapali` yapar (cevap metni zaten açıklamadır).

Birleştirmede zincir 0021→0022→0023→0024→0025 olarak doğrusallaştırılır (§4.3); bu dalda
`down_revision = "0021"`.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def _zaman(ad: str) -> sa.Column:
    return sa.Column(
        ad, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _id() -> sa.Column:
    return sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.create_table(
        "ajan_urunu_baglantisi",
        sa.Column(
            "requirement_id",
            _UUID,
            sa.ForeignKey("requirement.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("urun_kodu", sa.Text(), nullable=False),
        sa.Column("baglayan", sa.Text(), nullable=False),
        _zaman("olusturma"),
        _zaman("guncelleme"),
    )
    op.create_table(
        "ajan_testi_talebi",
        _id(),
        sa.Column(
            "requirement_id",
            _UUID,
            sa.ForeignKey("requirement.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("urun_kodu", sa.Text(), nullable=False),
        sa.Column("talep_no", sa.Text(), nullable=False, unique=True),
        sa.Column("durum", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("ozet", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "sonuc", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("simulasyon", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("baslatan", sa.Text(), nullable=True),
        sa.Column("gereksinim_hash", sa.Text(), nullable=True),
        sa.Column("islenme", sa.DateTime(timezone=True), nullable=True),
        sa.Column("surec", sa.Text(), nullable=True),
        sa.Column("surec_notu", sa.Text(), nullable=True),
        _zaman("olusturma"),
        _zaman("guncelleme"),
        sa.CheckConstraint(
            "durum IN ('error', 'failed', 'passed', 'queued', 'running')",
            name="ajan_testi_talebi_durum_ck",
        ),
        sa.CheckConstraint(
            "surec IS NULL OR surec IN ('bulgu', 'hata', 'onay_gecersiz', 'tamamlandi')",
            name="ajan_testi_talebi_surec_ck",
        ),
    )
    op.create_index(
        "ajan_testi_talebi_req_ix", "ajan_testi_talebi", ["requirement_id", "olusturma"]
    )
    op.create_table(
        "asistan_denetim",
        _id(),
        sa.Column(
            "mesaj_id",
            _UUID,
            sa.ForeignKey("asistan_mesaj.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("yon", sa.Text(), nullable=False),
        sa.Column("puan", sa.Integer(), nullable=False),
        sa.Column(
            "kategoriler", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("karar", sa.Text(), nullable=False),
        sa.Column("gerekce", sa.Text(), nullable=False, server_default=""),
        sa.Column("kaynak", sa.Text(), nullable=False),
        sa.Column("talep_no", sa.Text(), nullable=True),
        sa.Column("ai_call_id", _UUID, nullable=True),
        sa.Column("sure_ms", sa.Integer(), nullable=True),
        _zaman("olusturma"),
        sa.CheckConstraint("yon IN ('cevap', 'soru')", name="asistan_denetim_yon_ck"),
        sa.CheckConstraint("karar IN ('engelle', 'gec', 'uyar')", name="asistan_denetim_karar_ck"),
        sa.CheckConstraint(
            "kaynak IN ('agent-probe', 'sim', 'tp-gecit')", name="asistan_denetim_kaynak_ck"
        ),
        sa.CheckConstraint("puan BETWEEN 0 AND 100", name="asistan_denetim_puan_ck"),
    )
    op.create_index("asistan_denetim_mesaj_ix", "asistan_denetim", ["mesaj_id"])
    op.create_index("asistan_denetim_olusturma_ix", "asistan_denetim", ["olusturma"])
    op.drop_constraint("asistan_mesaj_kaynak_ck", "asistan_mesaj", type_="check")
    op.create_check_constraint(
        "asistan_mesaj_kaynak_ck",
        "asistan_mesaj",
        "kaynak IS NULL OR kaynak IN ('denetim', 'kapali', 'model', 'sablon', 'sozluk')",
    )
    for tablo in ("ajan_urunu_baglantisi", "ajan_testi_talebi", "asistan_denetim"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tablo} TO tp_app")


def downgrade() -> None:
    # Bilinçli veri dönüşümü (0027 notu): engel / "kontrol çalışmıyor" mesajları silinmez, kısıt
    # daraltılabilsin diye `kapali` olarak yeniden yazılır; kayıt denetim zincirinde kalır.
    op.execute("UPDATE asistan_mesaj SET kaynak = 'kapali' WHERE kaynak = 'denetim'")
    op.drop_constraint("asistan_mesaj_kaynak_ck", "asistan_mesaj", type_="check")
    op.create_check_constraint(
        "asistan_mesaj_kaynak_ck",
        "asistan_mesaj",
        "kaynak IS NULL OR kaynak IN ('kapali', 'model', 'sablon', 'sozluk')",
    )
    op.drop_table("asistan_denetim")
    op.drop_table("ajan_testi_talebi")
    op.drop_table("ajan_urunu_baglantisi")

"""Üretim dili boyutu (specs/011-uretim-dili §2.2).

- `script.dil`: üretilen testin dili — `ts` | `java` | `csharp` | `python`. Dil platformdan
  türetilmez (web her dille, uygulama platformları yalnız Java ile üretilir); mevcut satırlar
  bugünkü davranışla doldurulur: `web → ts`, diğerleri → `java`.
- `script.dil_kaynagi`: dil nereden geldi — `algilandi` (hedef repodaki testlerden), `secildi`
  (kullanıcı Kod üretimi ekranında seçti), `varsayilan` (algılama sonuçsuz / eski kayıt).
- `script_codegen.kaynak_kod`: yalnız doğrulanmamış dillerde (`csharp` | `python`) render edilen
  kaynak; forge'a commit edilmez.
- `script.durum` kümesine `unverified` eklenir (SCRIPT makinesi: `verifying → unverified`,
  `unverified → pending | closed`): doğrulanmamış dilde üretim bitti, kod derlenmedi/koşulmadı.

Etkin script anahtarı (case, platform) olarak kalır; dil değiştirmek yeniden üretmektir.

Model ↔ şema eşitliği tests/unit/features/codegen/test_dil.py'de doğrulanır.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DILLER = ("csharp", "java", "python", "ts")
DIL_KAYNAKLARI = ("algilandi", "secildi", "varsayilan")
ESKI_DURUMLAR = (
    "blocked", "checking", "closed", "failed", "merged", "pending", "pr_open", "verifying",
)  # fmt: skip
YENI_DURUMLAR = tuple(sorted((*ESKI_DURUMLAR, "unverified")))


def _in(kolon: str, degerler: Sequence[str]) -> str:
    return f"{kolon} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def upgrade() -> None:
    op.execute("ALTER TABLE script ADD COLUMN dil TEXT DEFAULT 'ts' NOT NULL")
    op.execute("UPDATE script SET dil = CASE WHEN platform = 'web' THEN 'ts' ELSE 'java' END")
    op.create_check_constraint("script_dil_ck", "script", _in("dil", DILLER))
    op.execute("ALTER TABLE script ADD COLUMN dil_kaynagi TEXT DEFAULT 'varsayilan' NOT NULL")
    op.create_check_constraint(
        "script_dil_kaynagi_ck", "script", _in("dil_kaynagi", DIL_KAYNAKLARI)
    )
    op.execute("ALTER TABLE script_codegen ADD COLUMN kaynak_kod TEXT")
    op.drop_constraint("script_durum_ck", "script", type_="check")
    op.create_check_constraint("script_durum_ck", "script", _in("durum", YENI_DURUMLAR))


def downgrade() -> None:
    # `unverified` script'lerin forge'da dalı/PR'ı yoktur; eski şemada karşılığı `closed`'dır.
    op.execute("UPDATE script SET durum = 'closed' WHERE durum = 'unverified'")
    op.drop_constraint("script_durum_ck", "script", type_="check")
    op.create_check_constraint("script_durum_ck", "script", _in("durum", ESKI_DURUMLAR))
    op.execute("ALTER TABLE script_codegen DROP COLUMN kaynak_kod")
    op.drop_constraint("script_dil_kaynagi_ck", "script", type_="check")
    op.execute("ALTER TABLE script DROP COLUMN dil_kaynagi")
    op.drop_constraint("script_dil_ck", "script", type_="check")
    op.execute("ALTER TABLE script DROP COLUMN dil")
